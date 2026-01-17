import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
import os

class BacktestEngine:
    """
    Component for connecting to MT5, fetching data, and running backtests.
    """
    def __init__(self, trade_setup):
        self.setup = trade_setup
        self.results = []

    def initialize_mt5(self):
        """Initializes connection to MT5 terminal."""
        if not mt5.initialize():
            print("MT5 Initialization failed, check if MT5 is open.")
            return False
        return True

    def get_historical_data(self, count=1000):
        """Fetches historical OHLC data from MT5 based on TradeSetUp settings."""
        # Convert timeframe string to MT5 constant if needed (simplified here)
        tf = mt5.TIMEFRAME_H1 # Default
        
        rates = mt5.copy_rates_from_pos(self.setup.symbol, tf, 0, count)
        if rates is None:
            print(f"Error getting rates for {self.setup.symbol}")
            return None
        
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        return df

    def run_simulation(self, data):
        """
        Simulates trading using TradeSetUp logic on historical data.
        This produces 'raw' backtest results.
        """
        print(f"Starting simulation for {self.setup.symbol}...")
        
        raw_trades = []
        # Simulation logic would iterate through data and call check_buy_condition etc.
        # This is a dummy example of how it connects
        for index, row in data.iterrows():
            if self.setup.check_buy_condition(row):
                raw_trades.append({
                    "time": row['time'],
                    "type": "BUY",
                    "price": row['close'],
                    "status": "CLOSED",
                    "profit": 10.5 # Dummy profit
                })
        
        self.results = raw_trades
        return raw_trades

    def shutdown(self):
        mt5.shutdown()
