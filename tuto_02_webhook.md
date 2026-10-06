# Python + Flaskで作るWebhook対応Pastebin（完全版）

このチュートリアルでは、ブラウザからの手動投稿に加え、**JSON API (Webhook) 経由での自動投稿**を受け付けるPastebinを構築します。

データベースは使わず、ファイルシステムのみで動作します。API通信には**APIキー認証**と**Webhook署名検証**を導入し、用途に応じた権限管理を実現します。

---

## 1. 追加・拡張される機能

前回から以下の機能が追加・拡張されます。

### 新規・強化されたAPI機能

* **認証方式の分離** — 汎用APIキー (`X-API-Key`) と GitHub Webhook署名検証 (`X-Hub-Signature-256`) を独立した環境変数で管理
* **マルチパターン認証** — 1つのエンドポイントで「内部スクリプトからのAPI利用」と「外部サービスからのWebhook受信」の両方を安全に処理
* **GitHub Webhook対応** — ペイロードの署名検証に対応し、送信元の真正性を担保

### アーキテクチャの改善

* **セキュアバイデフォルト** — API用環境変数が未設定の場合、APIエンドポイントは自動的に `403 Forbidden` で無効化
* **レート制限の統合** — `Flask-Limiter` を組み込み、APIの過剰利用を防止（本番ではRedisストレージを推奨）

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
# 開発環境では memory:// で十分ですが、本番では redis:// を使ってください
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=os.environ.get("LIMITER_STORAGE", "memory://"),
)

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
    return secrets.compare_digest(token.encode("utf-8"), expected.encode("utf-8"))


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

    content_bytes = content.encode("utf-8")
    if len(content_bytes) > MAX_PASTE_BYTES:
        abort(413, description="Payload too large.")

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
        except Exception as e:
            # abort(413) なはここでキャッチして専用ページへ
            if hasattr(e, 'code') and e.code == 413:
                abort(413)

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
@limiter.limit("10 per minute")  # APIはより厳しく制限
def api_create_paste():
    # 1. APIが環境変数で有効化されているか確認
    if not API_ENABLED:
        abort(403, description="API is disabled by server configuration.")

    is_authorized = False

    # パターンA: 汎用APIキーによる認証
    api_key = request.headers.get("X-API-Key")
    if PASTEBIN_API_KEY and api_key and secrets.compare_digest(api_key, PASTEBIN_API_KEY):
        is_authorized = True
        logging.info("Authorized via API Key.")

    # パターンB: GitHub Webhookの署名検証による認証
    if not is_authorized and GITHUB_WEBHOOK_SECRET:
        signature = request.headers.get("X-Hub-Signature-256")
        if signature and signature.startswith("sha256="):
            expected_sig = "sha256=" + hmac.new(
                GITHUB_WEBHOOK_SECRET.encode("utf-8"),
                request.data,
                hashlib.sha256
            ).hexdigest()

            if secrets.compare_digest(signature, expected_sig):
                is_authorized = True
                logging.info("Authorized via GitHub Webhook signature.")

    if not is_authorized:
        abort(401, description="Invalid credentials or signature.")

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
    if not content and request.headers.get("X-GitHub-Event"):
        commits = data.get("commits", [])
        if commits:
            content = "\n\n".join([
                f"Commit by {c.get('author', {}).get('name', 'Unknown')}:\n"
                f"Message: {c.get('message', '')}\n"
                f"URL: {c.get('url', '')}"
                for c in commits
            ])
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
        highlighted = highlight(content, lexer, HtmlFormatter(linenos=True, cssclass="highlight"))
        highlight_css = HtmlFormatter(linenos=True, cssclass="highlight").get_style_defs(".highlight")
    except ClassNotFound:
        highlighted = highlight(content, get_lexer_by_name("text"), HtmlFormatter(linenos=True, cssclass="highlight"))
        highlight_css = HtmlFormatter(linenos=True, cssclass="highlight").get_style_defs(".highlight")

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
# Error Handlers (Content Negotiation)
# ============================================================


def is_api_request():
    """リクエストがAPI/JSONを期待しているか判定する"""
    return request.path.startswith("/api/") or request.accept_mimetypes.accept_json


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


@app.errorhandler(500)
def internal_error(error):
    if is_api_request():
        return jsonify({"error": "Internal Server Error"}), 500
    return render_template("404.html", message="Internal Server Error."), 500


# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5000)
```

---

## 5. 環境変数の設定と起動

今回は3つの環境変数を設定する必要があります。

### Linux / macOS

```bash
export FLASK_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export PASTEBIN_API_KEY="my-super-secret-api-key-12345"
export GITHUB_WEBHOOK_SECRET="my-github-webhook-secret"
python app.py
```

### Windows (PowerShell)

```powershell
$env:FLASK_SECRET_KEY = python -c "import secrets; print(secrets.token_urlsafe(32))"
$env:PASTEBIN_API_KEY = "my-super-secret-api-key-12345"
$env:GITHUB_WEBHOOK_SECRET = "my-github-webhook-secret"
python app.py
```

> **セキュアバイデフォルト**: `PASTEBIN_API_KEY` も `GITHUB_WEBHOOK_SECRET` も設されていない場合、APIエンドポイントは `403 Forbidden` を返して完全に無効化されます。設定ミスによる事故防止になっています。

---

## 6. 動作確認

### 6.1 汎用APIキーでの投稿（成功パターン）

```bash
curl -X POST http://127.0.0.1:5000/api/v1/paste \
  -H "Content-Type: application/json" \
  -H "X-API-Key: my-super-secret-api-key-12345" \
  -d '{"content": "print(\"Hello from API!\")", "language": "python"}'
```

**レスンス:**

```json
{
  "paste_id": "aB3xK9Lm2Q",
  "raw_url": "http://127.0.0.1:5000/raw/aB3xK9Lm2Q",
  "status": "success",
  "url": "http://127.0.0.1:5000/paste/aB3xK9Lm2Q"
}
```

### 6.2 エラーパターン

**APIキーが間違っている:**

```bash
curl -X POST ... -H "X-API-Key: wrong-key" ...
```

**レスポンス:** `401 Unauthorized` と `{"error": "Invalid credentials or signature."}`

**サイズ超過:**

**レスポンス:** `413 Payload Too Large` と `{"error": "Payload Too Large", "max_bytes": 524288}`

---

## 7. Pythonスクリプトからの利用例

CI/CDパイプラインや監視スクリプトから使う場合の例です。

```python
import requests

WEBHOOK_URL = "http://127.0.0.1:5000/api/v1/paste"
API_KEY = "my-super-secret-api-key-12345"

log_data = 
