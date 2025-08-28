
from __future__ import annotations
import argparse
from ..data.loader import read_candles_csv
from ..risk.instruments import resolve_preset
from ..options.chooser import load_chain, pick_option_for_signal

def main():
    ap = argparse.ArgumentParser(description="Pick CE/PE, strike, and entry from spot + option chain CSV.")
    ap.add_argument("--data", required=True, help="CSV of candles (last close used as spot)")
    ap.add_argument("--chain", required=True, help="CSV of option chain snapshot")
    ap.add_argument("--symbol", required=True, help="Underlying symbol (e.g., NIFTY, BANKNIFTY)")
    ap.add_argument("--direction", required=True, choices=["BUY","SELL"], help="Direction from your signal")
    ap.add_argument("--mode", default="atm", choices=["atm","delta"], help="Strike selection mode")
    ap.add_argument("--delta", type=float, default=0.40, help="Target absolute delta when mode=delta")
    ap.add_argument("--sl-pct", type=float, default=0.25, help="Stop % below premium entry")
    ap.add_argument("--tp1-pct", type=float, default=0.50, help="TP1 % over premium entry")
    ap.add_argument("--tp2-pct", type=float, default=1.00, help="TP2 % over premium entry")
    ap.add_argument("--capital", type=float, default=1_000_000.0, help="Account capital")
    ap.add_argument("--risk-pct", type=float, default=0.005, help="Risk per trade fraction (0.005=0.5%)")
    args = ap.parse_args()

    df = read_candles_csv(args.data)
    if df.empty:
        raise SystemExit("[opts] Candle CSV is empty.")
    spot = float(df["close"].iloc[-1])

    preset = resolve_preset(args.symbol) or {}
    lot_size = int(preset.get("min_qty", 50))
    strike_step = int(preset.get("strike_step", 50))

    chain = load_chain(args.chain)

    pick = pick_option_for_signal(
        symbol=args.symbol,
        direction=args.direction,
        spot_price=spot,
        chain=chain,
        strike_step=strike_step,
        mode=args.mode,
        delta_target=args.delta,
        sl_pct=args.sl_pct,
        tp1_pct=args.tp1_pct,
        tp2_pct=args.tp2_pct,
        risk_capital=args.capital,
        risk_pct=args.risk_pct,
        lot_size=lot_size,
    )

    print(f"[{args.symbol}] spot={spot:.2f}  dir={args.direction}")
    print(f"{pick.side}  {args.symbol}  {pick.expiry}  strike={pick.strike:.0f}")
    print(f"ENTRY(limit): ₹{pick.entry:.2f}   SL: ₹{pick.stop:.2f}   TP1: ₹{pick.tp1:.2f}   TP2: ₹{pick.tp2:.2f}")
    print(f"SIZE: {pick.lots} lot(s)  (lot_size={pick.lot_size}, per-unit risk=₹{pick.premium_risk_per_unit:.2f})")
    print(f"notes: {pick.notes}")

if __name__ == "__main__":
    main()
