import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta
import os
import json

class AdvancedSafetyStrategyV3:
    def __init__(self, symbol="EURUSD", timeframe=mt5.TIMEFRAME_M30):
        """
        Initialize the Advanced Safety Strategy (v3.0 Advanced)
        Logic: Dual Fibo + Half-Risk on -5%DD + Partial Close at RR 3 + Break Even
        Trading Days: Mon, Tue, Wed, Fri (No Thursdays)
        """
        self.symbol = symbol
        self.timeframe = timeframe
        self.magic_number = 333333 # Unique magic number for v3 Advanced
        self.initial_balance = 1000.0
        
        # Core Strategy Parameters
        self.start_hour = 12       # Analysis and entry time (Server Time)
        self.close_hour = 0        # Force Close (Midnight)
        self.fibo_levels = [0.618, 0.786]
        self.sl_points = 15        # Fixed SL
        self.tp1_rr = 3.0          # Partial Close & BE point
        self.tp2_rr = 6.0          # Final TP point
        
        # Risk Settings
        self.standard_risk = 1.0   # 1% standard
        self.dd_threshold = -0.05  # -5% Drawdown limit
        
        # Allowed Weekdays (0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun)
        self.allowed_weekdays = [0, 1, 2, 4] # Exclude Thursday (3)
        
        # Initialize MT5
        if not mt5.initialize():
            print(f"MT5 Initialization failed: {mt5.last_error()}")
            quit()

    def get_account_status(self):
        """Get account info for Drawdown and Risk calculation"""
        acc_info = mt5.account_info()
        if acc_info is None: return 1000.0, 1000.0
        return acc_info.balance, acc_info.equity

    def get_drawdown_risk(self, current_balance):
        """Calculate risk based on Half-Risk on Drawdown logic"""
        # In live use, max_balance should ideally be tracked across sessions.
        # For simplicity, we reference initial balance or current balance if it's a new high.
        # A more robust implementation would save max_balance to a file.
        max_balance = self.initial_balance
        
        # Simple DD check against initial balance for this example
        if current_balance < (max_balance * (1 + self.dd_threshold)):
            return 0.5
        return 1.0

    def get_lot_size(self, risk_percent, sl_points):
        """Calculate Lot Size based on Risk % and SL points"""
        acc_info = mt5.account_info()
        if acc_info is None: return 0.01
        
        risk_amount = acc_info.balance * (risk_percent / 100)
        symbol_info = mt5.symbol_info(self.symbol)
        if symbol_info is None: return 0.01
        
        tick_value = symbol_info.trade_tick_value
        if sl_points == 0 or tick_value == 0: return 0.01
        
        lot_size = risk_amount / (sl_points * tick_value)
        
        # Normalize Lot Size
        step = symbol_info.volume_step
        lot_size = round(lot_size / step) * step
        return max(lot_size, symbol_info.volume_min)

    def manage_orders(self):
        """Manage active positions: Partial Close & Break Even at RR 3"""
        positions = mt5.positions_get(symbol=self.symbol, magic=self.magic_number)
        if not positions: return

        for pos in positions:
            entry_price = pos.price_open
            tick = mt5.symbol_info_tick(self.symbol)
            if not tick: continue
            
            current_price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
            
            # Calculate original SL distance
            # Note: We assume SL was set. If not, we skip.
            if pos.sl == 0: continue
            sl_dist = abs(entry_price - pos.sl)
            
            current_profit_points = abs(current_price - entry_price)
            current_rr = current_profit_points / sl_dist
            
            # 1. Partial Close & Break Even (when RR 3 hit)
            # Use comment or volume to check if already partially closed
            if current_rr >= self.tp1_rr and "Partial" not in pos.comment:
                print(f"[{datetime.now()}] RR 1:3 Hit for {pos.ticket}. Executing Partial Close (50%) & BE...")
                
                # Close 50%
                partial_vol = pos.volume / 2.0
                symbol_info = mt5.symbol_info(self.symbol)
                step = symbol_info.volume_step
                partial_vol = round(partial_vol / step) * step
                partial_vol = max(partial_vol, symbol_info.volume_min)
                
                close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
                
                request_close = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": self.symbol,
                    "volume": partial_vol,
                    "type": close_type,
                    "position": pos.ticket,
                    "price": current_price,
                    "magic": self.magic_number,
                    "comment": "Partial RR3",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }
                res_close = mt5.order_send(request_close)
                if res_close.retcode != mt5.TRADE_RETCODE_DONE:
                    print(f"Partial close failed: {res_close.comment}")
                
                # Move SL to Entry (Break Even)
                request_be = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "symbol": self.symbol,
                    "position": pos.ticket,
                    "sl": entry_price,
                    "tp": pos.tp,
                }
                res_be = mt5.order_send(request_be)
                if res_be.retcode != mt5.TRADE_RETCODE_DONE:
                    print(f"BE Move failed: {res_be.comment}")

    def cancel_all_pendings(self):
        orders = mt5.orders_get(symbol=self.symbol, magic=self.magic_number)
        if orders:
            for order in orders:
                mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": order.ticket})

    def close_all_positions(self):
        positions = mt5.positions_get(symbol=self.symbol, magic=self.magic_number)
        if positions:
            for pos in positions:
                close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
                tick = mt5.symbol_info_tick(self.symbol)
                price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": self.symbol,
                    "position": pos.ticket,
                    "volume": pos.volume,
                    "type": close_type,
                    "price": price,
                    "magic": self.magic_number,
                    "comment": "Force Close",
                }
                mt5.order_send(request)

    def run_strategy(self):
        now = datetime.now()
        
        # 0. Check Weekdays
        if now.weekday() not in self.allowed_weekdays:
            return

        # 1. Force Close at Midnight
        if now.hour == self.close_hour and now.minute == 0:
            print(f"[{now}] Midnight Force Close.")
            self.cancel_all_pendings()
            self.close_all_positions()
            return

        # 2. Daily Setup at 12:00
        if now.hour == self.start_hour and now.minute == 0:
            print(f"[{now}] Running Daily Setup v3 Advanced...")
            self.cancel_all_pendings()
            
            # Fetch data from 9:00 to now
            today_9am = now.replace(hour=9, minute=0, second=0, microsecond=0)
            rates = mt5.copy_rates_range(self.symbol, self.timeframe, today_9am, now)
            if rates is None or len(rates) < 2: return
            
            df = pd.DataFrame(rates)
            high_price = df['high'].max()
            low_price = df['low'].min()
            high_time = df.loc[df['high'].idxmax(), 'time']
            low_time = df.loc[df['low'].idxmin(), 'time']
            price_range = high_price - low_price
            
            if price_range <= 0: return

            balance, _ = self.get_account_status()
            risk = self.get_drawdown_risk(balance)
            lot = self.get_lot_size(risk, self.sl_points)
            
            sl_dist = self.sl_points * 0.00001
            tp2_dist = (self.sl_points * self.tp2_rr) * 0.00001
            
            current_tick = mt5.symbol_info_tick(self.symbol)
            if not current_tick: return

            if low_time < high_time: # BUY SETUP
                for fibo in self.fibo_levels:
                    entry = round(high_price - (price_range * fibo), 5)
                    # Simple filter: don't place buy limit if price already far below
                    if current_tick.ask > entry:
                        self.place_limit("BUY", entry, entry - sl_dist, entry + tp2_dist, lot, fibo)
            elif high_time < low_time: # SELL SETUP
                for fibo in self.fibo_levels:
                    entry = round(low_price + (price_range * fibo), 5)
                    if current_tick.bid < entry:
                        self.place_limit("SELL", entry, entry + sl_dist, entry - tp2_dist, lot, fibo)
            
            # Prevent multiple executions in the same minute
            import time as sleep_module
            sleep_module.sleep(60)

        # 3. Active Management (Always monitor for Partial/BE)
        self.manage_orders()

    def place_limit(self, direction, entry, sl, tp, lot, fibo):
        order_type = mt5.ORDER_TYPE_BUY_LIMIT if direction == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT
        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": self.symbol,
            "volume": lot,
            "type": order_type,
            "price": entry,
            "sl": sl,
            "tp": tp,
            "magic": self.magic_number,
            "comment": f"v3 Adv {fibo}",
            "type_time": mt5.ORDER_TIME_DAY,
        }
        result = mt5.order_send(request)
        print(f"{direction} Limit at {entry} (Fibo {fibo}) sent: {result.comment}")

if __name__ == "__main__":
    strategy = AdvancedSafetyStrategyV3()
    print(f"--- Advanced Safety v3.0 Started Monitoring ({strategy.symbol}) ---")
    import time as sleep_module
    while True:
        try:
            strategy.run_strategy()
            sleep_module.sleep(30) # Monitor every 30 seconds
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Loop Error: {e}")
            sleep_module.sleep(10)
    mt5.shutdown()
