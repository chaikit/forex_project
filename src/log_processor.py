import pandas as pd
import matplotlib.pyplot as plt
import os
import json
from datetime import datetime

class LogProcessor:
    """
    Component for processing raw data into CSV reports, visual graphs, 
    and detailed performance summaries with comparison.
    """
    def __init__(self, raw_data, start_hour=None, close_hour=None, tp_multiplier=1.1, output_dir="reports"):
        self.data = raw_data
        self.start_hour = start_hour
        self.close_hour = close_hour
        self.tp_multiplier = tp_multiplier
        self.output_dir = output_dir
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        self.history_file = os.path.join(output_dir, "report_history.json")

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
        plt.figure(figsize=(10, 6))
        plt.plot(df['entry_time'], df['balance'])
        plt.title('Backtest Performance - Equity Curve')
        plt.xlabel('Time')
        plt.ylabel('Balance')
        plt.grid(True)
        
        path = os.path.join(self.output_dir, filename)
        plt.savefig(path)
        plt.close()
        print(f"Performance graph saved to {path}")
        return path

    def calculate_avg_hour(self, series):
        """Calculate average hour using circular mean to handle midnight crossing."""
        if series.empty:
            return 0
        import numpy as np
        # Convert hours to radians
        radians = series.dt.hour * 2 * np.pi / 24 + series.dt.minute * 2 * np.pi / (24 * 60)
        # Average the vectors
        avg_x = np.mean(np.cos(radians))
        avg_y = np.mean(np.sin(radians))
        # Convert back to hours
        avg_rad = np.arctan2(avg_y, avg_x)
        avg_hour = avg_rad * 24 / (2 * np.pi)
        if avg_hour < 0:
            avg_hour += 24
        return avg_hour

    def calculate_metrics(self, df):
        if df.empty:
            return None
        
        total_orders = len(df)
        won_trades = df[df['comment'] == 'TP']
        lost_trades = df[df['comment'] == 'SL']
        forced_trades = df[df['comment'].str.contains("Close", na=False)]
        
        win_rate = (len(won_trades) / total_orders * 100) if total_orders > 0 else 0
        forced_pct = (len(forced_trades) / total_orders * 100) if total_orders > 0 else 0
        normal_close_pct = 100 - forced_pct
        
        avg_trigger_hour = self.calculate_avg_hour(df['entry_time'])
        
        # TP/SL specific metrics
        tpsl_trades = df[df['comment'].isin(['TP', 'SL'])]
        avg_tpsl_hour = self.calculate_avg_hour(tpsl_trades['exit_time']) if not tpsl_trades.empty else 0
        
        # Duration (Trigger to Close) excluding forced
        non_forced = df[~df['comment'].str.contains("Close", na=False)]
        avg_duration = (non_forced['exit_time'] - non_forced['entry_time']).mean().total_seconds() / 3600 if not non_forced.empty else 0
        
        # Risk Reward
        rr_display = f"1:{self.tp_multiplier}"
        
        # Drawdown and Recovery
        df_copy = df.copy().reset_index(drop=True)
        df_copy['cum_max'] = df_copy['balance'].cummax()
        df_copy['drawdown'] = (df_copy['cum_max'] - df_copy['balance']) / df_copy['cum_max'] * 100
        max_dd = df_copy['drawdown'].max()
        
        # Expected Value
        expected_value = (df_copy['profit'].sum() / total_orders) if total_orders > 0 else 0

        # Profit Recovery Time (Days)
        recovery_days = 0
        peak_time = df_copy.loc[0, 'entry_time']
        for i in range(1, len(df_copy)):
            if df_copy.loc[i, 'balance'] >= df_copy.loc[:i-1, 'balance'].max():
                duration = (df_copy.loc[i, 'entry_time'] - peak_time).days
                recovery_days = max(recovery_days, duration)
                peak_time = df_copy.loc[i, 'entry_time']

        return {
            "Total Orders": total_orders,
            "WinRate (%)": round(win_rate, 2),
            "Normal Close (%)": round(normal_close_pct, 2),
            "Forced Close (%)": round(forced_pct, 2),
            "Avg Trigger Hour": f"{int(avg_trigger_hour):02d}:{int((avg_trigger_hour%1)*60):02d}",
            "Avg TP/SL Hour": f"{int(avg_tpsl_hour):02d}:{int((avg_tpsl_hour%1)*60):02d}" if avg_tpsl_hour else "N/A",
            "Avg Duration (Hrs)": round(avg_duration, 2),
            "Risk Per Reward": rr_display,
            "Max Drawdown (%)": round(max_dd, 2),
            "Max Recovery (Days)": recovery_days,
            "Expected Value": round(expected_value, 2)
        }

    def generate_summary_report(self):
        df = pd.DataFrame(self.data)
        if df.empty: return "No trades to report."
        
        df['entry_time'] = pd.to_datetime(df['entry_time'])
        df['exit_time'] = pd.to_datetime(df['exit_time'])
        
        # Calculate Thai Time (Server + 5 hours)
        def to_thai_time(server_hour):
            if server_hour is None: return "N/A"
            thai_hour = (server_hour + 5) % 24
            return f"{server_hour:02d}:00 ({thai_hour:02d}:00 Thai)"

        report = {
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Strategy Settings": {
                "Trigger Setup Hour": to_thai_time(self.start_hour),
                "Forced Close Hour": to_thai_time(self.close_hour)
            },
            "Overall": self.calculate_metrics(df),
            "SetUp1 (61.8%)": self.calculate_metrics(df[df['setup'].str.contains("61.8")]),
            "SetUp2 (78.6%)": self.calculate_metrics(df[df['setup'].str.contains("78.6")])
        }
        
        self.display_report(report)
        self.compare_and_save(report)
        return report

    def display_report(self, report):
        print("\n" + "="*50)
        print("          STRATEGY PERFORMANCE REPORT")
        print("="*50)
        
        headers = ["Metric", "Overall", "SetUp1 (61.8%)", "SetUp2 (78.6%)"]
        metrics = report["Overall"].keys()
        
        print(f"{headers[0]:<20} | {headers[1]:<10} | {headers[2]:<15} | {headers[3]:<15}")
        print("-" * 70)
        
        for m in metrics:
            o = report["Overall"].get(m, "N/A")
            s1 = report["SetUp1 (61.8%)"].get(m, "N/A") if report["SetUp1 (61.8%)"] else "N/A"
            s2 = report["SetUp2 (78.6%)"].get(m, "N/A") if report["SetUp2 (78.6%)"] else "N/A"
            print(f"{m:<20} | {str(o):<10} | {str(s1):<15} | {str(s2):<15}")
        print("="*70 + "\n")

    def compare_and_save(self, current_report):
        history = []
        if os.path.exists(self.history_file):
            with open(self.history_file, 'r') as f:
                history = json.load(f)
        
        if history:
            last_report = history[-1]
            print("COMPARISON WITH PREVIOUS REPORT:")
            print(f"(Previous: {last_report['Timestamp']})")
            
            o_curr = current_report["Overall"]["WinRate (%)"]
            o_last = last_report["Overall"]["WinRate (%)"]
            diff = o_curr - o_last
            symbol = "+" if diff > 0 else ""
            print(f"Overall WinRate Change: {symbol}{diff:.2f}% ({o_last}% -> {o_curr}%)")
            
            p_curr = current_report["Overall"]["Expected Value"]
            p_last = last_report["Overall"]["Expected Value"]
            diff_p = p_curr - p_last
            symbol_p = "+" if diff_p > 0 else ""
            print(f"Expected Value Change: {symbol_p}{diff_p:.2f} ({p_last} -> {p_curr})")
            print("-" * 30 + "\n")
        
        history.append(current_report)
        # Keep only the last 2 reports
        history = history[-2:]
        with open(self.history_file, 'w') as f:
            json.dump(history, f, indent=4)
