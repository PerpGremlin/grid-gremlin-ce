# D162: the account as its assets, read by read (SPEC R25-R28). The owner's
# model: an account is just its assets; a perpetual position borrows against
# the asset it is margined in; the bots are rulesets that manage them. He
# wants to SEE how the account's coins and futures change — display only,
# nothing acts and nothing pages.
#
# The readout already reads every position and the whole wallet (R19, U138);
# each read is kept here as one small record — every coin's balance and loan,
# every perpetual position's size, entry and mark:
#   logs/account/<fleet>.json                the last 25 h, thinned (R26), and
#                                            the money moved in or out (R27)
#   logs/fills/<fleet>.account-days.jsonl    the first read of each UTC day,
#                                            kept long beside the kept ledger
# The readout reads these back (never writes) to say what changed since 1 h,
# 24 h and 7 d (R28); the reader that keeps the shared readout writes them.
import json
import time
from pathlib import Path

from common.files import write_json
from .apply import make_botid, rung_of
from .durable import fleet_tag, locked, logs_dir

WINDOWS = (('1h', 3600), ('24h', 86400), ('7d', 7 * 86400))
RECENT_S = 25 * 3600                       # a 24 h window always has a record before it
THIN_STEPS = ((2 * 3600, 120), (RECENT_S, 900))   # (age up to, one record per) — R26
TRANSFER_EVERY_S = 600                     # the venue's money records, read at most this often
TRANSFER_KEEP_S = 8 * 86400                # the longest window and a day
TRANSFER_SPAN_MS = 7 * 86_400_000 - 60_000  # the transfer lists' own seven-day limit
TRANSFER_OVERLAP_MS = 3_600_000            # each read reaches an hour back: late-listed moves
DAYS_TAIL_BYTES = 1 << 18                  # the days file's tail read back: months of days
EPS = 1e-9


def recent_path(fleet_path):
    return logs_dir(fleet_path) / 'account' / f'{fleet_tag(fleet_path)}.json'


def days_path(fleet_path):
    return logs_dir(fleet_path) / 'fills' / f'{fleet_tag(fleet_path)}.account-days.jsonl'


def pos_key(market, symbol, side):
    return f'{market}:{symbol}:{side}'


def split_key(key):
    market, rest = key.split(':', 1)
    symbol, side = rest.rsplit(':', 1)
    return market, symbol, side


# --- one record per read (R25) ------------------------------------------------

def snapshot_of(account):
    """R25: the readout's `account` as one record per venue — each coin's
    balance and loan, each perpetual position's size, entry and mark. A
    venue whose read failed is left out; a part the venue does not give
    (Hyperliquid's coin-by-coin wallet) is absent, never zero."""
    out = {}
    for venue, fig in sorted((account or {}).items()):
        if not fig:
            continue
        rec = {'tier': fig.get('tier')}
        if fig.get('wallet') is not None:
            rec['wallet'] = {c: {'balance': w.get('balance') or 0.0, 'loan': w.get('borrow') or 0.0}
                             for c, w in sorted(fig['wallet'].items())}
        if fig.get('positions') is not None:
            rec['positions'] = {pos_key(p['market'], p['symbol'], p['side']):
                                {'size': p['size'], 'entry': p.get('entry'), 'mark': p.get('mark')}
                                for p in fig['positions']}
        out[venue] = rec
    return out


def thin(records, now_ms):
    """R26: the last day kept thinly — one record per two minutes over the
    last two hours, one per fifteen minutes back to 25 hours, nothing
    older (the days file keeps one a day). The newest of each slot stays,
    so the newest read always does."""
    keep, seen = [], set()
    for r in sorted(records, key=lambda r: r['t'], reverse=True):
        age = (now_ms - r['t']) / 1000.0
        if age > RECENT_S:
            continue
        step = next(s for limit, s in THIN_STEPS if age <= limit)
        slot = (step, r['t'] // (step * 1000))
        if slot in seen:
            continue
        seen.add(slot)
        keep.append(r)
    return keep[::-1]


def utc_day(ms):
    return time.strftime('%Y-%m-%d', time.gmtime(ms / 1000.0))


def load_history(path):
    try:
        got = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        got = {}
    if not isinstance(got, dict):
        got = {}
    got.setdefault('version', 1)
    got.setdefault('records', [])
    got.setdefault('transfers', {})
    return got


def read_days(path, tail_bytes=DAYS_TAIL_BYTES):
    """The days file's newest records (its tail), oldest first; a torn or
    foreign line is skipped."""
    p = Path(path)
    try:
        with open(p, 'rb') as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - tail_bytes))
            raw = fh.read().decode('utf-8', 'replace')
    except OSError:
        return []
    lines = raw.splitlines()
    if size > tail_bytes:
        lines = lines[1:]                      # the first may be cut
    out = []
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and isinstance(r.get('t'), int) and isinstance(r.get('v'), dict):
            out.append(r)
    return out


