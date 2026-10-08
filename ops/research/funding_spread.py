"""Research (2026-10-08): the cross-venue carry — Bybit's USDT perp against
Hyperliquid's perp on the same coin, both directions, a year of funding.

  python3 ops/research/funding_spread.py [--days 365] [--coins BTC,ETH]

Hyperliquid funds hourly; its rates are summed into Bybit's 8-hour
settlement buckets. Public, keyless, mainnet HISTORY only — nothing is
placed anywhere (Hyperliquid trading stays testnet-only by directive).
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ops.research.funding_carry import STORE, fetch as fetch_bybit  # noqa: E402

HL = 'https://api.hyperliquid.xyz/info'
BYBIT_MAKER, HL_MAKER = 0.0002, 0.0001          # one leg each way, patient
EIGHT_H = 8 * 3_600_000


def fetch_hl(coin, start_ms, end_ms):
    STORE.mkdir(parents=True, exist_ok=True)
    cache = STORE / f'funding-HL-{coin}-{start_ms // 86_400_000}-{end_ms // 86_400_000}.json'
    if cache.exists():
        return json.loads(cache.read_text())
    rows, cursor = [], start_ms
    while cursor < end_ms:
        body = json.dumps({'type': 'fundingHistory', 'coin': coin, 'startTime': cursor,
                           'endTime': end_ms}).encode()
        req = urllib.request.Request(HL, data=body, headers={'Content-Type': 'application/json',
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
    seen, out = set(), []
    for x in sorted(rows, key=lambda x: x['t']):
        if x['t'] not in seen:
            seen.add(x['t'])
            out.append(x)
    cache.write_text(json.dumps(out))
    return out


def bucket8(rows):
    out = {}
    for x in rows:
        out[x['t'] // EIGHT_H] = out.get(x['t'] // EIGHT_H, 0.0) + x['rate']
    return out


def main(argv):
    days = int(argv[argv.index('--days') + 1]) if '--days' in argv else 365
    coins = argv[argv.index('--coins') + 1].split(',') if '--coins' in argv else ['BTC', 'ETH']
    end = int(time.time() * 1000)
    start = end - days * 86_400_000
    for coin in coins:
        by = bucket8(fetch_bybit('linear', f'{coin}USDT', start, end))
        hl_rows = fetch_hl(coin, start, end)
        hl = bucket8(hl_rows)
        keys = sorted(set(by) & set(hl))
        print(f'=== {coin}: {len(keys)} common 8h buckets; HL hourly rows {len(hl_rows)}')
        tot_by, tot_hl = sum(by[k] for k in keys), sum(hl[k] for k in keys)
        print(f'  a SHORT received over the year: Bybit {tot_by:+.2%}   Hyperliquid {tot_hl:+.2%}')
        # long HL / short Bybit collects by - hl; the other way collects hl - by
        a = [by[k] - hl[k] for k in keys]
        print(f'  static all year:  long HL / short Bybit {sum(a):+.2%}   long Bybit / short HL {-sum(a):+.2%}'
              f'   (one round trip of maker fees on both venues: {2 * (BYBIT_MAKER + HL_MAKER):.2%})')
        print(f'  spread per 8h: mean {sum(a) / len(a):+.4%}  |mean| {sum(abs(v) for v in a) / len(a):.4%}  '
              f'best {max(a):+.3%}  worst {min(a):+.3%}')
        months = {}
        for k, v in zip(keys, a):
            m = time.strftime('%Y-%m', time.gmtime(k * EIGHT_H / 1000))
            months[m] = months.get(m, 0.0) + v
        print('  by month, long HL / short Bybit:', '  '.join(f'{m} {v:+.2%}' for m, v in sorted(months.items())))
        # a patient book: hold the direction whose trailing 7-day spread is
        # positive and worth more than a switch; switch at maker on both
        # venues; flat when neither direction's trailing carry beats the fee
        fee = 2 * (BYBIT_MAKER + HL_MAKER)
        held, carry, switches, hist = 0, 0.0, 0, []
        for v in a:
            hist.append(v)
            trail = sum(hist[-21:]) / len(hist[-21:]) * 21          # 7 days of 8h buckets
            want = 1 if trail > fee else (-1 if -trail > fee else 0)
            if want != held:
                if held != 0:
                    carry -= fee / 2
                if want != 0:
                    carry -= fee / 2
                held, switches = want, switches + 1
            carry += held * v
        print(f'  patient book (7-day trailing, switch at maker, flat when it would not pay): '
              f'net {carry:+.2%} over the year, {switches} switches')
        # monthly walk-forward: the direction last month's spread paid, held this month
        ms = sorted(months)
        wf, prev = 0.0, None
        for m in ms:
            if prev is not None:
                d = 1 if months[prev] > 0 else -1
                wf += d * months[m] - (fee if ms.index(m) == 1 or (1 if months[prev] > 0 else -1) != (1 if months[ms[ms.index(m) - 2]] > 0 else -1) else 0.0) if ms.index(m) >= 2 else d * months[m] - fee
            prev = m
        print(f'  monthly walk-forward (hold the direction last month paid): net {wf:+.2%}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
