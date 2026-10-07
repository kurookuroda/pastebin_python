# Python + Flaskで作るWebhook対応Pastebin（完全版）

このチュートリアルでは、ブラウザからの手動投稿に加え、**JSON API (Webhook) 経由での自動投稿**を受け付けるPastebinを構築します。

データベースは使わず、ファイルシステムのみで動作します。API通信には**APIキー認証**と**Webhook署名検証**を導入し、用途に応じた権限管理を実現します。

---

## 1. 追加・拡張される機能

前回から以下の機能が追加・拡張されます。

### 新規・強化されたAPI機能

- **認証方式の分離** — 汎用APIキー (`X-API-Key`) と GitHub Webhook署名検証 (`X-Hub-Signature-256`) を独立した環境変数で管理
- **マルチパターン認証** — 1つのエンドポイントで「内部スクリプトからのAPI利用」と「外部サービスからのWebhook受信」の両方を安全に処理
- **GitHub Webhook対応** — ペイロードの署名検証に対応し、送信元の真正性を担保。Webhook 作成時に送られる `ping` イベントにも正しく応答します

### アーキテクチャの改善

- **セキュアバイデフォルト** — API用環境変数が未設定の場合、APIエンドポイントは自動的に `403 Forbidden` で無効化
- **レート制限の統合** — `Flask-Limiter` を組み込み、APIの過剰利用を防止（本番ではRedisストレージを推奨）
- **リバースプロキシ対応** — Nginx等の背後でも、利用者ごとにレート制限を掛けられる（環境変数 `TRUSTED_PROXY_COUNT`）

---

## 2. ディレクトリ構成

```text
pastebin/
├── app.py              <- Webhook対応版のFlaskアプリケーション
├── requirements.txt    <- 必要なパッケージ一覧
├── pastes/             <- 投稿されたテキストの保存先 (自動作成)
├── templates/
│   ├── index.html      <- 投稿フォームと表示画面
│   ├── 404.html        <- エラーページ
│   └── 413.html        <- サイズ超過エラーページ
└── static/
    └── style.css       <- 画面のデザイン
```

`templates/` と `static/` 内のファイルは前回と同じものをそのまま使えます。

---

## 3. 必要なパッケージ

`requirements.txt` に、レート制限用の `Flask-Limiter` を追加します。

```text
Flask
Pygments
shortuuid
Flask-Limiter
redis
```

インストール:

```bash
python -m pip install -r requirements.txt
```

> `redis` は本番環境で `Flask-Limiter` のストレージとして使うために含めていますが、開発環境だけであればなくても動作します。

---

## 4. Flaskアプリケーション (app.py)

以下が、今回の修正案をすべて反映した完全版の `app.py` です。

