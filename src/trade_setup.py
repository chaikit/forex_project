import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta

class LondonNYReversalStrategy:
    def __init__(self, symbol="EURUSD", timeframe=mt5.TIMEFRAME_M30, risk_percent=1.0, initial_balance=1000.0):
        """
        Initialize Strategy Configuration
        """
        self.symbol = symbol
        self.timeframe = timeframe
        self.risk_percent = risk_percent
        self.simulated_balance = initial_balance
        self.magic_number = 123456
        
        # Fibonacci Settings
        self.fibo_levels = [0.618, 0.786]
        
        # Time Settings
        self.start_hour = 13    # เวลาเริ่มวางแผนเทรด 6 โมงเย็น
        self.close_hour = 24     # เวลาปิดออเดอร์ทั้งหมด ตี 5
        
        # Connection Check
        if not mt5.initialize():
            print("initialize() failed, error code =", mt5.last_error())
            quit()

    def get_server_time(self):
        """ดึงเวลาปัจจุบันของ Server MT5"""
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            return datetime.now() # Fallback case
        return datetime.fromtimestamp(tick.time)

    def calculate_atr(self, df, period=14):
        """คำนวณ ATR แบบ Manual"""
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        atr = true_range.rolling(period).mean()
        return atr.iloc[-1]

    def get_lot_size(self, sl_points):
        """คำนวณ Lot Size ตามความเสี่ยง 1% (Fixed Balance $1000)"""
        balance = 1000.0 # Fixed ตามโจทย์
        risk_amount = balance * (self.risk_percent / 100)
        
        symbol_info = mt5.symbol_info(self.symbol)
        if symbol_info is None: return 0.01
            
        tick_value = symbol_info.trade_tick_value
        if sl_points == 0 or tick_value == 0: return 0.01

        lot_size = risk_amount / (sl_points * tick_value)
        
        # Normalize Lot Size
        step = symbol_info.volume_step
        lot_size = round(lot_size / step) * step
        return max(lot_size, symbol_info.volume_min)

    def cancel_pending_orders(self):
        """ยกเลิก Pending Order (Limit) ทั้งหมด"""
        orders = mt5.orders_get(symbol=self.symbol, magic=self.magic_number)
        if orders:
            for order in orders:
                request = {
                    "action": mt5.TRADE_ACTION_REMOVE,
                    "order": order.ticket,
                    "magic": self.magic_number,
                }
                mt5.order_send(request)
            print(f"Cancelled {len(orders)} pending orders.")

    def close_all_positions(self):
        """ปิด Position (ไม้ที่ Match แล้ว) ทั้งหมดทันที"""
        positions = mt5.positions_get(symbol=self.symbol, magic=self.magic_number)
        if positions:
            for pos in positions:
                # Determine close type (Opposite direction)
                if pos.type == mt5.ORDER_TYPE_BUY:
                    action_type = mt5.ORDER_TYPE_SELL
                    price = mt5.symbol_info_tick(self.symbol).bid
                else:
                    action_type = mt5.ORDER_TYPE_BUY
                    price = mt5.symbol_info_tick(self.symbol).ask
                
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": self.symbol,
                    "position": pos.ticket,
                    "volume": pos.volume,
                    "type": action_type,
                    "price": price,
                    "magic": self.magic_number,
                    "comment": "Time 0:00 Close",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }
                result = mt5.order_send(request)
                if result.retcode != mt5.TRADE_RETCODE_DONE:
                    print(f"Failed to close position {pos.ticket}: {result.comment}")
                else:
                    print(f"Position {pos.ticket} Closed at {price}")

    def run_strategy(self):
        """
        Main Loop: ควรถูกเรียกทำงานสม่ำเสมอ (เช่น ทุกนาที หรือทุก Tick)
        """
        server_time = self.get_server_time()
        
        # ==========================================
        # LOGIC 1: TIME 0:00 -> FORCE CLOSE
        # ==========================================

        if server_time.hour == self.close_hour and server_time.minute == 0:
            # เพื่อป้องกันการยิงรัวๆ อาจจะต้องมี Flag หรือ check ว่ามี order เหลือไหม
            if mt5.positions_get(symbol=self.symbol, magic=self.magic_number) or \
               mt5.orders_get(symbol=self.symbol, magic=self.magic_number):
                print(f"[{server_time}] Time 0:00 Reached. Force Closing All...")
                self.cancel_pending_orders()
                self.close_all_positions()
            return # จบการทำงานรอบนี้

        # ==========================================
        # LOGIC 2: TIME 20:00 -> START STRATEGY
        # ==========================================
        if server_time.hour != self.start_hour or server_time.minute != 0:
            return

        print(f"--- Strategy Execution Started at {server_time} ---")

        # เคลียร์ Pending Order เก่าก่อนเริ่มวันใหม่ (Position เก่าปล่อยรัน หรือแล้วแต่นโยบาย)
        self.cancel_pending_orders()
        
        # 1. Fetch Data
        today_start = server_time.replace(hour=9, minute=0, second=0, microsecond=0)
        rates = mt5.copy_rates_range(self.symbol, self.timeframe, today_start, server_time)
        
        if rates is None or len(rates) == 0:
            print("No data fetched")
            return

        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        
        # 2. Identify Swing High / Low
        max_idx = df['high'].idxmax()
        min_idx = df['low'].idxmin()
        high_price = df.loc[max_idx, 'high']
        high_time = df.loc[max_idx, 'time']
        low_price = df.loc[min_idx, 'low']
        low_time = df.loc[min_idx, 'time']
        
        current_tick = mt5.symbol_info_tick(self.symbol)
        
        # 3. Calculate ATR & Distances
        atr_val = self.calculate_atr(df, period=14)
        #distance_points = atr_val * 100000
        distance_points = 200
        distance_price = distance_points * 0.00001
        
        print(f"High: {high_price} ({high_time}), Low: {low_price} ({low_time})")

        price_range = high_price - low_price

        # 4. Determine Logic
        if low_time < high_time: # BUY SETUP
            for fibo in self.fibo_levels:
                entry_price = round(high_price - (price_range * fibo), 5)
                
                if current_tick.ask < entry_price: continue # Skip if price passed
                
                self.send_order("BUY", entry_price, distance_price, distance_points, fibo)

        elif high_time < low_time: # SELL SETUP
            for fibo in self.fibo_levels:
                entry_price = round(low_price + (price_range * fibo), 5)
                
                if current_tick.bid > entry_price: continue # Skip if price passed
                
                self.send_order("SELL", entry_price, distance_price, distance_points, fibo)

    def send_order(self, direction, entry_price, dist_price, dist_points, fibo_level):
        """Helper function เพื่อลด Code ซ้ำซ้อน"""
        lot_size = self.get_lot_size(dist_points)
        
        if direction == "BUY":
            order_type = mt5.ORDER_TYPE_BUY_LIMIT
            sl = entry_price - (dist_price * 0.3)
            tp = entry_price + (dist_price * 1.2)
        else:
            order_type = mt5.ORDER_TYPE_SELL_LIMIT
            sl = entry_price + (dist_price * 0.3)
            tp = entry_price - (dist_price * 1.2)

        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": self.symbol,
            "volume": lot_size,
            "type": order_type,
            "price": entry_price,
            "sl": sl,
            "tp": tp,
            "magic": self.magic_number,
            "comment": f"Fibo {fibo_level} {direction}",
            "type_time": mt5.ORDER_TIME_DAY,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }
        
        result = mt5.order_send(request)
        print(f"{direction} Limit Fibo {fibo_level}: {result.comment}")

# ==========================================
# Execution Hook
# ==========================================
if __name__ == "__main__":
    strategy = LondonNYReversalStrategy()
    strategy.run_strategy()