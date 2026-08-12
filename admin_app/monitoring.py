"""Health checks and manual tests behind the monitoring tab.

Pure service layer: it knows nothing about HTTP. main.py turns these
results into JSON; this module just answers "is each stage healthy?" and
"run this stage once, without saving anything".
"""
# پنل مانیتورینگ کل زنجیره را در چهار مرحله نشان می‌دهد:
#
#   ۱) جمع‌آوری داده  — آیا منبع در دسترس است و داده برمی‌گرداند؟
#   ۲) ذخیره‌سازی     — آیا داده‌ی امروز در دیتابیس هست؟
#   ۳) تطبیق          — چند مشترک با خاموشی‌های امروز تطبیق دارند؟
#   ۴) ارسال پیامک    — هنوز ساخته نشده (صادقانه اعلام می‌شود)
#
# هر مرحله یک وضعیت دارد که مبنای رنگ در رابط کاربری است:
#   ok / warning / error / not_implemented
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

from sqlmodel import Session, func, select

from outage_scraper.dates import OutageDate

from .matcher import match_subscriber
from .models import Outage, Subscriber
from .sync import SyncResult, fetch_records
from .system_state import get_setting, last_real_run, recent_runs

# اگر از آخرین اجرای واقعی بیش از این مدت گذشته باشد، هشدار داده می‌شود
STALE_AFTER = _dt.timedelta(hours=24)

# نام وضعیت‌ها — در رابط کاربری به رنگ ترجمه می‌شوند
STATUS_OK = "ok"
STATUS_WARNING = "warning"
STATUS_ERROR = "error"
STATUS_NOT_IMPLEMENTED = "not_implemented"


@dataclass
class StageHealth:
    """Health of one stage in the pipeline."""

    key: str            # شناسه‌ی فنی مرحله (برای رابط کاربری)
    title: str          # عنوان فارسی قابل نمایش
    status: str         # ok / warning / error / not_implemented
    summary: str        # یک جمله توضیح وضعیت فعلی
    details: dict = field(default_factory=dict)  # اعداد کمکی برای نمایش


@dataclass
class SystemStatus:
    """The whole monitoring picture, in one object."""

    is_enabled: bool
    enabled_summary: str
    stages: list[StageHealth] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# بررسی سلامت مرحله‌به‌مرحله
# ---------------------------------------------------------------------------

