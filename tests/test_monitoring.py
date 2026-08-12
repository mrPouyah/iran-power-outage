# تست‌های تب مانیتورینگ:
#   بخش ۱ — کلید فعال/غیرفعال سامانه
#   بخش ۲ — پاک‌سازی روزانه (و تضمین دست‌نخوردن داده‌ی مشترکین)
#   بخش ۳ — وضعیت سلامت مراحل
#   بخش ۴ — محافظت مسیرهای HTTP و رفتار «تست چیزی ذخیره نمی‌کند»
import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from admin_app import auth, monitoring, system_state
from admin_app.models import AdminUser, Outage, Subscriber, SyncRun
from admin_app.sync import purge_old_outages


@pytest.fixture
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'monitoring-test.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def make_outage(location: str, date: str, city: str = "بابل") -> Outage:
    return Outage(
        city=city, province="مازندران",
        date_jalali="…", date_gregorian=date,
        location=location, start_time="10:00", end_time="12:00",
    )


# ---------------------------------------------------------------------------
# بخش ۱ — کلید فعال/غیرفعال
# ---------------------------------------------------------------------------

def test_system_starts_disabled(session):
    # پیش‌فرض باید خاموش باشد تا سامانه بدون تأیید ادمین کاری نکند
    assert system_state.is_enabled(session) is False


def test_admin_can_switch_the_system_on_and_off(session):
    system_state.set_enabled(session, True, changed_by="pouyah")
    assert system_state.is_enabled(session) is True

    system_state.set_enabled(session, False, changed_by="pouyah")
    assert system_state.is_enabled(session) is False


def test_switching_records_who_did_it(session):
    setting = system_state.set_enabled(session, True, changed_by="pouyah")
    assert setting.updated_by == "pouyah"


# ---------------------------------------------------------------------------
# بخش ۲ — پاک‌سازی روزانه‌ی داده‌ی خاموشی
# ---------------------------------------------------------------------------

def test_purge_removes_only_days_before_the_target(session):
    session.add(make_outage("محله قدیمی", "2026-08-09"))
    session.add(make_outage("محله دیروزی", "2026-08-10"))
    session.add(make_outage("محله امروزی", "2026-08-11"))
    session.commit()

    removed = purge_old_outages(session, "بابل", "2026-08-11")

    assert removed == 2
    remaining = session.exec(select(Outage)).all()
    assert [o.date_gregorian for o in remaining] == ["2026-08-11"]


def test_purge_never_touches_subscribers_or_admins(session):
    # این مهم‌ترین تست ایمنی است: پاک‌سازی روزانه باید فقط جدول Outage را
    # لمس کند و هرگز اطلاعات مشترکین یا حساب ادمین را حذف نکند
    session.add(Subscriber(
        full_name="علی رضایی", mobile="09120000000",
        province="مازندران", city="بابل", neighborhood="غدیر",
    ))
    session.add(AdminUser(username="pouyah", password_hash=auth.hash_password("رمز-معتبر-۱۲۳")))
    session.add(make_outage("محله قدیمی", "2026-08-01"))
    session.commit()

    purge_old_outages(session, "بابل", "2026-08-11")

    assert len(session.exec(select(Subscriber)).all()) == 1
    assert len(session.exec(select(AdminUser)).all()) == 1
    assert len(session.exec(select(Outage)).all()) == 0


def test_purge_leaves_other_cities_alone(session):
    session.add(make_outage("محله بابل", "2026-08-01", city="بابل"))
    session.add(make_outage("محله ساری", "2026-08-01", city="ساری"))
    session.commit()

    purge_old_outages(session, "بابل", "2026-08-11")

    remaining = session.exec(select(Outage)).all()
    assert [o.city for o in remaining] == ["ساری"]


# ---------------------------------------------------------------------------
# بخش ۳ — وضعیت سلامت مراحل
# ---------------------------------------------------------------------------

def test_sms_stage_is_honestly_reported_as_not_implemented(session):
    status = monitoring.collect_status(session, "بابل", "مازندران")
    sms = next(s for s in status.stages if s.key == "notification")
    # عمداً «سالم» گزارش نمی‌شود، چون واقعاً ساخته نشده است
    assert sms.status == monitoring.STATUS_NOT_IMPLEMENTED


def test_collection_stage_warns_when_nothing_has_ever_run(session):
    status = monitoring.collect_status(session, "بابل", "مازندران")
    collection = next(s for s in status.stages if s.key == "collection")
    assert collection.status == monitoring.STATUS_WARNING


def test_collection_stage_reports_error_after_a_failed_run(session):
    system_state.record_run(
        session, city="بابل", is_dry_run=False,
        error_message="ConnectionError: منبع در دسترس نیست",
    )
    status = monitoring.collect_status(session, "بابل", "مازندران")
    collection = next(s for s in status.stages if s.key == "collection")
    assert collection.status == monitoring.STATUS_ERROR


