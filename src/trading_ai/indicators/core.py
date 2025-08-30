
from __future__ import annotations
import pandas as pd
import numpy as np
def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()
def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    delta = df["close"].diff()
    up = delta.clip(lower=0.0); down = -delta.clip(upper=0.0)
    roll_up = up.ewm(alpha=1/period, adjust=False).mean()
    roll_down = down.ewm(alpha=1/period, adjust=False).mean()
    rs = roll_up / roll_down.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs)); return df
def add_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    ema_fast = _ema(df["close"], fast); ema_slow = _ema(df["close"], slow)
    df["macd"] = ema_fast - ema_slow; df["macd_signal"] = _ema(df["macd"], signal); return df
def add_emas(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> pd.DataFrame:
    df["ema_fast"] = _ema(df["close"], fast); df["ema_slow"] = _ema(df["close"], slow); return df
def add_bbands(df: pd.DataFrame, period: int = 20, std: float = 2.0) -> pd.DataFrame:
    ma = df["close"].rolling(period).mean(); sd = df["close"].rolling(period).std()
    df["bb_mid"] = ma; df["bb_up"] = ma + std*sd; df["bb_dn"] = ma - std*sd
    pos = (df["close"] - df["bb_mid"]) / (df["bb_up"] - df["bb_dn"]).replace(0, np.nan)
    df["bb_pos"] = pos; return df
def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    high=df["high"]; low=df["low"]; close=df["close"]; prev_close = close.shift(1)
    tr = pd.concat([high-low, (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(period).mean(); return df
def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    # Create the column even if empty to keep downstream code happy
    if df is None or df.empty:
        df["vwap"] = np.nan
        return df

    # Force numeric types; index volumes are often blank -> 0
    for c in ("open","high","low","close","volume"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df[["open","high","low","close"]] = df[["open","high","low","close"]].ffill()
    if "volume" in df.columns:
        df["volume"] = df["volume"].fillna(0)

    # Need a datetime column named 'timestamp'
    if "timestamp" not in df.columns:
        raise ValueError("DataFrame must have a 'timestamp' column (datetime64[ns, tz])")

    # Day-wise cumulative typical price * volume
    day = df["timestamp"].dt.date
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    v  = df["volume"].astype(float)

    denom = v.groupby(day).cumsum()
    numer = (tp * v).groupby(day).cumsum()

    # Avoid divide-by-zero on days with all-zero volumes (common on indices)
    denom = denom.replace(0, np.nan)
    df["vwap"] = (numer / denom).ffill()

    return df