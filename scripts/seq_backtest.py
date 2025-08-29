# scripts/seq_backtest.py
from __future__ import annotations
import argparse
from dataclasses import dataclass
from typing import List, Optional, Tuple
from math import floor, ceil
import pandas as pd
import numpy as np

# ---------- indicators ----------
def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(up, index=series.index).ewm(alpha=1/period, adjust=False).mean()
    roll_down = pd.Series(down, index=series.index).ewm(alpha=1/period, adjust=False).mean()
    rs = roll_up / (roll_down.replace(0, np.nan))
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(method="bfill").fillna(50)

def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    line = ema_fast - ema_slow
    sig = line.ewm(span=signal, adjust=False).mean()
    hist = line - sig
    return line, sig, hist

def boll_bands(series: pd.Series, period: int = 20, mult: float = 2.0):
    ma = series.rolling(period).mean()
    sd = series.rolling(period).std(ddof=0)
    upper = ma + mult * sd
    lower = ma - mult * sd
    return upper, ma, lower

# ---------- strategy definitions ----------
@dataclass
class Entry:
    setup_idx: int
    confirm_idx: int
    setup_close: float
    entry_price: float
    ts_setup: pd.Timestamp
    ts_entry: pd.Timestamp

@dataclass
class TradeResult:
    symbol: str
    ts_entry: pd.Timestamp
    entry_price: float
    stop_price: float
    target_price: float
    exit_price: float
    ts_exit: pd.Timestamp
    outcome: str  # 'TP' or 'SL' or 'TIME'
    points: float
    lots: int
    lot_size: int
    qty: int
    delta_factor: float
    pnl_money: float
    hold_bars: int

def find_entries(df: pd.DataFrame, rsi_oversold: float, confirm_bars: int) -> List[Entry]:
    close = df["close"]
    r = rsi(close, 14)
    _, _, hist = macd(close)
    _, _, lower = boll_bands(close)

    setup_mask = (r <= rsi_oversold) & (close <= lower)
    entries: List[Entry] = []
    n = len(df)

    i = 0
    while i < n:
        if setup_mask.iat[i]:
            # look forward up to confirm_bars for MACD hist cross above 0
            j_end = min(n - 1, i + confirm_bars)
            confirmed = None
            for j in range(i + 1, j_end + 1):
                if hist.iat[j - 1] <= 0 and hist.iat[j] > 0:
                    confirmed = j
                    break
            if confirmed is not None:
                entries.append(Entry(
                    setup_idx=i,
                    confirm_idx=confirmed,
                    setup_close=float(close.iat[i]),
                    entry_price=float(close.iat[confirmed]),
                    ts_setup=df.index[i],
                    ts_entry=df.index[confirmed],
                ))
                i = confirmed + 1
                continue
        i += 1
    return entries

def backtest(
    symbol: str,
    df: pd.DataFrame,
    entries: List[Entry],
    sl_pts: float,
    tp_pts: Optional[float],
    lot_size: int,
    capital: float,
    risk_pct: float,
    delta_factor: float,
    max_hold_bars: int,
) -> List[TradeResult]:

    high = df["high"].values
    low  = df["low"].values
    idx = df.index

    trades: List[TradeResult] = []

    # position sizing (per trade): risk per unit = sl_pts * delta_factor
    # qty = floor( (capital * risk_pct) / (sl_pts*delta_factor) / lot_size ) * lot_size
    risk_budget = capital * risk_pct
    per_unit_risk = sl_pts * max(delta_factor, 1e-9)

    for e in entries:
        lots = int(floor(risk_budget / (per_unit_risk * lot_size)))
        if lots < 1:
            lots = 1  # force 1 lot for testing
        qty = lots * lot_size

        entry_idx = e.confirm_idx
        if entry_idx >= len(df) - 1:
            continue  # nothing to simulate after entry

        entry_price = e.entry_price
        stop_price = entry_price - sl_pts
        target_pts = tp_pts if (tp_pts and tp_pts > 0) else sl_pts * 1.5
        target_price = entry_price + target_pts

        # walk forward bar-by-bar
        k = entry_idx + 1
        exit_idx = None
        outcome = None
        reached_points = 0.0

        while k < len(df) and (k - entry_idx) <= max_hold_bars:
            bar_low = low[k]
            bar_high = high[k]

            # If both hit in same bar, choose SL first (conservative)
            hit_sl = bar_low <= stop_price
            hit_tp = bar_high >= target_price

            if hit_sl and hit_tp:
                exit_idx = k
                outcome = "SL"
                reached_points = -sl_pts
                break
            elif hit_sl:
                exit_idx = k
                outcome = "SL"
                reached_points = -sl_pts
                break
            elif hit_tp:
                exit_idx = k
                outcome = "TP"
                reached_points = target_pts
                break

            k += 1

        if exit_idx is None:
            # time exit at last checked bar
            exit_idx = min(len(df) - 1, entry_idx + max_hold_bars)
            # mark-to-market points (didn’t hit targets)
            last_close = float(df["close"].iat[exit_idx])
            reached_points = last_close - entry_price
            outcome = "TIME"

        exit_price = float(df["close"].iat[exit_idx])
        pnl_money = reached_points * qty * delta_factor

        trades.append(TradeResult(
            symbol=symbol,
            ts_entry=idx[entry_idx],
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            exit_price=exit_price,
            ts_exit=idx[exit_idx],
            outcome=outcome,
            points=reached_points,
            lots=lots,
            lot_size=lot_size,
            qty=qty,
            delta_factor=delta_factor,
            pnl_money=pnl_money,
            hold_bars=(exit_idx - entry_idx),
        ))

    return trades

