"""Daily job: scrape today's outages, persist them, then match subscribers.

Usage: python -m admin_app.sync --city بابل --province مازندران

The work is split so both the CLI and the monitoring web UI can reuse it:
fetching, storing, purging and matching are separate functions, and the
orchestrator *returns* a SyncResult instead of printing. Only main() prints.
"""
# این ماژول مراحل زیر را از هم جدا نگه می‌دارد، تا هم CLI و هم رابط وب
# مانیتورینگ از همان کد استفاده کنند (بدون کپی‌کاری):
#
#   ۱) fetch_records()      — فقط دریافت از منبع، بدون دست‌زدن به دیتابیس
#   ۲) purge_old_outages()  — حذف خاموشی‌های روزهای گذشته (فقط جدول Outage)
#   ۳) store_records()      — ذخیره‌ی رکوردهای تازه (بدون تکراری‌نویسی)
#   ۴) match_all()          — تطبیق مشترکین فعال با خاموشی‌های امروز
#   ۵) sync_and_match()     — همه پشت سر هم، و برگرداندن نتیجه‌ی ساختاریافته
#
# دو نکته‌ی مهم که در طراحی رعایت شده است:
#
#   • جداسازی مرحله‌ی ۱ از بقیه، امکان «تست بدون ذخیره» (dry-run) را در پنل
#     مانیتورینگ می‌دهد؛ تست هرگز داده‌ی واقعی را تغییر نمی‌دهد.
#   • پاک‌سازی روزانه فقط و فقط جدول Outage را لمس می‌کند. اطلاعات مشترکین
#     (Subscriber) و حساب‌های ادمین هرگز حذف نمی‌شوند.
from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field

from sqlmodel import Session, delete, select

from outage_scraper.cli import build_session, gather_records
from outage_scraper.dates import OutageDate
from outage_scraper.models import OutageRecord

from .db import engine, init_db
from .matcher import match_subscriber
from .models import Outage, Subscriber

logger = logging.getLogger("admin_app.sync")


# ---------------------------------------------------------------------------
# ساختار نتیجه
# ---------------------------------------------------------------------------
# این dataclass‌ها عمداً مقادیر ساده نگه می‌دارند (نه شیء ORM)، چون بعد از
# بسته‌شدن session، دسترسی به فیلدهای شیء ORM خطا می‌دهد. با این کار نتیجه
# کاملاً مستقل از دیتابیس است و مستقیم قابل تبدیل به JSON برای رابط وب.

@dataclass
class OutageSlot:
    """One outage window, as plain values."""

    location: str
    start_time: str | None = None
    end_time: str | None = None
    neighborhood_code: str | None = None
    source_url: str = ""


@dataclass
class SubscriberMatch:
    """One subscriber together with the outages that affect them today."""

    full_name: str
    mobile: str
    neighborhood: str
    outages: list[OutageSlot] = field(default_factory=list)


@dataclass
class SyncResult:
    """Everything one sync run produced — for the CLI and the web UI alike."""

    city: str
    province: str
    date_jalali: str
    date_gregorian: str
    fetched_count: int = 0        # چند ردیف از منبع دریافت شد
    stored_count: int = 0         # چندتا از آن‌ها تازه بود و ذخیره شد
    purged_count: int = 0         # چند خاموشی قدیمی پاک شد
    outages_today: int = 0        # کل خاموشی‌های امروز موجود در دیتابیس
    active_subscribers: int = 0   # مشترکین فعال این شهر
    matches: list[SubscriberMatch] = field(default_factory=list)
    saved: bool = False           # آیا این اجرا واقعاً چیزی ذخیره کرد؟
    error: str | None = None      # اگر اجرا شکست خورد، دلیلش

    @property
    def matched_count(self) -> int:
        return len(self.matches)


# ---------------------------------------------------------------------------
# مرحله ۱ — دریافت از منبع (بدون دیتابیس)
# ---------------------------------------------------------------------------

def fetch_records(city: str, province: str, date: OutageDate) -> list[OutageRecord]:
    """Fetch the outage rows for a date from the source. Touches no database."""
    # چون این تابع هیچ چیزی ذخیره نمی‌کند، برای «تست دستی» در پنل مانیتورینگ
    # امن است — نتیجه را نشان می‌دهد بدون تغییر داده‌ی واقعی
    logger.info("در حال دریافت برنامه‌ی خاموشی %s برای %s", city, date.jalali_long)
    return gather_records(
        city, province, date,
        max_search_results=6,
        request_delay=1.0,
        session=build_session(),
    )


# ---------------------------------------------------------------------------
# مرحله ۲ — پاک‌سازی داده‌ی خاموشیِ روزهای گذشته
# ---------------------------------------------------------------------------

