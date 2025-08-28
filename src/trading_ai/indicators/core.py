
from __future__ import annotations
import pandas as pd

def _ensure_cols(df: pd.DataFrame):
    for c in ["open","high","low","close","volume"]:
        if c not in df.columns:
            raise KeyError(f"Expected column '{c}'")


def add_rsi(df: pd.DataFrame, length: int = 14) -> pd.DataFrame:
    _ensure_cols(df)
    try:
        import pandas_ta as ta
        df["rsi"] = ta.rsi(df["close"], length=length)
    except Exception:
        # Simple fallback RSI (Wilder's smoothing approximation)
        delta = df["close"].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/length, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/length, adjust=False).mean()
        rs = gain / (loss.replace(0, 1e-12))
        df["rsi"] = 100 - (100 / (1 + rs))
    return df


def add_emas(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> pd.DataFrame:
    _ensure_cols(df)
    df["ema_fast"] = df["close"].ewm(span=fast, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=slow, adjust=False).mean()
    df["ema_trend"] = (df["ema_fast"] > df["ema_slow"]).map({True: "up", False: "down"})
    return df


def add_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    _ensure_cols(df)
    try:
        import pandas_ta as ta
        macd = ta.macd(df["close"], fast=fast, slow=slow, signal=signal)
        df["macd"] = macd["MACD_12_26_9"]
        df["macd_signal"] = macd["MACDs_12_26_9"]
    except Exception:
        ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        df["macd"] = macd_line
        df["macd_signal"] = signal_line
    df["macd_state"] = (df["macd"] > df["macd_signal"]).map({True: "bull", False: "bear"})
    df["macd_cross"] = (df["macd_state"].ne(df["macd_state"].shift(1))).astype(int)
    return df


def add_bbands(df: pd.DataFrame, length: int = 20, std: float = 2.0) -> pd.DataFrame:
    _ensure_cols(df)
    ma = df["close"].rolling(length).mean()
    dev = df["close"].rolling(length).std(ddof=0) * std
    df["bb_mid"] = ma
    df["bb_up"] = ma + dev
    df["bb_dn"] = ma - dev
    pos = []
    for c, up, dn in zip(df["close"], df["bb_up"], df["bb_dn"]):
        if pd.isna(up) or pd.isna(dn):
            pos.append(None)
        elif c > up:
            pos.append("above")
        elif c < dn:
            pos.append("below")
        else:
            pos.append("inside")
    df["bb_pos"] = pos
    return df


def add_atr(df: pd.DataFrame, length: int = 14) -> pd.DataFrame:
    _ensure_cols(df)
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = tr.rolling(length).mean()
    return df


def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    _ensure_cols(df)
    # Session VWAP: assumes DF contains a single session; reset per-day in production.

    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    cum_vol = df["volume"].cumsum()
    cum_tpv = (typical * df["volume"]).cumsum()
    df["vwap"] = cum_tpv / cum_vol.replace(0, pd.NA)
    return df
