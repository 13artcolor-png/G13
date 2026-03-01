"""
G13 AI Decision Module
======================
RESPONSABILITE UNIQUE: Appeler l'IA via Requesty pour obtenir une decision de trading.

Charge la cle API depuis api_keys.json + api_selections.json
Envoie le prompt a l'IA et retourne la reponse brute.

Usage:
    from agents.ai_decision import call_ai, parse_decision
    response = call_ai("fibo1", prompt, system_prompt)
    decision = parse_decision(response)
"""

import json
import re
import requests
from pathlib import Path
from typing import Optional, Dict

DATABASE_PATH = Path(__file__).parent.parent / "database"
CONFIG_PATH = DATABASE_PATH / "config"

REQUESTY_URL = "https://router.requesty.ai/v1/chat/completions"


def _load_api_config(agent_id: str) -> Dict:
    """
    Charge la config API pour un agent depuis api_keys.json + api_selections.json.
    
    Returns:
        dict: {"key": str, "model": str, "provider": str} ou {}
    """
    try:
        keys_file = CONFIG_PATH / "api_keys.json"
        selections_file = CONFIG_PATH / "api_selections.json"

        if not keys_file.exists() or not selections_file.exists():
            return {}

        with open(keys_file, "r", encoding="utf-8") as f:
            keys_data = json.load(f)
        with open(selections_file, "r", encoding="utf-8") as f:
            selections_data = json.load(f)

        key_id = selections_data.get("selections", {}).get(agent_id)
        if not key_id:
            return {}

        selected_key = next(
            (k for k in keys_data.get("keys", []) if k["id"] == key_id),
            None
        )
        return selected_key or {}

    except Exception as e:
        print(f"[AI] Erreur chargement API config {agent_id}: {e}")
        return {}


def call_ai(agent_id: str, prompt: str, system_prompt: str = None, max_tokens: int = 500) -> Optional[str]:
    """
    Appelle l'IA via Requesty.

    Args:
        agent_id: ID de l'agent (fibo1, fibo2, fibo3)
        prompt: Prompt utilisateur (contexte marche + question)
        system_prompt: Prompt systeme (role de l'agent)
        max_tokens: Nombre max de tokens en sortie (500 pour agents, 1500 pour strategist)

    Returns:
        str: Reponse brute de l'IA, ou None si erreur
    """
    api_config = _load_api_config(agent_id)

    if not api_config.get("key"):
        print(f"[AI] {agent_id} - Pas de cle API configuree")
        return None

    key = api_config["key"]
    model = api_config.get("model", "anthropic/claude-sonnet-4-20250514")
    provider = api_config.get("provider", "requesty")

    # Requesty exige le format "provider/model" (ex: google/gemini-2.5-flash)
    # Si le model ne contient pas de "/" et qu'on utilise Requesty, ajouter le prefix provider
    if "/" not in model and provider != "requesty":
        model = f"{provider}/{model}"

    # Construction des messages
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    # URL selon provider
    if provider == "groq" and not key.startswith("rqsty-"):
        url = "https://api.groq.com/openai/v1/chat/completions"
    else:
        url = REQUESTY_URL

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.3
    }

    try:
        print(f"[AI] {agent_id} - Appel {provider} ({model})...")
        response = requests.post(url, headers=headers, json=payload, timeout=30)

        if response.status_code != 200:
            print(f"[AI] {agent_id} - Erreur HTTP {response.status_code}: {response.text[:200]}")
            return None

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        print(f"[AI] {agent_id} - Reponse: {content[:80]}...")
        return content

    except requests.exceptions.Timeout:
        print(f"[AI] {agent_id} - Timeout API (30s)")
        return None
    except Exception as e:
        print(f"[AI] {agent_id} - Erreur appel API: {e}")
        return None


def parse_decision(response: str) -> Dict:
    """
    Parse la reponse de l'IA pour extraire la decision.

    PRIORITE: Cherche le pattern ACTION: BUY/SELL/HOLD en premier.
    Fallback: Cherche le premier mot-cle BUY/SELL dans les 30 premiers caracteres.

    Returns:
        dict: {"action": str, "reason": str, "confidence": int}
    """
    if not response:
        return {"action": "HOLD", "reason": "Pas de reponse IA", "confidence": 0}

    response_upper = response.upper()

    # PRIORITE 1: Chercher le pattern explicite ACTION: XXX
    action_match = re.search(r'ACTION\s*:\s*(BUY|SELL|HOLD)', response_upper)
    if action_match:
        action = action_match.group(1)
    else:
        # FALLBACK: Chercher dans les 30 premiers caracteres seulement
        # (evite de confondre BUY/SELL dans la raison)
        first_part = response_upper[:30]
        if "BUY" in first_part:
            action = "BUY"
        elif "SELL" in first_part:
            action = "SELL"
        else:
            action = "HOLD"

    # Extraire la raison
    reason = response[:150] if len(response) > 150 else response
    if "RAISON:" in response_upper:
        idx = response_upper.index("RAISON:")
        reason = response[idx + 7:].strip()[:150]
    elif "|" in response:
        parts = response.split("|")
        if len(parts) > 1:
            reason = parts[1].strip()[:150]

    # Extraire la confiance (si mentionnee)
    confidence = 50
    for word in response_upper.split():
        if "%" in word:
            try:
                num = int(word.replace("%", "").strip())
                if 0 <= num <= 100:
                    confidence = num
                    break
            except:
                pass

    return {
        "action": action,
        "reason": reason,
        "confidence": confidence,
        "raw_response": response
    }
