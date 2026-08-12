# پروژه: سامانه هشدار پیامکی خاموشی برق

> نسخه ۱ — پیش‌نویس اولیه (قبل از بازبینی فنی)

---

## ۱. خلاصه پروژه

یک سرویس خودکار که پیش از شروع خاموشی‌های برنامه‌ریزی‌شده، به کاربر پیامک هشدار می‌فرستد.

اطلاعات کاربران (موقعیت مکانی و شماره موبایل) توسط یک اپراتور انسانی از طریق یک رابط تحت وب وارد سامانه می‌شود. سامانه به‌صورت زمان‌بندی‌شده جدول خاموشی‌ها را از منابع رسمی برداشت می‌کند، آن را با پایگاه داده کاربران تطبیق می‌دهد و برای هر کاربر پیامک اختصاصی ارسال می‌کند.

**مدل درآمدی:** اشتراک ماهانه / سالانه.

---

## ۲. مسئله

- خاموشی‌های برنامه‌ریزی‌شده در بسیاری از مناطق روزانه و در بازه‌های حدوداً دو ساعته اعمال می‌شود.
- اطلاع‌رسانی موجود نیازمند این است که کاربر خودش اپلیکیشن یا سایت را باز کند و جدول را چک کند.
- بسیاری از کاربران این کار را فراموش می‌کنند یا به اینترنت دسترسی پایدار ندارند.

**راه‌حل:** اطلاع‌رسانی «فعال» (Push) از طریق پیامک — بدون نیاز به اینترنت و بدون نیاز به اقدام کاربر.

---

## ۳. معماری کلی

```
┌──────────────────────────┐        ┌──────────────────────────┐
│  منابع رسمی خاموشی        │        │  رابط وب (Admin UI)      │
│  (سایت / فید / جدول)      │        │  اپراتور انسانی           │
└────────────┬─────────────┘        └────────────┬─────────────┘
             │                                    │
             ▼                                    ▼
┌──────────────────────────┐        ┌──────────────────────────┐
│  Scraper + Parser         │        │  پایگاه داده کاربران      │
│  استخراج منطقه و ساعت     │        │  موقعیت + شماره موبایل    │
└────────────┬─────────────┘        └────────────┬─────────────┘
             │                                    │
             └────────────┬───────────────────────┘
                          ▼
              ┌──────────────────────────┐
              │  موتور تطبیق (Matcher)    │
              │  تطبیق خاموشی با کاربر    │
              └────────────┬─────────────┘
                           ▼
              ┌──────────────────────────┐
              │  درگاه پیامک (SMS API)    │
              └────────────┬─────────────┘
                           ▼
              ┌──────────────────────────┐
              │  موبایل مشترک             │
              └──────────────────────────┘
```

---

## ۴. اجزای سیستم

| جزء | وظیفه | فناوری پیشنهادی |
|---|---|---|
| Admin UI | ثبت و ویرایش اطلاعات کاربران توسط اپراتور | HTML + Tailwind |
| Backend API | منطق برنامه و اتصال اجزا | Python + FastAPI |
| Scraper | برداشت جدول خاموشی | `requests` + `BeautifulSoup` |
| Database | نگهداری کاربران و رویدادهای خاموشی | PostgreSQL (یا SQLite در MVP) |
| Scheduler | اجرای دوره‌ای برداشت و ارسال | APScheduler |
| SMS Gateway | ارسال پیامک | پنل پیامکی ایرانی (کاوه‌نگار / SMS.ir) |

---

## ۵. مدل داده

```sql
CREATE TABLE subscribers (
    id            SERIAL PRIMARY KEY,
    full_name     TEXT NOT NULL,
    mobile        TEXT NOT NULL UNIQUE,
    province      TEXT NOT NULL,
    city          TEXT NOT NULL,
    region        TEXT NOT NULL,      -- منطقه / محله
    is_active     BOOLEAN DEFAULT TRUE,
    created_at    TIMESTAMP DEFAULT NOW()
);

CREATE TABLE outages (
    id            SERIAL PRIMARY KEY,
    province      TEXT NOT NULL,
    city          TEXT NOT NULL,
    region        TEXT NOT NULL,
    start_at      TIMESTAMP NOT NULL,
    end_at        TIMESTAMP NOT NULL,
    source_url    TEXT,
    fetched_at    TIMESTAMP DEFAULT NOW()
);

CREATE TABLE messages (
    id            SERIAL PRIMARY KEY,
    subscriber_id INT REFERENCES subscribers(id),
    outage_id     INT REFERENCES outages(id),
    body          TEXT,
    status        TEXT,               -- sent / failed
    sent_at       TIMESTAMP DEFAULT NOW()
);
```

---

## ۶. نمونه کد — رابط وب (ثبت کاربر توسط اپراتور)

