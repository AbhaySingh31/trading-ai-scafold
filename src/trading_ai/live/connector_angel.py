from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Dict
from datetime import datetime, timezone

TickHandler = Callable[[str, float, datetime], None]

@dataclass
class AngelConfig:
    api_key: str
    client_code: str
    jwt_token: str      # RAW JWT (no 'Bearer ')
    feed_token: str
    # Map friendly symbols to Angel tokens.
    # For indices use 999-series tokens:
    #   NIFTY 50     -> token "99926000"
    #   BANKNIFTY    -> token "99926009"
    # Example:
    # instruments = {
    #   "NIFTY":     {"exchangeType": 1, "token": "99926000"},
    #   "BANKNIFTY": {"exchangeType": 1, "token": "99926009"},
    # }
    instruments: Dict[str, Dict[str, str]]

class AngelOneConnector:
    """Angel One SmartAPI WebSocket v2 connector (LTP stream)."""

    def __init__(self, cfg: AngelConfig, on_tick: TickHandler):
        self.cfg = cfg
        self.on_tick = on_tick
        self._sws = None
        self._token_to_symbol: Dict[str, str] = {}
        for sym, meta in (cfg.instruments or {}).items():
            tok = str(meta.get("token") or "")
            if tok:
                self._token_to_symbol[tok] = sym

    def start(self):
        try:
            # Correct import for smartapi-python
            from SmartApi.smartWebSocketV2 import SmartWebSocketV2
            used_mod = "SmartApi"
        except Exception:
            raise SystemExit("Angel SmartAPI not found. Install with: pip install smartapi-python")

        # Correct ctor order: (api_key, client_code, jwt_token, feed_token)
        self._sws = SmartWebSocketV2(
            self.cfg.api_key, self.cfg.client_code, self.cfg.jwt_token, self.cfg.feed_token
        )
        print(f"[angel] using import: {used_mod}")

        def _on_data(wsapp, message):
            try:
                now = datetime.now(timezone.utc)

                # v2 LTP messages often look like:
                # {'subscription_mode': 1, 'exchange_type': 1, 'token': '99926000',
                #  'exchange_timestamp': 1756462128000, 'last_traded_price': 2442685, ...}
                # Note: prices come in paise -> divide by 100.0 to rupees.
                if isinstance(message, dict):
                    tok = str(message.get("token") or message.get("symbolToken") or "")
                    if tok and tok in self._token_to_symbol:
                        ltp = (
                            message.get("last_traded_price")
                            or message.get("ltp")
                            or message.get("lastPrice")
                            or message.get("LastTradedPrice")
                        )
                        if ltp is not None:
                            price_rupees = float(ltp) / 100.0
                            sym = self._token_to_symbol[tok]
                            self.on_tick(sym, price_rupees, now)
                            return

                # Some variants wrap in "data": [ ... ]
                if isinstance(message, dict) and isinstance(message.get("data"), list):
                    for r in message["data"]:
                        tok = str(r.get("token") or r.get("symbolToken") or "")
                        if tok and tok in self._token_to_symbol:
                            ltp = (
                                r.get("last_traded_price")
                                or r.get("ltp")
                                or r.get("lastPrice")
                                or r.get("LastTradedPrice")
                                or r.get("lastTradedPrice")
                            )
                            if ltp is not None:
                                price_rupees = float(ltp) / 100.0
                                sym = self._token_to_symbol[tok]
                                self.on_tick(sym, price_rupees, now)
            except Exception as e:
                print("[angel][on_data] parse error:", e)

        def _on_open(wsapp):
            try:
                # Build token_list grouped by exchangeType
                by_ex: Dict[int, list] = {}
                for _, meta in self.cfg.instruments.items():
                    ex = int(meta["exchangeType"])
                    tok = str(meta["token"])
                    by_ex.setdefault(ex, []).append(tok)
                token_list = [{"exchangeType": ex, "tokens": toks} for ex, toks in by_ex.items()]

                # subscribe(correlation_id, mode, token_list) -> use mode=1 (LTP)
                corr = "ta_live"
                self._sws.subscribe(corr, 1, token_list)
                print("[angel] subscribed:", token_list)
            except Exception as e:
                print("[angel][on_open] subscribe error:", e)

        def _on_close(wsapp):
            print("[angel] websocket closed")

        def _on_error(wsapp, error):
            print("[angel] websocket error:", error)

        self._sws.on_data = _on_data
        self._sws.on_open = _on_open
        self._sws.on_close = _on_close
        self._sws.on_error = _on_error
        self._sws.connect()

    def stop(self):
        try:
            if self._sws:
                self._sws.close()
        except Exception:
            pass
