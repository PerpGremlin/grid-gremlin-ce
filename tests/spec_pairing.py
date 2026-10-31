# Specs for SPEC G23 (D35): exits pair per rung. A grid sells each held lot
# one rung above the rung it was bought at — how every exchange grid bot and
# 3Commas work — regardless of the position's average. The engine stays
# netted (G12): the held block is derived from size + the venue's average,
# never remembered. G6's average-cost floor is the opt-in.

from gridgremlin.adapters import LinearAdapter
from gridgremlin.backtest import backtest
from gridgremlin.bot import Bot
from gridgremlin.config import ConfigError, validate_config
from gridgremlin.events import Notifier
from gridgremlin.ladder import held_block, plan_grid, rung_floor

from spec_loop import FakeVenue

ADAPTER = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001,
                         'price_tick': 0.1, 'min_qty': 0.001,
                         'min_notional': 5.0, 'settle_coin': 'USDT'})
LOT = 0.007


def _cfg(**over):
    row = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
           'capital': 1000.0, 'leverage': 10, 'upper': 70000.0,
           'lower': 50000.0, 'rungs': 21, 'spacing_type': 'fixed'}
    row.update(over)
    return validate_config(row)


def _sells(orders):
    return sorted(o['price'] for o in orders if o['side'] == 'Sell')


def _buys(orders):
    return sorted(o['price'] for o in orders if o['side'] == 'Buy')


# --- the block: which rungs the lots came from, from truth alone ------------

def spec_G23_the_held_block_is_pinned_by_size_and_average():
    cfg = _cfg()
    assert held_block(cfg, 1, 58000.0) == (8, 8)          # one lot at 58k
    assert held_block(cfg, 3, 59000.0) == (8, 10)         # 58k, 59k, 60k
    assert held_block(cfg, 3, 58666.0) == (8, 10)         # nearest fit
    assert held_block(cfg, 1, 58400.0) == (8, 8)          # adopted mid-gap
    assert held_block(cfg, 1, 58600.0) == (9, 9)
    assert held_block(cfg, 0, 58000.0) is None
    assert held_block(cfg, 2, None) is None
    geo = _cfg(spacing_type='percent', rungs=11)          # 50k..70k geometric
    from gridgremlin.ladder import lattice_price
    lo, hi = held_block(geo, 2, (lattice_price(geo, 4) + lattice_price(geo, 5)) / 2)
    assert (lo, hi) == (4, 5)


# --- the pairing: one rung above each lot, never the average -----------------

def spec_G23_one_lot_dipped_below_its_rung_exits_one_rung_above():
    # bought at 58,000; the mark slipped to 57,600 (past any hysteresis) —
    # the exit rests at 59,000, never at the 58,000 the lot cost.
    # SABOTAGE: with the floor at the ref alone (G6 without a basis) the
    # 58,000 rung is above the ref and becomes a zero-spread exit (R9).
    orders = plan_grid(_cfg(), ADAPTER, 57600.0, held_base=LOT, basis=58000.0)
    assert _sells(orders)[0] == 59000.0
    assert 58000.0 not in _sells(orders)
    from gridgremlin.ladder import split, grid_rungs
    naive = split('long', grid_rungs(_cfg(), ADAPTER), 57600.0)   # floor = ref
    assert naive['exits'][0][1] == 58000.0                        # the defect


def spec_G23_three_lots_exit_one_rung_above_each_never_the_average():
    # bought 60k, 59k, 58k on the way down (average 59k); mark now 57,700.
    # Per rung: 59k, 60k, 61k — the 58k lot sells at 59k although the
    # average is 59k. Under G6 the first exit had to clear 59,059: 60k+.
    orders = plan_grid(_cfg(), ADAPTER, 57700.0, held_base=3 * LOT,
                       basis=59000.0)
    assert _sells(orders) == [59000.0, 60000.0, 61000.0]
    g6 = plan_grid(_cfg(exit_floor='basis'), ADAPTER, 57700.0,
                   held_base=3 * LOT, basis=59000.0)
    assert _sells(g6)[0] == 60000.0
    # G7 by identity: every rung below the mark re-arms — 57k downward.
    # The count proxy (basis mode, the old engine) suppresses the nearest
    # three instead and buys again only from 54k: the sparse-ladder defect
    # measured 2026-09-28 (JOURNAL) — one extra rung skipped per lot held
    assert _buys(orders)[-1] == 57000.0
    assert _buys(g6)[-1] == 54000.0


def spec_G23_after_a_bounce_the_survivor_still_exits_one_rung_up():
    # two of three exits filled on the bounce; the 60k lot remains with the
    # mark between 60k and 61k: its exit is 61k, and 60k re-arms nothing
    orders = plan_grid(_cfg(), ADAPTER, 60400.0, held_base=LOT, basis=60000.0)
    assert _sells(orders) == [61000.0]
    assert 60000.0 not in _buys(orders)                   # G7 still holds


def spec_G23_a_short_mirrors():
    # sold 60k, 61k, 62k (average 61k); mark 62,300: buy-backs at 61k, 60k,
    # 59k — the 62k lot covers at 61k although the average is 61k
    orders = plan_grid(_cfg(side='short'), ADAPTER, 62300.0,
                       held_base=-3 * LOT, basis=61000.0)
    buys = _buys(orders)
    assert buys[-3:] == [59000.0, 60000.0, 61000.0]
    assert 62000.0 not in buys
    floor = rung_floor(_cfg(side='short'), ADAPTER, 'short', 62300.0, [10, 11, 12])
    assert floor == 62000.0


def spec_G23_the_ref_still_bounds_the_floor():
    # G13: a block below the mark (adopted in profit) exits above the MARK,
    # nearest first — never marketable
    orders = plan_grid(_cfg(), ADAPTER, 60000.0, held_base=3 * LOT, basis=55000.0)
    assert _sells(orders) == [61000.0, 62000.0, 63000.0]
    assert rung_floor(_cfg(), ADAPTER, 'long', 60000.0, [4, 5, 6]) == 60000.0
    assert rung_floor(_cfg(), ADAPTER, 'long', 60000.0, []) == 60000.0
    assert rung_floor(_cfg(), ADAPTER, 'long', 60000.0, None) == 60000.0


def spec_G23_the_config_defaults_to_rung_and_refuses_the_rest():
    assert _cfg()['exit_floor'] == 'rung'
    assert _cfg(exit_floor='basis')['exit_floor'] == 'basis'
    try:
        _cfg(exit_floor='average')
    except ConfigError as e:
        assert 'exit_floor' in str(e)
    else:
        raise AssertionError('an unknown floor was accepted')


# --- G7 exactly: the descent arms every rung ---------------------------------

