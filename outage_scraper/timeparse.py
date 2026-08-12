"""Shared Farsi time-range / rotation-code regex helpers.

Used by both the generic parser.py table/text strategies (for
search-discovered pages of unknown markup) and site-specific adapters
under site_adapters/ (for known direct sources with fixed markup).
"""
# این فایل الگوهای مشترک (regex) برای تشخیص «بازه‌ی زمانی» و «کد خاموشی»
# در متن فارسی را نگه می‌دارد، تا parser.py و همه‌ی site_adapters/ از یک
# منطق واحد استفاده کنند و رفتار همه‌جا یکسان بماند.
from __future__ import annotations

import re

from .dates import to_en_digits

_TIME = r"[۰-۹0-9]{1,2}(?::[۰-۹0-9]{2})?"
# الگویی که یک بازه‌ی زمانی مثل «۱۰:۰۰ الی ۱۲:۳۰» یا «10 تا 12:30» را پیدا می‌کند
TIME_RANGE_RE = re.compile(
    rf"(?P<start>{_TIME})\s*(?:الی|تا|إلی|–|-|to)\s*(?P<end>{_TIME})"
)
# الگویی که «کد ۳» یا «کد خاموشی: 5» را در متن پیدا می‌کند
CODE_RE = re.compile(r"کد\s*(?:خاموشی|برنامه)?\s*[:\-]?\s*(?P<code>[۰-۹0-9]+)")


def normalize_time(raw: str) -> str:
    # ساعت را به فرمت یکنواخت "HH:MM" با رقم انگلیسی تبدیل می‌کند
    # (مثلاً «۱۴» می‌شود «14:00» و «۱۴:۵۰» می‌شود «14:50»)
    raw = to_en_digits(raw.strip())
    if ":" not in raw:
        raw = f"{raw}:00"
    return raw
