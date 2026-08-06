"""Known direct sources for outage schedules, tried before falling back to search.

Add more cities/URLs here as you confirm they publish a per-city page.
Everything else is discovered through search.web_search().
"""
from __future__ import annotations

from urllib.parse import quote

DIRECT_SOURCES: dict[str, list[str]] = {
    "بابل": [
        "https://app.e-saricity.ir/khamooshi/{city}",
    ],
}


def direct_urls_for(city: str) -> list[str]:
    templates = DIRECT_SOURCES.get(city, [])
    return [template.format(city=quote(city)) for template in templates]
