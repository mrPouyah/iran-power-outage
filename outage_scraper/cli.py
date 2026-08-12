from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from .dates import OutageDate
from .models import OutageRecord
from .parser import build_records, fetch, parse_outage_page
from .search import DEFAULT_HEADERS, web_search
from .sources import direct_sources_for

logger = logging.getLogger("outage_scraper")

SEARCH_QUERY_TEMPLATES = [
    "برنامه قطعی برق {city} {date}",
    "جدول خاموشی برق {city} {date}",
    "ساعت قطعی برق {city} امروز {date}",
]

CSV_FIELDS = [
    "date_jalali", "date_gregorian", "province", "city",
    "neighborhood_code", "location", "start_time", "end_time",
    "source_title", "source_url",
]


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    return session


def _dump_html(dump_dir: str, url: str, html: str) -> None:
    """Save a fetched page verbatim, so a failed parse can be inspected/debugged offline."""
    directory = Path(dump_dir)
    directory.mkdir(parents=True, exist_ok=True)
    safe_name = quote(url, safe="")[:150] + ".html"
    (directory / safe_name).write_text(html, encoding="utf-8")
    logger.debug("Dumped %s -> %s", url, directory / safe_name)


def gather_records(
    city: str,
    province: str,
    date: OutageDate,
    *,
    max_search_results: int,
    request_delay: float,
    session: requests.Session,
    debug_dump_dir: str | None = None,
) -> list[OutageRecord]:
    records: list[OutageRecord] = []

    for source in direct_sources_for(city):
        logger.info("در حال بررسی منبع مستقیم: %s", source.url)
        html = fetch(source.url, session)
        if html:
            if debug_dump_dir:
                _dump_html(debug_dump_dir, source.url, html)
            soup = BeautifulSoup(html, "html.parser")
            records.extend(build_records(
                source.extract(soup, date.gregorian),
                city=city, province=province,
                date_jalali=date.jalali_long, date_gregorian=str(date.gregorian),
                url=source.url,
            ))
        time.sleep(request_delay)

    if records:
        return records

    seen_urls: set[str] = set()
    for date_str in date.query_variants():
        for template in SEARCH_QUERY_TEMPLATES:
            query = template.format(city=city, date=date_str)
            logger.info("جستجو: %s", query)
            for result in web_search(query, session, max_results=max_search_results):
                url = result["url"]
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                html = fetch(url, session)
                if not html:
                    continue
                if debug_dump_dir:
                    _dump_html(debug_dump_dir, url, html)
                page_records = parse_outage_page(
                    html, city=city, province=province,
                    date_jalali=date.jalali_long, date_gregorian=str(date.gregorian),
                    url=url, title=result["title"],
                )
                if page_records:
                    logger.info("یافت شد: %d ردیف از %s", len(page_records), url)
                records.extend(page_records)
                time.sleep(request_delay)

            if records:
                return records
    return records


def write_output(records: list[OutageRecord], fmt: str, outfile: str | None) -> None:
    if fmt == "json":
        text = json.dumps([r.to_dict() for r in records], ensure_ascii=False, indent=2)
        if outfile:
            Path(outfile).write_text(text, encoding="utf-8")
        else:
            print(text)
        return

    if fmt == "csv":
        out = Path(outfile).open("w", newline="", encoding="utf-8-sig") if outfile else sys.stdout
        try:
            writer = csv.DictWriter(out, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for r in records:
                writer.writerow({field: getattr(r, field) for field in CSV_FIELDS})
        finally:
            if outfile:
                out.close()
        return

    _print_table(records)


def _print_table(records: list[OutageRecord]) -> None:
    if not records:
        print("هیچ برنامه قطعی برقی برای این تاریخ و شهر پیدا نشد.")
        print("منابع رسمی برای بررسی دستی: bargheman.com و سامانه توزیع برق استان (maztozi.ir) یا تماس با ۱۲۱.")
        return

    header = f"{'کد':<6}{'بازه زمانی':<16}{'محدوده / محله':<45}{'منبع'}"
    print(f"برنامه قطعی برق {records[0].city}، {records[0].province} — {records[0].date_jalali}\n")
    print(header)
    print("-" * len(header))
    for r in records:
        time_range = f"{r.start_time or '?'}-{r.end_time or '?'}"
        code = r.neighborhood_code or "-"
        location = r.location if len(r.location) <= 43 else r.location[:42] + "…"
        print(f"{code:<6}{time_range:<16}{location:<45}{r.source_url}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="جستجوگر برنامه قطعی برق (خاموشی) برای شهرهای ایران، بر اساس تاریخ.",
    )
    parser.add_argument("--date", default=None, help="تاریخ میلادی یا شمسی YYYY-MM-DD (پیش‌فرض: امروز)")
    parser.add_argument("--city", default="بابل", help="نام شهر به فارسی (پیش‌فرض: بابل)")
    parser.add_argument("--province", default="مازندران", help="نام استان به فارسی (پیش‌فرض: مازندران)")
    parser.add_argument("--format", choices=["table", "json", "csv"], default="table")
    parser.add_argument("--outfile", default=None, help="مسیر فایل خروجی برای json/csv (پیش‌فرض: چاپ در ترمینال)")
    parser.add_argument("--max-search-results", type=int, default=6)
    parser.add_argument("--request-delay", type=float, default=1.0, help="فاصله بین درخواست‌ها به ثانیه")
    parser.add_argument(
        "--debug-dump-dir", default=None,
        help="ذخیره HTML خام هر صفحه‌ی دریافت‌شده در این پوشه، برای اشکال‌زدایی",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    try:
        date = OutageDate.parse(args.date)
    except ValueError as exc:
        logger.error(str(exc))
        return 1

    logger.info("جستجوی برنامه قطعی برق %s (%s) برای تاریخ %s", args.city, args.province, date.jalali_long)

    session = build_session()
    records = gather_records(
        args.city,
        args.province,
        date,
        max_search_results=args.max_search_results,
        request_delay=args.request_delay,
        session=session,
        debug_dump_dir=args.debug_dump_dir,
    )
    write_output(records, args.format, args.outfile)
    return 0 if records else 2


if __name__ == "__main__":
    raise SystemExit(main())
