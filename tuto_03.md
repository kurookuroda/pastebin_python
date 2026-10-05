# Python + Flask + SQLiteで作るPastebin

このチュートリアルでは、PythonとFlask、SQLiteを使って、ファイルベースのPastebinを拡張し、より実用的なPastebinを作ります。

前章のファイルベース版では、データベースなしでシンプルに動作するPastebinを構築しました。この章では、SQLiteを導入することで以下の機能を追加します。

* **有効期限** — Pasteに有効期限を設定し、期限切れを自動削除
* **閲覧数** — 各Pasteの閲覧回数をカウント
* **削除機能** — 削除トークンを使ったPasteの削除
* **API** — 外部からのプログラマティックなアクセス
* **トランザクション的整合性** — データベースとファイルの整合性を保
* **UTC基準の日時管理** — タイムゾーンによる混乱を排除

---

## 1. ファイルベース版との違い

### 1.1 ファイルベース版の限界

ファイルベース版では、Paste IDをファイル名として直接保存していました。これはシンプルですが、以下の情報を管理することが困難です。

| 管理したい情報 | ファイルベース版での問題 |
|----------------|------------------------|
| 有効期限 | ファイルのmtimeを使うしかないが、正確な日時管理が困難 |
| 閲覧数 | ファイルに書き込むたびにロックが必要で競合しやすい |
| 削除トークン | ファイル内に保存すると表示時に露出する、別ファイルだと管理が複雑 |
| 作成日時 | ファイルのctime/mtimeはOS依存があり信頼できない |
| 一覧・検索 | ファイル名だけでは言語や日時で絞り込めない |

### 1.2 SQLiteを使う理由

SQLiteを導入することで、上記の問題を解決できます。

* **構造問データの管理** — テーブル形式でメタデータを管理
* **ACIDトランザクション** — 書き込みの原子性を保証
* **同時アクセスの安全性** — SQLiteがロックを管理
* **クエリによる検索** — SQLで柔軟な検索・絞り込みが可能
* **軽量** — 別途サーバーを立てる必要がない、ファイルベースのデータベース

### 1.3 なぜ本文はファイルに残すのか

SQLiteに本文も保存できますが、この構成では**メタデータのみをSQLiteに保存し、本文はファイルに残す**設計にします。

理由は以下の通りです。

* **SQLiteのBLOBは大きなテキストに向かない** — 数百KB以上のテキストを大量に保存するとデータベースファイルが肥大化
* **ファイルの方がシンプル** — 本文の読み書きはファイルの方が高速でシンプル
* **バックアップの分離** — メタデータと本文を別々にバックアップできる
* **責務の分離** — SQLiteは「管理情報」、ファイルは「本文」という明確な分離

つまり、以下の役割分担になります。

| 保存先 | 保存内容 |
|--------|----------|
| SQLite (`pastes.db`) | Paste ID、言語、作成日時、有効期限、閲覧数、削除トークンハッシュ |
| ファイル (`pastes/`) | Paste本文（純粋なテキスト） |

---

## 2. 完成する機能

### 基本機能（ファイルベース版から継承）

* テキストの投稿
* 言語の指定
* 一意なPaste IDの自動生成
* Paste IDによる閲覧
* シンタックスハイライト
* Rawテキストの表示
* CSRF対策
* 投稿サイズ制限
* パストラバーサル対策
* ファイル上書き防止
* 404 / 413エラーページ
* PRG（Post/Redirect/Get）
* UTF-8対応

### SQLite版で追加される機能

* **有効期限の設定** — 作成時に有効期限を指定可能
* **閲覧数カウント** — 閲覧時に自動的にカウントアップ
* **削除機能** — 削除トークンを使ったPaste削除
* **作成日時の記録** — UTCで統一管理
* **API** — HTTPヘッダー認証付きのREST風API
* **トランザクション安全** — DB書き込みとファイル書き込みの原子性
* **定期クリーンアップ** — 期限切れPasteの削除スクリプト

---

## 3. ディレクトリ構成

```text
pastebin/
├── app.py              ← Flaskアプリケーション本体
├── cleanup.py          ← 期限切れPasteの削除スクリプト
├── schema.sql          ← SQLiteのテーブル定義
├── requirements.txt    ← 必要なパッケージ
├── pastes.db           ← SQLiteデータベースファイル
├── pastes/             ← Paste本文の保存先
│   └── Ab3xK9Lm2Q
├── templates/
│   ├── index.html      ← 投稿フォーム
│   ├── view.html       ← Paste表示
│   ├── 404.html        ← Not Found
│   └── 413.html        ← Payload Too Large
└── static/
    └── style.css
```

### 追加されたファイル

| ファイル | 役割 |
|----------|------|
| `cleanup.py` | 期限切れPasteをDBとファイルから削除する独立スクリプト |
| `schema.sql` | データベースのテーブル構造を定義 |
| `pastes.db` | SQLiteデータベース（自動作成） |
| `templates/view.html` | Paste表示専用テプレート（index.htmlから分離） |

---

## 4. 必要なパッケージ

