"""SQLite接続の一元管理。

DBファイルのパスは環境変数 BBS_DB_PATH で変更できる（既定: ./bbs.db）。

スレッドごとに別の接続を持つ（threading.local）。1本の sqlite3.Connection を
複数スレッドで本当に同時に使うと、check_same_thread=False で例外は出なくなるが、
内部状態の競合で "bad parameter or other API misuse" のような実行時エラーが
不定期に発生する。FastAPIの同期エンドポイントはスレッドプールで実行されるため、
この対策は本番運用（gunicorn + 複数ワーカー/スレッド）では必須。
"""
import os
import sqlite3
import threading
from typing import Optional

DEFAULT_DB_PATH = "bbs.db"


class Database:
    _local = threading.local()
    _setup_lock = threading.Lock()
    _setup_done = False
    write_lock = threading.RLock()  # execute + commit + lastrowid をひとまとめにする（プロセス内）

    @classmethod
    def get_instance(cls) -> sqlite3.Connection:
        db = getattr(cls._local, "connection", None)
        if db is None:
            path = os.environ.get("BBS_DB_PATH", DEFAULT_DB_PATH)
            db = sqlite3.connect(path, check_same_thread=True)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA busy_timeout = 5000")  # 書き込み競合時に即エラーにせず少し待つ
            cls._ensure_schema(db)
            cls._local.connection = db
        return db

    @classmethod
    def _ensure_schema(cls, db: sqlite3.Connection) -> None:
        """テーブル・インデックスの作成は、プロセス内で一度だけ行う。"""
        if cls._setup_done:
            return
        with cls._setup_lock:
            if cls._setup_done:
                return
            cls._setup(db)
            cls._setup_done = True

    @classmethod
    def _setup(cls, db: sqlite3.Connection) -> None:
        db.execute("PRAGMA journal_mode = WAL")

        db.execute("""
            CREATE TABLE IF NOT EXISTS bbs_threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
                FOREIGN KEY (thread_id) REFERENCES bbs_threads(id)
            )
        """)

        # スレッド内の並べ替えとキーセットページネーションを支えるインデックス
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_posts_thread_created
            ON posts(thread_id, created_at, id)
        """)

        db.commit()

    @classmethod
    def close(cls) -> None:
        """呼び出したスレッド自身の接続を閉じる（全スレッド分を横断しては閉じない）。"""
        db = getattr(cls._local, "connection", None)
        if db is not None:
            db.close()
            cls._local.connection = None

    @classmethod
    def reset_for_tests(cls) -> None:
        """テスト専用: 次の get_instance() でスキーマを作り直させる。

        BBS_DB_PATH を切り替えるテストのために、_setup_done フラグを倒す。
        通常のアプリ実行では使わない。
        """
        cls.close()
        with cls._setup_lock:
            cls._setup_done = False
