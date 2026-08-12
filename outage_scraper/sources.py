"""Known direct sources for outage schedules, tried before falling back to search.

Each entry pairs a per-city URL with the site_adapters/ module that
knows how to read that specific site's markup. Add more cities/sources
here as you confirm they publish a per-city page; if the new site's
DOM shape differs from ones already covered, add a matching adapter
under site_adapters/ rather than stretching an existing one.
"""
# این فایل «فهرست منابع مستقیم و شناخته‌شده» را نگه می‌دارد: برای هر شهر،
# آدرس صفحه‌ی رسمی + آداپتور (تابع استخراج‌کننده‌ی) متناسب با آن سایت.
# این منابع همیشه قبل از جستجوی عمومی امتحان می‌شوند، چون دقیق‌تر و سریع‌ترند.
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Callable
from urllib.parse import quote

from bs4 import BeautifulSoup

from .site_adapters import e_saricity

# امضای (signature) هر تابع استخراج‌کننده: یک BeautifulSoup و تاریخ هدف می‌گیرد
# و لیستی از دیکشنری‌های خام رکورد برمی‌گرداند
Extractor = Callable[[BeautifulSoup, _dt.date], list[dict]]


@dataclass(frozen=True)
class DirectSource:
    # قالب آدرس (هنوز {city} در آن جایگزین نشده) + تابع استخراج‌کننده‌ی مخصوص همین سایت
    url_template: str
    extract: Extractor


DIRECT_SOURCES: dict[str, list[DirectSource]] = {
    "بابل": [
        DirectSource("https://app.e-saricity.ir/khamooshi/{city}", e_saricity.extract),
    ],
}


@dataclass(frozen=True)
class ResolvedSource:
    # نسخه‌ی «آماده به استفاده»: آدرس کامل (بعد از جایگزینی نام شهر)
    url: str
    extract: Extractor


def direct_sources_for(city: str) -> list[ResolvedSource]:
    # برای یک شهر مشخص، آدرس‌های DIRECT_SOURCES را کامل می‌کند
    # (نام شهر را داخل URL می‌گذارد) و لیست ResolvedSource برمی‌گرداند
    return [
        ResolvedSource(s.url_template.format(city=quote(city)), s.extract)
        for s in DIRECT_SOURCES.get(city, [])
    ]
