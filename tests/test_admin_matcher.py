# تست‌های تطبیق (matcher.py): آیا محله‌ی مشترک با متن محل خاموشی جور درمی‌آید
from admin_app.matcher import match_subscriber
from admin_app.models import Outage, Subscriber

CITY_KWARGS = dict(city="بابل", province="مازندران", date_jalali="پنجشنبه ۱۵ مرداد ۱۴۰۵", date_gregorian="2026-08-06")


def make_outage(location: str, start: str, end: str) -> Outage:
    return Outage(location=location, start_time=start, end_time=end, **CITY_KWARGS)


def test_matches_when_neighborhood_is_a_substring_of_location():
    subscriber = Subscriber(
        full_name="علی رضایی", mobile="09120000000",
        province="مازندران", city="بابل", neighborhood="غدیر",
    )
    outages = [
        make_outage("کاردرکلا/ غدیر 1", "14:00", "16:00"),
        make_outage("بابل جنوب", "10:00", "12:00"),
    ]

    matches = match_subscriber(subscriber, outages)

    assert len(matches) == 1
    assert matches[0].location == "کاردرکلا/ غدیر 1"


def test_no_matches_returns_empty_list():
    subscriber = Subscriber(
        full_name="سارا احمدی", mobile="09121111111",
        province="مازندران", city="بابل", neighborhood="محله‌ای که وجود ندارد",
    )
    outages = [make_outage("کاردرکلا/ غدیر 1", "14:00", "16:00")]

    assert match_subscriber(subscriber, outages) == []


def test_empty_neighborhood_matches_nothing():
    # اگر محله خالی ثبت شده باشد نباید همه‌چیز را match کند
    subscriber = Subscriber(
        full_name="بدون محله", mobile="09122222222",
        province="مازندران", city="بابل", neighborhood="  ",
    )
    outages = [make_outage("کاردرکلا/ غدیر 1", "14:00", "16:00")]

    assert match_subscriber(subscriber, outages) == []
