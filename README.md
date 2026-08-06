# جستجوگر برنامه قطعی برق ایران (Iran Power Outage Scraper)

A Python CLI that looks up scheduled power-outage ("خاموشی") announcements
for an Iranian city on a given date, and reports the **neighborhood/street
range**, **outage time window**, and **rotation code** (all in Farsi), for
example for بابل (Babol), مازندران (Mazandaran).

## How it works

For a given date, the tool:

1. **Tries known direct sources first** — dedicated per-city outage-table
   pages (currently `app.e-saricity.ir` for Babol; see `outage_scraper/sources.py`
   to add more).
2. **Falls back to a free web search** (DuckDuckGo's HTML endpoint, no API
   key needed) with several Farsi query phrasings combining the city name
   and the Jalali (Iranian calendar) date, since outage schedules are almost
   always published in Jalali dates in the news (e.g. "۱۴ مرداد ۱۴۰۵").
3. **Fetches and parses** each candidate page with two strategies:
   - a generic **table parser** that recognizes Farsi header keywords
     (منطقه/محله/ناحیه, از ساعت, تا ساعت, کد), and
   - a **text/regex fallback** for news roundups that describe the schedule
     in prose instead of a table (matches "HH:MM الی/تا HH:MM" time ranges
     near the city name, plus an optional "کد N").
4. Only pages that actually mention the requested city are considered, and
   duplicate rows across sources are removed.

Input dates are given in the Gregorian calendar (what you'd normally type)
and converted to the matching Jalali date internally.

## Install

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Today's schedule for Babol, Mazandaran (the defaults)
python -m outage_scraper

# A specific Gregorian date
python -m outage_scraper --date 2026-08-06

# A specific Jalali date instead (year < 1700 is treated as Jalali)
python -m outage_scraper --date 1405-05-15

# A different city/province
python -m outage_scraper --city ساری --province مازندران

# Machine-readable output
python -m outage_scraper --format json --outfile babol-2026-08-06.json
python -m outage_scraper --format csv --outfile babol-2026-08-06.csv

# Verbose logging (shows every source/query it tries)
python -m outage_scraper -v
```

Or equivalently `python run.py ...`.

### Sample table output

```
برنامه قطعی برق بابل، مازندران — پنجشنبه ۱۵ مرداد ۱۴۰۵

کد    بازه زمانی      محدوده / محله                                منبع
------------------------------------------------------------------------------
3     10:00-12:30     چهارراه شهربانی، محله اسلام، سادات محله      https://...
5     14:00-16:00     گرجی‌آباد، خیابان طالقانی                    https://...
```

## Exit codes

- `0` — records found and printed/written
- `1` — bad input (e.g. unparseable `--date`)
- `2` — ran fine but found no matching schedule for that city/date

## Limitations & notes

- **Not yet live-tested**: this was built and unit-tested inside a sandboxed
  environment with no general internet access, so the real sources have not
  been fetched and confirmed end-to-end. Run it with `-v` on a normal
  internet connection first; if a source returns nothing, check whether it's
  bot/geo-blocking (common for Iranian sites) or whether `parser.py`'s
  header keywords just don't match that page's actual markup, and adjust
  `outage_scraper/sources.py` / `parser.py` accordingly.
- **DuckDuckGo HTML scraping** has no API key requirement but can change
  its markup or rate-limit; `search.py` isolates this so it's easy to swap
  in a paid search API (Bing/SerpAPI/Google CSE) by replacing `web_search()`.
- **Accuracy**: this tool aggregates what's *publicly published*, which can
  change or be published late. For anything safety-critical, cross-check
  with the official portal (`bargheman.com`, requires your 13-digit bill
  ID) or by calling **121**.
- **Text-based extraction** requires the city name to appear in the same
  paragraph/list item as the time range; roundup articles that only name
  the city once at the top of a multi-city list may need the table-based
  path or an added direct source instead.

## Project layout

```
iran-power-outage/
├── outage_scraper/
│   ├── cli.py       # argument parsing + orchestration + output
│   ├── dates.py      # Gregorian <-> Jalali date handling
│   ├── models.py     # OutageRecord dataclass
│   ├── parser.py     # HTML fetch + table/text extraction
│   ├── search.py     # DuckDuckGo-based free web search
│   └── sources.py    # known direct per-city source URLs
├── tests/             # pytest unit tests (parser + output, offline)
├── requirements.txt
└── run.py             # convenience entry point
```

## Tests

```bash
pip install pytest
pytest tests/
```

Tests run entirely offline against synthetic HTML fixtures (no network
required) since they need to keep passing regardless of live-site
availability.
