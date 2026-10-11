# Hyperliquid's public instrument spec (no key). Candles live in ggdata (D91),
# read on the fleet's own network — testnet by the owner's directive.
import json
import urllib.request

from .client import BASE_URLS

def _info(body, env):
    req = urllib.request.Request(BASE_URLS[env] + '/info',
                                 data=json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def fetch_instrument(symbol, env='testnet'):
    """The universe entry for a coin — or a refusal naming the venue's way."""
    meta = _info({'type': 'meta'}, env)
    for entry in meta['universe']:
        if entry['name'] == symbol:
            return entry
    from ...apply import not_listed
    raise LookupError(not_listed(
        symbol, 'Hyperliquid lists no such market here — its markets are '
                'named by the coin alone (BTC, ETH), and the testnet lists '
                'fewer coins'))
