"""SQLite engine/session setup, shared by main.py (web app) and sync.py (CLI)."""
# این فایل مسئول ساخت اتصال به دیتابیس است: یک فایل SQLite در data/app.db
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from sqlmodel import Session, SQLModel, create_engine

# فایل دیتابیس در ریشه‌ی پروژه، داخل پوشه‌ی data/ (اگر نبود ساخته می‌شود)
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# check_same_thread=False چون هم FastAPI (چند ریکوئست) و هم اسکریپت sync
# ممکن است در ترد متفاوتی از همین engine استفاده کنند
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


def init_db() -> None:
    # اگر جدول‌ها وجود نداشته باشند، می‌سازد (idempotent - اجرای دوباره بی‌خطر است)
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    # برای استفاده هم به‌عنوان FastAPI dependency و هم با `with` مستقیم
    with Session(engine) as session:
        yield session
