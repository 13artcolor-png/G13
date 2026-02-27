"""
Strategy Module
===============
Analyse et ajustement automatique des strategies de trading.

- strategist.py: Analyse les performances et genere des suggestions
- ia_adjust.py: Applique les ajustements de parametres
"""

from .strategist import Strategist, get_strategist
from .ia_adjust import IAdjust, get_ia_adjust

__all__ = [
    "Strategist",
    "get_strategist",
    "IAdjust",
    "get_ia_adjust"
]
