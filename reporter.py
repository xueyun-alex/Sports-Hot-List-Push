from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from config import PLATFORMS, REPORT_FILE, TOP_N_REPORT
from storage import CountResult, Storage, evening_report_window, morning_report_window
from timezone_utils import get_tz


def _format_dt(dt: datetime) -> str:
    tz = get_tz()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    else:
        dt = dt.astimezone(tz)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _platform_display_name(platform_key: str) -> str:
    return PLATFORMS.get(platform_key, {}).get("name", platform_key)


def _format_item_line(index: int, item: CountResult, show_platform: bool = False) -> str:
    platform_tag = f"[{_platform_display_name(item.platform)}] " if show_platform else ""
    url_part = f"\n   链接: {item.url}" if item.url else ""
    return f"{index}. ({item.count}次) {platform_tag}{item.title}{url_part}"


def _format_section(title: str, items: List[CountResult], show_platform: bool = False) -> str:
    lines = [f"【{title}】"]
    if not items:
        lines.append("（暂无数据）")
        return "\n".join(lines)

    for index, item in enumerate(items, start=1):
        lines.append(_format_item_line(index, item, show_platform=show_platform))
    return "\n".join(lines)


def build_report(
    storage: Storage,
    window: Tuple[datetime, datetime, str],
    report_type: str,
) -> str:
    start, end, duration_label = window
    poll_count = storage.count_polls_in_window(start, end)

    sections = [
        "=" * 50,
        f"报告类型: {report_type}",
        f"报告时间: {_format_dt(end)}",
        f"统计窗口: {_format_dt(start)} ~ {_format_dt(end)} ({duration_label})",
        f"采集轮次: {poll_count} 次",
        "",
    ]

    for platform_key in PLATFORMS:
        platform_items = storage.count_in_window(
            start,
            end,
            platform_key=platform_key,
            limit=TOP_N_REPORT,
        )
        sections.append(
            _format_section(_platform_display_name(platform_key) + " Top5", platform_items)
        )
        sections.append("")

    global_items = storage.count_global_in_window(start, end, limit=TOP_N_REPORT)
    sections.append(_format_section("全站综合 Top5", global_items, show_platform=True))
    sections.append("=" * 50)
    sections.append("")
    return "\n".join(sections)


def write_report(content: str, report_file: Optional[Path] = None) -> None:
    target = report_file or REPORT_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(content)


def generate_evening_report(
    storage: Storage,
    now: Optional[datetime] = None,
    report_file: Optional[Path] = None,
) -> str:
    now = now or datetime.now(get_tz())
    window = evening_report_window(now)
    content = build_report(storage, window, report_type="晚间报告 (18:30)")
    write_report(content, report_file=report_file)
    return content


def generate_morning_report(
    storage: Storage,
    now: Optional[datetime] = None,
    report_file: Optional[Path] = None,
) -> str:
    now = now or datetime.now(get_tz())
    window = morning_report_window(now)
    content = build_report(storage, window, report_type="晨间报告 (08:30)")
    write_report(content, report_file=report_file)
    return content
