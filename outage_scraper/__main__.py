# این فایل باعث می‌شود پکیج مستقیماً با دستور «python -m outage_scraper» اجرا شود.
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
