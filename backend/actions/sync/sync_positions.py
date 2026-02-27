"""
Sync Positions Module
=====================
UNIQUE RESPONSIBILITY: Sync MT5 positions to local open_positions/{agent}.json

Usage:
    from actions.sync.sync_positions import sync_positions
    result = sync_positions("fibo1")
"""

import json
from pathlib import Path
from datetime import datetime
from actions.mt5.read_positions import read_positions

DATABASE_PATH = Path(__file__).parent.parent.parent / "database"


def sync_positions(agent_id: str) -> dict:
    """
    Sync MT5 positions to local JSON file.
    MT5 is the single source of truth.
    
    Args:
        agent_id: The agent identifier (fibo1, fibo2, fibo3)
        
    Returns:
        dict: {
            "success": bool,
            "message": str,
            "positions_count": int,
            "positions": List[dict]
        }
    
    Note: MT5 must be connected before calling this function.
    """
    try:
        # Read positions from MT5
        mt5_result = read_positions(agent_id)
        
        if not mt5_result["success"]:
            return {
                "success": False,
                "message": mt5_result["message"],
                "positions_count": 0,
                "positions": []
            }
        
        positions = mt5_result["positions"]
        
        # Add sync metadata
        for pos in positions:
            pos["synced_at"] = datetime.now().isoformat()
            pos["agent_id"] = agent_id
        
        # Write to local file
        file_path = DATABASE_PATH / "open_positions" / f"{agent_id}.json"
        with open(file_path, "w") as f:
            json.dump(positions, f, indent=2)
        
        return {
            "success": True,
            "message": f"Synced {len(positions)} positions for {agent_id}",
            "positions_count": len(positions),
            "positions": positions
        }
        
    except Exception as e:
        return {
            "success": False,
            "message": f"Error syncing positions: {str(e)}",
            "positions_count": 0,
            "positions": []
        }


def get_local_positions(agent_id: str) -> dict:
    """
    Read positions from local JSON file.
    
    Args:
        agent_id: The agent identifier
        
    Returns:
        dict: {
            "success": bool,
            "positions": List[dict],
            "count": int
        }
    """
    try:
        file_path = DATABASE_PATH / "open_positions" / f"{agent_id}.json"
        
        if not file_path.exists():
            return {
                "success": True,
                "positions": [],
                "count": 0
            }
        
        with open(file_path, "r") as f:
            positions = json.load(f)
        
        return {
            "success": True,
            "positions": positions,
            "count": len(positions)
        }
        
    except Exception as e:
        return {
            "success": False,
            "positions": [],
            "count": 0
        }
