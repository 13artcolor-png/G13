"""
G13 IA Adjust
=============
RESPONSABILITE: Appliquer automatiquement les ajustements suggeres par le Strategist.

DEUX MODES:
1. apply_exact_values() - Mode IA: valeurs exactes decidees par l'IA (principal)
2. auto_adjust() - Mode regles: pas fixes mecaniques (fallback)

Inclut rate-limiting et modification des positions ouvertes (SL/TP).

Usage:
    from strategy.ia_adjust import IAdjust, get_ia_adjust
    adjuster = get_ia_adjust()
    # Mode IA (valeurs exactes)
    result = adjuster.apply_exact_values("fibo1", {"tp_pct": 0.4, "sl_pct": 0.3}, "Raison IA")
    # Mode regles (fallback)
    result = adjuster.auto_adjust("fibo1", suggestions)
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

DATABASE_PATH = Path(__file__).parent.parent / "database"
CONFIG_PATH = DATABASE_PATH / "config"


class IAdjust:
    """
    Applique automatiquement les ajustements de parametres.

    Mode principal: apply_exact_values() - L'IA decide des valeurs precises.
    Mode fallback: auto_adjust() - Pas fixes mecaniques (regles if/else).
    """

    # ===== BORNES DES PARAMETRES =====
    AUTO_ADJUST_ENABLED = True

    TOLERANCE_MIN = 0.5       # Minimum tolerance (%)
    TOLERANCE_MAX = 5.0       # Maximum tolerance (%)

    COOLDOWN_MIN = 60         # Minimum cooldown (secondes)
    COOLDOWN_MAX = 600        # Maximum cooldown (secondes)

    TP_MIN = 0.1              # Minimum TP (%)
    TP_MAX = 1.0              # Maximum TP (%)

    SL_MIN = 0.2              # Minimum SL (%)
    SL_MAX = 1.0              # Maximum SL (%) - JAMAIS plus que TP_MAX

    POSITION_SIZE_MIN = 0.005   # Minimum position size
    POSITION_SIZE_MAX = 0.05    # Maximum position size

    # ===== GARDE-FOUS DURS =====
    MAX_SL_TP_RATIO = 1.5        # SL ne peut JAMAIS depasser 1.5x le TP
    MAX_CHANGE_PCT = 50           # Changement max = 50% de la valeur actuelle par ajustement
    DIRECTION_LOCK_SECONDS = 14400  # 4 heures avant de pouvoir inverser la direction d'un changement

    # ===== RATE LIMITING =====
    MIN_ADJUSTMENT_INTERVAL = 900   # 15 min minimum entre ajustements par agent
    MAX_ADJUSTMENTS_PER_HOUR = 4    # Max 4 cycles d'ajustement par agent par heure

    # ===== FALLBACK : PAS FIXES (mode regles) =====
    TOLERANCE_STEP = 0.5
    COOLDOWN_STEP = 30
    TP_STEP = 0.05
    SL_STEP = 0.05
    POSITION_SIZE_STEP = 0.005
    MIN_TRADES_BEFORE_ADJUST = 5
    # ==================================

    def __init__(self):
        self._last_adjustment_time = {}  # {agent_id: datetime}

    # ================================================================
    #  MODE PRINCIPAL : VALEURS EXACTES (appele par l'IA)
    # ================================================================

    def apply_exact_values(self, agent_id: str, changes: Dict, reason: str = "") -> Dict:
        """
        Applique des valeurs exactes sur la config d'un agent.
        Valide les bornes min/max. Genere les modifications MT5 si SL/TP change.

        Args:
            agent_id: L'identifiant de l'agent (fibo1, fibo2, fibo3)
            changes: Dict de {param: valeur_exacte}
                     ex: {"tp_pct": 0.4, "sl_pct": 0.3, "fibo_tolerance_pct": 2.5}
            reason: Raison de l'ajustement (pour le log)

        Returns:
            dict: {
                "success": bool,
                "adjustments": List[dict],
                "mt5_modifications": List[dict],
                "message": str
            }
        """
        if not self.AUTO_ADJUST_ENABLED:
            return {
                "success": True, "adjustments": [],
                "mt5_modifications": [], "message": "Auto-adjust desactive"
            }

        # Rate limiting
        if not self._can_adjust(agent_id):
            return {
                "success": True, "adjustments": [],
                "mt5_modifications": [], "message": "Rate limit atteint"
            }

        config = self._load_agent_config(agent_id)
        if not config:
            return {
                "success": False, "adjustments": [],
                "mt5_modifications": [], "message": f"Config non trouvee pour {agent_id}"
            }

        adjustments = []
        tp_changed = False
        sl_changed = False
        new_tp_pct = None
        new_sl_pct = None

        # Mapping des parametres vers leur emplacement dans la config
        PARAM_MAP = {
            "fibo_tolerance_pct": {"path": "top", "min": self.TOLERANCE_MIN, "max": self.TOLERANCE_MAX, "round": 2},
            "cooldown_seconds":   {"path": "top", "min": self.COOLDOWN_MIN, "max": self.COOLDOWN_MAX, "round": 0},
            "position_size_pct":  {"path": "top", "min": self.POSITION_SIZE_MIN, "max": self.POSITION_SIZE_MAX, "round": 4},
            "tp_pct":             {"path": "tpsl", "min": self.TP_MIN, "max": self.TP_MAX, "round": 3},
            "sl_pct":             {"path": "tpsl", "min": self.SL_MIN, "max": self.SL_MAX, "round": 3},
        }

        # Collecter les valeurs demandees (pour appliquer les garde-fous apres)
        requested_changes = {}
        for param, new_value in changes.items():
            if param not in PARAM_MAP:
                print(f"[IA Adjust] {agent_id}: parametre inconnu ignore: {param}")
                continue
            try:
                requested_changes[param] = float(new_value)
            except (ValueError, TypeError):
                print(f"[IA Adjust] {agent_id}: valeur invalide pour {param}: {new_value}")

        # === GARDE-FOU A : Ratio TP/SL obligatoire ===
        # SL ne peut JAMAIS depasser MAX_SL_TP_RATIO x TP
        tpsl_config = config.get("tpsl_config", {})
        final_tp = requested_changes.get("tp_pct", tpsl_config.get("tp_pct", 0.3))
        final_sl = requested_changes.get("sl_pct", tpsl_config.get("sl_pct", 0.5))
        if final_sl > final_tp * self.MAX_SL_TP_RATIO:
            old_sl = final_sl
            final_sl = round(final_tp * self.MAX_SL_TP_RATIO, 3)
            if "sl_pct" in requested_changes:
                requested_changes["sl_pct"] = final_sl
            print(f"[IA Adjust] {agent_id}: GARDE-FOU ratio TP/SL - SL {old_sl} -> {final_sl} (max {self.MAX_SL_TP_RATIO}x TP={final_tp})")

        for param, new_value in requested_changes.items():
            spec = PARAM_MAP[param]

            # Clamp aux bornes
            clamped = max(spec["min"], min(spec["max"], new_value))

            # Arrondir
            if spec["round"] == 0:
                clamped = int(clamped)
            else:
                clamped = round(clamped, spec["round"])

            # Lire la valeur actuelle
            if spec["path"] == "tpsl":
                tpsl = config.get("tpsl_config", {})
                current = tpsl.get(param, 0)
            else:
                current = config.get(param, 0)

            # Skip si pas de changement
            if clamped == current:
                continue

            # === GARDE-FOU B : Amplitude max de changement ===
            # Limite le changement a MAX_CHANGE_PCT % de la valeur actuelle
            if current > 0:
                max_delta = current * self.MAX_CHANGE_PCT / 100
                if abs(clamped - current) > max_delta:
                    old_clamped = clamped
                    if clamped > current:
                        clamped = round(current + max_delta, spec["round"]) if spec["round"] > 0 else int(current + max_delta)
                    else:
                        clamped = round(current - max_delta, spec["round"]) if spec["round"] > 0 else int(current - max_delta)
                    # Re-clamp aux bornes apres ajustement
                    clamped = max(spec["min"], min(spec["max"], clamped))
                    print(f"[IA Adjust] {agent_id}: GARDE-FOU amplitude - {param} {old_clamped} -> {clamped} (max {self.MAX_CHANGE_PCT}% de {current})")

            # === GARDE-FOU C : Verrouillage de direction ===
            # Si un parametre a ete change dans un sens recemment, interdire l'inversion
            direction_blocked = self._is_direction_locked(agent_id, param, current, clamped)
            if direction_blocked:
                print(f"[IA Adjust] {agent_id}: GARDE-FOU direction - {param} {current} -> {clamped} BLOQUE (inversion trop recente)")
                continue

            # Skip si pas de changement apres garde-fous
            if clamped == current:
                continue

            # Appliquer
            if spec["path"] == "tpsl":
                tpsl = config.get("tpsl_config", {})
                tpsl[param] = clamped
                config["tpsl_config"] = tpsl
                field_name = f"tpsl_config.{param}"
            else:
                config[param] = clamped
                field_name = param

            # Tracker les changements TP/SL pour les positions ouvertes
            if param == "tp_pct":
                tp_changed = True
                new_tp_pct = clamped
            elif param == "sl_pct":
                sl_changed = True
                new_sl_pct = clamped

            adjustments.append({
                "type": "EXACT_VALUE",
                "field": field_name,
                "old_value": current,
                "new_value": clamped,
                "reason": reason[:200] if reason else "",
                "timestamp": datetime.now().isoformat()
            })

        # Sauvegarder si des ajustements ont ete faits
        if adjustments:
            self._save_agent_config(agent_id, config)
            self._log_adjustments(agent_id, adjustments)
            self._last_adjustment_time[agent_id] = datetime.now()

        # Generer les modifications MT5 si TP ou SL a change
        mt5_modifications = []
        if tp_changed or sl_changed:
            mt5_modifications = self._build_mt5_modifications(
                agent_id, new_tp_pct, new_sl_pct
            )

        return {
            "success": True,
            "adjustments": adjustments,
            "mt5_modifications": mt5_modifications,
            "message": f"{len(adjustments)} ajustements appliques"
        }

    def _build_mt5_modifications(self, agent_id: str,
                                  new_tp_pct: float = None,
                                  new_sl_pct: float = None) -> List[Dict]:
        """
        Construit la liste des modifications MT5 pour les positions ouvertes.
        Recalcule SL/TP en fonction des nouveaux pourcentages.
        Protection: ne recule jamais un SL deja avance par le trailing stop.
        """
        positions = self._load_open_positions(agent_id)
        if not positions:
            return []

        modifications = []
        for pos in positions:
            mod = self._recalculate_sl_tp(pos, new_tp_pct, new_sl_pct)
            if mod:
                modifications.append(mod)

        return modifications

    def _recalculate_sl_tp(self, position: Dict,
                            new_tp_pct: float = None,
                            new_sl_pct: float = None) -> Optional[Dict]:
        """
        Recalcule SL/TP pour une position ouverte avec les nouveaux pourcentages.
        Meme formule que fibo_agent._calculate_sl_tp_pct().

        Protection trailing: ne recule jamais un SL deja avance par le trailing.
        - BUY: si SL actuel > nouveau SL calcule, on garde l'actuel (meilleur)
        - SELL: si SL actuel < nouveau SL calcule et SL actuel > 0, on garde l'actuel

        Returns:
            dict ou None si aucun changement necessaire
        """
        entry_price = position.get("price_open", 0)
        direction = position.get("type", "")  # "BUY" ou "SELL"
        ticket = position.get("ticket")
        symbol = position.get("symbol", "BTCUSD")
        current_sl = position.get("sl", 0)
        current_tp = position.get("tp", 0)

        if not entry_price or not ticket or not direction:
            return None

        final_sl = current_sl
        final_tp = current_tp
        changed = False

        # Recalculer SL
        if new_sl_pct is not None:
            sl_factor = new_sl_pct / 100
            if direction == "BUY":
                calc_sl = round(entry_price * (1 - sl_factor), 2)
                # Protection trailing : ne pas reculer le SL
                if current_sl <= 0 or calc_sl >= current_sl:
                    final_sl = calc_sl
                    changed = True
                # Sinon garder le SL actuel (trailing l'a deja avance)
            elif direction == "SELL":
                calc_sl = round(entry_price * (1 + sl_factor), 2)
                # Protection trailing : ne pas reculer le SL
                if current_sl <= 0 or calc_sl <= current_sl:
                    final_sl = calc_sl
                    changed = True

        # Recalculer TP
        if new_tp_pct is not None:
            tp_factor = new_tp_pct / 100
            if direction == "BUY":
                final_tp = round(entry_price * (1 + tp_factor), 2)
                changed = True
            elif direction == "SELL":
                final_tp = round(entry_price * (1 - tp_factor), 2)
                changed = True

        if not changed:
            return None

        return {
            "ticket": ticket,
            "symbol": symbol,
            "new_sl": final_sl,
            "new_tp": final_tp,
            "old_sl": current_sl,
            "old_tp": current_tp
        }

    # ================================================================
    #  RATE LIMITING
    # ================================================================

    def _is_direction_locked(self, agent_id: str, param: str, current: float, new_value: float) -> bool:
        """
        Verifie si la direction d'un changement est verrouillee.
        Si un parametre a ete modifie dans un sens recemment (< DIRECTION_LOCK_SECONDS),
        on interdit l'inversion de direction.
        Ex: Si SL a baisse de 0.6 -> 0.3 il y a 2h, on ne peut pas le remonter avant 4h.
        """
        if current == 0:
            return False

        new_direction = "up" if new_value > current else "down"

        # Chercher le dernier ajustement de ce parametre pour cet agent
        recent = self.get_recent_adjustments(50)
        lock_threshold = datetime.now().timestamp() - self.DIRECTION_LOCK_SECONDS

        # Trouver le champ dans les logs (peut etre "tpsl_config.tp_pct" ou "tp_pct")
        field_variants = [param, f"tpsl_config.{param}"]

        for adj in recent:
            if adj.get("agent_id") != agent_id:
                continue
            if adj.get("field") not in field_variants:
                continue

            try:
                ts = datetime.fromisoformat(adj.get("timestamp", "2000-01-01")).timestamp()
            except (ValueError, TypeError):
                continue

            # Trop ancien, pas de verrouillage
            if ts < lock_threshold:
                break

            # Determiner la direction du dernier ajustement
            old = adj.get("old_value", 0)
            new = adj.get("new_value", 0)
            try:
                last_direction = "up" if float(new) > float(old) else "down"
            except (ValueError, TypeError):
                continue

            # Si la direction actuelle est l'inverse de la derniere, bloquer
            if new_direction != last_direction:
                return True

            # Meme direction = ok
            return False

        return False

    def _can_adjust(self, agent_id: str) -> bool:
        """Verifie si l'agent peut etre ajuste (rate limiting)."""
        # Verifier intervalle minimum
        last_time = self._last_adjustment_time.get(agent_id)
        if last_time:
            elapsed = (datetime.now() - last_time).total_seconds()
            if elapsed < self.MIN_ADJUSTMENT_INTERVAL:
                print(f"[IA Adjust] {agent_id}: Rate limit - dernier ajustement il y a {elapsed:.0f}s (min: {self.MIN_ADJUSTMENT_INTERVAL}s)")
                return False

        # Verifier nombre max par heure
        recent = self.get_recent_adjustments(50)
        one_hour_ago = datetime.now().timestamp() - 3600
        count_this_hour = 0
        for adj in recent:
            if adj.get("agent_id") != agent_id:
                continue
            try:
                ts = datetime.fromisoformat(adj.get("timestamp", "2000-01-01")).timestamp()
                if ts > one_hour_ago:
                    count_this_hour += 1
            except (ValueError, TypeError):
                continue

        if count_this_hour >= self.MAX_ADJUSTMENTS_PER_HOUR:
            print(f"[IA Adjust] {agent_id}: Rate limit - {count_this_hour} ajustements cette heure (max: {self.MAX_ADJUSTMENTS_PER_HOUR})")
            return False

        return True

    # ================================================================
    #  MODE FALLBACK : PAS FIXES (regles mecaniques)
    # ================================================================

    def auto_adjust(self, agent_id: str, suggestions: List[Dict] = None) -> Dict:
        """
        Applique des ajustements mecaniques (pas fixes) bases sur les types de suggestions.
        MODE FALLBACK quand l'IA n'est pas disponible.

        Args:
            agent_id: L'identifiant de l'agent
            suggestions: Liste des suggestions du Strategist (type-based)

        Returns:
            dict: {"success": bool, "adjustments": List[dict], "mt5_modifications": list, "message": str}
        """
        if not self.AUTO_ADJUST_ENABLED:
            return {
                "success": True, "adjustments": [],
                "mt5_modifications": [], "message": "Auto-adjust desactive"
            }

        # Rate limiting
        if not self._can_adjust(agent_id):
            return {
                "success": True, "adjustments": [],
                "mt5_modifications": [], "message": "Rate limit atteint"
            }

        config = self._load_agent_config(agent_id)
        if not config:
            return {
                "success": False, "adjustments": [],
                "mt5_modifications": [], "message": f"Config non trouvee pour {agent_id}"
            }

        adjustments = []
        tp_changed = False
        sl_changed = False

        if suggestions:
            for suggestion in suggestions:
                adjustment = self._apply_suggestion(config, suggestion)
                if adjustment:
                    adjustments.append(adjustment)
                    # Tracker les changements TP/SL
                    if "tp_pct" in adjustment.get("field", ""):
                        tp_changed = True
                    if "sl_pct" in adjustment.get("field", ""):
                        sl_changed = True

        if adjustments:
            self._save_agent_config(agent_id, config)
            self._log_adjustments(agent_id, adjustments)
            self._last_adjustment_time[agent_id] = datetime.now()

        # Generer modifications MT5 si TP/SL a change
        mt5_modifications = []
        if tp_changed or sl_changed:
            tpsl = config.get("tpsl_config", {})
            mt5_modifications = self._build_mt5_modifications(
                agent_id,
                new_tp_pct=tpsl.get("tp_pct") if tp_changed else None,
                new_sl_pct=tpsl.get("sl_pct") if sl_changed else None
            )

        return {
            "success": True,
            "adjustments": adjustments,
            "mt5_modifications": mt5_modifications,
            "message": f"{len(adjustments)} ajustements appliques"
        }

    def _apply_suggestion(self, config: Dict, suggestion: Dict) -> Optional[Dict]:
        """Applique une suggestion type-based (fallback regles)."""
        suggestion_type = suggestion.get("type", "")

        if suggestion_type == "REDUCE_TOLERANCE":
            return self._reduce_tolerance(config)
        elif suggestion_type == "INCREASE_TOLERANCE":
            return self._increase_tolerance(config)
        elif suggestion_type == "INCREASE_COOLDOWN":
            return self._increase_cooldown(config)
        elif suggestion_type == "REDUCE_COOLDOWN":
            return self._reduce_cooldown(config)
        elif suggestion_type == "ADJUST_TPSL":
            return self._adjust_tpsl(config)
        elif suggestion_type == "RISK_MANAGEMENT":
            return self._reduce_sl(config)
        elif suggestion_type == "INCREASE_RISK":
            return self._increase_position_size(config)
        return None

    def _reduce_tolerance(self, config: Dict) -> Optional[Dict]:
        """Reduit fibo_tolerance_pct."""
        current = config.get("fibo_tolerance_pct", 2.0)
        new_value = round(max(self.TOLERANCE_MIN, current - self.TOLERANCE_STEP), 2)
        if new_value == current:
            return None
        config["fibo_tolerance_pct"] = new_value
        return {
            "type": "REDUCE_TOLERANCE", "field": "fibo_tolerance_pct",
            "old_value": current, "new_value": new_value,
            "timestamp": datetime.now().isoformat()
        }

    def _increase_tolerance(self, config: Dict) -> Optional[Dict]:
        """Augmente fibo_tolerance_pct."""
        current = config.get("fibo_tolerance_pct", 2.0)
        new_value = round(min(self.TOLERANCE_MAX, current + self.TOLERANCE_STEP), 2)
        if new_value == current:
            return None
        config["fibo_tolerance_pct"] = new_value
        return {
            "type": "INCREASE_TOLERANCE", "field": "fibo_tolerance_pct",
            "old_value": current, "new_value": new_value,
            "timestamp": datetime.now().isoformat()
        }

    def _increase_cooldown(self, config: Dict) -> Optional[Dict]:
        """Augmente cooldown_seconds."""
        current = config.get("cooldown_seconds", 180)
        new_value = min(self.COOLDOWN_MAX, current + self.COOLDOWN_STEP)
        if new_value == current:
            return None
        config["cooldown_seconds"] = new_value
        return {
            "type": "INCREASE_COOLDOWN", "field": "cooldown_seconds",
            "old_value": current, "new_value": new_value,
            "timestamp": datetime.now().isoformat()
        }

    def _reduce_cooldown(self, config: Dict) -> Optional[Dict]:
        """Reduit cooldown_seconds."""
        current = config.get("cooldown_seconds", 180)
        new_value = max(self.COOLDOWN_MIN, current - self.COOLDOWN_STEP)
        if new_value == current:
            return None
        config["cooldown_seconds"] = new_value
        return {
            "type": "REDUCE_COOLDOWN", "field": "cooldown_seconds",
            "old_value": current, "new_value": new_value,
            "timestamp": datetime.now().isoformat()
        }

    def _adjust_tpsl(self, config: Dict) -> Optional[Dict]:
        """Augmente TP (profit factor < 1)."""
        tpsl = config.get("tpsl_config", {})
        current_tp = tpsl.get("tp_pct", 0.3)
        new_tp = round(min(self.TP_MAX, current_tp + self.TP_STEP), 3)
        if new_tp == current_tp:
            return None
        tpsl["tp_pct"] = new_tp
        config["tpsl_config"] = tpsl
        return {
            "type": "ADJUST_TPSL", "field": "tpsl_config.tp_pct",
            "old_value": current_tp, "new_value": new_tp,
            "timestamp": datetime.now().isoformat()
        }

    def _reduce_sl(self, config: Dict) -> Optional[Dict]:
        """Reduit SL (perte moyenne > 2x gain moyen)."""
        tpsl = config.get("tpsl_config", {})
        current_sl = tpsl.get("sl_pct", 0.5)
        new_sl = round(max(self.SL_MIN, current_sl - self.SL_STEP), 3)
        if new_sl == current_sl:
            return None
        tpsl["sl_pct"] = new_sl
        config["tpsl_config"] = tpsl
        return {
            "type": "RISK_MANAGEMENT", "field": "tpsl_config.sl_pct",
            "old_value": current_sl, "new_value": new_sl,
            "timestamp": datetime.now().isoformat()
        }

    def _increase_position_size(self, config: Dict) -> Optional[Dict]:
        """Augmente position size (performance excellente)."""
        current = config.get("position_size_pct", 0.01)
        new_value = round(min(self.POSITION_SIZE_MAX, current + self.POSITION_SIZE_STEP), 4)
        if new_value == current:
            return None
        config["position_size_pct"] = new_value
        return {
            "type": "INCREASE_RISK", "field": "position_size_pct",
            "old_value": current, "new_value": new_value,
            "timestamp": datetime.now().isoformat()
        }

    # ================================================================
    #  UTILITAIRES
    # ================================================================

    def _load_agent_config(self, agent_id: str) -> Optional[Dict]:
        """Charge la config d'un agent."""
        config_file = CONFIG_PATH / "agents.json"
        if not config_file.exists():
            return None
        try:
            with open(config_file, "r") as f:
                all_configs = json.load(f)
                return all_configs.get(agent_id)
        except Exception:
            return None

    def _save_agent_config(self, agent_id: str, config: Dict):
        """Sauvegarde la config d'un agent."""
        config_file = CONFIG_PATH / "agents.json"
        try:
            with open(config_file, "r") as f:
                all_configs = json.load(f)
            all_configs[agent_id] = config
            with open(config_file, "w") as f:
                json.dump(all_configs, f, indent=4)
        except Exception as e:
            print(f"[IA Adjust] Erreur sauvegarde config: {e}")

    def _load_open_positions(self, agent_id: str) -> list:
        """Charge les positions ouvertes d'un agent."""
        pos_file = DATABASE_PATH / "open_positions" / f"{agent_id}.json"
        if not pos_file.exists():
            return []
        try:
            with open(pos_file, "r") as f:
                return json.load(f)
        except Exception:
            return []

    def _log_adjustments(self, agent_id: str, adjustments: List[Dict]):
        """Log les ajustements effectues."""
        log_file = DATABASE_PATH / "adjustments_log.json"
        try:
            existing = []
            if log_file.exists():
                with open(log_file, "r") as f:
                    existing = json.load(f)
            for adj in adjustments:
                adj["agent_id"] = agent_id
                existing.insert(0, adj)
            existing = existing[:100]
            with open(log_file, "w") as f:
                json.dump(existing, f, indent=2)
        except Exception as e:
            print(f"[IA Adjust] Erreur log: {e}")

    def get_recent_adjustments(self, limit: int = 20) -> List[Dict]:
        """Retourne les ajustements recents."""
        log_file = DATABASE_PATH / "adjustments_log.json"
        if not log_file.exists():
            return []
        try:
            with open(log_file, "r") as f:
                return json.load(f)[:limit]
        except Exception:
            return []

    def manual_adjust(self, agent_id: str, field: str, value) -> Dict:
        """Ajustement manuel d'un parametre."""
        config = self._load_agent_config(agent_id)
        if not config:
            return {"success": False, "message": "Agent non trouve"}
        old_value = config.get(field)
        config[field] = value
        self._save_agent_config(agent_id, config)
        adjustment = {
            "type": "MANUAL_ADJUST", "field": field,
            "old_value": old_value, "new_value": value,
            "timestamp": datetime.now().isoformat()
        }
        self._log_adjustments(agent_id, [adjustment])
        return {"success": True, "message": f"{field}: {old_value} -> {value}"}


# Singleton
_ia_adjust = None

def get_ia_adjust() -> IAdjust:
    """Retourne l'instance IAdjust singleton."""
    global _ia_adjust
    if _ia_adjust is None:
        _ia_adjust = IAdjust()
    return _ia_adjust