def spec_G7_the_descent_arms_every_rung_by_identity():
    """Measured 2026-09-28: under the count proxy a long that bought 60k
    and sees the mark at 59.5k has 59k SUPPRESSED (the proxy treats the
    lot as the nearest rung below the mark) — the ladder bought 60k, 58k,
    55k, 51k on the way down, one more rung skipped per lot. By identity
    the lot is at rung 10 and 59k re-arms."""
    cfg = _cfg()
    walk = [(1, [10], 60000.0, 59500.0), (2, [9, 10], 59500.0, 58500.0),
            (3, [8, 9, 10], 59000.0, 57500.0)]
    for held, rungs, basis, ref in walk:
        o = plan_grid(cfg, ADAPTER, ref, held_base=held * LOT, basis=basis,
                      held_rungs=rungs)
        assert _buys(o)[-1] == ref - 500.0, (held, _buys(o)[-1])   # next rung
        old = plan_grid(_cfg(exit_floor='basis'), ADAPTER, ref,
                        held_base=held * LOT, basis=basis)
        assert _buys(old)[-1] == ref - 500.0 - 1000.0 * held         # skipped


# --- through the live bot: the fill, the dip, the exit one rung up ----------

class _Clock:
    """The bot's clock and the venue's stamps, one time: advanced by hand."""

    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def stamp(self, fills):
        """A fill's time: now, never in the bot's future, after the last."""
        last = max((f['time_ms'] for f in fills), default=0)
        return max(last + 1, int(self.t * 1000) - 1000)


def _fill_row(fills, clock, side, price, qty, link, exec_id=None):
    return {'time_ms': clock.stamp(fills), 'side': side, 'price': float(price),
            'qty': float(qty), 'fee': 0.0, 'link_id': link,
            'exec_id': exec_id or str(len(fills)), 'symbol': 'BTCUSDT',
            'market_type': 'linear'}


def _recording(venue, clock):
    """FakeVenue has no fill history; record fills so G23's walk can read
    the venue's own account, link ids and all — over the window it ASKS
    for, as the venue answers (the first cut answered every fill to every
    window, so the two-day/thirty-day split never ran here, 2026-10-31)."""
    fills = []
    orig = venue.fill

    def fill(order_id, avg):
        o = next(x for x in venue.orders if x['order_id'] == order_id)
        fills.append(_fill_row(fills, clock, o['side'], avg, o['qty'],
                               o['link_id']))
        orig(order_id, avg)
    venue.fill = fill
    venue.fills_history = lambda mt, sym, a, b: [
        f for f in fills if a <= f['time_ms'] <= b]
    return fills


def spec_G23_a_live_fill_then_a_dip_pairs_and_rearms_by_identity():
    venue, lines = FakeVenue(mark=60500.0), []
    clock = _Clock()
    _recording(venue, clock)
    bot = Bot(_cfg(), ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1,
              clock=clock)
    bot.cycle()
    buy = next(o for o in venue.orders if o['side'] == 'Buy'
               and float(o['price']) == 60000.0)
    venue.fill(buy['order_id'], buy['price'])
    venue.mark = 59400.0                                   # dipped below 60k
    bot.cycle()
    sells = sorted(float(o['price']) for o in venue.orders if o['side'] == 'Sell')
    buys = sorted(float(o['price']) for o in venue.orders if o['side'] == 'Buy')
    assert sells == [61000.0], sells                      # not 60,000
    assert buys[-1] == 59000.0, buys                      # 59k armed (G7)
    assert bot._held_rungs(0.007) == [10]


# --- T3: under water, the per-rung grid keeps capturing the oscillations ----

def _saw(lo_px, hi_px, n):
    bars = []
    for _ in range(n):
        bars.append({'o': hi_px, 'h': hi_px + 5, 'l': lo_px - 5, 'c': lo_px})
        bars.append({'o': lo_px, 'h': hi_px + 5, 'l': lo_px - 5, 'c': hi_px})
    return bars


def spec_G23_underwater_oscillations_are_trips_per_rung_and_idle_under_G6():
    # fall from 65k to 56k (buys 64k..57k, average ~60.5k), then a 57k<->58k
    # saw for twenty bars: per-rung sells the 57k lot at 58k on every swing
    # and re-buys it; the average-cost floor sells nothing until ~60.6k.
    fall = [{'o': 65000, 'h': 65000, 'l': 56000, 'c': 56500}]
    saw = _saw(56900.0, 58100.0, 10)
    rung = backtest(_cfg(), ADAPTER, fall + saw, bar_hours=1 / 12)
    basis = backtest(_cfg(exit_floor='basis'), ADAPTER, fall + saw,
                     bar_hours=1 / 12)
    assert basis['trips'] == 0                              # idle under water
    assert rung['trips'] >= 8, rung['trips']                # a trip per swing
    assert rung['realized'] < 0 < rung['trips']             # booked against
    # the average (R2), as 3Commas' own docs say — the readout's D8 split
    # shows the realised line negative while the trips bank one gap each
    assert rung['grid_profit'] > 0                          # R12: the trips' own


# --- G25 (D36): a lot's exit rests where it was intended, window or not ------
# The owner: "they need to rest where they were intended to be exited
# indefinitely. and only closed when the user kills the bot." Resting on the
# venue first; the placement window re-places one cancelled from outside
# when the mark comes back (the virtual fallback).

from gridgremlin.ladder import grid_rungs, paired_exits, slide_offset  # noqa: E402

BOTH = {'trigger_rungs': 2, 'max_rungs': 100, 'confirm_seconds': 0,
        'direction': 'both'}


def _full_ladder_qty(cfg):
    from gridgremlin.ladder import rung_notionals
    return sum(ADAPTER.round_qty(ADAPTER.qty_from_notional(n, p))
               for n, p in zip(rung_notionals(cfg), grid_rungs(cfg, ADAPTER)))


def spec_G25_after_an_adverse_slide_every_lot_keeps_its_own_exit():
    cfg = _cfg(slide=dict(BOTH), max_position_base='unbounded')
    held = _full_ladder_qty(cfg)
    new = slide_offset(cfg, 0, 48000.0)
    assert new == -12                                  # window 38k..58k
    orders = plan_grid(cfg, ADAPTER, 48000.0, held, 59000.0, offset=new,
                       held_rungs=list(range(21)))
    sells = [o for o in orders if o['side'] == 'Sell']
    # 21 lots bought at 50k..70k exit at 51k..71k — one rung above each,
    # thirteen of them above the slid window's top; nothing poured on 58k
    assert sorted(o['price'] for o in sells) == [51000.0 + 1000 * i
                                                 for i in range(21)]
    assert sorted(o['rung'] for o in sells) == list(range(1, 22))
    # each exit carries the lot it closes: bought higher, fewer coins
    by_px = {o['price']: o['qty'] for o in sells}
    assert by_px[51000.0] >= by_px[70000.0] > 0
    assert abs(sum(by_px.values()) - held) < 1e-9     # G8: all of it covered


def spec_G25_a_short_mirrors():
    cfg = _cfg(side='short', slide=dict(BOTH), max_position_base='unbounded')
    new = slide_offset(cfg, 0, 72000.0)
    assert new == 12                                   # window 62k..82k
    orders = plan_grid(cfg, ADAPTER, 72000.0, 0.021, 69000.0, offset=new,
                       held_rungs=[18, 19, 20])        # sold at 68k..70k
    buys = sorted(o['price'] for o in orders if o['side'] == 'Buy')
    assert buys == [67000.0, 68000.0, 69000.0], buys  # below the window


