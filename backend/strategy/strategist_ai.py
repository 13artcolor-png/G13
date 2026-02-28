"""
G13 Strategist AI
=================
RESPONSABILITE: Analyse avancee des performances via IA (Requesty/Anthropic/OpenAI/Google).

L'IA recoit les performances + l'historique des ajustements et decide des VALEURS EXACTES
pour chaque parametre (pas des types generiques).

Reutilise call_ai() de agents/ai_decision.py pour l'appel API.
Fallback automatique sur l'analyse regles si pas de cle API ou erreur.

Usage:
    from strategy.strategist_ai import analyze_with_ai, has_ai_key
    if has_ai_key():
        result = analyze_with_ai()
"""

import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

DATABASE_PATH = Path(__file__).parent.parent / "database"
CONFIG_PATH = DATABASE_PATH / "config"

# Parametres ajustables avec bornes (doit rester synchronise avec IAdjust)
PARAM_BOUNDS = {
    "fibo_tolerance_pct": {"min": 0.5, "max": 5.0, "desc": "Zone autour du niveau Fibonacci (%)"},
    "cooldown_seconds":   {"min": 60,  "max": 600, "desc": "Temps d'attente entre trades (secondes)"},
    "tp_pct":             {"min": 0.1, "max": 1.0, "desc": "Take Profit en % du capital"},
    "sl_pct":             {"min": 0.2, "max": 2.0, "desc": "Stop Loss en % du capital"},
    "position_size_pct":  {"min": 0.005, "max": 0.05, "desc": "Taille de position en % du capital"},
}


def has_ai_key() -> bool:
    """Verifie si une cle API est configuree pour le strategist."""
    try:
        keys_file = CONFIG_PATH / "api_keys.json"
        selections_file = CONFIG_PATH / "api_selections.json"

        if not keys_file.exists() or not selections_file.exists():
            return False

        with open(keys_file, "r", encoding="utf-8") as f:
            keys_data = json.load(f)
        with open(selections_file, "r", encoding="utf-8") as f:
            selections_data = json.load(f)

        key_id = selections_data.get("selections", {}).get("strategist")
        if not key_id:
            return False

        selected_key = next(
            (k for k in keys_data.get("keys", []) if k["id"] == key_id),
            None
        )
        return bool(selected_key and selected_key.get("key"))

    except Exception:
        return False


def build_system_prompt() -> str:
    """Construit le prompt systeme pour le Strategist IA."""
    return """Tu es le Strategist IA de G13, un systeme de trading algorithmique BTCUSD.

TON ROLE: Analyser les performances des 3 agents de trading et decider des VALEURS EXACTES pour leurs parametres.

LES 3 AGENTS:
- FIBO1: Trade sur niveau Fibonacci 0.236 (retracements legers)
- FIBO2: Trade sur niveau Fibonacci 0.382 (retracements moyens)
- FIBO3: Trade sur niveau Fibonacci 0.618 (retracements profonds)

PARAMETRES AJUSTABLES (bornes strictes a respecter):
- fibo_tolerance_pct: Zone autour du niveau Fibo (min=0.5, max=5.0)
- cooldown_seconds: Temps entre trades en secondes (min=60, max=600)
- tp_pct: Take Profit en % du capital (min=0.1, max=1.0)
- sl_pct: Stop Loss en % du capital (min=0.2, max=2.0)
- position_size_pct: Taille de position (min=0.005, max=0.05)

REGLES D'ANALYSE:
1. WR < 30% = probleme d'entree -> reduire fibo_tolerance_pct
2. Profit factor < 1.0 = pertes > gains -> ajuster tp_pct et/ou sl_pct
3. Perte moyenne > 2x gain moyen -> reduire sl_pct
4. WR > 70% sur 20+ trades = excellent -> peut augmenter position_size_pct prudemment
5. Trop de trades en peu de temps -> augmenter cooldown_seconds
6. Pas assez de trades -> augmenter fibo_tolerance_pct ou reduire cooldown_seconds
7. Compare les agents entre eux pour identifier les patterns

REGLES ANTI-OSCILLATION (CRITIQUE):
1. CONSULTE TOUJOURS l'historique des ajustements recents fourni
2. Ne JAMAIS inverser un ajustement fait il y a moins de 30 minutes
3. Si un parametre oscille (ajuste dans un sens puis l'autre), ARRETE de le modifier
4. Prefere la STABILITE: ne change que ce qui est clairement sous-optimal
5. Ne fais PAS de micro-ajustements inutiles (ex: 0.3 -> 0.35 -> 0.3)

REGLES DE COHERENCE:
- Ne PAS augmenter position_size_pct si profit_factor < 1.0 (contradictoire)
- Ne PAS augmenter tp_pct au-dela de 0.6% sans bonne raison (trades longs = risque)
- Si un agent performe bien, NE LE TOUCHE PAS

FORMAT DE REPONSE (JSON OBLIGATOIRE - rien d'autre):
{
  "analysis": "Resume global en 2-3 phrases",
  "trend_analysis": "Tendance globale en 1-2 phrases",
  "adjustments": [
    {
      "agent_id": "fibo1",
      "reason": "Explication precise et courte",
      "priority": "high",
      "changes": {
        "tp_pct": 0.4,
        "fibo_tolerance_pct": 2.5
      }
    }
  ]
}

IMPORTANT:
- Reponds UNIQUEMENT en JSON valide, pas de texte avant ou apres
- "changes" contient UNIQUEMENT les parametres a modifier (valeurs CIBLES exactes, pas des deltas)
- Si aucun changement necessaire pour un agent, NE L'INCLUS PAS dans adjustments
- Si TOUT est stable, retourne un tableau adjustments VIDE
- Respecte STRICTEMENT les bornes min/max
- priority: "critical", "high", "medium", ou "low"
- Chaque adjustment DOIT avoir agent_id, reason, priority, changes"""


