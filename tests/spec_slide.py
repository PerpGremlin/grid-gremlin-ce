# Specs for SPEC G17-G20 (the slide, D28) and T6 (the backtester's window).
# The slide is a ratchet over an unchanged lattice: the window moves by whole
# rungs in the favourable direction (the adverse way too, opt-in: G24, D34),
# never back past where it started, never past the clamp.

import math

from gridgremlin.adapters import LinearAdapter
from gridgremlin.backtest import backtest
from gridgremlin.config import ConfigError, validate_config
from gridgremlin.ladder import (grid_rungs, lattice_index, lattice_price,
                                plan_grid, slide_offset, split)

ADAPTER = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001,
                         'price_tick': 0.1, 'min_qty': 0.001,
                         'min_notional': 5.0, 'settle_coin': 'USDT'})
SLIDE = {'trigger_rungs': 2, 'max_rungs': 100, 'confirm_seconds': 0}


def _cfg(**over):
    row = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
           'capital': 1000.0, 'leverage': 10, 'upper': 70000.0,
           'lower': 50000.0, 'rungs': 21, 'spacing_type': 'fixed',
           'slide': dict(SLIDE)}
    row.update(over)
    return validate_config(row)


def _bar(o, h, l, c):
    return {'o': o, 'h': h, 'l': l, 'c': c}


# --- G17: one lattice, many windows ------------------------------------------

def spec_G17_a_slid_window_shares_prices_with_home_on_the_overlap():
    for st in ('fixed', 'percent'):
        cfg = _cfg(spacing_type=st)
        home = grid_rungs(cfg, ADAPTER)
        slid = grid_rungs(cfg, ADAPTER, offset=5)
        assert slid[:16] == home[5:], st           # identical prices, same index
        assert slid[-1] > home[-1]                 # five new rungs above
        assert grid_rungs(cfg, ADAPTER, offset=-3)[3:] == home[:18]  # and below
    assert lattice_price(_cfg(), 20) == 70000.0    # endpoint exact, any window


def spec_G17_rung_ids_are_absolute_lattice_indices():
    cfg = _cfg()
    parts = split('long', grid_rungs(cfg, ADAPTER, 5), 62500.0, offset=5)
    ids = {i for i, _ in parts['entries']} | {i for i, _ in parts['exits']}
    assert min(ids) == 5 and max(ids) == 25
    orders = plan_grid(cfg, ADAPTER, 62500.0, offset=5)
    assert {o['rung'] for o in orders} <= set(range(5, 26))
    # the same absolute rung has the same price from either window
    by_home = {o['rung']: o['price'] for o in plan_grid(cfg, ADAPTER, 62500.0)}
    by_slid = {o['rung']: o['price'] for o in orders}
    for r in set(by_home) & set(by_slid):
        assert by_home[r] == by_slid[r], r


def spec_G17_lattice_index_inverts_lattice_price():
    for st in ('fixed', 'percent'):
        cfg = _cfg(spacing_type=st)
        for j in (-4, 0, 7, 20, 33):
            assert abs(lattice_index(cfg, lattice_price(cfg, j)) - j) < 1e-9


# --- G18: the trigger and the ratchet ----------------------------------------

def spec_G18_no_slide_until_the_ref_is_trigger_rungs_beyond_the_top():
    cfg = _cfg()                                   # top 70000, step 1000, K=2
    assert slide_offset(cfg, 0, 69000.0) == 0      # inside
    assert slide_offset(cfg, 0, 71999.0) == 0      # one rung past: not yet
    new = slide_offset(cfg, 0, 72000.0)            # exactly K rungs past
    assert new > 0
    # the ref lands at ref_position (0.5) of the new window
    rungs = grid_rungs(cfg, ADAPTER, new)
    assert rungs[0] <= 72000.0 <= rungs[-1]
    assert abs(lattice_index(cfg, 72000.0) - new - 10) < 1.0


