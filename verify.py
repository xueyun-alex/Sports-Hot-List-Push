"""One-shot verification: poll once, generate both report types."""

import argparse
import logging
import sys
from datetime import datetime
from typing import Tuple

from config import CATEGORIES, CATEGORY_AI, CATEGORY_SPORTS, DATA_DIR, PLATFORMS
from reporter import (
    generate_evening_report,
    generate_morning_report,
    parse_report_metadata,
    read_latest_report_block,
)
from scraper import HotItem, fetch_ai_category_modules, fetch_all_platforms
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


def _seed_mock_data(
    storage: Storage,
    polled_at: datetime,
    category: str,
    platform_keys: Tuple[str, ...],
) -> None:
    mock_items = [
        HotItem(1, "测试条目A", "https://example.com/a"),
        HotItem(2, "测试条目B", "https://example.com/b"),
    ]
    for key in platform_keys:
        storage.record_poll(key, mock_items, polled_at, category=category)


def test_poll_and_report(use_live_fetch: bool = True) -> Tuple[str, str]:
    test_db = DATA_DIR / "test_records.db"
    test_sports_report = DATA_DIR / "test_hotlist_report.txt"
    test_ai_report = DATA_DIR / "test_ai_hotlist_report.txt"

    for path in (test_db, test_sports_report, test_ai_report):
        if path.exists():
            path.unlink()

    storage = Storage(db_path=test_db)
    tz = get_tz()
    now = datetime.now(tz)

    ai_platforms: dict = {}
    if use_live_fetch:
        sports_results = fetch_all_platforms()
        for platform_key, items in sports_results.items():
            if items:
                storage.record_poll(
                    platform_key, items, now, category=CATEGORY_SPORTS
                )
                logger.info("Sports %s: %d items", platform_key, len(items))

        ai_platforms, ai_results = fetch_ai_category_modules()
        for platform_key, items in ai_results.items():
            if items:
                storage.record_poll(
                    platform_key, items, now, category=CATEGORY_AI
                )
                logger.info("AI %s: %d items", platform_key, len(items))

        if ai_platforms:
            logger.info("AI modules discovered: %d", len(ai_platforms))

    sports_count = storage.count_appearances(category=CATEGORY_SPORTS)
    ai_count = storage.count_appearances(category=CATEGORY_AI)
    if sports_count == 0:
        logger.warning("Using mock sports data")
        _seed_mock_data(
            storage,
            now,
            CATEGORY_SPORTS,
            tuple(PLATFORMS.keys()),
        )
    if ai_count == 0:
        logger.warning("Using mock AI data")
        _seed_mock_data(
            storage,
            now,
            CATEGORY_AI,
            ("ai_mock_module",),
        )
        ai_platforms = {"ai_mock_module": {"name": "测试AI模块"}}

    if not ai_platforms:
        ai_platforms = {"ai_mock_module": {"name": "测试AI模块"}}

    evening_sports = generate_evening_report(
        storage,
        CATEGORY_SPORTS,
        PLATFORMS,
        now=now,
        report_file=test_sports_report,
    )
    evening_ai = generate_evening_report(
        storage,
        CATEGORY_AI,
        ai_platforms,
        now=now,
        report_file=test_ai_report,
    )
    morning_sports = generate_morning_report(
        storage,
        CATEGORY_SPORTS,
        PLATFORMS,
        now=now.replace(hour=8, minute=30),
        report_file=test_sports_report,
    )
    morning_ai = generate_morning_report(
        storage,
        CATEGORY_AI,
        ai_platforms,
        now=now.replace(hour=8, minute=30),
        report_file=test_ai_report,
    )

    for content in (evening_sports, evening_ai, morning_sports, morning_ai):
        assert "全站综合 Top5" in content

    assert test_sports_report.exists()
    assert test_ai_report.exists()
    sports_content = test_sports_report.read_text(encoding="utf-8")
    ai_content = test_ai_report.read_text(encoding="utf-8")
    assert "晚间报告" in sports_content
    assert "分类: AI" in ai_content

    logger.info("Sports report: %s (%d bytes)", test_sports_report, len(sports_content))
    logger.info("AI report: %s (%d bytes)", test_ai_report, len(ai_content))
    logger.info("Database at %s", test_db)
    return evening_sports, evening_ai


def test_read_latest_report_block() -> None:
    test_sports_report = DATA_DIR / "test_hotlist_report.txt"
    test_ai_report = DATA_DIR / "test_ai_hotlist_report.txt"
    if not test_sports_report.is_file() or not test_ai_report.is_file():
        raise RuntimeError(
            "test_read_latest_report_block requires test_poll_and_report output"
        )

    sports_block = read_latest_report_block(test_sports_report)
    ai_block = read_latest_report_block(test_ai_report)
    assert sports_block is not None
    assert ai_block is not None
    assert "报告类型:" in sports_block
    assert "分类: AI" in ai_block

    sports_type, sports_cat = parse_report_metadata(sports_block)
    ai_type, ai_cat = parse_report_metadata(ai_block)
    assert "晨间报告" in sports_type
    assert sports_cat == "体育"
    assert "晨间报告" in ai_type
    assert ai_cat == "AI"

    assert read_latest_report_block(DATA_DIR / "nonexistent_report.txt") is None
    logger.info("read_latest_report_block OK")


def test_push(evening_report: str, prefix: str) -> None:
    from pushplus import build_push_title, send_report

    title = build_push_title(prefix, "晚间报告 (18:30)", evening_report)
    if send_report(title, evening_report) is None:
        raise RuntimeError("PushPlus push failed")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify hotlist monitor")
    parser.add_argument(
        "--push",
        action="store_true",
        help="After verification, send sports and AI evening reports via PushPlus",
    )
    parser.add_argument(
        "--no-live-fetch",
        action="store_true",
        help="Skip live TopHub fetch (use mock data only)",
    )
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    test_window_logic()
    evening_sports, evening_ai = test_poll_and_report(
        use_live_fetch=not args.no_live_fetch
    )
    test_read_latest_report_block()
    if args.push:
        test_push(evening_sports, CATEGORIES[CATEGORY_SPORTS]["push_prefix"])
        test_push(evening_ai, CATEGORIES[CATEGORY_AI]["push_prefix"])
        logger.info("PushPlus test pushes sent (sports + AI)")
    logger.info("All verification checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
