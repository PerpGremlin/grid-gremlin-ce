# Specs for SPEC M1, M2, M5's config half, M8. Golden fixtures from the field
# study (the 3Commas conventions, DECISIONS D11).

from gridgremlin.adapters import LinearAdapter
from gridgremlin.config import ConfigError, validate_config
from gridgremlin.ladder import martingale_schedule, plan_martingale, plan_grid

ADAPTER = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001,
                         'price_tick': 0.1, 'min_qty': 0.001,
                         'min_notional': 5.0, 'settle_coin': 'USDT'})


def _cfg(**over):
    row = {'strategy': 'martingale', 'market_type': 'linear',
           'symbol': 'BTCUSDT', 'side': 'long', 'capital': 1000.0,
           'leverage': 10, 'base_order_size': 1000.0,
           'safety_order_size': 1000.0, 'order_size_multiplier': 2.0,
           'deviation_pct': 0.01, 'deviation_step_multiplier': 2.0,
           'max_averaging_orders': 3, 'take_profit_avg_pct': 0.01}
    row.update(over)
    return validate_config(row)


def _refused(row, *fragments):
    try:
        validate_config(row)
    except ConfigError as e:
        for frag in fragments:
            assert frag in str(e), f'expected {frag!r} in {str(e)!r}'
        return str(e)
    raise AssertionError(f'accepted, expected refusal: {fragments}')


# --- M2: the 3Commas schedule, golden ----------------------------------------

def spec_M2_size_progression_is_multiplier_of_previous():
    sched = martingale_schedule(_cfg())
    assert [n for n, _ in sched] == [1000.0, 1000.0, 2000.0, 4000.0]


def spec_M2_deviation_steps_compound():
    # the canonical 3Commas example: 1% deviation, step scale 2 -> -1%, -3%, -7%
    sched = martingale_schedule(_cfg())
    assert [round(d, 6) for _, d in sched] == [0.0, 0.01, 0.03, 0.07]


def spec_M2_flat_multipliers_give_equal_sizes_and_spacing():
    sched = martingale_schedule(_cfg(order_size_multiplier=1.0,
                                     deviation_step_multiplier=1.0))
    assert [n for n, _ in sched] == [1000.0] * 4
    assert [round(d, 6) for _, d in sched] == [0.0, 0.01, 0.02, 0.03]


def spec_M2_series_total_refusal_states_the_numbers():
    msg = _refused({'strategy': 'martingale', 'market_type': 'linear',
                    'symbol': 'BTCUSDT', 'side': 'long', 'capital': 1000.0,
                    'leverage': 10, 'base_order_size': 1000.0,
                    'safety_order_size': 1000.0, 'order_size_multiplier': 2.0,
                    'deviation_pct': 0.01, 'max_averaging_orders': 4,
                    'take_profit_avg_pct': 0.01},
                   '16000', '1600', 'capital is 1000')
    assert 'max_averaging_orders' in msg          # the message says what to lower


def spec_M2_vocabulary_bounds():
    _refused({**_row_dict(), 'order_size_multiplier': 0.5})   # < 1 shrinks: refused
    _refused({**_row_dict(), 'max_averaging_orders': 0})
    _refused({**_row_dict(), 'max_averaging_orders': 2.5})
    _refused({**_row_dict(), 'deviation_pct': 0})


def _row_dict():
    return {'strategy': 'martingale', 'market_type': 'linear',
            'symbol': 'BTCUSDT', 'side': 'long', 'capital': 1000.0,
            'leverage': 10, 'base_order_size': 100.0,
            'safety_order_size': 100.0, 'deviation_pct': 0.01,
            'max_averaging_orders': 3, 'take_profit_avg_pct': 0.01}


# --- M8: no range bounds -----------------------------------------------------

def spec_M8_range_bounds_are_not_martingale_keys():
    # pins: M7 M9 (no floor/cap/damping keys; no signal keys — absence is derived)
    _refused({**_row_dict(), 'lower': 50000.0}, 'unknown key')
    _refused({**_row_dict(), 'upper': 70000.0}, 'unknown key')
    for key in ('min_position_base', 'max_position_base', 'damping', 'signal',
                'start_signal'):
        _refused({**_row_dict(), key: 1}, 'unknown key')
    _refused({**_row_dict(), 'no_trade_pct': 1}, 'retired')      # B9, by name


