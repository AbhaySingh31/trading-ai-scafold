
# Trading AI — Hybrid Pipeline (NIFTY/BANKNIFTY & Midcaps)

**Status:** v0.1 scaffold • Date: 2025-08-28

This repository implements the milestone plan we discussed: indicators & rule filters run locally,
and an LLM (optional) provides judgment. Start offline with CSV replay, then swap in live feeds.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
```

### Run a replay (simulated live)

```bash
python -m src.trading_ai.cli.replay   --data data/BANKNIFTY_5m_sample.csv   --symbol BANKNIFTY --timeframe 5m   --signals-out out/signals.csv   --trades-out out/trades.csv
```

## Structure

```
src/trading_ai/
  data/loader.py        # CSV load + validation
  indicators/core.py    # RSI, MACD, EMA, Bollinger, ATR, VWAP
  rules/filters.py      # trigger logic + cooldowns/state
  llm/interface.py      # JSON contract + stub client
  journal/io.py         # CSV appenders
  cli/replay.py         # entrypoint to run a candle stream
tests/                  # unit + integration tests (placeholders)
data/                   # sample CSVs
```

## Contracts

**Signal package (Python → LLM):**
```json
{
  "symbol": "BANKNIFTY",
  "timeframe": "5m",
  "price": 45000,
  "rsi": 28.4,
  "macd_state": "bull",
  "ema20_vs_ema50": "up",
  "bands_position": "inside",
  "volume_multiple": 1.9,
  "atr": 120.5,
  "key_levels": {"support": 44800, "resistance": 45500},
  "context": "expiry day; high vix"
}
```

**LLM JSON output (must be parseable):**
```json
{
  "action": "BUY",
  "entry": 45020,
  "stop_loss": 44880,
  "targets": [45150, 45500],
  "position_size_hint": "medium",
  "confidence": 0.68,
  "notes": "Buy on pullback to VWAP; trail after T1."
}
```

## Testing
- Unit tests will cover indicator correctness (spot values), filter triggers, cooldown logic,
  and JSON parsing. An end-to-end replay will assert a fixed number of signals on the sample CSV.

## Next
- Fill in indicator calculations (pandas-ta), add rule thresholds, run the replay on sample data.
