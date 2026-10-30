# The daily drift check (SPEC F39–F41; D-number: owner to assign, the lead
# proposes D156). Positions cannot drift: the exchange is the only durable
# state and every cycle reads it (E3). Profit can: a bot's realised, its
# fees and its grid trips are counted from the kept ledger (R18), and a fill
# missing from it would make every figure after it quietly wrong. Once a
# day, before the digest, each fleet's ledger is set beside the venue's own
# record of the last week:
#   1. fills — every execution the venue lists for a market is in the
#      ledger and the ledger has none it does not, by execution id (F39);
#   2. realised — each bot's average-cost realised over the window against
#      the venue's own closed P&L, within a stated tolerance (F40);
#   3. a grid's U113 identity on its real book — the trips' gross less the
#      average-cost realised is what the open lots cost beyond the book's
#      average, times the position (F41).
# Read-only toward the venues: the reads the collector already makes, and
# the venue's closed P&L — nothing here can place, amend or cancel. The
# report is logs/drift/<fleet>.json; the digest says a fleet only when
# something is off, and a venue it could not read is said, never agreement.
#   python3 -m gridgremlin.pnl_drift run <fleet.json> ... [--days 7]
#   python3 -m gridgremlin.pnl_drift show
import json
import sys
import time
from pathlib import Path

from common.files import write_json

ROOT = Path('logs/drift')
LOOKBACK_DAYS = 7.0
DAY_MS = 86_400_000
SETTLE_MS = 3_600_000          # the newest hour is the collector's to finish
                               # (kept_fills.OVERLAP_MS: a late-listed fill)
STALE_S = 2 * 3600             # the check runs minutes before the digest
BEHIND_MS = 2 * 3_600_000      # the ledger topped up minutes before it, too
PORTFOLIO_DAYS = 90.0          # a portfolio row's books count from its anchor:
                               # read back that far, never further
SEEN_CAP = 400                 # a portfolio row keeps its newest 400 ids
# F40's tolerance: a cent of the quote (a millionth of the coin for an
# inverse book) plus one basis point of the notional the window closed. The
# venue rounds each row to 8 decimals and may hold an entry price rounded
# to its tick (under half a basis point on every market the fleets trade);
# a missing exit moves the figure by its own margin — a rung's gap, tens of
# basis points of that fill — and check 1 names the fill itself either way.
REAL_ABS = {'quote': 0.01, 'coin': 1e-6}
REAL_REL = 1e-4
# F41: the identity is arithmetic on one record — float rounding only.
IDENT_ABS = {'quote': 1e-6, 'coin': 1e-10}
IDENT_REL = 1e-9
FIELD_REL = 1e-9               # a fill's price, size or fee re-read
SHOW_IDS = 3                   # ids named in the digest line; show lists all


# --- reading the venue --------------------------------------------------------

def venue_fills(clients, venue, market_type, symbol, start_ms, end_ms):
    """The venue's executions of one market in the window, in the ledger's
    shape (the collector's own readers, so the two lists are comparable),
    and for Hyperliquid each fill's closedPnl by execution id."""
    if venue == 'hyperliquid':
        from .exchange.hyperliquid.truth import read_fills
        from .kept_fills import hl_history
        hl = clients['hl']
        raw = hl_history(hl, int(start_ms), int(end_ms))
        got = read_fills(raw, {symbol}, hl.address)
        closed = {str(f.get('tid')): float(f.get('closedPnl') or 0.0)
                  for f in raw if f.get('coin') == symbol}
        return [dict(f, venue='hyperliquid') for f in got], closed
    from .exchange.bybit.truth import read_fills
    got = read_fills(clients['bybit'], market_type, symbol, int(start_ms), int(end_ms))
    return [dict(f, venue='bybit') for f in got], None


def venue_realised(clients, market_type, symbol, start_ms, end_ms, side):
    """Bybit's closed P&L rows for a market closed inside the window (one
    per closing order, `gross` from the row's own values), only the
    closing side `side` when a hedge pair shares the market (None: every
    row)."""
    from .exchange.bybit.truth import read_closed_pnl
    rows = read_closed_pnl(clients['bybit'], market_type, symbol, int(start_ms), int(end_ms))
    return [r for r in rows if (side is None or r['side'] == side)
            and start_ms <= r['time_ms'] <= end_ms]


# --- the three checks --------------------------------------------------------

def _key(f):
    return str(f['exec_id'])


def _same(a, b):
    return all(abs(float(a[k]) - float(b[k])) <= FIELD_REL * max(1.0, abs(float(b[k])))
               for k in ('price', 'qty', 'fee'))


