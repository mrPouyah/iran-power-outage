from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional


# این فایل ساختار داده‌ی اصلی پروژه را تعریف می‌کند: یک «رکورد خاموشی»
@dataclass
class OutageRecord:
    """One scheduled outage slot for one neighborhood/street group."""

    city: str
    province: str
    date_jalali: str
    date_gregorian: str
    location: str                              # نام محله/خیابان (متن آزاد فارسی)
    start_time: Optional[str] = None           # ساعت شروع خاموشی، مثلاً "14:00"
    end_time: Optional[str] = None             # ساعت پایان خاموشی
    neighborhood_code: Optional[str] = None    # کد چرخه‌ی خاموشی (اگر منبع منتشر کرده باشد)
    source_url: str = ""                       # لینک صفحه‌ای که این رکورد از آن استخراج شده
    source_title: str = ""                     # عنوان صفحه/نتیجه‌ی جستجو (اگر موجود بود)

    def to_dict(self) -> dict:
        # تبدیل رکورد به دیکشنری ساده، برای خروجی JSON/CSV
        return asdict(self)

    def key(self) -> tuple:
        """Identity used for de-duplication across sources."""
        # چون ممکن است یک خاموشی از چند منبع یا چند بار پیدا شود،
        # این «کلید» برای حذف رکوردهای تکراری استفاده می‌شود
        return (self.location.strip(), self.start_time, self.end_time, self.neighborhood_code)
