import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta
import os
import shutil
from src.log_processor import LogProcessor

# Custom Backtester with Reverse EMA 200 Filter (4-Year Period)
# Mean Reversion: Buy only if Price < EMA 200 | Sell only if Price > EMA 200
class BacktesterV3_4YearsEMAReverse:
    def __init__(self, symbol="EURUSD", initial_balance=1000.0, risk_percent=1.0):
        self.symbol = symbol
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.risk_percent = risk_percent
        self.trades = []
        self.magic_number = 123456
        self.fibo_levels = [0.618, 0.786]
        self.start_hour = 12
        self.close_hour = 0
        
        self.sl_points = 15
        self.tp_points = 90 # RR 1:6
        self.rr_ratio = 6.0

        if not mt5.initialize():
            print("MT5 Initialization failed", flush=True)
            quit()

    def get_data(self, start_date):
        print(f"Fetching M30 data for {self.symbol} from {start_date}...", flush=True)
        # Fetch extra data (around 20 days) to calculate EMA correctly
        from_date = start_date - timedelta(days=20) 
        utc_to = datetime.now()
        rates = mt5.copy_rates_range(self.symbol, mt5.TIMEFRAME_M30, from_date, utc_to)
        if rates is None: 
            print(f"Failed to get rates: {mt5.last_error()}", flush=True)
            return None
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        
        # Calculate EMA 200
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
        
        # Filter back to actual requested start date for trading
        df = df[df['time'] >= start_date].copy().reset_index(drop=True)
        return df

    def run(self, df, allowed_weekdays=None):
        if df is None or len(df) == 0: return

        df['date'] = df['time'].dt.date
        days = df['date'].unique()
        
        sl_price_dist = self.sl_points * 0.00001
        tp_price_dist = self.tp_points * 0.00001

        for date in days:
            if allowed_weekdays is not None and date.weekday() not in allowed_weekdays:
                continue

            day_data = df[df['date'] == date].copy()
            if len(day_data) < 5: continue

            range_data = day_data[(day_data['time'].dt.hour >= 9) & (day_data['time'].dt.hour < self.start_hour)]
            if range_data.empty: continue

            high_idx = range_data['high'].idxmax()
            low_idx = range_data['low'].idxmin()
            high_price = range_data.loc[high_idx, 'high']
            low_price = range_data.loc[low_idx, 'low']
            high_time = range_data.loc[high_idx, 'time']
            low_time = range_data.loc[low_idx, 'time']
            price_range = high_price - low_price
            if price_range == 0: continue

            start_search_idx = range_data.index[-1] + 1
            if start_search_idx >= len(df): continue
            
            force_close_time = datetime.combine(date + timedelta(days=1), time(0, 0))
            
            if low_time < high_time: # BUY SETUP
                for fibo in self.fibo_levels:
                    entry = round(high_price - (price_range * fibo), 5)
                    self.simulate_trade(df, start_search_idx, "BUY", entry, entry - sl_price_dist, entry + tp_price_dist, force_close_time, fibo)
            elif high_time < low_time: # SELL SETUP
                for fibo in self.fibo_levels:
                    entry = round(low_price + (price_range * fibo), 5)
                    self.simulate_trade(df, start_search_idx, "SELL", entry, entry + sl_price_dist, entry - tp_price_dist, force_close_time, fibo)

    def simulate_trade(self, df, start_idx, side, entry, sl, tp, force_close, fibo):
        future_df = df.iloc[start_idx:]
        for idx_rel, row in enumerate(future_df.itertuples()):
            if row.time >= force_close: return False
            
            # Entry condition
            if (side == "BUY" and row.low <= entry) or (side == "SELL" and row.high >= entry):
                entry_time = row.time
                ema_val = row.ema200
                
                # REVERSE EMA FILTER Logic: Buy < EMA, Sell > EMA
                if (side == "BUY" and entry > ema_val) or (side == "SELL" and entry < ema_val):
                    return False 
                
                search_idx_start = start_idx + idx_rel + 1
                if search_idx_start >= len(df): return True 
                
                for t_row in df.iloc[search_idx_start:].itertuples():
                    if t_row.time >= force_close:
                        pf = (t_row.open - entry) / (entry - sl) if side == "BUY" else (entry - t_row.open) / (sl - entry)
                        self.record_trade(entry_time, t_row.time, side, f"v3.0 EMA Reverse RR1:6", entry, t_row.open, pf, "Force Close")
                        return True
                    
                    if (side == "BUY" and t_row.low <= sl) or (side == "SELL" and t_row.high >= sl):
                        self.record_trade(entry_time, t_row.time, side, f"v3.0 EMA Reverse RR1:6", entry, sl, -1.0, "SL")
                        return True
                        
                    if (side == "BUY" and t_row.high >= tp) or (side == "SELL" and t_row.low <= tp):
                        self.record_trade(entry_time, t_row.time, side, f"v3.0 EMA Reverse RR1:6", entry, tp, self.rr_ratio, "TP")
                        return True
                return True
        return False

    def record_trade(self, entry_time, exit_time, side, setup, entry, exit, pf, comment):
        risk = self.balance * (self.risk_percent / 100)
        profit = risk * pf
        self.balance += profit
        self.trades.append({
            "entry_time": entry_time, "exit_time": exit_time,
            "type": side, "setup": setup, "entry": entry, "exit": exit,
            "profit": profit, "balance": self.balance, "comment": comment,
            "atr": 0, "adx": 0
        })

    def shutdown(self): mt5.shutdown()

if __name__ == "__main__":
    tester = BacktesterV3_4YearsEMAReverse()
    start_date = datetime(2022, 1, 24)
    data = tester.get_data(start_date)
    
    if data is not None:
        tester.run(data, allowed_weekdays=[0, 1, 2, 4])
        print(f"\nFinal Balance: ${tester.balance:.2f}")
        print(f"Total Trades: {len(tester.trades)}")
        
        suffix = "4y_v3_RR6_EMA_Reverse"
        if not os.path.exists("reports"): os.makedirs("reports")
        
        logger = LogProcessor(tester.trades, start_hour=12, close_hour=0, tp_multiplier=6.0)
        logger.export_to_csv(f"backtest_results_{suffix}.csv")
        logger.create_performance_graph(f"performance_{suffix}.png")
        logger.generate_summary_report()
        
    tester.shutdown()
