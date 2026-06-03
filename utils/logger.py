import logging
import os

LOG_DIR  = os.path.join(os.path.dirname(__file__), '..', 'data', 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'bot.log')

os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()          # also prints to console
    ]
)

logger = logging.getLogger(__name__)