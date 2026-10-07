# The readout (SPEC R1-R5): venue fills -> per-bot grid profit vs total P&L
# (D8's reporting model). Read-only by construction — no write client in this
# module's import graph (R4). Usage:
#   python3 -m gridgremlin.report <fleet.json> [--hours N]
import json
import sys
import time
from pathlib import Path

from .apply import make_botid, rung_of
from .config import validate_fleet
from .ladder import SEED_RUNG, fee_floor_for
from .exchange.env import load_env
from .exchange.errors import VenueError

EPS = 1e-12
HL_FILL_CAP = 2000


def owner_of(link_id, botids):
    """R1: a fill is a bot's iff rung_of parses under that botid (I1)."""
    for botid in botids:
        if rung_of(link_id, botid) is not None:
            return botid
    return None


def closer_of(fill, closers):
    """R7: a fill the VENUE created to close a position (hosted TP/SL,
    trailing, liquidation) carries no link — the venue says what it is, and
    I2 says exactly one bot owns (market, symbol, side), so the fill belongs
    to the bot whose exits sit on that side. Evidence, not inference."""
    if not fill.get('venue_closed'):
        return None
    return closers.get((fill.get('market_type'), fill['symbol'],
                        fill['side']))


def new_book():
    return {'fills': 0, 'first_side': None, 'first_ms': None,   # R18
            'bought': 0.0, 'sold': 0.0, 'realized': 0.0,
            'fees': 0.0, 'position': 0.0, 'avg_cost': 0.0, 'inverse': False,
            'funding': 0.0,        # D63: set after the ledger, per window
            # R6 — the activity layer, same fills, no new state:
            'trips': 0,            # realisation events (a grid's round trips)
            'rounds': 0,           # flat crossings (a martingale's rounds)
            'round_pnl_sum': 0.0,  # realized per completed round, summed
            'so_fills': 0,         # entry fills at rung >= 1 (safety orders)
            'same_rung': 0,        # R9: exits filled at a price we BOUGHT at
            'gap_realized': 0.0,   # R12: exits measured against their OWN
            'gap_trips': 0,        #      rung (R11's identity), summed
            '_entry_px': set(),    # prices this book has entered at
            'max_depth': 0,        # deepest safety rung ever reached
            'anchored': False,     # R13: re-anchored flat at a base order
            '_round_realized0': 0.0, '_round_depth': 0}


def apply_fill(book, side, price, qty, fee, inverse=False, rung=None,
               entry_side=None, own_entry=None):
    """R2: average-cost accounting — a reduce realises, a flip re-anchors.
    A4's unit law holds here too: an inverse book realises in the BASE coin
    (qty is $1 contracts), a linear/spot book in the quote coin.
    R6: the same stream carries the activity — a realisation is a TRIP, a
    flat crossing closes a ROUND, an entry fill at rung >= 1 is a SAFETY
    order and its rung is the round's depth."""
    signed = qty if side == 'buy' else -qty
    pos = book['position']
    prev_avg = book['avg_cost']   # R9 reads the pre-fill cost
    if book['first_side'] is None:
        book['first_side'] = side
    book['inverse'] = inverse
    if entry_side is not None and side == entry_side and rung and rung >= 1:
        book['so_fills'] += 1
        book['_round_depth'] = max(book['_round_depth'], rung)
        book['max_depth'] = max(book['max_depth'], book['_round_depth'])
    if abs(pos) < EPS or (pos > 0) == (signed > 0):
        total = abs(pos) + qty
        book['avg_cost'] = (book['avg_cost'] * abs(pos) + price * qty) / total
        book['position'] = pos + signed
    else:
        closed = min(abs(pos), qty)
        held = 1.0 if pos > 0 else -1.0
        book['trips'] += 1
        if inverse:
            book['realized'] += closed * (1.0 / book['avg_cost']
                                          - 1.0 / price) * held
        else:
            book['realized'] += (price - book['avg_cost']) * closed * held
        book['position'] = pos + signed
        if qty - closed > EPS:
            book['avg_cost'] = price
        elif abs(book['position']) < EPS:
            book['position'], book['avg_cost'] = 0.0, 0.0
            book['rounds'] += 1                       # a flat crossing
            book['round_pnl_sum'] += (book['realized']
                                      - book['_round_realized0'])
            book['_round_realized0'] = book['realized']
            book['_round_depth'] = 0
    # R9: the zero-spread signature is an exit whose margin against the
    # cost it closes is inside the fee. The first cut compared against a
    # lifetime set of every entry price — grids REUSE a fixed lattice, so
    # profitable full-gap trips flagged whenever a later round exited where
    # an earlier one entered (audit 2026-08-07 H1: two profitable bots
    # chased). The margin is per-exit, against this book's own average.
    entering = (abs(pos) < EPS or (pos > 0) == (signed > 0))
    if own_entry is not None and not entering:
        # R11: a grid exit is judged against ITS OWN entry level (the lot
        # one rung below for a long, above for a short: G25/D36), never
        # the book's average. A sliding grid's average moves with every
        # lot it adds, so a full-gap exit below the average read as churn
        # (6 of 80 flagged on 2026-10-03, every one a full gap by identity)
        margin = (price - own_entry) * (1.0 if entry_side == 'buy' else -1.0)
        if margin / own_entry < 0.0005:
            book['same_rung'] += 1
    elif not entering and abs(pos) >= EPS and prev_avg > 0:
        margin = (price - prev_avg) * (1.0 if pos > 0 else -1.0)
        if abs(margin) / prev_avg < 0.0005:   # inside a spot fee
            book['same_rung'] += 1
    if own_entry is not None:
        # R12: what THIS trip earned, by the rung it closes. The book's
        # realized is average-cost: a long grid that bought cheaper lots on
        # the way down carries an average above its exits, so every full-gap
        # trip "realised" a loss while the remainder's mark-to-average rose
        # by the same amount (2026-10-03: -156 per trip printed on a grid
        # whose every exit was a full gap). The sum is the same; the split
        # is not. Identity needs no book: an exit-side fill with a rung
        # closes that rung's lot, whatever a window that opened mid-round
        # (R7) made of the position — so this is summed on every such fill,
        # for the fill's whole quantity.
        sign = 1.0 if entry_side == 'buy' else -1.0
        if inverse:
            book['gap_realized'] += qty * (1.0 / own_entry - 1.0 / price) * sign
        else:
            book['gap_realized'] += (price - own_entry) * qty * sign
        book['gap_trips'] += 1
    book['fees'] += fee
    book['fills'] += 1
    book['bought' if side == 'buy' else 'sold'] += qty
    return book


