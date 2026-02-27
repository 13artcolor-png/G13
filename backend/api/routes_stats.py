"""
G13 API - Stats Routes
======================
Routes pour les statistiques de trading.
"""

from fastapi import APIRouter

from actions.stats import calculate_stats, get_stats, get_all_stats
from strategy import get_strategist

router = APIRouter(prefix="/stats", tags=["Stats"])


@router.get("/")
async def get_all_agents_stats():
    """Obtenir les stats de tous les agents."""
    return get_all_stats()


@router.get("/{agent_id}")
async def get_agent_stats(agent_id: str):
    """Obtenir les stats d'un agent specifique."""
    return get_stats(agent_id)


@router.post("/calculate/{agent_id}")
async def recalculate_stats(agent_id: str):
    """Recalculer les stats d'un agent depuis les trades clotures."""
    result = calculate_stats(agent_id)
    return result


@router.post("/calculate")
async def recalculate_all_stats():
    """Recalculer les stats de tous les agents."""
    results = {}
    for agent_id in ["fibo1", "fibo2", "fibo3"]:
        results[agent_id] = calculate_stats(agent_id)
    return results


@router.get("/analysis/{agent_id}")
async def get_analysis(agent_id: str):
    """Obtenir l'analyse complete du Strategist pour un agent."""
    strategist = get_strategist()
    return strategist.analyze(agent_id)


@router.get("/analysis")
async def get_all_analysis():
    """Obtenir l'analyse de tous les agents."""
    strategist = get_strategist()
    return strategist.get_all_agents_analysis()


@router.get("/summary")
async def get_summary():
    """Resume rapide pour le dashboard."""
    strategist = get_strategist()
    return strategist.get_quick_summary()
