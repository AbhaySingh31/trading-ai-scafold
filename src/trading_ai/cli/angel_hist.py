# -*- coding: utf-8 -*-
"""
Fetch Angel One historical candles for a symbol/token and write CSV with IST timestamps.

Usage (either pass --token or put <SYMBOL>_TOKEN in .env):
  python -m src.trading_ai.cli.angel_hist ^
    --use-env ^
    --symbol NIFTY --interval 1m ^
    --from 25-08-2025 --to 29-08-2025 ^
    --out data/NIFTY_1m_25082025_29082025.csv

.env keys (examples):
  ANGEL_API_KEY=...
  ANGEL_CLIENT_CODE=...
  ANGEL_MPIN=...
  ANGEL_TOTP_SECRET=...
  NIFTY_TOKEN=99926000
  BANKNIFTY_TOKEN=99926009
"""
from __future__ import annotations

import argparse
import re
from datetime import date, datetime, timedelta
from typing import List, Any
import pandas as pd


# ---------- .env loader (supports inline "# comments") ----------
def load_env(path: str) -> dict:
    env = {}
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            # strip inline comments after '#'
            v = re.split(r"\s+#", v, maxsplit=1)[0].strip()
            env[k.strip()] = v
    return env


# ---------- interval mapping ----------
def to_api_interval(s: str) -> str:
    x = (s or "").strip().lower()
    mp = {
        "1m": "ONE_MINUTE",
        "one_minute": "ONE_MINUTE",
        "5m": "FIVE_MINUTE",
        "five_minute": "FIVE_MINUTE",
        "15m": "FIFTEEN_MINUTE",
        "30m": "THIRTY_MINUTE",
        "60m": "ONE_HOUR",
        "1h": "ONE_HOUR",
        "day": "ONE_DAY",
        "1d": "ONE_DAY",
    }
    return mp.get(x, "ONE_MINUTE")


# ---------- parse Angel candle timestamp to IST ----------
def to_ist(ts: Any) -> pd.Timestamp:
    # Angel often returns ISO8601 with +05:30. Parse to UTC then convert to IST.
    t = pd.to_datetime(ts, errors="coerce", utc=True)
    # if parse returned NaT, try as naive IST
    if pd.isna(t):
        t = pd.to_datetime(ts, errors="coerce").tz_localize("Asia/Kolkata")
    else:
        t = t.tz_convert("Asia/Kolkata")
    return t


# ---------- fetch one trading day's candles ----------
def fetch_day(sc, token: str, api_interval: str, d: date) -> List[list]:
    # Angel expects "YYYY-MM-DD HH:MM" (no timezone info)
    from_str = f"{d:%Y-%m-%d} 09:15"
    to_str = f"{d:%Y-%m-%d} 15:30"
    req = {
        "exchange": "NSE",
        "symboltoken": token,
        "interval": api_interval,
        "fromdate": from_str,
        "todate": to_str,
    }
    data = sc.getCandleData(req)

    if not data or not data.get("status"):
        print(f"[warn] getCandleData failed: {data}")
        return []

    # Expected: {"status":True,"message":"SUCCESS","data":{"candles":[[ts,o,h,l,c,v],...]}}
    payload = data.get("data")
    if isinstance(payload, dict):
        arr = payload.get("candles") or []
    elif isinstance(payload, list):
        arr = payload
    else:
        arr = []

    if not arr:
        print(f"[warn] getCandleData empty for {d}: {data.get('message','SUCCESS')}")
        return []

    out = []
    for row in arr:
        # row should be [ts, open, high, low, close, volume]
        ist = to_ist(row[0])
        out.append([ist, row[1], row[2], row[3], row[4], row[5]])
    return out


def main():
    ap = argparse.ArgumentParser(description="Angel One historical candle fetcher (CSV in IST).")
    ap.add_argument("--use-env", action="store_true", help="Read login creds and tokens from .env")
    ap.add_argument("--env-path", default=".env")
    ap.add_argument("--symbol", required=True, help="Friendly symbol (e.g., NIFTY or BANKNIFTY)")
    ap.add_argument("--token", help="Angel symbol token (e.g., 99926000). If omitted, reads <SYMBOL>_TOKEN from .env")
    ap.add_argument("--interval", required=True, help="1m / 5m / 15m / 30m / 60m / 1d")
    ap.add_argument("--from", dest="dfrom", required=True, help="dd-mm-yyyy")
    ap.add_argument("--to", dest="dto", required=True, help="dd-mm-yyyy")
    ap.add_argument("--out", required=True, help="CSV output path")
    # Optional direct creds (if not using --use-env)
    ap.add_argument("--api-key")
    ap.add_argument("--client-code")
    ap.add_argument("--mpin")
    ap.add_argument("--totp-secret")
    ap.add_argument("--otp")
    args = ap.parse_args()

    env = load_env(args.env_path) if args.use_env else {}

    api_key = args.api_key or env.get("ANGEL_API_KEY", "")
    client = args.client_code or env.get("ANGEL_CLIENT_CODE", "")
    mpin = args.mpin or env.get("ANGEL_MPIN", "")
    totp_secret = args.totp_secret or env.get("ANGEL_TOTP_SECRET")
    otp = args.otp
    if not otp and totp_secret:
        try:
            import pyotp
            otp = pyotp.TOTP(totp_secret).now()
        except Exception as e:
            raise SystemExit(f"TOTP error: {e}")

    if not api_key or not client or not mpin or not (otp or totp_secret):
        raise SystemExit("Missing api/client/mpin/totp (or otp). Tip: use --use-env with a filled .env")

    # token: from arg OR from .env <SYMBOL>_TOKEN (e.g. NIFTY_TOKEN)
    token = args.token
    if not token and env:
        token_key = f"{args.symbol.upper()}_TOKEN"
        token = env.get(token_key)
    if not token:
        raise SystemExit(f"--token missing and {args.symbol.upper()}_TOKEN not found in .env")

    api_interval = to_api_interval(args.interval)
    print(f"[info] API interval = {api_interval} for '{args.interval}'")

    from SmartApi import SmartConnect
    sc = SmartConnect(api_key=api_key)
    login = sc.generateSession(client, mpin, otp)
    if not login or not login.get("status"):
        raise SystemExit(f"Login failed: {login}")

    start = datetime.strptime(args.dfrom, "%d-%m-%Y").date()
    end = datetime.strptime(args.dto, "%d-%m-%Y").date()

    rows: List[list] = []
    d = start
    while d <= end:
        rows.extend(fetch_day(sc, token, api_interval, d))
        d += timedelta(days=1)

    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    if not df.empty:
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.sort_values("timestamp")
    df.to_csv(args.out, index=False)
    print(f"[ok] {len(df)} rows -> {args.out}")


if __name__ == "__main__":
    main()