def summarize(trades: List[TradeResult]) -> str:
    wins = sum(1 for t in trades if t.outcome == "TP")
    losses = sum(1 for t in trades if t.outcome == "SL")
    timeouts = sum(1 for t in trades if t.outcome == "TIME")
    total = len(trades)
    win_rate = (wins / total * 100.0) if total else 0.0
    total_r_points = sum(t.points / max(1e-9, abs(t.points) if t.points != 0 else 1) for t in trades)  # not super meaningful; we’ll just show money
    total_money = sum(t.pnl_money for t in trades)
    return (f"Trades: {total} | Wins: {wins}  Losses: {losses}  Time exits: {timeouts}\n"
            f"Win rate: {win_rate:.1f}%  Total PnL (money): {total_money:,.2f}")

def main():
    ap = argparse.ArgumentParser(description="Sequential backtest with point-based stops/targets & custom lot sizes")
    ap.add_argument("--data", required=True, help="CSV with columns: timestamp,open,high,low,close,volume")
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--rsi-oversold", type=float, default=50.0)
    ap.add_argument("--confirm-bars", type=int, default=5)
    ap.add_argument("--sl-pts", type=float, required=True, help="Stop in *points* (underlying approximation of premium)")
    ap.add_argument("--tp1-pts", type=float, default=0.0, help="Take-profit in *points*. If 0, uses 1.5×SL as target")
    ap.add_argument("--tp2-pts", type=float, default=0.0, help="(Reserved) ignored for now; single target backtest")
    ap.add_argument("--lot-size", type=int, required=True, help="Contract lot size to use for qty calc")
    ap.add_argument("--capital", type=float, default=30000.0)
    ap.add_argument("--risk-pct", type=float, default=0.02)
    ap.add_argument("--delta-factor", type=float, default=1.0, help="Premium response factor (0.35–0.5 common); 1.0 = 1:1")
    ap.add_argument("--max-hold-bars", type=int, default=20, help="Time-based exit if neither SL/TP hit")
    ap.add_argument("--out-trades", required=True)
    args = ap.parse_args()

    df = pd.read_csv(args.data)
    # robust timestamp parse
    if "timestamp" not in df.columns:
        raise SystemExit("CSV must have a 'timestamp' column")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.sort_values("timestamp").set_index("timestamp")
    req = ["open","high","low","close"]
    for c in req:
        if c not in df.columns:
            raise SystemExit(f"CSV missing column: {c}")

    entries = find_entries(df, rsi_oversold=args.rsi_oversold, confirm_bars=args.confirm_bars)
    trades = backtest(
        symbol=args.symbol,
        df=df,
        entries=entries,
        sl_pts=args.sl_pts,
        tp_pts=(args.tp1_pts if args.tp1_pts > 0 else None),
        lot_size=args.lot_size,
        capital=args.capital,
        risk_pct=args.risk_pct,
        delta_factor=args.delta_factor,
        max_hold_bars=args.max_hold_bars,
    )

    # save
    out_cols = [
        "symbol","ts_entry","entry_price","stop_price","target_price","ts_exit","exit_price",
        "outcome","points","lots","lot_size","qty","delta_factor","pnl_money","hold_bars"
    ]
    out_df = pd.DataFrame([t.__dict__ for t in trades], columns=out_cols)
    out_df.to_csv(args.out_trades, index=False)

    print(f"Saved -> {args.out_trades}")
    print(summarize(trades))

if __name__ == "__main__":
    main()
