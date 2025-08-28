
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Any
import pandas as pd
@dataclass
class TriggerConfig:
    rsi_oversold: float = 30.0
    volume_multiple: float = 1.5
    cooldown_bars: int = 10
def compute_volume_multiple(vol: pd.Series, lookback: int = 20) -> pd.Series:
    avg = vol.rolling(lookback).mean(); return vol / avg
def _macd_cross_up(macd: pd.Series, signal: pd.Series, i: int) -> bool:
    if i < 1: return False
    return (macd.iat[i] > signal.iat[i]) and (macd.iat[i-1] <= signal.iat[i-1])
def explain_bar(row: pd.Series, vol_mult_value, cfg: TriggerConfig) -> Dict[str, Any]:
    rsi_ok = pd.notna(row.get("rsi")) and row["rsi"] < cfg.rsi_oversold
    macd_ok = pd.notna(row.get("macd")) and pd.notna(row.get("macd_signal")) and (row["macd"] > row["macd_signal"])
    vol_ok = pd.notna(vol_mult_value) and float(vol_mult_value) > cfg.volume_multiple
    above_bb = pd.notna(row.get("bb_up")) and pd.notna(row.get("close")) and (row["close"] > row["bb_up"])
    long_meanrev = bool(rsi_ok and macd_ok and vol_ok); long_momo = bool(above_bb and vol_ok)
    trigger = "meanrev" if long_meanrev else ("momentum" if long_momo else "")
    note = "" if vol_ok else "volume below threshold"
    if trigger == "" and vol_ok:
        if not rsi_ok and not above_bb: note = "neither RSI<oversold nor close>upperBB"
        elif not rsi_ok: note = "RSI not oversold"
        elif not macd_ok: note = "MACD not bullish"
        elif not above_bb: note = "not above upper band"
    return {"rsi_ok":bool(rsi_ok),"macd_ok":bool(macd_ok),"vol_ok":bool(vol_ok),"above_bb":bool(above_bb),"trigger":trigger,"note":note}
def detect_setups(df: pd.DataFrame, cfg: TriggerConfig) -> List[Dict[str, Any]]:
    vol_mult = compute_volume_multiple(df["volume"]); signals: List[Dict[str, Any]] = []; last_sig_idx = -10**9
    for i in range(len(df)):
        row = df.iloc[i]
        warmup_missing = any(pd.isna(row.get(k)) for k in ["rsi","macd","macd_signal","ema_fast","ema_slow","bb_up","bb_dn","atr"])
        if warmup_missing: continue
        if (i - last_sig_idx) < cfg.cooldown_bars: continue
        rsi_ok = row["rsi"] < cfg.rsi_oversold
        vol_ok = float(vol_mult.iat[i]) > cfg.volume_multiple if pd.notna(vol_mult.iat[i]) else False
        momo_ok = (row["close"] > row["bb_up"]) and vol_ok
        meanrev_ok = rsi_ok and _macd_cross_up(df["macd"], df["macd_signal"], i) and vol_ok
        if meanrev_ok or momo_ok:
            bands_pos = "above" if row["close"] > row["bb_up"] else ("below" if row["close"] < row["bb_dn"] else "inside")
            macd_state = "bull" if row["macd"] > row["macd_signal"] else "bear"
            ema_state = "up" if row["ema_fast"] > row["ema_slow"] else "down"
            win = df.iloc[max(0, i-20):i]; context = "momentum" if momo_ok else "meanreversion"
            key_levels = {"support": float(win["low"].mean()) if len(win) else float(row["low"]), "resistance": float(win["high"].mean()) if len(win) else float(row["high"])}
            signals.append({"timestamp":row["timestamp"],"symbol":row.get("symbol",""),"timeframe":row.get("timeframe",""),"price":float(row["close"]), "rsi":float(row["rsi"]),"macd_state":macd_state,"ema20_vs_ema50":ema_state,"bands_position":bands_pos,"volume_multiple": float(vol_mult.iat[i]) if pd.notna(vol_mult.iat[i]) else 0.0,"atr":float(row["atr"]),"context":context,"key_levels":key_levels})
            last_sig_idx = i
    return signals
