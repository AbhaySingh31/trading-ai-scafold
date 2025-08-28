
from __future__ import annotations
from math import floor
from typing import Tuple
def _round_down(n: float, step: int) -> int:
    step = max(int(step), 1); return int(floor(n / step) * step)
def compute_size(action: str, entry: float, stop: float, *, capital: float, risk_pct: float, point_value: float = 1.0, min_qty: int = 1, round_to: int = 1) -> Tuple[int, float, float]:
    if action.upper() not in ("BUY","SELL"): return (0,0.0,0.0)
    if point_value <= 0: point_value = 1.0
    dist = (entry - stop) if action.upper()=="BUY" else (stop - entry)
    if dist <= 0: dist = max(abs(entry)*1e-4, 0.01)
    risk_per_unit_money = abs(dist) * point_value; budget_risk = max(capital * max(risk_pct, 0.0), 0.0)
    if risk_per_unit_money <= 0: return (0,0.0,0.0)
    raw_qty = budget_risk / risk_per_unit_money; qty = max(_round_down(raw_qty, round_to), int(min_qty))
    max_risk_money = qty * risk_per_unit_money; return (qty, risk_per_unit_money, max_risk_money)
