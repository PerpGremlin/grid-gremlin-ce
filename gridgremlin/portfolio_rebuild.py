"""The owner's one-time rebuild of a portfolio row's hedge books from the
venue's own fills (2026-10-11): every fill of every short leg since the
row's anchor replayed through today's book (`_apply` — the harmonic entry,
the inverse fee in the coin, H8), set beside what the row stored. The carry
row's stored realised figure kept the pre-H8 arithmetic (about 1 SOL); the
venue's fills are the truth.

Dry-run by default: prints each book stored against rebuilt. With --apply
the rebuilt books replace the stored ones — refused when a rebuilt position
disagrees with the stored one (a fill the replay could not see), and refused
while the fleet runs (the row is held in memory and written every cycle).
Stop the fleet first.

  python3 -m gridgremlin.portfolio_rebuild <fleet.json> <name> [--spot] [--apply]

--spot (H9b, 2026-10-15): the spot coins' average-cost books instead,
replayed from the venue's record since the anchor — every spot fill, and
the coins an inverse hedge's funding and realised P&L added, each at the
price of its moment — refused when the replayed coins differ from the
row's by more than dust.
"""
import json
import sys
import time
from pathlib import Path

POS_TOL = 1e-9


def rebuild(fills_by_book):
    """{book key: (fills oldest first, inverse)} -> {book key: book}, each
    fill {'side', 'price', 'qty', 'fee'} applied to an empty book."""
    from .portfolio_bot import _apply
    out = {}
    for key, (fills, inverse) in fills_by_book.items():
        book = {'position': 0.0, 'avg': 0.0, 'realized': 0.0, 'fees': 0.0}
        for f in fills:
            _apply(book, f['side'], float(f['price']), float(f['qty']), float(f.get('fee') or 0.0), inverse)
        out[key] = book
    return out


def compare(stored, rebuilt):
    """Lines saying each book stored against rebuilt, and the books whose
    positions disagree (a refused apply)."""
    lines, bad = [], []
    for key in sorted(set(stored) | set(rebuilt)):
        a = stored.get(key) or {'position': 0.0, 'avg': 0.0, 'realized': 0.0, 'fees': 0.0}
        b = rebuilt.get(key) or {'position': 0.0, 'avg': 0.0, 'realized': 0.0, 'fees': 0.0}
        if abs(a['position'] - b['position']) > POS_TOL * max(1.0, abs(a['position'])):
            bad.append(key)
        lines.append(f"{key}: position {a['position']:.10g} → {b['position']:.10g} · avg {a['avg']:.10g} → {b['avg']:.10g}"
                     f" · realised {a['realized']:+.10g} → {b['realized']:+.10g}"
                     f" ({b['realized'] - a['realized']:+.6g}) · fees {a['fees']:.10g} → {b['fees']:.10g}")
    return lines, bad


def rebuild_spot(events):
    """H9b: a spot coin's average-cost book replayed from the venue's own
    record, oldest first. events: ('fill', side, qty, price, fee) for a
    spot fill; ('coin', amount, price) for coins that came or went without
    one — an inverse hedge's funding paid in the coin, its realised coin
    and fees — at the price of that moment."""
    from .portfolio_bot import spot_fill, spot_sync
    book = {'coins': 0.0, 'cost': 0.0, 'realized': 0.0, 'fees': 0.0}
    for e in events:
        if e[0] == 'fill':
            spot_fill(book, e[1], float(e[2]), float(e[3]), float(e[4]))
        else:
            spot_sync(book, max(book['coins'] + float(e[1]), 0.0), float(e[2]))
    return book


def hedge_coin_events(fills):
    """An inverse hedge's fills, oldest first, as the coins they realised
    (less their fee in the coin) at each fill's price — the coins H8 counts
    in the row's book."""
    from .portfolio_bot import _apply
    book = {'position': 0.0, 'avg': 0.0, 'realized': 0.0, 'fees': 0.0}
    out = []
    for f in fills:
        before = book['realized'] - book['fees']
        _apply(book, f['side'], float(f['price']), float(f['qty']), float(f.get('fee') or 0.0), True)
        delta = book['realized'] - book['fees'] - before
        if abs(delta) > 1e-15:
            out.append((int(f['time_ms']), ('coin', delta, float(f['price']))))
    return out


SPOT_TOL = 0.005        # the replayed coins may differ from the row's by dust, not more


def spot_compare(held, rebuilt, prices):
    """Lines saying each coin's replayed book beside the coins the row
    holds, and the coins that differ by more than SPOT_TOL (refused)."""
    lines, bad = [], []
    for c in sorted(rebuilt):
        b, have = rebuilt[c], held.get(c, 0.0)
        if abs(b['coins'] - have) > SPOT_TOL * max(have, 1e-12):
            bad.append(c)
        avg = b['cost'] / b['coins'] if b['coins'] > 1e-12 else 0.0
        lines.append(f"{c}: replayed {b['coins']:.10g} coins against {have:.10g} held · average cost "
                     f"{avg:,.6g} · floating {b['coins'] * prices.get(c, 0.0) - b['cost']:+,.2f}"
                     f" · realised {b['realized']:+,.2f}")
    return lines, bad


