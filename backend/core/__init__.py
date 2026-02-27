"""
Core Module
===========
Composants principaux du bot de trading G13.

- trading_loop.py: Boucle principale de trading
"""

from .trading_loop import TradingLoop, get_trading_loop

__all__ = [
    "TradingLoop",
    "get_trading_loop"
]
