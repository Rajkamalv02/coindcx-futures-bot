import hmac
import hashlib
import time
import json
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY    = os.getenv("COINDCX_API_KEY")
API_SECRET = os.getenv("COINDCX_API_SECRET")

def get_auth_headers(body: dict) -> tuple:
    """
    Generate HMAC signature and return headers + json body.
    Returns: (headers dict, json_body string)
    """
    json_body = json.dumps(body, separators=(',', ':'))

    signature = hmac.new(
        API_SECRET.encode('utf-8'),
        json_body.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    headers = {
        'Content-Type': 'application/json',
        'X-AUTH-APIKEY': API_KEY,
        'X-AUTH-SIGN': signature
    }

    return headers, json_body


def get_timestamp() -> int:
    return int(time.time() * 1000)