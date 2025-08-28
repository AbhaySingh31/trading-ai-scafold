
Options Picker Add-on
=====================

New files:
- src/trading_ai/options/chooser.py
- src/trading_ai/cli/opts_pick.py
- src/trading_ai/risk/instruments.py (adds strike_step)

Usage (standalone picker):
-------------------------
python -m src.trading_ai.cli.opts_pick ^
  --data data\NIFTY_5m_latest.csv ^
  --chain data\CHAIN_SAMPLE_NIFTY.csv ^
  --symbol NIFTY --direction BUY ^
  --mode atm --capital 1000000 --risk-pct 0.005

Replay with option selection (after integrating into your replay if desired):
----------------------------------------------------------------------------
python -m src.trading_ai.cli.replay ^
  --data data\BANKNIFTY_5m_demo_signals_INSESS.csv ^
  --symbol BANKNIFTY --timeframe 5m ^
  --simulate --overwrite --use-presets ^
  --opts-chain data\CHAIN_SAMPLE_NIFTY.csv ^
  --opts-mode atm --opt-sl-pct 0.25 --opt-tp1-pct 0.5 --opt-tp2-pct 1.0 ^
  --signals-out out\signals.csv --trades-out out\trades.csv

Option chain CSV example included at: data/CHAIN_SAMPLE_NIFTY.csv
