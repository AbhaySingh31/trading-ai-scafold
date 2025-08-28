
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

@dataclass
class Candle:
    ts: datetime   # UTC, bar start time
    o: float
    h: float
    l: float
    c: float
    v: float      # proxy volume (tick count) if real volume not available

def floor_time(dt: datetime, minutes: int) -> datetime:
    m = (dt.minute // minutes) * minutes
    return dt.replace(second=0, microsecond=0, minute=m)

class BarAggregator:
    """Aggregate ticks -> 1m and 5m candles. Uses tick-count as volume proxy by default."""
    def __init__(self, five_min: int = 5):
        self.five = five_min
        self.one_min_bars: Dict[str, Dict[datetime, Candle]] = {}
        self.five_min_bars: Dict[str, Dict[datetime, Candle]] = {}
        self.last_5m_closed: Dict[str, Optional[datetime]] = {}

    def on_tick(self, symbol: str, price: float, ts_utc: Optional[datetime] = None) -> None:
        if ts_utc is None:
            ts_utc = datetime.now(timezone.utc)
        key1 = floor_time(ts_utc, 1)
        d1 = self.one_min_bars.setdefault(symbol, {})
        c = d1.get(key1)
        if c is None:
            d1[key1] = Candle(ts=key1, o=price, h=price, l=price, c=price, v=1.0)
        else:
            c.h = max(c.h, price); c.l = min(c.l, price); c.c = price; c.v += 1.0

    def _rollup_5m(self, symbol: str) -> None:
        d1 = self.one_min_bars.get(symbol, {})
        if not d1: return
        d5 = self.five_min_bars.setdefault(symbol, {})
        keys = sorted(d1.keys())
        if not keys: return
        from collections import defaultdict
        groups = defaultdict(list)
        for k in keys:
            g = floor_time(k, self.five)
            groups[g].append(k)
        for g, mins in groups.items():
            mins.sort()
            now5 = floor_time(datetime.now(timezone.utc), self.five)
            if g >= now5:
                continue
            if g in d5:
                continue
            opens = d1[mins[0]].o
            highs = max(d1[m].h for m in mins)
            lows  = min(d1[m].l for m in mins)
            close = d1[mins[-1]].c
            vol   = sum(d1[m].v for m in mins)
            d5[g] = Candle(ts=g, o=opens, h=highs, l=lows, c=close, v=vol)

    def try_close_5m(self, symbol: str) -> Optional[Candle]:
        self._rollup_5m(symbol)
        d5 = self.five_min_bars.get(symbol, {})
        if not d5: return None
        latest_closed = max(d5.keys())
        if self.last_5m_closed.get(symbol) == latest_closed:
            return None
        now5 = floor_time(datetime.now(timezone.utc), self.five)
        if latest_closed >= now5:
            return None
        self.last_5m_closed[symbol] = latest_closed
        return d5[latest_closed]

    def last_n_5m(self, symbol: str, n: int = 300) -> List[Candle]:
        d5 = self.five_min_bars.get(symbol, {})
        ks = sorted(d5.keys())
        return [d5[k] for k in ks[-n:]]
