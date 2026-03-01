"""
G13 API - Routes Compatibilite G12
==================================
Routes pour compatibilite avec le frontend G12.
Mappe les anciennes routes vers les nouvelles.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, Dict, List, Any
import json
from pathlib import Path
from datetime import datetime

from actions.session import start_session, end_session, get_session_info
from actions.stats import get_stats, get_all_stats, calculate_stats
from actions.sync import sync_positions, sync_closed_trades, get_local_positions, get_local_closed_trades
from actions.mt5 import connect_mt5, disconnect_mt5, close_all_positions, get_full_market_data
from actions.decisions import get_recent_decisions
from strategy import get_strategist

# Import optionnel des modules data (peuvent echouer si requests non installe)
try:
    from data import get_binance, get_sentiment
    DATA_MODULES_AVAILABLE = True
except ImportError as e:
    print(f"[Warning] Modules data non disponibles: {e}")
    DATA_MODULES_AVAILABLE = False
    get_binance = None
    get_sentiment = None

router = APIRouter(prefix="/api", tags=["Compatibilite G12"])

DATABASE_PATH = Path(__file__).parent.parent / "database"
CONFIG_PATH = DATABASE_PATH / "config"


def _get_active_killzones() -> dict:
    """
    Determine quelles sessions de marche (killzones) sont actives
    en fonction de l'heure UTC actuelle.

    Horaires UTC standards:
    - ASIE (Tokyo):    00:00 - 09:00 UTC
    - LONDON:          07:00 - 16:00 UTC
    - KILLZONE (overlap LDN/NY): 12:00 - 15:00 UTC
    - NEW YORK:        13:00 - 22:00 UTC
    """
    from datetime import datetime, timezone
    now_utc = datetime.now(timezone.utc)
    h = now_utc.hour
    weekday = now_utc.weekday()  # 0=lundi ... 6=dimanche

    # Marches fermes le weekend (samedi + dimanche)
    is_weekend = weekday >= 5

    return {
        "asia":    {"active": not is_weekend and 0 <= h < 9,   "hours": "00:00-09:00 UTC"},
        "london":  {"active": not is_weekend and 7 <= h < 16,  "hours": "07:00-16:00 UTC"},
        "overlap": {"active": not is_weekend and 12 <= h < 15, "hours": "12:00-15:00 UTC"},
        "usa":     {"active": not is_weekend and 13 <= h < 22, "hours": "13:00-22:00 UTC"},
        "is_weekend": is_weekend,
    }


def _build_frontend_stats(all_stats: dict) -> dict:
    """
    Transforme les stats backend en format attendu par le frontend.
    Backend: wins, losses, winrate, avg_win
    Frontend: winning_trades, losing_trades, win_rate, avg_profit, + totaux agreges
    """
    agents = {}
    total_trades = 0
    total_wins = 0
    total_losses = 0
    total_profit = 0.0

    for agent_id in ["fibo1", "fibo2", "fibo3"]:
        s = all_stats.get(agent_id, {})
        trades = s.get("total_trades", 0)
        wins = s.get("wins", 0)
        losses = s.get("losses", 0)
        profit = s.get("total_profit", 0)

        agents[agent_id] = {
            "total_trades": trades,
            "winning_trades": wins,
            "losing_trades": losses,
            "win_rate": s.get("winrate", 0),
            "total_profit": round(profit, 2),
            "avg_profit": s.get("avg_win", 0),
        }

        total_trades += trades
        total_wins += wins
        total_losses += losses
        total_profit += profit

    global_winrate = round((total_wins / total_trades * 100), 2) if total_trades > 0 else 0

    return {
        "agents": agents,
        "total_trades": total_trades,
        "total_wins": total_wins,
        "total_losses": total_losses,
        "win_rate": global_winrate,
        "total_profit": round(total_profit, 2),
    }

# ===================== SESSION =====================

@router.get("/status")
async def get_status():
    """Status global du bot (compatibilite G12)."""
    import MetaTrader5 as mt5
    from core import get_trading_loop

    session = get_session_info()
    all_stats = get_all_stats()
    trading_loop = get_trading_loop()

    session_data = session.get("session", {})
    # is_trading = VRAI etat de la trading loop (pas le status session)
    # Garantit que G13 demarre ARRETE meme si session.json dit "active"
    is_trading = trading_loop.is_running

    # Charger configs agents
    agents_config = {}
    try:
        with open(CONFIG_PATH / "agents.json", "r") as f:
            agents_config = json.load(f)
    except:
        pass

    # Charger comptes MT5
    mt5_accounts = {}
    try:
        with open(CONFIG_PATH / "mt5_accounts.json", "r") as f:
            mt5_accounts = json.load(f)
    except:
        pass

    # Construire session avec le champ 'name' attendu par le frontend
    session_id = session_data.get("id", "")
    session_with_name = {
        **session_data,
        "name": session_id[:8] if session_id else "--",
        "sessions": _get_active_killzones()
    }

    # Recuperer donnees de marche et balances des comptes
    price_data = None
    accounts_with_balance = {}
    total_balance = 0
    total_equity = 0

    # TOUJOURS lire MT5 pour afficher balances/positions/P&L en temps reel
    # (meme quand la trading loop est arretee - on veut voir les positions ouvertes)
    live_positions = []
    connected_agents = set()  # Agents qui ont reussi a se connecter a MT5
    from actions.mt5.read_positions import read_positions

    for agent_id in ["fibo1", "fibo2", "fibo3"]:
        account_cfg = mt5_accounts.get(agent_id, {})
        accounts_with_balance[agent_id] = {
            "login": account_cfg.get("login", 0),
            "server": account_cfg.get("server", ""),
            "balance": 0,
            "equity": 0,
            "connected": False
        }

        connected = False
        try:
            connect_result = connect_mt5(agent_id)
            if not connect_result["success"]:
                continue
            connected = True
            connected_agents.add(agent_id)

            account_info = connect_result.get("account_info", {})
            balance = account_info.get("balance", 0)
            equity = account_info.get("equity", balance)

            accounts_with_balance[agent_id]["balance"] = balance
            accounts_with_balance[agent_id]["equity"] = equity
            accounts_with_balance[agent_id]["connected"] = True

            total_balance += balance
            total_equity += equity

            # Lire positions LIVE depuis MT5 (P&L en temps reel)
            pos_result = read_positions(agent_id)
            if pos_result["success"] and pos_result["positions"]:
                for pos in pos_result["positions"]:
                    pos["agent_id"] = agent_id
                live_positions.extend(pos_result["positions"])
            elif pos_result["success"] and pos_result["count"] == 0:
                # MT5 confirme 0 positions => nettoyer fichier local perime
                local_file = DATABASE_PATH / "open_positions" / f"{agent_id}.json"
                if local_file.exists():
                    try:
                        with open(local_file, "r") as lf:
                            old = json.load(lf)
                        if old:  # Fichier non vide = donnees perimes
                            with open(local_file, "w") as lf:
                                json.dump([], lf, indent=2)
                    except:
                        pass

            # Recuperer price data une seule fois (depuis fibo1)
            if agent_id == "fibo1" and price_data is None:
                try:
                    price_data = get_full_market_data("BTCUSD")
                except Exception as e:
                    print(f"[Status] Erreur market data: {e}")

        except Exception as e:
            print(f"[Status] EXCEPTION {agent_id}: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # TOUJOURS liberer le lock MT5 si connecte
            if connected:
                try:
                    disconnect_mt5()
                except:
                    pass

    # Recuperer donnees Binance Futures
    futures_data = None
    if DATA_MODULES_AVAILABLE and get_binance:
        try:
            binance = get_binance()
            binance_all = binance.get_all_data()
            if binance_all:
                futures_data = {
                    "funding_rate": binance_all.get("funding", {}).get("funding_rate") if binance_all.get("funding") else None,
                    "oi_change_1h": binance_all.get("open_interest", {}).get("change_1h_pct") if binance_all.get("open_interest") else None,
                    "long_short_ratio": binance_all.get("long_short_ratio", {}).get("long_short_ratio") if binance_all.get("long_short_ratio") else None,
                    "orderbook_imbalance": binance_all.get("orderbook", {}).get("imbalance_pct") if binance_all.get("orderbook") else None,
                    "orderbook_bias": binance_all.get("orderbook", {}).get("bias") if binance_all.get("orderbook") else None
                }
        except Exception as e:
            print(f"[Status] Erreur Binance: {e}")

    # Recuperer donnees Sentiment
    sentiment_data = None
    if DATA_MODULES_AVAILABLE and get_sentiment:
        try:
            sentiment = get_sentiment()
            sentiment_all = sentiment.get_all_sentiment()
            if sentiment_all:
                sentiment_data = {
                    "fear_greed_index": sentiment_all.get("fear_greed", {}).get("value") if sentiment_all.get("fear_greed") else None,
                    "fear_greed_label": sentiment_all.get("fear_greed", {}).get("label") if sentiment_all.get("fear_greed") else None,
                    "news_bias": sentiment_all.get("news_sentiment", {}).get("bias") if sentiment_all.get("news_sentiment") else None,
                    "global_bias": sentiment_all.get("global_bias")
                }
        except Exception as e:
            print(f"[Status] Erreur Sentiment: {e}")

    # Generer analyse
    analysis_data = None
    mom_1m = 0
    mom_5m = 0
    volatility = 0

    if price_data:
        mom_1m = price_data.get("fibo1", {}).get("1m", 0)
        mom_5m = price_data.get("fibo1", {}).get("5m", 0)
        volatility = price_data.get("volatility_pct", 0)

    # Determiner biais base sur momentum + sentiment + futures
    bullish_signals = 0
    bearish_signals = 0

    # Momentum signals
    if mom_1m > 0.05:
        bullish_signals += 1
    elif mom_1m < -0.05:
        bearish_signals += 1

    if mom_5m > 0.03:
        bullish_signals += 1
    elif mom_5m < -0.03:
        bearish_signals += 1

    # Sentiment signals
    if sentiment_data:
        fg = sentiment_data.get("fear_greed_index")
        if fg and fg < 30:
            bullish_signals += 1  # Extreme fear = buy signal
        elif fg and fg > 70:
            bearish_signals += 1  # Extreme greed = sell signal

    # Futures signals
    if futures_data:
        ob_bias = futures_data.get("orderbook_bias")
        if ob_bias == "bullish":
            bullish_signals += 1
        elif ob_bias == "bearish":
            bearish_signals += 1

    # Calculer bias et confidence
    total_signals = bullish_signals + bearish_signals
    if total_signals == 0:
        bias = "neutral"
        confidence = 50
    elif bullish_signals > bearish_signals:
        bias = "bullish"
        confidence = min(90, 50 + (bullish_signals - bearish_signals) * 15)
    elif bearish_signals > bullish_signals:
        bias = "bearish"
        confidence = min(90, 50 + (bearish_signals - bullish_signals) * 15)
    else:
        bias = "neutral"
        confidence = 50

    analysis_data = {
        "bias": bias,
        "confidence": confidence,
        "tendance": bias,
        "session": session_id[:8] if session_id else "--",
        "volatility_pct": volatility
    }

    # Ajouter label volatilite dans session (pour badge frontend)
    if volatility >= 2.0:
        session_with_name["volatility"] = "ultra"
    elif volatility >= 1.0:
        session_with_name["volatility"] = "high"
    elif volatility >= 0.5:
        session_with_name["volatility"] = "medium"
    else:
        session_with_name["volatility"] = "low"

    # Verifier si au moins un MT5 est connecte
    any_mt5_connected = any(acc.get("connected") for acc in accounts_with_balance.values())

    # Positions: MT5 live = source de verite pour les agents connectes
    # Fallback fichiers locaux UNIQUEMENT pour agents non connectes
    all_positions = list(live_positions)
    for agent_id in ["fibo1", "fibo2", "fibo3"]:
        if agent_id in connected_agents:
            # Agent connecte a MT5 => MT5 fait foi (meme si 0 positions)
            continue
        # Agent non connecte => fallback fichiers locaux
        try:
            result = get_local_positions(agent_id)
            positions = result.get("positions", [])
            all_positions.extend(positions)
        except Exception as e:
            print(f"[Status] Erreur positions {agent_id}: {e}")

    return {
        "trading_active": is_trading,
        "session": session_with_name,
        "loops": {
            "trading": {
                "running": is_trading
            }
        },
        "mt5": {
            "connected": any_mt5_connected
        },
        "agents": {
            agent_id: {
                "enabled": cfg.get("enabled", False),
                "name": cfg.get("name", agent_id),
                "stats": all_stats.get(agent_id, {}),
                # Champs attendus par le frontend (cartes agents)
                "session_pnl": all_stats.get(agent_id, {}).get("total_profit", 0),
                "session_trades": all_stats.get(agent_id, {}).get("total_trades", 0),
            }
            for agent_id, cfg in agents_config.items()
        },
        # Stats structurees pour le tableau "Stat Session" du frontend
        "stats": _build_frontend_stats(all_stats),
        "account": {
            "balance": total_balance or session_data.get("balance_start") or 0,
            "equity": total_equity or session_data.get("balance_start") or 0,
            "accounts": accounts_with_balance
        },
        "price": price_data,
        "futures": futures_data,
        "sentiment": sentiment_data,
        "analysis": analysis_data,
        "positions": all_positions,
        "decisions": get_recent_decisions(10)
    }


@router.get("/session")
async def get_session():
    """Info session enrichie (ID, debut, trades_count, total_pnl, killzones)."""
    info = get_session_info()
    session_data = info.get("session") or {}
    is_active = info.get("is_active", False)

    # Calculer trades_count et total_pnl depuis les stats
    all_stats = get_all_stats()
    trades_count = sum(s.get("total_trades", 0) for s in all_stats.values())
    total_pnl = sum(s.get("total_profit", 0) for s in all_stats.values())

    # Killzones basees sur l'heure UTC actuelle
    killzones = _get_active_killzones()

    # Format plat attendu par le frontend
    return {
        "active": is_active,
        "id": session_data.get("id"),
        "start_time": session_data.get("start_time"),
        "balance_start": session_data.get("balance_start"),
        "status": session_data.get("status", "stopped"),
        "trades_count": trades_count,
        "total_pnl": round(total_pnl, 2),
        "killzones": killzones,
        "duration_seconds": info.get("duration_seconds")
    }


@router.get("/session/performance")
async def get_session_performance():
    """Performance de la session avec historique pour graphiques."""
    all_stats = get_all_stats()
    session = get_session_info()

    total_trades = sum(s.get("total_trades", 0) for s in all_stats.values())
    total_profit = sum(s.get("total_profit", 0) for s in all_stats.values())

    # Charger l'historique de performance pour les graphiques
    performance = {}
    history_file = DATABASE_PATH / "performance_history.json"
    if history_file.exists():
        try:
            with open(history_file, "r") as f:
                performance = json.load(f)
        except Exception as e:
            print(f"[Performance] Erreur lecture historique: {e}")

    return {
        "session_id": session.get("session", {}).get("id"),
        "total_trades": total_trades,
        "total_profit": round(total_profit, 2),
        "by_agent": all_stats,
        "performance": performance
    }


@router.get("/session/start")
@router.post("/session/start")
async def api_session_start():
    """Creer une NOUVELLE session (appele uniquement par 'Nouvelle Session').
    force_new=True : reset les donnees et cree une session fraiche."""
    # Recuperer balance MT5 pour la nouvelle session
    total_balance = 0
    for agent_id in ["fibo1", "fibo2", "fibo3"]:
        try:
            result = connect_mt5(agent_id)
            if result["success"]:
                account_info = result.get("account_info", {})
                total_balance += account_info.get("balance", 0)
                disconnect_mt5()
        except:
            pass

    initial_balance = total_balance if total_balance > 0 else None
    print(f"[Nouvelle Session] Balance MT5 capturee: {total_balance}")
    return start_session(initial_balance=initial_balance, force_new=True)


@router.get("/session/end")
@router.post("/session/end")
async def api_session_end():
    """Terminer session (compatibilite G12)."""
    return end_session()


@router.post("/session/sync")
async def api_session_sync():
    """Sync session avec MT5 (compatibilite G12)."""
    results = {}
    total_new_trades = 0
    total_pnl = 0.0

    for agent_id in ["fibo1", "fibo2", "fibo3"]:
        try:
            connect_result = connect_mt5(agent_id)
            if connect_result["success"]:
                pos_result = sync_positions(agent_id)
                closed_result = sync_closed_trades(agent_id)
                results[agent_id] = {
                    "positions": pos_result,
                    "closed": closed_result
                }
                # Agreeger pour le frontend
                total_new_trades += closed_result.get("new_trades", 0)
                disconnect_mt5()
        except Exception as e:
            results[agent_id] = {"error": str(e)}

    # Calculer P&L total depuis les closed_trades locaux
    for agent_id in ["fibo1", "fibo2", "fibo3"]:
        try:
            local = get_local_closed_trades(agent_id)
            for t in local.get("trades", []):
                total_pnl += t.get("profit", 0)
        except Exception:
            pass

    return {
        "success": True,
        "results": results,
        "new_trades": total_new_trades,
        "total_synced_pnl": round(total_pnl, 2)
    }


# ===================== TRADING =====================

@router.post("/trading/start")
async def trading_start():
    """Demarrer le trading (compatibilite G12)."""
    from core import get_trading_loop

    # D'abord connecter aux 3 MT5 et recuperer les balances
    total_balance = 0
    connections = {}

    print("[Trading Start] Connexion aux comptes MT5...")

    for agent_id in ["fibo1", "fibo2", "fibo3"]:
        try:
            print(f"[Trading Start] Connexion {agent_id}...")
            result = connect_mt5(agent_id)
            if result["success"]:
                account_info = result.get("account_info", {})
                balance = account_info.get("balance", 0)
                total_balance += balance
                connections[agent_id] = {
                    "connected": True,
                    "balance": balance,
                    "login": account_info.get("login")
                }
                print(f"[Trading Start] {agent_id} connecte - Balance: {balance}")
                disconnect_mt5()
            else:
                connections[agent_id] = {
                    "connected": False,
                    "error": result.get("message", "Connection failed")
                }
                print(f"[Trading Start] {agent_id} ERREUR: {result.get('message')}")
        except Exception as e:
            connections[agent_id] = {"connected": False, "error": str(e)}
            print(f"[Trading Start] {agent_id} EXCEPTION: {e}")

    # Verifier qu'au moins un MT5 est connecte
    connected_count = sum(1 for c in connections.values() if c.get("connected"))
    print(f"[Trading Start] {connected_count}/3 comptes connectes - Balance totale: {total_balance}")

    if connected_count == 0:
        return {
            "success": False,
            "message": "Aucun compte MT5 connecte",
            "connections": connections
        }

    # Demarrer la session avec la balance totale
    result = start_session(initial_balance=total_balance)
    if result["success"]:
        # Demarrer la trading loop
        loop = get_trading_loop()
        loop.start()

    return {
        "success": result["success"],
        "message": result.get("message", ""),
        "connections": connections,
        "total_balance": total_balance
    }


@router.post("/trading/stop")
async def trading_stop():
    """Arreter le trading SANS terminer la session.
    La session persiste jusqu'a ce que l'utilisateur clique sur 'Nouvelle Session'.
    Cela permet de relancer start.bat et reprendre la meme session."""
    from core import get_trading_loop

    # Arreter la trading loop uniquement
    loop = get_trading_loop()
    loop.stop()

    # NE PAS appeler end_session() - la session reste active
    return {"success": True, "message": "Trading arrete. Session conservee."}


@router.post("/trading/close-all")
async def trading_close_all():
    """Fermer toutes les positions (compatibilite G12)."""
    results = {}
    for agent_id in ["fibo1", "fibo2", "fibo3"]:
        try:
            connect_result = connect_mt5(agent_id)
            if connect_result["success"]:
                results[agent_id] = close_all_positions(agent_id)
                disconnect_mt5()
        except Exception as e:
            results[agent_id] = {"error": str(e)}

    return {"success": True, "results": results}


# ===================== AGENTS =====================

@router.get("/agents/toggle")
async def toggle_agent(agent_id: str, enabled: bool):
    """Activer/desactiver un agent (compatibilite G12)."""
    try:
        with open(CONFIG_PATH / "agents.json", "r") as f:
            configs = json.load(f)

        if agent_id in configs:
            configs[agent_id]["enabled"] = enabled

            with open(CONFIG_PATH / "agents.json", "w") as f:
                json.dump(configs, f, indent=4)

            return {"success": True}

        return {"success": False, "error": "Agent not found"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ===================== CONFIG =====================

@router.get("/config/all")
async def get_all_config():
    """Toutes les configs (agents + risque global)."""
    result = {"agents": {}, "risk": {}, "spread": {}}
    try:
        with open(CONFIG_PATH / "agents.json", "r") as f:
            result["agents"] = json.load(f)
    except:
        pass
    try:
        risk_file = CONFIG_PATH / "risk_config.json"
        if risk_file.exists():
            with open(risk_file, "r") as f:
                result["risk"] = json.load(f)
    except:
        pass
    # Spread/Trailing/BE: lire depuis tpsl_config du premier agent (TP/SL sont par agent)
    try:
        first_agent = next(iter(result["agents"].values()), {})
        tpsl = first_agent.get("tpsl_config", {})
        if tpsl:
            result["spread"] = {
                "max_spread_points": tpsl.get("max_spread_points", 50),
                "spread_check_enabled": tpsl.get("spread_check_enabled", True),
                "trailing_start_pct": tpsl.get("trailing_start_pct", 0.2),
                "trailing_distance_pct": tpsl.get("trailing_distance_pct", 0.1),
                "trailing_enabled": tpsl.get("trailing_enabled", True),
                "break_even_pct": tpsl.get("break_even_pct", 0.15),
                "break_even_enabled": tpsl.get("break_even_enabled", True),
            }
    except:
        pass
    return result


@router.get("/config/agent/{agent_id}")
async def get_agent_config(agent_id: str):
    """Config d'un agent (compatibilite G12)."""
    try:
        with open(CONFIG_PATH / "agents.json", "r") as f:
            configs = json.load(f)
        return configs.get(agent_id, {})
    except:
        return {}


