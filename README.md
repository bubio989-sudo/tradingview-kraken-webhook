Simple Flask webhook to receive TradingView alerts and place Kraken market orders.
Set env vars: KRAKEN_API_KEY, KRAKEN_API_SECRET, WEBHOOK_TOKEN, DEFAULT_PAIR (optional).
Start: gunicorn webhook:app --bind 0.0.0.0:$PORT
