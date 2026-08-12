"""Authentication for the operator/admin panel.

Session-cookie login: the operator signs in once through an HTML form,
receives an opaque random token in an httponly cookie, and that token is
validated against the AdminSession table on every request.

Passwords are never stored — only a salted scrypt hash. scrypt comes
from Python's own hashlib, so this adds no new dependency.
"""
# این ماژول تمام منطق «چه کسی اجازه‌ی ورود دارد» را در یک جا نگه می‌دارد،
# تا main.py فقط مسیرها را تعریف کند و درگیر جزئیات رمز/نشست نشود.
#
# جریان کلی کار:
#   ۱) اپراتور نام کاربری و رمز را در فرم ورود می‌زند
#   ۲) verify_password() رمز را با هش ذخیره‌شده مقایسه می‌کند
#   ۳) در صورت درستی، create_session() یک توکن تصادفی می‌سازد و در DB ثبت می‌کند
#   ۴) توکن داخل کوکی httponly به مرورگر داده می‌شود
#   ۵) در هر درخواست بعدی، require_admin_* آن کوکی را اعتبارسنجی می‌کند
from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import secrets

from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session, select

from .db import get_session
from .models import AdminSession, AdminUser

# ---------------------------------------------------------------------------
# تنظیمات
# ---------------------------------------------------------------------------

# نام کوکی‌ای که توکن نشست در آن نگهداری می‌شود
COOKIE_NAME = "outage_admin_session"

# طول عمر نشست: حدود یک شیفت کاری اپراتور. بعد از این مدت باید دوباره وارد شود.
SESSION_TTL = _dt.timedelta(hours=12)

# مسیری که کاربر احراز هویت‌نشده به آن هدایت می‌شود
LOGIN_PATH = "/login"

# پارامترهای scrypt — مقادیر پیشنهادی برای ورود تعاملی (RFC 7914).
# عمداً «کند» هستند تا حمله‌ی حدس رمز (brute force) پرهزینه شود.
_SCRYPT_N = 2 ** 14        # هزینه‌ی CPU/حافظه
_SCRYPT_R = 8              # اندازه‌ی بلاک
_SCRYPT_P = 1              # موازی‌سازی
_SCRYPT_MAXMEM = 64 * 1024 * 1024   # سقف حافظه‌ی مجاز (۶۴ مگابایت)
_SALT_BYTES = 16
_HASH_BYTES = 64


# ---------------------------------------------------------------------------
# مرحله ۱ — هش کردن و بررسی رمز عبور
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Hash a plaintext password with a fresh random salt.

    Returns a self-describing string so the scrypt parameters can be
    changed later without invalidating existing hashes.
    """
    # برای هر رمز یک salt تصادفی جدید ساخته می‌شود، تا دو کاربر با رمز
    # یکسان هم هش متفاوتی داشته باشند (جلوگیری از rainbow table)
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = _scrypt(password, salt)

    # قالب ذخیره‌سازی: پارامترها هم داخل خود رشته می‌آیند تا در آینده
    # بتوان سختی هش را بالا برد بدون اینکه رمزهای قدیمی بی‌اعتبار شوند
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Check a plaintext password against a stored hash. Never raises."""
    try:
        # رشته‌ی ذخیره‌شده را به اجزایش می‌شکنیم تا با همان پارامترهای
        # اصلی (نه پارامترهای فعلی ماژول) دوباره هش را حساب کنیم
        algorithm, n, r, p, salt_hex, digest_hex = stored.split("$")
        if algorithm != "scrypt":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = _scrypt(
            password,
            bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p), dklen=len(expected),
        )
    except (ValueError, AttributeError):
        # هش خراب یا با قالب ناشناخته = ورود ناموفق، نه کرش کردن برنامه
        return False

    # مقایسه‌ی زمان-ثابت: جلوگیری از حمله‌ی timing که با اندازه‌گیری
    # زمان پاسخ، رمز را کاراکتربه‌کاراکتر حدس می‌زند
    return hmac.compare_digest(expected, actual)


def _scrypt(
    password: str,
    salt: bytes,
    *,
    n: int = _SCRYPT_N,
    r: int = _SCRYPT_R,
    p: int = _SCRYPT_P,
    dklen: int = _HASH_BYTES,
) -> bytes:
    """Thin wrapper so hashing and verifying always agree on the call shape."""
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n, r=r, p=p,
        maxmem=_SCRYPT_MAXMEM,
        dklen=dklen,
    )


