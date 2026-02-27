"""
G13 Fibonacci Agent
===================
RESPONSABILITE: Trading base sur les niveaux Fibonacci + ICT/SMC.

IMPORTANT: Ce fichier contient la logique de trading.
Les parametres sont dans database/config/agents.json.
"""

from typing import Dict, Optional
from .base import BaseAgent


class FiboAgent(BaseAgent):
    """
    Agent de trading Fibonacci.

    STRATEGIE:
    - Entre quand le prix atteint un niveau Fibonacci avec tolerance
    - Utilise ICT/SMC pour confirmer la direction
    - TP/SL bases sur le niveau Fibonacci suivant

    PARAMETRES CONFIGURABLES (dans agents.json):
    - fibo_level: Niveau Fibonacci cible ("0.236", "0.382", "0.5", "0.618")
    - fibo_tolerance_pct: Tolerance autour du niveau (%)
    - signal_timeframe: Timeframe pour l'analyse ("M1", "M5", "M15")
    """

    # Niveaux Fibonacci standards
    FIBO_LEVELS = {
        "0.236": 0.236,
        "0.382": 0.382,
        "0.5": 0.5,
        "0.618": 0.618,
        "0.786": 0.786
    }

    def should_open_trade(self, market_data: Dict) -> Optional[Dict]:
        """
        Decide si ouvrir un trade base sur Fibonacci.

        Args:
            market_data: {
                "symbol": str,
                "price": float,
                "high": float,
                "low": float,
                "trend": str ("bullish", "bearish", "neutral"),
                "fibo_levels": dict  # Calcules par le market data provider
            }

        Returns:
            dict si trade, None sinon
        """
        if not self.can_trade():
            return None

        price = market_data.get("price")
        fibo_levels = market_data.get("fibo_levels", {})
        trend = market_data.get("trend", "neutral")

        if not price or not fibo_levels:
            return None

        # Niveau Fibonacci cible
        target_level = self.config.get("fibo_level", "0.236")
        target_price = fibo_levels.get(target_level)

        if not target_price:
            return None

        # Calculer la tolerance
        tolerance_pct = self.config.get("fibo_tolerance_pct", 2.0)
        tolerance = target_price * (tolerance_pct / 100)

        # Verifier si le prix est proche du niveau Fibonacci
        distance = abs(price - target_price)

        if distance > tolerance:
            return None

        # Determiner la direction basee sur la tendance
        direction = self._determine_direction(price, target_price, trend)

        if not direction:
            return None

        # Calculer SL et TP
        sl, tp = self._calculate_sl_tp(price, direction, fibo_levels)

        return {
            "symbol": market_data.get("symbol", "BTCUSD"),
            "direction": direction,
            "entry_price": price,
            "sl": sl,
            "tp": tp,
            "fibo_level": target_level,
            "reason": f"Prix proche du niveau Fibo {target_level} ({target_price:.2f})"
        }

    def _determine_direction(self, price: float, fibo_price: float, trend: str) -> Optional[str]:
        """
        Determine la direction du trade.

        MODIFIABLE: Ajuster la logique de direction ici.
        """
        # Si le prix est AU-DESSUS du niveau Fibo -> potentiel SELL (retour vers le niveau)
        # Si le prix est EN-DESSOUS du niveau Fibo -> potentiel BUY (retour vers le niveau)

        if trend == "bullish" and price < fibo_price:
            return "BUY"
        elif trend == "bearish" and price > fibo_price:
            return "SELL"
        elif trend == "neutral":
            # En range, trader le rebond sur le niveau
            if price < fibo_price:
                return "BUY"
            else:
                return "SELL"

        return None

    def _calculate_sl_tp(self, entry_price: float, direction: str, fibo_levels: Dict) -> tuple:
        """
        Calcule le Stop Loss et Take Profit.

        MODIFIABLE: Ajuster les ratios SL/TP ici.
        """
        # SL: 1% du prix d'entree
        # TP: 2% du prix d'entree (ratio 1:2)

        sl_pct = 0.01
        tp_pct = 0.02

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

        Args:
            position: {
                "ticket": int,
                "direction": str,
                "profit": float,
                "time": int  # timestamp ouverture
            }
            market_data: Donnees de marche actuelles

        Returns:
            True si doit fermer
        """
        # Fermer si profit > seuil ou perte > seuil
        profit = position.get("profit", 0)
        min_hold_seconds = self.config.get("min_hold_seconds", 300)

        # Ne pas fermer avant le temps minimum de hold
        open_time = position.get("time", 0)
        from datetime import datetime
        elapsed = (datetime.now().timestamp() - open_time) if open_time else 0

        if elapsed < min_hold_seconds:
            return False

        # Conditions de fermeture
        # TODO: Ajouter la logique de trailing stop, etc.

        return False


# Classes specifiques pour chaque agent (si besoin de personnalisation)
class Fibo1Agent(FiboAgent):
    """Agent Fibo1 - peut avoir des regles specifiques."""

    def __init__(self):
        super().__init__("fibo1")


class Fibo2Agent(FiboAgent):
    """Agent Fibo2 - peut avoir des regles specifiques."""

    def __init__(self):
        super().__init__("fibo2")


class Fibo3Agent(FiboAgent):
    """Agent Fibo3 - peut avoir des regles specifiques."""

    def __init__(self):
        super().__init__("fibo3")
