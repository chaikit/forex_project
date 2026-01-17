import pandas as pd
import matplotlib.pyplot as plt
import os

class LogProcessor:
    """
    Component for processing raw data into CSV reports and visual graphs.
    """
    def __init__(self, raw_data, output_dir="reports"):
        self.data = raw_data
        self.output_dir = output_dir
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

    def export_to_csv(self, filename="backtest_results.csv"):
        """Save results as CSV for further analysis."""
        df = pd.DataFrame(self.data)
        path = os.path.join(self.output_dir, filename)
        df.to_csv(path, index=False)
        print(f"Results exported to {path}")
        return path

    def create_performance_graph(self, filename="performance_chart.png"):
        """Generate a graph showing performance over time."""
        if not self.data:
            print("No data available to plot.")
            return None

        df = pd.DataFrame(self.data)
        
        # Simple dummy visualization of profit over time
        plt.figure(figsize=(10, 6))
        plt.plot(df['time'], df['profit'].cumsum())
        plt.title('Backtest Performance - Equity Curve')
        plt.xlabel('Time')
        plt.ylabel('Cumulative Profit')
        plt.grid(True)
        
        path = os.path.join(self.output_dir, filename)
        plt.savefig(path)
        plt.close()
        print(f"Performance graph saved to {path}")
        return path
