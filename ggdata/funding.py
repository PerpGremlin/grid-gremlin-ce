"""One funding fetcher (D91: one of each): each venue's public settlements as
[{'t', 'rate'}] oldest first — Bybit (linear and inverse), Hyperliquid
(hourly, on the network named), Binance and OKX. A market the venue does not
list is []. Every function takes the fetcher it reads with."""
import json
import time
import urllib.error
import urllib.request

from common.http import get_json

from .candles import BYBIT, HL_INFO

BINANCE_F = 'https://fapi.binance.com'
OKX = 'https://www.okx.com'


def bybit_funding(market_type, symbol, start_ms, end_ms, fetch=get_json, limit=200, pages=200, strict=False):
    """Bybit's settlements, paged back by end time from end_ms to start_ms,
    `limit` a page. A market Bybit does not list is [] — or, `strict`, an
    error naming it (a page that says which source it could not read)."""
    rows, end = {}, int(end_ms)
    for _ in range(pages):
        if end <= start_ms:
            break
        d = fetch(f'{BYBIT}/v5/market/funding/history?category={market_type}&symbol={symbol}'
                  f'&startTime={int(start_ms)}&endTime={end}&limit={limit}')
        if d.get('retCode', 0) != 0:
            if strict:
                raise ValueError(f"bybit {d.get('retCode')}: {d.get('retMsg')}")
            break                                       # not listed (a coin with no inverse)
        page = (d.get('result') or {}).get('list') or []
        for x in page:
            t = int(x['fundingRateTimestamp'])
            if start_ms <= t <= end_ms:
                rows[t] = float(x['fundingRate'])
        if len(page) < limit:
            break
        oldest = min(int(x['fundingRateTimestamp']) for x in page)
        if oldest >= end:
            break
        end = oldest - 1
    return [{'t': t, 'rate': rows[t]} for t in sorted(rows)]


def hl_funding(coin, start_ms, end_ms, network='mainnet', fetch=get_json, sleep=time.sleep):
    """Hyperliquid's hourly settlements, paged forward; its public endpoint
    meters by the minute, so a 429 waits and tries again."""
    rows, cursor = {}, int(start_ms)
    while cursor < end_ms:
        req = urllib.request.Request(HL_INFO[network], data=json.dumps(
            {'type': 'fundingHistory', 'coin': coin, 'startTime': cursor, 'endTime': int(end_ms)}).encode(),
            headers={'Content-Type': 'application/json'})
        try:
            page = fetch(req)
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            sleep(10.0)
            continue
        if not page:
            break
        for x in page:
            rows[int(x['time'])] = float(x['fundingRate'])
        newest = max(int(x['time']) for x in page)
        if newest <= cursor:
            break
        cursor = newest + 1
        sleep(1.0)
    return [{'t': t, 'rate': rows[t]} for t in sorted(rows)]


def binance_funding(symbol, limit=200, fetch=get_json):
    """Binance's last `limit` settlements of a USDT perpetual."""
    d = fetch(f'{BINANCE_F}/fapi/v1/fundingRate?symbol={symbol}&limit={limit}')
    if not isinstance(d, list):
        raise ValueError(f'binance: {d}')
    return sorted(({'t': int(r['fundingTime']), 'rate': float(r['fundingRate'])} for r in d), key=lambda x: x['t'])


def okx_funding(inst_id, limit=100, fetch=get_json):
    """OKX's last `limit` settlements of a swap (its realised rate)."""
    d = fetch(f'{OKX}/api/v5/public/funding-rate-history?instId={inst_id}&limit={limit}')
    if str(d.get('code')) != '0':
        raise ValueError(f"okx {d.get('code')}: {d.get('msg')}")
    return sorted(({'t': int(r['fundingTime']), 'rate': float(r.get('realizedRate') or r['fundingRate'])}
                   for r in d.get('data') or []), key=lambda x: x['t'])
