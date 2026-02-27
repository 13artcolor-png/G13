"""
MT5 Read Positions Module
=========================
UNIQUE RESPONSIBILITY: Read open positions from MT5

Usage:
    from actions.mt5.read_positions import read_positions
    positions = read_positions("fibo1")
"""

import MetaTrader5 as mt5
from typing import List, Dict, Any


def read_positions(agent_id: str, symbol: str = None) -> dict:
    """
    Read all open positions from MT5 for an agent.
    
    Args:
        agent_id: The agent identifier (for logging/filtering)
        symbol: Optional symbol filter (e.g., "XAUUSD")
        
    Returns:
        dict: {
            "success": bool,
            "message": str,
            "positions": List[dict],
            "count": int
        }
    
    Note: MT5 must be connected before calling this function.
    """
    try:
        if symbol:
            positions = mt5.positions_get(symbol=symbol)
        else:
            positions = mt5.positions_get()
        
        if positions is None:
            error = mt5.last_error()
            return {
                "success": False,
                "message": f"Failed to get positions: {error}",
                "positions": [],
                "count": 0
            }
        
        positions_list = []
        for pos in positions:
            positions_list.append({
                "ticket": pos.ticket,
                "symbol": pos.symbol,
                "type": "BUY" if pos.type == 0 else "SELL",
                "volume": pos.volume,
                "price_open": pos.price_open,
                "price_current": pos.price_current,
                "sl": pos.sl,
                "tp": pos.tp,
                "profit": pos.profit,
                "swap": pos.swap,
                "time": pos.time,
                "magic": pos.magic,
                "comment": pos.comment
            })
        
        return {
            "success": True,
            "message": f"Found {len(positions_list)} positions",
            "positions": positions_list,
            "count": len(positions_list)
        }
        
    except Exception as e:
        return {
            "success": False,
            "message": f"Error reading positions: {str(e)}",
            "positions": [],
            "count": 0
        }
