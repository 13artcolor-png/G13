"""
G13 Prompt Builder
==================
Construit les prompts pour les agents IA.
Strategie simple: Tendance M5 -> Fibonacci M1 -> Suivre la tendance -> Sinon HOLD.
"""

from typing import Dict, Optional, List
import numpy as np


def build_system_prompt(agent_id: str, config: Dict) -> str:
    """Prompt systeme pour un agent."""
    name = config.get("name", agent_id.upper())
    fibo_level = config.get("fibo_level", "0.382")
    tolerance = config.get("fibo_tolerance_pct", 2.0)

    return f"""Tu es {name}, un agent de trading BTCUSD.

NIVEAU FIBO CIBLE: {fibo_level} (tolerance: {tolerance}%)

STRATEGIE SIMPLE:
1. TENDANCE M5 (EMA 20/50) = ta DIRECTION. Haussier = BUY. Baissier = SELL. Neutre = HOLD.
2. FIBONACCI M1 (dernier swing high/low) = ton TIMING. Tu entres quand le prix retrace vers ton niveau {fibo_level}.
3. SL/TP = STRUCTURELS. SL sous le dernier plus bas (BUY) ou au-dessus du dernier plus haut (SELL). TP a l'oppose.

REGLES:
- TOUJOURS suivre la tendance M5. Jamais de contre-tendance.
- BOS (Break of Structure) dans le sens de la tendance = confirmation, GO.
- CHOCH (Change of Character) contre la tendance = HOLD, retournement possible.
- Prix loin du niveau Fibo (>{tolerance}%) = HOLD, pas de setup.
- Tendance neutre = HOLD.

FORMAT OBLIGATOIRE:
ACTION: [BUY/SELL/HOLD] | RAISON: [explication courte]"""


def build_opener_prompt(market_data: Dict, config: Dict,
                        institutional: Optional[Dict] = None,
                        sentiment: Optional[Dict] = None,
                        futures: Optional[Dict] = None,
                        open_positions_count: int = 0) -> str:
    """Prompt avec les donnees de marche."""
    price = market_data.get("price", 0)
    spread = market_data.get("spread", 0)
    trend = market_data.get("trend", "neutral")
    fibo_levels = market_data.get("fibo_levels", {})
    high = market_data.get("high", 0)
    low = market_data.get("low", 0)
    momentum_5m = market_data.get("momentum_5m", 0)
    momentum_1m = market_data.get("momentum_1m", 0)

    target_level = config.get("fibo_level", "0.382")
    tolerance_pct = config.get("fibo_tolerance_pct", 2.0)
    max_positions = config.get("max_positions", 5)
    tpsl = config.get("tpsl_config", {})

    # Distance au niveau cible
    target_price = fibo_levels.get(target_level, 0) if fibo_levels else 0
    distance_pct = abs(price - target_price) / target_price * 100 if target_price and price else 999
    in_zone = distance_pct <= tolerance_pct
    zone_status = "DANS LA ZONE" if in_zone else "HORS ZONE"

    # Section BOS/CHOCH
    bos_choch_section = ""
    if institutional and "recommendation" in institutional:
        bos = institutional.get("bos")
        choch = institutional.get("choch")
        structure = institutional.get("market_structure", {})
        bos_str = bos["description"] if bos else "Aucun"
        choch_str = choch["description"] if choch else "Aucun"
        bos_choch_section = f"""
BOS: {bos_str}
CHOCH: {choch_str}
Structure: {structure.get('trend', 'NEUTRAL')} (HH:{structure.get('hh_count', 0)} HL:{structure.get('hl_count', 0)} LH:{structure.get('lh_count', 0)} LL:{structure.get('ll_count', 0)})"""

    prompt = f"""PRIX: ${price:,.2f} | SPREAD: {spread:.2f} pts
TENDANCE M5: {trend}
MOMENTUM: 1m={momentum_1m:.3f}% | 5m={momentum_5m:.3f}%

FIBONACCI M1 (dernier swing):
- Plus Haut: ${high:,.2f}
- Plus Bas: ${low:,.2f}
- Niveau {target_level}: ${target_price:,.2f}
- Distance: {distance_pct:.2f}% | {zone_status}
{bos_choch_section}
POSITIONS: {open_positions_count}/{max_positions}

DECIDE: Tendance M5 {trend} -> {zone_status} -> BUY, SELL ou HOLD ?
FORMAT: ACTION: [BUY/SELL/HOLD] | RAISON: [courte]"""

    return prompt


def get_institutional_analysis(candles: List[Dict]) -> Optional[Dict]:
    """Execute l'analyse institutionnelle sur des bougies OHLC."""
    try:
        import sys
        from pathlib import Path
        backend_path = str(Path(__file__).parent.parent)
        if backend_path not in sys.path:
            sys.path.insert(0, backend_path)

        from institutional_patterns import InstitutionalPatternDetector

        if not candles or len(candles) < 20:
            return None

        highs = np.array([c["high"] for c in candles])
        lows = np.array([c["low"] for c in candles])
        closes = np.array([c["close"] for c in candles])

        detector = InstitutionalPatternDetector(swing_lookback=3)
        analysis = detector.analyze(highs, lows, closes)

        return analysis

    except ImportError:
        print("[PromptBuilder] Module institutional_patterns non disponible")
        return None
    except Exception as e:
        print(f"[PromptBuilder] Erreur analyse institutionnelle: {e}")
        return None
