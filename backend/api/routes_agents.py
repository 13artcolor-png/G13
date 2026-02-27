"""
G13 API - Agents Routes
=======================
Routes pour la gestion des agents de trading.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
import json
from pathlib import Path

from agents import create_agent, get_all_agents

router = APIRouter(prefix="/agents", tags=["Agents"])

CONFIG_PATH = Path(__file__).parent.parent / "database" / "config" / "agents.json"


class AgentConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    fibo_level: Optional[str] = None
    fibo_tolerance_pct: Optional[float] = None
    cooldown_seconds: Optional[int] = None
    position_size_pct: Optional[float] = None
    max_positions: Optional[int] = None


@router.get("/")
async def list_agents():
    """Liste tous les agents et leur statut."""
    agents = get_all_agents()
    return {
        agent_id: agent.get_status()
        for agent_id, agent in agents.items()
    }


@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    """Obtenir les details d'un agent."""
    agent = create_agent(agent_id)

    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    return agent.get_status()


@router.patch("/{agent_id}")
async def update_agent_config(agent_id: str, config: AgentConfigUpdate):
    """Mettre a jour la configuration d'un agent."""
    try:
        with open(CONFIG_PATH, "r") as f:
            all_configs = json.load(f)

        if agent_id not in all_configs:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

        # Mettre a jour seulement les champs fournis
        update_data = config.model_dump(exclude_none=True)
        all_configs[agent_id].update(update_data)

        with open(CONFIG_PATH, "w") as f:
            json.dump(all_configs, f, indent=4)

        return {
            "success": True,
            "message": f"Agent {agent_id} updated",
            "config": all_configs[agent_id]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{agent_id}/enable")
async def enable_agent(agent_id: str):
    """Activer un agent."""
    return await update_agent_config(agent_id, AgentConfigUpdate(enabled=True))


@router.post("/{agent_id}/disable")
async def disable_agent(agent_id: str):
    """Desactiver un agent."""
    return await update_agent_config(agent_id, AgentConfigUpdate(enabled=False))
