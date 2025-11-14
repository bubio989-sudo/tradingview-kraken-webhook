import os
import time
import base64
import hashlib
import hmac
import urllib.parse
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# ================== RATE LIMITING ==================
LAST_HIT = {'ts': 0}
RATE_LIMIT_SECONDS = int(os.getenv('WEBHOOK_RATE_LIMIT_SEC', '60'))

# ================== KRAKEN API CREDENTIALS ==================
KRAKEN_API_KEY = os.getenv('KRAKEN_API_KEY')
KRAKEN_API_SECRET = os.getenv('KRAKEN_API_SECRET')
KRAKEN_API_URL = 'https://api.kraken.com'

# ================== KRAKEN API SIGNATURE ==================
def get_kraken_signature(urlpath, data, secret):
    postdata = urllib.parse.urlencode(data)
    encoded = (str(data['nonce']) + postdata).encode()
    message = urlpath.encode() + hashlib.sha256(encoded).digest()
    mac = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    sigdigest = base64.b64encode(mac.digest())
    return sigdigest.decode()

# ================== KRAKEN API REQUEST ==================
def kraken_request(uri_path, data):
    headers = {
        'API-Key': KRAKEN_API_KEY,
        'API-Sign': get_kraken_signature(uri_path, data, KRAKEN_API_SECRET)
    }
    response = requests.post(KRAKEN_API_URL + uri_path, headers=headers, data=data)
    return response.json()

# ================== ROUTES ==================
@app.route('/')
def home():
    return jsonify({
        'status': 'Kraken Webhook Server Running',
        'endpoints': ['/webhook', '/balance']
    })

@app.route('/webhook', methods=['POST'])
def webhook():
    global LAST_HIT
    
    # Rate limit check
    now = time.time()
    if now - LAST_HIT['ts'] < RATE_LIMIT_SECONDS:
        return jsonify({
            'status': 'ignored',
            'reason': 'rate_limited',
            'wait_seconds': round(RATE_LIMIT_SECONDS - (now - LAST_HIT['ts']), 1)
        }), 200
    
    LAST_HIT['ts'] = now
    
    try:
        data = request.get_json()
        if not data or 'message' not in data:
            return jsonify({'error': 'No message field in request'}), 400
        
        # Parse TradingView alert message
        msg = data['message']
        parts = {}
        for pair in msg.split(';'):
            if ':' in pair:
                key, val = pair.split(':', 1)
                parts[key.strip()] = val.strip()
        
        symbol = parts.get('symbol', 'BTC-USD')
        action = parts.get('action', '').lower()
        amount = float(parts.get('amount', 10))
        
        if action not in ['buy', 'sell']:
            return jsonify({'error': 'Invalid action. Must be buy or sell'}), 400
        
        # Use symbol as-is (BTC-USD, BTC/USD, etc.)
        # Kraken will accept various formats
        
        # Place market order on Kraken
        order_data = {
            'nonce': str(int(time.time() * 1000)),
            'ordertype': 'market',
            'type': action,
            'volume': amount / 100000,  # Convert USD to BTC volume estimate
            'pair': symbol.replace('-', '').replace('/', '')  # BTCUSD format
        }
        
        result = kraken_request('/0/private/AddOrder', order_data)
        
        if result.get('error'):
            return jsonify({
                'status': 'error',
                'kraken_error': result['error']
            }), 400
        
        return jsonify({
            'status': 'success',
            'message': f'{action.upper()} order placed',
            'order_id': result['result']['txid'][0] if result.get('result', {}).get('txid') else None,
            'pair': symbol,
            'volume': order_data['volume'],
            'price': result['result']['descr']['price'] if result.get('result', {}).get('descr') else None
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/balance', methods=['GET'])
def balance():
    try:
        data = {'nonce': str(int(time.time() * 1000))}
        result = kraken_request('/0/private/Balance', data)
        
        if result.get('error'):
            return jsonify({'error': result['error']}), 400
        
        return jsonify(result['result']), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
