# Python + Flaskで作るシンプルなPastebin

このチュートリアルでは、PythonとFlaskを使って、テキストを保存・共有できるシンプルなPastebinを作ります。

Pastebinとは、テキストやコードを一時的に保存し、URLで共有できるWebサービスです。GitHub GistやPastebin.comのようなものです。

このチュートリアルの特徴は、**データベースを使わず**、ファイルシステムだけで動作させることです。小さな規模ならデータベースなしでも十分動作し、構成がシンプルになるため、Flaskの学習にも適しています。

---

## 1. 完成する機能

このPastebinで実装する機能は以下の通りです。

### 基本機能

* **テキストの投稿** — フォームからテキストを送信して保存
* **言語の指定** — Python、JavaScriptなどの言語を選択
* **一意なPaste IDの自動生成** — 短いランダムな文字列でPasteを識別
* **Paste IDによる閲覧** — `/paste/Ab3xK9Lm2Q` のようなURLで閲覧
* **シンタックスハイライト** — Pygmentsでコードに色付けして表示
* **Rawテキストの表示** — 色付けなしの純粋なテキストを表示

### セキュリティ機能

* **CSRF対策** — 別サイトからの悪意あるPOSTを防ぐ
* **投稿サイズ制限** — 巨大なデータの投稿を防ぐ（512KB上限）
* **パストラバーサル対策** — `../../etc/passwd` のような攻撃を防ぐ
* **ファイル上書き防止** — 既存のPasteを誤って上書きしない
* **404 / 413エラーページ** — 適切なエラーを返す
* **PRG（Post/Redirect/Get）** — 二重投稿を防ぐ
* **UTF-8対応** — 日本語などのマルチバイト文字を正しく扱う
* **Flaskセッションを利用したCSRFトークン** — セッションと連携したトークン
* **Pygmentsによるコードハイライト** — 安全なHTML変換

### なぜこれらの機能が必要か

Webアプリケーションを作るとき、単に「動けばよい」わけではありません。以下のような問題が実際に起こり得ます。

* 悪意あるサイトから勝手にフォーム送信される（CSRF攻撃）
* `../../../etc/passwd` のような入力でサーバーのファイルを読まれる（パストラバーサル）
* 巨大なファイル送信でサーバーのディスクやメモリを圧迫する（DoS攻撃）
* 日本語を投稿すると文字化けする（文字コード問題）
* ブラウザ更新で同じ投稿が何度も送信される（二重投稿）

このチュートリアルでは、これらの問題を一つずつ対処しながらアプリケーションを構築します。

---

## 2. ディレクトリ構成

最終的な構成は次のようになります。

```text
pastebin/
├── app.py              ← Flaskアプリケーションの本体
├── requirements.txt    ← 必要なパッケージ一覧
├── pastes/             ← 投稿されたテキストの保存先
│   └── Ab3xK9Lm2Q    ← Paste IDがファイル名になる
├── templates/          ← HTMLテンプレート
│   ├── index.html      ← 投稿フォームと表示画面（兼用）
│   ├── 404.html        ← 見つからない場合のエラーページ
│   └── 413.html        ← サイズ超過時のエラーページ
└── static/
    └── style.css       ← 画面のデザイン
```

### 各ファイルの役割

| ファイル | 役割 |
|----------|------|
| `app.py` | Flaskのルーティング、フォーム処理、セキュリティ対策をすべて担当 |
| `requirements.txt` | 必要なPythonパッケージを列挙 |
| `pastes/` | 実際のPaste本文をテキストファイルとして保存 |
| `templates/index.html` | 投稿フォームとPaste表示の両方を担当 |
| `templates/404.html` | Pasteが見つからない場合の画面 |
| `templates/413.html` | 投稿サイズが大きすぎる場合の画面 |
| `static/style.css` | 画面の見た目を整える |

### なぜデータベースを使わないのか

この構成では、Paste IDそのものをファイル名として使用します。例えば、Paste IDが `Ab3xK9Lm2Q` なら、ファイルパスは `pastes/Ab3xK9Lm2Q` になります。

つまり、Pasteを読み込むときに「データベースでIDを検索してファイルパスを取得する」という手間が不要です。URLのIDをそのままファイル名に使えるため、データベースがなくても動作します。

この方式のメリットは以下の通りです。

* 構成がシンプル（データベースのセットアップが不要）
* バックアップが容易（`pastes/` ディレクトリをコピーするだけ）
* 小規模な用途であれば十分実用的

一方、以下のような機能が必要になったらデータベースを検討すべきです。

* 有効期限の管理
* 閲覧数のカウント
* ユーザーごとの管理
* 検索機能
* 一覧表示

このチュートリアルではあえてデータベースを使わず、「最小構成でどこまで実用的にできるか」を示します。

---

## 3. 必要なパッケージ

### requirements.txt

```text
Flask
Pygments
shortuuid
```

### 各パッケージの役割

| パッケージ | 役割 |
|------------|------|
| **Flask** | PythonのWebアプリケーションフレームワーク。ルーティング、テンプレート、セッションなどを提供 |
| **Pygments** | プログラミング言語のシンタックスハイライト（コードに色付け）を行うライブラリ |
| **shortuuid** | 短く読みやすいUUIDを生成するライブラリ。Paste IDとして使用 |

### インストール方法

```bash
python -m pip install -r requirements.txt
```

または、直接インストールする場合は以下のようにします。

```bash
python -m pip install Flask Pygments shortuuid
```

### 仮想環境を使う場合

複数のPythonプロジェクトを管理する場合は、仮想環境の使用を推奨します。

```bash
# 仮想環境を作成
python -m venv venv

# Linux/macOSの場合
source venv/bin/activate

# Windowsの場合
venv\Scripts\activate

# パッケージをインストール
python -m pip install -r requirements.txt
```

---

## 4. Flaskアプリケーション（app.py）

`app.py` はこのアプリケーションの中核です。以下に全文を示し、その後で各部分を詳しく解説します。

