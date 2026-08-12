# تست‌های پایگاه‌داده‌ی مشترکین: ذخیره، خواندن، و محدودیت شماره‌ی تکراری
import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from admin_app.models import Subscriber


@pytest.fixture
def session(tmp_path):
    # یک دیتابیس SQLite موقت و جدا برای هر تست، تا تست‌ها روی هم اثر نگذارند
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_create_and_read_subscriber(session):
    subscriber = Subscriber(
        full_name="علی رضایی", mobile="09120000000",
        province="مازندران", city="بابل", neighborhood="غدیر ۱",
    )
    session.add(subscriber)
    session.commit()

    found = session.exec(select(Subscriber).where(Subscriber.mobile == "09120000000")).first()
    assert found is not None
    assert found.neighborhood == "غدیر ۱"
    assert found.is_active is True


def test_deleting_a_subscriber_removes_only_that_row(session):
    session.add(Subscriber(
        full_name="علی رضایی", mobile="09120000001",
        province="مازندران", city="بابل", neighborhood="غدیر",
    ))
    session.add(Subscriber(
        full_name="سارا احمدی", mobile="09120000002",
        province="مازندران", city="بابل", neighborhood="بابل جنوب",
    ))
    session.commit()

    target = session.exec(select(Subscriber).where(Subscriber.mobile == "09120000001")).first()
    session.delete(target)
    session.commit()

    remaining = session.exec(select(Subscriber)).all()
    assert len(remaining) == 1
    assert remaining[0].mobile == "09120000002"


def test_duplicate_mobile_is_rejected_by_the_database(session):
    session.add(Subscriber(
        full_name="علی رضایی", mobile="09120000000",
        province="مازندران", city="بابل", neighborhood="غدیر ۱",
    ))
    session.commit()

    session.add(Subscriber(
        full_name="یک نفر دیگر", mobile="09120000000",
        province="مازندران", city="بابل", neighborhood="محله‌ی دیگر",
    ))
    with pytest.raises(IntegrityError):
        session.commit()
