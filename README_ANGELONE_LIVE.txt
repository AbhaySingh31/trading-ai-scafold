
Angel One SmartAPI Live Run (WS) - Addon
========================================

What you get
------------
- Angel One WebSocket v2 connector (LTP stream)
- Tick -> 1m -> 5m aggregation
- On each 5m close: run indicators + rules, print a clean trading plan, log to CSV

Install
-------
pip install smartapi-python pyotp

Step 1: Generate JWT + Feed Token (one-time per session)
-------------------------------------------------------
python -m src.trading_ai.cli.angel_login ^
  --api-key YOUR_API_KEY ^
  --client-code YOUR_CLIENT_CODE ^
  --password YOUR_PASSWORD ^
  --otp 123456
# or use TOTP:
# python -m src.trading_ai.cli.angel_login --api-key ... --client-code ... --password ... --totp-secret BASE32SECRET

It prints:
{
  "jwt_token": "...",
  "feed_token": "..."
}

Step 2: Run the live loop (30s check; acts on 5m closes)
--------------------------------------------------------
python -m src.trading_ai.cli.live_run ^
  --api-key YOUR_API_KEY ^
  --client-code YOUR_CLIENT_CODE ^
  --jwt-token "<JWT_FROM_STEP1>" ^
  --feed-token "<FEED_FROM_STEP1>" ^
  --instruments "{"NIFTY":{"exchangeType":1,"token":"26000"},"BANKNIFTY":{"exchangeType":1,"token":"26009"}}" ^
  --symbols NIFTY,BANKNIFTY ^
  --interval 30 ^
  --use-presets --tick-size 0.05 --risk-pct 0.005

Notes
-----
- You must pass the correct exchangeType and token for your account. The example uses common index tokens; confirm against Angel One's instrument master.
- This prints underlying plans. If you want live **option premium** and contract selection inside this loop, we can add an options quote call for the chosen trading symbol and apply your premium SL/TP sizing (easy drop-in once you confirm).
- Market hours & throttling: keep interval around 30s; CPU-light.