### requirements.txt

```text
Flask
Pygments
shortuuid
```

ファイルベース版と同じパッケージです。SQLiteはPythonの標準ライブラリに含まれているため、追加のインストールは不要です。

### インストール

```bash
python -m pip install -r requirements.txt
```

---

## 5. データベース設計

### 5.1 schema.sql

```sql
CREATE TABLE IF NOT EXISTS pastes (
    paste_id         TEXT PRIMARY KEY,
    language         TEXT NOT NULL DEFAULT 'text',
    created_at       TEXT NOT NULL,
    expires_at       TEXT,
    view_count       INTEGER NOT NULL DEFAULT 0,
    delete_token_hash TEXT
);

CREATE INDEX IF NOT EXISTS idx_expires_at ON pastes(expires_at);
```

#### 各カラムの説明

| カラム | 型 | 説明 |
|--------|-----|------|
| `paste_id` | TEXT | 主キー。shortuuidで生成したPaste ID |
| `language` | TEXT | 言語名（python、javascriptなど） |
| `created_at` | TEXT | 作成日時（ISO 8601形式、UTC） |
| `expires_at` | TEXT | 有効期限（ISO 8601形式、UTC）。NULLの場合は無期限 |
| `view_count` | INTEGER | 閲覧数。デフォルト0 |
| `delete_token_hash` | TEXT | 削除トークンのSHA-256ハッシュ値。NULLの場合は削除不可 |

#### なぜ日時はTEXT型か

SQLiteには日時専用の型がありません。日時の保存方法には以下の選択肢があります。

| 方法 | 例 | 特徴 |
|------|-----|------|
| TEXT | `2024-01-15T08:30:00+00:00` | 人間が読める、ISO 8601標準準拠 |
| INTEGER | `1705312200` | Unix epoch秒。比較は高速だが可読性が低い |
| REAL | `1705312200.123` | Unix epoch秒（小数点以下あり） |

このチュートリアルでは**TEXT型（ISO 8601形式）**を採用します。理由は以下の通りです。

* 人間が直接読んで理解できる
* Pythonの `datetime.isoformat()` と `datetime.fromisoformat()` で直接変換できる
* タイムゾーン情報を含められる
* 辞書順ソートで時系列順になる

#### なぜ削除トークンはハッシュ化するのか

削除トークンは「そのトークンを知っている者のみがPasteを削除できる」という認証情報です。データベースに平文で保存すると、以下のリスクがあります。

* データベースファイルが漏洩した場合、すべてのPasteの削除トークンが流出
* バックアップファイルから削除トークンが復元可能

SHA-256でハッシュ化して保存することで、たとえデータベースが漏洩しても、元のトークンを逆算することは困難です。検証時には「受け取たトークンをハッシュ化して、保存されたハッシュと比較」します。

#### インデックスの意味

```sql
CREATE INDEX IF NOT EXISTS idx_expires_at ON pastes(expires_at);
```

`expires_at` カラムにインデックスを作成します。クリーンアップ時に「有効期限が現在時刻より古いレコード」を検索するため、このカラムへのインデックスがないと、Paste数が増えるにつれて検索が遅くなります。

### 5.2 データベースの初期化

```python
import sqlite3

DATABASE_PATH = "pastes.db"

def init_db():
    with sqlite3.connect(DATABASE_PATH) as conn:
        with open("schema.sql", "r", encoding="utf-8") as f:
            conn.executescript(f.read())
```

`executescript()` は複数のSQL文を一度に実行できます。`schema.sql` の `IF NOT EXISTS` により、何度実行しても既存のテーブルやインデックスは上書きされません。

---

## 6. Flaskアプリケーション（app.py）

### 6.1 全文