def merge_transfers(old, got, now_ms):
    """R27: the venue's money records kept by id, the last eight days; the
    span read runs from the earliest read that joins up to this one."""
    old = old or {}
    rows = {r['id']: r for r in old.get('rows') or []}
    rows.update({r['id']: r for r in got.get('rows') or []})
    floor = now_ms - TRANSFER_KEEP_S * 1000
    joined = old.get('read_ms') is not None and old['read_ms'] >= got['from_ms']
    start = min(old.get('from_ms') or got['from_ms'], got['from_ms']) if joined else got['from_ms']
    return {'from_ms': max(start, floor), 'read_ms': got['to_ms'], 'unread': got.get('unread') or {},
            'rows': sorted((r for r in rows.values() if r['t'] >= floor), key=lambda r: r['t'])}


def record(fleet_path, contract, now_ms=None):
    """R25-R27, the one writer: this readout's account as a record in the
    last day's file (thinned), the first of each UTC day in the days file,
    and the money records it read merged in. Under one lock, so two readers
    of one fleet never undo each other. Returns the history written."""
    t = (contract or {}).get('generated_ms')
    acct = snapshot_of((contract or {}).get('account'))
    now_ms = (t or int(time.time() * 1000)) if now_ms is None else now_ms
    moved = any((fig or {}).get('transfers') for fig in ((contract or {}).get('account') or {}).values())
    if not ((acct and t) or moved):
        return None                            # nothing read: nothing written
    path = recent_path(fleet_path)
    with locked(path):
        hist = load_history(path)
        if acct and t:
            hist['records'] = thin([r for r in hist['records'] if r.get('t') != t]
                                   + [{'t': t, 'v': acct}], now_ms)
            day = utc_day(t)
            if hist.get('last_day') is None:
                last = read_days(days_path(fleet_path))
                hist['last_day'] = last[-1].get('day') if last else None
            if hist['last_day'] != day:
                dp = days_path(fleet_path)
                dp.parent.mkdir(parents=True, exist_ok=True)
                with open(dp, 'a') as fh:
                    fh.write(json.dumps({'day': day, 't': t, 'v': acct}) + '\n')
                hist['last_day'] = day
        for venue, fig in sorted(((contract or {}).get('account') or {}).items()):
            got = (fig or {}).get('transfers')
            if got and got.get('from_ms') is not None:
                hist['transfers'][venue] = merge_transfers(hist['transfers'].get(venue), got, now_ms)
        write_json(path, hist, indent=None)
    return hist


def keep(fleet_path, contract):
    """`record` for a reader that must not fail on it: the phone's shared
    readout and the panel's own. A failure is said, and the read stands."""
    import sys
    try:
        record(fleet_path, contract)
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f'account record {fleet_path}: {e}', file=sys.stderr, flush=True)


def transfers_due(hist, venue, now_ms):
    """R27: where the next read of the venue's money records starts, or None
    while the last one is under TRANSFER_EVERY_S old — five calls a fleet
    every ten minutes, not every readout."""
    tr = (hist or {}).get('transfers', {}).get(venue) or {}
    last = tr.get('read_ms')
    if last is not None and now_ms - last < TRANSFER_EVERY_S * 1000:
        return None
    start = now_ms - TRANSFER_SPAN_MS
    if last is not None:
        start = max(start, last - TRANSFER_OVERLAP_MS)
    return start


# --- what changed (R28) -------------------------------------------------------

def before_of(records, venue, at_ms):
    """The newest record of `venue` at or before `at_ms`, and whether the
    history is shorter than asked (then its oldest, said as such)."""
    have = [r for r in records if venue in r['v']]
    if not have:
        return None, True
    older = [r for r in have if r['t'] <= at_ms]
    return (older[-1], False) if older else (have[0], True)


