"""
G13 Strategist
==============
RESPONSABILITE: Analyser les performances et suggerer des ajustements.

IMPORTANT: Ce fichier est concu pour etre facilement modifiable.
Chaque regle de decision est clairement separee et documentee.

Usage:
    from strategy.strategist import Strategist
    strategist = Strategist()
    analysis = strategist.analyze("fibo1")
    suggestions = strategist.get_suggestions("fibo1")
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

DATABASE_PATH = Path(__file__).parent.parent / "database"


class Strategist:
    """
    Analyse les performances de trading et genere des suggestions.

    REGLES MODIFIABLES:
    - MIN_TRADES_FOR_ANALYSIS: Nombre minimum de trades pour analyser
    - WIN_RATE_THRESHOLDS: Seuils pour les suggestions
    - PROFIT_FACTOR_THRESHOLDS: Seuils profit factor
    """

    # ===== PARAMETRES MODIFIABLES =====
    MIN_TRADES_FOR_ANALYSIS = 5

    WIN_RATE_THRESHOLDS = {
        "critical": 30,    # En dessous: probleme critique
        "warning": 45,     # En dessous: attention
        "good": 55,        # Au dessus: bon
        "excellent": 70    # Au dessus: excellent
    }

    PROFIT_FACTOR_THRESHOLDS = {
        "critical": 0.5,   # En dessous: tres perdant
        "warning": 1.0,    # En dessous: perdant
        "good": 1.5,       # Au dessus: profitable
        "excellent": 2.0   # Au dessus: tres profitable
    }
    # ==================================

    def __init__(self):
        self.last_analysis = {}

    def analyze(self, agent_id: str) -> Dict:
        """
        Analyse complete des performances d'un agent.

        Args:
            agent_id: L'identifiant de l'agent (fibo1, fibo2, fibo3)

        Returns:
            dict: {
                "success": bool,
                "stats": dict,
                "evaluation": str,
                "suggestions": List[dict]
            }
        """
        trades = self._load_closed_trades(agent_id)

        if len(trades) < self.MIN_TRADES_FOR_ANALYSIS:
            return {
                "success": True,
                "stats": {},
                "evaluation": "insufficient_data",
                "message": f"Besoin de {self.MIN_TRADES_FOR_ANALYSIS} trades minimum ({len(trades)} actuellement)",
                "suggestions": []
            }

        stats = self._calculate_stats(trades)
        evaluation = self._evaluate_performance(stats)
        suggestions = self._generate_suggestions(agent_id, stats, evaluation)

        self.last_analysis[agent_id] = {
            "stats": stats,
            "evaluation": evaluation,
            "timestamp": datetime.now().isoformat()
        }

        return {
            "success": True,
            "stats": stats,
            "evaluation": evaluation,
            "suggestions": suggestions
        }

    def _load_closed_trades(self, agent_id: str) -> List[Dict]:
        """Charge les trades clotures depuis le fichier local."""
        file_path = DATABASE_PATH / "closed_trades" / f"{agent_id}.json"

        if not file_path.exists():
            return []

        try:
            with open(file_path, "r") as f:
                return json.load(f)
        except:
            return []

    def _calculate_stats(self, trades: List[Dict]) -> Dict:
        """Calcule les statistiques de trading."""
        if not trades:
            return {}

        profits = [t.get("profit", 0) for t in trades]
        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p < 0]

        total_wins = sum(wins) if wins else 0
        total_losses = abs(sum(losses)) if losses else 0

        return {
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "winrate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
            "total_profit": round(sum(profits), 2),
            "avg_win": round(total_wins / len(wins), 2) if wins else 0,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
            "profit_factor": round(total_wins / total_losses, 2) if total_losses > 0 else 0,
            "best_trade": round(max(profits), 2) if profits else 0,
            "worst_trade": round(min(profits), 2) if profits else 0
        }

    def _evaluate_performance(self, stats: Dict) -> str:
        """
        Evalue la performance globale.

        MODIFIABLE: Ajuster les seuils dans WIN_RATE_THRESHOLDS et PROFIT_FACTOR_THRESHOLDS
        """
        winrate = stats.get("winrate", 0)
        pf = stats.get("profit_factor", 0)

        # Evaluation basee sur winrate
        if winrate < self.WIN_RATE_THRESHOLDS["critical"]:
            return "critical"
        elif winrate < self.WIN_RATE_THRESHOLDS["warning"]:
            return "warning"
        elif winrate >= self.WIN_RATE_THRESHOLDS["excellent"]:
            return "excellent"
        elif winrate >= self.WIN_RATE_THRESHOLDS["good"]:
            return "good"

        # Si winrate neutre, verifier profit factor
        if pf < self.PROFIT_FACTOR_THRESHOLDS["warning"]:
            return "warning"
        elif pf >= self.PROFIT_FACTOR_THRESHOLDS["good"]:
            return "good"

        return "neutral"

    def _generate_suggestions(self, agent_id: str, stats: Dict, evaluation: str) -> List[Dict]:
        """
        Genere des suggestions d'amelioration.

        MODIFIABLE: Ajouter/modifier les regles de suggestions ici.
        """
        suggestions = []

        # REGLE 1: Winrate critique -> Resserrer les entrees
        if evaluation == "critical":
            suggestions.append({
                "priority": "high",
                "type": "REDUCE_TOLERANCE",
                "message": f"Winrate critique ({stats['winrate']}%). Reduire fibo_tolerance_pct.",
                "suggested_action": "Diminuer fibo_tolerance_pct de 0.5%"
            })

        # REGLE 2: Profit factor < 1 -> Ajuster TP/SL
        if stats.get("profit_factor", 0) < 1.0 and stats.get("total_trades", 0) >= 10:
            suggestions.append({
                "priority": "high",
                "type": "ADJUST_TPSL",
                "message": f"Profit factor negatif ({stats['profit_factor']}). Les pertes depassent les gains.",
                "suggested_action": "Augmenter TP ou reduire SL"
            })

        # REGLE 3: Avg loss > 2x avg win -> Probleme de gestion du risque
        avg_win = stats.get("avg_win", 0)
        avg_loss = abs(stats.get("avg_loss", 0))
        if avg_loss > avg_win * 2 and avg_win > 0:
            suggestions.append({
                "priority": "medium",
                "type": "RISK_MANAGEMENT",
                "message": f"Perte moyenne ({avg_loss}) trop elevee vs gain moyen ({avg_win}).",
                "suggested_action": "Reduire le SL ou ameliorer les points d'entree"
            })

        # REGLE 4: Excellent -> Peut augmenter le risque
        if evaluation == "excellent" and stats.get("total_trades", 0) >= 20:
            suggestions.append({
                "priority": "low",
                "type": "INCREASE_RISK",
                "message": f"Excellente performance ({stats['winrate']}% WR). Peut augmenter l'exposition.",
                "suggested_action": "Augmenter position_size_pct prudemment"
            })

        return suggestions

    def get_all_agents_analysis(self) -> Dict:
        """Analyse tous les agents."""
        return {
            "fibo1": self.analyze("fibo1"),
            "fibo2": self.analyze("fibo2"),
            "fibo3": self.analyze("fibo3")
        }

    def get_quick_summary(self) -> Dict:
        """Resume rapide pour le dashboard."""
        all_stats = self.get_all_agents_analysis()

        total_trades = 0
        total_profit = 0
        best_agent = None
        best_winrate = 0

        for agent_id, data in all_stats.items():
            stats = data.get("stats", {})
            total_trades += stats.get("total_trades", 0)
            total_profit += stats.get("total_profit", 0)

            wr = stats.get("winrate", 0)
            if wr > best_winrate:
                best_winrate = wr
                best_agent = agent_id

        return {
            "total_trades": total_trades,
            "total_profit": round(total_profit, 2),
            "best_agent": best_agent,
            "best_winrate": best_winrate,
            "updated_at": datetime.now().isoformat()
        }


# Singleton
_strategist = None

def get_strategist() -> Strategist:
    """Retourne l'instance Strategist singleton."""
    global _strategist
    if _strategist is None:
        _strategist = Strategist()
    return _strategist