def exit_side_owner(fill, closers):
    """R16: an UNLINKED fill on a market's exit side belongs to the bot
    whose exits sit on that side, whoever created it — a modify the venue
    rebuilt without the link (I6's incident), a hand close, a venue close
    without a label. I2 makes it unambiguous: one bot owns (market, symbol,
    side), and on a hedge pair the long's exits are sells and the short's
    are buys. The readout books the money where it went; the engine's own
    law is untouched — to it an unlinked reduce is still an outside hand
    (D1), which is the signal the kill needs."""
    if fill.get('link_id'):
        return None                       # linked to someone: not this rule
    return closers.get((fill.get('market_type'), fill['symbol'],
                        fill['side']))


def attribute(fills, botids, closers=None, entry_sides=None):
    """R1/R7/R16 in time order: (key, fill) for every fill. An unlinked
    exit-side fill (R16) is a bot's only while the bot's OWN fills say it
    holds something, and only up to what it holds — a hand sale made while
    the bot was flat, or beyond its holding, is not its exit (the demo SOL
    long read 8.2 short of the exchange the moment R16 landed: the owner's
    September hand-flattening sat inside the month). The excess goes to
    the unowned bucket (R3) as its own fill."""
    closers, entry_sides = closers or {}, entry_sides or {}
    running, out = {}, []
    for f in sorted(fills, key=lambda f: f['time_ms']):
        key = owner_of(f['link_id'], botids) or closer_of(f, closers)
        if key is None:
            bot = exit_side_owner(f, closers)
            held = running.get(bot, 0.0) if bot else 0.0
            if bot and held > EPS:
                take = min(f['qty'], held)
                if take < f['qty'] - EPS:
                    rest = dict(f, qty=f['qty'] - take,
                                fee=f['fee'] * (1 - take / f['qty']),
                                exec_id=f"{f['exec_id']}:rest")
                    out.append((('unowned', f['symbol']), rest))
                    f = dict(f, qty=take, fee=f['fee'] * take / f['qty'])
                key = bot
            else:
                key = ('unowned', f['symbol'])
        if isinstance(key, str):
            signed = f['qty'] if f['side'] == entry_sides.get(key) else -f['qty']
            running[key] = max(running.get(key, 0.0) + signed, 0.0)
        out.append((key, f))
    return out


def ledger(fills, botids, inverse_ids=(), entry_sides=None, closers=None,
           grids=None, rounders=()):
    """R1/R3: time-ordered fills -> books keyed by botid, or by
    ('unowned', symbol) — external activity is reported, never dropped.
    R6: rung and entry side ride along so the activity layer can count.
    R7: venue-created closes attribute by the position they closed.
    R11: `grids` maps a grid botid to its validated config, so an exit's
    own entry level is known from its link rung.
    R13: `rounders` are the bots whose round begins FLAT with a base order
    — the entry side's rung 0 (a martingale; D37's maker base rests there
    too). A window that opened mid-round carries a phantom position that
    no later close can land at zero, so its rounds counted nothing (ADA,
    692 fills and no round). At a NEW base order's first fill the book is
    re-anchored flat: identity, not inference. A split base order shares
    one link and anchors once."""
    books, entry_sides = {}, entry_sides or {}
    closers, grids = closers or {}, grids or {}
    last_base = {}
    entry_px = {}        # R15: (bot, rung) -> the price that lot was bought at
    for key, f in attribute(fills, botids, closers, entry_sides):   # R16
        rung = rung_of(f['link_id'], key) if isinstance(key, str) else None
        if (key in rounders and rung == 0 and f['side'] == entry_sides.get(key)
                and f['link_id'] != last_base.get(key)):
            last_base[key] = f['link_id']
            book = books.setdefault(key, new_book())
            if abs(book['position']) >= EPS:          # opened mid-round
                book['position'], book['avg_cost'] = 0.0, 0.0
                book['anchored'] = True
                book['_round_realized0'] = book['realized']
                book['_round_depth'] = 0
        own = None
        if rung is not None and key in grids and f['side'] == \
                entry_sides.get(key) and rung != SEED_RUNG:
            entry_px[(key, rung)] = f['price']        # R15: the lot's own price
        if rung is not None and key in grids and f['side'] != \
                entry_sides.get(key) and rung != SEED_RUNG:
            # R15: the lot this exit closes was bought at a PRICE the
            # window may have seen — the venue's own number first; the
            # config's lattice level only when the entry fill is not in the
            # window (a slid or re-identified lattice is then still right
            # whenever the buy was seen; the SOL long 2026-10-05: 60 of 61
            # trips flagged after a 31->19 re-lattice, judged against a
            # lattice its older fills were never on)
            step = -1 if entry_sides.get(key) == 'buy' else 1
            own = entry_px.get((key, rung + step))
            if own is None:
                from .ladder import lattice_price
                own = lattice_price(grids[key], rung + step)
        book = books.setdefault(key, new_book())
        if book['first_ms'] is None:
            book['first_ms'] = f['time_ms']           # R18: since when
        apply_fill(book,
                   f['side'], f['price'], f['qty'], f['fee'],
                   inverse=key in inverse_ids, rung=rung, own_entry=own,
                   entry_side=entry_sides.get(key))
    return books


def per_trip(book, truncated=False):
    """R12: a grid's figure per trip is what its exits earned against
    their own rungs, which a window opening mid-round cannot spoil; a book
    with no rung-identified exit falls back to average-cost realized per
    trip (fills without links, R9's world) — unless the window is truncated
    (R7), when that book's position is a phantom and the figure is None,
    never a guess. An inverse book's figure is in the base coin, as its
    realized is (A4)."""
    if book['gap_trips']:
        return book['gap_realized'] / book['gap_trips']
    if truncated or not book['trips']:
        return None
    return book['realized'] / book['trips']


def per_trip_net(book, truncated=False):
    """D63's companion: what a trip earned AFTER fees, as every grid
    platform states its grid profit — both legs' fees off each trip, at
    this book's average fee per fill. None where per_trip is None."""
    gross = per_trip(book, truncated)
    if gross is None:
        return None
    return gross - 2.0 * (book['fees'] / book['fills'] if book['fills'] else 0.0)


def unreal_pnl(book, mark):
    """Mark-to-average on the open remainder, in the book's own coin (A4)."""
    if abs(book['position']) < EPS:
        return 0.0
    if mark is None:
        return None
    if book.get('inverse'):
        return book['position'] * (1.0 / book['avg_cost'] - 1.0 / mark)
    return (mark - book['avg_cost']) * book['position']


