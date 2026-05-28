import logging
import threading
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

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
    PUSHPLUS_CMD_ENABLED,
    PUSHPLUS_CMD_POLL_SECONDS,
    PUSHPLUS_ENABLED,
    REPORT_COMMAND_TEXT,
    TIMEZONE,
    USER_AGENT,
)
from pushplus import (
    build_push_title,
    check_open_api_access,
    fetch_clawbot_inbound_messages,
    is_clawbot_inbound_available,
    is_report_command,
    send_report,
    send_report_with_retry,
)
from reporter import (
    generate_evening_report,
    generate_morning_report,
    parse_report_metadata,
    read_latest_report_block,
)
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
        self._report_lock = threading.Lock()
        self._ai_platforms: Dict[str, dict] = {}
        self._last_seen_clawbot_msgs: set = set()
        self._clawbot_cmd_access_warned = False

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
        with self._report_lock:
            self._run_category_report_unlocked(report_fn, label)

    def _run_category_report_unlocked(self, report_fn, label: str) -> None:
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

    def _pick_on_demand_report_fn(self, now: datetime):
        if now.hour < 8 or (now.hour == 8 and now.minute < 30):
            return generate_morning_report
        return generate_evening_report

    def _generate_fresh_report(self, category: str) -> Optional[str]:
        meta = CATEGORIES[category]
        platforms = (
            PLATFORMS if category == CATEGORY_SPORTS else self._ai_platforms
        )
        if category == CATEGORY_AI and not platforms:
            logger.warning(
                "On-demand report skipped for %s: no AI platforms loaded",
                meta["label"],
            )
            return None

        now = datetime.now(self.tz)
        report_fn = self._pick_on_demand_report_fn(now)
        logger.info(
            "No on-disk report for %s (%s), generating on demand",
            meta["label"],
            meta["report_file"],
        )
        return report_fn(self.storage, category, platforms, now=now)

    def resend_latest_reports(self) -> Tuple[int, List[str], List[str]]:
        """Return (sent_count, skipped_labels, generated_labels)."""
        sent = 0
        skipped: List[str] = []
        generated: List[str] = []

        with self._report_lock:
            for category in (CATEGORY_SPORTS, CATEGORY_AI):
                meta = CATEGORIES[category]
                report_file = meta["report_file"]
                content = read_latest_report_block(report_file)
                push_suffix = "手动重发"

                if not content:
                    content = self._generate_fresh_report(category)
                    if content:
                        generated.append(meta["label"])
                        push_suffix = "即时生成"

                if not content:
                    logger.warning(
                        "No report available for %s (%s)",
                        meta["label"],
                        report_file,
                    )
                    skipped.append(meta["label"])
                    continue

                report_label, _ = parse_report_metadata(content)
                if not report_label:
                    report_label = "最新简报"

                prefix = meta["push_prefix"]
                title = build_push_title(
                    prefix, f"{report_label} ({push_suffix})", content
                )
                ok = send_report_with_retry(
                    title, content, session=self.session
                )
                if ok:
                    sent += 1
                    logger.info("Manual resend delivered: %s", title)
                else:
                    logger.error("Manual resend failed after retries: %s", title)
                    skipped.append(meta["label"])

        return sent, skipped, generated

    def check_wechat_commands(self) -> None:
        if not PUSHPLUS_CMD_ENABLED or not PUSHPLUS_ENABLED:
            return

        if not is_clawbot_inbound_available():
            if not self._clawbot_cmd_access_warned:
                self._clawbot_cmd_access_warned = True
                _, detail = check_open_api_access(session=self.session)
                logger.error(
                    "WeChat command polling inactive: %s", detail
                )
            return

        messages = fetch_clawbot_inbound_messages(session=self.session)
        current = {(msg["type"], msg["text"]) for msg in messages}
        new_msgs = current - self._last_seen_clawbot_msgs
        self._last_seen_clawbot_msgs = current

        if not any(is_report_command(text) for _, text in new_msgs):
            return

        logger.info("WeChat report command received, resending latest reports")
        sent, skipped, generated = self.resend_latest_reports()

        ack_title = "体育热榜 | 指令确认"
        if sent == 0:
            ack_content = (
                "未能推送简报：尚无落盘报告且即时生成失败。"
                "请确认程序已采集到数据，或等待 08:30 / 18:30 定时报告。"
            )
            send_report(ack_title, ack_content, session=self.session)
        elif skipped:
            ack_content = (
                f"已推送 {sent} 条简报"
                + (f"（{', '.join(generated)} 为即时生成）" if generated else "")
                + f"；{', '.join(skipped)} 暂无数据已跳过。"
            )
            send_report(ack_title, ack_content, session=self.session)

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

        if PUSHPLUS_CMD_ENABLED:
            cmd_ok, cmd_detail = check_open_api_access(session=self.session)
            if cmd_ok:
                logger.info(cmd_detail)
            else:
                logger.error(
                    "ClawBot command polling will not work until open API is fixed: %s",
                    cmd_detail,
                )
            self.scheduler.add_job(
                self.check_wechat_commands,
                trigger=IntervalTrigger(seconds=PUSHPLUS_CMD_POLL_SECONDS),
                id="clawbot_cmd_job",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            logger.info(
                "ClawBot command polling scheduled every %ds (trigger: %r)",
                PUSHPLUS_CMD_POLL_SECONDS,
                REPORT_COMMAND_TEXT,
            )
        else:
            logger.info(
                "ClawBot command polling disabled "
                "(need PUSHPLUS_TOKEN, PUSHPLUS_SECRET_KEY, channel=clawbot)"
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