def compare_fills(ours, theirs):
    """F39 for one market: (missing from the ledger, extra in it, changed)
    — fills by execution id; changed = the same id with another price,
    size or fee."""
    a = {_key(f): f for f in ours}
    b = {_key(f): f for f in theirs}
    missing = [b[k] for k in sorted(set(b) - set(a), key=lambda k: b[k]['time_ms'])]
    extra = [a[k] for k in sorted(set(a) - set(b), key=lambda k: a[k]['time_ms'])]
    changed = [b[k] for k in sorted(set(a) & set(b)) if not _same(a[k], b[k])]
    return missing, extra, changed


def owner_name(f, botids, closers):
    """Whose a fill is, for saying it: its link's bot (R1), else the bot
    whose exits sit on its side when the venue made it or it carries no
    link (R7/R16), else no bot's."""
    from .report import owner_of
    b = owner_of(f.get('link_id') or '', botids)
    if b is None and (f.get('venue_closed') or not f.get('link_id')):
        b = closers.get((f.get('market_type'), f.get('symbol'), f.get('side')))
    return b or 'unowned'


def _flat_after_opening(counted, entry_side):
    """A fresh anchor's record opens with a balance at the price recording
    began, not the venue's entry (R18): its realised is the venue's only
    from the first return to flat. That moment + 1 ms, or None."""
    from .report import EPS
    pos, tol = 0.0, 1e-9 * max(1.0, counted[0]['qty']) + EPS
    for f in counted:
        pos += f['qty'] if f['side'] == entry_side else -f['qty']
        if abs(pos) <= tol:
            return f['time_ms'] + 1
    return None


def bot_record(kept, fleet, botid):
    """(counted fills, opened anchor) of a bot's whole kept record (R18,
    the card's and the pane's), or None when it has no whole start."""
    from .kept_fills import anchor_of, since_cut
    from .report import bot_fills, counted_fills, fleet_maps
    _, entry_sides, closers, _ = fleet_maps(fleet)
    own = since_cut(kept, botid, bot_fills(kept.get('fills') or [], botid, closers, entry_sides))
    return counted_fills(botid, own, entry_sides[botid], anchor_of(kept, botid), None)


def _book(counted, botid, cfg, upto_ms, fleet):
    from .report import fleet_maps, ledger, new_book
    _, entry_sides, closers, _ = fleet_maps(fleet)
    inverse = {botid} if cfg['market_type'] == 'inverse' else set()
    rounders = {botid} if cfg.get('strategy') == 'martingale' else set()
    fills = [f for f in counted if f['time_ms'] < upto_ms]
    return ledger(fills, [botid], inverse, entry_sides, closers,
                  rounders=rounders).get(botid) or new_book()


def realised_by_fill(counted, botid, cfg, fleet):
    """{execution id: what that fill realised} along the bot's whole kept
    book (R2) — so a window's realised can leave out single orders."""
    from .report import fleet_maps, ledger
    _, entry_sides, closers, _ = fleet_maps(fleet)
    series = {}
    ledger(counted, [botid], {botid} if cfg['market_type'] == 'inverse' else set(), entry_sides,
           closers, rounders={botid} if cfg.get('strategy') == 'martingale' else set(),
           series=series)
    out, before = {}, 0.0
    for f, (_, net) in zip(counted, series.get(botid, [])):   # net = realised - fees, running
        out[_key(f)] = net - before + f['fee']
        before = net
    return out


def straddling(rows, exits, frm, end):
    """F40: the orders not wholly inside [frm, end] — a closing order whose
    fills there do not add up to the size its closed P&L row closed (some
    fell before the window, or after it: a resting exit filled in part), or
    whose row lies outside it. Left out of both sides, never an alarm."""
    filled, closed = {}, {}
    for f in exits:
        if frm <= f['time_ms'] <= end and f.get('order_id'):
            filled[f['order_id']] = filled.get(f['order_id'], 0.0) + f['qty']
    for r in rows:
        if r.get('order_id'):
            closed[r['order_id']] = closed.get(r['order_id'], 0.0) + r['qty']
    return {o for o in set(filled) | set(closed)
            if abs(filled.get(o, 0.0) - closed.get(o, 0.0))
            > 1e-9 * max(1.0, filled.get(o, 0.0), closed.get(o, 0.0))}


