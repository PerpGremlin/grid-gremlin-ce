# Specs for SPEC R15/R15b/U113/F41 (2026-10-31): a grid exit consumes the
# lots it closes. The pairing (report.ledger, the price each exit is judged
# against) and the drift check's walk (pnl_drift.open_lots, written apart)
# use one disposal rule — the engine's own netting (G23): the lot one rung
# inside the exit first (G25), then the newest open lot of any rung, seed
# lots included. Before it, `entry_px` and the seed's price were lookups no
# exit ever consumed: a duplicate exit, a same-rung re-buy and a partial
# entry fill were credited as full-gap trips against lots already gone.
# Every guard has a sabotage spec that puts the lookup back. Magnitudes in
# the replay fixtures are made up; only the shapes are the live ones.

import random

from gridgremlin import pnl_drift as pd
from gridgremlin import report
from gridgremlin.config import validate_config
from gridgremlin.ladder import SEED_RUNG
from gridgremlin.report import ledger

B = 'linXUSDTl'
S = 'linXUSDTs'
CFG = validate_config({'market_type': 'linear', 'symbol': 'XUSDT', 'side': 'long',
                       'capital': 1000, 'leverage': 10, 'lower': 100.0, 'upper': 200.0,
                       'rungs': 21, 'spacing_type': 'fixed'})              # rung j at 100 + 5j


def f(t, side, price, qty, rung, fee=0.0, bot=B, link=None):
    return {'time_ms': t, 'side': side, 'price': price, 'qty': qty, 'fee': fee,
            'link_id': link or f'{bot}-{rung}-{t}', 'symbol': 'XUSDT', 'exec_id': f'e{t}'}


def trips(fills, bot=B, entry='buy', cfg=CFG, inverse=False):
    """(book, [own per fill]) — the pairing as the pane reads it (U113)."""
    got = {}
    book = ledger(fills, [bot], {bot} if inverse else (), {bot: entry}, grids={bot: cfg},
                  trips=got)[bot]
    return book, [o for o, _ in got[bot]]


def _lookup(held, qty, inside=None):
    """The sabotage: the old R15/R15b — a price looked up, never consumed:
    the latest buy at the inside rung, else the seed's, for the whole exit
    (and, with `forget` a no-op, never let go at a flat)."""
    at = [lot for lot in held if inside is not None and lot[0] == inside] or \
         [lot for lot in held if lot[0] == SEED_RUNG]
    return [(at[-1][1], qty, at[-1][3])] if at else []


def _sabotaged(check):
    real = report.take_lots, report.forget
    report.take_lots, report.forget = _lookup, lambda held: None
    try:
        check()
    except AssertionError:
        return True
    finally:
        report.take_lots, report.forget = real
    return False


# --- the pairing ----------------------------------------------------------------

def _duplicate_exit():
    # a seed, a lot at rung 12, a lot at 11; the exit at 12 closes rung 11's
    # lot; a duplicate of it consumes what is really held next — the rung-12
    # lot (its own rung) and half a seed lot: (0.5 x 160 + 0.5 x 148) = 154
    fills = [f(1, 'buy', 148.0, 2.0, SEED_RUNG, link=f'{B}-{SEED_RUNG}-s'),
             f(2, 'buy', 160.0, 0.5, 12), f(3, 'buy', 155.0, 1.0, 11),
             f(4, 'sell', 160.0, 1.0, 12), f(5, 'sell', 160.0, 1.0, 12)]
    book, own = trips(fills)
    assert own[3] == 155.0 and abs(own[4] - 154.0) < 1e-9, own
    assert abs(book['gap_realized'] - (5.0 + 6.0)) < 1e-9


def spec_R15_a_duplicate_exit_is_priced_against_the_lot_it_really_consumed():
    _duplicate_exit()


def spec_R15_sabotage_a_looked_up_price_credits_the_duplicate_a_full_gap():
    assert _sabotaged(_duplicate_exit)


def _same_rung_churn():
    # bought at rung 8 twice, sold at rung 8: no rung-7 lot is held, so the
    # exit takes the newest rung-8 lot — a trip of 0, a same-rung exit (R9)
    fills = [f(1, 'buy', 140.0, 1.0, 8), f(2, 'buy', 140.0, 1.0, 8), f(3, 'sell', 140.0, 1.0, 8)]
    book, own = trips(fills)
    assert own[2] == 140.0 and abs(book['gap_realized']) < 1e-12 and book['same_rung'] == 1, book


def spec_R15_same_rung_churn_is_a_trip_of_zero_counted_same_rung():
    _same_rung_churn()


def spec_R15_sabotage_same_rung_churn_reads_a_full_gap_on_the_lattice():
    assert _sabotaged(_same_rung_churn)


