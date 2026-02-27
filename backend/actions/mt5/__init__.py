"""
MT5 Actions Module
==================
All MT5-related actions, each in its own file.
"""
from .connect import connect_mt5, disconnect_mt5
from .read_positions import read_positions
from .read_history import read_history
from .open_trade import open_trade
from .close_trade import close_trade, close_all_positions
from .market_data import get_market_data, get_current_price, get_ohlc, calculate_fibonacci_levels, get_full_market_data
from .modify_trade import modify_trade_sl_tp, get_symbol_info

__all__ = [
    "connect_mt5",
    "disconnect_mt5",
    "read_positions",
    "read_history",
    "open_trade",
    "close_trade",
    "close_all_positions",
    "get_market_data",
    "get_current_price",
    "get_ohlc",
    "calculate_fibonacci_levels",
    "get_full_market_data",
    "modify_trade_sl_tp",
    "get_symbol_info"
]
