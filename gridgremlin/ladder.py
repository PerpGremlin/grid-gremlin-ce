# The ladder: lattice, lot, split, exits, caps (SPEC G1-G13, G17-G23). Pure (E1).
# The why lives in docs/SPEC.md — code cites IDs and states only what the
# code itself cannot show.

import math
from decimal import Decimal

from .fees import FEE_FLOOR_PCT, SPOT_FEE_FLOOR_PCT, fee_floor_for  # noqa: E402,F401  (C10: G6's floors live in the fee table)
CROSS_GUARD_BPS = 5.0    # B3/B8: one definition; the placer imports THIS one
SPACING_GUARD_MULTIPLE = 3.0   # B8: spacing must clear the guard with margin
SEED_RUNG = -1_000_000   # S3/G23: the seed's link rung — no lattice has it, so a
                         # seeded lot sets no floor and suppresses no entry


def lattice_price(cfg, j):
    """G17: the price of ABSOLUTE lattice index j. The home window is
    j in [0, N); a slid window reads the same lattice at an offset, so one
    index has one price whichever window shows it. Endpoint j = N-1 is
    `upper` exactly (G1's endpoint rule, kept for every window)."""
    lower, upper, n = cfg['lower'], cfg['upper'], cfg['rungs']
    if j == n - 1:
        return upper
    if cfg['spacing_type'] == 'percent':
        ratio = (upper / lower) ** (1.0 / (n - 1))
        return lower * ratio ** j
    step = (upper - lower) / (n - 1)
    return lower + step * j


def lattice_index(cfg, price):
    """G17: the real-valued lattice index of a price (inverse of
    lattice_price), for the slide trigger — never for a rung."""
    lower, upper, n = cfg['lower'], cfg['upper'], cfg['rungs']
    if cfg['spacing_type'] == 'percent':
        ratio = (upper / lower) ** (1.0 / (n - 1))
        return math.log(price / lower) / math.log(ratio)
    return (price - lower) / ((upper - lower) / (n - 1))


def stop_level_for(cfg, offset=0):
    """X8: the mark_price stop of a window. An absolute `level` is itself;
    `rungs_beyond` sits that many lattice rungs past the window's near edge
    (below the bottom for a long, above the top for a short), so the stop
    follows every slide."""
    stop = cfg.get('stop') or {}
    if stop.get('level') is not None:
        return stop['level']
    r = stop.get('rungs_beyond')
    if r is None:
        return None
    if cfg['side'] == 'long':
        return lattice_price(cfg, offset - r)
    return lattice_price(cfg, offset + cfg['rungs'] - 1 + r)


def grid_rungs(cfg, adapter, offset=0):
    """G1/G3: N tick-rounded prices over the window at `offset` (home: 0),
    N-1 gaps. Index i of the result is absolute index offset + i."""
    n = cfg['rungs']
    return [adapter.round_price(lattice_price(cfg, offset + i)) for i in range(n)]


def slide_offset(cfg, offset, ref):
    """G18/G19: the ratchet, pure. Unchanged unless the ref sits
    `trigger_rungs` whole rungs beyond one of the window's edges. Then the
    window moves by whole rungs so the ref lands at `ref_position` of the
    range, clamped to `max_rungs` from home either way (G19).

    Which edges count: by default only the FAVOURABLE one (long: above the
    top; short: below the bottom) — a long window never slides down, a short
    one never up (D28). `direction: both` adds the adverse edge (D34): a long
    slides DOWN when the ref sits `trigger_rungs` below the bottom, a short UP
    above the top, by the same rule. A move never overshoots back past where
    it started: each step only goes the way the ref went."""
    s = cfg.get('slide')
    if not s:
        return offset
    n, k, m = cfg['rungs'], s['trigger_rungs'], s['max_rungs']
    land = int(round(s['ref_position'] * (n - 1)))
    x = lattice_index(cfg, ref)
    both = s.get('direction', 'favourable') == 'both'
    long = cfg['side'] == 'long'
    if (long or both) and x >= offset + (n - 1) + k:          # up
        return max(offset, min(int(math.floor(x)) - land, m))
    if (not long or both) and x <= offset - k:                # down
        return min(offset, max(int(math.ceil(x)) - land, -m))
    return offset


