"""
Session History Module
======================
RESPONSABILITE UNIQUE: Archiver une session terminee dans un fichier texte exploitable.

A chaque fin de session (nouvelle session ou arret), toutes les donnees
sont consolidees dans un rapport texte stocke dans database/history/.

Nommage: YYYY-MM-DD_HHhMM_+12.50$.txt  (profit positif)
         YYYY-MM-DD_HHhMM_-3.20$.txt    (profit negatif)
         YYYY-MM-DD_HHhMM_0.00$.txt      (pas de trades)

Usage:
    from actions.session.session_history import archive_session
    archive_session()
"""

import json
from pathlib import Path
from datetime import datetime

DATABASE_PATH = Path(__file__).parent.parent.parent / "database"
HISTORY_DIR = DATABASE_PATH / "history"


def archive_session() -> dict:
    """
    Archive la session courante dans un fichier texte exploitable.
    Collecte: session info, stats par agent, trades fermes, decisions IA, tickets.

    Returns:
        dict: {"success": bool, "message": str, "file_path": str|None}
    """
    try:
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)

        # === 1. Donnees session ===
        session = _load_json(DATABASE_PATH / "session.json", {})
        session_id = session.get("id", "unknown")
        start_time_str = session.get("start_time", "")
        balance_start = session.get("balance_start", 0)

        # Date de fin = maintenant
        end_time = datetime.now()
        end_time_str = end_time.isoformat()

        # Calculer duree
        duration_str = "N/A"
        if start_time_str:
            try:
                start_dt = datetime.fromisoformat(start_time_str)
                delta = end_time - start_dt
                hours = int(delta.total_seconds() // 3600)
                minutes = int((delta.total_seconds() % 3600) // 60)
                duration_str = f"{hours}h{minutes:02d}min"
            except Exception:
                pass

        # === 2. Stats par agent ===
        agents_stats = {}
        total_profit = 0.0
        total_trades = 0

        for agent_id in ["fibo1", "fibo2", "fibo3"]:
            stats = _load_json(DATABASE_PATH / "stats" / f"{agent_id}.json", {})
            agents_stats[agent_id] = stats
            total_profit += stats.get("total_profit", 0)
            total_trades += stats.get("total_trades", 0)

        # === 3. Trades fermes par agent ===
        agents_trades = {}
        for agent_id in ["fibo1", "fibo2", "fibo3"]:
            trades = _load_json(DATABASE_PATH / "closed_trades" / f"{agent_id}.json", [])
            agents_trades[agent_id] = trades

        # === 4. Decisions IA ===
        decisions = _load_json(DATABASE_PATH / "decisions" / "decisions.json", [])

        # === 5. Tickets de session ===
        tickets = _load_json(DATABASE_PATH / "session_tickets.json", [])

        # === 6. Ajustements strategist ===
        adjustments = _load_json(DATABASE_PATH / "adjustments_log.json", [])

        # === GENERER LE RAPPORT ===
        report = _build_report(
            session=session,
            session_id=session_id,
            start_time_str=start_time_str,
            end_time_str=end_time_str,
            duration_str=duration_str,
            balance_start=balance_start,
            total_profit=total_profit,
            total_trades=total_trades,
            agents_stats=agents_stats,
            agents_trades=agents_trades,
            decisions=decisions,
            tickets=tickets,
            adjustments=adjustments
        )

        # === NOM DU FICHIER ===
        # Format: YYYY-MM-DD_HHhMM_+12.50$.txt
        date_part = end_time.strftime("%Y-%m-%d_%Hh%M")
        if total_profit >= 0:
            profit_part = f"+{total_profit:.2f}$"
        else:
            profit_part = f"{total_profit:.2f}$"

        filename = f"{date_part}_{profit_part}.txt"
        file_path = HISTORY_DIR / filename

        # Ecrire le fichier
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(report)

        print(f"[History] Session archivee: {filename}")

        return {
            "success": True,
            "message": f"Session archivee dans {filename}",
            "file_path": str(file_path)
        }

    except Exception as e:
        print(f"[History] ERREUR archivage: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "message": f"Erreur archivage: {str(e)}",
            "file_path": None
        }


def _build_report(
    session, session_id, start_time_str, end_time_str, duration_str,
    balance_start, total_profit, total_trades,
    agents_stats, agents_trades, decisions, tickets, adjustments
) -> str:
    """Construit le rapport texte complet de la session."""

    lines = []
    sep = "=" * 80
    sep2 = "-" * 80

    # === EN-TETE ===
    lines.append(sep)
    lines.append(f"  G13 - RAPPORT DE SESSION")
    lines.append(sep)
    lines.append(f"  Session ID    : {session_id}")
    lines.append(f"  Debut         : {_format_datetime(start_time_str)}")
    lines.append(f"  Fin           : {_format_datetime(end_time_str)}")
    lines.append(f"  Duree         : {duration_str}")
    lines.append(f"  Balance depart: {balance_start:.2f} $" if balance_start else "  Balance depart: N/A")
    lines.append(f"  Balance fin   : {(balance_start + total_profit):.2f} $" if balance_start else "  Balance fin   : N/A")
    lines.append(f"  Profit total  : {total_profit:+.2f} $")
    lines.append(f"  Trades total  : {total_trades}")
    lines.append(sep)
    lines.append("")

    # === RESUME PAR AGENT ===
    lines.append("  RESUME PAR AGENT")
    lines.append(sep2)

    for agent_id in ["fibo1", "fibo2", "fibo3"]:
        stats = agents_stats.get(agent_id, {})
        t = stats.get("total_trades", 0)
        w = stats.get("wins", 0)
        l = stats.get("losses", 0)
        wr = stats.get("winrate", 0)
        pnl = stats.get("total_profit", 0)
        avg_w = stats.get("avg_win", 0)
        avg_l = stats.get("avg_loss", 0)
        rr = stats.get("risk_reward", 0)

        lines.append(f"  {agent_id.upper()}")
        lines.append(f"    Trades : {t}  (W:{w} / L:{l})")
        lines.append(f"    Winrate: {wr:.1f}%")
        lines.append(f"    P&L    : {pnl:+.2f} $")
        lines.append(f"    Avg Win: {avg_w:+.2f} $  |  Avg Loss: {avg_l:+.2f} $  |  R:R: {rr:.2f}")
        lines.append("")

    lines.append(sep2)
    lines.append("")

    # === DETAIL DES TRADES ===
    lines.append("  DETAIL DES TRADES")
    lines.append(sep2)

    any_trade = False
    for agent_id in ["fibo1", "fibo2", "fibo3"]:
        trades = agents_trades.get(agent_id, [])
        if not trades:
            continue

        any_trade = True
        lines.append(f"  --- {agent_id.upper()} ({len(trades)} trades) ---")

        for trade in trades:
            ticket = trade.get("position_id", trade.get("ticket", "?"))
            symbol = trade.get("symbol", "?")
            direction = trade.get("type", "?")
            volume = trade.get("volume", 0)
            price = trade.get("price", 0)
            open_price = trade.get("open_price", "?")
            profit = trade.get("profit", 0)
            swap = trade.get("swap", 0)
            commission = trade.get("commission", 0)
            time_unix = trade.get("time", 0)

            time_str = _unix_to_str(time_unix) if time_unix else "?"
            result_icon = "WIN" if profit > 0 else ("LOSS" if profit < 0 else "BE")

            lines.append(f"    #{ticket}  {symbol}  {direction}  {volume} lots")
            lines.append(f"      Ouverture: {open_price}  ->  Fermeture: {price}  ({time_str})")
            lines.append(f"      Profit: {profit:+.2f} $  (swap: {swap:.2f}, comm: {commission:.2f})  [{result_icon}]")
            lines.append("")

    if not any_trade:
        lines.append("  Aucun trade durant cette session.")
        lines.append("")

    lines.append(sep2)
    lines.append("")

    # === TICKETS DE SESSION ===
    lines.append("  TICKETS DE SESSION")
    lines.append(sep2)

    if tickets:
        for t in tickets:
            status = t.get("status", "?")
            lines.append(f"    #{t.get('ticket', '?')}  {t.get('agent_id', '?')}  {t.get('direction', '?')}  {t.get('symbol', '?')}  [{status}]  ouvert: {_format_datetime(t.get('opened_at', ''))}")
    else:
        lines.append("  Aucun ticket enregistre.")

    lines.append("")
    lines.append(sep2)
    lines.append("")

    # === DECISIONS IA ===
    lines.append("  DECISIONS IA")
    lines.append(sep2)

    if decisions:
        for d in decisions:
            agent = d.get("agent_id", "?")
            action = d.get("decision", "?")
            symbol = d.get("symbol", "?")
            price = d.get("price", 0)
            executed = "EXECUTE" if d.get("executed") else "non execute"
            reason = d.get("reason", "")[:120]
            ts = _format_datetime(d.get("timestamp", ""))

            lines.append(f"    [{ts}] {agent} -> {action} {symbol} @ {price:.2f}  ({executed})")
            lines.append(f"      Raison: {reason}")
            lines.append("")
    else:
        lines.append("  Aucune decision IA enregistree.")
        lines.append("")

    lines.append(sep2)
    lines.append("")

    # === AJUSTEMENTS STRATEGIST ===
    if adjustments:
        lines.append("  AJUSTEMENTS STRATEGIST")
        lines.append(sep2)

        for adj in adjustments:
            agent = adj.get("agent_id", "?")
            adj_type = adj.get("type", "?")
            field = adj.get("field", "?")
            old_val = adj.get("old_value", "?")
            new_val = adj.get("new_value", "?")
            ts = _format_datetime(adj.get("timestamp", ""))

            lines.append(f"    [{ts}] {agent} {adj_type}: {field} {old_val} -> {new_val}")

        lines.append("")
        lines.append(sep2)
        lines.append("")

    # === FIN ===
    lines.append(sep)
    lines.append("  FIN DU RAPPORT")
    lines.append(sep)

    return "\n".join(lines)


def _format_datetime(iso_str: str) -> str:
    """Formate une date ISO en format lisible."""
    if not iso_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return iso_str


def _unix_to_str(timestamp: int) -> str:
    """Convertit un timestamp unix en date lisible."""
    try:
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return str(timestamp)


def _load_json(path: Path, default):
    """Charge un fichier JSON avec fallback sur default."""
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, Exception):
        pass
    return default
