
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any
import pandas as pd
import numpy as np

@dataclass
class OptionPick:
    side: str
    expiry: str
    strike: float
    entry: float
    stop: float
    tp1: float
    tp2: float
    lots: int
    lot_size: int
    premium_risk_per_unit: float
    notes: str

def _parse_expiry(s: Any) -> Optional[pd.Timestamp]:
    if pd.isna(s):
        return None
    fmts = [None, "%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d", "%d/%m/%Y"]
    for fmt in fmts:
        try:
            if fmt is None:
                return pd.to_datetime(s, utc=True)
            dt = datetime.strptime(str(s), fmt).replace(tzinfo=timezone.utc)
            return pd.to_datetime(dt, utc=True)
        except Exception:
            continue
    return None

def load_chain(csv_path: str | Path) -> pd.DataFrame:
    p = Path(csv_path)
    if not p.exists():
        raise SystemExit(f"[opts] Option chain not found: {p.resolve()}")
    df = pd.read_csv(p)
    need = ["strike", "type", "expiry"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise SystemExit(f"[opts] Missing columns in chain: {missing}")
    df["type"] = df["type"].astype(str).str.upper().str.strip()
    df = df[df["type"].isin(["CE", "PE"])].copy()
    df["strike"] = pd.to_numeric(df["strike"], errors="coerce")
    df["expiry_ts"] = df["expiry"].apply(_parse_expiry)
    for c in ["bid", "ask", "ltp"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if {"bid","ask"} <= set(df.columns):
        df["mid"] = (df["bid"] + df["ask"]) / 2.0
    else:
        df["mid"] = np.nan
    df["price"] = df["mid"].where(~df["mid"].isna(), df.get("ltp", np.nan))
    df = df.dropna(subset=["strike","expiry_ts","price"])
    if "delta" in df.columns:
        df["delta"] = pd.to_numeric(df["delta"], errors="coerce")
    else:
        df["delta"] = np.nan
    return df

def nearest_expiry(df: pd.DataFrame, mode: str = "weekly") -> pd.Timestamp:
    now = pd.Timestamp.utcnow()
    elig = df[df["expiry_ts"] >= now].sort_values("expiry_ts")
    if elig.empty:
        return df["expiry_ts"].sort_values().iloc[-1]
    return elig["expiry_ts"].iloc[0]

def round_to_step(x: float, step: int) -> float:
    if step <= 0:
        return float(round(x))
    return float(round(x / step) * step)

def choose_strike_by_mode(spot: float, step: int, side: str, mode: str, df: pd.DataFrame, delta_target: float | None) -> float:
    if mode == "atm" or (delta_target is None):
        return round_to_step(spot, step)
    sub = df[df["delta"].notna()].copy()
    if sub.empty:
        return round_to_step(spot, step)
    target = abs(delta_target) * (1 if side == "CE" else -1)
    sub = sub[sub["type"] == side].copy()
    if sub.empty:
        return round_to_step(spot, step)
    sub["delta_gap"] = (sub["delta"] - target).abs()
    sub["atm_gap"] = (sub["strike"] - round_to_step(spot, step)).abs()
    pick = sub.sort_values(["delta_gap","atm_gap"]).iloc[0]
    return float(pick["strike"])

def pick_option_for_signal(
    symbol: str,
    direction: str,
    spot_price: float,
    chain: pd.DataFrame,
    *,
    strike_step: int = 50,
    expiry_mode: str = "weekly",
    mode: str = "atm",
    delta_target: float = 0.40,
    sl_pct: float = 0.25,
    tp1_pct: float = 0.50,
    tp2_pct: float = 1.00,
    risk_capital: float = 1_000_000.0,
    risk_pct: float = 0.005,
    lot_size: int = 50,
) -> OptionPick:
    side = "CE" if direction.upper() == "BUY" else "PE"
    exp = nearest_expiry(chain, mode=expiry_mode)
    df_exp = chain[chain["expiry_ts"] == exp]
    strike = choose_strike_by_mode(spot_price, strike_step, side, mode, df_exp, delta_target)
    row = df_exp[(df_exp["type"]==side) & (df_exp["strike"]==strike)].copy()
    if row.empty:
        side_df = df_exp[df_exp["type"]==side].copy()
        row = side_df.iloc[(side_df["strike"] - strike).abs().argsort()].head(1)
    r = row.iloc[0]
    entry = float(r["price"])
    if not np.isfinite(entry):
        raise SystemExit("[opts] No valid price (bid/ask/ltp) for chosen contract.")
    stop = max(0.05, entry * (1 - sl_pct))
    tp1  = entry * (1 + tp1_pct)
    tp2  = entry * (1 + tp2_pct)
    per_unit_risk = entry - stop
    if per_unit_risk <= 0:
        raise SystemExit("[opts] Computed per-unit risk <= 0; adjust sl_pct or chain quality.")
    budget = risk_capital * risk_pct
    raw_units = int(budget // (per_unit_risk * lot_size)) * lot_size
    lots = max(0, raw_units // lot_size)
    return OptionPick(
        side=side, expiry=str(exp.date()), strike=float(strike),
        entry=round(entry,2), stop=round(stop,2), tp1=round(tp1,2), tp2=round(tp2,2),
        lots=int(lots), lot_size=int(lot_size), premium_risk_per_unit=round(per_unit_risk,2),
        notes=f"{symbol} spot={spot_price:.2f} mode={mode} delta≈{delta_target if mode=='delta' else 'n/a'}"
    )