def slide_is_adverse(cfg, old, new):
    """D34: a move against the side — a long's window down, a short's up."""
    return (new < old) if cfg['side'] == 'long' else (new > old)


def rung_notionals(cfg):
    """Per-rung quote allocation: ladder_notional x w_i/sum(w)."""
    n, total = cfg['rungs'], cfg['ladder_notional']
    weights = cfg.get('rung_weights')
    if not weights:
        return [total / n] * n
    s = sum(weights)
    return [total * w / s for w in weights]


def lot(cfg, adapter, split_ref):
    """G4: the canonical lot — mean rung notional at the split ref."""
    notionals = rung_notionals(cfg)
    mean = sum(notionals) / len(notionals)
    return adapter.round_qty(adapter.qty_from_notional(mean, split_ref))


def trip_economics(rungs, maker_fee):
    """G16, pure: (net_fraction, gap_fraction, round_trip_fee). A grid's
    round trip earns one rung gap and pays the maker fee twice — if the
    gap cannot clear that, every completed trip loses money."""
    if len(rungs) < 2:
        return None, None, None
    gaps = [(b - a) / a for a, b in zip(rungs, rungs[1:]) if a > 0]
    gap = min(gaps) if gaps else None
    if gap is None:
        return None, None, None
    round_trip = 2.0 * (maker_fee or 0.0)
    return gap - round_trip, gap, round_trip


def exit_floor(side, split_ref, basis, market_type=None):
    """G6: the price an exit must clear; no basis -> the ref alone."""
    if basis is None or basis <= 0:
        return split_ref
    pct = fee_floor_for(market_type)
    if side == 'long':
        return max(split_ref, basis * (1.0 + pct))
    return min(split_ref, basis * (1.0 - pct))


def held_block(cfg, n_lots, basis):
    """G23 (D35): WHICH rungs a netted position's lots came from, derived
    from truth alone — the n contiguous lattice rungs whose mean is nearest
    the venue's average entry. Size + average pin the block exactly on any
    lattice; nothing per-lot is ever remembered (G12 stands). Returns the
    block's absolute index range (lo, hi), or None without a basis."""
    if n_lots <= 0 or basis is None or basis <= 0:
        return None
    centre = lattice_index(cfg, basis) - (n_lots - 1) / 2.0
    best = None
    for lo in (int(math.floor(centre)) + d for d in (-1, 0, 1, 2)):
        mean = sum(lattice_price(cfg, j) for j in range(lo, lo + n_lots)) / n_lots
        err = abs(mean - basis)
        if best is None or err < best[0]:
            best = (err, lo)
    lo = best[1]
    return lo, lo + n_lots - 1


def rung_floor(cfg, adapter, side, split_ref, held_rungs):
    """G23 (D35): exits pair per rung. A long sells each held lot one rung
    above the rung it was bought at, so the floor is the LOWEST held rung's
    price (a short's highest) — never the average. The ref still bounds it
    (G13: nothing marketable). Nothing held, or nothing known -> the ref."""
    if not held_rungs:
        return split_ref
    if side == 'long':
        return max(split_ref, adapter.round_price(lattice_price(cfg, min(held_rungs))))
    return min(split_ref, adapter.round_price(lattice_price(cfg, max(held_rungs))))


