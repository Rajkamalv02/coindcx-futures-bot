import os
from datetime import datetime, timezone
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

def encode_mongo_uri(uri: str | None) -> str:
    """
    Safely encode username and password in MongoDB URI.
    Handles special characters like @, #, $, %, etc.
    """
    if not uri:
        return ""
    try:
        # URI format: mongodb+srv://username:password@host/...
        prefix   = "mongodb+srv://"
        rest     = uri[len(prefix):]          # username:password@host/...
        at_index = rest.rfind('@')            # rfind handles @ in password
        userinfo = rest[:at_index]            # username:password
        hostpart = rest[at_index + 1:]        # host/...

        if ':' not in userinfo:
            return uri

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
            "is_active":     True if order_data.get("order_status") == "filled" else False,
            "leverage":      order_data.get("leverage"),
            "quantity":      order_data.get("quantity"),
            "trade_amount":  order_data.get("trade_amount"),

            # Stats (populated on close)
            "exit_price":    None,
            "exit_time":     None,
            "fees_usdt":     0.0,
            "realized_pnl_usdt": 0.0,
            "exit_reason":   None,

            # Metadata
            "created_at":    datetime.now(timezone.utc),
            "updated_at":    datetime.now(timezone.utc),
        }

        result = collection.insert_one(document)
        logger.info(f"Order saved to MongoDB: {result.inserted_id}")
        return str(result.inserted_id)

    except Exception as e:
        logger.error(f"Failed to save order to MongoDB: {e}")
        return ""


def update_order_status(order_id: str, status: str, extra: dict | None = None):
    """
    Update order status in MongoDB by CoinDCX order_id.
    """
    try:
        database   = get_db()
        collection = database["orders"]

        update = {
            "$set": {
                "order_status": status,
                "updated_at":   datetime.now(timezone.utc),
            }
        }

        # If it moves to filled, mark it as an active trade
        if status == "filled":
            update["$set"]["is_active"] = True

        if extra:
            update["$set"].update(extra)

        collection.update_one({"order_id": order_id}, update)
        logger.info(f"Order {order_id} status updated to {status}")

    except Exception as e:
        logger.error(f"Failed to update order in MongoDB: {e}")


def get_open_orders() -> list:
    """
    Fetch all orders with status 'placed' or 'open'.
    These are orders WAITING to be filled.
    """
    try:
        database   = get_db()
        collection = database["orders"]
        orders     = list(collection.find(
            {"order_status": {"$in": ["placed", "open", "initial", "init"]}},
            {"_id": 0}
        ))
        return orders
    except Exception as e:
        logger.error(f"Failed to fetch open orders: {e}")
        return []


def get_active_trades() -> list:
    """
    Fetch all 'filled' orders that haven't been closed (TP/SL not hit yet).
    """
    try:
        database   = get_db()
        collection = database["orders"]
        trades     = list(collection.find(
            {"is_active": True, "order_status": "filled"},
            {"_id": 0}
        ))
        return trades
    except Exception as e:
        logger.error(f"Failed to fetch active trades: {e}")
        return []


def mark_trade_closed(order_id: str, exit_data: dict):
    """
    Update a filled trade with exit details and mark it inactive.
    """
    try:
        database   = get_db()
        collection = database["orders"]

        update = {
            "$set": {
                "is_active":         False,
                "order_status":      "closed",
                "exit_price":        exit_data.get("exit_price"),
                "exit_time":         datetime.now(timezone.utc),
                "fees_usdt":         exit_data.get("fees_usdt", 0.0),
                "realized_pnl_usdt": exit_data.get("pnl_usdt", 0.0),
                "exit_reason":       exit_data.get("reason", "unknown"),
                "updated_at":        datetime.now(timezone.utc),
            }
        }

        collection.update_one({"order_id": order_id}, update)
        logger.info(f"Trade {order_id} marked CLOSED. PnL: {exit_data.get('pnl_usdt')}")

    except Exception as e:
        logger.error(f"Failed to close trade in MongoDB: {e}")