```python
#!/usr/bin/env python3

import hashlib
import logging
import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone, timedelta

import shortuuid
from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import ClassNotFound, get_all_lexers, get_lexer_by_name


app = Flask(__name__)

# ============================================================
# Configuration
# ============================================================

secret_key = os.environ.get("FLASK_SECRET_KEY")

if not secret_key:
    raise RuntimeError(
        "FLASK_SECRET_KEY environment variable is required."
    )

app.secret_key = secret_key

MAX_PASTE_BYTES = 512 * 1024
app.config["MAX_CONTENT_LENGTH"] = MAX_PASTE_BYTES + 16 * 1024

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = (
    os.environ.get("FLASK_HTTPS", "").lower() == "true"
)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
PASTE_DIR = os.path.join(BASE_DIR, "pastes")
DATABASE_PATH = os.path.join(BASE_DIR, "pastes.db")

os.makedirs(PASTE_DIR, exist_ok=True)

API_KEY = os.environ.get("PASTEBIN_API_KEY")

# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


# ============================================================
# Database
# ============================================================

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with app.app_context():
        db = get_db()
        with app.open_resource("schema.sql", mode="r") as f:
            db.executescript(f.read())
        db.commit()


# ============================================================
# Paste ID validation
# ============================================================

VALID_PASTE_ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def is_valid_paste_id(paste_id):
    return bool(
        isinstance(paste_id, str)
        and VALID_PASTE_ID.fullmatch(paste_id)
    )


# ============================================================
# Language handling
# ============================================================

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
    if language in ALLOWED_LANGUAGES:
        return language
    return "text"


# ============================================================
# CSRF
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
    return secrets.compare_digest(token, expected)


# ============================================================
# Delete token
# ============================================================

def hash_delete_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_delete_token():
    return secrets.token_urlsafe(16)


def verify_delete_token(token, stored_hash):
    if not token or not stored_hash:
        return False
    return secrets.compare_digest(
        hash_delete_token(token),
        stored_hash,
    )


# ============================================================
# Date/time helpers
# ============================================================

def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def parse_iso_datetime(value):
    if not value:
        return None
    return datetime.fromisoformat(value)


def is_expired(expires_at):
    if not expires_at:
        return False
    expiry = parse_iso_datetime(expires_at)
    return datetime.now(timezone.utc) > expiry


# ============================================================
# Paste operations
# ============================================================

def create_paste_in_db(paste_id, language, expires_at, delete_token_hash):
    db = get_db()
    db.execute(
        """
        INSERT INTO pastes (paste_id, language, created_at, expires_at, delete_token_hash)
        VALUES (?, ?, ?, ?, ?)
        """,
        (paste_id, language, utc_now_iso(), expires_at, delete_token_hash),
    )
    db.commit()


def get_paste_from_db(paste_id):
    db = get_db()
    row = db.execute(
        "SELECT * FROM pastes WHERE paste_id = ?",
        (paste_id,),
    ).fetchone()
    return row


def increment_view_count(paste_id):
    db = get_db()
    db.execute(
        "UPDATE pastes SET view_count = view_count + 1 WHERE paste_id = ?",
        (paste_id,),
    )
    db.commit()


def delete_paste_from_db(paste_id):
    db = get_db()
    db.execute("DELETE FROM pastes WHERE paste_id = ?", (paste_id,))
    db.commit()


# ============================================================
# File operations
# ============================================================

def get_paste_file_path(paste_id):
    return os.path.join(PASTE_DIR, paste_id)


def write_paste_file(paste_id, content):
    file_path = get_paste_file_path(paste_id)
    with open(file_path, "x", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    return file_path


def read_paste_file(paste_id):
    file_path = get_paste_file_path(paste_id)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeError):
        abort(404)


def remove_paste_file(paste_id):
    file_path = get_paste_file_path(paste_id)
    try:
        os.remove(file_path)
    except OSError:
        pass


# ============================================================
# Transaction-safe paste creation
# ============================================================

def create_paste(content, language, expires_at=None):
    for _ in range(20):
        paste_id = shortuuid.random(length=10)
        if not is_valid_paste_id(paste_id):
            continue

        delete_token = generate_delete_token()
        delete_token_hash = hash_delete_token(delete_token)

        db = get_db()
        try:
            db.execute("BEGIN IMMEDIATE")

            # Check if paste_id already exists
            existing = db.execute(
                "SELECT 1 FROM pastes WHERE paste_id = ?",
                (paste_id,),
            ).fetchone()

            if existing:
                db.rollback()
                continue

            db.execute(
                """
                INSERT INTO pastes (paste_id, language, created_at, expires_at, delete_token_hash)
                VALUES (?, ?, ?, ?, ?)
                """,
                (paste_id, language, utc_now_iso(), expires_at, delete_token_hash),
            )

            write_paste_file(paste_id, content)

            db.commit()
            return paste_id, delete_token

        except Exception:
            db.rollback()
            remove_paste_file(paste_id)
            raise

    raise RuntimeError("Unable to generate a unique paste ID.")


# ============================================================
# API key verification
# ============================================================

def verify_api_key():
    if not API_KEY:
        return False
    provided = request.headers.get("X-API-Key", "")
    if not provided:
        return False
    return secrets.compare_digest(provided, API_KEY)


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
        language = sanitize_language(request.form.get("language", "text"))

        # Optional expiration
        expires_minutes = request.form.get("expires_minutes", "")
        expires_at = None
        if expires_minutes:
            try:
                minutes = int(expires_minutes)
                if minutes > 0:
                    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
            except ValueError:
                pass

        if not content:
            flash("Paste content is required.", "error")
            return render_template(
                "index.html",
                csrf_token=get_csrf_token(),
                language_options=LANGUAGE_OPTIONS,
            ), 400

        content_bytes = content.encode("utf-8")
        if len(content_bytes) > MAX_PASTE_BYTES:
            abort(413)

        try:
            paste_id, delete_token = create_paste(content, language, expires_at)
        except RuntimeError:
            logging.exception("Failed to create paste.")
            flash("Unable to create paste.", "error")
            return render_template(
                "index.html",
                csrf_token=get_csrf_token(),
                language_options=LANGUAGE_OPTIONS,
            ), 500
        except OSError:
            logging.exception("Failed to write paste.")
            flash("Unable to save paste.", "error")
            return render_template(
                "index.html",
                csrf_token=get_csrf_token(),
                language_options=LANGUAGE_OPTIONS,
            ), 500

        logging.info("Created paste: %s", paste_id)

        # Show delete token once
        flash(f"Paste created. Delete token: {delete_token}", "info")

        return redirect(url_for("view_paste", paste_id=paste_id))

    return render_template(
        "index.html",
        csrf_token=get_csrf_token(),
        language_options=LANGUAGE_OPTIONS,
    )


@app.route("/paste/<paste_id>")
def view_paste(paste_id):
    if not is_valid_paste_id(paste_id):
        abort(404)

    row = get_paste_from_db(paste_id)
    if not row:
        abort(404)

    if is_expired(row["expires_at"]):
        abort(404)

    increment_view_count(paste_id)

    content = read_paste_file(paste_id)
    language = sanitize_language(row["language"])

    try:
        lexer = get_lexer_by_name(language)
        highlighted = highlight(
            content,
            lexer,
            HtmlFormatter(linenos=True, cssclass="highlight"),
        )
        highlight_css = HtmlFormatter(
            linenos=True, cssclass="highlight"
        ).get_style_defs(".highlight")
    except ClassNotFound:
        highlighted = highlight(
            content,
            get_lexer_by_name("text"),
            HtmlFormatter(linenos=True, cssclass="highlight"),
        )
        highlight_css = HtmlFormatter(
            linenos=True, cssclass="highlight"
        ).get_style_defs(".highlight")

    return render_template(
        "view.html",
        paste_id=paste_id,
        paste_language=language,
        paste_content=highlighted,
        highlight_css=highlight_css,
        view_count=row["view_count"] + 1,
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        csrf_token=get_csrf_token(),
    )


@app.route("/raw/<paste_id>")
def raw_paste(paste_id):
    if not is_valid_paste_id(paste_id):
        abort(404)

    row = get_paste_from_db(paste_id)
    if not row or is_expired(row["expires_at"]):
        abort(404)

    increment_view_count(paste_id)

    content = read_paste_file(paste_id)

    response = app.response_class(
        content,
        status=200,
        mimetype="text/plain",
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.route("/delete/<paste_id>", methods=["POST"])
def delete_paste(paste_id):
    if not is_valid_paste_id(paste_id):
        abort(404)

    csrf_token = request.form.get("csrf_token", "")
    if not verify_csrf_token(csrf_token):
        abort(400)

    row = get_paste_from_db(paste_id)
    if not row:
        abort(404)

    token = request.form.get("delete_token", "")
    if not verify_delete_token(token, row["delete_token_hash"]):
        flash("Invalid delete token.", "error")
        return redirect(url_for("view_paste", paste_id=paste_id))

    delete_paste_from_db(paste_id)
    remove_paste_file(paste_id)

    logging.info("Deleted paste: %s", paste_id)
    flash("Paste deleted.", "info")
    return redirect(url_for("index"))


# ============================================================
# API Routes
# ============================================================

@app.route("/api/pastes", methods=["POST"])
def api_create_paste():
    if not verify_api_key():
        abort(401)

    data = request.get_json(silent=True) or {}
    content = data.get("content", "")
    language = sanitize_language(data.get("language", "text"))

    expires_minutes = data.get("expires_minutes")
    expires_at = None
    if expires_minutes:
        try:
            minutes = int(expires_minutes)
            if minutes > 0:
                expires_at = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
        except (ValueError, TypeError):
            pass

    if not content:
        return {"error": "Paste content is required."}, 400

    content_bytes = content.encode("utf-8")
    if len(content_bytes) > MAX_PASTE_BYTES:
        return {"error": "Paste too large."}, 413

    try:
        paste_id, delete_token = create_paste(content, language, expires_at)
    except RuntimeError:
        logging.exception("Failed to create paste via API.")
        return {"error": "Unable to create paste."}, 500
    except OSError:
        logging.exception("Failed to write paste via API.")
        return {"error": "Unable to save paste."}, 500

    logging.info("Created paste via API: %s", paste_id)

    response_data = {
        "paste_id": paste_id,
        "url": url_for("view_paste", paste_id=paste_id, _external=True),
        "raw_url": url_for("raw_paste", paste_id=paste_id, _external=True),
        "delete_token": delete_token,
    }

    if expires_at:
        response_data["expires_at"] = expires_at

    return response_data, 201


@app.route("/api/pastes/<paste_id>", methods=["GET"])
def api_get_paste(paste_id):
    if not is_valid_paste_id(paste_id):
        abort(404)

    row = get_paste_from_db(paste_id)
    if not row or is_expired(row["expires_at"]):
        abort(404)

    increment_view_count(paste_id)

    content = read_paste_file(paste_id)

    return {
        "paste_id": paste_id,
        "language": row["language"],
        "content": content,
        "view_count": row["view_count"] + 1,
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
    }, 200


@app.route("/api/pastes/<paste_id>", methods=["DELETE"])
def api_delete_paste(paste_id):
    if not verify_api_key():
        abort(401)

    if not is_valid_paste_id(paste_id):
        abort(404)

    row = get_paste_from_db(paste_id)
    if not row:
        abort(404)

    token = request.headers.get("X-Delete-Token", "")
    if not verify_delete_token(token, row["delete_token_hash"]):
        return {"error": "Invalid or missing delete token."}, 403

    delete_paste_from_db(paste_id)
    remove_paste_file(paste_id)

    logging.info("Deleted paste via API: %s", paste_id)
    return {"message": "Paste deleted."}, 200


# ============================================================
# Error handlers
# ============================================================

@app.errorhandler(400)
def bad_request(error):
    return render_template("404.html", message="Bad request."), 400


@app.errorhandler(401)
def unauthorized(error):
    return render_template("404.html", message="Unauthorized."), 401


@app.errorhandler(404)
def not_found(error):
    return render_template("404.html", message="Paste not found."), 404


@app.errorhandler(413)
def request_too_large(error):
    return render_template("413.html", max_bytes=MAX_PASTE_BYTES), 413


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    init_db()
    app.run(debug=False, host="127.0.0.1", port=5000)
```

