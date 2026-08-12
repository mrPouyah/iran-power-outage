"""SQLModel table definitions for the admin app's SQLite database."""
# این فایل جدول‌های پایگاه‌داده را تعریف می‌کند:
#   ۱) Subscriber    — مشترکین ثبت‌شده توسط اپراتور
#   ۲) Outage        — خاموشی‌های برداشت‌شده از منابع رسمی
#   ۳) AdminUser     — کاربران مجاز به ورود به پنل اپراتور
#   ۴) AdminSession  — نشست‌های فعال ورود (کوکی‌های معتبر)
#   ۵) SystemSetting — کلید فعال/غیرفعال کل سامانه
#   ۶) SyncRun       — تاریخچه‌ی اجراها، برای نمایش در پنل مانیتورینگ
# همه با SQLModel نوشته شده‌اند تا هم مدل پایتونی باشند و هم جدول دیتابیس.
from __future__ import annotations

import datetime as _dt
from typing import Optional

from sqlmodel import Field, SQLModel


class Subscriber(SQLModel, table=True):
    """One customer registered by an operator over the phone."""

    # اطلاعاتی که بازاریاب تلفنی از مشتری می‌گیرد و ثبت می‌کند
    id: Optional[int] = Field(default=None, primary_key=True)
    full_name: str
    mobile: str = Field(unique=True, index=True)
    province: str
    city: str
    neighborhood: str  # محله/خیابان سکونت، به‌صورت متن آزاد فارسی (پایه‌ی تطبیق)
    # «کد محله»: فیلد اختیاری و فعلاً فقط برای ذخیره؛ چون مشخص نیست دقیقاً
    # همان کدی است که منابع خاموشی منتشر می‌کنند یا نه، در matcher.py
    # استفاده نمی‌شود تا این ابهام برطرف شود.
    neighborhood_code: Optional[str] = None
    is_active: bool = True
    created_at: _dt.datetime = Field(default_factory=_dt.datetime.now)


class Outage(SQLModel, table=True):
    """One persisted copy of an outage_scraper.models.OutageRecord."""

    # همان فیلدهای OutageRecord (در outage_scraper/models.py)، به‌اضافه‌ی
    # fetched_at، تا نتیجه‌ی هر اسکرِیپ به‌جای فقط چاپ‌شدن، ردیف پایدار بشود
    id: Optional[int] = Field(default=None, primary_key=True)
    city: str
    province: str
    date_jalali: str
    date_gregorian: str
    location: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    neighborhood_code: Optional[str] = None
    source_url: str = ""
    source_title: str = ""
    fetched_at: _dt.datetime = Field(default_factory=_dt.datetime.now)


class AdminUser(SQLModel, table=True):
    """An operator allowed to sign in to the admin panel."""

    # کاربرانی که اجازه‌ی ورود به پنل ثبت مشترک را دارند.
    # نکته‌ی امنیتی: رمز عبور هرگز به‌صورت خام ذخیره نمی‌شود — فقط
    # حاصلِ هش scrypt به‌همراه salt تصادفی (تولیدشده در auth.py).
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    # با غیرفعال‌کردن این فیلد، دسترسی اپراتور بدون حذف سابقه‌اش قطع می‌شود
    is_active: bool = True
    created_at: _dt.datetime = Field(default_factory=_dt.datetime.now)


class AdminSession(SQLModel, table=True):
    """One active login session, referenced by the browser's cookie."""

    # هر بار ورود موفق، یک ردیف اینجا ساخته می‌شود و مقدار token داخل
    # کوکی مرورگر قرار می‌گیرد. چون نشست‌ها در دیتابیس‌اند (نه در حافظه)،
    # با ری‌استارت شدن سرور، اپراتورها از حساب خارج نمی‌شوند.
    id: Optional[int] = Field(default=None, primary_key=True)
    token: str = Field(unique=True, index=True)
    admin_id: int = Field(foreign_key="adminuser.id", index=True)
    created_at: _dt.datetime = Field(default_factory=_dt.datetime.now)
    # تاریخ انقضا؛ نشست منقضی‌شده حتی اگر کوکی‌اش باقی باشد نامعتبر است
    expires_at: _dt.datetime


class SystemSetting(SQLModel, table=True):
    """Single-row table holding the global on/off switch."""

    # این جدول عمداً فقط یک ردیف دارد (id=1) و کلید اصلی روشن/خاموش بودن
    # کل سامانه است. وقتی خاموش باشد، اجرای زمان‌بندی‌شده هیچ داده‌ای ذخیره
    # یا پیامکی ارسال نمی‌کند — ولی «تست دستی» همچنان کار می‌کند.
    id: Optional[int] = Field(default=None, primary_key=True)
    # پیش‌فرض خاموش است: تا وقتی ادمین صریحاً روشن نکرده، سامانه
    # به‌طور تصادفی شروع به ذخیره‌سازی یا ارسال پیامک نمی‌کند
    is_enabled: bool = False
    updated_at: _dt.datetime = Field(default_factory=_dt.datetime.now)
    # نام کاربری ادمینی که آخرین بار وضعیت را عوض کرد (برای پیگیری)
    updated_by: Optional[str] = None


class SyncRun(SQLModel, table=True):
    """Log of one pipeline execution, so the monitoring panel can show history."""

    # بدون این جدول، پنل مانیتورینگ نمی‌تواند بگوید «آخرین اجرا کِی بود و
    # آیا موفق بود». هر اجرا — چه موفق چه ناموفق — اینجا ثبت می‌شود.
    id: Optional[int] = Field(default=None, primary_key=True)
    started_at: _dt.datetime = Field(default_factory=_dt.datetime.now, index=True)
    finished_at: Optional[_dt.datetime] = None
    city: str = ""
    # "success" یا "failed" — مبنای رنگ سبز/قرمز در پنل مانیتورینگ
    status: str = "success"
    # آیا این اجرا واقعی بود یا فقط تست؟ تست‌ها هرگز داده ذخیره نمی‌کنند.
    is_dry_run: bool = False
    fetched_count: int = 0
    stored_count: int = 0
    purged_count: int = 0
    matched_count: int = 0
    # متن خطا در صورت شکست، تا اپراتور بدون باز کردن لاگ سرور علت را ببیند
    error_message: Optional[str] = None