def total_pnl(book, mark):
    """R5: grid profit (realized - fees) plus mark-to-average on the open
    remainder; an unknown mark yields None, never a guess. Inverse books
    are BASE-coin throughout and convert to quote AT MARK for display.
    D63: plus the funding paid or received over the same window — its own
    term; unread funding counts as nothing here and is said where shown."""
    net = book['realized'] - book['fees'] + (book.get('funding') or 0.0)
    u = unreal_pnl(book, mark)
    if u is None:
        return None
    total = net + u
    if book.get('inverse'):
        return total * mark if mark is not None else None
    return total


def fleet_maps(fleet):
    """R18: what attribution needs from a fleet — each bot's market, its
    entry side, the exit side it closes by (I2), and each market's venue."""
    key_of, entry_sides, closers, venue_of = {}, {}, {}, {}
    for cfg in fleet['bots']:
        b = make_botid(cfg['market_type'], cfg['symbol'], cfg['side'])
        key_of[b] = (cfg['market_type'], cfg['symbol'])
        entry_sides[b] = 'buy' if cfg['side'] == 'long' else 'sell'
        closers[(cfg['market_type'], cfg['symbol'],
                 'sell' if cfg['side'] == 'long' else 'buy')] = b
        venue_of[(cfg['market_type'], cfg['symbol'])] = cfg['venue']
    return key_of, entry_sides, closers, venue_of


def kept_held(fleet, held):
    """R18: what each bot holds, for finding its record's start. A spot
    bot's figure is the engine's own count from its last snapshot (D58: its
    coins, not the wallet's — the venue states no spot position); a spot bot
    the snapshot does not name has no figure."""
    out = dict(held)
    view = _watchdog_view(fleet) or {}
    belief = (view.get('belief') or {}).get('bots') or {}
    for cfg in fleet['bots']:
        if cfg['market_type'] != 'spot':
            continue
        b = make_botid(cfg['market_type'], cfg['symbol'], cfg['side'])
        pos = (belief.get(b) or {}).get('position')
        if pos is None:
            out.pop(b, None)
        else:
            out[b] = abs(float(pos))
    return out


def opening_fill(botid, entry_side, fresh):
    """R18: a fresh start's opening balance as the record's first fill —
    the holding at the price when recording began, no fee."""
    return {'exec_id': f'open:{botid}', 'time_ms': fresh['time_ms'],
            'side': entry_side, 'price': fresh['price'], 'qty': fresh['qty'],
            'fee': 0.0, 'link_id': f'{botid}-0-open', 'symbol': '',
            'market_type': ''}


def counted_fills(botid, own, entry_side, anchor, live):
    """R18: the fills a bot's kept book counts — from its stored anchor
    (the collector's, fixed), or a live clean start that reaches further
    back; a fresh anchor opens with its opening balance. Returns (counted,
    opened) or None when the record has no whole start yet."""
    start, opened = None, None
    if anchor and anchor['kind'] == 'clean':
        start = anchor['time_ms'] if live is None \
            else min(live, anchor['time_ms'])
    elif anchor:
        if live is not None and live <= anchor['time_ms']:
            start = live
        else:
            opened = anchor
    else:
        start = live
    if start is not None:
        return [f for f in own if f['time_ms'] >= start], None
    if opened is None:
        return None
    counted = [f for f in own if f['time_ms'] > opened['time_ms']]
    if opened['qty'] > 0:
        counted = [opening_fill(botid, entry_side, opened)] + counted
    return counted, opened


def kept_venue_key(venue, market_type, symbol):
    """R18: the kept ledger's collection mark for a bot's market."""
    return ('hyperliquid' if venue == 'hyperliquid'
            else f'bybit:{market_type}:{symbol}')


def kept_books(fleet_path, fresh, venue_of, key_of, since_ms, inverse_ids,
               entry_sides, closers, grids, rounders, held,
               root='logs/fills'):
    """R18: every bot's book since its first kept fill — the kept ledger
    merged with this readout's own fresh fills, one fill once (I4). A bot
    whose market was last collected before this window began has a hole
    between the two: `behind` names the moment collection reached, and
    the figure is not shown as whole. None when nothing is kept."""
    from .kept_fills import load, merge, store_path
    path = store_path(fleet_path, root)
    if not path.exists():
        return None
    try:
        kept = load(path)
    except RuntimeError as e:
        print(f'[warn] {e}', file=sys.stderr)
        return None
    tagged = [dict(f, venue='hyperliquid'
                   if venue_of.get((f['market_type'], f['symbol']))
                   == 'hyperliquid' else 'bybit') for f in fresh]
    merged = merge(kept['fills'], tagged)
    anchors = kept.get('anchors') or {}
    books = {}
    for b in key_of:
        own = bot_fills(merged, b, closers, entry_sides)
        live = first_flat_ms(own, entry_sides[b], held.get(b))
        anchor = anchors.get(b)
        if not own and not anchor:
            continue
        # the stored anchor rules (the collector's, fixed); a live clean
        # start counts only when it reaches FURTHER back — a later flat
        # never replaces an anchor, and a lagging read never loses one
        got = counted_fills(b, own, entry_sides[b], anchor, live)
        if got is not None:
            counted, opened = got
        else:                             # no whole record: said, not summed
            if not own:
                continue
            books[b] = dict(new_book(), fills=len(own), whole=False,
                            first_ms=own[0]['time_ms'], realized=None)
            continue
        book = ledger(counted, [b], inverse_ids, entry_sides, closers,
                      grids, rounders=rounders).get(b) or new_book()
        book['whole'] = True
        if opened is not None:
            book['opened'] = {k: opened[k] for k in ('time_ms', 'qty',
                                                     'price')}
            book['first_ms'] = opened['time_ms']
        books[b] = book
    behind = {}
    for b in key_of:
        market_type, symbol = key_of[b]
        done = kept['collected'].get(kept_venue_key(
            venue_of[(market_type, symbol)], market_type, symbol))
        behind[b] = None if done is not None and done >= since_ms \
            else (done or 0)
    return books, behind


# --- venue pulls (reads only) ------------------------------------------------

