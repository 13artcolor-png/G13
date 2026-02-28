"""
G13 Trading Loop
================
RESPONSABILITE: Boucle principale de trading.

ARCHITECTURE:
- UN SEUL passage par agent par iteration
- UNE connexion MT5 pour TOUTES les operations d'un agent
- Disconnect AVANT l'appel IA (libere MT5 pour l'agent suivant)
- Reconnect uniquement si trade a executer
- Traitement SEQUENTIEL: fibo1 termine completement avant fibo2, etc.

Usage:
    from core.trading_loop import TradingLoop
    loop = TradingLoop()
    loop.start()
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional
import threading
import time

# Imports des actions
from actions.mt5 import connect_mt5, disconnect_mt5, read_positions, open_trade, close_trade, get_market_data, modify_trade_sl_tp, get_ohlc
from actions.mt5.market_data import calculate_momentum, calculate_volatility
from actions.sync import sync_positions, sync_closed_trades
from actions.session import get_session_info, is_session_active
from actions.session.session_tickets import save_ticket
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

# ===== CONFIG RISQUE GLOBALE PAR DEFAUT =====
DEFAULT_RISK = {
    "max_drawdown_pct": 10,
    "max_daily_loss_pct": 5,
    "emergency_close_pct": 15,
    "winner_never_loser": True
}


class TradingLoop:
    """
    Boucle principale de trading.

    CYCLE PAR AGENT (sequentiel):
    1. Connect MT5
    2. Sync positions + closed trades
    3. Manage positions (trailing/BE)
    4. Get market data
    5. Disconnect MT5
    6. Appel IA (pas besoin de MT5)
    7. Si signal: Connect MT5 -> Execute trade -> Disconnect
    """

    # ===== PARAMETRES MODIFIABLES =====
    LOOP_INTERVAL = 10        # Intervalle principal (secondes)
    STATS_INTERVAL = 60       # Stats toutes les 60s
    STRATEGIST_INTERVAL = 300 # Strategist toutes les 5 minutes
    # ==================================

    def __init__(self):
        self.is_running = False
        self._thread = None
        self._last_stats = 0
        self._last_strategist = 0
        self.agents = {}
        # Risque global: balances de reference par agent
        self._start_balances = {}      # {agent_id: balance} - balance au 1er connect de la session
        self._day_start_balances = {}  # {agent_id: balance} - balance au debut de la journee
        self._current_day = None       # date du jour pour detecter changement de journee
        self._risk_blocked = {}        # {agent_id: "raison"} - agents bloques par le risque

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

                # Log periodique
                if iteration % 6 == 0:
                    print(f"[TradingLoop] Iteration #{iteration} - Agents: {list(self.agents.keys())}")

                # Traiter chaque agent sequentiellement (UN par UN)
                self._process_all_agents()

                # Stats periodiques (pas besoin de MT5)
                current_time = time.time()
                if current_time - self._last_stats >= self.STATS_INTERVAL:
                    self._update_stats()
                    self._last_stats = current_time

                # Strategist periodique: analyse + auto-ajustement
                if current_time - self._last_strategist >= self.STRATEGIST_INTERVAL:
                    self._run_strategist()
                    self._last_strategist = current_time

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
            "trailing_enabled": tpsl.get("trailing_enabled", True),
            "break_even_pct": tpsl.get("break_even_pct", DEFAULT_TPSL["break_even_pct"]),
            "break_even_enabled": tpsl.get("break_even_enabled", True),
            "max_spread_points": tpsl.get("max_spread_points", DEFAULT_TPSL["max_spread_points"]),
        }

    # ===== RISQUE GLOBAL =====

    def _load_risk_config(self) -> Dict:
        """Charge la config risque globale depuis risk_config.json."""
        try:
            risk_file = CONFIG_PATH / "risk_config.json"
            if risk_file.exists():
                with open(risk_file, "r") as f:
                    return json.load(f)
        except:
            pass
        return DEFAULT_RISK.copy()

    def _check_global_risk(self, agent_id: str, account_info: Dict) -> Dict:
        """
        Verifie les limites de risque globales pour un agent.
        Utilise l'equity du compte MT5 vs balance de reference.

        Returns:
            dict: {"can_trade": bool, "emergency_close": bool, "reason": str}
        """
        risk = self._load_risk_config()
        equity = account_info.get("equity", 0)
        balance = account_info.get("balance", 0)
        today = datetime.now().date()

        # Stocker la balance de reference au 1er connect
        if agent_id not in self._start_balances and balance > 0:
            self._start_balances[agent_id] = balance
            print(f"[Risque] {agent_id} - Balance de reference session: {balance:.2f}")

        # Detecter changement de jour -> reset balance journaliere
        if self._current_day != today:
            self._current_day = today
            self._day_start_balances = {}
            self._risk_blocked = {}
            print(f"[Risque] Nouveau jour detecte ({today}), reset des compteurs journaliers")

        if agent_id not in self._day_start_balances and balance > 0:
            self._day_start_balances[agent_id] = balance
            print(f"[Risque] {agent_id} - Balance debut journee: {balance:.2f}")

        start_balance = self._start_balances.get(agent_id, balance)
        day_balance = self._day_start_balances.get(agent_id, balance)

        if start_balance <= 0 or equity <= 0:
            return {"can_trade": True, "emergency_close": False, "reason": ""}

        # === URGENCE: fermeture immediate si perte critique ===
        emergency_pct = risk.get("emergency_close_pct", 15)
        drawdown_from_start = (start_balance - equity) / start_balance * 100
        if drawdown_from_start >= emergency_pct:
            reason = f"URGENCE: drawdown {drawdown_from_start:.1f}% >= seuil {emergency_pct}% (equity: {equity:.2f}, ref: {start_balance:.2f})"
            print(f"[Risque] {agent_id} - {reason}")
            return {"can_trade": False, "emergency_close": True, "reason": reason}

        # === MAX DRAWDOWN: bloquer nouveaux trades ===
        max_dd = risk.get("max_drawdown_pct", 10)
        if drawdown_from_start >= max_dd:
            reason = f"DRAWDOWN: {drawdown_from_start:.1f}% >= max {max_dd}% (equity: {equity:.2f}, ref: {start_balance:.2f})"
            if agent_id not in self._risk_blocked:
                print(f"[Risque] {agent_id} - {reason}")
                self._risk_blocked[agent_id] = reason
            return {"can_trade": False, "emergency_close": False, "reason": reason}

        # === PERTE JOUR MAX: bloquer nouveaux trades pour la journee ===
        max_daily = risk.get("max_daily_loss_pct", 5)
        daily_loss = (day_balance - equity) / day_balance * 100
        if daily_loss >= max_daily:
            reason = f"PERTE JOUR: {daily_loss:.1f}% >= max {max_daily}% (equity: {equity:.2f}, debut jour: {day_balance:.2f})"
            if agent_id not in self._risk_blocked:
                print(f"[Risque] {agent_id} - {reason}")
                self._risk_blocked[agent_id] = reason
            return {"can_trade": False, "emergency_close": False, "reason": reason}

        # Debloquer si les conditions sont redevenues OK
        if agent_id in self._risk_blocked:
            print(f"[Risque] {agent_id} - Conditions OK, debloque (DD: {drawdown_from_start:.1f}%, Jour: {daily_loss:.1f}%)")
            del self._risk_blocked[agent_id]

        return {"can_trade": True, "emergency_close": False, "reason": ""}

    def _emergency_close_all(self, agent_id: str):
        """
        Fermeture d'URGENCE de toutes les positions de cet agent.
        PREREQUIS: MT5 deja connecte.
        """
        print(f"[Risque] !!!!! FERMETURE D'URGENCE {agent_id} !!!!!")
        pos_result = read_positions(agent_id)
        if not pos_result.get("success") or not pos_result.get("positions"):
            print(f"[Risque] {agent_id} - Aucune position a fermer")
            return

        agent_positions = [
            p for p in pos_result["positions"]
            if f"G13_{agent_id}" in p.get("comment", "")
        ]

        for pos in agent_positions:
            ticket = pos.get("ticket")
            result = close_trade(agent_id, ticket)
            if result.get("success"):
                print(f"[Risque] {agent_id} - Position #{ticket} fermee d'urgence (P&L: {result.get('profit', 0):.2f})")
            else:
                print(f"[Risque] {agent_id} - ECHEC fermeture #{ticket}: {result.get('message')}")

    def _check_killzone(self, agent_id: str, config: Dict) -> bool:
        """
        Verifie si l'heure actuelle est dans la killzone de l'agent.
        Si killzone desactivee, retourne True (peut trader).
        Les heures sont en UTC.

        Returns:
            bool: True si peut trader, False si hors killzone
        """
        kz_enabled = config.get("killzone_enabled", False)
        # Accepter string "true"/"false" ou bool
        if isinstance(kz_enabled, str):
            kz_enabled = kz_enabled.lower() == "true"

        if not kz_enabled:
            return True  # Killzone desactivee = peut trader tout le temps

        kz_start = config.get("killzone_start", "08:00")
        kz_end = config.get("killzone_end", "22:00")

        try:
            from datetime import timezone
            now_utc = datetime.now(timezone.utc)
            current_minutes = now_utc.hour * 60 + now_utc.minute

            start_parts = str(kz_start).split(":")
            start_minutes = int(start_parts[0]) * 60 + int(start_parts[1])

            end_parts = str(kz_end).split(":")
            end_minutes = int(end_parts[0]) * 60 + int(end_parts[1])

            # Gerer le cas ou la killzone traverse minuit (ex: 22:00 - 06:00)
            if start_minutes <= end_minutes:
                in_killzone = start_minutes <= current_minutes < end_minutes
            else:
                in_killzone = current_minutes >= start_minutes or current_minutes < end_minutes

            if not in_killzone:
                print(f"[Killzone] {agent_id} HORS killzone ({kz_start}-{kz_end} UTC, actuel: {now_utc.strftime('%H:%M')} UTC)")
                return False

            return True

        except Exception as e:
            print(f"[Killzone] {agent_id} erreur parsing: {e}")
            return True  # En cas d'erreur, autoriser le trading

    # ===== CYCLE PRINCIPAL =====

    def _process_all_agents(self):
        """
        Traite tous les agents SEQUENTIELLEMENT.
        fibo1 termine completement (connect->sync->manage->data->disconnect->IA->trade)
        AVANT que fibo2 commence. Pas de conflit MT5 possible.
        """
        configs = self._load_agents_config()

        for agent_id, config in configs.items():
            if not config.get("enabled", False):
                continue

            try:
                self._full_agent_cycle(agent_id, config)
            except Exception as e:
                print(f"[TradingLoop] Erreur agent {agent_id}: {e}")
                # Securite: toujours disconnect en cas d'erreur
                try:
                    disconnect_mt5()
                except:
                    pass

    def _full_agent_cycle(self, agent_id: str, config: Dict):
        """
        Cycle complet pour UN agent. Tout est sequentiel.

        PHASE 1 (MT5 connecte):
          - Sync positions + closed trades
          - Manage positions (trailing/BE)
          - Check can_trade
          - Get market data
          - Disconnect MT5

        PHASE 2 (MT5 libre):
          - Enrichir donnees (sentiment, futures)
          - Appel IA via Requesty

        PHASE 3 (MT5 reconnect si besoin):
          - Execute trade si signal IA
          - Disconnect MT5
        """
        # Creer l'agent si necessaire
        if agent_id not in self.agents:
            self.agents[agent_id] = create_agent(agent_id)
            print(f"[TradingLoop] Agent {agent_id} cree")

        agent = self.agents[agent_id]
        if not agent:
            return

        agent.reload_config()

        # ===== PHASE 1: TOUT CE QUI NECESSITE MT5 =====
        result = connect_mt5(agent_id)
        if not result["success"]:
            print(f"[TradingLoop] {agent_id} connexion MT5 echouee")
            return

        market_data = None
        can_trade = False
        risk_allows_trading = True

        try:
            # Controle risque global (drawdown, perte jour, urgence)
            account_info = result.get("account_info", {})
            if account_info:
                risk_check = self._check_global_risk(agent_id, account_info)

                if risk_check["emergency_close"]:
                    # URGENCE: fermer toutes les positions immediatement
                    self._emergency_close_all(agent_id)
                    sync_positions(agent_id)
                    sync_closed_trades(agent_id)
                    disconnect_mt5()
                    return

                if not risk_check["can_trade"]:
                    risk_allows_trading = False

            # Sync positions + verification tickets fermes (TICKET-BASED)
            sync_positions(agent_id)
            sync_closed_trades(agent_id)

            # Gerer positions ouvertes (trailing/BE + winner_never_loser) - MT5 deja connecte
            tpsl = self._get_tpsl_config(config)
            risk_config = self._load_risk_config()
            self._manage_positions_connected(agent_id, tpsl, risk_config)

            # Verifier si l'agent peut trader (lit fichier JSON, pas MT5)
            if risk_allows_trading:
                can_trade = agent.can_trade()
            else:
                can_trade = False

            # Check Killzone AVANT market data et IA (economiser les ressources)
            if can_trade:
                can_trade = self._check_killzone(agent_id, config)

            if can_trade:
                # Recuperer market data - MT5 deja connecte
                symbol = config.get("symbol", "BTCUSD")
                timeframe = config.get("timeframe", "M5")
                market_data = self._get_market_data_connected(symbol, timeframe)

        except Exception as e:
            print(f"[TradingLoop] {agent_id} erreur phase MT5: {e}")

        # TOUJOURS disconnect apres phase 1
        disconnect_mt5()

        # ===== PHASE 2: DECISION IA (MT5 libre) =====
        if not can_trade:
            return

        if not market_data or not market_data.get("success"):
            print(f"[TradingLoop] {agent_id} - Pas de market data")
            return

        # Log
        price = market_data.get("price", 0)
        fibo_levels = market_data.get("fibo_levels", {})
        trend = market_data.get("trend", "neutral")
        print(f"[TradingLoop] {agent_id} - Prix: {price}, Trend: {trend}, Fibo: {list(fibo_levels.keys())}")

        # Enrichir avec donnees externes (pas besoin MT5)
        self._enrich_market_data(market_data)

        # Decision IA (appel API - peut prendre 2-5 secondes)
        trade_signal = agent.should_open_trade(market_data)

        if trade_signal:
            print(f"[TradingLoop] {agent_id} - SIGNAL: {trade_signal['direction']} @ {trade_signal.get('entry_price')}")
            # ===== PHASE 3: EXECUTION (reconnect MT5) =====
            self._execute_trade(agent_id, trade_signal, config)
        else:
            # Log distance Fibo si proche
            target_level = config.get("fibo_level", "0.236")
            target_price = fibo_levels.get(target_level, 0)
            if target_price and price:
                distance_pct = abs(price - target_price) / target_price * 100
                if distance_pct < 5:
                    print(f"[TradingLoop] {agent_id} - Proche Fibo {target_level} ({target_price:.2f}), distance: {distance_pct:.2f}%")

    # ===== OPERATIONS MT5 (MT5 deja connecte) =====

    def _manage_positions_connected(self, agent_id: str, tpsl: Dict, risk_config: Dict = None):
        """
        Gere trailing stop + break-even + winner_never_loser.
        PREREQUIS: MT5 deja connecte.
        """
        pos_result = read_positions(agent_id)
        if not pos_result.get("success") or not pos_result.get("positions"):
            return

        agent_positions = [
            p for p in pos_result["positions"]
            if f"G13_{agent_id}" in p.get("comment", "")
        ]

        winner_never_loser = False
        if risk_config:
            winner_never_loser = risk_config.get("winner_never_loser", False)

        for pos in agent_positions:
            self._manage_single_position(agent_id, pos, tpsl, winner_never_loser)

    def _manage_single_position(self, agent_id: str, pos: Dict, tpsl: Dict, winner_never_loser: bool = False):
        """
        Gere une position: trailing stop + break-even + winner_never_loser.
        PREREQUIS: MT5 deja connecte.
        """
        ticket = pos.get("ticket")
        pos_type = pos.get("type", "")
        price_open = pos.get("price_open", 0)
        price_current = pos.get("price_current", 0)
        current_sl = pos.get("sl", 0)
        symbol = pos.get("symbol", "BTCUSD")

        if not price_open or not price_current:
            return

        if pos_type == "BUY":
            gain_pct = (price_current - price_open) / price_open * 100
            is_buy = True
        elif pos_type == "SELL":
            gain_pct = (price_open - price_current) / price_open * 100
            is_buy = False
        else:
            return

        be_pct = tpsl["break_even_pct"]
        trail_start_pct = tpsl["trailing_start_pct"]
        trail_dist_pct = tpsl["trailing_distance_pct"]
        trailing_on = tpsl.get("trailing_enabled", True)
        be_on = tpsl.get("break_even_enabled", True)

        new_sl = None

        # === TRAILING STOP (priorite haute) ===
        if trailing_on and gain_pct >= trail_start_pct:
            trail_distance = price_open * (trail_dist_pct / 100)

            if is_buy:
                trailing_sl = price_current - trail_distance
                if trailing_sl > current_sl:
                    new_sl = trailing_sl
                    print(f"[Trailing] #{ticket} {agent_id} BUY gain={gain_pct:.3f}% -> SL {current_sl:.2f} => {trailing_sl:.2f}")
            else:
                trailing_sl = price_current + trail_distance
                if trailing_sl < current_sl or current_sl == 0:
                    new_sl = trailing_sl
                    print(f"[Trailing] #{ticket} {agent_id} SELL gain={gain_pct:.3f}% -> SL {current_sl:.2f} => {trailing_sl:.2f}")

        # === BREAK-EVEN ===
        # Buffer = 0.02% du prix d'entree (scale avec l'actif, pas une valeur fixe)
        # Ex: BTCUSD a $64,000 => buffer ~$12.80 au lieu de $1 en dur
        elif be_on and gain_pct >= be_pct:
            be_buffer = price_open * 0.0002  # 0.02% du prix
            if is_buy:
                be_sl = price_open + be_buffer
                if current_sl < be_sl:
                    new_sl = be_sl
                    print(f"[BreakEven] #{ticket} {agent_id} BUY gain={gain_pct:.3f}% -> SL => {be_sl:.2f} (buffer={be_buffer:.2f})")
            else:
                be_sl = price_open - be_buffer
                if current_sl > be_sl or current_sl == 0:
                    new_sl = be_sl
                    print(f"[BreakEven] #{ticket} {agent_id} SELL gain={gain_pct:.3f}% -> SL => {be_sl:.2f} (buffer={be_buffer:.2f})")

        # === WINNER NEVER LOSER ===
        # Des qu'un trade est en profit suffisant (>0.05%), forcer le SL a break-even
        # Seuil 0.05% pour eviter les faux declenchements a cause du spread
        elif winner_never_loser and gain_pct >= 0.05:
            be_buffer = price_open * 0.0002  # 0.02% du prix
            if is_buy:
                wnl_sl = price_open + be_buffer
                if current_sl < wnl_sl:
                    new_sl = wnl_sl
                    print(f"[WinnerNeverLoser] #{ticket} {agent_id} BUY gain={gain_pct:.3f}% -> SL => {wnl_sl:.2f}")
            else:
                wnl_sl = price_open - be_buffer
                if current_sl > wnl_sl or current_sl == 0:
                    new_sl = wnl_sl
                    print(f"[WinnerNeverLoser] #{ticket} {agent_id} SELL gain={gain_pct:.3f}% -> SL => {wnl_sl:.2f}")

        if new_sl is not None:
            result = modify_trade_sl_tp(ticket, new_sl=new_sl, symbol=symbol)
            if result.get("success") and result.get("changed"):
                print(f"[Position] #{ticket} {agent_id} SL modifie: {result['old_sl']:.2f} => {result['new_sl']:.2f}")
            elif not result.get("success"):
                print(f"[Position] #{ticket} {agent_id} ERREUR modification: {result['message']}")

    def _get_market_data_connected(self, symbol: str, timeframe: str) -> Dict:
        """
        Recupere les donnees de marche.
        PREREQUIS: MT5 deja connecte.
        """
        try:
            market_data = get_market_data(symbol, timeframe)

            ohlc_result = get_ohlc(symbol, timeframe, 100)
            if ohlc_result.get("success") and ohlc_result.get("candles"):
                market_data["candles"] = ohlc_result["candles"]

            ohlc_m1 = get_ohlc(symbol, "M1", 20)
            if ohlc_m1.get("success") and ohlc_m1.get("candles"):
                market_data["momentum_1m"] = calculate_momentum(ohlc_m1["candles"], 5)

            ohlc_m5 = get_ohlc(symbol, "M5", 50)
            if ohlc_m5.get("success") and ohlc_m5.get("candles"):
                market_data["momentum_5m"] = calculate_momentum(ohlc_m5["candles"], 5)
                market_data["volatility_pct"] = calculate_volatility(ohlc_m5["candles"], 20)

            market_data["spread_points"] = market_data.get("spread", 0)

            return market_data

        except Exception as e:
            print(f"[TradingLoop] Erreur market data: {e}")
            return {"success": False, "symbol": symbol}

    def _enrich_market_data(self, market_data: Dict):
        """
        Ajoute sentiment + futures. Pas besoin MT5. Ne bloque pas si erreur.
        """
        try:
            from data.sentiment import SentimentData
            fg = SentimentData().get_fear_greed_index()
            if fg:
                market_data["sentiment"] = fg
        except:
            pass

        try:
            from data.binance_data import BinanceData
            binance = BinanceData()
            funding = binance.get_funding_rate()
            ls_ratio = binance.get_long_short_ratio()
            if funding or ls_ratio:
                market_data["futures"] = {
                    "funding_rate": funding.get("funding_rate", "N/A") if funding else "N/A",
                    "long_short_ratio": ls_ratio.get("ratio", "N/A") if ls_ratio else "N/A"
                }
        except:
            pass

    def _execute_trade(self, agent_id: str, signal: Dict, config: Dict):
        """Execute un trade. Gere sa propre connexion MT5."""
        try:
            result = connect_mt5(agent_id)
            if not result["success"]:
                print(f"[TradingLoop] Connexion MT5 echouee pour execution {agent_id}")
                return

            # Arrondir le volume au volume_step du symbole (ex: 0.035 -> 0.03)
            raw_volume = config.get("position_size_pct", 0.01)
            symbol = signal.get("symbol", "BTCUSD")
            import MetaTrader5 as mt5_mod
            sym_info = mt5_mod.symbol_info(symbol)
            if sym_info and sym_info.volume_step > 0:
                step = sym_info.volume_step
                volume = max(sym_info.volume_min, round(int(raw_volume / step) * step, 8))
                if volume != raw_volume:
                    print(f"[TradingLoop] Volume ajuste: {raw_volume} -> {volume} (step={step})")
            else:
                volume = raw_volume

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
                ticket = trade_result.get("ticket")
                print(f"[TradingLoop] Trade ouvert: {agent_id} {signal['direction']} ticket #{ticket}")

                # Enregistrer le ticket dans session_tickets.json
                if ticket:
                    save_ticket(
                        agent_id=agent_id,
                        ticket=ticket,
                        symbol=signal.get("symbol", "BTCUSD"),
                        direction=signal["direction"]
                    )

                if agent_id in self.agents:
                    self.agents[agent_id].mark_trade_executed()
                sync_positions(agent_id)
            else:
                print(f"[TradingLoop] Echec trade: {trade_result['message']}")

            disconnect_mt5()

        except Exception as e:
            print(f"[TradingLoop] Erreur execution trade: {e}")
            try:
                disconnect_mt5()
            except:
                pass

    # ===== STATS =====

    def _update_stats(self):
        """Met a jour les stats (pas besoin de MT5)."""
        for agent_id in ["fibo1", "fibo2", "fibo3"]:
            try:
                calculate_stats(agent_id)
            except Exception as e:
                print(f"[TradingLoop] Erreur stats {agent_id}: {e}")

        # Sauvegarder snapshot performance pour persistence graphiques
        self._save_performance_snapshot()

    def _save_performance_snapshot(self):
        """
        Sauvegarde un point de performance pour chaque agent + master.
        Persiste dans performance_history.json pour restaurer les graphiques apres redemarrage.
        """
        try:
            from actions.stats import get_all_stats
            from actions.sync import get_local_positions

            all_stats = get_all_stats()
            timestamp = datetime.now().isoformat()

            # Calculer les donnees par agent
            master_closed = 0
            master_floating = 0

            history_file = DATABASE_PATH / "performance_history.json"

            # Charger historique existant
            history = {}
            if history_file.exists():
                with open(history_file, "r") as f:
                    history = json.load(f)

            for agent_id in ["fibo1", "fibo2", "fibo3"]:
                if agent_id not in history:
                    history[agent_id] = []

                stats = all_stats.get(agent_id, {})
                closed_pnl = stats.get("total_profit", 0)

                # P&L flottant depuis positions ouvertes
                floating_pnl = 0
                try:
                    pos_result = get_local_positions(agent_id)
                    positions = pos_result.get("positions", [])
                    floating_pnl = sum(p.get("profit", 0) for p in positions)
                except:
                    pass

                master_closed += closed_pnl
                master_floating += floating_pnl

                history[agent_id].append({
                    "timestamp": timestamp,
                    "closed_pnl": round(closed_pnl, 2),
                    "floating_pnl": round(floating_pnl, 2)
                })

            # Master (somme de tous les agents)
            if "master" not in history:
                history["master"] = []

            history["master"].append({
                "timestamp": timestamp,
                "closed_pnl": round(master_closed, 2),
                "floating_pnl": round(master_floating, 2)
            })

            # Limiter a 2000 points par agent (environ 33h a 60s d'intervalle)
            for key in history:
                if len(history[key]) > 2000:
                    history[key] = history[key][-2000:]

            with open(history_file, "w") as f:
                json.dump(history, f)

        except Exception as e:
            print(f"[TradingLoop] Erreur sauvegarde performance: {e}")

    def _run_strategist(self):
        """Analyse performances et applique auto-ajustements (IA si dispo, sinon regles)."""
        try:
            strategist = get_strategist()
            ia_adjust = get_ia_adjust()

            # Charger configs agents pour verifier ia_adjust_enabled
            agents_config = {}
            agents_file = Path(__file__).parent.parent / "database" / "config" / "agents.json"
            if agents_file.exists():
                with open(agents_file, "r") as f:
                    agents_config = json.load(f)

            # Utiliser analyze_with_ai() qui tente l'IA puis fallback regles
            ai_result = strategist.analyze_with_ai()
            source = ai_result.get("source", "rules")
            fmt = ai_result.get("format", "types")
            print(f"[Strategist] Analyse {source.upper()} ({fmt}) lancee")

            if ai_result.get("analysis"):
                print(f"[Strategist] Resume IA: {ai_result['analysis'][:120]}")

            # Collecter les modifications MT5 a appliquer
            all_mt5_mods = {}

            if fmt == "exact_values":
                # === NOUVEAU FORMAT : valeurs exactes de l'IA ===
                for adj in ai_result.get("adjustments", []):
                    agent_id = adj.get("agent_id", "")
                    if agent_id not in ("fibo1", "fibo2", "fibo3"):
                        continue

                    # Afficher stats
                    agents_raw = ai_result.get("agents", {})
                    agent_data = agents_raw.get(agent_id, {})
                    stats = agent_data.get("stats", {})
                    if stats:
                        print(f"[Strategist] {agent_id}: WR:{stats.get('winrate', 0)}%, PF:{stats.get('profit_factor', 0)}")

                    # Verifier ia_adjust_enabled
                    agent_cfg = agents_config.get(agent_id, {})
                    if not agent_cfg.get("ia_adjust_enabled", False):
                        print(f"[Strategist] {agent_id}: auto-ajustement DESACTIVE")
                        continue

                    changes = adj.get("changes", {})
                    reason = adj.get("reason", "")
                    result = ia_adjust.apply_exact_values(agent_id, changes, reason)

                    for a in result.get("adjustments", []):
                        print(f"[Strategist] {agent_id} AJUSTEMENT: {a['field']}: {a['old_value']} -> {a['new_value']}")

                    mt5_mods = result.get("mt5_modifications", [])
                    if mt5_mods:
                        all_mt5_mods[agent_id] = mt5_mods

            else:
                # === ANCIEN FORMAT : types de suggestions (regles fallback) ===
                suggestions_by_agent = ai_result.get("suggestions_by_agent", {})

                # Si source=rules, construire suggestions_by_agent depuis agents
                if source == "rules" and not suggestions_by_agent:
                    agents_raw = ai_result.get("agents", {})
                    for agent_id, data in agents_raw.items():
                        slist = data.get("suggestions", [])
                        if slist:
                            suggestions_by_agent[agent_id] = slist

                for agent_id in ["fibo1", "fibo2", "fibo3"]:
                    suggestions = suggestions_by_agent.get(agent_id, [])
                    if not suggestions:
                        continue

                    agents_raw = ai_result.get("agents", {})
                    agent_data = agents_raw.get(agent_id, {})
                    stats = agent_data.get("stats", {})
                    evaluation = agent_data.get("evaluation", "?")
                    if stats:
                        print(f"[Strategist] {agent_id}: {evaluation} (WR:{stats.get('winrate', 0)}%, PF:{stats.get('profit_factor', 0)})")

                    agent_cfg = agents_config.get(agent_id, {})
                    if not agent_cfg.get("ia_adjust_enabled", False):
                        print(f"[Strategist] {agent_id}: auto-ajustement DESACTIVE, {len(suggestions)} suggestion(s) ignoree(s)")
                        continue

                    result = ia_adjust.auto_adjust(agent_id, suggestions)
                    for adj in result.get("adjustments", []):
                        print(f"[Strategist] {agent_id} AJUSTEMENT: {adj['type']} - {adj['field']}: {adj['old_value']} -> {adj['new_value']}")

                    mt5_mods = result.get("mt5_modifications", [])
                    if mt5_mods:
                        all_mt5_mods[agent_id] = mt5_mods

            # === PHASE MT5 : Modifier les SL/TP des positions ouvertes ===
            if all_mt5_mods:
                self._apply_mt5_modifications(all_mt5_mods)

        except Exception as e:
            print(f"[Strategist] Erreur: {e}")
            import traceback
            traceback.print_exc()

    def _apply_mt5_modifications(self, all_mt5_mods: Dict):
        """
        Modifie les SL/TP des positions ouvertes sur MT5.
        Connecte a MT5 pour chaque agent, modifie les positions, deconnecte.

        Args:
            all_mt5_mods: {agent_id: [{"ticket": int, "symbol": str, "new_sl": float, "new_tp": float, ...}]}
        """
        for agent_id, modifications in all_mt5_mods.items():
            if not modifications:
                continue

            print(f"[Strategist] {agent_id}: {len(modifications)} position(s) a modifier sur MT5")

            try:
                result = connect_mt5(agent_id)
                if not result.get("success"):
                    print(f"[Strategist] {agent_id}: MT5 connexion echouee, positions NON modifiees")
                    continue

                for mod in modifications:
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
                        print(f"[Strategist] {agent_id} #{ticket}: SL {mod.get('old_sl')} -> {mod['new_sl']}, TP {mod.get('old_tp')} -> {mod['new_tp']}")
                    elif not mod_result.get("success"):
                        print(f"[Strategist] {agent_id} #{ticket}: ECHEC modification: {mod_result.get('message', '?')}")

                disconnect_mt5()

            except Exception as e:
                print(f"[Strategist] {agent_id}: Erreur MT5 modification: {e}")
                try:
                    disconnect_mt5()
                except Exception:
                    pass

    def get_status(self) -> Dict:
        """Retourne le status de la boucle."""
        return {
            "is_running": self.is_running,
            "agents_loaded": list(self.agents.keys()),
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
