try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

from config import TIMEZONE


def get_tz() -> ZoneInfo:
    return ZoneInfo(TIMEZONE)
