# scripts/seq_diag.py
import argparse
import pandas as pd
import numpy as np

def ema(s, span): return s.ewm(span=span, adjust=False).mean()

def rsi_wilder(close, period=14):
    d = close.diff()
    up = pd.Series(np.where(d > 0, d, 0.0), index=close.index)
    dn = pd.Series(np.where(d < 0, -d, 0.0), index=close.index)
    roll_up = up.ewm(alpha=1/period, adjust=False).mean()
    roll_dn = dn.ewm(alpha=1/period, adjust=False).mean()
    rs = roll_up / roll_dn
    return 100 - (100 / (1 + rs))

def macd(close, fast=12, slow=26, signal=9):
    m = ema(close, fast) - ema(close, slow)
    s = ema(m, signal)
    return m, s, m - s

def bbands(close, period=20, mult=2.0):
    ma = close.rolling(period).mean()
    sd = close.rolling(period).std()
    return ma, ma + mult*sd, ma - mult*sd

def main():
    ap = argparse.ArgumentParser("Sequential diag: BB+RSI first, MACD confirms within K bars")
    ap.add_argument("--data", required=True)
    ap.add_argument("--symbol", default="SYMBOL")
    ap.add_argument("--rsi-oversold", type=float, default=45.0)
    ap.add_argument("--confirm-bars", type=int, default=3, help="MACD cross-up must happen within next K bars")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    df = pd.read_csv(args.data)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.sort_values("timestamp").reset_index(drop=True)

    close = df["close"].astype(float)
    df["rsi"] = rsi_wilder(close, 14)
    df["macd"], df["macd_signal"], df["macd_hist"] = macd(close)
    df["bb_ma"], df["bb_up"], df["bb_dn"] = bbands(close, 20, 2.0)

    # Setup bar = oversold & at/below lower band
    setup = (df["rsi"] <= args.rsi_oversold) & (df["close"] <= df["bb_dn"])

    # MACD cross-up definition
    cross_up = (df["macd"] > df["macd_signal"]) & (df["macd"].shift(1) <= df["macd_signal"].shift(1))

    hits = []
    K = args.confirm_bars
    idx = np.where(setup.values)[0]
    for i in idx:
        j0, j1 = i+1, min(i+K, len(df)-1)
        if j0 > j1: continue
        # did a cross-up occur in (i, i+K] ?
        win = np.any(cross_up.iloc[j0:j1+1].values)
        if win:
            j = j0 + np.argmax(cross_up.iloc[j0:j1+1].values)  # first confirm bar
            hits.append((i, j))

    print(f"=== {args.symbol} | {args.data} ===")
    print(f"Bars: {len(df)}  |  Setup bars (RSI<= {args.rsi_oversold}, Close<=LowerBB): {int(setup.sum())}")
    print(f"Confirms within {K} bars: {len(hits)}")
    if hits[:5]:
        print("First few:")
        for (i,j) in hits[:5]:
            print(f"  setup@{df['timestamp'][i]}  ->  confirm@{df['timestamp'][j]}  "
                  f"(setup close={df['close'][i]:.2f}, confirm close={df['close'][j]:.2f})")

    if args.out and hits:
        out = df.loc[[j for (_,j) in hits], ["timestamp","open","high","low","close","rsi","macd","macd_signal","bb_dn","bb_ma","bb_up"]]
        out.to_csv(args.out, index=False)
        print(f"Saved confirmed entries -> {args.out}")

if __name__ == "__main__":
    main()
