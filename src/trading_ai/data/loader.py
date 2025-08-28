
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
import pandas as pd
from datetime import datetime

SessionTZ = Literal["Asia/Kolkata", "UTC"]

@dataclass(frozen=True)
class CandleSchema:
    timestamp_col: str = "timestamp"
    open_col: str = "open"
    high_col: str = "high"
    low_col: str = "low"
    close_col: str = "close"
    volume_col: str = "volume"


def read_candles_csv(path: str, schema: CandleSchema = CandleSchema()) -> pd.DataFrame:
    """Read CSV into a strictly-typed DataFrame with expected columns.

    Expected columns: timestamp, open, high, low, close, volume
    """

    df = pd.read_csv(path)
    expected = [schema.timestamp_col, schema.open_col, schema.high_col, schema.low_col, schema.close_col, schema.volume_col]
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing} in {path}")
    # Parse timestamp
    df[schema.timestamp_col] = pd.to_datetime(df[schema.timestamp_col], utc=True, errors="coerce")
    if df[schema.timestamp_col].isna().any():
        bad = df[df[schema.timestamp_col].isna()].index.tolist()[:5]
        raise ValueError(f"Unparseable timestamps at rows: {bad}")
    # Enforce numeric types
    for col in [schema.open_col, schema.high_col, schema.low_col, schema.close_col, schema.volume_col]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        if df[col].isna().any():
            bad = df[df[col].isna()].index.tolist()[:5]
            raise ValueError(f"Non-numeric values in column '{col}' at rows: {bad}")
    # Basic OHLC sanity
    if (df[schema.high_col] < df[[schema.open_col, schema.close_col]].max(axis=1)).any():
        raise ValueError("Found high < max(open, close)")
    if (df[schema.low_col] > df[[schema.open_col, schema.close_col]].min(axis=1)).any():
        raise ValueError("Found low > min(open, close)")
    # Sorted, deduped
    df = df.sort_values(schema.timestamp_col).drop_duplicates(subset=[schema.timestamp_col])
    df = df.reset_index(drop=True)
    return df


def enforce_market_hours(df: pd.DataFrame, tz: SessionTZ = "Asia/Kolkata") -> pd.DataFrame:
    """Filter rows to Indian market hours (default cash session 09:15–15:30 IST)."""

    s = df.copy()
    s["_ts_local"] = s["timestamp"].dt.tz_convert(tz)
    # Market hours: 09:15 <= time <= 15:30
    mask = (s["_ts_local"].dt.time >= pd.Timestamp("09:15").time()) & (s["_ts_local"].dt.time <= pd.Timestamp("15:30").time())
    out = s.loc[mask].drop(columns=["_ts_local"])  # type: ignore
    return out
