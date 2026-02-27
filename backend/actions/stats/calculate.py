"""
Stats Calculation Module
========================
UNIQUE RESPONSIBILITY: Calculate and save trading statistics

Usage:
    from actions.stats.calculate import calculate_stats
    result = calculate_stats("fibo1")
"""

import json
from pathlib import Path
from datetime import datetime

DATABASE_PATH = Path(__file__).parent.parent.parent / "database"


def calculate_stats(agent_id: str) -> dict:
    """
    Calculate statistics from closed trades and save to stats file.
    
    Args:
        agent_id: The agent identifier
        
    Returns:
        dict: {
            "success": bool,
            "message": str,
            "stats": dict
        }
    """
    try:
        # Read closed trades
        trades_file = DATABASE_PATH / "closed_trades" / f"{agent_id}.json"
        
        trades = []
        if trades_file.exists():
            with open(trades_file, "r") as f:
                trades = json.load(f)
        
        # Calculate stats
        total_trades = len(trades)
        wins = sum(1 for t in trades if t.get("profit", 0) > 0)
        losses = sum(1 for t in trades if t.get("profit", 0) < 0)
        breakeven = total_trades - wins - losses
        
        total_profit = sum(t.get("profit", 0) for t in trades)
        
        winrate = (wins / total_trades * 100) if total_trades > 0 else 0
        
        # Calculate average win/loss
        winning_trades = [t["profit"] for t in trades if t.get("profit", 0) > 0]
        losing_trades = [t["profit"] for t in trades if t.get("profit", 0) < 0]
        
        avg_win = sum(winning_trades) / len(winning_trades) if winning_trades else 0
        avg_loss = sum(losing_trades) / len(losing_trades) if losing_trades else 0
        
        # Risk/Reward ratio
        risk_reward = abs(avg_win / avg_loss) if avg_loss != 0 else 0
        
        stats = {
            "agent_id": agent_id,
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "breakeven": breakeven,
            "winrate": round(winrate, 2),
            "total_profit": round(total_profit, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "risk_reward": round(risk_reward, 2),
            "updated_at": datetime.now().isoformat()
        }
        
        # Save to stats file
        stats_file = DATABASE_PATH / "stats" / f"{agent_id}.json"
        with open(stats_file, "w") as f:
            json.dump(stats, f, indent=2)
        
        return {
            "success": True,
            "message": f"Stats calculated for {agent_id}: {total_trades} trades, {winrate:.1f}% winrate",
            "stats": stats
        }
        
    except Exception as e:
        return {
            "success": False,
            "message": f"Error calculating stats: {str(e)}",
            "stats": None
        }


def get_stats(agent_id: str) -> dict:
    """
    Get current stats from file.
    
    Args:
        agent_id: The agent identifier
        
    Returns:
        dict: The stats or default values
    """
    try:
        stats_file = DATABASE_PATH / "stats" / f"{agent_id}.json"
        
        if stats_file.exists():
            with open(stats_file, "r") as f:
                return json.load(f)
        
        return {
            "agent_id": agent_id,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "winrate": 0,
            "total_profit": 0,
            "updated_at": None
        }
        
    except:
        return {
            "agent_id": agent_id,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "winrate": 0,
            "total_profit": 0,
            "updated_at": None
        }


def get_all_stats() -> dict:
    """
    Get stats for all agents.
    
    Returns:
        dict: {"fibo1": {...}, "fibo2": {...}, "fibo3": {...}}
    """
    return {
        "fibo1": get_stats("fibo1"),
        "fibo2": get_stats("fibo2"),
        "fibo3": get_stats("fibo3")
    }
