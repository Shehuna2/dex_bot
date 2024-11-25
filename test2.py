import logging
from time import time
from binance.client import Client
from aiogram import Bot, Dispatcher
import asyncio

# Setup logging
logging.basicConfig(level=logging.INFO)

# API Credentials
BINANCE_API_KEY = "fZjkR4L7d0oCa4FE87soSqvYNcyrutlmjtIVVhXfwVnRbEuCx7qrtYkI5zWF3Qfc"
BINANCE_API_SECRET = 'S8UJohKiOkVHgH59Bcsa8KP3URLPPNzyOewiFYF4pXX8OKaDhVG6Ewejtbiw4A2v'
TELEGRAM_BOT_TOKEN = '7574272150:AAEx0Vv8fog11nOheF8LIqqQVw0kLDaZMBE'
CHAT_ID = "7843740783"  # Replace with your actual chat ID

# Initialize Binance client and Telegram bot
client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)
bot = Bot(token=TELEGRAM_BOT_TOKEN)

# Cache for Binance prices
cached_prices = {}
last_update_time = 0

def get_prices(cache_duration=10):
    """Fetch and cache Binance ticker prices."""
    global cached_prices, last_update_time
    current_time = time()
    if current_time - last_update_time > cache_duration:
        try:
            tickers = client.get_all_tickers()
            cached_prices = {ticker['symbol']: float(ticker['price']) for ticker in tickers}
            last_update_time = current_time
        except Exception as e:
            logging.error(f"Error fetching prices: {e}")
    return cached_prices

def detect_arbitrage(prices):
    """Detect arbitrage opportunities across specified paths."""
    paths = [("BTCUSDT", "ETHBTC", "ETHUSDT")]
    fee_rate = 0.001  # Binance trading fee
    opportunities = []

    for path in paths:
        try:
            rates = [
                prices[path[0]],          # First pair rate
                1 / prices[path[1]],      # Inverse of the second pair rate
                prices[path[2]]           # Third pair rate
            ]
            profit = (rates[0] * rates[1] * rates[2] * (1 - fee_rate) ** 3 - 1) * 100
            if profit > 0:  # Only log profitable opportunities
                opportunities.append((path, profit))
        except KeyError:
            logging.warning(f"Price data missing for path: {path}")
    return opportunities

async def notify_user(opportunities):
    """
    Notify the user about detected arbitrage opportunities with execution instructions.
    """
    for path, profit in opportunities:
        # Create the alert message in Markdown format
        message = (
            f"💡 **Arbitrage Opportunity Detected!**\n"
            f"Path: {path}\n"
            f"Profit: {profit:.2f}%\n\n"
            f"📖 **Execution Guide**:\n"
            f"1. Trade **{path[0]}**: Use the base currency to buy the first asset.\n"
            f"2. Trade **{path[1]}**: Convert the first asset to the second asset.\n"
            f"3. Trade **{path[2]}**: Convert the second asset back to the target currency.\n"
            f"4. Complete all trades quickly to secure the opportunity.\n\n"
            f"⚠️ **Note**: Verify market prices and fees before executing trades."
        )
        try:
            # Send the alert to the user via Telegram
            await bot.send_message(CHAT_ID, message, parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Error sending Telegram message: {e}")
                        
async def main():
    """Main loop to detect and alert on arbitrage opportunities."""
    logging.info("Arbitrage detection bot started.")
    try:
        while True:
            prices = get_prices()
            opportunities = detect_arbitrage(prices)
            if opportunities:
                await notify_user(opportunities)
            await asyncio.sleep(10)  # Adjust frequency as needed
    except Exception as e:
        logging.error(f"Error in main loop: {e}")
    finally:
        await bot.close()

# Run the bot
if __name__ == "__main__":
    asyncio.run(main())