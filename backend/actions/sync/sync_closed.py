"""
Sync Closed Trades Module
=========================
UNIQUE RESPONSIBILITY: Sync MT5 closed trades to local closed_trades/{agent}.json

PRINCIPE G13 (TICKET-BASED):
- Les trades sont traces UNIQUEMENT par leur numero de ticket
- Pas de requete par plage de dates (unreliable avec les timezones MT5)
- On verifie chaque ticket de session_tickets.json via mt5.history_deals_get(position=ticket)
- Si un deal de fermeture (entry==1) existe -> le trade est ferme -> on l'enregistre

Usage:
    from actions.sync.sync_closed import sync_closed_trades
    result = sync_closed_trades("fibo1")
"""

import json
import MetaTrader5 as mt5
from pathlib import Path
from datetime import datetime
from actions.session.session_tickets import get_session_tickets, mark_ticket_closed

DATABASE_PATH = Path(__file__).parent.parent.parent / "database"


def sync_closed_trades(agent_id: str, **kwargs) -> dict:
    """
    Verifie chaque ticket de la session pour cet agent.
    Si le trade est ferme sur MT5, l'enregistre dans closed_trades/{agent}.json.

    TICKET-BASED: pas de dates, uniquement les tickets enregistres dans session_tickets.json.

    Args:
        agent_id: fibo1, fibo2, fibo3
        **kwargs: ignore les anciens parametres (from_date, etc.)

    Returns:
        dict: {"success": bool, "message": str, "new_trades": int, "total_trades": int}

    Note: MT5 doit etre connecte avant d'appeler cette fonction.
    """
    try:
        # Charger les trades deja enregistres localement
        file_path = DATABASE_PATH / "closed_trades" / f"{agent_id}.json"
        file_path.parent.mkdir(parents=True, exist_ok=True)

        existing_trades = []
        existing_tickets = set()

        if file_path.exists():
            with open(file_path, "r") as f:
                existing_trades = json.load(f)
                existing_tickets = {t.get("position_id", t.get("ticket")) for t in existing_trades}

        # Recuperer les tickets de la session pour cet agent
        session_tickets = get_session_tickets(agent_id=agent_id)

        if not session_tickets:
            return {
                "success": True,
                "message": f"Aucun ticket de session pour {agent_id}",
                "new_trades": 0,
                "total_trades": len(existing_trades)
            }

        new_trades_count = 0

        for ticket_entry in session_tickets:
            ticket = ticket_entry["ticket"]

            # Deja enregistre localement -> skip
            if ticket in existing_tickets:
                continue

            # Deja marque ferme dans session_tickets mais pas dans closed_trades
            # -> on re-verifie sur MT5

            # Interroger MT5 par ticket (position_id)
            deals = mt5.history_deals_get(position=ticket)

            if deals is None or len(deals) == 0:
                # Pas encore de deals pour ce ticket (position toujours ouverte ou erreur)
                continue

            # Chercher le deal de fermeture (entry == 1 = DEAL_ENTRY_OUT)
            closing_deal = None
            opening_deal = None
            for deal in deals:
                if deal.entry == 1:  # Fermeture
                    closing_deal = deal
                elif deal.entry == 0:  # Ouverture
                    opening_deal = deal

            if closing_deal is None:
                # Position encore ouverte (seul le deal d'ouverture existe)
                continue

            # Trade ferme ! Construire l'enregistrement
            trade_record = {
                "ticket": closing_deal.ticket,
                "order": closing_deal.order,
                "position_id": closing_deal.position_id,
                "symbol": closing_deal.symbol,
                "type": "BUY" if closing_deal.type == 0 else "SELL",
                "volume": closing_deal.volume,
                "price": closing_deal.price,
                "profit": closing_deal.profit,
                "swap": closing_deal.swap,
                "commission": closing_deal.commission,
                "time": closing_deal.time,
                "magic": closing_deal.magic,
                "comment": closing_deal.comment,
                "entry": closing_deal.entry,
                "agent_id": agent_id,
                "synced_at": datetime.now().isoformat()
            }

            # Ajouter prix d'ouverture si disponible
            if opening_deal:
                trade_record["open_price"] = opening_deal.price
                trade_record["open_time"] = opening_deal.time

            existing_trades.append(trade_record)
            existing_tickets.add(ticket)
            new_trades_count += 1

            # Marquer le ticket comme ferme dans session_tickets.json
            mark_ticket_closed(ticket)

            print(f"[SyncClosed] {agent_id} ticket #{ticket} FERME -> profit: {closing_deal.profit}")

        # Trier par time (plus recent en premier)
        existing_trades.sort(key=lambda x: x.get("time", 0), reverse=True)

        # Sauvegarder
        with open(file_path, "w") as f:
            json.dump(existing_trades, f, indent=2)

        return {
            "success": True,
            "message": f"Sync {agent_id}: {new_trades_count} nouveaux trades fermes",
            "new_trades": new_trades_count,
            "total_trades": len(existing_trades)
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Erreur sync closed trades: {str(e)}",
            "new_trades": 0,
            "total_trades": 0
        }


def get_local_closed_trades(agent_id: str, limit: int = None) -> dict:
    """
    Lit les trades fermes depuis le fichier JSON local.

    Args:
        agent_id: fibo1, fibo2, fibo3
        limit: Nombre max de trades a retourner (plus recents en premier)

    Returns:
        dict: {"success": bool, "trades": list, "count": int}
    """
    try:
        file_path = DATABASE_PATH / "closed_trades" / f"{agent_id}.json"

        if not file_path.exists():
            return {
                "success": True,
                "trades": [],
                "count": 0
            }

        with open(file_path, "r") as f:
            trades = json.load(f)

        if limit:
            trades = trades[:limit]

        return {
            "success": True,
            "trades": trades,
            "count": len(trades)
        }

    except Exception as e:
        return {
            "success": False,
            "trades": [],
            "count": 0
        }
