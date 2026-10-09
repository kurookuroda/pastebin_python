"""超単純なIPベースのレートリミッター（固定ウィンドウ）。

Cloudflareのレート制限ルール（エッジ側）が主な防御線で、これは二段目の保険。
プロセス内メモリに状態を持つだけなので、再起動で消え、複数workerとは状態を共有しない。
そのため gunicorn --workers N では、実質的な上限が N 倍になる点に注意（docs/deployment.md 参照）。
それで十分な小規模掲示板向け。厳密な上限が要るなら Redis 等に置き換える。
"""
import threading
import time
from typing import Dict, Tuple

from fastapi import HTTPException, Request


class FixedWindowLimiter:
    """`limit` 回 / `window_seconds` 秒 を超えたら 429 を返す。"""

    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._buckets: Dict[str, Tuple[int, float]] = {}  # key -> (count, window_start)

    def hit(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            count, window_start = self._buckets.get(key, (0, now))
            if now - window_start >= self.window_seconds:
                count, window_start = 0, now
            count += 1
            self._buckets[key] = (count, window_start)
            if count > self.limit:
                retry_after = max(0, int(self.window_seconds - (now - window_start)) + 1)
                raise HTTPException(
                    status_code=429,
                    detail="投稿が多すぎます。しばらく待ってから再度お試しください。",
                    headers={"Retry-After": str(retry_after)},
                )

    def reset(self) -> None:
        """全バケットを消す（主にテストでの状態分離のため）。"""
        with self._lock:
            self._buckets.clear()

    def purge_expired(self) -> None:
        """古いバケットを掃除する（メモリが際限なく増えないように）。"""
        now = time.monotonic()
        with self._lock:
            expired = [k for k, (_, start) in self._buckets.items() if now - start >= self.window_seconds * 2]
            for k in expired:
                del self._buckets[k]


def get_client_ip(request: Request) -> str:
    """クライアントの実IPを取り出す。

    前提: このアプリは直接インターネットに公開せず、Cloudflare Tunnel
    （cloudflared）だけがループバック経由で接続する構成（docs/deployment.md 参照）。
    その前提が崩れる経路（直接公開・別のリバースプロキシ経由など）では、
    'CF-Connecting-IP' を誰でも偽装できてしまう点に注意すること。
    """
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()
    if request.client:
        return request.client.host
    return "unknown"
