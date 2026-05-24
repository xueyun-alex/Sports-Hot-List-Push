from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
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
