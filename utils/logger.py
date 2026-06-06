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