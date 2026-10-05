# シンプルな Pastebin を Python + Flask で作る
## 〜安全な最小構成チュートリアル〜

---

## 1. Pastebin とは

Pastebin は、テキストやコードスニペットを一時的に保存し、一意の URL で共有できる Web サービスです。

このチュートリアルでは、**小構成でありながらセキュリティを考慮した** Pastebin を Flask で構築します。

---

## 2. ファイル構成

```
pastebin/
├── app.py
├── pastes/              # 自動生成される
├── templates/
│   ├── index.html
│   ├── 404.html
│   └── 413.html
└── static/
    └── style.css
```

---

## 3. 事前準備

### 3.1 仮想環境の作成と有効化

```bash
mkdir pastebin
cd pastebin
python -m venv venv
```

**macOS / Linux:**
```bash
source venv/bin/activate
```

**Windows:**
```bash
venv\Scripts\activate
```

### 3.2 必要なパッケージのインストール

```bash
pip install Flask shortuuid pygments
```

### 3.3 ディレクトリの作成

```bash
mkdir -p pastes templates static
```

---

## 4. ソースコード

### 4.1 app.py（メインアプリケーション）

```python
import os
import re
import secrets
import logging

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
from pygments.lexers import get_all_lexers, get_lexer_by_name
from pygments.util import ClassNotFound

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

app = Flask(__name__)

# =============================================================================
# 設定
# =============================================================================

# 本番では FLASK_SECRET_KEY を必ず設定すること
# 未設定の場合は起動時にエラーとする（デフォルト値による事故を防ぐ）
app.secret_key = os.environ.get("FLASK_SECRET_KEY")
if not app.secret_key:
    raise RuntimeError(
        "環境変数 FLASK_SECRET_KEY が設定されていません。"
        "起動前に 'export FLASK_SECRET_KEY=$(openssl rand -hex 32)' を実行してください。"
    )

# 本文の最大サイズ（512KB）
MAX_PASTE_BYTES = 512 * 1024
# HTTPリクエスト全体の上限は、本文＋フォムのオーバーヘッドを見込んで少し大きく
app.config["MAX_CONTENT_LENGTH"] = MAX_PASTE_BYTES + 16 * 1024

# 保存先を絶対パス化（カレントディレクトリに依存しない）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PASTE_DIR = os.path.join(BASE_DIR, "pastes")
if not os.path.exists(PASTE_DIR):
    try:
        os.makedirs(PASTE_DIR)
        logging.info(f"ディレクトリ '{PASTE_DIR}' を作成しました。")
    except OSError as e:
        logging.error(f"ディレクトリ '{PASTE_DIR}' の作成中にエラー: {e}")
        raise

# paste_id の許可パターン（パストラバーサル防止＋長さ制限）
VALID_PASTE_ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

_language_options_cache = None
_allowed_language_codes = None


# =============================================================================
# ヘルパー関数
# =============================================================================

def get_language_options():
    global _language_options_cache
    if _language_options_cache is None:
        _language_options_cache = sorted(
            [(lexer[1][0], lexer[0]) for lexer in get_all_lexers() if lexer[1]]
        )
        logging.info("言語オプションのキャッシュを初期化しました。")
    return _language_options_cache


def get_allowed_language_codes():
    global _allowed_language_codes
    if _allowed_language_codes is None:
        _allowed_language_codes = {code for code, _name in get_language_options()}
        _allowed_language_codes.add("text")
    return _allowed_language_codes


def is_valid_paste_id(paste_id):
    return bool(VALID_PASTE_ID.match(paste_id))


def get_csrf_token():
    token = session.get("csrf_token")
    if token is None:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def verify_csrf_token(token):
    return token == session.get("csrf_token")


def sanitize_language(language):
    language = language.strip().lower()
    if language in get_allowed_language_codes():
        return language
    return "text"


def generate_unique_paste_id():
    max_attempts = 10
    for _ in range(max_attempts):
        paste_id = shortuuid.uuid()
        file_path = os.path.join(PASTE_DIR, paste_id)
        # isfile() で「ファイル」であることを確認（ディレクトリ名と同名を排除）
        if not os.path.isfile(file_path):
            return paste_id, file_path
    logging.error("paste_id の生成が %d 回連続で衝突しました。", max_attempts)
    abort(500, "Failed to generate unique paste ID")


# =============================================================================
# ルート
# =============================================================================

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        content = request.form.get("content", "")
        raw_language = request.form.get("language", "")
        language = sanitize_language(raw_language)
        csrf_token = request.form.get("csrf_token", "")

        if not verify_csrf_token(csrf_token):
            logging.warning("CSRFトークンが一致しませんでした。")
            abort(400, "Invalid CSRF token")

        if not content.strip():
            flash("ペーストするコンテンツを入力してください。", "error")
            return render_template(
                "index.html",
                languages=get_language_options(),
                csrf_token=get_csrf_token(),
            )

        content_bytes = content.encode("utf-8")
        if len(content_bytes) > MAX_PASTE_BYTES:
            flash(
                f"コンテンツが大きすぎます。最大 {MAX_PASTE_BYTES:,} バイトまでです。",
                "error",
            )
            return render_template(
                "index.html",
                languages=get_language_options(),
                csrf_token=get_csrf_token(),
            )

        paste_id, file_path = generate_unique_paste_id()

        try:
            with open(file_path, "x", encoding="utf-8") as f:
                f.write(f"{language}\n{content}")

            logging.info(f"ペーストID {paste_id} を保存しました。")
            flash("ペーストが正常に作成されました！", "success")
            return redirect(url_for("view_paste", paste_id=paste_id))

        except FileExistsError:
            logging.warning(f"ペーストID {paste_id} が衝突しました。")
            flash("ペーストの保存中に衝突が発生しました。もう一度お試しください。", "error")
            return render_template(
                "index.html",
                languages=get_language_options(),
                csrf_token=get_csrf_token(),
            )
        except IOError as e:
            logging.error(f"ペーストID {paste_id} の書き込みエラー: {e}")
            flash("ペーストの保存中にエラーが発生しました。", "error")
            return render_template(
                "index.html",
                languages=get_language_options(),
                csrf_token=get_csrf_token(),
            )

    return render_template(
        "index.html",
        languages=get_language_options(),
        csrf_token=get_csrf_token(),
    )


@app.route("/<paste_id>")
def view_paste(paste_id):
    if not is_valid_paste_id(paste_id):
        abort(404)

    file_path = os.path.join(PASTE_DIR, paste_id)

    # isfile() で「ファイル」であることを確認（ディレクトリ名と同名を排除）
    if not os.path.isfile(file_path):
        logging.warning(f"ペーストID {paste_id} が見つかりませんでした。")
        abort(404)

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            language = f.readline().strip()
            content = f.read()
    except IOError as e:
        logging.error(f"ペーストID {paste_id} の読み込みエラー: {e}")
        abort(500)

    try:
        lexer = get_lexer_by_name(language, stripall=True)
    except ClassNotFound:
        logging.warning(f"不明な言語 '{language}'。テキストとして表示します。")
        lexer = get_lexer_by_name("text", stripall=True)

    formatter = HtmlFormatter(linenos=True, cssclass="source")
    highlighted_content = highlight(content, lexer, formatter)
    highlight_css = formatter.get_style_defs(".source")

    raw_url = url_for("raw_paste", paste_id=paste_id, _external=True)

    return render_template(
        "index.html",
        paste_content=highlighted_content,
        highlight_css=highlight_css,
        paste_id=paste_id,
        raw_url=raw_url,
    )


@app.route("/raw/<paste_id>")
def raw_paste(paste_id):
    if not is_valid_paste_id(paste_id):
        abort(404)

    file_path = os.path.join(PASTE_DIR, paste_id)
    if not os.path.isfile(file_path):
        abort(404)

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            _language = f.readline().strip()
            content = f.read()
    except IOError as e:
        logging.error(f"ペーストID {paste_id} の読み込みエラー: {e}")
        abort(500)

    return content, 200, {"Content-Type": "text/plain; charset=utf-8"}


# =============================================================================
# エラーハンドラ
# =============================================================================

@app.errorhandler(404)
def page_not_found(error):
    return render_template("404.html"), 404


@app.errorhandler(413)
def request_entity_too_large(error):
    return render_template("413.html"), 413


# =============================================================================
# 起動
# =============================================================================

if __name__ == "__main__":
    # 本番では debug=False にすること！
    app.run(debug=False, host="127.0.0.1", port=5000)
```

