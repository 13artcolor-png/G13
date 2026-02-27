"""
G13 API - Trades Routes
=======================
Routes pour la gestion des trades et positions.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from actions.sync import (
    sync_positions, get_local_positions,
    sync_closed_trades, get_local_closed_trades,
    validate_positions
)
from actions.mt5 import connect_mt5, disconnect_mt5, read_positions, close_trade

router = APIRouter(prefix="/trades", tags=["Trades"])


@router.get("/positions/{agent_id}")
async def get_positions(agent_id: str):
    """Obtenir les positions ouvertes d'un agent."""
    result = get_local_positions(agent_id)
    return result


@router.get("/closed/{agent_id}")
async def get_closed_trades(agent_id: str, limit: int = 50):
    """Obtenir les trades clotures d'un agent."""
    result = get_local_closed_trades(agent_id, limit=limit)
    return result


@router.post("/sync/{agent_id}")
async def sync_agent_trades(agent_id: str):
    """
    Synchroniser les trades d'un agent avec MT5.
    Synchronise les positions ouvertes ET l'historique.
    """
    # Connecter a MT5
    connect_result = connect_mt5(agent_id)
    if not connect_result["success"]:
        raise HTTPException(status_code=500, detail=connect_result["message"])

    try:
        # Sync positions ouvertes
        positions_result = sync_positions(agent_id)

        # Sync trades clotures
        closed_result = sync_closed_trades(agent_id)

        return {
            "success": True,
            "positions": positions_result,
            "closed_trades": closed_result
        }
    finally:
        disconnect_mt5()


@router.post("/validate/{agent_id}")
async def validate_agent_positions(agent_id: str):
    """Valider que les positions locales correspondent a MT5."""
    # Connecter a MT5
    connect_result = connect_mt5(agent_id)
    if not connect_result["success"]:
        raise HTTPException(status_code=500, detail=connect_result["message"])

    try:
        result = validate_positions(agent_id)
        return result
    finally:
        disconnect_mt5()


@router.delete("/position/{agent_id}/{ticket}")
async def close_position(agent_id: str, ticket: int):
    """Fermer une position specifique."""
    # Connecter a MT5
    connect_result = connect_mt5(agent_id)
    if not connect_result["success"]:
        raise HTTPException(status_code=500, detail=connect_result["message"])

    try:
        result = close_trade(agent_id, ticket)

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"])

        # Re-sync apres fermeture
        sync_positions(agent_id)

        return result
    finally:
        disconnect_mt5()
