from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config import CATEGORIES, PLATFORMS, TOP_N_REPORT

REPORT_BLOCK_SEPARATOR = "=" * 50
from storage import CountResult, Storage, evening_report_window, morning_report_window
from timezone_utils import get_tz


def _format_dt(dt: datetime) -> str:
    tz = get_tz()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    else:
        dt = dt.astimezone(tz)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _platform_display_name(platform_key: str, platforms: Dict[str, dict]) -> str:
    return platforms.get(platform_key, {}).get("name", platform_key)


def _format_item_line(
    index: int,
    item: CountResult,
    platforms: Dict[str, dict],
    show_platform: bool = False,
) -> str:
    platform_tag = (
        f"[{_platform_display_name(item.platform, platforms)}] "
        if show_platform
        else ""
    )
    title_line = f"{index}. ({item.count}次) {platform_tag}{item.title}"
    if item.url:
        return f"链接: {item.url}\n{title_line}"
    return title_line


def _format_section(
    title: str,
    items: List[CountResult],
    platforms: Dict[str, dict],
    show_platform: bool = False,
) -> str:
    lines = [f"【{title}】"]
    if not items:
        lines.append("（暂无数据）")
        return "\n".join(lines)

    item_lines = [
        _format_item_line(index, item, platforms, show_platform=show_platform)
        for index, item in enumerate(items, start=1)
    ]
    lines.append("\n---\n".join(item_lines))
    return "\n".join(lines)


def build_report(
    storage: Storage,
    window: Tuple[datetime, datetime, str],
    report_type: str,
    category: str,
    platforms: Dict[str, dict],
    top_n_report: int = TOP_N_REPORT,
) -> str:
    start, end, duration_label = window
    poll_count = storage.count_polls_in_window(start, end, category=category)
    category_label = CATEGORIES[category]["label"]

    sections = [
        "=" * 50,
        f"报告类型: {report_type}",
        f"分类: {category_label}",
        f"报告时间: {_format_dt(end)}",
        f"统计窗口: {_format_dt(start)} ~ {_format_dt(end)} ({duration_label})",
        f"采集轮次: {poll_count} 次",
        "",
    ]

    for platform_key in platforms:
        platform_items = storage.count_in_window(
            start,
            end,
            platform_key=platform_key,
            limit=top_n_report,
            category=category,
        )
        sections.append(
            _format_section(
                _platform_display_name(platform_key, platforms) + " Top5",
                platform_items,
                platforms,
            )
        )
        sections.append("")

    global_items = storage.count_global_in_window(
        start, end, limit=top_n_report, category=category
    )
    sections.append(
        _format_section("全站综合 Top5", global_items, platforms, show_platform=True)
    )
    sections.append("=" * 50)
    sections.append("")
    return "\n".join(sections)


def parse_report_metadata(content: str) -> Tuple[str, str]:
    """Return (report_type_label, category_label) from a report block."""
    report_type = ""
    category_label = ""
    for line in content.splitlines():
        if line.startswith("报告类型:"):
            report_type = line.split(":", 1)[1].strip()
        elif line.startswith("分类:"):
            category_label = line.split(":", 1)[1].strip()
        if report_type and category_label:
            break
    return report_type, category_label


def read_latest_report_block(report_file: Path) -> Optional[str]:
    if not report_file.is_file():
        return None

    raw = report_file.read_text(encoding="utf-8")
    if not raw.strip():
        return None

    blocks = raw.split(REPORT_BLOCK_SEPARATOR)
    for block in reversed(blocks):
        block = block.strip()
        if not block or "报告类型:" not in block:
            continue
        return f"{REPORT_BLOCK_SEPARATOR}\n{block}\n{REPORT_BLOCK_SEPARATOR}\n"

    return None


def write_report(content: str, report_file: Optional[Path] = None) -> None:
    target = report_file or CATEGORIES["sports"]["report_file"]
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(content)


def generate_evening_report(
    storage: Storage,
    category: str,
    platforms: Dict[str, dict],
    now: Optional[datetime] = None,
    report_file: Optional[Path] = None,
) -> str:
    now = now or datetime.now(get_tz())
    window = evening_report_window(now)
    content = build_report(
        storage,
        window,
        report_type="晚间报告 (18:30)",
        category=category,
        platforms=platforms,
    )
    target = report_file or CATEGORIES[category]["report_file"]
    write_report(content, report_file=target)
    return content


def generate_morning_report(
    storage: Storage,
    category: str,
    platforms: Dict[str, dict],
    now: Optional[datetime] = None,
    report_file: Optional[Path] = None,
) -> str:
    now = now or datetime.now(get_tz())
    window = morning_report_window(now)
    content = build_report(
        storage,
        window,
        report_type="晨间报告 (08:30)",
        category=category,
        platforms=platforms,
    )
    target = report_file or CATEGORIES[category]["report_file"]
    write_report(content, report_file=target)
    return content