### 4.2 templates/index.html

```html
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pastebin Service</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
    {% if highlight_css %}
    <style>
        {{ highlight_css|safe }}
    </style>
    {% endif %}
</head>
<body>
    <h1>Pastebin Service</h1>

    <!-- フラッシュメッセージ -->
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            <ul class="flashes">
            {% for category, message in messages %}
                <li class="{{ category }}">{{ message }}</li>
            {% endfor %}
            </ul>
        {% endif %}
    {% endwith %}

    <!-- ペースト表示画面 -->
    {% if paste_content %}

    <div class="paste-meta">
        <p>Paste ID: <code>{{ paste_id }}</code></p>
        <p>
            <a href="{{ raw_url }}">View Raw</a> |
            <a href="{{ url_for('index') }}">New Paste</a>
        </p>
    </div>

    <div class="highlight">
        {{ paste_content|safe }}
    </div>

    <!-- 新規作成フォーム -->
    {% else %}

    <form method="POST" action="{{ url_for('index') }}" novalidate>
        <input type="hidden" name="csrf_token" value="{{ csrf_token }}">

        <div class="form-group">
            <label for="language">Language:</label><br>
            <select name="language" id="language" required>
                {% for code, name in languages %}
                <option value="{{ code }}">{{ name }}</option>
                {% endfor %}
            </select>
        </div>

        <div class="form-group">
            <label for="content">Content:</label><br>
            <textarea
                name="content"
                id="content"
                rows="20"
                cols="80"
                placeholder="Paste your code here..."
                required
            ></textarea>
        </div>

        <div class="form-group">
            <button type="submit">Submit</button>
        </div>
    </form>

    {% endif %}

    <footer>
        <p><small><a href="{{ url_for('index') }}">Back to Top</a></small></p>
    </footer>
</body>
</html>
```

