"""
Decision Logger
===============
Sauvegarde chaque decision IA dans database/decisions/decisions.json.
Garde les N dernieres decisions (FIFO).
"""
import json
from pathlib import Path
from datetime import datetime
from threading import Lock

DATABASE_PATH = Path(__file__).parent.parent.parent / "database"
DECISIONS_FILE = DATABASE_PATH / "decisions" / "decisions.json"
MAX_DECISIONS = 100  # Garder les 100 dernieres decisions
_file_lock = Lock()


def log_decision(agent_id: str, action: str, reason: str, symbol: str = "BTCUSD",
                 price: float = 0, executed: bool = False) -> None:
    """
    Enregistre une decision IA.

    Args:
        agent_id: fibo1, fibo2, fibo3
        action: BUY, SELL, HOLD
        reason: Raison de la decision (texte IA)
        symbol: Symbole trade
        price: Prix au moment de la decision
        executed: True si un trade a ete ouvert suite a cette decision
    """
    decision = {
        "agent_id": agent_id,
        "decision": action,
        "reason": reason,
        "symbol": symbol,
        "price": price,
        "executed": executed,
        "timestamp": datetime.now().isoformat()
    }

    with _file_lock:
        # Lire les decisions existantes
        decisions = _load_decisions()
        # Ajouter la nouvelle en tete
        decisions.insert(0, decision)
        # Limiter la taille
        decisions = decisions[:MAX_DECISIONS]
        # Sauvegarder
        _save_decisions(decisions)


def get_recent_decisions(limit: int = 10) -> list:
    """Retourne les N dernieres decisions."""
    with _file_lock:
        decisions = _load_decisions()
    return decisions[:limit]


def _load_decisions() -> list:
    """Charge les decisions depuis le fichier JSON."""
    try:
        if DECISIONS_FILE.exists():
            with open(DECISIONS_FILE, "r") as f:
                return json.load(f)
    except (json.JSONDecodeError, Exception):
        pass
    return []


def _save_decisions(decisions: list) -> None:
    """Sauvegarde les decisions dans le fichier JSON."""
    DECISIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DECISIONS_FILE, "w") as f:
        json.dump(decisions, f, indent=2)
