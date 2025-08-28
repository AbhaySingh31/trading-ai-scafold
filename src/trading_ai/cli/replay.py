from __future__ import annotations
import argparse
from pathlib import Path
from typing import List, Dict, Any
import pandas as pd

from ..data.loader import read_candles_csv, enforce_market_hours
from ..indicators.core import add_rsi, add_macd, add_emas, add_bbands, add_atr, add_vwap
from ..rules.filters import detect_setups, TriggerConfig, compute_volume_multiple, explain_bar
from ..journal.io import append_rows_csv
from ..risk.sizing import compute_size
from ..risk.instruments import resolve_preset, print_preset_banner
from ..risk.tick import round_to_tick
from ..llm.interface import LLMClient
from ..backtest.sim import simulate_trades


def _tick_decimals(tick: float) -> int:
    """Infer how many decimals to show for a given tick (e.g., 0.05 -> 2)."""
    s = f"{tick:.10f}".rstrip("0").rstrip(".")
    if "." in s:
        return len(s.split(".")[1])
    return 0


def _is_on_tick(x: float, tick: float, eps: float = 1e-9) -> bool:
    """True if x is within eps of a multiple of tick (handles float noise)."""
    if not tick or tick <= 0:
        return True
    k = round(x / tick)
    return abs(x - k * tick) < eps


def _maybe_overwrite(paths: list[str], enabled: bool) -> None:
    if not enabled:
        return
    for p in paths:
        try:
            Path(p).unlink(missing_ok=True)
        except Exception:
            pass


