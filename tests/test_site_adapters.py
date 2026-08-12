# تست‌های آداپتور اختصاصی e-saricity، شامل فیلتر کردن بر اساس برچسب نسبیِ روز
import datetime as dt

from bs4 import BeautifulSoup

from outage_scraper.site_adapters import e_saricity

TODAY = dt.date.today()
YESTERDAY = TODAY - dt.timedelta(days=1)
THREE_DAYS_AGO = TODAY - dt.timedelta(days=3)

CARD_HTML = f"""
<html><body>
<div class="addresses-card">
    <div class="card" data-id="2ae0e6b5-918a-11f1-a08d-00163e4051d0"
         data-address="کاردرکلا/ غدیر 1" data-time="امروز ۱۴:۵۴ - ۱۶:۵۴">
        <p class="address-text">کاردرکلا/ غدیر ۱</p>
    </div>
    <div class="card" data-id="afa2e787-85c0-11f1-9da2-00163e4051d0"
         data-address="بابل جنوب" data-time="امروز ۱۶:۰۰ - ۱۸:۰۰">
        <p class="address-text">بابل جنوب</p>
    </div>
    <div class="card" data-id="yesterday-id"
         data-address="دیروزی" data-time="دیروز ۰۹:۰۰ - ۱۱:۰۰">
        <p class="address-text">دیروزی</p>
    </div>
    <div class="card" data-id="3-days-ago-id"
         data-address="سه روز قبل" data-time="3 روز قبل ۰۹:۰۰ - ۱۱:۰۰">
        <p class="address-text">سه روز قبل</p>
    </div>
    <div class="card" data-id="no-time-id">
        <p class="address-text">بدون زمان</p>
    </div>
</div>
</body></html>
"""


def test_extracts_only_cards_matching_the_target_date():
    soup = BeautifulSoup(CARD_HTML, "html.parser")
    records = e_saricity.extract(soup, TODAY)

    assert len(records) == 2

    first = records[0]
    assert first["location"] == "کاردرکلا/ غدیر 1"
    assert first["start_time"] == "14:54"
    assert first["end_time"] == "16:54"
    assert first["neighborhood_code"] is None

    second = records[1]
    assert second["location"] == "بابل جنوب"
    assert second["start_time"] == "16:00"
    assert second["end_time"] == "18:00"


def test_extracts_yesterdays_cards_when_target_date_is_yesterday():
    soup = BeautifulSoup(CARD_HTML, "html.parser")
    records = e_saricity.extract(soup, YESTERDAY)

    assert len(records) == 1
    assert records[0]["location"] == "دیروزی"


def test_extracts_n_days_ago_cards():
    soup = BeautifulSoup(CARD_HTML, "html.parser")
    records = e_saricity.extract(soup, THREE_DAYS_AGO)

    assert len(records) == 1
    assert records[0]["location"] == "سه روز قبل"


def test_skips_cards_without_a_time():
    soup = BeautifulSoup('<div class="card" data-address="x"></div>', "html.parser")
    assert e_saricity.extract(soup, TODAY) == []


def test_relative_day_label():
    assert e_saricity.relative_day_label(0) == "امروز"
    assert e_saricity.relative_day_label(-1) == "دیروز"
    assert e_saricity.relative_day_label(-3) == "3 روز قبل"
    assert e_saricity.relative_day_label(2) == "2 روز دیگر"