def paired_exits(cfg, adapter, split_ref, held_rungs, n_lots, window_exits,
                 bid=None, ask=None, resting=frozenset(), within=None):
    """G25 (D36): every held lot's exit rests where it was intended — one
    rung beyond the rung it was bought at (a long's above, a short's below)
    — wherever that rung now lies on the lattice, inside the slid window or
    not. Nothing but a fill or the bot's end removes it: W3 leaves a
    resting, still-planned order alone, and one cancelled from outside is
    re-placed when the mark comes back inside the window (the virtual
    fallback). A lot whose own rung cannot be placed now (not beyond the
    ref, or inside B4's guard band) and does not already rest there is
    displaced: it takes the nearest free placeable window exit, as G23 did,
    so a mark jittering across the rung keeps the exit it already has.
    Seed lots (off every lattice) are displaced too. `within` (lo, hi)
    confines the own rungs to the window: set when the rungs are the block
    the average pins, not the bot's fills — a guess never places an order
    outside the window, and S5's adopted basis beyond the range still gets
    no exits. Under `within`, an own exit already resting outside the window
    is kept anyway: the venue order is the proof once the fills have aged
    out of the history window.
    Each own exit carries the qty of the lot it closes — the lot sized at
    the rung it was bought at, not at today's ref — so a lot bought high is
    never short of an exit; a displaced lot carries `lot` at the ref.
    Returns [(rung, price, qty)] nearest-first, for G8's pour."""
    side = cfg['side']
    long = side == 'long'
    step = 1 if long else -1
    beyond = (lambda q: q > split_ref) if long else (lambda q: q < split_ref)
    out, taken = [], set()
    if within:
        # the venue is the proof when the fills are not (older than the
        # history window, or lagging): an exit already RESTING outside the
        # window was placed for a proven lot, so it keeps resting (E3)
        for j in sorted(resting, reverse=not long):
            if not within[0] <= j <= within[1]:
                taken.add(j)
                out.append((j, adapter.round_price(lattice_price(cfg, j)),
                            lot(cfg, adapter, lattice_price(cfg, j - step))))
    for h in sorted(held_rungs or (), reverse=not long):
        j = h + step
        price = adapter.round_price(lattice_price(cfg, j))
        if j in taken or (within and not within[0] <= j <= within[1]):
            continue
        if j in resting or (beyond(price) and placeable_exits(
                side, [(j, price)], bid, ask, resting)):
            taken.add(j)
            out.append((j, price, lot(cfg, adapter, lattice_price(cfg, h))))
    displaced = max(0, n_lots - len(out))
    at_ref = lot(cfg, adapter, split_ref)
    for j, price in placeable_exits(side, window_exits, bid, ask, resting):
        if displaced <= 0:
            break
        if j not in taken:
            taken.add(j)
            out.append((j, price, at_ref))
            displaced -= 1
    out.sort(key=lambda ip: ip[1], reverse=not long)
    return out


def split(side, rungs, split_ref, basis=None, market_type=None, offset=0,
          floor=None):
    """G5: entries strictly one side of the ref, exits strictly beyond the
    floor, nearest-first. Indices are ABSOLUTE lattice indices (G17):
    offset + position in `rungs`; at home, index 0 = lowest rung. The floor
    is G6's (basis mode) unless the caller derived G23's."""
    if floor is None:
        floor = exit_floor(side, split_ref, basis, market_type)
    indexed = [(offset + i, p) for i, p in enumerate(rungs)]
    if side == 'long':
        entries = [(i, p) for i, p in indexed if p < split_ref]
        exits = [(i, p) for i, p in indexed if p > floor]
        entries.sort(key=lambda ip: -ip[1])
        exits.sort(key=lambda ip: ip[1])
    else:
        entries = [(i, p) for i, p in indexed if p > split_ref]
        exits = [(i, p) for i, p in indexed if p < floor]
        entries.sort(key=lambda ip: ip[1])
        exits.sort(key=lambda ip: -ip[1])
    return {'entries': entries, 'exits': exits}


def guard_band(bid, ask):
    """B3: max(spread, guard-bps of mid). Defined once."""
    return max(ask - bid, (bid + ask) / 2.0 * CROSS_GUARD_BPS / 1e4)


def min_gap(rungs):
    """B8: the true tightest gap (the mean lies on geometric grids)."""
    return min(b - a for a, b in zip(rungs, rungs[1:]))


def spacing_clears_guard(rungs, bid, ask):
    """B8: (ok, gap, guard) — gap measured at the true minimum."""
    gap, guard = min_gap(rungs), guard_band(bid, ask)
    return gap >= SPACING_GUARD_MULTIPLE * guard, gap, guard


# --- the plan level: caps, the exit ladder, the entry guard (G7-G13) ---------

