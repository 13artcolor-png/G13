"""
G13 - Modify Trade
==================
RESPONSABILITE: Modifier le SL/TP d'une position ouverte sur MT5.

Usage:
    from actions.mt5.modify_trade import modify_trade_sl_tp, get_symbol_info
    result = modify_trade_sl_tp(ticket, new_sl=xxx, new_tp=yyy)
"""

import MetaTrader5 as mt5


def get_symbol_info(symbol: str) -> dict:
    """
    Recupere les infos d'un symbole MT5.
    
    Returns:
        dict avec tick_size, tick_value, volume_min, volume_max, volume_step, digits, contract_size
    """
    try:
        info = mt5.symbol_info(symbol)
        if not info:
            return {"success": False, "message": f"Symbol {symbol} introuvable"}
        
        return {
            "success": True,
            "symbol": symbol,
            "tick_size": info.trade_tick_size,
            "tick_value": info.trade_tick_value,
            "volume_min": info.volume_min,
            "volume_max": info.volume_max,
            "volume_step": info.volume_step,
            "digits": info.digits,
            "contract_size": info.trade_contract_size,
            "point": info.point
        }
    except Exception as e:
        return {"success": False, "message": f"Erreur get_symbol_info: {e}"}


def modify_trade_sl_tp(ticket: int, new_sl: float = None, new_tp: float = None, symbol: str = None) -> dict:
    """
    Modifie le SL et/ou TP d'une position ouverte.
    
    Args:
        ticket: Numero du ticket de la position
        new_sl: Nouveau Stop Loss (None = pas de changement)
        new_tp: Nouveau Take Profit (None = pas de changement)
        symbol: Symbole (optionnel, auto-detecte si absent)
    
    Returns:
        dict avec success, message, old_sl, old_tp, new_sl, new_tp
    """
    try:
        # Recuperer la position actuelle
        position = mt5.positions_get(ticket=ticket)
        if not position or len(position) == 0:
            return {"success": False, "message": f"Position {ticket} introuvable"}
        
        pos = position[0]
        current_sl = pos.sl
        current_tp = pos.tp
        pos_symbol = symbol or pos.symbol
        
        # Utiliser les valeurs actuelles si non specifiees
        final_sl = new_sl if new_sl is not None else current_sl
        final_tp = new_tp if new_tp is not None else current_tp
        
        # Verifier qu'il y a un changement significatif
        if abs(final_sl - current_sl) < 0.01 and abs(final_tp - current_tp) < 0.01:
            return {"success": True, "message": "Aucun changement necessaire", "changed": False}
        
        # Arrondir selon les digits du symbole
        sym_info = mt5.symbol_info(pos_symbol)
        if sym_info:
            digits = sym_info.digits
            final_sl = round(final_sl, digits)
            final_tp = round(final_tp, digits)
        
        # Envoyer la requete de modification
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": pos_symbol,
            "sl": final_sl,
            "tp": final_tp,
        }
        
        result = mt5.order_send(request)
        
        if result is None:
            error = mt5.last_error()
            return {"success": False, "message": f"order_send None: {error}"}
        
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            return {
                "success": True,
                "changed": True,
                "message": f"Position {ticket} modifiee: SL={final_sl} TP={final_tp}",
                "old_sl": current_sl,
                "old_tp": current_tp,
                "new_sl": final_sl,
                "new_tp": final_tp
            }
        else:
            return {
                "success": False,
                "message": f"Modification echouee: code={result.retcode} {result.comment}"
            }
    
    except Exception as e:
        return {"success": False, "message": f"Erreur modify_trade: {e}"}
