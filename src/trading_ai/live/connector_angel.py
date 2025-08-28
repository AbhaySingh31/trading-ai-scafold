
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Dict, Optional
from datetime import datetime, timezone

TickHandler = Callable[[str, float, datetime], None]

@dataclass
class AngelConfig:
    api_key: str
    client_code: str
    jwt_token: str
    feed_token: str
    # instruments: map your friendly symbols to Angel's exchangeType + token
    # Example: {"NIFTY": {"exchangeType": 1, "token": "26000"}, "BANKNIFTY": {"exchangeType": 1, "token": "26009"}}
    instruments: Dict[str, Dict[str, str]]

class AngelOneConnector:
    """Angel One SmartAPI WebSocket v2 connector (LTP stream)."""
    def __init__(self, cfg: AngelConfig, on_tick: TickHandler):
        self.cfg = cfg
        self.on_tick = on_tick
        self._sws = None
        self._token_to_symbol: Dict[str, str] = {}
        for sym, meta in (cfg.instruments or {}).items():
            tok = str(meta.get("token"))
            if tok:
                self._token_to_symbol[tok] = sym

    def start(self):
        try:
            # library: smartapi (smartapi-python)
            from smartapi import SmartWebSocketV2
        except ImportError:
            raise SystemExit("Install Angel SmartAPI: pip install smartapi-python")
        self._sws = SmartWebSocketV2(self.cfg.api_key, self.cfg.jwt_token, self.cfg.client_code, self.cfg.feed_token)

        def _on_data(wsapp, message):
            # message may be dict or JSON-like; handle common shapes
            try:
                if isinstance(message, dict):
                    data = message.get("data") or message.get("message") or message
                else:
                    data = message
                now = datetime.now(timezone.utc)
                # Typical shape: {'data': [{'token': '26000', 'lastTradedPrice': 24520, ...}, ...]}
                rows = []
                if isinstance(data, list):
                    rows = data
                elif isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
                    rows = data["data"]
                elif isinstance(data, dict):
                    rows = [data]
                for r in rows:
                    tok = str(r.get("token") or r.get("symbolToken") or "")
                    sym = self._token_to_symbol.get(tok)
                    if not sym:
                        continue
                    ltp = r.get("lastTradedPrice") or r.get("ltp") or r.get("LTP") or r.get("LastTradedPrice")
                    if ltp is None:
                        continue
                    self.on_tick(sym, float(ltp), now)
            except Exception as e:
                print("[angel][on_data] parse error:", e)

        def _on_open(wsapp):
            try:
                # Build token list per exchange
                by_ex = {}
                for sym, meta in self.cfg.instruments.items():
                    ex = int(meta["exchangeType"])
                    tok = str(meta["token"])
                    by_ex.setdefault(ex, []).append(tok)
                token_list = [{"exchangeType": ex, "tokens": toks} for ex, toks in by_ex.items()]
                # Subscribe LTP (mode=1). Some SDKs require correlation_id; use a fixed one.
                corr = "ta_live"
                self._sws.subscribe(corr, mode=1, token_list=token_list)
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
