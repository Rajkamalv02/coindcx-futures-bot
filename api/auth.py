import hmac
import hashlib
import time
import json
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY    = os.getenv("COINDCX_API_KEY")
API_SECRET = os.getenv("COINDCX_API_SECRET")

# BUG-10 FIX: Validate API keys on load to prevent cryptic NoneType errors later
if not API_KEY or not API_SECRET:
    raise ValueError("CRITICAL: COINDCX_API_KEY or COINDCX_API_SECRET not found in .env file")

def get_auth_headers(body: dict) -> tuple:
    """For spot/user endpoints — uses X-AUTH-SIGN"""
    json_body = json.dumps(body, separators=(',', ':'))
    signature = hmac.new(
        API_SECRET.encode('utf-8'),
        json_body.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    headers = {
        'Content-Type':  'application/json',
        'X-AUTH-APIKEY': API_KEY,
        'X-AUTH-SIGN':   signature
    }
    return headers, json_body


def get_futures_auth_headers(body: dict) -> tuple:
    """For futures trading endpoints — uses X-AUTH-SIGNATURE"""
    json_body = json.dumps(body, separators=(',', ':'))
    signature = hmac.new(
        API_SECRET.encode('utf-8'),
        json_body.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    headers = {
        'Content-Type':    'application/json',
        'X-AUTH-APIKEY':   API_KEY,
        'X-AUTH-SIGNATURE': signature
    }
    return headers, json_body


def get_timestamp() -> int:
    return int(time.time() * 1000)