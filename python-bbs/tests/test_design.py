import html
import re
import zoneinfo

import pytest

import main
from formatting import make_display_dt
from models import BbsThread, Post


def make_thread(title="デザイン確認", posts=0) -> int:
    thread_id = BbsThread.create(title)
    for i in range(posts):
        Post.create(thread_id, f"名無しさん{i}", f"本文{i}")
    return thread_id


def test_stylesheet_is_served_and_linked(client):
    css = client.get("/static/style.css")
    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert ".post-head" in css.text

    thread_id = make_thread()
    for url in ("/", f"/thread/{thread_id}"):
        page = client.get(url).text
        assert 'href="/static/style.css"' in page
        assert "tailwindcss" not in page


def test_tailwind_theme_switch(client, monkeypatch):
    monkeypatch.setitem(main.templates.env.globals, "theme", "tailwind")
    page = client.get("/").text
    assert "@tailwindcss/browser@4.1.11" in page
    assert 'type="text/tailwindcss"' in page
    assert "/static/style.css" not in page


def test_unknown_theme_value_falls_back_to_classic():
    assert main.THEME in ("classic", "tailwind")


def test_templates_use_the_shared_class_names(client):
    thread_id = make_thread(posts=2)
    page = client.get(f"/thread/{thread_id}").text
    for cls in ("site-header", "panel", "thread-title", "post-head", "post-no", "post-name", "post-body", "form"):
        assert f'class="{cls}' in page or f'"{cls} ' in page or f' {cls}"' in page, cls


def test_display_dt_converts_utc_to_jst():
    try:
        tz = zoneinfo.ZoneInfo("Asia/Tokyo")
    except zoneinfo.ZoneInfoNotFoundError:
        pytest.skip("tzdata が無い環境")
    display = make_display_dt(tz)
    assert display("2026-10-09 12:34:56.789") == "2026/10/09(金) 21:34:56"
    assert display("2026-12-31 15:00:00.000") == "2027/01/01(金) 00:00:00"
    assert display("not a date") == "not a date"


def test_post_numbers_are_continuous_across_pages(client):
    thread_id = make_thread(posts=65)
    numbers, url = [], f"/thread/{thread_id}"
    while True:
        page = client.get(url).text
        numbers += [int(n) for n in re.findall(r'id="res(\d+)"', page)]
        m = re.search(r'href="(/thread/\d+\?cursor_time=[^"]+)"', page)
        if not m:
            break
        url = html.unescape(m.group(1))
    assert numbers == list(range(1, 66))


def test_tampered_start_does_not_break_the_page(client):
    thread_id = make_thread(posts=3)
    time = "2026-01-01%2000:00:00.000"
    for start in ("abc", "-5", "0", "99999999999999999999"):
        r = client.get(f"/thread/{thread_id}?cursor_time={time}&cursor_id=1&start={start}")
        assert r.status_code == 200, start
        assert 'id="res1"' in r.text, start
    # カーソルが無効なら start が付いていても 1 から数える
    r = client.get(f"/thread/{thread_id}?cursor_time=zzz&cursor_id=1&start=50")
    assert 'id="res1"' in r.text


def test_thread_list_is_numbered_from_page_offset(client):
    for i in range(25):
        make_thread(f"番号テスト{i}")
    page2 = client.get("/?page=2").text
    first_no = int(re.search(r'class="thread-no">(\d+):', page2).group(1))
    assert first_no == 21
