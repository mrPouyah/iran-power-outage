# تست‌های احراز هویت پنل ادمین:
#   بخش ۱ — هش و بررسی رمز عبور (بدون نیاز به دیتابیس)
#   بخش ۲ — چرخه‌ی کامل نشست (ورود، اعتبارسنجی، انقضا، خروج)
#   بخش ۳ — محافظت واقعی مسیرهای HTTP از طریق TestClient
import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from admin_app import auth
from admin_app.models import AdminSession, AdminUser


# ---------------------------------------------------------------------------
# بخش ۱ — هش رمز عبور
# ---------------------------------------------------------------------------

def test_password_verifies_against_its_own_hash():
    stored = auth.hash_password("رمز-درست-۱۲۳")
    assert auth.verify_password("رمز-درست-۱۲۳", stored) is True


def test_wrong_password_is_rejected():
    stored = auth.hash_password("رمز-درست-۱۲۳")
    assert auth.verify_password("رمز-غلط", stored) is False


def test_same_password_hashes_differently_each_time():
    # به‌خاطر salt تصادفی، دو هش از یک رمز نباید یکسان باشند
    assert auth.hash_password("یک-رمز") != auth.hash_password("یک-رمز")


def test_plaintext_password_is_never_stored():
    stored = auth.hash_password("رمزِ-محرمانه")
    assert "رمزِ-محرمانه" not in stored


def test_malformed_hash_returns_false_instead_of_crashing():
    # هش خراب در دیتابیس نباید کل برنامه را از کار بیندازد
    for broken in ["", "بدون-دلار", "md5$1$1$1$aa$bb", "scrypt$نامعتبر"]:
        assert auth.verify_password("هرچیزی", broken) is False


# ---------------------------------------------------------------------------
# بخش ۲ — چرخه‌ی نشست
# ---------------------------------------------------------------------------

