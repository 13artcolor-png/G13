"""
Strategy Module
===============
Analyse et ajustement automatique des strategies de trading.

- strategist.py: Analyse les performances et genere des suggestions (regles)
- strategist_ai.py: Analyse avancee via IA (Requesty/Anthropic/OpenAI/Google)
- ia_adjust.py: Applique les ajustements de parametres
"""

from .strategist import Strategist, get_strategist
from .ia_adjust import IAdjust, get_ia_adjust
from .strategist_ai import analyze_with_ai, has_ai_key

__all__ = [
    "Strategist",
    "get_strategist",
    "IAdjust",
    "get_ia_adjust",
    "analyze_with_ai",
    "has_ai_key"
]