def check_realised(record, cfg, botid, fleet, start_ms, end_ms, unowned, venue_rows,
                   venue_exits=None):
    """F40 for one bot: ({ours, venue, tol, from_ms, rows, ...}, None) or
    (None, why it was not compared). `venue_rows(from_ms)` reads the
    venue's rows ({order_id, gross, stated, qty}); it may raise (said by
    the caller as unread). `venue_exits`: the venue's own fills of the
    bot's exits in the window, with their orders (Bybit) — an order
    straddling the window is left out of both sides; None where each row
    is one fill (Hyperliquid)."""
    if cfg['market_type'] == 'spot':
        return None, 'spot: the venue states no closed P&L'
    if record is None:
        return None, 'no whole record yet (R18)'
    counted, opened = record
    if unowned:
        return None, (f"{unowned} fill{'s' if unowned > 1 else ''} on {cfg['symbol']} "
                      'belong to no bot of this fleet')
    entry = 'buy' if cfg['side'] == 'long' else 'sell'
    frm = start_ms
    if counted and str(counted[0].get('exec_id', '')).startswith('open:'):
        flat = _flat_after_opening(counted, entry)
        if flat is None or flat >= end_ms:
            return None, ("its record opens at a fresh anchor's balance (R18) and has "
                          'not been flat since: the venue counts from its own entry')
        frm = max(frm, flat)
    if counted:
        frm = max(frm, counted[0]['time_ms'])
    rows = venue_rows(frm)
    dropped = straddling(rows, venue_exits, frm, end_ms) if venue_exits is not None else set()
    order_of = {_key(f): f.get('order_id') for f in venue_exits or []}
    deltas = realised_by_fill(counted, botid, cfg, fleet)
    exits = [f for f in counted if frm <= f['time_ms'] <= end_ms and f['side'] != entry
             and order_of.get(_key(f)) not in dropped]
    ours = sum(deltas.get(_key(f), 0.0) for f in exits)
    kept_rows = [r for r in rows if not (r.get('order_id') and r['order_id'] in dropped)]
    venue = sum(r['gross'] for r in kept_rows)
    inverse = cfg['market_type'] == 'inverse'
    closed_value = sum((f['qty'] / f['price'] if inverse else f['qty'] * f['price'])
                       for f in exits if f['price'])
    unit = 'coin' if inverse else 'quote'
    tol = REAL_ABS[unit] + REAL_REL * closed_value
    return {'ours': ours, 'venue': venue, 'tol': tol, 'from_ms': frm, 'rows': len(kept_rows),
            'fees': sum(f['fee'] for f in counted if frm <= f['time_ms'] <= end_ms),
            'straddling': len(dropped),
            'residue': sum(r['stated'] for r in kept_rows) - venue,      # what closedPnl holds besides
            'off': abs(ours - venue) > tol}, None


def open_lots(counted, botid, entry_side, inverse=False):
    """F41's lots, walked from the record by its own hand (not report's):
    each entry fill a lot; each exit consumes the lots it closes as the
    engine nets them (G23) — the lot one rung inside it first (G25), then
    the newest open lot of any rung, seed lots included; an exit with no
    rung (a venue's or a hand's close) the newest first. Returns {lots
    [(price, qty)] left, no_lot (exits the whole inventory could not
    cover), same_rung (exits whose lot was bought at their own rung, R9:
    said, not a failure), exits [(fill, qty covered, its cost)] — the cost
    in quote, or in coin for an inverse}."""
    from .apply import rung_of
    from .ladder import SEED_RUNG
    step = -1 if entry_side == 'buy' else 1
    book = {}                                   # seq -> [rung, price, qty]
    seq = 0
    no_lot = same = 0
    exits = []
    for f in counted:
        rung = rung_of(f.get('link_id') or '', botid)
        if f['side'] == entry_side:
            seq += 1
            book[seq] = [rung, f['price'], f['qty']]
            continue
        inside = rung + step if rung is not None and rung != SEED_RUNG else None
        newest = sorted(book, reverse=True)
        order = [k for k in newest if book[k][0] == inside] + \
                [k for k in newest if book[k][0] != inside]
        left, cost, own_rung = f['qty'], 0.0, False
        for k in order:
            if left <= 1e-12 * max(1.0, f['qty']):
                break
            r, p, q = book[k]
            take = q if q < left else left
            book[k][2] = q - take
            if book[k][2] <= 1e-12 * max(1.0, f['qty']):
                del book[k]
            left -= take
            cost += take / p if inverse else take * p
            own_rung = own_rung or (rung is not None and r == rung)
        if left > 1e-9 * max(1.0, f['qty']):
            no_lot += 1
        same += own_rung
        exits.append((f, f['qty'] - left, cost))
    return {'lots': [(p, q) for _, p, q in book.values()], 'no_lot': no_lot,
            'same_rung': same, 'exits': exits}


def first_disagreement(exits, rows, inverse):
    """F41's diagnostic: the first exit whose pairing (the pane's `own`,
    report's R15) cost differs from the walker's consumed cost —
    {fill, time_ms, pairing, walker}, or None."""
    by_time = {}
    for row in rows:
        if not row['entry'] and row.get('own') is not None:
            by_time.setdefault((row['time_ms'], row['price'], row['qty']), []).append(row['own'])
    for f, covered, cost in exits:
        owns = by_time.get((f['time_ms'], f['price'], f['qty']))
        if not owns:
            continue
        own = owns.pop(0)
        paired = f['qty'] / own if inverse else f['qty'] * own
        if abs(paired - cost) > IDENT_ABS['coin' if inverse else 'quote'] + IDENT_REL * abs(cost):
            return {'fill': f.get('exec_id') or f.get('link_id') or '', 'time_ms': f['time_ms'],
                    'pairing': paired, 'walker': cost}
    return None