### 4.3 templates/404.html

```html
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <title>404 Not Found</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
    <h1>404 Not Found</h1>
    <p>指定されたペーストが見つかりませんでした。</p>
    <p><a href="{{ url_for('index') }}">トップページに戻る</a></p>
</body>
</html>
```

### 4.4 templates/413.html

```html
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <title>413 Payload Too Large</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
    <h1>413 Payload Too Large</h1>
    <p>送信されたデータが大きすぎます。</p>
    <p><a href="{{ url_for('index') }}">トップページに戻る</a></p>
</body>
</html>
```

### 4.5 static/style.css

```css
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
    margin: 20px auto;
    padding: 0 20px;
    max-width: 900px;
    line-height: 1.6;
    color: #333;
}

h1 {
    color: #222;
    border-bottom: 2px solid #eee;
    padding-bottom: 10px;
}

.form-group {
    margin-bottom: 15px;
}

label {
    font-weight: bold;
    display: inline-block;
    margin-bottom: 5px;
}

textarea {
    width: 100%;
    font-family: "Consolas", "Monaco", "Courier New", monospace;
    font-size: 14px;
    padding: 10px;
    border: 1px solid #ccc;
    border-radius: 4px;
    resize: vertical;
}

select {
    padding: 6px 10px;
    border: 1px solid #ccc;
    border-radius: 4px;
    font-size: 14px;
}

button {
    padding: 10px 24px;
    font-size: 14px;
    color: #fff;
    background-color: #0366d6;
    border: none;
    border-radius: 4px;
    cursor: pointer;
}

button:hover {
    background-color: #0256b9;
}

.highlight {
    background-color: #f6f8fa;
    padding: 16px;
    border: 1px solid #e1e4e8;
    border-radius: 6px;
    margin-top: 20px;
    overflow-x: auto;
}

.paste-meta {
    margin: 10px 0;
    padding: 10px;
    background-color: #f1f8ff;
    border: 1px solid #c8e1ff;
    border-radius: 4px;
    font-size: 0.9em;
}

.paste-meta code {
    background-color: #e1e4e8;
    padding: 2px 6px;
    border-radius: 3px;
    font-family: monospace;
}

.flashes {
    list-style: none;
    padding: 0;
    margin-bottom: 20px;
}

.flashes li {
    padding: 12px 16px;
    border-radius: 4px;
    margin-bottom: 10px;
}

.flashes li.error {
    color: #721c24;
    background-color: #f8d7da;
    border: 1px solid #f5c6cb;
}

.flashes li.success {
    color: #155724;
    background-color: #d4edda;
    border: 1px solid #c3e6cb;
}

a {
    color: #0366d6;
    text-decoration: none;
}

a:hover {
    text-decoration: underline;
}

footer {
    margin-top: 40px;
    padding-top: 20px;
    border-top: 1px solid #eee;
    text-align: center;
    color: #666;
}
```

---

## 5. セキュリティ対策の解説

### 5.1 パストラバーサル（Path Traversal）防止

```python
VALID_PASTE_ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
```

URL から取得した `paste_id` をファイルパスに使う前に、正規表現で検証しています。長さを 64 文字に制限することで、異常に長いパスを排除します。

### 5.2 UTF-8 エンコーディングの明示

```python
with open(file_path, "x", encoding="utf-8") as f:
```

