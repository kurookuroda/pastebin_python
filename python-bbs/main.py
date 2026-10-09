"""FastAPI掲示板のエントリポイント: uvicorn main:app --reload"""
import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from database import Database
from formatting import load_timezone, make_display_dt
from models import BbsThread, Post
from ratelimit import FixedWindowLimiter, get_client_ip

BASE_DIR = Path(__file__).resolve().parent  # どのディレクトリから起動しても動くように絶対パスにする

THREADS_PER_PAGE = 20
POSTS_PER_PAGE = 30
MAX_PAGE = 999_999
MAX_POST_NO = 10_000_000
SQLITE_MAX_INT = 2**63 - 1  # SQLite INTEGER は64bit符号付き

# デザインテーマ: classic（素のCSS・既定）/ tailwind（Tailwind CDN）
THEME = os.environ.get("BBS_THEME", "classic").strip().lower()
if THEME not in ("classic", "tailwind"):
    THEME = "classic"

# アプリ側のレートリミット（Cloudflareのエッジ制限が主防御、これは二段目の保険）。
# IPあたり、スレッド作成は60秒に3回まで、レス投稿は60秒に10回まで。
THREAD_LIMITER = FixedWindowLimiter(limit=3, window_seconds=60)
POST_LIMITER = FixedWindowLimiter(limit=10, window_seconds=60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async def purge_loop():
        while True:
            await asyncio.sleep(120)
            THREAD_LIMITER.purge_expired()
            POST_LIMITER.purge_expired()

    task = asyncio.create_task(purge_loop())
    try:
        yield
    finally:
        task.cancel()


DISABLE_DOCS = os.environ.get("BBS_DISABLE_DOCS", "true").strip().lower() not in ("0", "false", "no")

app = FastAPI(
    title="Simple BBS",
    lifespan=lifespan,
    docs_url=None if DISABLE_DOCS else "/docs",
    redoc_url=None if DISABLE_DOCS else "/redoc",
    openapi_url=None if DISABLE_DOCS else "/openapi.json",
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
_tz, _tz_label = load_timezone(os.environ.get("BBS_TZ", "Asia/Tokyo"))
templates.env.filters["display_dt"] = make_display_dt(_tz)
templates.env.globals["theme"] = THEME
templates.env.globals["tz_label"] = _tz_label

# アプリ起動時にDBを初期化
Database.get_instance()


def parse_cursor(
    cursor_time: Optional[str], cursor_id: Optional[str]
) -> Optional[Tuple[str, int]]:
    """URLのカーソルを検証する。不正なら None（= 先頭ページにフォールバック）。

    cursor_id を int で受けると FastAPI が 422 を返してしまうため、str で受けて自前で検証する。
    """
    if not cursor_time or not cursor_id:
        return None
    try:
        parsed_id = int(cursor_id)
        datetime.strptime(cursor_time, "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        return None
    # 範囲外の値をSQLiteに渡すと OverflowError（500）になる
    if not 0 < parsed_id <= SQLITE_MAX_INT:
        return None
    return cursor_time, parsed_id


def parse_start(start: Optional[str]) -> int:
    """ページ先頭のレス番号（表示専用）。不正なら 1。

    キーセット方式では「何件目か」をDBから出せないので、URLで持ち回る。
    表示にしか使わないため、改ざんされても検索結果には影響しない。
    """
    try:
        number = int(start) if start else 1
    except ValueError:
        return 1
    return number if 1 <= number <= MAX_POST_NO else 1


@app.get("/")
def index(request: Request, page: int = 1):
    total = BbsThread.count()
    total_pages = max(1, (total + THREADS_PER_PAGE - 1) // THREADS_PER_PAGE)
    page = min(max(1, page), MAX_PAGE, total_pages)

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "threads": BbsThread.paginate(page, THREADS_PER_PAGE),
            "page": page,
            "total_pages": total_pages,
            "first_no": (page - 1) * THREADS_PER_PAGE + 1,
        },
    )


@app.post("/thread")
def create_thread(request: Request, title: str = Form(..., max_length=200)):
    THREAD_LIMITER.hit(get_client_ip(request))
    title = title.strip()
    if title:
        BbsThread.create(title)
    return RedirectResponse(url="/", status_code=303)


# {thread_id:int} により、数字以外のパスは自動で404になる
@app.get("/thread/{thread_id:int}")
def show_thread(
    request: Request,
    thread_id: int,
    cursor_time: Optional[str] = None,
    cursor_id: Optional[str] = None,
    start: Optional[str] = None,
):
    thread = BbsThread.find(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="スレッドが見つかりません")

    cursor = parse_cursor(cursor_time, cursor_id)
    posts = Post.after(
        thread_id,
        cursor[0] if cursor else None,
        cursor[1] if cursor else None,
        POSTS_PER_PAGE,
    )
    # カーソルが無効（= 先頭ページ）のときは、start が付いていても 1 から数える
    first_post_no = parse_start(start) if cursor else 1

    last_post = posts[-1] if posts else None
    has_next = last_post is not None and Post.has_more(
        thread_id, last_post.created_at, last_post.id
    )

    return templates.TemplateResponse(
        request,
        "thread.html",
        {
            "thread": thread,
            "posts": posts,
            "has_next": has_next,
            "last_post": last_post,
            "first_post_no": first_post_no,
            "next_post_no": first_post_no + len(posts),
            "per_page": POSTS_PER_PAGE,
        },
    )


@app.post("/thread/{thread_id:int}/post")
def create_post(
    request: Request,
    thread_id: int,
    name: Optional[str] = Form(default="", max_length=100),
    body: str = Form(..., max_length=10_000),
):
    POST_LIMITER.hit(get_client_ip(request))
    if BbsThread.find(thread_id) is None:
        raise HTTPException(status_code=404, detail="スレッドが見つかりません")

    name = (name or "").strip() or "名無しさん"
    body = body.strip()
    if body:
        Post.create(thread_id, name, body)

    # PRGパターン: リロードによる二重投稿を防ぐ
    return RedirectResponse(url=f"/thread/{thread_id}", status_code=303)
