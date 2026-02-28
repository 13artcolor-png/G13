"""
G13 Fibonacci Agent (IA)
========================
RESPONSABILITE: Trading base sur Fibonacci + ICT/SMC + Decision IA.

FLUX:
1. can_trade() -> verifie enabled, cooldown, max_positions
2. Analyse institutionnelle (patterns ICT/SMC) sur les bougies
3. Construction du prompt (marche + Fibo + ICT + sentiment)
4. Appel IA via Requesty (Claude/Grok)
5. Parse reponse -> BUY/SELL/HOLD
6. Execute seulement si l'IA decide BUY ou SELL

PARAMETRES CONFIGURABLES (dans agents.json):
- fibo_level: Niveau Fibonacci cible ("0.236", "0.382", "0.5", "0.618")
- fibo_tolerance_pct: Tolerance autour du niveau (%)
- max_positions: Nombre max de positions simultanees
- cooldown_seconds: Delai entre deux trades
"""

from typing import Dict, Optional
from .base import BaseAgent
from .ai_decision import call_ai, parse_decision
from .prompt_builder import build_opener_prompt, build_system_prompt, get_institutional_analysis
from actions.decisions import log_decision


class FiboAgent(BaseAgent):
    """
    Agent de trading Fibonacci + IA.

    Utilise l'IA pour CHAQUE decision de trading.
    L'algorithme Fibonacci fournit le contexte, l'IA decide.
    """

    def should_open_trade(self, market_data: Dict) -> Optional[Dict]:
        """
        Decide si ouvrir un trade via l'IA.

        Args:
            market_data: {
                "symbol": str,
                "price": float,
                "high": float, "low": float,
                "trend": str,
                "fibo_levels": dict,
                "spread": float,
                "candles": list (optionnel),
                "sentiment": dict (optionnel),
                "futures": dict (optionnel),
                "momentum_1m": float (optionnel),
                "momentum_5m": float (optionnel),
                "volatility_pct": float (optionnel)
            }

        Returns:
            dict si trade, None sinon
        """
        if not self.can_trade():
            return None

        price = market_data.get("price")
        fibo_levels = market_data.get("fibo_levels", {})
        spread = market_data.get("spread", 0)

        if not price or not fibo_levels:
            return None

        # Verifier le spread max AVANT d'appeler l'IA (economiser des tokens)
        tpsl = self.config.get("tpsl_config", {})
        max_spread = tpsl.get("max_spread_points", 50)
        spread_points = market_data.get("spread_points", spread)
        if spread_points > max_spread:
            return None

        # Analyse institutionnelle sur les bougies
        institutional = None
        candles = market_data.get("candles", [])
        if candles and len(candles) >= 20:
            institutional = get_institutional_analysis(candles)

        # Nombre de positions ouvertes
        open_pos_count = self.get_open_positions_count()

        # Construire les prompts
        system_prompt = build_system_prompt(self.agent_id, self.config)
        prompt = build_opener_prompt(
            market_data=market_data,
            config=self.config,
            institutional=institutional,
            sentiment=market_data.get("sentiment"),
            futures=market_data.get("futures"),
            open_positions_count=open_pos_count
        )

        # Appeler l'IA
        response = call_ai(self.agent_id, prompt, system_prompt)

        if response is None:
            print(f"[{self.agent_id}] IA indisponible -> HOLD")
            return None

        # Parser la decision
        decision = parse_decision(response)
        action = decision.get("action", "HOLD")
        reason = decision.get("reason", "")

        print(f"[{self.agent_id}] IA decide: {action} | {reason[:80]}")

        # Enregistrer la decision (BUY, SELL ou HOLD)
        executed = action in ("BUY", "SELL")
        log_decision(
            agent_id=self.agent_id,
            action=action,
            reason=reason,
            symbol=market_data.get("symbol", "BTCUSD"),
            price=price,
            executed=executed
        )

        if action == "HOLD":
            return None

        # L'IA a decide BUY ou SELL -> construire le signal
        direction = action  # "BUY" ou "SELL"

        # Calculer SL/TP en % du capital (comme CLAUDE.md l'exige)
        sl, tp = self._calculate_sl_tp_pct(price, direction)

        return {
            "symbol": market_data.get("symbol", "BTCUSD"),
            "direction": direction,
            "entry_price": price,
            "sl": sl,
            "tp": tp,
            "fibo_level": self.config.get("fibo_level", "0.236"),
            "reason": f"IA: {reason[:100]}",
            "ai_decision": decision
        }

    def _calculate_sl_tp_pct(self, entry_price: float, direction: str) -> tuple:
        """
        Calcule SL/TP en % du prix (bases sur tpsl_config).
        Utilise les % du capital definis dans agents.json.
        """
        tpsl = self.config.get("tpsl_config", {})
        sl_pct = tpsl.get("sl_pct", 0.5) / 100  # 0.5% -> 0.005
        tp_pct = tpsl.get("tp_pct", 0.3) / 100  # 0.3% -> 0.003

        if direction == "BUY":
            sl = entry_price * (1 - sl_pct)
            tp = entry_price * (1 + tp_pct)
        else:
            sl = entry_price * (1 + sl_pct)
            tp = entry_price * (1 - tp_pct)

        return round(sl, 2), round(tp, 2)

    def should_close_trade(self, position: Dict, market_data: Dict) -> bool:
        """
        Decide si fermer une position.
        Le trailing stop et break-even sont geres dans trading_loop._manage_single_position.
        """
        return False


# Classes specifiques pour chaque agent
class Fibo1Agent(FiboAgent):
    """Agent Fibo1 - Niveau 0.236"""
    def __init__(self):
        super().__init__("fibo1")


class Fibo2Agent(FiboAgent):
    """Agent Fibo2 - Niveau 0.382"""
    def __init__(self):
        super().__init__("fibo2")


class Fibo3Agent(FiboAgent):
    """Agent Fibo3 - Niveau 0.618"""
    def __init__(self):
        super().__init__("fibo3")
