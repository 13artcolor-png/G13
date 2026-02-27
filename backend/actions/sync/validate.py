"""
Validation Module
=================
UNIQUE RESPONSIBILITY: Validate local data against MT5 (source of truth)

Usage:
    from actions.sync.validate import validate_positions
    result = validate_positions("fibo1")
"""

import json
from pathlib import Path
from actions.mt5.read_positions import read_positions

DATABASE_PATH = Path(__file__).parent.parent.parent / "database"


def validate_positions(agent_id: str) -> dict:
    """
    Validate local positions against MT5.
    
    Args:
        agent_id: The agent identifier
        
    Returns:
        dict: {
            "valid": bool,
            "message": str,
            "local_count": int,
            "mt5_count": int,
            "missing_locally": List[int],
            "extra_locally": List[int]
        }
    
    Note: MT5 must be connected before calling this function.
    """
    try:
        # Read MT5 positions
        mt5_result = read_positions(agent_id)
        
        if not mt5_result["success"]:
            return {
                "valid": False,
                "message": mt5_result["message"],
                "local_count": 0,
                "mt5_count": 0,
                "missing_locally": [],
                "extra_locally": []
            }
        
        mt5_tickets = {p["ticket"] for p in mt5_result["positions"]}
        
        # Read local positions
        file_path = DATABASE_PATH / "open_positions" / f"{agent_id}.json"
        local_positions = []
        
        if file_path.exists():
            with open(file_path, "r") as f:
                local_positions = json.load(f)
        
        local_tickets = {p["ticket"] for p in local_positions}
        
        # Find discrepancies
        missing_locally = list(mt5_tickets - local_tickets)
        extra_locally = list(local_tickets - mt5_tickets)
        
        is_valid = len(missing_locally) == 0 and len(extra_locally) == 0
        
        if is_valid:
            message = f"Validation OK: {len(mt5_tickets)} positions match"
        else:
            message = f"Validation FAILED: {len(missing_locally)} missing, {len(extra_locally)} extra"
        
        return {
            "valid": is_valid,
            "message": message,
            "local_count": len(local_tickets),
            "mt5_count": len(mt5_tickets),
            "missing_locally": missing_locally,
            "extra_locally": extra_locally
        }
        
    except Exception as e:
        return {
            "valid": False,
            "message": f"Validation error: {str(e)}",
            "local_count": 0,
            "mt5_count": 0,
            "missing_locally": [],
            "extra_locally": []
        }


def auto_fix_positions(agent_id: str) -> dict:
    """
    Automatically fix local positions to match MT5.
    Simply re-syncs from MT5 (the source of truth).
    
    Args:
        agent_id: The agent identifier
        
    Returns:
        dict: {"success": bool, "message": str}
    """
    from actions.sync.sync_positions import sync_positions
    return sync_positions(agent_id)
