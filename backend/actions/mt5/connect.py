"""
MT5 Connection Module
=====================
UNIQUE RESPONSIBILITY: Connect to a MT5 account

Usage:
    from actions.mt5.connect import connect_mt5
    success = connect_mt5("fibo1")
"""

import MetaTrader5 as mt5
import json
import time
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent.parent / "database" / "config" / "mt5_accounts.json"

# Timeout pour l'initialisation MT5 (millisecondes)
MT5_TIMEOUT = 60000  # 60 secondes pour laisser le terminal demarrer


def load_mt5_config() -> dict:
    """Load MT5 accounts configuration."""
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def connect_mt5(agent_id: str) -> dict:
    """
    Connect to MT5 for a specific agent.
    Ouvre automatiquement le terminal MT5 si necessaire.

    Args:
        agent_id: The agent identifier (fibo1, fibo2, fibo3)

    Returns:
        dict: {"success": bool, "message": str, "account_info": dict|None}
    """
    config = load_mt5_config()

    if agent_id not in config:
        return {
            "success": False,
            "message": f"Agent {agent_id} not found in MT5 config",
            "account_info": None
        }

    account = config[agent_id]

    if not account.get("enabled", False):
        return {
            "success": False,
            "message": f"Agent {agent_id} is disabled",
            "account_info": None
        }

    # Parametres de connexion
    path = account.get("path") or None
    login = account["login"]
    password = account["password"]
    server = account["server"]

    # Fermer toute connexion precedente
    mt5.shutdown()

    # Initialiser MT5 avec tous les parametres (ouvre le terminal automatiquement)
    initialized = mt5.initialize(
        path=path,
        login=login,
        password=password,
        server=server,
        timeout=MT5_TIMEOUT
    )

    if not initialized:
        error = mt5.last_error()
        return {
            "success": False,
            "message": f"MT5 initialize failed for {agent_id}: {error}",
            "account_info": None
        }

    # Attendre que le terminal soit pret (petite pause)
    time.sleep(1)

    # Verifier que le login est correct
    account_info = mt5.account_info()
    if account_info is None:
        mt5.shutdown()
        return {
            "success": False,
            "message": f"Failed to get account info for {agent_id}",
            "account_info": None
        }

    # Verifier que c'est le bon compte
    if account_info.login != login:
        mt5.shutdown()
        return {
            "success": False,
            "message": f"Wrong account connected: expected {login}, got {account_info.login}",
            "account_info": None
        }

    return {
        "success": True,
        "message": f"Connected to MT5 account {login}",
        "account_info": {
            "login": account_info.login,
            "balance": account_info.balance,
            "equity": account_info.equity,
            "margin": account_info.margin,
            "margin_free": account_info.margin_free,
            "server": server
        }
    }


def disconnect_mt5() -> dict:
    """
    Disconnect from MT5.
    
    Returns:
        dict: {"success": bool, "message": str}
    """
    mt5.shutdown()
    return {
        "success": True,
        "message": "MT5 disconnected"
    }
