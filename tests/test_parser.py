from outage_scraper.parser import parse_outage_page

COMMON_KWARGS = dict(
    city="بابل",
    province="مازندران",
    date_jalali="سه‌شنبه ۱۴ مرداد ۱۴۰۵",
    date_gregorian="2026-08-05",
    url="https://example.test/babol-outage",
    title="جدول قطعی برق بابل",
)

TABLE_HTML = """
<html><body>
<h1>جدول قطعی برق بابل</h1>
<table>
<tr><th>کد</th><th>محله / منطقه</th><th>از ساعت</th><th>تا ساعت</th></tr>
<tr><td>۳</td><td>چهارراه شهربانی، محله اسلام، سادات محله</td><td>۱۰:۰۰</td><td>۱۲:۳۰</td></tr>
<tr><td>۵</td><td>گرجی‌آباد، خیابان طالقانی</td><td>۱۴:۰۰</td><td>۱۶:۰۰</td></tr>
</table>
</body></html>
"""

TEXT_HTML = """
<html><body>
<p>برنامه خاموشی بابل امروز: محله اسلام و سادات محله از ساعت ۱۰:۰۰ الی ۱۲:۳۰ کد ۳ دچار قطعی برق خواهند شد.</p>
<li>خاموشی بابل، منطقه گرجی‌آباد از ۱۴ تا ۱۶:۰۰</li>
</body></html>
"""


def test_parses_table_based_schedule():
    records = parse_outage_page(TABLE_HTML, **COMMON_KWARGS)

    assert len(records) == 2

    first = records[0]
    assert first.neighborhood_code == "3"
    assert first.start_time == "10:00"
    assert first.end_time == "12:30"
    assert "سادات محله" in first.location

    second = records[1]
    assert second.neighborhood_code == "5"
    assert second.start_time == "14:00"
    assert second.end_time == "16:00"
    assert "گرجی‌آباد" in second.location


def test_parses_text_based_schedule_when_no_table():
    records = parse_outage_page(TEXT_HTML, **COMMON_KWARGS)

    assert len(records) == 2
    assert records[0].neighborhood_code == "3"
    assert records[0].start_time == "10:00"
    assert records[0].end_time == "12:30"

    assert records[1].start_time == "14:00"
    assert records[1].end_time == "16:00"


def test_ignores_pages_that_never_mention_the_city():
    html = "<html><body><table><tr><th>محله</th><th>از ساعت</th><th>تا ساعت</th></tr><tr><td>x</td><td>۱۰:۰۰</td><td>۱۲:۰۰</td></tr></table></body></html>"
    kwargs = dict(COMMON_KWARGS, city="ساری")
    assert parse_outage_page(html, **kwargs) == []
