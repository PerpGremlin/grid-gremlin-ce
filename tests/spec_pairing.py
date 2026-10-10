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

def _recording(venue):
    """FakeVenue has no fill history; record fills so G23's walk can read
    the venue's own account, link ids and all."""
    fills = []
    orig = venue.fill

    def fill(order_id, avg):
        o = next(x for x in venue.orders if x['order_id'] == order_id)
        fills.append({'time_ms': 1000 * (len(fills) + 1), 'side': o['side'],
                      'price': float(avg), 'qty': float(o['qty']), 'fee': 0.0,
                      'link_id': o['link_id'], 'exec_id': str(len(fills)),
                      'symbol': 'BTCUSDT', 'market_type': 'linear'})
        orig(order_id, avg)
    venue.fill = fill
    venue.fills_history = lambda mt, sym, a, b: list(fills)
    return fills


def spec_G23_a_live_fill_then_a_dip_pairs_and_rearms_by_identity():
    venue, lines = FakeVenue(mark=60500.0), []
    _recording(venue)
    bot = Bot(_cfg(), ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1)
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
    assert rung['grid_profit'] < 0 < rung['trips']          # booked against
    # the average (R2), as 3Commas' own docs say — the readout's D8 split
    # shows the realised line negative while the trips bank one gap each


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
    _recording(venue)
    _accumulating(venue)
    stop = {'watch': 'mark_price', 'rungs_beyond': 3}
    bot = Bot(_cfg(slide=dict(BOTH), max_position_base='unbounded', stop=stop),
              ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1)
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
    # ...until the mark comes back inside the placement window
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
    fills = _recording(venue)
    _accumulating(venue)
    stop = {'watch': 'mark_price', 'rungs_beyond': 3}
    bot = Bot(_cfg(slide=dict(BOTH), max_position_base='unbounded', stop=stop),
              ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1)
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
    fills.clear()                                 # 30 days on: aged out
    bot._rungs_cache = None
    for _ in range(3):
        bot.cycle()
    after = sorted(float(o['price']) for o in venue.orders
                   if o['side'] == 'Sell')
    assert before == after == [59000.0, 60000.0, 61000.0]


# --- G26: the fill list lags the position; an exit never fires twice ---------

def _two_lots_then_the_lower_exit_fills(lag=True):
    """Buy 60k (rung 10) and 59k (rung 9); their exits rest at 61k and 60k.
    The 60k exit fills. The venue's POSITION says so at once; its fill list
    says so a few seconds later."""
    venue, lines = FakeVenue(mark=60500.0), []
    fills = _recording(venue)
    bot = Bot(_cfg(), ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1)
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
    late = {'time_ms': 9000, 'side': 'Sell', 'price': 60000.0, 'qty': sold,
            'fee': 0.0, 'link_id': exit_['link_id'], 'exec_id': 'late',
            'symbol': 'BTCUSDT', 'market_type': 'linear'}
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
    assert bot._rungs_cache[1] == [10]


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
    of ours. Waiting forever would leave the holding without exits."""
    from gridgremlin.bot import RUNGS_LAG_CYCLES
    venue, bot, _, _, lines = _two_lots_then_the_lower_exit_fills()
    for _ in range(RUNGS_LAG_CYCLES + 2):
        bot.cycle()
    assert sum('do not account for the change' in ln for ln in lines) == 1
    assert _sells(venue.orders)                    # exits are maintained again
    assert not any('caught up' in ln for ln in lines)   # re-baselined, not caught up


def spec_G26_through_flat_and_back_the_new_lot_gets_its_exit_at_once():
    """The baseline is the last account that added up, not the last
    holding: sold to flat and bought again, the fills since still net to
    the change, and nothing waits."""
    venue, lines = FakeVenue(mark=60500.0), []
    fills = _recording(venue)
    bot = Bot(_cfg(), ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1)
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
        fills.append({'time_ms': 1000 * (len(fills) + 1), 'side': 'Sell',
                      'price': 61000.0, 'qty': float(exit_['qty']),
                      'fee': 0.0, 'link_id': exit_['link_id'],
                      'exec_id': f'x{len(fills)}', 'symbol': 'BTCUSDT',
                      'market_type': 'linear'})
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
    fills = _recording(venue)
    bot = Bot(_cfg(), ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1)
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
    late = {'time_ms': 9000, 'side': 'Buy', 'price': 59000.0, 'qty': q2,
            'fee': 0.0, 'link_id': nxt['link_id'], 'exec_id': 'late',
            'symbol': 'BTCUSDT', 'market_type': 'linear'}
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
