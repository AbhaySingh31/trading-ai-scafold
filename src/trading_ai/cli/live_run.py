
from __future__ import annotations
import argparse, time, json
from datetime import datetime, timezone
import pandas as pd

from ..live.aggregate import BarAggregator
from ..live.connector_angel import AngelOneConnector, AngelConfig
from ..indicators.core import add_rsi, add_macd, add_emas, add_bbands, add_atr, add_vwap
from ..rules.filters import detect_setups, TriggerConfig, compute_volume_multiple
from ..risk.instruments import resolve_preset
from ..risk.tick import round_to_tick
from ..llm.interface import LLMClient

def agg_to_df(candles):
    rows = []
    for c in candles:
        rows.append({
            "timestamp": c.ts.isoformat(),
            "open": c.o, "high": c.h, "low": c.l, "close": c.c, "volume": c.v
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df

def main():
    ap = argparse.ArgumentParser(description="Live 30s loop (Angel One): WS -> 5m -> signal -> print/log")
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--client-code", required=True)
    ap.add_argument("--jwt-token", required=True)
    ap.add_argument("--feed-token", required=True)
    ap.add_argument("--instruments", required=True,
                    help="JSON map of symbols to {exchangeType, token}, e.g. '{"NIFTY":{"exchangeType":1,"token":"26000"}}'")
    ap.add_argument("--symbols", default="NIFTY,BANKNIFTY")
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--timeframe", default="5m")
    ap.add_argument("--use-presets", action="store_true")
    ap.add_argument("--volume-multiple", type=float, default=1.5)
    ap.add_argument("--rsi-oversold", type=float, default=30.0)
    ap.add_argument("--cooldown", type=int, default=10)
    ap.add_argument("--tick-size", type=float, default=0.05)
    ap.add_argument("--tick-round", default="nearest", choices=["nearest","up","down"])
    ap.add_argument("--capital", type=float, default=1_000_000.0)
    ap.add_argument("--risk-pct", type=float, default=0.005)
    ap.add_argument("--out-trades", default="out/trades_live.csv")
    args = ap.parse_args()

    try:
        instruments = json.loads(args.instruments)
    except Exception as e:
        raise SystemExit(f"--instruments JSON parse error: {e}")

    agg = BarAggregator(5)

    def on_tick(sym, price, ts):
        agg.on_tick(sym, price, ts)

    cfg = AngelConfig(api_key=args.api_key, client_code=args.client_code,
                      jwt_token=args.jwt_token, feed_token=args.feed_token,
                      instruments=instruments)
    conn = AngelOneConnector(cfg, on_tick)
    conn.start()

    llm = LLMClient()

    print("[live] started (Angel One). Waiting for 5m bar closes...")
    while True:
        time.sleep(args.interval)
        for sym in args.symbols.split(","):
            closed = agg.try_close_5m(sym)
            if not closed:
                continue
            bars = agg.last_n_5m(sym, n=200)
            df = agg_to_df(bars)
            df["symbol"] = sym; df["timeframe"] = args.timeframe

            for f in (add_rsi, add_macd, add_emas, add_bbands, add_atr, add_vwap):
                df = f(df)

            cfg_trig = TriggerConfig(rsi_oversold=float(args.rsi_oversold),
                                     volume_multiple=float(args.volume_multiple),
                                     cooldown_bars=int(args.cooldown))
            df["vol_mult_src"] = df["volume"]
            df["vol_mult"] = compute_volume_multiple(df["vol_mult_src"])

            signals = detect_setups(df, cfg_trig)
            if not signals:
                print(f"[live][{sym}] {closed.ts.isoformat()} no-signal")
                continue

            s = signals[-1]
            d = llm.decide(s)

            entry = float(d["entry"]); sl = float(d["stop_loss"]); t1 = float(d["targets"][0]); t2 = float(d["targets"][1])
            if args.tick_size and args.tick_size > 0:
                entry = round_to_tick(entry, args.tick_size, args.tick_round)
                sl    = round_to_tick(sl,    args.tick_size, args.tick_round)
                t1    = round_to_tick(t1,    args.tick_size, args.tick_round)
                t2    = round_to_tick(t2,    args.tick_size, args.tick_round)

            print(f"[plan][{sym}] {s['timestamp']} {d['action']} entry={entry} SL={sl} T1={t1} T2={t2} note={d['notes']}")
            from ..journal.io import append_rows_csv
            row = {"timestamp": s["timestamp"], "symbol": sym, "timeframe": args.timeframe,
                   "action": d["action"], "entry": entry, "stop_loss": sl, "t1": t1, "t2": t2}
            append_rows_csv(args.out_trades, [row], header=list(row.keys()))

if __name__ == "__main__":
    main()