@pytest.fixture
def session(tmp_path):
    # دیتابیس موقت و مستقل برای هر تست
    engine = create_engine(f"sqlite:///{tmp_path / 'auth-test.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def admin(session):
    user = AdminUser(username="operator1", password_hash=auth.hash_password("رمز-معتبر-۱۲۳"))
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def test_authenticate_accepts_correct_credentials(session, admin):
    assert auth.authenticate(session, "operator1", "رمز-معتبر-۱۲۳") is not None


def test_authenticate_rejects_wrong_password(session, admin):
    assert auth.authenticate(session, "operator1", "رمز-اشتباه") is None


def test_authenticate_rejects_unknown_username(session, admin):
    assert auth.authenticate(session, "کاربر-ناموجود", "رمز-معتبر-۱۲۳") is None


def test_authenticate_rejects_deactivated_account(session, admin):
    # غیرفعال کردن حساب باید فوراً جلوی ورود را بگیرد
    admin.is_active = False
    session.add(admin)
    session.commit()
    assert auth.authenticate(session, "operator1", "رمز-معتبر-۱۲۳") is None


def test_destroy_session_removes_the_row(session, admin):
    token = auth.create_session(session, admin)
    auth.destroy_session(session, token)
    assert session.exec(select(AdminSession).where(AdminSession.token == token)).first() is None


def test_expired_session_is_rejected_and_cleaned_up(session, admin):
    # یک نشست دستیِ منقضی‌شده می‌سازیم تا لازم نباشد ۱۲ ساعت صبر کنیم
    expired = AdminSession(
        token="توکن-منقضی",
        admin_id=admin.id,
        expires_at=dt.datetime.now() - dt.timedelta(minutes=1),
    )
    session.add(expired)
    session.commit()

    class FakeRequest:
        cookies = {auth.COOKIE_NAME: "توکن-منقضی"}

    assert auth.resolve_admin(FakeRequest(), session) is None
    # ردیف منقضی باید همان‌جا حذف شده باشد تا جدول انباشته نشود
    assert session.exec(select(AdminSession).where(AdminSession.token == "توکن-منقضی")).first() is None


# ---------------------------------------------------------------------------
# بخش ۳ — محافظت واقعی مسیرهای HTTP
# ---------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient wired to a throwaway database, with one known admin."""
    # دیتابیس اپ را به یک فایل موقت هدایت می‌کنیم تا تست‌ها به داده‌ی
    # واقعی مشترکین دست نزنند
    engine = create_engine(f"sqlite:///{tmp_path / 'app-test.db'}")
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

    # follow_redirects=False تا بتوانیم خودِ ریدایرکت را بررسی کنیم
    yield TestClient(main_module.app, follow_redirects=False)
    main_module.app.dependency_overrides.clear()


def test_subscriber_api_is_closed_to_anonymous_callers(client):
    # این مهم‌ترین تست این فایل است: قبل از احراز هویت، این مسیر
    # نام و شماره موبایل تمام مشترکین را بدون هیچ محدودیتی برمی‌گرداند
    response = client.get("/api/subscribers")
    assert response.status_code == 401


def test_creating_a_subscriber_requires_login(client):
    response = client.post("/api/subscribers", json={
        "full_name": "علی رضایی", "mobile": "09120000000",
        "province": "مازندران", "city": "بابل", "neighborhood": "غدیر",
    })
    assert response.status_code == 401


def test_deleting_a_subscriber_requires_login(client):
    # حذف داده‌ی شخصی هم مثل خواندنش باید پشت احراز هویت باشد
    assert client.delete("/api/subscribers/1").status_code == 401


def test_home_page_redirects_anonymous_visitor_to_login(client):
    response = client.get("/")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_page_itself_is_reachable_while_signed_out(client):
    response = client.get("/login")
    assert response.status_code == 200


def test_wrong_password_does_not_issue_a_cookie(client):
    response = client.post("/login", data={"username": "operator1", "password": "غلط"})
    assert response.status_code == 303
    assert "error=1" in response.headers["location"]
    assert auth.COOKIE_NAME not in response.cookies


def test_signed_in_admin_can_create_then_delete_a_subscriber(client):
    client.post("/login", data={"username": "operator1", "password": "رمز-معتبر-۱۲۳"})

    created = client.post("/api/subscribers", json={
        "full_name": "علی رضایی", "mobile": "09120000001",
        "province": "مازندران", "city": "بابل", "neighborhood": "غدیر",
    })
    assert created.status_code == 200
    subscriber_id = created.json()["id"]

    deleted = client.delete(f"/api/subscribers/{subscriber_id}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    # بعد از حذف، فهرست باید خالی باشد
    assert client.get("/api/subscribers").json() == []


def test_deleting_a_missing_subscriber_returns_404(client):
    client.post("/login", data={"username": "operator1", "password": "رمز-معتبر-۱۲۳"})
    assert client.delete("/api/subscribers/99999").status_code == 404


def test_deleting_a_subscriber_does_not_remove_the_admin_account(client):
    # حذف مشترک نباید هیچ اثری روی حساب‌های ورود داشته باشد
    client.post("/login", data={"username": "operator1", "password": "رمز-معتبر-۱۲۳"})
    created = client.post("/api/subscribers", json={
        "full_name": "علی رضایی", "mobile": "09120000001",
        "province": "مازندران", "city": "بابل", "neighborhood": "غدیر",
    })
    client.delete(f"/api/subscribers/{created.json()['id']}")

    # اگر حساب ادمین آسیب دیده بود، این درخواست ۴۰۱ می‌گرفت
    assert client.get("/api/subscribers").status_code == 200


def test_successful_login_grants_access_and_logout_revokes_it(client):
    # ۱) ورود موفق باید کوکی نشست بدهد
    login = client.post("/login", data={"username": "operator1", "password": "رمز-معتبر-۱۲۳"})
    assert login.status_code == 303
    assert login.headers["location"] == "/"
    assert auth.COOKIE_NAME in login.cookies

    # ۲) حالا همان مسیری که قبلاً ۴۰۱ می‌داد باید باز باشد
    assert client.get("/api/subscribers").status_code == 200

    # ۳) بعد از خروج، دسترسی باید دوباره بسته شود
    assert client.post("/logout").status_code == 303
    assert client.get("/api/subscribers").status_code == 401
