# -*- coding: utf-8 -*-
"""
Multi-Timeframe (MTF) backtest runner.

Fixes:
- robust tz-aware timestamp parsing and IST conversion,
- numeric coercion before VWAP,
- numpy import for dtype checks.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import numpy as np
import pandas as pd

from trading_ai.indicators.core import add_vwap

IST_TZ = "Asia/Kolkata"


def read_csv_ist(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "timestamp" not in df.columns:
        raise SystemExit(f"[mtf] 'timestamp' column missing in {path}")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df["timestamp"] = df["timestamp"].dt.tz_convert(IST_TZ)
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def enforce_market_hours(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    ts = df["timestamp"].dt.tz_convert(IST_TZ)
    hhmm = ts.dt.strftime("%H:%M")
    mask = (hhmm >= "09:15") & (hhmm <= "15:30")
    return df.loc[mask].copy()


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = add_vwap(df)
    return df


def run(args):
    fast_path = args.fast_csv or args.fast
    slow_path = args.slow_csv or args.slow
    if not fast_path or not slow_path:
        raise SystemExit("--fast/--fast-csv and --slow/--slow-csv are required")

    df_fast = enrich(enforce_market_hours(read_csv_ist(fast_path)))
    df_slow = enrich(enforce_market_hours(read_csv_ist(slow_path)))

    # Your signal/trade code would run here.
    signals = pd.DataFrame(columns=["timestamp", "symbol", "timeframe", "signal", "note"])
    trades = pd.DataFrame(columns=["symbol", "entry_time", "exit_time", "direction",
                                   "entry_price", "exit_price", "pnl_money", "outcome"])

    if args.use_presets:
        if args.symbol.upper() == "BANKNIFTY":
            print(f"[presets] BANKNIFTY: round_to=15  min_qty=15  point_value=1.0  "
                  f"tick_size={args.tick_size}  tick_round=nearest  strike_step=100")
        else:
            print(f"[presets] NIFTY: round_to=50  min_qty=50  point_value=1.0  "
                  f"tick_size={args.tick_size}  tick_round=nearest  strike_step=50")

    if args.out_signals:
        signals.to_csv(args.out_signals, index=False)
    if args.out_trades:
        trades.to_csv(args.out_trades, index=False)

    print(f"MTF done. Signals={len(signals)} Trades={len(trades)}")
    if args.out_signals and args.out_trades:
        print(f"Saved -> {args.out_signals} , {args.out_trades}")


def main():
    ap = argparse.ArgumentParser(description="MTF backtest runner (fixed tz/numeric handling).")
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--fast-csv", dest="fast_csv")
    ap.add_argument("--slow-csv", dest="slow_csv")
    ap.add_argument("--fast")
    ap.add_argument("--slow")
    ap.add_argument("--out-signals")
    ap.add_argument("--out-trades")
    ap.add_argument("--use-presets", action="store_true")
    ap.add_argument("--tick-size", type=float, default=0.05)
    ap.add_argument("--risk-pct", type=float, default=0.005)
    args = ap.parse_args()
    run(args)


if __name__ == "__main__":
    main()
