# src/trading_ai/cli/live_run.py
from __future__ import annotations
"""
Angel One live runner:
- Subscribes to NIFTY/BANKNIFTY ticks via SmartAPI WS v2
- Aggregates ticks -> 5m bars
- On each 5m close: compute indicators, detect setups, get LLM decision
- (Optional) Pick ATM CE/PE for next weekly expiry and fetch live option premium
- Print a one-liner plan and append to CSV

Prereqs:
    pip install smartapi-python pyotp requests
Run:
    python -m src.trading_ai.cli.live_run \
      --api-key YOUR_API_KEY \
      --client-code YOUR_CLIENT_CODE \
      --jwt-token "<JWT_FROM_angel_login>" \
      --feed-token "<FEED_FROM_angel_login>" \
      --instruments '{"NIFTY":{"exchangeType":1,"token":"26000"},"BANKNIFTY":{"exchangeType":1,"token":"26009"}}' \
      --symbols NIFTY,BANKNIFTY \
      --interval 30 \
      --use-presets --tick-size 0.05 --risk-pct 0.005 \
      --opt-enable --opt-sl-pct 0.25 --opt-tp1-pct 0.5 --opt-tp2-pct 1.0
"""

import argparse
import json
import time
from datetime import datetime, timezone
from typing import List, Dict, Any

import pandas as pd

from ..live.aggregate import BarAggregator
from ..live.connector_angel import AngelOneConnector, AngelConfig
from ..indicators.core import add_rsi, add_macd, add_emas, add_bbands, add_atr, add_vwap
from ..rules.filters import detect_setups, TriggerConfig, compute_volume_multiple
from ..risk.tick import round_to_tick
from ..llm.interface import LLMClient
from ..journal.io import append_rows_csv

# Option helpers (Angel instrument master + quote)
from ..angel.opts import pick_atm_option, get_option_ltp, size_option_lots
from ..utils.expiry import next_thursday_ist


