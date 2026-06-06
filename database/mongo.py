import os
from datetime import datetime
from urllib.parse import quote_plus
from pymongo import MongoClient
from dotenv import load_dotenv
from utils.logger import logger

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DB  = os.getenv("MONGODB_DB", "coindcx_bot")

client = None
db     = None

def get_db():
    global client, db
    if db is None:
        try:
            # Auto-encode special characters in password
            uri = encode_mongo_uri(MONGODB_URI)
            client = MongoClient(uri)
            db     = client[MONGODB_DB]
            client.admin.command('ping')
            logger.info("MongoDB connected successfully")
        except Exception as e:
            logger.error(f"MongoDB connection failed: {e}")
            raise
    return db
def encode_mongo_uri(uri: str) -> str:
    """
    Safely encode username and password in MongoDB URI.
    Handles special characters like @, #, $, %, etc.
    """
    try:
        # URI format: mongodb+srv://username:password@host/...
        prefix   = "mongodb+srv://"
        rest     = uri[len(prefix):]          # username:password@host/...
        at_index = rest.rfind('@')            # rfind handles @ in password
        userinfo = rest[:at_index]            # username:password
        hostpart = rest[at_index + 1:]        # host/...

        colon_index = userinfo.index(':')
        username    = userinfo[:colon_index]
        password    = userinfo[colon_index + 1:]

        encoded_user = quote_plus(username)
        encoded_pass = quote_plus(password)

        return f"{prefix}{encoded_user}:{encoded_pass}@{hostpart}"

    except Exception:
        # If parsing fails return original and let pymongo handle the error
        return uri

def save_order(order_data: dict) -> str:
    """
    Save a trade order to MongoDB.
    Returns inserted document id as string.
    """
    try:
        database   = get_db()
        collection = database["orders"]

        document = {
            # Signal info
            "symbol":        order_data.get("symbol"),
            "direction":     order_data.get("direction"),
            "score":         order_data.get("score"),
            "strength":      order_data.get("strength"),
            "reasons":       order_data.get("reasons", []),
            "timeframe":     order_data.get("timeframe"),
            "confirm_trend": order_data.get("confirm_trend"),

            # Price levels (USDT)
            "entry_usdt":    order_data.get("entry"),
            "target_usdt":   order_data.get("target"),
            "sl_usdt":       order_data.get("stop_loss"),
            "rsi":           order_data.get("rsi"),
            "atr":           order_data.get("atr"),

            # Price levels (INR)
            "entry_inr":     order_data.get("entry_inr"),
            "target_inr":    order_data.get("target_inr"),
            "sl_inr":        order_data.get("stop_loss_inr"),
            "inr_rate":      order_data.get("inr_rate"),

            # Order execution info
            "order_id":      order_data.get("order_id"),
            "order_status":  order_data.get("order_status", "placed"),
            "leverage":      order_data.get("leverage"),
            "quantity":      order_data.get("quantity"),
            "trade_amount":  order_data.get("trade_amount"),

            # Metadata
            "created_at":    datetime.utcnow(),
            "updated_at":    datetime.utcnow(),
        }

        result = collection.insert_one(document)
        logger.info(f"Order saved to MongoDB: {result.inserted_id}")
        return str(result.inserted_id)

    except Exception as e:
        logger.error(f"Failed to save order to MongoDB: {e}")
        return None


def update_order_status(order_id: str, status: str, extra: dict = None):
    """
    Update order status in MongoDB by CoinDCX order_id.
    """
    try:
        database   = get_db()
        collection = database["orders"]

        update = {
            "$set": {
                "order_status": status,
                "updated_at":   datetime.utcnow(),
            }
        }

        if extra:
            update["$set"].update(extra)

        collection.update_one({"order_id": order_id}, update)
        logger.info(f"Order {order_id} status updated to {status}")

    except Exception as e:
        logger.error(f"Failed to update order in MongoDB: {e}")


def get_open_orders() -> list:
    """
    Fetch all orders with status 'placed' or 'open'.
    """
    try:
        database   = get_db()
        collection = database["orders"]
        orders     = list(collection.find(
            {"order_status": {"$in": ["placed", "open"]}},
            {"_id": 0}
        ))
        return orders
    except Exception as e:
        logger.error(f"Failed to fetch open orders: {e}")
        return []