```python
#!/usr/bin/env python3

import hashlib
import hmac
import logging
import os
import re
import secrets

import shortuuid
from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import ClassNotFound, get_all_lexers, get_lexer_by_name
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)

# ============================================================
# Configuration
# ============================================================

SECRET_KEY = os.environ.get("FLASK_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("FLASK_SECRET_KEY environment variable is required.")
app.secret_key = SECRET_KEY

# 汎用APIアクセス用のキー (スクリプトやCI/CDから利用)
PASTEBIN_API_KEY = os.environ.get("PASTEBIN_API_KEY")

# GitHub/GitLab等のWebhook署名検証用シークレット
GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET")

# どちらかが設定されていればAPIエンドポイントを有効化
API_ENABLED = bool(PASTEBIN_API_KEY or GITHUB_WEBHOOK_SECRET)

# リバースプロキシ (Nginx等) の背後で動かす場合に、プロキシの段数を指定する。
# 0 (既定) の場合は X-Forwarded-* ヘッダーを信用しない。
# プロキシがないのに 1 以上にすると、クライアントがヘッダーを偽装して
# レート制限を回避できてしまうので注意。
try:
    TRUSTED_PROXY_COUNT = int(os.environ.get("TRUSTED_PROXY_COUNT", "0"))
except ValueError:
    raise RuntimeError("TRUSTED_PROXY_COUNT must be an integer.")
if TRUSTED_PROXY_COUNT < 0:
    raise RuntimeError("TRUSTED_PROXY_COUNT must not be negative.")

if TRUSTED_PROXY_COUNT > 0:
    # import 時に適用する (gunicorn では `if __name__ == "__main__"` は実行されない)
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=TRUSTED_PROXY_COUNT,
        x_proto=TRUSTED_PROXY_COUNT,
        x_host=TRUSTED_PROXY_COUNT,
    )

MAX_PASTE_BYTES = 512 * 1024
app.config["MAX_CONTENT_LENGTH"] = MAX_PASTE_BYTES * 3 + 16 * 1024

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FLASK_HTTPS", "").lower() == "true"

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
PASTE_DIR = os.path.join(BASE_DIR, "pastes")
os.makedirs(PASTE_DIR, exist_ok=True)

# ============================================================
# Logging
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

# ============================================================
# Rate Limiting
# ============================================================
# 開発環境では memory:// で十分ですが、本番では redis:// を使ってください。
#
# default_limits: 制限を指定していないルート (閲覧など) すべてに適用される。
#   ブラウザでの通常の利用を妨げない、ゆるめの値にしておく。
# @limiter.limit(...): 書き込みのルートに、より厳しい制限を追加する。
#   override_defaults=False を付けない場合、そのルートでは default_limits が
#   置き換えられて適用されなくなるため、ここでは False を指定する。
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["1000 per day", "200 per hour"],
    storage_uri=os.environ.get("LIMITER_STORAGE", "memory://"),
)

API_RATE_LIMIT = "10 per minute;50 per hour"
FORM_RATE_LIMIT = "10 per minute;30 per hour"

# ============================================================
# Validation & Helpers
# ============================================================

VALID_PASTE_ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def is_valid_paste_id(paste_id):
    return bool(isinstance(paste_id, str) and VALID_PASTE_ID.fullmatch(paste_id))


def get_language_options():
    languages = set()
    for _, aliases, _, _ in get_all_lexers():
        for alias in aliases:
            languages.add(alias)
    return sorted(languages)


LANGUAGE_OPTIONS = get_language_options()
ALLOWED_LANGUAGES = set(LANGUAGE_OPTIONS)


def sanitize_language(language):
    if not isinstance(language, str):
        return "text"
    language = language.strip().lower()
    return language if language in ALLOWED_LANGUAGES else "text"


def validate_content_size(content):
    """UTF-8 にエンコードできること、サイズ上限以内であることを確認する。"""
    try:
        content_bytes = content.encode("utf-8")
    except UnicodeEncodeError:
        # JSON の "\ud800" のような孤立サロゲートは UTF-8 にできない
        abort(400, description="Content contains invalid Unicode characters.")

    if len(content_bytes) > MAX_PASTE_BYTES:
        abort(413, description="Payload too large.")


def format_push_commits(commits):
    """GitHub の push イベントの commits を、貼り付け用のテキストにする。"""
    if not isinstance(commits, list):
        return ""

    entries = []
    for commit in commits:
        if not isinstance(commit, dict):
            continue
        author = commit.get("author")
        name = author.get("name") if isinstance(author, dict) else None
        entries.append(
            f"Commit by {name or 'Unknown'}:\n"
            f"Message: {commit.get('message', '')}\n"
            f"URL: {commit.get('url', '')}"
        )
    return "\n\n".join(entries)


# ============================================================
# Constant-time comparison
# ============================================================


def constant_time_equals(a, b):
    """2つの文字列を一定時間で比較する。非ASCII文字が入っていても TypeError にならない。"""
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


# ============================================================
# CSRF (Browser Form Only)
# ============================================================


def get_csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def verify_csrf_token(token):
    expected = session.get("csrf_token")
    if not token or not expected:
        return False
    return constant_time_equals(token, expected)


# ============================================================
# Paste Creation (Shared Logic)
# ============================================================


def create_paste_file():
    for _ in range(20):
        paste_id = shortuuid.random(length=10)
        if not is_valid_paste_id(paste_id):
            continue

        file_path = os.path.join(PASTE_DIR, paste_id)
        try:
            # "x" mode: 排他作成 (既存ファイルがあればFileExistsError)
            file_object = open(file_path, "x", encoding="utf-8", newline="\n")
            return paste_id, file_path, file_object
        except FileExistsError:
            continue
    raise RuntimeError("Unable to generate a unique paste ID.")


def save_paste_content(content: str, language: str) -> str:
    """
    テキストと言語を受け取り、バリデーションとファイル保存を行う共通関数。
    成功すれば paste_id を返し、失敗すれば abort() を発生させる。
    """
    language = sanitize_language(language)
    content = content.replace("\r\n", "\n").replace("\r", "\n")

    if not content:
        abort(400, description="Content is required.")

    validate_content_size(content)

    try:
        paste_id, file_path, file_object = create_paste_file()
        try:
            file_object.write(language + "\n")
            file_object.write(content)
            file_object.flush()
            os.fsync(file_object.fileno())
        except Exception:
            file_object.close()
            try:
                os.remove(file_path)
            except OSError:
                pass
            raise
        finally:
            file_object.close()

        logging.info("Created paste: %s", paste_id)
        return paste_id

    except RuntimeError:
        logging.exception("Failed to create paste.")
        abort(500, description="Unable to create paste.")
    except OSError:
        logging.exception("Failed to write paste.")
        abort(500, description="Unable to save paste.")


# ============================================================
# Routes
# ============================================================

@app.route("/", methods=["GET", "POST"])
@limiter.limit(FORM_RATE_LIMIT, methods=["POST"], override_defaults=False)
def index():
    if request.method == "POST":
        csrf_token = request.form.get("csrf_token", "")
        if not verify_csrf_token(csrf_token):
            abort(400)

        content = request.form.get("content", "")
        language = request.form.get("language", "text")

        try:
            paste_id = save_paste_content(content, language)
            return redirect(url_for("view_paste", paste_id=paste_id))
        except HTTPException:
            # abort() (400/413/500 など) はそのままエラーハンドラへ委譲
            raise
        except Exception:
            logging.exception("Failed to create paste via form.")
            flash("Error creating paste.", "error")
            return render_template(
                "index.html",
                csrf_token=get_csrf_token(),
                language_options=LANGUAGE_OPTIONS,
            ), 400

    return render_template(
        "index.html",
        csrf_token=get_csrf_token(),
        language_options=LANGUAGE_OPTIONS,
    )


@app.route("/api/v1/paste", methods=["POST"])
@limiter.limit(API_RATE_LIMIT, override_defaults=False)  # APIはより厳しく制限
def api_create_paste():
    # 1. APIが環境変数で有効化されているか確認
    if not API_ENABLED:
        # 403 = サーバ側の設定による無効化 (クライアントの責ではない)
        abort(403, description="API is disabled by server configuration.")

    # 2. 認証 (GitHub の ping も含め、すべてのリクエストで最初に行う)
    is_authorized = False

    # パターンA: 汎用APIキーによる認証
    api_key = request.headers.get("X-API-Key")
    if PASTEBIN_API_KEY and api_key:
        if constant_time_equals(api_key, PASTEBIN_API_KEY):
            is_authorized = True
            logging.debug("Authorized via API Key.")

    # パターンB: GitHub Webhookの署名検証による認証
    if not is_authorized and GITHUB_WEBHOOK_SECRET:
        signature = request.headers.get("X-Hub-Signature-256")
        if signature and signature.startswith("sha256="):
            expected_sig = "sha256=" + hmac.new(
                GITHUB_WEBHOOK_SECRET.encode("utf-8"),
                request.data,
                hashlib.sha256
            ).hexdigest()

            if constant_time_equals(signature, expected_sig):
                is_authorized = True
                logging.debug("Authorized via GitHub Webhook signature.")

    if not is_authorized:
        # 401 = クライアントの認証情報が無効
        abort(401, description="Invalid credentials or signature.")

    github_event = request.headers.get("X-GitHub-Event")

    # GitHub の Webhook 作成時に送られる疎通確認 (ping) には、認証のあとで即応答する。
    # ここで 400 を返すと GitHub 側で配信失敗と表示されてしまう。
    if github_event == "ping":
        return jsonify({"status": "pong"}), 200

    # 3. JSONリクエストの検証
    if not request.is_json:
        abort(400, description="Content-Type must be application/json.")

    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        abort(400, description="Invalid JSON payload.")

    content = data.get("content")
    language = data.get("language", "text")

    # GitHub Webhookの場合、ペイロードからcontentを抽出する例
    # 通常のAPI利用時は上記でcontentが取得できる
    if not content and github_event:
        if github_event != "push":
            # push 以外のイベントは対象外。200 を返して、GitHub 側では配信成功にする。
            return jsonify({"status": "ignored", "reason": "Unsupported event."}), 200

        content = format_push_commits(data.get("commits"))
        if not content:
            return jsonify({"status": "ignored", "reason": "No commits in payload."}), 200
        language = "text"

    if not isinstance(content, str):
        abort(400, description="'content' must be a string.")

    # 4. 保存処理 (共通関数を使用)
    paste_id = save_paste_content(content, language)

    # 5. 成功レスポンス
    return jsonify({
        "status": "success",
        "paste_id": paste_id,
        "url": url_for("view_paste", paste_id=paste_id, _external=True),
        "raw_url": url_for("raw_paste", paste_id=paste_id, _external=True)
    }), 201


@app.route("/paste/<paste_id>")
def view_paste(paste_id):
    if not is_valid_paste_id(paste_id):
        abort(404)

    file_path = os.path.join(PASTE_DIR, paste_id)
    if not os.path.isfile(file_path):
        abort(404)

    try:
        with open(file_path, "r", encoding="utf-8", newline="\n") as f:
            language = f.readline().rstrip("\n")
            content = f.read()
    except (OSError, UnicodeError):
        abort(404)

    language = sanitize_language(language)
    try:
        lexer = get_lexer_by_name(language)
    except ClassNotFound:
        lexer = get_lexer_by_name("text")
    formatter = HtmlFormatter(linenos=True, cssclass="highlight")
    highlighted = highlight(content, lexer, formatter)
    highlight_css = formatter.get_style_defs(".highlight")

    return render_template(
        "index.html",
        paste_id=paste_id,
        paste_language=language,
        paste_content=highlighted,
        highlight_css=highlight_css,
        csrf_token=get_csrf_token(),
        language_options=LANGUAGE_OPTIONS,
    )


@app.route("/raw/<paste_id>")
def raw_paste(paste_id):
    if not is_valid_paste_id(paste_id):
        abort(404)

    file_path = os.path.join(PASTE_DIR, paste_id)
    if not os.path.isfile(file_path):
        abort(404)

    try:
        with open(file_path, "r", encoding="utf-8", newline="\n") as f:
            f.readline()  # 言語名の行をスキップ
            content = f.read()
    except (OSError, UnicodeError):
        abort(404)

    response = app.response_class(content, status=200, mimetype="text/plain")
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


# ============================================================
# Error Handlers
# ============================================================


def is_api_request():
    """API のルートか判定する。

    Accept ヘッダーで判定してはいけない。ブラウザの Accept には `*/*` が含まれ、
    これが application/json にも一致するため、画面のエラーまで JSON になってしまう。
    """
    return request.path.startswith("/api/")


@app.errorhandler(400)
def bad_request(error):
    if is_api_request():
        return jsonify({"error": error.description or "Bad Request"}), 400
    return render_template("404.html", message="Bad request."), 400


@app.errorhandler(401)
def unauthorized(error):
    if is_api_request():
        return jsonify({"error": error.description or "Unauthorized"}), 401
    return render_template("404.html", message="Unauthorized."), 401


@app.errorhandler(403)
def forbidden(error):
    if is_api_request():
        return jsonify({"error": error.description or "Forbidden"}), 403
    return render_template("404.html", message="Forbidden."), 403


@app.errorhandler(404)
def not_found(error):
    if is_api_request():
        return jsonify({"error": "Paste not found."}), 404
    return render_template("404.html", message="Paste not found."), 404


@app.errorhandler(413)
def request_too_large(error):
    if is_api_request():
        return jsonify({"error": "Payload Too Large", "max_bytes": MAX_PASTE_BYTES}), 413
    return render_template("413.html", max_bytes=MAX_PASTE_BYTES), 413


@app.errorhandler(405)
def method_not_allowed(error):
    if is_api_request():
        response = jsonify({"error": "Method not allowed."})
    else:
        response = app.make_response(
            render_template("404.html", message="Method not allowed.")
        )
    response.status_code = 405
    # 405 の応答には、許可されているメソッドを Allow ヘッダーで伝える必要がある
    if error.valid_methods:
        response.headers["Allow"] = ", ".join(error.valid_methods)
    return response


@app.errorhandler(429)
def too_many_requests(error):
    if is_api_request():
        return jsonify({"error": "Too many requests."}), 429
    return render_template("404.html", message="Too many requests."), 429


@app.errorhandler(500)
def internal_error(error):
    if is_api_request():
        return jsonify({"error": "Internal Server Error"}), 500
    return render_template("404.html", message="Internal Server Error."), 500


# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    # 本番では gunicorn 等のWSGIサーバを使います。
    # リバースプロキシ (Nginx等) の背後では、環境変数 TRUSTED_PROXY_COUNT を設定してください (8.3 参照)。
    app.run(debug=False, host="127.0.0.1", port=5000)
```

### 4.1 設計上のポイント

#### エラー応答の形式

`/api/` で始まるパスは、**常にJSON**を返します。それ以外のパスは、HTMLを返します。

`Accept` ヘッダーで判定すると、ブラウザの画面でもエラーがJSONになります。ブラウザの `Accept` ヘッダー（`text/html,...,*/*;q=0.8`）には `*/*` が含まれ、これが `application/json` にも一致してしまうためです。

405（許可されていないメソッド）と429（レート制限超過）にもハンドラを用意しています。ハンドラがないと、APIでもFlaskの標準のHTMLエラーページが返ります。

#### 認証は最初に行う

GitHub の `ping` も含め、すべてのリクエストで、最初に認証を行います。`ping` にも署名が付いているので、Secret の設定ミスは、`ping` が `401` になることで気づけます。

#### GitHub のイベントの扱い

`push` 以外のイベントや、コミットが空の `push`（ブランチ削除など）は、貼り付ける内容がありません。これらには `200` と `{"status": "ignored"}` を返します。`400` を返すと、GitHub 側で配信失敗と表示されるためです。

#### 文字列の比較

APIキー・署名・CSRFトークンの比較は、すべて `constant_time_equals()` を通します。`secrets.compare_digest()` に `str` を渡すと、ASCII文字だけでなければ `TypeError` になります。HTTPヘッダーは、利用者が自由に内容を決めて送れるので、非ASCII文字を送られると500エラーになります。UTF-8のバイト列にしてから比較すれば、これを避けられます。

#### レート制限の掛け方

`@limiter.limit(...)` でルートに制限を付けると、**そのルートでは `default_limits` が置き換えられます**。`override_defaults=False` を指定すると、`default_limits` に追加する形になります。このコードでは、すべて追加する形にしています。

---

## 5. 環境変数の設定と起動

今回は3つの環境変数を設定する必要があります。3つとも、推測されにくいランダムな値にしてください。

### Linux / macOS

```bash
export FLASK_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export PASTEBIN_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export GITHUB_WEBHOOK_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python app.py
```

### Windows (PowerShell)

```powershell
$env:FLASK_SECRET_KEY = python -c "import secrets; print(secrets.token_urlsafe(32))"
$env:PASTEBIN_API_KEY = python -c "import secrets; print(secrets.token_urlsafe(32))"
$env:GITHUB_WEBHOOK_SECRET = python -c "import secrets; print(secrets.token_urlsafe(32))"
python app.py
```

`GITHUB_WEBHOOK_SECRET` は、GitHub の Webhook 設定の **Secret** 欄にも、同じ値を入力します（`echo "$GITHUB_WEBHOOK_SECRET"` で表示できます）。

必要に応じて、次の環境変数も設定できます。

| 環境変数 | 内容 |
|----------|------|
| `LIMITER_STORAGE` | レート制限の保存先（既定は `memory://`。本番は `redis://...`。8.1 参照） |
| `TRUSTED_PROXY_COUNT` | リバースプロキシの段数（既定は `0`。8.3 参照） |
| `FLASK_HTTPS` | `true` で Cookie の `Secure` 属性を有効にする（8.2 参照） |

> **セキュアバイデフォルト**: `PASTEBIN_API_KEY` も `GITHUB_WEBHOOK_SECRET` も設定されていない場合、APIエンドポイントは `403 Forbidden` を返して完全に無効化されます。設定ミスによる事故防止になっています。

### レート制限の値

制限は、IPアドレスごとに数えられます。

| 対象 | 制限 |
|------|------|
| `POST /api/v1/paste` | 10件/分、50件/時間 |
| `POST /`（フォームの投稿） | 10件/分、30件/時間 |
| すべてのルート（閲覧など） | 200件/時間、1000件/日 |

すべてのルートに共通の制限（最後の行）は、書き込みのルートにも**追加で**適用されます。そのため、APIの実効的な上限は、`1時間あたり最大50件` です。

内部ツールの利用頻度に応じて、`default_limits`、`API_RATE_LIMIT`、`FORM_RATE_LIMIT` の値を調整してください。また、GitHub Webhook の連続イベント (push のバースト等) で 429 が返る可能性がある場合は、`API_RATE_LIMIT` を緩める調整が必要です。

---

## 6. 動作確認

### 6.1 汎用APIキーでの投稿（成功パターン）

```bash
curl -X POST http://127.0.0.1:5000/api/v1/paste \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $PASTEBIN_API_KEY" \
  -d '{"content": "print(\"Hello from API!\")", "language": "python"}'
```

**レスポンス:**

```json
{
  "paste_id": "aB3xK9Lm2Q",
  "raw_url": "http://127.0.0.1:5000/raw/aB3xK9Lm2Q",
  "status": "success",
  "url": "http://127.0.0.1:5000/paste/aB3xK9Lm2Q"
}
```

### 6.2 GitHub Webhook からの投稿

GitHub リポジトリの Settings → Webhooks で以下を設定します。

- **Payload URL**: `http://<あなたのサーバ>/api/v1/paste`
- **Content type**: `application/json`
- **Secret**: `GITHUB_WEBHOOK_SECRET` と同じ値

作成時に送られる `ping` イベントには `{"status": "pong"}` が返り、GitHub 側「緑のチェックマーク」がつきます。`ping` にも署名が付いているので、Secret が一致していない場合は `401` になり、GitHub 側で配信失敗と表示されます。

**Which events would you like to trigger this webhook?** では、**Just the push event** を選ぶのがおすすめです。

`push` 以外のイベントや、コミットが空の `push`（ブランチ削除など）が届いた場合は、`200` と `{"status": "ignored", ...}` を返して無視します。GitHub 側では、配信成功として扱われます。

### 6.3 エラーパターン

**APIキーが間違っている:**

```bash
curl -X POST ... -H "X-API-Key: wrong-key" ...
```

**レスポンス:** `401 Unauthorized` と `{"error": "Invalid credentials or signature."}`

> 401 (認証情報が無効) と 403 (サーバ側でAPIが無効化されている) は意味が異なります。トラブルシュート時の見分けに使ってください。

**サイズ超過:**

**レスポンス:** `413 Payload Too Large` と `{"error": "Payload Too Large", "max_bytes": 524288}`

**レート制限を超えた:**

**レスポンス:** `429 Too Many Requests` と `{"error": "Too many requests."}`

---

## 7. Pythonスクリプトからの利用例

CI/CDパイプラインや監視スクリプトから使う場合の例です。

```python
import os
import sys

import requests

WEBHOOK_URL = "http://127.0.0.1:5000/api/v1/paste"
API_KEY = os.environ["PASTEBIN_API_KEY"]  # コードに直接書かず、環境変数から読む


def post_paste(content: str, language: str = "text") -> str:
    """テキストをPastebinに投稿し、ブラウザで開けるURLを返す。"""
    response = requests.post(
        WEBHOOK_URL,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": API_KEY,
        },
        json={"content": content, "language": language},
        timeout=10,
    )
    response.raise_for_status()  # 401/413/429 等はここで例外化
    data = response.json()
    print(f"Paste created: {data['url']}")
    return data["url"]


if __name__ == "__main__":
    # 例: ログファイルやコマンド出力を丸ごと貼り付ける
    content = sys.stdin.read()
    if not content.strip():
        print("No input received.", file=sys.stderr)
        sys.exit(1)
    post_paste(content, language="text")
```

使い方:

```bash
# コマンド出力をパイプでそのまま投稿
$ some-command --verbose | python post_paste.py
Paste created: http://127.0.0.1:5000/paste/xY3zA9QbLm
```

---

## 8. 本番運用時の必須セキュリティ対策

### 8.1 レート制限のストレージ（Redis推奨）

開発環境では `memory://` で動作しますが、本番でGunicornなどで複数ワーカーを立ち上げた場合、プロセス間でカウンターが共有されず、レート制限が事実上無効化されてしまいます。

**対策:**

```bash
# Redisをインストール・起動した上で
python -m pip install redis
```

そして環境変数を設定:

```bash
export LIMITER_STORAGE="redis://localhost:6379/0"
```

これでどのワーカーがリクエストを処理しても、正確にリクエスト数がカウント・制限されるようになります。

### 8.2 HTTPS環境での設定

HTTPS で公開する場合は `FLASK_HTTPS=true` を設定して、Cookieの `Secure` 属性を有効にしてください。

```bash
export FLASK_HTTPS=true
```

HTTPからHTTPSへの転送（リダイレクト）や、`Strict-Transport-Security` ヘッダーは、このアプリではなく、リバースプロキシ（Nginx等）側で設定します。

### 8.3 リバースプロキシの背後で動かす場合

Nginx等の背後でGunicornを動かすと、Flaskから見たリクエスト元のIPアドレスは、常にプロキシ（`127.0.0.1`）になります。レート制限はIPアドレスごとに数えるため、**すべての利用者が1つの枠を共有**してしまいます。1人が制限を使い切ると、他の利用者やGitHubからのWebhookも、1時間止まります。

これを防ぐため、`TRUSTED_PROXY_COUNT` にプロキシの段数を設定します。

```bash
export TRUSTED_PROXY_COUNT=1   # Nginx が1段
```

Nginx側では、元のIPアドレスなどをヘッダーで渡します。

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
}
```

設定すると、次の2つが正しくなります。

* レート制限が、利用者ごとのIPアドレスで数えられる
* APIが返す `url` と `raw_url` が、`https://公開ホスト名/...` になる

#### 注意：プロキシがないときは 0 のままにする

プロキシがないのに `1` 以上にすると、クライアントが `X-Forwarded-For` ヘッダーを自由に偽装でき、リクエストごとに別のIPアドレスを名乗ってレート制限を回避できてしまいます。`TRUSTED_PROXY_COUNT` は、実際のプロキシの段数と、必ず一致させてください。

また、`ProxyFix` はモジュールの読み込み時に適用します。`if __name__ == "__main__":` の中に書くと、Gunicornで起動したときには実行されず、設定が反映されません。

---

## 9. まとめ

今回の修正案を反映した完全版により、Pastebinは以下の3つの顔を持つようになりました。

1. **人間向け**: ブラウザからCSRF対策フォームで安全にコードを共有
2. **機械向け（汎用API）**: APIキー認証でCI/CDや監視スクリプトから自動投稿
3. **外部サービス向け（Webhook）**: 署名検証でGitHub等からの自動連携を安全に受信

APIキーとWebhookシークレットを分離したことで、万が一どちらかが漏洩しても、もう一方の認証は守られる、 defense in depth（深層防御）の設計になっています。

---

## 10. 次のステップ: TTL（自動有効期限）機能の予告

さらに機能を拡張するなら、**自動有効期限（TTL）機能**が実用的です。

### なぜ `os.path.getmtime()` ではダメなのか

`mtime`（最終更新時刻）はファイルのコピー・移動・バックアップからの復元で値が変わってしまいます。期限切れのはずの paste が「まだ有効」に見えてしまう事故を防ぐため、期限切れ時刻は **ファイル内に明示的に保存** する方針が正解です。

### ファイルフォーマットの拡張

期限を保存するために、ファイルの形式を拡張します。ただし、すでに保存されているPasteは、**旧形式（1行目が言語、2行目以降が本文）**のままです。新旧の形式を、見分けられるようにする必要があります。

そこで、新形式では、1行目に**形式を示す印**（`%%pastebin-v2`）を置きます。

```text
%%pastebin-v2
python
1699300000
print("Hello, TTL!")
```

| 行 | 内容 |
|----|------|
| 1行目 | 形式を示す印（`%%pastebin-v2`） |
| 2行目 | 言語 |
| 3行目 | 期限切れ時刻（Unixtime）。期限なしの場合は `0` |
| 4行目以降 | 本文 |

#### なぜ印が必要なのか

印がなく、「2行目を期限として読む」とすると、旧形式のPasteで次の事故が起こります。旧形式の2行目は、本文の1行目だからです。

| 旧形式の本文の1行目 | 起きること |
|---------------------|------------|
| 普通の文章 | 数値に変換できず、読めなくなる（404） |
| `12345` | 過去の時刻とみなされ、**期限切れとしてファイルが削除される** |
| `0` | 期限なしとみなされ、その行が本文から消える |

旧形式の1行目は、必ず言語名（`python` など）なので、`%%pastebin-v2` と一致することはありません。印があれば、旧形式のPasteは、そのまま（期限なしで）読めます。移行のためにファイルを書き換える必要もありません。

### 実装スケッチ

```python
import time
from typing import Optional, Tuple

FORMAT_V2_MARKER = "%%pastebin-v2"
MAX_EXPIRES_IN = 10 * 365 * 24 * 60 * 60  # 最大10年 (秒)


def read_paste_with_ttl(paste_id: str) -> Tuple[str, str]:
    """
    ファイルを読み込み、(language, content) を返す。
    - 旧形式 (印なし) は、期限なしとして読む
    - 新形式 (印あり) は、期限をチェックする。期限切れなら 404 を送出する
    - 新形式のヘッダーが壊れていれば 404 にする
    """
    if not is_valid_paste_id(paste_id):
        abort(404)

    file_path = os.path.join(PASTE_DIR, paste_id)
    if not os.path.isfile(file_path):
        abort(404)

    try:
        with open(file_path, "r", encoding="utf-8", newline="\n") as f:
            first_line = f.readline().rstrip("\n")
            if first_line != FORMAT_V2_MARKER:
                # 旧形式: 1行目が言語、2行目以降が本文。期限なし。
                return sanitize_language(first_line), f.read()

            language = f.readline().rstrip("\n")
            expires_line = f.readline().rstrip("\n")
            content = f.read()
    except (OSError, UnicodeError):
        abort(404)

    try:
        expires_at = int(expires_line)
    except ValueError:
        abort(404)  # ヘッダーが壊れたファイルは存在しないものとして扱う

    if expires_at != 0 and time.time() > expires_at:
        # 期限切れ: ファイルを削除して 404 を返す（クリーンアップ）
        try:
            os.remove(file_path)
        except OSError:
            pass
        abort(404)

    return sanitize_language(language), content


def save_paste_with_ttl(
    content: str, language: str, expires_in: Optional[int] = None
) -> str:
    """
    TTL 対応版の保存関数。
    expires_in が None なら期限なし、秒数が指定されれば現在時刻 + expires_in を書き込む。
    """
    language = sanitize_language(language)
    content = content.replace("\r\n", "\n").replace("\r", "\n")

    if not content:
        abort(400, description="Content is required.")

    validate_content_size(content)

    # 期限切れ時刻を計算 (0 = 期限なし)
    expires_at = 0
    if expires_in is not None:
        if (
            isinstance(expires_in, bool)
            or not isinstance(expires_in, int)
            or not 0 < expires_in <= MAX_EXPIRES_IN
        ):
            abort(400, description="expires_in must be a positive integer (seconds).")
        expires_at = int(time.time()) + expires_in

    try:
        paste_id, file_path, file_object = create_paste_file()
        try:
            file_object.write(FORMAT_V2_MARKER + "\n")
            file_object.write(language + "\n")
            file_object.write(str(expires_at) + "\n")
            file_object.write(content)
            file_object.flush()
            os.fsync(file_object.fileno())
        except Exception:
            file_object.close()
            try:
                os.remove(file_path)
            except OSError:
                pass
            raise
        finally:
            file_object.close()

        logging.info("Created paste: %s (expires_at=%s)", paste_id, expires_at)
        return paste_id

    except RuntimeError:
        logging.exception("Failed to create paste.")
        abort(500, description="Unable to create paste.")
    except OSError:
        logging.exception("Failed to write paste.")
        abort(500, description="Unable to save paste.")
```

### 閲覧のルートも置き換える

`view_paste` と `raw_paste` は、4章のコードでは、ファイルの読み込みを、それぞれのルートの中に直接書いていました。TTL対応では、**両方**を `read_paste_with_ttl()` を使う形に置き換えます。

```python
@app.route("/paste/<paste_id>")
def view_paste(paste_id):
    language, content = read_paste_with_ttl(paste_id)

    try:
        lexer = get_lexer_by_name(language)
    except ClassNotFound:
        lexer = get_lexer_by_name("text")
    formatter = HtmlFormatter(linenos=True, cssclass="highlight")
    highlighted = highlight(content, lexer, formatter)
    highlight_css = formatter.get_style_defs(".highlight")

    return render_template(
        "index.html",
        paste_id=paste_id,
        paste_language=language,
        paste_content=highlighted,
        highlight_css=highlight_css,
        csrf_token=get_csrf_token(),
        language_options=LANGUAGE_OPTIONS,
    )


@app.route("/raw/<paste_id>")
def raw_paste(paste_id):
    _, content = read_paste_with_ttl(paste_id)

    response = app.response_class(content, status=200, mimetype="text/plain")
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
```

片方だけ置き換えると、置き換え忘れたルートでは、期限が無視されるうえ、新形式のヘッダー（印・言語・期限）が本文として表示されてしまいます。ファイルを読むコードは、1つの関数にまとめておくのが安全です。

### ポイント

- **明示的な期限保存**: `mtime` に依存せず、ファイル内の Unixtime で期限を管理
- **旧形式との共存**: 1行目の印で新旧を見分け、旧形式のPasteは、書き換えずに期限なしで読める
- **自己クリーンアップ**: 閲覧時に期限切れを検出したら即座にファイルを削除
- **壊れたヘッダーへの対応**: 新形式で、期限の行が数値でなければ `404` にする
- **期限なしとの区別**: `expires_at = 0` を「期限なし」のマーカーとして使う
- **ルートの置き換え**: `view_paste` と `raw_paste` の両方で、同じ読み込み関数を使う

この設計なら、閲覧時に都度チェックするだけでなく、cron で定期的に `pastes/` ディレクトリを走査して期限切れファイルを一掃するスクリプトも書けます。その場合も、印のない旧形式のファイルは、期限がないので削除の対象にしないでください。

ファイルの中に期限を明示的に保存すれば、データベースなしでも期限の管理ができます。ただし、閲覧数のカウントや、一覧・検索など、より多くの情報が必要になったら、データベース（SQLite版のチュートリアル）の導入を検討してください。
