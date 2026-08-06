"""Fetching + extraction of outage records from a page's HTML.

Two extraction strategies are tried in order, since sources publish
this data in very different shapes:

1. Table-based: a <table> with header cells that look like
   "منطقه/محله" (location), "ساعت شروع/از" (start), "ساعت پایان/تا"
   (end) and optionally "کد" (code).
2. Text-based fallback: paragraphs/list items that mention the target
   city and contain a "HH:MM الی HH:MM" style time range, used by news
   roundups that describe the schedule in prose instead of a table.
"""
from __future__ import annotations

import logging
import re

import requests
from bs4 import BeautifulSoup

from .dates import to_en_digits
from .models import OutageRecord

logger = logging.getLogger(__name__)

_TIME = r"[۰-۹0-9]{1,2}(?::[۰-۹0-9]{2})?"
TIME_RANGE_RE = re.compile(
    rf"(?P<start>{_TIME})\s*(?:الی|تا|إلی|–|-|to)\s*(?P<end>{_TIME})"
)
CODE_RE = re.compile(r"کد\s*(?:خاموشی|برنامه)?\s*[:\-]?\s*(?P<code>[۰-۹0-9]+)")

LOCATION_HEADER_KEYWORDS = ("منطقه", "محله", "ناحیه", "خیابان", "محدوده", "آدرس")
START_HEADER_KEYWORDS = ("از ساعت", "شروع", "از")
END_HEADER_KEYWORDS = ("تا ساعت", "پایان", "تا")
CODE_HEADER_KEYWORDS = ("کد",)

PAGE_SCAN_CHARS = 20_000  # enough for a full article without reading huge pages


def _normalize_time(raw: str) -> str:
    raw = to_en_digits(raw.strip())
    if ":" not in raw:
        raw = f"{raw}:00"
    return raw


def _classify_header(text: str) -> str | None:
    text = text.strip()
    if any(k in text for k in CODE_HEADER_KEYWORDS):
        return "code"
    if any(k in text for k in START_HEADER_KEYWORDS):
        return "start"
    if any(k in text for k in END_HEADER_KEYWORDS):
        return "end"
    if any(k in text for k in LOCATION_HEADER_KEYWORDS):
        return "location"
    return None


def fetch(url: str, session: requests.Session, timeout: int = 15) -> str | None:
    try:
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
        if resp.encoding is None or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding
        return resp.text
    except requests.RequestException as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None


def _page_mentions_city(soup: BeautifulSoup, city: str) -> bool:
    return city in soup.get_text(" ", strip=True)[:PAGE_SCAN_CHARS]


def _records_from_tables(soup: BeautifulSoup) -> list[dict]:
    out: list[dict] = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header_cells = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
        col_roles = [_classify_header(c) for c in header_cells]
        if not any(col_roles):
            continue

        for row in rows[1:]:
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
            if not cells:
                continue
            record = {"location": "", "start_time": None, "end_time": None, "neighborhood_code": None}
            for role, value in zip(col_roles, cells):
                if role == "location" and value:
                    record["location"] = (record["location"] + " " + value).strip()
                elif role == "start" and value:
                    record["start_time"] = _normalize_time(value)
                elif role == "end" and value:
                    record["end_time"] = _normalize_time(value)
                elif role == "code" and value:
                    record["neighborhood_code"] = to_en_digits(value)

            row_text = " ".join(cells)
            if not (record["start_time"] and record["end_time"]):
                m = TIME_RANGE_RE.search(row_text)
                if m:
                    record["start_time"] = record["start_time"] or _normalize_time(m["start"])
                    record["end_time"] = record["end_time"] or _normalize_time(m["end"])

            if record["location"] and record["start_time"]:
                out.append(record)
    return out


def _records_from_text(soup: BeautifulSoup, city: str) -> list[dict]:
    out: list[dict] = []
    for el in soup.find_all(["p", "li"]):
        block = el.get_text(" ", strip=True)
        if city not in block:
            continue
        for m in TIME_RANGE_RE.finditer(block):
            code_match = CODE_RE.search(block)
            location = block[: m.start()].strip(" -،:")
            out.append({
                "location": location or block.strip(),
                "start_time": _normalize_time(m["start"]),
                "end_time": _normalize_time(m["end"]),
                "neighborhood_code": to_en_digits(code_match["code"]) if code_match else None,
            })
    return out


def parse_outage_page(
    html: str,
    *,
    city: str,
    province: str,
    date_jalali: str,
    date_gregorian: str,
    url: str,
    title: str = "",
) -> list[OutageRecord]:
    soup = BeautifulSoup(html, "html.parser")
    if not _page_mentions_city(soup, city):
        return []

    raw_records = _records_from_tables(soup)
    if not raw_records:
        raw_records = _records_from_text(soup, city)

    records: list[OutageRecord] = []
    seen: set[tuple] = set()
    for r in raw_records:
        rec = OutageRecord(
            city=city,
            province=province,
            date_jalali=date_jalali,
            date_gregorian=date_gregorian,
            location=r["location"],
            start_time=r.get("start_time"),
            end_time=r.get("end_time"),
            neighborhood_code=r.get("neighborhood_code"),
            source_url=url,
            source_title=title,
        )
        if rec.key() in seen:
            continue
        seen.add(rec.key())
        records.append(rec)
    return records
