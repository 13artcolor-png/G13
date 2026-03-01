"""
MT5 Market Data Module
======================
UNIQUE RESPONSIBILITY: Recuperer les donnees de marche depuis MT5

Usage:
    from actions.mt5.market_data import get_market_data, get_ohlc
    data = get_market_data("XAUUSD")
"""

import MetaTrader5 as mt5
from datetime import datetime, timedelta
from typing import Dict, List, Optional


def get_current_price(symbol: str) -> dict:
    """
    Recupere le prix actuel d'un symbole.

    Args:
        symbol: Le symbole (ex: "XAUUSD")

    Returns:
        dict: {"success": bool, "bid": float, "ask": float, "spread": float}

    Note: MT5 doit etre connecte avant d'appeler cette fonction.
    """
    try:
        tick = mt5.symbol_info_tick(symbol)

        if tick is None:
            return {
                "success": False,
                "message": f"Impossible de recuperer le tick pour {symbol}",
                "bid": 0,
                "ask": 0,
                "spread": 0
            }

        return {
            "success": True,
            "bid": tick.bid,
            "ask": tick.ask,
            "spread": round(tick.ask - tick.bid, 5),
            "time": tick.time
        }

    except Exception as e:
        return {
            "success": False,
            "message": str(e),
            "bid": 0,
            "ask": 0,
            "spread": 0
        }


def get_ohlc(symbol: str, timeframe: str = "M5", count: int = 100) -> dict:
    """
    Recupere les donnees OHLC (Open, High, Low, Close).

    Args:
        symbol: Le symbole (ex: "XAUUSD")
        timeframe: Timeframe ("M1", "M5", "M15", "H1", "H4", "D1")
        count: Nombre de bougies

    Returns:
        dict: {
            "success": bool,
            "candles": List[dict],
            "high": float,  # Plus haut sur la periode
            "low": float    # Plus bas sur la periode
        }
    """
    try:
        # Mapper le timeframe
        tf_map = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1
        }

        mt5_tf = tf_map.get(timeframe, mt5.TIMEFRAME_M5)

        # Recuperer les rates
        rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, count)

        if rates is None or len(rates) == 0:
            return {
                "success": False,
                "message": f"Pas de donnees pour {symbol}",
                "candles": [],
                "high": 0,
                "low": 0
            }

        candles = []
        highs = []
        lows = []

        for rate in rates:
            candles.append({
                "time": rate['time'],
                "open": rate['open'],
                "high": rate['high'],
                "low": rate['low'],
                "close": rate['close'],
                "volume": rate['tick_volume']
            })
            highs.append(rate['high'])
            lows.append(rate['low'])

        return {
            "success": True,
            "candles": candles,
            "high": max(highs),
            "low": min(lows),
            "count": len(candles)
        }

    except Exception as e:
        return {
            "success": False,
            "message": str(e),
            "candles": [],
            "high": 0,
            "low": 0
        }


def calculate_fibonacci_levels(high: float, low: float) -> dict:
    """
    Calcule les niveaux Fibonacci entre un high et un low.

    Args:
        high: Prix le plus haut
        low: Prix le plus bas

    Returns:
        dict: Niveaux Fibonacci
    """
    diff = high - low

    return {
        "0": high,
        "0.236": high - (diff * 0.236),
        "0.382": high - (diff * 0.382),
        "0.5": high - (diff * 0.5),
        "0.618": high - (diff * 0.618),
        "0.786": high - (diff * 0.786),
        "1": low
    }