def purge_old_outages(session: Session, city: str, before_date: str) -> int:
    """Delete this city's outages from days before `before_date`. Returns the count.

    Only ever touches the Outage table — subscriber records and admin
    accounts are never affected by this cleanup.
    """
    # ⚠️ این تنها تابع حذف‌کننده در کل پروژه است. عمداً:
    #   • فقط روی مدل Outage عمل می‌کند (نه Subscriber، نه AdminUser)
    #   • شرط حذف «کوچک‌تر از تاریخ هدف» است، نه «مخالف تاریخ هدف» — تا اگر
    #     روزی سیستم برای یک تاریخ گذشته اجرا شد، داده‌ی امروز نابود نشود
    #   • محدود به همان شهر است، تا شهرهای دیگر تحت تأثیر قرار نگیرند
    stale = session.exec(
        select(Outage).where(
            Outage.city == city,
            Outage.date_gregorian < before_date,
        )
    ).all()

    if not stale:
        return 0

    session.exec(
        delete(Outage).where(
            Outage.city == city,
            Outage.date_gregorian < before_date,
        )
    )
    session.commit()
    logger.info("%d خاموشی مربوط به روزهای گذشته پاک شد", len(stale))
    return len(stale)


# ---------------------------------------------------------------------------
# مرحله ۳ — ذخیره‌سازی
# ---------------------------------------------------------------------------

def _already_stored(session: Session, record: OutageRecord) -> bool:
    # همان منطق OutageRecord.key() ولی به‌صورت کوئری روی دیتابیس، تا اسکرِیپ
    # تکراری در طول روز، ردیف تکراری نسازد
    existing = session.exec(
        select(Outage).where(
            Outage.city == record.city,
            Outage.date_gregorian == record.date_gregorian,
            Outage.location == record.location,
            Outage.start_time == record.start_time,
            Outage.end_time == record.end_time,
        )
    ).first()
    return existing is not None


def store_records(session: Session, records: list[OutageRecord]) -> list[Outage]:
    # رکوردهای تازه (OutageRecord از outage_scraper) را به ردیف‌های Outage
    # در دیتابیس تبدیل و ذخیره می‌کند؛ رکوردهای از قبل ذخیره‌شده را رد می‌کند
    stored: list[Outage] = []
    for record in records:
        if _already_stored(session, record):
            continue
        outage = Outage(
            city=record.city,
            province=record.province,
            date_jalali=record.date_jalali,
            date_gregorian=record.date_gregorian,
            location=record.location,
            start_time=record.start_time,
            end_time=record.end_time,
            neighborhood_code=record.neighborhood_code,
            source_url=record.source_url,
            source_title=record.source_title,
        )
        session.add(outage)
        stored.append(outage)
    session.commit()
    return stored


# ---------------------------------------------------------------------------
# مرحله ۴ — تطبیق مشترکین
# ---------------------------------------------------------------------------

def load_todays_outages(session: Session, city: str, date: OutageDate) -> list[Outage]:
    """Read back every outage stored for this city/date."""
    return list(session.exec(
        select(Outage).where(
            Outage.city == city,
            Outage.date_gregorian == str(date.gregorian),
        )
    ).all())


def load_active_subscribers(session: Session, city: str) -> list[Subscriber]:
    """Every subscriber of this city who is still active."""
    return list(session.exec(
        select(Subscriber).where(
            Subscriber.city == city,
            Subscriber.is_active == True,  # noqa: E712 — SQLModel به == نیاز دارد، نه is
        )
    ).all())


def match_all(subscribers: list[Subscriber], outages: list[Outage]) -> list[SubscriberMatch]:
    """Return only the subscribers who actually have an outage today."""
    results: list[SubscriberMatch] = []
    for subscriber in subscribers:
        hits = match_subscriber(subscriber, outages)
        if not hits:
            continue
        results.append(SubscriberMatch(
            full_name=subscriber.full_name,
            mobile=subscriber.mobile,
            neighborhood=subscriber.neighborhood,
            outages=[_to_slot(o) for o in hits],
        ))
    return results


def _to_slot(outage: Outage) -> OutageSlot:
    """Convert a database row into a session-independent plain value."""
    return OutageSlot(
        location=outage.location,
        start_time=outage.start_time,
        end_time=outage.end_time,
        neighborhood_code=outage.neighborhood_code,
        source_url=outage.source_url,
    )


# ---------------------------------------------------------------------------
# مرحله ۵ — ارکستراسیون
# ---------------------------------------------------------------------------

