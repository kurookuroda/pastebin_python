import os
import pathlib
import tempfile

# main / database をimportする前に、テスト専用のDBを指定する
_tmp = tempfile.mkdtemp(prefix="bbs-test-")
os.environ["BBS_DB_PATH"] = str(pathlib.Path(_tmp) / "test.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from main import app, POST_LIMITER, THREAD_LIMITER  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    # レートリミッターはプロセス内グローバル状態なので、テスト間で引き継がれないようにする。
    THREAD_LIMITER.reset()
    POST_LIMITER.reset()
    yield


@pytest.fixture
def client():
    return TestClient(app, follow_redirects=False)
