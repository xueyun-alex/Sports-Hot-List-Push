import logging
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from tkinter import ttk
from typing import Callable, Dict, List, Optional

from config import PLATFORMS, POLL_INTERVAL_MINUTES
from monitor import HotListMonitor
from scraper import HotItem

logger = logging.getLogger(__name__)

FONT_FAMILY = "Microsoft YaHei"
FONT_NORMAL = (FONT_FAMILY, 10)
FONT_TITLE = (FONT_FAMILY, 11, "bold")
FONT_STATUS = (FONT_FAMILY, 9)

PLATFORM_LAYOUT = [
    ("sina_sports", "douyin_sports"),
    ("hupu_nba", "dongqiudi"),
]


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
        self._last_successful: Dict[str, List[HotItem]] = {}
        self.monitor = HotListMonitor(on_poll_complete=self._schedule_ui_update)

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self.root, padding=(8, 8, 8, 4))
        toolbar.pack(fill="x")

        ttk.Label(toolbar, text="体育热榜监控", font=FONT_TITLE).pack(side="left")

        self.refresh_btn = ttk.Button(
            toolbar,
            text="立即刷新",
            command=self._manual_refresh,
        )
        self.refresh_btn.pack(side="right")

        grid = ttk.Frame(self.root, padding=(8, 4, 8, 4))
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

        status_frame = ttk.Frame(self.root, padding=(8, 4, 8, 8))
        status_frame.pack(fill="x")

        self.status_var = tk.StringVar(value="状态：正在初始化...")
        ttk.Label(
            status_frame,
            textvariable=self.status_var,
            font=FONT_STATUS,
            anchor="w",
        ).pack(fill="x")

    def _show_title_in_status(self, title: str) -> None:
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