def spec_G25_an_average_pinned_block_never_leaves_the_window():
    """Only lots the bot's own fills prove get exits outside the window; a
    block the average pins is a fit, and S5's adopted basis beyond the range
    keeps no exits. Sabotage of `within`: the adopted lots would rest sells
    above the range for a position the grid never bought."""
    cfg = _cfg()
    orders = plan_grid(cfg, ADAPTER, 60000.0, 0.021, 71000.0)
    assert not [o for o in orders if o['side'] == 'Sell']
    proven = plan_grid(cfg, ADAPTER, 60000.0, 0.021, 71000.0,
                       held_rungs=[20, 21, 22])
    assert _sells(proven) == [71000.0, 72000.0, 73000.0]


def spec_G25_a_mark_jittering_on_the_rung_keeps_the_exit_it_has():
    cfg = _cfg()
    win = [(15, 65000.0), (16, 66000.0)]
    # 64k is inside the guard band of a 63,990 ask and does not rest: the
    # lot keeps the nearest placeable window exit instead of flipping
    moved = paired_exits(cfg, ADAPTER, 63990.0, [13], 1, win,
                         bid=63980.0, ask=63990.0, resting=frozenset({15}))
    assert [e[:2] for e in moved] == [(15, 65000.0)]
    # once its own rung rests it stays, whichever side the mark sits
    kept = paired_exits(cfg, ADAPTER, 64010.0, [13], 1, win,
                        bid=64000.0, ask=64010.0, resting=frozenset({14}))
    assert [e[:2] for e in kept] == [(14, 64000.0)]
    # the seed's lot has no rung of its own: displaced, as before
    seed = paired_exits(cfg, ADAPTER, 60000.0, [], 1, win)
    assert [e[:2] for e in seed] == [(15, 65000.0)]


def _accumulating(venue):
    """FakeVenue's fill REPLACES the position; a ladder of buys adds up."""
    rec = venue.fill

    def fill(order_id, avg):
        prev = dict(venue.position) if venue.position else None
        o = next(x for x in venue.orders if x['order_id'] == order_id)
        rec(order_id, avg)
        if prev:
            a, b = float(prev['size']), float(o['qty'])
            venue.position['size'] = f'{a + b:.3f}'
            venue.position['avgPrice'] = str(
                (a * float(prev['avgPrice']) + b * float(avg)) / (a + b))
    venue.fill = fill


def spec_G25_live_exits_rest_through_an_adverse_slide_and_come_back():
    venue, lines = FakeVenue(mark=60500.0), []
    clock = _Clock()
    _recording(venue, clock)
    _accumulating(venue)
    stop = {'watch': 'mark_price', 'rungs_beyond': 3}
    bot = Bot(_cfg(slide=dict(BOTH), max_position_base='unbounded', stop=stop),
              ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1,
              clock=clock)
    bot.cycle()
    for px in (60000.0, 59000.0, 58000.0):             # three lots bought
        buy = next(o for o in venue.orders if o['side'] == 'Buy'
                   and float(o['price']) == px)
        venue.fill(buy['order_id'], buy['price'])
        venue.mark = px - 400.0
        bot.cycle()
    before = {o['order_id']: float(o['price']) for o in venue.orders
              if o['side'] == 'Sell'}
    assert sorted(before.values()) == [59000.0, 60000.0, 61000.0]
    venue.mark = 48000.0
    bot.cycle()
    assert bot.offset == -12 and bot.alive             # the window slid down
    after = {o['order_id']: float(o['price']) for o in venue.orders
             if o['side'] == 'Sell'}
    assert after == before                             # same orders, resting
    assert not any('cancel' in ln and 'Sell' in ln for ln in lines)
    # cancelled from outside while the mark is far: nothing re-places it...
    top = next(k for k, v in after.items() if v == 61000.0)
    venue.cancel_order('linear', 'BTCUSDT', top)
    bot.cycle()
    assert 61000.0 not in [float(o['price']) for o in venue.orders]
    # ...until the mark comes back inside the placement window (and G23's
    # wait has settled the order as cancelled from outside: no fill of it
    # listed in a minute, 2026-10-31)
    clock.t += 61.0
    venue.mark = 59500.0
    bot.cycle()
    assert 61000.0 in [float(o['price']) for o in venue.orders
                       if o['side'] == 'Sell']


def spec_G25_a_resting_exit_outlives_the_fill_history():
    """The fills prove a lot for HISTORY_WINDOW_DAYS; a lot held longer falls
    back to the block the average pins, which stays inside the window. Its
    exit already rests on the venue, and that order is the proof: it stays.
    Sabotage: drop the resting-order rule and the diff cancels it."""
    venue, lines = FakeVenue(mark=60500.0), []
    clock = _Clock()
    fills = _recording(venue, clock)
    _accumulating(venue)
    stop = {'watch': 'mark_price', 'rungs_beyond': 3}
    bot = Bot(_cfg(slide=dict(BOTH), max_position_base='unbounded', stop=stop),
              ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1,
              clock=clock)
    bot.cycle()
    for px in (60000.0, 59000.0, 58000.0):
        buy = next(o for o in venue.orders if o['side'] == 'Buy'
                   and float(o['price']) == px)
        venue.fill(buy['order_id'], buy['price'])
        venue.mark = px - 400.0
        bot.cycle()
    venue.mark = 48000.0
    bot.cycle()
    assert bot.offset == -12
    before = sorted(float(o['price']) for o in venue.orders
                    if o['side'] == 'Sell')
    clock.t += 31 * 86_400.0                      # 31 days on: aged out of
    bot._rungs_cache = None                       # the window the bot reads
    assert fills and not venue.fills_history('linear', 'BTCUSDT',
                                             int(clock.t * 1000) - 30 * 86_400_000,
                                             int(clock.t * 1000))
    for _ in range(3):
        bot.cycle()
    after = sorted(float(o['price']) for o in venue.orders
                   if o['side'] == 'Sell')
    assert before == after == [59000.0, 60000.0, 61000.0]


# --- G23: the fitted block is counted in its own rungs' lots (the review) ----

def _descent(cfg, top):
    """Lots bought from rung `top` down to rung 0, each sized at its own
    rung: (held, average)."""
    from gridgremlin.ladder import lattice_price, rung_notionals
    qs = [(lattice_price(cfg, j), ADAPTER.round_qty(ADAPTER.qty_from_notional(
        rung_notionals(cfg)[j], lattice_price(cfg, j)))) for j in range(top + 1)]
    held = round(sum(q for _, q in qs), 3)
    return held, sum(p * q for p, q in qs) / held