```python
#!/usr/bin/env python3

import logging
import os
import re
import secrets

import shortuuid
from flask import (
    Flask,
    abort,
    flash,
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

# HTTPリクエスト全体のサイズ制限。
# Paste本文以外のフォームデータ等を考慮して少し余裕を持たせる。
# HTMLフォームのPOST送信では日本語などのマルチバイト文字がURLエンコードされ、
# UTF-8の3バイト文字が "%XX%XX%XX" の9バイトに膨らむため、
# 本文上限の約3倍の余裕を持たせる。実際の本文サイズはアプリケーション側で厳密にチェックする。
app.config["MAX_CONTENT_LENGTH"] = MAX_PASTE_BYTES * 3 + 16 * 1024

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# HTTPS環境ではTrueにする。
app.config["SESSION_COOKIE_SECURE"] = (
    os.environ.get("FLASK_HTTPS", "").lower() == "true"
)

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
# Paste ID validation
# ============================================================

VALID_PASTE_ID = re.compile(
    r"^[a-zA-Z0-9_-]{1,64}$"
)


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

    return secrets.compare_digest(
        token.encode("utf-8"),
        expected.encode("utf-8"),
    )


# ============================================================
# Paste ID generation
# ============================================================

def create_paste():
    """
    一意なPaste IDを生成し、
    排他的にファイルを作成する。

    戻り値:
        (paste_id, file_path, file_object)
    """

    for _ in range(20):
        paste_id = shortuuid.random(length=10)

        if not is_valid_paste_id(paste_id):
            continue

        file_path = os.path.join(
            PASTE_DIR,
            paste_id,
        )

        try:
            file_object = open(
                file_path,
                "x",
                encoding="utf-8",
                newline="\n",
            )

            return paste_id, file_path, file_object

        except FileExistsError:
            continue

    raise RuntimeError(
        "Unable to generate a unique paste ID."
    )


# ============================================================
# Read paste
# ============================================================

def get_paste_file_path(paste_id):
    if not is_valid_paste_id(paste_id):
        abort(404)

    file_path = os.path.join(
        PASTE_DIR,
        paste_id,
    )

    if not os.path.isfile(file_path):
        abort(404)

    return file_path


def read_paste(paste_id):
    file_path = get_paste_file_path(paste_id)

    try:
        with open(
            file_path,
            "r",
            encoding="utf-8",
            newline="\n",
        ) as f:
            language = f.readline().rstrip("\n")
            content = f.read()

    except (OSError, UnicodeError):
        abort(404)

    return language, content


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
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        language = sanitize_language(
            request.form.get("language", "text")
        )

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
            paste_id, file_path, file_object = create_paste()

            try:
                file_object.write(
                    language + "\n"
                )
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
                try:
                    file_object.close()
                except Exception:
                    pass

        except RuntimeError:
            logging.exception(
                "Failed to create paste."
            )

            flash(
                "Unable to create paste.",
                "error",
            )

            return render_template(
                "index.html",
                csrf_token=get_csrf_token(),
                language_options=LANGUAGE_OPTIONS,
            ), 500

        except OSError:
            logging.exception(
                "Failed to write paste."
            )

            flash(
                "Unable to save paste.",
                "error",
            )

            return render_template(
                "index.html",
                csrf_token=get_csrf_token(),
                language_options=LANGUAGE_OPTIONS,
            ), 500

        logging.info(
            "Created paste: %s",
            paste_id,
        )

        return redirect(
            url_for(
                "view_paste",
                paste_id=paste_id,
            )
        )

    return render_template(
        "index.html",
        csrf_token=get_csrf_token(),
        language_options=LANGUAGE_OPTIONS,
    )


@app.route("/paste/<paste_id>")
def view_paste(paste_id):
    language, content = read_paste(
        paste_id
    )

    language = sanitize_language(
        language
    )

    try:
        lexer = get_lexer_by_name(
            language
        )

        highlighted = highlight(
            content,
            lexer,
            HtmlFormatter(
                linenos=True,
                cssclass="highlight",
            ),
        )

        highlight_css = HtmlFormatter(
            linenos=True,
            cssclass="highlight",
        ).get_style_defs(".highlight")

    except ClassNotFound:
        highlighted = highlight(
            content,
            get_lexer_by_name("text"),
            HtmlFormatter(
                linenos=True,
                cssclass="highlight",
            ),
        )

        highlight_css = HtmlFormatter(
            linenos=True,
            cssclass="highlight",
        ).get_style_defs(".highlight")

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
    _, content = read_paste(
        paste_id
    )

    response = app.response_class(
        content,
        status=200,
        mimetype="text/plain",
    )

    response.headers["X-Content-Type-Options"] = "nosniff"

    return response


# ============================================================
# Error handlers
# ============================================================

@app.errorhandler(400)
def bad_request(error):
    return render_template(
        "404.html",
        message="Bad request.",
    ), 400


@app.errorhandler(404)
def not_found(error):
    return render_template(
        "404.html",
        message="Paste not found.",
    ), 404


@app.errorhandler(413)
def request_too_large(error):
    return render_template(
        "413.html",
        max_bytes=MAX_PASTE_BYTES,
    ), 413


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    app.run(
        debug=False,
        host="127.0.0.1",
        port=5000,
    )
```

---

## 5. app.py の各部分の解説

### 5.1 インポート

```python
import logging
import os
import re
import secrets

import shortuuid
from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import ClassNotFound, get_all_lexers, get_lexer_by_name
```

| モジュール | 用途 |
|------------|------|
| `logging` | アプリケーションの動作記録（ログ）を出力 |
| `os` | ファイルパスの操作、環境変数の取得 |
| `re` | 正規表現（Paste IDの検証に使用） |
| `secrets` | 暗号学的に安全な乱数の生成（CSRFトークンに使用） |
| `shortuuid` | 短いランダムなIDの生成 |
| `Flask` | Webフレームワーク本体 |
| `abort` | エラーレスポンスを即座に返す |
| `flash` | 次のリクエストで表示するメッセージを設定 |
| `redirect` | 別URLへリダイレクト |
| `render_template` | HTMLテンプレートをレンダリング |
| `request` | 現在のHTTPリクエスト情報 |
| `session` | ユーザーセッション（Cookieベース） |
| `url_for` | ルート名からURLを生成 |
| `highlight` | Pygmentsのシンタックスハイライト関数 |
| `HtmlFormatter` | HTML出力用のフォーマッタ |
| `ClassNotFound` | 存在しない言語名を指定した場合の例外 |
| `get_all_lexers` | Pygmentsが対応するすべての言語を取得 |
| `get_lexer_by_name` | 言語名からLexer（構文解析器）を取得 |

