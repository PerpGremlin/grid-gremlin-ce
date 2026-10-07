# The daily digest (SPEC F17, D62). Once a day, after the archive and
# before Tokyo opens, one message: the UTC day per exchange — what was made
# after fees, trips and rounds, what is open now, the kept history — then
# what happened (from the fleet log since the last digest) and whether the
# machinery is healthy. Read-only toward the venues: it reads the archive the
# readout just wrote, the kept ledger, the snapshots and the logs.
#   python3 -m gridgremlin.digest <fleet.json> ... [--dry]
import json
import re
import sys
import time
from pathlib import Path

from .config import VENUE_ICONS, validate_fleet
from .durable import write_json
from .exchange.env import load_env
from .report import card_total

STATE = Path('logs/digest.state.json')
STALE_S = 600            # a snapshot older than this: the fleet is not running


def fleet_tag(fleet_path):
    return Path(fleet_path).stem.replace('fleet.', '', 1)


def log_path(fleet_path):
    """The fleet's systemd-appended log: logs/fleet-<tag>.log, dots dashed
    (fleet.hl.testnet.json -> logs/fleet-hl-testnet.log)."""
    return Path('logs') / f"fleet-{fleet_tag(fleet_path).replace('.', '-')}.log"


def day_books(fleet, kept, day_start_ms, now_ms):
    """Each bot's kept book at the day's start and now, from the same
    anchored fills the readout counts (R18): {botid: (start, now)}. A bot
    with no whole record yet is absent — never summed."""
    from .report import (bot_fills, counted_fills, fleet_maps, ledger,
                         make_botid, new_book)
    key_of, entry_sides, closers, _ = fleet_maps(fleet)
    inverse = {make_botid(c['market_type'], c['symbol'], c['side'])
               for c in fleet['bots'] if c['market_type'] == 'inverse'}
    rounders = {make_botid(c['market_type'], c['symbol'], c['side'])
                for c in fleet['bots'] if c.get('strategy') == 'martingale'}
    anchors = kept.get('anchors') or {}
    out = {}
    for b in key_of:
        own = bot_fills(kept['fills'], b, closers, entry_sides)
        got = counted_fills(b, own, entry_sides[b], anchors.get(b), None)
        if got is None:
            continue
        counted, _ = got

        def book(upto):
            fills = [f for f in counted if f['time_ms'] < upto]
            return ledger(fills, [b], inverse, entry_sides, closers,
                          rounders=rounders).get(b) or new_book()
        out[b] = (book(day_start_ms), book(now_ms + 1))
    return out


def net(book, mark=None):
    """Realised after fees, in quote — an inverse book's coin at the mark
    (A4); None when an inverse book has no mark."""
    v = book['realized'] - book['fees']
    if book.get('inverse'):
        return None if mark is None else v * mark
    return v


def log_events(path, offset):
    """What the log said since the last digest: (counts, new offset). The
    log carries no clock, so the digest keeps its place; a log smaller than
    the place was rotated, and is read from its start."""
    counts = {'kills': 0, 'stop/trail closes': 0, 'refused orders': 0,
              'fill lags (G26)': 0, 'margin': 0, 'tracebacks': 0}
    try:
        size = path.stat().st_size
    except OSError:
        return counts, offset
    if size < offset:
        offset = 0
    with open(path, 'rb') as f:
        f.seek(offset)
        for raw in f:
            line = raw.decode(errors='replace')
            if 'Traceback' in line:
                counts['tracebacks'] += 1
            if not line.startswith('[ship]'):
                continue
            if line.startswith('[ship] kill '):
                counts['kills'] += 1
            elif line.startswith('[ship] margin '):
                counts['margin'] += 1
            elif (line.startswith('[ship] exit ') and ': position ' not in line) \
                    or ('crossed' in line and line.startswith('[ship] tp ')):
                counts['stop/trail closes'] += 1
            elif 'rejected' in line or 'REFUSED' in line:
                counts['refused orders'] += 1
            elif 'G26' in line:
                counts['fill lags (G26)'] += 1
        offset = f.tell()
    return counts, offset


def _m(v):
    return '—' if v is None else f'{v:+,.2f}'


