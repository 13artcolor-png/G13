"""
G13 - Test Lot Sizing Exponentiel
==================================
Ce script teste le calcul de lot size dynamique.
Il se connecte a MT5 via fibo1, calcule le lot size
et ouvre un trade BUY BTCUSD.

Usage: python test_lot_sizing.py
Executer depuis: G13 backend
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import math
import MetaTrader5 as mt5
import json

# === CONFIG ===
AGENT_ID = "fibo1"
SYMBOL = "BTCUSD"
RISK_PCT = 0.5  # 0.5% du capital par trade
SL_FALLBACK_PCT = 0.5  # 0.5% du prix d'entree
TP_FALLBACK_PCT = 1.0  # 1.0% du prix d'entree (R:R = 2:1)

def main():
    print("=" * 60)
    print("  G13 - TEST LOT SIZING EXPONENTIEL")
    print("=" * 60)

    # 1. Charger config MT5
    config_path = os.path.join(os.path.dirname(__file__), "database", "config", "mt5_accounts.json")
    with open(config_path, "r") as f:
        mt5_accounts = json.load(f)

    account = mt5_accounts.get(AGENT_ID, {})
    login = account.get("login")
    password = account.get("password")
    server = account.get("server")

    print(f"\n[1] Connexion MT5: {login} @ {server}")

    # 2. Connexion MT5
    if not mt5.initialize():
        print(f"ERREUR: MT5 initialize failed: {mt5.last_error()}")
        return

    if not mt5.login(login, password=password, server=server):
        print(f"ERREUR: MT5 login failed: {mt5.last_error()}")
        mt5.shutdown()
        return

    # 3. Balance
    account_info = mt5.account_info()
    balance = account_info.balance
    equity = account_info.equity
    print(f"[2] Balance: {balance:.2f} EUR | Equity: {equity:.2f} EUR")

    # 4. Prix actuel
    tick = mt5.symbol_info_tick(SYMBOL)
    if not tick:
        print(f"ERREUR: Impossible de recuperer le prix de {SYMBOL}")
        mt5.shutdown()
        return

    price = tick.ask  # BUY au ask
    bid = tick.bid
    spread = tick.ask - tick.bid
    print(f"[3] Prix {SYMBOL}: Bid={bid:.2f} Ask={price:.2f} Spread={spread:.2f}")

    # 5. Symbol info
    sym_info = mt5.symbol_info(SYMBOL)
    if not sym_info:
        print(f"ERREUR: symbol_info failed pour {SYMBOL}")
        mt5.shutdown()
        return

    tick_size = sym_info.trade_tick_size
    tick_value = sym_info.trade_tick_value
    volume_min = sym_info.volume_min
    volume_max = sym_info.volume_max
    volume_step = sym_info.volume_step
    digits = sym_info.digits
    contract_size = sym_info.trade_contract_size

    print(f"[4] Symbol info:")
    print(f"    tick_size={tick_size}, tick_value={tick_value}")
    print(f"    volume_min={volume_min}, volume_max={volume_max}, volume_step={volume_step}")
    print(f"    contract_size={contract_size}, digits={digits}")

    # 6. Calculer SL et TP
    sl_distance_pct = SL_FALLBACK_PCT / 100
    tp_distance_pct = TP_FALLBACK_PCT / 100

    sl = round(price * (1 - sl_distance_pct), digits)
    tp = round(price * (1 + tp_distance_pct), digits)
    sl_distance = abs(price - sl)
    tp_distance = abs(tp - price)
    rr_ratio = tp_distance / sl_distance if sl_distance > 0 else 0

    print(f"\n[5] SL/TP:")
    print(f"    Entry: {price:.2f}")
    print(f"    SL:    {sl:.2f} (distance: {sl_distance:.2f}, {SL_FALLBACK_PCT}%)")
    print(f"    TP:    {tp:.2f} (distance: {tp_distance:.2f}, {TP_FALLBACK_PCT}%)")
    print(f"    R:R =  {rr_ratio:.2f}")

    # 7. CALCUL LOT SIZE EXPONENTIEL
    risk_amount = balance * (RISK_PCT / 100)
    loss_per_lot = sl_distance * (tick_value / tick_size)

    if loss_per_lot <= 0:
        print(f"ERREUR: loss_per_lot = {loss_per_lot}")
        mt5.shutdown()
        return

    raw_lot = risk_amount / loss_per_lot

    # Arrondir au volume_step
    if volume_step > 0:
        lot_size = math.floor(raw_lot / volume_step) * volume_step
    else:
        lot_size = raw_lot

    # Clamp
    lot_size = max(volume_min, min(lot_size, volume_max))

    # Arrondir
    decimals = len(str(volume_step).rstrip('0').split('.')[-1]) if '.' in str(volume_step) else 0
    lot_size = round(lot_size, decimals)

    print(f"\n[6] LOT SIZING EXPONENTIEL:")
    print(f"    Balance:      {balance:.2f} EUR")
    print(f"    Risk:         {RISK_PCT}% = {risk_amount:.2f} EUR")
    print(f"    SL distance:  {sl_distance:.2f} points")
    print(f"    Loss/lot:     {loss_per_lot:.2f} EUR")
    print(f"    Raw lot:      {raw_lot:.6f}")
    print(f"    Final lot:    {lot_size}")
    print(f"    Perte max:    {lot_size * loss_per_lot:.2f} EUR (si SL touche)")

    # 8. Simuler avec balance x2 (pour montrer l'exponentiel)
    balance_x2 = balance * 2
    risk_x2 = balance_x2 * (RISK_PCT / 100)
    lot_x2 = math.floor((risk_x2 / loss_per_lot) / volume_step) * volume_step
    lot_x2 = max(volume_min, min(lot_x2, volume_max))
    lot_x2 = round(lot_x2, decimals)

    print(f"\n[7] SIMULATION EXPONENTIELLE:")
    print(f"    Si balance = {balance_x2:.2f} EUR (x2)")
    print(f"    Lot size =   {lot_x2} (risque {risk_x2:.2f} EUR)")
    print(f"    >>> Les lots doublent quand le capital double = EXPONENTIEL")

    # 9. Ouvrir le trade
    print(f"\n[8] OUVERTURE TRADE:")
    print(f"    BUY {lot_size} {SYMBOL} @ {price:.2f}")
    print(f"    SL={sl:.2f} TP={tp:.2f}")

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": lot_size,
        "type": mt5.ORDER_TYPE_BUY,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 20,
        "magic": 999999,  # Magic special pour test
        "comment": "G13_TEST_LOT_SIZING",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)

    if result is None:
        print(f"    ERREUR: order_send retourne None: {mt5.last_error()}")
    elif result.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"    SUCCES! Ticket: #{result.order}")
        print(f"    Prix execute: {result.price}")
        print(f"    Volume: {result.volume}")
    else:
        print(f"    ECHEC: code={result.retcode}, message={result.comment}")

    # 10. Cleanup
    mt5.shutdown()
    print(f"\n{'=' * 60}")
    print(f"  TEST TERMINE")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