### 5.2 設定セクション

```python
secret_key = os.environ.get("FLASK_SECRET_KEY")

if not secret_key:
    raise RuntimeError(
        "FLASK_SECRET_KEY environment variable is required."
    )

app.secret_key = secret_key
```

Flaskのセッション機能には秘密鍵が必要です。この秘密鍵はセッションCookieの署名に使用され、漏洩するとセッションが改ざんされる危険があります。

そのため、コード内に直接書かず、**環境変数から取得**します。環境変数が設定されていない場合は、明示的にエラーを発生させて起動を阻止します。

#### なぜ環境変数から取得するのか

秘密鍵をソースコードに直接書くと、以下の問題が生じます。

* Gitリポジトリに誤ってコミットされる可能性がある
* 複数人で開発する際に鍵が共有されてしまう
* 本番と開発で同じ鍵が使われる可能性がある

環境変数にすることで、ソースコードと秘密情報を分離できます。

---

```python
MAX_PASTE_BYTES = 512 * 1024
```

Paste本文の最大サイズを512KB（524,288バイト）に設定します。この値は実際のバイト数で計算されます。

---

```python
# HTMLフォームのPOST送信では日本語などのマルチバイト文字がURLエンコードされ、
# UTF-8の3バイト文字が "%XX%XX%XX" の9バイトに膨らむため、
# 本文上限の約3倍の余裕を持たせる。実際の本文サイズはアプリケーション側で厳密にチェックする。
app.config["MAX_CONTENT_LENGTH"] = MAX_PASTE_BYTES * 3 + 16 * 1024
```

Flask組み込みのリクエストサイズ制限です。HTMLフォームからPOST送信されるデータは `application/x-www-form-urlencoded` 形式になるため、日本語などのマルチバイト文字はURLエンコードされます。例えば「あ」（UTF-8で3バイト）は `%E3%81%82` の9バイトに膨らみます。そのため、リクエスト全体の上限は本文上限の約3倍に設定し、実際の本文サイズはアプリケーション側（`len(content_bytes)`）で厳密にチェックします。

この制限により、Flaskは巨大なリクエストを受信した時点で413エラーを返します。

---

```python
app.config["SESSION_COOKIE_HTTPONLY"] = True
```

セッションCookieに `HttpOnly` 属性を付与します。これにより、JavaScriptからCookieにアクセスできなくなり、XSS攻撃によるセッション窃取のリスクを低減します。

---

```python
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
```

セッションCookieに `SameSite=Lax` 属性を付与します。これにより、別サイトからのPOSTリクエストでCookieが送信されにくくなり、CSRF攻撃のリスクを低減します。

---

```python
app.config["SESSION_COOKIE_SECURE"] = (
    os.environ.get("FLASK_HTTPS", "").lower() == "true"
)
```

HTTPS環境では `Secure` 属性を付与します。これにより、CookieはHTTPS接続時のみ送信されます。HTTP環境では機能しないため、環境変数 `FLASK_HTTPS` で制御します。

---

```python
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
PASTE_DIR = os.path.join(BASE_DIR, "pastes")

os.makedirs(PASTE_DIR, exist_ok=True)
```

`pastes/` ディレクトリのパスを絶対パスで取得します。`os.path.abspath()` を使うことで、スクリプトをどのディレクトリから実行しても正しいパスが得られます。

`exist_ok=True` により、ディレクトリが既に存在する場合でもエラーになりません。

### 5.3 ログ設定

```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
```

ログの出力形式を設定します。`INFO` レベル以上のログ（情報、警告、エラー）が、時刻とレベル名付で出力されます。

ログは以下の用途で使用します。

* Paste作成時の記録
* エラー発生時の詳細記録
* 異常検知（例：ID生成の連続失敗）

### 5.4 Paste IDの検証

```python
VALID_PASTE_ID = re.compile(
    r"^[a-zA-Z0-9_-]{1,64}$"
)


def is_valid_paste_id(paste_id):
    return bool(
        isinstance(paste_id, str)
        and VALID_PASTE_ID.fullmatch(paste_id)
    )
```

#### なぜ検証が必要か

URLから取得した `paste_id` をそのままファイルパスに使うと、重大なセキュリティ問題が生じます。

例えば、悪意あるユーザーが以下のようなURLにアクセスしたとします。

```text
/paste/../../../etc/passwd
```

もし検証なしで `os.path.join(PASTE_DIR, paste_id)` を実行すると、以下のようなパスができてしまいます。

```text
/pastes/../../../etc/passwd
```

これは実質的に `/etc/passwd` を指し、サーバーの機密ファイルが読み取られる可能性があります。この攻撃手法を**パストラバーサル（Path Traversal）**と呼びます。

#### 正規表現の意味

```python
r"^[a-zA-Z0-9_-]{1,64}$"
```

| 記号 | 意味 |
|------|------|
| `^` | 文字列の先頭 |
| `[a-zA-Z0-9_-]` | 許可する文字（英数字、アンダースコア、ハイフン） |
| `{1,64}` | 1文字以上64文字以下 |
| `$` | 文字列の末尾 |

この正規表現により、以下の文字は一切含まれません。

* `.`（ドット）
* `/`（スラッシュ）
* `\`（バックスラッシュ）
* 空白文字
* その他の特殊文字

つまり、ディレクトリ traversal に使用される `/` や `\` が含まれないため、パストラバーサル攻撃を根本的に防ぎます。

また、`fullmatch()` を使用することで、文字列全体がパターンに一致することを確認します。部分一致ではなく、完全な一致を要求します。

### 5.5 言語処理

```python
def get_language_options():
    languages = set()

    for _, aliases, _, _ in get_all_lexers():
        for alias in aliases:
            languages.add(alias)

    return sorted(languages)


LANGUAGE_OPTIONS = get_language_options()
ALLOWED_LANGUAGES = set(LANGUAGE_OPTIONS)
```

Pygmentsが対応するすべてのプログラミング言語のエイリアスを取得します。例えば `python`、`javascript`、`html` などです。

`set` に変換することで重複を排除し、ソートして返します。

モジュール読み込み時に一度だけ実行し、結果を `LANGUAGE_OPTIONS` と `ALLOWED_LANGUAGES` に保持します。

---

```python
def sanitize_language(language):
    if not isinstance(language, str):
        return "text"

    language = language.strip().lower()

    if language in ALLOWED_LANGUAGES:
        return language

    return "text"
