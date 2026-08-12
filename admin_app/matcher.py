"""Match a subscriber's registered neighborhood against today's outages.

Pure function, no database access, so it's trivial to unit-test with
plain fixtures — same pattern as outage_scraper.parser's
`_records_from_tables`/`_records_from_text`.
"""
# چون داده‌ی خاموشی متن آزاد فارسی است (نه یک کد استاندارد)، تطبیق فعلاً
# ساده و بر پایه‌ی زیررشته است: اگر نام محله‌ی مشترک داخل متن محل خاموشی
# باشد، یعنی مشترک امروز خاموشی دارد. دقیق‌تر کردن این تطبیق (نرمال‌سازی
# املای عربی/فارسی، کلمات کلیدی چندگانه و ...) یک قدم بعدی است.
from __future__ import annotations

from .models import Outage, Subscriber


def match_subscriber(subscriber: Subscriber, outages: list[Outage]) -> list[Outage]:
    keyword = subscriber.neighborhood.strip()
    if not keyword:
        return []
    return [o for o in outages if keyword in o.location]
