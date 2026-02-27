"""
Agents Module
=============
Agents de trading G13.

- base.py: Classe de base abstraite
- fibo_agent.py: Agent Fibonacci + ICT/SMC
"""

from .base import BaseAgent
from .fibo_agent import FiboAgent, Fibo1Agent, Fibo2Agent, Fibo3Agent

__all__ = [
    "BaseAgent",
    "FiboAgent",
    "Fibo1Agent",
    "Fibo2Agent",
    "Fibo3Agent"
]


# Factory pour creer les agents
def create_agent(agent_id: str):
    """Cree un agent par son ID."""
    agents = {
        "fibo1": Fibo1Agent,
        "fibo2": Fibo2Agent,
        "fibo3": Fibo3Agent
    }

    agent_class = agents.get(agent_id)
    if agent_class:
        return agent_class()
    return None


def get_all_agents():
    """Retourne tous les agents."""
    return {
        "fibo1": Fibo1Agent(),
        "fibo2": Fibo2Agent(),
        "fibo3": Fibo3Agent()
    }