def check_identity(kept, fleet, botid, cfg, record):
    """F41 for one grid: ({gross, realised, shift, lots_qty, position, tol,
    off}, None) or (None, why not checked)."""
    from .fill_list import fill_list
    if not (cfg.get('lower') and cfg.get('upper')):
        return None, None                             # grid-only: nothing to say
    if record is None:
        return None, 'no whole record yet (R18)'
    counted, opened = record
    if opened is not None and opened.get('qty'):
        return None, "its record opens at a fresh anchor's balance (R18), not at lots"
    got = fill_list(kept, fleet, botid)
    if got is None or not got.get('whole'):
        return None, 'no whole record yet (R18)'
    if got['unmatched']:
        return None, (f"{got['unmatched']} exit{'s' if got['unmatched'] > 1 else ''} with no "
                      'entry to match (a venue or hand close): the identity needs every exit matched')
    entry = 'buy' if cfg['side'] == 'long' else 'sell'
    inverse = cfg['market_type'] == 'inverse'
    walk = open_lots(counted, botid, entry, inverse)
    lots, unmatched = walk['lots'], walk['no_lot']
    book = _book(counted, botid, cfg, 1 << 62, fleet)
    sign = 1.0 if entry == 'buy' else -1.0
    pos = abs(book['position'])
    held = sum(q for _, q in lots)
    if inverse:
        open_cost = sum(q / p for p, q in lots)
        shift = sign * ((pos / book['avg_cost'] if book['avg_cost'] else 0.0) - open_cost)
        scale = sum(f['qty'] / f['price'] for f in counted if f['price'])
    else:
        open_cost = sum(p * q for p, q in lots)
        shift = sign * (open_cost - book['avg_cost'] * pos)
        scale = sum(f['qty'] * f['price'] for f in counted)
    unit = 'coin' if inverse else 'quote'
    tol = IDENT_ABS[unit] + IDENT_REL * scale
    lots_off = abs(held - pos) > 1e-9 * max(1.0, pos)
    gap = got['trip_gross'] - got['realized'] - shift
    first = first_disagreement(walk['exits'], got['rows'], inverse)
    return {'gross': got['trip_gross'], 'realised': got['realized'], 'shift': shift,
            'lots_qty': held, 'position': pos, 'tol': tol, 'gap': gap, 'no_lot': unmatched,
            'same_rung': walk['same_rung'], 'first_off': first,
            'off': bool(unmatched) or lots_off or abs(gap) > tol, 'lots_off': lots_off}, None


# --- one fleet ---------------------------------------------------------------

def _market_key(cfg):
    return ('hyperliquid' if cfg['venue'] == 'hyperliquid' else 'bybit',
            cfg['market_type'], cfg['symbol'])


def _collected(kept, key):
    from .report import kept_venue_key
    return (kept.get('collected') or {}).get(kept_venue_key(key[0], key[1], key[2]))


