import logging
import re
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

from config import PLATFORMS, TOP_N_TRACK, TOPHUB_BASE_URL, USER_AGENT

logger = logging.getLogger(__name__)

HOT_SUFFIX_PATTERNS = [
    re.compile(r"\s+\d[\d,]*次播放\s*$"),
    re.compile(r"\s+\d[\d,]*亮\s*$"),
    re.compile(r"\s+\d[\d,]+\s*$"),
    re.compile(r"\s+(足球|篮球|体坛)\s*$"),
]

EXTERNAL_DOMAINS = ("sina.com", "hupu.com", "dongqiudi.com", "douyin.com")


@dataclass
class HotItem:
    rank: int
    title: str
    url: Optional[str]


def normalize_title(title: str) -> str:
    text = re.sub(r"\s+", " ", title.strip())
    for pattern in HOT_SUFFIX_PATTERNS:
        text = pattern.sub("", text)
    return text.strip()


def fetch_node_html(hashid: str, session: Optional[requests.Session] = None) -> str:
    url = f"{TOPHUB_BASE_URL}/n/{hashid}"
    if session is None:
        session = requests.Session()
        session.trust_env = False
    response = session.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def _extract_title_from_link(link: Tag) -> str:
    title_span = link.find("span", class_="t")
    if title_span:
        return normalize_title(title_span.get_text(" ", strip=True))

    text = link.get_text(" ", strip=True)
    rank_span = link.find("span", class_="s")
    if rank_span:
        rank_text = rank_span.get_text(strip=True)
        if text.startswith(rank_text):
            text = text[len(rank_text) :].strip()

    return normalize_title(text)


def _extract_rank_from_link(link: Tag, fallback: int) -> int:
    rank_span = link.find("span", class_="s")
    if rank_span:
        digits = re.sub(r"\D", "", rank_span.get_text(strip=True))
        if digits:
            return int(digits)
    return fallback


def _parse_cc_cd_links(soup: BeautifulSoup) -> List[HotItem]:
    items: List[HotItem] = []
    containers = soup.select("motion.cc-cd-cb-l, div.cc-cd-cb-l")
    links: List[Tag] = []
    for container in containers:
        links.extend(container.find_all("a", href=True))

    if not links:
        for card in soup.select("motion.cc-cd, div.cc-cd"):
            links.extend(card.select("div.cc-cd-cb-l a[href]"))

    for index, link in enumerate(links, start=1):
        title = _extract_title_from_link(link)
        if not title:
            continue
        rank = _extract_rank_from_link(link, index)
        items.append(HotItem(rank=rank, title=title, url=link.get("href")))
    return items


def _parse_table_rows(soup: BeautifulSoup) -> List[HotItem]:
    items: List[HotItem] = []
    for row in soup.select("table tbody tr"):
        if row.find_parent("tbody", class_="filter-data"):
            continue
        if row.find_parent("tbody", class_="snapshot-data"):
            continue
        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        rank_digits = re.sub(r"\D", "", cells[0].get_text(strip=True))
        if not rank_digits:
            continue
        rank = int(rank_digits)

        link = cells[1].find("a", href=True)
        if link:
            title = normalize_title(link.get_text(" ", strip=True))
            url = link.get("href")
        else:
            title = normalize_title(cells[1].get_text(" ", strip=True))
            url = None

        if title:
            items.append(HotItem(rank=rank, title=title, url=url))
    return items


def _is_external_link(href: str) -> bool:
    return any(domain in href for domain in EXTERNAL_DOMAINS)


def _score_items(items: List[HotItem]) -> int:
    top = items[:TOP_N_TRACK]
    external_count = sum(
        1 for item in top if item.url and _is_external_link(item.url)
    )
    return external_count * 100 + len(top)


def _parse_content_links(soup: BeautifulSoup) -> List[HotItem]:
    items: List[HotItem] = []
    main = soup.select_one(".node-list, .table, .bc-cc, .node-content, main") or soup.body or soup

    seen_urls = set()
    for link in main.find_all("a", href=True):
        href = link.get("href", "")
        if not href or href.startswith("#"):
            continue
        if not _is_external_link(href):
            continue

        title = normalize_title(link.get_text(" ", strip=True))
        if len(title) < 4:
            continue

        absolute_url = urljoin(TOPHUB_BASE_URL, href)
        if absolute_url in seen_urls:
            continue
        seen_urls.add(absolute_url)
        items.append(HotItem(rank=len(items) + 1, title=title, url=absolute_url))

    return items


def parse_top_items(html: str, limit: int = TOP_N_TRACK) -> List[HotItem]:
    soup = BeautifulSoup(html, "html.parser")

    best: List[HotItem] = []
    best_score = -1
    for parser in (_parse_table_rows, _parse_cc_cd_links, _parse_content_links):
        try:
            parsed = parser(soup)
        except Exception as exc:
            logger.debug("Parser %s failed: %s", parser.__name__, exc)
            continue
        score = _score_items(parsed)
        if score > best_score:
            best_score = score
            best = parsed

    deduped: List[HotItem] = []
    seen = set()
    for item in sorted(best, key=lambda x: x.rank):
        key = (item.url or "", item.title)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return deduped[:limit]


def fetch_platform_items(
    platform_key: str,
    session: Optional[requests.Session] = None,
) -> List[HotItem]:
    platform = PLATFORMS[platform_key]
    html = fetch_node_html(platform["hashid"], session=session)
    items = parse_top_items(html)
    if not items:
        logger.warning("No items parsed for %s (%s)", platform["name"], platform["hashid"])
    return items


def fetch_all_platforms(session: Optional[requests.Session] = None) -> dict:
    client = session or requests.Session()
    client.trust_env = False
    results = {}
    for key in PLATFORMS:
        try:
            results[key] = fetch_platform_items(key, session=client)
        except Exception as exc:
            logger.exception("Failed to fetch %s: %s", key, exc)
            results[key] = []
    return results
