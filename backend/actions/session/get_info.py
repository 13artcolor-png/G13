"""
Session Info Module
===================
UNIQUE RESPONSIBILITY: Get current session information

Usage:
    from actions.session.get_info import get_session_info
    info = get_session_info()
"""

import json
from pathlib import Path
from datetime import datetime

DATABASE_PATH = Path(__file__).parent.parent.parent / "database"
SESSION_FILE = DATABASE_PATH / "session.json"


def get_session_info() -> dict:
    """
    Get current session information.
    
    Returns:
        dict: {
            "success": bool,
            "session": dict,
            "is_active": bool,
            "duration_seconds": int|None
        }
    """
    try:
        if not SESSION_FILE.exists():
            return {
                "success": True,
                "session": {
                    "id": None,
                    "start_time": None,
                    "balance_start": None,
                    "status": "stopped"
                },
                "is_active": False,
                "duration_seconds": None
            }
        
        with open(SESSION_FILE, "r") as f:
            session = json.load(f)
        
        is_active = session.get("status") == "active"
        
        # Calculate duration if active
        duration_seconds = None
        if is_active and session.get("start_time"):
            start = datetime.fromisoformat(session["start_time"])
            duration_seconds = int((datetime.now() - start).total_seconds())
        
        return {
            "success": True,
            "session": session,
            "is_active": is_active,
            "duration_seconds": duration_seconds
        }
        
    except Exception as e:
        return {
            "success": False,
            "session": None,
            "is_active": False,
            "duration_seconds": None
        }


def is_session_active() -> bool:
    """Quick check if session is active."""
    result = get_session_info()
    return result.get("is_active", False)
