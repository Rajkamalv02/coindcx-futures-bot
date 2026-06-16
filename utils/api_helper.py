import requests
import json
from utils.logger import api_logger

def log_api_call(method, url, headers, data=None, params=None, response=None):
    """Logs the details of an API request and response for critical trading endpoints."""
    # Only log if it's related to trading/account (ignore high-volume market data)
    important_keywords = [
        'order', 
        'leverage', 
        'accounts', 
        'balance', 
        'position'
    ]
    is_important = any(k in url.lower() for k in important_keywords)
    
    if not is_important:
        return

    try:
        api_logger.info("-" * 80)
        api_logger.info(f"REQUEST: {method} {url}")
        if params:
            api_logger.info(f"PARAMS: {params}")
        if data:
            # Mask sensitive info if needed, but for debugging usually keep it
            api_logger.info(f"BODY: {data}")
        
        if response is not None:
            api_logger.info(f"RESPONSE STATUS: {response.status_code}")
            try:
                # Try to log pretty-printed JSON
                api_logger.info(f"RESPONSE BODY: {json.dumps(response.json(), indent=2)}")
            except:
                api_logger.info(f"RESPONSE BODY: {response.text}")
        api_logger.info("-" * 80)
    except Exception as e:
        api_logger.error(f"Logging error: {e}")

class APISession:
    """A wrapper for requests to automatically log all CoinDCX hits."""
    
    @staticmethod
    def get(url, **kwargs):
        resp = requests.get(url, **kwargs)
        log_api_call("GET", url, kwargs.get('headers'), params=kwargs.get('params'), response=resp)
        return resp

    @staticmethod
    def post(url, **kwargs):
        resp = requests.post(url, **kwargs)
        log_api_call("POST", url, kwargs.get('headers'), data=kwargs.get('data'), response=resp)
        return resp
