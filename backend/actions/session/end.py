"""
Session End Module
==================
UNIQUE RESPONSIBILITY: End the current trading session

Usage:
    from actions.session.end import end_session
    result = end_session()
"""

import json
from pathlib import Path
from datetime import datetime

DATABASE_PATH = Path(__file__).parent.parent.parent / "database"
SESSION_FILE = DATABASE_PATH / "session.json"


def end_session(final_balance: float = None) -> dict:
    """
    End the current trading session.
    
    Args:
        final_balance: Ending balance (optional)
        
    Returns:
        dict: {
            "success": bool,
            "message": str,
            "session": dict,
            "profit": float|None
        }
    """
    try:
        # Read current session
        if not SESSION_FILE.exists():
            return {
                "success": False,
                "message": "No session file found",
                "session": None,
                "profit": None
            }
        
        with open(SESSION_FILE, "r") as f:
            session = json.load(f)
        
        if session.get("status") != "active":
            return {
                "success": False,
                "message": "No active session to end",
                "session": session,
                "profit": None
            }
        
        # Calculate profit
        profit = None
        if final_balance and session.get("balance_start"):
            profit = final_balance - session["balance_start"]
        
        # Archiver la session AVANT de la marquer comme terminee
        try:
            from actions.session.session_history import archive_session
            archive_result = archive_session()
            if archive_result["success"]:
                print(f"[Session] Session archivee: {archive_result['file_path']}")
        except Exception as archive_err:
            print(f"[Session] Erreur archivage (non bloquant): {archive_err}")

        # Update session
        session["status"] = "stopped"
        session["end_time"] = datetime.now().isoformat()
        session["balance_end"] = final_balance
        session["profit"] = profit

        # Write to file
        with open(SESSION_FILE, "w") as f:
            json.dump(session, f, indent=2)

        return {
            "success": True,
            "message": f"Session {session['id']} ended",
            "session": session,
            "profit": profit
        }
        
    except Exception as e:
        return {
            "success": False,
            "message": f"Error ending session: {str(e)}",
            "session": None,
            "profit": None
        }
