"""
G13 API - Session Routes
========================
Routes pour la gestion des sessions de trading.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from actions.session import start_session, end_session, get_session_info

router = APIRouter(prefix="/session", tags=["Session"])


class StartSessionRequest(BaseModel):
    initial_balance: Optional[float] = None


class EndSessionRequest(BaseModel):
    final_balance: Optional[float] = None


@router.get("/")
async def get_session():
    """Obtenir les informations de la session actuelle."""
    result = get_session_info()
    return result


@router.post("/start")
async def start(request: StartSessionRequest):
    """Demarrer une nouvelle session de trading."""
    result = start_session(initial_balance=request.initial_balance)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return result


@router.post("/stop")
async def stop(request: EndSessionRequest):
    """Arreter la session de trading actuelle."""
    result = end_session(final_balance=request.final_balance)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return result


@router.get("/status")
async def status():
    """Verifier si une session est active."""
    info = get_session_info()
    return {
        "is_active": info.get("is_active", False),
        "session_id": info.get("session", {}).get("id"),
        "duration_seconds": info.get("duration_seconds")
    }
