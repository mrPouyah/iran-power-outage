"""Create or update an admin account from the command line.

Usage:
    python -m admin_app.create_admin --username operator1

The password is asked for interactively so it never lands in the shell
history or in a script file.
"""
# بدون این اسکریپت هیچ‌کس نمی‌تواند وارد پنل شود (چون جدول کاربران خالی
# است). این «مشکل مرغ و تخم‌مرغ» عمداً با یک ابزار خط فرمان حل شده، نه با
# یک کاربر پیش‌فرض مثل admin/admin که فراموش شود و راه نفوذ باز بگذارد.
from __future__ import annotations

import argparse
import getpass
import sys

from sqlmodel import Session, select

from .auth import hash_password
from .db import engine, init_db
from .models import AdminUser

# حداقل طول رمز؛ جلوی رمزهای بی‌معنی مثل «۱۲۳» را می‌گیرد
MIN_PASSWORD_LENGTH = 8


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ساخت یا به‌روزرسانی حساب اپراتور پنل ادمین",
    )
    parser.add_argument("--username", required=True, help="نام کاربری اپراتور")
    return parser.parse_args(argv)


def prompt_for_password() -> str | None:
    """Ask for the password twice (hidden), return None if they don't match."""
    # getpass یعنی رمز هنگام تایپ روی صفحه نمایش داده نمی‌شود
    password = getpass.getpass("رمز عبور جدید: ")
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"خطا: رمز عبور باید حداقل {MIN_PASSWORD_LENGTH} کاراکتر باشد.")
        return None

    # تکرار رمز، تا اشتباه تایپی باعث قفل‌شدن حساب نشود
    if password != getpass.getpass("تکرار رمز عبور: "):
        print("خطا: دو رمز وارد‌شده یکسان نیستند.")
        return None
    return password


def upsert_admin(session: Session, username: str, password: str) -> str:
    """Create the admin, or reset the password if the username already exists."""
    admin = session.exec(
        select(AdminUser).where(AdminUser.username == username)
    ).first()

    if admin is None:
        # حالت ۱: کاربر جدید
        session.add(AdminUser(username=username, password_hash=hash_password(password)))
        action = "ساخته شد"
    else:
        # حالت ۲: کاربر موجود — رمزش را عوض کن و در صورت غیرفعال بودن، فعالش کن.
        # (همین مسیر برای «رمزم را فراموش کردم» هم استفاده می‌شود.)
        admin.password_hash = hash_password(password)
        admin.is_active = True
        session.add(admin)
        action = "رمز عبورش به‌روزرسانی شد"

    session.commit()
    return action


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    password = prompt_for_password()
    if password is None:
        return 1

    init_db()  # اطمینان از وجود جدول‌ها، اگر برای اولین بار اجرا می‌شود
    with Session(engine) as session:
        action = upsert_admin(session, args.username, password)

    print(f"حساب «{args.username}» {action}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