def detect_trend(candles: List[dict]) -> str:
    """
    Detecte la tendance avec EMA 20 vs EMA 50 (methode robuste).

    Args:
        candles: Liste des bougies OHLC (minimum 50 pour fiabilite)

    Returns:
        str: "bullish", "bearish", ou "neutral"
    """
    if len(candles) < 50:
        return "neutral"

    closes = [c['close'] for c in candles]

    # Calculer EMA 20 et EMA 50
    ema20 = _calculate_ema(closes, 20)
    ema50 = _calculate_ema(closes, 50)

    if ema50 == 0:
        return "neutral"

    # Ecart en % entre EMA 20 et EMA 50
    diff_pct = ((ema20 - ema50) / ema50) * 100

    # Seuil 0.05% pour eviter le bruit (EMA lisse deja beaucoup)
    if diff_pct > 0.05:
        return "bullish"
    elif diff_pct < -0.05:
        return "bearish"
    else:
        return "neutral"


def _calculate_ema(values: List[float], period: int) -> float:
    """Calcule l'EMA (Exponential Moving Average) sur une serie de valeurs."""
    if len(values) < period:
        return 0.0

    multiplier = 2.0 / (period + 1)
    # SMA initiale
    sma_sum = 0.0
    for i in range(period):
        sma_sum += values[i]
    ema = sma_sum / period

    for i in range(period, len(values)):
        ema = (values[i] - ema) * multiplier + ema

    return ema


def find_last_swings(candles: List[dict], lookback: int = 3) -> dict:
    """
    Trouve le dernier swing high et le dernier swing low sur les bougies.

    Un swing high = bougie dont le high est superieur aux N bougies avant et apres.
    Un swing low = bougie dont le low est inferieur aux N bougies avant et apres.

    Args:
        candles: Bougies OHLC
        lookback: Nombre de bougies pour confirmer un swing (defaut 3)

    Returns:
        dict: {"swing_high": float, "swing_low": float}
    """
    n = len(candles)
    if n < lookback * 2 + 1:
        # Pas assez de bougies, utiliser max/min bruts
        return {
            "swing_high": max(c["high"] for c in candles),
            "swing_low": min(c["low"] for c in candles)
        }

    swing_highs = []
    swing_lows = []

    for i in range(lookback, n - lookback):
        # Swing high: plus haut que les N voisins de chaque cote
        is_high = True
        for j in range(1, lookback + 1):
            if candles[i]["high"] <= candles[i - j]["high"] or candles[i]["high"] <= candles[i + j]["high"]:
                is_high = False
                break
        if is_high:
            swing_highs.append(candles[i]["high"])

        # Swing low: plus bas que les N voisins de chaque cote
        is_low = True
        for j in range(1, lookback + 1):
            if candles[i]["low"] >= candles[i - j]["low"] or candles[i]["low"] >= candles[i + j]["low"]:
                is_low = False
                break
        if is_low:
            swing_lows.append(candles[i]["low"])

    # Prendre le dernier swing detecte (le plus recent)
    sh = swing_highs[-1] if swing_highs else max(c["high"] for c in candles)
    sl = swing_lows[-1] if swing_lows else min(c["low"] for c in candles)

    return {"swing_high": sh, "swing_low": sl}


def calculate_momentum(candles: List[dict], periods: int = 5) -> float:
    """
    Calcule le momentum en pourcentage.

    Args:
        candles: Liste des bougies OHLC
        periods: Nombre de periodes pour le calcul

    Returns:
        float: Momentum en pourcentage
    """
    if len(candles) < periods + 1:
        return 0.0

    current = candles[-1]['close']
    previous = candles[-(periods + 1)]['close']

    if previous == 0:
        return 0.0

    return round(((current - previous) / previous) * 100, 3)


def calculate_volatility(candles: List[dict], periods: int = 20) -> float:
    """
    Calcule la volatilite (ecart-type des variations en %).

    Args:
        candles: Liste des bougies OHLC
        periods: Nombre de periodes

    Returns:
        float: Volatilite en pourcentage
    """
    if len(candles) < periods:
        return 0.0

    recent = candles[-periods:]
    returns = []

    for i in range(1, len(recent)):
        prev_close = recent[i-1]['close']
        if prev_close > 0:
            ret = (recent[i]['close'] - prev_close) / prev_close * 100
            returns.append(ret)

    if not returns:
        return 0.0

    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)

    return round(variance ** 0.5, 2)


