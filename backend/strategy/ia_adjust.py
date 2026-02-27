"""
G13 IA Adjust
=============
RESPONSABILITE: Appliquer automatiquement les ajustements suggeres par le Strategist.

IMPORTANT: Ce fichier est concu pour etre facilement modifiable.
Chaque action d'ajustement est clairement separee.

Usage:
    from strategy.ia_adjust import IAdjust
    adjuster = IAdjust()
    result = adjuster.auto_adjust("fibo1")
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

DATABASE_PATH = Path(__file__).parent.parent / "database"
CONFIG_PATH = DATABASE_PATH / "config"


class IAdjust:
    """
    Applique automatiquement les ajustements de parametres.

    REGLES MODIFIABLES:
    - TOLERANCE_STEP: Pas d'ajustement pour fibo_tolerance_pct
    - TOLERANCE_MIN/MAX: Limites de tolerance
    - COOLDOWN_STEP: Pas d'ajustement pour cooldown
    - AUTO_ADJUST_ENABLED: Activer/desactiver l'auto-ajustement
    """

    # ===== PARAMETRES MODIFIABLES =====
    AUTO_ADJUST_ENABLED = True

    TOLERANCE_STEP = 0.5      # Pas d'ajustement (%)
    TOLERANCE_MIN = 0.5       # Minimum tolerance (%)
    TOLERANCE_MAX = 5.0       # Maximum tolerance (%)

    COOLDOWN_STEP = 30        # Pas d'ajustement (secondes)
    COOLDOWN_MIN = 60         # Minimum cooldown (secondes)
    COOLDOWN_MAX = 600        # Maximum cooldown (secondes)

    MIN_TRADES_BEFORE_ADJUST = 5  # Trades minimum avant ajustement
    # ==================================

    def __init__(self):
        self.adjustments_log = []

    def auto_adjust(self, agent_id: str, suggestions: List[Dict] = None) -> Dict:
        """
        Applique automatiquement les ajustements necessaires.

        Args:
            agent_id: L'identifiant de l'agent
            suggestions: Liste des suggestions du Strategist (optionnel)

        Returns:
            dict: {
                "success": bool,
                "adjustments": List[dict],
                "message": str
            }
        """
        if not self.AUTO_ADJUST_ENABLED:
            return {
                "success": True,
                "adjustments": [],
                "message": "Auto-adjust desactive"
            }

        # Charger la config de l'agent
        config = self._load_agent_config(agent_id)
        if not config:
            return {
                "success": False,
                "adjustments": [],
                "message": f"Config non trouvee pour {agent_id}"
            }

        adjustments = []

        # Traiter chaque suggestion
        if suggestions:
            for suggestion in suggestions:
                adjustment = self._apply_suggestion(agent_id, config, suggestion)
                if adjustment:
                    adjustments.append(adjustment)

        # Sauvegarder si des ajustements ont ete faits
        if adjustments:
            self._save_agent_config(agent_id, config)
            self._log_adjustments(agent_id, adjustments)

        return {
            "success": True,
            "adjustments": adjustments,
            "message": f"{len(adjustments)} ajustements appliques"
        }

    def _apply_suggestion(self, agent_id: str, config: Dict, suggestion: Dict) -> Optional[Dict]:
        """
        Applique une suggestion specifique.

        MODIFIABLE: Ajouter de nouveaux types de suggestions ici.
        """
        suggestion_type = suggestion.get("type", "")

        # AJUSTEMENT 1: Reduire la tolerance
        if suggestion_type == "REDUCE_TOLERANCE":
            return self._reduce_tolerance(config)

        # AJUSTEMENT 2: Augmenter la tolerance
        elif suggestion_type == "INCREASE_TOLERANCE":
            return self._increase_tolerance(config)

        # AJUSTEMENT 3: Augmenter le cooldown
        elif suggestion_type == "INCREASE_COOLDOWN":
            return self._increase_cooldown(config)

        # AJUSTEMENT 4: Reduire le cooldown
        elif suggestion_type == "REDUCE_COOLDOWN":
            return self._reduce_cooldown(config)

        return None

    def _reduce_tolerance(self, config: Dict) -> Optional[Dict]:
        """Reduit fibo_tolerance_pct."""
        current = config.get("fibo_tolerance_pct", 2.0)
        new_value = max(self.TOLERANCE_MIN, current - self.TOLERANCE_STEP)

        if new_value == current:
            return None

        config["fibo_tolerance_pct"] = round(new_value, 2)

        return {
            "type": "REDUCE_TOLERANCE",
            "field": "fibo_tolerance_pct",
            "old_value": current,
            "new_value": new_value,
            "timestamp": datetime.now().isoformat()
        }

    def _increase_tolerance(self, config: Dict) -> Optional[Dict]:
        """Augmente fibo_tolerance_pct."""
        current = config.get("fibo_tolerance_pct", 2.0)
        new_value = min(self.TOLERANCE_MAX, current + self.TOLERANCE_STEP)

        if new_value == current:
            return None

        config["fibo_tolerance_pct"] = round(new_value, 2)

        return {
            "type": "INCREASE_TOLERANCE",
            "field": "fibo_tolerance_pct",
            "old_value": current,
            "new_value": new_value,
            "timestamp": datetime.now().isoformat()
        }

    def _increase_cooldown(self, config: Dict) -> Optional[Dict]:
        """Augmente cooldown_seconds."""
        current = config.get("cooldown_seconds", 180)
        new_value = min(self.COOLDOWN_MAX, current + self.COOLDOWN_STEP)

        if new_value == current:
            return None

        config["cooldown_seconds"] = new_value

        return {
            "type": "INCREASE_COOLDOWN",
            "field": "cooldown_seconds",
            "old_value": current,
            "new_value": new_value,
            "timestamp": datetime.now().isoformat()
        }

    def _reduce_cooldown(self, config: Dict) -> Optional[Dict]:
        """Reduit cooldown_seconds."""
        current = config.get("cooldown_seconds", 180)
        new_value = max(self.COOLDOWN_MIN, current - self.COOLDOWN_STEP)

        if new_value == current:
            return None

        config["cooldown_seconds"] = new_value

        return {
            "type": "REDUCE_COOLDOWN",
            "field": "cooldown_seconds",
            "old_value": current,
            "new_value": new_value,
            "timestamp": datetime.now().isoformat()
        }

    def _load_agent_config(self, agent_id: str) -> Optional[Dict]:
        """Charge la config d'un agent."""
        config_file = CONFIG_PATH / "agents.json"

        if not config_file.exists():
            return None

        try:
            with open(config_file, "r") as f:
                all_configs = json.load(f)
                return all_configs.get(agent_id)
        except:
            return None

    def _save_agent_config(self, agent_id: str, config: Dict):
        """Sauvegarde la config d'un agent."""
        config_file = CONFIG_PATH / "agents.json"

        try:
            with open(config_file, "r") as f:
                all_configs = json.load(f)

            all_configs[agent_id] = config

            with open(config_file, "w") as f:
                json.dump(all_configs, f, indent=4)
        except Exception as e:
            print(f"[IA Adjust] Erreur sauvegarde config: {e}")

    def _log_adjustments(self, agent_id: str, adjustments: List[Dict]):
        """Log les ajustements effectues."""
        log_file = DATABASE_PATH / "adjustments_log.json"

        try:
            existing = []
            if log_file.exists():
                with open(log_file, "r") as f:
                    existing = json.load(f)

            for adj in adjustments:
                adj["agent_id"] = agent_id
                existing.insert(0, adj)

            # Garder les 100 derniers
            existing = existing[:100]

            with open(log_file, "w") as f:
                json.dump(existing, f, indent=2)
        except Exception as e:
            print(f"[IA Adjust] Erreur log: {e}")

    def get_recent_adjustments(self, limit: int = 20) -> List[Dict]:
        """Retourne les ajustements recents."""
        log_file = DATABASE_PATH / "adjustments_log.json"

        if not log_file.exists():
            return []

        try:
            with open(log_file, "r") as f:
                return json.load(f)[:limit]
        except:
            return []

    def manual_adjust(self, agent_id: str, field: str, value) -> Dict:
        """
        Ajustement manuel d'un parametre.

        Args:
            agent_id: L'identifiant de l'agent
            field: Le champ a modifier
            value: La nouvelle valeur

        Returns:
            dict: {"success": bool, "message": str}
        """
        config = self._load_agent_config(agent_id)
        if not config:
            return {"success": False, "message": "Agent non trouve"}

        old_value = config.get(field)
        config[field] = value

        self._save_agent_config(agent_id, config)

        adjustment = {
            "type": "MANUAL_ADJUST",
            "field": field,
            "old_value": old_value,
            "new_value": value,
            "timestamp": datetime.now().isoformat()
        }
        self._log_adjustments(agent_id, [adjustment])

        return {
            "success": True,
            "message": f"{field}: {old_value} -> {value}"
        }


# Singleton
_ia_adjust = None

def get_ia_adjust() -> IAdjust:
    """Retourne l'instance IAdjust singleton."""
    global _ia_adjust
    if _ia_adjust is None:
        _ia_adjust = IAdjust()
    return _ia_adjust