---

## 7. app.py の各部分の解説

### 7.1 データベース接続の管理

```python
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db
```

Flaskの `g` オブジェクトは、**リクエスト単位**のグローバル名前空間です。同じリクエスト内で複数回 `get_db()` を呼んでも、新しい接続が作られるのは最初の1回だけです。

`sqlite3.Row` を `row_factory` に設定することで、結果を辞書のようにアクセスできます。

```python
row = db.execute("SELECT * FROM pastes WHERE paste_id = ?", (paste_id,)).fetchone()
language = row["language"]  # 辞書のようにカラム名でアクセス
```

---

```python
@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()
```

リクエスト終了時にデータベース接続を自動的に閉じます。例外が発生しても確実に実行されます。

### 7.2 削除トークンの設計

```python
def hash_delete_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_delete_token():
    return secrets.token_urlsafe(16)
```

削除トークンの生成とハッシュ化を分離しています。

**生成時の流れ**

```
secrets.token_urlsafe(16) → 平文トークン
    ↓
SHA-256ハッシュ化
    ↓
データベースに保存（ハッシュ値のみ）
    ↓
ユーザーに平文トークンを一度だけ表示
```

**検証時の流れ**

```
ユーザーがトークンを送信
    ↓
受け取ったトークンをSHA-256ハッシュ化
    ↓
データベースのハッシュ値と compare_digest で比較
```

