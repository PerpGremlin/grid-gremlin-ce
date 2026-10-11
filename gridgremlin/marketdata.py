"""K13: each coin's market data over time, from the big venues' public
endpoints — the asset page's charts (U71). Open interest, the perpetual's
basis to spot, the book's spread and depth, the long share of all accounts
(retail) and of the biggest ones (top traders), and the net taker flow on
perpetuals and on spot. Hourly, merged into one file per coin and kept 30
days, so a venue's short window (OKX's top traders: 100 hours) still grows a
month. No key, no private endpoint; display only — nothing acts on it.
"""
import json
import time
from pathlib import Path

SERIES_DIR = 'logs/series'
KEEP_S = 30 * 86_400
FULL_IF_OLDER_S = 12 * 3600          # a series this stale is refetched whole
H = 3_600_000

# name -> (heading, unit) — the page draws each group on one chart
SERIES = {
    'price': ('price', 'USD'),
    'oi.bybit': ('open interest', 'USD'), 'oi.binance': ('open interest', 'USD'), 'oi.okx': ('open interest', 'USD'),
    'basis.bybit': ('basis, perpetual over spot', '%'),
    'retail.bybit': ('retail — share of all accounts long', 'share'),
    'retail.binance': ('retail — share of all accounts long', 'share'),
    'retail.okx': ('retail — share of all accounts long', 'share'),
    'top.binance_accounts': ('top traders — share long', 'share'),
    'top.binance_positions': ('top traders — share long', 'share'),
    'top.okx_positions': ('top traders — share long', 'share'),
    'taker.binance': ('perpetual taker flow, buys − sells', 'USD'),
    'taker.okx': ('perpetual taker flow, buys − sells', 'USD'),
    'spot.binance': ('spot net flow, taker buys − sells', 'USD'),
    'spot.okx': ('spot net flow, taker buys − sells', 'USD'),
    'spread.bybit': ('bid–ask spread', 'bps'), 'spread.binance': ('bid–ask spread', 'bps'),
    'depth.bybit': ('book depth within 1% of the mid', 'USD'),
    'depth.binance': ('book depth within 1% of the mid', 'USD'),
    'imbalance.bybit': ('book imbalance, bids − asks over both', 'share'),
    'imbalance.binance': ('book imbalance, bids − asks over both', 'share'),
}

BYBIT = 'https://api.bybit.com/v5/market'
BINANCE_F = 'https://fapi.binance.com'
BINANCE_S = 'https://api.binance.com/api/v3'
OKX = 'https://www.okx.com/api/v5/rubik/stat'
OKX_NAME = {'XAUT': 'XAU'}        # OKX trades gold itself, not Tether's token; they track each other


def _share(ratio):
    """A long/short ratio as the share long."""
    return ratio / (1.0 + ratio) if ratio is not None and ratio >= 0 else None


def _okx(fetch, url, pause):
    pause(0.3)                        # OKX's statistics: five calls in two seconds
    d = fetch(url)
    if str(d.get('code')) != '0':
        raise ValueError(f"okx {d.get('code')}: {d.get('msg')}")
    return d.get('data') or []


def _book(fetch, venue, symbol):
    """Spread, depth within 1% each side, and imbalance, from one snapshot."""
    if venue == 'bybit':
        d = fetch(f'{BYBIT}/orderbook?category=linear&symbol={symbol}&limit=500')['result']
        bids, asks = d['b'], d['a']
    else:
        d = fetch(f'{BINANCE_F}/fapi/v1/depth?symbol={symbol}&limit=1000')
        bids, asks = d['bids'], d['asks']
    bids = [(float(p), float(q)) for p, q in bids]
    asks = [(float(p), float(q)) for p, q in asks]
    if not bids or not asks:
        raise ValueError('empty book')
    bb, ba = bids[0][0], asks[0][0]
    mid = (bb + ba) / 2
    bid = sum(p * q for p, q in bids if p >= mid * 0.99)
    ask = sum(p * q for p, q in asks if p <= mid * 1.01)
    return {'spread': (ba - bb) / mid * 1e4, 'depth': bid + ask,
            'imbalance': (bid - ask) / (bid + ask) if bid + ask else 0.0}


