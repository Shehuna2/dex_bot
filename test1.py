import os
import time
import logging
import pandas as pd
from itertools import permutations
from binance.client import Client
from binance.exceptions import BinanceAPIException
from binance import ThreadedWebsocketManager



# Binance API setup
API_KEY = os.getenv('BINANCE_API_KEY')
API_SECRET = os.getenv('BINANCE_API_SECRET')
client = Client(api_key=API_KEY, api_secret=API_SECRET, testnet=True)
client.API_URL = 'https://testnet.binance.vision/api'

# Logging setup
logging.basicConfig(
    level=logging.DEBUG,  # Log all levels
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("arbitrage_bot.log", mode='a'),  # Append to log file
        logging.StreamHandler()  # Print to console
    ]
)

# Separate logger for trade history
trade_logger = logging.getLogger("trades")
trade_logger.setLevel(logging.INFO)
trade_logger.addHandler(logging.FileHandler("trade_history.log"))

# Fetch balances for specified assets
def get_balances(assets):
    try:
        balances = {}
        for asset in assets:
            balance = client.get_asset_balance(asset=asset)
            if balance:
                balances[asset] = {
                    'free': float(balance['free']),
                    'locked': float(balance['locked'])
                }
        return balances
    except Exception as e:
        logging.error(f"Error fetching balances: {e}")
        return {}

# Display balances in logs
def display_balances(assets):
    balances = get_balances(assets)
    logging.info("Current Balances:")
    for asset, balance in balances.items():
        logging.info(f"{asset}: Free: {balance['free']:.8f}, Locked: {balance['locked']:.8f}")

# Calculate profit (optional)
def calculate_profit(initial_balances, current_balances):
    profit = 0
    for asset, initial_balance in initial_balances.items():
        if asset in current_balances:
            profit += (current_balances[asset]['free'] - initial_balance['free'])
    return profit

# Global variable to hold real-time prices
live_prices = {}
def start_price_stream():
    def handle_message(msg):
        if msg['e'] == '24hrTicker':
            live_prices[msg['s']] = float(msg['c'])

    twm = ThreadedWebsocketManager(api_key=API_KEY, api_secret=API_SECRET)
    twm.start()
    twm.start_ticker_socket(callback=handle_message)
    logging.info("Started WebSocket for real-time prices.")

# Find arbitrage opportunities dynamically
def find_arbitrage_opportunities(prices):
    fee_rate = 0.001  # 0.1% per trade
    opportunities = []
    trading_pairs = prices.keys()

    for path in permutations(trading_pairs, 3):
        pair_1, pair_2, pair_3 = path

        if pair_1[-3:] == pair_2[:3] and pair_2[-3:] == pair_3[:3] and pair_3[-3:] == pair_1[:3]:
            try:
                rate_1 = prices[pair_1]
                rate_2 = prices[pair_2]
                rate_3 = 1 / prices[pair_3]

                # Adjust for fees
                profit = (rate_1 * rate_2 * rate_3 * (1 - fee_rate) ** 3 - 1) * 100
                if profit > 0:
                    opportunities.append({
                        'path': f"{pair_1} -> {pair_2} -> {pair_3}",
                        'profit': profit,
                        'rates': [rate_1, rate_2, rate_3]
                    })
            except KeyError:
                continue
    return sorted(opportunities, key=lambda x: x['profit'], reverse=True)

# Get trading rules for a symbol
def get_trading_rules(symbol):
    try:
        symbol_info = client.get_symbol_info(symbol)
        if not symbol_info:
            raise ValueError(f"Symbol {symbol} not found")
        for filter_data in symbol_info['filters']:
            if filter_data['filterType'] == 'LOT_SIZE':
                return {
                    'stepSize': float(filter_data['stepSize']),
                    'minQty': float(filter_data['minQty']),
                    'maxQty': float(filter_data['maxQty']),
                }
    except Exception as e:
        logging.error(f"Error fetching trading rules for {symbol}: {e}")
        raise

