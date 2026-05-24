import logging
import threading
import tkinter as tk
import webbrowser
from datetime import datetime, timedelta
from tkinter import ttk
from typing import Callable, Dict, List, Optional, Tuple

from config import PLATFORMS, POLL_INTERVAL_MINUTES
from monitor import HotListMonitor
from scraper import HotItem
from storage import AppearanceRecord, Storage
from timezone_utils import get_tz

logger = logging.getLogger(__name__)

FONT_FAMILY = "Microsoft YaHei"
FONT_NORMAL = (FONT_FAMILY, 10)
FONT_TITLE = (FONT_FAMILY, 11, "bold")
FONT_STATUS = (FONT_FAMILY, 9)

PLATFORM_LAYOUT = [
    ("sina_sports", "douyin_sports"),
    ("hupu_nba", "dongqiudi"),
]

TIME_RANGE_OPTIONS = ("今天", "最近24小时", "最近7天", "全部")
FETCH_LIMIT = 500


def _platform_display_name(platform_key: str) -> str:
    return PLATFORMS.get(platform_key, {}).get("name", platform_key)


def _format_polled_at(polled_at: str) -> str:
    try:
        dt = datetime.fromisoformat(polled_at)
        if dt.tzinfo is not None:
            dt = dt.astimezone(get_tz())
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return polled_at


def _compute_time_range(option: str) -> Tuple[Optional[datetime], Optional[datetime]]:
    tz = get_tz()
    now = datetime.now(tz)
    if option == "今天":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now
    if option == "最近24小时":
        return now - timedelta(hours=24), now
    if option == "最近7天":
        return now - timedelta(days=7), now
    return None, None


class PlatformPanel(ttk.LabelFrame):
    def __init__(self, master: tk.Misc, platform_key: str) -> None:
        super().__init__(master, text=PLATFORMS[platform_key]["name"], padding=4)
        self.platform_key = platform_key
        self._url_map: Dict[str, Optional[str]] = {}

        self.tree = ttk.Treeview(
            self,
            columns=("rank", "title"),
            show="headings",
            height=10,
            selectmode="browse",
        )
        self.tree.heading("rank", text="#")
        self.tree.heading("title", text="标题")
        self.tree.column("rank", width=36, anchor="center", stretch=False)
        self.tree.column("title", width=280, anchor="w")

        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        self._on_select_callback: Optional[Callable[[str], None]] = None

    def set_select_callback(self, callback: Callable[[str], None]) -> None:
        self._on_select_callback = callback

    def update_items(self, items: List[HotItem]) -> None:
        self.tree.delete(*self.tree.get_children())
        self._url_map.clear()

        if not items:
            item_id = self.tree.insert("", "end", values=("-", "暂无数据"))
            self._url_map[item_id] = None
            return

        for item in items:
            item_id = self.tree.insert("", "end", values=(item.rank, item.title))
            self._url_map[item_id] = item.url

    def _on_double_click(self, _event: tk.Event) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        url = self._url_map.get(selection[0])
        if url:
            webbrowser.open(url)

    def _on_select(self, _event: tk.Event) -> None:
        if not self._on_select_callback:
            return
        selection = self.tree.selection()
        if not selection:
            return
        values = self.tree.item(selection[0], "values")
        if len(values) >= 2 and values[1] != "暂无数据":
            self._on_select_callback(values[1])


