"""
Session Tickets Module
======================
RESPONSABILITE UNIQUE: Gerer les tickets de trades ouverts pendant la session courante.

PRINCIPE G13:
- La session enregistre la date/heure de debut
- Les trades sont traces UNIQUEMENT par leur numero de ticket
- sync_closed_trades() verifie chaque ticket via MT5 (pas de requete par date)
- Nouvelle session = session_tickets.json vide

Usage:
    from actions.session.session_tickets import save_ticket, get_session_tickets, clear_session_tickets
"""

import json
from pathlib import Path
from threading import Lock

DATABASE_PATH = Path(__file__).parent.parent.parent / "database"
TICKETS_FILE = DATABASE_PATH / "session_tickets.json"
_file_lock = Lock()


def save_ticket(agent_id: str, ticket: int, symbol: str, direction: str) -> None:
    """
    Enregistre un ticket de trade ouvert pendant cette session.

    Args:
        agent_id: fibo1, fibo2, fibo3
        ticket: Numero de ticket MT5 (position_id)
        symbol: Symbole trade (ex: BTCUSD)
        direction: BUY ou SELL
    """
    from datetime import datetime

    entry = {
        "ticket": ticket,
        "agent_id": agent_id,
        "symbol": symbol,
        "direction": direction,
        "opened_at": datetime.now().isoformat(),
        "status": "open"  # open / closed
    }

    with _file_lock:
        tickets = _load_tickets()
        # Eviter doublon
        existing = {t["ticket"] for t in tickets}
        if ticket not in existing:
            tickets.append(entry)
            _save_tickets(tickets)
            print(f"[SessionTickets] Ticket #{ticket} enregistre ({agent_id} {direction} {symbol})")


def mark_ticket_closed(ticket: int) -> None:
    """Marque un ticket comme ferme (ne le supprime pas, pour historique session)."""
    with _file_lock:
        tickets = _load_tickets()
        for t in tickets:
            if t["ticket"] == ticket:
                t["status"] = "closed"
                break
        _save_tickets(tickets)


def get_session_tickets(agent_id: str = None, status: str = None) -> list:
    """
    Retourne les tickets de la session.

    Args:
        agent_id: Filtrer par agent (optionnel)
        status: Filtrer par statut "open" ou "closed" (optionnel)

    Returns:
        list de tickets
    """
    with _file_lock:
        tickets = _load_tickets()

    if agent_id:
        tickets = [t for t in tickets if t["agent_id"] == agent_id]
    if status:
        tickets = [t for t in tickets if t.get("status") == status]

    return tickets


def get_open_ticket_numbers(agent_id: str = None) -> list:
    """Retourne la liste des numeros de tickets encore ouverts."""
    tickets = get_session_tickets(agent_id=agent_id, status="open")
    return [t["ticket"] for t in tickets]


def get_all_ticket_numbers(agent_id: str = None) -> list:
    """Retourne TOUS les numeros de tickets de la session (ouverts + fermes)."""
    tickets = get_session_tickets(agent_id=agent_id)
    return [t["ticket"] for t in tickets]


def clear_session_tickets() -> None:
    """Efface tous les tickets (appele lors d'une nouvelle session)."""
    with _file_lock:
        _save_tickets([])
        print("[SessionTickets] Tickets session effaces")


def _load_tickets() -> list:
    """Charge les tickets depuis le fichier JSON."""
    try:
        if TICKETS_FILE.exists():
            with open(TICKETS_FILE, "r") as f:
                return json.load(f)
    except (json.JSONDecodeError, Exception):
        pass
    return []


def _save_tickets(tickets: list) -> None:
    """Sauvegarde les tickets dans le fichier JSON."""
    TICKETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TICKETS_FILE, "w") as f:
        json.dump(tickets, f, indent=2)
