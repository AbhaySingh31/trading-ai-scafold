
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
    ts = pd.to_datetime(df["timestamp"], utc=True); day = ts.dt.tz_convert("Asia/Kolkata").dt.date
    tp = (df["high"] + df["low"] + df["close"]) / 3.0; v = df["volume"].astype(float)
    df["vwap"] = (tp*v).groupby(day).cumsum() / v.groupby(day).cumsum(); return df