def fetch_coin(fetch, coin, have, now, pause=time.sleep):
    """One coin's points from every source: {series: {ms: value}} and the
    sources that could not be read. `have` is the kept series, to fetch only
    the last two days of a series kept fresh."""
    now_ms = int(now * 1000)
    hour = now_ms // H * H
    sym = f'{coin}USDT'
    got, unread = {}, {}

    def fresh(name):
        pts = have.get(name) or {}
        return bool(pts) and now_ms - max(int(t) for t in pts) < FULL_IF_OLDER_S * 1000

    def lim(name, full):
        return 48 if fresh(name) else full

    def put(name, pts):
        got[name] = {int(t): v for t, v in pts if v is not None}

    def source(names, fn):
        try:
            fn()
        except (OSError, ValueError, KeyError, IndexError, TypeError) as e:
            for n in names:
                unread[n] = f'{type(e).__name__}: {e}'[:160]

    price = {}

    def bybit_price():
        rows = fetch(f'{BYBIT}/kline?category=linear&symbol={sym}&interval=60&limit={lim("price", 720)}')['result']['list']
        price.update({int(r[0]): float(r[4]) for r in rows})
        put('price', price.items())
        idx = fetch(f'{BYBIT}/index-price-kline?category=linear&symbol={sym}&interval=60&limit={lim("basis.bybit", 720)}')['result']['list']
        put('basis.bybit', [(int(r[0]), (price[int(r[0])] / float(r[4]) - 1) * 100)
                            for r in idx if int(r[0]) in price and float(r[4]) > 0])
    source(['price', 'basis.bybit'], bybit_price)

    def bybit_ratio():
        rows = fetch(f'{BYBIT}/account-ratio?category=linear&symbol={sym}&period=1h&limit={lim("retail.bybit", 500)}')['result']['list']
        put('retail.bybit', [(int(r['timestamp']), float(r['buyRatio'])) for r in rows])
    source(['retail.bybit'], bybit_ratio)

    def bybit_oi():
        rows = fetch(f'{BYBIT}/open-interest?category=linear&symbol={sym}&intervalTime=1h&limit={lim("oi.bybit", 200)}')['result']['list']
        known = dict(price)
        known.update({int(t): v for t, v in (have.get('price') or {}).items()})
        put('oi.bybit', [(int(r['timestamp']), float(r['openInterest']) * known[int(r['timestamp'])])
                         for r in rows if int(r['timestamp']) in known])
    source(['oi.bybit'], bybit_oi)

    def binance():
        def data(ep, name):
            d = fetch(f'{BINANCE_F}/futures/data/{ep}?symbol={sym}&period=1h&limit={lim(name, 500)}')
            if not isinstance(d, list):
                raise ValueError(f"binance: {d.get('msg') if isinstance(d, dict) else d}")
            return d
        put('retail.binance', [(r['timestamp'], float(r['longAccount'])) for r in data('globalLongShortAccountRatio', 'retail.binance')])
        put('top.binance_accounts', [(r['timestamp'], float(r['longAccount'])) for r in data('topLongShortAccountRatio', 'top.binance_accounts')])
        put('top.binance_positions', [(r['timestamp'], float(r['longAccount'])) for r in data('topLongShortPositionRatio', 'top.binance_positions')])
        put('oi.binance', [(r['timestamp'], float(r['sumOpenInterestValue'])) for r in data('openInterestHist', 'oi.binance')])
        known = dict(price)
        known.update({int(t): v for t, v in (have.get('price') or {}).items()})
        put('taker.binance', [(r['timestamp'], (float(r['buyVol']) - float(r['sellVol'])) * known[int(r['timestamp'])])
                              for r in data('takerlongshortRatio', 'taker.binance') if int(r['timestamp']) in known])
    source(['retail.binance', 'top.binance_accounts', 'top.binance_positions', 'oi.binance', 'taker.binance'], binance)

    def binance_spot():
        rows = fetch(f'{BINANCE_S}/klines?symbol={sym}&interval=1h&limit={lim("spot.binance", 720)}')
        if not isinstance(rows, list):
            raise ValueError(f'binance spot: {rows}')
        put('spot.binance', [(int(r[0]), 2 * float(r[10]) - float(r[7])) for r in rows])   # taker buys − sells, in USD
    source(['spot.binance'], binance_spot)

    oc = OKX_NAME.get(coin, coin)
    known = dict(price)
    known.update({int(t): v for t, v in (have.get('price') or {}).items()})
    okx_calls = (                                  # each its own source: gold has no OKX spot market
        ('retail.okx', f'{OKX}/contracts/long-short-account-ratio?ccy={oc}&period=1H',
         lambda r: _share(float(r[1]))),
        ('oi.okx', f'{OKX}/contracts/open-interest-volume?ccy={oc}&period=1H', lambda r: float(r[1])),
        ('taker.okx', f'{OKX}/taker-volume?ccy={oc}&instType=CONTRACTS&period=1H',
         lambda r: float(r[2]) - float(r[1])),                                  # [ts, sells, buys], USD
        ('spot.okx', f'{OKX}/taker-volume?ccy={oc}&instType=SPOT&period=1H',
         lambda r: (float(r[2]) - float(r[1])) * known[int(r[0])] if int(r[0]) in known else None),   # in the coin
        ('top.okx_positions', f'{OKX}/contracts/long-short-position-ratio-contract-top-trader'
         f'?instId={oc}-USDT-SWAP&period=1H', lambda r: _share(float(r[1]))),
    )
    for name, url, value in okx_calls:
        def one(name=name, url=url, value=value):
            put(name, [(int(r[0]), value(r)) for r in _okx(fetch, url, pause)])
        source([name], one)

    for venue in ('bybit', 'binance'):            # the book has no history: a point an hour from now on
        def book(venue=venue):
            b = _book(fetch, venue, sym)
            for k in ('spread', 'depth', 'imbalance'):
                got[f'{k}.{venue}'] = {hour: b[k]}
        source([f'{k}.{venue}' for k in ('spread', 'depth', 'imbalance')], book)
    return got, unread


