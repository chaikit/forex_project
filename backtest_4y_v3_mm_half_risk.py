import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta
import os
import shutil
from src.log_processor import LogProcessor

# Custom Backtester with Half-Risk on Drawdown MM (4-Year Period)
# Reduces risk to 0.5% if Drawdown exceeds threshold, resets at New High.
class BacktesterV3_4YearsMMHalfRisk:
    def __init__(self, symbol="EURUSD", initial_balance=1000.0):
        self.symbol = symbol
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.max_balance = initial_balance
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

    def run(self, df, dd_threshold, allowed_weekdays=None):
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
            
            # MM Logic: Determine risk for today's setups
            current_dd = (self.balance - self.max_balance) / self.max_balance
            risk_percent = 1.0 # Standard
            if current_dd <= dd_threshold: # e.g. -0.05
                risk_percent = 0.5 # Half Risk
            
            if low_time < high_time: # BUY SETUP
                for fibo in self.fibo_levels:
                    entry = round(high_price - (price_range * fibo), 5)
                    self.simulate_trade(df, start_search_idx, "BUY", entry, entry - sl_price_dist, entry + tp_price_dist, force_close_time, fibo, risk_percent)
            elif high_time < low_time: # SELL SETUP
                for fibo in self.fibo_levels:
                    entry = round(low_price + (price_range * fibo), 5)
                    self.simulate_trade(df, start_search_idx, "SELL", entry, entry + sl_price_dist, entry - tp_price_dist, force_close_time, fibo, risk_percent)

    def simulate_trade(self, df, start_idx, side, entry, sl, tp, force_close, fibo, risk_percent):
        future_df = df.iloc[start_idx:]
        for idx_rel, row in enumerate(future_df.itertuples()):
            if row.time >= force_close: return False
            if (side == "BUY" and row.low <= entry) or (side == "SELL" and row.high >= entry):
                entry_time = row.time
                search_idx_start = start_idx + idx_rel + 1
                if search_idx_start >= len(df): return True 
                
                for t_row in df.iloc[search_idx_start:].itertuples():
                    if t_row.time >= force_close:
                        pf = (t_row.open - entry) / (entry - sl) if side == "BUY" else (entry - t_row.open) / (sl - entry)
                        self.record_trade(entry_time, t_row.time, side, f"v3.0 MM-Dual Fibo {fibo}", entry, t_row.open, pf, "Force Close", risk_percent)
                        return True
                    if (side == "BUY" and t_row.low <= sl) or (side == "SELL" and t_row.high >= sl):
                        self.record_trade(entry_time, t_row.time, side, f"v3.0 MM-Dual Fibo {fibo}", entry, sl, -1.0, "SL", risk_percent)
                        return True
                    if (side == "BUY" and t_row.high >= tp) or (side == "SELL" and t_row.low <= tp):
                        self.record_trade(entry_time, t_row.time, side, f"v3.0 MM-Dual Fibo {fibo}", entry, tp, self.rr_ratio, "TP", risk_percent)
                        return True
                return True
        return False

    def record_trade(self, entry_time, exit_time, side, setup, entry, exit, pf, comment, risk_percent):
        risk = self.balance * (risk_percent / 100)
        profit = risk * pf
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
    tester = BacktesterV3_4YearsMMHalfRisk()
    start_date = datetime(2022, 1, 24)
    data = tester.get_data(start_date)
    
    if data is not None:
        thresholds = [-0.05, -0.10]
        for th in thresholds:
            print(f"\n--- Running Backtest MM: Half-Risk if DD > {th*100:.1f}% ---")
            tester.reset()
            tester.run(data, th, allowed_weekdays=[0, 1, 2, 4])
            
            print(f"Final Balance: ${tester.balance:.2f} | Total Trades: {len(tester.trades)}")
            
            suffix = f"4y_v3_MM_HalfRisk_DD{int(abs(th)*100)}"
            if not os.path.exists("reports"): os.makedirs("reports")
            
            logger = LogProcessor(tester.trades, start_hour=12, close_hour=0, tp_multiplier=6.0)
            logger.export_to_csv(f"backtest_results_{suffix}.csv")
            logger.create_performance_graph(f"performance_{suffix}.png")
            logger.generate_summary_report()
            
            src_history = os.path.join("reports", "report_history.json")
            if os.path.exists(src_history):
                dest_history = os.path.join("reports", f"report_history_{suffix}.json")
                shutil.copy(src_history, dest_history)

    tester.shutdown()