def spec_G23_review_a_fitted_descent_counts_its_lots_at_their_own_rungs():
    """Twelve lots bought 61k down to 50k (0.097), no fill history, the mark
    at 49,950. Counted in lots at the mark they were eleven: the block lost
    its top rung and the 61k lot exited at 61k, its own buy price, two fees
    for nothing. Counted in its own rungs' lots the block is the twelve, and
    each exits one rung up. A seed (bought at the ref, the block across it)
    keeps today's count."""
    cfg = _cfg()
    held, avg = _descent(cfg, 11)
    assert held == 0.097
    orders = plan_grid(cfg, ADAPTER, 49950.0, held_base=held, basis=avg)
    sells = {o['price']: o['qty'] for o in orders if o['side'] == 'Sell'}
    assert sorted(sells) == [51000.0 + 1000 * i for i in range(12)], sells
    assert sells[62000.0] == 0.007 and sells[61000.0] == 0.007
    assert abs(sum(sells.values()) - held) < 1e-9          # G8: all covered
    # carried up: three lots bought 55k..57k (0.008 each), the mark now
    # 60,500 where a lot is 0.007 — three exits above the mark, not four
    up = plan_grid(cfg, ADAPTER, 60500.0, held_base=0.024, basis=56000.0)
    assert _sells(up) == [61000.0, 62000.0, 63000.0], _sells(up)
    # a seed: three lots at the ref, the block across it — today's count
    seed = plan_grid(cfg, ADAPTER, 60000.0, held_base=3 * LOT, basis=60000.0)
    assert len(_sells(seed)) == 3


def spec_G25_review_a_weighted_lot_exits_at_its_own_rungs_weight():
    """G25: each exit is sized to the lot it closes. With weights
    [3]*5 + [1]*16 the lots bought at 52k..54k are 0.018, 0.018 and 0.017;
    sized at the MEAN rung they got 0.009, 0.008 and 0.008, and the count at
    the ref added three exits for lots that do not exist — a one-rung bounce
    sold half of what was meant."""
    cfg = _cfg(rung_sizing='weighted', rung_weights=[3] * 5 + [1] * 16)
    orders = plan_grid(cfg, ADAPTER, 51500.0, 0.053, 53000.0,
                       held_rungs=[2, 3, 4])
    sells = [(o['price'], o['qty']) for o in orders if o['side'] == 'Sell']
    assert sells == [(53000.0, 0.018), (54000.0, 0.018), (55000.0, 0.017)], sells
    # a seed lot beside them (no rung of its own, 0.009 at the ref) is the
    # one displaced lot: it takes the nearest free window exit
    seeded = plan_grid(cfg, ADAPTER, 51500.0, 0.062, 53000.0,
                       held_rungs=[2, 3, 4])
    assert [(o['price'], o['qty']) for o in seeded if o['side'] == 'Sell'] == \
        sells + [(56000.0, 0.009)]


# --- G26: the fill list lags the position; an exit never fires twice ---------

def _two_lots_then_the_lower_exit_fills(lag=True):
    """Buy 60k (rung 10) and 59k (rung 9); their exits rest at 61k and 60k.
    The 60k exit fills. The venue's POSITION says so at once; its fill list
    says so a few seconds later."""
    venue, lines = FakeVenue(mark=60500.0), []
    clock = _Clock()
    fills = _recording(venue, clock)
    bot = Bot(_cfg(), ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1,
              clock=clock)
    bot.cycle()
    held, cost = 0.0, 0.0
    for px in (60000.0, 59000.0):
        buy = next(o for o in venue.orders if o['side'] == 'Buy'
                   and float(o['price']) == px)
        qty = float(buy['qty'])
        venue.fill(buy['order_id'], buy['price'])
        held, cost = held + qty, cost + qty * px
        venue.position = dict(venue.position, size=f'{held:.3f}',
                              avgPrice=str(cost / held))
        venue.mark = px - 400.0
        bot.cycle()
    assert _sells(venue.orders) == [60000.0, 61000.0]
    exit_ = next(o for o in venue.orders if o['side'] == 'Sell'
                 and float(o['price']) == 60000.0)
    sold = float(exit_['qty'])
    venue.orders.remove(exit_)                     # the 59k lot is sold
    venue.position = dict(venue.position, size=f'{held - sold:.3f}',
                          avgPrice='60000')
    venue.mark = 59900.0                           # and price fell back
    clock.t += 1.0
    late = _fill_row(fills, clock, 'Sell', 60000.0, sold, exit_['link_id'],
                     'late')                       # stamped when it filled
    if not lag:
        fills.append(late)
    return venue, bot, fills, late, lines


def spec_G26_a_lagging_fill_list_never_re_places_the_exit_that_just_filled():
    """Measured live 2026-10-02: 21 of 93 trips on the demo grids closed at
    zero spread and 11 at a loss. Seconds after an exit filled, the fill
    list still lacked it; the walk covered the smaller holding with the
    lot that had just been SOLD, re-placed that lot's exit, and its second
    fill closed an older lot at the price it was bought."""
    venue, bot, fills, late, _ = _two_lots_then_the_lower_exit_fills()
    for _ in range(3):
        bot.cycle()                                # the list still lags
        assert _sells(venue.orders) == [61000.0]   # nothing new, nothing cut
    fills.append(late)                             # the venue catches up
    bot.cycle()
    assert _sells(venue.orders) == [61000.0]       # the 60k lot's own exit
    assert _buys(venue.orders)[-1] == 59000.0      # and 59k is armed again
    assert bot._rungs_cache[2] == [10]


def spec_G26_how_long_the_fill_list_lagged_is_logged_when_it_catches_up():
    """The loose end, measured (2026-10-11: 42 escalations across three
    fleets, each after one ordinary fill, once on both sides of one symbol
    at once): when the list catches up, the log says after how many cycles
    — log-only, never the phone. A prompt list says nothing."""
    venue, bot, fills, late, lines = _two_lots_then_the_lower_exit_fills()
    for _ in range(3):
        bot.cycle()
    fills.append(late)
    bot.cycle()
    said = [ln for ln in lines if 'fill list caught up' in ln]
    assert said == ['[log] net linBTCUSDTl: fill list caught up after 3 cycle(s) (G26)'], said
    venue, bot, _, _, lines = _two_lots_then_the_lower_exit_fills(lag=False)
    bot.cycle()
    assert not any('caught up' in ln for ln in lines)


def spec_G26_a_prompt_fill_list_costs_nothing():
    venue, bot, _, _, _ = _two_lots_then_the_lower_exit_fills(lag=False)
    bot.cycle()
    assert _sells(venue.orders) == [61000.0]
    assert _buys(venue.orders)[-1] == 59000.0      # re-armed the same cycle


def spec_G26_a_change_the_fills_never_explain_stops_freezing_and_says_so():
    """An outside hand or a liquidation changes the position with no fill
    of ours. Waiting forever would leave the holding without exits.
    Here the exit's order also left the book with no fill listed: it is
    awaited first (G23, a minute, then an outside cancel), and G26's own
    wait starts when it settles (2026-10-31, the second review). SABOTAGE:
    keep G26's clock from the order's wait and the bot escalates the
    moment the order settles."""
    from gridgremlin.bot import RUNGS_LAG_SECONDS
    venue, bot, _, _, lines = _two_lots_then_the_lower_exit_fills()
    bot.cycle()
    assert not any('do not account' in ln for ln in lines)
    for _ in range(int(RUNGS_LAG_SECONDS) - 1):        # HL's 2 s poll
        bot._now.t += 2.0
        bot.cycle()
    assert not any('do not account' in ln for ln in lines)   # still waiting
    for _ in range(3):
        bot._now.t += 2.0
        bot.cycle()
    assert sum('do not account for the change' in ln for ln in lines) == 1
    assert _sells(venue.orders)                    # exits are maintained again
    assert not any('caught up' in ln for ln in lines)   # re-baselined, not caught up