def check_fleet(fleet, kept, now_ms, clients, days=LOOKBACK_DAYS, portfolio_rows=None,
                shared=None):
    """One fleet's report: {'t', 'days', 'bots': {botid: entry}, 'unread':
    [why], 'shared': [notes]}. `clients` are the read clients (fakes in
    specs); `portfolio_rows` the fleet's portfolio state ({botid: row});
    `shared` {(venue, market_type, symbol): [other fleets]} for notes."""
    from .config import market_rows
    from .report import attribute, fleet_maps, make_botid
    key_of, entry_sides, closers, _ = fleet_maps(fleet)
    botids = list(key_of)
    rows = market_rows(fleet)
    by_market = {}
    for cfg in rows:
        by_market.setdefault(_market_key(cfg), []).append(cfg)
    report = {'t': now_ms / 1000.0, 'days': days, 'bots': {}, 'unread': [], 'shared': [],
              'behind': []}
    start = int(now_ms - days * DAY_MS)
    for key, cfgs in sorted(by_market.items()):
        venue, mt, sym = key
        for other in (shared or {}).get(key, []):
            report['shared'].append(f'{mt} {sym} is also traded by fleet {other}: '
                                    'each fill is attributed by its link id (R1)')
        mark = _collected(kept, key)
        names = {make_botid(c['market_type'], c['symbol'], c['side']): c for c in cfgs}
        end = None if mark is None else int(mark - SETTLE_MS)
        if mark is None or now_ms - mark > BEHIND_MS or end <= start:
            # a ledger behind shortens the window — or empties it: said,
            # never a clean report over days nobody compared
            report['behind'].append({'market': f'{mt} {sym}', 'mark': mark})
        if mark is None:
            for b in names:
                report['bots'][b] = {'market': f'{mt} {sym}', 'note': 'the ledger has not collected this market yet'}
            continue
        if end <= start:
            for b in names:
                report['bots'][b] = {'market': f'{mt} {sym}', 'note': 'the ledger stops before the window'}
            continue
        try:
            theirs, hl_closed = venue_fills(clients, venue, mt, sym, start, end)
        except Exception as e:                                    # noqa: BLE001
            report['unread'].append(f'{venue} {mt} {sym}: {e}')
            continue
        theirs = [f for f in theirs if start <= f['time_ms'] <= end]
        when = {_key(f): f['time_ms'] for f in theirs}
        ours = [f for f in kept.get('fills') or []
                if (f.get('venue'), f.get('market_type'), f.get('symbol')) == key
                and start <= f['time_ms'] <= end]
        missing, extra, changed = compare_fills(ours, theirs)
        everyone = {b: {'market': f'{mt} {sym}', 'missing': [], 'extra': [], 'changed': []}
                    for b in names}
        for label, fills in (('missing', missing), ('extra', extra), ('changed', changed)):
            for f in fills:
                who = owner_name(f, botids, closers)
                who = f'unowned {sym}' if who == 'unowned' else who
                everyone.setdefault(who, {'market': f'{mt} {sym}', 'missing': [], 'extra': [],
                                          'changed': []})[label].append(_key(f))
        # the venue's position holds every fill on the market: one no bot
        # owns (R3, a hand's, another fleet's) moves its closed P&L and no
        # book of ours — counted the readout's way (R16: an unlinked exit
        # is a bot's only while it holds)
        market = [f for f in kept.get('fills') or []
                  if (f.get('venue'), f.get('market_type'), f.get('symbol')) == key]
        unowned_n = sum(1 for k, f in attribute(market, botids, closers, entry_sides)
                        if not isinstance(k, str) and f['time_ms'] >= start)
        pair = len(names) > 1
        for b, cfg in names.items():
            entry = everyone[b]
            entry['kind'] = ('grid' if cfg.get('lower') and cfg.get('upper')
                             else 'dca' if cfg.get('strategy') == 'martingale' else 'bot')
            entry['unit'] = sym[:-3] if mt == 'inverse' else ''
            record = bot_record(kept, fleet, b)
            exit_side = 'sell' if cfg['side'] == 'long' else 'buy'

            def venue_rows(frm, exit_side=exit_side):
                if venue == 'hyperliquid':       # closedPnl per fill, gross at the source
                    return [{'order_id': None, 'gross': v, 'stated': v, 'qty': 0.0}
                            for k, v in hl_closed.items() if frm <= when.get(k, -1) <= end]
                return venue_realised(clients, mt, sym, frm, end, exit_side if pair else None)
            exits = (None if venue == 'hyperliquid' else
                     [f for f in theirs if f['side'] == exit_side and owner_name(f, botids, closers) == b])
            try:
                entry['realised'], entry['realised_note'] = check_realised(
                    record, cfg, b, fleet, start, end, unowned_n, venue_rows, exits)
            except Exception as e:                                # noqa: BLE001
                entry['realised'], entry['realised_note'] = None, None
                report['unread'].append(f'{venue} {mt} {sym} closed P&L: {e}')
            try:
                entry['identity'], entry['identity_note'] = check_identity(kept, fleet, b, cfg, record)
            except Exception as e:                                # noqa: BLE001 — one bot's own
                entry['identity'], entry['identity_note'] = None, None
                entry['failed'] = f'its identity could not be worked ({type(e).__name__}: {e})'
        for b, entry in everyone.items():
            report['bots'][b] = entry
    for b, row in (portfolio_rows or {}).items():
        cfg = next((c for c in fleet['bots'] if c.get('strategy') == 'portfolio'
                    and f"pfo{c.get('name')}" == b), None)
        if cfg is not None:
            shorts = {(c['market_type'], c['symbol']) for c in rows if c['side'] == 'short'}
            report['bots'][b] = check_portfolio(cfg, b, row, now_ms, clients, days,
                                                report['unread'], shorts)
    return report


def portfolio_markets(cfg, row):
    """A portfolio row's markets: [(kind, market_type, symbol, book key)]
    — every leg (H2), and a hedge's old market a move left a book on (H17)."""
    from .portfolio import leg_markets
    out = {f'{k}:{c}': (k, mt, sym) for k, c, mt, sym, _ in leg_markets(cfg)}
    for key, book in (row.get('books') or {}).items():
        if book.get('symbol') and book.get('market_type'):
            out[key] = ('hedge', book['market_type'], book['symbol'])
    return [(k, mt, sym, None if k == 'spot' else key) for key, (k, mt, sym) in sorted(out.items())]