```

ユーザーから送信された言語名を検証・正規化します。

| 入力 | 出力 | 理由 |
|------|------|------|
| `"python"` | `"python"` | 許可リストに含まれる |
| `"Python"` | `"python"` | 小文字に正規化 |
| `" PYTHON "` | `"python"` | 前後の空白を除去、小文字化 |
| `"unknown_lang"` | `"text"` | 許可リストにないためフォールバック |
| `123` | `"text"` | 文字列でないためフォールバック |

Pygmentsに存在しない言語名を渡すと `ClassNotFound` 例外が発生します。これを防ぐため、存在しない言語は `"text"`（プレーンテキスト）にフォールバックします。

### 5.6 CSRF対策

#### CSRFとは

**CSRF（Cross-Site Request Forgery）**とは、悪意あるサイトが、利用者のブラウザを使って別サイト（この場合はPastebin）に意図しないリクエストを送信させる攻撃です。

例えば、以下のようなHTMLが悪意あるサイトに置かれていたとします。

```html
<form action="https://victim-pastebin.example.com/" method="POST" id="evil">
  <input type="hidden" name="content" value="Hacked!">
  <input type="hidden" name="language" value="text">
</form>
<script>document.getElementById("evil").submit();</script>
```

セッションCookieで本人確認をしているサービスの場合、その利用者がこのページを開くと、ブラウザが自動的にCookie付きでフォームを送信し、本人の意図しない操作が実行されてしまいます。

#### 対策：CSRFトークン

CSRF対策の基本は、**リクエストに秘密のトークンを含める**ことです。このトークンは以下の条件を満たす必要があります。

* サーバーが生成し、セッションに紐づけて保存する
* フォームにhiddenフィールドとして埋め込む
* 送信時にセッションのトークンと比較して一致を確認する

悪意あるサイトは、被害者向けに発行されたフォームページの中身（＝トークン）を読み取れません（ブラウザの**同一オリジンポリシー**による）。そのため、正しいトークンをフォームに含めることができません。

なお、`HttpOnly` はJavaScriptからCookieを読めなくする別の対策であり、CSRFトークンが守られる理由そのものではありません。

#### このアプリでのCSRF対策の位置づけ

このPastebinにはログイン機能がなく、誰でも投稿できます。そのため、攻撃者は被害者のブラウザを使わなくても、自分で `POST /` を送れば同じことができます（自分のセッションでトークンを取得して送信するだけです）。

つまり、このアプリではCSRFトークンが実質的に防いでいるものはほとんどなく、**学習用の実装**です。ログイン機能や、利用者ごとの操作（削除・編集など）を追加したときに、本来の効果を発揮します。スパム投稿への対策は、13.4 のレート制限の領域です。

---

```python
def get_csrf_token():
    token = session.get("csrf_token")

    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token

    return token
```

CSRFトークンを取得または生成します。

* セッションに既にトークンがあれば、それを返す
* なければ `secrets.token_urlsafe(32)` で新しく生成し、セッションに保存

`secrets` モジュールは暗号学的に安全な乱数を生成するため、トークンの予測が困難です。

`token_urlsafe(32)` は約43文字のURL安全な文字列を生成します。

---

```python
def verify_csrf_token(token):
    expected = session.get("csrf_token")

    if not token or not expected:
        return False

    return secrets.compare_digest(
        token.encode("utf-8"),
        expected.encode("utf-8"),
    )
```

送信されたトークンを検証します。

`secrets.compare_digest()` を使用する理由は、**タイミング攻撃**を防ぐためです。通常の文字列比較（`==`）は、先頭から1文字ずつ比較し、不一致が見つかった時点で終了します。攻撃者はこの比較時間の差を測定することで、正しいトークンを推測できる可能性があります。

`secrets.compare_digest()` は常に一定時間で比較を行い、この攻撃を防ぎます。

なお、`compare_digest()` に `str` を渡す場合は、ASCII文字だけで構成されていないと `TypeError` になります。CSRFトークンはフォームから送られる値で、利用者が自由に内容を変えられるため、`あ` のような文字を送られると500エラーになってしまいます。そこで、両方を `.encode("utf-8")` でバイト列にしてから比較します。

### 5.7 Paste IDの生成

```python
def create_paste():
    for _ in range(20):
        paste_id = shortuuid.random(length=10)

        if not is_valid_paste_id(paste_id):
            continue

        file_path = os.path.join(
            PASTE_DIR,
            paste_id,
        )

        try:
            file_object = open(
                file_path,
                "x",
                encoding="utf-8",
                newline="\n",
            )

            return paste_id, file_path, file_object

        except FileExistsError:
            continue

    raise RuntimeError(
        "Unable to generate a unique paste ID."
    )
```

#### 処理の流れ

1. `shortuuid.random(length=10)` で10文字のランダムなIDを生成
2. `is_valid_paste_id()` で検証（セキュリティのため二重チェック）
3. `open()` の `"x"` モードで排他的にファイルを作成
4. 既にファイルが存在する場合は `FileExistsError` が発生し、別のIDを生成して再試行
5. 最大20回試行して失敗した場合は `RuntimeError` を発生

#### "x" モードとは

Pythonの `open()` 関数のモードには以下の種類があります。

| モード | 動作 |
|--------|------|
| `"w"` | 書き込み（既存ファイルは上書き） |
| `"a"` | 追加（既存ファイルは末尾に追加） |
| `"x"` | 排他作成（既存ファイルがあればエラー） |
| `"r"` | 読み込み |

`"x"` モードは「exclusive creation」の略で、ファイルが存在しない場合のみ作成を許可します。これにより、既存のPasteを誤って上書きする事故を防ぎます。

#### shortuuid.random(length=10) の衝突確率

shortuuidはUUIDをBase57エンコーディングした文字列を生成します。10文字の場合、約 `3.6 × 10^17`（57の10乗）通りの組み合わせがあります。実用上、衝突の確率は無視できるレベルですが、理論的には可能性があるため、衝突時の再試行処理を入れています。

### 5.8 Pasteの読み込み

```python
def get_paste_file_path(paste_id):
    if not is_valid_paste_id(paste_id):
        abort(404)

    file_path = os.path.join(
        PASTE_DIR,
        paste_id,
    )

    if not os.path.isfile(file_path):
        abort(404)

    return file_path