def spec_G26_through_flat_and_back_the_new_lot_gets_its_exit_at_once():
    """The baseline is the last account that added up, not the last
    holding: sold to flat and bought again, the fills since still net to
    the change, and nothing waits."""
    venue, lines = FakeVenue(mark=60500.0), []
    clock = _Clock()
    fills = _recording(venue, clock)
    bot = Bot(_cfg(), ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1,
              clock=clock)
    bot.cycle()
    for _ in range(2):
        buy = next(o for o in venue.orders if o['side'] == 'Buy'
                   and float(o['price']) == 60000.0)
        venue.fill(buy['order_id'], buy['price'])
        venue.mark = 59900.0
        bot.cycle()
        assert _sells(venue.orders) == [61000.0]       # same cycle
        exit_ = venue.orders[[float(o['price']) for o in venue.orders]
                             .index(61000.0)]
        clock.t += 1.0
        fills.append(_fill_row(fills, clock, 'Sell', 61000.0, exit_['qty'],
                               exit_['link_id'], f'x{len(fills)}'))
        venue.orders.remove(exit_)
        venue.position = None                          # flat
        venue.mark = 60500.0
        for _ in range(4):                             # E9 confirms flat
            bot.cycle()
        assert bot.alive


def spec_G26_a_lagging_entry_fill_is_never_bought_twice():
    """Measured live 2026-10-02, three hours on the first cut: the exit
    side froze, but entries were planned from the last good account — so
    when the missing fill was an ENTRY, its rung looked empty and was
    bought again (two lots at one level). While the fills do not add up,
    nothing moves on either side."""
    venue, lines = FakeVenue(mark=60500.0), []
    clock = _Clock()
    fills = _recording(venue, clock)
    bot = Bot(_cfg(), ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1,
              clock=clock)
    bot.cycle()
    buy = next(o for o in venue.orders if o['side'] == 'Buy'
               and float(o['price']) == 60000.0)
    q1 = float(buy['qty'])
    venue.fill(buy['order_id'], buy['price'])
    venue.mark = 59600.0
    bot.cycle()                                    # one lot, exit at 61k
    nxt = next(o for o in venue.orders if o['side'] == 'Buy'
               and float(o['price']) == 59000.0)
    q2 = float(nxt['qty'])
    clock.t += 1.0
    late = _fill_row(fills, clock, 'Buy', 59000.0, q2, nxt['link_id'], 'late')
    venue.orders.remove(nxt)                       # 59k fills; the list lags
    venue.position = dict(venue.position, size=f'{q1 + q2:.3f}',
                          avgPrice=str((60000 * q1 + 59000 * q2) / (q1 + q2)))
    venue.mark = 59100.0                           # bounced just above it
    before = sorted((o['side'], float(o['price'])) for o in venue.orders)
    for _ in range(3):
        bot.cycle()
        now = sorted((o['side'], float(o['price'])) for o in venue.orders)
        assert now == before, set(now) ^ set(before)   # nothing moved
    assert not any('nothing harvestable' in ln for ln in lines)
    fills.append(late)
    bot.cycle()
    assert _sells(venue.orders) == [60000.0, 61000.0]  # both lots' exits
    assert 59000.0 not in _buys(venue.orders)          # held, not re-bought


# --- G23/G26: one list per derivation, reads only move forward (2026-10-31) ---
# Measured on the demo and HL fleets 2026-10-22..30: 28 and 23 orders a full
# account would never have planned — a rung re-bought while its lot was held,
# an exit re-placed after it filled. The check ran on the two-day read, the
# walk on a second, unchecked thirty-day read that had not caught up.

def _honest(venue, fills, hidden):
    """The venue's answer over the window asked, a fill in `hidden` missing
    from any read longer than three days (Bybit's thirty-day read behind
    its two-day read)."""
    venue.fills_history = lambda mt, sym, a, b: [
        f for f in fills if a <= f['time_ms'] <= b
        and not (b - a > 3 * 86_400_000 and f['exec_id'] in hidden)]


def _lots_bought_three_days_ago():
    """Buy 60k (rung 10) and 59k (rung 9); exits rest at 61k and 60k; three
    days pass, so the two-day read holds none of the lots."""
    venue, lines = FakeVenue(mark=60500.0), []
    clock = _Clock()
    fills, hidden = _recording(venue, clock), set()
    _honest(venue, fills, hidden)
    bot = Bot(_cfg(), ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1,
              clock=clock)
    bot.cycle()
    held, cost = 0.0, 0.0
    for px in (60000.0, 59000.0):
        buy = next(o for o in venue.orders if o['side'] == 'Buy'
                   and float(o['price']) == px)
        clock.t += 1.0
        venue.fill(buy['order_id'], buy['price'])
        held, cost = held + float(buy['qty']), cost + float(buy['qty']) * px
        venue.position = dict(venue.position, size=f'{held:.3f}',
                              avgPrice=str(cost / held))
        venue.mark = px - 400.0
        bot.cycle()
    assert _sells(venue.orders) == [60000.0, 61000.0]
    clock.t += 3 * 86_400.0
    bot.cycle()
    return venue, bot, fills, hidden, clock, held, lines


def spec_G23_lots_older_than_two_days_are_walked_from_the_thirty_day_read():
    """The fixture answers the window asked, so the two-day read covers
    nothing here and the thirty-day read names the lots. SABOTAGE: walk the
    two-day read alone and the derivation is None (the block)."""
    venue, bot, fills, _, clock, held, _ = _lots_bought_three_days_ago()
    buy = next(o for o in venue.orders if o['side'] == 'Buy'
               and float(o['price']) == 58000.0)
    clock.t += 1.0
    venue.fill(buy['order_id'], buy['price'])
    venue.position = dict(venue.position,
                          size=f"{held + float(buy['qty']):.3f}")
    venue.mark = 57600.0
    bot.cycle()
    assert bot._rungs_cache[2] == [8, 9, 10], bot._rungs_cache
    assert _sells(venue.orders) == [59000.0, 60000.0, 61000.0]


def spec_G26_one_list_a_thirty_day_read_behind_the_two_day_read_moves_nothing():
    """The 60k exit fills. The two-day read lists it and nets to the change;
    the thirty-day read — the one the walk needs, the lots being three days
    old — does not list it yet, so its lot still looks held. Walked from
    that second read the 60k exit was placed again (demo, 2026-10-28..30).
    One list: the thirty-day read is the one checked, and it is behind the
    two-day read. SABOTAGE: check the two-day read and walk the thirty-day
    read (the old code) and the 60k exit is placed again."""
    venue, bot, fills, hidden, clock, held, _ = _lots_bought_three_days_ago()
    exit_ = next(o for o in venue.orders if o['side'] == 'Sell'
                 and float(o['price']) == 60000.0)
    sold = float(exit_['qty'])
    venue.orders.remove(exit_)
    clock.t += 1.0
    fills.append(_fill_row(fills, clock, 'Sell', 60000.0, sold,
                           exit_['link_id'], 'sold'))
    hidden.add('sold')
    venue.position = dict(venue.position, size=f'{held - sold:.3f}',
                          avgPrice='60000')
    venue.mark = 59900.0
    before = sorted(o['order_id'] for o in venue.orders)
    for _ in range(3):
        clock.t += 1.0
        bot.cycle()
        assert sorted(o['order_id'] for o in venue.orders) == before
    hidden.clear()                                 # the long read catches up
    clock.t += 1.0
    bot.cycle()
    assert _sells(venue.orders) == [61000.0]
    assert _buys(venue.orders)[-1] == 59000.0      # the sold lot's rung re-arms
    assert bot._rungs_cache[2] == [10]


