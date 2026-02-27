"""
Sync Closed Trades Module
=========================
UNIQUE RESPONSIBILITY: Sync MT5 history to local closed_trades/{agent}.json

Usage:
    from actions.sync.sync_closed import sync_closed_trades
    result = sync_closed_trades("fibo1")
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from actions.mt5.read_history import read_history

DATABASE_PATH = Path(__file__).parent.parent.parent / "database"


def sync_closed_trades(agent_id: str, from_date: datetime = None) -> dict:
    """
    Sync MT5 closed deals to local JSON file.
    Only adds new trades (avoids duplicates).
    
    Args:
        agent_id: The agent identifier (fibo1, fibo2, fibo3)
        from_date: Start date for sync (default: 30 days ago)
        
    Returns:
        dict: {
            "success": bool,
            "message": str,
            "new_trades": int,
            "total_trades": int
        }
    
    Note: MT5 must be connected before calling this function.
    """
    try:
        # Read existing local trades
        file_path = DATABASE_PATH / "closed_trades" / f"{agent_id}.json"
        
        existing_trades = []
        existing_tickets = set()
        
        if file_path.exists():
            with open(file_path, "r") as f:
                existing_trades = json.load(f)
                existing_tickets = {t["ticket"] for t in existing_trades}
        
        # Read history from MT5
        mt5_result = read_history(agent_id, from_date=from_date)
        
        if not mt5_result["success"]:
            return {
                "success": False,
                "message": mt5_result["message"],
                "new_trades": 0,
                "total_trades": len(existing_trades)
            }
        
        # Add only new trades
        new_trades_count = 0
        for deal in mt5_result["deals"]:
            if deal["ticket"] not in existing_tickets:
                deal["synced_at"] = datetime.now().isoformat()
                deal["agent_id"] = agent_id
                existing_trades.append(deal)
                existing_tickets.add(deal["ticket"])
                new_trades_count += 1
        
        # Sort by time (most recent first)
        existing_trades.sort(key=lambda x: x.get("time", 0), reverse=True)
        
        # Write to local file
        with open(file_path, "w") as f:
            json.dump(existing_trades, f, indent=2)
        
        return {
            "success": True,
            "message": f"Added {new_trades_count} new trades for {agent_id}",
            "new_trades": new_trades_count,
            "total_trades": len(existing_trades)
        }
        
    except Exception as e:
        return {
            "success": False,
            "message": f"Error syncing closed trades: {str(e)}",
            "new_trades": 0,
            "total_trades": 0
        }


def get_local_closed_trades(agent_id: str, limit: int = None) -> dict:
    """
    Read closed trades from local JSON file.
    
    Args:
        agent_id: The agent identifier
        limit: Max number of trades to return (most recent first)
        
    Returns:
        dict: {
            "success": bool,
            "trades": List[dict],
            "count": int
        }
    """
    try:
        file_path = DATABASE_PATH / "closed_trades" / f"{agent_id}.json"
        
        if not file_path.exists():
            return {
                "success": True,
                "trades": [],
                "count": 0
            }
        
        with open(file_path, "r") as f:
            trades = json.load(f)
        
        if limit:
            trades = trades[:limit]
        
        return {
            "success": True,
            "trades": trades,
            "count": len(trades)
        }
        
    except Exception as e:
        return {
            "success": False,
            "trades": [],
            "count": 0
        }