# ---------------------------------------------------------------------------
# مرحله ۲ — ساخت، اعتبارسنجی و پایان دادن به نشست
# ---------------------------------------------------------------------------

def authenticate(session: Session, username: str, password: str) -> AdminUser | None:
    """Return the matching active admin, or None if the credentials are wrong."""
    admin = session.exec(
        select(AdminUser).where(AdminUser.username == username)
    ).first()

    # نکته‌ی امنیتی: چه کاربر وجود نداشته باشد، چه رمز غلط باشد، چه حساب
    # غیرفعال باشد — همگی None برمی‌گردانند تا مهاجم نفهمد کدام
    # نام کاربری واقعاً در سیستم وجود دارد.
    if admin is None or not admin.is_active:
        return None
    if not verify_password(password, admin.password_hash):
        return None
    return admin


def create_session(session: Session, admin: AdminUser) -> str:
    """Issue a new session token for an admin."""
    # توکن با secrets ساخته می‌شود (نه random) چون باید از نظر رمزنگاری
    # غیرقابل‌حدس باشد؛ ۳۲ بایت تصادفی برای این کار کافی است
    token = secrets.token_urlsafe(32)

    # انقضای نشست در دیتابیس از همان SESSION_TTL می‌آید که کوکی هم
    # استفاده می‌کند، پس این دو هیچ‌وقت از هم جدا نمی‌افتند
    session.add(AdminSession(
        token=token,
        admin_id=admin.id,
        expires_at=_dt.datetime.now() + SESSION_TTL,
    ))
    session.commit()
    return token


def destroy_session(session: Session, token: str | None) -> None:
    """Delete a session row so its cookie stops working (logout)."""
    if not token:
        return
    row = session.exec(select(AdminSession).where(AdminSession.token == token)).first()
    if row is not None:
        session.delete(row)
        session.commit()


def resolve_admin(request: Request, session: Session) -> AdminUser | None:
    """Find the signed-in admin behind a request, or None. Does not raise."""
    # ۱) توکن را از کوکی درخواست بردار
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None

    # ۲) نشست متناظر را در دیتابیس پیدا کن
    row = session.exec(select(AdminSession).where(AdminSession.token == token)).first()
    if row is None:
        return None

    # ۳) اگر منقضی شده، همان‌جا پاکش کن تا جدول نشست‌ها انباشته نشود
    if row.expires_at < _dt.datetime.now():
        session.delete(row)
        session.commit()
        return None

    # ۴) کاربر مربوطه را برگردان — مگر اینکه در این فاصله غیرفعال شده باشد
    admin = session.get(AdminUser, row.admin_id)
    if admin is None or not admin.is_active:
        return None
    return admin


# ---------------------------------------------------------------------------
# مرحله ۳ — نگهبان مسیرها (FastAPI dependencies)
# ---------------------------------------------------------------------------
# دو نگهبان داریم چون رفتار درست برای «صفحه» و «API» فرق می‌کند:
#   - کاربر مرورگر باید به صفحه‌ی ورود هدایت شود (۳۰۳)
#   - فراخوانی API باید خطای تمیز ۴۰۱ بگیرد، نه صفحه‌ی HTML
# هر دو از همان resolve_admin() بالا استفاده می‌کنند، پس منطق تکراری نیست.

def require_admin_page(
    request: Request,
    session: Session = Depends(get_session),
) -> AdminUser:
    """Guard for HTML pages: redirects a signed-out visitor to the login page."""
    admin = resolve_admin(request, session)
    if admin is None:
        # ۳۰۳ به مرورگر می‌گوید «با GET به این آدرس برو» — رفتار درست
        # برای هدایت بعد از یک درخواست ناموفق
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="ابتدا باید وارد شوید",
            headers={"Location": LOGIN_PATH},
        )
    return admin


def require_admin_api(
    request: Request,
    session: Session = Depends(get_session),
) -> AdminUser:
    """Guard for JSON endpoints: returns 401 instead of redirecting."""
    admin = resolve_admin(request, session)
    if admin is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="برای دسترسی به این بخش باید وارد شوید",
        )
    return admin
