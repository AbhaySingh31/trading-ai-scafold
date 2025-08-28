
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, List
import pandas as pd

@dataclass
class TriggerConfig:
    rsi_oversold: float = 30.0
    volume_multiple: float = 1.5
    cooldown_bars: int = 10


def compute_volume_multiple(s: pd.Series, window: int = 20) -> pd.Series:
    avg = s.rolling(window).mean()
    return s / avg


def detect_setups(df: pd.DataFrame, cfg: TriggerConfig) -> List[Dict[str, Any]]:
    """Return a list of signal packages at rows where triggers fire."""

    signals: List[Dict[str, Any]] = []
    vol_mult = compute_volume_multiple(df["volume"]).rename("vol_mult")

    last_signal_idx = -10**9  # far back

    for i in range(len(df)):

        row = df.iloc[i]

        # Warm-up: skip until indicators valid

        if any(pd.isna(row.get(k)) for k in ["rsi","macd","macd_signal","ema_fast","ema_slow","bb_up","bb_dn","atr"]):

            continue

        # Cooldown

        if i - last_signal_idx < cfg.cooldown_bars:
            continue


        # Conditions

        long_meanrev = (row["rsi"] < cfg.rsi_oversold) and (row["macd"] > row["macd_signal"]) and (vol_mult.iat[i] > cfg.volume_multiple)

        long_momo = (row["close"] > row["bb_up"]) and (vol_mult.iat[i] > cfg.volume_multiple)


        if long_meanrev or long_momo:

            pkg = {

                "symbol": row.get("symbol","UNKNOWN"),

                "timeframe": row.get("timeframe","UNKNOWN"),

                "timestamp": row["timestamp"],

                "price": float(row["close"]),

                "rsi": float(row["rsi"]),

                "macd_state": "bull" if row["macd"] > row["macd_signal"] else "bear",

                "ema20_vs_ema50": "up" if row["ema_fast"] > row["ema_slow"] else "down",

                "bands_position": row["bb_pos"],

                "volume_multiple": float(vol_mult.iat[i]),

                "atr": float(row["atr"]),

                "key_levels": {"support": float(row["close"] - 1.2*row["atr"]), "resistance": float(row["close"] + 1.8*row["atr"])},

                "context": "meanrev" if long_meanrev else "momentum",

            }

            signals.append(pkg)

            last_signal_idx = i

    return signals