`secrets.compare_digest()` を使用することで、タイミング攻撃を防ぎます。

### 7.3 UTC日時の統一管理

```python
def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()
```

`timezone.utc` を明示することで、タイムゾーン付きの日時（例：`2024-01-15T08:30:00+00:00`）を生成します。

#### なぜUTCを使うのか

* サーバーが異なるタイムゾーン移動しても日時が変わらない
* 夏時間（DST）の有無に関係なく一貫した動作
* クライアントのタイムゾーンと独立して比較できる

```python
# NG: タイムゾーンなし（ローカル時刻。サーバー設定に依存）
datetime.now()  # 2024-01-15 17:30:00（JSTなら日本時間）

# OK: UTC明示
datetime.now(timezone.utc).isoformat()  # 2024-01-15T08:30:00+00:00
```

### 7.4 トランザクション安全なPaste作成

```python
def create_paste(content, language, expires_at=None):
    for _ in range(20):
        paste_id = shortuuid.random(length=10)
        ...
        db = get_db()
        try:
            db.execute("BEGIN IMMEDIATE")
            ...
            db.execute("INSERT INTO pastes ...")
            write_paste_file(paste_id, content)
            db.commit()
            return paste_id, delete_token
        except Exception:
            db.rollback()
            remove_paste_file(paste_id)
            raise
```

#### BEGIN IMMEDIATE の意味

SQLiteのトランザクションには以下のモードがあります。

| モード | 動作 |
|--------|------|
| `BEGIN DEFERRED` | 最初の読み書きまでロックを取得しない（デフォルト） |
| `BEGIN IMMEDIATE` | 開始時に書き込みロックを取得 |
| `BEGIN EXCLUSIVE` | 開始時に排他ロックを取得 |

`BEGIN IMMEDIATE` を使う理由は、**書き込み競合時のエラーを早期に検出**するためです。デフォルトの `DEFERRED` では、コミット時に競合が発見されることがあります。

#### ロールバッとクリーンアップ

例外発生時の処理は以下の順序です。

1. `db.rollback()` — データベースの変更を取り消し
2. `remove_paste_file(paste_id)` — 作成途中のファイルを削除

これにより、以下の不整合を防ぎます。

* DBにレコードがあるがファイルがない
* ファイルがあるがDBにレコードがない

### 7.5 有効期限の処理

```python
def is_expired(expires_at):
    if not expires_at:
        return False
    expiry = parse_iso_datetime(expires_at)
    return datetime.now(timezone.utc) > expiry
```

`expires_at` が `NULL`（無期限）の場合は常に `False` を返します。それ以外の場合は、現在のUTC時刻と比較します。

