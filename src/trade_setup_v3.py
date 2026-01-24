import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta

class LondonNYReversalStrategyV3:
    def __init__(self, symbol="EURUSD", timeframe=mt5.TIMEFRAME_M30, risk_percent=1.0, initial_balance=1000.0):
        """
        Strategy v3.0: Fixed 50 Pt SL, RR 1:4, 12:00 Start, No Thursdays
        """
        self.symbol = symbol
        self.timeframe = timeframe
        self.risk_percent = risk_percent
        self.base_balance = initial_balance
        self.magic_number = 123456
        
        # Strategy Settings
        self.fibo_levels = [0.618, 0.786]
        self.start_hour = 12
        self.close_hour = 24 # 0:00 Next Day
        
        # Fixed Distances (Points) based on high-profit backtest (Distance 50)
        self.sl_points = 15
        self.tp_points = 60 # RR 1:4

        if not mt5.initialize():
            print(f"MT5 Initialization failed: {mt5.last_error()}")
            quit()

    def get_server_time(self):
        tick = mt5.symbol_info_tick(self.symbol)
        return datetime.fromtimestamp(tick.time) if tick else datetime.now()

    def get_lot_size(self, sl_points):
        risk_amount = self.base_balance * (self.risk_percent / 100)
        symbol_info = mt5.symbol_info(self.symbol)
        if not symbol_info: return 0.01
        
        tick_value = symbol_info.trade_tick_value
        if sl_points == 0 or tick_value == 0: return 0.01

        lot_size = risk_amount / (sl_points * tick_value)
        step = symbol_info.volume_step
        lot_size = round(lot_size / step) * step
        return max(lot_size, symbol_info.volume_min)

    def cancel_pending_orders(self):
        orders = mt5.orders_get(symbol=self.symbol, magic=self.magic_number)
        if orders:
            for order in orders:
                mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": order.ticket})
            print(f"Cancelled {len(orders)} pending orders.")

    def close_all_positions(self):
        positions = mt5.positions_get(symbol=self.symbol, magic=self.magic_number)
        if positions:
            for pos in positions:
                tick = mt5.symbol_info_tick(self.symbol)
                action = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
                price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
                
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": self.symbol,
                    "position": pos.ticket,
                    "volume": pos.volume,
                    "type": action,
                    "price": price,
                    "magic": self.magic_number,
                    "comment": "Time 0:00 Close",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }
                mt5.order_send(request)
            print(f"Closed {len(positions)} positions.")

    def run_strategy(self):
        server_time = self.get_server_time()
        
        # 1. Day Check (Exclude Thursday = 3)
        if server_time.weekday() == 3:
            return

        # 2. 0:00 Force Close
        if server_time.hour == 0 and server_time.minute == 0:
            self.cancel_pending_orders()
            self.close_all_positions()
            return

        # 3. Strategy Start Time (12:00)
        if server_time.hour != self.start_hour or server_time.minute != 0:
            return

        print(f"--- Strategy v3.0 Started at {server_time} ---")
        self.cancel_pending_orders()
        
        today_9am = server_time.replace(hour=9, minute=0, second=0, microsecond=0)
        rates = mt5.copy_rates_range(self.symbol, self.timeframe, today_9am, server_time)
        if rates is None or len(rates) == 0: return

        df = pd.DataFrame(rates)
        high_price = df['high'].max()
        low_price = df['low'].min()
        high_time = df.loc[df['high'].idxmax(), 'time']
        low_time = df.loc[df['low'].idxmin(), 'time']
        price_range = high_price - low_price
        
        current_tick = mt5.symbol_info_tick(self.symbol)
        distance_price_sl = self.sl_points * 0.00001
        distance_price_tp = self.tp_points * 0.00001
        lot_size = self.get_lot_size(self.sl_points)

        if low_time < high_time: # BUY SETUP
            for fibo in self.fibo_levels:
                entry = round(high_price - (price_range * fibo), 5)
                if current_tick.ask < entry: continue
                self.place_limit(mt5.ORDER_TYPE_BUY_LIMIT, entry, entry - distance_price_sl, entry + distance_price_tp, lot_size, fibo)
        
        elif high_time < low_time: # SELL SETUP
            for fibo in self.fibo_levels:
                entry = round(low_price + (price_range * fibo), 5)
                if current_tick.bid > entry: continue
                self.place_limit(mt5.ORDER_TYPE_SELL_LIMIT, entry, entry + distance_price_sl, entry - distance_price_tp, lot_size, fibo)

    def place_limit(self, order_type, price, sl, tp, volume, fibo):
        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": self.symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "magic": self.magic_number,
            "comment": f"v3.0 Fibo {fibo}",
            "type_time": mt5.ORDER_TIME_DAY,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }
        res = mt5.order_send(request)
        print(f"Order {order_type} Fibo {fibo} sent: {res.comment}")

if __name__ == "__main__":
    strategy = LondonNYReversalStrategyV3()
    strategy.run_strategy()
