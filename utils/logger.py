import logging
import os
from datetime import datetime

# ── Setup ──────────────────────────────────────────────
LOG_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

# Generate date for daily logs
CURRENT_DATE = datetime.now().strftime("%Y-%m-%d")

# Common Formatter
FORMATTER = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')

# Shared Error File Handler (for error_logger and others)
ERROR_FILE_PATH = os.path.join(LOG_DIR, f'error_{CURRENT_DATE}.log')
error_file_handler = logging.FileHandler(ERROR_FILE_PATH, encoding='utf-8')
error_file_handler.setLevel(logging.ERROR)
error_file_handler.setFormatter(FORMATTER)

# Shared Console Handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(FORMATTER)

def setup_logger(name, log_file, level=logging.INFO, include_console=False):
    """
    Creates a logger that:
    1. Logs EVERYTHING (>= level) to its specific file.
    2. Logs ONLY ERRORS to the global error log.
    3. Prints EVERYTHING (>= level) to the console ONLY IF include_console=True.
    """
    _logger = logging.getLogger(name)
    _logger.setLevel(level)

    # 1. Module-specific file handler
    file_path = os.path.join(LOG_DIR, log_file)
    file_handler = logging.FileHandler(file_path, encoding='utf-8')
    file_handler.setFormatter(FORMATTER)
    _logger.addHandler(file_handler)
    
    # 2. Global error file handler
    _logger.addHandler(error_file_handler)
    
    # 3. Console handler
    if include_console:
        _logger.addHandler(console_handler)
        
    return _logger

# ── Export Loggers ─────────────────────────────────────

# General bot logger (Console + File)
logger = setup_logger('bot', f'bot_{CURRENT_DATE}.log', include_console=True)

# Scanner specific logger (FILE ONLY - high volume)
scanner_logger = setup_logger('scanner', f'scanner_{CURRENT_DATE}.log', include_console=False)

# Trading specific logger (Console + File - important)
trade_logger = setup_logger('trading', f'trading_{CURRENT_DATE}.log', include_console=True)
api_logger = setup_logger('coindcx', f'coindcx_{CURRENT_DATE}.log', include_console=False)

# ── CSV Ledger for PnL Tracking ────────────────────────
import csv

LEDGER_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'trading_ledger.csv')

def write_to_ledger(trade_data: dict):
    """
    Appends a single trade record to the CSV ledger.
    """
    file_exists = os.path.isfile(LEDGER_FILE)
    
    headers = [
        "timestamp", "symbol", "direction", "entry_price", "exit_price", 
        "quantity", "fees_usdt", "net_pnl_usdt", "reason"
    ]
    
    try:
        os.makedirs(os.path.dirname(LEDGER_FILE), exist_ok=True)
        with open(LEDGER_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            if not file_exists:
                writer.writeheader()
            
            # Extract necessary things
            row = {
                "timestamp":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "symbol":      trade_data.get("symbol"),
                "direction":   trade_data.get("direction"),
                "entry_price": trade_data.get("entry_price"),
                "exit_price":  trade_data.get("exit_price"),
                "quantity":    trade_data.get("quantity"),
                "fees_usdt":   trade_data.get("fees_usdt"),
                "net_pnl_usdt": trade_data.get("pnl_usdt"),
                "reason":      trade_data.get("reason")
            }
            writer.writerow(row)
    except Exception as e:
        logger.error(f"Failed to write to CSV ledger: {e}")