def run(args: argparse.Namespace) -> None:
    _maybe_overwrite([args.signals_out, args.trades_out], args.overwrite)

    df = read_candles_csv(args.data)
    df["symbol"] = args.symbol
    df["timeframe"] = args.timeframe

    # NSE intraday session filter
    df = enforce_market_hours(df)

    # Indicators
    for f in (add_rsi, add_macd, add_emas, add_bbands, add_atr, add_vwap):
        df = f(df)

    # Triggers config
    cfg = TriggerConfig(
        rsi_oversold=float(args.rsi_oversold),
        volume_multiple=float(args.volume_multiple),
        cooldown_bars=int(args.cooldown),
    )

    # --- Instrument presets (optional) ---
    if getattr(args, "use_presets", False):
        preset = resolve_preset(args.symbol)
        if preset:
            # override only if left at defaults
            if args.round_to == 1:
                args.round_to = int(preset["round_to"])
            if args.min_qty == 1:
                args.min_qty = int(preset["min_qty"])
            if abs(args.point_value - 1.0) < 1e-9:
                args.point_value = float(preset["point_value"])
            # tick params: only set if user left disabled (0 / None)
            if (getattr(args, "tick_size", 0.0) or 0.0) <= 0.0 and "tick_size" in preset:
                args.tick_size = float(preset["tick_size"])
            if (getattr(args, "tick_round", None) in (None, "")) and "tick_round" in preset:
                args.tick_round = str(preset["tick_round"])
            print_preset_banner(args.symbol, preset, args)

    # Precompute volume multiple for diagnostics/filters
    df["vol_mult"] = compute_volume_multiple(df["volume"])

    # Optional diagnostics CSV
    if args.why_csv:
        import csv
        Path(args.why_csv).parent.mkdir(parents=True, exist_ok=True)
        with open(args.why_csv, "w", newline="", encoding="utf-8") as f:
            fields = [
                "timestamp",
                "symbol",
                "timeframe",
                "rsi_ok",
                "macd_ok",
                "vol_ok",
                "above_bb",
                "cooldown_blocked",
                "trigger",
                "note",
            ]
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            last_signal_idx = -10**9
            for i in range(len(df)):
                row = df.iloc[i]
                warmup_missing = any(
                    pd.isna(row.get(k))
                    for k in ["rsi", "macd", "macd_signal", "ema_fast", "ema_slow", "bb_up", "bb_dn", "atr"]
                )
                cooldown_blocked = (i - last_signal_idx) < cfg.cooldown_bars
                exp = {"cooldown_blocked": bool(cooldown_blocked), **explain_bar(row, df["vol_mult"].iat[i], cfg)}
                w.writerow(
                    {
                        "timestamp": row["timestamp"],
                        "symbol": row.get("symbol", ""),
                        "timeframe": row.get("timeframe", ""),
                        "rsi_ok": exp["rsi_ok"] if not warmup_missing else False,
                        "macd_ok": exp["macd_ok"] if not warmup_missing else False,
                        "vol_ok": exp["vol_ok"] if not warmup_missing else False,
                        "above_bb": exp["above_bb"] if not warmup_missing else False,
                        "cooldown_blocked": exp["cooldown_blocked"],
                        "trigger": "" if warmup_missing else exp["trigger"],
                        "note": "warm-up" if warmup_missing else exp["note"],
                    }
                )
                if not warmup_missing and exp["trigger"]:
                    last_signal_idx = i

    # Detect setups -> signals rows
    signals = detect_setups(df, cfg)

    # Optional indicators dump
    if args.dump_indicators:
        dump_cols = [
            "timestamp",
            "symbol",
            "timeframe",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "rsi",
            "macd",
            "macd_signal",
            "ema_fast",
            "ema_slow",
            "bb_up",
            "bb_dn",
            "bb_mid",
            "bb_pos",
            "atr",
            "vwap",
            "vol_mult",
        ]
        df.to_csv(args.dump_indicators, index=False, columns=[c for c in dump_cols if c in df.columns])

    # Write signals
    append_rows_csv(
        args.signals_out,
        signals,
        header=[
            "timestamp",
            "symbol",
            "timeframe",
            "price",
            "rsi",
            "macd_state",
            "ema20_vs_ema50",
            "bands_position",
            "volume_multiple",
            "atr",
            "context",
            "key_levels",
        ],
    )

    # LLM stub -> trades + sizing + tick rounding
    llm = LLMClient()
    trades: List[Dict[str, Any]] = []
    for s in signals:
        d = llm.decide(s)

        # Tick rounding (only if a positive tick size is provided)
        if args.tick_size and args.tick_size > 0:
            entry = round_to_tick(float(d["entry"]), args.tick_size, args.tick_round)
            sl = round_to_tick(float(d["stop_loss"]), args.tick_size, args.tick_round)
            t1 = round_to_tick(float(d["targets"][0]), args.tick_size, args.tick_round)
            t2 = round_to_tick(float(d["targets"][1]), args.tick_size, args.tick_round)
        else:
            entry = float(d["entry"])
            sl = float(d["stop_loss"])
            t1 = float(d["targets"][0])
            t2 = float(d["targets"][1])

        qty, rpu_money, max_risk_money = compute_size(
            d["action"],
            entry,
            sl,
            capital=float(args.capital),
            risk_pct=float(args.risk_pct),
            point_value=float(args.point_value),
            min_qty=int(args.min_qty),
            round_to=int(args.round_to),
        )

        # pretty formatting for CSV (does not affect math)
        dec = _tick_decimals(args.tick_size) if (args.tick_size and args.tick_size > 0) else None
        if dec is not None:
            entry_fmt = float(f"{entry:.{dec}f}")
            sl_fmt = float(f"{sl:.{dec}f}")
            t1_fmt = float(f"{t1:.{dec}f}")
            t2_fmt = float(f"{t2:.{dec}f}")
        else:
            entry_fmt, sl_fmt, t1_fmt, t2_fmt = entry, sl, t1, t2

        # on-tick assertions (booleans) to make validation easy
        entry_on = _is_on_tick(entry, args.tick_size)
        stop_on = _is_on_tick(sl, args.tick_size)
        t1_on = _is_on_tick(t1, args.tick_size)
        t2_on = _is_on_tick(t2, args.tick_size)

        trades.append(
            {
                "timestamp": s["timestamp"],
                "symbol": s["symbol"],
                "timeframe": s["timeframe"],
                "action": d["action"],
                "entry": entry_fmt,       # formatted for neat CSV
                "stop_loss": sl_fmt,      # formatted
                "t1": t1_fmt,             # formatted
                "t2": t2_fmt,             # formatted
                "entry_on_tick": entry_on,
                "stop_on_tick": stop_on,
                "t1_on_tick": t1_on,
                "t2_on_tick": t2_on,
                "confidence": d["confidence"],
                "notes": d["notes"],
                "qty": int(qty),
                "risk_per_unit": round(rpu_money, 2),
                "max_risk": round(max_risk_money, 2),
                "point_value": float(args.point_value),
                "capital": float(args.capital),
                "risk_pct": float(args.risk_pct),
            }
        )

    # Simulated exits / write trades
    if args.simulate:
        trades = simulate_trades(df, trades)
        append_rows_csv(
            args.trades_out,
            trades,
            header=[
                "timestamp",
                "symbol",
                "timeframe",
                "action",
                "entry",
                "stop_loss",
                "t1",
                "t2",
                "entry_on_tick",
                "stop_on_tick",
                "t1_on_tick",
                "t2_on_tick",
                "confidence",
                "notes",
                "qty",
                "risk_per_unit",
                "max_risk",
                "point_value",
                "capital",
                "risk_pct",
                "entry_filled",
                "entry_time",
                "exit_price",
                "exit_time",
                "pnl",
                "R",
                "status",
                "pnl_money",
            ],
        )
    else:
        append_rows_csv(
            args.trades_out,
            trades,
            header=[
                "timestamp",
                "symbol",
                "timeframe",
                "action",
                "entry",
                "stop_loss",
                "t1",
                "t2",
                "entry_on_tick",
                "stop_on_tick",
                "t1_on_tick",
                "t2_on_tick",
                "confidence",
                "notes",
                "qty",
                "risk_per_unit",
                "max_risk",
                "point_value",
                "capital",
                "risk_pct",
            ],
        )

    print(f"Signals: {len(signals)} | Trades: {len(trades)}\nSaved -> {args.signals_out} , {args.trades_out}")


