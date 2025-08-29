from __future__ import annotations
import argparse
from pathlib import Path
from typing import List, Dict, Any
import pandas as pd
from datetime import datetime
from ..data.loader import read_candles_csv, enforce_market_hours
from ..indicators.core import add_rsi, add_macd, add_emas, add_bbands, add_atr, add_vwap
from ..rules.filters import detect_setups, TriggerConfig, compute_volume_multiple
from ..journal.io import append_rows_csv
from ..risk.sizing import compute_size
from ..risk.instruments import resolve_preset, print_preset_banner
from ..risk.tick import round_to_tick
from ..llm.interface import LLMClient
from ..backtest.sim import simulate_trades

def floor_to_5m(ts: pd.Timestamp) -> pd.Timestamp:
    # both our CSVs are UTC ISO. Ensure tz-aware.
    t = pd.Timestamp(ts).tz_convert("UTC") if ts.tzinfo else pd.Timestamp(ts, tz="UTC")
    minute = (t.minute // 5) * 5
    return t.replace(minute=minute, second=0, microsecond=0)

def enrich(df: pd.DataFrame) -> pd.DataFrame:
    for f in (add_rsi, add_macd, add_emas, add_bbands, add_atr, add_vwap):
        df = f(df)
    return df

def run(args: argparse.Namespace) -> None:
    # Load data
    df_fast = read_candles_csv(args.data_fast)
    df_fast["symbol"] = args.symbol; df_fast["timeframe"] = args.timeframe_fast
    df_fast = enforce_market_hours(df_fast); df_fast = enrich(df_fast)

    df_slow = read_candles_csv(args.data_slow)
    df_slow["symbol"] = args.symbol; df_slow["timeframe"] = args.timeframe_slow
    df_slow = enforce_market_hours(df_slow); df_slow = enrich(df_slow)

    # Presets
    if args.use_presets:
        preset = resolve_preset(args.symbol)
        if preset:
            if args.round_to == 1: args.round_to = int(preset["round_to"])
            if args.min_qty == 1: args.min_qty = int(preset["min_qty"])
            if abs(args.point_value - 1.0) < 1e-9: args.point_value = float(preset["point_value"])
            if (args.tick_size or 0.0) <= 0.0 and "tick_size" in preset:
                args.tick_size = float(preset["tick_size"])
            if (not args.tick_round) and "tick_round" in preset:
                args.tick_round = str(preset["tick_round"])
            print_preset_banner(args.symbol, preset, args)

    # Volume multiples (indices may be 0 volume)
    df_fast["vol_mult"] = compute_volume_multiple(df_fast["volume"])
    df_slow["vol_mult"] = compute_volume_multiple(df_slow["volume"])

    # Triggers per TF
    cfg_fast = TriggerConfig(
        rsi_oversold=float(args.rsi_oversold),
        volume_multiple=float(args.volume_multiple_fast),
        cooldown_bars=int(args.cooldown),
    )
    cfg_slow = TriggerConfig(
        rsi_oversold=float(args.rsi_oversold),
        volume_multiple=float(args.volume_multiple_slow),
        cooldown_bars=int(args.cooldown),
    )

    sig_fast = detect_setups(df_fast, cfg_fast)  # list of dicts
    sig_slow = detect_setups(df_slow, cfg_slow)

    # Build slow whitelist by 5m-bucket timestamp
    slow_ok = set()
    for s in sig_slow:
        # floor to its own 5m bucket (works even if timeframe is already 5m)
        b = floor_to_5m(pd.Timestamp(s["timestamp"]))
        slow_ok.add(b)

    # Keep only fast signals whose 5m bucket is whitelisted
    signals = []
    for s in sig_fast:
        b = floor_to_5m(pd.Timestamp(s["timestamp"]))
        if b in slow_ok:
            signals.append(s)

    # Write signals CSV
    Path(args.out_signals).parent.mkdir(parents=True, exist_ok=True)
    append_rows_csv(
        args.out_signals, signals,
        header=["timestamp","symbol","timeframe","price","rsi","macd_state","ema20_vs_ema50","bands_position","volume_multiple","atr","context","key_levels"]
    )

    # Trades: LLM stub -> sizing -> tick rounding -> simulate
    llm = LLMClient()
    trades: List[Dict[str, Any]] = []
    for s in signals:
        d = llm.decide(s)
        entry = float(d["entry"]); sl = float(d["stop_loss"])
        t1 = float(d["targets"][0]); t2 = float(d["targets"][1])
        if args.tick_size and args.tick_size > 0:
            entry = round_to_tick(entry, args.tick_size, args.tick_round)
            sl    = round_to_tick(sl,    args.tick_size, args.tick_round)
            t1    = round_to_tick(t1,    args.tick_size, args.tick_round)
            t2    = round_to_tick(t2,    args.tick_size, args.tick_round)
        qty, rpu_money, max_risk_money = compute_size(
            d["action"], entry, sl,
            capital=float(args.capital), risk_pct=float(args.risk_pct),
            point_value=float(args.point_value), min_qty=int(args.min_qty), round_to=int(args.round_to)
        )
        trades.append({
            "timestamp": s["timestamp"], "symbol": s["symbol"], "timeframe": s["timeframe"],
            "action": d["action"], "entry": entry, "stop_loss": sl, "t1": t1, "t2": t2,
            "confidence": d["confidence"], "notes": d["notes"],
            "qty": int(qty), "risk_per_unit": round(rpu_money, 2), "max_risk": round(max_risk_money, 2),
            "point_value": float(args.point_value), "capital": float(args.capital), "risk_pct": float(args.risk_pct),
        })

    if args.simulate:
        # Simulate against the *fast* DF (higher resolution)
        trades = simulate_trades(df_fast, trades)
        append_rows_csv(args.out_trades, trades, header=[
            "timestamp","symbol","timeframe","action","entry","stop_loss","t1","t2",
            "confidence","notes","qty","risk_per_unit","max_risk","point_value","capital","risk_pct",
            "entry_filled","entry_time","exit_price","exit_time","pnl","R","status","pnl_money",
        ])
    else:
        append_rows_csv(args.out_trades, trades, header=[
            "timestamp","symbol","timeframe","action","entry","stop_loss","t1","t2",
            "confidence","notes","qty","risk_per_unit","max_risk","point_value","capital","risk_pct",
        ])

    print(f"MTF done. Signals={len(signals)} Trades={len(trades)}")
    print(f"Saved -> {args.out_signals} , {args.out_trades}")

def main():
    p = argparse.ArgumentParser(description="Multi-timeframe backtest: require 1m signal aligned with 5m context.")
    p.add_argument("--symbol", required=True)
    p.add_argument("--data-fast", required=True)
    p.add_argument("--data-slow", required=True)
    p.add_argument("--timeframe-fast", default="1m")
    p.add_argument("--timeframe-slow", default="5m")

    p.add_argument("--rsi-oversold", type=float, default=30.0)
    p.add_argument("--volume-multiple-fast", type=float, default=0.0)
    p.add_argument("--volume-multiple-slow", type=float, default=0.0)
    p.add_argument("--cooldown", type=int, default=10)

    p.add_argument("--simulate", action="store_true")
    p.add_argument("--use-presets", action="store_true")
    p.add_argument("--tick-size", type=float, default=0.0)
    p.add_argument("--tick-round", type=str, default="nearest", choices=["nearest","up","down"])

    p.add_argument("--capital", type=float, default=1000000.0)
    p.add_argument("--risk-pct", type=float, default=0.005)
    p.add_argument("--point-value", type=float, default=1.0)
    p.add_argument("--min-qty", type=int, default=1)
    p.add_argument("--round-to", type=int, default=1)

    p.add_argument("--out-signals", default="out/signals_mtf.csv")
    p.add_argument("--out-trades", default="out/trades_mtf.csv")

    args = p.parse_args()
    run(args)

if __name__ == "__main__":
    main()
