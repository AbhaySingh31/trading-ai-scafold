
from __future__ import annotations
import pandas as pd
def read_candles_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path); df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values("timestamp").reset_index(drop=True)
def enforce_market_hours(df: pd.DataFrame) -> pd.DataFrame:
    ts = pd.to_datetime(df["timestamp"], utc=True); ist = ts.dt.tz_convert("Asia/Kolkata")
    hhmm = ist.dt.hour*60 + ist.dt.minute; open_m=9*60+15; close_m=15*60+30
    return df.loc[(hhmm>=open_m)&(hhmm<=close_m)].reset_index(drop=True)