def get_full_market_data(symbol: str = "BTCUSD") -> dict:
    """
    Recupere toutes les donnees de marche pour le frontend.
    Inclut prix, spread, momentum multi-timeframe et volatilite.

    Args:
        symbol: Le symbole (default BTCUSD)

    Returns:
        dict: {
            "price": float,
            "spread_points": float,
            "volatility_pct": float,
            "fibo1": {"1m": float, "5m": float},
            "fibo2": {"1m": float, "5m": float},
            "fibo3": {"1m": float, "5m": float}
        }
    """
    result = {
        "price": 0,
        "spread_points": 0,
        "volatility_pct": 0,
        "fibo1": {"1m": 0, "5m": 0},
        "fibo2": {"1m": 0, "5m": 0},
        "fibo3": {"1m": 0, "5m": 0}
    }

    try:
        # Prix actuel
        price_data = get_current_price(symbol)
        if price_data["success"]:
            result["price"] = price_data["bid"]
            # Spread en points (pour BTC, 1 point = 0.01)
            result["spread_points"] = round(price_data["spread"], 2)

        # OHLC M1 pour momentum 1m
        ohlc_m1 = get_ohlc(symbol, "M1", 20)
        if ohlc_m1["success"] and ohlc_m1["candles"]:
            mom_1m = calculate_momentum(ohlc_m1["candles"], 5)
            result["fibo1"]["1m"] = mom_1m
            result["fibo2"]["1m"] = mom_1m
            result["fibo3"]["1m"] = mom_1m

        # OHLC M5 pour momentum 5m et volatilite
        ohlc_m5 = get_ohlc(symbol, "M5", 50)
        if ohlc_m5["success"] and ohlc_m5["candles"]:
            mom_5m = calculate_momentum(ohlc_m5["candles"], 5)
            result["fibo1"]["5m"] = mom_5m
            result["fibo2"]["5m"] = mom_5m
            result["fibo3"]["5m"] = mom_5m
            result["volatility_pct"] = calculate_volatility(ohlc_m5["candles"], 20)

    except Exception as e:
        print(f"[Market Data] Erreur: {e}")

    return result


def get_market_data(symbol: str, timeframe: str = "M5") -> dict:
    """
    Recupere toutes les donnees de marche necessaires pour le trading.

    Args:
        symbol: Le symbole
        timeframe: Timeframe pour l'analyse

    Returns:
        dict: {
            "symbol": str,
            "price": float,
            "bid": float,
            "ask": float,
            "spread": float,
            "high": float,
            "low": float,
            "trend": str,
            "fibo_levels": dict
        }
    """
    # Prix actuel
    price_data = get_current_price(symbol)

    if not price_data["success"]:
        return {
            "success": False,
            "message": price_data.get("message", "Erreur prix"),
            "symbol": symbol,
            "price": 0,
            "fibo_levels": {}
        }

    # Donnees OHLC
    ohlc_data = get_ohlc(symbol, timeframe, 100)

    if not ohlc_data["success"]:
        return {
            "success": False,
            "message": ohlc_data.get("message", "Erreur OHLC"),
            "symbol": symbol,
            "price": price_data["bid"],
            "fibo_levels": {}
        }

    # Calculer Fibonacci
    fibo_levels = calculate_fibonacci_levels(ohlc_data["high"], ohlc_data["low"])

    # Detecter tendance
    trend = detect_trend(ohlc_data["candles"])

    return {
        "success": True,
        "symbol": symbol,
        "price": price_data["bid"],
        "bid": price_data["bid"],
        "ask": price_data["ask"],
        "spread": price_data["spread"],
        "high": ohlc_data["high"],
        "low": ohlc_data["low"],
        "trend": trend,
        "fibo_levels": fibo_levels,
        "timeframe": timeframe
    }
