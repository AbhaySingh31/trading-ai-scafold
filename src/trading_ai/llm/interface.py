
from __future__ import annotations
from typing import Dict, Any
import json

class LLMClient:
    """Stub LLM: returns deterministic JSON response for testing.

    In production, replace `decide` impl with a real model call and keep the contract.
    """

    def decide(self, signal_package: Dict[str, Any]) -> Dict[str, Any]:
        price = float(signal_package["price"])
        atr = float(signal_package["atr"]) if signal_package.get("atr") else 0.0
        # Simple heuristic for stub

        action = "BUY" if signal_package.get("macd_state") == "bull" else "HOLD"

        sl = price - max(atr, price*0.002)

        t1 = price + max(atr*1.0, price*0.003)

        t2 = price + max(atr*1.8, price*0.005)

        out = {

            "action": action,

            "entry": price,

            "stop_loss": round(sl, 2),

            "targets": [round(t1, 2), round(t2, 2)],

            "position_size_hint": "medium" if action == "BUY" else "none",

            "confidence": 0.6 if action == "BUY" else 0.4,

            "notes": "stub model",

        }

        # Validate JSON serializable

        json.dumps(out)

        return out
