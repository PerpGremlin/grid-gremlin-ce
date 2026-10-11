"""D84: the collector — the order book and the liquidations, recorded as they
happen (neither keeps a public history). Every five minutes, per coin:

  the book   — Coinbase's whole spot book (every level, aggregated) and OKX's
               deep perpetual book (5,000 levels, about ±0.8%), summed into
               bands of 0.1% of a reference price across ±5% of the mid;
               the free books of Bybit and Binance reach only ±0.15%;
  liquidations — OKX's public liquidation orders, each with its side, price
               and size (contracts × the contract's value), paged back until
               they overlap the last run, so a burst is not missed.

Kept per coin and day under logs/collect/, seven days. Keyless, public
endpoints only; display only — no bot reads it. Run by a timer:
  python3 -m gridgremlin.collector
"""
import json
import math
import sys
import time
from pathlib import Path

DIR = 'logs/collect'
KEEP_DAYS = 7
BAND = 0.001                 # a band is 0.1% of the day's reference price
REACH = 0.05                 # ±5% of the mid
COINBASE = 'https://api.exchange.coinbase.com/products/{}-USD/book?level=2'
OKX_BOOK = 'https://www.okx.com/api/v5/market/books-full?instId={}-USDT-SWAP&sz=5000'
OKX_LIQ = 'https://www.okx.com/api/v5/public/liquidation-orders?instType=SWAP&uly={}-USDT&state=filled'
OKX_INST = 'https://www.okx.com/api/v5/public/instruments?instType=SWAP'
OKX_NAME = {'XAUT': 'XAU'}   # OKX trades gold itself (K13)
NO_COINBASE = {'XAUT'}


def bands(levels, ref, mid):
    """[(price, size in coins)] -> {band index: USD}, the band k holding
    prices in [ref·(1 + k·BAND), ref·(1 + (k+1)·BAND)); only within REACH of
    the mid. Index 0 starts at the reference price."""
    out = {}
    lo, hi = mid * (1 - REACH), mid * (1 + REACH)
    for p, q in levels:
        if lo <= p <= hi and q > 0:
            k = math.floor((p / ref - 1) / BAND)
            out[k] = out.get(k, 0.0) + p * q
    return out


def merge(*maps):
    out = {}
    for m in maps:
        for k, v in m.items():
            out[k] = out.get(k, 0.0) + v
    return out


def read_book(fetch, coin):
    """Both venues' books: mid, bids and asks as [(price, coins)], and what
    could not be read."""
    bids, asks, mids, unread = [], [], [], {}
    if coin not in NO_COINBASE:
        try:
            d = fetch(COINBASE.format(coin))
            b = [(float(p), float(q)) for p, q, *_ in d['bids']]
            a = [(float(p), float(q)) for p, q, *_ in d['asks']]
            if b and a:
                bids += b
                asks += a
                mids.append((b[0][0] + a[0][0]) / 2)
        except (OSError, ValueError, KeyError, IndexError, TypeError) as e:
            unread['coinbase'] = f'{type(e).__name__}: {e}'[:120]
    try:
        oc = OKX_NAME.get(coin, coin)
        d = fetch(OKX_BOOK.format(oc))
        if str(d.get('code')) != '0':
            raise ValueError(f"okx {d.get('code')}: {d.get('msg')}")
        r = d['data'][0]
        ct = _ctval(fetch, oc)
        b = [(float(x[0]), float(x[1]) * ct) for x in r['bids']]   # contracts × the contract's coins
        a = [(float(x[0]), float(x[1]) * ct) for x in r['asks']]
        if b and a:
            bids += b
            asks += a
            mids.append((b[0][0] + a[0][0]) / 2)
    except (OSError, ValueError, KeyError, IndexError, TypeError) as e:
        unread['okx'] = f'{type(e).__name__}: {e}'[:120]
    mid = sum(mids) / len(mids) if mids else None
    return mid, bids, asks, unread


_CT = {}


def _ctval(fetch, okx_coin):
    """A contract's coins on OKX (BTC 0.01, ETH 0.1, DOGE 1000 …), read once a run."""
    if not _CT:
        for x in fetch(OKX_INST)['data']:
            if x.get('instId', '').endswith('-USDT-SWAP'):
                _CT[x['instId'][:-10]] = float(x['ctVal'])
    return _CT[okx_coin]