def spec_G26_a_read_missing_a_fill_already_seen_is_frozen():
    """Reads only move forward. The 59k lot's exit filled and was listed;
    59k was bought again. The next read lists the new buy but has lost the
    exit: its new fills net to the change, and walked, the old 59k lot
    looks held beside the new one. A read missing a fill an earlier read
    listed is behind: nothing placed or cancelled, nothing cached, no
    baseline. SABOTAGE: drop the forward check and the new lot's exit is
    placed from the read that went backwards."""
    venue, lines = FakeVenue(mark=60500.0), []
    clock = _Clock()
    fills, hidden = _recording(venue, clock), set()
    venue.fills_history = lambda mt, sym, a, b: [
        f for f in fills if a <= f['time_ms'] <= b
        and f['exec_id'] not in hidden]
    bot = Bot(_cfg(), ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1,
              clock=clock)
    bot.cycle()
    held, cost = 0.0, 0.0
    for px in (60000.0, 59000.0):
        buy = next(o for o in venue.orders if o['side'] == 'Buy'
                   and float(o['price']) == px)
        clock.t += 1.0
        venue.fill(buy['order_id'], buy['price'])
        held, cost = held + float(buy['qty']), cost + float(buy['qty']) * px
        venue.position = dict(venue.position, size=f'{held:.3f}',
                              avgPrice=str(cost / held))
        venue.mark = px - 400.0
        bot.cycle()
    exit_ = next(o for o in venue.orders if o['side'] == 'Sell'
                 and float(o['price']) == 60000.0)
    sold = float(exit_['qty'])
    venue.orders.remove(exit_)
    clock.t += 1.0
    fills.append(_fill_row(fills, clock, 'Sell', 60000.0, sold,
                           exit_['link_id'], 'sold'))
    venue.position = dict(venue.position, size=f'{held - sold:.3f}')
    venue.mark = 59900.0
    clock.t += 1.0
    bot.cycle()
    assert _sells(venue.orders) == [61000.0] and bot._rungs_cache[2] == [10]
    again = next(o for o in venue.orders if o['side'] == 'Buy'
                 and float(o['price']) == 59000.0)
    clock.t += 1.0
    fills.append(_fill_row(fills, clock, 'Buy', 59000.0, again['qty'],
                           again['link_id'], 'again'))
    venue.orders.remove(again)
    venue.position = dict(venue.position, size=f'{held:.3f}')
    hidden.add('sold')                             # the read went backwards
    venue.mark = 59600.0
    before = sorted(o['order_id'] for o in venue.orders)
    for _ in range(3):
        clock.t += 1.0
        bot.cycle()
        assert sorted(o['order_id'] for o in venue.orders) == before
        assert bot._rungs_cache[2] == [10]         # never cached from it
    hidden.clear()
    clock.t += 1.0
    bot.cycle()
    assert bot._rungs_cache[2] == [9, 10]
    assert _sells(venue.orders) == [60000.0, 61000.0]


def _reader(fills, clock):
    venue = FakeVenue(mark=60500.0)
    venue.fills_history = lambda mt, sym, a, b: [
        f for f in fills if a <= f['time_ms'] <= b]
    return Bot(_cfg(), ADAPTER, venue, Notifier(sink=[].append), gen_seed=1,
               clock=clock)


def spec_G23_the_walk_stops_at_an_unlinked_flatten():
    """The fleets were flattened by hand on 2026-10-21: unlinked sells, which
    the walk dropped as not ours — so a holding the newer fills did not
    cover was covered from lots sold in the flatten. The walk stops at the
    last flat; what
    the fills after it cannot cover is adoption (None, the block).
    SABOTAGE: drop the unlinked closes from the walk and the flattened lots
    come back as held rungs."""
    clock, fills = _Clock(), []
    bot = _reader(fills, clock)
    b = bot.botid
    for rung, px in ((10, 60000.0), (9, 59000.0)):
        clock.t += 60.0
        fills.append(_fill_row(fills, clock, 'Buy', px, LOT, f'{b}-{rung}-a'))
    clock.t += 60.0
    fills.append(_fill_row(fills, clock, 'Sell', 59100.0, 2 * LOT, ''))  # flatten
    clock.t += 60.0
    fills.append(_fill_row(fills, clock, 'Buy', 58000.0, LOT, f'{b}-8-b'))
    assert bot._held_rungs(LOT) == [8]                # covered after the flat
    fresh = _reader(fills, clock)                     # a restart: no baseline
    assert fresh._held_rungs(2 * LOT) is None         # never the sold lots


def spec_G23_an_order_filled_in_parts_is_one_lot():
    """Partial fills made one lot per execution: an order filled in three
    parts named its rung three times, and the plan counted three lots at
    their own rung's weight (G25) — the exits short, the cap spent.
    SABOTAGE: walk executions instead of orders and the rung is named
    three times."""
    clock, fills = _Clock(), []
    bot = _reader(fills, clock)
    link = f'{bot.botid}-10-a'
    for part in (0.003, 0.002, 0.002):
        clock.t += 1.0
        fills.append(_fill_row(fills, clock, 'Buy', 60000.0, part, link))
    clock.t += 1.0
    fills.append(_fill_row(fills, clock, 'Buy', 59000.0, LOT,
                           f'{bot.botid}-9-a'))
    assert bot._held_rungs(2 * LOT) == [9, 10]


def spec_G23_a_float_residue_is_never_a_lot():
    """Ten lots bought 65k down to 56k (0.007 above 60k, 0.008 below), five
    sold on the way back up. The sells net the five newest buys to a float
    residue of 1e-18, and `take > 0` named the sold 60k lot as held: its
    exit at 61k was placed again and filled with no lot under it (found by
    the rehearsal, 2026-10-31; main had it with a perfect list). SABOTAGE:
    count any positive take and rung 10 comes back."""
    clock, fills = _Clock(), []
    bot = _reader(fills, clock)
    b = bot.botid
    for rung in range(15, 5, -1):
        clock.t += 60.0
        fills.append(_fill_row(fills, clock, 'Buy', 50000.0 + 1000 * rung,
                               0.007 if rung >= 10 else 0.008,
                               f'{b}-{rung}-a'))
    for rung in range(6, 11):
        clock.t += 60.0
        fills.append(_fill_row(fills, clock, 'Sell', 51000.0 + 1000 * rung,
                               0.007 if rung >= 10 else 0.008,
                               f'{b}-{rung + 1}-b'))
    assert bot._held_rungs(0.035) == [11, 12, 13, 14, 15]


# --- G23: an own order that left the book is awaited in the fills (review,
# 2026-10-31) -------------------------------------------------------------------

