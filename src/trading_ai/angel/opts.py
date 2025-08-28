# src/trading_ai/angel/opts.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
import requests
import pandas as pd
import math

INSTRUMENT_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"

@dataclass
class OptContract:
    tradingsymbol: str
    symboltoken: str
    expiry: str
    strike: float
    lotsize: int

# ---- instrument master cache ----
_instr_df: Optional[pd.DataFrame] = None

def load_instrument_master(force: bool = False) -> pd.DataFrame:
    global _instr_df
    if _instr_df is not None and not force:
        return _instr_df
    j = requests.get(INSTRUMENT_URL, timeout=20).json()
    df = pd.DataFrame(j)
    # normalize
    df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce")
    df["strike"] = pd.to_numeric(df["strike"], errors="coerce") / 100.0  # Angel stores strike*100
    df["lotsize"] = pd.to_numeric(df["lotsize"], errors="coerce")
    _instr_df = df
    return df

def _nearest_strike(df: pd.DataFrame, target: float) -> float:
    # pick the available strike closest to target
    ix = (df["strike"] - target).abs().idxmin()
    return float(df.loc[ix, "strike"])

def pick_atm_option(underlying: str, spot: float, ce_or_pe: str, expiry_dt: datetime) -> OptContract:
    """
    Choose weekly ATM option by nearest strike for given underlying ("NIFTY" / "BANKNIFTY").
    expiry_dt should be UTC date (we compare date only).
    """
    df = load_instrument_master()
    q = df[
        (df["exch_seg"] == "NFO")
        & (df["instrumenttype"] == "OPTIDX")
        & (df["name"] == underlying)
        & (df["expiry"].dt.date == expiry_dt.date())
        & (df["symbol"].str.endswith(ce_or_pe))
    ]
    if q.empty:
        raise RuntimeError(f"No options found for {underlying} {expiry_dt.date()} {ce_or_pe}")

    strike = _nearest_strike(q, spot)
    qq = q[q["strike"] == strike]
    if qq.empty:
        raise RuntimeError("Nearest strike not present (unexpected)")

    row = qq.iloc[0]
    return OptContract(
        tradingsymbol=str(row["symbol"]),
        symboltoken=str(row["token"]),
        expiry=str(row["expiry"].date()),
        strike=float(row["strike"]),
        lotsize=int(row["lotsize"]),
    )

# ---- quotes ----
def angel_headers(api_key: str, jwt_token: str) -> Dict[str, str]:
    # Minimal set that works with Market Feeds quote API
    return {
        "Authorization": f"Bearer {jwt_token}",
        "X-PrivateKey": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-UserType": "USER",
        "X-SourceID": "WEB",
        "X-ClientLocalIP": "127.0.0.1",
        "X-ClientPublicIP": "127.0.0.1",
        "X-MACAddress": "00:00:00:00:00:00",
    }

def get_option_ltp(api_key: str, jwt_token: str, tradingsymbol: str, symboltoken: str) -> float:
    """
    Angel Market Feeds 'quote' API, LTP mode.
    Exchange = NFO for index options. Returns last traded price.
    """
    url = "https://apiconnect.angelbroking.com/rest/secure/angelbroking/market/v1/quote/"
    payload = {
        "mode": "LTP",
        "exchangeTokens": {
            "NFO": [symboltoken]
        }
    }
    r = requests.post(url, headers=angel_headers(api_key, jwt_token), json=payload, timeout=10)
    j = r.json()
    if not j.get("data"):
        raise RuntimeError(f"Quote failed for {tradingsymbol}: {j}")
    # SmartAPI returns list of dicts with 'lastTradedPrice'
    row = j["data"][0]
    ltp = row.get("ltp") or row.get("lastTradedPrice") or row.get("LTP")
    if ltp is None:
        raise RuntimeError(f"LTP missing in response for {tradingsymbol}: {row}")
    return float(ltp)

def size_option_lots(budget_money: float, entry: float, sl: float, lotsize: int) -> Tuple[int, float]:
    """
    Risk-based lot sizing: lots = floor(budget / ((entry - sl) * lotsize)).
    Returns (lots, per_lot_risk_money).
    """
    per_lot_risk = max(entry - sl, 0.0) * lotsize
    if per_lot_risk <= 0:
        return (0, 0.0)
    lots = int(math.floor(budget_money / per_lot_risk))
    return (lots, per_lot_risk)
