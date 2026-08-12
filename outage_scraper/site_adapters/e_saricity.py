"""Adapter for app.e-saricity.ir's Babol outage page.

This site is a client-rendered card list, not an HTML <table>: each
outage is a `.card`-class element carrying `data-address` and a
`data-time` attribute. parser.py's generic table/text strategies don't
recognize this shape and, when run against this page anyway,
false-match unrelated time-like strings elsewhere on the page. This
adapter reads the real attributes directly instead.

Crucially, `data-time` is not an absolute date — the page always
reflects "now" and labels each entry relative to it: "امروز" (today),
"دیروز" (yesterday), "N روز قبل" (N days ago), "N روز دیگر" (N days from
now), e.g. `data-time="امروز ۱۴:۵۴ - ۱۶:۵۴"`. So the requested date has
to be converted to that same relative label before matching, or every
day in the site's rolling history/future window gets returned at once.

The page does not publish a rotation/neighborhood code anywhere, so
neighborhood_code is always None for records from this source.
"""
# آداپتور اختصاصی سایت app.e-saricity.ir (منبع مستقیم شهر بابل).
# نکته‌ی مهم: این سایت هر خاموشی را با برچسب «نسبی» به امروز مشخص می‌کند
# (نه تاریخ مطلق)، پس این فایل باید تاریخ درخواستی کاربر را به همان
# برچسب نسبی («امروز»/«دیروز»/«N روز قبل»/«N روز دیگر») تبدیل کند تا
# فقط رکوردهای همان روز را برگرداند، نه کل آرشیو سایت را.
from __future__ import annotations

import datetime as _dt

from bs4 import BeautifulSoup

from ..timeparse import TIME_RANGE_RE, normalize_time

CARD_SELECTOR = "[data-time]"


def relative_day_label(day_offset: int) -> str:
    # فاصله‌ی روز (نسبت به امروز) را به برچسب فارسی‌ای که خودِ سایت
    # استفاده می‌کند تبدیل می‌کند؛ مثلاً ۰ می‌شود «امروز»، ۲- می‌شود «2 روز قبل»
    if day_offset == 0:
        return "امروز"
    if day_offset == -1:
        return "دیروز"
    if day_offset < -1:
        return f"{-day_offset} روز قبل"
    return f"{day_offset} روز دیگر"


def extract(soup: BeautifulSoup, target_date: _dt.date) -> list[dict]:
    # تاریخ هدف را به برچسب نسبی تبدیل می‌کند، سپس فقط کارت‌هایی را
    # می‌خواند که data-time شان دقیقاً با همین برچسب شروع می‌شود
    day_offset = (target_date - _dt.date.today()).days
    label = relative_day_label(day_offset)

    out: list[dict] = []
    for card in soup.select(CARD_SELECTOR):
        raw_time = card.get("data-time", "")
        if not raw_time.startswith(label):
            continue
        m = TIME_RANGE_RE.search(raw_time)
        if not m:
            continue

        # آدرس محل معمولاً در attribute هست؛ اگر نبود از متن نمایشی می‌خوانیم
        address = card.get("data-address", "").strip()
        if not address:
            text_el = card.select_one(".address-text") or card
            address = text_el.get_text(" ", strip=True)
        if not address:
            continue

        out.append({
            "location": address,
            "start_time": normalize_time(m["start"]),
            "end_time": normalize_time(m["end"]),
            "neighborhood_code": None,  # این سایت کد خاموشی منتشر نمی‌کند
        })
    return out
