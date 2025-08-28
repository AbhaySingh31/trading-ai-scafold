# src/trading_ai/cli/compare.py
from __future__ import annotations
import argparse
from typing import Dict, Any, Tuple
from ..analytics.metrics import summarize_trades

NUM_FIELDS = [
    "trades",
    "win_rate_pct",
    "total_R",
    "avg_R",
    "max_drawdown_R",
    "total_pnl_money",
]

TEXTY_FIELDS = [
    "profit_factor",         # can be "inf"
    "profit_factor_money",   # can be "inf"
]

def _to_float(x) -> float | None:
    try:
        return float(x)
    except Exception:
        return None

def _fmt(x) -> str:
    if isinstance(x, (int,)) or (isinstance(x, float) and x.is_integer()):
        return f"{int(x)}"
    try:
        xf = float(x)
        if abs(xf) >= 1000:
            return f"{xf:,.2f}"
        return f"{xf:.2f}"
    except Exception:
        return str(x)

def _delta(a: Any, b: Any) -> Tuple[str, str]:
    """Return (absolute_delta_str, percent_delta_str or '—')."""
    fa, fb = _to_float(a), _to_float(b)
    if fa is None or fb is None:
        return (f"{b} - {a}", "—")
    absd = fb - fa
    if fa == 0:
        pct = "—"
    else:
        pct = f"{(absd / abs(fa)) * 100:.1f}%"
    return ( _fmt(absd), pct )

def compare(a_metrics: Dict[str, Any], b_metrics: Dict[str, Any], label_a: str, label_b: str) -> str:
    lines = []
    lines.append(f"Compare: {label_a}  vs  {label_b}")
    lines.append("-" * 64)

    # numeric fields with deltas
    for k in NUM_FIELDS:
        a = a_metrics.get(k, "n/a")
        b = b_metrics.get(k, "n/a")
        d_abs, d_pct = _delta(a, b)
        lines.append(f"{k:>18}:  {label_a}={_fmt(a):>10}   {label_b}={_fmt(b):>10}   Δ={d_abs:>10}   ({d_pct})")

    # text-like fields (no % delta)
    for k in TEXTY_FIELDS:
        a = a_metrics.get(k, "n/a")
        b = b_metrics.get(k, "n/a")
        lines.append(f"{k:>18}:  {label_a}={a!s:>10}   {label_b}={b!s:>10}   Δ={(b if a!=b else '0')}")

    lines.append("-" * 64)
    # quick judgment hints
    def arrow(val: float | None, invert: bool=False) -> str:
        if val is None: return ""
        if invert:
            return "↑ better" if val < 0 else "↓ worse" if val > 0 else "="
        return "↑ better" if val > 0 else "↓ worse" if val < 0 else "="

    # summarize a few key directions
    d_totalR = _to_float(b_metrics.get("total_R")) ; d_totalR = None if d_totalR is None else d_totalR - (_to_float(a_metrics.get("total_R")) or 0.0)
    d_ddR    = _to_float(b_metrics.get("max_drawdown_R")) ; d_ddR = None if d_ddR is None else d_ddR - (_to_float(a_metrics.get("max_drawdown_R")) or 0.0)

    lines.append(f"Total_R delta: { _fmt(d_totalR) if d_totalR is not None else 'n/a' }   {arrow(d_totalR)}")
    lines.append(f"MaxDD_R delta: { _fmt(d_ddR) if d_ddR is not None else 'n/a' }   {arrow(d_ddR, invert=True)}")
    return "\n".join(lines)

def main():
    ap = argparse.ArgumentParser(description="Compare two backtest runs and print metric deltas.")
    ap.add_argument("--a-trades", required=True, help="Path to TRADES CSV (run A)")
    ap.add_argument("--b-trades", required=True, help="Path to TRADES CSV (run B)")
    ap.add_argument("--label-a", default="A", help="Label for run A (e.g., cooldown=5)")
    ap.add_argument("--label-b", default="B", help="Label for run B (e.g., cooldown=15)")
    args = ap.parse_args()

    a_metrics = summarize_trades(args.a_trades)
    b_metrics = summarize_trades(args.b_trades)
    report = compare(a_metrics, b_metrics, args.label_a, args.label_b)
    print(report)

if __name__ == "__main__":
    main()
