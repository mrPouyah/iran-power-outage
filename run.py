"""Convenience entry point: python run.py --city بابل --date 2026-08-06"""
# یک نقطه‌ی ورود ساده در ریشه‌ی پروژه، معادل «python -m outage_scraper»
# تا نیازی به تایپ کردن نام کامل پکیج نباشد.
from outage_scraper.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
11