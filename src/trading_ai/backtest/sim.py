from __future__ import annotations
from typing import List, Dict, Any
import pandas as pd

def _find_entry_index(df: pd.DataFrame, ts) -> int | None:
    idx = df.index[df['timestamp'] >= ts]
    if len(idx) == 0:
        return None
    i = int(idx[0]) + 1  # enter next bar open
    if i >= len(df):
        return None
    return i

def simulate_trades(df: pd.DataFrame, trades: List[Dict[str, Any]], max_bars: int = 60) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    for t in trades:
        action = t.get('action', 'HOLD').upper()
        if action not in ('BUY', 'SELL'):
            enriched.append({**t, "exit_price": None, "exit_time": None, "pnl": 0.0, "R": 0.0, "status": "SKIPPED"})
            continue

        entry_idx = _find_entry_index(df, pd.Timestamp(t["timestamp"]).tz_convert("UTC"))
        if entry_idx is None:
            enriched.append({**t, "exit_price": None, "exit_time": None, "pnl": 0.0, "R": 0.0, "status": "NO_ENTRY"})
            continue

        entry_price = float(df.iloc[entry_idx]["open"])
        sl = float(t["stop_loss"])
        t1 = float(t["t1"])
        t2 = float(t["t2"])

        status = "OPEN"
        exit_price = None
        exit_time = None

        # Risk per unit (R)
        if action == "BUY":
            risk_per_unit = max(entry_price - sl, 1e-6)
        else:
            risk_per_unit = max(sl - entry_price, 1e-6)

        for i in range(entry_idx, min(entry_idx + max_bars, len(df))):
            row = df.iloc[i]
            high = float(row["high"]); low = float(row["low"]); ts = row["timestamp"]

            if action == "BUY":
                if low <= sl:
                    exit_price, exit_time, status = sl, ts, "SL_HIT"; break
                if high >= t2:
                    exit_price, exit_time, status = t2, ts, "TP2_HIT"; break
                if high >= t1:
                    exit_price, exit_time, status = t1, ts, "TP1_HIT"; break
            else:  # SELL
                if high >= sl:
                    exit_price, exit_time, status = sl, ts, "SL_HIT"; break
                if low <= t2:
                    exit_price, exit_time, status = t2, ts, "TP2_HIT"; break
                if low <= t1:
                    exit_price, exit_time, status = t1, ts, "TP1_HIT"; break

        if exit_price is None:
            row = df.iloc[min(entry_idx + max_bars - 1, len(df)-1)]
            exit_price = float(row["close"])
            exit_time = row["timestamp"]
            status = "TIMEOUT"

        pnl = (exit_price - entry_price) if action == "BUY" else (entry_price - exit_price)
        R = pnl / risk_per_unit if risk_per_unit else 0.0

        enriched.append({
            **t,
            "entry_filled": entry_price,
            "entry_time": df.iloc[entry_idx]["timestamp"],
            "exit_price": round(exit_price, 2),
            "exit_time": exit_time,
            "pnl": round(pnl, 2),
            "R": round(R, 3),
            "status": status,
        })
    return enriched
