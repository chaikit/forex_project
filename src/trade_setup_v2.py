import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta

class LondonNYReversalStrategy:
    def __init__(self, symbol="EURUSD", timeframe=mt5.TIMEFRAME_M30, risk_percent=1.0, initial_balance=1000.0):
        """
        Initialize Strategy Configuration with ADX Filter
        """
        self.symbol = symbol
        self.timeframe = timeframe
        self.risk_percent = risk_percent
        self.simulated_balance = initial_balance
        self.magic_number = 123456
        
        # Fibonacci Settings
        self.fibo_levels = [0.618, 0.786]
        
        # Time Settings
        self.start_hour = 13    # เวลาเริ่มวางแผนเทรด 6 โมงเย็น (MT5 Server Time)
        self.close_hour = 24     # เวลาปิดออเดอร์ทั้งหมด ตี 5 (MT5 Server Time)
        
        # Filter Settings
        self.adx_threshold = 15.0
        
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

    def calculate_adx(self, df, period=14):
        """คำนวณ ADX โดยใช้ Wilder's Smoothing"""
        if len(df) < period * 2:
            return None
            
        sub_df = df.copy()
        sub_df['up_move'] = sub_df['high'] - sub_df['high'].shift(1)
        sub_df['down_move'] = sub_df['low'].shift(1) - sub_df['low']
        
        sub_df['plus_dm'] = np.where((sub_df['up_move'] > sub_df['down_move']) & (sub_df['up_move'] > 0), sub_df['up_move'], 0)
        sub_df['minus_dm'] = np.where((sub_df['down_move'] > sub_df['up_move']) & (sub_df['down_move'] > 0), sub_df['down_move'], 0)
        
        high_low = sub_df['high'] - sub_df['low']
        high_close = np.abs(sub_df['high'] - sub_df['close'].shift())
        low_close = np.abs(sub_df['low'] - sub_df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        sub_df['tr'] = np.max(ranges, axis=1)
        
        def wilders_smoothing(data, n):
            smooth = np.zeros(len(data))
            first_idx = data.first_valid_index() + n
            if first_idx >= len(data): return smooth
            
            smooth[first_idx] = data.iloc[first_idx-n+1:first_idx+1].mean()
            for i in range(first_idx + 1, len(data)):
                smooth[i] = (smooth[i-1] * (n - 1) + data.iloc[i]) / n
            return smooth

        sub_df['atr_smooth'] = wilders_smoothing(sub_df['tr'], period)
        plus_di_raw = 100 * wilders_smoothing(sub_df['plus_dm'], period) / sub_df['atr_smooth']
        minus_di_raw = 100 * wilders_smoothing(sub_df['minus_dm'], period) / sub_df['atr_smooth']
        
        sub_df['dx'] = 100 * np.abs(plus_di_raw - minus_di_raw) / (plus_di_raw + minus_di_raw)
        adx_values = wilders_smoothing(sub_df['dx'], period)
        return adx_values[-1]

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
        Main Loop with ADX Filter
        """
        server_time = self.get_server_time()
        
        # 0:00 Force Close
        if server_time.hour == self.close_hour and server_time.minute == 0:
            if mt5.positions_get(symbol=self.symbol, magic=self.magic_number) or \
               mt5.orders_get(symbol=self.symbol, magic=self.magic_number):
                print(f"[{server_time}] Time 0:00 Reached. Force Closing All...")
                self.cancel_pending_orders()
                self.close_all_positions()
            return

        # Start Strategy Logic
        if server_time.hour != self.start_hour or server_time.minute != 0:
            return

        print(f"--- Strategy Execution Started at {server_time} (with ADX Filter) ---")
        self.cancel_pending_orders()
        
        # 1. Fetch Data (Extended for ADX smoothing)
        # Fetching approx 24 hours of data to ensure enough bars for 14-period ADX smoothing
        lookback_start = server_time - timedelta(hours=24)
        rates = mt5.copy_rates_range(self.symbol, self.timeframe, lookback_start, server_time)
        
        if rates is None or len(rates) < 30:
            print("Insufficient data fetched for calculation")
            return

        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        
        # 2. Calculate Indicators
        adx_val = self.calculate_adx(df)
        atr_val = self.calculate_atr(df)
        
        if adx_val is None:
            print("ADX Calculation failed")
            return

        print(f"Market Sentiment -> ADX: {adx_val:.2f}, ATR: {atr_val:.5f}")

        # 3. ADX Filter Check
        if adx_val < self.adx_threshold:
            print(f"Strategy Filtered: ADX {adx_val:.2f} is below threshold {self.adx_threshold}. Skipping today.")
            return

        # 4. Identify Swing High / Low (Specific to 9:00 - 13:00 window)
        strategy_range_data = df[(df['time'].dt.hour >= 9) & (df['time'].dt.hour < self.start_hour)]
        if strategy_range_data.empty:
            print("No data in strategy time window (9:00-13:00)")
            return

        max_idx = strategy_range_data['high'].idxmax()
        min_idx = strategy_range_data['low'].idxmin()
        high_price = strategy_range_data.loc[max_idx, 'high']
        high_time = strategy_range_data.loc[max_idx, 'time']
        low_price = strategy_range_data.loc[min_idx, 'low']
        low_time = strategy_range_data.loc[min_idx, 'time']
        
        current_tick = mt5.symbol_info_tick(self.symbol)
        distance_points = 200
        distance_price = distance_points * 0.00001
        
        print(f"High: {high_price} ({high_time}), Low: {low_price} ({low_time})")
        price_range = high_price - low_price

        # 5. Place Orders
        if low_time < high_time: # BUY SETUP
            for fibo in self.fibo_levels:
                entry_price = round(high_price - (price_range * fibo), 5)
                if current_tick.ask < entry_price: continue 
                self.send_order("BUY", entry_price, distance_price, distance_points, fibo)

        elif high_time < low_time: # SELL SETUP
            for fibo in self.fibo_levels:
                entry_price = round(low_price + (price_range * fibo), 5)
                if current_tick.bid > entry_price: continue 
                self.send_order("SELL", entry_price, distance_price, distance_points, fibo)

    def send_order(self, direction, entry_price, dist_price, dist_points, fibo_level):
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
            "comment": f"Fibo {fibo_level} {direction} (ADX Filtered)",
            "type_time": mt5.ORDER_TIME_DAY,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }
        result = mt5.order_send(request)
        print(f"{direction} Limit Fibo {fibo_level}: {result.comment}")

if __name__ == "__main__":
    strategy = LondonNYReversalStrategy()
    strategy.run_strategy()