def section(fleet_path, now, day_start, archive_root='logs/daily',
            kept_root='logs/fills', state=None):
    """One exchange's lines, and the log place to remember."""
    from .kept_fills import load, store_path
    from .report import make_botid
    fleet = validate_fleet(json.loads(Path(fleet_path).read_text()))
    tag = fleet_tag(fleet_path)
    venue = fleet['bots'][0]['venue'] if fleet['bots'] else ''
    head = VENUE_ICONS.get(venue, venue) + f' · {tag}'
    day = time.strftime('%Y-%m-%d', time.gmtime(now))
    arch = Path(archive_root) / tag / f'{day}.json'
    try:
        record = json.loads(arch.read_text())
    except (OSError, ValueError):
        record = None
    contract = (record or {}).get('readout') or {}
    bots = contract.get('bots') or {}
    sf = contract.get('since_first') or {}
    lines = [head]
    try:
        kept = load(store_path(fleet_path, kept_root))
    except RuntimeError:
        kept = {'fills': [], 'anchors': {}, 'collected': {}}
    books = day_books(fleet, kept, int(day_start * 1000), int(now * 1000))
    dca = {make_botid(c['market_type'], c['symbol'], c['side'])
           for c in fleet['bots'] if c.get('strategy') == 'martingale'}
    day_net, fees, trips, rounds, per_bot, left = 0.0, 0.0, 0, 0, [], 0
    for b, (start, end) in books.items():
        mark = (bots.get(b) or {}).get('mark')
        a, z = net(start, mark), net(end, mark)
        if a is None or z is None:
            left += 1
            continue
        d = z - a
        day_net += d
        fees += (end['fees'] - start['fees']) * (mark if end.get('inverse')
                                                 else 1.0)
        if b in dca:                         # a DCA bot's unit is the round,
            rounds += end['rounds'] - start['rounds']
        else:                                # a grid's the trip (R6)
            trips += end['trips'] - start['trips']
        if abs(d) > 1e-9:
            per_bot.append((d, b))
    # D63: the day is the kept fills' — trading after fees, before funding;
    # funding lands in the kept-history figure below and on every card
    lines.append(f'day {_m(day_net)} after fees, before funding '
                 f'(fees {fees:,.2f}) · '
                 f'{trips} trips · {rounds} rounds'
                 + (f' · {left} not counted' if left else ''))
    open_now = [v.get('unreal_at_mark') for v in bots.values()
                if v and v.get('unreal_at_mark') is not None]
    kept_total, kept_out = 0.0, 0
    for v in sf.values():
        if not v or not v.get('fills'):
            continue
        if (not v.get('whole', True) or v.get('behind') is not None
                or v.get('realized') is None):
            kept_out += 1
            continue
        kept_total += card_total(v)                             # D63
    if record is None:
        lines.append('no archive for today — open and kept figures unread')
    else:
        lines.append(f'open now {_m(sum(open_now) if open_now else None)} · '
                     f'kept history {_m(kept_total)}'
                     + (f' ({kept_out} left out)' if kept_out else ''))
    if per_bot:
        per_bot.sort()
        best, worst = per_bot[-1], per_bot[0]
        lines.append(f'best {best[1]} {_m(best[0])}'
                     + (f' · worst {worst[1]} {_m(worst[0])}'
                        if worst[1] != best[1] else ''))
    from .archive import last_snapshot
    from .report import _watchdog_view
    snap = last_snapshot(fleet_path) or (record or {}).get('snapshot') or {}
    if snap.get('equity') is not None:
        from .report import account_leverage
        mm = snap.get('mm_rate')
        levs = list(account_leverage(contract).values())
        lev = ''
        if levs and levs[0]['now'] is not None:
            lev = f" · account leverage {levs[0]['now']:.2f}x"
            if levs[0]['fall'] is not None:
                lev += (f" (all filled: {levs[0]['fall']:.2f}x on a fall, "
                        f"{levs[0]['rise']:.2f}x on a rise)")
        lines.append(f"equity {snap['equity']:,.0f}" + lev
                     + (f' · margin rate {mm:.1%}' if mm is not None else ''))
    state = state if state is not None else {}
    first = tag not in state
    counts, place = log_events(log_path(fleet_path), state.get(tag, 0))
    said = ' · '.join(f'{k} {v}' for k, v in counts.items() if v)
    lines.append(('since the log began (first digest): ' if first
                  else 'since the last digest: ')
                 + (said or 'nothing to report'))
    age = now - snap['t'] if snap.get('t') else None
    alive = sum(1 for v in (snap.get('bots') or {}).values()
                if v.get('alive', True))
    health = []
    if age is None or age > STALE_S:
        health.append('⚠️ snapshot stale — is the fleet running?')
    else:
        health.append(f'{alive}/{len(fleet["bots"])} bots alive')
    wd = _watchdog_view(fleet) or contract.get('watchdog') or {}
    if wd.get('swept_s_ago') is not None:
        health.append(f"watchdog {wd['swept_s_ago'] // 60:.0f} min ago")
    if kept.get('collected'):
        health.append('ledger '
                      f"{(now * 1000 - max(kept['collected'].values())) / 6e4:.0f}"
                      ' min ago')
    lines.append('health: ' + ' · '.join(health))
    return lines, tag, place


def build(fleet_paths, now=None, **roots):
    now = time.time() if now is None else now
    day_start = now - now % 86400
    day = time.strftime('%Y-%m-%d', time.gmtime(now))
    try:
        state = json.loads(STATE.read_text())
    except (OSError, ValueError):
        state = {}
    parts, places = [f'🧌 daily digest · {day} (UTC day)'], {}
    market_store = roots.pop('market_store', None)
    for fp in fleet_paths:
        try:
            lines, tag, place = section(fp, now, day_start, state=state,
                                        **roots)
        except Exception as e:                       # noqa: BLE001
            lines, tag, place = [f'{fp}: unreadable — {e}'], None, None
        parts.append('\n'.join(lines))
        if tag is not None:
            places[tag] = place
    from .market import digest_block, latest                     # D67
    try:
        parts.append('\n'.join(digest_block(latest(market_store), now)))
    except Exception as e:                                       # noqa: BLE001
        parts.append(f'market: unreadable — {e}')
    return '\n\n'.join(parts), dict(state, **places)


def main(argv):
    dry = '--dry' in argv
    argv = [a for a in argv if a != '--dry']
    if not argv:
        print('usage: python3 -m gridgremlin.digest <fleet.json> ... [--dry]')
        return 2
    load_env()
    text, state = build(argv)
    print(text)
    if dry:
        return 0
    from .watchdog import send_telegram
    send_telegram(text[:3900])
    write_json(STATE, state)            # the log place moves only once sent
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
