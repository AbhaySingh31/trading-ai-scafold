# scripts/quick_diag.py
import argparse
import pandas as pd
import numpy as np

def ema(s, span):
    return s.ewm(span=span, adjust=False).mean()

def rsi_wilder(close, period=14):
    delta = close.diff()
    up = np.where(delta > 0, delta, 0.0)
    dn = np.where(delta < 0, -delta, 0.0)
    up = pd.Series(up, index=close.index)
    dn = pd.Series(dn, index=close.index)
    roll_up = up.ewm(alpha=1/period, adjust=False).mean()
    roll_dn = dn.ewm(alpha=1/period, adjust=False).mean()
    rs = roll_up / roll_dn
    rsi = 100 - (100 / (1 + rs))
    return rsi

def macd(close, fast=12, slow=26, signal=9):
    macd_line = ema(close, fast) - ema(close, slow)
    sig = ema(macd_line, signal)
    hist = macd_line - sig
    return macd_line, sig, hist

def bbands(close, period=20, mult=2.0):
    ma = close.rolling(period).mean()
    sd = close.rolling(period).std()
    upper = ma + mult * sd
    lower = ma - mult * sd
    return ma, upper, lower

def main():
    ap = argparse.ArgumentParser("Quick diag: count candidate bars in a CSV")
    ap.add_argument("--data", required=True, help="Path to CSV with columns: timestamp,open,high,low,close,volume")
    ap.add_argument("--symbol", default="SYMBOL")
    ap.add_argument("--rsi-oversold", type=float, default=45.0)
    ap.add_argument("--out", default=None, help="Optional CSV of candidate bars")
    args = ap.parse_args()

    df = pd.read_csv(args.data)
    # robust timestamp parse; Angel hist gives ISO with +05:30
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.sort_values("timestamp").reset_index(drop=True)

    # sanity
    n = len(df)
    vol_zero_pct = float((df["volume"] == 0).sum()) / n * 100.0
    first_ts = df["timestamp"].iloc[0]
    last_ts = df["timestamp"].iloc[-1]

    # indicators
    close = df["close"].astype(float)
    df["rsi"] = rsi_wilder(close, 14)
    df["macd"], df["macd_signal"], df["macd_hist"] = macd(close)
    df["bb_ma"], df["bb_up"], df["bb_dn"] = bbands(close, 20, 2.0)

    # gates
    rsi_ok = df["rsi"] <= args.rsi_oversold
    macd_up = (df["macd"] > df["macd_signal"]) & (df["macd"].shift(1) <= df["macd_signal"].shift(1))
    bb_lower = df["close"] <= df["bb_dn"]

    all_ok = rsi_ok & macd_up & bb_lower

    print(f"=== {args.symbol} | file={args.data} ===")
    print(f"rows: {n}, first: {first_ts}, last: {last_ts}")
    print(f"volume==0: {vol_zero_pct:.1f}% of bars")
    print(f"RSI<= {args.rsi_oversold:.1f}: {int(rsi_ok.sum())}")
    print(f"MACD cross-up: {int(macd_up.sum())}")
    print(f"Close <= lower BB: {int(bb_lower.sum())}")
    print(f"ALL three aligned: {int(all_ok.sum())}")

    if args.out:
        cand = df.loc[all_ok, ["timestamp","open","high","low","close","volume","rsi","macd","macd_signal","bb_dn","bb_ma","bb_up"]]
        cand.to_csv(args.out, index=False)
        print(f"Saved candidates -> {args.out}")

if __name__ == "__main__":
    main()