def build_analysis_prompt() -> str:
    """Construit le prompt utilisateur avec performances + historique ajustements."""

    # Charger configs agents
    agents_config = {}
    try:
        with open(CONFIG_PATH / "agents.json", "r", encoding="utf-8") as f:
            agents_config = json.load(f)
    except Exception:
        pass

    # Charger et analyser les trades par agent
    agents_data = {}
    fibo_levels = {"fibo1": "0.236", "fibo2": "0.382", "fibo3": "0.618"}

    for agent_id in ["fibo1", "fibo2", "fibo3"]:
        trades = _load_closed_trades(agent_id)
        config = agents_config.get(agent_id, {})
        tpsl = config.get("tpsl_config", {})
        stats = _calculate_stats(trades)
        recent = trades[-10:] if len(trades) > 10 else trades

        agents_data[agent_id] = {
            "level": fibo_levels.get(agent_id, "?"),
            "config": config,
            "tpsl": tpsl,
            "stats": stats,
            "recent_trades": recent,
            "total_trades_count": len(trades)
        }

    # Construire le prompt
    prompt = "=== ANALYSE PERFORMANCES G13 ===\n\n"

    for agent_id, data in agents_data.items():
        cfg = data["config"]
        tpsl = data["tpsl"]
        stats = data["stats"]
        recent = data["recent_trades"]

        prompt += f"AGENT {agent_id.upper()} (niveau Fibonacci {data['level']}):\n"
        prompt += f"  Config actuelle: tolerance={cfg.get('fibo_tolerance_pct', '?')}%, "
        prompt += f"cooldown={cfg.get('cooldown_seconds', '?')}s, "
        prompt += f"TP={tpsl.get('tp_pct', '?')}%, "
        prompt += f"SL={tpsl.get('sl_pct', '?')}%, "
        prompt += f"position={cfg.get('position_size_pct', '?')}%\n"

        if stats:
            prompt += f"  Stats: {stats['total_trades']} trades | "
            prompt += f"Win Rate: {stats['winrate']}% | "
            prompt += f"Profit Factor: {stats['profit_factor']} | "
            prompt += f"P&L: {stats['total_profit']} EUR\n"
            prompt += f"  Gain moy: {stats['avg_win']} EUR | "
            prompt += f"Perte moy: {stats['avg_loss']} EUR | "
            prompt += f"Best: {stats['best_trade']} EUR | "
            prompt += f"Worst: {stats['worst_trade']} EUR\n"
        else:
            prompt += "  Stats: Aucun trade cloture\n"

        # Derniers trades
        if recent:
            prompt += f"  Derniers {len(recent)} trades:\n"
            for t in recent[-5:]:
                direction = t.get("direction", "?")
                profit = t.get("profit", 0)
                symbol = t.get("symbol", "BTCUSD")
                closed_at = t.get("closed_at", t.get("close_time", "?"))
                prompt += f"    - {direction} {symbol}: {'+' if profit >= 0 else ''}{profit} EUR ({closed_at})\n"

        prompt += "\n"

    # Stats globales
    all_trades = sum(d["stats"].get("total_trades", 0) for d in agents_data.values())
    all_wins = sum(d["stats"].get("wins", 0) for d in agents_data.values())
    all_profit = sum(d["stats"].get("total_profit", 0) for d in agents_data.values())

    global_wr = round(all_wins / all_trades * 100, 1) if all_trades > 0 else 0

    prompt += f"GLOBAL:\n"
    prompt += f"  Total trades: {all_trades} | Win Rate: {global_wr}% | P&L total: {round(all_profit, 2)} EUR\n\n"

    # Historique des ajustements recents
    from strategy.ia_adjust import get_ia_adjust
    recent_adjustments = get_ia_adjust().get_recent_adjustments(20)

    if recent_adjustments:
        prompt += "HISTORIQUE DES AJUSTEMENTS RECENTS (du plus recent au plus ancien):\n"
        for adj in recent_adjustments:
            ts = adj.get("timestamp", "?")[:16]
            agent = adj.get("agent_id", "?")
            field = adj.get("field", "?")
            old = adj.get("old_value", "?")
            new = adj.get("new_value", "?")
            adj_type = adj.get("type", "?")
            prompt += f"  [{ts}] {agent}: {field} {old} -> {new} ({adj_type})\n"
        prompt += "\n"
    else:
        prompt += "HISTORIQUE DES AJUSTEMENTS: Aucun ajustement recent.\n\n"

    prompt += "=== TA MISSION ===\n"
    prompt += "Analyse les performances ci-dessus. Consulte l'historique des ajustements pour eviter l'oscillation.\n"
    prompt += "Decide des VALEURS EXACTES pour les parametres a modifier. Ne touche pas a ce qui fonctionne bien.\n"
    prompt += "Reponds UNIQUEMENT en JSON valide."

    return prompt