```

#### なぜ `os.path.isfile()` を使うのか

`os.path.exists()` でもファイルの存在確認はできますが、`isfile()` を使う理由があります。

* `exists()` はディレクトリでも `True` を返す
* `isfile()` は「ファイル」であることを確認する

もし `pastes/` 内にディレクトリが存在し、その名前がPaste IDと一致した場合、`exists()` だけではディレクトリと区別できません。`isfile()` を使うことで、ディレクトリ名を誤ってPaste IDとして扱うことを防ぎます。

---

```python
def read_paste(paste_id):
    file_path = get_paste_file_path(paste_id)

    try:
        with open(
            file_path,
            "r",
            encoding="utf-8",
            newline="\n",
        ) as f:
            language = f.readline().rstrip("\n")
            content = f.read()

    except (OSError, UnicodeError):
        abort(404)

    return language, content
```

Pasteファイルを読み込みます。ファイルの形式は以下の通りです。

```text
python
def hello():
    print("Hello")

```

* 1行目：言語名（`python` など）
* 2行目以降：Paste本文

`readline()` で1行目を読み取り、`rstrip("\n")` で末尾の改行を除去します。その後 `read()` で残りの全文を読み込みます。

`encoding="utf-8"` を明示することで、日本語などのマルチバイト文字が正しく読み込まれます。

`newline="\n"` も明示しています。これを指定しないと、OSによって改行の変換方法が変わります（詳しくは 5.9 の「改行コードの正規化」を参照）。

`OSError`（ファイル読み込み失敗）や `UnicodeError`（文字コードの問題）が発生した場合は、404エラーを返します。これにより、内部エラーの詳細が外部に漏洩するのを防ぎます。

### 5.9 トップページのルート

```python
@app.route("/", methods=["GET", "POST"])
def index():
```

`/` へのGETリクエストではフォームを表示し、POSTリクエストではフォームデータを処理します。

#### POST時の処理フロー

```
CSRFトークン検証
    ↓
入力内容の取得と検証
    ↓
サイズチェック
    ↓
Paste ID生成とファイル作成
    ↓
データ書き込み
    ↓
リダイレクト
```

---

#### CSRFトークンの検証

```python
csrf_token = request.form.get("csrf_token", "")

if not verify_csrf_token(csrf_token):
    abort(400)
```

フォームから送信されたCSRFトークンを検証します。不一致の場合は400（Bad Request）を返します。

---

#### 入力の検証

```python
content = request.form.get("content", "")
content = content.replace("\r\n", "\n").replace("\r", "\n")
language = sanitize_language(
    request.form.get("language", "text")
)

if not content:
    flash("Paste content is required.", "error")

    return render_template(
        "index.html",
        csrf_token=get_csrf_token(),
        language_options=LANGUAGE_OPTIONS,
    ), 400
```

内容が空の場合はエラーメッセージを登録し、フォームを再表示します。`flash()` で登録したメッセージは、テンプレート側の `get_flashed_messages()` で取り出して表示します（6.1 参照）。一度表示したメッセージは、自動的に消えます。

HTTPステータスコード400を返すことで、これがクライアント側のエラー（入力漏れ）であることを明示します。

---

#### 改行コードの正規化

```python
content = request.form.get("content", "")
content = content.replace("\r\n", "\n").replace("\r", "\n")
```

ブラウザは、`<textarea>` の改行を `\r\n`（CRLF）に変換して送信します。このまま保存すると、次の問題が起こります。

* `/raw/<Paste ID>` の出力に `\r\n` がそのまま含まれる
* Windowsでは、Pythonのテキストモードが書き込み時に `\n` を `\r\n` に変換するため、`\r\n` が `\r\r\n` として保存される。読み込み時には `\r\r\n` が改行2つに解釈され、空行が2倍になる

そこで、受信した時点で改行を `\n` に統一します。あわせて、ファイルを開くときに `newline="\n"` を指定し、OSごとの変換を無効にします。これで、どのOSでも保存される内容は同じになります。

この変換は文字数を減らすだけなので、サイズチェック（バイト数の計算）の前に行って問題ありません。

---

#### サイズチェック

```python
content_bytes = content.encode("utf-8")

if len(content_bytes) > MAX_PASTE_BYTES:
    abort(413)
```

文字列をUTF-8でエンコードしてからバイト数を計算します。Pythonの `len()` は文字数を返しますが、日本語などのマルチバイト文字は1文字あたり複数バイトになるため、**バイト数で計算**する必要があります。

例えば、以下の文字列を考えます。

```python
text = "こんにちは"  # 5文字
print(len(text))           # 5（文字数）
print(len(text.encode("utf-8")))  # 15（バイト数）
```

日本語はUTF-8で1文字あたり3バイトになるため、文字数とバイト数は異なります。サイズ制限はバイト数で判断する必要があります。

413は「Payload Too Large」を意味するHTTPステータスコードです。

---

#### ファイル書き込み

```python
paste_id, file_path, file_object = create_paste()

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
    try:
        file_object.close()
    except Exception:
        pass
```

##### flush() と fsync() の役割

ファイル書き込みには複数の層のバッファが存在します。

```
Pythonのバッファ
    ↓ flush()
OSのバッファ
    ↓ fsync()
物理ディスク
```

* `write()` はPythonのバッファに書き込むだけ
* `flush()` はPythonのバッファをOSに渡す
* `fsync()` はOSのバッファを物理ディスクに同期させる

`fsync()` を呼ぶことで、書き込みが確実にディスクに保存されたことを保証します。これにより、直後にサーバーがクラッシュしてもデータが失われるリスクを減らします。

##### エラー時のクリーンアップ

`except` ブロックで、書き込み途中にエラーが発生した場合、作成途中のファイルを削除します。これにより、不完全なファイルが残るのを防ぎます。

`finally` ブロックで、成功・失敗に関わらずファイルオブジェクトを確実に閉じます。

---

#### PRG（Post/Redirect/Get）

```python
return redirect(
    url_for(
        "view_paste",
        paste_id=paste_id,
    )
)
```

Paste作成成功後、直接レスポンスを返すのではなく、Paste表示ページへリダイレクトします。

これにより、以下の問題を防ぎます。

* ブラウザの更新ボタンを押すと「フォームを再送信しますか？」の確認が表示される
* 更新時に同じPasteが二重に作成される

```
POST /              ← フォーム送信
    ↓
