# Identity and the diff (SPEC I1-I3, E2's decision half). Pure.

from .config import ConfigError

PRICE_EPS = 1e-9
QTY_RTOL = 0.05


def make_botid(market_type, symbol, side):
    """I1: {market_type[:3]}{symbol}{side initial}, hyphens stripped (D20)."""
    return f'{market_type[:3]}{symbol}{side[0]}'.replace('-', '')


def row_botid(row):
    """A fleet file row's id: a portfolio row (D78) is pfo<name>; every
    other row is I1's make_botid."""
    if row.get('strategy') == 'portfolio':
        return f"pfo{row.get('name')}"
    return make_botid(row['market_type'], row['symbol'], row['side'])


def coin_in_botid(text):
    """U32: a bot's id pasted where a market was wanted — linFARTCOINUSDTl
    for FARTCOINUSDT. The coin inside it, or None when the text is not
    shaped like an id (I1: market_type[:3] + symbol + side initial)."""
    import re
    m = re.fullmatch(r'(lin|inv|spo)([A-Za-z0-9]{2,})([ls])',
                     (text or '').strip(), re.IGNORECASE)
    return m.group(2).upper() if m else None


def not_listed(symbol, venue_words):
    """U32: the not-listed refusal, with the hint when the text is a bot's
    name. `venue_words` is the venue's own sentence about its names."""
    coin = coin_in_botid(symbol)
    hint = (f" — {symbol} looks like a bot's name, not a market; the coin "
            f"inside it is {coin}, type that" if coin else '')
    up = (symbol or '').upper()
    if not hint and up.endswith('USDC') and len(up) > 4 and 'Bybit' in venue_words:
        # U40 (owner 2026-10-05 typed BTCUSDC): Bybit names its USDC
        # perpetual with PERP, not the coin it settles in
        hint = (f" — Bybit's USDC perpetual is named {up[:-4]}PERP, "
                'not with USDC on the end; type that')
    return f'{symbol}: {venue_words}{hint}'


def make_link(botid, rung, gen):
    return f'{botid}-{rung}-{gen}'


def rung_of(link_id, botid):
    """I1: ours iff prefixed and the rung parses; anything else is None."""
    prefix = botid + '-'
    if not (link_id or '').startswith(prefix):
        return None
    rest = link_id[len(prefix):]
    neg = rest.startswith('-')            # G17: a short's slid window sits
    body = rest[1:] if neg else rest      # below home — negative indices
    tail = body.split('-', 1)[0]
    try:
        value = int(tail)
    except ValueError:
        return None
    return -value if neg else value


def widest_rung(cfg):
    """I3: the rung index whose link PRINTS longest for this row. A lot's
    exit rests one rung beyond the rung it was bought at (G25), so the
    furthest link is one past the furthest window's far edge: `rungs` above
    home for a long, -1 below it for a short; with a slide, `max_rungs`
    further (a short's is negative: the sign is a character too;
    `direction: both` reaches both ways, D34). Whichever prints longest."""
    n = int(cfg.get('rungs', 99) or 99)
    s = cfg.get('slide')
    m = int(s['max_rungs']) if s else 0
    up, down = n + m, -1 - m
    if s and s.get('direction') == 'both':
        edges = [up, down]
    else:
        edges = [down if cfg.get('side') == 'short' else up]
    edges.append(n - 1)
    return max(edges, key=lambda r: len(str(r)))


def check_link_fits(botid, max_rung, venue_limit, gen_chars=10):
    """I3: refuse at build, never skip a row silently."""
    longest = len(make_link(botid, max_rung, '9' * gen_chars))
    if longest > venue_limit:
        raise ConfigError(f'{botid}: order link would be {longest} chars '
                          f'(venue limit {venue_limit}) — shorten the symbol '
                          'set or the rung count')


def bot_identity(cfg, adapter):
    """I2: the collision key — (market_type, symbol, opening positionIdx)."""
    entry_side = 'Buy' if cfg['side'] == 'long' else 'Sell'
    idx = adapter.position_idx(entry_side, False)
    return (cfg['market_type'], cfg['symbol'], 0 if idx is None else idx)


def check_fleet_unique(identities):
    seen = {}
    for botid, ident in identities:
        if ident in seen:
            raise ConfigError(f'{botid} and {seen[ident]} both own {ident} — '
                              'one bot per (market_type, symbol, positionIdx)')
        seen[ident] = botid
    return identities


def matches(desired, order, qty_rtol=QTY_RTOL):
    """Truncation-tolerant: a venue-shrunk exit is a match; oversized is not."""
    if order['side'] != desired['side']:
        return False
    if bool(order['reduce_only']) != bool(desired['reduce_only']):
        return False
    if abs(order['price'] - desired['price']) > PRICE_EPS:
        return False
    dq, oq = desired['qty'], order['qty']
    if desired['reduce_only']:
        # truncation-tolerant DOWN TO A POINT: the venue shrinks an exit to
        # the position, but a resting order far below the desire is not
        # truncation, it is a grown position with a stale cover — matching
        # it forever left the growth unexited (audit 2026-08-07 MED). Below
        # three quarters, replace (the diff makes it an amend).
        return dq * 0.75 <= oq <= dq * (1.0 + qty_rtol)
    return abs(dq - oq) <= qty_rtol * dq


def diff(desired, resting, botid, qty_rtol=QTY_RTOL):
    """E2's decisions: keep matches, cancel our deviations, create the missing.
    Foreign orders are invisible (I1). Duplicates on one rung keep one match.
    Returns (to_cancel, to_create)."""
    ours = {}
    for o in resting:
        rung = rung_of(o.get('link_id'), botid)
        if rung is not None:
            ours.setdefault(rung, []).append(o)
    to_cancel, to_create = [], []
    for d in desired:
        candidates = ours.pop(d['rung'], [])
        kept = False
        for o in candidates:
            if not kept and matches(d, o, qty_rtol):
                kept = True
            else:
                to_cancel.append(o)
        if not kept:
            to_create.append(d)
    for leftovers in ours.values():
        to_cancel.extend(leftovers)              # rungs the plan no longer wants
    return to_cancel, to_create


def pair_amends(to_cancel, to_create, botid):
    """Same (rung, side, reduce_only) at the SAME price -> a qty-only amend.
    A moved price is never amended (the trail-shaped 3.8 lesson).
    Returns (amends, cancels, creates); amends are (order, desired) pairs."""
    def key(rung, item):
        return (rung, item['side'], bool(item['reduce_only']))

    creates_by_key = {}
    for d in to_create:
        creates_by_key.setdefault(key(d['rung'], d), []).append(d)
    amends, cancels = [], []
    for o in to_cancel:
        rung = rung_of(o.get('link_id'), botid)
        bucket = creates_by_key.get(key(rung, o), [])
        paired = None
        for d in bucket:
            if abs(o['price'] - d['price']) <= PRICE_EPS:
                paired = d
                break
        if paired is None:
            cancels.append(o)
        else:
            bucket.remove(paired)
            amends.append((o, paired))
    creates = [d for bucket in creates_by_key.values() for d in bucket]
    return amends, cancels, creates
