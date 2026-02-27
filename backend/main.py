"""
G13 - Trading Bot Backend
=========================
Point d'entree principal du backend G13.
Usage:
    uvicorn main:app --reload --port 8000
"""
import sys
from pathlib import Path

# Ajouter le dossier backend au path pour les imports
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from api import session_router, agents_router, trades_router, stats_router
from api.routes_compat import router as compat_router

# Creation de l'application FastAPI
app = FastAPI(
    title="G13 Trading Bot",
    description="Backend API pour le bot de trading G13 - Fibonacci + ICT/SMC",
    version="1.0.0"
)

# Configuration CORS pour le frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En production, specifier les origines exactes
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Enregistrement des routers
app.include_router(session_router)
app.include_router(agents_router)
app.include_router(trades_router)
app.include_router(stats_router)
app.include_router(compat_router)  # Routes compatibilite G12


@app.on_event("startup")
async def auto_resume_trading():
    """
    Auto-resume: si une session etait active avant le reload,
    relancer la trading loop automatiquement.
    """
    try:
        from actions.session import get_session_info
        from core import get_trading_loop

        session = get_session_info()
        session_data = session.get("session", {})

        if session_data.get("status") == "active":
            loop = get_trading_loop()
            if not loop.is_running:
                loop.start()
                print(f"[AutoResume] Trading loop relancee (session {session_data.get('id', '?')[:8]})")
            else:
                print(f"[AutoResume] Trading loop deja active")
        else:
            print(f"[AutoResume] Pas de session active, trading loop non demarree")
    except Exception as e:
        print(f"[AutoResume] Erreur: {e}")


@app.get("/")
async def root():
    """Servir le frontend."""
    frontend_path = Path(__file__).parent.parent / "frontend" / "index.html"
    if frontend_path.exists():
        return FileResponse(
            frontend_path,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    return {"name": "G13 Trading Bot", "version": "1.0.0", "status": "running"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