def _agg_to_df(candles) -> pd.DataFrame:
    """Convert a list of Candle objects -> DataFrame compatible with our indicators/rules."""
    rows: List[Dict[str, Any]] = []
    for c in candles:
        rows.append(
            {
                "timestamp": c.ts.isoformat(),
                "open": c.o,
                "high": c.h,
                "low": c.l,
                "close": c.c,
                "volume": c.v,  # tick-count proxy
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def main() -> None:
    DEFAULT_INSTRUMENTS = {
    "NIFTY": {"exchangeType": 1, "token": "26000"},
    "BANKNIFTY": {"exchangeType": 1, "token": "26009"},
    }

    ap = argparse.ArgumentParser(
        description="Live 30s loop (Angel One): WS -> 5m -> signal -> print/log (+ optional option premium)"
    )
    # ---- Angel session ----
    ap.add_argument("--api-key", required=True, help="Angel SmartAPI app key")
    ap.add_argument("--client-code", required=True, help="Angel client code (user id)")
    ap.add_argument("--jwt-token", required=True, help="JWT from login helper")
    ap.add_argument("--feed-token", required=True, help="Feed token from login helper")
    ap.add_argument(
    "--instruments",
    default=json.dumps(DEFAULT_INSTRUMENTS),
    help="JSON map of instruments (default = NIFTY/BANKNIFTY)"
    )
    # ---- Symbols / loop ----
    ap.add_argument("--symbols", default="NIFTY,BANKNIFTY", help="Comma list of underlyings to watch")
    ap.add_argument("--interval", type=int, default=30, help="Loop interval seconds (30 is fine)")
    ap.add_argument("--timeframe", default="5m", help="Label for outputs (kept as 5m)")

    # ---- Strategy knobs ----
    ap.add_argument("--use-presets", action="store_true", help="(kept for compatibility)")
    ap.add_argument("--volume-multiple", type=float, default=1.5, help="Volume multiple vs avg (tick-count proxy)")
    ap.add_argument("--rsi-oversold", type=float, default=30.0, help="RSI threshold used by rules (mean-rev leg)")
    ap.add_argument("--cooldown", type=int, default=10, help="Min bars between signals")

    # ---- Price rounding / risk budget (underlying) ----
    ap.add_argument("--tick-size", type=float, default=0.05, help="Underlying price tick size (0 disables)")
    ap.add_argument(
        "--tick-round",
        default="nearest",
        choices=["nearest", "up", "down"],
        help="Underlying tick rounding direction",
    )
    ap.add_argument("--capital", type=float, default=1_000_000.0, help="Account capital (money)")
    ap.add_argument("--risk-pct", type=float, default=0.005, help="Risk per trade fraction (0.005 = 0.5%)")

    # ---- Output ----
    ap.add_argument("--out-trades", default="out/trades_live.csv", help="CSV to append plans")

    # ---- Options (premium plan) ----
    ap.add_argument(
        "--opt-enable",
        action="store_true",
        help="Also pick ATM CE/PE and price it using live premium (Market Feeds quote)",
    )
    ap.add_argument("--opt-sl-pct", type=float, default=0.25, help="Option SL as % of entry premium (0.25 = 25%)")
    ap.add_argument("--opt-tp1-pct", type=float, default=0.50, help="Option TP1 as % of entry premium")
    ap.add_argument("--opt-tp2-pct", type=float, default=1.00, help="Option TP2 as % of entry premium")

    args = ap.parse_args()

    # Parse instruments JSON
    try:
        instruments = json.loads(args.instruments)
    except Exception as e:
        raise SystemExit(f"--instruments JSON parse error: {e}")

    # Set up aggregation and WS connector
    agg = BarAggregator(5)

    def on_tick(sym: str, price: float, ts) -> None:
        agg.on_tick(sym, price, ts)

    cfg = AngelConfig(
        api_key=args.api_key,
        client_code=args.client_code,
        jwt_token=args.jwt_token,
        feed_token=args.feed_token,
        instruments=instruments,
    )
    conn = AngelOneConnector(cfg, on_tick)
    conn.start()

    llm = LLLM = LLMClient()

    print("[live] started (Angel One). Waiting for 5m bar closes...")

    # Main loop
    while True:
        time.sleep(args.interval)

        for sym in [s.strip() for s in args.symbols.split(",") if s.strip()]:
            closed = agg.try_close_5m(sym)
            if not closed:
                # no newly closed 5m bar for this symbol
                continue

            # Collect recent bars and compute indicators
            bars = agg.last_n_5m(sym, n=200)
            df = _agg_to_df(bars)
            df["symbol"] = sym
            df["timeframe"] = args.timeframe

            for f in (add_rsi, add_macd, add_emas, add_bbands, add_atr, add_vwap):
                df = f(df)

            # Trigger config & volume proxy (tick-count)
            cfg_trig = TriggerConfig(
                rsi_oversold=float(args.rsi_oversold),
                volume_multiple=float(args.volume_multiple),
                cooldown_bars=int(args.cooldown),
            )
            df["vol_mult_src"] = df["volume"]
            df["vol_mult"] = compute_volume_multiple(df["vol_mult_src"])

            # Find signals on the full set, then act on the last (just-closed) bar if any
            signals = detect_setups(df, cfg_trig)
            if not signals:
                print(f"[live][{sym}] {closed.ts.isoformat()} no-signal")
                continue

            s = signals[-1]
            llm_decision = llm.decide(s)

            # Round underlying levels to tick (optional)
            entry = float(llm_decision["entry"])
            sl = float(llm_decision["stop_loss"])
            t1 = float(llm_decision["targets"][0])
            t2 = float(llm_decision["targets"][1])

            if args.tick_size and args.tick_size > 0:
                entry = round_to_tick(entry, args.tick_size, args.tick_round)
                sl = round_to_tick(sl, args.tick_size, args.tick_round)
                t1 = round_to_tick(t1, args.tick_size, args.tick_round)
                t2 = round_to_tick(t2, args.tick_size, args.tick_round)

            # Print underlying plan
            print(
                f"[plan][{sym}] {s['timestamp']} {llm_decision['action']} "
                f"entry={entry} SL={sl} T1={t1} T2={t2} note={llm_decision['notes']}"
            )

            # Log underlying plan
            try:
                row = {
                    "timestamp": s["timestamp"],
                    "symbol": sym,
                    "timeframe": args.timeframe,
                    "action": llm_decision["action"],
                    "entry": entry,
                    "stop_loss": sl,
                    "t1": t1,
                    "t2": t2,
                }
                append_rows_csv(args.out_trades, [row], header=list(row.keys()))
            except Exception:
                pass

            # ---- OPTIONAL: live option pick + premium plan ----
            if args.opt_enable:
                try:
                    # CE for BUY; PE for SELL (simple mapping)
                    ce_or_pe = "CE" if llm_decision["action"].upper() == "BUY" else "PE"

                    # Weekly expiry = next Thursday (IST)
                    exp_utc = next_thursday_ist(datetime.now(timezone.utc))

                    # Use the *closed* underlying price as ATM reference
                    spot = float(closed.c)

                    # Resolve ATM contract from Angel instrument master
                    oc = pick_atm_option(sym, spot, ce_or_pe, exp_utc)

                    # Live option premium (LTP) via Market Feeds 'quote' API
                    opt_entry = get_option_ltp(args.api_key, args.jwt_token, oc.tradingsymbol, oc.symboltoken)

                    # Premium SL/TPs (percent-based)
                    opt_sl = round(opt_entry * (1.0 - float(args.opt_sl_pct)), 2)
                    opt_t1 = round(opt_entry * (1.0 + float(args.opt_tp1_pct)), 2)
                    opt_t2 = round(opt_entry * (1.0 + float(args.opt_tp2_pct)), 2)

                    # Risk-based lot sizing
                    budget = float(args.capital) * float(args.risk_pct)
                    lots, per_lot_risk = size_option_lots(budget, opt_entry, opt_sl, oc.lotsize)

                    print(
                        f"[opt][{sym}] {oc.tradingsymbol} ({oc.expiry} {oc.strike:.0f}{ce_or_pe}) "
                        f"LTP={opt_entry:.2f} ENTRY={opt_entry:.2f} SL={opt_sl:.2f} "
                        f"TP1={opt_t1:.2f} TP2={opt_t2:.2f} lots={lots} lot_size={oc.lotsize} "
                        f"budget={budget:.0f} per_lot_risk≈{per_lot_risk:.0f}"
                    )

                    # Append option plan to CSV
                    try:
                        row_opt = {
                            "timestamp": s["timestamp"],
                            "symbol": sym,
                            "timeframe": args.timeframe,
                            "action": llm_decision["action"],
                            "underlying_entry": entry,
                            "underlying_sl": sl,
                            "opt_tradingsymbol": oc.tradingsymbol,
                            "opt_token": oc.symboltoken,
                            "opt_expiry": oc.expiry,
                            "opt_strike": oc.strike,
                            "opt_side": ce_or_pe,
                            "opt_lotsize": oc.lotsize,
                            "opt_entry": round(opt_entry, 2),
                            "opt_sl": opt_sl,
                            "opt_tp1": opt_t1,
                            "opt_tp2": opt_t2,
                            "opt_suggested_lots": lots,
                            "risk_budget": round(budget, 2),
                        }
                        append_rows_csv(args.out_trades, [row_opt], header=list(row_opt.keys()))
                    except Exception:
                        pass

                except Exception as e:
                    print(f"[opt][{sym}] option-pick failed: {e}")


if __name__ == "__main__":
    main()
