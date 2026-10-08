"""Research (2026-10-09): the carry — what a delta-neutral pair of perps
would have earned from funding over the year, net of the fees to hold it.

  python3 ops/research/funding_carry.py [--days 365] [--coins BTC,ETH]

Public funding history (no key), cached under logs/research/. For each
product the 8-hourly rates; for each pair of products the spread a long
on one and a short on the other would have collected. Nothing here
touches a venue with a key or any running code.
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / 'logs' / 'research'
HOST = 'https://api.bybit.com'
PRODUCTS = {'BTC': (('linear', 'BTCUSDT'), ('linear', 'BTCPERP'), ('inverse', 'BTCUSD')),
            'ETH': (('linear', 'ETHUSDT'), ('linear', 'ETHPERP'), ('inverse', 'ETHUSD'))}
TAKER, MAKER = 0.00055, 0.0002


def fetch(category, symbol, start_ms, end_ms):
    STORE.mkdir(parents=True, exist_ok=True)
    cache = STORE / f'funding-{symbol}-{start_ms // 86_400_000}-{end_ms // 86_400_000}.json'
    if cache.exists():
        return json.loads(cache.read_text())
    rows, cursor = [], end_ms
    while cursor > start_ms:
        q = urllib.parse.urlencode({'category': category, 'symbol': symbol, 'startTime': start_ms,
                                    'endTime': cursor, 'limit': 200})
        req = urllib.request.Request(f'{HOST}/v5/market/funding/history?{q}',
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
    seen, out = set(), []
    for x in sorted(rows, key=lambda x: x['t']):
        if x['t'] not in seen:
            seen.add(x['t'])
            out.append(x)
    cache.write_text(json.dumps(out))
    return out


def by_month(rows):
    out = {}
    for x in rows:
        key = time.strftime('%Y-%m', time.gmtime(x['t'] / 1000))
        out[key] = out.get(key, 0.0) + x['rate']
    return out


def main(argv):
    days = int(argv[argv.index('--days') + 1]) if '--days' in argv else 365
    coins = argv[argv.index('--coins') + 1].split(',') if '--coins' in argv else ['BTC', 'ETH']
    end = int(time.time() * 1000)
    start = end - days * 86_400_000
    for coin in coins:
        series = {}
        for category, symbol in PRODUCTS[coin]:
            series[symbol] = fetch(category, symbol, start, end)
        print(f'=== {coin}: funding over {days} days (a SHORT receives the rate when positive)')
        for symbol, rows in series.items():
            tot = sum(x['rate'] for x in rows)
            pos = sum(1 for x in rows if x['rate'] > 0)
            neg = sum(1 for x in rows if x['rate'] < 0)
            mean = tot / len(rows) if rows else 0
            print(f"  {symbol:8} {len(rows):4} settlements  total {tot:+.2%}  mean/8h {mean:+.4%}  "
                  f"(annualised {mean * 3 * 365:+.1%})  positive {pos} negative {neg}  "
                  f"worst 8h {min((x['rate'] for x in rows), default=0):+.3%}  best {max((x['rate'] for x in rows), default=0):+.3%}")
        months = sorted({m for rows in series.values() for m in by_month(rows)})
        print('  by month (short receives):')
        for m in months:
            print('   ', m, '  '.join(f"{s} {by_month(r).get(m, 0.0):+.2%}" for s, r in series.items()))
        # pairs: long A / short B collects funding(B) - funding(A); the legs
        # cost two taker entries and two exits once, or maker if patient
        syms = list(series)
        times = {}
        for s, rows in series.items():
            for x in rows:
                times.setdefault(x['t'] // 3_600_000 // 8, {})[s] = x['rate']
        print('  pairs over the year, net of one round trip in fees:')
        for a in syms:
            for b in syms:
                if a == b:
                    continue
                spread = sum(v[b] - v[a] for v in times.values() if a in v and b in v)
                n = sum(1 for v in times.values() if a in v and b in v)
                print(f"    long {a:8} / short {b:8}: gross {spread:+.2%} over {n} settlements  "
                      f"net taker {spread - 4 * TAKER:+.2%}  net maker {spread - 4 * MAKER:+.2%}")
        # a rotating book: each settlement, hold the pair whose last-3-day
        # average spread is best; rotate at maker fees when the leader changes
        keys = sorted(times)
        hist = {}
        held, carry, rotations = None, 0.0, 0
        for k in keys:
            v = times[k]
            for a in syms:
                for b in syms:
                    if a != b and a in v and b in v:
                        hist.setdefault((a, b), []).append(v[b] - v[a])
            best = max(((sum(h[-9:]) / len(h[-9:]), p) for p, h in hist.items() if len(h) >= 9), default=None)
            if best is None:
                continue
            avg, pair = best
            if avg <= 0:
                target = None                       # nothing pays: stay flat
            else:
                target = pair
            if target != held:
                if held is not None:
                    carry -= 2 * MAKER              # close two legs
                if target is not None:
                    carry -= 2 * MAKER              # open two legs
                held = target
                rotations += 1
            if held and held[0] in v and held[1] in v:
                carry += v[held[1]] - v[held[0]]
        print(f"  rotating book (best 3-day pair, flat when none pays, maker fees): "
              f"net {carry:+.2%} over the year, {rotations} rotations")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