def spec_M8_depth_derives_from_the_schedule():
    sched = martingale_schedule(_cfg())
    assert max(d for _, d in sched) == 0.07       # 7% deep at 3 orders, typed nowhere


# --- M5's config half --------------------------------------------------------

def spec_M5_repeat_is_a_coerced_flag():
    assert _cfg(repeat=1)['repeat'] is True
    assert _cfg()['repeat'] is False


def spec_M5_absolute_take_profit_stays_retired():
    _refused({**_row_dict(), 'take_profit_price': 60000.0}, 'retired')


# --- M1: the same maths, demonstrably ----------------------------------------

def spec_M1_flat_martingale_reproduces_the_grid_entry_ladder():
    # multiplier 1 + arithmetic deviations == a grid's entry ladder over the
    # same prices, through the same adapter maths — one implementation (M1).
    grid_cfg = validate_config({'market_type': 'linear', 'symbol': 'BTCUSDT',
                                'side': 'long', 'capital': 1000.0,
                                'leverage': 10, 'upper': 70000.0,
                                'lower': 50000.0, 'rungs': 21,
                                'spacing_type': 'fixed'})
    grid_buys = {(o['price'], o['qty'])
                 for o in plan_grid(grid_cfg, ADAPTER, 60000.0)}
    per_rung = 10000.0 / 21
    mart_cfg = _cfg(base_order_size=per_rung, safety_order_size=per_rung,
                    order_size_multiplier=1.0, deviation_pct=1.0 / 60.0,
                    deviation_step_multiplier=1.0, max_averaging_orders=9)
    mart_buys = {(o['price'], o['qty'])
                 for o in plan_martingale(mart_cfg, ADAPTER, 60000.0, 60000.0)}
    assert mart_buys and mart_buys <= grid_buys   # same prices, same qtys


def spec_M1_cumulative_prefix_suppression():
    cfg = _cfg()
    sched = martingale_schedule(cfg)
    base_qty = ADAPTER.round_qty(sched[0][0] / 60000.0)
    s1_qty = ADAPTER.round_qty(sched[1][0] / (60000.0 * 0.99))
    full = plan_martingale(cfg, ADAPTER, 60000.0, 60000.0)
    assert [o['rung'] for o in full] == [1, 2, 3]
    held = plan_martingale(cfg, ADAPTER, 60000.0, 60000.0,
                           held_base=base_qty + s1_qty)
    assert [o['rung'] for o in held] == [2, 3]     # base + s1 filled -> s1 gone


def spec_M24_a_filled_rung_stays_suppressed_whatever_is_held():
    """A tranche exit shrinks the holding under the prefix: the rung that
    filled this round is named, and named rungs are never re-placed."""
    cfg = _cfg()
    sched = martingale_schedule(cfg)
    base_qty = ADAPTER.round_qty(sched[0][0] / 60000.0)
    back_to_base = plan_martingale(cfg, ADAPTER, 60000.0, 60000.0,
                                   held_base=base_qty)
    assert [o['rung'] for o in back_to_base] == [1, 2, 3]   # prefix alone
    named = plan_martingale(cfg, ADAPTER, 60000.0, 60000.0,
                            held_base=base_qty, filled_rungs=frozenset({1}))
    assert [o['rung'] for o in named] == [2, 3]
    deeper = plan_martingale(cfg, ADAPTER, 60000.0, 60000.0,
                             held_base=base_qty, filled_rungs={1, 2})
    assert [o['rung'] for o in deeper] == [3]


def spec_G13_martingale_orders_stay_on_the_entry_side():
    # ref below the first safety order: that order would be a marketable buy
    cfg = _cfg()
    orders = plan_martingale(cfg, ADAPTER, 60000.0, 58500.0)
    prices = [o['price'] for o in orders]
    assert 59400.0 not in prices                   # s1 (-1%) skipped: >= ref
    assert prices and all(p < 58500.0 for p in prices)


