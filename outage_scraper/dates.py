"""Gregorian <-> Jalali (Iranian calendar) helpers.

Iranian outage announcements are always dated in the Jalali calendar
(e.g. "۱۴ مرداد ۱۴۰۵"), so the scraper accepts a Gregorian date on the
command line and derives the Jalali forms actually used in search
queries and on the source pages.
"""
# این فایل مسئول تبدیل بین تقویم میلادی و شمسی (جلالی) است.
# چون منابع خاموشی برق همیشه تاریخ را به شمسی می‌نویسند (مثلاً «۱۴ مرداد ۱۴۰۵»)
# ولی کاربر معمولاً تاریخ میلادی وارد می‌کند، این ماژول پل بین این دو است.
from __future__ import annotations

import datetime as _dt

import jdatetime

FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
EN_DIGITS = "0123456789"
_TO_FA = str.maketrans(EN_DIGITS, FA_DIGITS)
_TO_EN = str.maketrans(FA_DIGITS, EN_DIGITS)

FA_MONTHS = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]

# Python's date.weekday(): Monday=0 ... Sunday=6
# نگاشت شماره‌ی روز هفته‌ی پایتون (دوشنبه=۰) به نام فارسی روز هفته
WEEKDAYS_FA = {
    0: "دوشنبه", 1: "سه‌شنبه", 2: "چهارشنبه", 3: "پنجشنبه",
    4: "جمعه", 5: "شنبه", 6: "یکشنبه",
}


def to_fa_digits(text: str) -> str:
    # اعداد انگلیسی (0-9) داخل متن را به رقم فارسی (۰-۹) تبدیل می‌کند
    return text.translate(_TO_FA)


def to_en_digits(text: str) -> str:
    # برعکسِ تابع بالا: رقم فارسی را به انگلیسی تبدیل می‌کند
    # (لازم است چون داده‌های خام سایت‌ها گاهی فارسی و گاهی انگلیسی‌اند)
    return text.translate(_TO_EN)


class OutageDate:
    """A single calendar day, available in both Gregorian and Jalali form."""

    # این کلاس یک روز تقویمی را هم‌زمان به دو صورت میلادی و شمسی نگه می‌دارد
    def __init__(self, gregorian: _dt.date):
        self.gregorian = gregorian
        self.jalali = jdatetime.date.fromgregorian(date=gregorian)

    @classmethod
    def parse(cls, text: str | None) -> "OutageDate":
        """Accepts None/"today", a Gregorian "YYYY-MM-DD", or a Jalali "YYYY-MM-DD"."""
        # ورودی --date را می‌خواند: خالی یا "today" یعنی امروز،
        # و بر اساس سال (بزرگ‌تر یا کوچک‌تر از ۱۷۰۰) تشخیص می‌دهد میلادی است یا شمسی
        if not text or text.strip().lower() == "today":
            return cls(_dt.date.today())

        text = to_en_digits(text.strip())
        try:
            year, month, day = (int(part) for part in text.split("-"))
        except ValueError as exc:
            raise ValueError(
                f"Unrecognized date format: {text!r} (expected YYYY-MM-DD)"
            ) from exc

        if year > 1700:  # Gregorian
            return cls(_dt.date(year, month, day))
        return cls(jdatetime.date(year, month, day).togregorian())  # Jalali

    @property
    def jalali_long(self) -> str:
        # فرمت نمایشی کامل تاریخ شمسی، مثل «پنجشنبه ۱۵ مرداد ۱۴۰۵»
        j = self.jalali
        weekday = WEEKDAYS_FA[self.gregorian.weekday()]
        return f"{weekday} {to_fa_digits(str(j.day))} {FA_MONTHS[j.month - 1]} {to_fa_digits(str(j.year))}"

    @property
    def jalali_numeric(self) -> str:
        # فرمت عددی تاریخ شمسی به شکل YYYY/MM/DD (برای جستجو در وب)
        j = self.jalali
        return f"{j.year:04d}/{j.month:02d}/{j.day:02d}"

    def query_variants(self) -> list[str]:
        """Different ways this date shows up in Farsi news text, for search queries."""
        # چند شکل مختلف نوشتن همین تاریخ که در متن خبرها دیده می‌شود،
        # تا جستجوی وب شانس بیشتری برای پیدا کردن صفحه‌ی درست داشته باشد
        j = self.jalali
        day_fa = to_fa_digits(str(j.day))
        year_fa = to_fa_digits(str(j.year))
        return [
            f"{day_fa} {FA_MONTHS[j.month - 1]} {year_fa}",
            f"{j.day} {FA_MONTHS[j.month - 1]} {j.year}",
            self.jalali_numeric,
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.jalali_long