def spec_G18_a_long_window_never_retreats():
    cfg = _cfg()
    up = slide_offset(cfg, 0, 80000.0)
    assert up > 0
    assert slide_offset(cfg, up, 50000.0) == up    # the crash does not slide it
    assert slide_offset(cfg, up, 20000.0) == up


def spec_G18_a_short_window_slides_down_only():
    cfg = _cfg(side='short')
    assert slide_offset(cfg, 0, 51000.0) == 0
    down = slide_offset(cfg, 0, 48000.0)           # K rungs below the bottom
    assert down < 0
    rungs = grid_rungs(cfg, ADAPTER, down)
    assert rungs[0] <= 48000.0 <= rungs[-1]
    assert slide_offset(cfg, down, 90000.0) == down  # the rally does not lift it


def spec_G18_ref_position_one_puts_the_whole_ladder_below_the_ref():
    cfg = _cfg(slide=dict(SLIDE, ref_position=1.0))
    new = slide_offset(cfg, 0, 75000.0)
    assert grid_rungs(cfg, ADAPTER, new)[-1] <= 75000.0
    assert all(o['side'] == 'Buy' for o in plan_grid(cfg, ADAPTER, 75000.0, offset=new))


def spec_G18_ref_position_one_puts_a_shorts_whole_ladder_above_the_ref():
    # the outside review's twelfth finding (owner, 2026-10-30): 1.0 is the
    # ENTRY side for a short too — its sells above the ref. Measured from the
    # bottom, a short 50k..70k falling to 45k slid to 25k..45k and planned
    # nothing but exits it did not hold.
    cfg = _cfg(side='short', slide=dict(SLIDE, ref_position=1.0))
    new = slide_offset(cfg, 0, 45000.0)
    rungs = grid_rungs(cfg, ADAPTER, new)
    assert rungs[0] >= 45000.0 and rungs[0] - 45000.0 < 1000.0
    orders = plan_grid(cfg, ADAPTER, 45000.0, offset=new)
    assert orders and all(o['side'] == 'Sell' for o in orders)
    # 0.0 is the mirror: the whole ladder below, the exit side
    low = _cfg(side='short', slide=dict(SLIDE, ref_position=0.0))
    assert grid_rungs(low, ADAPTER, slide_offset(low, 0, 45000.0))[-1] <= 45000.0


def spec_G18_the_middle_is_the_middle_for_either_side():
    # the 0.5 default lands the ref on the same index whichever side
    for n in (12, 21):
        long_ = _cfg(rungs=n)
        short = _cfg(rungs=n, side='short')
        up = slide_offset(long_, 0, 80000.0)
        down = slide_offset(short, 0, 40000.0)
        assert (math.floor(lattice_index(long_, 80000.0)) - up
                == math.ceil(lattice_index(short, 40000.0)) - down), n


def spec_G18_without_slide_the_offset_is_frozen():
    cfg = _cfg(slide=None)
    assert 'slide' not in cfg or not cfg['slide']
    assert slide_offset(cfg, 0, 1e9) == 0


# --- G19: the clamp ----------------------------------------------------------

def spec_G19_the_clamp_bounds_the_window_from_home():
    cfg = _cfg(slide=dict(SLIDE, max_rungs=3))
    assert slide_offset(cfg, 0, 1e6) == 3
    assert slide_offset(cfg, 3, 1e6) == 3
    assert slide_offset(_cfg(side='short', slide=dict(SLIDE, max_rungs=3)),
                        0, 1.0) == -3


# --- G20: inventory survives the slide ----------------------------------------