def spec_C5_placeable_defers_for_martingale():
    from gridgremlin.config import check_placeable
    assert check_placeable(_cfg(), ADAPTER)        # no refusal without a price


# --- M16's config half (D37) -------------------------------------------------

def spec_M16_market_stays_the_default_and_maker_is_the_opt_in():
    assert _cfg()['start_order_type'] == 'market'
    cfg = _cfg(start_order_type='maker')
    assert cfg['start_order_requote_seconds'] == 40.0    # 3Commas' interval
    assert cfg['start_order_expire_seconds'] is None     # chase until filled


def spec_M16_3commas_limit_is_refused_by_name():
    _refused({**_row_dict(), 'start_order_type': 'limit'}, 'maker', 'D37',
             'taker')


def spec_M16_entry_timers_need_the_maker_entry():
    _refused({**_row_dict(), 'start_order_requote_seconds': 30}, 'D37')
    _refused({**_row_dict(), 'start_order_expire_seconds': 600}, 'D37')
    _refused({**_row_dict(), 'start_order_type': 'maker',
              'start_order_requote_seconds': 0})


# --- X9-X11, D41: the stop's opt-ins and the round limit (config half) -------

_PCT_STOP = {'watch': 'mark_price', 'from_base_pct': 0.10}


def spec_X9_the_timeout_is_the_engines_own_watch_only():
    """D33's "Time" mode. A venue-hosted stop fires on the first touch, so
    a timeout beside it would be a promise the engine cannot keep."""
    cfg = _cfg(stop={'watch': 'mark_price', 'level': 50000,
                     'confirm_seconds': 30})
    assert cfg['stop']['confirm_seconds'] == 30.0
    base = {'strategy': 'martingale', 'market_type': 'linear',
            'symbol': 'BTCUSDT', 'side': 'long', 'capital': 1000.0,
            'leverage': 10, 'base_order_size': 1000.0,
            'safety_order_size': 1000.0, 'max_averaging_orders': 3,
            'deviation_pct': 0.01, 'take_profit_avg_pct': 0.01}
    _refused(dict(base, stop={'watch': 'account_equity', 'level': 500,
                              'confirm_seconds': 30}),
             'confirm_seconds', 'watch: mark_price')
    _refused(dict(base, stop={'watch': 'mark_price', 'level': 50000,
                              'server_side': True, 'confirm_seconds': 30}),
             'server_side', 'first touch')
    _refused(dict(base, stop={'watch': 'mark_price', 'level': 50000,
                              'confirm_seconds': 0}), 'confirm_seconds')
    grid = validate_config({
        'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
        'capital': 1000, 'lower': 50000, 'upper': 60000, 'rungs': 11,
        'stop': {'watch': 'mark_price', 'level': 48000,
                 'confirm_seconds': 60}})
    assert grid['stop']['confirm_seconds'] == 60.0     # a grid's stop too


def spec_X2_a_plain_stop_validates_exactly_as_before():
    """The opt-ins are returned only when asked for."""
    assert _cfg(stop={'watch': 'mark_price', 'level': 50000})['stop'] == {
        'watch': 'mark_price', 'level': 50000.0, 'server_side': False}


