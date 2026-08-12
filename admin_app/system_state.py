"""The global on/off switch, and the log of pipeline runs.

Kept in its own module so both the scheduled job and the monitoring panel
read the same state through the same functions, rather than each poking at
the SystemSetting row directly.
"""
# دو مسئولیت مرتبط:
#   ۱) خواندن/نوشتن کلید فعال‌بودن کل سامانه (SystemSetting)
#   ۲) ثبت هر اجرای خط لوله در تاریخچه (SyncRun)
#
# قاعده‌ی اصلی: وقتی سامانه غیرفعال است، اجرای واقعی (ذخیره‌سازی/ارسال)
# انجام نمی‌شود؛ ولی تست دستی همچنان کار می‌کند تا ادمین بتواند قبل از
# روشن کردن سامانه، از سالم بودن ورک‌فلو مطمئن شود.
from __future__ import annotations

import datetime as _dt

from sqlmodel import Session, desc, select

from .models import SyncRun, SystemSetting

# چون جدول تنظیمات فقط یک ردیف دارد، شناسه‌اش ثابت است
_SETTING_ID = 1


# ---------------------------------------------------------------------------
# کلید فعال / غیرفعال
# ---------------------------------------------------------------------------

def get_setting(session: Session) -> SystemSetting:
    """Read the settings row, creating it (disabled) on first use."""
    setting = session.get(SystemSetting, _SETTING_ID)
    if setting is None:
        # اولین اجرا: ردیف تنظیمات را با حالت «خاموش» می‌سازیم. پیش‌فرضِ
        # خاموش عمدی است تا سامانه بدون تأیید صریح ادمین کاری نکند.
        setting = SystemSetting(id=_SETTING_ID, is_enabled=False)
        session.add(setting)
        session.commit()
        session.refresh(setting)
    return setting


def is_enabled(session: Session) -> bool:
    """True when the admin has switched the system on."""
    return get_setting(session).is_enabled


def set_enabled(session: Session, enabled: bool, *, changed_by: str) -> SystemSetting:
    """Turn the whole system on or off, recording who did it."""
    setting = get_setting(session)
    setting.is_enabled = enabled
    setting.updated_at = _dt.datetime.now()
    setting.updated_by = changed_by
    session.add(setting)
    session.commit()
    session.refresh(setting)
    return setting


# ---------------------------------------------------------------------------
# تاریخچه‌ی اجراها
# ---------------------------------------------------------------------------

def record_run(
    session: Session,
    *,
    city: str,
    is_dry_run: bool,
    fetched_count: int = 0,
    stored_count: int = 0,
    purged_count: int = 0,
    matched_count: int = 0,
    error_message: str | None = None,
    started_at: _dt.datetime | None = None,
) -> SyncRun:
    """Append one execution to the run history."""
    run = SyncRun(
        started_at=started_at or _dt.datetime.now(),
        finished_at=_dt.datetime.now(),
        city=city,
        # وضعیت مستقیماً از وجود یا نبود پیام خطا استنتاج می‌شود، تا این دو
        # هیچ‌وقت با هم ناسازگار نشوند
        status="failed" if error_message else "success",
        is_dry_run=is_dry_run,
        fetched_count=fetched_count,
        stored_count=stored_count,
        purged_count=purged_count,
        matched_count=matched_count,
        error_message=error_message,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def recent_runs(session: Session, limit: int = 10) -> list[SyncRun]:
    """Most recent executions first — the monitoring panel's history table."""
    return list(session.exec(
        select(SyncRun).order_by(desc(SyncRun.started_at)).limit(limit)
    ).all())


def last_real_run(session: Session) -> SyncRun | None:
    """The most recent non-test run, used for the 'last sync' health check."""
    # تست‌ها عمداً کنار گذاشته می‌شوند: اینکه ادمین دکمه‌ی تست را زده باشد
    # نباید سامانه را «سالم و به‌روز» نشان دهد در حالی که اجرای واقعی نشده
    return session.exec(
        select(SyncRun)
        .where(SyncRun.is_dry_run == False)  # noqa: E712 — SQLModel به == نیاز دارد
        .order_by(desc(SyncRun.started_at))
    ).first()
