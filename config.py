import os
import sys
from pathlib import Path


def _resolve_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and (key not in os.environ or not os.environ[key].strip()):
            os.environ[key] = value


BASE_DIR = _resolve_base_dir()
_load_env_file(BASE_DIR / ".env")
DATA_DIR = BASE_DIR / "data"

PLATFORMS = {
    "sina_sports": {
        "name": "新浪体育新闻",
        "hashid": "wWmoOqYd4E",
    },
    "douyin_sports": {
        "name": "抖音体育榜",
        "hashid": "3adqqzadng",
    },
    "hupu_nba": {
        "name": "虎扑NBA热帖",
        "hashid": "6ARe1YLe7n",
    },
    "dongqiudi": {
        "name": "懂球帝今日头条",
        "hashid": "n3moBE1eN5",
    },
}

TOPHUB_BASE_URL = "https://tophub.today"
POLL_INTERVAL_MINUTES = 5
TOP_N_TRACK = 10
TOP_N_REPORT = 5
REPORT_FILE = DATA_DIR / "hotlist_report.txt"
DB_PATH = DATA_DIR / "records.db"
TIMEZONE = "Asia/Shanghai"
RETENTION_DAYS = 30

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

PUSHPLUS_TOKEN = os.getenv("PUSHPLUS_TOKEN", "").strip()
PUSHPLUS_SECRET_KEY = os.getenv("PUSHPLUS_SECRET_KEY", "").strip()
PUSHPLUS_CHANNEL = os.getenv("PUSHPLUS_CHANNEL", "clawbot").strip()
PUSHPLUS_API_URL = os.getenv(
    "PUSHPLUS_API_URL", "https://www.pushplus.plus/send"
).strip()
PUSHPLUS_ACCESS_KEY_URL = os.getenv(
    "PUSHPLUS_ACCESS_KEY_URL",
    "https://www.pushplus.plus/api/common/openApi/getAccessKey",
).strip()
PUSHPLUS_SEND_RESULT_URL = os.getenv(
    "PUSHPLUS_SEND_RESULT_URL",
    "https://www.pushplus.plus/api/open/message/sendMessageResult",
).strip()
_enabled = os.getenv("PUSHPLUS_ENABLED", "").strip().lower()
if _enabled in ("0", "false", "no"):
    PUSHPLUS_ENABLED = False
elif _enabled in ("1", "true", "yes"):
    PUSHPLUS_ENABLED = True
else:
    PUSHPLUS_ENABLED = bool(PUSHPLUS_TOKEN)

_verify = os.getenv("PUSHPLUS_VERIFY_ENABLED", "").strip().lower()
if _verify in ("0", "false", "no"):
    PUSHPLUS_VERIFY_ENABLED = False
elif _verify in ("1", "true", "yes"):
    PUSHPLUS_VERIFY_ENABLED = True
else:
    PUSHPLUS_VERIFY_ENABLED = bool(PUSHPLUS_SECRET_KEY)

PUSHPLUS_PUSH_MAX_RETRIES = max(
    1, int(os.getenv("PUSHPLUS_PUSH_MAX_RETRIES", "3"))
)
PUSHPLUS_VERIFY_POLL_INTERVAL = max(
    1, int(os.getenv("PUSHPLUS_VERIFY_POLL_INTERVAL", "5"))
)
PUSHPLUS_VERIFY_TIMEOUT = max(
    10, int(os.getenv("PUSHPLUS_VERIFY_TIMEOUT", "90"))
)
PUSHPLUS_RETRY_DELAY = max(
    1, int(os.getenv("PUSHPLUS_RETRY_DELAY", "10"))
)