def _one_lot(notifier=None):
    """One lot bought at 60k (rung 10): its exit rests at 61k, 59k is armed.
    The venue's fills are a list the spec can hold back (`hidden`)."""
    venue, lines = FakeVenue(mark=60500.0), []
    clock = _Clock()
    fills, hidden = [], set()

    def fill(order_id):
        o = next(x for x in venue.orders if x['order_id'] == order_id)
        clock.t += 0.5
        fills.append(_fill_row(fills, clock, o['side'], o['price'], o['qty'],
                               o['link_id']))
        venue.orders = [x for x in venue.orders if x['order_id'] != order_id]
        return fills[-1]
    venue.fills_history = lambda mt, sym, a, b: [
        f for f in fills if a <= f['time_ms'] <= b
        and f['exec_id'] not in hidden]
    bot = Bot(_cfg(), ADAPTER, venue,
              notifier or Notifier(sink=lines.append), gen_seed=1,
              clock=clock)
    bot.cycle()
    buy = next(o for o in venue.orders if o['side'] == 'Buy'
               and float(o['price']) == 60000.0)
    fill(buy['order_id'])
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': '0.007',
                      'avgPrice': '60000', 'leverage': '10',
                      'unrealisedPnl': '0'}
    venue.mark = 59400.0
    for _ in range(2):
        clock.t += 2.0
        bot.cycle()
    assert _sells(venue.orders) == [61000.0] and bot._rungs_cache[2] == [10]
    return venue, bot, fills, hidden, clock, fill, lines


def _book(venue):
    return sorted(o['order_id'] for o in venue.orders)


def spec_G23_an_exit_and_the_entry_below_in_one_poll_are_awaited_in_the_fills():
    """The 61k exit and the 59k entry fill in one poll: the holding is what
    it was, the fill list has neither yet. The first cut re-read the fills
    on the vanished links, found the newest fill unchanged, concluded an
    outside cancel and cleared the trigger — and re-placed 61k and bought
    59k again with lot 9 held (the review's repro). Each link is awaited
    until a fill of it is listed: nothing moves meanwhile, then the lots are
    paired from the list. SABOTAGE: never await the vanished links and 61k
    is placed again over a sold lot."""
    venue, bot, fills, hidden, clock, fill, _ = _one_lot()
    s = next(o for o in venue.orders if o['side'] == 'Sell')
    hidden.add(fill(s['order_id'])['exec_id'])
    b = next(o for o in venue.orders if o['side'] == 'Buy'
             and float(o['price']) == 59000.0)
    hidden.add(fill(b['order_id'])['exec_id'])
    before = _book(venue)
    for _ in range(5):
        clock.t += 2.0
        bot.cycle()
        assert _book(venue) == before, _book(venue)
    hidden.clear()
    clock.t += 2.0
    bot.cycle()
    assert bot._rungs_cache[2] == [9]
    assert _sells(venue.orders) == [60000.0]           # lot 9's own exit
    assert 59000.0 not in _buys(venue.orders)          # held, not re-bought


def spec_G23_an_order_cancelled_from_outside_is_settled_after_the_wait():
    """No fill of it is ever listed: after G26's wait it is taken as
    cancelled from outside, said once, and re-placed. SABOTAGE: never
    settle by the wait and the bot stays frozen."""
    venue, bot, fills, hidden, clock, fill, lines = _one_lot()
    s = next(o for o in venue.orders if o['side'] == 'Sell')
    venue.cancel_order('linear', 'BTCUSDT', s['order_id'])
    for _ in range(25):
        clock.t += 2.0
        bot.cycle()
        assert 61000.0 not in _sells(venue.orders)
    for _ in range(6):
        clock.t += 2.0
        bot.cycle()
    assert _sells(venue.orders) == [61000.0]
    assert sum('taken as cancelled from outside' in ln for ln in lines) == 1


def spec_G23_a_failed_read_after_an_order_left_never_plans_from_a_guess():
    """The 61k exit fills (holding down to nothing? no: an entry fills with
    it, the size unchanged) and the next reads fail. Inside the wait the
    cached lots are kept and nothing moves — the first cut fell back to the
    block the average pins and placed from it. SABOTAGE: on a failed read
    return the block (None) without the freeze and the book moves."""
    from gridgremlin.exchange.errors import VenueError
    venue, bot, fills, hidden, clock, fill, _ = _one_lot()
    s = next(o for o in venue.orders if o['side'] == 'Sell')
    fill(s['order_id'])
    b = next(o for o in venue.orders if o['side'] == 'Buy'
             and float(o['price']) == 59000.0)
    fill(b['order_id'])
    honest = venue.fills_history

    def down(mt, sym, a, b):
        raise VenueError('executions: timed out')
    venue.fills_history = down
    before = _book(venue)
    for _ in range(5):
        clock.t += 2.0
        bot.cycle()
        assert _book(venue) == before
        assert bot._rungs_cache[2] == [10]
    venue.fills_history = honest
    clock.t += 2.0
    bot.cycle()
    assert _sells(venue.orders) == [60000.0] and bot._rungs_cache[2] == [9]


def spec_G23_an_order_placed_this_cycle_is_watched_too():
    """The book was taken before the cycle's own placements, so an order
    placed this cycle was not watched: had it filled before the next cycle
    beside another of ours placed with it, the size unchanged, nothing
    would have re-read the fills. Every order resting after the cycle is
    watched. SABOTAGE: watch only what rested before the placements and
    the orders the first cycle placed are not watched."""
    venue, lines = FakeVenue(mark=60500.0), []
    bot = Bot(_cfg(), ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1,
              clock=_Clock())
    bot.cycle()
    placed = {o['link_id'] for o in venue.orders}
    assert placed and placed <= bot._rungs_links


def spec_G23_a_cancel_that_comes_back_gone_is_still_awaited():
    """A cancel the venue answers 'gone' found the order already gone —
    filled, as like as not. Subtracted as our own cancel, its fill was
    never awaited. SABOTAGE: subtract 'gone' cancels and the stray's fill,
    held back, never freezes the bot."""
    from gridgremlin.exchange.errors import VenueError
    venue, bot, fills, hidden, clock, fill, _ = _one_lot()
    stray = {'order_id': 'stray', 'link_id': f'{bot.botid}-3-zz',
             'side': 'Buy', 'price': 53000.0, 'qty': '0.009',
             'reduce_only': False, 'position_idx': 1}
    venue.orders.append(stray)                        # ours, not planned
    real_cancel = venue.cancel_order

    def cancel(mt, sym, oid):
        if oid == 'stray':                            # it filled first
            hidden.add(fill('stray')['exec_id'])
            raise VenueError('order not exists', kind='gone')
        return real_cancel(mt, sym, oid)
    venue.cancel_order = cancel
    clock.t += 2.0
    bot.cycle()
    assert f'{bot.botid}-3-zz' in bot._rungs_links
    clock.t += 2.0
    bot.cycle()
    assert bot._rungs_awaited and bot._rungs_frozen(clock())


