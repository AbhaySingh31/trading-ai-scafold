from __future__ import annotations
import argparse
from pathlib import Path
from typing import List, Dict, Any

import pandas as pd  # for diagnostics/warm-up checks

from ..data.loader import read_candles_csv, enforce_market_hours
from ..indicators.core import add_rsi, add_macd, add_emas, add_bbands, add_atr, add_vwap
from ..rules.filters import (
    detect_setups,
    TriggerConfig,
    compute_volume_multiple,
    explain_bar,  # diagnostics helper
)
from ..journal.io import append_rows_csv
from ..llm.interface import LLMClient
from ..backtest.sim import simulate_trades  # requires v0.3 backtest module


def _maybe_overwrite(paths: list[str], enabled: bool) -> None:
    if not enabled:
        return
    for p in paths:
        try:
            Path(p).unlink(missing_ok=True)  # Python 3.11+
        except Exception:
            pass


def run(args: argparse.Namespace) -> None:
    # Clean outputs if requested
    _maybe_overwrite([args.signals_out, args.trades_out], args.overwrite)

    # Load & annotate
    df = read_candles_csv(args.data)
    df["symbol"] = args.symbol
    df["timeframe"] = args.timeframe

    # Keep only market hours (IST 09:15–15:30)
    df = enforce_market_hours(df)

    # Compute indicators locally
    for f in (add_rsi, add_macd, add_emas, add_bbands, add_atr, add_vwap):
        df = f(df)

    # Configurable thresholds
    cfg = TriggerConfig(
        rsi_oversold=float(args.rsi_oversold),
        volume_multiple=float(args.volume_multiple),
        cooldown_bars=int(args.cooldown),
    )

    # For optional inspection
    df["vol_mult"] = compute_volume_multiple(df["volume"])

    # Optional diagnostics CSV (per-bar why a setup did/didn't pass)
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
            last_signal_idx = -10**9  # track hypothetical signals for cooldown visualization
            for i in range(len(df)):
                row = df.iloc[i]
                # warm-up == any required indicator is NaN
                warmup_missing = any(
                    pd.isna(row.get(k))
                    for k in [
                        "rsi",
                        "macd",
                        "macd_signal",
                        "ema_fast",
                        "ema_slow",
                        "bb_up",
                        "bb_dn",
                        "atr",
                    ]
                )
                cooldown_blocked = (i - last_signal_idx) < cfg.cooldown_bars
                exp = {
                    "cooldown_blocked": bool(cooldown_blocked),
                    **explain_bar(row, df["vol_mult"].iat[i], cfg),
                }
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
                # mark where a trigger would occur so cooldown shows up on subsequent rows
                if not warmup_missing and exp["trigger"]:
                    last_signal_idx = i

    # Detect setups
    signals = detect_setups(df, cfg)

    # Optional indicator dump for debugging
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
        df.to_csv(
            args.dump_indicators,
            index=False,
            columns=[c for c in dump_cols if c in df.columns],
        )

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

    # LLM stub -> trades
    llm = LLMClient()
    trades: List[Dict[str, Any]] = []
    for s in signals:
        d = llm.decide(s)
        trades.append(
            {
                "timestamp": s["timestamp"],
                "symbol": s["symbol"],
                "timeframe": s["timeframe"],
                "action": d["action"],
                "entry": d["entry"],
                "stop_loss": d["stop_loss"],
                "t1": d["targets"][0],
                "t2": d["targets"][1],
                "confidence": d["confidence"],
                "notes": d["notes"],
            }
        )

    # Optional simulation to compute exits & P/L
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
                "confidence",
                "notes",
                "entry_filled",
                "entry_time",
                "exit_price",
                "exit_time",
                "pnl",
                "R",
                "status",
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
                "confidence",
                "notes",
            ],
        )

    print(
        f"Signals: {len(signals)} | Trades: {len(trades)}\nSaved -> {args.signals_out} , {args.trades_out}"
    )


def main():
    p = argparse.ArgumentParser(description="Replay candles -> signals -> stub trades")
    p.add_argument("--data", required=True, help="CSV path with candles")
    p.add_argument("--symbol", required=True)
    p.add_argument("--timeframe", required=True)
    p.add_argument("--signals-out", default="out/signals.csv")
    p.add_argument("--trades-out", default="out/trades.csv")

    # Tunables & options
    p.add_argument("--rsi-oversold", default=30.0, type=float)
    p.add_argument("--volume-multiple", default=1.5, type=float)
    p.add_argument("--cooldown", default=10, type=int)
    p.add_argument("--dump-indicators", dest="dump_indicators", default=None)
    p.add_argument("--simulate", action="store_true", help="Simulate exits & P/L using simple OCO logic")
    p.add_argument("--overwrite", action="store_true", help="Delete signals/trades outputs before writing")
    p.add_argument("--why", dest="why_csv", default=None, help="Write per-bar diagnostics CSV")

    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
