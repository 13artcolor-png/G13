"""
G13 API - Routes Compatibilite G12
==================================
Routes pour compatibilite avec le frontend G12.
Mappe les anciennes routes vers les nouvelles.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, List, Any
import json
from pathlib import Path
from datetime import datetime

from actions.session import start_session, end_session, get_session_info
from actions.stats import get_stats, get_all_stats, calculate_stats
from actions.sync import sync_positions, sync_closed_trades, get_local_positions, get_local_closed_trades
from actions.mt5 import connect_mt5, disconnect_mt5, close_all_positions, get_full_market_data
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
    is_trading = session_data.get("status") == "active"

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
        "name": session_id[:8] if session_id else "--"
    }

    # Recuperer donnees de marche et balances des comptes
    price_data = None
    accounts_with_balance = {}
    total_balance = 0
    total_equity = 0

    # Recuperer balance/equity de chaque compte MT5 individuellement
    for agent_id in ["fibo1", "fibo2", "fibo3"]:
        account_cfg = mt5_accounts.get(agent_id, {})
        accounts_with_balance[agent_id] = {
            "login": account_cfg.get("login", 0),
            "server": account_cfg.get("server", ""),
            "balance": 0,
            "equity": 0,
            "connected": False
        }

        if is_trading:
            try:
                connect_result = connect_mt5(agent_id)
                if connect_result["success"]:
                    account_info = connect_result.get("account_info", {})
                    balance = account_info.get("balance", 0)
                    equity = account_info.get("equity", balance)

                    accounts_with_balance[agent_id]["balance"] = balance
                    accounts_with_balance[agent_id]["equity"] = equity
                    accounts_with_balance[agent_id]["connected"] = True

                    total_balance += balance
                    total_equity += equity

                    # Recuperer price data une seule fois (depuis fibo1)
                    if agent_id == "fibo1" and price_data is None:
                        price_data = get_full_market_data("BTCUSD")

                    disconnect_mt5()
            except Exception as e:
                print(f"[Status] Erreur compte {agent_id}: {e}")

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

    # Verifier si au moins un MT5 est connecte
    any_mt5_connected = any(acc.get("connected") for acc in accounts_with_balance.values())

    # Recuperer toutes les positions ouvertes depuis les fichiers JSON locaux
    all_positions = []
    for agent_id in ["fibo1", "fibo2", "fibo3"]:
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
                "stats": all_stats.get(agent_id, {})
            }
            for agent_id, cfg in agents_config.items()
        },
        "stats": all_stats,
        "account": {
            "balance": total_balance or session_data.get("balance_start") or 0,
            "equity": total_equity or session_data.get("balance_start") or 0,
            "accounts": accounts_with_balance
        },
        "price": price_data,
        "futures": futures_data,
        "sentiment": sentiment_data,
        "analysis": analysis_data,
        "positions": all_positions
    }


@router.get("/session")
async def get_session():
    """Info session (compatibilite G12)."""
    return get_session_info()


@router.get("/session/performance")
async def get_session_performance():
    """Performance de la session (compatibilite G12)."""
    all_stats = get_all_stats()
    session = get_session_info()

    total_trades = sum(s.get("total_trades", 0) for s in all_stats.values())
    total_profit = sum(s.get("total_profit", 0) for s in all_stats.values())

    return {
        "session_id": session.get("session", {}).get("id"),
        "total_trades": total_trades,
        "total_profit": round(total_profit, 2),
        "by_agent": all_stats
    }


@router.get("/session/start")
@router.post("/session/start")
async def api_session_start():
    """Demarrer session (compatibilite G12)."""
    return start_session()


@router.get("/session/end")
@router.post("/session/end")
async def api_session_end():
    """Terminer session (compatibilite G12)."""
    return end_session()


@router.post("/session/sync")
async def api_session_sync():
    """Sync session avec MT5 (compatibilite G12)."""
    results = {}
    for agent_id in ["fibo1", "fibo2", "fibo3"]:
        try:
            connect_result = connect_mt5(agent_id)
            if connect_result["success"]:
                results[agent_id] = {
                    "positions": sync_positions(agent_id),
                    "closed": sync_closed_trades(agent_id)
                }
                disconnect_mt5()
        except Exception as e:
            results[agent_id] = {"error": str(e)}

    return {"success": True, "results": results}


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
    """Arreter le trading (compatibilite G12)."""
    from core import get_trading_loop

    # Arreter la trading loop
    loop = get_trading_loop()
    loop.stop()

    # Terminer la session
    result = end_session()
    return {"success": result["success"], "message": result.get("message", "")}


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
    """Toutes les configs (compatibilite G12)."""
    try:
        with open(CONFIG_PATH / "agents.json", "r") as f:
            agents = json.load(f)
        return {"agents": agents}
    except:
        return {"agents": {}}


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
    """Mettre a jour config agent (compatibilite G12)."""
    try:
        with open(CONFIG_PATH / "agents.json", "r") as f:
            configs = json.load(f)

        if agent_id in configs:
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
    if agent:
        result = get_local_closed_trades(agent, limit=limit)
        return result.get("trades", [])

    # Tous les agents
    all_trades = []
    for agent_id in ["fibo1", "fibo2", "fibo3"]:
        result = get_local_closed_trades(agent_id, limit=limit)
        all_trades.extend(result.get("trades", []))

    # Trier par temps
    all_trades.sort(key=lambda x: x.get("time", 0), reverse=True)
    return all_trades[:limit]


@router.post("/positions/validate")
async def validate_positions():
    """Valider positions (compatibilite G12)."""
    from actions.sync import validate_positions

    results = {}
    for agent_id in ["fibo1", "fibo2", "fibo3"]:
        try:
            connect_result = connect_mt5(agent_id)
            if connect_result["success"]:
                results[agent_id] = validate_positions(agent_id)
                disconnect_mt5()
        except Exception as e:
            results[agent_id] = {"error": str(e)}

    return results


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
async def manage_keys(action: str = None, key_data: Dict[str, Any] = None):
    """Gerer les cles API (compatibilite G12)."""
    try:
        with open(CONFIG_PATH / "api_keys.json", "r") as f:
            data = json.load(f)

        keys = data.get("keys", [])

        if action == "add" and key_data:
            keys.append(key_data)
        elif action == "update" and key_data:
            for i, k in enumerate(keys):
                if k.get("id") == key_data.get("id"):
                    keys[i] = key_data
                    break
        elif action == "delete" and key_data:
            keys = [k for k in keys if k.get("id") != key_data.get("id")]

        with open(CONFIG_PATH / "api_keys.json", "w") as f:
            json.dump({"keys": keys}, f, indent=4)

        return {"success": True}
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
    """Analyse du Strategist (compatibilite G12)."""
    strategist = get_strategist()
    return strategist.get_all_agents_analysis()


@router.post("/strategist/execute")
async def strategist_execute():
    """Executer suggestions Strategist (compatibilite G12)."""
    from strategy import get_ia_adjust

    strategist = get_strategist()
    ia_adjust = get_ia_adjust()

    results = {}
    for agent_id in ["fibo1", "fibo2", "fibo3"]:
        analysis = strategist.analyze(agent_id)
        suggestions = analysis.get("suggestions", [])

        if suggestions:
            result = ia_adjust.auto_adjust(agent_id, suggestions)
            results[agent_id] = result

    return {"success": True, "results": results}


@router.get("/strategist/logs")
async def get_strategist_logs(limit: int = 50):
    """Logs du Strategist (compatibilite G12)."""
    from strategy import get_ia_adjust
    ia_adjust = get_ia_adjust()
    return ia_adjust.get_recent_adjustments(limit=limit)


# ===================== CONFIG SPREAD/RISK =====================

@router.get("/config/spread")
async def get_spread_config():
    """Config spread (compatibilite G12)."""
    # G13 n'utilise pas de config spread separee
    return {"tp_pct": 1.0, "sl_pct": 0.5}


@router.post("/config/spread")
async def update_spread_config(config: Dict[str, Any]):
    """Update spread config (compatibilite G12)."""
    return {"success": True}


@router.post("/config/risk")
async def update_risk_config(config: Dict[str, Any]):
    """Update risk config (compatibilite G12)."""
    return {"success": True}


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
