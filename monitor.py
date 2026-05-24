import logging
import threading
from datetime import datetime
from typing import Callable, Dict, List, Optional

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import DATA_DIR, PLATFORMS, POLL_INTERVAL_MINUTES, TIMEZONE, USER_AGENT
from pushplus import build_push_title, send_report
from reporter import generate_evening_report, generate_morning_report
from scraper import HotItem, fetch_all_platforms
from storage import Storage
from timezone_utils import get_tz

logger = logging.getLogger(__name__)

PollCallback = Callable[[Dict[str, List[HotItem]], datetime], None]


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

    def poll_once(self) -> Dict[str, List[HotItem]]:
        with self._poll_lock:
            now = datetime.now(self.tz)
            logger.info("Starting poll at %s", now.strftime("%Y-%m-%d %H:%M:%S"))

            results = fetch_all_platforms(session=self.session)
            total = 0
            for platform_key, items in results.items():
                if not items:
                    logger.warning("No items for %s", PLATFORMS[platform_key]["name"])
                    continue
                count = self.storage.record_poll(platform_key, items, now)
                total += count
                logger.info(
                    "Recorded %d items for %s",
                    count,
                    PLATFORMS[platform_key]["name"],
                )

            removed = self.storage.cleanup_old_records()
            if removed:
                logger.info("Cleaned up %d old records", removed)

            logger.info("Poll complete, %d records written", total)

            if self.on_poll_complete:
                self.on_poll_complete(results, now)

            return results

    def run_evening_report(self) -> None:
        logger.info("Generating evening report")
        content = generate_evening_report(self.storage)
        logger.info("Evening report written (%d chars)", len(content))
        title = build_push_title("晚间报告 (18:30)", content)
        send_report(title, content, session=self.session)

    def run_morning_report(self) -> None:
        logger.info("Generating morning report")
        content = generate_morning_report(self.storage)
        logger.info("Morning report written (%d chars)", len(content))
        title = build_push_title("晨间报告 (08:30)", content)
        send_report(title, content, session=self.session)

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
