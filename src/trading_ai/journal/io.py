
from __future__ import annotations
import csv
from pathlib import Path
from typing import Dict, Any, Iterable

def append_rows_csv(path: str | Path, rows: Iterable[Dict[str, Any]], header: Iterable[str] | None = None) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    write_header = not p.exists()
    with p.open("a", newline="", encoding="utf-8") as f:
        if header and write_header:
            csv.DictWriter(f, fieldnames=list(header)).writeheader()
        w = csv.DictWriter(f, fieldnames=list(header) if header else None, extrasaction="ignore")
        for r in rows:
            w.writerow(r)
