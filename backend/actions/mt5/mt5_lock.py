"""
MT5 Lock Module
===============
RESPONSABILITE: Verrou global pour l'acces a MT5.

MT5 Python API est un SINGLETON GLOBAL: une seule connexion possible a la fois.
Plusieurs threads y accedent (trading loop + routes API FastAPI).
Ce verrou garantit l'acces exclusif.

Usage:
    from actions.mt5.mt5_lock import mt5_lock
    
    # Le lock est acquis par connect_mt5() et libere par disconnect_mt5()
    # Ne pas utiliser directement sauf cas special.
"""

import threading

# Verrou global MT5 - timeout 30s pour eviter deadlock
mt5_lock = threading.Lock()

# Timeout pour acquire (secondes)
MT5_LOCK_TIMEOUT = 30
