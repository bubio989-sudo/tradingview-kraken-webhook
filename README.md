TradingView → Render → Kraken webhook.
Set env vars on Render: KRAKEN_API_KEY, KRAKEN_API_SECRET, WEBHOOK_TOKEN, DEFAULT_PAIR (optional).
Start command: gunicorn webhook:app --bind 0.0.0.0:$PORT
