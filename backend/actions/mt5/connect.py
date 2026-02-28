"""
MT5 Connection Module
=====================
UNIQUE RESPONSIBILITY: Connect to a MT5 account

THREAD SAFETY:
- connect_mt5() acquiert le verrou global MT5
- disconnect_mt5() libere le verrou global MT5
- Entre les deux, aucun autre thread ne peut acceder a MT5
- Timeout de 30s sur le lock pour eviter deadlock

Usage:
    from actions.mt5.connect import connect_mt5, disconnect_mt5
    result = connect_mt5("fibo1")
    # ... operations MT5 ...
    disconnect_mt5()
"""

import MetaTrader5 as mt5
import json
import time
from pathlib import Path
from actions.mt5.mt5_lock import mt5_lock, MT5_LOCK_TIMEOUT

CONFIG_PATH = Path(__file__).parent.parent.parent / "database" / "config" / "mt5_accounts.json"

# Timeout pour l'initialisation MT5 (millisecondes)
MT5_TIMEOUT = 60000


def load_mt5_config() -> dict:
    """Load MT5 accounts configuration."""
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def connect_mt5(agent_id: str) -> dict:
    """
    Connect to MT5 for a specific agent.
    ACQUIERT le verrou global MT5 - disconnect_mt5() DOIT etre appele apres.

    Args:
        agent_id: The agent identifier (fibo1, fibo2, fibo3)

    Returns:
        dict: {"success": bool, "message": str, "account_info": dict|None}
    """
    # Acquerir le verrou (bloque si un autre thread utilise MT5)
    acquired = mt5_lock.acquire(timeout=MT5_LOCK_TIMEOUT)
    if not acquired:
        return {
            "success": False,
            "message": f"MT5 lock timeout ({MT5_LOCK_TIMEOUT}s) pour {agent_id}",
            "account_info": None
        }

    try:
        config = load_mt5_config()

        if agent_id not in config:
            mt5_lock.release()
            return {
                "success": False,
                "message": f"Agent {agent_id} not found in MT5 config",
                "account_info": None
            }

        account = config[agent_id]

        if not account.get("enabled", False):
            mt5_lock.release()
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

        # Initialiser MT5
        initialized = mt5.initialize(
            path=path,
            login=login,
            password=password,
            server=server,
            timeout=MT5_TIMEOUT
        )

        if not initialized:
            error = mt5.last_error()
            mt5_lock.release()
            return {
                "success": False,
                "message": f"MT5 init failed {agent_id}: {error}",
                "account_info": None
            }

        # Attendre que le terminal soit pret
        time.sleep(1)

        # Verifier le login
        account_info = mt5.account_info()
        if account_info is None:
            mt5.shutdown()
            mt5_lock.release()
            return {
                "success": False,
                "message": f"No account info for {agent_id}",
                "account_info": None
            }

        if account_info.login != login:
            mt5.shutdown()
            mt5_lock.release()
            return {
                "success": False,
                "message": f"Wrong account: expected {login}, got {account_info.login}",
                "account_info": None
            }

        # Succes - lock reste acquis jusqu'a disconnect_mt5()
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

    except Exception as e:
        try:
            mt5_lock.release()
        except RuntimeError:
            pass
        return {
            "success": False,
            "message": f"MT5 connect exception {agent_id}: {e}",
            "account_info": None
        }


def disconnect_mt5() -> dict:
    """
    Disconnect from MT5 et LIBERE le verrou global.
    DOIT etre appele apres chaque connect_mt5() reussi.
    """
    mt5.shutdown()
    try:
        mt5_lock.release()
    except RuntimeError:
        pass
    return {
        "success": True,
        "message": "MT5 disconnected"
    }
