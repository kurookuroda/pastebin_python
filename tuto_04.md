# Python + Flask + SQLiteで作るPastebin（完成版）

このチュートリアルでは、PythonとFlask、SQLiteを使って、ファイルベースのPastebinを拡張し、より実用的なPastebinを完成させます。

前章のファイルベース版では、データベースなしでシンプルに動作するPastebinを構築しました。この章では、SQLiteを導入することで以下の機能を追加します。

* **有効期限** — Pasteに有効期限を設定し、期限切れを削除
* **閲覧数** — 各Pasteの閲覧回数をカウント
* **削除機能** — 削除トークンを使ったPasteの削除
* **API** — 外部からのプログラマティックなアクセス
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
| 一覧・検索 | ファイルだけでは言語や日時で絞り込めない |

### 1.2 SQLiteを使う理由

SQLiteを導入することで、上記の問題を解決できます。

* **構造化データの管理** — テーブル形式でメタデータを管理
* **ACIDトランザクション** — SQLite内部の操作について原子性を保証
* **同時アクセスの安全性** — SQLiteがDBファイルへのロックを管理
* **クエリによる検索** — SQLで柔軟な検索・絞り込みが可能
* **軽量** — 別途サーバーを立てる必要がない、ファイルベースのデータベース

ただし、SQLiteのトランザクションはSQLite自身の操作に対してのみ有効です。本文ファイルへの書き込みとSQLiteの操作を合わせた完全な原子性は保証されません。

### 1.3 なぜ本文はファイルに残すのか

SQLiteに本文も保存できますが、この構成では**メタデータのみをSQLiteに保存し、本文はファイルに残す**設計にします。

理由は以下の通りです。

* **SQLiteのBLOBは大きなテキストに向かない** — 数KB以上のテキストを大量に保存するとデータベースファイルが肥大化
* **ファイルの方がシンプル** — 本文の読み書きはファイルの方が高速でシンプル
* **バックアップの分離** — メタデータと本文を別々にバックアップできる
* **責務の分離** — SQLiteは「管理情報」、ファイルは「本文」という明確な分離

つまり、以下の役割分担になります。

| 保存先 | 保存内容 |
|--------|----------|
| SQLite (`pastes.db`) | Paste ID、言語、作成日時、有効期限、閲覧数、削除トークンハッシュ |
| ファイル (`pastes/`) | Paste本文（純粋なテキスト） |

### 1.4 DBとファイルの整合性について（重要）

この構成では、SQLiteとファイルの両方を使います。**SQLiteのトランザクションはSQLiteの操作だけを対象にするため、DBとファイルを完全に原子的に扱うことはできません**。

例えば、以下のような不整合が理論上は起こり得ます。

| 状況 | 結果 |
|------|------|
| DBにINSERT成功 → ファイル書き込み失敗 → 補償削除成功 | DBにもファイルもない → 整合 |
| DBにINSERT成功 → ファイル書き込み成功 | DBにもファイルもある → 整合 |
| DBにINSERT成功 → COMMIT → ファイル書き込み直前にクラッシュ | DBにレコードがあるがファイルがない → 不整合 |
| 削除時：DB削除成功 → ファイル削除失敗 | DBにないがファイルだけ残る（孤立ファイル）→ 不整合 |

本チュートリアルでは、以下の方針で不整合をできるだけ減らします。

* **作成時** — DBにINSERTしてCOMMIT **した後**にファイルを書き込む。ファイル書き込みが失敗したら、DBレコードを削除して補償する
* **削除時** — DBレコードを先に削除し、ファイル削除の失敗はログに記録。孤立ファイルは後続のクリーンアップや手動で対応
* **クリーンアップ時** — ファイル削除後にDBレコードを削除。DB削除前にクラッシュすると孤立ファイルが残る可能性がある
* **閲覧時** — ファイルが存在しない場合は404を返す。DBレコードがあっても正常動作を維持

この制約は「ファイルとDBを分離する」アーキテクチャの本質的な制約です。完全な整合性が必要な場合は、本文もSQLiteに保存するか、より高度な分散トランザクション機構を検討してください。

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
* **閲覧数カウント** — `/paste/`、`/raw/`、`/api/pastes/` のすべてのアクセスで自動的にカウント（仕様として統一）。ただし `HEAD` リクエストでは加算しない
* **削除機能** — 削除トークンを使ったPaste削除
* **作成日時の記録** — UTCで統一管理
* **API** — HTTPヘッダー認証付きのREST風API（レートリミットは別途検討が必要）。APIルートは常にJSONを返す
* **定期クリーンアップ** — 期限切れPasteの削除スクリプト

---

## 3. ディレクトリ構成

```text
pastebin/
├── app.py              ← Flaskアプリケーション本体
├── cleanup.py          ← 期限切れPasteの削除スクリプト
├── migrate.py          ← ファイルベース版からの移行スクリプト
├── schema.sql          ← SQLiteのテーブル定義
├── requirements.txt    ← 必要なパッケージ
├── pastes.db           ← SQLiteデータベースファイル
├── pastes/             ← Paste本文の保存先
│   └── Ab3xK9Lm2Q
├── templates/
│   ├── index.html      ← 投稿フォーム
│   ├── view.html       ← Paste表示
│   ├── 400.html        ← Bad Request
│   ├── 401.html        ← Unauthorized
│   ├── 403.html        ← Forbidden
│   ├── 404.html        ← Not Found
│   └── 413.html        ← Payload Too Large
└── static/
    └── style.css
```

### 追加されたファイル

| ファイル | 役割 |
|----------|------|
| `cleanup.py` | 期限切れPasteをDBとファイルから削除する独立スクリプト |
| `migrate.py` | ファイルベース版からSQLite版への移行スクリプト |
| `schema.sql` | データベースのテーブル構造を定義 |
| `pastes.db` | SQLiteデータベース（自動作成） |
| `templates/view.html` | Paste表示専用テンプレート（index.htmlから分離） |
| `templates/400.html` | 不正なリクエスト時のエラーページ |
| `templates/401.html` | 未認証時のエラーページ |
| `templates/403.html` | 権限不足時のエラーページ |

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

SHA-256でハッシュ化して保存することで、たとえデータベースが漏洩しても、元のトークンを直接知ることは困難になります。ただし、SHA-256そののが安全なのではなく、`secrets.token_urlsafe(16)` で生成された十分にランダムなトークンに対しては、総当たりによる逆算が現実的ではない、という点が重要です。もしトークンが短かったり、予測可能なパターン（連番など）だったりすると、SHA-256でも総当たりで元のトークンを見つけ出すことが可能です。十分なエントロピー（ランダム性）を持つトークンを使うことが前提となります。

検証時には「受け取ったトークンをハッシュ化して、保存されたハッシュと比較」します。

