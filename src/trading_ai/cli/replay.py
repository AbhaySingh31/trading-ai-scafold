
from __future__ import annotations
import argparse
import pandas as pd
from pathlib import Path
from typing import List, Dict, Any
from ..data.loader import read_candles_csv, enforce_market_hours
from ..indicators.core import add_rsi, add_macd, add_emas, add_bbands, add_atr, add_vwap
from ..rules.filters import detect_setups, TriggerConfig
from ..journal.io import append_rows_csv
from ..llm.interface import LLMClient

def run(args: argparse.Namespace) -> None:
    df = read_candles_csv(args.data)
    # annotate symbol/timeframe columns for downstream

    df["symbol"] = args.symbol

    df["timeframe"] = args.timeframe

    df = enforce_market_hours(df)

    # indicators

    for f in (add_rsi, add_macd, add_emas, add_bbands, add_atr, add_vwap):

        df = f(df)

    # detect setups

    cfg = TriggerConfig()

    signals = detect_setups(df, cfg)

    # write signals

    append_rows_csv(args.signals_out, signals, header=[

        "timestamp","symbol","timeframe","price","rsi","macd_state","ema20_vs_ema50","bands_position","volume_multiple","atr","context","key_levels"

    ])

    # LLM (stub) decisions -> simple trades log

    llm = LLMClient()

    trades: List[Dict[str, Any]] = []

    for s in signals:

        decision = llm.decide(s)

        trades.append({

            "timestamp": s["timestamp"],

            "symbol": s["symbol"],

            "timeframe": s["timeframe"],

            "action": decision["action"],

            "entry": decision["entry"],

            "stop_loss": decision["stop_loss"],

            "t1": decision["targets"][0],

            "t2": decision["targets"][1],

            "confidence": decision["confidence"],

            "notes": decision["notes"],

        })

    append_rows_csv(args.trades_out, trades, header=["timestamp","symbol","timeframe","action","entry","stop_loss","t1","t2","confidence","notes"])

    print(f"Signals: {len(signals)} | Trades: {len(trades)}\nSaved -> {args.signals_out} , {args.trades_out}")



def main():

    p = argparse.ArgumentParser(description="Replay candles -> signals -> stub trades")

    p.add_argument("--data", required=True, help="CSV path with candles")

    p.add_argument("--symbol", required=True)

    p.add_argument("--timeframe", required=True)

    p.add_argument("--signals-out", default="out/signals.csv")

    p.add_argument("--trades-out", default="out/trades.csv")

    args = p.parse_args()

    run(args)


if __name__ == "__main__":

    main()

