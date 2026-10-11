"""One candle fetcher (D91: one of each) — Bybit's main public host (its demo
host serves the same candles: measured 2026-10-11, 600 hourly bars, no OHLC
difference) and Hyperliquid's info endpoint on the network named. Bars are
oldest first, one per open time: {'t', 'o', 'h', 'l', 'c', 'v'}. Every
function takes the fetcher it reads with, so a spec never reaches the net."""
import json
import urllib.request

from common.http import get_json

BYBIT = 'https://api.bybit.com'
HL_INFO = {'mainnet': 'https://api.hyperliquid.xyz/info',
           'testnet': 'https://api.hyperliquid-testnet.xyz/info'}
BYBIT_LIMIT, HL_LIMIT = 1000, 5000
HL_INTERVALS = {1: '1m', 3: '3m', 5: '5m', 15: '15m', 30: '30m', 60: '1h',
                120: '2h', 240: '4h', 480: '8h', 720: '12h', 1440: '1d'}


def bybit_interval(minutes):
    return {1440: 'D', 10080: 'W'}.get(int(minutes), str(int(minutes)))


def hl_interval(minutes):
    """Hyperliquid's name for a bar length — or a refusal naming the ones it has."""
    name = HL_INTERVALS.get(int(minutes))
    if name is None:
        raise ValueError(f'Hyperliquid has no {minutes}-minute candle — one of {sorted(HL_INTERVALS)}')
    return name


def parse_bybit(rows):
    """Bybit answers newest first; bars run oldest first."""
    return [{'t': int(r[0]), 'o': float(r[1]), 'h': float(r[2]), 'l': float(r[3]),
             'c': float(r[4]), 'v': float(r[5]) if len(r) > 5 else 0.0} for r in reversed(rows)]


def parse_hl(rows):
    """Hyperliquid's candleSnapshot rows, oldest first, one per open time (a
    page seam can repeat one)."""
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: int(r['t'])):
        t = int(r['t'])
        if t in seen:
            continue
        seen.add(t)
        out.append({'t': t, 'o': float(r['o']), 'h': float(r['h']), 'l': float(r['l']),
                    'c': float(r['c']), 'v': float(r.get('v') or 0.0)})
    return out


def _dedupe(bars):
    seen, out = set(), []
    for b in sorted(bars, key=lambda b: b['t']):
        if b['t'] not in seen:
            seen.add(b['t'])
            out.append(b)
    return out


def hl_info(network='testnet', fetch=get_json):
    """A callable posting a body to Hyperliquid's info endpoint."""
    def post(body):
        return fetch(urllib.request.Request(HL_INFO[network], data=json.dumps(body).encode(),
                                            headers={'Content-Type': 'application/json'}))
    return post


def candles(venue, market_type, symbol, minutes, start_ms, end_ms, fetch=get_json, network='testnet', info=None):
    """The bars between start_ms and end_ms, paged forward. Hyperliquid's on
    `network` (the fleet's own: testnet by the owner's directive)."""
    if venue == 'hyperliquid':
        post = info or hl_info(network, fetch)
        interval, rows, cursor = hl_interval(minutes), [], int(start_ms)
        step = int(minutes) * 60_000 * HL_LIMIT
        while cursor < end_ms:
            rows += post({'type': 'candleSnapshot', 'req': {'coin': symbol, 'interval': interval,
                                                            'startTime': cursor, 'endTime': min(cursor + step, end_ms)}}) or []
            cursor += step
        return parse_hl(rows)
    bars, cursor, step = [], int(start_ms), int(minutes) * 60_000 * BYBIT_LIMIT
    while cursor < end_ms:
        d = fetch(f'{BYBIT}/v5/market/kline?category={market_type}&symbol={symbol}'
                  f'&interval={bybit_interval(minutes)}&start={cursor}&end={min(cursor + step, end_ms)}&limit={BYBIT_LIMIT}')
        bars += parse_bybit((d.get('result') or {}).get('list') or [])
        cursor += step
    return _dedupe(bars)


def last_candles(market_type, symbol, minutes, n, end_ms=None, fetch=get_json):
    """Bybit's last `n` bars up to end_ms (now when None), paged backward,
    oldest first."""
    out, end = {}, end_ms
    while len(out) < n:
        need = min(BYBIT_LIMIT, n - len(out))
        url = (f'{BYBIT}/v5/market/kline?category={market_type}&symbol={symbol}'
               f'&interval={bybit_interval(minutes)}&limit={need}' + (f'&end={int(end)}' if end else ''))
        rows = ((fetch(url).get('result') or {}).get('list')) or []
        if not rows:
            break
        for b in parse_bybit(rows):
            out[b['t']] = b
        end = min(int(r[0]) for r in rows) - 1
        if len(rows) < need:
            break
    return [out[t] for t in sorted(out)][-n:]
