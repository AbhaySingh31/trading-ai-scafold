# src/trading_ai/risk/tick.py
from __future__ import annotations
import math

def round_to_tick(price: float, tick: float, how: str = "nearest") -> float:
    """Round price to the given tick size.
    how ∈ {"nearest","up","down"}; if tick<=0, returns price unchanged.
    """
    try:
        p = float(price)
        t = float(tick)
    except Exception:
        return price
    if t <= 0:
        return p

    q = p / t
    if how == "up":
        return round(math.ceil(q) * t, 10)
    if how == "down":
        return round(math.floor(q) * t, 10)
    # nearest
    return round(round(q) * t, 10)
