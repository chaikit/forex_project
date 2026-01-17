import MetaTrader5 as mt5
import sys

def test_mt5_connection():
    print(f"Python version: {sys.version}")
    print("Attempting to initialize MetaTrader 5...")
    
    # Initialize connection to the MetaTrader 5 terminal
    if not mt5.initialize():
        print(f"initialize() failed, error code = {mt5.last_error()}")
        return False
    
    print("MT5 initialized successfully!")
    
    # Check if we are connected to the trade server
    terminal_info = mt5.terminal_info()
    if terminal_info is None:
        print(f"Failed to get terminal info, error code = {mt5.last_error()}")
        mt5.shutdown()
        return False
    
    print(f"Terminal Info: {terminal_info._asdict()}")
    
    # Try to get account info
    account_info = mt5.account_info()
    if account_info is None:
        print(f"Failed to get account info. Please make sure you are logged in to an account in MT5. Error code = {mt5.last_error()}")
    else:
        print("Account Info retrieved successfully!")
        print(f"Account ID: {account_info.login}")
        print(f"Trade Server: {account_info.server}")
        print(f"Balance: {account_info.balance}")
    
    # Shut down connection to the MetaTrader 5 terminal
    mt5.shutdown()
    print("MT5 connection closed.")
    return True

if __name__ == "__main__":
    if test_mt5_connection():
        print("\nSUCCESS: Python can talk to MT5.")
    else:
        print("\nFAILED: Could not establish MT5 connection. Make sure MetaTrader 5 terminal is installed and open.")