def _bybit_pull(rows, since_ms, now_ms):
    from .exchange.bybit.client import Client
    from .exchange.bybit.truth import read_fills
    client = Client()
    fills, marks = [], {}
    for category, symbol in sorted({(r['market_type'], r['symbol'])
                                    for r in rows}):
        fills += read_fills(client, category, symbol, since_ms, now_ms)
        try:
            # the CLIENT method, not the raw reader — it knows spot truth
            # needs the instrument's base coin (V6)
            marks[(category, symbol)] = client.read_symbol_truth(
                category, symbol)['mark']
        except (VenueError, OSError):
            marks[(category, symbol)] = None
    return fills, marks


def _hl_pull(rows, since_ms):
    from .exchange.hyperliquid.client import InfoClient
    from .exchange.hyperliquid.truth import read_fills
    client = InfoClient()
    coins = sorted({r['symbol'] for r in rows})
    raw = client.user_fills_by_time(since_ms)
    if len(raw) >= HL_FILL_CAP:
        print(f'[warn] HL answered its {HL_FILL_CAP}-fill cap — the window '
              'is truncated, narrow --hours', file=sys.stderr)
    fills = read_fills(raw, set(coins), client.address)
    marks = {}
    try:                       # ONE read for every coin's mark: the panel's
        meta, ctxs = client.meta_and_ctxs()     # readout shares the fleet's
        names = [e['name'] for e in meta['universe']]   # rate budget
        for coin in coins:
            ctx = ctxs[names.index(coin)] if coin in names else {}
            marks[('linear', coin)] = _f_or_none(ctx.get('markPx'))
    except (VenueError, OSError, ValueError, IndexError):
        for coin in coins:
            marks.setdefault(('linear', coin), None)
    return fills, marks