サーバー処理
    ↓
Redirect → GET /paste/Ab3xK9Lm2Q
    ↓
Paste表示
```

このパターンを **Post/Redirect/Get（PRG）** と呼びます。

### 5.10 Paste表示のルート

```python
@app.route("/paste/<paste_id>")
def view_paste(paste_id):
```

`/paste/<paste_id>` へのGETリクエストを処理します。

#### シンタックスハイライト

```python
try:
    lexer = get_lexer_by_name(language)

    highlighted = highlight(
        content,
        lexer,
        HtmlFormatter(
            linenos=True,
            cssclass="highlight",
        ),
    )
```

Pygmentsの `highlight()` 関数は以下の引数を受け取ります。

| 引数 | 内容 |
|------|------|
| `content` | ハイライト対象のソースコード |
| `lexer` | 言語固有の構文解析器（Tokenizer） |
| `formatter` | 出力形式（ここではHTML） |

`HtmlFormatter(linenos=True)` は行番号を付与します。

---

```python
highlight_css = HtmlFormatter(
    linenos=True,
    cssclass="highlight",
).get_style_defs(".highlight")
```

ハイライト用のCSS定義を生成します。これをテンプレートの `<style>` タグに埋め込むことで、コードに色が付きます。

---

#### フォールバック

```python
except ClassNotFound:
    highlighted = highlight(
        content,
        get_lexer_by_name("text"),
        HtmlFormatter(
            linenos=True,
            cssclass="highlight",
        ),
    )
```

もし言語名が不正で `get_lexer_by_name()` が失敗した場合、プレーンテキストとして表示します。これにより、未知の言語名でページ全体がエラーになるのを防ぎます。

### 5.11 Raw表示のルート

```python
@app.route("/raw/<paste_id>")
def raw_paste(paste_id):
    _, content = read_paste(paste_id)

    response = app.response_class(
        content,
        status=200,
        mimetype="text/plain",
    )

    response.headers["X-Content-Type-Options"] = "nosniff"

    return response
```

色付けなしの純粋なテキストを返します。`mimetype="text/plain"` により、ブラウザは内容をテキストとして表示します。

`X-Content-Type-Options: nosniff` は、ブラウザがContent-Typeヘッダーを無視して内容を推測する動作を抑制します。これにより、悪意あるコンテンツが誤ってHTMLやJavaScriptとして実行されるリスクを低減します。

### 5.12 エラーハンドラ

```python
@app.errorhandler(404)
def not_found(error):
    return render_template(
        "404.html",
        message="Paste not found.",
    ), 404
```

404エラーが発生した場合、専用のテンプレートを表示します。エラーの原因（存在しないPaste、不正なID、期限切れなど）を区別せず、すべて「見つからない」として扱うことで、内部情報の漏洩を防ぎます。

例えば、以下のような情報を攻撃者に与えないようにします。

* 「このIDは存在するが期限切れです」→ 存在確認ができてしまう
* 「このIDは形式が不正です」→ 検証ロジックの推測が可能

すべて一律で404を返すことで、**情報漏洩を最小限**に抑えます。

---

## 6. テンプレート

### 6.1 index.html

`templates/index.html` は、**投稿フォーム**と**Paste表示**の両方を担当します。`paste_content` 変数が存在するかどうかで表示を切り替えます。

```html
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pastebin</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
    {% if highlight_css %}
    <style>{{ highlight_css|safe }}</style>
    {% endif %}
</head>
<body>
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            <div class="messages">
                {% for category, message in messages %}
                    <div class="message {{ category }}">{{ message }}</div>
                {% endfor %}
            </div>
        {% endif %}
    {% endwith %}
```

`{{ url_for('static', filename='style.css') }}` は、Flaskが自動的に `static/style.css` のURLを生成します。

`{% if highlight_css %}` で、ハイライト用のCSSが存在する場合のみ `<style>` タグを出力します。Paste表示時のみCSSが必要で、フォーム表示時は不要なためです。

---

#### エラーメッセージの表示

`<body>` の直後に、`flash()` で登録されたメッセージを表示する部分があります。

```html
{% with messages = get_flashed_messages(with_categories=true) %}
```

`get_flashed_messages(with_categories=true)` は、登録されたメッセージを `(カテゴリ, メッセージ)` の組のリストで返します。`flash("...", "error")` の第2引数がカテゴリで、ここでは `error` です。

この表示部分がないと、`flash()` を呼んでもメッセージは画面に出ません。

メッセージの `{{ message }}` には `|safe` を付けていないので、自動エスケープが働きます。

---

```html
{% if paste_content %}
```

`paste_content` 変数が存在する場合は、Paste表示モードになります。存在しない場合は、投稿フォームを表示します。

#### Paste表示部分

```html
<section class="paste">
    <div class="paste-header">
        <div>
            <strong>Paste ID:</strong>
            <code>{{ paste_id }}</code>
        </div>
        <div>
            <strong>Language:</strong>
            <code>{{ paste_language }}</code>
        </div>
    </div>

    <div class="paste-links">
        <a href="{{ url_for('raw_paste', paste_id=paste_id) }}">Raw</a>
        <a href="{{ url_for('index') }}">New Paste</a>
    </div>

    <div class="paste-content">
        {{ paste_content|safe }}
    </div>