```html
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
  <meta charset="UTF-8" />
  <title>ثبت مشترک جدید</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-50 p-8 font-sans">

  <div class="max-w-lg mx-auto bg-white rounded-xl p-6 shadow">
    <h1 class="text-xl mb-6">ثبت مشترک جدید</h1>

    <form id="form" class="space-y-4">
      <div>
        <label class="block mb-1 text-sm">نام و نام خانوادگی</label>
        <input name="full_name" required
               class="w-full border rounded-lg p-2" />
      </div>

      <div>
        <label class="block mb-1 text-sm">شماره موبایل</label>
        <input name="mobile" required placeholder="09123456789"
               class="w-full border rounded-lg p-2" />
      </div>

      <div class="grid grid-cols-3 gap-3">
        <input name="province" placeholder="استان" required
               class="border rounded-lg p-2" />
        <input name="city" placeholder="شهر" required
               class="border rounded-lg p-2" />
        <input name="region" placeholder="منطقه" required
               class="border rounded-lg p-2" />
      </div>

      <button type="submit"
              class="w-full bg-blue-600 text-white rounded-lg p-2">
        ثبت مشترک
      </button>
    </form>

    <p id="msg" class="mt-4 text-sm"></p>
  </div>

<script>
document.getElementById('form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target));
  const res = await fetch('/api/subscribers', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  const out = document.getElementById('msg');
  if (res.ok) {
    out.textContent = 'مشترک با موفقیت ثبت شد.';
    e.target.reset();
  } else {
    out.textContent = 'خطا در ثبت مشترک.';
  }
});
</script>
</body>
</html>
```

---

## ۷. نمونه کد — بک‌اند پایتون

### ۷.۱ مدل‌ها و API

```python
# main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlmodel import SQLModel, Field, Session, create_engine, select
from datetime import datetime
from typing import Optional

engine = create_engine("sqlite:///app.db")
app = FastAPI(title="Outage SMS Alert")


class Subscriber(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    full_name: str
    mobile: str
    province: str
    city: str
    region: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)


class SubscriberIn(BaseModel):
    full_name: str
    mobile: str
    province: str
    city: str
    region: str


@app.on_event("startup")
def init_db():
    SQLModel.metadata.create_all(engine)


@app.post("/api/subscribers")
def create_subscriber(data: SubscriberIn):
    with Session(engine) as s:
        exists = s.exec(
            select(Subscriber).where(Subscriber.mobile == data.mobile)
        ).first()
        if exists:
            raise HTTPException(400, "این شماره قبلاً ثبت شده است")
        sub = Subscriber(**data.dict())
        s.add(sub)
        s.commit()
        s.refresh(sub)
        return sub
```

### ۷.۲ برداشت جدول خاموشی

```python
# scraper.py
import requests
from bs4 import BeautifulSoup
from datetime import datetime


def fetch_outages(url: str) -> list[dict]:
    """جدول خاموشی را از صفحه رسمی برداشت می‌کند."""
    html = requests.get(url, timeout=20).text
    soup = BeautifulSoup(html, "html.parser")

    outages = []
    for row in soup.select("table tr")[1:]:
        cells = [c.get_text(strip=True) for c in row.select("td")]
        if len(cells) < 4:
            continue
        region, date_str, start_str, end_str = cells[:4]
        outages.append({
            "region": region,
            "start_at": datetime.strptime(f"{date_str} {start_str}", "%Y/%m/%d %H:%M"),
            "end_at": datetime.strptime(f"{date_str} {end_str}", "%Y/%m/%d %H:%M"),
            "source_url": url,
        })
    return outages
```

### ۷.۳ موتور تطبیق و ارسال

```python
# notifier.py
from datetime import datetime, timedelta
from sqlmodel import Session, select
from kavenegar import KavenegarAPI

API_KEY = "YOUR_API_KEY"
LEAD_MINUTES = 30  # چند دقیقه قبل از خاموشی هشدار داده شود


def build_message(outage) -> str:
    return (
        f"اطلاع‌رسانی خاموشی\n"
        f"منطقه: {outage.region}\n"
        f"از ساعت {outage.start_at:%H:%M} تا {outage.end_at:%H:%M}"
    )


def send_sms(mobile: str, text: str):
    api = KavenegarAPI(API_KEY)
    api.sms_send({"receptor": mobile, "message": text})


def dispatch(engine):
    now = datetime.now()
    window_end = now + timedelta(minutes=LEAD_MINUTES)

    with Session(engine) as s:
        outages = s.exec(
            select(Outage).where(
                Outage.start_at >= now,
                Outage.start_at <= window_end,
            )
        ).all()

        for outage in outages:
            subs = s.exec(
                select(Subscriber).where(
                    Subscriber.region == outage.region,
                    Subscriber.is_active == True,
                )
            ).all()
            for sub in subs:
                send_sms(sub.mobile, build_message(outage))
```

### ۷.۴ زمان‌بندی

```python
# scheduler.py
from apscheduler.schedulers.blocking import BlockingScheduler
from scraper import fetch_outages
from notifier import dispatch

sched = BlockingScheduler(timezone="Asia/Tehran")

sched.add_job(lambda: fetch_outages(SOURCE_URL), "interval", hours=6)
sched.add_job(lambda: dispatch(engine), "interval", minutes=10)

sched.start()
```

---

## ۸. مدل درآمدی

- اشتراک ماهانه برای هر شماره موبایل.
- تخفیف برای اشتراک سالانه.
- پلن ویژه کسب‌وکارها (چند شماره).

---

## ۹. نقشه راه

| فاز | خروجی |
|---|---|
| ۱ | رابط وب + پایگاه داده + ثبت دستی کاربران |
| ۲ | Scraper و Parser جدول خاموشی |
| ۳ | موتور تطبیق و ارسال پیامک |
| ۴ | درگاه پرداخت و مدیریت اشتراک |
| ۵ | ثبت‌نام مستقیم کاربر (بدون اپراتور) |

---

## ۱۰. ریسک‌ها

- تغییر ساختار صفحه منبع و خراب شدن Scraper.
- تأخیر یا نادرستی داده‌های منتشرشده.
- هزینه پیامک.
