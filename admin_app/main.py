"""FastAPI admin app: subscriber registration + pipeline monitoring.

Run with: uvicorn admin_app.main:app --reload

Every route except the login page requires a signed-in operator; the
authentication itself lives in auth.py and the monitoring logic in
monitoring.py — this module only wires them to URLs.
"""
# ساختار این فایل:
#   بخش ۱ — ورود و خروج (تنها مسیرهای باز)
#   بخش ۲ — تب ثبت مشترک
#   بخش ۳ — تب مانیتورینگ (وضعیت، کلید فعال/غیرفعال، تست‌ها)
#
# قاعده: هیچ مسیری بیرون از بخش ۱ نباید بدون نگهبان (require_admin_*) باشد.
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlmodel import Session, select

from outage_scraper.dates import OutageDate

from .auth import (
    COOKIE_NAME,
    LOGIN_PATH,
    SESSION_TTL,
    authenticate,
    create_session,
    destroy_session,
    require_admin_api,
    require_admin_page,
)
from .db import engine, get_session, init_db
from .models import AdminUser, Subscriber
from .monitoring import (
    collect_status,
    data_test_to_dict,
    matching_test_to_dict,
    result_to_dict,
    run_data_test,
    run_matching_test,
)
from .sync import sync_and_match
from .system_state import is_enabled, record_run, set_enabled

logger = logging.getLogger("admin_app.main")

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# شهر پیش‌فرضی که پنل مانیتورینگ آن را نشان می‌دهد. وقتی سامانه چندشهری
# شد، این باید از تنظیمات یا از انتخاب کاربر بیاید.
DEFAULT_CITY = "بابل"
DEFAULT_PROVINCE = "مازندران"

init_db()  # جدول‌ها را قبل از شروع سرو کردن درخواست‌ها می‌سازد (idempotent)

app = FastAPI(title="پنل مدیریت سامانه هشدار خاموشی")


class SubscriberIn(BaseModel):
    # داده‌ای که فرم ثبت می‌فرستد؛ از خودِ مدل جدول جدا نگه داشته می‌شود
    # تا فیلدهای داخلی (id، created_at) از بیرون قابل‌تنظیم نباشند
    full_name: str
    mobile: str
    province: str
    city: str
    neighborhood: str
    neighborhood_code: str | None = None


class EnabledIn(BaseModel):
    """Body of the on/off switch request."""

    enabled: bool


# ---------------------------------------------------------------------------
# بخش ۱ — ورود و خروج (تنها مسیرهای باز، بدون احراز هویت)
# ---------------------------------------------------------------------------

@app.get(LOGIN_PATH, response_class=HTMLResponse)
def login_form(request: Request) -> Response:
    """The sign-in page itself — necessarily reachable while signed out."""
    return templates.TemplateResponse(request, "login.html")


@app.post(LOGIN_PATH)
def login_submit(
    username: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
) -> Response:
    """Validate credentials, then hand the browser a session cookie."""
    # ۱) بررسی نام کاربری و رمز
    admin = authenticate(session, username, password)
    if admin is None:
        # برگشت به فرم ورود با نشانه‌ی خطا. عمداً جزئیات نمی‌دهیم که
        # مشخص نشود کدام‌یک (نام کاربری یا رمز) اشتباه بوده است.
        return RedirectResponse(f"{LOGIN_PATH}?error=1", status_code=303)

    # ۲) ساخت نشست جدید در دیتابیس
    token = create_session(session, admin)

    # ۳) قرار دادن توکن در کوکی و هدایت به صفحه‌ی اصلی
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        token,
        # httponly: جاوااسکریپت صفحه نمی‌تواند کوکی را بخواند (دفاع در برابر XSS)
        httponly=True,
        # samesite=lax: کوکی همراه درخواست‌های سایت دیگر فرستاده نمی‌شود (دفاع در برابر CSRF)
        samesite="lax",
        # max_age (ثانیه) به‌جای expires (تاریخ) استفاده شده تا مشکل
        # منطقه‌ی زمانی پیش نیاید؛ همان SESSION_TTL که انقضای دیتابیس را
        # هم تعیین می‌کند، پس کوکی و نشست همیشه هم‌زمان منقضی می‌شوند
        max_age=int(SESSION_TTL.total_seconds()),
        path="/",
    )
    return response