def check_portfolio(cfg, botid, row, now_ms, clients, days, unread, others=()):
    """F39/F40 for a portfolio row (D78), on the Bybit account it trades:
    1. its fills on each leg in the window are among the ids its row has
    settled (`seen`, its newest SEEN_CAP: a full list judges only the
    fills no older than the oldest of them the venue lists, and none when
    it lists none); extras are not judged — `seen` keeps no times.
    2. each perp book's realised (since the row's anchor, gross, in the
    leg's settle coin) against the venue's closed P&L on the closing side
    (a short closes by buying), when the anchor is within PORTFOLIO_DAYS.
    A market another row of the fleet shorts too (`others`) is not
    compared: its closed P&L is both rows'. Check 3 is a grid's alone."""
    start = int(now_ms - days * DAY_MS)
    end = int((row.get('fills_to_ms') or now_ms) - SETTLE_MS)
    seen = set(str(x) for x in row.get('seen') or [])
    entry = {'kind': 'portfolio', 'market': 'portfolio', 'missing': [], 'extra': [], 'changed': [],
             'realised': None, 'realised_note': None, 'books': {}}
    prefix = botid + '-'
    theirs = []
    for kind, mt, sym, _ in portfolio_markets(cfg, row):
        try:
            got, _ = venue_fills(clients, 'bybit', mt, sym, start, end)
        except Exception as e:                                    # noqa: BLE001
            unread.append(f'bybit {mt} {sym}: {e}')
            continue
        theirs += [f for f in got if str(f.get('link_id') or '').startswith(prefix)
                   and start <= f['time_ms'] <= end]
    theirs.sort(key=lambda f: f['time_ms'])
    judged = theirs
    if len(seen) >= SEEN_CAP:                   # the row forgot its oldest ids
        held = [f['time_ms'] for f in theirs if _key(f) in seen]
        judged = [f for f in theirs if held and f['time_ms'] >= min(held)]
    entry['missing'] = [_key(f) for f in judged if _key(f) not in seen]
    since = row.get('since_ms')
    if since is None or since < now_ms - PORTFOLIO_DAYS * DAY_MS:
        entry['realised_note'] = ('its books count from its anchor, before the '
                                  f'{PORTFOLIO_DAYS:.0f}-day reach; portfolio_rebuild replays them whole')
        return entry
    for kind, mt, sym, key in portfolio_markets(cfg, row):
        book = (row.get('books') or {}).get(key) if key else None
        if book is None:
            continue
        if (mt, sym) in others:
            entry['realised_note'] = f'{mt} {sym} is shorted by another row too: its closed P&L is both'
            continue
        unit = 'coin' if mt == 'inverse' else 'quote'
        try:
            got = venue_realised(clients, mt, sym, since, end + SETTLE_MS, 'buy')
        except Exception as e:                                    # noqa: BLE001
            unread.append(f'bybit {mt} {sym} closed P&L: {e}')
            continue
        venue = sum(r['gross'] for r in got)
        tol = REAL_ABS[unit] + REAL_REL * sum(r['exit_value'] for r in got)
        off = abs(book['realized'] - venue) > tol
        entry['books'][key] = {'ours': book['realized'], 'venue': venue, 'tol': tol, 'off': off,
                               'unit': sym[:-3] if mt == 'inverse' else ''}
    return entry


# --- what is said ------------------------------------------------------------

def _num(v):
    return f'{v:+,.2f}' if abs(v) >= 0.01 or v == 0 else f'{v:+.8f}'


def _ids(ids):
    return ', '.join(ids[:SHOW_IDS]) + (f' +{len(ids) - SHOW_IDS} more' if len(ids) > SHOW_IDS else '')