UNBOUNDED = 'unbounded'


def sellable_base(cfg, adapter, held_base):
    """G9: held minus the floor — never the same variable as held."""
    return adapter.round_qty(max(0.0, abs(held_base) - cfg['min_position_base']))


def position_cap(cfg, adapter, rungs):
    """G10: 'unbounded' -> None; absent -> the full-ladder sum."""
    cap = cfg.get('max_position_base')
    if cap == UNBOUNDED:
        return None
    if cap is not None:
        return float(cap)
    notionals = rung_notionals(cfg)
    return sum(adapter.qty_from_notional(nt, p) for nt, p in zip(notionals, rungs))


def lots_free(cap, held_base, lot_qty):
    """G10: whole lots of headroom under the cap, measured off HELD."""
    if cap is None or lot_qty <= 0:
        return None                                # unbounded
    return max(0, int((cap - abs(held_base)) / lot_qty + 1e-9))


def lots_held(sellable, lot_qty):
    """G7: the suppression count, measured off SELLABLE."""
    if lot_qty <= 0:
        return 0
    # ceil, not round: at exactly half a lot held, round() suppressed
    # nothing and the nearest entry re-armed with half its lot unexited
    # (audit 2026-08-07 LOW). Suppress while ANY of the lot is held.
    import math
    return math.ceil(sellable / lot_qty - 1e-9)


def exit_ladder(exits, sellable, lot_qty, adapter):
    """G8: one lot per rung nearest-first; the last rung absorbs a 0.5-1.5
    lot remainder; sub-minimum shares walk outward. Integer qty-steps: float
    subtraction plus flooring loses a step per iteration."""
    step = adapter.qty_step
    if sellable <= 0 or not exits or lot_qty <= 0 or step <= 0:
        return []
    total = int(round(sellable / step))
    lot_steps = max(1, int(round(lot_qty / step)))
    if total <= 0:
        return []

    def qty(steps):
        return float(Decimal(str(step)) * steps)

    kept, remaining = [], total
    for n, (i, price) in enumerate(exits):
        if remaining <= 0:
            break
        dump = remaining * 2 <= lot_steps * 3 or n == len(exits) - 1
        share = remaining if dump else lot_steps
        if adapter.meets_minimum(qty(share), price):
            kept.append([i, price, share])
        elif kept:
            kept[-1][2] += share
        else:
            continue
        remaining -= share
        if dump:
            break
    if remaining > 0 and kept:
        kept[-1][2] += remaining
    return [(i, price, qty(s)) for i, price, s in kept]


def exit_ladder_sized(exits, sellable, adapter):
    """G8 over G25's exits: each rung takes the lot it closes, nearest-first;
    a remainder of up to half that lot folds onto it, the last rung absorbs
    whatever is left (G8 covers the whole sellable), sub-minimum shares fold
    back. Integer qty-steps, as exit_ladder."""
    step = adapter.qty_step
    if sellable <= 0 or not exits or step <= 0:
        return []
    remaining = int(round(sellable / step))

    def qty(steps):
        return float(Decimal(str(step)) * steps)

    kept = []
    for n, (i, price, lot_q) in enumerate(exits):
        if remaining <= 0:
            break
        want = max(1, int(round(lot_q / step)))
        dump = remaining * 2 <= want * 3 or n == len(exits) - 1
        share = remaining if dump else want
        if adapter.meets_minimum(qty(share), price):
            kept.append([i, price, share])
        elif kept:
            kept[-1][2] += share
        else:
            continue
        remaining -= share
        if dump:
            break
    if remaining > 0 and kept:
        kept[-1][2] += remaining
    return [(i, price, qty(s)) for i, price, s in kept]


def placeable_exits(side, exits, bid, ask, resting_rungs):
    """B4: drop exit rungs inside the guard band of the opposite quote so the
    pour walks outward — unless that rung's exit already rests (keyed by side,
    never reduce_only). No book, no filter."""
    if bid is None or ask is None:
        return exits
    guard = guard_band(bid, ask)
    if side == 'long':
        return [(i, p) for i, p in exits
                if i in resting_rungs or p > bid + guard]
    return [(i, p) for i, p in exits
            if i in resting_rungs or p < ask - guard]


