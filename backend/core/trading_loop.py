"""
G13 Trading Loop
================
RESPONSABILITE: Boucle principale de trading.

Cette boucle:
1. Verifie si la session est active
2. Pour chaque agent actif:
   - Sync les positions avec MT5
   - Analyse le marche
   - Execute les decisions de trading
3. Met a jour les stats

Usage:
    from core.trading_loop import TradingLoop
    loop = TradingLoop()
    loop.start()
"""

import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional
import threading
import time

# Imports des actions
from actions.mt5 import connect_mt5, disconnect_mt5, read_positions, open_trade, close_trade, get_market_data
from actions.sync import sync_positions, sync_closed_trades
from actions.session import get_session_info, is_session_active
from actions.stats import calculate_stats
from strategy import get_strategist, get_ia_adjust
from agents import create_agent

DATABASE_PATH = Path(__file__).parent.parent / "database"
CONFIG_PATH = DATABASE_PATH / "config"


class TradingLoop:
    """
    Boucle principale de trading.

    PARAMETRES MODIFIABLES:
    - LOOP_INTERVAL: Intervalle entre chaque iteration (secondes)
    - SYNC_INTERVAL: Intervalle de synchronisation MT5 (secondes)
    - STATS_INTERVAL: Intervalle de calcul des stats (secondes)
    """

    # ===== PARAMETRES MODIFIABLES =====
    LOOP_INTERVAL = 10        # Intervalle principal (secondes)
    SYNC_INTERVAL = 30        # Sync MT5 toutes les 30s
    STATS_INTERVAL = 60       # Stats toutes les 60s
    # ==================================

    def __init__(self):
        self.is_running = False
        self._thread = None
        self._last_sync = 0
        self._last_stats = 0
        self.agents = {}
        self.market_data = {}

    def start(self):
        """Demarre la boucle de trading."""
        if self.is_running:
            return {"success": False, "message": "Trading loop deja active"}

        self.is_running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        return {"success": True, "message": "Trading loop demarree"}

    def stop(self):
        """Arrete la boucle de trading."""
        self.is_running = False
        return {"success": True, "message": "Trading loop arretee"}

    def _run_loop(self):
        """Boucle principale (executee dans un thread)."""
        print("[TradingLoop] ========== DEMARRAGE ==========")
        iteration = 0

        while self.is_running:
            try:
                iteration += 1

                # Verifier si session active
                if not is_session_active():
                    if iteration % 6 == 0:
                        print("[TradingLoop] En attente session active...")
                    time.sleep(self.LOOP_INTERVAL)
                    continue

                current_time = time.time()

                # Log periodique
                if iteration % 6 == 0:
                    print(f"[TradingLoop] Iteration #{iteration} - Agents: {list(self.agents.keys())}")

                # Sync MT5 periodiquement
                if current_time - self._last_sync >= self.SYNC_INTERVAL:
                    self._sync_all_agents()
                    self._last_sync = current_time

                # Calculer stats periodiquement
                if current_time - self._last_stats >= self.STATS_INTERVAL:
                    self._update_stats()
                    self._last_stats = current_time

                # Executer la logique de trading pour chaque agent
                self._process_agents()

                time.sleep(self.LOOP_INTERVAL)

            except Exception as e:
                print(f"[TradingLoop] ERREUR: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(self.LOOP_INTERVAL)

        print("[TradingLoop] ========== ARRETEE ==========")

    def _load_agents_config(self) -> Dict:
        """Charge la config des agents."""
        try:
            with open(CONFIG_PATH / "agents.json", "r") as f:
                return json.load(f)
        except:
            return {}

    def _sync_all_agents(self):
        """Synchronise tous les agents avec MT5."""
        configs = self._load_agents_config()

        for agent_id, config in configs.items():
            if not config.get("enabled", False):
                continue

            try:
                result = connect_mt5(agent_id)
                if result["success"]:
                    sync_positions(agent_id)
                    sync_closed_trades(agent_id)
                    disconnect_mt5()
                    print(f"[TradingLoop] {agent_id} synced")
            except Exception as e:
                print(f"[TradingLoop] Erreur sync {agent_id}: {e}")

    def _update_stats(self):
        """Met a jour les stats de tous les agents."""
        for agent_id in ["fibo1", "fibo2", "fibo3"]:
            try:
                calculate_stats(agent_id)
            except Exception as e:
                print(f"[TradingLoop] Erreur stats {agent_id}: {e}")

    def _process_agents(self):
        """Execute la logique de trading pour chaque agent."""
        configs = self._load_agents_config()

        for agent_id, config in configs.items():
            if not config.get("enabled", False):
                continue

            try:
                self._process_single_agent(agent_id, config)
            except Exception as e:
                print(f"[TradingLoop] Erreur agent {agent_id}: {e}")

    def _process_single_agent(self, agent_id: str, config: Dict):
        """Traite un seul agent."""
        # Creer ou recuperer l'agent
        if agent_id not in self.agents:
            self.agents[agent_id] = create_agent(agent_id)
            print(f"[TradingLoop] Agent {agent_id} cree")

        agent = self.agents[agent_id]
        if not agent:
            print(f"[TradingLoop] Agent {agent_id} est None!")
            return

        # Recharger la config
        agent.reload_config()

        # Verifier si l'agent peut trader
        if not agent.can_trade():
            return

        # Recuperer les donnees de marche depuis MT5
        market_data = self._get_market_data(agent_id)

        if not market_data.get("success", True):
            print(f"[TradingLoop] {agent_id} - Pas de market data")
            return

        # Log des donnees de marche
        price = market_data.get("price", 0)
        fibo_levels = market_data.get("fibo_levels", {})
        trend = market_data.get("trend", "neutral")
        print(f"[TradingLoop] {agent_id} - Prix: {price}, Trend: {trend}, Fibo: {list(fibo_levels.keys())}")

        # Verifier si on doit ouvrir un trade
        trade_signal = agent.should_open_trade(market_data)

        if trade_signal:
            print(f"[TradingLoop] {agent_id} - SIGNAL: {trade_signal['direction']} @ {trade_signal.get('entry_price')}")
            self._execute_trade(agent_id, trade_signal)
        else:
            # Log pourquoi pas de signal (occasionnel)
            target_level = config.get("fibo_level", "0.236")
            target_price = fibo_levels.get(target_level, 0)
            if target_price and price:
                distance_pct = abs(price - target_price) / target_price * 100
                if distance_pct < 5:  # Log si proche
                    print(f"[TradingLoop] {agent_id} - Proche Fibo {target_level} ({target_price:.2f}), distance: {distance_pct:.2f}%")

    def _get_market_data(self, agent_id: str) -> Dict:
        """
        Recupere les donnees de marche depuis MT5.
        """
        # Charger la config de l'agent pour le symbole
        configs = self._load_agents_config()
        config = configs.get(agent_id, {})
        symbol = config.get("symbol", "BTCUSD")
        timeframe = config.get("timeframe", "M5")

        try:
            # Connexion MT5 pour recuperer les donnees
            result = connect_mt5(agent_id)
            if not result["success"]:
                print(f"[TradingLoop] Connexion MT5 echouee pour market data: {agent_id}")
                return {"success": False, "symbol": symbol}

            # Recuperer les donnees de marche
            market_data = get_market_data(symbol, timeframe)
            disconnect_mt5()

            return market_data

        except Exception as e:
            print(f"[TradingLoop] Erreur market data {agent_id}: {e}")
            return {"success": False, "symbol": symbol, "error": str(e)}

    def _execute_trade(self, agent_id: str, signal: Dict):
        """Execute un trade."""
        try:
            result = connect_mt5(agent_id)
            if not result["success"]:
                print(f"[TradingLoop] Connexion MT5 echouee pour {agent_id}")
                return

            # Charger la config pour la taille de position
            configs = self._load_agents_config()
            config = configs.get(agent_id, {})
            volume = config.get("position_size_pct", 0.01)

            # Ouvrir le trade
            trade_result = open_trade(
                agent_id=agent_id,
                symbol=signal.get("symbol", "BTCUSD"),
                direction=signal["direction"],
                volume=volume,
                sl=signal.get("sl"),
                tp=signal.get("tp"),
                comment=f"G13_{agent_id}"
            )

            if trade_result["success"]:
                print(f"[TradingLoop] Trade ouvert: {agent_id} {signal['direction']}")
                # Marquer le trade comme execute
                if agent_id in self.agents:
                    self.agents[agent_id].mark_trade_executed()
                # Sync apres trade
                sync_positions(agent_id)
            else:
                print(f"[TradingLoop] Echec trade: {trade_result['message']}")

            disconnect_mt5()

        except Exception as e:
            print(f"[TradingLoop] Erreur execution trade: {e}")

    def get_status(self) -> Dict:
        """Retourne le status de la boucle."""
        return {
            "is_running": self.is_running,
            "agents_loaded": list(self.agents.keys()),
            "last_sync": self._last_sync,
            "last_stats": self._last_stats
        }


# Singleton
_trading_loop = None

def get_trading_loop() -> TradingLoop:
    """Retourne l'instance TradingLoop singleton."""
    global _trading_loop
    if _trading_loop is None:
        _trading_loop = TradingLoop()
    return _trading_loop