@router.post("/config/agent/{agent_id}")
async def update_agent_config(agent_id: str, config: Dict[str, Any]):
    """Mettre a jour config agent avec deep merge pour tpsl_config."""
    try:
        with open(CONFIG_PATH / "agents.json", "r") as f:
            configs = json.load(f)

        if agent_id in configs:
            # Deep merge pour tpsl_config (ne pas ecraser les cles non envoyees)
            if "tpsl_config" in config and isinstance(config["tpsl_config"], dict):
                existing_tpsl = configs[agent_id].get("tpsl_config", {})
                existing_tpsl.update(config["tpsl_config"])
                configs[agent_id]["tpsl_config"] = existing_tpsl
                del config["tpsl_config"]

            # Shallow merge pour le reste des cles
            configs[agent_id].update(config)

            with open(CONFIG_PATH / "agents.json", "w") as f:
                json.dump(configs, f, indent=4)

            return {"success": True}

        return {"success": False, "error": "Agent not found"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ===================== ACCOUNTS MT5 =====================

@router.get("/accounts")
async def get_accounts():
    """Liste des comptes MT5 (compatibilite G12)."""
    try:
        with open(CONFIG_PATH / "mt5_accounts.json", "r") as f:
            return json.load(f)
    except:
        return {}


@router.get("/accounts/status/all")
async def get_accounts_status():
    """Status de tous les comptes MT5 (compatibilite G12)."""
    accounts = {}
    try:
        with open(CONFIG_PATH / "mt5_accounts.json", "r") as f:
            mt5_config = json.load(f)

        for agent_id, config in mt5_config.items():
            accounts[agent_id] = {
                "login": config.get("login"),
                "server": config.get("server"),
                "enabled": config.get("enabled", False),
                "connected": False,
                "balance": 0
            }
    except:
        pass

    return accounts


@router.post("/accounts/{agent_id}")
async def update_account(agent_id: str, config: Dict[str, Any]):
    """Mettre a jour compte MT5 (compatibilite G12)."""
    try:
        with open(CONFIG_PATH / "mt5_accounts.json", "r") as f:
            configs = json.load(f)

        if agent_id in configs:
            configs[agent_id].update(config)

            with open(CONFIG_PATH / "mt5_accounts.json", "w") as f:
                json.dump(configs, f, indent=4)

            return {"success": True}

        return {"success": False, "error": "Account not found"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/accounts/{agent_id}/test")
async def test_account(agent_id: str):
    """Tester connexion MT5 (compatibilite G12)."""
    result = connect_mt5(agent_id)
    if result["success"]:
        disconnect_mt5()
    return result


# ===================== TRADES =====================

@router.get("/trades")
async def get_trades(agent: str = None, limit: int = 100):
    """Liste des trades (compatibilite G12)."""
    agents_to_query = [agent] if agent and agent != "all" else ["fibo1", "fibo2", "fibo3"]

    all_trades = []
    for agent_id in agents_to_query:
        result = get_local_closed_trades(agent_id, limit=limit)
        all_trades.extend(result.get("trades", []))

    # Trier par temps de fermeture (plus recent en premier)
    all_trades.sort(key=lambda x: x.get("time", 0), reverse=True)
    raw = all_trades[:limit]

    # Transformer en format attendu par le frontend
    trades = []
    for t in raw:
        # Direction originale = inverse du closing deal type
        close_type = t.get("type", "")
        if close_type == "SELL":
            direction = "BUY"
        elif close_type == "BUY":
            direction = "SELL"
        else:
            direction = close_type

        # Convertir timestamp unix en ISO
        close_time = t.get("time", 0)
        timestamp = datetime.fromtimestamp(close_time).isoformat() if close_time else None

        trades.append({
            "ticket": t.get("position_id", t.get("ticket", 0)),
            "agent_id": t.get("agent_id", ""),
            "symbol": t.get("symbol", ""),
            "direction": direction,
            "volume": t.get("volume", 0),
            "entry_price": t.get("open_price", 0),
            "exit_price": t.get("price", 0),
            "profit": t.get("profit", 0),
            "profit_eur": t.get("profit", 0),
            "timestamp": timestamp,
            "close_reason": t.get("comment", ""),
        })

    return {"trades": trades}


@router.post("/positions/validate")
async def api_validate_positions():
    """Valider positions et nettoyer les fantomes."""
    from actions.sync import validate_positions as do_validate
    from actions.sync import auto_fix_positions

    results = {}
    for agent_id in ["fibo1", "fibo2", "fibo3"]:
        try:
            connect_result = connect_mt5(agent_id)
            if connect_result["success"]:
                validation = do_validate(agent_id)
                removed = 0
                # Si positions fantomes detectees, nettoyer en re-syncant depuis MT5
                extra = validation.get("extra_locally", [])
                if extra:
                    auto_fix_positions(agent_id)
                    removed = len(extra)
                disconnect_mt5()
                results[agent_id] = {
                    "valid": validation.get("valid", False),
                    "removed": removed,
                    "message": validation.get("message", "")
                }
            else:
                results[agent_id] = {"valid": False, "removed": 0, "message": "MT5 non connecte"}
        except Exception as e:
            results[agent_id] = {"valid": False, "removed": 0, "error": str(e)}

    return {"success": True, "results": results}


@router.post("/open-history-folder")
async def open_history_folder():
    """Ouvre le dossier history/ dans l'explorateur de fichiers."""
    import subprocess
    history_path = DATABASE_PATH / "history"
    history_path.mkdir(exist_ok=True)
    try:
        subprocess.Popen(["explorer", str(history_path.resolve())])
        return {"success": True, "message": "Dossier ouvert"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/restart-backend")
async def restart_backend():
    """Redemarre le serveur backend G13.
    Cree un script .bat temporaire, le lance dans une nouvelle fenetre,
    puis arrete le processus actuel proprement."""
    import threading
    import os

    backend_dir = Path(__file__).parent.parent

    def _do_restart():
        import time
        time.sleep(0.5)  # Laisser la reponse HTTP partir

        # Creer un script de redemarrage temporaire
        restart_bat = backend_dir / "_restart.bat"
        with open(restart_bat, "w") as f:
            f.write("@echo off\n")
            f.write("title G13 Backend\n")
            f.write("echo ========================================\n")
            f.write("echo       G13 Backend - Redemarrage\n")
            f.write("echo ========================================\n")
            f.write("echo.\n")
            f.write("echo Attente arret ancien processus...\n")
            f.write("timeout /t 3 /nobreak >nul\n")
            f.write(f'cd /d "{backend_dir}"\n')
            f.write("echo Demarrage uvicorn...\n")
            f.write("python -m uvicorn main:app --host 0.0.0.0 --port 8000\n")
            f.write("pause\n")

        # Lancer le script dans une nouvelle fenetre (aucun probleme de guillemets)
        os.startfile(str(restart_bat))

        # Arreter le processus actuel
        os._exit(0)

    threading.Thread(target=_do_restart, daemon=True).start()
    return {"success": True, "message": "Redemarrage en cours..."}


# ===================== KEYS API =====================

@router.get("/keys")
async def get_keys():
    """Liste des cles API (compatibilite G12)."""
    try:
        with open(CONFIG_PATH / "api_keys.json", "r") as f:
            data = json.load(f)
            return {"keys": data.get("keys", [])}
    except:
        return {"keys": []}


@router.get("/keys/selections")
async def get_keys_selections():
    """Selections des cles API (compatibilite G12)."""
    try:
        with open(CONFIG_PATH / "api_selections.json", "r") as f:
            data = json.load(f)
            return {"selections": data.get("selections", {})}
    except:
        return {"selections": {}}


@router.post("/keys/selections")
async def update_keys_selections(selections: Dict[str, str]):
    """Mettre a jour selections cles API (compatibilite G12)."""
    try:
        with open(CONFIG_PATH / "api_selections.json", "w") as f:
            json.dump({"selections": selections}, f, indent=4)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/keys")
async def manage_keys(request: Request):
    """Gerer les cles API - accepte le tableau complet depuis le frontend."""
    try:
        body = await request.json()

        # Le frontend envoie {"keys": [...]} - ecriture directe
        if "keys" in body:
            with open(CONFIG_PATH / "api_keys.json", "w") as f:
                json.dump({"keys": body["keys"]}, f, indent=4)
            return {"success": True}

        return {"success": False, "error": "Format invalide: 'keys' manquant"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ===================== STRATEGIST =====================

@router.get("/strategist/insights")
async def get_strategist_insights():
    """Insights du Strategist (compatibilite G12)."""
    strategist = get_strategist()
    return strategist.get_quick_summary()


@router.get("/strategist/analyze")
async def strategist_analyze():
    """Analyse enrichie du Strategist - IA si cle disponible, sinon regles."""
    strategist = get_strategist()

    # Utiliser analyze_with_ai() qui gere le fallback automatiquement
    ai_result = strategist.analyze_with_ai()
    source = ai_result.get("source", "rules")
    raw = ai_result.get("agents", strategist.get_all_agents_analysis())

    # Construire le format attendu par le frontend
    by_agent = {}
    total_trades = 0
    total_wins = 0
    total_losses = 0
    total_profit = 0.0
    total_win_amount = 0.0
    total_loss_amount = 0.0
    max_win = 0.0
    max_loss = 0.0
    any_data = False

    for agent_id, data in raw.items():
        stats = data.get("stats", {})
        evaluation = data.get("evaluation", "insufficient_data")

        trades = stats.get("total_trades", 0)
        if trades > 0:
            any_data = True

        total_trades += trades
        total_wins += stats.get("wins", 0)
        total_losses += stats.get("losses", 0)
        total_profit += stats.get("total_profit", 0)

        avg_w = stats.get("avg_win", 0)
        avg_l = stats.get("avg_loss", 0)
        wins_count = stats.get("wins", 0)
        losses_count = stats.get("losses", 0)
        total_win_amount += avg_w * wins_count
        total_loss_amount += abs(avg_l) * losses_count

        best = stats.get("best_trade", 0)
        worst = stats.get("worst_trade", 0)
        if best > max_win:
            max_win = best
        if worst < max_loss:
            max_loss = worst

        by_agent[agent_id] = {
            "total_trades": trades,
            "win_rate": stats.get("winrate", 0),
            "profit_factor": stats.get("profit_factor", 0),
            "total_profit": stats.get("total_profit", 0),
            "evaluation": evaluation
        }

    if not any_data:
        return {
            "status": "insufficient_data",
            "message": f"Besoin de {strategist.MIN_TRADES_FOR_ANALYSIS} trades minimum"
        }

    # Suggestions : format exact_values (nouveau) ou types (ancien)
    all_suggestions = []
    fmt = ai_result.get("format", "types")

    if fmt == "exact_values":
        # Nouveau format : afficher les valeurs exactes
        for adj in ai_result.get("adjustments", []):
            changes = adj.get("changes", {})
            changes_str = ", ".join(f"{k}: {v}" for k, v in changes.items())
            all_suggestions.append({
                "priority": adj.get("priority", "medium"),
                "category": "EXACT_VALUES",
                "suggestion": f"{adj.get('agent_id', '').upper()}: {changes_str}",
                "reason": adj.get("reason", ""),
                "agent_id": adj.get("agent_id", ""),
                "changes": changes
            })
    else:
        # Ancien format : types de suggestions
        for s in ai_result.get("suggestions", []):
            all_suggestions.append({
                "priority": s.get("priority", "medium"),
                "category": s.get("type", s.get("category", "")),
                "suggestion": s.get("reason", s.get("message", s.get("suggestion", ""))),
                "reason": s.get("suggested_action", s.get("reason", "")),
                "agent_id": s.get("agent_id", "")
            })

    # Stats globales
    global_winrate = round(total_wins / total_trades * 100, 1) if total_trades > 0 else 0
    total_loss_abs = total_loss_amount if total_loss_amount > 0 else 1
    global_pf = round(total_win_amount / total_loss_abs, 2)
    avg_win = round(total_win_amount / total_wins, 2) if total_wins > 0 else 0
    avg_loss = round(-total_loss_amount / total_losses, 2) if total_losses > 0 else 0

    return {
        "status": "ok",
        "source": source,
        "ai_analysis": ai_result.get("analysis", ""),
        "trend_analysis": ai_result.get("trend_analysis", ""),
        "suggestions": all_suggestions,
        "by_agent": by_agent,
        "global": {
            "total_trades": total_trades,
            "win_rate": global_winrate,
            "profit_factor": global_pf,
            "total_profit": round(total_profit, 2),
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "max_win": round(max_win, 2),
            "max_loss": round(max_loss, 2)
        }
    }


@router.post("/strategist/execute")
async def strategist_execute():
    """Executer suggestions Strategist (valeurs exactes IA ou regles fallback)."""
    from strategy import get_ia_adjust
    from actions.mt5 import connect_mt5, disconnect_mt5, modify_trade_sl_tp

    strategist = get_strategist()
    ia_adjust = get_ia_adjust()

    # Charger configs agents
    agents_cfg = {}
    try:
        with open(CONFIG_PATH / "agents.json", "r") as f:
            agents_cfg = json.load(f)
    except Exception:
        pass

    # Lancer l'analyse IA/regles
    ai_result = strategist.analyze_with_ai()
    fmt = ai_result.get("format", "types")

    results = {}
    executed_count = 0
    all_mt5_mods = {}

    if fmt == "exact_values":
        # Nouveau format : valeurs exactes
        for adj in ai_result.get("adjustments", []):
            agent_id = adj.get("agent_id", "")
            if agent_id not in ("fibo1", "fibo2", "fibo3"):
                continue
            if not agents_cfg.get(agent_id, {}).get("ia_adjust_enabled", False):
                continue

            result = ia_adjust.apply_exact_values(
                agent_id, adj.get("changes", {}), adj.get("reason", "")
            )
            results[agent_id] = result
            executed_count += len(result.get("adjustments", []))

            if result.get("mt5_modifications"):
                all_mt5_mods[agent_id] = result["mt5_modifications"]
    else:
        # Ancien format : regles
        for agent_id in ["fibo1", "fibo2", "fibo3"]:
            if not agents_cfg.get(agent_id, {}).get("ia_adjust_enabled", False):
                continue

            analysis = strategist.analyze(agent_id)
            suggestions = analysis.get("suggestions", [])

            if suggestions:
                result = ia_adjust.auto_adjust(agent_id, suggestions)
                results[agent_id] = result
                executed_count += len(result.get("adjustments", []))

                if result.get("mt5_modifications"):
                    all_mt5_mods[agent_id] = result["mt5_modifications"]

    # Appliquer les modifications MT5 (SL/TP positions ouvertes)
    mt5_results = {}
    for agent_id, mods in all_mt5_mods.items():
        try:
            conn = connect_mt5(agent_id)
            if conn.get("success"):
                modified = 0
                for mod in mods:
                    ticket = mod.get("ticket")
                    if not ticket:
                        continue
                    mod_result = modify_trade_sl_tp(
                        ticket=ticket,
                        new_sl=mod.get("new_sl"),
                        new_tp=mod.get("new_tp"),
                        symbol=mod.get("symbol")
                    )
                    if mod_result.get("success") and mod_result.get("changed"):
                        modified += 1
                disconnect_mt5()
                mt5_results[agent_id] = f"{modified} position(s) modifiee(s)"
            else:
                mt5_results[agent_id] = "connexion MT5 echouee"
        except Exception as e:
            mt5_results[agent_id] = f"erreur: {e}"
            try:
                disconnect_mt5()
            except Exception:
                pass

    return {
        "success": True,
        "results": results,
        "executed_count": executed_count,
        "mt5_modifications": mt5_results
    }


@router.get("/strategist/logs")
async def get_strategist_logs(limit: int = 50):
    """Logs du Strategist - transformes au format attendu par le frontend."""
    from strategy import get_ia_adjust
    ia_adjust = get_ia_adjust()
    raw_logs = ia_adjust.get_recent_adjustments(limit=limit)

    # Transformer au format frontend (type, timestamp, reason, details)
    TYPE_LABELS = {
        "REDUCE_TOLERANCE": "Tolerance reduite",
        "INCREASE_TOLERANCE": "Tolerance augmentee",
        "INCREASE_COOLDOWN": "Cooldown augmente",
        "REDUCE_COOLDOWN": "Cooldown reduit",
        "ADJUST_TPSL": "TP/SL ajuste",
        "RISK_MANAGEMENT": "Gestion du risque",
        "INCREASE_RISK": "Risque augmente",
        "MANUAL_ADJUST": "Ajustement manuel",
        "EXACT_VALUE": "Valeur exacte IA",
    }

    logs = []
    for log in raw_logs:
        action_type = log.get("type", "")
        agent = log.get("agent_id", "")
        field = log.get("field", "")
        old_val = log.get("old_value")
        new_val = log.get("new_value")
        label = TYPE_LABELS.get(action_type, action_type)

        logs.append({
            "type": "ACTION_EXECUTED",
            "timestamp": log.get("timestamp"),
            "reason": f"{label} - Agent {agent.upper()}: {field} ({old_val} -> {new_val})",
            "details": {
                "action": action_type,
                "agent": agent,
                "field": field,
                "old_value": old_val,
                "new_value": new_val
            }
        })

    return {"logs": logs}


# ===================== CONFIG SPREAD/RISK =====================

@router.get("/config/spread")
async def get_spread_config():
    """Config spread (sans TP/SL qui sont maintenant par agent)."""
    try:
        with open(CONFIG_PATH / "agents.json", "r") as f:
            agents = json.load(f)

        first_agent = next(iter(agents.values()), {})
        tpsl = first_agent.get("tpsl_config", {})

        return {
            "max_spread_points": tpsl.get("max_spread_points", 50),
            "spread_check_enabled": tpsl.get("spread_check_enabled", True),
            "trailing_start_pct": tpsl.get("trailing_start_pct", 0.2),
            "trailing_distance_pct": tpsl.get("trailing_distance_pct", 0.1),
            "trailing_enabled": tpsl.get("trailing_enabled", True),
            "break_even_pct": tpsl.get("break_even_pct", 0.15),
            "break_even_enabled": tpsl.get("break_even_enabled", True)
        }
    except:
        return {
            "max_spread_points": 50,
            "spread_check_enabled": True,
            "trailing_start_pct": 0.2,
            "trailing_distance_pct": 0.1,
            "trailing_enabled": True,
            "break_even_pct": 0.15,
            "break_even_enabled": True
        }


@router.post("/config/spread")
async def update_spread_config(config: Dict[str, Any]):
    """Update spread/trailing/break-even config (global, applique a tous les agents). TP/SL sont par agent."""
    try:
        with open(CONFIG_PATH / "agents.json", "r") as f:
            agents = json.load(f)

        # Appliquer a TOUS les agents (spread, trailing, break-even sont globaux)
        for agent_id in agents:
            if "tpsl_config" not in agents[agent_id]:
                agents[agent_id]["tpsl_config"] = {}

            tpsl = agents[agent_id]["tpsl_config"]
            tp_pct = tpsl.get("tp_pct", 0.3)

            # Spread - clamp max_spread_points a 100
            if "max_spread_points" in config:
                val = float(config["max_spread_points"])
                tpsl["max_spread_points"] = min(val, 100.0)
            if "spread_check_enabled" in config:
                tpsl["spread_check_enabled"] = bool(config["spread_check_enabled"])
            # Trailing
            if "trailing_distance_pct" in config:
                tpsl["trailing_distance_pct"] = float(config["trailing_distance_pct"])
            trail_dist = tpsl.get("trailing_distance_pct", 0.1)
            if "trailing_start_pct" in config:
                val = float(config["trailing_start_pct"])
                # Garde-fou: trailing_start >= tp - distance
                min_start = round(tp_pct - trail_dist, 4)
                tpsl["trailing_start_pct"] = max(val, min_start)
            if "trailing_enabled" in config:
                tpsl["trailing_enabled"] = bool(config["trailing_enabled"])
            # Break Even - clamp a tp_pct max
            if "break_even_pct" in config:
                val = float(config["break_even_pct"])
                tpsl["break_even_pct"] = min(val, tp_pct)
            if "break_even_enabled" in config:
                tpsl["break_even_enabled"] = bool(config["break_even_enabled"])

        with open(CONFIG_PATH / "agents.json", "w") as f:
            json.dump(agents, f, indent=4)

        print(f"[Config] Spread/Trailing/BE mis a jour: {config}")
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/config/risk")
async def get_risk_config():
    """Retourne la config risque globale depuis risk_config.json."""
    try:
        risk_file = CONFIG_PATH / "risk_config.json"
        if risk_file.exists():
            with open(risk_file, "r") as f:
                return json.load(f)
        return {
            "max_drawdown_pct": 10,
            "max_daily_loss_pct": 5,
            "emergency_close_pct": 15,
            "winner_never_loser": True
        }
    except:
        return {}


@router.post("/config/risk")
async def update_risk_config(config: Dict[str, Any]):
    """Update risk config GLOBAL - sauvegarde dans risk_config.json (pas agents.json)."""
    try:
        risk_file = CONFIG_PATH / "risk_config.json"

        # Charger config existante
        current = {}
        if risk_file.exists():
            with open(risk_file, "r") as f:
                current = json.load(f)

        # Mettre a jour les champs recus
        if "max_drawdown_pct" in config:
            current["max_drawdown_pct"] = float(config["max_drawdown_pct"])
        if "max_daily_loss_pct" in config:
            current["max_daily_loss_pct"] = float(config["max_daily_loss_pct"])
        if "emergency_close_pct" in config:
            current["emergency_close_pct"] = float(config["emergency_close_pct"])
        if "winner_never_loser" in config:
            current["winner_never_loser"] = bool(config["winner_never_loser"])

        with open(risk_file, "w") as f:
            json.dump(current, f, indent=4)

        print(f"[Config] Risk GLOBAL mis a jour: {current}")
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ===================== SESSION EXPORT =====================

@router.get("/session/export")
async def export_session():
    """Exporter la session (compatibilite G12)."""
    session = get_session_info()
    all_stats = get_all_stats()

    all_trades = []
    for agent_id in ["fibo1", "fibo2", "fibo3"]:
        result = get_local_closed_trades(agent_id)
        all_trades.extend(result.get("trades", []))

    return {
        "session": session.get("session", {}),
        "stats": all_stats,
        "trades": all_trades,
        "exported_at": datetime.now().isoformat()
    }
