import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta
import os
import shutil
from src.log_processor import LogProcessor

# Advanced Backtester: Half-Risk MM + Partial Close + Break Even (4-Year Period)
# Logic: 
# 1. MM: Risk 1% if DD > -5%, else Risk 0.5%. Reset at New High.
# 2. Partial Close: Exit 50% at RR 1:3.
# 3. Break Even: Move remaining 50% SL to Entry when RR 1:3 hit.
# 4. Final TP: Remaining 50% at RR 1:6.
class BacktesterV3_4YearsAdvanced:
    def __init__(self, symbol="EURUSD", initial_balance=1000.0):
        self.symbol = symbol
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.max_balance = initial_balance
        self.trades = []
        self.fibo_levels = [0.618, 0.786]
        self.start_hour = 12
        self.sl_points = 15
        self.tp1_rr = 3.0 # Partial Close RR
        self.tp2_rr = 6.0 # Final Close RR

        if not mt5.initialize():
            print("MT5 Initialization failed", flush=True)
            quit()

    def reset(self):
        self.balance = self.initial_balance
        self.max_balance = self.initial_balance
        self.trades = []

    def get_data(self, start_date):
        print(f"Fetching M30 data for {self.symbol} from {start_date}...", flush=True)
        utc_from = start_date
        utc_to = datetime.now()
        rates = mt5.copy_rates_range(self.symbol, mt5.TIMEFRAME_M30, utc_from, utc_to)
        if rates is None: 
            print(f"Failed to get rates: {mt5.last_error()}", flush=True)
            return None
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        return df

    def run(self, df, dd_threshold=-0.05, allowed_weekdays=None):
        if df is None or len(df) == 0: return

        df['date'] = df['time'].dt.date
        days = df['date'].unique()
        
        sl_dist = self.sl_points * 0.00001
        tp1_dist = (self.sl_points * self.tp1_rr) * 0.00001
        tp2_dist = (self.sl_points * self.tp2_rr) * 0.00001

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
            
            # MM Logic
            current_dd = (self.balance - self.max_balance) / self.max_balance
            risk_percent = 1.0 if current_dd > dd_threshold else 0.5
            
            if low_time < high_time: # BUY SETUP
                for fibo in self.fibo_levels:
                    entry = round(high_price - (price_range * fibo), 5)
                    self.simulate_trade(df, start_search_idx, "BUY", entry, entry - sl_dist, entry + tp1_dist, entry + tp2_dist, force_close_time, fibo, risk_percent)
            elif high_time < low_time: # SELL SETUP
                for fibo in self.fibo_levels:
                    entry = round(low_price + (price_range * fibo), 5)
                    self.simulate_trade(df, start_search_idx, "SELL", entry, entry + sl_dist, entry - tp1_dist, entry - tp2_dist, force_close_time, fibo, risk_percent)

    def simulate_trade(self, df, start_idx, side, entry, sl, tp1, tp2, force_close, fibo, risk_percent):
        future_df = df.iloc[start_idx:]
        for idx_rel, row in enumerate(future_df.itertuples()):
            if row.time >= force_close: return False
            if (side == "BUY" and row.low <= entry) or (side == "SELL" and row.high >= entry):
                entry_time = row.time
                current_sl = sl
                partial_closed = False
                
                search_idx_start = start_idx + idx_rel + 1
                if search_idx_start >= len(df): return True 
                
                for t_row in df.iloc[search_idx_start:].itertuples():
                    if t_row.time >= force_close:
                        # Close remaining according to status
                        if partial_closed:
                            # 50% was already closed at tp1 (RR 3). Remaining 50% closed at current price.
                            pf_rem = (t_row.open - entry) / (entry - sl) if side == "BUY" else (entry - t_row.open) / (sl - entry)
                            total_pf = (self.tp1_rr * 0.5) + (pf_rem * 0.5)
                            self.record_trade(entry_time, t_row.time, side, f"v3.0 Advanced Fibo {fibo}", entry, t_row.open, total_pf, "Force Close (Partial Done)", risk_percent)
                        else:
                            # 100% closed at current price
                            pf = (t_row.open - entry) / (entry - sl) if side == "BUY" else (entry - t_row.open) / (sl - entry)
                            self.record_trade(entry_time, t_row.time, side, f"v3.0 Advanced Fibo {fibo}", entry, t_row.open, pf, "Force Close", risk_percent)
                        return True
                    
                    # 1. Check for TP1 (Partial Close & BE)
                    if not partial_closed:
                        if (side == "BUY" and t_row.high >= tp1) or (side == "SELL" and t_row.low <= tp1):
                            partial_closed = True
                            current_sl = entry # Moving SL to BE
                        
                    # 2. Check for SL
                    if (side == "BUY" and t_row.low <= current_sl) or (side == "SELL" and t_row.high >= current_sl):
                        if partial_closed:
                            # 50% at RR 3 | 50% at BE (0)
                            total_pf = (self.tp1_rr * 0.5) + (0.0 * 0.5)
                            self.record_trade(entry_time, t_row.time, side, f"v3.0 Advanced Fibo {fibo}", entry, current_sl, total_pf, "Partial Hit -> BE Hit", risk_percent)
                        else:
                            # 100% at SL (-1)
                            self.record_trade(entry_time, t_row.time, side, f"v3.0 Advanced Fibo {fibo}", entry, current_sl, -1.0, "SL", risk_percent)
                        return True

                    # 3. Check for Final TP2
                    if (side == "BUY" and t_row.high >= tp2) or (side == "SELL" and t_row.low <= tp2):
                        if partial_closed:
                            # 50% at RR 3 | 50% at RR 6
                            total_pf = (self.tp1_rr * 0.5) + (self.tp2_rr * 0.5)
                            self.record_trade(entry_time, t_row.time, side, f"v3.0 Advanced Fibo {fibo}", entry, tp2, total_pf, "TP1 & TP2 Hit", risk_percent)
                        else:
                            # 100% at RR 6 (Extreme case where it jumps to tp2 instantly)
                            self.record_trade(entry_time, t_row.time, side, f"v3.0 Advanced Fibo {fibo}", entry, tp2, self.tp2_rr, "Direct TP2 Hit", risk_percent)
                        return True
                return True
        return False

    def record_trade(self, entry_time, exit_time, side, setup, entry, exit, pf, comment, risk_percent):
        risk_val = self.balance * (risk_percent / 100)
        profit = risk_val * pf
        self.balance += profit
        if self.balance > self.max_balance:
            self.max_balance = self.balance
            
        self.trades.append({
            "entry_time": entry_time, "exit_time": exit_time,
            "type": side, "setup": setup, "entry": entry, "exit": exit,
            "profit": profit, "balance": self.balance, "comment": f"{comment} (Risk {risk_percent}%)",
            "atr": 0, "adx": 0
        })

    def shutdown(self): mt5.shutdown()

if __name__ == "__main__":
    tester = BacktesterV3_4YearsAdvanced()
    start_date = datetime(2022, 1, 24)
    data = tester.get_data(start_date)
    
    if data is not None:
        print(f"\n--- Running Final Advanced Backtest: MM Half-Risk @ -5% | Partial 1:3 | Final 1:6 ---")
        tester.reset()
        tester.run(data, dd_threshold=-0.05, allowed_weekdays=[0, 1, 2, 4])
        
        print(f"Final Balance: ${tester.balance:.2f} | Total Trades: {len(tester.trades)}")
        
        suffix = "4y_v3_Advanced_Safety"
        if not os.path.exists("reports"): os.makedirs("reports")
        
        # LogProcessor needs adjusted tp_multiplier for EV calculation
        logger = LogProcessor(tester.trades, start_hour=12, close_hour=0, tp_multiplier=4.5) # Avg TP (3+6)/2 = 4.5
        logger.export_to_csv(f"backtest_results_{suffix}.csv")
        logger.create_performance_graph(f"performance_{suffix}.png")
        logger.generate_summary_report()
        
    tester.shutdown()
