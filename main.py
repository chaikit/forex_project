from src.trade_setup import TradeSetUp
from src.backtest_engine import BacktestEngine
from src.log_processor import LogProcessor
import pandas as pd

def main():
    print("Initializing Forex Project Structure...")
    
    # 1. Initialize Trade SetUp
    setup = TradeSetUp(symbol="EURUSD", timeframe="H1")
    print(f"Trade Setup ready with parameters: {setup.get_parameters()}")

    # 2. Connect to MT5 and Run Backtest
    # Note: This requires MT5 to be running on your machine.
    engine = BacktestEngine(setup)
    
    # Normally we would call engine.initialize_mt5()
    # For this structure demonstration, we simulate some data if MT5 is not available
    print("Simulating data for demonstration...")
    dummy_data = pd.DataFrame({
        'time': pd.date_range(start='2023-01-01', periods=10, freq='H'),
        'close': [1.0800, 1.0810, 1.0805, 1.0820, 1.0825, 1.0815, 1.0830, 1.0840, 1.0835, 1.0850]
    })
    
    raw_results = engine.run_simulation(dummy_data)
    
    # Add dummy results if simulation returned empty (since conditions are placeholders)
    if not raw_results:
        raw_results = [
            {"time": "2023-01-01 00:00", "type": "BUY", "price": 1.0800, "profit": 5.0},
            {"time": "2023-01-01 01:00", "type": "SELL", "price": 1.0810, "profit": -2.0},
            {"time": "2023-01-01 02:00", "type": "BUY", "price": 1.0805, "profit": 10.0}
        ]

    # 3. Log and Process Results
    logger = LogProcessor(raw_results)
    csv_path = logger.export_to_csv()
    graph_path = logger.create_performance_graph()

    print("--- Process Complete ---")
    print(f"Log generated: {csv_path}")
    print(f"Graph generated: {graph_path}")

if __name__ == "__main__":
    main()
