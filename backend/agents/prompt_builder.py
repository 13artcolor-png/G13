"""
G13 Prompt Builder
==================
RESPONSABILITE UNIQUE: Construire les prompts pour les agents IA.

Assemble les donnees de marche, niveaux Fibonacci, patterns institutionnels,
sentiment et momentum en un prompt structure pour l'IA.

Usage:
    from agents.prompt_builder import build_opener_prompt, build_system_prompt
    system = build_system_prompt("fibo1", config)
    prompt = build_opener_prompt(market_data, config, institutional, sentiment, futures)
"""

from typing import Dict, Optional, List
import numpy as np


def build_system_prompt(agent_id: str, config: Dict) -> str:
    """
    Construit le prompt systeme pour un agent.
    
    Args:
        agent_id: ID de l'agent (fibo1, fibo2, fibo3)
        config: Configuration de l'agent depuis agents.json
    """
    name = config.get("name", agent_id.upper())
    description = config.get("description", "")
    fibo_level = config.get("fibo_level", "0.236")

    tolerance = config.get("fibo_tolerance_pct", 2.0)

    return f"""Tu es {name}, un agent de trading IA specialise BTCUSD.
{description}

TON NIVEAU FIBONACCI CIBLE: {fibo_level}
TOLERANCE: {tolerance}% autour du niveau cible (si le prix est a moins de {tolerance}% du niveau, considere qu'il est PROCHE)

REGLES:
1. Reponds UNIQUEMENT par: ACTION: BUY | RAISON: ... ou ACTION: SELL | RAISON: ... ou ACTION: HOLD | RAISON: ...
2. Si le prix est dans la zone de tolerance de ton niveau Fibo -> cherche un signal d'entree
3. L'analyse institutionnelle (ICT/SMC) est un BONUS, pas une obligation. Un pattern ICT renforce le signal mais son absence ne doit PAS empecher un trade si le niveau Fibo et la tendance sont alignes
4. Respecte le sens de la structure de marche (BUY en tendance haussiere, SELL en tendance baissiere)
5. HOLD uniquement si le prix est LOIN de ton niveau cible (>{tolerance}%) OU si la tendance contredit clairement le signal

FORMAT DE REPONSE (OBLIGATOIRE):
ACTION: [BUY/SELL/HOLD] | RAISON: [explication courte et precise]"""