def spec_G20_held_lots_keep_their_exits_after_a_slide():
    cfg = _cfg()
    held, basis = 0.02, 68000.0                    # two lots bought near the top
    new = slide_offset(cfg, 0, 72500.0)
    orders = plan_grid(cfg, ADAPTER, 72500.0, held, basis, offset=new)
    exits = [o for o in orders if o['side'] == 'Sell']
    assert exits and abs(sum(o['qty'] for o in exits) - held) < 1e-9
    assert all(o['price'] >= basis * 1.001 for o in exits)      # G6 floor holds
    assert all(o['price'] > 72500.0 for o in exits)             # G13: not marketable


# --- the sabotage: without the slide a trend leaves the grid idle ------------

def _trend(start=60000.0, per_bar=600.0, bars=60):
    """A rising zig-zag: every bar dips 1.3 rungs and rallies 1.1 rungs, net
    +0.6 rungs — a grid inside its range trips every bar; outside, nothing."""
    out, p = [], start
    for _ in range(bars):
        out.append(_bar(p, p + 1100.0, p - 1300.0, p + per_bar))
        p += per_bar
    return out


def spec_G18_sabotage_no_slide_idles_through_a_trend():
    # pins: G11 (out of range the grid idles)
    bars = _trend()
    frozen = backtest(_cfg(slide=None), ADAPTER, bars, fee_rate=0.0002)
    sliding = backtest(_cfg(), ADAPTER, bars, fee_rate=0.0002)
    assert frozen['slides'] == 0 and sliding['slides'] >= 2
    # the frozen grid stops trading once price leaves 70000; the slid one keeps going
    assert sliding['trips'] > frozen['trips'] * 2
    assert sliding['entry_fills'] > frozen['entry_fills'] * 2
    assert sliding['net'] > frozen['net']


# --- T6: the backtester rests only the window ---------------------------------

def spec_T6_a_rung_outside_the_window_never_fills():
    cfg = _cfg(slide=None, place_within_pct=0.02)   # 2%: 58800..61200 at 60000
    r = backtest(cfg, ADAPTER, [_bar(60000.0, 60100.0, 55500.0, 59500.0)])
    assert r['entry_fills'] == 1                     # 59000 rests; 56000-58000 do not
    wide = backtest(_cfg(slide=None, place_within_pct=0.2), ADAPTER,
                    [_bar(60000.0, 60100.0, 55500.0, 59500.0)])
    assert wide['entry_fills'] == 4


def spec_T6b_a_resting_exit_is_not_moved_by_the_quote_guard():
    # bought at 59000, its exit placed at 60000 from 59500's open; the next
    # open sits inside the guard of 60000: the venue order stays (B4) and fills
    cfg = _cfg(slide=None)
    r = backtest(cfg, ADAPTER, [_bar(60000.0, 60100.0, 58995.0, 59500.0),
                                _bar(59500.0, 59600.0, 59400.0, 59500.0),
                                _bar(59999.5, 60100.0, 59990.0, 60050.0)])
    assert r['entry_fills'] == 1 and r['trips'] == 1 and r['held'] == 0.0
    # never placed (no bar opened clear of the guard): it goes a rung up
    fresh = backtest(cfg, ADAPTER, [_bar(60000.0, 60100.0, 58995.0, 59999.5),
                                    _bar(59999.5, 60100.0, 59990.0, 60050.0)])
    assert fresh['trips'] == 0 and fresh['held'] > 0


def spec_T6b_a_resting_exit_outside_the_window_still_fills():
    # W3: the 60000 exit rests from 59500; the next open (58700) puts it
    # outside a 2% window, and the venue order is still there to fill
    cfg = _cfg(slide=None, place_within_pct=0.02)
    r = backtest(cfg, ADAPTER, [_bar(60000.0, 60100.0, 58995.0, 59500.0),
                                _bar(59500.0, 59600.0, 59400.0, 59500.0),
                                _bar(58700.0, 60100.0, 58650.0, 60050.0)])
    assert r['entry_fills'] == 1 and r['trips'] == 1
    # never resting (bought and gapped away before it was placed): no fill
    gapped = backtest(cfg, ADAPTER, [_bar(60000.0, 60100.0, 58995.0, 58700.0),
                                     _bar(58700.0, 60100.0, 58650.0, 60050.0)])
    assert gapped['trips'] == 0