@app.post("/logout")
def logout(request: Request, session: Session = Depends(get_session)) -> Response:
    """Sign out: delete the session row, then clear the cookie."""
    # نشست را از دیتابیس حذف می‌کنیم تا حتی اگر کوکی جایی کپی شده باشد،
    # دیگر کار نکند. (پاک کردن صرفِ کوکی برای امنیت کافی نیست.)
    destroy_session(session, request.cookies.get(COOKIE_NAME))

    response = RedirectResponse(LOGIN_PATH, status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


# ---------------------------------------------------------------------------
# بخش ۲ — تب ثبت مشترک
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def registration_page(
    request: Request,
    admin: AdminUser = Depends(require_admin_page),
) -> Response:
    """Subscriber registration tab. Redirects to /login when signed out."""
    return templates.TemplateResponse(request, "register.html", {"active_tab": "register"})


@app.post("/api/subscribers", response_model=Subscriber)
def create_subscriber(
    data: SubscriberIn,
    admin: AdminUser = Depends(require_admin_api),
) -> Subscriber:
    with Session(engine) as session:
        exists = session.exec(
            select(Subscriber).where(Subscriber.mobile == data.mobile)
        ).first()
        if exists:
            raise HTTPException(400, "این شماره قبلاً ثبت شده است")

        subscriber = Subscriber(**data.model_dump())
        session.add(subscriber)
        session.commit()
        session.refresh(subscriber)
        return subscriber


@app.get("/api/subscribers", response_model=list[Subscriber])
def list_subscribers(admin: AdminUser = Depends(require_admin_api)) -> list[Subscriber]:
    # فهرست مشترکین ثبت‌شده تا الان، تا اپراتور پیشرفت ثبت پله‌پله را ببیند.
    # این مسیر داده‌ی شخصی (نام و موبایل) برمی‌گرداند، پس حتماً باید
    # پشت نگهبان احراز هویت بماند.
    with Session(engine) as session:
        return session.exec(select(Subscriber).order_by(Subscriber.created_at.desc())).all()


@app.delete("/api/subscribers/{subscriber_id}")
def delete_subscriber(
    subscriber_id: int,
    admin: AdminUser = Depends(require_admin_api),
) -> dict:
    """Remove one subscriber — used for wrong entries or cancelled subscriptions."""
    with Session(engine) as session:
        subscriber = session.get(Subscriber, subscriber_id)
        if subscriber is None:
            raise HTTPException(404, "این مشترک یافت نشد")

        # نام و شماره را قبل از حذف برمی‌داریم تا هم در لاگ ثبت شود و هم
        # رابط کاربری بتواند پیام تأیید مشخصی نشان دهد
        removed = {"full_name": subscriber.full_name, "mobile": subscriber.mobile}
        session.delete(subscriber)
        session.commit()

    # ثبت در لاگ سرور: حذف داده‌ی شخصی باید قابل پیگیری باشد
    logger.info("مشترک %s (%s) توسط %s حذف شد",
                removed["full_name"], removed["mobile"], admin.username)
    return {"deleted": True, **removed}


# ---------------------------------------------------------------------------
# بخش ۳ — تب مانیتورینگ
# ---------------------------------------------------------------------------

@app.get("/monitoring", response_class=HTMLResponse)
def monitoring_page(
    request: Request,
    admin: AdminUser = Depends(require_admin_page),
) -> Response:
    """Monitoring tab — the dashboard shell; data arrives via the APIs below."""
    return templates.TemplateResponse(request, "monitoring.html", {"active_tab": "monitoring"})


@app.get("/api/monitoring/status")
def monitoring_status(
    admin: AdminUser = Depends(require_admin_api),
    session: Session = Depends(get_session),
) -> dict:
    """Health of every pipeline stage, plus the run history."""
    status = collect_status(session, DEFAULT_CITY, DEFAULT_PROVINCE)
    return {
        "is_enabled": status.is_enabled,
        "enabled_summary": status.enabled_summary,
        "stages": [
            {
                "key": s.key, "title": s.title,
                "status": s.status, "summary": s.summary,
                "details": s.details,
            }
            for s in status.stages
        ],
        "history": status.history,
    }


@app.post("/api/monitoring/enabled")
def set_system_enabled(
    body: EnabledIn,
    admin: AdminUser = Depends(require_admin_api),
    session: Session = Depends(get_session),
) -> dict:
    """Turn the whole system on or off."""
    # نام ادمین ثبت می‌شود تا بعداً معلوم باشد چه کسی سامانه را خاموش/روشن کرده
    setting = set_enabled(session, body.enabled, changed_by=admin.username)
    logger.info("سامانه توسط %s %s شد", admin.username, "فعال" if body.enabled else "غیرفعال")
    return {
        "is_enabled": setting.is_enabled,
        "updated_by": setting.updated_by,
        "updated_at": setting.updated_at.isoformat(),
    }


@app.post("/api/monitoring/test/data")
def test_data_collection(
    admin: AdminUser = Depends(require_admin_api),
    session: Session = Depends(get_session),
) -> dict:
    """Manual test: fetch today's outage list from the source, saving nothing.

    Returns only the outage data — matching against subscribers is not part
    of this check, because that happens automatically during a real run.
    Works whether or not the system is enabled, so the admin can verify the
    source before switching it on.
    """
    result = run_data_test(DEFAULT_CITY, DEFAULT_PROVINCE)

    # خودِ اجرای تست در تاریخچه ثبت می‌شود (با برچسب «تست») تا معلوم باشد
    # چه زمانی و با چه نتیجه‌ای بررسی شده — ولی روی وضعیت سلامت اثر ندارد
    record_run(
        session, city=DEFAULT_CITY, is_dry_run=True,
        fetched_count=result.count,
        error_message=result.error,
    )
    return data_test_to_dict(result)


@app.post("/api/monitoring/test/matching")
def test_matching(
    admin: AdminUser = Depends(require_admin_api),
    session: Session = Depends(get_session),
) -> dict:
    """Manual test: match live outage data against the real subscriber list.

    Saves nothing. Returns both matched and unmatched subscribers, so a
    subscriber who unexpectedly gets no notification can be diagnosed.
    """
    result = run_matching_test(session, DEFAULT_CITY, DEFAULT_PROVINCE)

    record_run(
        session, city=DEFAULT_CITY, is_dry_run=True,
        fetched_count=result.total_outages,
        matched_count=len(result.matched),
        error_message=result.error,
    )
    return matching_test_to_dict(result)


@app.post("/api/monitoring/run-sync")
def run_real_sync(
    admin: AdminUser = Depends(require_admin_api),
    session: Session = Depends(get_session),
) -> dict:
    """Run the real pipeline: purge old outages, store today's, match subscribers."""
    # اجرای واقعی فقط وقتی مجاز است که ادمین سامانه را فعال کرده باشد —
    # این همان محافظی است که جلوی ذخیره‌سازی ناخواسته را می‌گیرد
    if not is_enabled(session):
        raise HTTPException(
            status_code=409,
            detail="سامانه غیرفعال است. برای اجرای واقعی، ابتدا آن را فعال کنید.",
        )

    result = sync_and_match(DEFAULT_CITY, DEFAULT_PROVINCE, OutageDate.parse(None))
    record_run(
        session, city=DEFAULT_CITY, is_dry_run=False,
        fetched_count=result.fetched_count,
        stored_count=result.stored_count,
        purged_count=result.purged_count,
        matched_count=result.matched_count,
        error_message=result.error,
    )
    return result_to_dict(result)
