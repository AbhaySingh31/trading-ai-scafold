#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Scalp backtester (1m bars) for NIFTY / BANKNIFTY options.

Momentum-on-either-side:
- CE (long): setup if RSI <= rsi_floor; confirm on MACD cross-up.
- PE (long put): setup if RSI >= (100 - rsi_floor); confirm on MACD cross-down.
- Enter at next bar OPEN after confirm, exit on TP/SL/time.
- PnL (₹) ≈ (dir * (exit - entry)) * lot_size * delta_factor
  where dir=+1 for CE, dir=-1 for PE.

CLI:
  --data DATA
  --symbol {NIFTY,BANKNIFTY}
  --side {BOTH,CE,PE}           (default BOTH)
  --rsi-floor FLOAT             (default 50)
  --confirm-within INT          (bars, default 2)
  --tp-pts FLOAT                (required)
  --sl-pts FLOAT                (required)
  --delta-factor FLOAT          (default 0.40)
  --max-hold-bars INT           (default 30)
  --lot-size INT                (required)
  --out-trades CSV              (required)

Assumptions:
- CSV columns: timestamp, open, high, low, close (volume optional).
- If timestamp is tz-naive we assume IST; otherwise converted to IST.
"""

from __future__ import annotations
import argparse
from dataclasses import dataclass
from typing import List, Tuple, Set

import pandas as pd
import numpy as np


# ---------- indicators ----------
def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

def rsi14(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = (delta.clip(lower=0)).ewm(alpha=1/period, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs = up / (down.replace(0, np.nan))
    rsi = 100 - (100 / (1 + rs))
    return rsi.bfill().fillna(50)

def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


# ---------- helpers ----------
def ensure_ist(df: pd.DataFrame) -> pd.DataFrame:
    if "timestamp" not in df.columns:
        raise SystemExit("CSV must have a 'timestamp' column.")
    ts = pd.to_datetime(df["timestamp"], utc=False, errors="coerce")
    if ts.isna().any():
        bad = df.loc[ts.isna(), "timestamp"].head(3).tolist()
        raise SystemExit(f"Bad timestamp parse. Examples: {bad}")
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize("Asia/Kolkata")
    else:
        ts = ts.dt.tz_convert("Asia/Kolkata")
    out = df.copy()
    out["timestamp"] = ts
    return out

def strike_step_for(symbol: str) -> int:
    return 50 if symbol.upper() == "NIFTY" else 100

def round_to_step(x: float, step: int) -> int:
    return int(round(x / step) * step)


# ---------- model ----------
@dataclass
class Trade:
    symbol: str
    side: str          # 'CE' or 'PE'
    dir: int           # +1 for CE, -1 for PE
    strike: int
    setup_time: pd.Timestamp
    confirm_time: pd.Timestamp
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    exit_reason: str   # TP / SL / TIME
    entry_price: float
    exit_price: float
    pnl_pts: float
    pnl_money: float
    rsi_on_setup: float
    tp_pts: float
    sl_pts: float
    lots: int


def find_trades(
    df: pd.DataFrame,
    symbol: str,
    want_side: str,        # 'CE' / 'PE' / 'BOTH'
    rsi_floor: float,
    confirm_within: int,
    tp_pts: float,
    sl_pts: float,
    delta_factor: float,
    max_hold_bars: int,
    lot_size: int,
) -> List[Trade]:

    df = df.reset_index(drop=True)
    open_ = df["open"].astype(float).values
    high  = df["high"].astype(float).values
    low   = df["low"].astype(float).values
    close = df["close"].astype(float).values
    ts    = df["timestamp"]  # <-- keep as Series to preserve tz

    # Indicators
    rsi = rsi14(pd.Series(close))
    macd_line, signal_line, _ = macd(pd.Series(close))
    cross_up   = (macd_line > signal_line) & (macd_line.shift(1) <= signal_line.shift(1))
    cross_down = (macd_line < signal_line) & (macd_line.shift(1) >= signal_line.shift(1))

    # Setup gates
    setup_ce = (rsi <= rsi_floor)
    setup_pe = (rsi >= (100.0 - rsi_floor))

    consider_ce = want_side in ("CE", "BOTH")
    consider_pe = want_side in ("PE", "BOTH")

    step = strike_step_for(symbol)
    trades: List[Trade] = []

    # DEDUPE: only one entry per confirm bar per side
    taken_ce: Set[pd.Timestamp] = set()
    taken_pe: Set[pd.Timestamp] = set()

    n = len(df)
    i = 0
    while i < n:
        # Try CE side
        if consider_ce and bool(setup_ce.iloc[i]):
            c_idx = None
            for j in range(i + 1, min(i + 1 + confirm_within, n)):
                if bool(cross_up.iloc[j]):
                    c_idx = j
                    break
            if c_idx is not None and c_idx + 1 < n:
                confirm_time = ts.iloc[c_idx]  # already IST
                if confirm_time not in taken_ce:
                    taken_ce.add(confirm_time)
                    entry_idx = c_idx + 1
                    entry_time = ts.iloc[entry_idx]
                    entry_price = float(open_[entry_idx])
                    strike = round_to_step(entry_price, step)
                    dir_ = +1  # CE

                    target = entry_price + tp_pts
                    stop   = entry_price - sl_pts
                    exit_idx = None
                    exit_reason = "TIME"
                    for k in range(entry_idx, min(entry_idx + max_hold_bars, n)):
                        if float(high[k]) >= target:
                            exit_idx = k; exit_reason = "TP"; exit_price = target; break
                        if float(low[k])  <= stop:
                            exit_idx = k; exit_reason = "SL"; exit_price = stop;   break
                    if exit_idx is None:
                        exit_idx = min(entry_idx + max_hold_bars - 1, n - 1)
                        exit_price = float(close[exit_idx])

                    pnl_pts = dir_ * (exit_price - entry_price)
                    pnl_money = pnl_pts * lot_size * float(delta_factor)

                    t = Trade(
                        symbol=symbol, side="CE", dir=dir_, strike=int(strike),
                        setup_time=ts.iloc[i],
                        confirm_time=confirm_time,
                        entry_time=entry_time, exit_time=ts.iloc[exit_idx],
                        exit_reason=exit_reason, entry_price=entry_price, exit_price=float(exit_price),
                        pnl_pts=float(pnl_pts), pnl_money=float(pnl_money),
                        rsi_on_setup=float(rsi.iloc[i]), tp_pts=float(tp_pts), sl_pts=float(sl_pts), lots=1
                    )
                    trades.append(t)

                    et = t.entry_time.strftime("%Y-%m-%d %H:%M:%S")
                    st = t.setup_time.strftime("%Y-%m-%d %H:%M:%S")
                    ct = t.confirm_time.strftime("%H:%M:%S")
                    xt = t.exit_time.strftime("%H:%M:%S")
                    sign = "+" if t.pnl_pts >= 0 else ""
                    print(f"[{symbol}] ENTER CE ATM {t.strike} @ {t.entry_price:.2f} (entry {et}) | "
                          f"setup {st}, confirm {ct} | "
                          f"EXIT {t.exit_reason} {t.exit_price:.2f} @ {xt} | "
                          f"P/L pts={sign}{t.pnl_pts:.2f} ₹={sign}{t.pnl_money:.2f} | "
                          f"RSI={t.rsi_on_setup:.1f}, MACD↑ at {ct}, TP={tp_pts:.1f}, SL={sl_pts:.1f}, lots={t.lots}")

                    i = entry_idx  # skip to entry bar to avoid immediate re-use

        # Try PE side
        if consider_pe and bool(setup_pe.iloc[i]):
            c_idx = None
            for j in range(i + 1, min(i + 1 + confirm_within, n)):
                if bool(cross_down.iloc[j]):
                    c_idx = j
                    break
            if c_idx is not None and c_idx + 1 < n:
                confirm_time = ts.iloc[c_idx]  # already IST
                if confirm_time not in taken_pe:
                    taken_pe.add(confirm_time)
                    entry_idx = c_idx + 1
                    entry_time = ts.iloc[entry_idx]
                    entry_price = float(open_[entry_idx])
                    strike = round_to_step(entry_price, step)
                    dir_ = -1  # PE

                    target = entry_price + dir_ * tp_pts      # entry - tp
                    stop   = entry_price - dir_ * sl_pts      # entry + sl
                    exit_idx = None
                    exit_reason = "TIME"
                    for k in range(entry_idx, min(entry_idx + max_hold_bars, n)):
                        if float(low[k])  <= target:  # down move hits TP
                            exit_idx = k; exit_reason = "TP"; exit_price = target; break
                        if float(high[k]) >= stop:    # up move hits SL
                            exit_idx = k; exit_reason = "SL"; exit_price = stop;   break
                    if exit_idx is None:
                        exit_idx = min(entry_idx + max_hold_bars - 1, n - 1)
                        exit_price = float(close[exit_idx])

                    pnl_pts = dir_ * (exit_price - entry_price)
                    pnl_money = pnl_pts * lot_size * float(delta_factor)

                    t = Trade(
                        symbol=symbol, side="PE", dir=dir_, strike=int(strike),
                        setup_time=ts.iloc[i],
                        confirm_time=confirm_time,
                        entry_time=entry_time, exit_time=ts.iloc[exit_idx],
                        exit_reason=exit_reason, entry_price=entry_price, exit_price=float(exit_price),
                        pnl_pts=float(pnl_pts), pnl_money=float(pnl_money),
                        rsi_on_setup=float(rsi.iloc[i]), tp_pts=float(tp_pts), sl_pts=float(sl_pts), lots=1
                    )
                    trades.append(t)

                    et = t.entry_time.strftime("%Y-%m-%d %H:%M:%S")
                    st = t.setup_time.strftime("%Y-%m-%d %H:%M:%S")
                    ct = t.confirm_time.strftime("%H:%M:%S")
                    xt = t.exit_time.strftime("%H:%M:%S")
                    sign = "+" if t.pnl_pts >= 0 else ""
                    print(f"[{symbol}] ENTER PE ATM {t.strike} @ {t.entry_price:.2f} (entry {et}) | "
                          f"setup {st}, confirm {ct} | "
                          f"EXIT {t.exit_reason} {t.exit_price:.2f} @ {xt} | "
                          f"P/L pts={sign}{t.pnl_pts:.2f} ₹={sign}{t.pnl_money:.2f} | "
                          f"RSI={t.rsi_on_setup:.1f}, MACD↓ at {ct}, TP={tp_pts:.1f}, SL={sl_pts:.1f}, lots={t.lots}")

                    i = entry_idx

        i += 1

    return trades


# ---------- CLI ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--symbol", required=True, choices=["NIFTY", "BANKNIFTY"])
    ap.add_argument("--side", choices=["BOTH","CE","PE"], default="BOTH")
    ap.add_argument("--rsi-floor", type=float, default=50.0)
    ap.add_argument("--confirm-within", type=int, default=2)
    ap.add_argument("--tp-pts", type=float, required=True)
    ap.add_argument("--sl-pts", type=float, required=True)
    ap.add_argument("--delta-factor", type=float, default=0.40)
    ap.add_argument("--max-hold-bars", type=int, default=30)
    ap.add_argument("--lot-size", type=int, required=True)
    ap.add_argument("--out-trades", required=True)
    # placeholders for parity if you pass them:
    ap.add_argument("--capital", type=float, default=30000.0)
    ap.add_argument("--risk-pct", type=float, default=0.02)
    args = ap.parse_args()

    df = pd.read_csv(args.data)
    needed = {"timestamp","open","high","low","close"}
    missing = needed.difference(df.columns)
    if missing:
        raise SystemExit(f"CSV missing columns: {sorted(missing)}")

    df = ensure_ist(df)

    trades = find_trades(
        df=df,
        symbol=args.symbol.upper(),
        want_side=args.side,
        rsi_floor=args.rsi_floor,
        confirm_within=args.confirm_within,
        tp_pts=args.tp_pts,
        sl_pts=args.sl_pts,
        delta_factor=args.delta_factor,
        max_hold_bars=args.max_hold_bars,
        lot_size=args.lot_size,
    )

    # Save
    cols = ["symbol","side","strike","setup_time","confirm_time","entry_time","exit_time",
            "exit_reason","entry_price","exit_price","pnl_pts","pnl_money","rsi_on_setup",
            "tp_pts","sl_pts","lots"]
    if trades:
        rows = [{
            "symbol": t.symbol, "side": t.side, "strike": t.strike,
            "setup_time": t.setup_time.isoformat(),
            "confirm_time": t.confirm_time.isoformat(),
            "entry_time": t.entry_time.isoformat(),
            "exit_time": t.exit_time.isoformat(),
            "exit_reason": t.exit_reason,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "pnl_pts": t.pnl_pts,
            "pnl_money": t.pnl_money,
            "rsi_on_setup": t.rsi_on_setup,
            "tp_pts": t.tp_pts, "sl_pts": t.sl_pts, "lots": t.lots
        } for t in trades]
        pd.DataFrame(rows)[cols].to_csv(args.out_trades, index=False)
    else:
        pd.DataFrame(columns=cols).to_csv(args.out_trades, index=False)

    wins  = sum(1 for t in trades if t.exit_reason=="TP")
    losses= sum(1 for t in trades if t.exit_reason=="SL")
    times = sum(1 for t in trades if t.exit_reason=="TIME")
    total = len(trades)
    pnl   = sum(t.pnl_money for t in trades)
    print(f"Saved -> {args.out_trades}")
    print(f"Trades: {total} | Wins: {wins}  Losses: {losses}  Time exits: {times}")
    print(f"Total PnL (₹): {pnl:.2f}")


if __name__ == "__main__":
    main()
