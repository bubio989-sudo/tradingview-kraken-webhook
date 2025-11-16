from flask import Flask, request, jsonify
import krakenex
from pykrakenapi import KrakenAPI
import logging

app = Flask(__name__)

# Initialize Kraken API client
kraken = krakenex.API()
kraken.load_key('path/to/your/kraken.key')  # You'll need to create this file with your API keys
k = KrakenAPI(kraken)

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        print(f"Received webhook: {data}")
        
        # Parse the message from TradingView
        message = data.get('message', '')
        parsed_data = parse_tradingview_message(message)
        
        if parsed_data:
            # Place order on Kraken
            result = place_kraken_order(parsed_data)
            return jsonify({"status": "success", "result": result})
        else:
            return jsonify({"status": "error", "message": "Failed to parse message"}), 400
            
    except Exception as e:
        logging.error(f"Error processing webhook: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

def parse_tradingview_message(message):
    """Parse the TradingView alert message"""
    try:
        # Expected format: "symbol: BTC-USD; action: buy; amount: 10.0"
        parts = message.split(';')
        data = {}
        for part in parts:
            key, value = part.split(':')
            data[key.strip()] = value.strip()
        return data
    except Exception as e:
        logging.error(f"Error parsing message: {str(e)}")
        return None

def place_kraken_order(order_data):
    """Place an order on Kraken"""
    try:
        symbol = order_data['symbol']
        action = order_data['action']
        amount = float(order_data['amount'])
        
        # Convert action to Kraken format
        type = 'buy' if action == 'buy' else 'sell'
        
        # Place market order
        result = k.add_standard_order(
            pair=symbol,
            type=type,
            ordertype='market',
            volume=amount
        )
        
        return result
    except Exception as e:
        logging.error(f"Error placing Kraken order: {str(e)}")
        raise e

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
