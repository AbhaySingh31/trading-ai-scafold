
from __future__ import annotations
from typing import Dict, Any
class LLMClient:
    def decide(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        price = float(signal["price"]); atr = float(signal.get("atr", 0.0) or 0.0)
        if atr <= 0: atr = max(price*0.001, 10)
        entry = price; sl = price - 3*atr; t1 = price + 1.5*atr; t2 = price + 3.0*atr
        return {"action":"BUY","entry":entry,"stop_loss":sl,"targets":[t1,t2],"confidence":0.6,"notes":"stub model"}
