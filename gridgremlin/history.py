# Public market history for rehearsals (H7): Bybit's candles and funding
# rates and Hyperliquid's funding, fetched once and cached under
# logs/research/ by coin, interval and day span. No key. The engine's
# rehearsal reads here; the research harnesses in ops/research/ import it
# too — the engine never imports research (the 2026-10-08 audit).
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / 'logs' / 'research'
BYBIT = 'https://api.bybit.com'
HL_INFO = 'https://api.hyperliquid.xyz/info'
H = 3_600_000


def _dedupe(rows, key='t'):
    seen, out = set(), []
    for x in sorted(rows, key=lambda x: x[key]):
        if x[key] not in seen:
            seen.add(x[key])
            out.append(x)
    return out


def fetch_klines(symbol, minutes, start_ms, end_ms):
    """Bybit linear candles with volume, oldest first, cached."""
    STORE.mkdir(parents=True, exist_ok=True)
    cache = STORE / f'{symbol}-{minutes}m-{start_ms // 86_400_000}-{end_ms // 86_400_000}.json'
    if cache.exists():
        return json.loads(cache.read_text())
    bars, cursor, step = [], start_ms, minutes * 60_000 * 1000
    interval = 'D' if minutes == 1440 else str(minutes)
    while cursor < end_ms:
        q = urllib.parse.urlencode({'category': 'linear', 'symbol': symbol, 'interval': interval,
                                    'start': cursor, 'end': min(cursor + step, end_ms), 'limit': 1000})
        req = urllib.request.Request(f'{BYBIT}/v5/market/kline?{q}', headers={'User-Agent': 'grid-gremlin research'})
        with urllib.request.urlopen(req, timeout=30) as r:
            rows = json.load(r)['result'].get('list', [])
        bars.extend({'t': int(x[0]), 'o': float(x[1]), 'h': float(x[2]), 'l': float(x[3]),
                     'c': float(x[4]), 'v': float(x[5])} for x in rows)
        cursor += step
        time.sleep(0.15)
    out = _dedupe(bars)
    cache.write_text(json.dumps(out))
    return out


def fetch_funding(category, symbol, start_ms, end_ms):
    """Bybit funding rates [{'t', 'rate'}], oldest first, cached."""
    STORE.mkdir(parents=True, exist_ok=True)
    cache = STORE / f'funding-{symbol}-{start_ms // 86_400_000}-{end_ms // 86_400_000}.json'
    if cache.exists():
        return json.loads(cache.read_text())
    rows, cursor = [], end_ms
    while cursor > start_ms:
        q = urllib.parse.urlencode({'category': category, 'symbol': symbol, 'startTime': start_ms,
                                    'endTime': cursor, 'limit': 200})
        req = urllib.request.Request(f'{BYBIT}/v5/market/funding/history?{q}',
                                     headers={'User-Agent': 'grid-gremlin research'})
        with urllib.request.urlopen(req, timeout=30) as r:
            page = json.load(r)['result'].get('list', [])
        if not page:
            break
        rows.extend({'t': int(x['fundingRateTimestamp']), 'rate': float(x['fundingRate'])} for x in page)
        oldest = min(int(x['fundingRateTimestamp']) for x in page)
        if oldest >= cursor:
            break
        cursor = oldest - 1
        time.sleep(0.15)
    out = _dedupe(rows)
    cache.write_text(json.dumps(out))
    return out


def fetch_hl_funding(coin, start_ms, end_ms):
    """Hyperliquid's hourly funding [{'t', 'rate'}], oldest first, cached."""
    STORE.mkdir(parents=True, exist_ok=True)
    cache = STORE / f'funding-HL-{coin}-{start_ms // 86_400_000}-{end_ms // 86_400_000}.json'
    if cache.exists():
        return json.loads(cache.read_text())
    rows, cursor = [], start_ms
    while cursor < end_ms:
        body = json.dumps({'type': 'fundingHistory', 'coin': coin, 'startTime': cursor,
                           'endTime': end_ms}).encode()
        req = urllib.request.Request(HL_INFO, data=body, headers={'Content-Type': 'application/json',
                                                                  'User-Agent': 'grid-gremlin research'})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                page = json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(10.0)                  # the public info endpoint meters by the minute
            continue
        if not page:
            break
        rows.extend({'t': int(x['time']), 'rate': float(x['fundingRate'])} for x in page)
        newest = max(int(x['time']) for x in page)
        if newest <= cursor:
            break
        cursor = newest + 1
        time.sleep(1.0)
    out = _dedupe(rows)
    cache.write_text(json.dumps(out))
    return out


def hl_8h(rows):
    """Hyperliquid pays hourly; a rehearsal's clock is 8h — sum each bucket."""
    out = {}
    for x in rows:
        b = x['t'] // (8 * H)
        out[b] = out.get(b, 0.0) + x['rate']
    return [{'t': b * 8 * H, 'rate': r} for b, r in sorted(out.items())]