</section>
```

`{{ paste_content|safe }}` の `|safe` は、Jinja2に「このHTMLはエスケープされずにそのまま出力してよい」と伝えるフィルタです。

#### なぜ safe を使うのか

`paste_content` はPygmentsが生成したHTMLです。Pygmentsは信頼できるライブラリで、以下の処理を行っています。

* ソースコードを構文解析してHTMLタグに変換
* キーワード、文字列、コメントなどに `<span>` タグとCSSクラスを付与
* ユーザーの入力をそのままHTMLとして出力するのではなく、構造化されたHTMLとして返す

つまり、ユーザーが `<script>alert(1)</script>` と入力しても、Pygmentsはこれを「コード内の文字列」として処理し、HTMLエンティティに変換するか、安全な `<span>` タグで囲みます。

そのため、`paste_content` に `|safe` を適用しても、XSSのリスクはありません。

一方、`{{ paste_id }}` や `{{ paste_language }}` には `|safe` を適用していません。これらはユーザーが間接的に影響できる値であり、Jinja2の自動エスケープによってHTML特殊文字（`<`, `>`, `&` など）が安全に変換されます。

---

#### 投稿フォーム部分

```html
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
            <label for="content">Content</label>
            <textarea id="content" name="content" rows="24"
                      maxlength="524288" spellcheck="false"></textarea>
        </div>

        <div class="form-footer">
            <p>Maximum size: 512 KiB</p>
            <button type="submit">Create Paste</button>
        </div>
    </form>
</section>
```

`novalidate` 属性は、ブラウザのデフォルトのフォーム検証を無効にします。サーバー側で検証を行うため、ブラウザ側の検証と競合しないようにします。

`maxlength="524288"` は、HTMLレベルでの入力制限です（512 * 1024 = 524288）。ただし、これはあくまで補助的な制限であり、サーバー側でも必ず検証を行います。ブラウザの制限は回避可能なため、サーバー側の検証が本質的です。

`spellcheck="false"` は、コード入力時にブラウザのスペルチェックを無効にします。変数名や構文が誤って赤波線で表示されるのを防ぎます。

### 6.2 404.html

```html
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pastebin - Error</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
    <div class="container">
        <h1>Pastebin</h1>
        <section class="error-page">
            <h2>Not Found</h2>
            <p>{{ message or "The requested resource was not found." }}</p>
            <p><a href="{{ url_for('index') }}">Back to Pastebin</a></p>
        </section>
    </div>
</body>
</html>
```

404エラー時に表示されるページです。`message` 変数が渡された場合はそのメッセージを、渡されなかった場合はデフォルトメッセージを表示します。

### 6.3 413.html

```html
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pastebin - Too Large</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
    <div class="container">
        <h1>Pastebin</h1>
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

413エラー時に表示されるページです。`{{ (max_bytes / 1024)|int }}` で、バイト数をKiBに変換して整数で表示します。`|int` はJinja2のフィルタで、値を整数に変換します。

---

## 7. CSS

`static/style.css` は画面の見た目を整えます。以下に主な設計意図を説明します。

### 7.1 レイアウト

```css
.container {
    width: min(1100px, calc(100% - 32px));
    margin: 0 auto;
    padding: 24px 0 48px;
}
```

`min(1100px, calc(100% - 32px))` は、画面幅が広い場合は最大1100pxに制限し、狭い場合は画面幅から32px引いた幅にする、という意味です。これにより、モバイルでも見やすいレイアウトになります。

### 7.2 レスポンシブ対応

```css
@media (max-width: 700px) {
    .container {
        width: min(100% - 20px, 1100px);
        padding-top: 12px;
    }

    .form-footer {
        flex-direction: column;
    }

    button {
        width: 100%;
    }
}
```

画面幅が700px以下の場合、以下の調整を行います。

* 余白を縮小
* フッターのボタンを縦並びに変更
* ボタンを画面幅いっぱいに広げる

これにより、スマートフォンなどの小さい画面でも操作しやすくなります。

### 7.3 メッセージ表示

```css
.message {
    padding: 10px 14px;
    margin-bottom: 16px;
    border: 1px solid #ccc;
    border-radius: 6px;
    background: #f5f5f5;
}

.message.error {
    border-color: #d9534f;
    background: #fdecea;
    color: #8a1f1b;
}
```

`flash(..., "error")` のカテゴリ名が `class="message error"` になるので、CSSでカテゴリごとに見た目を切り替えられます。

---

## 8. セキュリティ対策のまとめ

### 8.1 対策一覧

| 脅威 | 対策 | 実装箇所 |
|------|------|----------|
| **パストラバーサル** | Paste IDを正規表現で検証 | `is_valid_paste_id()` |
| **CSRF攻撃** | CSRFトークンの生成と検証 | `get_csrf_token()`, `verify_csrf_token()` |
| **DoS（サイズ攻撃）** | リクエストサイズ上限 | `MAX_CONTENT_LENGTH`, `MAX_PASTE_BYTES` |
| **ファイル上書き** | `"x"` モードでの排他作成 | `create_paste()` |
| **XSS** | Pygmentsによる安全なHTML変換 + Jinja2自動エスケープ | `view_paste()`, テンプレート |
| **セッション窃取** | `HttpOnly`, `SameSite`, `Secure` Cookie属性 | 設定セクション |
| **二重投稿** | PRGパターン | `index()` のリダイレクト |
| **タイミング攻撃** | `secrets.compare_digest()` | `verify_csrf_token()` |
| **情報漏洩** | エラーの詳細を隠蔽、一律404 | エラーハンドラ |

### 8.2 各対策の詳細

#### パストラバーサル対策

```python
VALID_PASTE_ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
```

`/` や `\` を含まない文字列のみを許可することで、ディレクトリ移動を不可能にします。

#### CSRF対策

```python
# フォームに埋め込む
csrf_token = secrets.token_urlsafe(32)
session["csrf_token"] = csrf_token

# 送信時に検証
secrets.compare_digest(token.encode("utf-8"), expected.encode("utf-8"))
```

セッションに紐づいた秘密トークンを使い、別サイトからの偽造リクエストを防ぎます。ただし、ログイン機能のないこのアプリでの実質的な効果は限定的です（5.6 参照）。

#### DoS対策

```python
MAX_PASTE_BYTES = 512 * 1024
# HTMLフォームのPOST送信では日本語などのマルチバイト文字がURLエンコードされ、
# UTF-8の3バイト文字が "%XX%XX%XX" の9バイトに膨らむため、
# 本文上限の約3倍の余裕を持たせる。実際の本文サイズはアプリケーション側で厳密にチェックする。
app.config["MAX_CONTENT_LENGTH"] = MAX_PASTE_BYTES * 3 + 16 * 1024
```

Flaskレベルとアプリケーションレベルの二重でサイズ制限を設けます。

#### XSS対策

```html
<!-- 自動エスケープ（safeなし） -->
{{ paste_id }}
{{ paste_language }}

