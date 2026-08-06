from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional


@dataclass
class OutageRecord:
    """One scheduled outage slot for one neighborhood/street group."""

    city: str
    province: str
    date_jalali: str
    date_gregorian: str
    location: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    neighborhood_code: Optional[str] = None
    source_url: str = ""
    source_title: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def key(self) -> tuple:
        """Identity used for de-duplication across sources."""
        return (self.location.strip(), self.start_time, self.end_time, self.neighborhood_code)
