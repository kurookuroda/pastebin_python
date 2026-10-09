"""表示用のフォーマット処理（テンプレートのフィルタ）。"""
import logging
from datetime import datetime, timezone, tzinfo
from typing import Callable, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

WEEKDAYS = "月火水木金土日"
DB_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


def load_timezone(name: str) -> Tuple[tzinfo, str]:
    """タイムゾーン名から (tzinfo, 表示用ラベル) を返す。見つからなければUTC。"""
    try:
        return ZoneInfo(name), name
    except Exception:
        logger.warning("タイムゾーン %r を読み込めないため UTC で表示します（Windowsでは `pip install tzdata` が必要です）", name)
        return timezone.utc, "UTC"


def make_display_dt(tz: tzinfo) -> Callable[[str], str]:
    """DBのUTC日時文字列を「2026/10/09(金) 21:34:56」形式に変換するフィルタを作る。"""

    def display_dt(value: str) -> str:
        try:
            dt = datetime.strptime(value, DB_DATETIME_FORMAT).replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return value  # 想定外の形式はそのまま表示する
        dt = dt.astimezone(tz)
        return f"{dt:%Y/%m/%d}({WEEKDAYS[dt.weekday()]}) {dt:%H:%M:%S}"

    return display_dt