def main():
    p = argparse.ArgumentParser(description="Replay candles -> signals -> stub trades")
    p.add_argument("--data", required=True, help="CSV path with candles")
    p.add_argument("--symbol", required=True, help="Symbol (e.g., NIFTY, BANKNIFTY)")
    p.add_argument("--timeframe", required=True, help="Timeframe label for outputs (e.g., 5m)")

    p.add_argument("--signals-out", default="out/signals.csv", help="Path to write signals CSV")
    p.add_argument("--trades-out", default="out/trades.csv", help="Path to write trades CSV")

    p.add_argument("--rsi-oversold", default=30.0, type=float, help="RSI oversold threshold for mean-reversion")
    p.add_argument("--volume-multiple", default=1.5, type=float, help="Volume multiple vs 20-bar average")
    p.add_argument("--cooldown", default=10, type=int, help="Minimum bars between signals")
    p.add_argument("--dump-indicators", dest="dump_indicators", default=None, help="Write enriched indicators CSV")
    p.add_argument("--simulate", action="store_true", help="Simulate exits & P/L using simple OCO logic")
    p.add_argument("--overwrite", action="store_true", help="Delete signals/trades outputs before writing")
    p.add_argument("--why", dest="why_csv", default=None, help="Write per-bar diagnostics CSV")

    # Sizing
    p.add_argument("--capital", type=float, default=1000000.0, help="Account capital in money")
    p.add_argument("--risk-pct", type=float, default=0.005, help="Risk per trade as fraction (e.g., 0.005=0.5%)")
    p.add_argument("--point-value", type=float, default=1.0, help="Money per 1 price point (contract multiplier)")
    p.add_argument("--min-qty", type=int, default=1, help="Minimum quantity")
    p.add_argument("--round-to", type=int, default=1, help="Round quantity down to nearest multiple")

    # Presets
    p.add_argument("--use-presets", action="store_true", help="Apply instrument lot/point defaults based on --symbol")

    # Tick rounding
    p.add_argument("--tick-size", type=float, default=0.0, help="Price tick size (0 disables rounding)")
    p.add_argument("--tick-round", type=str, default="nearest", choices=["nearest", "up", "down"],
                   help="Tick rounding direction")

    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
