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

  python3 -m gridgremlin.portfolio_rebuild <fleet.json> <name> [--apply]
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


def main(argv):
    apply = '--apply' in argv
    argv = [a for a in argv if a != '--apply']
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
