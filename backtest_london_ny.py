import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta
import os
from src.log_processor import LogProcessor

class LondonNYBacktester:
    def __init__(self, symbol="EURUSD", initial_balance=1000.0, risk_percent=1.0):
        self.symbol = symbol
        self.balance = initial_balance
        self.risk_percent = risk_percent
        self.trades = []
        self.magic_number = 123456
        self.fibo_levels = [0.618, 0.786]
        
        if not mt5.initialize():
            print("MT5 Initialization failed", flush=True)
            quit()

    def get_data(self, start_date):
        print(f"Fetching M30 data for {self.symbol} from {start_date}...", flush=True)
        utc_from = start_date
        utc_to = datetime.now()
        rates = mt5.copy_rates_range(self.symbol, mt5.TIMEFRAME_M30, utc_from, utc_to)
        if rates is None:
            print("Failed to get rates", flush=True)
            return None
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        return df

    def calculate_atr(self, df, current_idx, period=14):
        if current_idx < period:
            return None
        sub_df = df.iloc[current_idx-period+1:current_idx+1]
        high_low = sub_df['high'] - sub_df['low']
        high_close = np.abs(sub_df['high'] - sub_df['close'].shift())
        low_close = np.abs(sub_df['low'] - sub_df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        return true_range.mean()

    def run(self, df):
        if df is None or len(df) == 0:
            return

        df['date'] = df['time'].dt.date
        days = df['date'].unique()

        for d_idx, date in enumerate(days):
            day_data = df[df['date'] == date].copy()
            if len(day_data) < 10: continue

            # Logic at 19:00
            range_data = day_data[(day_data['time'].dt.hour >= 8) & (day_data['time'].dt.hour < 19)]
            if range_data.empty: continue

            max_idx = range_data['high'].idxmax()
            min_idx = range_data['low'].idxmin()
            
            high_price = range_data.loc[max_idx, 'high']
            high_time = range_data.loc[max_idx, 'time']
            low_price = range_data.loc[min_idx, 'low']
            low_time = range_data.loc[min_idx, 'time']
            
            price_range = high_price - low_price
            if price_range == 0: continue

            last_idx_before_20 = range_data.index[-1]
            atr_val = self.calculate_atr(df, last_idx_before_20)
            if atr_val is None: continue
            
            distance_price = 200 * 0.00001
            
            # Search after 20:00 until 00:00 next day
            start_search_idx = last_idx_before_20 + 1
            if start_search_idx >= len(df): continue
            
            # Find 02:00 limit (Next day)
            force_close_time = datetime.combine(date + timedelta(days=1), time(2, 0))
            future_data = df.iloc[start_search_idx:]
            
            if low_time < high_time: # BUY SETUP
                for fibo in self.fibo_levels:
                    entry_price = round(high_price - (price_range * fibo), 5)
                    sl_price = entry_price - distance_price
                    tp_price = entry_price + (distance_price * 0.5)
                    
                    for idx, row in future_data.iterrows():
                        if row['time'] >= force_close_time: break # Order Expired
                        
                        if row['low'] <= entry_price:
                            # Entry Hit
                            entry_time = row['time']
                            trade_data = df.iloc[idx+1:]
                            closed = False
                            for t_idx, t_row in trade_data.iterrows():
                                if t_row['time'] >= force_close_time:
                                    # Forced Close at 02:00
                                    self.record_trade(entry_time, "BUY", entry_price, t_row['open'], (t_row['open'] - entry_price) / distance_price, "02:00 Close")
                                    closed = True
                                    break
                                elif t_row['low'] <= sl_price:
                                    self.record_trade(entry_time, "BUY", entry_price, sl_price, -1.0, f"Fibo {fibo} SL")
                                    closed = True
                                    break
                                elif t_row['high'] >= tp_price:
                                    self.record_trade(entry_time, "BUY", entry_price, tp_price, 1.0, f"Fibo {fibo} TP")
                                    closed = True
                                    break
                            if not closed and not trade_data.empty: # Fallback if end of history
                                last_row = trade_data.iloc[-1]
                                self.record_trade(entry_time, "BUY", entry_price, last_row['close'], (last_row['close'] - entry_price) / distance_price, "End of History")
                            break
            
            elif high_time < low_time: # SELL SETUP
                for fibo in self.fibo_levels:
                    entry_price = round(low_price + (price_range * fibo), 5)
                    sl_price = entry_price + distance_price
                    tp_price = entry_price - (distance_price * 0.5)
                    
                    for idx, row in future_data.iterrows():
                        if row['time'] >= force_close_time: break # Order Expired
                        
                        if row['high'] >= entry_price:
                            entry_time = row['time']
                            trade_data = df.iloc[idx+1:]
                            closed = False
                            for t_idx, t_row in trade_data.iterrows():
                                if t_row['time'] >= force_close_time:
                                    # Forced Close at 02:00
                                    self.record_trade(entry_time, "SELL", entry_price, t_row['open'], (entry_price - t_row['open']) / distance_price, "02:00 Close")
                                    closed = True
                                    break
                                elif t_row['high'] >= sl_price:
                                    self.record_trade(entry_time, "SELL", entry_price, sl_price, -1.0, f"Fibo {fibo} SL")
                                    closed = True
                                    break
                                elif t_row['low'] <= tp_price:
                                    self.record_trade(entry_time, "SELL", entry_price, tp_price, 1.0, f"Fibo {fibo} TP")
                                    closed = True
                                    break
                            if not closed and not trade_data.empty:
                                last_row = trade_data.iloc[-1]
                                self.record_trade(entry_time, "SELL", entry_price, last_row['close'], (entry_price - last_row['close']) / distance_price, "End of History")
                            break

    def record_trade(self, time, type, entry, exit, profit_factor, comment):
        risk_amount = self.balance * (self.risk_percent / 100)
        profit = risk_amount * profit_factor
        self.balance += profit
        self.trades.append({
            "time": time,
            "type": type,
            "entry": entry,
            "exit": exit,
            "profit": profit,
            "balance": self.balance,
            "comment": comment
        })

    def shutdown(self):
        mt5.shutdown()

if __name__ == "__main__":
    backtester = LondonNYBacktester()
    start_date = datetime(2026, 1, 1)
    data = backtester.get_data(start_date)
    
    if data is not None:
        backtester.run(data)
        print(f"Backtest Finished. Total trades: {len(backtester.trades)}", flush=True)
        print(f"Final Balance: ${backtester.balance:.2f}", flush=True)
        logger = LogProcessor(backtester.trades)
        logger.export_to_csv("london_ny_backtest.csv")
        logger.create_performance_graph("london_ny_performance.png")
    backtester.shutdown()
