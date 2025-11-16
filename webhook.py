# webhook.py
import os
import logging
from decimal import Decimal, ROUND_DOWN
from flask import Flask, request, jsonify
import krakenex

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Environment variables (set these in Render)
KRAKEN_API_KEY = os.getenv("KRAKEN_API_KEY")
KRAKEN_API_SECRET = os.getenv("KRAKEN_API_SECRET")
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN")  # Bearer token for TradingView header auth
DEFAULT_PAIR = os.getenv("DEFAULT_PAIR", "XBTUSD")  # Kraken-style pair fallback

kraken = krakenex.API()
if KRAKEN_API_KEY and KRAKEN_API_SECRET:
    kraken.key = KRAKEN_API_KEY
    kraken.secret = KRAKEN_API_SECRET

def normalize_pair(symbol: str) -> str:
    """Convert formats like 'BTC-USD' or 'BTCUSD' to Kraken style 'XBTUSD'."""
    if not symbol:
        return DEFAULT_PAIR
    p = symbol.upper().replace('-', '').replace('_', '').replace('/', '')
    p = p.replace('BTC', 'XBT')  # Kraken uses XBT for Bitcoin
    return p

def parse_message(payload):
    """
    Accept either:
      - a JSON payload with keys (symbol, action, amount), or
      - a string message like 'symbol: BTC-USD; action: buy; amount: 10.0'
    Returns dict: {'symbol':..., 'action': 'buy'|'sell', 'amount': float} or None.
    """
    try:
        if isinstance(payload, dict):
            # if TradingView sends {"message": "symbol: BTC-USD; ..."}
            if payload.get("message") and isinstance(payload["message"], str):
                msg = payload["message"]
            else:
                s = payload.get("symbol") or payload.get("ticker") or payload.get("pair")
                a = payload.get("action")
                amt = payload.get("amount")
                if s and a and amt is not None:
                    return {"symbol": s, "action": a.lower(), "amount": float(amt)}
                msg = None
        elif isinstance(payload, str):
            msg = payload
        else:
            msg = None
    except Exception:
        msg = None

    if not msg:
        return None

    parts = [p.strip() for p in msg.split(';') if p.strip()]
    data = {}
    for part in parts:
        if ':' in part:
            k, v = part.split(':', 1)
            data[k.strip().lower()] = v.strip()

    symbol = data.get('symbol') or data.get('pair')
    action = data.get('action')
    amount = data.get('amount')
    if not (symbol and action and amount):
        return None
    try:
        amount = float(amount)
    except ValueError:
        return None
    return {"symbol": symbol, "action": action.lower(), "amount": amount}

def get_last_price(pair: str) -> float:
    """Query Kraken public ticker for last price."""
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
    """
    Place a Kraken market order.
    volume is base-currency amount (e.g., BTC).
    """
    order_type = 'buy' if action == 'buy' else 'sell'
    # Round volume conservatively (8 decimals)
    vol_str = str(Decimal(volume).quantize(Decimal('0.00000001'), rounding=ROUND_DOWN))
    params = {
        'pair': pair,
        'type': order_type,
        'ordertype': 'market',
        'volume': vol_str
    }
    res = kraken.query_private('AddOrder', params)
    return res

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

@app.route("/webhook", methods=["POST"])
def webhook():
    # Simple Bearer token auth
    auth = request.headers.get('Authorization', '')
    if WEBHOOK_TOKEN:
        expected = f"Bearer {WEBHOOK_TOKEN}"
        if auth != expected:
            logging.warning("Unauthorized webhook request. Authorization header mismatch.")
            return jsonify({"status": "error", "message": "unauthorized"}), 401

    # Get payload
    payload = None
    try:
        payload = request.get_json(force=True, silent=True) or request.data.decode('utf-8')
    except Exception:
        payload = request.data.decode('utf-8') or None

    parsed = parse_message(payload)
    if not parsed:
        logging.error("Failed to parse payload: %s", payload)
        return jsonify({"status": "error", "message": "invalid payload"}), 400

    symbol = normalize_pair(parsed['symbol'])
    action = parsed['action']
    usd_amount = float(parsed['amount'])

    logging.info("Order request parsed: pair=%s action=%s usd_amount=%s", symbol, action, usd_amount)

    try:
        price = get_last_price(symbol)
    except Exception as e:
        logging.exception("Failed to fetch price: %s", str(e))
        return jsonify({"status": "error", "message": "price_fetch_failed", "error": str(e)}), 500

    # Convert USD amount -> base currency volume
    volume = usd_amount / price
    volume = float(Decimal(volume).quantize(Decimal('0.00000001'), rounding=ROUND_DOWN))

    logging.info("Placing market order: %s %s @ price=%s => volume=%s", action, symbol, price, volume)

    try:
        result = place_market_order(symbol, action, volume)
        logging.info("Order placed: %s", result)
        return jsonify({"status": "success", "order_result": result}), 200
    except Exception as e:
        logging.exception("Order failed: %s", str(e))
        return jsonify({"status": "error", "message": "order_failed", "error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