#### インデックスの意味

```sql
CREATE INDEX IF NOT EXISTS idx_expires_at ON pastes(expires_at);
```

`expires_at` カラムにインデックスを作成します。クリーンアップ時に「有効期限が現在時刻より古いレコード」を検索するため、このカラムへのインデックスがないと、Paste数が増えるにつれて検索が遅くなります。

### 5.2 データベースの初期化

```python
def init_db():
    """Initialize the database if it does not exist."""
    conn = sqlite3.connect(DATABASE_PATH)
    schema_path = os.path.join(BASE_DIR, "schema.sql")
    if os.path.exists(schema_path):
        with open(schema_path, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
    conn.close()


# Initialize DB on import so it works with gunicorn too.
init_db()
```

`executescript()` は複数のSQL文を一度に実行できます。`schema.sql` の `IF NOT EXISTS` により、何度実行しても既存のテーブルやインデックスは上書きされません。

#### なぜ import 時に初期化するのか

`if __name__ == "__main__":` の中で `init_db()` を呼ぶと、`python app.py` で起動した場合のみ初期化されます。Gunicorn等のWSGIサーバーで起動した場合、`__main__` ブロックは実行されないため、データベースが未初期化のままリクエストを受け付け、「no such table」エラーが発生します。

モジュールのインポート時に `init_db()` を呼ぶことで、どの起動方法でも確実にデータベースが初期化されます。

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
    jsonify,
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
# Allow ~3x for URL-encoded form overhead; actual content is checked separately.
app.config["MAX_CONTENT_LENGTH"] = MAX_PASTE_BYTES * 3 + 16 * 1024

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
        # isolation_level=None: manual transaction management.
        # This avoids conflict between explicit BEGIN and Python sqlite3's
        # implicit transaction handling.
        conn = sqlite3.connect(DATABASE_PATH, timeout=10.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrent read/write performance
        conn.execute("PRAGMA journal_mode=WAL").fetchone()
        conn.execute("PRAGMA busy_timeout=5000")
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Initialize the database if it does not exist."""
    conn = sqlite3.connect(DATABASE_PATH)
    schema_path = os.path.join(BASE_DIR, "schema.sql")
    if os.path.exists(schema_path):
        with open(schema_path, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
    conn.close()


# Initialize DB on import so it works with gunicorn too.
init_db()


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

def get_paste_from_db(paste_id):
    db = get_db()
    row = db.execute(
        "SELECT * FROM pastes WHERE paste_id = ?",
        (paste_id,),
    ).fetchone()
    return row


def increment_view_count(paste_id):
    """
    Increment view count and return the updated value.
    Uses RETURNING clause to get the new value atomically.
    Skips increment for HEAD requests.
    Returns None if the paste no longer exists (deleted by another request).
    """
    if request.method == "HEAD":
        row = get_paste_from_db(paste_id)
        return row["view_count"] if row else None

    db = get_db()
    row = db.execute(
        "UPDATE pastes SET view_count = view_count + 1 "
        "WHERE paste_id = ? RETURNING view_count",
        (paste_id,),
    ).fetchone()
    db.commit()
    return row["view_count"] if row else None


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
    with open(file_path, "x", encoding="utf-8", newline="") as f:
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
        return True
    except OSError:
        return False


# ============================================================
# Paste creation with compensation on failure
# ============================================================

def normalize_newlines(text):
    """Normalize CRLF to LF before saving."""
    return text.replace("\r\n", "\n")


def create_paste(content, language, expires_at=None):
    """
    Create a paste with DB record and file.

    Order: BEGIN -> INSERT -> COMMIT -> write file
    If file write fails, compensate by deleting the DB record.

    This minimizes the window where DB has a record but file does not.
    The remaining risk is a crash between COMMIT and file write,
    which leaves a DB record without a file. This is handled by
    returning 404 when the file is missing on read.
    """
    content = normalize_newlines(content)

    for _ in range(20):
        paste_id = shortuuid.random(length=10)
        if not is_valid_paste_id(paste_id):
            continue

        delete_token = generate_delete_token()
        delete_token_hash = hash_delete_token(delete_token)

        db = get_db()
        try:
            db.execute("BEGIN IMMEDIATE")

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

            db.commit()

            # Write file AFTER commit to minimize inconsistent window
            try:
                write_paste_file(paste_id, content)
            except OSError:
                # Compensate: delete DB record since file write failed
                try:
                    db.execute("DELETE FROM pastes WHERE paste_id = ?", (paste_id,))
                    db.commit()
                except Exception:
                    logging.exception("Failed to compensate DB deletion for paste %s", paste_id)
                raise

            return paste_id, delete_token

        except Exception:
            db.rollback()
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
# Error response helpers
# ============================================================

def wants_json():
    """Check if the client expects JSON response."""
    accept = request.headers.get("Accept", "")
    return request.is_json or accept.startswith("application/json")


def api_error(message, status_code):
    """Always return JSON for API routes."""
    return jsonify({"error": message}), status_code


def web_error(message, status_code):
    """Return HTML error response for browser routes."""
    if status_code == 404:
        return render_template("404.html", message=message), status_code
    if status_code == 413:
        return render_template("413.html", max_bytes=MAX_PASTE_BYTES), status_code
    if status_code == 400:
        return render_template("400.html", message=message or "Bad request."), status_code
    if status_code == 401:
        return render_template("401.html", message=message or "Unauthorized."), status_code
    if status_code == 403:
        return render_template("403.html", message=message or "Forbidden."), status_code
    return render_template("404.html", message=message), status_code


def error_response(message, status_code):
    """Return appropriate error format based on route."""
    # API routes always return JSON
    if request.path.startswith("/api/"):
        return api_error(message, status_code)
    # Browser routes return HTML
    return web_error(message, status_code)


# ============================================================
# Input validation helpers
# ============================================================

def validate_paste_content(content):
    """Validate paste content. Returns (is_valid, error_message)."""
    if not isinstance(content, str):
        return False, "Content must be a string."
    if not content:
        return False, "Paste content is required."
    try:
        content_bytes = content.encode("utf-8")
    except UnicodeEncodeError:
        return False, "Content contains invalid Unicode characters."
    if len(content_bytes) > MAX_PASTE_BYTES:
        return False, "Paste too large."
    return True, None


def validate_expires_minutes(expires_minutes):
    """Validate expiration minutes. Returns (is_valid, expires_at, error_message)."""
    if expires_minutes is None or expires_minutes == "":
        return True, None, None
    # Reject booleans and floats explicitly
    if isinstance(expires_minutes, bool):
        return False, None, "Expiration must be an integer."
    if isinstance(expires_minutes, float):
        return False, None, "Expiration must be an integer."
    try:
        minutes = int(expires_minutes)
        if minutes <= 0:
            return False, None, "Expiration must be a positive integer."
        if minutes > 525600 * 10:  # Max 10 years
            return False, None, "Expiration too far in the future."
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
        return True, expires_at, None
    except (ValueError, TypeError):
        return False, None, "Expiration must be a valid integer."


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

        is_valid, error_msg = validate_paste_content(content)
        if not is_valid:
            if "too large" in error_msg:
                abort(413)
            flash(error_msg, "error")
            return render_template(
                "index.html",
                csrf_token=get_csrf_token(),
                language_options=LANGUAGE_OPTIONS,
            ), 400

        expires_minutes = request.form.get("expires_minutes", "")
        is_valid, expires_at, error_msg = validate_expires_minutes(expires_minutes)
        if not is_valid:
            flash(error_msg, "error")
            return render_template(
                "index.html",
                csrf_token=get_csrf_token(),
                language_options=LANGUAGE_OPTIONS,
            ), 400

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

        # Store delete token temporarily in session with a paste-specific key.
        # NOTE: Flask sessions are signed but NOT encrypted. The token is
        # stored in the client cookie in plaintext (base64-encoded).
        # This is acceptable only because:
        # 1. The token is only stored briefly (removed on first view)
        # 2. HTTPS prevents network interception
        # 3. HttpOnly prevents JavaScript access
        # For higher security, store tokens server-side (e.g., Redis, DB).
        session[f"_delete_token_{paste_id}"] = delete_token

        return redirect(url_for("view_paste", paste_id=paste_id))

    return render_template(
        "index.html",
        csrf_token=get_csrf_token(),
        language_options=LANGUAGE_OPTIONS,
    )


@app.route("/paste/<paste_id>")
def view_paste(paste_id):
    if not is_valid_paste_id(paste_id):
        return error_response("Paste not found.", 404)

    row = get_paste_from_db(paste_id)
    if not row:
        return error_response("Paste not found.", 404)

    if is_expired(row["expires_at"]):
        return error_response("Paste not found.", 404)

    # Atomically increment and get the updated view count
    view_count = increment_view_count(paste_id)
    if view_count is None:
        return error_response("Paste not found.", 404)

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

    # Retrieve and remove the delete token from session if present
    delete_token = session.pop(f"_delete_token_{paste_id}", None)

    return render_template(
        "view.html",
        paste_id=paste_id,
        paste_language=language,
        paste_content=highlighted,
        highlight_css=highlight_css,
        view_count=view_count,
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        csrf_token=get_csrf_token(),
        delete_token=delete_token,
    )


@app.route("/raw/<paste_id>")
def raw_paste(paste_id):
    if not is_valid_paste_id(paste_id):
        return error_response("Paste not found.", 404)

    row = get_paste_from_db(paste_id)
    if not row:
        return error_response("Paste not found.", 404)

    view_count = increment_view_count(paste_id)
    if view_count is None:
        return error_response("Paste not found.", 404)

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
        return error_response("Paste not found.", 404)

    csrf_token = request.form.get("csrf_token", "")
    if not verify_csrf_token(csrf_token):
        abort(400)

    row = get_paste_from_db(paste_id)
    if not row:
        return error_response("Paste not found.", 404)

    token = request.form.get("delete_token", "")
    if not verify_delete_token(token, row["delete_token_hash"]):
        flash("Invalid delete token.", "error")
        return redirect(url_for("view_paste", paste_id=paste_id))

    # Delete DB record first, then file.
    # If file deletion fails, the DB is consistent and the orphan file
    # can be cleaned up later.
    delete_paste_from_db(paste_id)
    file_removed = remove_paste_file(paste_id)

    if not file_removed:
        logging.warning("Failed to remove paste file during deletion: %s", paste_id)

    logging.info("Deleted paste: %s", paste_id)

    flash("Paste deleted.", "info")
    return redirect(url_for("index"))


# ============================================================
# API Routes
# ============================================================

@app.route("/api/pastes", methods=["POST"])
def api_create_paste():
    if not verify_api_key():
        return api_error("Unauthorized.", 401)

    data = request.get_json(silent=True)
    if data is None:
        return api_error("Invalid JSON body.", 400)
    if not isinstance(data, dict):
        return api_error("Request body must be a JSON object.", 400)

    # Validate content field exists and is correct type
    if "content" not in data:
        return api_error("Paste content is required.", 400)
    content = data["content"]
    if not isinstance(content, str):
        return api_error("Content must be a string.", 400)

    language = sanitize_language(data.get("language", "text"))

    # Validate content size
    is_valid, error_msg = validate_paste_content(content)
    if not is_valid:
        status = 413 if "too large" in error_msg else 400
        return api_error(error_msg, status)

    # Validate expiration
    expires_minutes = data.get("expires_minutes")
    is_valid, expires_at, error_msg = validate_expires_minutes(expires_minutes)
    if not is_valid:
        return api_error(error_msg, 400)

    try:
        paste_id, delete_token = create_paste(content, language, expires_at)
    except RuntimeError:
        logging.exception("Failed to create paste via API.")
        return api_error("Unable to create paste.", 500)
    except OSError:
        logging.exception("Failed to write paste via API.")
        return api_error("Unable to save paste.", 500)

    logging.info("Created paste via API: %s", paste_id)

    response_data = {
        "paste_id": paste_id,
        "url": url_for("view_paste", paste_id=paste_id, _external=True),
        "raw_url": url_for("raw_paste", paste_id=paste_id, _external=True),
        "delete_token": delete_token,
    }

    if expires_at:
        response_data["expires_at"] = expires_at

    return jsonify(response_data), 201


@app.route("/api/pastes/<paste_id>", methods=["GET"])
def api_get_paste(paste_id):
    if not is_valid_paste_id(paste_id):
        return api_error("Paste not found.", 404)

    row = get_paste_from_db(paste_id)
    if not row or is_expired(row["expires_at"]):
        return api_error("Paste not found.", 404)

    view_count = increment_view_count(paste_id)
    if view_count is None:
        return api_error("Paste not found.", 404)

    content = read_paste_file(paste_id)

    return jsonify({
        "paste_id": paste_id,
        "language": row["language"],
        "content": content,
        "view_count": view_count,
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
    }), 200


@app.route("/api/pastes/<paste_id>", methods=["DELETE"])
def api_delete_paste(paste_id):
    if not verify_api_key():
        return api_error("Unauthorized.", 401)

    if not is_valid_paste_id(paste_id):
        return api_error("Paste not found.", 404)

    row = get_paste_from_db(paste_id)
    if not row:
        return api_error("Paste not found.", 404)

    token = request.headers.get("X-Delete-Token", "")
    if not verify_delete_token(token, row["delete_token_hash"]):
        return api_error("Invalid or missing delete token.", 403)

    delete_paste_from_db(paste_id)
    file_removed = remove_paste_file(paste_id)

    if not file_removed:
        logging.warning("Failed to remove paste file during API deletion: %s", paste_id)

    logging.info("Deleted paste via API: %s", paste_id)
    return jsonify({"message": "Paste deleted."}), 200


# ============================================================
# Error handlers
# ============================================================

@app.errorhandler(400)
def bad_request(error):
    return error_response("Bad request.", 400)


@app.errorhandler(401)
def unauthorized(error):
    return error_response("Unauthorized.", 401)


@app.errorhandler(403)
def forbidden(error):
    return error_response("Forbidden.", 403)


@app.errorhandler(404)
def not_found(error):
    return error_response("Paste not found.", 404)


@app.errorhandler(413)
def request_too_large(error):
    return error_response("Payload too large.", 413)


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5000)
```

---

## 7. app.py の各部分の解説

### 7.1 データベース接続の管理

```python
def get_db():
    if "db" not in g:
        conn = sqlite3.connect(DATABASE_PATH, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        g.db = conn
    return g.db
```

Flaskの `g` オブジェクトは、**リクエスト単位**のグローバル名前空間です。同じリクエスト内で複数回 `get_db()` を呼んでも、新しい接続が作られるのは最初の1回だけです。

#### WALモードとbusy_timeout

```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=5000")
```

| PRAGMA | 効果 |
|--------|------|
| `journal_mode=WAL` | Write-Ahead Loggingを有効化。読み書きの並行性が向上 |
| `busy_timeout=5000` | ロック競合時に5秒待ってからエラーを返す |

SQLiteのデフォルトのジャーナルモード（`DELETE` または `TRUNCATE`）では、書き込み中は読み取りがブロックされます。WALモードでは、書き込み中でも読み取りが可能になり、複数ワーカー環境での性能が向上します。

`busy_timeout` は、別の接続が書き込みロックを持っている場合に、指定したミリ秒間待機してから `SQLITE_BUSY` エラーを返します。これにより、短時間のロック競合によるエラーを減らせます。

---

```python
@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()
```

リクエスト終了時にデータベース接続を自動的に閉じます。例外が発生しても確実に実行されます。

### 7.2 データベースの初期化

```python
def init_db():
    conn = sqlite3.connect(DATABASE_PATH)
    schema_path = os.path.join(BASE_DIR, "schema.sql")
    if os.path.exists(schema_path):
        with open(schema_path, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
    conn.close()


init_db()
```

モジュールのインポート時に `init_db()` を呼ぶことで、どの起動方法でも確実にデータベースが初期化されます。

#### なぜ import 時に初期化するのか

`if __name__ == "__main__":` の中で `init_db()` を呼ぶと、以下の問題が生じます。

| 起動方法 | `__main__` の実行 | 結果 |
|----------|-------------------|------|
| `python app.py` | 実行される | 初期化される |
| `gunicorn app:app` | 実行されない | 未初期化でエラー |
| `flask run` | 実行されない | 未初期化でエラー |

モジュールのインポート時に初期化することで、すべての起動方法で一貫した動作を保証します。

### 7.3 削除トークンの設計

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

#### SHA-256ハッシュ化の安全性について

SHA-256でハッシュ化すること自体が安全なのではなく、**`secrets.token_urlsafe(16)` で生成された十分にランダムなトークンに対しては、総当たりによる逆算が現実的ではない**、という点が重要です。

もしトークンが短かったり、予測可能なパターン（連番など）だったりするとSHA-256でも総当たりで元のトークンを見つけ出すことが可能です。十分なエントロピー（ランダム性）を持つトークンを使うことが前提となります。

### 7.4 UTC日時の統一管理

```python
def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()
```

`timezone.utc` を明示することで、タイムゾーン付きの日時（例：`2024-01-15T08:30:00+00:00`）を生成します。

#### なぜUTCを使うのか

* サーバーが異なるタイムゾーンに移動しても日時が変わらない
* 夏時間（DST）の有無に関係なく一貫した動作
* クライアントのタイムゾーンと独立して比較できる

```python
# NG: タイムゾーンなし（ローカル時刻。サーバー設定に依存）
datetime.now()  # 2024-01-15 17:30:00（JSTなら日本時間）

# OK: UTC明示
datetime.now(timezone.utc).isoformat()  # 2024-01-15T08:30:00+00:00
```

### 7.5 閲覧数の原子性

```python
def increment_view_count(paste_id):
    if request.method == "HEAD":
        row = get_paste_from_db(paste_id)
        return row["view_count"] if row else 0

    db = get_db()
    row = db.execute(
        "UPDATE pastes SET view_count = view_count + 1 WHERE paste_id = ? RETURNING view_count",
        (paste_id,),
    ).fetchone()
    db.commit()
    return row["view_count"] if row else 0
```

このアプリケーションでは、以下のすべてのエンドポイントで閲覧時に `increment_view_count()` が呼ばれます。

| エンドポイント | 用途 |
|---------------|------|
| `GET /paste/<paste_id>` | HTML表示（シンタックスハイライト付き） |
| `GET /raw/<paste_id>` | 純粋なテキスト表示 |
| `GET /api/pastes/<paste_id>` | APIによるJSON取得 |

これは意図的な仕様です。いずれの方法でPasteにアクセスしても、閲覧としてカウントされます。

`UPDATE pastes SET view_count = view_count + 1` は、データベース側で現在値に1を加算する方式です。Python側で現在値を読み込んで `+1` して書き戻す方式と比べて、同時アクセス時の競合に対してより安全です

さらに `RETURNING view_count` 句を使うことで、UPDATEと同じトランザクション内で更新後の値を取得します。これにより、同時アクセス時でも正確な更新後の値を返せます。

#### HEADリクエストの扱い

`HEAD` リクエストは、リンクプレビューやbotによる自動アクセスで使用されることがあります。これらを閲覧としてカウントすると、実際の閲覧数より多くなってしまう可能性があります。そのため、`request.method == "HEAD"` の場合は加算をスキップし、現在の値をそのまま返します。

#### RETURNING句について

`RETURNING` はSQLite 3.35.0（2021年3月リリース）以降でサポートされています。現代のPython環境では問題なく動作しますが、古い環境では以下の代替実装が必要です。

```python
# 古いSQLiteでの代替実装
def increment_view_count_fallback(paste_id):
    db = get_db()
    db.execute("UPDATE pastes SET view_count = view_count + 1 WHERE paste_id = ?", (paste_id,))
    db.commit()
    row = db.execute("SELECT view_count FROM pastes WHERE paste_id = ?", (paste_id,)).fetchone()
    return row["view_count"] if row else 0
```

### 7.6 改行コードの正規化

```python
def normalize_newlines(text):
    return text.replace("\r\n", "\n")
```

ブラウザの `textarea` は、Windows環境では `CRLF`（`\r\n`）で改行を送信することがあります。これをそのまま保存すると、`/raw` で `\r\n` がそのまま出力され、想定と異なる表示になる可能性があります。

保存前に `CRLF` を `LF` に正規化することで、改行コードを一貫した形式で保存します。

### 7.7 Paste作成時の補償処理

```python
def create_paste(content, language, expires_at=None):
    content = normalize_newlines(content)

    for _ in range(20):
        paste_id = shortuuid.random(length=10)
        ...
        db = get_db()
        try:
            db.execute("BEGIN IMMEDIATE")
            ...
            db.execute("INSERT INTO pastes ...")
            db.commit()

            # Write file AFTER commit to minimize inconsistent window
            try:
                write_paste_file(paste_id, content)
            except OSError:
                # Compensate: delete DB record since file write failed
                try:
                    db.execute("DELETE FROM pastes WHERE paste_id = ?", (paste_id,))
                    db.commit()
                except Exception:
                    logging.exception("Failed to compensate DB deletion for paste %s", paste_id)
                raise

            return paste_id, delete_token
```

#### なぜCOMMITの後にファイル書き込みを行うのか

作成時の順序として「DBのCOMMIT → ファイル書き込み」を採用しています。これにより、不整合の発生する時間的な窓を最小限に抑えます。

もし逆の順序（ファイル書き込み → DBのCOMMIT）にすると、ファイルは存在するがDBにレコードがない状態が長く続き、外部からファイルが見えてしまう可能性があります。

「DBのCOMMIT → ファイル書き込み」の順序では、DBにレコードがあるがファイルがない状態は一瞬だけです。ファイル書き込みが失敗した場合は、DBレコードを削除して補償します。

#### 残るリスク

ただし、この方式でも以下のリスクは残ります。

* COMMIT直後、ファイル書き込みの前にプロセスがクラッシュ → DBにレコードがあるがファイルがない
* 補償のDELETE実行中にクラッシュ → DBにレコードがあるまま

これらは「DBとファイルを分離する」アーキテクチャでは避けられません。閲覧時にファイルが存在しない場合は404を返すことで、ユーザーへの影響は最小限に抑えます。

### 7.8 削除時の処理順序

```python
def delete_paste(paste_id):
    ...
    delete_paste_from_db(paste_id)
    file_removed = remove_paste_file(paste_id)

    if not file_removed:
        logging.warning("Failed to remove paste file during deletion: %s", paste_id)
```

削除時は**DBレコードを先に削除し、ファイル削除の失敗はログに記録**する方式を採用しています。

#### なぜDBを先に削除するのか

DBを先に削除することで、外部からの閲覧リクエストは即座に404を返します。ファイルが残っていても、DBにレコードがないため「存在しないPaste」として扱われます。

もしファイルを先に削除してDB削除が失敗すると、DBにレコードがあるがファイルがない状態になり、閲覧時に404が返される一方でDBにはゴミレコードが残ります。

どちらの順序でも不整合は生じますが、DBを先に削除する方が、外部から見た一貫性は高くなります。

### 7.9 入力検証

#### 本文の検証

```python
def validate_paste_content(content):
    if not isinstance(content, str):
        return False, "Content must be a string."
    if not content:
        return False, "Paste content is required."
    try:
        content_bytes = content.encode("utf-8")
    except UnicodeEncodeError:
        return False, "Content contains invalid Unicode characters."
    if len(content_bytes) > MAX_PASTE_BYTES:
        return False, "Paste too large."
    return True, None
```

| 検証項目 | チェック内容 |
|----------|-------------|
| contentの型 | `str` であること |
| contentの存在 | 空文字列でないこと |
| contentのエンコード | 孤立サロゲート等の無効なUnicodeを含まないこと |
| contentのサイズ | UTF-8エンコード後が512KB以下であること |

`try-except UnicodeEncodeError` で囲むことで、孤立サロゲート（例：`\uD800`）のような無効なUnicode文字列を検出できます。これらの文字はPythonの文字列としては存在できますが、UTF-8にエンコードできません。検証しないと、ファイル書き込み時に `UnicodeEncodeError` が発生し、500エラーになります。

#### 有効期限の検証

```python
def validate_expires_minutes(expires_minutes):
    if expires_minutes is None or expires_minutes == "":
        return True, None, None
    if isinstance(expires_minutes, bool):
        return False, None, "Expiration must be an integer."
    if isinstance(expires_minutes, float):
        return False, None, "Expiration must be an integer."
    try:
        minutes = int(expires_minutes)
        if minutes <= 0:
            return False, None, "Expiration must be a positive integer."
        if minutes > 525600 * 10:  # Max 10 years
            return False, None, "Expiration too far in the future."
        ...
```

| 入力 | 結果 | 理由 |
|------|------|------|
| `60` | 有効 | 正の整数 |
| `"60"` | 有効 | 整数に変換可能 |
| `True` | 無効 | `bool` は `int` のサブクラスだが意図しない動作 |
| `1.9` | 無効 | `float` は拒否 |
| `-10` | 無効 | 負の整数 |
| `999999999` | 無効 | 10年を超える |

Pythonでは `bool` は `int` のサブクラスです。`int(True)` は `1` になるため、`isinstance(True, int)` は `True` になります。これを防ぐため、明示的に `bool` を拒否しています。

### 7.10 エラー応答の切り替え

```python
def api_error(message, status_code):
    return jsonify({"error": message}), status_code


def web_error(message, status_code):
    if status_code == 404:
        return render_template("404.html", message=message), status_code
    if status_code == 400:
        return render_template("400.html", message=message), status_code
    ...


def error_response(message, status_code):
    if request.path.startswith("/api/"):
        return api_error(message, status_code)
    return web_error(message, status_code)
```

APIルート（`/api/` で始まるパス）は**常にJSON**を返します。ブラウザルートはHTMLテンプレートを返します。

#### なぜ `wants_json()` ではなくパスベースで判定するのか

curlのデフォルトでは `Accept: */*` が送信されます。これは `application/json` に前方一致しないため、`wants_json()` ベースの判定ではAPIエラーがHTMLで返ってしまいます。

パスベース（`request.path.startswith("/api/")`）の判定であれば、curlのデフォルト設定でも確実にJSONが返されます。

### 7.11 サイズ制限の設計

```python
MAX_PASTE_BYTES = 512 * 1024
# Allow ~3x for URL-encoded form overhead; actual content is checked separately.
app.config["MAX_CONTENT_LENGTH"] = MAX_PASTE_BYTES * 3 + 16 * 1024
```

#### なぜ `MAX_CONTENT_LENGTH` を広げるのか

Flaskの `MAX_CONTENT_LENGTH` はHTTPリクエスト全体のサイズを制限します。フォーム送信時、本文はURLエンコードされ、日本語の1文字は約9バイト（UTF-8の3バイトが `%XX%XX%XX` に変換）になります。

例えば、10万文字の「あ」（30万バイトのUTF-8）をフォーム送信すると、URLエンコード後は約90万バイトになります。`MAX_CONTENT_LENGTH` を512KB+16KBに設定すると、本文が実際には512KB以下でも413エラーになります。

そのため、`MAX_CONTENT_LENGTH` を本文上限の約3倍に広げ、**実際の本文サイズは `validate_paste_content()` で厳密にチェック**します。

| 制限 | 値 | 役割 |
|------|-----|------|
| `MAX_CONTENT_LENGTH` | 約1.5MB | HTTPリクエスト全体の上限（DoS対策） |
| `MAX_PASTE_BYTES` | 512KB | Paste本文の実際の上限 |

#### textarea の maxlength について

```html
<textarea maxlength="524288">
```

`maxlength` はHTMLレベルでの補助的な制限です。ブラウザの実装により、これは**UTF-16の文字数**をカウントします。日本語の1文字はUTF-16では1文字ですが、UTF-8では3バイトになります。したがって、`maxlength="524288"` は512KBのバイト数制限とは一致しません。

これはあくまでUX上の補助であり、サーバー側の `validate_paste_content()` が本質的な制限です。

### 7.12 セッションと削除トークンの受け渡し

```python
# 作成時
session[f"_delete_token_{paste_id}"] = delete_token

# 表示時
delete_token = session.pop(f"_delete_token_{paste_id}", None)
```

削除トークンは、作成直後にセッションに一時的に保存し、Paste表示ページで一度だけ取り出して表示します。`session.pop()` を使うことで、表示後にセッションから自動的に削除されます。

#### セキュリティ上の注意

Flaskのセッションは**署名はされるが暗号化はされません**。つまり、Cookieの内容は改ざんを検出できますが、中身を読むことは可能です。削除トークンはbase64エンコーディングされたCookieに平文で含まれます。

これは以下の理由で許容されます。

* トークンは一時的にしか保存されない（`pop()` で即削除）
* `HttpOnly` 属性によりJavaScriptからアクセス不可
* HTTPS環境ではネットワーク上で暗号化される

より高いセキュリティが必要な場合は、サーバー側（Redisや別テーブル）にトークンを保存してください。

#### 削除トークンの表示について

作成直後のリダイレクト先で削除トークンが一度だけ表示されますが、ユーザーがページを再読込すると `session.pop()` によりトークンは消えます。UI的には「このページを閉じるとトークンは再表示できません」という警告を表示するのが親切です。

```html
{% if delete_token %}
<div class="message info">
    <strong>Delete Token:</strong> <code>{{ delete_token }}</code>
    <p>⚠️ Save this token now. It will NOT be shown again after you leave this page.</p>
</div>
{% endif %}
```

---

## 8. クリーンアップスクリプト（cleanup.py）

```python
#!/usr/bin/env python3

import logging
import os
import sqlite3
from datetime import datetime, timezone

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
PASTE_DIR = os.path.join(BASE_DIR, "pastes")
DATABASE_PATH = os.path.join(BASE_DIR, "pastes.db")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def cleanup():
    """
    Delete expired pastes from both database and filesystem.

    Order for each expired paste:
        1. Delete the file (if it exists)
        2. Delete the DB record
        3. Commit

    If a file deletion fails, the DB record is still deleted.
    The orphan file will be detected and removed by orphan cleanup.

    If commit fails after file deletions, DB records remain but files
    may have been deleted. This leaves "DB record without file" inconsistency,
    which is handled by the read path returning 404.
    """
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")

    now = datetime.now(timezone.utc).isoformat()

    rows = conn.execute(
        "SELECT paste_id FROM pastes WHERE expires_at IS NOT NULL AND expires_at < ?",
        (now,),
    ).fetchall()

    deleted_count = 0
    failed_files = []

    for row in rows:
        paste_id = row["paste_id"]
        file_path = os.path.join(PASTE_DIR, paste_id)

        # 1. Delete file first
        if os.path.isfile(file_path):
            try:
                os.remove(file_path)
                logging.info("Removed expired paste file: %s", paste_id)
            except OSError as e:
                failed_files.append(paste_id)
                logging.warning("Failed to remove paste file %s: %s", paste_id, e)

        # 2. Delete DB record regardless of file deletion success
        conn.execute("DELETE FROM pastes WHERE paste_id = ?", (paste_id,))
        deleted_count += 1

    conn.commit()
    conn.close()

    logging.info(
        "Cleanup completed. Deleted %d expired pastes. File failures: %d",
        deleted_count,
        len(failed_files),
    )


def cleanup_orphan_files():
    """
    Remove files in pastes/ that have no corresponding DB record.
    This handles orphan files left by failed deletions or crashes.
    """
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")

    rows = conn.execute("SELECT paste_id FROM pastes").fetchall()
    valid_ids = {row["paste_id"] for row in rows}
    conn.close()

    removed = 0
    for filename in os.listdir(PASTE_DIR):
        file_path = os.path.join(PASTE_DIR, filename)
        if not os.path.isfile(file_path):
            continue
        if filename not in valid_ids:
            try:
                os.remove(file_path)
                removed += 1
                logging.info("Removed orphan file: %s", filename)
            except OSError as e:
                logging.warning("Failed to remove orphan file %s: %s", filename, e)

    logging.info("Orphan cleanup completed. Removed %d orphan files.", removed)


if __name__ == "__main__":
    cleanup()
    cleanup_orphan_files()
```

### 8.1 なぜ独立スクリプトにするのか

Flaskアプリケーション内にクリーンアップ処理を組み込む方法もあります（例：`threading.Timer` で定期実行）。しかし、以下の理由で独立スクリプトを推奨します。

| 方法 | 問題 |
|------|------|
| Flask内スレッド | 複数ワーカー（Gunicorn等）で重複実行される可能性がある |
| Flask内スレッド | アプリケーションコードと混在し、責務が不明確 |
| 独立スクリプト | cronやsystemd timerで管理でき、実行タイミングを外部制御できる |
| 独立スクリプト | テスト・手動実行が容易 |

### 8.2 クリーンアップ時の不整合について

クリーンアップスクリプトでは、以下の順序で処理を行います。

1. 期限切れのPasteをDBから検索
2. 各Pasteについて、ファイルを削除
3. DBからレコードを削除
4. `commit()`

ファイル削除とDB削除の間でエラーが発生した場合、以下の不整合が起こり得ます。

| 状況 | 結果 |
|------|------|
| ファイル削除成功 → DB削除成功 → commit成功 | 整合 |
| ファイル削除失敗 → DB削除成功 → commit成功 | DBにないがファイルが残る（孤立ファイル）→ 不整合 |
| ファイル削除成功 → DB削除成功 → commit失敗 | ファイルがないがDBレコードが残る → 不整合 |

これらの不整合は、DBとファイルを分離しているアーキテクチャでは避けられません。`cleanup_orphan_files()` 関を定期的に実行することで、孤立ファイルを検出・削除できます。

### 8.3 cleanup.py の busy_timeout

```python
conn = sqlite3.connect(DATABASE_PATH)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA busy_timeout=5000")
```

`cleanup.py` でも `busy_timeout=5000` を設定しています。Flaskアプリが書き込み中にクリーンアップが走ると、ロック競合が発生します。`busy_timeout` がないと、即座に `SQLITE_BUSY` エラーで失敗します。5秒の待機時間を設けることで、短時間のロック競合を回避できます。

`cleanup_orphan_files()` 側の接続にも同様に設定しています。

### 8.4 PRAGMA の結果フェッチについて

```python
conn.execute("PRAGMA journal_mode=WAL").fetchone()
```

`PRAGMA journal_mode=WAL` は結果行を返します。フェッチしなくても実害はほぼありませんが、cursorが開いたままになり、場合によっては `ProgrammingError` の原因になることがあります。`fetchone()` で結果を消費することで、cursorを確実に閉じます。

### 8.5 定期実行の設定

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

        {% if delete_token %}
        <div class="message info">
            <strong>Delete Token:</strong> <code>{{ delete_token }}</code>
            <p>⚠️ Save this token now. It will NOT be shown again after you leave this page.</p>
        </div>
        {% endif %}

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

### 9.3 400.html

```html
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pastebin — Bad Request</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
<div class="container">
    <h1><a href="{{ url_for('index') }}">Pastebin</a></h1>
    <section class="error-page">
        <h2>Bad Request</h2>
        <p>{{ message or "The request could not be understood." }}</p>
        <p><a href="{{ url_for('index') }}">Back to Pastebin</a></p>
    </section>
</div>
</body>
</html>
```

### 9.4 401.html

```html
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pastebin — Unauthorized</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
<div class="container">
    <h1><a href="{{ url_for('index') }}">Pastebin</a></h1>
    <section class="error-page">
        <h2>Unauthorized</h2>
        <p>{{ message or "Authentication is required." }}</p>
        <p><a href="{{ url_for('index') }}">Back to Pastebin</a></p>
    </section>
</div>
</body>
</html>
```

### 9.5 403.html

```html
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pastebin — Forbidden</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
<div class="container">
    <h1><a href="{{ url_for('index') }}">Pastebin</a></h1>
    <section class="error-page">
        <h2>Forbidden</h2>
        <p>{{ message or "You do not have permission to perform this action." }}</p>
        <p><a href="{{ url_for('index') }}">Back to Pastebin</a></p>
    </section>
</div>
</body>
</html>
```

### 9.6 404.html

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

### 9.7 413.html

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

### 11.2 アプリケーションの起動

```bash
python app.py
```

### 11.3 Gunicornでの起動

```bash
python -m pip install gunicorn
gunicorn -w 4 -b 127.0.0.1:8000 app:app
```

データベースはモジュールインポート時に初期化されるため、Gunicornでも問題なく動作します。

### 11.4 HTTPS環境

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

### 12.4 API認証について

APIの **作成（POST）** と **削除（DELETE）** には `X-API-Key` ヘッダーによる認証が必要です。**取得（GET）** は認証なしでアクセスできます。これは意図的な仕様です。Pasteの共有（閲覧）は認証なしで行えるように、管理操作（作成・削除）のみ認証を要求するためです。

#### 注意：API GET での閲覧数

API GET も閲覧数をインクリメントします。認証なしでアクセスできるため、第三者が繰り返しリクエストすることで閲覧数を水増しできる可能性があります。これはレートリミット未実装の現状では防ぎきれませんAPIルートへのレートリミット導入を検討してください。

---

## 13. セキュリティ対策のまとめ

### ファイルベース版から継承

| 脅威 | 対策 |
|------|------|
| パストラバーサル | Paste IDの正規表現検証 |
| CSRF攻撃 | CSRFトークンの生成と検証 |
| DoS（サイズ攻撃） | リクエストサイズ上限 |
| ファイル上書き | `"x"` モードの排他作成 |
| XSS | Pygmentsによる安全なHTML変換 |
| セッション窃取 | `HttpOnly`, `SameSite`, `Secure` Cookie属性 |
| 二重投稿 | PRGパターン |
| タイミング攻撃 | `secrets.compare_digest()` |

### SQLite版で追加

| 脅威 | 対策 |
|------|------|
| 削除トークンの漏洩 | SHA-256ハッシュ化で保存（十分なエントロピーのトークンが前提） |
| 不正なAPIアクセス | `X-API-Key` ヘッダー認証（作成・削除のみ） |
| 期限切れPasteの閲覧 | 閲覧時の有効期限チェック |
| DBとファイルの不整合 | 補償処理とログ記録で不整合を減らす |
| 情報漏洩 | エラー詳細隠蔽、一律404 |
| 同時アクセス時の閲覧数 | `RETURNING` 句による原子性の確保 |
| 無効なUnicode | `UnicodeEncodeError` の検証 |
| 改行コードの不整合 | 保存前の `CRLF` → `LF` 正規化 |
| SQLiteのロック競合 | WALモードと `busy_timeout` |

### 未対策の項目（別途検討が必要）

| 脅威 | 現状 | 対策案 |
|------|------|--------|
| APIの大量投稿 | レートリミットなし | Flask-Limiter等の導入 |
| DBとファイルの完全な整合性 | 分離アーキテクチャの限界 | 本文もDBに入れる、または2PC等 |
| セッションの平文トークン | 署名のみ、暗号化なし | サーバー側ストレージへの移行 |
| API GETでの閲覧数水増し | 認証なしでアクセス可能 | APIルートへのレートリミット導入 |

---

## 14. ファイルベース版からの移行

### 14.1 移行の考え方

ファイルベース版からSQLite版へ移行する場合、以下の変換が必要です。

* 旧ファイル形式（1行目に言語情報、その後に本文）から、言語情報をDBに移行
* 本文だけを新しいファイル形式で保存
* 作成日時はファイルのmtimeを参考にするが、正確な日時ではないことを理解する

### 14.2 移行スクリプト

```python
#!/usr/bin/env python3
"""
Migrate pastes from file-based format to SQLite-based format.

Old file format:
    Line 1: language name
    Line 2+: paste content

New file format:
    Paste content only (language is stored in DB)

This script is idempotent: running it multiple times is safe.
"""

import os
import sqlite3
from datetime import datetime, timezone

from pygments.lexers import get_all_lexers

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
PASTE_DIR = os.path.join(BASE_DIR, "pastes")
DB_PATH = os.path.join(BASE_DIR, "pastes.db")

# Rebuild allowed language set (same logic as app.py)
ALLOWED_LANGUAGES = set()
for _, aliases, _, _ in get_all_lexers():
    for alias in aliases:
        ALLOWED_LANGUAGES.add(alias)


def sanitize_language(language):
    if not isinstance(language, str):
        return "text"
    language = language.strip().lower()
    if language in ALLOWED_LANGUAGES:
        return language
    return "text"


def migrate():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")

    # Ensure table exists
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pastes (
            paste_id         TEXT PRIMARY KEY,
            language         TEXT NOT NULL DEFAULT 'text',
            created_at       TEXT NOT NULL,
            expires_at       TEXT,
            view_count       INTEGER NOT NULL DEFAULT 0,
            delete_token_hash TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_expires_at ON pastes(expires_at);
    """)

    for filename in os.listdir(PASTE_DIR):
        filepath = os.path.join(PASTE_DIR, filename)
        if not os.path.isfile(filepath):
            continue

        # Skip already-migrated pastes (already in DB)
        existing = conn.execute(
            "SELECT 1 FROM pastes WHERE paste_id = ?", (filename,)
        ).fetchone()
        if existing:
            print(f"Skipping already migrated: {filename}")
            continue

        # Capture mtime BEFORE any modification
        mtime = os.path.getmtime(filepath)
        created_at = datetime.fromtimestamp(
            mtime, tz=timezone.utc
        ).isoformat()

        # Read old format
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if not lines:
            continue

        # Validate language before inserting into DB
        language = sanitize_language(lines[0].strip())
        content = "".join(lines[1:])

        # Write new format atomically using temp file + replace
        temp_path = filepath + ".tmp"
        try:
            with open(temp_path, "w", encoding="utf-8", newline="") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, filepath)
        except OSError as e:
            print(f"Failed to rewrite {filename}: {e}")
            if os.path.exists(temp_path):
                os.remove(temp_path)
            continue

        # Insert into DB
        conn.execute(
            """
            INSERT INTO pastes (paste_id, language, created_at, expires_at, view_count, delete_token_hash)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (filename, language, created_at, None, 0, None),
        )
        print(f"Migrated: {filename} (language={language})")

    conn.commit()
    conn.close()
    print("Migration completed.")


if __name__ == "__main__":
    migrate()
```

### 14.3 移行スクリプトの設計上の注意点

#### べき等性（Idempotency）

移行スクリプトは何度実行しても安全です。DBに既に存在するPaste IDはスキップされます。

#### mtimeの取得順序

ファイルの `mtime` は**ファイル書き換えの前**に取得します。書き換え後に取得すると、移行実行時刻になってしまいます。

#### 言語の検証

```python
from pygments.lexers import get_all_lexers

ALLOWED_LANGUAGES = set()
for _, aliases, _, _ in get_all_lexers():
    for alias in aliases:
        ALLOWED_LANGUAGES.add(alias)


def sanitize_language(language):
    if not isinstance(language, str):
        return "text"
    language = language.strip().lower()
    if language in ALLOWED_LANGUAGES:
        return language
    return "text"
```

旧ファイルの1行目の言語名をそのままDBに挿入するのではなく、`sanitize_language()` で検証します。無効な言語名は `"text"` にフォールバックされます。これにより、DBに無効な言語名が残ることを防ぎます。

#### アトミックなファイル書き込み

一時ファイルに書き込んでから `os.replace()` で置き換えることで、書き込み途中のファイルが残るリスクを減らします。`os.replace()` はOSレベルでアトミック（不可分）に実行されます。

#### 作成日時の限界

`os.path.getmtime()` は正確な作成日時ではありません。ファイルのコピー操作等でも値が変わる可能性があります。正確な作成日時を記録するには、ファイルベース版の段階で作成日時を別途記録しておく必要があります。

---

## 15. Paste IDの空間

`shortuuid.random(length=10)` で生成されるIDの空間について説明します。

shortuuidはUUIDをBase57エンコーディングした文字列を生成します。使用される文字は以下の通りです。

```
23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz
```

（`0`, `O`, `1`, `l`, `I` を除外して読み間違いを防ぐ）

10文字の場合の組み合わせ数は以下の通りです。

```
57^10 ≈ 3.6 × 10^17
```

これは約360京（360 quadrillion）通りです。実用上、衝突の確率は無視できるレベルですが、理論的には可能性があるため、衝突時の再試行処理を入れています。

`shortuuid` は内部で `secrets.token_bytes()` を使用しており、暗号論的に安全な乱数源を使っています。

---

## 16. まとめ

このチュートリアルで、ファイルベースのPastebinをSQLiteで拡張し、より実用的な構成にしました。

### 追加された価値

| 機能 | ファイルベース版 | SQLite版 |
|------|----------------|----------|
| 有効期限 | 不可 | 可能 |
| 閲覧数 | 不可 | 自動カウント（全エンドポイントで統一、HEADは除外） |
| 削除機能 | 不可 | トークン認証付き |
| API | 不可 | REST風API（レートリミットは別途検討） |
| UTC日時管理 | 不可 | 統一 |
| 定期クリーンアップ | 不可 | 独立スクリプト |

### 構成の特徴

* **本文はファイル** — 大きなテキストを効率的に管理
* **メタデータはSQLite** — 構造化データを安全に管理
* **不整合を減らす設計** — 補償処理とログ記録でDBとファイルの不整合を最小化
* **UTC日時を統一** — タイムゾーンの混乱を排除
* **独立したクリーンアップ** — 運用時の柔軟性を確保
* **Gunicorn対応** — インポート時のDB初期化
* **APIは常にJSON** — パスベースの判定で確実なJSON応答

### この構成の限界

DBとファイルを分離しているため、**完全な原子性は保証できません**。これはアーキテクチャの本質的な制約です。以下の不整合が理論上は起こり得ます。

* DBにレコードがあるがファイルがない（作成時のクラッシュ）
* ファイルがあるがDBにレコードがない（削除時の失敗）

これらの不整合は、閲覧時の404応答やクリーンアップスクリプトで緩和されますが、完全には除去できません。完全な整合性が必要な場合は、本文もSQLiteに保存するか、より高度な分散トランザクション機構を検討してください。

この構成は、小〜中規模のPastebinサービスとして十分実用的です。さらに大規模化する場合は、PostgreSQL等の本格的なRDBMSや、オブジェクトストレージの検討が必要になりますが、その判断基準もこのチュートリアルで示した設計思想を参考にできます。
