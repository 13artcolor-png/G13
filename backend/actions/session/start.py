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


def start_session(initial_balance: float = None) -> dict:
    """
    Start a new trading session.

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
                "success": True,  # Changed to True - session is ready
                "message": "Session already active",
                "session": current
            }
        
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
        
        return {
            "success": True,
            "message": f"Session {session_id} started",
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
