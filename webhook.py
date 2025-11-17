# webhook.py
import os
import logging
from decimal import Decimal, ROUND_DOWN
from flask import Flask, request, jsonify
import krakenex

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Env vars
KRAKEN_API_KEY = os.getenv("KRAKEN_API_KEY")
KRAKEN_API_SECRET = os.getenv("KRAKEN_API_SECRET")
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN")  # Bearer token
DEFAULT_PAIR = os.getenv("DEFAULT_PAIR", "XBTUSD")  # Kraken pair fallback

kraken = krakenex.API()
if KRAKEN_API_KEY and KRAKEN_API_SECRET:
    kraken.key = KRAKEN_API_KEY
    kraken.secret = KRAKEN_API_SECRET

def normalize_pair(symbol: str) -> str:
    if not symbol:
        return DEFAULT_PAIR
    p = symbol.upper().replace('-', '').replace('_', '').replace('/', '')
    p = p.replace('BTC', 'XBT')  # Kraken uses XBT
    return p

def parse_message(payload):
    # Accept JSON {symbol, action, amount} or string "symbol: BTC-USD; action: buy; amount: 10"
    if isinstance(payload, dict):
        if payload.get('symbol') and payload.get('action') and payload.get('amount') is not None:
            try:
                return {"symbol": payload['symbol'], "action": payload['action'].lower(), "amount": float(payload['amount'])}
            except:
                return None
        if isinstance(payload.get('message'), str):
            msg = payload['message']
        else:
            msg = None
    elif isinstance(payload, str):
        msg = payload
    else:
        msg = None

    if not msg:
        return None

    parts = [p.strip() for p in msg.split(';') if p.strip()]
    data = {}
    for part in parts:
        if ':' in part:
            k, v = part.split(':', 1)
            data[k.strip().lower()] = v.strip()
    symbol = data.get('symbol')
    action = data.get('action')
    amount = data.get('amount')
    if not (symbol and action and amount):
        return None
    try:
        return {"symbol": symbol, "action": action, "amount": float(amount)}
    except:
        return None

def get_last_price(pair: str) -> float:
    res = kraken.query_public('Ticker', {'pair': pair})
    if res.get('error'):
        raise Exception("Kraken API error: " + str(res['error']))
    result = res.get('result')
    if not result:
        raise Exception("No ticker result for pair " + pair)
    key = list(result.keys())[0]
    last = result[key]['c'][0]
    return float(last)

def place_market_order(pair: str, action: str, volume: float):
    order_type = 'buy' if action == 'buy' else 'sell'
    params = {
        'pair': pair,
        'type': order_type,
        'ordertype': 'market',
        'volume': str(Decimal(volume).quantize(Decimal('0.00000001'), rounding=ROUND_DOWN))
    }
    return kraken.query_private('AddOrder', params)

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status":"ok"})

@app.route("/webhook", methods=["POST"])
def webhook():
    # Authorization header check (TradingView will send as custom header)
    auth = request.headers.get('Authorization', '')
    if WEBHOOK_TOKEN:
        expected = f"Bearer {WEBHOOK_TOKEN}"
        if auth != expected:
            logging.warning("Unauthorized request")
            return jsonify({"status":"error","message":"unauthorized"}), 401

    # load JSON if possible, else use raw body
    payload = None
    try:
        payload = request.get_json(force=True, silent=True) or request.data.decode('utf-8')
    except:
        payload = request.data.decode('utf-8') if request.data else None

    parsed = parse_message(payload)
    if not parsed:
        return jsonify({"status":"error","message":"invalid payload"}), 400

    symbol = normalize_pair(parsed['symbol'])
    action = parsed['action']
    usd_amount = float(parsed['amount'])
    logging.info("Request parsed: %s %s %s", symbol, action, usd_amount)

    try:
        price = get_last_price(symbol)
    except Exception as e:
        logging.exception("Price fetch failed")
        return jsonify({"status":"error","message":"price_fetch_failed","error":str(e)}), 500

    volume = usd_amount / price
    volume = float(Decimal(volume).quantize(Decimal('0.00000001'), rounding=ROUND_DOWN))

    logging.info("Placing market order pair=%s type=%s volume=%s price=%s", symbol, action, volume, price)
    try:
        result = place_market_order(symbol, action, volume)
        logging.info("Order result: %s", result)
        return jsonify({"status":"success","order_result":result}), 200
    except Exception as e:
        logging.exception("Order failed")
        return jsonify({"status":"error","message":"order_failed","error":str(e)}), 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