def merge(have, got, now):
    """The kept series with the new points in, trimmed to KEEP_S."""
    cut = int((now - KEEP_S) * 1000)
    out = {}
    for name in set(have) | set(got):
        pts = {int(t): v for t, v in (have.get(name) or {}).items()}
        pts.update(got.get(name) or {})
        out[name] = {str(t): v for t, v in sorted(pts.items()) if t >= cut}
    return out


def path_for(coin, root=None):
    return Path(root or SERIES_DIR) / f'{coin}.json'


def load(coin, root=None):
    try:
        return json.loads(path_for(coin, root).read_text())
    except (OSError, ValueError):
        return {}


def update(fetch, coins, now, root=None, pause=time.sleep):
    """Every coin's series fetched, merged and kept; returns what the
    reading says of it: the newest value of each series and what was not
    read, per coin."""
    from .durable import write_json
    said = {}
    for coin in coins:
        have = load(coin, root)
        got, unread = fetch_coin(fetch, coin, have, now, pause)
        kept = merge(have, got, now)
        p = path_for(coin, root)
        p.parent.mkdir(parents=True, exist_ok=True)
        write_json(p, kept)
        said[coin] = {'latest': {n: v[max(v, key=int)] for n, v in kept.items() if v},
                      'day': summary(kept, now), 'unread': unread}
    return said


def summary(kept, now):
    """What the fleet page's tabs say of a coin, from its kept series: open
    interest summed over the venues and its change over 24 hours; the 24
    hours' taker flow summed, perpetual and spot."""
    now_ms = int(now * 1000)
    day = now_ms - 86_400_000

    def at(name, t):                               # the value at or just before t
        pts = [(int(k), v) for k, v in (kept.get(name) or {}).items() if int(k) <= t]
        return max(pts)[1] if pts else None

    def summed(prefix):
        names = [n for n in kept if n.startswith(prefix)]
        tot = sum(v for n in names for k, v in kept[n].items() if day < int(k) <= now_ms)
        return tot if names else None

    venues = [n for n in kept if n.startswith('oi.')]
    oi_now = [at(n, now_ms) for n in venues]
    oi_then = [at(n, day) for n in venues]
    both = [(a, b) for a, b in zip(oi_now, oi_then) if a is not None and b is not None]
    return {'oi': sum(a for a in oi_now if a is not None) if venues else None,
            'oi_24h_pct': ((sum(a for a, _ in both) / sum(b for _, b in both) - 1) * 100
                           if both and sum(b for _, b in both) else None),
            'taker_24h': summed('taker.'), 'spot_24h': summed('spot.')}


def series(coin, names, since_ms, root=None):
    """For the page: each named series from `since_ms`, oldest first, as
    [(ms, value)]."""
    kept = load(coin, root)
    return {n: sorted((int(t), v) for t, v in (kept.get(n) or {}).items() if int(t) >= since_ms) for n in names}