def analyze_with_ai() -> Optional[Dict]:
    """
    Lance une analyse complete via IA.
    L'IA decide des valeurs exactes pour chaque parametre.

    Returns:
        dict: {
            "source": "ai",
            "format": "exact_values" ou "types",
            "analysis": str,
            "adjustments": List[dict],
            "trend_analysis": str
        }
        ou None si l'IA n'est pas disponible/echoue
    """
    if not has_ai_key():
        print("[Strategist AI] Pas de cle API configuree")
        return None

    from agents.ai_decision import call_ai

    system_prompt = build_system_prompt()
    user_prompt = build_analysis_prompt()

    print("[Strategist AI] Appel IA pour analyse avancee...")
    response = call_ai("strategist", user_prompt, system_prompt)

    if not response:
        print("[Strategist AI] Pas de reponse IA")
        return None

    # Parser la reponse JSON
    result = _parse_ai_response(response)
    if result:
        fmt = result.get("format", "?")
        adj_count = len(result.get("adjustments", result.get("suggestions", [])))
        print(f"[Strategist AI] Analyse OK ({fmt}): {adj_count} ajustement(s)")
        return result

    print("[Strategist AI] Echec parsing reponse IA")
    return None


def _parse_ai_response(response: str) -> Optional[Dict]:
    """Parse la reponse JSON de l'IA. Supporte le nouveau format (exact_values) et l'ancien (types)."""
    try:
        # Nettoyer la reponse (enlever markdown code blocks si present)
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)

        data = json.loads(cleaned)

        analysis = data.get("analysis", "")
        trend_analysis = data.get("trend_analysis", "")

        # === NOUVEAU FORMAT : adjustments avec valeurs exactes ===
        adjustments = data.get("adjustments", [])
        if adjustments and isinstance(adjustments, list):
            validated = []
            for adj in adjustments:
                if not isinstance(adj, dict):
                    continue
                agent_id = adj.get("agent_id", "")
                if agent_id not in ("fibo1", "fibo2", "fibo3"):
                    print(f"[Strategist AI] agent_id invalide ignore: {agent_id}")
                    continue
                changes = adj.get("changes", {})
                if not changes or not isinstance(changes, dict):
                    continue

                # Valider que les parametres sont connus
                valid_changes = {}
                for param, value in changes.items():
                    if param in PARAM_BOUNDS:
                        try:
                            valid_changes[param] = float(value)
                        except (ValueError, TypeError):
                            print(f"[Strategist AI] Valeur invalide pour {param}: {value}")
                    else:
                        print(f"[Strategist AI] Parametre inconnu ignore: {param}")

                if not valid_changes:
                    continue

                validated.append({
                    "agent_id": agent_id,
                    "reason": adj.get("reason", ""),
                    "priority": adj.get("priority", "medium"),
                    "changes": valid_changes
                })

            if validated:
                return {
                    "source": "ai",
                    "format": "exact_values",
                    "analysis": analysis,
                    "adjustments": validated,
                    "trend_analysis": trend_analysis
                }

        # === ANCIEN FORMAT (fallback) : suggestions avec types ===
        suggestions = data.get("suggestions", [])
        if suggestions and isinstance(suggestions, list):
            # Types compatibles avec l'ancien IAdjust
            valid_types = [
                "REDUCE_TOLERANCE", "INCREASE_TOLERANCE",
                "INCREASE_COOLDOWN", "REDUCE_COOLDOWN",
                "ADJUST_TPSL", "RISK_MANAGEMENT", "INCREASE_RISK"
            ]
            valid_suggestions = []
            for s in suggestions:
                if not isinstance(s, dict):
                    continue
                suggestion_type = s.get("type", "")
                if suggestion_type not in valid_types:
                    continue
                valid_suggestions.append({
                    "agent_id": s.get("agent_id", ""),
                    "type": suggestion_type,
                    "priority": s.get("priority", "medium"),
                    "reason": s.get("reason", ""),
                    "message": s.get("reason", ""),
                    "suggested_action": f"Appliquer {suggestion_type}"
                })

            if valid_suggestions:
                return {
                    "source": "ai",
                    "format": "types",
                    "analysis": analysis,
                    "suggestions": valid_suggestions,
                    "trend_analysis": trend_analysis
                }

        # Aucun ajustement (l'IA dit que tout est stable)
        return {
            "source": "ai",
            "format": "exact_values",
            "analysis": analysis,
            "adjustments": [],
            "trend_analysis": trend_analysis
        }

    except json.JSONDecodeError as e:
        print(f"[Strategist AI] JSON invalide: {e}")
        print(f"[Strategist AI] Reponse brute: {response[:300]}")
        return None
    except Exception as e:
        print(f"[Strategist AI] Erreur parsing: {e}")
        return None


def _load_closed_trades(agent_id: str) -> list:
    """Charge les trades clotures d'un agent."""
    file_path = DATABASE_PATH / "closed_trades" / f"{agent_id}.json"
    if not file_path.exists():
        return []
    try:
        with open(file_path, "r") as f:
            return json.load(f)
    except Exception:
        return []


def _calculate_stats(trades: list) -> dict:
    """Calcule les statistiques de trading."""
    if not trades:
        return {}

    profits = [t.get("profit", 0) for t in trades]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p < 0]

    total_wins = sum(wins) if wins else 0
    total_losses = abs(sum(losses)) if losses else 0

    return {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "winrate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
        "total_profit": round(sum(profits), 2),
        "avg_win": round(total_wins / len(wins), 2) if wins else 0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
        "profit_factor": round(total_wins / total_losses, 2) if total_losses > 0 else 0,
        "best_trade": round(max(profits), 2) if profits else 0,
        "worst_trade": round(min(profits), 2) if profits else 0
    }
