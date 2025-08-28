
from __future__ import annotations
import argparse, json
from ..analytics.metrics import summarize_trades
def main():
    p = argparse.ArgumentParser(description="Analyze trades.csv and print summary metrics")
    p.add_argument("--trades", required=True, help="Path to trades.csv")
    p.add_argument("--out-json", default=None, help="Optional path to write metrics JSON")
    args = p.parse_args()
    stats = summarize_trades(args.trades); print(json.dumps(stats, indent=2))
    if args.out_json:
        with open(args.out_json, "w", encoding="utf-8") as f: json.dump(stats, f, indent=2)
if __name__ == "__main__": main()