def _seed_at_most_its_quantity():
    # a seed of 1 at 150; two exits at rung 12: the first takes the seed lot
    # (+10); the second finds nothing held — the lattice's rung 11 (155), +5
    fills = [f(1, 'buy', 150.0, 1.0, SEED_RUNG, link=f'{B}-{SEED_RUNG}-s'),
             f(2, 'sell', 160.0, 1.0, 12), f(3, 'sell', 160.0, 1.0, 12)]
    book, own = trips(fills)
    assert own[1:] == [150.0, 155.0] and abs(book['gap_realized'] - 15.0) < 1e-9, own


def spec_R15b_the_seed_prices_at_most_the_seeds_quantity():
    _seed_at_most_its_quantity()


def spec_R15b_sabotage_an_unlimited_seed_price_is_caught():
    assert _sabotaged(_seed_at_most_its_quantity)


def _lattice_only_uncovered():
    # R15's mid-round fixture: the entry not in the window, the lattice
    one, own = trips([f(2, 'sell', 160.0, 1.0, 12)])
    assert own == [155.0] and abs(one['gap_realized'] - 5.0) < 1e-9
    # half the exit covered by a seen lot at 152, half by the lattice's 155
    book, own = trips([f(1, 'buy', 152.0, 0.5, 11), f(2, 'sell', 160.0, 1.0, 12)])
    assert abs(own[1] - 153.5) < 1e-9 and abs(book['gap_realized'] - 6.5) < 1e-9, own


def spec_R15_the_lattice_prices_only_quantity_no_seen_lot_covers():
    _lattice_only_uncovered()


def spec_R15_sabotage_a_seen_lot_pricing_the_whole_exit_is_caught():
    assert _sabotaged(_lattice_only_uncovered)


def _flat_forgets():
    # rung 5 bought off its lattice (124) and sold flat at rung 6; the next
    # buy is at rung 7 (135): the next exit at rung 6 consumes THAT lot
    fills = [f(1, 'buy', 124.0, 1.0, 5), f(2, 'sell', 130.0, 1.0, 6),
             f(3, 'buy', 135.0, 1.0, 7), f(4, 'sell', 130.0, 1.0, 6)]
    book, own = trips(fills)
    assert own[3] == 135.0 and abs(book['gap_realized'] - (6.0 - 5.0)) < 1e-9, own
    # nothing held after the flat: the lattice (125), never the old buy
    _, own = trips(fills[:2] + [f(3, 'sell', 130.0, 1.0, 6)])
    assert own[2] == 125.0, own


def spec_R15_entries_before_a_flat_never_price_an_exit_after_it():
    _flat_forgets()


def spec_R15_sabotage_a_lot_remembered_past_the_flat_is_caught():
    assert _sabotaged(_flat_forgets)


def _partial_entry_passes_on():
    # Hyperliquid filled the rung-8 buy in two parts (one link): each is a
    # lot; an exit takes the newest part first and the remainder from the next
    link = f'{B}-8-a'
    fills = [f(1, 'buy', 139.0, 0.4, 8, link=link), f(2, 'buy', 141.0, 0.6, 8, link=link),
             f(3, 'sell', 145.0, 0.3, 9), f(4, 'sell', 145.0, 0.7, 9)]
    book, own = trips(fills)
    assert own[2] == 141.0 and abs(own[3] - (0.3 * 141.0 + 0.4 * 139.0) / 0.7) < 1e-9, own
    assert abs(book['gap_realized'] - (145.0 - (0.4 * 139.0 + 0.6 * 141.0))) < 1e-9


def spec_R15_a_partial_entry_fill_passes_the_remainder_to_the_next_lot():
    _partial_entry_passes_on()


def spec_R15_sabotage_the_last_partial_pricing_the_whole_exit_is_caught():
    assert _sabotaged(_partial_entry_passes_on)


def spec_R15_a_short_and_an_inverse_book_consume_their_mirror():
    """A short's exit closes the lot one rung ABOVE it (its mirror); an
    inverse book's own entry is the harmonic price of the coins it took."""
    fills = [f(1, 'sell', 160.0, 1.0, 12, bot=S), f(2, 'sell', 155.0, 1.0, 11, bot=S),
             f(3, 'buy', 155.0, 1.0, 11, bot=S), f(4, 'buy', 150.0, 1.0, 10, bot=S)]
    book, own = trips(fills, bot=S, entry='sell')
    assert own[2:] == [160.0, 155.0] and abs(book['gap_realized'] - 10.0) < 1e-9, own
    inv = [f(1, 'buy', 100.0, 100.0, 4), f(2, 'buy', 125.0, 100.0, 4), f(3, 'sell', 130.0, 200.0, 6)]
    book, own = trips(inv, inverse=True)
    assert abs(own[2] - 200.0 / (1.0 + 0.8)) < 1e-9
    assert abs(book['gap_realized'] - (200.0 / own[2] - 200.0 / 130.0)) < 1e-12