def _f_or_none(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


# --- R14: money is counted from the last flat -------------------------------

WIDEN_CAP_HOURS = 720.0       # a month: the venue's history has an edge too


def bot_fills(fills, botid, closers=None, entry_sides=None):
    """This bot's own fills: by link, a venue-created close attributed to
    the position it closed (R7), or an unlinked exit-side fill while it
    held (R16) — the same attribution the ledger uses, so the walk and
    the book agree."""
    return [f for key, f in attribute(fills, [botid], closers, entry_sides)
            if key == botid]


def last_flat_ms(fills, entry_side):
    """R14, pure: walk this bot's fills forward keeping its own position;
    the round that is open now began at the first fill AFTER the last
    moment the position was flat. None when the fills never reach flat
    (the round is older than everything seen) — or when there are none."""
    pos, held, last_return = 0.0, False, None
    for i, f in enumerate(fills):
        pos += f['qty'] if f['side'] == entry_side else -f['qty']
        if abs(pos) >= EPS:
            held = True
        elif held:
            last_return = i          # a RETURN to flat, seen, is the tell;
            held = False             # the window's own first fill is not
    if last_return is None:
        return None
    if last_return + 1 < len(fills):
        return fills[last_return + 1]['time_ms']
    return fills[last_return]['time_ms'] + 1     # flat now: nothing open


def first_flat_ms(fills, entry_side, venue_size):
    """R18, pure: the EARLIEST moment this bot's own fills can be counted
    from. Unwind the holding the exchange states now, newest fill first —
    an entry taken off lowers it, an exit taken off raises it; each time it
    lands on flat, the record from that fill on is whole. The earliest such
    landing wins; unwinding below flat is a contradiction (the record
    reaches back into a position bought before it) and stops the walk.
    None when no landing is found, or the exchange's figure is unknown —
    a book that opened mid-position realises against nothing (the first
    backfill: +181k and -202k on one demo BTC pair, 2026-10-05)."""
    if venue_size is None:
        return None
    tol = 1e-9 * max(1.0, venue_size) + EPS
    pos, start = venue_size, None
    for f in sorted(fills, key=lambda f: f['time_ms'], reverse=True):
        pos += -f['qty'] if f['side'] == entry_side else f['qty']
        if pos < -tol:
            break
        if abs(pos) <= tol:
            start = f['time_ms']
    return start


def count_from_flat(botid, hours, now_ms, pull, entry_side,
                    closers=None, venue_size=None):
    """R14: widen this bot's window in doublings up to WIDEN_CAP_HOURS until
    its own fills show a return to flat AND the fills since it add up to
    what the exchange says is held (`venue_size`, the proof that the flat
    is real and not a slice's phantom — R7's lesson); return (fills since
    that point, counted_from, counted_since_ms). `pull(since_ms)` is the
    venue read for this bot's market. 'flat' = found; 'cap' = never in a
    month, the month's fills returned and the truncation stands."""
    entry_sides = {botid: entry_side}
    h, fills = hours, []
    while True:
        h = min(h * 2.0, WIDEN_CAP_HOURS)
        wide_since = now_ms - int(h * 3600 * 1000)
        fills = bot_fills(pull(wide_since), botid, closers, entry_sides)
        start = last_flat_ms(fills, entry_side)
        if start is not None and start > wide_since:
            since = [f for f in fills if f['time_ms'] >= start]
            held = sum(f['qty'] if f['side'] == entry_side else -f['qty']
                       for f in since)
            if venue_size is None or abs(abs(held) - venue_size) <= (
                    1e-9 * max(1.0, venue_size) + EPS):
                return since, 'flat', start
        if h >= WIDEN_CAP_HOURS:
            return fills, 'cap', wide_since


def _venue_held_all(venue, rows):
    """What the exchange says each bot's side holds now — the yardstick a
    flat point must satisfy and the tell that a window is partial (R14).
    One read per venue (Hyperliquid) or per market (Bybit, the hedge pair
    sharing it); a bot the read could not serve is absent."""
    held = {}
    try:
        if venue == 'hyperliquid':
            from .exchange.hyperliquid.client import InfoClient
            from .exchange.hyperliquid.truth import read_positions
            state = InfoClient().clearinghouse_state()
            for cfg in rows:
                held[make_botid(cfg['market_type'], cfg['symbol'], cfg['side'])] = \
                    _side_size(read_positions(state, cfg['symbol']), cfg['side'])
        else:
            from .exchange.bybit.client import Client
            from .exchange.bybit.truth import read_positions
            client, seen = Client(), {}
            for cfg in rows:
                key = (cfg['market_type'], cfg['symbol'])
                if key not in seen:
                    seen[key] = read_positions(client.position_list(*key))
                held[make_botid(cfg['market_type'], cfg['symbol'], cfg['side'])] = \
                    _side_size(seen[key], cfg['side'])
    except (VenueError, OSError, KeyError, ValueError, TypeError):
        pass
    return held


def _side_size(positions, side):
    want = 'Buy' if side == 'long' else 'Sell'
    for p in (positions or {}).values():
        if p.get('size') and p.get('side') == want:
            return abs(float(p['size']))
    return 0.0


# --- the table ---------------------------------------------------------------

def _n(v, nd=2):
    return '—' if v is None else f'{v:,.{nd}f}'


def window_truncated(book, side):
    """R7: a window that opens MID-round sees the close but not the open, so
    the ledger's remainder contradicts the bot's own direction. Say so —
    never print a phantom position as if it were real."""
    if side is None:
        return False
    # a balanced slice nets the phantom away and the sign test passes it
    # (audit 2026-08-07 MED): the window's FIRST fill is the other tell —
    # a one-sided book cannot legitimately open with its exit side
    first = book.get('first_side')
    if first and (first == ('sell' if side == 'long' else 'buy')):
        return True
    if abs(book['position']) < EPS:
        return False
    return (book['position'] < 0) if side == 'long' else (book['position'] > 0)


def _row(name, book, mark, side=None):
    inv = book.get('inverse')
    scale = (mark if inv and mark is not None else 1.0)
    unreal = unreal_pnl(book, mark)
    if inv and mark is None:
        unreal = None
    cut = window_truncated(book, side)
    open_at = ('flat' if abs(book['position']) < EPS
               else f"{book['position']:.10g}@{book['avg_cost']:,.6g}")
    if cut:
        open_at = 'pre-window*'
    def usd(v):
        return None if v is None else v * scale
    return (f"{name:<18}{book['fills']:>6}"
            f"{_n(usd(book['realized'])):>12}{_n(usd(book['fees'])):>10}"
            f"{_n(usd(book.get('funding'))):>10}"
            f"{open_at:>20}{_n(usd(unreal)):>12}"
            f"{_n(total_pnl(book, mark)):>12}")


def _watchdog_view(fleet):
    """The watcher, watched (F1/F2): each bot's ceiling, and how long ago
    the watchdog last swept — its state file's own mtime, so a dead timer
    shows as a growing number instead of a silence."""
    path = fleet.get('watchdog')
    if not path:
        return None
    try:
        wd = json.loads(Path(path).read_text())
        ceilings = {b: v.get('max') for b, v in
                    (wd.get('positions') or {}).items()}
        swept = None
        state = wd.get('state')
        if state and Path(state).exists():
            swept = max(0, int(time.time() - Path(state).stat().st_mtime))
        belief = {}
        snap = wd.get('snapshot')
        if snap and Path(snap).exists():
            lines = Path(snap).read_text().strip().splitlines()
            if lines:
                row = json.loads(lines[-1])
                belief = {'age_s': max(0, int(time.time() - row.get('t', 0))),
                          'bots': row.get('bots', {}),
                          'equity': row.get('equity'),        # R19
                          'mm_rate': row.get('mm_rate'),
                          'tiers': row.get('tiers')}          # D65
        return {'ceilings': ceilings, 'swept_s_ago': swept,
                'belief': belief}
    except (OSError, ValueError):
        return None


def account_leverage(contract):
    """R19, the owner's measure of risk, per exchange, as the exchange
    states it: its own total position value over its own equity figure
    (Hyperliquid's account value; Bybit's margin balance) — every position
    on the account, a hand-held one too. And as if every order filled — by
    DIRECTION, since a long's ladder fills on a fall and a short's on a
    rise and one market cannot do both (summed, the demo read 38.9x for a
    move that cannot happen, 2026-10-06): `fall` adds every long bot's
    unfilled ladder to its row's most in the market (`terms.notional`),
    `rise` every short's, each over the whole collateral — on a unified
    Hyperliquid account the account value is only the margin held so far,
    which a projection outgrows. Conservative: the other side's exits are
    not netted off. {venue: {now, notional, equity, fall, fall_notional,
    rise, rise_notional, collateral, unsized}}; None where unknown."""
    bots, terms = contract.get('bots') or {}, contract.get('terms') or {}
    out = {}
    for venue, fig in (contract.get('account') or {}).items():
        if not fig:
            continue
        rest, unsized = {'l': 0.0, 's': 0.0}, 0
        for b, t in terms.items():
            if t.get('venue') != venue:
                continue
            most = t.get('notional')
            if most is None:
                unsized += 1
                continue
            v = bots.get(b) or {}
            pos = abs(v.get('position') or 0.0)
            now = (pos if v.get('inverse') else
                   pos * v['mark'] if v.get('mark') is not None else 0.0)
            rest['s' if b.endswith('s') else 'l'] += max(0.0, most - now)
        eq, coll = fig.get('equity'), fig.get('collateral')
        row = {'now': fig['notional'] / eq if eq and eq > 0 else None,
               'notional': fig['notional'], 'equity': eq,
               'collateral': coll, 'unsized': unsized}
        for way, side in (('fall', 'l'), ('rise', 's')):
            n = fig['notional'] + rest[side]
            row[f'{way}_notional'] = n
            row[way] = n / coll if coll and coll > 0 else None
        out[venue] = row
    return out


def _big(v):
    return '—' if v is None else (f'{v / 1000:,.0f}k' if v >= 10_000
                                  else f'{v:,.0f}')


def leverage_lines(contract):
    """R19: the one wording every surface uses — {venue: (now, filled)}."""
    out = {}
    for venue, a in account_leverage(contract).items():
        now = ('account leverage —' if a['now'] is None else
               f"account leverage {a['now']:.2f}x ({_big(a['notional'])} in "
               f"positions on {_big(a['equity'])})")
        filled = ('if every order filled —' if a['fall'] is None else
                  f"if every order filled: {a['fall']:.2f}x on a fall "
                  f"({_big(a['fall_notional'])}), {a['rise']:.2f}x on a rise "
                  f"({_big(a['rise_notional'])}), on "
                  f"{_big(a['collateral'])} collateral"
                  + (f"; {a['unsized']} bots unsized" if a['unsized'] else ''))
        out[venue] = (now, filled)
    return out


def base_coin(symbol):
    """An inverse contract's own coin, from its name: BTCUSD -> BTC,
    ETHUSDH26 -> ETH. The part before the quote."""
    sym = str(symbol or '')
    for quote in ('USDT', 'USDC', 'USD'):
        i = sym.find(quote)
        if i > 0:
            return sym[:i]
    return sym or 'coin'


def settle_quote(venue, symbol):
    """The coin a linear book's money is in: Hyperliquid names its markets
    by the coin alone and settles all of them in USDC — 'BTC' read as a
    BTC-quoted market split HL's total in two (audit 2026-10-06)."""
    if venue == 'hyperliquid' or str(symbol).endswith('PERP'):
        return 'USDC'                     # Bybit's xxxPERP is its USDC perp
    return next((c for c in ('USDT', 'USDC', 'USD', 'EUR', 'BTC')
                 if str(symbol).endswith(c)), 'quote')


def money_units(venue, market_type, symbol):
    """U53: {quote, margin_coin} — the coin a bot's money figures are in
    (capital, notional, loss, P&L) and the coin the venue's margin on its
    position is in. Linear and spot: the settle quote for both. Inverse:
    dollars for the money ($1 contracts, A4), the base coin for margin."""
    if market_type == 'inverse':
        return {'quote': 'USD', 'margin_coin': base_coin(symbol)}
    q = settle_quote(venue, symbol)
    return {'quote': q, 'margin_coin': q}


def _market_for(key_of, venue_of, now_ms):
    """D67: the newest kept market reading beside each bot; a store that
    cannot be read is said once and the cards carry nothing."""
    from .market import for_bots, latest
    try:
        return for_bots(latest(), key_of, venue_of, now_ms / 1000.0)
    except (OSError, ValueError, KeyError) as e:
        print(f'[warn] market readings unread — {e}', file=sys.stderr)
        return {}


def card_total(b):
    """D63: a contract book's total, the one sum every renderer shows —
    realised after fees, plus the funding paid or received, plus the open
    remainder at the mark. Unread funding or mark counts as nothing here;
    the renderer says which part it could not read."""
    return (b['realized'] - b['fees'] + (b.get('funding') or 0.0)
            + (b.get('unreal_at_mark') or 0.0))


def funding_of(events, market_type, symbol, entry_side, start_ms, end_ms):
    """D63: what this bot's leg paid (-) or received (+) in funding over
    [start, end] — I2 makes (market, symbol, side) one bot, and a funding
    event names the side of the position it was charged on."""
    return sum(e['amount'] for e in events
               if e['market_type'] == market_type and e['symbol'] == symbol
               and e['side'] == entry_side
               and start_ms <= e['time_ms'] <= end_ms)


def _funding_pull(by_venue, start_of, now_ms):
    """D63: every perp market's funding from the earliest moment one of its
    books starts (`start_of[(market_type, symbol)]`) — one read per market
    on Bybit, one per address on Hyperliquid from its earliest. Spot has
    none. A venue that cannot be read is named, never summed as zero."""
    events, unread = [], set()
    for venue, rows in sorted(by_venue.items()):
        markets = sorted({(r['market_type'], r['symbol']) for r in rows
                          if r['market_type'] != 'spot'
                          and (r['market_type'], r['symbol']) in start_of})
        if not markets:
            continue
        try:
            if venue == 'hyperliquid':
                from .exchange.hyperliquid.client import InfoClient
                from .exchange.hyperliquid.truth import read_funding
                events += read_funding(InfoClient(), {s for _, s in markets},
                                       min(start_of[m] for m in markets),
                                       now_ms)
            else:
                from .exchange.bybit.client import Client
                from .exchange.bybit.truth import read_funding
                client = Client()
                for mt, sym in markets:
                    events += read_funding(client, mt, sym,
                                           start_of[(mt, sym)], now_ms)
        except (VenueError, OSError) as e:
            print(f'[warn] {venue}: funding unread — {e}', file=sys.stderr)
            unread.add(venue)
    return events, unread


def set_funding(book, events, unread, venue, market_type, symbol,
                entry_side, start_ms, end_ms):
    """D63: the book's funding over its own window; None when its venue's
    funding could not be read, so no figure claims a zero it never saw."""
    book['funding'] = (None if venue in unread else
                       funding_of(events, market_type, symbol, entry_side,
                                  start_ms, end_ms))
    return book


def public_book(book, mark=None, side=None, strategy=None, symbol=None):
    """The data contract, one book: every public field of the ledger, plus
    what a renderer needs and nothing it must compute. Private working
    state (underscore keys, sets) never leaves this module — the panel and
    the terminal table read THIS, so they can never disagree (D8/R7)."""
    out = {k: v for k, v in book.items()
           if not k.startswith('_') and not isinstance(v, set)}
    out['mark'] = mark
    out['side'] = side
    out['strategy'] = strategy
    out['truncated'] = window_truncated(book, side)
    out['per_trip'] = per_trip(book, out['truncated'])  # R12
    out['per_trip_net'] = per_trip_net(book, out['truncated'])
    if out['truncated']:
        out['same_rung'] = None    # a margin against a partial average is
                                   # not a verdict (R9 honours R7)
    unreal = None
    if mark is not None and abs(book['position']) > 1e-12 \
            and book['avg_cost'] > 0:
        unreal = unreal_pnl(book, mark)
    out['unreal_at_mark'] = unreal
    if book.get('inverse'):
        # A4: an inverse book keeps its money in the BASE coin. The contract
        # speaks quote (the panel printed -0.0003 BTC as "-0.00" dollars,
        # 2026-10-03): convert at the mark, and carry the coin figures too
        out['settle'] = {'coin': base_coin(symbol), 'realized': book['realized'],
                         'fees': book['fees'], 'unreal': unreal,
                         'funding': book.get('funding')}
        out['settle']['per_trip'] = out['per_trip']
        if mark is not None:
            for k in ('realized', 'fees', 'gap_realized'):
                out[k] = book[k] * mark
            if book.get('funding') is not None:
                out['funding'] = book['funding'] * mark
            for k in ('per_trip', 'per_trip_net'):
                if out[k] is not None:
                    out[k] = out[k] * mark
            out['unreal_at_mark'] = None if unreal is None else unreal * mark
        else:
            out['realized'] = out['fees'] = out['unreal_at_mark'] = None
            out['per_trip'] = out['funding'] = out['per_trip_net'] = None
    return out


def main(argv):
    hours = 24.0
    as_json = '--json' in argv
    if as_json:
        argv = [a for a in argv if a != '--json']
    if '--hours' in argv:
        i = argv.index('--hours')
        hours = float(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    if len(argv) != 1:
        print('usage: python3 -m gridgremlin.report <fleet.json> [--hours N] [--json]')
        return 2
    load_env()
    fleet = validate_fleet(json.loads(Path(argv[0]).read_text()))
    now_ms = int(time.time() * 1000)
    since_ms = now_ms - int(hours * 3600 * 1000)
    by_venue, key_of, inverse_ids = {}, {}, set()
    strat_of, entry_sides, closers, side_of = {}, {}, {}, {}
    range_of, grids, terms = {}, {}, {}
    for cfg in fleet['bots']:
        by_venue.setdefault(cfg['venue'], []).append(cfg)
        botid = make_botid(cfg['market_type'], cfg['symbol'], cfg['side'])
        key_of[botid] = (cfg['market_type'], cfg['symbol'])
        strat_of[botid] = cfg.get('strategy', 'grid')
        entry_sides[botid] = 'buy' if cfg['side'] == 'long' else 'sell'
        side_of[botid] = cfg['side']
        if cfg.get('lower') and cfg.get('upper'):
            range_of[botid] = {'lower': cfg['lower'], 'upper': cfg['upper'],
                               'rungs': cfg.get('rungs')}
            grids[botid] = cfg
        # U16: the terms a card states — what is invested, at what leverage,
        # and the most it puts in the market (the row's own numbers, C4)
        terms[botid] = {'capital': cfg.get('capital'),
                        'venue': cfg['venue'],                   # R19
                        'leverage': cfg.get('leverage') or 1.0,
                        'notional': cfg.get('ladder_total_notional')
                        or cfg.get('ladder_notional'),   # a DCA ladder's
                                                         # own total first
                        # U36: what kind of thing it is, for the card
                        'market_type': cfg['market_type'],
                        'strategy': cfg.get('strategy', 'grid'),
                        'spot_borrow': bool(cfg.get('spot_borrow')),
                        'multiplier': cfg.get('order_size_multiplier'),
                        'add_ons': cfg.get('max_averaging_orders'),
                        # U53: what the money is counted in — an inverse
                        # row's capital and notional are dollars ($1
                        # contracts) and its margin is the coin itself
                        **money_units(cfg['venue'], cfg['market_type'],
                                      cfg['symbol'])}
        if cfg.get('strategy') == 'martingale':          # U52: the ladder's sum
            from .ladder import ladder_summary
            terms[botid]['ladder'] = ladder_summary(cfg)
        exit_side = 'sell' if cfg['side'] == 'long' else 'buy'
        closers[(cfg['market_type'], cfg['symbol'], exit_side)] = botid
        if cfg['market_type'] == 'inverse':
            inverse_ids.add(botid)
            inverse_ids.add(('unowned', cfg['symbol']))
    botids = list(key_of)
    fills, marks = [], {}
    for venue, rows in sorted(by_venue.items()):
        try:
            got, m = (_hl_pull(rows, since_ms) if venue == 'hyperliquid'
                      else _bybit_pull(rows, since_ms, now_ms))
        except (VenueError, OSError) as e:
            print(f'[warn] {venue}: unreachable, skipped — {e}',
                  file=sys.stderr)
            continue
        fills += got
        marks.update(m)
    account = {}                       # R19: each exchange's own figures
    for venue in by_venue:
        try:
            if venue == 'hyperliquid':
                from .exchange.hyperliquid.client import InfoClient
                from .exchange.hyperliquid.truth import account_figures
                client = InfoClient()
                account[venue] = dict(account_figures(client),
                                      tier=client.env)          # D65
            else:
                from .exchange.bybit.client import Client
                from .exchange.bybit.truth import account_figures
                client = Client()
                account[venue] = dict(account_figures(client),
                                      tier=client.env)          # D65
        except (VenueError, OSError, KeyError, ValueError, TypeError) as e:
            print(f'[warn] {venue}: account figures unread — {e}',
                  file=sys.stderr)
            account[venue] = None
    rounders = {b for b, s in strat_of.items() if s == 'martingale'}
    books = ledger(fills, botids, inverse_ids, entry_sides, closers, grids,
                   rounders=rounders)
    # R14: a bot whose round is older than the window is counted from the
    # last time it was flat (a month at most) — the card's headline for the
    # busiest grid read -14k on a day the exchange showed +9.6k for the round
    cfg_of = {make_botid(c['market_type'], c['symbol'], c['side']): c
              for c in fleet['bots']}
    held = {}
    for venue, rows in by_venue.items():
        held.update(_venue_held_all(venue, rows))
    pulled = {}          # (venue, market, since) -> fills: one read serves
                         # every bot that widens to that horizon — HL's
                         # history read is per ADDRESS, so every bot's
                         # doubling was a fresh call, and the panel's
                         # readout every ten seconds lost the fleet 5% of
                         # its cycles to the rate limit (2026-10-05)
    for botid in botids:
        book = books.get(botid)
        size = held.get(botid)
        shown = abs(book['position']) if book is not None else 0.0
        # the tell is the exchange: a window whose book does not hold what
        # the venue holds opened mid-round — for a short as much as a long
        # (the sign test alone let every short's partial book through)
        partial = (size is not None
                   and abs(shown - size) > 1e-9 * max(1.0, size) + EPS)
        if not partial and (book is None
                            or not window_truncated(book, side_of.get(botid))):
            continue
        cfg = cfg_of[botid]
        venue = cfg['venue']

        def pull(since, cfg=cfg, venue=venue):
            key = (venue, None if venue == 'hyperliquid'
                   else (cfg['market_type'], cfg['symbol']), since)
            if key not in pulled:
                rows = (by_venue[venue] if venue == 'hyperliquid' else [cfg])
                got, _ = (_hl_pull(rows, since) if venue == 'hyperliquid'
                          else _bybit_pull(rows, since, now_ms))
                pulled[key] = got
            return pulled[key]
        try:
            own, how, start = count_from_flat(
                botid, hours, now_ms, pull, entry_sides[botid],
                closers, venue_size=size)
        except (VenueError, OSError) as e:
            print(f'[warn] {botid}: could not widen the window — {e}',
                  file=sys.stderr)
            continue
        wide = ledger(own, [botid], inverse_ids, entry_sides, closers, grids,
                      rounders=rounders).get(botid) or new_book()
        wide['counted_from'] = how
        wide['counted_since_ms'] = start
        books[botid] = wide
    venue_of = {(c['market_type'], c['symbol']): c['venue']
                for c in fleet['bots']}
    fresh = fills + [f for got in pulled.values() for f in got]
    since_first = kept_books(argv[0], fresh, venue_of, key_of, since_ms,
                             inverse_ids, entry_sides, closers, grids,
                             rounders, kept_held(fleet, held))
    # D63: funding over each book's own window, one pull from the earliest
    starts = {b: (books[b].get('counted_since_ms') or since_ms)
              for b in botids if b in books}
    sf_starts = ({b: bk['first_ms'] for b, bk in since_first[0].items()
                  if bk.get('whole') and bk.get('first_ms')}
                 if since_first is not None else {})
    start_of = {}
    for b, start in list(starts.items()) + list(sf_starts.items()):
        start_of[key_of[b]] = min(start, start_of.get(key_of[b], start))
    events, unread = _funding_pull(by_venue, start_of, now_ms)
    venue_of_bot = {b: venue_of[key_of[b]] for b in botids}
    for got, start_of in ((books, starts),
                          (since_first[0] if since_first else {}, sf_starts)):
        for b, start in start_of.items():
            set_funding(got[b], events, unread, venue_of_bot[b],
                        key_of[b][0], key_of[b][1], entry_sides[b],
                        start, now_ms)
    if as_json:
        contract = {
            'window_hours': hours,
            'generated_ms': now_ms,
            'bots': {b: (public_book(books[b], marks.get(key_of[b]),
                                     side_of.get(b), strat_of.get(b),
                                     key_of[b][1])
                         if b in books else None)   # quiet ≠ absent: every
                     for b in botids},              # configured bot appears
            'ranges': range_of,
            'terms': terms,
            'account': account,
            'watchdog': _watchdog_view(fleet),
            'fee_floors': {b: fee_floor_for(key_of[b][0]) for b in botids},
            'market': _market_for(key_of, venue_of, now_ms),        # D67
            'unowned': {k[1]: public_book(books[k])
                        for k in books if isinstance(k, tuple)
                        and k[0] == 'unowned'}}
        if since_first is not None:                  # R18: the kept ledger
            sf_books, behind = since_first
            contract['since_first'] = {
                b: (None if b not in sf_books else
                    {'fills': sf_books[b]['fills'], 'whole': False,
                     'first_ms': sf_books[b]['first_ms'],
                     'behind': behind.get(b)}
                    if not sf_books[b]['whole'] else
                    dict(public_book(sf_books[b], marks.get(key_of[b]),
                                     side_of.get(b), strat_of.get(b),
                                     key_of[b][1]),
                         behind=behind.get(b)))
                for b in botids}
        print(json.dumps(contract))
        return 0
    print(f'last {hours:g}h · grid profit = realized − fees (D8) · '
          f'total adds funding (D63) and mark-to-average on the open '
          f'remainder')
    print(f"{'bot':<18}{'fills':>6}{'realized':>12}{'fees':>10}"
          f"{'funding':>10}{'open@avg':>20}{'unreal':>12}{'total':>12}")
    for botid in botids:
        book = books.get(botid)
        if book is None:
            print(f'{botid:<18}{0:>6}{"—":>12}{"—":>10}{"—":>10}'
                  f'{"—":>20}{"—":>12}{"—":>12}')
            continue
        print(_row(botid, book, marks.get(key_of[botid]),
                   side=side_of.get(botid)))
    for key in sorted(k for k in books if isinstance(k, tuple)
                      and k[0] == 'unowned'):
        _, symbol = key
        mark = next((m for (_, sym), m in marks.items()
                     if sym == symbol and m is not None), None)
        print(_row(f'unowned {symbol}', books[key], mark))
    counted = [(k, b) for k, b in books.items()
               if isinstance(k, str) and b.get('counted_from') == 'flat']
    if counted:
        print('counted from the last time it was flat (R14): '
              + ', '.join(f"{k} {(now_ms - b['counted_since_ms']) / 3.6e6:.1f}h"
                          for k, b in counted))
    if any(window_truncated(b, side_of.get(k))
           for k, b in books.items() if isinstance(k, str)):
        print("* never flat in a month: that bot's realized and remainder "
              "are partial — the exchange's own position figure is the truth")
    # A4 in miniature: 'quote' is not one currency — totals group by the
    # symbol's actual quote coin, one row each (audit 2026-08-07 LOW)
    by_quote = {}
    for k, b in books.items():
        if isinstance(k, tuple) or b.get('inverse'):
            continue
        sym = key_of.get(k, (None, ''))[1]
        q = settle_quote(venue_of.get(key_of.get(k)), sym)
        by_quote.setdefault(q, []).append(b)
    for q, owned in sorted(by_quote.items()):
        realized = sum(b['realized'] for b in owned)
        fees = sum(b['fees'] for b in owned)
        funding = sum(b.get('funding') or 0.0 for b in owned)
        print(f"{f'TOTAL ({q})':<18}{sum(b['fills'] for b in owned):>6}"
              f'{_n(realized):>12}{_n(fees):>10}{_n(funding):>10}'
              f'{"":>20}{"":>12}{_n(realized - fees + funding):>12}')
    print()
    print(f"{'— activity —':<18}{'trips':>7}{'per-trip':>10}{'net':>9}"
          f"{'rounds':>8}{'avg/round':>11}{'SO fills':>10}{'max depth':>11}{'bought':>12}{'sold':>12}"
          '   per-trip = what each exit earned against its own rung (R12);'
          ' net = after both legs\' fees')
    for botid in botids:
        b = books.get(botid)
        if b is None or b['fills'] == 0:
            continue
        if strat_of.get(botid) == 'martingale':
            avg = (b['round_pnl_sum'] / b['rounds']) if b['rounds'] else None
            wash = (f"  <- {b['same_rung']} ZERO-SPREAD exit(s) (R9)"
                    if b['same_rung']
                    and not window_truncated(b, side_of.get(botid)) else '')
            print(f"{botid:<18}{'—':>7}{'—':>10}{'—':>9}{b['rounds']:>8}"
                  f"{_n(avg):>11}{b['so_fills']:>10}{b['max_depth']:>11}"
                  f"{_n(b['bought']):>12}{_n(b['sold']):>12}{wash}")
        else:
            cut = window_truncated(b, side_of.get(botid))
            per, net = per_trip(b, cut), per_trip_net(b, cut)
            if b.get('inverse'):                       # A4: coin -> quote
                mk = marks.get(key_of[botid])
                per = per * mk if per is not None and mk is not None else None
                net = net * mk if net is not None and mk is not None else None
            wash = (f"  <- {b['same_rung']} ZERO-SPREAD exit(s) (R9)"
                    if b['same_rung'] and not cut else '')
            print(f"{botid:<18}{b['trips']:>7}{_n(per):>10}{_n(net):>9}"
                  f"{'—':>8}{'—':>11}{'—':>10}{'—':>11}"
                  f"{_n(b['bought']):>12}{_n(b['sold']):>12}{wash}")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