def sync_and_match(city: str, province: str, date: OutageDate) -> SyncResult:
    """Run the full pipeline, persisting results. Returns what happened.

    This is the "real" run: it purges yesterday's outages and stores today's.
    For a read-only check that writes nothing, use dry_run() instead.
    """
    result = SyncResult(
        city=city, province=province,
        date_jalali=date.jalali_long, date_gregorian=str(date.gregorian),
    )

    init_db()
    try:
        records = fetch_records(city, province, date)
        result.fetched_count = len(records)

        with Session(engine) as session:
            # پاک‌سازی قبل از ذخیره: داده‌ی خاموشی روزهای گذشته دیگر لازم نیست
            result.purged_count = purge_old_outages(session, city, str(date.gregorian))
            result.stored_count = len(store_records(session, records))
            result.saved = True

            outages = load_todays_outages(session, city, date)
            subscribers = load_active_subscribers(session, city)
            result.outages_today = len(outages)
            result.active_subscribers = len(subscribers)
            result.matches = match_all(subscribers, outages)
    except Exception as exc:  # noqa: BLE001 — هر خطایی باید در نتیجه گزارش شود
        # به‌جای کرش کردن، خطا را داخل نتیجه برمی‌گردانیم تا هم CLI و هم
        # پنل مانیتورینگ بتوانند آن را به کاربر نشان دهند
        logger.exception("اجرای همگام‌سازی شکست خورد")
        result.error = f"{type(exc).__name__}: {exc}"

    return result


def dry_run(city: str, province: str, date: OutageDate) -> SyncResult:
    """Exercise the whole workflow **without writing anything**.

    Used by the monitoring panel's manual test buttons: it hits the real
    source and matches against the real subscriber list, but never stores,
    never purges, and works regardless of whether the system is enabled.
    """
    result = SyncResult(
        city=city, province=province,
        date_jalali=date.jalali_long, date_gregorian=str(date.gregorian),
    )

    try:
        # ۱) دریافت واقعی از منبع — این تنها بخشی است که به بیرون وصل می‌شود
        records = fetch_records(city, province, date)
        result.fetched_count = len(records)

        with Session(engine) as session:
            # ۲) تطبیق روی رکوردهای تازه‌ی دریافتی (نه روی دیتابیس)، تا نتیجه
            #    دقیقاً همان چیزی باشد که در اجرای واقعی رخ می‌داد
            subscribers = load_active_subscribers(session, city)
            result.active_subscribers = len(subscribers)

            # OutageRecord را به Outage موقتِ در-حافظه تبدیل می‌کنیم؛ چون
            # session.add() صدا زده نمی‌شود، هیچ‌چیز در دیتابیس نوشته نمی‌شود
            in_memory = [
                Outage(
                    city=r.city, province=r.province,
                    date_jalali=r.date_jalali, date_gregorian=r.date_gregorian,
                    location=r.location, start_time=r.start_time, end_time=r.end_time,
                    neighborhood_code=r.neighborhood_code, source_url=r.source_url,
                )
                for r in records
            ]
            result.outages_today = len(in_memory)
            result.matches = match_all(subscribers, in_memory)
    except Exception as exc:  # noqa: BLE001
        logger.exception("اجرای آزمایشی شکست خورد")
        result.error = f"{type(exc).__name__}: {exc}"

    # saved همیشه False می‌ماند — این ضمانتِ «تست چیزی ذخیره نمی‌کند» است
    return result


# ---------------------------------------------------------------------------
# رابط خط فرمان
# ---------------------------------------------------------------------------

def print_result(result: SyncResult) -> None:
    """Human-readable rendering of a SyncResult — CLI only."""
    if result.error:
        print(f"خطا در اجرا: {result.error}")
        return

    if result.purged_count:
        print(f"{result.purged_count} خاموشی مربوط به روزهای گذشته پاک شد")
    if result.saved:
        print(f"{result.stored_count} ردیف تازه ذخیره شد (از {result.fetched_count} ردیف دریافتی)")
    else:
        print(f"[اجرای آزمایشی — چیزی ذخیره نشد] {result.fetched_count} ردیف دریافت شد")

    if result.active_subscribers == 0:
        print("هیچ مشترک فعالی برای این شهر ثبت نشده است.")
        return

    if not result.matches:
        print(f"هیچ‌کدام از {result.active_subscribers} مشترک فعال، امروز خاموشی ندارند.")
        return

    for match in result.matches:
        print(f"\n{match.full_name} ({match.mobile}) - محله: {match.neighborhood}")
        for slot in match.outages:
            print(f"  {slot.start_time}-{slot.end_time}  {slot.location}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="هم‌خوانی روزانه‌ی خاموشی با مشترکین ثبت‌شده")
    parser.add_argument("--city", default="بابل")
    parser.add_argument("--province", default="مازندران")
    parser.add_argument("--date", default=None)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="اجرای آزمایشی: بررسی کل ورک‌فلو بدون ذخیره‌سازی هیچ داده‌ای",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    date = OutageDate.parse(args.date)
    run = dry_run if args.dry_run else sync_and_match
    result = run(args.city, args.province, date)
    print_result(result)
    return 1 if result.error else 0


if __name__ == "__main__":
    raise SystemExit(main())
