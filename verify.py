"""One-shot verification: poll once, generate both report types."""

import argparse
import logging
import sys
from datetime import datetime
from typing import Tuple

from config import DATA_DIR
from reporter import generate_evening_report, generate_morning_report
from scraper import HotItem, fetch_all_platforms
from storage import Storage, evening_report_window, morning_report_window
from timezone_utils import get_tz

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("verify")


def test_window_logic() -> None:
    tz = get_tz()
    evening_now = datetime(2026, 5, 24, 18, 30, tzinfo=tz)
    morning_now = datetime(2026, 5, 25, 8, 30, tzinfo=tz)

    e_start, e_end, e_label = evening_report_window(evening_now)
    m_start, m_end, m_label = morning_report_window(morning_now)

    assert e_label == "10小时"
    assert e_start.hour == 8 and e_start.minute == 30
    assert e_end.hour == 18 and e_end.minute == 30

    assert m_label == "14小时"
    assert m_start.day == 24 and m_start.hour == 18 and m_start.minute == 30
    assert m_end.day == 25 and m_end.hour == 8 and m_end.minute == 30

    logger.info("Window logic OK")


def _seed_mock_data(storage: Storage, polled_at: datetime) -> None:
    mock_items = [
        HotItem(1, "测试条目A", "https://example.com/a"),
        HotItem(2, "测试条目B", "https://example.com/b"),
    ]
    for key in ("sina_sports", "douyin_sports", "hupu_nba", "dongqiudi"):
        storage.record_poll(key, mock_items, polled_at)


def test_poll_and_report(use_live_fetch: bool = True) -> Tuple[str, str]:
    test_db = DATA_DIR / "test_records.db"
    test_report = DATA_DIR / "test_hotlist_report.txt"

    for path in (test_db, test_report):
        if path.exists():
            path.unlink()

    storage = Storage(db_path=test_db)
    tz = get_tz()
    now = datetime.now(tz)

    total = 0
    if use_live_fetch:
        results = fetch_all_platforms()
        for platform_key, items in results.items():
            if items:
                total += storage.record_poll(platform_key, items, now)
                logger.info("Platform %s: %d items", platform_key, len(items))

    if total == 0:
        logger.warning("Using mock data")
        _seed_mock_data(storage, now)

    evening = generate_evening_report(storage, now=now, report_file=test_report)
    morning = generate_morning_report(
        storage,
        now=now.replace(hour=8, minute=30),
        report_file=test_report,
    )

    assert "全站综合 Top5" in evening
    assert "全站综合 Top5" in morning
    assert test_report.exists()
    content = test_report.read_text(encoding="utf-8")
    assert "晚间报告" in content
    assert "晨间报告" in content

    logger.info("Report file written to %s (%d bytes)", test_report, len(content))
    logger.info("Database at %s", test_db)
    return evening, morning


def test_push(evening_report: str) -> None:
    from pushplus import build_push_title, send_report

    title = build_push_title("晚间报告 (18:30)", evening_report)
    if not send_report(title, evening_report):
        raise RuntimeError("PushPlus push failed")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify hotlist monitor")
    parser.add_argument(
        "--push",
        action="store_true",
        help="After verification, send evening report via PushPlus",
    )
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    test_window_logic()
    evening, _morning = test_poll_and_report(use_live_fetch=True)
    if args.push:
        test_push(evening)
        logger.info("PushPlus test push sent")
    logger.info("All verification checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