# --- C: the key is bounded ----------------------------------------------------

def spec_C3_slide_knobs_are_bounded_and_defaulted():
    cfg = _cfg()
    assert cfg['slide'] == {'trigger_rungs': 2, 'max_rungs': 100,
                            'ref_position': 0.5, 'confirm_seconds': 0.0,
                            'direction': 'favourable'}             # D28's default
    ok = {'trigger_rungs': 1, 'max_rungs': 5, 'confirm_seconds': 0}
    for bad in (dict(ok, trigger_rungs=0), {'trigger_rungs': 1},
                dict(ok, trigger_rungs=1.5), dict(ok, ref_position=1.5),
                dict(ok, snap_home=True), dict(ok, confirm_seconds=-1),
                dict(ok, direction='adverse'), dict(ok, direction=None),
                {'trigger_rungs': 1, 'max_rungs': 5},      # G21: never defaulted
                'yes'):
        try:
            _cfg(slide=bad)
        except ConfigError:
            continue
        raise AssertionError(f'accepted {bad!r}')
    try:
        validate_config({'market_type': 'linear', 'symbol': 'BTCUSDT',
                         'side': 'long', 'strategy': 'martingale',
                         'capital': 100.0, 'leverage': 5, 'base_order_size': 10,
                         'safety_order_size': 10, 'order_size_multiplier': 1.5,
                         'deviation_pct': 0.01, 'deviation_step_multiplier': 1.0,
                         'max_averaging_orders': 3, 'take_profit_avg_pct': 0.01,
                         'slide': dict(SLIDE)})
    except ConfigError as e:
        assert 'slide' in str(e)
    else:
        raise AssertionError('a martingale accepted slide')


# --- D34: the adverse slide, opt-in -----------------------------------------
# `direction: both` adds the adverse edge to D28's ratchet: a long window may
# slide DOWN, a short's UP, by the same trigger, landing and clamp. The new
# far rungs are new lots beyond capital, so the cap must be lifted or raised.

BOTH = dict(SLIDE, direction='both')


def _both(**over):
    over.setdefault('slide', dict(BOTH))
    over.setdefault('max_position_base', 'unbounded')
    return _cfg(**over)


def spec_G24_a_long_slides_down_only_when_asked():
    assert slide_offset(_cfg(), 0, 48000.0) == 0          # D28: the stop's side
    cfg = _both()
    assert slide_offset(cfg, 0, 48500.0) == 0             # 1.5 rungs: not yet
    assert slide_offset(cfg, 0, 48000.0) == -12           # K=2 below the bottom
    # the ref lands at ref_position of the slid window, as on the way up
    assert grid_rungs(cfg, ADAPTER, -12)[10] == 48000.0
    capped = _both(slide=dict(BOTH, max_rungs=5))
    assert slide_offset(capped, 0, 20000.0) == -5         # G19 holds both ways


def spec_G24_a_short_slides_up_only_when_asked():
    short = _cfg(side='short')
    assert slide_offset(short, 0, 72000.0) == 0
    assert slide_offset(_both(side='short'), 0, 72000.0) == 12
    assert slide_offset(_both(side='short'), 0, 48000.0) == -12   # D28 kept


def spec_G24_both_keeps_the_favourable_ratchet_and_only_moves_the_ref_s_way():
    cfg = _both()
    assert slide_offset(cfg, 0, 72000.0) == 12            # D28's slide, unchanged
    down = slide_offset(cfg, 0, 48000.0)
    # inside the slid window nothing moves; the trigger count is the only band
    assert slide_offset(cfg, down, 42000.0) == down
    assert slide_offset(cfg, down, 56000.0) == down
    # back up past the slid top + K: it follows up again, by the same rule
    assert slide_offset(cfg, down, 61000.0) == 1
    # a deeper fall moves it further down, never up
    assert slide_offset(cfg, down, 30000.0) == -30