#### なぜ閲覧時にチェックするのか

期限切れPasteの削除は `cleanup.py` で定期的に行いますが、クリーンアップの実行間隔中に期限が切れたPasteにもアクセスできる可能性があります。閲覧時にもチェックすることで、いつでも期限切れPasteを見せないことを保証します。

### 7.6 API認証

```python
def verify_api_key():
    if not API_KEY:
        return False
    provided = request.headers.get("X-API-Key", "")
    if not provided:
        return False
    return secrets.compare_digest(provided, API_KEY)
```

API Keyは環境変数 `PASTEBIN_API_KEY` から取得します。設定されていない場合は、APIへのアクセスをすべて拒否します。

#### API Keyの生成

```bash
export PASTEBIN_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

---

## 8. クリーンアップスクリプト（cleanup.py）

```python
#!/usr/bin/env python3

import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
PASTE_DIR = os.path.join(BASE_DIR, "pastes")
DATABASE_PATH = os.path.join(BASE_DIR, "pastes.db")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def cleanup():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row

    now = datetime.now(timezone.utc).isoformat()

    rows = conn.execute(
        "SELECT paste_id FROM pastes WHERE expires_at IS NOT NULL AND expires_at < ?",
        (now,),
    ).fetchall()

    deleted_count = 0

    for row in rows:
        paste_id = row["paste_id"]
        file_path = os.path.join(PASTE_DIR, paste_id)

        try:
            os.remove(file_path)
            logging.info("Removed expired paste file: %s", paste_id)
        except OSError:
            logging.warning("Failed to remove paste file: %s", paste_id)

        conn.execute("DELETE FROM pastes WHERE paste_id = ?", (paste_id,))
        deleted_count += 1

    conn.commit()
    conn.close()

    logging.info("Cleanup completed. Deleted %d expired pastes.", deleted_count)


if __name__ == "__main__":
    cleanup()
```

### 8.1 なぜ独立スクリプトにするのか

Flaskアプリケーション内にクリーンアップ処理を組み込む方法もあります（例：`threading.Timer` で定期実行）。しかし、以下の理由で独立スクリプトを推奨しま。

| 方法 | 問題 |
|------|------|
| Flask内スレッド | 複数ワーカー（Gunicorn等）で重複実行される可能性がある |
| Flask内スレッド | アプリケーションコードと混在し、責務が不明確 |
| 独立スクリプト | cronやsystemd timerで管理でき、実行タイミングを外部制御できる |
| 独立スクリプト | テスト・手動実行が容易 |

### 8.2 定期実行の設定

#### cron を使う場合

```bash
# 毎時間実行
crontab -e
```

```text
0 * * * * cd /path/to/pastebin && /path/to/venv/bin/python cleanup.py >> /var/log/pastebin-cleanup.log 2>&1
```

#### systemd timer を使う場合

`/etc/systemd/system/pastebin-cleanup.service`

```ini
[Unit]
Description=Pastebin Cleanup

[Service]
Type=oneshot
ExecStart=/path/to/venv/bin/python /path/to/pastebin/cleanup.py
WorkingDirectory=/path/to/pastebin
```

`/etc/systemd/system/pastebin-cleanup.timer`

```ini
[Unit]
Description=Run Pastebin Cleanup hourly

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl enable pastebin-cleanup.timer
sudo systemctl start pastebin-cleanup.timer
```

---

## 9. テンプレート

### 9.1 index.html（投稿フォーム）

```html
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pastebin</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
<div class="container">
    <header>
        <h1><a href="{{ url_for('index') }}">Pastebin</a></h1>
    </header>

    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            <div class="messages">
                {% for category, message in messages %}
                    <div class="message {{ category }}">{{ message }}</div>
                {% endfor %}
            </div>
        {% endif %}
    {% endwith %}

    <section class="new-paste">
        <h2>New Paste</h2>
        <form method="post" action="{{ url_for('index') }}" novalidate>
            <input type="hidden" name="csrf_token" value="{{ csrf_token }}">

            <div class="form-row">
                <label for="language">Language</label>
                <select id="language" name="language">
                    <option value="text">Plain Text</option>
                    {% for language in language_options %}
                        {% if language != "text" %}
                        <option value="{{ language }}">{{ language }}</option>
                        {% endif %}
                    {% endfor %}
                </select>
            </div>

            <div class="form-row">
                <label for="expires_minutes">Expires in (minutes, optional)</label>
                <input
                    type="number"
                    id="expires_minutes"
                    name="expires_minutes"
                    min="1"
                    placeholder="Leave empty for no expiration"
                >
            </div>

            <div class="form-row">
                <label for="content">Content</label>
                <textarea
                    id="content"
                    name="content"
                    rows="24"
                    maxlength="524288"
                    spellcheck="false"
                ></textarea>
            </div>

            <div class="form-footer">
                <p>Maximum size: 512 KiB</p>
                <button type="submit">Create Paste</button>
            </div>
        </form>
    </section>
