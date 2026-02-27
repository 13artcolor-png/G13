"""
G13 Trading Loop
================
RESPONSABILITE: Boucle principale de trading.

Cette boucle:
1. Verifie si la session est active
2. Pour chaque agent actif:
   - Sync les positions avec MT5
   - Gere les positions ouvertes (trailing/BE)
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
from actions.mt5 import connect_mt5, disconnect_mt5, read_positions, open_trade, close_trade, get_market_data, modify_trade_sl_tp
from actions.sync import sync_positions, sync_closed_trades
from actions.session import get_session_info, is_session_active
from actions.stats import calculate_stats
from strategy import get_strategist, get_ia_adjust
from agents import create_agent

DATABASE_PATH = Path(__file__).parent.parent / "database"
CONFIG_PATH = DATABASE_PATH / "config"

# ===== CONFIG TPSL PAR DEFAUT =====
DEFAULT_TPSL = {
    "tp_pct": 0.3,
    "sl_pct": 0.5,
    "trailing_start_pct": 0.2,
    "trailing_distance_pct": 0.1,
    "break_even_pct": 0.15,
    "max_spread_points": 50
}


class TradingLoop:
    """
    Boucle principale de trading.

    PARAMETRES MODIFIABLES:
    - LOOP_INTERVAL: Intervalle entre chaque iteration (secondes)
    - SYNC_INTERVAL: Intervalle de synchronisation MT5 (secondes)
    - STATS_INTERVAL: Intervalle de calcul des stats (secondes)
    - MANAGE_INTERVAL: Intervalle de gestion positions (secondes)
    """

    # ===== PARAMETRES MODIFIABLES =====
    LOOP_INTERVAL = 10        # Intervalle principal (secondes)
    SYNC_INTERVAL = 30        # Sync MT5 toutes les 30s
    STATS_INTERVAL = 60       # Stats toutes les 60s
    MANAGE_INTERVAL = 5       # Gestion positions toutes les 5s
    # ==================================

    def __init__(self):
        self.is_running = False
        self._thread = None
        self._last_sync = 0
        self._last_stats = 0
        self._last_manage = 0
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

                # Gerer les positions ouvertes (trailing/BE) - haute frequence
                if current_time - self._last_manage >= self.MANAGE_INTERVAL:
                    self._manage_all_positions()
                    self._last_manage = current_time

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

    def _get_tpsl_config(self, agent_config: Dict) -> Dict:
        """Recupere la config TPSL d'un agent (avec fallback sur defaut)."""
        tpsl = agent_config.get("tpsl_config", {})
        return {
            "tp_pct": tpsl.get("tp_pct", DEFAULT_TPSL["tp_pct"]),
            "sl_pct": tpsl.get("sl_pct", DEFAULT_TPSL["sl_pct"]),
            "trailing_start_pct": tpsl.get("trailing_start_pct", DEFAULT_TPSL["trailing_start_pct"]),
            "trailing_distance_pct": tpsl.get("trailing_distance_pct", DEFAULT_TPSL["trailing_distance_pct"]),
            "break_even_pct": tpsl.get("break_even_pct", DEFAULT_TPSL["break_even_pct"]),
            "max_spread_points": tpsl.get("max_spread_points", DEFAULT_TPSL["max_spread_points"]),
        }

    # ===== GESTION DES POSITIONS (TRAILING / BREAK-EVEN) =====

    def _manage_all_positions(self):
        """Gere les positions ouvertes de tous les agents (trailing stop + break-even)."""
        configs = self._load_agents_config()

        for agent_id, config in configs.items():
            if not config.get("enabled", False):
                continue

            try:
                self._manage_agent_positions(agent_id, config)
            except Exception as e:
                print(f"[TradingLoop] Erreur gestion positions {agent_id}: {e}")

    def _manage_agent_positions(self, agent_id: str, config: Dict):
        """Gere les positions d'un agent: trailing stop + break-even."""
        tpsl = self._get_tpsl_config(config)

        try:
            result = connect_mt5(agent_id)
            if not result["success"]:
                return

            # Lire les positions ouvertes
            pos_result = read_positions(agent_id)
            if not pos_result.get("success") or not pos_result.get("positions"):
                disconnect_mt5()
                return

            # Filtrer par agent (comment contient G13_agentid)
            agent_positions = [
                p for p in pos_result["positions"]
                if f"G13_{agent_id}" in p.get("comment", "")
            ]

            for pos in agent_positions:
                self._manage_single_position(agent_id, pos, tpsl)

            disconnect_mt5()

        except Exception as e:
            print(f"[TradingLoop] Erreur manage positions {agent_id}: {e}")
            try:
                disconnect_mt5()
            except:
                pass

    def _manage_single_position(self, agent_id: str, pos: Dict, tpsl: Dict):
        """
        Gere une position individuelle:
        1. Break-even: Si profit >= break_even_pct, deplace SL au prix d'entree
        2. Trailing stop: Si profit >= trailing_start_pct, suit le prix avec trailing_distance_pct
        """
        ticket = pos.get("ticket")
        pos_type = pos.get("type", "")
        price_open = pos.get("price_open", 0)
        price_current = pos.get("price_current", 0)
        current_sl = pos.get("sl", 0)
        current_tp = pos.get("tp", 0)
        symbol = pos.get("symbol", "BTCUSD")

        if not price_open or not price_current:
            return

        # Calculer le gain en %
        if pos_type == "BUY":
            gain_pct = (price_current - price_open) / price_open * 100
            is_buy = True
        elif pos_type == "SELL":
            gain_pct = (price_open - price_current) / price_open * 100
            is_buy = False
        else:
            return

        # Seuils
        be_pct = tpsl["break_even_pct"]
        trail_start_pct = tpsl["trailing_start_pct"]
        trail_dist_pct = tpsl["trailing_distance_pct"]

        new_sl = None

        # === TRAILING STOP (priorite haute) ===
        if gain_pct >= trail_start_pct:
            trail_distance = price_open * (trail_dist_pct / 100)

            if is_buy:
                # BUY: trailing SL = prix actuel - distance
                trailing_sl = price_current - trail_distance
                # Ne deplacer que vers le haut
                if trailing_sl > current_sl:
                    new_sl = trailing_sl
                    print(f"[Trailing] #{ticket} {agent_id} BUY gain={gain_pct:.3f}% -> SL {current_sl:.2f} => {trailing_sl:.2f}")
            else:
                # SELL: trailing SL = prix actuel + distance
                trailing_sl = price_current + trail_distance
                # Ne deplacer que vers le bas
                if trailing_sl < current_sl or current_sl == 0:
                    new_sl = trailing_sl
                    print(f"[Trailing] #{ticket} {agent_id} SELL gain={gain_pct:.3f}% -> SL {current_sl:.2f} => {trailing_sl:.2f}")

        # === BREAK-EVEN (si trailing pas encore actif) ===
        elif gain_pct >= be_pct:
            if is_buy:
                # BUY: SL au prix d'entree (+ petit buffer)
                be_sl = price_open + 1.0  # +1 point de buffer
                if current_sl < be_sl:
                    new_sl = be_sl
                    print(f"[BreakEven] #{ticket} {agent_id} BUY gain={gain_pct:.3f}% -> SL {current_sl:.2f} => {be_sl:.2f} (BE)")
            else:
                # SELL: SL au prix d'entree (- petit buffer)
                be_sl = price_open - 1.0
                if current_sl > be_sl or current_sl == 0:
                    new_sl = be_sl
                    print(f"[BreakEven] #{ticket} {agent_id} SELL gain={gain_pct:.3f}% -> SL {current_sl:.2f} => {be_sl:.2f} (BE)")

        # Appliquer la modification
        if new_sl is not None:
            result = modify_trade_sl_tp(ticket, new_sl=new_sl, symbol=symbol)
            if result.get("success") and result.get("changed"):
                print(f"[Position] #{ticket} {agent_id} SL modifie: {result['old_sl']:.2f} => {result['new_sl']:.2f}")
            elif not result.get("success"):
                print(f"[Position] #{ticket} {agent_id} ERREUR modification: {result['message']}")

    # ===== SYNC & STATS =====

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