def test_a_manual_test_run_does_not_make_the_system_look_healthy(session):
    # زدن دکمه‌ی تست نباید سامانه را «به‌روز و سالم» نشان دهد، چون
    # اجرای واقعی هنوز انجام نشده است
    system_state.record_run(session, city="بابل", is_dry_run=True, fetched_count=100)

    status = monitoring.collect_status(session, "بابل", "مازندران")
    collection = next(s for s in status.stages if s.key == "collection")
    assert collection.status == monitoring.STATUS_WARNING


def test_collection_stage_warns_when_the_last_run_is_stale(session):
    old = dt.datetime.now() - dt.timedelta(hours=30)
    system_state.record_run(session, city="بابل", is_dry_run=False, started_at=old)

    status = monitoring.collect_status(session, "بابل", "مازندران")
    collection = next(s for s in status.stages if s.key == "collection")
    assert collection.status == monitoring.STATUS_WARNING


# ---------------------------------------------------------------------------
# بخش ۴ — مسیرهای HTTP
# ---------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'monitoring-app.db'}")
    SQLModel.metadata.create_all(engine)

    from admin_app import db as db_module
    from admin_app import main as main_module

    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(main_module, "engine", engine)

    def _test_session():
        with Session(engine) as s:
            yield s

    main_module.app.dependency_overrides[db_module.get_session] = _test_session

    with Session(engine) as s:
        s.add(AdminUser(username="operator1", password_hash=auth.hash_password("رمز-معتبر-۱۲۳")))
        s.commit()

    yield TestClient(main_module.app, follow_redirects=False)
    main_module.app.dependency_overrides.clear()


@pytest.fixture
def signed_in(client):
    client.post("/login", data={"username": "operator1", "password": "رمز-معتبر-۱۲۳"})
    return client


def test_monitoring_page_requires_login(client):
    assert client.get("/monitoring").status_code == 303


def test_monitoring_status_api_requires_login(client):
    assert client.get("/api/monitoring/status").status_code == 401


def test_manual_test_endpoint_requires_login(client):
    assert client.post("/api/monitoring/test/data").status_code == 401


def test_power_switch_requires_login(client):
    assert client.post("/api/monitoring/enabled", json={"enabled": True}).status_code == 401


def test_status_lists_all_four_stages(signed_in):
    data = signed_in.get("/api/monitoring/status").json()
    keys = [s["key"] for s in data["stages"]]
    assert keys == ["collection", "storage", "matching", "notification"]


def test_power_switch_toggles_and_is_reflected_in_status(signed_in):
    assert signed_in.get("/api/monitoring/status").json()["is_enabled"] is False

    signed_in.post("/api/monitoring/enabled", json={"enabled": True})
    assert signed_in.get("/api/monitoring/status").json()["is_enabled"] is True


def test_real_sync_is_refused_while_the_system_is_disabled(signed_in):
    # محافظ اصلی: تا وقتی ادمین سامانه را فعال نکرده، اجرای واقعی
    # (که داده ذخیره و پاک می‌کند) نباید امکان‌پذیر باشد
    response = signed_in.post("/api/monitoring/run-sync")
    assert response.status_code == 409


def _fake_data_test(monkeypatch, outages: list[dict] | None = None):
    """Replace the live fetch with a fixed result, so tests need no network."""
    from admin_app import main as main_module
    from admin_app.monitoring import DataTestResult

    def fake(city, province, date_text=None):
        return DataTestResult(
            city=city, province=province,
            date_jalali="…", date_gregorian="2026-08-11",
            outages=outages if outages is not None else [],
        )

    monkeypatch.setattr(main_module, "run_data_test", fake)


def test_manual_test_works_even_while_the_system_is_disabled(signed_in, monkeypatch):
    # تست دستی باید مستقل از کلید فعال/غیرفعال کار کند، تا ادمین بتواند
    # قبل از روشن کردن سامانه از در دسترس بودن منبع مطمئن شود
    _fake_data_test(monkeypatch, [
        {"location": "غدیر ۱۹", "start_time": "10:00", "end_time": "12:00",
         "neighborhood_code": None, "source_url": ""},
    ])

    response = signed_in.post("/api/monitoring/test/data")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["outages"][0]["location"] == "غدیر ۱۹"


def test_data_test_returns_outages_only_without_subscriber_matching(signed_in, monkeypatch):
    # تست دریافت داده عمداً تطبیق با مشترکین را انجام نمی‌دهد؛ تطبیق فقط
    # هنگام اجرای واقعی و به‌صورت خودکار رخ می‌دهد
    _fake_data_test(monkeypatch, [
        {"location": "محله الف", "start_time": "10:00", "end_time": "12:00",
         "neighborhood_code": None, "source_url": ""},
    ])

    body = signed_in.post("/api/monitoring/test/data").json()

    assert "outages" in body
    assert "matches" not in body
    assert "active_subscribers" not in body


