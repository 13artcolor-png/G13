# -*- coding: utf-8 -*-
"""
G13 - Donnees Sentiment
Fear & Greed Index, News RSS
"""

import requests
from datetime import datetime
from typing import Optional, Dict, List
import time


class SentimentData:
    """Recupere les donnees de sentiment pour BTC"""

    def __init__(self):
        self.fear_greed_url = "https://api.alternative.me/fng/"
        self.cache = {}
        self.cache_duration = 60  # secondes

    def _get_cached(self, key: str) -> Optional[Dict]:
        """Recupere depuis le cache si valide"""
        if key in self.cache:
            data, timestamp = self.cache[key]
            if time.time() - timestamp < self.cache_duration:
                return data
        return None

    def _set_cache(self, key: str, data: Dict):
        """Stocke dans le cache"""
        self.cache[key] = (data, time.time())

    def get_fear_greed_index(self) -> Optional[Dict]:
        """Recupere le Fear & Greed Index"""
        cached = self._get_cached("fear_greed")
        if cached:
            return cached

        try:
            response = requests.get(self.fear_greed_url, timeout=5)

            if response.status_code != 200:
                return None

            data = response.json()

            if "data" not in data or len(data["data"]) == 0:
                return None

            current = data["data"][0]

            value = int(current.get("value", 50))
            if value <= 25:
                interpretation = "Extreme Fear"
                signal = "bullish"
            elif value <= 40:
                interpretation = "Fear"
                signal = "slightly_bullish"
            elif value <= 60:
                interpretation = "Neutral"
                signal = "neutral"
            elif value <= 75:
                interpretation = "Greed"
                signal = "slightly_bearish"
            else:
                interpretation = "Extreme Greed"
                signal = "bearish"

            result = {
                "value": value,
                "label": current.get("value_classification", "Unknown"),
                "interpretation": interpretation,
                "signal": signal,
                "timestamp": datetime.now().isoformat()
            }

            self._set_cache("fear_greed", result)
            return result

        except Exception as e:
            print(f"[Sentiment] Erreur Fear & Greed: {e}")
            return None

    def get_news_sentiment(self) -> Optional[Dict]:
        """Retourne un sentiment de news simplifie (basee sur fear/greed)"""
        fear_greed = self.get_fear_greed_index()
        if not fear_greed:
            return None

        value = fear_greed["value"]

        # Score de -100 a +100 base sur fear/greed
        score = (value - 50) * 2  # 0->-100, 50->0, 100->+100

        return {
            "score": round(score, 1),
            "bias": "bullish" if score > 20 else "bearish" if score < -20 else "neutral",
            "timestamp": datetime.now().isoformat()
        }

    def get_all_sentiment(self) -> Dict:
        """Recupere toutes les donnees de sentiment"""
        fear_greed = self.get_fear_greed_index()
        news = self.get_news_sentiment()

        global_score = 50
        if fear_greed:
            global_score = fear_greed["value"]

        return {
            "fear_greed": fear_greed,
            "news_sentiment": news,
            "global_score": round(global_score, 1),
            "global_bias": "bullish" if global_score > 60 else "bearish" if global_score < 40 else "neutral"
        }


# Singleton
_sentiment_instance = None

def get_sentiment() -> SentimentData:
    """Retourne l'instance Sentiment singleton"""
    global _sentiment_instance
    if _sentiment_instance is None:
        _sentiment_instance = SentimentData()
    return _sentiment_instance
