"""
Session Start Module
====================
UNIQUE RESPONSIBILITY: Start a new trading session
Usage:
    from actions.session.start import start_session
    result = start_session()
"""
import json
import uuid
from pathlib import Path
from datetime import datetime

DATABASE_PATH = Path(__file__).parent.parent.parent / "database"
SESSION_FILE = DATABASE_PATH / "session.json"


def _reset_all_data():
    """
    Reset ALL historical data for a fresh session.
    Clears: closed_trades, stats, open_positions, decisions, logs.
    Preserves: config/ (agents.json, api_keys.json, etc.)
    """
    folders_to_clear = [
        "closed_trades",
        "stats",
        "open_positions",
        "decisions",
        "logs",
    ]

    for folder_name in folders_to_clear:
        folder = DATABASE_PATH / folder_name
        if not folder.exists():
            continue

        for f in folder.iterdir():
            if f.is_file() and f.suffix == ".json":
                if folder_name == "stats":
                    # Reset stats to zero structure
                    agent_id = f.stem  # fibo1, fibo2, fibo3
                    empty_stats = {
                        "agent_id": agent_id,
                        "total_trades": 0,
                        "wins": 0,
                        "losses": 0,
                        "breakeven": 0,
                        "winrate": 0.0,
                        "total_profit": 0.0,
                        "avg_win": 0.0,
                        "avg_loss": 0.0,
                        "risk_reward": 0.0,
                        "updated_at": datetime.now().isoformat()
                    }
                    with open(f, "w") as fh:
                        json.dump(empty_stats, fh, indent=2)
                elif folder_name in ("closed_trades", "open_positions"):
                    # Reset to empty list
                    with open(f, "w") as fh:
                        json.dump([], fh, indent=2)
                else:
                    # decisions, logs: delete file
                    f.unlink()

    print(f"[Session] All data reset for new session")


def start_session(initial_balance: float = None) -> dict:
    """
    Start a new trading session.

    If a session is already active AND has no balance yet, update it.
    If a session is already active WITH balance, end it first then create new.
    If no session active, create a fresh one with full data reset.

    Args:
        initial_balance: Starting balance (optional, can be fetched from MT5)

    Returns:
        dict: {
            "success": bool,
            "message": str,
            "session": dict
        }
    """
    try:
        # Check if session already active
        current = get_session_raw()

        if current.get("status") == "active":
            # Si balance fournie et session sans balance, mettre a jour
            if initial_balance and not current.get("balance_start"):
                current["balance_start"] = initial_balance
                with open(SESSION_FILE, "w") as f:
                    json.dump(current, f, indent=2)
                return {
                    "success": True,
                    "message": f"Session {current.get('id')} updated with balance",
                    "session": current
                }
            return {
                "success": True,
                "message": "Session already active",
                "session": current
            }

        # === NEW SESSION ===
        # Reset all historical data
        _reset_all_data()

        # Create new session
        session_id = str(uuid.uuid4())[:8]
        session = {
            "id": session_id,
            "start_time": datetime.now().isoformat(),
            "balance_start": initial_balance,
            "status": "active"
        }

        # Write to file
        with open(SESSION_FILE, "w") as f:
            json.dump(session, f, indent=2)

        print(f"[Session] New session {session_id} started (data reset)")

        return {
            "success": True,
            "message": f"Session {session_id} started (all data reset)",
            "session": session
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Error starting session: {str(e)}",
            "session": None
        }


def get_session_raw() -> dict:
    """Read raw session data from file."""
    try:
        if SESSION_FILE.exists():
            with open(SESSION_FILE, "r") as f:
                return json.load(f)
        return {"id": None, "start_time": None, "balance_start": None, "status": "stopped"}
    except:
        return {"id": None, "start_time": None, "balance_start": None, "status": "stopped"}