def problems(report, now=None):
    """What is off in one fleet's report, each a short phrase; none when
    it agrees. A venue that could not be read is said, never agreement."""
    now = time.time() if now is None else now
    out = []
    if now - report['t'] > STALE_S:
        out.append(f"report {(now - report['t']) / 3600:.0f} h old — did the check run?")
    for u in report.get('unread') or []:
        out.append(f'couldn\'t read {u}')
    for b in report.get('behind') or []:
        out.append(f"ledger has never collected {b['market']}" if b['mark'] is None else
                   f"ledger collected {b['market']} only to "
                   + time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(b['mark'] / 1000)))
    for b, e in sorted((report.get('bots') or {}).items()):
        said = [e['failed']] if e.get('failed') else []
        n = len(e.get('missing') or [])
        if n:
            said.append(f"{n} fill{'s' if n > 1 else ''} missing from the ledger ({_ids(e['missing'])})")
        n = len(e.get('extra') or [])
        if n:
            said.append(f"{n} fill{'s' if n > 1 else ''} in the ledger the venue does not list "
                        f"({_ids(e['extra'])})")
        n = len(e.get('changed') or [])
        if n:
            said.append(f"{n} fill{'s' if n > 1 else ''} differ from the venue's ({_ids(e['changed'])})")
        r = e.get('realised')
        unit = f" {e['unit']}" if e.get('unit') else ''
        if r and r['off']:
            said.append(f"realised {_num(r['ours'])}{unit} vs venue {_num(r['venue'])}{unit}")
        for key, bk in (e.get('books') or {}).items():
            if bk['off']:
                u = f" {bk['unit']}" if bk.get('unit') else ''
                said.append(f"{key} realised {_num(bk['ours'])}{u} vs venue {_num(bk['venue'])}{u}")
        i = e.get('identity')
        if i and i['off']:
            if i['no_lot']:
                said.append(f"{i['no_lot']} exit{'s' if i['no_lot'] > 1 else ''} close no lot the "
                            'record holds (an entry missing before the window?)')
            elif i['lots_off']:
                said.append(f"open lots hold {i['lots_qty']:.10g}, the book {i['position']:.10g}")
            else:
                said.append(f"trips {_num(i['gross'])} − realised {_num(i['realised'])} is "
                            f"{_num(i['gross'] - i['realised'])}, the open lots say {_num(i['shift'])}")
        if said:
            out.append(f'{b} ' + ' · '.join(said))
    return out


def reports(root=ROOT):
    return sorted(Path(root).glob('*.json'))


def digest_lines(root=None, now=None, tags=None):
    """F39: the digest's lines — one per fleet with something off; none
    when every report agrees, or when no check has run at all. `tags`: the
    digest's own fleets — a report of a fleet no longer named is left
    alone. One report that will not read is its own line, never the rest's."""
    now = time.time() if now is None else now
    out = []
    for p in reports(ROOT if root is None else root):
        if tags is not None and p.stem not in tags:
            continue
        try:
            said = problems(json.loads(p.read_text()), now)
        except Exception as e:                                    # noqa: BLE001
            said = [f'unreadable — {type(e).__name__}: {e}']
        if said:
            out.append(f'📏 drift · {p.stem}: ' + ' · '.join(said))
    return out


def details(report):
    """`show`'s lines below the digest's: every figure, compared or not."""
    out = []
    for n in report.get('shared') or []:
        out.append(f'  note: {n}')
    for b in report.get('behind') or []:
        out.append(f"  ledger mark for {b['market']}: " + ('none' if b['mark'] is None else
                   time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(b['mark'] / 1000))))
    for b, e in sorted((report.get('bots') or {}).items()):
        head = f"  {b} ({e.get('kind', 'bot')}, {e.get('market', '')})"
        if e.get('note'):
            out.append(f"{head}: {e['note']}")
            continue
        if e.get('failed'):
            out.append(f"{head}: {e['failed']}")
        out.append(head + f": fills missing {len(e.get('missing') or [])}, extra "
                   f"{len(e.get('extra') or [])}, changed {len(e.get('changed') or [])}")
        for label in ('missing', 'extra', 'changed'):
            if e.get(label):
                out.append(f"    {label}: {', '.join(e[label])}")
        r = e.get('realised')
        if r:
            out.append(f"    realised ours {r['ours']:+.8f} · venue {r['venue']:+.8f} "
                       f"({r['rows']} rows) · tolerance {r['tol']:.8f} · fees ours {r['fees']:.8f} · from "
                       + time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(r['from_ms'] / 1000)))
            out.append(f"    venue's closedPnl + fees − gross (the fees/funding residue): "
                       f"{r.get('residue', 0.0):+.8f} · orders across the window left out: "
                       f"{r.get('straddling', 0)}")
        elif e.get('realised_note'):
            out.append(f"    realised not compared: {e['realised_note']}")
        for key, bk in (e.get('books') or {}).items():
            out.append(f"    {key} realised ours {bk['ours']:+.8f} · venue {bk['venue']:+.8f} · "
                       f"tolerance {bk['tol']:.8f}")
        i = e.get('identity')
        if i:
            out.append(f"    identity: trips {i['gross']:+.8f} − realised {i['realised']:+.8f} = "
                       f"{i['gross'] - i['realised']:+.8f}; open lots {i['shift']:+.8f} "
                       f"({i['lots_qty']:.10g} held, book {i['position']:.10g})")
            if i.get('same_rung'):
                out.append(f"    same-rung exits (R9, a trip of ~0): {i['same_rung']}")
            d = i.get('first_off')
            if d:
                out.append(f"    first exit the pairing and the walk price apart: {d['fill']} at "
                           + time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(d['time_ms'] / 1000))
                           + f" — pairing {d['pairing']:.8f}, walk {d['walker']:.8f}")
        elif e.get('identity_note'):
            out.append(f"    identity not checked: {e['identity_note']}")
    return out


