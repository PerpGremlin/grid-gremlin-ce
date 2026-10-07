# Public candle fetch for the backtest CLI. No keys, no signing — market data.
# HL is testnet-only by the owner's directive, so the candles are the
# testnet's own: the prices the fleet actually faces there (thinner than
# mainnet's). If HL mainnet is ever opened this takes the fleet's flag.
import json
import urllib.request

from .client import BASE_URLS

INTERVALS = {1: '1m', 3: '3m', 5: '5m', 15: '15m', 30: '30m', 60: '1h',
             120: '2h', 240: '4h', 480: '8h', 720: '12h', 1440: '1d'}
CANDLE_LIMIT = 5000           # the venue answers at most this many per call


def interval_for(bar_minutes):
    """The venue's name for a bar length — or a refusal naming the ones it has."""
    name = INTERVALS.get(int(bar_minutes))
    if name is None:
        raise ValueError(f'Hyperliquid has no {bar_minutes}-minute candle — '
                         f'one of {sorted(INTERVALS)}')
    return name


def parse_candles(rows):
    """The venue's candleSnapshot rows -> bars oldest first, one per open
    time (a page boundary can repeat a candle)."""
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: int(r['t'])):
        t = int(r['t'])
        if t in seen:
            continue
        seen.add(t)
        out.append({'t': t, 'o': float(r['o']), 'h': float(r['h']),
                    'l': float(r['l']), 'c': float(r['c'])})
    return out


def _info(body, env):
    req = urllib.request.Request(BASE_URLS[env] + '/info',
                                 data=json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def fetch_bars(symbol, bar_minutes, start_ms, end_ms, env='testnet'):
    interval = interval_for(bar_minutes)
    rows, cursor = [], start_ms
    step = bar_minutes * 60_000 * CANDLE_LIMIT
    while cursor < end_ms:
        rows += _info({'type': 'candleSnapshot',
                       'req': {'coin': symbol, 'interval': interval,
                               'startTime': cursor,
                               'endTime': min(cursor + step, end_ms)}}, env)
        cursor += step
    return parse_candles(rows)


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
