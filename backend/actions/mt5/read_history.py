"""
MT5 Read History Module
=======================
UNIQUE RESPONSIBILITY: Read closed trades history from MT5

Usage:
    from actions.mt5.read_history import read_history
    deals = read_history("fibo1", from_date, to_date)
"""

import MetaTrader5 as mt5
from datetime import datetime, timedelta
from typing import Optional


def read_history(
    agent_id: str,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    symbol: Optional[str] = None
) -> dict:
    """
    Read closed deals history from MT5.
    
    Args:
        agent_id: The agent identifier (for logging)
        from_date: Start date (default: 30 days ago)
        to_date: End date (default: now)
        symbol: Optional symbol filter
        
    Returns:
        dict: {
            "success": bool,
            "message": str,
            "deals": List[dict],
            "count": int
        }
    
    Note: MT5 must be connected before calling this function.
    """
    try:
        # Default date range: last 30 days
        if to_date is None:
            to_date = datetime.now()
        if from_date is None:
            from_date = to_date - timedelta(days=30)
        
        # Get deals from MT5
        if symbol:
            deals = mt5.history_deals_get(from_date, to_date, symbol=symbol)
        else:
            deals = mt5.history_deals_get(from_date, to_date)
        
        if deals is None:
            error = mt5.last_error()
            return {
                "success": False,
                "message": f"Failed to get history deals: {error}",
                "deals": [],
                "count": 0
            }
        
        # Filter only OUT deals (closing trades)
        deals_list = []
        for deal in deals:
            # DEAL_ENTRY_OUT = 1 means closing a position
            if deal.entry == 1:
                deals_list.append({
                    "ticket": deal.ticket,
                    "order": deal.order,
                    "position_id": deal.position_id,
                    "symbol": deal.symbol,
                    "type": "BUY" if deal.type == 0 else "SELL",
                    "volume": deal.volume,
                    "price": deal.price,
                    "profit": deal.profit,
                    "swap": deal.swap,
                    "commission": deal.commission,
                    "time": deal.time,
                    "magic": deal.magic,
                    "comment": deal.comment,
                    "entry": deal.entry
                })
        
        return {
            "success": True,
            "message": f"Found {len(deals_list)} closed deals",
            "deals": deals_list,
            "count": len(deals_list)
        }
        
    except Exception as e:
        return {
            "success": False,
            "message": f"Error reading history: {str(e)}",
            "deals": [],
            "count": 0
        }
