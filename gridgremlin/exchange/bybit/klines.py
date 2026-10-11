# Bybit's public instrument spec (no key). Candles and funding live in ggdata (D91).
import json
import urllib.parse
import urllib.request

PUBLIC_HOST = 'https://api-demo.bybit.com'   # public data; demo-phase posture


def fetch_instrument(category, symbol):
    q = urllib.parse.urlencode({'category': category, 'symbol': symbol})
    with urllib.request.urlopen(
            f'{PUBLIC_HOST}/v5/market/instruments-info?{q}', timeout=20) as r:
        return json.load(r)['result']['list'][0]
