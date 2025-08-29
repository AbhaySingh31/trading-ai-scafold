# src/trading_ai/cli/angel_hist.py
from __future__ import annotations
import argparse, sys, os, re
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import List, Dict, Any, Optional

try:
    from SmartApi import SmartConnect  # Angel One SDK (smartapi-python)
except ImportError:
    print("Install Angel SmartAPI: pip install smartapi-python", file=sys.stderr)
    raise

try:
    import pyotp
except Exception:
    pyotp = None

IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")

# Angel index tokens (hist endpoint accepts these index tokens)
INDEX_TOKENS = {
    "NIFTY": "99926000",
    "BANKNIFTY": "99926009",
}

INTERVAL_MAP = {
    "1m":  "ONE_MINUTE",
    "3m":  "THREE_MINUTE",
    "5m":  "FIVE_MINUTE",
    "10m": "TEN_MINUTE",
    "15m": "FIFTEEN_MINUTE",
    "30m": "THIRTY_MINUTE",
    "60m": "ONE_HOUR",
    "day": "ONE_DAY",
}

def load_env(path: str) -> dict:
    """Read simple KEY=VALUE lines, ignore blank lines and lines starting with #.
    Also supports inline comments after the value like: VALUE   # note
    """
    m: dict[str, str] = {}
    if not os.path.exists(path):
        return m
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            s = raw.strip()
            if not s or s.startswith("#"):
                continue
            if "=" not in s:
                continue
            k, v = s.split("=", 1)
            k = k.strip()
            v = v.strip()
            # strip inline comment that follows whitespace + '#'
            if " #" in v or v.endswith("#"):
                v = re.split(r"\s+#", v, 1)[0].strip()
            # remove surrounding quotes if present
            if (len(v) >= 2) and ((v[0] == v[-1]) and v[0] in ("'", '"')):
                v = v[1:-1]
            m[k] = v
    return m


def env_get(env: dict, key: str, default: Optional[str] = None) -> Optional[str]:
    for cand in (key.upper(), f"ANGEL_{key.upper()}"):
        if cand in env and env[cand]:
            return env[cand]
    return default

@dataclass
class FetchArgs:
    api_key: str
    client_code: str
    mpin: str
    totp_secret: Optional[str]
    otp: Optional[str]
    symbol: str
    token: Optional[str]
    interval: str
    from_date: str
    to_date: str
    out: Optional[str]

def parse_ist(dmy: str) -> date:
    return datetime.strptime(dmy, "%d-%m-%Y").date()

def daterange(d0: date, d1: date):
    cur = d0
    while cur <= d1:
        yield cur
        cur += timedelta(days=1)

def fmt_out_path(symbol: str, interval: str, d0: date, d1: date) -> str:
    a = d0.strftime("%Y%m%d"); b = d1.strftime("%Y%m%d")
    return f"data/{symbol}_{interval}_{a}_{b}.csv"

def login(api_key: str, client_code: str, mpin: str, totp_secret: Optional[str], otp: Optional[str]) -> SmartConnect:
    if not otp:
        if not totp_secret:
            raise SystemExit("Provide --otp or --totp-secret")
        if pyotp is None:
            raise SystemExit("Install pyotp for TOTP: pip install pyotp")
        try:
            otp = pyotp.TOTP(totp_secret).now()
        except Exception as e:
            raise SystemExit(f"TOTP error: {e}")

    sc = SmartConnect(api_key=api_key)
    resp = sc.generateSession(client_code, mpin, otp)
    if not resp or not resp.get("status"):
        raise SystemExit(f"Login failed: {resp}")
    return sc

def parse_ts_any(s: Any) -> datetime:
    """
    Accepts:
      - 'YYYY-mm-dd HH:MM:SS'
      - 'YYYY-mm-dd HH:MM:SS.fff'
      - ISO-8601 'YYYY-mm-ddTHH:MM:SS' with or without timezone, e.g. '+05:30'
      - int/float epoch seconds or ms
    Returns tz-aware IST datetime.
    """
    if isinstance(s, (int, float)):
        # Guess ms vs sec
        if s > 1e12:
            dt = datetime.fromtimestamp(s / 1000.0, tz=IST)
        else:
            dt = datetime.fromtimestamp(s, tz=IST)
        return dt

    if not isinstance(s, str):
        raise ValueError(f"Unsupported timestamp type: {type(s)}")

    # Try ISO first (handles '+05:30', 'Z', etc.)
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)  # assume IST if no tz
        return dt.astimezone(IST)
    except Exception:
        pass

    # Try space format
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=IST)
        except Exception:
            continue

    # Last resort: strip trailing timezone if present like '+05:30'
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(?:\.\d+)?(?:[+-]\d{2}:\d{2})?$", s)
    if m:
        return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)

    raise ValueError(f"Unrecognized timestamp format: {s}")