# --- replays shaped on the live sequences (magnitudes made up) --------------------

def spec_U113_replay_eth_a_duplicate_exit_94s_later():
    """The demo ETH long: a buy at rung 11, the sell at 12 that closes it,
    and a duplicate sell at 12 94 s later that really consumed the rung-12
    lot and part of the seed. The duplicate was credited a full gap."""
    s = 1_000
    fills = [f(0, 'buy', 151.0, 3.0, SEED_RUNG, fee=0.03, link=f'{B}-{SEED_RUNG}-s'),
             f(10 * s, 'buy', 160.0, 0.4, 12, fee=0.004), f(20 * s, 'buy', 155.0, 0.4, 11, fee=0.004),
             f(30 * s, 'sell', 160.0, 0.4, 12, fee=0.004), f(124 * s, 'sell', 160.0, 0.5, 12, fee=0.005)]
    book, own = trips(fills)
    assert own[3] == 155.0 and abs(own[4] - (0.4 * 160.0 + 0.1 * 151.0) / 0.5) < 1e-9, own
    assert abs(book['gap_realized'] - (2.0 + 0.9)) < 1e-9 and book['same_rung'] == 0
    walk = pd.open_lots(fills, B, 'buy')
    assert walk['no_lot'] == 0 and abs(sum(q for _, q in walk['lots']) - book['position']) < 1e-12


def spec_U113_replay_sol_a_rebuy_three_seconds_later_then_a_same_rung_sell():
    """The demo SOL long: a rung-7 fill, a re-buy at rung 7 three seconds
    later, then a sell at rung 7 — a trip of 0, counted same-rung."""
    fills = [f(0, 'buy', 135.2, 2.0, 7, fee=0.01), f(3_000, 'buy', 135.1, 2.0, 7, fee=0.01),
             f(60_000, 'sell', 135.1, 2.0, 7, fee=0.01)]
    book, own = trips(fills)
    assert own[2] == 135.1 and abs(book['gap_realized']) < 1e-12 and book['same_rung'] == 1
    walk = pd.open_lots(fills, B, 'buy')
    assert walk['same_rung'] == 1 and walk['lots'] == [(135.2, 2.0)] and walk['no_lot'] == 0


def spec_U113_replay_hl_eth_repeated_buy_and_sell_at_one_rung():
    """The Hyperliquid ETH long: buy and sell at rung 8 over and over —
    each sell takes the buy before it, never the rung below's lattice."""
    fills = []
    for i in range(6):
        fills += [f(2 * i, 'buy', 140.0 + 0.01 * i, 0.25, 8), f(2 * i + 1, 'sell', 140.0 + 0.01 * i, 0.25, 8)]
    book, own = trips(fills)
    assert abs(book['gap_realized']) < 1e-12 and book['same_rung'] == 6, book
    assert own[1::2] == [140.0 + 0.01 * i for i in range(6)]
    walk = pd.open_lots(fills, B, 'buy')
    assert walk['lots'] == [] and walk['same_rung'] == 6 and walk['no_lot'] == 0


# --- the walk (F41) ---------------------------------------------------------------

def _old_walk(counted, botid, entry_side, inverse=False):
    """The sabotage: F41's first walk — the rung pool, then the seed's,
    and 'no lot' whenever both were empty, whatever else was held."""
    from gridgremlin.apply import rung_of
    step = -1 if entry_side == 'buy' else 1
    at, seed, unmatched = {}, [], 0
    for x in counted:
        rung = rung_of(x.get('link_id') or '', botid)
        if x['side'] == entry_side:
            (seed if rung == SEED_RUNG else at.setdefault(rung, [])).append([x['price'], x['qty']])
            continue
        left = x['qty']
        pools = ([at.get(rung + step, [])] if rung is not None and rung != SEED_RUNG else []) + [seed]
        for pool in pools:
            while left > 1e-12 and pool:
                take = min(pool[-1][1], left)
                pool[-1][1] -= take
                left -= take
                if pool[-1][1] <= 1e-12:
                    pool.pop()
        unmatched += left > 1e-9
    lots = [(p, q) for pool in list(at.values()) + [seed] for p, q in pool if q > 1e-12]
    return {'lots': lots, 'no_lot': unmatched, 'same_rung': 0, 'exits': []}


def _walk_says_no_lot_only_when_empty(walk=None):
    walk = walk or pd.open_lots
    churn = [f(1, 'buy', 140.0, 1.0, 8), f(2, 'buy', 140.0, 1.0, 8), f(3, 'sell', 140.0, 1.0, 8)]
    got = walk(churn, B, 'buy')
    assert got['no_lot'] == 0 and sum(q for _, q in got['lots']) == 1.0, got
    empty = [f(1, 'buy', 140.0, 1.0, 8), f(2, 'sell', 145.0, 1.0, 9), f(3, 'sell', 145.0, 1.0, 9)]
    assert walk(empty, B, 'buy')['no_lot'] == 1


