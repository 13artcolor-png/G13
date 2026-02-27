"""
G13 Base Agent
==============
RESPONSABILITE: Classe de base pour tous les agents de trading.

Chaque agent herite de cette classe et implemente sa propre logique.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional
from abc import ABC, abstractmethod

DATABASE_PATH = Path(__file__).parent.parent / "database"
CONFIG_PATH = DATABASE_PATH / "config"


class BaseAgent(ABC):
    """
    Classe de base abstraite pour les agents de trading.

    Chaque agent doit implementer:
    - should_open_trade(): Decide si ouvrir un trade
    - should_close_trade(): Decide si fermer un trade
    """

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.config = self._load_config()
        self.last_trade_time = None
        self.is_running = False

    def _load_config(self) -> Dict:
        """Charge la configuration de l'agent."""
        config_file = CONFIG_PATH / "agents.json"

        if not config_file.exists():
            return self._default_config()

        try:
            with open(config_file, "r") as f:
                all_configs = json.load(f)
                return all_configs.get(self.agent_id, self._default_config())
        except:
            return self._default_config()

    def _default_config(self) -> Dict:
        """Configuration par defaut."""
        return {
            "name": self.agent_id.upper(),
            "enabled": True,
            "fibo_level": "0.236",
            "fibo_tolerance_pct": 2.0,
            "cooldown_seconds": 180,
            "position_size_pct": 0.01,
            "max_positions": 5
        }

    def reload_config(self):
        """Recharge la configuration depuis le fichier."""
        self.config = self._load_config()

    def is_enabled(self) -> bool:
        """Verifie si l'agent est active."""
        return self.config.get("enabled", False)

    def can_trade(self) -> bool:
        """Verifie si l'agent peut trader (cooldown respecte)."""
        if not self.is_enabled():
            return False

        if self.last_trade_time is None:
            return True

        cooldown = self.config.get("cooldown_seconds", 180)
        elapsed = (datetime.now() - self.last_trade_time).total_seconds()

        return elapsed >= cooldown

    def mark_trade_executed(self):
        """Marque qu'un trade vient d'etre execute."""
        self.last_trade_time = datetime.now()

    @abstractmethod
    def should_open_trade(self, market_data: Dict) -> Optional[Dict]:
        """
        Decide si ouvrir un trade.

        Args:
            market_data: Donnees de marche (prix, indicateurs, etc.)

        Returns:
            dict avec direction et parametres si trade, None sinon
            Exemple: {"direction": "BUY", "sl": 2900, "tp": 2950}
        """
        pass

    @abstractmethod
    def should_close_trade(self, position: Dict, market_data: Dict) -> bool:
        """
        Decide si fermer une position.

        Args:
            position: La position ouverte
            market_data: Donnees de marche actuelles

        Returns:
            True si la position doit etre fermee
        """
        pass

    def get_status(self) -> Dict:
        """Retourne le statut de l'agent."""
        return {
            "agent_id": self.agent_id,
            "name": self.config.get("name", self.agent_id),
            "enabled": self.is_enabled(),
            "can_trade": self.can_trade(),
            "is_running": self.is_running,
            "config": self.config
        }
