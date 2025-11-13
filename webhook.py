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

def to_kraken_pair(symbol):
    """Map common symbol formats to Kraken pair codes"""
    s = symbol.replace('-', '').replace('/', '').upper()
    mapping = {
        'BTCUSD': 'XBTUSD',
        'BTCUSDT': 'XBTUSDT',
        'XBTUSD': 'XBTUSD',
        'ETHUSD': 'ETHUSD',
        'ETHUSDT': 'ETHUSDT',
    }
    return mapping.get(s, s)

def place_kraken_order(pair, side, amount_usd):
    """Place market order on Kraken"""
    try:
        # Convert to Kraken pair format
        kraken_pair = to_kraken_pair(pair)
        
        print(f"Placing {side} order for {kraken_pair} with ${amount_usd}")
        
        # Get current price
        ticker_response = kraken.query_public('Ticker', {'pair': kraken_pair})
        
        if ticker_response.get('error'):
            return {'success': False, 'error': f"Ticker error: {ticker_response['error']}"}
        
        # Get first result key (Kraken returns pair with possible alias)
        result = ticker_response['result']
        result_key = next(iter(result.keys()))
        current_price = float(result[result_key]['c'][0])
        
        # Calculate volume
        volume = round(amount_usd / current_price, 8)
        
        print(f"Current price: ${current_price}, Volume: {volume}")
        
        # Place order
        order_response = kraken.query_private('AddOrder', {
            'ordertype': 'market',
            'type': side,
            'volume': str(volume),
            'pair': kraken_pair
        })
        
        if order_response.get('error'):
            return {'success': False, 'error': order_response['error']}
        
        # Extract transaction ID
        txid = None
        if isinstance(order_response.get('result', {}).get('txid'), list):
            if order_response['result']['txid']:
                txid = order_response['result']['txid'][0]
        
        print(f"Order placed successfully. TxID: {txid}")
        
        return {
            'success': True,
            'order_id': txid,
            'volume': volume,
            'price': current_price
        }
    
    except Exception as e:
        print(f"Exception in place_kraken_order: {str(e)}")
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
        
        print(f"Received webhook data: {data}")
        
        # Parse alert message (format: "symbol: BTC-USD; action: buy; amount: 10.0")
        message = data.get('message', '')
        
        if not message:
            return jsonify({'error': 'No message field in request'}), 400
        
        print(f"Parsing message: {message}")
        
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
        
        print(f"Parsed - Symbol: {symbol}, Action: {action}, Amount: {amount}")
        
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
        print(f"Exception in webhook: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