def fetch_day(sc: SmartConnect, symboltoken: str, interval_key: str, day: date) -> List[List[Any]]:
    """Return a list of [ts, o, h, l, c, v] for the given day/interval."""
    if interval_key not in INTERVAL_MAP:
        raise SystemExit(f"Unsupported interval '{interval_key}'. Use one of {list(INTERVAL_MAP.keys())}")

    start_ist = datetime.combine(day, time(9, 15), IST)
    end_ist   = datetime.combine(day, time(15, 30), IST)

    payload = {
        "exchange": "NSE",
        "symboltoken": symboltoken,
        "interval": INTERVAL_MAP[interval_key],
        "fromdate": start_ist.strftime("%Y-%m-%d %H:%M"),
        "todate":   end_ist.strftime("%Y-%m-%d %H:%M"),
    }
    out = sc.getCandleData(payload)

    # Normalize Angel's variable shapes:
    # - dict: {"status":true,"data":{"candles":[...]}}
    # - dict: {"status":true,"data":[...]}
    # - dict: {"data":[...]}
    # - list: [...]
    raw = out
    candles: List[List[Any]] = []
    try:
        if isinstance(raw, list):
            candles = raw
        elif isinstance(raw, dict):
            data = raw.get("data", raw)
            if isinstance(data, list):
                candles = data
            elif isinstance(data, dict):
                candles = data.get("candles") or data.get("data") or []
            else:
                candles = []
        else:
            candles = []
    except Exception:
        candles = []

    if not candles:
        msg = raw.get("message") if isinstance(raw, dict) else str(type(raw))
        print(f"[warn] getCandleData empty for {day}: {msg}", file=sys.stderr)

    return candles

def write_csv(rows: List[Dict[str, Any]], out_path: str):
    from pathlib import Path
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    import csv
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["timestamp","open","high","low","close","volume"])
        for r in rows:
            w.writerow([r["timestamp"], r["open"], r["high"], r["low"], r["close"], r["volume"]])
    print(f"[ok] {len(rows)} rows -> {out_path}")

def main():
    ap = argparse.ArgumentParser(description="Fetch Angel One historical OHLC for NIFTY/BANKNIFTY in a date range.")
    ap.add_argument("--use-env", action="store_true", help="Read credentials/dates from .env")
    ap.add_argument("--env-path", default=".env")
    ap.add_argument("--api-key"); ap.add_argument("--client-code"); ap.add_argument("--mpin")
    ap.add_argument("--totp-secret"); ap.add_argument("--otp")
    ap.add_argument("--symbol", choices=["NIFTY","BANKNIFTY"])
    ap.add_argument("--token")
    ap.add_argument("--interval", default="5m", choices=list(INTERVAL_MAP.keys()))
    ap.add_argument("--from", dest="from_date")
    ap.add_argument("--to", dest="to_date")
    ap.add_argument("--out")
    args = ap.parse_args()

    env = load_env(args.env_path) if args.use_env else {}

    api_key = args.api_key or env_get(env, "api_key")
    client_code = args.client_code or env_get(env, "client_code")
    mpin = args.mpin or env_get(env, "mpin")
    totp_secret = args.totp_secret or env_get(env, "totp_secret")
    otp = args.otp

    symbol = args.symbol
    token = args.token
    interval = args.interval
    from_date = args.from_date or env.get("HIST_FROM")
    to_date   = args.to_date   or env.get("HIST_TO")

    if not (api_key and client_code and mpin and (totp_secret or otp)):
        raise SystemExit("Missing api/client/mpin/totp (or otp). Tip: use --use-env with a filled .env")
    if not (symbol and from_date and to_date):
        raise SystemExit("Missing symbol/from/to. Tip: set SYMBOLS, HIST_FROM, HIST_TO in .env or pass flags.")

    token = token or INDEX_TOKENS.get(symbol)
    if not token:
        raise SystemExit(f"No token known for {symbol}. Provide --token.")

    d0 = parse_ist(from_date); d1 = parse_ist(to_date)
    sc = login(api_key, client_code, mpin, totp_secret, otp)

    all_rows = []
    for day in daterange(d0, d1):
        for c in fetch_day(sc, token, interval, day):
            # c = [ ts, open, high, low, close, volume ]
            ts_local = parse_ts_any(c[0])      # tz-aware IST
            ts_utc = ts_local.astimezone(UTC)  # normalize to UTC for our pipeline

            # robust volume parsing
            vol = c[5] if len(c) > 5 else 0
            try:
                v = int(float(vol))
            except Exception:
                v = 0

            all_rows.append({
                "timestamp": ts_utc.isoformat().replace("+00:00", "Z"),
                "open": float(c[1]), "high": float(c[2]), "low": float(c[3]), "close": float(c[4]),
                "volume": v
            })

    out_path = args.out or fmt_out_path(symbol, interval, d0, d1)
    write_csv(all_rows, out_path)
    print(f"Next: {symbol} {interval} CSV ready -> {out_path}")

if __name__ == "__main__":
    main()