def _check_collection(session: Session) -> StageHealth:
    """Stage 1 — is the scraper running successfully and recently?"""
    run = last_real_run(session)

    # حالت ۱: هرگز اجرای واقعی نشده
    if run is None:
        return StageHealth(
            key="collection", title="جمع‌آوری داده", status=STATUS_WARNING,
            summary="هنوز هیچ اجرای واقعی ثبت نشده است.",
            details={},
        )

    # حالت ۲: آخرین اجرا شکست خورده
    if run.status == "failed":
        return StageHealth(
            key="collection", title="جمع‌آوری داده", status=STATUS_ERROR,
            summary=f"آخرین اجرا با خطا مواجه شد: {run.error_message}",
            details={"last_run": run.started_at.isoformat(), "fetched": run.fetched_count},
        )

    # حالت ۳: موفق بوده ولی خیلی وقت پیش — احتمالاً زمان‌بند کار نمی‌کند
    age = _dt.datetime.now() - run.started_at
    if age > STALE_AFTER:
        hours = int(age.total_seconds() // 3600)
        return StageHealth(
            key="collection", title="جمع‌آوری داده", status=STATUS_WARNING,
            summary=f"آخرین اجرای موفق {hours} ساعت پیش بوده — زمان‌بند را بررسی کنید.",
            details={"last_run": run.started_at.isoformat(), "fetched": run.fetched_count},
        )

    # حالت ۴: همه‌چیز مرتب
    return StageHealth(
        key="collection", title="جمع‌آوری داده", status=STATUS_OK,
        summary=f"آخرین اجرای موفق، {run.fetched_count} ردیف دریافت کرد.",
        details={"last_run": run.started_at.isoformat(), "fetched": run.fetched_count},
    )


def _check_storage(session: Session, city: str, date: OutageDate) -> StageHealth:
    """Stage 2 — is today's data actually in the database?"""
    today = session.exec(
        select(func.count()).select_from(Outage).where(
            Outage.city == city,
            Outage.date_gregorian == str(date.gregorian),
        )
    ).one()
    total = session.exec(select(func.count()).select_from(Outage)).one()

    # داده‌ی امروز نبودن لزوماً خرابی نیست (شاید هنوز اجرا نشده)، پس هشدار
    if today == 0:
        return StageHealth(
            key="storage", title="ذخیره‌سازی", status=STATUS_WARNING,
            summary="برای امروز هیچ خاموشی‌ای در پایگاه‌داده ذخیره نشده است.",
            details={"today": 0, "total": total},
        )

    return StageHealth(
        key="storage", title="ذخیره‌سازی", status=STATUS_OK,
        summary=f"{today} خاموشی برای امروز در پایگاه‌داده موجود است.",
        details={"today": today, "total": total},
    )


def _check_matching(session: Session, city: str, date: OutageDate) -> StageHealth:
    """Stage 3 — how many subscribers are matched against today's outages?"""
    subscribers = session.exec(
        select(Subscriber).where(
            Subscriber.city == city,
            Subscriber.is_active == True,  # noqa: E712
        )
    ).all()

    # بدون مشترک، تطبیق بی‌معناست
    if not subscribers:
        return StageHealth(
            key="matching", title="تطبیق مشترکین", status=STATUS_WARNING,
            summary="هیچ مشترک فعالی برای این شهر ثبت نشده است.",
            details={"active_subscribers": 0, "matched": 0},
        )

    outages = session.exec(
        select(Outage).where(
            Outage.city == city,
            Outage.date_gregorian == str(date.gregorian),
        )
    ).all()

    # از همان تابع تطبیقی استفاده می‌کنیم که اجرای واقعی استفاده می‌کند،
    # تا عددی که اینجا نشان داده می‌شود دقیقاً با واقعیت یکی باشد
    matched = sum(1 for s in subscribers if match_subscriber(s, list(outages)))

    return StageHealth(
        key="matching", title="تطبیق مشترکین", status=STATUS_OK,
        summary=f"{matched} مشترک از {len(subscribers)} مشترک فعال، امروز خاموشی دارند.",
        details={"active_subscribers": len(subscribers), "matched": matched},
    )


def _check_notification() -> StageHealth:
    """Stage 4 — SMS/Telegram sending is genuinely not built yet."""
    # عمداً «سالم» گزارش نمی‌شود: این مرحله واقعاً پیاده‌سازی نشده و نشان
    # دادن آن به‌صورت سبز، گزارش گمراه‌کننده‌ای به ادمین می‌داد.
    return StageHealth(
        key="notification", title="ارسال پیامک", status=STATUS_NOT_IMPLEMENTED,
        summary="این مرحله هنوز پیاده‌سازی نشده است (تلگرام / میرکا اس‌ام‌اس).",
        details={},
    )


# ---------------------------------------------------------------------------
# جمع‌بندی وضعیت کل سامانه
# ---------------------------------------------------------------------------

def collect_status(session: Session, city: str, province: str) -> SystemStatus:
    """Build the complete monitoring picture shown on the dashboard."""
    date = OutageDate.parse(None)  # امروز
    setting = get_setting(session)

    status = SystemStatus(
        is_enabled=setting.is_enabled,
        enabled_summary=(
            "سامانه فعال است و اجرای خودکار داده را ذخیره می‌کند."
            if setting.is_enabled
            else "سامانه غیرفعال است — اجرای خودکار هیچ داده‌ای ذخیره یا ارسال نمی‌کند."
        ),
        stages=[
            _check_collection(session),
            _check_storage(session, city, date),
            _check_matching(session, city, date),
            _check_notification(),
        ],
        history=[
            {
                "started_at": run.started_at.strftime("%Y-%m-%d %H:%M:%S"),
                "kind": "تست" if run.is_dry_run else "واقعی",
                "status": run.status,
                "fetched": run.fetched_count,
                "stored": run.stored_count,
                "purged": run.purged_count,
                "matched": run.matched_count,
                "error": run.error_message,
            }
            for run in recent_runs(session, limit=10)
        ],
    )
    return status


# ---------------------------------------------------------------------------
# تست دستی دریافت داده — هرگز چیزی ذخیره نمی‌کند
# ---------------------------------------------------------------------------

@dataclass
class DataTestResult:
    """Raw outage list fetched from the source, with nothing saved."""

    city: str
    province: str
    date_jalali: str
    date_gregorian: str
    outages: list[dict] = field(default_factory=list)
    error: str | None = None

    @property
    def count(self) -> int:
        return len(self.outages)


def run_data_test(city: str, province: str, date_text: str | None = None) -> DataTestResult:
    """Manual test: fetch today's outage list from the source and return it.

    Deliberately does *only* the data-collection step: no subscriber
    matching, no storing. Matching against subscribers happens
    automatically during a real run, so it is not part of this check —
    here the admin only wants to confirm the source is reachable and the
    parsed outage rows look right.
    """
    date = OutageDate.parse(date_text)
    result = DataTestResult(
        city=city, province=province,
        date_jalali=date.jalali_long, date_gregorian=str(date.gregorian),
    )

    try:
        # fetch_records فقط از منبع می‌خواند و به دیتابیس دست نمی‌زند
        records = fetch_records(city, province, date)
        result.outages = [
            {
                "location": r.location,
                "start_time": r.start_time,
                "end_time": r.end_time,
                "neighborhood_code": r.neighborhood_code,
                "source_url": r.source_url,
            }
            for r in records
        ]
    except Exception as exc:  # noqa: BLE001 — خطا باید در نتیجه گزارش شود، نه کرش
        result.error = f"{type(exc).__name__}: {exc}"

    return result


def data_test_to_dict(result: DataTestResult) -> dict:
    """Flatten a DataTestResult into JSON-friendly primitives for the UI."""
    return {
        "city": result.city,
        "province": result.province,
        "date_jalali": result.date_jalali,
        "date_gregorian": result.date_gregorian,
        "count": result.count,
        "outages": result.outages,
        "error": result.error,
    }


# ---------------------------------------------------------------------------
# تست دستی همسان‌سازی مشترک با ساعت قطعی — هرگز چیزی ذخیره نمی‌کند
# ---------------------------------------------------------------------------

@dataclass
class MatchingTestResult:
    """Which subscribers would be notified today, and which would not."""

    city: str
    province: str
    date_jalali: str
    date_gregorian: str
    total_outages: int = 0
    # مشترکینی که محله‌شان با یکی از قطعی‌های امروز خواند
    matched: list[dict] = field(default_factory=list)
    # مشترکینی که هیچ تطبیقی نداشتند. این فهرست عمداً برگردانده می‌شود:
    # وقتی انتظار تطبیق دارید و چیزی نمی‌آید، تنها راه عیب‌یابی همین است
    # (مثلاً اختلاف املای «ی» فارسی و «ي» عربی، یا محله‌ی خیلی جزئی).
    unmatched: list[dict] = field(default_factory=list)
    error: str | None = None

    @property
    def active_subscribers(self) -> int:
        return len(self.matched) + len(self.unmatched)


def run_matching_test(
    session: Session,
    city: str,
    province: str,
    date_text: str | None = None,
) -> MatchingTestResult:
    """Manual test: match live outage data against the real subscriber list.

    Fetches the source exactly as a real run would, and runs the same
    matcher, but stores nothing. Shows both matched and unmatched
    subscribers so a missing notification can be diagnosed.
    """
    date = OutageDate.parse(date_text)
    result = MatchingTestResult(
        city=city, province=province,
        date_jalali=date.jalali_long, date_gregorian=str(date.gregorian),
    )

    try:
        # ۱) دریافت زنده از منبع — همان داده‌ای که اجرای واقعی می‌گرفت
        records = fetch_records(city, province, date)
        result.total_outages = len(records)

        # ۲) تبدیل به شیء Outage در حافظه. چون session.add() صدا زده
        #    نمی‌شود، هیچ‌چیز در دیتابیس نوشته نمی‌شود.
        outages = [
            Outage(
                city=r.city, province=r.province,
                date_jalali=r.date_jalali, date_gregorian=r.date_gregorian,
                location=r.location, start_time=r.start_time, end_time=r.end_time,
                neighborhood_code=r.neighborhood_code, source_url=r.source_url,
            )
            for r in records
        ]

        # ۳) همان matcher اجرای واقعی، تا نتیجه دقیقاً واقعی باشد
        subscribers = session.exec(
            select(Subscriber).where(
                Subscriber.city == city,
                Subscriber.is_active == True,  # noqa: E712
            )
        ).all()

        for subscriber in subscribers:
            hits = match_subscriber(subscriber, outages)
            entry = {
                "full_name": subscriber.full_name,
                "mobile": subscriber.mobile,
                "neighborhood": subscriber.neighborhood,
            }
            if hits:
                entry["outages"] = [
                    {
                        "location": o.location,
                        "start_time": o.start_time,
                        "end_time": o.end_time,
                        "neighborhood_code": o.neighborhood_code,
                    }
                    for o in hits
                ]
                result.matched.append(entry)
            else:
                result.unmatched.append(entry)
    except Exception as exc:  # noqa: BLE001 — خطا باید گزارش شود، نه کرش
        result.error = f"{type(exc).__name__}: {exc}"

    return result


def matching_test_to_dict(result: MatchingTestResult) -> dict:
    """Flatten a MatchingTestResult into JSON-friendly primitives for the UI."""
    return {
        "city": result.city,
        "province": result.province,
        "date_jalali": result.date_jalali,
        "date_gregorian": result.date_gregorian,
        "total_outages": result.total_outages,
        "active_subscribers": result.active_subscribers,
        "matched_count": len(result.matched),
        "matched": result.matched,
        "unmatched": result.unmatched,
        "error": result.error,
    }


# ---------------------------------------------------------------------------
# نتیجه‌ی اجرای واقعی (شامل تطبیق خودکار با مشترکین)
# ---------------------------------------------------------------------------

def result_to_dict(result: SyncResult) -> dict:
    """Flatten a SyncResult into JSON-friendly primitives for the UI."""
    return {
        "city": result.city,
        "province": result.province,
        "date_jalali": result.date_jalali,
        "date_gregorian": result.date_gregorian,
        "fetched_count": result.fetched_count,
        "stored_count": result.stored_count,
        "purged_count": result.purged_count,
        "outages_today": result.outages_today,
        "active_subscribers": result.active_subscribers,
        "matched_count": result.matched_count,
        # saved صریحاً برگردانده می‌شود تا رابط کاربری بتواند به کاربر
        # اطمینان بدهد که این اجرا چیزی در دیتابیس تغییر داده یا نه
        "saved": result.saved,
        "error": result.error,
        "matches": [
            {
                "full_name": m.full_name,
                "mobile": m.mobile,
                "neighborhood": m.neighborhood,
                "outages": [
                    {
                        "location": o.location,
                        "start_time": o.start_time,
                        "end_time": o.end_time,
                        "neighborhood_code": o.neighborhood_code,
                    }
                    for o in m.outages
                ],
            }
            for m in result.matches
        ],
    }
