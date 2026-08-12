"""Free-text web search, no API key required.

Uses DuckDuckGo's HTML endpoint (html.duckduckgo.com), which returns
plain server-rendered result links and is meant for this kind of
lightweight scripted use. If DuckDuckGo changes its markup or blocks a
request, this simply returns an empty list and the caller moves on to
the next query/source.
"""
# این ماژول وقتی به کار می‌آید که شهر مورد نظر «منبع مستقیم» شناخته‌شده
# نداشته باشد (یعنی در sources.py ثبت نشده)؛ به‌جای آن با جستجوی متنی در
# داک‌داک‌گو، صفحاتی که احتمالاً جدول خاموشی دارند را پیدا می‌کند.
from __future__ import annotations

import logging
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DDG_HTML_URL = "https://html.duckduckgo.com/html/"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.5,en;q=0.3",
}


def _unwrap_redirect(href: str) -> str:
    """DuckDuckGo wraps result links as /l/?uddg=<url-encoded-target>."""
    # داک‌داک‌گو لینک واقعی نتیجه را داخل یک لینک ریدایرکت مخفی می‌کند؛
    # این تابع لینک اصلی را از داخل آن بیرون می‌کشد
    if "uddg=" in href:
        target = parse_qs(urlparse(href).query).get("uddg")
        if target:
            return unquote(target[0])
    return href


def web_search(query: str, session: requests.Session, max_results: int = 8) -> list[dict]:
    """Return up to max_results {"title", "url"} dicts for a free-text query."""
    # یک عبارت جستجو (مثلاً «برنامه قطعی برق بابل ۱۵ مرداد ۱۴۰۵») می‌فرستد
    # و لیستی از نتایج (عنوان + لینک) را برمی‌گرداند
    try:
        resp = session.post(
            DDG_HTML_URL,
            data={"q": query},
            headers=DEFAULT_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Web search failed for %r: %s", query, exc)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results: list[dict] = []
    for link in soup.select("a.result__a"):
        href = _unwrap_redirect(link.get("href", ""))
        title = link.get_text(strip=True)
        if href and title:
            results.append({"title": title, "url": href})
        if len(results) >= max_results:
            break
    return results