</div>
</body>
</html>
```

### 9.2 view.html（Paste表示）

```html
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pastebin — {{ paste_id }}</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
    {% if highlight_css %}
    <style>{{ highlight_css|safe }}</style>
    {% endif %}
</head>
<body>
<div class="container">
    <header>
        <h1><a href="{{ url_for('index') }}">Pastebin</a></h1>
    </header>

    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            <div class="messages">
                {% for category, message in messages %}
                    <div class="message {{ category }}">{{ message }}</div>
                {% endfor %}
            </div>
        {% endif %}
    {% endwith %}

    <section class="paste">
        <div class="paste-header">
            <div><strong>Paste ID:</strong> <code>{{ paste_id }}</code></div>
            <div><strong>Language:</strong> <code>{{ paste_language }}</code></div>
            <div><strong>Views:</strong> {{ view_count }}</div>
            <div><strong>Created:</strong> {{ created_at }}</div>
            {% if expires_at %}
            <div><strong>Expires:</strong> {{ expires_at }}</div>
            {% endif %}
        </div>

        <div class="paste-links">
            <a href="{{ url_for('raw_paste', paste_id=paste_id) }}">Raw</a>
            <a href="{{ url_for('index') }}">New Paste</a>
        </div>

        <div class="paste-content">
            {{ paste_content|safe }}
        </div>

        <hr>

        <form method="post" action="{{ url_for('delete_paste', paste_id=paste_id) }}" novalidate>
            <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
            <div class="form-row">
                <label for="delete_token">Delete Token</label>
                <input type="text" id="delete_token" name="delete_token" required>
            </div>
            <button type="submit" class="danger">Delete Paste</button>
        </form>
    </section>
</div>
</body>
</html>
```

### 9.3 404.html

```html
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pastebin — Not Found</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
<div class="container">
    <h1><a href="{{ url_for('index') }}">Pastebin</a></h1>
    <section class="error-page">
        <h2>Not Found</h2>
        <p>{{ message or "The requested paste was not found or has expired." }}</p>
        <p><a href="{{ url_for('index') }}">Back to Pastebin</a></p>
    </section>
</div>
</body>
</html>
```

### 9.4 413.html

```html
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pastebin — Too Large</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
<div class="container">
    <h1><a href="{{ url_for('index') }}">Pastebin</a></h1>
    <section class="error-page">
        <h2>Payload Too Large</h2>
        <p>The submitted paste is too large.</p>
        <p>Maximum size: {{ (max_bytes / 1024)|int }} KiB</p>
        <p><a href="{{ url_for('index') }}">Back to Pastebin</a></p>
    </section>
</div>
</body>
</html>
```

---

## 10. CSS

ファイルベース版に以下を追加します。

```css
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background: #f5f5f5;
    color: #222;
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

.container {
    width: min(1100px, calc(100% - 32px));
    margin: 0 auto;
    padding: 24px 0 48px;
}

header {
    margin-bottom: 24px;
}

h1 {
    margin: 0;
}

h1 a {
    color: inherit;
    text-decoration: none;
}

h2 {
    margin-top: 0;
}

.new-paste,
.paste,
.error-page {
    background: #fff;
    border: 1px solid #ddd;
    border-radius: 8px;
    padding: 20px;
}

.form-row {
    margin-bottom: 20px;
}

.form-row label {
    display: block;
    margin-bottom: 8px;
    font-weight: 600;
}

select,
input[type="number"],
input[type="text"],
textarea {
    width: 100%;
    border: 1px solid #bbb;
    border-radius: 6px;
    font: inherit;
}

select,
input[type="number"],
input[type="text"] {
    padding: 8px;
    background: #fff;
}

textarea {
    min-height: 400px;
    padding: 12px;
    resize: vertical;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    line-height: 1.5;
}

.form-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 16px;
}

.form-footer p {
    margin: 0;
    color: #666;
}

button {
    border: 0;
    border-radius: 6px;
    padding: 10px 18px;
    background: #222;
    color: #fff;
    font: inherit;
    cursor: pointer;
}

button:hover {
    opacity: 0.9;
}

button.danger {
    background: #c00;
}

.messages {
    margin-bottom: 20px;
}

.message {
    padding: 12px;
    border-radius: 6px;
    background: #eee;
}

.message.error {
    background: #f8d7da;
}

.message.info {
    background: #d1ecf1;
}

.paste-header {
    display: flex;
    flex-wrap: wrap;
    gap: 20px;
    margin-bottom: 16px;
}

.paste-header code {
    margin-left: 4px;
}

.paste-links {
    display: flex;
    gap: 16px;
    margin-bottom: 16px;
}

.paste-content {
    overflow-x: auto;
    border: 1px solid #ddd;
    border-radius: 6px;
    margin-bottom: 24px;
}

.paste-content pre {
    margin: 0;
}

.error-page {
    text-align: center;
}

a {
    color: #1558a6;
}

hr {
    border: 0;
    border-top: 1px solid #ddd;
    margin: 24px 0;
}