def funding_coin_events(client, symbol, since_ms, now_ms):
    """An inverse leg's funding settlements in its coin, each with the
    price it settled at (execPrice) — read here, from the executions, so
    the engine's own reader stays as it is."""
    out, seen = [], set()
    start = int(since_ms)
    while start < now_ms:
        end = min(start + 7 * 86_400_000, now_ms)
        cursor = None
        for _ in range(50):
            page = client.executions_page('inverse', symbol, start, end, cursor, exec_type='Funding')
            for e in page.get('list', []):
                key = (e.get('execId'), e.get('side'))
                if e.get('execType') != 'Funding' or key in seen or e.get('side') != 'Sell':
                    continue
                seen.add(key)
                out.append((int(e.get('execTime') or 0),
                            ('coin', -float(e.get('execFee') or 0.0), float(e.get('execPrice') or 0.0))))
            cursor = page.get('nextPageCursor')
            if not cursor:
                break
        start = end
    return out


def main_spot(bot, row, client, now_ms, apply, state):
    """H9b: every spot coin's cost book rebuilt from the anchor."""
    prices = {c: float(client.read_symbol_truth('spot', leg['symbol'])['mark'] or 0.0)
              for c, leg in bot.legs['spot'].items()}
    held, rebuilt = {}, {}
    for coin, leg in bot.legs['spot'].items():
        events = [(int(f['time_ms']), ('fill', f['side'], f['qty'], f['price'], f.get('fee') or 0.0))
                  for f in bot._own_fills('spot', leg['symbol'], row['since_ms'], now_ms)]
        hedge = bot.legs['hedge'].get(coin)
        if hedge and hedge['market_type'] == 'inverse':
            fills = sorted(bot._own_fills('inverse', hedge['symbol'], row['since_ms'], now_ms),
                           key=lambda f: (f['time_ms'], f['exec_id']))
            events += hedge_coin_events(fills)
            events += funding_coin_events(client, hedge['symbol'], row['since_ms'], now_ms)
        events.sort(key=lambda e: e[0])
        print(f'{coin}: {len(events)} events since the anchor')
        rebuilt[coin] = rebuild_spot([e[1] for e in events])
        inv = sum(b['realized'] - b['fees'] for k, b in (row.get('books') or {}).items()
                  if k == f'hedge:{coin}' and hedge and hedge['market_type'] == 'inverse')
        held[coin] = row['coins'].get(coin, 0.0) + inv
    lines, bad = spot_compare(held, rebuilt, prices)
    print('\n'.join(lines))
    if bad:
        print(f'refused: the replayed coins disagree on {", ".join(bad)} — something the replay could not see')
        return 1
    if not apply:
        print('dry run — nothing written; --apply replaces the spot cost books')
        return 0
    costs = row.setdefault('spot_cost', {})
    for c, b in rebuilt.items():
        costs[c] = dict(b, since_ms=row['since_ms'], rebuilt_ms=now_ms)
    state.set(bot.botid, row)
    print(f"{bot.botid}: spot cost books rebuilt from the venue's record and written")
    return 0


def main(argv):
    apply = '--apply' in argv
    spot = '--spot' in argv
    argv = [a for a in argv if a not in ('--apply', '--spot')]
    if len(argv) != 2:
        print(__doc__.strip())
        return 2
    fleet_path, name = argv
    from .config import validate_fleet
    from .events import Notifier
    from .exchange.bybit.client import WriteClient
    from common.env import load_env
    from .exchange.env import select_account
    from .main import build_portfolio, fleet_running
    from .portfolio_state import PortfolioState
    from .tombstones import Tombstones, path_for
    load_env()
    fleet = validate_fleet(json.loads(Path(fleet_path).read_text()))
    select_account(fleet['account'])
    if fleet_running(fleet_path, {c['venue'] for c in fleet['bots']}, fleet['account']):
        print('the fleet is running on this file — stop it first (the row is held in memory)')
        return 1
    rows = [c for c in fleet['bots'] if c.get('strategy') == 'portfolio' and c['name'] == name]
    if not rows:
        print(f'no portfolio row named {name}')
        return 2
    from .durable import state_path
    state = PortfolioState(str(state_path(fleet_path, fleet, 'portfolio_state')))
    client = WriteClient()
    if client.env == 'mainnet':
        print('mainnet: not from here (D25)')
        return 1
    bot, _ = build_portfolio(rows[0], client, Notifier(sink=print), state, Tombstones(str(path_for(fleet_path, fleet))))
    row = state.get(bot.botid)
    if not row:
        print(f'{bot.botid}: no stored book — nothing to rebuild')
        return 1
    now_ms = int(time.time() * 1000)
    if spot:
        return main_spot(bot, row, client, now_ms, apply, state)
    fills_by_book = {}
    for kind in ('hedge', 'short'):
        for coin, leg in bot.legs[kind].items():
            fills = sorted(bot._own_fills(leg['market_type'], leg['symbol'], row['since_ms'], now_ms),
                           key=lambda f: (f['time_ms'], f['exec_id']))
            fills_by_book[f'{kind}:{coin}'] = (fills, leg['market_type'] == 'inverse')
            print(f'{kind}:{coin}: {len(fills)} fills since the anchor')
    rebuilt = rebuild(fills_by_book)
    lines, bad = compare(row.get('books') or {}, rebuilt)
    print('\n'.join(lines))
    if bad:
        print(f'refused: the rebuilt position disagrees on {", ".join(bad)} — a fill the replay could not see')
        return 1
    if not apply:
        print('dry run — nothing written; --apply replaces the books')
        return 0
    row['books'] = dict(row.get('books') or {}, **rebuilt)     # the spot side's books untouched
    row['rebuilt_ms'] = now_ms                               # `seen` stays: the next read starts after it
    state.set(bot.botid, row)
    print(f'{bot.botid}: books rebuilt from the venue\'s fills and written')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
