# src/trading_ai/utils/expiry.py
from __future__ import annotations
from datetime import datetime, timedelta, timezone

def next_thursday_ist(now_utc: datetime) -> datetime:
    ist_offset = timedelta(hours=5, minutes=30)
    ist = now_utc + ist_offset
    days_ahead = (3 - ist.weekday()) % 7  # Thu=3
    th_ist = (ist + timedelta(days=days_ahead)).replace(hour=0, minute=0, second=0, microsecond=0)
    return th_ist - ist_offset