@media (max-width: 700px) {
    .container {
        width: min(100% - 20px, 1100px);
        padding-top: 12px;
    }

    .new-paste,
    .paste,
    .error-page {
        padding: 14px;
    }

    .form-footer {
        flex-direction: column;
        align-items: stretch;
    }

    button {
        width: 100%;
    }
}
```

---

## 11. 起動方法

### 11.1 環境変数の設定

```bash
export FLASK_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export PASTEBIN_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

### 11.2 データベースの初期化

```bash
python -c "from app import init_db; init_db()"
```

または、初回起動時に自動初期化されます。

```bash
python app.py
```

### 11.3 HTTPS環境

```bash
export FLASK_HTTPS=true
python app.py
```

---

## 12. APIの使い方

### 12.1 Pasteの作成

```bash
curl -X POST http://127.0.0.1:5000/api/pastes \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{
    "content": "def hello():\n    print(\"Hello\")",
    "language": "python",
    "expires_minutes": 60
  }'
```

レスポンス例

```json
{
  "paste_id": "Ab3xK9Lm2Q",
  "url": "http://127.0.0.1:5000/paste/Ab3xK9Lm2Q",
  "raw_url": "http://127.0.0.1:5000/raw/Ab3xK9Lm2Q",
  "delete_token": "abcd1234...",
  "expires_at": "2024-01-15T09:30:00+00:00"
}
```

### 12.2 Pasteの取得

```bash
curl http://127.0.0.1:5000/api/pastes/Ab3xK9Lm2Q
```

### 12.3 Pasteの削除

```bash
curl -X DELETE http://127.0.0.1:5000/api/pastes/Ab3xK9Lm2Q \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "X-Delete-Token: DELETE_TOKEN_HERE"
```

---

## 13. セキュリティ対策のまとめ

### ファイルベース版から継承

| 威 | 対策 |
|------|------|
| パストラバーサル | Paste IDの正規表現検証 |
| CSRF攻撃 | CSRFトークンの生成と検証 |
| DoS（サイズ攻撃） | リクエストサイズ上限 |
| ファイル上書き | `"x"` モードでの排他作成 |
| XSS | Pygmentsによる安全なHTML変換 |
| セッション窃取 | `HttpOnly`, `SameSite`, `Secure` Cookie属性 |
| 二重投稿 | PRGパターン |
| タイミング攻撃 | `secrets.compare_digest()` |

### SQLite版で追加

| 脅威 | 対策 |
|------|------|
| 削除トークンの漏洩 | SHA-256ハッシュ化で保存 |
| 不正なAPIアクセス | `X-API-Key` ヘッダー認証 |
| 期限切れPasteの閲覧 | 閲覧時の有効期限チェック |
| DBとファイルの不整合 | トランザクションとロールバック |
| 情報漏洩 | エラー詳細の隠蔽、一律404 |

---

## 14. ファイルベース版からの移行

### 14.1 移行の考え方

ファイルベース版からSQLite版へ移行する場合、既存のPasteファイルをSQLiteに登録するスクリプトが必要です。

### 14.2 移スクリプト例

```python
import os
import sqlite3
from datetime import datetime, timezone

PASTE_DIR = "pastes"
DB_PATH = "pastes.db"

conn = sqlite3.connect(DB_PATH)

for filename in os.listdir(PASTE_DIR):
    filepath = os.path.join(PASTE_DIR, filename)
    if not os.path.isfile(filepath):
        continue

    with open(filepath, "r", encoding="utf-8") as f:
        language = f.readline().strip()

    created_at = datetime.fromtimestamp(
        os.path.getctime(filepath),
        tz=timezone.utc
    ).isoformat()

    conn.execute(
        "INSERT OR IGNORE INTO pastes (paste_id, language, created_at) VALUES (?, ?, ?)",
        (filename, language, created_at),
    )

conn.commit()
conn.close()
```

---

## 15. まとめ

このチュートリアルでは、ファイルベースのPastebinをSQLiteで拡張し、より実用的な構成にしました。

### 追加された価値

| 機能 | ファイルベース版 | SQLite版 |
|------|----------------|----------|
| 有効期限 | 不可 | 可能 |
| 閲覧数 | 不可 | 自動カウント |
| 削除機能 | 不可 | トークン認証付き |
| API | 不可 | REST風API |
| トランザクション安全 | 部分的 | 完全 |
| UTC日時管理 | 不可 | 統一 |
| 定期クリーンアップ | 不可 | 独立スクリプト |

### 構成の特徴

* **本文はファイル** — 大きなテキストを効率的に管理
* **メタデータはSQLite** — 構造化データを安全に管理
* **トランザクションで整合性を保証** — DBとファイルの不整合を防ぐ
* **UTC日時を統一** — タイムゾーンの混乱を排除
* **独立したクリーンアップ** — 運用時の柔軟性を確保

この構成は、小〜中規模のPastebinサービスとして十分実用的です。さらに大規模化する場合は、PostgreSQL等の本格的なRDBMSや、オブジェクトストレージの検討が必要になりますが、その判断基準もこのチュートリアルで示した設計思想を参考にできます。