<!-- Pygments生成HTML（safeあり、安全） -->
{{ paste_content|safe }}
```

ユーザー入力に近い値は自動エスケープし、Pygmentsが生成したHTMLのみ `safe` を適用します。

---

## 9. 起動方法

### 9.1 環境変数の設定

#### Linux / macOS

```bash
export FLASK_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

#### Windows PowerShell

```powershell
$env:FLASK_SECRET_KEY = python -c "import secrets; print(secrets.token_urlsafe(32))"
```

#### Windows CMD

```cmd
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

出力された値を手動で設定します。

```cmd
set FLASK_SECRET_KEY=出力された値
```

### 9.2 アプリケーションの起動

```bash
python app.py
```

以下のメッセージが表示されたら成功です。

```
 * Running on http://127.0.0.1:5000
```

ブラウザで `http://127.0.0.1:5000/` を開きます。

### 9.3 HTTPS環境の場合

```bash
export FLASK_HTTPS=true
python app.py
```

`FLASK_HTTPS=true` を設定すると、`SESSION_COOKIE_SECURE` が有効になり、CookieがHTTPS接続時のみ送信されるようになります。

---

## 10. 使い方

### 10.1 Pasteの作成

1. ブラウザで `http://127.0.0.1:5000/` を開く
2. Languageからプログラミング言語を選択（例：python）
3. Contentにコードやテキストを入力
4. 「Create Paste」ボタンをクリック
5. `/paste/Ab3xK9Lm2Q` のようなURLにリダイレクトされる

### 10.2 Pasteの閲覧

作成時にリダイレクトされたURL、または `http://127.0.0.1:5000/paste/<Paste ID>` を開きます。

コードはシンタックスハイライトされて表示されます。

### 10.3 Raw表示

Pasteページの「Raw」リンクをクリックするか、直接 `/raw/<Paste ID>` にアクセスします。

純粋なテキストが `text/plain` として表示されます。

---

## 11. ファイルの保存形式

### 11.1 ファイル構造

Paste IDが `Ab3xK9Lm2Q` の場合、以下のファイルが作成されます。

```text
pastes/Ab3xK9Lm2Q
```

ファイルの内容は以下のようになります。

```text
python
def hello():
    print("Hello, Pastebin!")
```

* 1行目：言語名（`python`）
* 2行目以降：Paste本文

### 11.2 なぜこの形式か

データベースを使わないため、言語情報もファイルに保存する必要があります。1行目に言語名を入れることで、ファイルだけで言語と本文の両方を管理できます。

読み込み時は以下のように分離します。

```python
language = f.readline().rstrip("\n")  # 1行目：言語
content = f.read()                    # 残り：本文
```

---

## 12. データのバックアップ

データベースを使わないため、バックアップは非常に簡単です。

### 12.1 手動バックアップ

```bash
cp -r pastes/ pastes_backup_$(date +%Y%m%d)/
```

### 12.2 定期バックアップ（cron例）

```bash
# 毎日午前3時にバックアップ
0 3 * * * cp -r /path/to/pastebin/pastes/ /backup/pastes_$(date +\%Y\%m\%d)/
```

---

## 13. 公開運用時の注意

### 13.1 開発用サーバーの制限

`app.run()` で起動するサーバーは、Flaskの開発用サーバーです。本番環境では以下の点に注意が必要です。

* 同時接続の処理能力に限界がある
* 直接インターネットに公開しないこと
* WSGIサーバー（GunicornやuWSGI）を使用すること

### 13.2 推奨構成

```text
Internet
    │
    ▼
HTTPS（TLS終端）
    │
    ▼
Reverse Proxy（Nginx等）
    │
    ▼
WSGI Server（Gunicorn等）
    │
    ▼
Flask Application
    │
    ▼
pastes/
```

### 13.3 Gunicornでの起動例

```bash
python -m pip install gunicorn
gunicorn -w 4 -b 127.0.0.1:8000 app:app
```

| オプション | 意味 |
|------------|------|
| `-w 4` | workerプロセスを4つ起動 |
| `-b 127.0.0.1:8000` | 127.0.0.1:8000で待ち受け |
| `app:app` | `app.py` の `app` 変数を使用 |

### 13.4 レート制限の検討

公開サービスとして運用する場合、以下の制限を検討します。

* IPアドレスごとの投稿数制限
* 1時間あたりの投稿数上限
* 同一内容の連続投稿の防止

これらはFlask-Limiter等の拡張機能で実装できます。

---

## 14. トラブルシューティング

### 14.1 `RuntimeError: FLASK_SECRET_KEY environment variable is required.`

環境変数 `FLASK_SECRET_KEY` が設定されていません。起動前に以下を実行してください。

```bash
export FLASK_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

### 14.2 `413 Payload Too Large`

投稿内容が512KBを超えています。内容を分割するか、サイズを縮小してください。

### 14.3 Pasteが表示されない

* `pastes/` ディレクトリが存在するか確認
* ファイルの権限を確認
* ログを確認

### 14.4 シンタックスハイライトが効かない

Pygmentsが言語名を認識できなかった場合、プレーンテキストとして表示されます。言語名が正しいか確認してください。

---

## 15. まとめ

このチュートリアルでは、データベースを使わずに、セキュリティを考慮したPastebinを構築しました。

### 学べること

| テーマ | 内容 |
|--------|------|
| Flaskの基礎 | ルーティング、テンプレート、セッション |
| ファイルI/O | 排他作成、エンコーディング、同期書き込み |
| セキュリティ | CSRF、パストラバーサル、XSS、サイズ制限 |
| エラーハンドリング | 適切なHTTPステータスコード、エラーページ |
| セッション管理 | Cookie属性、秘密鍵の管理 |

### この構成の限界

以下の機能が必要になった場合は、データベースの導入を検討してください。

* 有効期限の管理
* 閲覧数の記録
* ユーザー管理
* 検索機能
* Pasteの一覧表示

しかし、小規模な個人用Pastebinや学習目的であれば、このファイルベースの構成は十分実用的です。

---

*このチュートリアルは、Flaskを使ったWebアプリケーション開発の入門として、またセキュリティを考慮したアプリケーション設計の参考として利用できます。*