def test_data_test_writes_nothing_to_the_database(signed_in, monkeypatch):
    _fake_data_test(monkeypatch, [
        {"location": "محله الف", "start_time": "10:00", "end_time": "12:00",
         "neighborhood_code": None, "source_url": ""},
    ])

    before = signed_in.get("/api/monitoring/status").json()["stages"]
    stored_before = next(s for s in before if s["key"] == "storage")["details"]["total"]

    signed_in.post("/api/monitoring/test/data")

    after = signed_in.get("/api/monitoring/status").json()["stages"]
    stored_after = next(s for s in after if s["key"] == "storage")["details"]["total"]
    assert stored_before == stored_after


def test_manual_test_is_logged_as_a_dry_run(signed_in, monkeypatch):
    _fake_data_test(monkeypatch)
    signed_in.post("/api/monitoring/test/data")

    history = signed_in.get("/api/monitoring/status").json()["history"]
    assert history[0]["kind"] == "تست"


# ---------------------------------------------------------------------------
# بخش ۵ — تست همسان‌سازی مشترک با ساعت قطعی
# ---------------------------------------------------------------------------

def _fake_source(monkeypatch, locations: list[str]):
    """Replace the live source with fixed outage rows, so tests need no network."""
    from outage_scraper.models import OutageRecord

    from admin_app import monitoring as monitoring_module

    def fake_fetch(city, province, date):
        return [
            OutageRecord(
                city=city, province=province,
                date_jalali="…", date_gregorian=str(date.gregorian),
                location=loc, start_time="10:00", end_time="12:00",
            )
            for loc in locations
        ]

    monkeypatch.setattr(monitoring_module, "fetch_records", fake_fetch)


def _add_subscriber(session, name: str, neighborhood: str, mobile: str):
    session.add(Subscriber(
        full_name=name, mobile=mobile,
        province="مازندران", city="بابل", neighborhood=neighborhood,
    ))
    session.commit()


def test_matching_test_reports_a_subscriber_who_has_an_outage(session, monkeypatch):
    _fake_source(monkeypatch, ["کاردرکلا/ غدیر ۱۹", "محله دیگر"])
    _add_subscriber(session, "علی رضایی", "غدیر", "09120000001")

    result = monitoring.run_matching_test(session, "بابل", "مازندران")

    assert len(result.matched) == 1
    assert result.matched[0]["full_name"] == "علی رضایی"
    assert result.matched[0]["outages"][0]["start_time"] == "10:00"
    assert result.unmatched == []


def test_matching_test_also_lists_subscribers_without_an_outage(session, monkeypatch):
    # این فهرست برای عیب‌یابی حیاتی است: بدون آن، مشترکی که اشتباه ثبت
    # شده به‌کلی نامرئی می‌ماند و کسی نمی‌فهمد چرا پیامک نگرفته
    _fake_source(monkeypatch, ["محله الف"])
    _add_subscriber(session, "سارا احمدی", "محله‌ای که وجود ندارد", "09120000002")

    result = monitoring.run_matching_test(session, "بابل", "مازندران")

    assert result.matched == []
    assert len(result.unmatched) == 1
    assert result.unmatched[0]["neighborhood"] == "محله‌ای که وجود ندارد"


def test_matching_test_counts_every_active_subscriber(session, monkeypatch):
    _fake_source(monkeypatch, ["محله الف"])
    _add_subscriber(session, "دارای قطعی", "الف", "09120000003")
    _add_subscriber(session, "بدون قطعی", "ب", "09120000004")

    result = monitoring.run_matching_test(session, "بابل", "مازندران")

    assert result.active_subscribers == 2
    assert len(result.matched) == 1
    assert len(result.unmatched) == 1


def test_matching_test_writes_nothing_to_the_database(session, monkeypatch):
    _fake_source(monkeypatch, ["کاردرکلا/ غدیر ۱۹"])
    _add_subscriber(session, "علی رضایی", "غدیر", "09120000001")

    monitoring.run_matching_test(session, "بابل", "مازندران")

    # هیچ خاموشی‌ای نباید ذخیره شده باشد
    assert session.exec(select(Outage)).all() == []
    # و مشترک هم باید دست‌نخورده مانده باشد
    assert len(session.exec(select(Subscriber)).all()) == 1


def test_matching_test_endpoint_requires_login(client):
    assert client.post("/api/monitoring/test/matching").status_code == 401


def test_matching_test_endpoint_returns_both_groups(signed_in, monkeypatch):
    from admin_app import main as main_module
    from admin_app.monitoring import MatchingTestResult

    monkeypatch.setattr(
        main_module, "run_matching_test",
        lambda s, c, p, d=None: MatchingTestResult(
            city=c, province=p, date_jalali="…", date_gregorian="2026-08-11",
            total_outages=5,
            matched=[{"full_name": "الف", "mobile": "0912", "neighborhood": "غدیر", "outages": []}],
            unmatched=[{"full_name": "ب", "mobile": "0913", "neighborhood": "ناموجود"}],
        ),
    )

    body = signed_in.post("/api/monitoring/test/matching").json()

    assert body["matched_count"] == 1
    assert body["active_subscribers"] == 2
    assert len(body["unmatched"]) == 1