def spec_F41_the_walk_says_no_lot_only_on_an_empty_inventory():
    _walk_says_no_lot_only_when_empty()


def spec_F41_sabotage_the_rung_and_seed_only_walk_is_caught():
    try:
        _walk_says_no_lot_only_when_empty(_old_walk)
    except AssertionError:
        return
    raise AssertionError('the old walk passed')


# --- the property: pairing and walk agree, the identity holds ----------------------

def _generate(rng, entry):
    """A whole record of one grid: seeds from flat, entries filled whole or
    in parts, exits at their rung, duplicates, same-rung churn; never an
    exit past what is held (the record is whole)."""
    exit_side = 'sell' if entry == 'buy' else 'buy'
    step = 1 if entry == 'buy' else -1          # an exit sits one rung outside its lot
    bot = B if entry == 'buy' else S
    out, held, t, last = [], 0.0, 0, None
    for _ in range(rng.randint(5, 60)):
        t += rng.randint(1, 5)
        if held < 1e-9 and rng.random() < 0.3:
            link = f'{bot}-{SEED_RUNG}-g{t}'           # one seed order, filled in parts
            for _ in range(rng.randint(1, 2)):
                q = rng.choice((0.5, 1.0, 1.5))
                out.append(f(t, entry, round(rng.uniform(140, 160), 2), q, SEED_RUNG,
                             fee=q * 0.01, bot=bot, link=link))
                held += q
                t += 1
            continue
        roll = rng.random()
        if roll < 0.5 or held < 1e-9:
            r = rng.randint(4, 16)
            link = f'{bot}-{r}-g{t}'
            for _ in range(rng.randint(1, 2)):
                q = rng.choice((0.25, 0.5, 1.0))
                out.append(f(t, entry, 100.0 + 5 * r + rng.choice((0.0, 0.3, -0.4)), q, r,
                             fee=q * 0.02, bot=bot, link=link))
                held += q
                t += 1
        elif roll < 0.6 and last is not None:
            q = min(last['qty'], held)
            out.append(dict(last, time_ms=t, qty=q, exec_id=f'e{t}', link_id=f"{last['link_id']}d{t}"))
            held -= q
        else:
            r = rng.randint(4, 16) + rng.choice((step, 0))
            q = min(rng.choice((0.25, 0.5, 1.0)), held)
            last = f(t, exit_side, 100.0 + 5 * r, q, r, fee=q * 0.02, bot=bot)
            out.append(last)
            held -= q
    return bot, out


def _property(seed=20261031, n=300):
    rng = random.Random(seed)
    for i in range(n):
        entry = rng.choice(('buy', 'sell'))
        inverse = rng.random() < 0.25
        bot, fills = _generate(rng, entry)
        cfg = dict(CFG, side='long' if entry == 'buy' else 'short')
        book, own = trips(fills, bot=bot, entry=entry, cfg=cfg, inverse=inverse)
        walk = pd.open_lots(fills, bot, entry, inverse)
        sign = 1.0 if entry == 'buy' else -1.0
        gross = 0.0
        exits = iter(walk['exits'])
        for x, o in zip(fills, own):
            if x['side'] == entry:
                continue
            w, covered, cost = next(exits)
            assert w is x and abs(covered - x['qty']) < 1e-9, (i, x)
            paired = x['qty'] / o if inverse else x['qty'] * o
            assert abs(paired - cost) < 1e-9 * max(1.0, cost), (i, x, paired, cost)
            gross += (x['qty'] * (1 / o - 1 / x['price']) if inverse else (x['price'] - o) * x['qty']) * sign
        assert abs(gross - book['gap_realized']) < 1e-9 * max(1.0, abs(gross)), i
        pos = abs(book['position'])
        held = sum(q for _, q in walk['lots'])
        assert walk['no_lot'] == 0 and abs(held - pos) < 1e-9, (i, held, pos)
        if inverse:
            shift = sign * ((pos / book['avg_cost'] if book['avg_cost'] else 0.0)
                            - sum(q / p for p, q in walk['lots']))
        else:
            shift = sign * (sum(p * q for p, q in walk['lots']) - book['avg_cost'] * pos)
        assert abs(gross - book['realized'] - shift) < 1e-8, (i, gross - book['realized'], shift)


def spec_F41_property_the_pairing_and_the_walk_agree_and_the_identity_holds():
    _property()


def spec_F41_sabotage_the_property_catches_a_looked_up_price():
    assert _sabotaged(lambda: _property(n=60))
