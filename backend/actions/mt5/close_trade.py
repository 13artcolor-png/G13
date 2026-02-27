"""
MT5 Close Trade Module
======================
UNIQUE RESPONSIBILITY: Close a trade on MT5

Usage:
    from actions.mt5.close_trade import close_trade
    result = close_trade("fibo1", ticket=123456)
"""

import MetaTrader5 as mt5


def close_trade(agent_id: str, ticket: int) -> dict:
    """
    Close a specific trade on MT5.
    
    Args:
        agent_id: The agent identifier
        ticket: The position ticket to close
        
    Returns:
        dict: {
            "success": bool,
            "message": str,
            "profit": float|None,
            "close_info": dict|None
        }
    
    Note: MT5 must be connected before calling this function.
    """
    try:
        # Get position info
        position = mt5.positions_get(ticket=ticket)
        
        if position is None or len(position) == 0:
            return {
                "success": False,
                "message": f"Position {ticket} not found",
                "profit": None,
                "close_info": None
            }
        
        pos = position[0]
        symbol = pos.symbol
        volume = pos.volume
        pos_type = pos.type
        
        # Get current price
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return {
                "success": False,
                "message": f"Failed to get tick for {symbol}",
                "profit": None,
                "close_info": None
            }
        
        # Determine close direction (opposite of position type)
        if pos_type == 0:  # BUY position -> close with SELL
            close_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
        else:  # SELL position -> close with BUY
            close_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
        
        # Prepare close request
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": close_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": hash(agent_id) % 1000000,
            "comment": f"G13_{agent_id}_close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        # Send close order
        result = mt5.order_send(request)
        
        if result is None:
            error = mt5.last_error()
            return {
                "success": False,
                "message": f"Close order failed: {error}",
                "profit": None,
                "close_info": None
            }
        
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return {
                "success": False,
                "message": f"Close rejected: {result.comment} (code: {result.retcode})",
                "profit": None,
                "close_info": None
            }
        
        return {
            "success": True,
            "message": f"Position {ticket} closed @ {result.price}",
            "profit": pos.profit,
            "close_info": {
                "ticket": ticket,
                "close_price": result.price,
                "volume": volume,
                "symbol": symbol,
                "profit": pos.profit
            }
        }
        
    except Exception as e:
        return {
            "success": False,
            "message": f"Error closing trade: {str(e)}",
            "profit": None,
            "close_info": None
        }


def close_all_positions(agent_id: str, symbol: str = None) -> dict:
    """
    Close all positions (optionally filtered by symbol).
    
    Args:
        agent_id: The agent identifier
        symbol: Optional symbol filter
        
    Returns:
        dict: {
            "success": bool,
            "message": str,
            "closed_count": int,
            "total_profit": float
        }
    """
    try:
        if symbol:
            positions = mt5.positions_get(symbol=symbol)
        else:
            positions = mt5.positions_get()
        
        if positions is None or len(positions) == 0:
            return {
                "success": True,
                "message": "No positions to close",
                "closed_count": 0,
                "total_profit": 0.0
            }
        
        closed_count = 0
        total_profit = 0.0
        
        for pos in positions:
            result = close_trade(agent_id, pos.ticket)
            if result["success"]:
                closed_count += 1
                total_profit += result["profit"] or 0.0
        
        return {
            "success": True,
            "message": f"Closed {closed_count}/{len(positions)} positions",
            "closed_count": closed_count,
            "total_profit": total_profit
        }
        
    except Exception as e:
        return {
            "success": False,
            "message": f"Error closing positions: {str(e)}",
            "closed_count": 0,
            "total_profit": 0.0
        }