# Adjust quantity based on trading rules
def adjust_quantity(symbol, quantity):
    try:
        rules = get_trading_rules(symbol)
        step_size = rules['stepSize']
        min_qty = rules['minQty']
        max_qty = rules['maxQty']

        # Ensure quantity respects stepSize, minQty, and maxQty
        adjusted_qty = max(min(max_qty, quantity), min_qty)
        adjusted_qty -= adjusted_qty % step_size
        return adjusted_qty
    except Exception as e:
        logging.error(f"Error adjusting quantity for {symbol}: {e}")
        raise

# Execute trades
def execute_trades(path, rates, initial_amount=0.001):
    try:
        logging.info(f"Executing trade for path: {path} with rates {rates}")
        base_amount = initial_amount
        for i, pair in enumerate(path):
            rate = rates[i]

            # Adjust quantity to meet Binance requirements
            quantity = adjust_quantity(pair, base_amount / rate)

            # Place market buy order
            order = client.order_market_buy(symbol=pair, quantity=quantity)
            logging.info(f"Executed {pair}: {order}")
            base_amount = quantity * rate  # Update base amount for the next leg

        logging.info("Arbitrage trade completed successfully.")

        # Display updated balances for the assets involved in the path
        display_balances(assets=[path[0][:3], path[0][-3:], path[1][-3:]])
    except BinanceAPIException as e:
        logging.error(f"Trade Error: {e}")
    except Exception as e:
        logging.error(f"Unexpected Error: {e}")


# Main bot loop
def arbitrage_bot():
    logging.info("Starting Binance Arbitrage Bot...")
    tracked_assets = ['BTC', 'USDT', 'ETH']  # Add the assets you want to track

    # Fetch initial balances
    initial_balances = get_balances(tracked_assets)

    while True:
        try:
            # Display current balances
            display_balances(tracked_assets)

            # Fetch prices and find opportunities
            prices = get_prices()
            if prices:
                opportunities = find_arbitrage_opportunities(prices)
                if opportunities:
                    logging.info("Arbitrage Opportunities Found:")
                    for opp in opportunities[:5]:  # Show top 5 opportunities
                        logging.info(f"Path: {opp['path']}, Profit: {opp['profit']:.2f}%")
                        if opp['profit'] > 0.5:  # Threshold to execute trade
                            execute_trades(
                                path=opp['path'].split(" -> "),
                                rates=opp['rates']
                            )

                            # Fetch and calculate profit after trading
                            current_balances = get_balances(tracked_assets)
                            profit = calculate_profit(initial_balances, current_balances)
                            logging.info(f"Profit from this cycle: {profit:.8f}")
                else:
                    logging.info("No Arbitrage Opportunities.")

            # Delay before the next cycle
            time.sleep(10)

        except KeyboardInterrupt:
            logging.info("Bot stopped by user.")
            break
        except Exception as e:
            logging.error(f"Error in bot loop: {e}")

#Back testing
def backtest(prices_df, initial_amount=0.001):
    """
    Simulates arbitrage trades using historical price data.
    :param prices_df: Pandas DataFrame with columns ['path', 'rates']
    :param initial_amount: Initial base amount for simulation.
    """
    logging.info("Starting backtesting...")
    base_amount = initial_amount

    for index, row in prices_df.iterrows():
        path = row['path'].split(" -> ")
        rates = row['rates']
        profit = (rates[0] * rates[1] * (1 / rates[2]) * (1 - 0.001) ** 3 - 1) * 100  # Adjust for fees
        base_amount *= (profit / 100) + 1
        logging.info(f"Path: {row['path']}, Profit: {profit:.2f}%, Current Amount: {base_amount:.6f}")

    logging.info(f"Final amount after backtesting: {base_amount:.6f}")

if __name__ == "__main__":
    # Example of backtesting usage
    prices_data = pd.DataFrame([
        {'path': 'BTCUSDT -> ETHBTC -> ETHUSDT', 'rates': [50000, 0.02, 2500]},
        {'path': 'BTCUSDT -> BNBUSDT -> BNBBTC', 'rates': [50000, 500, 0.0018]},
    ])
    backtest(prices_data)

    # Start the bot
    arbitrage_bot()