def bot_fills_qty(fills, market, symbol, side, t0, t1):
    """R28: what the bot of that market and side bought less sold for its
    position (an entry adds, an exit takes away) in (t0, t1] — its own
    fills only, by the link (I1). A hand trade carries no link and is not
    the bot's here."""
    botid = make_botid(market, symbol, side)
    entry = 'buy' if side == 'long' else 'sell'
    q = 0.0
    for f in fills:
        if (f.get('market_type') != market or f.get('symbol') != symbol
                or not t0 < f.get('time_ms', 0) <= t1
                or rung_of(f.get('link_id') or '', botid) is None):
            continue
        q += f['qty'] if f.get('side') == entry else -f['qty']
    return q


def split_change(change, bots):
    """R28: a position's change in two that add up exactly: the bots' own
    fills, and the rest, not from a bot."""
    return bots, change - bots


def _balances(before, now):
    if before.get('wallet') is None or now.get('wallet') is None:
        return None
    out = []
    for coin in sorted(set(before['wallet']) | set(now['wallet'])):
        b = before['wallet'].get(coin) or {}
        n = now['wallet'].get(coin) or {}
        row = {'coin': coin, 'before': b.get('balance', 0.0), 'now': n.get('balance', 0.0)}
        row['change'] = row['now'] - row['before']
        if b.get('loan') or n.get('loan'):
            row['loan_before'], row['loan_now'] = b.get('loan', 0.0), n.get('loan', 0.0)
        out.append(row)
    return out


def _positions(before, now, t0, t1, venue, fills, run, kept, complete):
    if before.get('positions') is None or now.get('positions') is None:
        return None
    out = []
    for key in sorted(set(before['positions']) | set(now['positions'])):
        market, symbol, side = split_key(key)
        b = (before['positions'].get(key) or {}).get('size', 0.0)
        n = (now['positions'].get(key) or {}).get('size', 0.0)
        row = {'key': key, 'market': market, 'symbol': symbol, 'side': side,
               'before': b, 'now': n, 'change': n - b,
               'state': 'new' if key not in before['positions'] else
                        'closed' if key not in now['positions'] else 'held'}
        mkt = (venue, market, symbol, side)
        if mkt in kept:
            row['bots'], row['rest'] = split_change(row['change'],
                                                    bot_fills_qty(fills, market, symbol, side, t0, t1))
            if not complete(venue, market, symbol, t0):
                row['why'] = 'the kept ledger is behind: a bot fill may be missing from its part'
        elif mkt in run:
            row['bots'] = row['rest'] = None
            row['why'] = "a Portfolio Bot's leg: its fills are not in the kept ledger, so the change is not split"
        else:
            row['bots'], row['rest'] = split_change(row['change'], 0.0)
        if abs(row['change']) > EPS or row['state'] != 'held':
            out.append(row)
    return out


def _transfers(tr, t0, t1):
    if not tr:
        return {'rows': [], 'unread': {'the records': 'not read yet'}, 'from_ms': None}
    rows = [r for r in tr.get('rows') or [] if t0 < r['t'] <= t1]
    return {'rows': rows, 'unread': tr.get('unread') or {}, 'from_ms': tr.get('from_ms')}


def account_change(records, now_rec, now_ms, fills=(), run=(), kept=(), complete=None,
                   transfers=None, positions=None):
    """R28: for each venue read now, what changed since 1 h, 24 h and 7 d:
    each coin's balance (and loan) before, now and the change — shown, not
    explained; each position's size before, now and the change, new or
    closed, split into what the bots' own fills on that market and side
    account for and the rest, not from a bot; and the money the venue
    records as moved in or out over the window (or why it was not read).
    `run`: (venue, market, symbol, side) a bot runs; `kept`: those whose
    fills the kept ledger holds; `positions`: the venue's positions now,
    for the list of those no bot runs."""
    complete = complete or (lambda *a: True)
    run, kept = set(run), set(kept)
    out = {}
    for venue, now in sorted(now_rec.items()):
        windows = {}
        for name, secs in WINDOWS:
            before, short = before_of(records, venue, now_ms - secs * 1000)
            if before is None or before['t'] >= now_ms:
                windows[name] = {'none': 'no earlier record yet'}
                continue
            b = before['v'][venue]
            t0 = before['t']
            windows[name] = {'from_ms': t0, 'short': short,
                             'balances': _balances(b, now),
                             'positions': _positions(b, now, t0, now_ms, venue, fills, run,
                                                     kept, complete),
                             'transfers': _transfers((transfers or {}).get(venue), t0, now_ms)}
        loose = [dict(p) for p in (positions or {}).get(venue) or []
                 if (venue, p['market'], p['symbol'], p['side']) not in run]
        out[venue] = {'windows': windows, 'not_from_a_bot': loose}
    return out
