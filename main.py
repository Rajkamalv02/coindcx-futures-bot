import schedule
import time
from config.settings import WATCHLIST, SCAN_INTERVAL_MINUTES
from api.fetcher import get_active_instruments, get_candles
from signals.indicators import build_dataframe, calculate_indicators
from signals.scanner import detect_signal
from alerts.telegram import send_signal
from utils.logger import logger


def get_symbols() -> list:
    if WATCHLIST:
        return WATCHLIST
    # Auto fetch filtered symbols — no penny coins
    from api.fetcher import get_filtered_symbols
    return get_filtered_symbols(min_price=0.5, min_volume=500000)

def run_scanner():
    logger.info("=" * 50)
    logger.info("Scanner started...")

    symbols = get_symbols()
    logger.info(f"Scanning {len(symbols)} symbols")

    for symbol in symbols:
        try:
            candles = get_candles(symbol)
            df      = build_dataframe(candles)
            df      = calculate_indicators(df)
            signal  = detect_signal(df, symbol)

            if signal:
                send_signal(signal)
            else:
                logger.info(f"No signal: {symbol}")

        except Exception as e:
            logger.error(f"Error processing {symbol}: {e}")

    logger.info("Scanner completed.")
    logger.info("=" * 50)


if __name__ == "__main__":
    logger.info("CoinDCX Futures EMA Bot started")

    # Run once immediately on start
    run_scanner()

    # Then run every X minutes
    schedule.every(SCAN_INTERVAL_MINUTES).minutes.do(run_scanner)

    while True:
        schedule.run_pending()
        time.sleep(1)