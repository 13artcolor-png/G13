"""
MT5 Open Trade Module
=====================
UNIQUE RESPONSIBILITY: Open a trade on MT5

Usage:
    from actions.mt5.open_trade import open_trade
    result = open_trade("fibo1", "XAUUSD", "BUY", 0.01, sl=2900, tp=2950)
"""

import MetaTrader5 as mt5


def open_trade(
    agent_id: str,
    symbol: str,
    direction: str,
    volume: float,
    sl: float = None,
    tp: float = None,
    comment: str = ""
) -> dict:
    """
    Open a trade on MT5.
    
    Args:
        agent_id: The agent identifier
        symbol: Trading symbol (e.g., "XAUUSD")
        direction: "BUY" or "SELL"
        volume: Lot size
        sl: Stop loss price (optional)
        tp: Take profit price (optional)
        comment: Trade comment (optional)
        
    Returns:
        dict: {
            "success": bool,
            "message": str,
            "ticket": int|None,
            "order_info": dict|None
        }
    
    Note: MT5 must be connected before calling this function.
    """
    try:
        # Get symbol info
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            return {
                "success": False,
                "message": f"Symbol {symbol} not found",
                "ticket": None,
                "order_info": None
            }
        
        # Enable symbol if needed
        if not symbol_info.visible:
            if not mt5.symbol_select(symbol, True):
                return {
                    "success": False,
                    "message": f"Failed to select symbol {symbol}",
                    "ticket": None,
                    "order_info": None
                }
        
        # Get current price
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return {
                "success": False,
                "message": f"Failed to get tick for {symbol}",
                "ticket": None,
                "order_info": None
            }
        
        # Determine order type and price
        if direction.upper() == "BUY":
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
        
        # Prepare order request
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "deviation": 20,
            "magic": hash(agent_id) % 1000000,
            "comment": comment or f"G13_{agent_id}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        if sl:
            request["sl"] = sl
        if tp:
            request["tp"] = tp
        
        # Send order
        result = mt5.order_send(request)
        
        if result is None:
            error = mt5.last_error()
            return {
                "success": False,
                "message": f"Order send failed: {error}",
                "ticket": None,
                "order_info": None
            }
        
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return {
                "success": False,
                "message": f"Order rejected: {result.comment} (code: {result.retcode})",
                "ticket": None,
                "order_info": None
            }
        
        return {
            "success": True,
            "message": f"Order executed: {direction} {volume} {symbol} @ {result.price}",
            "ticket": result.order,
            "order_info": {
                "ticket": result.order,
                "volume": result.volume,
                "price": result.price,
                "symbol": symbol,
                "direction": direction
            }
        }
        
    except Exception as e:
        return {
            "success": False,
            "message": f"Error opening trade: {str(e)}",
            "ticket": None,
            "order_info": None
        }