def build_opener_prompt(market_data: Dict, config: Dict,
                        institutional: Optional[Dict] = None,
                        sentiment: Optional[Dict] = None,
                        futures: Optional[Dict] = None,
                        open_positions_count: int = 0) -> str:
    """
    Construit le prompt d'ouverture de position.

    Args:
        market_data: Donnees MT5 (prix, fibo, trend, spread, momentum...)
        config: Configuration agent
        institutional: Analyse institutionnelle (patterns ICT/SMC)
        sentiment: Fear & Greed, news
        futures: Funding rate, L/S ratio
        open_positions_count: Nombre de positions ouvertes pour cet agent
    """
    price = market_data.get("price", 0)
    spread = market_data.get("spread", 0)
    trend = market_data.get("trend", "neutral")
    fibo_levels = market_data.get("fibo_levels", {})
    high = market_data.get("high", 0)
    low = market_data.get("low", 0)
    volatility = market_data.get("volatility_pct", 0)
    momentum_5m = market_data.get("momentum_5m", 0)
    momentum_1m = market_data.get("momentum_1m", 0)

    target_level = config.get("fibo_level", "0.236")
    tolerance_pct = config.get("fibo_tolerance_pct", 2.0)
    max_positions = config.get("max_positions", 5)
    tpsl = config.get("tpsl_config", {})

    # Calculer la distance au niveau cible
    target_price = fibo_levels.get(target_level, 0) if fibo_levels else 0
    distance_pct = abs(price - target_price) / target_price * 100 if target_price and price else 999
    in_zone = distance_pct <= tolerance_pct

    # Section Fibonacci
    fibo_section = ""
    if fibo_levels:
        zone_status = f"DANS LA ZONE (distance: {distance_pct:.2f}%, tolerance: {tolerance_pct}%)" if in_zone else f"HORS ZONE (distance: {distance_pct:.2f}%, tolerance: {tolerance_pct}%)"
        fibo_section = f"""
NIVEAUX FIBONACCI (100 bougies):
- Swing High: ${high:,.2f}
- Swing Low: ${low:,.2f}
- 0.236: ${fibo_levels.get('0.236', 0):,.2f}
- 0.382: ${fibo_levels.get('0.382', 0):,.2f}
- 0.5: ${fibo_levels.get('0.5', 0):,.2f}
- 0.618: ${fibo_levels.get('0.618', 0):,.2f}
- 0.786: ${fibo_levels.get('0.786', 0):,.2f}
NIVEAU CIBLE: {target_level} (${target_price:,.2f})
DISTANCE: {distance_pct:.2f}% | TOLERANCE: {tolerance_pct}% | STATUS: {zone_status}"""

    # Section institutionnelle
    inst_section = ""
    if institutional and "recommendation" in institutional:
        rec = institutional.get("recommendation", {})
        patterns = institutional.get("patterns_detected", [])
        structure = institutional.get("market_structure", {})
        liquidity = institutional.get("liquidity_zones", [])

        pattern_list = [
            f"{p['type']} ({p['confidence']*100:.0f}%)" for p in patterns[:3]
        ]
        liq_list = [
            f"{lz['type']} @ {lz['level']:.2f} ({lz['distance_pct']:+.2f}%)"
            for lz in liquidity[:3]
        ]

        inst_section = f"""
ANALYSE INSTITUTIONNELLE (ICT/SMC):
- Structure: {structure.get('trend', 'NEUTRAL')}
- HH: {structure.get('hh_count', 0)} | HL: {structure.get('hl_count', 0)} | LH: {structure.get('lh_count', 0)} | LL: {structure.get('ll_count', 0)}
- Patterns: {', '.join(pattern_list) if pattern_list else 'Aucun'}
- Zones liquidite: {', '.join(liq_list) if liq_list else 'Aucune'}
- Recommandation ICT: {rec.get('action', 'HOLD')} ({rec.get('confidence', 0)*100:.0f}%)
- Raison: {rec.get('reason', 'N/A')}"""

    # Section sentiment
    sent_section = ""
    if sentiment:
        fg_index = sentiment.get("fear_greed_index", "N/A")
        fg_label = sentiment.get("fear_greed_label", "N/A")
        sent_section = f"""
SENTIMENT:
- Fear & Greed: {fg_index} ({fg_label})"""

    # Section futures
    fut_section = ""
    if futures:
        fut_section = f"""
FUTURES:
- Funding Rate: {futures.get('funding_rate', 'N/A')}%
- Long/Short Ratio: {futures.get('long_short_ratio', 'N/A')}"""

    # Positions ouvertes
    pos_section = f"""
POSITIONS OUVERTES: {open_positions_count}/{max_positions}"""

    prompt = f"""=== ANALYSE BTCUSD ===

PRIX ACTUEL: ${price:,.2f}
SPREAD: {spread:.2f} points (max: {tpsl.get('max_spread_points', 50)} pts)
TENDANCE: {trend}
MOMENTUM 1m: {momentum_1m:.3f}% | 5m: {momentum_5m:.3f}%
VOLATILITE: {volatility:.2f}%
{fibo_section}
{inst_section}
{sent_section}
{fut_section}
{pos_section}

CONFIG TP/SL:
- Take Profit: {tpsl.get('tp_pct', 0.3)}% du capital
- Stop Loss: {tpsl.get('sl_pct', 0.5)}% du capital
- Trailing: demarre a +{tpsl.get('trailing_start_pct', 0.2)}%, distance {tpsl.get('trailing_distance_pct', 0.1)}%
- Break Even: a +{tpsl.get('break_even_pct', 0.15)}%

=== TA MISSION ===
Analyse le contexte ci-dessus. Decide: BUY, SELL, ou HOLD.

QUAND TRADER:
- Le prix est dans la zone de tolerance de ton niveau Fibo cible ({target_level}) ET la tendance/structure est favorable -> BUY ou SELL selon la tendance
- Un pattern ICT/SMC confirme le signal -> renforce la conviction (mais n'est PAS obligatoire)

QUAND HOLD:
- Le prix est LOIN de ton niveau Fibo cible (bien au-dela de la tolerance)
- La structure de marche contredit clairement le signal Fibonacci
- Le spread depasse le max autorise
- Tu as deja {open_positions_count}/{max_positions} positions ouvertes

FORMAT: ACTION: [BUY/SELL/HOLD] | RAISON: [explication courte]"""

    return prompt


def get_institutional_analysis(candles: List[Dict]) -> Optional[Dict]:
    """
    Execute l'analyse institutionnelle sur des bougies OHLC.
    
    Args:
        candles: Liste de dict {"open", "high", "low", "close", "volume"}
    
    Returns:
        dict: Resultat de l'analyse ou None si erreur
    """
    try:
        import sys
        from pathlib import Path
        # Ajouter le dossier backend au path pour l'import
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
