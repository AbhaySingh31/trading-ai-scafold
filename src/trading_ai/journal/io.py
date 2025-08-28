
from __future__ import annotations
import csv, os
from typing import List, Dict, Any
def append_rows_csv(path: str, rows: List[Dict[str, Any]], header: list[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    file_exists = os.path.exists(path) and os.path.getsize(path) > 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        if not file_exists: w.writeheader()
        for r in rows: w.writerow({k: r.get(k, "") for k in header})