class HistoryPanel(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        storage: Storage,
        on_select: Callable[[str], None],
        on_loading: Callable[[bool], None],
    ) -> None:
        super().__init__(master, padding=(8, 4, 8, 4))
        self.storage = storage
        self._on_select = on_select
        self._on_loading = on_loading
        self._url_map: Dict[str, Optional[str]] = {}
        self._loading = False
        self._loaded_once = False

        filter_bar = ttk.Frame(self)
        filter_bar.pack(fill="x", pady=(0, 4))

        ttk.Label(filter_bar, text="平台:", font=FONT_NORMAL).pack(side="left")
        self.platform_var = tk.StringVar(value="全部")
        platform_values = ["全部"] + [_platform_display_name(k) for k in PLATFORMS]
        self.platform_combo = ttk.Combobox(
            filter_bar,
            textvariable=self.platform_var,
            values=platform_values,
            state="readonly",
            width=16,
        )
        self.platform_combo.pack(side="left", padx=(4, 12))

        ttk.Label(filter_bar, text="时间:", font=FONT_NORMAL).pack(side="left")
        self.time_var = tk.StringVar(value="今天")
        self.time_combo = ttk.Combobox(
            filter_bar,
            textvariable=self.time_var,
            values=list(TIME_RANGE_OPTIONS),
            state="readonly",
            width=12,
        )
        self.time_combo.pack(side="left", padx=(4, 12))

        self.query_btn = ttk.Button(filter_bar, text="查询", command=self.query)
        self.query_btn.pack(side="left")

        table_frame = ttk.Frame(self)
        table_frame.pack(fill="both", expand=True)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            table_frame,
            columns=("id", "platform", "rank", "title", "polled_at"),
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("id", text="ID")
        self.tree.heading("platform", text="平台")
        self.tree.heading("rank", text="排名")
        self.tree.heading("title", text="标题")
        self.tree.heading("polled_at", text="采集时间")
        self.tree.column("id", width=48, anchor="center", stretch=False)
        self.tree.column("platform", width=110, anchor="w", stretch=False)
        self.tree.column("rank", width=48, anchor="center", stretch=False)
        self.tree.column("title", width=360, anchor="w")
        self.tree.column("polled_at", width=150, anchor="center", stretch=False)

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        self.summary_var = tk.StringVar(value="")
        ttk.Label(
            self,
            textvariable=self.summary_var,
            font=FONT_STATUS,
            anchor="w",
        ).pack(fill="x", pady=(4, 0))

    def on_tab_shown(self) -> None:
        if not self._loaded_once:
            self.query()

    def _platform_key_from_display(self, display: str) -> Optional[str]:
        if display == "全部":
            return None
        for key, info in PLATFORMS.items():
            if info["name"] == display:
                return key
        return None

    def query(self) -> None:
        if self._loading:
            return
        self._loading = True
        self._loaded_once = True
        self.query_btn.configure(state="disabled")
        self._on_loading(True)

        platform_key = self._platform_key_from_display(self.platform_var.get())
        start, end = _compute_time_range(self.time_var.get())

        def worker() -> None:
            try:
                total = self.storage.count_appearances(start, end, platform_key)
                records = self.storage.fetch_appearances(
                    start,
                    end,
                    platform_key,
                    limit=FETCH_LIMIT,
                )
                self.after(0, lambda: self._apply_results(records, total))
            except Exception:
                logger.exception("Failed to load history records")
                self.after(0, lambda: self._apply_error())

        threading.Thread(target=worker, daemon=True).start()

    def _apply_results(self, records: List[AppearanceRecord], total: int) -> None:
        self.tree.delete(*self.tree.get_children())
        self._url_map.clear()

        for record in records:
            rank_display = record.rank if record.rank is not None else "-"
            item_id = self.tree.insert(
                "",
                "end",
                values=(
                    record.id,
                    _platform_display_name(record.platform),
                    rank_display,
                    record.title,
                    _format_polled_at(record.polled_at),
                ),
            )
            self._url_map[item_id] = record.url

        shown = len(records)
        if total == 0:
            self.summary_var.set("暂无记录")
        elif total > shown:
            self.summary_var.set(f"共 {total} 条，显示最近 {shown} 条")
        else:
            self.summary_var.set(f"共 {total} 条")

        self._finish_loading()

    def _apply_error(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._url_map.clear()
        self.summary_var.set("加载失败，请重试")
        self._finish_loading()

    def _finish_loading(self) -> None:
        self._loading = False
        self.query_btn.configure(state="normal")
        self._on_loading(False)

    def _on_double_click(self, _event: tk.Event) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        url = self._url_map.get(selection[0])
        if url:
            webbrowser.open(url)

    def _on_tree_select(self, _event: tk.Event) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        values = self.tree.item(selection[0], "values")
        if len(values) >= 4:
            self._on_select(str(values[3]))


class HotListApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("体育热榜监控")
        self.root.minsize(900, 620)
        self.root.geometry("960x680")

        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Treeview", font=FONT_NORMAL, rowheight=24)
        style.configure("Treeview.Heading", font=FONT_NORMAL)
        style.configure("TLabelframe.Label", font=FONT_TITLE)

        self._polling = False
        self._history_loading = False
        self._last_successful: Dict[str, List[HotItem]] = {}
        self.monitor = HotListMonitor(on_poll_complete=self._schedule_ui_update)
        self.history_storage = Storage()

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)

        live_tab = ttk.Frame(self.notebook)
        history_tab = ttk.Frame(self.notebook)
        self.notebook.add(live_tab, text="实时热榜")
        self.notebook.add(history_tab, text="历史记录")

        toolbar = ttk.Frame(live_tab, padding=(8, 8, 8, 4))
        toolbar.pack(fill="x")

        ttk.Label(toolbar, text="体育热榜监控", font=FONT_TITLE).pack(side="left")

        self.refresh_btn = ttk.Button(
            toolbar,
            text="立即刷新",
            command=self._manual_refresh,
        )
        self.refresh_btn.pack(side="right")

        grid = ttk.Frame(live_tab, padding=(8, 4, 8, 4))
        grid.pack(fill="both", expand=True)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        grid.rowconfigure(0, weight=1)
        grid.rowconfigure(1, weight=1)

        self.panels: Dict[str, PlatformPanel] = {}
        for row_idx, row_keys in enumerate(PLATFORM_LAYOUT):
            for col_idx, platform_key in enumerate(row_keys):
                panel = PlatformPanel(grid, platform_key)
                panel.grid(
                    row=row_idx,
                    column=col_idx,
                    sticky="nsew",
                    padx=(0 if col_idx == 0 else 4, 0),
                    pady=(0 if row_idx == 0 else 4, 0),
                )
                panel.set_select_callback(self._show_title_in_status)
                self.panels[platform_key] = panel

        self.history_panel = HistoryPanel(
            history_tab,
            self.history_storage,
            on_select=self._show_title_in_status,
            on_loading=self._set_history_loading,
        )
        self.history_panel.pack(fill="both", expand=True)

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        status_frame = ttk.Frame(self.root, padding=(8, 4, 8, 8))
        status_frame.pack(fill="x")

        self.status_var = tk.StringVar(value="状态：正在初始化...")
        ttk.Label(
            status_frame,
            textvariable=self.status_var,
            font=FONT_STATUS,
            anchor="w",
        ).pack(fill="x")

    def _on_tab_changed(self, _event: tk.Event) -> None:
        if self.notebook.index(self.notebook.select()) == 1:
            self.history_panel.on_tab_shown()

    def _set_history_loading(self, loading: bool) -> None:
        self._history_loading = loading
        if loading:
            self.status_var.set("状态：正在加载历史记录...")
        else:
            self._restore_live_status()

    def _restore_live_status(self) -> None:
        polled_at = getattr(self, "_last_polled_at", None)
        if not polled_at:
            self.status_var.set("状态：就绪")
            return
        time_str = polled_at.strftime("%Y-%m-%d %H:%M:%S")
        self.status_var.set(
            f"状态：就绪 | 上次更新 {time_str} | 每 {POLL_INTERVAL_MINUTES} 分钟自动刷新"
        )

    def _show_title_in_status(self, title: str) -> None:
        if self._history_loading:
            return
        polled_at = getattr(self, "_last_polled_at", None)
        time_part = ""
        if polled_at:
            time_part = f" | 上次更新 {polled_at.strftime('%Y-%m-%d %H:%M:%S')}"
        self.status_var.set(f"状态：就绪{time_part} | {title}")

    def _schedule_ui_update(
        self,
        results: Dict[str, List[HotItem]],
        polled_at: datetime,
    ) -> None:
        self.root.after(0, lambda: self._refresh_panels(results, polled_at))

    def _refresh_panels(
        self,
        results: Dict[str, List[HotItem]],
        polled_at: datetime,
    ) -> None:
        self._polling = False
        self._last_polled_at = polled_at

        failed = []
        for platform_key, panel in self.panels.items():
            items = results.get(platform_key, [])
            if items:
                self._last_successful[platform_key] = items
                panel.update_items(items)
            elif platform_key in self._last_successful:
                panel.update_items(self._last_successful[platform_key])
                failed.append(PLATFORMS[platform_key]["name"])
            else:
                panel.update_items([])
                failed.append(PLATFORMS[platform_key]["name"])

        self.refresh_btn.configure(state="normal")

        if self._history_loading:
            return

        time_str = polled_at.strftime("%Y-%m-%d %H:%M:%S")
        status = f"状态：就绪 | 上次更新 {time_str} | 每 {POLL_INTERVAL_MINUTES} 分钟自动刷新"
        if failed:
            status += f" | 抓取失败：{', '.join(failed)}"
        self.status_var.set(status)

    def _set_polling_status(self) -> None:
        self._polling = True
        self.refresh_btn.configure(state="disabled")
        polled_at = getattr(self, "_last_polled_at", None)
        if polled_at:
            time_str = polled_at.strftime("%Y-%m-%d %H:%M:%S")
            self.status_var.set(f"状态：正在抓取... | 上次更新 {time_str}")
        else:
            self.status_var.set("状态：正在抓取...")

    def _manual_refresh(self) -> None:
        if self._polling:
            return
        self._set_polling_status()
        threading.Thread(target=self.monitor.poll_once, daemon=True).start()

    def _on_close(self) -> None:
        self.monitor.stop()
        self.root.destroy()

    def run(self) -> None:
        self._set_polling_status()
        threading.Thread(target=self.monitor.start, daemon=True).start()
        self.root.mainloop()


def run_app() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    HotListApp().run()
