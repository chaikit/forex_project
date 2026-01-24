import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta
import os
import json

class HolyGrailStrategyV4:
    def __init__(self, symbol="EURUSD", timeframe=mt5.TIMEFRAME_M30):
        """
        Initialize the Ultimate Safety Strategy (v4.0)
        Logic: Dual Fibo + Half-Risk on -5%DD + Partial Close at RR 3 + Break Even
        """
        self.symbol = symbol
        self.timeframe = timeframe
        self.magic_number = 444444
        self.initial_balance = 1000.0
        
        # Core Strategy Parameters (From the best backtest)
        self.start_hour = 12       # เวลาวางแผนเทรด (Server Time)
        self.close_hour = 0        # เวลา Force Close (Midnight)
        self.fibo_levels = [0.618, 0.786]
        self.sl_points = 15        # Fixed SL for Scaling v3 logic
        self.tp1_rr = 3.0          # Partial Close & BE point
        self.tp2_rr = 6.0          # Final TP point
        
        # Risk Settings
        self.standard_risk = 1.0   # 1% standard
        self.dd_threshold = -0.05  # -5% Drawdown limit
        
        # Initialize MT5
        if not mt5.initialize():
            print(f"MT5 Initialization failed: {mt5.last_error()}")
            quit()

    def get_account_status(self):
        """ดึงข้อมูล Account เพื่อคำนวณ Drawdown และ Risk"""
        acc_info = mt5.account_info()
        if acc_info is None: return 1000.0, 1000.0
        
        # ในระบบโปรดักชั่น เราควรอ้างอิงจาก Equity High ที่เราบันทึกไว้เอง
        # หรือใช้ Balance ปัจจุบันเทียบกับทุนเริ่มต้น (กรณีเริ่มต้นบัญชีใหม่)
        return acc_info.balance, acc_info.equity

    def get_drawdown_risk(self, current_balance):
        """คำนวณความเสี่ยงตามระบบ Half-Risk on Drawdown"""
        # หมายเหตุ: ในการใช้งานจริง ควรมีฐานข้อมูลหรือไฟล์บันทึก Max Balance แยกต่างหาก
        # ในตัวอย่างนี้ขออ้างอิงจากทุนเริ่มต้น $1000 เพื่อความง่าย
        max_balance = self.initial_balance 
        
        # หากยอดเงินปัจจุบันขยับขึ้นไปเป็น New High ให้จำค่าใหม่
        # (ในการรันจริง ควรบันทึกค่านี้ลงไฟล์เพื่อเก็บสถานะระหว่างวัน)
        # current_drawdown = (current_balance - max_balance) / max_balance
        
        # สำหรับตัวอย่างนี้ เราจะใช้ความเสี่ยง 1% เป็นมาตรฐาน
        # หากพอร์ตติดลบเกิน 5% (-0.05) ให้ลดเหลือ 0.5%
        if current_balance < (max_balance * 0.95):
            return 0.5
        return 1.0

    def get_lot_size(self, risk_percent, sl_points):
        """คำนวณ Lot Size ตาม Risk % และ SL"""
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
        """
        หัวใจของการคุมไม้ที่ Match แล้ว (Partial Close & Break Even)
        ควรเรียกฟังก์ชันนี้ทุกครั้งที่มี Tick ใหม่
        """
        positions = mt5.positions_get(symbol=self.symbol, magic=self.magic_number)
        if not positions: return

        for pos in positions:
            entry_price = pos.price_open
            current_price = mt5.symbol_info_tick(self.symbol).bid if pos.type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(self.symbol).ask
            
            # คำนวณระยะ SL เดิม
            sl_dist = abs(entry_price - pos.sl)
            if sl_dist == 0: continue
            
            current_profit_points = abs(current_price - entry_price)
            current_rr = current_profit_points / sl_dist
            
            # 1. เงื่อนไข Partial Close & Break Even (เมื่อถึง RR 3)
            # เราจะเช็คจาก Comment เพื่อดูว่าเคย Partial ไปหรือยัง (หรือเช็คจาก Volume ที่ลดลง)
            if current_rr >= self.tp1_rr and "Partial" not in pos.comment:
                print(f"[{datetime.now()}] RR 1:3 Reached for {pos.ticket}. Executing Partial Close & BE...")
                
                # Close 50%
                partial_vol = pos.volume / 2.0
                step = mt5.symbol_info(self.symbol).volume_step
                partial_vol = round(partial_vol / step) * step
                
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
                mt5.order_send(request_close)
                
                # Move SL to Entry (Break Even)
                request_be = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "symbol": self.symbol,
                    "position": pos.ticket,
                    "sl": entry_price, # เลื่อนไปที่หน้าทุน
                    "tp": pos.tp,
                }
                mt5.order_send(request_be)

    def cancel_all_pendings(self):
        """ยกเลิก Pending Order ทั้งหมด"""
        orders = mt5.orders_get(symbol=self.symbol, magic=self.magic_number)
        if orders:
            for order in orders:
                mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": order.ticket})

    def close_all_positions(self):
        """ปิดออเดอร์ที่ค้างอยู่ทั้งหมด (ใช้ตอนเลิกงานเที่ยงคืน)"""
        positions = mt5.positions_get(symbol=self.symbol, magic=self.magic_number)
        if positions:
            for pos in positions:
                close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
                price = mt5.symbol_info_tick(self.symbol).bid if pos.type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(self.symbol).ask
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": self.symbol,
                    "position": pos.ticket,
                    "volume": pos.volume,
                    "type": close_type,
                    "price": price,
                    "magic": self.magic_number,
                    "comment": "Admin Force Close",
                }
                mt5.order_send(request)

    def run_daily_setup(self):
        """วางแผนเทรดประจำวันตอนเวลา 12:00"""
        now = datetime.now()
        
        # 1. Force Close ตอนเที่ยงคืน
        if now.hour == self.close_hour and now.minute == 0:
            print(f"[{now}] Midnight Reached. Closing everything.")
            self.cancel_all_pendings()
            self.close_all_positions()
            return

        # 2. ทำงานเฉพาะเวลา 12:00
        if now.hour != self.start_hour or now.minute != 0:
            # ระหว่างวัน ให้คอยดูลูกไม้ (Partial/BE)
            self.manage_orders()
            return

        print(f"[{now}] --- Starting Daily Setup v4 (Holy Grail) ---")
        self.cancel_all_pendings()
        
        today_start = now.replace(hour=9, minute=0, second=0)
        rates = mt5.copy_rates_range(self.symbol, self.timeframe, today_start, now)
        if rates is None or len(rates) < 2: return
        
        df = pd.DataFrame(rates)
        high_price = df['high'].max()
        low_price = df['low'].min()
        high_time = df.loc[df['high'].idxmax(), 'time']
        low_time = df.loc[df['low'].idxmin(), 'time']
        price_range = high_price - low_price
        
        # Determine current Risk based on Drawdown
        balance, _ = self.get_account_status()
        risk_to_use = self.get_drawdown_risk(balance)
        lot = self.get_lot_size(risk_to_use, self.sl_points)
        
        sl_dist = self.sl_points * 0.00001
        tp2_dist = (self.sl_points * self.tp2_rr) * 0.00001
        
        if low_time < high_time: # BUY SETUP
            for fibo in self.fibo_levels:
                entry = round(high_price - (price_range * fibo), 5)
                self.place_limit("BUY", entry, entry - sl_dist, entry + tp2_dist, lot, fibo)
        elif high_time < low_time: # SELL SETUP
            for fibo in self.fibo_levels:
                entry = round(low_price + (price_range * fibo), 5)
                self.place_limit("SELL", entry, entry + sl_dist, entry - tp2_dist, lot, fibo)

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
            "comment": f"v4 Dual {fibo}",
            "type_time": mt5.ORDER_TIME_DAY,
        }
        result = mt5.order_send(request)
        print(f"{direction} Limit at {entry} (Fibo {fibo}): {result.comment}")

if __name__ == "__main__":
    strategy = HolyGrailStrategyV4()
    print("Holy Grail v4.0 is running... Monitoring MT5 Loop.")
    import time as sleep_module
    while True:
        try:
            strategy.run_daily_setup()
            sleep_module.sleep(30) # เช็คทุก 30 วินาที
        except KeyboardInterrupt:
            print("Stopping...")
            break
        except Exception as e:
            print(f"Error in main loop: {e}")
            sleep_module.sleep(10)
    mt5.shutdown()