# --- running it --------------------------------------------------------------

def _clients(fleet):
    """The read clients a fleet's venues need — never a write client."""
    from .config import market_rows
    venues = {c['venue'] for c in market_rows(fleet)}
    out = {}
    if venues - {'hyperliquid'} or any(c.get('strategy') == 'portfolio' for c in fleet['bots']):
        from .exchange.bybit.client import Client
        out['bybit'] = Client()
    if 'hyperliquid' in venues:
        from .exchange.hyperliquid.client import InfoClient
        out['hl'] = InfoClient()
    return out


def _shared(fleets):
    """{(venue, account, market_type, symbol): [fleet tags]} across the
    fleets of one run — two fleets on one account and market."""
    from .config import market_rows
    seen = {}
    for tag, fleet in fleets:
        for c in market_rows(fleet):
            k = (_market_key(c), fleet.get('account', 'default'))
            if tag not in seen.setdefault(k, []):
                seen[k].append(tag)
    out = {}
    for tag, fleet in fleets:
        out[tag] = {}
        for (key, acct), tags in seen.items():
            if acct == fleet.get('account', 'default') and tag in tags and len(tags) > 1:
                out[tag][key] = [t for t in tags if t != tag]
    return out


def run(fleet_paths, root=ROOT, now_ms=None, days=LOOKBACK_DAYS, clients_for=None,
        fills_root='logs/fills'):
    """Check each fleet and write its report; one fleet's trouble is its
    own report's, never the others' (a whole-fleet failure is written as
    unread, so the digest says it rather than an old clean report)."""
    from .config import validate_fleet
    from .durable import fleet_tag, state_path
    from .exchange.env import select_account
    from .kept_fills import load, store_path
    from .trades import with_trades
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    loaded = []
    for fp in fleet_paths:
        try:
            raw = json.loads(Path(fp).read_text())
            loaded.append((fp, raw, with_trades(fp, validate_fleet(raw)), None))
        except Exception as e:                                    # noqa: BLE001
            loaded.append((fp, None, None, e))
    shared = _shared([(fleet_tag(fp), f) for fp, _, f, err in loaded if err is None])
    written = []
    for fp, raw, fleet, err in loaded:
        tag = fleet_tag(fp)
        if err is None:
            try:
                if fleet['bots']:
                    select_account(fleet['account'])               # H5
                clients = (clients_for or _clients)(fleet)
                kept = load(store_path(fp, fills_root))
                pf = {}
                if any(c.get('strategy') == 'portfolio' for c in fleet['bots']):
                    p = state_path(fp, raw, 'portfolio_state')
                    pf = json.loads(p.read_text()) if p.exists() else {}
                report = check_fleet(fleet, kept, now_ms, clients, days, pf, shared.get(tag))
            except Exception as e:                                # noqa: BLE001
                err = e
        if err is not None:
            report = {'t': now_ms / 1000.0, 'days': days, 'bots': {}, 'shared': [],
                      'unread': [f'the fleet ({type(err).__name__}: {err})']}
        path = Path(root) / f'{tag}.json'
        write_json(path, report)
        written.append((path, report))
    return written


def main(argv):
    cmd = argv[0] if argv else ''
    root = Path(argv[argv.index('--root') + 1]) if '--root' in argv else ROOT
    if cmd == 'run':
        days = float(argv[argv.index('--days') + 1]) if '--days' in argv else LOOKBACK_DAYS
        fleets = [a for i, a in enumerate(argv[1:], 1)
                  if not a.startswith('--') and argv[i - 1] not in ('--days', '--root')]
        if not fleets:
            print('usage: python3 -m gridgremlin.pnl_drift run <fleet.json> ... [--days 7]')
            return 2
        from common.env import load_env
        load_env()
        for path, report in run(fleets, root, days=days):
            said = problems(report)
            print(f'{path.stem}: ' + (' · '.join(said) if said else
                                      f"agrees — {len(report['bots'])} bots over {days:g} days"))
        return 0                       # a drift is reported, never a failed unit
    if cmd == 'show':
        now = time.time()
        lines = digest_lines(root, now)
        print('\n'.join(lines) if lines else 'every fleet agrees with its venue')
        for p in reports(root):
            try:
                r = json.loads(p.read_text())
            except (OSError, ValueError):
                continue
            print(f"{p.stem} (checked {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(r['t']))}, "
                  f"{r.get('days', LOOKBACK_DAYS):g} days):")
            print('\n'.join(details(r)) or '  nothing to check')
        return 0
    print('usage: python3 -m gridgremlin.pnl_drift run <fleet.json> ... [--days 7] | show')
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
