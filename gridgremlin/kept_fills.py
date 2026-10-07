# The kept ledger (SPEC R18). The readout counts from the exchange, and the
# exchanges forget: Hyperliquid answers only its newest fills, Bybit in
# 7-day slices, and a card counts from its bot's last flat — so nothing said
# what a bot has made since it first traded. This keeps every fill of a
# fleet, once, in logs/fills/<fleet>.json: read from the venues (read-only,
# R4), merged by execution id (I4), written atomically. Each venue key
# records how far collection has reached, so the readout can tell a quiet
# market from a ledger that has fallen behind.
#   python3 -m gridgremlin.kept_fills <fleet.json> ... [--out logs/fills]
#                                     [--backfill-days 90]
import json
import sys
import time
from pathlib import Path

from .config import validate_fleet
from .durable import locked, write_json
from .exchange.env import load_env

HL_CAP = 2000                    # HL answers at most this many fills a call
OVERLAP_MS = 3_600_000           # re-read an hour back: late-listed fills
BACKFILL_DAYS = 90.0


def store_path(fleet_path, root='logs/fills'):
    tag = Path(fleet_path).stem.replace('fleet.', '', 1)
    return Path(root) / f'{tag}.json'


def load(path):
    """The kept ledger, or an empty one. A file that will not parse is
    refused by name — never silently started again (that would lose the
    very history it exists to keep)."""
    p = Path(path)
    if not p.exists():
        return {'version': 1, 'collected': {}, 'fills': []}
    try:
        kept = json.loads(p.read_text())
    except ValueError as e:
        raise RuntimeError(f'{p}: the kept ledger does not parse — move it '
                           f'aside to start again ({e})') from None
    kept.setdefault('collected', {})
    kept.setdefault('fills', [])
    return kept


def fill_key(f):
    return (f.get('venue'), f.get('market_type'), str(f['exec_id']))


def merge(kept_fills, new_fills):
    """I4: one fill, once — the newer read of an execution id wins (a
    venue may relabel a fill after the fact), time-ordered."""
    by_key = {fill_key(f): f for f in kept_fills}
    for f in new_fills:
        by_key[fill_key(f)] = f
    return sorted(by_key.values(), key=lambda f: (f['time_ms'],
                                                  str(f['exec_id'])))


def hl_history(client, start_ms, end_ms):
    """HL caps an answer at 2000 fills and says nothing of order; a window
    that hits the cap is halved until every half fits, whatever the order."""
    raw = client.user_fills_by_time(start_ms, end_ms)
    if len(raw) < HL_CAP or end_ms - start_ms <= 1000:
        return raw
    mid = (start_ms + end_ms) // 2
    return (hl_history(client, start_ms, mid)
            + hl_history(client, mid + 1, end_ms))


def _since(kept, key, now_ms, backfill_days):
    done = kept['collected'].get(key)
    if done is None:
        return int(now_ms - backfill_days * 86_400_000)
    return int(done - OVERLAP_MS)


def collect(fleet, kept, now_ms, bybit=None, hl=None,
            backfill_days=BACKFILL_DAYS):
    """New fills for every venue key the fleet names, plus every key the
    ledger already holds (a bot taken out of the fleet keeps its history).
    `bybit`/`hl` are the read clients (stubs in specs). Returns the new
    ledger; a venue that cannot be read is skipped and its mark not moved."""
    kept = dict(kept, collected=dict(kept['collected']),
                fills=list(kept['fills']))       # every other key rides on
    keys = {('hyperliquid' if c['venue'] == 'hyperliquid' else 'bybit',
             c['market_type'], c['symbol']) for c in fleet['bots']}
    keys |= {(f['venue'], f['market_type'], f['symbol'])
             for f in kept['fills']}
    new, errors = [], []
    bybit_keys = sorted(k for k in keys if k[0] == 'bybit')
    if bybit_keys and bybit is not None:
        from .exchange.bybit.truth import read_fills
        for _, market_type, symbol in bybit_keys:
            mark = f'bybit:{market_type}:{symbol}'
            try:
                got = read_fills(bybit, market_type, symbol,
                                 _since(kept, mark, now_ms, backfill_days),
                                 now_ms)
            except Exception as e:                   # noqa: BLE001
                errors.append(f'{mark}: {e}')
                continue
            new += [dict(f, venue='bybit') for f in got]
            kept['collected'][mark] = now_ms
    coins = {k[2] for k in keys if k[0] == 'hyperliquid'}
    if coins and hl is not None:
        from .exchange.hyperliquid.truth import read_fills
        mark = 'hyperliquid'
        try:
            raw = hl_history(hl, _since(kept, mark, now_ms, backfill_days),
                             now_ms)
            got = read_fills(raw, coins, hl.address)
        except Exception as e:                       # noqa: BLE001
            errors.append(f'{mark}: {e}')
        else:
            new += [dict(f, venue='hyperliquid') for f in got]
            kept['collected'][mark] = now_ms
    kept['fills'] = merge(kept['fills'], new)
    return kept, errors