def plan_grid(cfg, adapter, split_ref, held_base=0.0, basis=None,
              bid=None, ask=None, resting_exit_rungs=frozenset(), offset=0,
              held_rungs=None):
    """G12: the netted plan, pure. G7 suppression, G8 exits, G10 cap, G13
    non-marketable by construction, B4 book-aware exits. Returns {rung, side,
    price, qty, reduce_only} dicts; `rung` is the absolute lattice index
    (G17) so a slid window's overlap keeps its identity.

    G23 (D35): `held_rungs` is WHICH rungs the held lots came from (one
    absolute index per lot), derived by the caller from the venue's fills;
    None with a basis falls back to the block the average pins (held_block).
    In `exit_floor: rung` mode (the default) suppression and pairing are by
    identity — an entry rung re-arms iff its lot is gone (G7 exactly), and
    each lot exits one rung above its own. `exit_floor: basis` is the old
    engine: G6's average floor and the count proxy (the nearest n rungs)."""
    rungs = grid_rungs(cfg, adapter, offset)
    lot_qty = lot(cfg, adapter, split_ref)
    sellable = sellable_base(cfg, adapter, held_base)
    suppressed = lots_held(sellable, lot_qty)
    floor, held_set = None, None
    from_fills = held_rungs is not None
    if cfg.get('exit_floor', 'rung') == 'rung':
        if held_rungs is None:
            # the fit: the block the average pins. It suppresses entries
            # only when it lies WHOLLY on the entry side of the ref — lots
            # bought below and carried up. A block on or across the ref
            # (a seed, a fresh market fill, a lagging fill list) came from
            # no entry rung the ref has not passed: nothing to suppress.
            block = held_block(cfg, suppressed, basis)
            if block:
                held_rungs = list(range(block[0], block[1] + 1))
                edge = lattice_price(cfg, block[1] if cfg['side'] == 'long'
                                     else block[0])
                across = (edge >= split_ref if cfg['side'] == 'long'
                          else edge <= split_ref)
                held_set = set() if across else set(held_rungs)
        else:
            held_set = set(held_rungs)
        floor = rung_floor(cfg, adapter, cfg['side'], split_ref, held_rungs)
    parts = split(cfg['side'], rungs, split_ref, basis,
                  cfg.get('market_type'), offset, floor=floor)
    if floor is not None:
        # G25 (D36): each lot's exit stays at its own rung, window or not
        parts['exits'] = paired_exits(cfg, adapter, split_ref, held_rungs,
                                      suppressed, parts['exits'], bid, ask,
                                      resting_exit_rungs,
                                      within=(None if from_fills else
                                              (offset, offset + len(rungs) - 1)))
    sized = None
    if floor is not None:
        sized = parts['exits']              # G25: already placeable, sized
    else:
        parts['exits'] = placeable_exits(cfg['side'], parts['exits'], bid,
                                         ask, resting_exit_rungs)
    notionals = rung_notionals(cfg)

    entry_side, exit_side = ('Buy', 'Sell') if cfg['side'] == 'long' else ('Sell', 'Buy')
    exits_ro = cfg['market_type'] != 'spot'
    orders = []

    ladder = (exit_ladder_sized(sized, sellable, adapter) if sized is not None
              else exit_ladder(parts['exits'], sellable, lot_qty, adapter))
    for i, price, qty in ladder:
        orders.append({'rung': i, 'side': exit_side, 'price': price, 'qty': qty,
                       'reduce_only': exits_ro})

    free = lots_free(position_cap(cfg, adapter, rungs), held_base, lot_qty)
    if held_set is not None:                     # G7 by identity (G23)
        armed = [(i, p) for i, p in parts['entries'] if i not in held_set]
    else:                                        # G7 by count (the proxy)
        armed = parts['entries'][suppressed:]
    for i, price in armed:
        if free is not None and free <= 0:
            break
        qty = adapter.round_qty(adapter.qty_from_notional(notionals[i - offset],
                                                          price))
        if qty <= 0 or not adapter.meets_minimum(qty, price):
            continue
        orders.append({'rung': i, 'side': entry_side, 'price': price, 'qty': qty,
                       'reduce_only': False})
        if free is not None:
            free -= 1
    return orders


