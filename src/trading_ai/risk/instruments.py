
from __future__ import annotations
from typing import Optional, Dict

PRESETS: dict[str, Dict[str, float | int | str]] = {
    "NIFTY":       {"min_qty": 50,  "round_to": 50,  "point_value": 1.0, "tick_size": 0.05, "tick_round": "nearest", "strike_step": 50},
    "BANKNIFTY":   {"min_qty": 15,  "round_to": 15,  "point_value": 1.0, "tick_size": 0.05, "tick_round": "nearest", "strike_step": 100},
    "MIDCAPNIFTY": {"min_qty": 25,  "round_to": 25,  "point_value": 1.0, "tick_size": 0.05, "tick_round": "nearest", "strike_step": 25},
}

def resolve_preset(symbol: str) -> Optional[Dict[str, float | int | str]]:
    s = symbol.upper()
    if s in PRESETS:
        return PRESETS[s]
    for key in PRESETS:
        if key in s:
            return PRESETS[key]
    return None

def print_preset_banner(symbol: str, preset: Dict[str, float | int | str], args) -> None:
    tick_size = getattr(args, "tick_size", 0)
    tick_round = getattr(args, "tick_round", "nearest")
    strike_step = preset.get("strike_step", "n/a")
    print(f"[presets] {symbol}: round_to={args.round_to}  min_qty={args.min_qty}  point_value={args.point_value}  "
          f"tick_size={tick_size}  tick_round={tick_round}  strike_step={strike_step}")
