import logging
import threading
from datetime import datetime
from typing import Callable, Dict, List, Optional

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import (
    CATEGORIES,
    CATEGORY_AI,
    CATEGORY_SPORTS,
    DATA_DIR,
    PLATFORMS,
    POLL_INTERVAL_MINUTES,
    TIMEZONE,
    USER_AGENT,
)
from pushplus import build_push_title, send_report_with_retry
from reporter import generate_evening_report, generate_morning_report
from scraper import HotItem, fetch_ai_category_modules, fetch_all_platforms
from storage import Storage
from timezone_utils import get_tz

logger = logging.getLogger(__name__)

PollCallback = Callable[[Dict[str, Dict[str, List[HotItem]]], datetime], None]


class HotListMonitor:
    def __init__(self, on_poll_complete: Optional[PollCallback] = None) -> None:
        self.storage = Storage()
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.tz = get_tz()
        self.scheduler = BackgroundScheduler(timezone=self.tz)
        self.on_poll_complete = on_poll_complete
        self._poll_lock = threading.Lock()
        self._ai_platforms: Dict[str, dict] = {}

    @property
    def ai_platforms(self) -> Dict[str, dict]:
        return dict(self._ai_platforms)

    def _record_category_results(
        self,
        results: Dict[str, List[HotItem]],
        platforms: Dict[str, dict],
        category: str,
        polled_at: datetime,
    ) -> int:
        total = 0
        for platform_key, items in results.items():
            if not items:
                name = platforms.get(platform_key, {}).get("name", platform_key)
                logger.warning("No items for %s", name)
                continue
            count = self.storage.record_poll(
                platform_key, items, polled_at, category=category
            )
            total += count
            logger.info(
                "Recorded %d items for %s",
                count,
                platforms[platform_key]["name"],
            )
        return total

    def poll_once(self) -> Dict[str, Dict[str, List[HotItem]]]:
        with self._poll_lock:
            now = datetime.now(self.tz)
            logger.info("Starting poll at %s", now.strftime("%Y-%m-%d %H:%M:%S"))

            sports_results = fetch_all_platforms(session=self.session)
            sports_total = self._record_category_results(
                sports_results, PLATFORMS, CATEGORY_SPORTS, now
            )

            ai_platforms, ai_results = fetch_ai_category_modules(session=self.session)
            if ai_platforms:
                self._ai_platforms = ai_platforms
            ai_total = self._record_category_results(
                ai_results,
                self._ai_platforms,
                CATEGORY_AI,
                now,
            )

            removed = self.storage.cleanup_old_records()
            if removed:
                logger.info("Cleaned up %d old records", removed)

            logger.info(
                "Poll complete, %d sports + %d ai records written",
                sports_total,
                ai_total,
            )

            results_by_category = {
                CATEGORY_SPORTS: sports_results,
                CATEGORY_AI: ai_results,
            }

            if self.on_poll_complete:
                self.on_poll_complete(results_by_category, now)

            return results_by_category

    def _run_category_report(self, report_fn, label: str) -> None:
        for category in (CATEGORY_SPORTS, CATEGORY_AI):
            platforms = (
                PLATFORMS if category == CATEGORY_SPORTS else self._ai_platforms
            )
            if category == CATEGORY_AI and not platforms:
                logger.warning("Skipping %s report: no AI platforms loaded", label)
                continue

            prefix = CATEGORIES[category]["push_prefix"]
            content = report_fn(self.storage, category, platforms)
            logger.info("%s %s report written (%d chars)", prefix, label, len(content))
            title = build_push_title(prefix, f"{label}", content)
            ok = send_report_with_retry(title, content, session=self.session)
            if ok:
                logger.info("Report push delivered: %s", title)
            else:
                logger.error("Report push failed after retries: %s", title)

    def run_evening_report(self) -> None:
        logger.info("Generating evening reports")
        self._run_category_report(generate_evening_report, "晚间报告 (18:30)")

    def run_morning_report(self) -> None:
        logger.info("Generating morning reports")
        self._run_category_report(generate_morning_report, "晨间报告 (08:30)")

    def start(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        self.scheduler.add_job(
            self.poll_once,
            trigger=IntervalTrigger(minutes=POLL_INTERVAL_MINUTES),
            id="poll_job",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.add_job(
            self.run_evening_report,
            trigger=CronTrigger(hour=18, minute=30),
            id="evening_report_job",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.add_job(
            self.run_morning_report,
            trigger=CronTrigger(hour=8, minute=30),
            id="morning_report_job",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        self.scheduler.start()
        logger.info(
            "Scheduler started: poll every %d min, reports at 08:30 and 18:30 (%s)",
            POLL_INTERVAL_MINUTES,
            TIMEZONE,
        )

        self.poll_once()

    def stop(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        self.session.close()
        logger.info("Monitor stopped")