# --- the martingale: the same maths, different data (M1, M2, M8) -------------

def martingale_schedule(cfg):
    """M2: [(notional, cumulative deviation)] — index 0 is the base order."""
    k = cfg['order_size_multiplier']
    s = cfg['deviation_step_multiplier']
    d = cfg['deviation_pct']
    out = [(cfg['base_order_size'], 0.0)]
    cumdev = 0.0
    for i in range(cfg['max_averaging_orders']):
        cumdev += d * s ** i
        out.append((cfg['safety_order_size'] * k ** i, cumdev))
    return out


def ladder_summary(cfg):
    """U52 (the ledger's DCA summary box): what the ladder adds up to,
    step by step, as fractions of the base price — so it is true before a
    round opens and whatever the price. Row i: where the step fills
    (`fill_pct`, signed: a long's steps fill below), its `notional`, the
    quote `committed` once it has filled, the average entry then
    (`avg_pct`, signed), and how far the price must move from that fill
    for the whole position to reach take-profit (`to_tp_pct`). Row 0 is
    the base order. The take-profit is the single target, else the first
    tranche's."""
    sign = -1.0 if cfg['side'] == 'long' else 1.0
    tp = cfg.get('take_profit_avg_pct')
    if tp is None:
        tp = (cfg.get('take_profit_tranches') or [{}])[0].get('at_avg_pct')
    rows, committed, coins = [], 0.0, 0.0
    for i, (notional, cumdev) in enumerate(martingale_schedule(cfg)):
        price = 1.0 + sign * cumdev
        committed += notional
        coins += notional / price
        avg = committed / coins
        target = avg * (1.0 - sign * tp) if tp is not None else None
        rows.append({'step': i, 'fill_pct': price - 1.0, 'notional': notional,
                     'committed': committed, 'avg_pct': avg - 1.0,
                     'to_tp_pct': None if target is None else target / price - 1.0})
    return rows


def anchor_from_rung(cfg, price, rung):
    """M15: invert the deviation schedule — a resting safety order at
    rung n was priced anchor x (1 +/- cumdev_n), so the anchor is
    recoverable from the venue instead of remembered."""
    sched = martingale_schedule(cfg)
    if rung is None or rung < 1 or rung >= len(sched):
        return None
    _, cumdev = sched[rung]
    sign = -1.0 if cfg['side'] == 'long' else 1.0
    factor = 1.0 + sign * cumdev
    return price / factor if factor else None


def plan_martingale(cfg, adapter, base_price, split_ref, held_base=0.0,
                    scale=1.0, filled_rungs=frozenset()):
    """M1: safety orders from the schedule — cumulative-prefix suppression,
    entry side only (G13), no exits (the round TP is slice 12). The base order
    itself is lifecycle, not a resting rung. `scale` is M12's reinvest factor:
    every size in the series, same multiplier, invariants preserved by
    proportionality. M24: a rung that FILLED this round stays suppressed
    whatever is held — a tranche exit shrinks the holding, not the ladder."""
    sign = -1.0 if cfg['side'] == 'long' else 1.0
    entry_side = 'Buy' if cfg['side'] == 'long' else 'Sell'
    orders, cum = [], 0.0
    for n, (notional, cumdev) in enumerate(martingale_schedule(cfg)):
        price = adapter.round_price(base_price * (1.0 + sign * cumdev))
        qty = adapter.round_qty(adapter.qty_from_notional(notional * scale,
                                                          price))
        cum += qty
        if n == 0:
            continue
        if held_base >= cum - 1e-12 or n in filled_rungs:
            continue
        if (cfg['side'] == 'long') == (price >= split_ref):
            continue
        if qty <= 0 or not adapter.meets_minimum(qty, price):
            continue
        orders.append({'rung': n, 'side': entry_side, 'price': price,
                       'qty': qty, 'reduce_only': False})
    return orders