def spec_G24_direction_both_requires_the_cap_lifted_or_raised():
    try:
        _cfg(slide=dict(BOTH))
    except ConfigError as e:
        assert 'D34' in str(e) and 'unbounded' in str(e), str(e)
    else:
        raise AssertionError('direction both accepted under the default cap')
    assert _both()['slide']['direction'] == 'both'
    assert _both(max_position_base=0.5)['max_position_base'] == 0.5


def _full_home_ladder(cfg):
    from gridgremlin.ladder import rung_notionals
    home = grid_rungs(cfg, ADAPTER)
    return sum(ADAPTER.round_qty(ADAPTER.qty_from_notional(n, p))
               for n, p in zip(rung_notionals(cfg), home))


def spec_G24_sabotage_the_default_cap_stops_an_adverse_slide_part_way():
    """Why the refusal exists: the default cap is the ladder's own size, and
    the old window's lots already fill it. Lifted, every new rung below the
    ref arms; under the default, half of them silently do not."""
    cfg = _both()
    held = _full_home_ladder(cfg)
    new = slide_offset(cfg, 0, 48000.0)

    def entries(c):
        return [o for o in plan_grid(c, ADAPTER, 48000.0, held, 59000.0,
                                     offset=new, held_rungs=list(range(21)))
                if o['side'] == 'Buy']
    lifted = entries(cfg)
    default = dict(cfg)
    default.pop('max_position_base')              # what the refusal prevents
    assert len(lifted) == 10                      # 38000..47000: all of them
    assert 0 < len(entries(default)) < len(lifted)


def _fall(start=60000.0, per_bar=600.0, bars=60):
    """_trend mirrored: every bar pops 1.3 rungs and drops 1.1, net -0.6."""
    out, p = [], start
    for _ in range(bars):
        out.append(_bar(p, p + 1300.0, p - 1100.0, p - per_bar))
        p -= per_bar
    return out


def spec_G24_an_adverse_slide_keeps_trading_a_falling_market():
    bars = _fall()
    kept = backtest(_cfg(max_position_base='unbounded'), ADAPTER, bars,
                    fee_rate=0.0002)
    both = backtest(_both(), ADAPTER, bars, fee_rate=0.0002)
    assert kept['slides'] == 0 and kept['offset'] == 0    # D28 idles below
    assert both['slides'] >= 2 and both['offset'] < 0
    assert both['trips'] > kept['trips'] * 2              # the mirror of G18's
    assert both['net'] > kept['net']                      # sabotage fixture


def spec_G24_an_adverse_slide_buys_beyond_capital_in_the_replay():
    """The commitment D34 names: a straight fall, no bounce. The default
    buys the home ladder's rungs it passes and stops; `both` follows the
    fall and carries more inventory than the WHOLE home ladder."""
    bars = [_bar(60500.0 - 1000 * i, 60600.0 - 1000 * i,
                 59450.0 - 1000 * i, 59500.0 - 1000 * i) for i in range(40)]
    kept = backtest(_cfg(max_position_base='unbounded'), ADAPTER, bars)
    both = backtest(_both(), ADAPTER, bars)
    ladder = _full_home_ladder(_both())
    assert kept['max_held'] <= ladder
    assert both['max_held'] > 2 * ladder
    assert both['entry_fills'] > 2 * kept['entry_fills']


# --- G17/G19: a fixed lattice never slides to a rung at zero (the review) ----

FINE = LinearAdapter({'symbol': 'XUSDT', 'qty_step': 1.0, 'price_tick': 0.0001,
                      'min_qty': 1.0, 'min_notional': 5.0, 'settle_coin': 'USDT'})