すべてのファイル入出力で `encoding="utf-8"` を明示し、日本語テキストの文字化けを防ぎます。

### 5.3 CSRF 対策

```python
def get_csrf_token():
    token = session.get("csrf_token")
    if token is None:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token
```

- セッショに紐づいたトークンを生成
- 「なければ作る」方式で複数タブに対応
- フォーム送信時に検証

### 5.4 サイズ制限

```python
MAX_PASTE_BYTES = 512 * 1024
app.config["MAX_CONTENT_LENGTH"] = MAX_PASTE_BYTES + 16 * 1024
```

- Flask 組み込みの `MAX_CONTENT_LENGTH` で HTTP レベルで制限
- `MAX_PASTE_BYTES` でアプリケーションレベルでも検証
- 本文サイズと HTTP リクエスト全体のサイズを分離

### 5.5 ID 衝突対策

```python
def generate_unique_paste_id():
    for _ in range(10):
        paste_id = shortuuid.uuid()
        file_path = os.path.join(PASTE_DIR, paste_id)
        if not os.path.isfile(file_path):
            return paste_id, file_path
```

```python
with open(file_path, "x", encoding="utf-8") as f:
```

- `isfile()` で重複チェック
- `"x"` モード（排他作成）で既存ファイル上書きを防止

### 5.6 ファイル存在確認の厳密化

```python
if not os.path.isfile(file_path):
    abort(404)
```

`os.path.exists()` ではなく `os.path.isfile()` を使用し、ディレクトリ名と同名の ID での誤動作を防ぎます。

### 5.7 Pygments 言語のフォールバック

```python
def sanitize_language(language):
    if language in get_allowed_language_codes():
        return language
    return "text"
```

許可リストにない言語は `"text"` に正規化し、不正な値での 500 エラーを防ぎます。

### 5.8 PRG パターン（Post/Redirect/Get）

```python
return redirect(url_for("view_paste", paste_id=paste_id))
```

作成後にリダイレクトすることで、ブラウザの再読み込みによる二重送信を防ぎます。

### 5.9 保存パスの絶対パス化

```python
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PASTE_DIR = os.path.join(BASE_DIR, "pastes")
```

スクリプトの実行ディレクトリに依存せず、確実に正しい場所に保存されます。

### 5.10 SECRET_KEY の必須化

```python
app.secret_key = os.environ.get("FLASK_SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("環境変数 FLASK_SECRET_KEY が設定されていません。")
```

デフォルト値を持たせず、未設定の場合は起動時にエラーを発生させます。これにより、本番環境で弱い秘密鍵が使われる事故を防ぎます。

### 5.11 Pygments の処理負荷について

512KB のペーストでも Pygments のシンタックスハイライト処理は CPU・メモリを消費します。公開サービスとして大量アクセスを受ける場合、以下の対策を検討してください。

- ハイライト結果をキャッシュする
- 非同期ジョブキューで処理を分離する
- サイズ上限をさらに下げる

PoC（概念実証）としての利用であれば、現状の構成で十分です。

---

## 6. 起動方法

### 6.1 環境変数の設定

```bash
export FLASK_SECRET_KEY="$(openssl rand -hex 32)"
```

### 6.2 アプリケーションの起動

```bash
python app.py
```

ブラウザで `http://127.0.0.1:5000` を開きます。

---

## 7. 本番運用時の注意

### 7.1 本番サーバーの使用

```bash
pip install gunicorn
gunicorn -w 4 -b 127.0.0.1:8000 app:app
```

### 7.2 HTTPS の利用

Let's Encrypt 等で SSL 証明書を取得し、HTTPS で運用してください。

---

## 8. まとめ

この Pastebin は以下の特徴を持ちます。

| 項目 | 対応状況 |
|------|----------|
| パストラバーサル防止 | 正規表現＋長さ制限による ID 検証 |
| UTF-8 対応 | 全ファイル入出力で明示 |
| CSRF 対策 | セッション連携トークン |
| サイズ制限 | HTTP / アプリケーション 両ベル |
| ID 衝突防止 | isfile() チェック＋排他作成 |
| 言語フォールバック | 許可リスト + "text" 代替 |
| PRG パターン | 二重送信防止 |
| 絶対パス保存 | 実行ディレクトリ非依存 |
| SECRET_KEY 必須化 | デフォルト値なし、未設定時は起動拒否 |
| debug=False | 本番向け設定 |

---

*このチュートリアルは「最小構成でありながらセキュリティを意識した Pastebin」として、Flask の入門教材として利用できます。*
