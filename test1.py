import os
import time
import logging
from itertools import permutations
from binance.client import Client
from binance.exceptions import BinanceAPIException
from binance import ThreadedWebsocketManager
from config import PROFIT_THRESHOLD, INITIAL_TRADE_AMOUNT, RETRY_INTERVAL


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
def execute_trades(path, rates, initial_amount=0.001, slippage_tolerance=0.01):
    try:
        logging.info(f"Executing trade for path: {path} with rates {rates}")
        base_amount = initial_amount
        for i, pair in enumerate(path):
            rate = rates[i]

            # Adjust for slippage
            expected_rate = client.get_symbol_ticker(symbol=pair)['price']
            if abs((float(expected_rate) - rate) / rate) > slippage_tolerance:
                logging.warning(f"Slippage exceeded for {pair}. Aborting trade.")
                return

            quantity = adjust_quantity(pair, base_amount / rate)
            order = client.order_market_buy(symbol=pair, quantity=quantity)
            logging.info(f"Executed {pair}: {order}")
            base_amount = quantity * float(expected_rate)
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
            prices = live_prices if live_prices else get_prices()
            if prices:
                opportunities = find_arbitrage_opportunities(prices)
                if opportunities:
                    logging.info("Arbitrage Opportunities Found:")
                    for opp in opportunities[:5]:
                        logging.info(f"Path: {opp['path']}, Profit: {opp['profit']:.2f}%")
                        if opp['profit'] > PROFIT_THRESHOLD:
                            execute_trades(
                                path=opp['path'].split(" -> "),
                                rates=opp['rates'],
                                initial_amount=INITIAL_TRADE_AMOUNT
                            )
                else:
                    logging.info("No Arbitrage Opportunities.")
            time.sleep(RETRY_INTERVAL)
        except KeyboardInterrupt:
            logging.info("Bot stopped by user.")
            break
        except Exception as e:
            logging.error(f"Error in bot loop: {e}")

if __name__ == "__main__":
    arbitrage_bot()