def _cheap(**over):
    """A short 1.0..3.0 in 11 rungs: step 0.2, max_rungs 20."""
    row = {'market_type': 'linear', 'symbol': 'XUSDT', 'side': 'short',
           'capital': 1000.0, 'leverage': 1, 'upper': 3.0, 'lower': 1.0,
           'rungs': 11, 'spacing_type': 'fixed',
           'slide': dict(SLIDE, max_rungs=20)}
    row.update(over)
    return validate_config(row)


def spec_G17_review_a_fixed_lattice_floors_its_slide_a_step_above_zero():
    """The fixed lattice extends below `lower` by its step, and the clamp was
    only +-max_rungs: at 0.55 the short slid to -0.4..1.6, and the 0.0 rung
    divided by zero in position_cap on every cycle. The window's floor keeps
    every rung it rests — and the rung below it, where a short's bottom lot
    covers — at least a step above zero."""
    cfg = _cheap()
    new = slide_offset(cfg, 0, 0.55)
    assert new == -3, new
    rungs = grid_rungs(cfg, FINE, new)
    assert abs(rungs[0] - 0.4) < 1e-9 and lattice_price(cfg, new - 1) > 0.19
    for ref in (0.55, 0.3, 0.01):
        assert slide_offset(cfg, new, ref) == new          # floored, held
        plan_grid(cfg, FINE, ref, offset=new)              # never raises
    held = plan_grid(cfg, FINE, 0.3, held_base=-1000.0, basis=0.4,
                     offset=new, held_rungs=[new])
    assert all(o['price'] > 0 for o in held)
    # a geometric lattice never reaches zero: no floor, the clamp alone
    geo = _cheap(spacing_type='percent')
    assert slide_offset(geo, 0, 0.05) < -3


def spec_G17_review_sabotage_the_clamp_alone_lands_a_rung_on_zero():
    """Why the floor exists: at the offset the clamp alone allows, a rung is
    priced 0.0 and the plan raises on every cycle — the bot frozen."""
    cfg = _cheap()
    alone = max(int(math.ceil(lattice_index(cfg, 0.55))) - 5, -20)
    assert alone == -7
    assert min(abs(p) for p in grid_rungs(cfg, FINE, alone)) < 1e-9
    try:
        plan_grid(cfg, FINE, 0.55, offset=alone)
    except ZeroDivisionError:
        return
    raise AssertionError('a rung at 0.0 planned without raising')


def spec_X8_review_a_rungs_beyond_stop_at_or_below_zero_is_refused():
    """A long's `rungs_beyond` stop on a fixed lattice can sit at or below
    zero, and never fire: refused by name. Under G24 the stop follows the
    window down, so the slide's floor stops the window while the stop is
    still a step above zero. A short's sits above the top; a geometric
    lattice never reaches zero."""
    from gridgremlin.ladder import stop_level_for

    def build(**over):
        return _cheap(side='long', **over)
    try:
        build(stop={'watch': 'mark_price', 'rungs_beyond': 5})   # 1.0 - 1.0 = 0
    except ConfigError as e:
        assert 'rungs_beyond' in str(e) and 'zero' in str(e), e
    else:
        raise AssertionError('a stop at 0.0 was accepted')
    # direction both: the floor alone would take the window to 0.4 and the
    # stop three rungs below it to -0.2; it stops at 0.8, the stop at 0.2
    both = build(slide=dict(BOTH, max_rungs=20), max_position_base='unbounded',
                 stop={'watch': 'mark_price', 'rungs_beyond': 3})
    low = slide_offset(both, 0, 0.05)
    assert low == -1, low
    assert abs(stop_level_for(both, low) - 0.2) < 1e-9
    build(stop={'watch': 'mark_price', 'rungs_beyond': 4})        # 0.2: fine
    _cheap(stop={'watch': 'mark_price', 'rungs_beyond': 30})      # a short's
    build(spacing_type='percent', stop={'watch': 'mark_price', 'rungs_beyond': 30})