FRESH_AFTER_MISSES = 3     # hourly runs in a row with no clean start: the
                           # busiest pair lags its fills (G26) — 3 h of margin


def settle_anchors(fleet, kept, now_ms, held, mark_of):
    """R18: where each bot's kept record starts, settled by the collector
    and STORED, so a moment's lag can never move it. A clean start found
    is kept as found (a flat in the past stays a flat — the BTC pair's
    record would otherwise have been lost to a G26 lag on 2026-10-05). A
    bot that has never had one, on FRESH_AFTER_MISSES runs in a row,
    starts fresh: from now, holding what it holds at the price now (an
    opening balance; owner, 2026-10-05). Once set an anchor never moves.
    No holding figure, or a holding with no price, waits — never guessed."""
    from .report import bot_fills, first_flat_ms, fleet_maps, make_botid
    _, entry_sides, closers, _ = fleet_maps(fleet)
    anchors = dict(kept.get('anchors') or {})
    misses = dict(kept.get('misses') or {})
    for cfg in fleet['bots']:
        b = make_botid(cfg['market_type'], cfg['symbol'], cfg['side'])
        if b in anchors:
            continue                          # once: an anchor never moves
        own = bot_fills(kept['fills'], b, closers, entry_sides)
        size = held.get(b)
        if not own and not size:
            continue                          # flat and unseen: starts clean
        start = first_flat_ms(own, entry_sides[b], size) if own else None
        if start is not None:
            anchors[b] = {'kind': 'clean', 'time_ms': int(start)}
            misses.pop(b, None)
            continue
        if size is None:
            continue
        misses[b] = misses.get(b, 0) + 1
        if misses[b] < FRESH_AFTER_MISSES:
            continue                          # a lag passes; a hole stays
        price = mark_of(cfg) if size > 0 else 0.0
        if price is None:
            continue
        anchors[b] = {'kind': 'fresh', 'time_ms': int(now_ms), 'qty': size,
                      'price': price}
        misses.pop(b, None)
    return dict(kept, anchors=anchors, misses=misses)


def _held_and_marks(fleet, clients):
    """The holding each bot's record must land on (R14's read, spot from
    the engine's snapshot), and a price read per market when asked."""
    from .report import _venue_held_all, kept_held
    held = {}
    by_venue = {}
    for cfg in fleet['bots']:
        by_venue.setdefault(cfg['venue'], []).append(cfg)
    for venue, rows in by_venue.items():
        held.update(_venue_held_all(venue, rows))
    held = kept_held(fleet, held)

    def mark_of(cfg):
        try:
            if cfg['venue'] == 'hyperliquid':
                from .exchange.hyperliquid.truth import read_symbol_truth
                return read_symbol_truth(clients['hl'], cfg['symbol'])['mark']
            return clients['bybit'].read_symbol_truth(
                cfg['market_type'], cfg['symbol'])['mark']
        except Exception:                            # noqa: BLE001
            return None
    return held, mark_of


def keep(fleet_path, root='logs/fills', now_ms=None, clients=None,
         backfill_days=BACKFILL_DAYS, held_and_marks=None):
    """Read, collect, write — under the file's lock, re-read inside it."""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    fleet = validate_fleet(json.loads(Path(fleet_path).read_text()))
    venues = {c['venue'] for c in fleet['bots']}
    if clients is None:
        clients = {}
        if venues - {'hyperliquid'}:
            from .exchange.bybit.client import Client
            clients['bybit'] = Client()
        if 'hyperliquid' in venues:
            from .exchange.hyperliquid.client import InfoClient
            clients['hl'] = InfoClient()
    path = store_path(fleet_path, root)
    with locked(path):
        before = load(path)
        kept, errors = collect(fleet, before, now_ms, clients.get('bybit'),
                               clients.get('hl'), backfill_days)
        if not errors:                    # a fresh start needs a whole read
            held, mark_of = (held_and_marks or _held_and_marks)(fleet,
                                                                clients)
            kept = settle_anchors(fleet, kept, now_ms, held, mark_of)
        write_json(path, kept, indent=None)
    return path, len(kept['fills']) - len(before['fills']), errors


def main(argv):
    if not argv:
        print('usage: python3 -m gridgremlin.kept_fills <fleet.json> ... '
              '[--out logs/fills] [--backfill-days 90]')
        return 2
    out, days = 'logs/fills', BACKFILL_DAYS
    for flag in ('--out', '--backfill-days'):
        if flag in argv:
            i = argv.index(flag)
            if flag == '--out':
                out = argv[i + 1]
            else:
                days = float(argv[i + 1])
            argv = argv[:i] + argv[i + 2:]
    load_env()
    failed = 0
    for fleet in argv:
        try:
            path, added, errors = keep(fleet, out, backfill_days=days)
            print(f'kept {path}: {added:+d} fills')
            for e in errors:
                failed += 1
                print(f'[warn] {fleet}: {e}', file=sys.stderr)
        except Exception as e:                       # noqa: BLE001
            failed += 1                   # one fleet's trouble never costs
            print(f'[warn] {fleet}: {e}', file=sys.stderr)   # the others
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
