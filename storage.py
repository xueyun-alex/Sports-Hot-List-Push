import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

from timezone_utils import get_tz

from config import DATA_DIR, DB_PATH, RETENTION_DAYS
from scraper import HotItem

SCHEMA = """
CREATE TABLE IF NOT EXISTS appearances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    rank INTEGER,
    polled_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_appearances_time ON appearances(polled_at);
CREATE INDEX IF NOT EXISTS idx_appearances_platform ON appearances(platform, polled_at);
"""


@dataclass
class CountResult:
    platform: str
    title: str
    url: Optional[str]
    count: int
    last_seen: str


@dataclass
class AppearanceRecord:
    id: int
    platform: str
    title: str
    url: Optional[str]
    rank: Optional[int]
    polled_at: str


class Storage:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def record_poll(
        self,
        platform_key: str,
        items: List[HotItem],
        polled_at: datetime,
    ) -> int:
        polled_at_str = polled_at.isoformat()
        rows = [
            (platform_key, item.title, item.url, item.rank, polled_at_str)
            for item in items
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO appearances (platform, title, url, rank, polled_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )
            return len(rows)

    def count_in_window(
        self,
        start: datetime,
        end: datetime,
        platform_key: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[CountResult]:
        params: List = [start.isoformat(), end.isoformat()]
        platform_filter = ""
        if platform_key:
            platform_filter = "AND platform = ?"
            params.append(platform_key)

        query = f"""
            SELECT
                platform,
                title,
                url,
                COUNT(*) AS count,
                MAX(polled_at) AS last_seen
            FROM appearances
            WHERE polled_at >= ? AND polled_at <= ? {platform_filter}
            GROUP BY platform, COALESCE(url, ''), title
            ORDER BY count DESC, last_seen DESC, title ASC
        """
        if limit:
            query += f" LIMIT {int(limit)}"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            CountResult(
                platform=row["platform"],
                title=row["title"],
                url=row["url"],
                count=row["count"],
                last_seen=row["last_seen"],
            )
            for row in rows
        ]

    def count_global_in_window(
        self,
        start: datetime,
        end: datetime,
        limit: int = 5,
    ) -> List[CountResult]:
        query = """
            SELECT
                platform,
                title,
                url,
                COUNT(*) AS count,
                MAX(polled_at) AS last_seen
            FROM appearances
            WHERE polled_at >= ? AND polled_at <= ?
            GROUP BY COALESCE(url, ''), title
            ORDER BY count DESC, last_seen DESC, title ASC
            LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(
                query,
                (start.isoformat(), end.isoformat(), limit),
            ).fetchall()

        return [
            CountResult(
                platform=row["platform"],
                title=row["title"],
                url=row["url"],
                count=row["count"],
                last_seen=row["last_seen"],
            )
            for row in rows
        ]

    def _appearance_filters(
        self,
        start: Optional[datetime],
        end: Optional[datetime],
        platform_key: Optional[str],
    ) -> Tuple[str, List]:
        conditions: List[str] = []
        params: List = []
        if start is not None:
            conditions.append("polled_at >= ?")
            params.append(start.isoformat())
        if end is not None:
            conditions.append("polled_at <= ?")
            params.append(end.isoformat())
        if platform_key:
            conditions.append("platform = ?")
            params.append(platform_key)
        where = " AND ".join(conditions) if conditions else "1=1"
        return where, params

    def fetch_appearances(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        platform_key: Optional[str] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> List[AppearanceRecord]:
        where, params = self._appearance_filters(start, end, platform_key)
        query = f"""
            SELECT id, platform, title, url, rank, polled_at
            FROM appearances
            WHERE {where}
            ORDER BY polled_at DESC, id DESC
            LIMIT ? OFFSET ?
        """
        params.extend([int(limit), int(offset)])

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            AppearanceRecord(
                id=row["id"],
                platform=row["platform"],
                title=row["title"],
                url=row["url"],
                rank=row["rank"],
                polled_at=row["polled_at"],
            )
            for row in rows
        ]

    def count_appearances(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        platform_key: Optional[str] = None,
    ) -> int:
        where, params = self._appearance_filters(start, end, platform_key)
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS total FROM appearances WHERE {where}",
                params,
            ).fetchone()
        return int(row["total"]) if row else 0

    def count_polls_in_window(self, start: datetime, end: datetime) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(DISTINCT polled_at) AS poll_count
                FROM appearances
                WHERE polled_at >= ? AND polled_at <= ?
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchone()
        return int(row["poll_count"]) if row else 0

    def cleanup_old_records(self, days: int = RETENTION_DAYS) -> int:
        cutoff = datetime.now(get_tz()) - timedelta(days=days)
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM appearances WHERE polled_at < ?",
                (cutoff.isoformat(),),
            )
            return cursor.rowcount

def evening_report_window(now: datetime) -> Tuple[datetime, datetime, str]:
    tz = get_tz()
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    else:
        now = now.astimezone(tz)

    end = now.replace(hour=18, minute=30, second=0, microsecond=0)
    start = end.replace(hour=8, minute=30)
    label = "10小时"
    return start, end, label


def morning_report_window(now: datetime) -> Tuple[datetime, datetime, str]:
    tz = get_tz()
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    else:
        now = now.astimezone(tz)

    end = now.replace(hour=8, minute=30, second=0, microsecond=0)
    start = (end - timedelta(days=1)).replace(hour=18, minute=30)
    label = "14小时"
    return start, end, label
