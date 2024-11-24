import os
import time
import logging
from itertools import permutations
from binance.client import Client
from binance.exceptions import BinanceAPIException

# Binance API setup
API_KEY = os.getenv('BINANCE_API_KEY')
API_SECRET = os.getenv('BINANCE_API_SECRET')
client = Client(api_key=API_KEY, api_secret=API_SECRET, testnet=True)
client.API_URL = 'https://testnet.binance.vision/api'

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("arbitrage_bot.log"),
        logging.StreamHandler()
    ]
)

# Fetch prices and convert to a dictionary
def get_prices():
    for _ in range(5):  # Retry logic
        try:
            tickers = client.get_all_tickers()
            return {ticker['symbol']: float(ticker['price']) for ticker in tickers}
        except Exception as e:
            logging.warning(f"Error fetching prices: {e}. Retrying in 5 seconds...")
            time.sleep(5)
    raise Exception("Failed to fetch prices after retries.")

# Find arbitrage opportunities dynamically
def find_arbitrage_opportunities(prices):
    opportunities = []
    trading_pairs = prices.keys()
    
    # Generate all possible triangular paths
    for path in permutations(trading_pairs, 3):
        pair_1, pair_2, pair_3 = path

        # Ensure pairs are connected logically
        if pair_1[-3:] == pair_2[:3] and pair_2[-3:] == pair_3[:3] and pair_3[-3:] == pair_1[:3]:
            try:
                rate_1 = prices[pair_1]
                rate_2 = prices[pair_2]
                rate_3 = 1 / prices[pair_3]

                # Calculate profit percentage
                profit = (rate_1 * rate_2 * rate_3 - 1) * 100
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
    except BinanceAPIException as e:
        logging.error(f"Trade Error: {e}")
    except Exception as e:
        logging.error(f"Unexpected Error: {e}")

# Main bot loop
def arbitrage_bot():
    logging.info("Starting Binance Arbitrage Bot...")
    while True:
        try:
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
                else:
                    logging.info("No Arbitrage Opportunities.")
            time.sleep(10)
        except KeyboardInterrupt:
            logging.info("Bot stopped by user.")
            break
        except Exception as e:
            logging.error(f"Error in bot loop: {e}")

if __name__ == "__main__":
    arbitrage_bot()
