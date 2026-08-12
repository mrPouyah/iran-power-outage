"""Adapters for known direct outage sources whose exact markup we track.

Unlike parser.py's generic table/text strategies (aimed at arbitrary,
unknown search-result pages), each module here targets one specific
site's real DOM/tech stack. Register new adapters in ../sources.py
against a DIRECT_SOURCES entry.
"""
# این پکیج محل نگه‌داری «آداپتورهای اختصاصی هر سایت» است.
# هر سایت رسمی ساختار HTML متفاوتی دارد (جدول، کارت، متن آزاد و...)،
# پس به‌جای یک پارسر عمومی حدسی، برای هر سایت شناخته‌شده یک فایل
# جداگانه با منطق دقیق همان سایت می‌نویسیم.
from __future__ import annotations

from . import e_saricity

__all__ = ["e_saricity"]
