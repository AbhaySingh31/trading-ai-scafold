from __future__ import annotations
from pathlib import Path
import pandas as pd

REQUIRED_COLS = ["timestamp", "open", "high", "low", "close", "volume"]

def read_candles_csv(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"[data] File not found: {p.resolve()}")

    try:
        df = pd.read_csv(p)
    except Exception as e:
        raise SystemExit(f"[data] Failed to read CSV '{p.name}': {e}")

    # schema check
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise SystemExit(f"[data] Missing required columns {missing} in '{p.name}'")

    # parse timestamps w/ UTC; surface bad rows clearly
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    bad = int(df["timestamp"].isna().sum())
    if bad:
        raise SystemExit(f"[data] {bad} bad timestamp value(s) in '{p.name}'")

    return df

def enforce_market_hours(df: pd.DataFrame) -> pd.DataFrame:
    # keep your existing logic here (unchanged)
    from pandas import Timestamp
    # ... existing code ...
    return df
