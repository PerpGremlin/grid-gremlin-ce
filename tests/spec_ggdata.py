"""D91 step 2b: one candle fetcher and one funding fetcher (ggdata), against a
fake venue — paging, Hyperliquid's POST on the network named, a market not
listed, the rate-limit wait."""
import json
import urllib.error
from urllib.parse import parse_qs, urlparse

H = 3_600_000


def _bybit(n_bars=2500, n_fund=450, t_end=1_800_000_000_000, missing=('XAUTUSD',)):
    calls = []
    def fetch(url):
        calls.append(url)
        u = urlparse(url if isinstance(url, str) else url.full_url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path.endswith('/kline'):
            m = int(q['interval']) * 60_000
            ts = [t_end - i * m for i in range(n_bars)]
            lo, hi = int(q.get('start', 0)), int(q.get('end', t_end))
            sel = [t for t in ts if lo <= t <= hi][:int(q['limit'])]
            return {'result': {'list': [[str(t), '1', '2', '0.5', '1.5', '7', '0'] for t in sel]}}   # newest first
        if u.path.endswith('/funding/history'):
            if q['symbol'] in missing:
                return {'retCode': 10001, 'retMsg': 'params error: Symbol Invalid', 'result': {}}
            ts = [t_end - i * 8 * H for i in range(n_fund)]
            sel = [t for t in ts if int(q['startTime']) <= t <= int(q['endTime'])][:int(q['limit'])]
            return {'retCode': 0, 'result': {'list': [{'fundingRateTimestamp': str(t), 'fundingRate': '0.0001'} for t in sel]}}
        raise AssertionError(url)
    return fetch, calls, t_end


def spec_D91_one_candle_fetcher_for_every_venue():
    from ggdata.candles import candles, last_candles
    fetch, calls, t_end = _bybit()
    bars = candles('bybit', 'linear', 'BTCUSDT', 60, t_end - 1500 * H, t_end, fetch)
    # paged forward, one per hour; a range's first bar is not served (Bybit answers the newest
    # 1,000 of a 1,001-bar span) — as the copies it replaced did, kept identical on purpose
    assert len(bars) == 1500 and bars[0]['t'] == t_end - 1499 * H and bars[-1]['t'] == t_end
    assert all(b['v'] == 7.0 for b in bars) and len({b['t'] for b in bars}) == len(bars)
    assert all('api.bybit.com' in c for c in calls)                         # the main public host
    calls.clear()
    last = last_candles('linear', 'BTCUSDT', 60, 1200, t_end, fetch)
    assert len(last) == 1200 and last[-1]['t'] == t_end and last[0]['t'] == t_end - 1199 * H   # paged backward
    assert len(calls) == 2
    seen = []
    def info(body):
        seen.append(body)
        r = body['req']
        return [{'t': t, 'o': '1', 'h': '2', 'l': '0.5', 'c': '1.5', 'v': '3'}
                for t in range(r['startTime'], r['endTime'] + 1, 4 * H)]
    hl = candles('hyperliquid', 'linear', 'SOL', 240, t_end - 40 * H, t_end, info=info)
    assert len(hl) == 11 and seen[0]['req']['interval'] == '4h' and seen[0]['type'] == 'candleSnapshot'
    posted = []
    def net_fetch(req):
        posted.append((req.full_url, json.loads(req.data)))
        return []
    candles('hyperliquid', 'linear', 'SOL', 60, t_end - H, t_end, fetch=net_fetch, network='testnet')
    assert posted[0][0] == 'https://api.hyperliquid-testnet.xyz/info'      # the fleet's own network
    try:
        candles('hyperliquid', 'linear', 'SOL', 7, 0, H, info=info)
        raise AssertionError('a 7-minute candle accepted')
    except ValueError as e:
        assert 'no 7-minute candle' in str(e)


def spec_D91_one_funding_fetcher_for_every_venue():
    from ggdata.funding import binance_funding, bybit_funding, hl_funding, okx_funding
    fetch, calls, t_end = _bybit()
    rows = bybit_funding('linear', 'BTCUSDT', t_end - 400 * 8 * H, t_end, fetch)
    assert len(rows) == 401 and rows[0]['t'] < rows[-1]['t'] and rows[-1] == {'t': t_end, 'rate': 0.0001}   # paged back
    assert bybit_funding('inverse', 'XAUTUSD', 0, t_end, fetch) == []      # not listed: nothing, quietly
    try:
        bybit_funding('inverse', 'XAUTUSD', 0, t_end, fetch, strict=True)
        raise AssertionError('not named')
    except ValueError as e:
        assert '10001' in str(e)
    calls.clear()
    assert len(bybit_funding('linear', 'BTCUSDT', 0, t_end, fetch, limit=48, pages=1)) == 48 and 'limit=48' in calls[0]
    waits, tries = [], {'n': 0}
    def hl_fetch(req):
        tries['n'] += 1
        if tries['n'] == 1:
            raise urllib.error.HTTPError(req.full_url, 429, 'slow down', {}, None)
        body = json.loads(req.data)
        return [] if body['startTime'] > 3 * H else [{'time': t, 'fundingRate': '0.00001'} for t in (H, 2 * H, 3 * H)]
    hl = hl_funding('BTC', 0, 10 * H, network='mainnet', fetch=hl_fetch, sleep=waits.append)
    assert [x['t'] for x in hl] == [H, 2 * H, 3 * H] and waits[0] == 10.0   # a 429 waits, then reads on
    bn = binance_funding('BTCUSDT', fetch=lambda u: [{'fundingTime': 2, 'fundingRate': '0.1'}, {'fundingTime': 1, 'fundingRate': '0.2'}])
    assert [x['t'] for x in bn] == [1, 2]
    ok = okx_funding('BTC-USDT-SWAP', fetch=lambda u: {'code': '0', 'data': [{'fundingTime': '5', 'realizedRate': '0.3', 'fundingRate': '0.9'}]})
    assert ok == [{'t': 5, 'rate': 0.3}]                                   # the realised rate