def spec_G26_a_fill_older_than_the_hour_that_leaves_the_answer_is_not_a_lag():
    """Reads only move forward over the last hour. A fill two hours old
    that leaves the venue's answer for good (a demo reset, a venue that
    forgets) is no lag a wait ends: held as one, the bot froze and re-read
    every cycle for the rest of the window. SABOTAGE: remember fills for
    the whole window and the bot freezes."""
    clock, fills = _Clock(), []
    bot = _reader(fills, clock)
    b = bot.botid
    fills.append(_fill_row(fills, clock, 'Buy', 60000.0, LOT, f'{b}-10-a',
                           'old'))
    clock.t += 7200.0
    fills.append(_fill_row(fills, clock, 'Buy', 59000.0, LOT, f'{b}-9-a'))
    assert bot._held_rungs(2 * LOT) == [9, 10]
    fills.pop(0)                                      # forgotten by the venue
    clock.t += 60.0
    fills.append(_fill_row(fills, clock, 'Sell', 60000.0, LOT, f'{b}-10-b',
                           'sold'))
    assert bot._held_rungs(LOT) is None               # adoption: the block
    assert not bot._rungs_frozen(clock())             # not a lag


def spec_G26_the_escalation_reaches_the_phone():
    """Past the wait the bot pairs from fills that do not add up — the
    owner needs to know now: urgent (D60), not a plain warn that needs five
    in fifteen minutes to page. SABOTAGE: a plain warn."""
    said = []

    class Rec(Notifier):
        def event(self, kind, botid, text, icon='', urgent=False):
            said.append((kind, text, urgent))
    venue, bot, fills, hidden, clock, fill, _ = _one_lot(Rec())
    venue.position = dict(venue.position, size='0.014')   # an outside hand
    for _ in range(35):
        clock.t += 2.0
        bot.cycle()
    esc = [u for k, t, u in said if 'do not account' in t]
    assert esc == [True], esc


def spec_G23_an_unlinked_fill_that_reduced_nothing_is_no_close():
    """In hedge mode a hand may open the opposite side on our symbol: an
    unlinked sell that closed nothing (Bybit's closedSize 0, HL's 'Open
    Short'). Counted as a close, it sold our lots in the walk. Where the
    venue says, only a reduce is a close. SABOTAGE: count every unlinked
    exit-side fill and the lots are lost."""
    clock, fills = _Clock(), []
    bot = _reader(fills, clock)
    b = bot.botid
    for rung, px in ((10, 60000.0), (9, 59000.0)):
        clock.t += 60.0
        fills.append(_fill_row(fills, clock, 'Buy', px, LOT, f'{b}-{rung}-a'))
    clock.t += 60.0
    fills.append(dict(_fill_row(fills, clock, 'Sell', 59100.0, 2 * LOT, ''),
                      reduces=False))                 # a short, by hand
    assert bot._held_rungs(2 * LOT) == [9, 10]


# --- G23: the venue's own status settles an order that left the book
# (2026-10-31, the second review) -----------------------------------------------

def spec_G23_an_order_the_venue_rejected_is_settled_by_its_status_at_once():
    """A post-only order is accepted, then cancelled by the venue (B5); no
    fill will ever list it. Waiting the minute out froze the whole bot —
    in a fast market a minute per reject, new lots without exits. The
    venue's status of the order, asked once, says it ended with nothing
    executed: settled at once, the exit re-placed. SABOTAGE: never ask and
    the bot is frozen for the minute."""
    venue, bot, fills, hidden, clock, fill, lines = _one_lot()
    asked = []

    def status(mt, sym, link):
        asked.append(link)
        return 'cancelled'
    venue.order_status = status
    s = next(o for o in venue.orders if o['side'] == 'Sell')
    venue.orders = [o for o in venue.orders if o is not s]    # rejected
    for _ in range(2):
        clock.t += 2.0
        bot.cycle()
    assert _sells(venue.orders) == [61000.0]
    assert asked == [s['link_id']]
    assert not any('cancelled from outside' in ln for ln in lines)


def spec_G23_a_status_read_that_fails_or_says_filled_settles_nothing():
    """The status is asked for an answer, never assumed: a read that fails
    is asked again and keeps the wait (E5); 'filled' keeps it until the
    fill is listed. SABOTAGE: take a failed read as settled, or 'filled'
    as settled, and the exit is placed again over a lot already sold."""
    from gridgremlin.exchange.errors import VenueError
    venue, bot, fills, hidden, clock, fill, _ = _one_lot()
    answers = ['down', 'down', 'filled']

    def status(mt, sym, link):
        a = answers.pop(0) if answers else 'filled'
        if a == 'down':
            raise VenueError('timed out', kind='rate_limit')
        return a
    venue.order_status = status
    s = next(o for o in venue.orders if o['side'] == 'Sell')
    hidden.add(fill(s['order_id'])['exec_id'])        # filled, not listed
    b = next(o for o in venue.orders if o['side'] == 'Buy'
             and float(o['price']) == 59000.0)
    hidden.add(fill(b['order_id'])['exec_id'])        # size unchanged
    before = _book(venue)
    for _ in range(6):
        clock.t += 2.0
        bot.cycle()
        assert _book(venue) == before
    assert answers == []                               # asked until answered
    hidden.clear()
    clock.t += 2.0
    bot.cycle()
    assert bot._rungs_cache[2] == [9] and _sells(venue.orders) == [60000.0]


def spec_G23_what_reduces_is_the_venues_word():
    """HL: 'Close Long', a flip ('Long > Short', its closing part) and our
    own liquidation reduce; 'Open Short' does not. Bybit: a forced fill
    (BustTrade, AdlTrade) reduces like any close. SABOTAGE: HL's 'Close'
    alone, or Bybit's closedSize alone, and the flip, our liquidation and
    the forced close are no closes."""
    from gridgremlin.exchange.hyperliquid.truth import read_fills as hl_read
    from gridgremlin.exchange.bybit.truth import read_fills as bb_read
    me = '0x' + 'ab' * 20

    def row(i, d, liq=None):
        return {'coin': 'SOL', 'tid': i, 'time': i, 'side': 'A', 'px': '1',
                'sz': '1', 'fee': '0', 'cloid': None, 'dir': d,
                'liquidation': liq}
    got = hl_read([row(1, 'Close Long'), row(2, 'Long > Short'),
                   row(3, 'Open Short'),
                   row(4, 'Open Short', {'liquidatedUser': me})],
                  {'SOL'}, me)
    assert [f['reduces'] for f in got] == [True, True, False, True]

    class Bybit:
        def executions_page(self, category, symbol, start, end, cursor=None):
            return {'list': [
                {'execId': 'x', 'execType': 'BustTrade', 'execTime': '5',
                 'symbol': symbol, 'side': 'Sell', 'execPrice': '1',
                 'execQty': '1', 'execFee': '0', 'orderLinkId': '',
                 'closedSize': '0'},
                {'execId': 'y', 'execType': 'Trade', 'execTime': '6',
                 'symbol': symbol, 'side': 'Sell', 'execPrice': '1',
                 'execQty': '1', 'execFee': '0', 'orderLinkId': '',
                 'closedSize': '0'}], 'nextPageCursor': None}
    fills = bb_read(Bybit(), 'linear', 'SOLUSDT', 0, 10)
    assert [f['reduces'] for f in fills] == [True, False]
