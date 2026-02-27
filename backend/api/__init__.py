"""
G13 API Module
==============
Routes API FastAPI pour G13.

- routes_session.py: Gestion des sessions
- routes_agents.py: Gestion des agents
- routes_trades.py: Positions et trades
- routes_stats.py: Statistiques et analyse
"""

from .routes_session import router as session_router
from .routes_agents import router as agents_router
from .routes_trades import router as trades_router
from .routes_stats import router as stats_router
from .routes_compat import router as compat_router

__all__ = [
    "session_router",
    "agents_router",
    "trades_router",
    "stats_router",
    "compat_router"
]
