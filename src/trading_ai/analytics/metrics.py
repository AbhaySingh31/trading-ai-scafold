
from __future__ import annotations
import pandas as pd
from typing import Dict, Any
def summarize_trades(trades_csv: str) -> Dict[str, Any]:
    df = pd.read_csv(trades_csv); has_R = "R" in df.columns; has_pnl = "pnl" in df.columns
    n = len(df); wins=losses=breakeven=0; total_R=0.0; total_pnl_pos=0.0; total_pnl_neg=0.0; total_pnl_money_pos=0.0; total_pnl_money_neg=0.0; has_money=False
    equity_R=[]; cum_R=0.0
    for _, r in df.iterrows():
        if has_R and pd.notna(r["R"]): R=float(r["R"])
        elif has_pnl and pd.notna(r.get("pnl")) and pd.notna(r.get("entry")) and pd.notna(r.get("stop_loss")):
            entry=float(r["entry"]); sl=float(r["stop_loss"]); risk=abs(entry-sl) if abs(entry-sl)>1e-6 else 1.0; R=float(r["pnl"])/risk
        else: R=0.0
        if "pnl_money" in df.columns and pd.notna(r.get("pnl_money")):
            has_money=True; pm=float(r["pnl_money"]); 
            if pm>0: total_pnl_money_pos += pm
            elif pm<0: total_pnl_money_neg += pm
        total_R += R; cum_R += R; equity_R.append(cum_R)
        if R>1e-9: wins += 1; total_pnl_pos += max(float(r.get("pnl",0.0)), 0.0)
        elif R<-1e-9: losses += 1; total_pnl_neg += min(float(r.get("pnl",0.0)), 0.0)
        else: breakeven += 1
    win_rate = (wins/n)*100.0 if n else 0.0; avg_R=(total_R/n) if n else 0.0
    profit_factor = (total_pnl_pos/abs(total_pnl_neg)) if total_pnl_neg!=0 else (float("inf") if total_pnl_pos>0 else 0.0)
    profit_factor_money = (total_pnl_money_pos/abs(total_pnl_money_neg)) if total_pnl_money_neg!=0 else ((float("inf") if total_pnl_money_pos>0 else 0.0) if has_money else None)
    max_dd=0.0; peak=float("-inf")
    for v in equity_R:
        peak=max(peak,v); dd=peak-v; max_dd=max(max_dd, dd)
    return {"trades":int(n),"wins":int(wins),"losses":int(losses),"breakeven":int(breakeven),"win_rate_pct":round(win_rate,2),"total_R":round(total_R,3),"avg_R":round(avg_R,3),"profit_factor":("inf" if profit_factor==float("inf") else round(profit_factor,3)),"max_drawdown_R":round(max_dd,3),"total_pnl_money":(round(total_pnl_money_pos+total_pnl_money_neg,2) if has_money else None),"profit_factor_money":("inf" if has_money and profit_factor_money==float("inf") else (round(profit_factor_money,3) if has_money else None))}