def read_liquidations(fetch, coin, since_ms, pages=5):
    """OKX's liquidations of `coin` newer than since_ms, oldest first:
    [{'ts', 'side' (the position liquidated: long or short), 'px', 'coins',
    'usd'}], paged back with `after` until they overlap since_ms."""
    oc = OKX_NAME.get(coin, coin)
    ct = _ctval(fetch, oc)
    out, after = {}, None
    for _ in range(pages):
        d = fetch(OKX_LIQ.format(oc) + (f'&after={after}' if after else ''))
        if str(d.get('code')) != '0':
            raise ValueError(f"okx {d.get('code')}: {d.get('msg')}")
        rows = (d.get('data') or [{}])[0].get('details') or []
        for r in rows:
            ts = int(r['ts'])
            if ts > since_ms:
                coins = float(r['sz']) * ct
                px = float(r['bkPx'])
                out[(ts, r.get('posSide'), r['bkPx'], r['sz'])] = {
                    'ts': ts, 'side': r.get('posSide') or ('long' if r.get('side') == 'sell' else 'short'),
                    'px': px, 'coins': coins, 'usd': coins * px}
        if not rows or min(int(r['ts']) for r in rows) <= since_ms:
            break
        after = min(int(r['ts']) for r in rows)
    return sorted(out.values(), key=lambda x: x['ts'])


def day_of(t):
    return time.strftime('%Y-%m-%d', time.gmtime(t))


def run(fetch, coins, now, root=None):
    """One collection: each coin's book banded and its new liquidations,
    appended to the day's files; files past KEEP_DAYS removed. Returns what
    was read, per coin."""
    root = Path(root or DIR)
    said = {}
    state_p = root / 'state.json'
    try:
        state = json.loads(state_p.read_text())
    except (OSError, ValueError):
        state = {}
    day = day_of(now)
    for coin in coins:
        cdir = root / coin
        cdir.mkdir(parents=True, exist_ok=True)
        st = state.setdefault(coin, {})
        mid, bids, asks, unread = read_book(fetch, coin)
        if mid:
            if st.get('ref_day') != day or not st.get('ref'):
                st['ref'], st['ref_day'] = mid, day        # bands align across the day
            row = {'t': int(now), 'mid': mid, 'ref': st['ref'], 'band': BAND,
                   'bids': {str(k): round(v) for k, v in bands(bids, st['ref'], mid).items()},
                   'asks': {str(k): round(v) for k, v in bands(asks, st['ref'], mid).items()},
                   'unread': unread}
            with open(cdir / f'book-{day}.jsonl', 'a') as f:
                f.write(json.dumps(row) + '\n')
        try:
            liqs = read_liquidations(fetch, coin, st.get('liq_ms') or int((now - 3600) * 1000))
            if liqs:
                with open(cdir / f'liq-{day}.jsonl', 'a') as f:
                    for x in liqs:
                        f.write(json.dumps(x) + '\n')
                st['liq_ms'] = liqs[-1]['ts']
            n_liq = len(liqs)
        except (OSError, ValueError, KeyError, IndexError, TypeError) as e:
            unread['okx_liq'] = f'{type(e).__name__}: {e}'[:120]
            n_liq = None
        said[coin] = {'mid': mid, 'liquidations': n_liq, 'unread': unread}
    cut = day_of(now - KEEP_DAYS * 86400)
    for f in root.glob('*/*.jsonl'):
        if f.stem.split('-', 1)[1] < cut:
            f.unlink()
    from .durable import write_json
    write_json(state_p, state)
    return said


def read_days(coin, kind, since, root=None):
    """For the page: a coin's rows of `kind` ('book' or 'liq') from `since`
    (epoch seconds), oldest first."""
    root = Path(root or DIR) / coin
    out = []
    for f in sorted(root.glob(f'{kind}-*.jsonl')):
        if f.stem.split('-', 1)[1] < day_of(since):
            continue
        for line in f.read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            t = r.get('t') or r.get('ts', 0) / 1000
            if t >= since:
                out.append(r)
    return out


def main(argv):
    from .market import fetch_json, latest
    row = latest() or {}
    coins = list(row.get('hmm') or {}) or ['BTC', 'ETH', 'SOL']
    said = run(fetch_json, coins, time.time())
    bad = {c: s['unread'] for c, s in said.items() if s['unread']}
    print(f"collector: {len(said)} coins, {sum(s['liquidations'] or 0 for s in said.values())} new liquidations"
          + (f", unread {bad}" if bad else ''), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
