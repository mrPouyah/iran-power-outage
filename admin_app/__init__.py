"""Operator-facing admin app: subscriber database + daily outage sync/matching.

Separate tech stack from outage_scraper/ on purpose (FastAPI + SQLite web
app vs. a plain CLI scraper), so it lives as its own package and imports
outage_scraper as a library rather than the other way around.
"""
# این پکیج «لایه‌ی عملیاتی» بالای outage_scraper است: پایگاه‌داده‌ی
# مشترکین، رابط وب ثبت اپراتور، و منطق هم‌خوانی (sync) روزانه.
__all__ = ["models", "db", "auth", "matcher", "sync", "main", "create_admin"]
