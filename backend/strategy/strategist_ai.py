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

# Parametres ajustables avec bornes (synchronise avec IAdjust)
PARAM_BOUNDS = {
    "fibo_tolerance_pct": {"min": 0.5, "max": 5.0, "desc": "Zone autour du niveau Fibonacci (%)"},
    "cooldown_seconds":   {"min": 60,  "max": 600, "desc": "Temps d'attente entre trades (secondes)"},
    "tp_pct":             {"min": 0.1, "max": 1.0, "desc": "Take Profit en % du capital"},
    "sl_pct":             {"min": 0.2, "max": 1.0, "desc": "Stop Loss en % du capital"},
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
    return """Tu es l'optimiseur de G13, un systeme de trading BTCUSD en argent reel.

OBJECTIF UNIQUE: Rendre chaque agent MATHEMATIQUEMENT rentable.

=== LA SEULE CHOSE QUI COMPTE ===

Un agent est rentable si et seulement si:
  Esperance = (WinRate x GainMoyen) - ((1 - WinRate) x PerteMoyenne) > 0

Exemple PERDANT:
  TP=0.4%, SL=1.2% -> Gain moy ~1.5 EUR, Perte moy ~13 EUR
  WR minimum pour survivre = 13 / (1.5 + 13) = 89.6%
  -> Meme avec 70% de win rate, cette config PERD de l'argent

Exemple GAGNANT:
  TP=0.5%, SL=0.3% -> Gain moy ~5 EUR, Perte moy ~3 EUR
  WR minimum = 3 / (5 + 3) = 37.5%
  -> Rentable des 38% de win rate

=== LES 3 AGENTS ===
- FIBO1: Fibonacci 0.236 (retracements legers)
- FIBO2: Fibonacci 0.382 (retracements moyens)
- FIBO3: Fibonacci 0.618 (retracements profonds)

=== PARAMETRES AJUSTABLES (bornes strictes) ===
- tp_pct: Take Profit en % du capital (min=0.1, max=1.0) - ce que tu gagnes
- sl_pct: Stop Loss en % du capital (min=0.2, max=1.0) - ce que tu perds
- fibo_tolerance_pct: Zone d'entree autour du Fibo (min=0.5, max=5.0)
- cooldown_seconds: Pause entre trades (min=60, max=600)
- position_size_pct: Taille position (min=0.005, max=0.05)

=== REGLE ABSOLUE ===
Le SL doit TOUJOURS etre <= 1.5x le TP.
Si TP=0.4%, alors SL max = 0.6%. JAMAIS plus.
Un SL > TP signifie que chaque perte efface plusieurs gains = mort lente mathematique.

=== COMMENT DECIDER ===
1. CALCULE l'esperance de chaque agent avec la formule ci-dessus
2. Si esperance < 0: le ratio TP/SL est le probleme -> REDUIS le SL ou AUGMENTE le TP
3. Si esperance > 0: NE TOUCHE A RIEN (la stabilite compte plus que l'optimisation)
4. Si pas assez de trades: ajuste tolerance ou cooldown, PAS le TP/SL
5. Compare les agents: celui qui marche le mieux = reference pour les autres
6. Ne PAS augmenter position_size_pct si profit_factor < 1.0

=== STABILITE (CRITIQUE) ===
- Maximum 1-2 parametres modifies par agent par cycle
- Pas de micro-ajustements (ecart < 0.1 = inutile, ne change rien)
- Regarde l'historique fourni: si un parametre a ete modifie recemment, NE LE RETOUCHE PAS
- Un agent rentable (esperance > 0) NE DOIT PAS etre modifie

=== FORMAT DE REPONSE (JSON strict, rien d'autre) ===
{
  "analysis": "Resume global 2-3 phrases avec calcul d'esperance par agent",
  "trend_analysis": "Tendance en 1-2 phrases",
  "adjustments": [
    {
      "agent_id": "fibo1",
      "reason": "Esperance = -X EUR/trade. SL trop grand vs TP. Reduction SL pour ratio favorable.",
      "priority": "high",
      "changes": {"sl_pct": 0.3}
    }
  ]
}

REGLES FORMAT:
- JSON valide UNIQUEMENT, pas de texte avant ou apres
- "changes" = valeurs CIBLES exactes (pas des deltas)
- Si aucun changement pour un agent, NE L'INCLUS PAS
- Si TOUT est stable, adjustments = []
- priority: "critical", "high", "medium", "low"
- Dans "reason", INCLUS TOUJOURS le calcul d'esperance qui justifie ta decision"""


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

        if stats and stats.get("total_trades", 0) > 0:
            wr = stats['winrate'] / 100  # en decimal
            avg_win = stats['avg_win']
            avg_loss = abs(stats['avg_loss'])
            esperance = round((wr * avg_win) - ((1 - wr) * avg_loss), 2)
            wr_minimum = round(avg_loss / (avg_win + avg_loss) * 100, 1) if (avg_win + avg_loss) > 0 else 0
            sl_tp_ratio = round(float(tpsl.get('sl_pct', 0.5)) / float(tpsl.get('tp_pct', 0.3)), 2) if float(tpsl.get('tp_pct', 0.3)) > 0 else 999

            prompt += f"  Stats: {stats['total_trades']} trades | "
            prompt += f"Win Rate: {stats['winrate']}% | "
            prompt += f"Profit Factor: {stats['profit_factor']} | "
            prompt += f"P&L: {stats['total_profit']} EUR\n"
            prompt += f"  Gain moy: +{avg_win} EUR | "
            prompt += f"Perte moy: -{avg_loss} EUR\n"
            prompt += f"  >>> ESPERANCE PAR TRADE: {'+' if esperance >= 0 else ''}{esperance} EUR "
            prompt += f"({'RENTABLE' if esperance > 0 else 'PERDANT'})\n"
            prompt += f"  >>> WR minimum requis: {wr_minimum}% (actuel: {stats['winrate']}%)\n"
            prompt += f"  >>> Ratio SL/TP: {sl_tp_ratio}x "
            prompt += f"({'OK' if sl_tp_ratio <= 1.5 else 'DANGEREUX - SL trop grand vs TP'})\n"
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
    response = call_ai("strategist", user_prompt, system_prompt, max_tokens=1500)

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
