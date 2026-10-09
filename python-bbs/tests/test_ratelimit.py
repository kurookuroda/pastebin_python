import time

import pytest

from models import BbsThread
from ratelimit import FixedWindowLimiter, get_client_ip


def test_limiter_allows_up_to_the_limit_then_blocks():
    limiter = FixedWindowLimiter(limit=3, window_seconds=60)
    for _ in range(3):
        limiter.hit("1.2.3.4")  # raises on failure
    with pytest.raises(Exception) as exc_info:
        limiter.hit("1.2.3.4")
    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers


def test_limiter_is_per_key():
    limiter = FixedWindowLimiter(limit=1, window_seconds=60)
    limiter.hit("a")
    limiter.hit("b")  # different key, independent budget


def test_limiter_resets_after_window():
    limiter = FixedWindowLimiter(limit=1, window_seconds=0.05)
    limiter.hit("x")
    time.sleep(0.07)
    limiter.hit("x")  # window elapsed, should not raise


def test_purge_expired_drops_old_and_keeps_recent():
    limiter = FixedWindowLimiter(limit=5, window_seconds=0.05)
    limiter.hit("old")
    time.sleep(0.12)
    limiter.hit("fresh")
    limiter.purge_expired()
    assert "old" not in limiter._buckets
    assert "fresh" in limiter._buckets


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    def __init__(self, headers=None, client_host="10.0.0.1"):
        self.headers = headers or {}
        self.client = _FakeClient(client_host) if client_host else None


def test_get_client_ip_prefers_cf_connecting_ip_header():
    req = _FakeRequest(headers={"CF-Connecting-IP": "203.0.113.5"}, client_host="127.0.0.1")
    assert get_client_ip(req) == "203.0.113.5"


def test_get_client_ip_falls_back_to_socket_peer():
    req = _FakeRequest(headers={}, client_host="192.0.2.9")
    assert get_client_ip(req) == "192.0.2.9"


def test_get_client_ip_handles_missing_client():
    req = _FakeRequest(headers={}, client_host=None)
    assert get_client_ip(req) == "unknown"


def test_thread_creation_rate_limited_via_http(client):
    for i in range(3):
        r = client.post("/thread", data={"title": f"連投テスト{i}"})
        assert r.status_code == 303
    r = client.post("/thread", data={"title": "4通目"})
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_post_creation_rate_limited_via_http(client):
    thread_id = BbsThread.create("レート制限確認用")
    for i in range(10):
        r = client.post(f"/thread/{thread_id}/post", data={"body": f"れす{i}"})
        assert r.status_code == 303
    r = client.post(f"/thread/{thread_id}/post", data={"body": "11通目"})
    assert r.status_code == 429


def test_rate_limit_is_per_ip_via_cf_connecting_ip_header(client):
    thread_id = BbsThread.create("IP別レート制限確認用")
    for i in range(10):
        client.post(f"/thread/{thread_id}/post", data={"body": f"A{i}"})
    # 別IP（CF-Connecting-IPヘッダ）を名乗れば、別バケットとして扱われる
    r = client.post(
        f"/thread/{thread_id}/post",
        data={"body": "別IPから"},
        headers={"CF-Connecting-IP": "203.0.113.77"},
    )
    assert r.status_code == 303
