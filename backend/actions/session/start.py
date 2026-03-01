"""
Session Start Module
====================
UNIQUE RESPONSIBILITY: Start a new trading session
Usage:
    from actions.session.start import start_session
    result = start_session()
"""
import json
import uuid
from pathlib import Path
from datetime import datetime

DATABASE_PATH = Path(__file__).parent.parent.parent / "database"
SESSION_FILE = DATABASE_PATH / "session.json"


def _archive_previous_session():
    """
    Archive la session precedente si elle contient des donnees.
    Verifie qu'il y a eu au moins 1 trade ou 1 decision avant d'archiver
    (pas d'archivage pour les sessions vides).
    """
    try:
        # Verifier si une session existe
        session = get_session_raw()
        if not session.get("id"):
            return

        # Verifier s'il y a des donnees a archiver (au moins 1 trade ou 1 decision)
        has_data = False

        for agent_id in ["fibo1", "fibo2", "fibo3"]:
            trades_file = DATABASE_PATH / "closed_trades" / f"{agent_id}.json"
            if trades_file.exists():
                with open(trades_file, "r") as f:
                    trades = json.load(f)
                if trades:
                    has_data = True
                    break

        if not has_data:
            decisions_file = DATABASE_PATH / "decisions" / "decisions.json"
            if decisions_file.exists():
                with open(decisions_file, "r") as f:
                    decisions = json.load(f)
                if decisions:
                    has_data = True

        if not has_data:
            tickets_file = DATABASE_PATH / "session_tickets.json"
            if tickets_file.exists():
                with open(tickets_file, "r") as f:
                    tickets = json.load(f)
                if tickets:
                    has_data = True

        if not has_data:
            print("[Session] Session precedente vide, pas d'archivage")
            return

        # Archiver
        from actions.session.session_history import archive_session
        result = archive_session()
        if result["success"]:
            print(f"[Session] Session precedente archivee: {result['file_path']}")
        else:
            print(f"[Session] ERREUR archivage: {result['message']}")

    except Exception as e:
        print(f"[Session] Erreur verification archivage: {e}")


def _reset_all_data():
    """
    Reset ALL historical data for a fresh session.
    ETAPE 1: Archiver la session precedente (si elle a des donnees)
    ETAPE 2: Clear closed_trades, stats, open_positions, decisions, logs
    Preserves: config/ (agents.json, api_keys.json, etc.) et history/
    """
    # ARCHIVER la session precedente AVANT de tout effacer
    _archive_previous_session()

    folders_to_clear = [
        "closed_trades",
        "stats",
        "open_positions",
        "decisions",
        "logs",
    ]

    for folder_name in folders_to_clear:
        folder = DATABASE_PATH / folder_name
        if not folder.exists():
            continue

        for f in folder.iterdir():
            if f.is_file() and f.suffix == ".json":
                if folder_name == "stats":
                    # Reset stats to zero structure
                    agent_id = f.stem  # fibo1, fibo2, fibo3
                    empty_stats = {
                        "agent_id": agent_id,
                        "total_trades": 0,
                        "wins": 0,
                        "losses": 0,
                        "breakeven": 0,
                        "winrate": 0.0,
                        "total_profit": 0.0,
                        "avg_win": 0.0,
                        "avg_loss": 0.0,
                        "risk_reward": 0.0,
                        "updated_at": datetime.now().isoformat()
                    }
                    with open(f, "w") as fh:
                        json.dump(empty_stats, fh, indent=2)
                elif folder_name in ("closed_trades", "open_positions"):
                    # Reset to empty list
                    with open(f, "w") as fh:
                        json.dump([], fh, indent=2)
                else:
                    # decisions, logs: delete file
                    f.unlink()

    # Reset les tickets de session
    from actions.session.session_tickets import clear_session_tickets
    clear_session_tickets()

    # Reset l'historique de performance des graphiques
    history_file = DATABASE_PATH / "performance_history.json"
    if history_file.exists():
        with open(history_file, "w") as fh:
            json.dump({}, fh)
        print(f"[Session] Performance history reset")

    print(f"[Session] All data reset for new session")


def start_session(initial_balance: float = None, force_new: bool = False) -> dict:
    """
    Demarre ou reprend une session de trading.

    REGLE ABSOLUE: Une session persiste jusqu'a ce que l'utilisateur clique sur "Nouvelle Session".
    - force_new=False (defaut) : REPREND la session existante (meme si status=stopped)
    - force_new=True : Cree une NOUVELLE session avec reset des donnees (uniquement via "Nouvelle Session")

    Args:
        initial_balance: Balance de depart (optionnel, recupere de MT5)
        force_new: Si True, force la creation d'une nouvelle session (uniquement "Nouvelle Session")

    Returns:
        dict: {"success": bool, "message": str, "session": dict}
    """
    try:
        current = get_session_raw()

        # === MODE REPRISE (defaut) : reprendre la session existante ===
        if not force_new:
            if current.get("id"):
                # Session existe -> la reprendre
                changed = False

                # Remettre en active si elle etait stopped
                if current.get("status") != "active":
                    current["status"] = "active"
                    changed = True

                # Mettre a jour la balance si fournie et absente
                if initial_balance and not current.get("balance_start"):
                    current["balance_start"] = initial_balance
                    changed = True

                if changed:
                    with open(SESSION_FILE, "w") as f:
                        json.dump(current, f, indent=2)

                session_id = current.get("id")
                print(f"[Session] Session {session_id} reprise (status: active)")
                return {
                    "success": True,
                    "message": f"Session {session_id} reprise",
                    "session": current
                }
            # Pas de session existante -> en creer une (premier lancement)

        # === MODE NOUVELLE SESSION : reset complet ===
        _reset_all_data()

        session_id = str(uuid.uuid4())[:8]
        session = {
            "id": session_id,
            "start_time": datetime.now().isoformat(),
            "balance_start": initial_balance,
            "status": "active"
        }

        with open(SESSION_FILE, "w") as f:
            json.dump(session, f, indent=2)

        print(f"[Session] Nouvelle session {session_id} (data reset)")

        return {
            "success": True,
            "message": f"Session {session_id} started (all data reset)",
            "session": session
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Error starting session: {str(e)}",
            "session": None
        }


def get_session_raw() -> dict:
    """Read raw session data from file."""
    try:
        if SESSION_FILE.exists():
            with open(SESSION_FILE, "r") as f:
                return json.load(f)
        return {"id": None, "start_time": None, "balance_start": None, "status": "stopped"}
    except:
        return {"id": None, "start_time": None, "balance_start": None, "status": "stopped"}