def spec_X10_the_stop_as_a_percent_from_the_base_order():
    """3Commas' form of the level, and their rule: beyond the last safety
    order. The fixture's ladder reaches 1% + 2% + 4% = 7%."""
    cfg = _cfg(stop=dict(_PCT_STOP))
    assert cfg['stop'] == {'watch': 'mark_price', 'level': None,
                           'server_side': False, 'from_base_pct': 0.10}
    row = {'strategy': 'martingale', 'market_type': 'linear',
           'symbol': 'BTCUSDT', 'side': 'long', 'capital': 1000.0,
           'leverage': 10, 'base_order_size': 1000.0,
           'safety_order_size': 1000.0, 'order_size_multiplier': 2.0,
           'deviation_pct': 0.01, 'deviation_step_multiplier': 2.0,
           'max_averaging_orders': 3, 'take_profit_avg_pct': 0.01}
    _refused(dict(row, stop={'watch': 'mark_price', 'from_base_pct': 0.07}),
             'inside the safety ladder', 'beyond the last safety order')
    _refused(dict(row, stop=dict(_PCT_STOP, level=50000)),
             'two answers to one question')
    _refused(dict(row, stop=dict(_PCT_STOP, server_side=True)),
             'server_side')
    _refused(dict(row, stop={'watch': 'account_equity',
                             'from_base_pct': 0.1}), 'watch: mark_price')
    _refused({'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
              'capital': 1000, 'lower': 50000, 'upper': 60000, 'rungs': 11,
              'stop': dict(_PCT_STOP)}, 'a grid has no base order')


def spec_X11_ending_the_round_is_an_opt_in_with_its_conditions():
    """D42. The default stays D1's off button; 'end_round' needs a level
    that moves with the round, and a next round to go to."""
    assert 'action' not in _cfg(stop={'watch': 'mark_price',
                                      'level': 50000})['stop']
    cfg = _cfg(repeat=True, stop=dict(_PCT_STOP, action='end_round'),
               stop_cooldown_seconds=600)
    assert cfg['stop']['action'] == 'end_round'
    assert cfg['stop_cooldown_seconds'] == 600.0
    row = {'strategy': 'martingale', 'market_type': 'linear',
           'symbol': 'BTCUSDT', 'side': 'long', 'capital': 1000.0,
           'leverage': 10, 'base_order_size': 1000.0,
           'safety_order_size': 1000.0, 'order_size_multiplier': 2.0,
           'deviation_pct': 0.01, 'deviation_step_multiplier': 2.0,
           'max_averaging_orders': 3, 'take_profit_avg_pct': 0.01}
    _refused(dict(row, repeat=True,
                  stop={'watch': 'mark_price', 'level': 50000,
                        'action': 'end_round'}),
             "needs 'from_base_pct'", 'fire at once or never')
    _refused(dict(row, stop=dict(_PCT_STOP, action='end_round')),
             "without 'repeat'")
    _refused(dict(row, repeat=True, stop=dict(_PCT_STOP, action='pause')),
             'action')
    _refused(dict(row, repeat=True, stop=dict(_PCT_STOP),
                  stop_cooldown_seconds=600),
             "needs stop.action: 'end_round'")


def spec_D41_the_round_limit_is_counted_from_a_stated_moment():
    cfg = _cfg(repeat=True, max_rounds=5,
               max_rounds_since='2026-10-02T14:30:00Z')
    assert cfg['max_rounds'] == 5
    assert cfg['max_rounds_since_ms'] == 1790951400000
    assert _cfg(repeat=True, max_rounds=1,                 # no zone = UTC
                max_rounds_since='2026-10-02T14:30:00')[
        'max_rounds_since_ms'] == 1790951400000
    assert 'max_rounds' not in _cfg(repeat=True)           # opt-in
    row = {'strategy': 'martingale', 'market_type': 'linear',
           'symbol': 'BTCUSDT', 'side': 'long', 'capital': 1000.0,
           'leverage': 10, 'base_order_size': 1000.0,
           'safety_order_size': 1000.0, 'max_averaging_orders': 3,
           'deviation_pct': 0.01, 'take_profit_avg_pct': 0.01,
           'repeat': True}
    _refused(dict(row, max_rounds=5), 'travel together', 'the panel stamps')
    _refused(dict(row, max_rounds_since='2026-10-02T14:30:00Z'),
             'travel together')
    _refused(dict(row, max_rounds=5, max_rounds_since='yesterday'),
             "a moment like '2026-10-02T14:30:00Z'")
    _refused(dict(row, max_rounds=0,
                  max_rounds_since='2026-10-02T14:30:00Z'), 'max_rounds')
    _refused(dict(row, repeat=False, max_rounds=5,
                  max_rounds_since='2026-10-02T14:30:00Z'),
             "without 'repeat'")
