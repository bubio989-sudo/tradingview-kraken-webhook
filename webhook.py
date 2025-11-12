import os
import time
import hashlib
import hmac
import base64
import urllib.parse
from flask import Flask, request, jsonify
import krakenex

app = Flask(__name__)

# Kraken API credentials from environment variables
API_KEY = os.environ.get('KRAKEN_API_KEY')
API_SECRET = os.environ.get('KRAKEN_API_SECRET')

if not API_KEY or not API_SECRET:
    raise ValueError("Missing KRAKEN_API_KEY or KRAKEN_API_SECRET environment variables")

# Initialize Kraken client
kraken = krakenex.API(key=API_KEY, secret=API_SECRET)

def get_kraken_signature(urlpath, data, secret):
    """Generate Kraken API signature"""
    postdata = urllib.parse.urlencode(data)
    encoded = (str(data['nonce']) + postdata).encode()
    message = urlpath.encode() + hashlib.sha256(encoded).digest()
    signature = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    return base64.b64encode(signature.digest()).decode()

def place_kraken_order(pair, side, amount_usd):
    """Place market order on Kraken"""
    try:
        # Kraken uses different pair format: XBTUSD for BTC/USD
        kraken_pair = pair.replace('-', '').replace('BTC', 'XBT').replace('USD', 'USD')
        
        # Get current price to calculate volume
        ticker_response = kraken.query_public('Ticker', {'pair': kraken_pair})
        if ticker_response.get('error'):
            return {'success': False, 'error': f"Ticker error: {ticker_response['error']}"}
        
        current_price = float(ticker_response['result'][kraken_pair]['c'][0])
        volume = round(amount_usd / current_price, 8)  # BTC volume
        
        # Prepare order
        nonce = str(int(time.time() * 1000))
        order_data = {
            'nonce': nonce,
            'ordertype': 'market',
            'type': side,  # 'buy' or 'sell'
            'volume': str(volume),
            'pair': kraken_pair
        }
        
        # Place order
        response = kraken.query_private('AddOrder', order_data)
        
        if response.get('error'):
            return {'success': False, 'error': response['error']}
        
        return {
            'success': True,
            'order_id': response['result']['txid'][0] if response['result'].get('txid') else None,
            'volume': volume,
            'price': current_price
        }
    
    except Exception as e:
        return {'success': False, 'error': str(e)}

@app.route('/')
def home():
    return jsonify({
        'status': 'Kraken Webhook Server Running',
        'endpoints': ['/webhook', '/balance']
    })

@app.route('/balance', methods=['GET'])
def get_balance():
    """Check account balance"""
    try:
        response = kraken.query_private('Balance')
        if response.get('error'):
            return jsonify({'error': response['error']}), 400
        return jsonify({'balance': response['result']})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/webhook', methods=['POST'])
def webhook():
    """Receive TradingView alerts and execute trades"""
    try:
        data = request.get_json()
        
        # Parse alert message (format: "symbol: BTC-USD; action: buy; amount: 10.0")
        message = data.get('message', '')
        
        # Extract fields
        parts = message.split(';')
        symbol = None
        action = None
        amount = None
        
        for part in parts:
            if ':' in part:
                key, value = part.split(':', 1)
                key = key.strip().lower()
                value = value.strip()
                
                if key == 'symbol':
                    symbol = value
                elif key == 'action':
                    action = value.lower()
                elif key == 'amount':
                    amount = float(value)
        
        if not all([symbol, action, amount]):
            return jsonify({'error': 'Missing required fields: symbol, action, amount'}), 400
        
        # Execute order
        result = place_kraken_order(symbol, action, amount)
        
        if result['success']:
            return jsonify({
                'status': 'success',
                'message': f"{action.upper()} order placed",
                'order_id': result.get('order_id'),
                'volume': result.get('volume'),
                'price': result.get('price')
            })
        else:
            return jsonify({'error': result['error']}), 400
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
