import csv
import json

from outage_scraper.cli import write_output
from outage_scraper.models import OutageRecord

RECORD = OutageRecord(
    city="بابل",
    province="مازندران",
    date_jalali="سه‌شنبه ۱۴ مرداد ۱۴۰۵",
    date_gregorian="2026-08-05",
    location="محله اسلام، سادات محله",
    start_time="10:00",
    end_time="12:30",
    neighborhood_code="3",
    source_url="https://example.test/babol-outage",
    source_title="جدول قطعی برق بابل",
)


def test_json_output_roundtrips(tmp_path):
    outfile = tmp_path / "out.json"
    write_output([RECORD], "json", str(outfile))
    data = json.loads(outfile.read_text(encoding="utf-8"))
    assert data[0]["neighborhood_code"] == "3"
    assert data[0]["location"] == "محله اسلام، سادات محله"


def test_csv_output_roundtrips(tmp_path):
    outfile = tmp_path / "out.csv"
    write_output([RECORD], "csv", str(outfile))
    with outfile.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["neighborhood_code"] == "3"
    assert rows[0]["start_time"] == "10:00"


def test_table_output_does_not_crash(capsys):
    write_output([RECORD], "table", None)
    captured = capsys.readouterr()
    assert "بابل" in captured.out
