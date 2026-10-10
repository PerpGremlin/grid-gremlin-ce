# Specs for SPEC T3 (trade-through, funding, honesty) and T4 (the v2 diff).

import json
import subprocess
from pathlib import Path

from gridgremlin.adapters import LinearAdapter
from gridgremlin.backtest import backtest
from gridgremlin.config import validate_config
from gridgremlin.ladder import plan_grid

ADAPTER = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001,
                         'price_tick': 0.1, 'min_qty': 0.001,
                         'min_notional': 5.0, 'settle_coin': 'USDT'})
V2_COMMIT = '79c7da3'      # the dissected reference — T4 is meaningless elsewhere


def _v2root():
    """T4 needs the v2 checkout AT THE REFERENCE COMMIT. Parity was proven on
    the reference machine; on boxes without that checkout (the VPS carries the
    older live commit) T4 stands down loudly instead of failing forever."""
    import subprocess as sp
    for cand in (Path.home() / 'dev/projects/grid-gremlin-v2',
                 Path('/opt/example/grid-gremlin-v2')):
        if not cand.exists():
            continue
        head = sp.run(['git', '-C', str(cand), 'rev-parse', '--short', 'HEAD'],
                      capture_output=True, text=True).stdout.strip()
        if head.startswith(V2_COMMIT):
            return cand
    print(f'  T4: no v2 checkout at {V2_COMMIT} on this machine — parity was '
          'proven at the reference; standing down')
    return None


V2 = _v2root()


def _cfg(**over):
    row = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
           'capital': 1000.0, 'leverage': 10, 'upper': 70000.0,
           'lower': 50000.0, 'rungs': 21, 'spacing_type': 'fixed'}
    row.update(over)
    return validate_config(row)


def _bar(o, h, l, c):
    return {'o': o, 'h': h, 'l': l, 'c': c}


# --- T3: trade-through, never touch ------------------------------------------

def spec_T3_touch_is_not_a_fill():
    touched = backtest(_cfg(), ADAPTER, [_bar(60000, 60500, 59000.0, 60000)])
    assert touched.get('entry_fills') == 0        # low == rung: NO fill
    through = backtest(_cfg(), ADAPTER, [_bar(60000, 60500, 58995.0, 60000)])
    assert through['entry_fills'] == 1            # low < rung: fill


def spec_T3_a_round_trip_earns_spacing_minus_fees():
    bars = [_bar(60000, 60050, 58995.0, 59200),   # 59k entry fills
            _bar(59500, 60050.0, 59400, 60000)]   # 60k exit fills (>59,059 floor)
    r = backtest(_cfg(), ADAPTER, bars, fee_rate=0.0002)
    assert r['trips'] == 1 and r['held'] == 0.0 and r['basis'] is None
    assert abs(r['grid_profit'] - 1000.0 * 0.008) < 1e-9   # rung qty, not lot
    assert 0 < r['fees'] < r['grid_profit']
    assert abs(r['net'] - (r['grid_profit'] - r['fees'])) < 1e-9


def spec_T3_funding_bleeds_a_held_position():
    bars = [_bar(60000, 60050, 58995.0, 59000)] + [
        _bar(59000, 59050, 58999.0, 59000)] * 5   # hold 5 quiet bars
    r = backtest(_cfg(), ADAPTER, bars, funding_rate_hourly=1e-4)
    assert r['funding'] > 0                       # a long pays positive funding
    assert abs(r['funding'] - sum(0.007 * 59000 * 1e-4 for _ in range(5))
               - 0.007 * 59000 * 1e-4) < 1.0


def spec_T3_the_honesty_case_grid_profit_up_total_down():
    # the v1 backtester booked +54 on a crash that cost -151. Trade-through +
    # mark-to-market: a crash shows small realized profit and a NEGATIVE total.
    crash = [_bar(60000, 60050, 58995.0, 59000),
             _bar(59000, 59050, 56995.0, 57000),
             _bar(57000, 57050, 54995.0, 55000),
             _bar(55000, 55050, 52995.0, 53000)]
    r = backtest(_cfg(), ADAPTER, crash)
    assert r['grid_profit'] >= 0
    assert r['total'] < 0                         # the truth v1 hid
    assert r['max_drawdown'] > 0


def spec_T3_replay_uses_the_real_plan():
    import inspect
    import gridgremlin.backtest as bt
    src = inspect.getsource(bt)
    assert 'plan_grid' in src                     # T3: no second engine
    assert 'def plan' not in src


# --- T4: v3 diffed against v2 on shared fixtures -----------------------------

V2_SCRIPT = r'''
import json, sys
sys.path.insert(0, {v2root!r})
from gridgremlin.config import validate_config
from gridgremlin.exchange.adapters import LinearAdapter
from gridgremlin.strategy.grid import plan_grid
fix = json.loads(sys.argv[1])
cfg = validate_config(fix['row'])
adapter = LinearAdapter(fix['spec'])
truth = {{'ref': fix['ref'], 'mark': fix['ref'], 'orders': [],
          'positions': {{int(k): v for k, v in fix['positions'].items()}}}}
orders = plan_grid(cfg, truth, adapter, 'diffbot')
print(json.dumps(sorted([o['side'], o['price'], o['qty'], bool(o['reduce_only'])]
                        for o in orders)))
'''


def _v2_plan(row, spec, ref, positions):
    fix = json.dumps({'row': row, 'spec': spec, 'ref': ref,
                      'positions': positions})
    out = subprocess.run(
        ['python3', '-c', V2_SCRIPT.format(v2root=str(V2)), fix],
        capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, f'v2 harness failed: {out.stderr[-500:]}'
    return sorted(tuple(o) for o in json.loads(out.stdout))


def _v3_plan(ref, held=0.0, basis=None, qty_step=0.001):
    spec = {'symbol': 'BTCUSDT', 'qty_step': qty_step, 'price_tick': 0.1,
            'min_qty': qty_step, 'min_notional': 5.0, 'settle_coin': 'USDT'}
    adapter = LinearAdapter(spec)
    # T4 is parity with v2, which floored exits at the average (G6); under
    # D35 that floor is the opt-in, so parity is measured in that mode
    orders = plan_grid(_cfg(exit_floor='basis'), adapter, ref, held, basis)
    return sorted((o['side'], o['price'], o['qty'], bool(o['reduce_only']))
                  for o in orders)


def _v2_row():
    return {'category': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
            'capital': 1000.0, 'leverage': 10, 'upper': 70000.0,
            'lower': 50000.0, 'rungs': 21, 'spacing_type': 'fixed'}


def _v2_spec(qty_step=0.001):
    return {'symbol': 'BTCUSDT', 'qty_step': qty_step, 'price_tick': 0.1,
            'min_qty': qty_step, 'min_notional': 5.0, 'settle_coin': 'USDT'}


def spec_T4_flat_plans_match_v2_exactly():
    if V2 is None:
        return
    v2 = _v2_plan(_v2_row(), _v2_spec(), 60000.0, {})
    assert _v3_plan(60000.0) == v2


def spec_T4_adopt_in_profit_matches_v2():
    if V2 is None:
        return
    positions = {1: {'position_idx': 1, 'side': 'Buy', 'size': 0.021,
                     'avg_entry': 55000.0}}
    v2 = _v2_plan(_v2_row(), _v2_spec(), 60000.0, positions)
    assert _v3_plan(60000.0, held=0.021, basis=55000.0) == v2


def spec_T4_adopt_underwater_matches_v2():
    if V2 is None:
        return
    positions = {1: {'position_idx': 1, 'side': 'Buy', 'size': 0.021,
                     'avg_entry': 65000.0}}
    v2 = _v2_plan(_v2_row(), _v2_spec(), 60000.0, positions)
    assert _v3_plan(60000.0, held=0.021, basis=65000.0) == v2


def spec_T4_the_lot_anchor_divergence_is_intended_and_cited():
    if V2 is None:
        return
    # D5: v2 re-prices the lot at the nearest exit rung when holding; v3 uses
    # the split ref always. At a fine qty step the units differ — this is the
    # one intended divergence, decided 2026-08-04.
    step = 0.0001
    positions = {1: {'position_idx': 1, 'side': 'Buy', 'size': 0.0237,
                     'avg_entry': 55000.0}}
    v2 = _v2_plan(_v2_row(), _v2_spec(step), 60000.0, positions)
    v3 = _v3_plan(60000.0, held=0.0237, basis=55000.0, qty_step=step)
    v2_sells = [(p, q) for s, p, q, ro in v2 if s == 'Sell']
    v3_sells = [(p, q) for s, p, q, ro in v3 if s == 'Sell']
    assert {p for p, _ in v2_sells} == {p for p, _ in v3_sells}   # same rungs
    assert v2_sells != v3_sells                                   # D5: unit moved
    v2_lot = min(q for _, q in v2_sells)
    v3_lot = min(q for _, q in v3_sells)
    assert v2_lot != v3_lot and abs(v2_lot - v3_lot) <= 2 * step


def spec_T3_kline_rows_reverse_to_oldest_first_bars():
    from gridgremlin.exchange.bybit.klines import parse_kline_rows
    rows = [['2000', '61', '62', '60', '61.5', '9', '9'],     # newest first
            ['1000', '60', '61', '59', '60.5', '9', '9']]
    bars = parse_kline_rows(rows)
    assert [b['t'] for b in bars] == [1000, 2000]
    assert bars[0] == {'t': 1000, 'o': 60.0, 'h': 61.0, 'l': 59.0, 'c': 60.5}


def spec_T3_inventory_is_kept_in_integer_steps_not_floats():
    """float subtract-then-floor dropped a whole qty-step per iteration —
    the exit ladder was fixed for this in slice 3; the backtester was not
    (audit 2026-08-06). Inventory must land exactly on the step grid."""
    from gridgremlin.adapters import LinearAdapter
    A = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.1,
                       'price_tick': 0.1, 'min_qty': 0.1,
                       'min_notional': None, 'settle_coin': 'USDT'})
    assert A.round_qty(0.3 - 0.1) == 0.1        # the hazard, still true
    cfg = _cfg(lower=90.0, upper=110.0, rungs=5, capital=300.0, leverage=1,
               spacing_type='fixed', place_within_pct=0.2)   # T6: both rungs resting
    r = backtest(cfg, A, [{'o': 100.0, 'h': 100.2, 'l': 89.0, 'c': 91.0},
                          {'o': 91.0, 'h': 92.0, 'l': 88.0, 'c': 90.0}])
    assert r['entry_fills'] >= 2                # a deep dip, many rungs
    steps = r['held'] / 0.1
    assert abs(steps - round(steps)) < 1e-9     # exactly on the grid
    assert r['held'] > 0                        # and nothing evaporated


# --- T8: the step optimiser is the rehearsal, swept (D50) ---------------------

def _saw(lo, hi, legs, per_leg):
    """Bars that walk lo -> hi -> lo ... in straight legs: every rung inside
    the range is traded through on each leg, so finer grids trip more."""
    bars, t = [], 0
    for leg in range(legs):
        a, b = (lo, hi) if leg % 2 == 0 else (hi, lo)
        for i in range(per_leg):
            o = a + (b - a) * i / per_leg
            c = a + (b - a) * (i + 1) / per_leg
            bars.append({'t': t, 'o': o, 'h': max(o, c), 'l': min(o, c),
                         'c': c})
            t += 300_000
    return bars


def spec_T8_the_sweep_returns_every_candidate_names_the_best_and_the_plateau():
    from gridgremlin.backtest_cli import sweep_rungs
    raw = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
           'capital': 1000.0, 'leverage': 10, 'upper': 70000.0,
           'lower': 50000.0, 'rungs': 21, 'spacing_type': 'fixed'}
    bars = _saw(50000.0, 70000.0, 6, 40)
    out = sweep_rungs(raw, bars, ADAPTER, fee=0.0002, bar_minutes=5,
                      candidates=range(5, 42, 4))
    rows = out['rows']
    assert [r['rungs'] for r in rows] == sorted(r['rungs'] for r in rows)
    assert all(set(r) >= {'rungs', 'gap_pct', 'net', 'trips', 'fees',
                          'fee_share', 'max_drawdown'} for r in rows)
    scored = [r for r in rows if 'net' in r]
    assert out['best'] == max(scored, key=lambda r: r['net'])['rungs']
    lo, hi = out['plateau']
    assert lo <= out['best'] <= hi
    top = max(r['net'] for r in scored)
    assert all(r['net'] >= 0.95 * top for r in scored if lo <= r['rungs'] <= hi
               and r['rungs'] in (lo, hi))
    # the best was refined by 2 on each side when inside the sweep
    assert any(r['rungs'] in (out['best'] - 2, out['best'] + 2) for r in rows)
    assert out['score'] == 'net' and out['bars'] == len(bars)


def spec_T8_a_gap_inside_the_fee_is_skipped_by_name_not_run():
    from gridgremlin.backtest_cli import sweep_rungs
    raw = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
           'capital': 1000.0, 'leverage': 10, 'upper': 51000.0,
           'lower': 50000.0, 'rungs': 11, 'spacing_type': 'fixed'}
    out = sweep_rungs(raw, _saw(50000.0, 51000.0, 2, 20), ADAPTER,
                      fee=0.002, candidates=[3, 5, 11, 21])    # 0.4% round trip
    by = {r['rungs']: r for r in out['rows']}
    assert 'skipped' in by[11] and 'G16' in by[11]['skipped'] and 'net' not in by[11]
    assert 'skipped' in by[21]
    assert 'net' in by[3] and 'net' in by[5]
    none = sweep_rungs(raw, _saw(50000.0, 51000.0, 2, 20), ADAPTER,
                       fee=0.002, candidates=[11, 21])
    assert none['best'] is None and none['plateau'] is None


def spec_T8_a_buy_the_dips_bot_has_no_step_to_find():
    from gridgremlin.backtest_cli import run_draft
    dca = json.dumps({'market_type': 'linear', 'symbol': 'BTCUSDT',
                      'side': 'long', 'strategy': 'martingale',
                      'capital': 1000, 'leverage': 5, 'base_order_size': 50,
                      'safety_order_size': 50, 'deviation_pct': 0.01,
                      'max_averaging_orders': 2, 'take_profit_avg_pct': 0.01})
    out = run_draft(dca, 7, 5, 0.0002, optimize=True)
    assert 'refused' in out and 'rungs' in out['refused']


def spec_T8_what_is_written_for_one_rung_count_is_set_aside_and_said():
    from gridgremlin.backtest_cli import sweep_rungs
    raw = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
           'capital': 1000.0, 'leverage': 10, 'upper': 70000.0,
           'lower': 50000.0, 'rungs': 5, 'spacing_type': 'fixed',
           'rung_sizing': 'weighted', 'rung_weights': [2, 1.5, 1, 1.5, 2],
           '_note': 'notes never ride'}
    out = sweep_rungs(raw, _saw(50000.0, 70000.0, 2, 20), ADAPTER,
                      candidates=[5, 9])
    assert out['dropped'] == ['rung_weights', 'rung_sizing']
    assert all('net' in r for r in out['rows'])          # both ran, equal-sized


# --- T3: Hyperliquid candles, parsed like Bybit's ----------------------------

def spec_T3_hl_candles_replay_oldest_first_one_per_open():
    from gridgremlin.exchange.hyperliquid.klines import (interval_for,
                                                        parse_candles)
    rows = [{'t': 2000, 'o': '2', 'h': '3', 'l': '1', 'c': '2.5'},
            {'t': 1000, 'o': '1', 'h': '2', 'l': '0.5', 'c': '1.5'},
            {'t': 2000, 'o': '2', 'h': '3', 'l': '1', 'c': '2.5'}]   # a page seam
    bars = parse_candles(rows)
    assert [b['t'] for b in bars] == [1000, 2000]
    assert bars[0] == {'t': 1000, 'o': 1.0, 'h': 2.0, 'l': 0.5, 'c': 1.5}
    assert interval_for(5) == '5m' and interval_for(60) == '1h'
    try:
        interval_for(7)
        assert False
    except ValueError as e:
        assert '7-minute' in str(e) and '5' in str(e)


def spec_T3_the_draft_door_knows_both_venues_and_names_the_rest():
    from gridgremlin.backtest_cli import draft_guards
    hl = {'venue': 'hyperliquid', 'market_type': 'linear', 'strategy': 'grid'}
    assert draft_guards(hl) is None
    assert draft_guards(dict(hl, venue='bybit')) is None
    why = draft_guards(dict(hl, venue='nowhere'))
    assert 'nowhere' in why and 'hyperliquid' in why and 'bybit' in why
    assert draft_guards(dict(hl, venue='bybit', market_type='inverse')) is None   # A4: its own maths now


def spec_T8_a_level_under_the_venues_minimum_is_skipped_by_name():
    from gridgremlin.backtest_cli import sweep_rungs
    raw = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
           'capital': 1000.0, 'leverage': 1, 'upper': 70000.0,
           'lower': 50000.0, 'rungs': 5, 'spacing_type': 'fixed'}
    out = sweep_rungs(raw, _saw(50000.0, 70000.0, 2, 20), ADAPTER,
                      candidates=[3, 41])   # 500 a level vs 25: 25 at 70k
    by = {r['rungs']: r for r in out['rows']}     # rounds to no lot at all
    assert 'net' in by[3]
    assert 'skipped' in by[41] and 'minimum' in by[41]['skipped']


# --- T9: two windows, out of sample, the range visited ----------------------

def spec_T9_the_sweep_is_read_on_two_windows_and_tested_out_of_sample():
    from gridgremlin.backtest_cli import sweep_windows, visited_pct
    raw = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
           'capital': 1000.0, 'leverage': 10, 'upper': 70000.0,
           'lower': 50000.0, 'rungs': 21, 'spacing_type': 'fixed'}
    bars = _saw(50000.0, 70000.0, 4, 20)              # 80 bars, two halves
    said = []
    out = sweep_windows(raw, bars, ADAPTER,
                        progress=lambda t, f=None: said.append(t))
    assert set(out['windows']) == {'14d', '7d', 'older7d'}
    for w in out['windows'].values():
        assert w['best'] is not None and w['rows']
    assert out['visited'] == {'7d': 100.0, '14d': 100.0}   # the saw stays in
    oos = out['oos']
    assert oos['fit_rungs'] == out['windows']['older7d']['best']
    assert oos['newer_best'] == out['windows']['7d']['best']
    assert oos['fit_net_newer'] is not None and oos['holds'] in (True, False)
    assert oos['fit_net_newer'] <= oos['newer_best_net'] + 1e-9   # by definition
    assert any(s.startswith('window older7d: replay') for s in said)
    assert any('older week' in s for s in said)
    outside = _saw(80000.0, 90000.0, 2, 10)
    assert visited_pct(outside, 50000.0, 70000.0) == 0.0
    assert visited_pct([], 1, 2) is None


def spec_T3a_an_inverse_row_rehearses_in_the_adapters_own_maths_instead_of_being_refused():
    """The owner pressed rehearse on the inverse ETH long (2026-10-08) and
    the gate said 'linear-only … confident nonsense'. The backtester asks
    the adapter now: fees on the contracts, the basis harmonic, the P&L in
    the coin stated in USD."""
    from gridgremlin.adapters import InverseAdapter
    from gridgremlin.backtest_cli import draft_guards
    inv = InverseAdapter({'symbol': 'BTCUSD', 'qty_step': 1, 'price_tick': 0.5, 'min_qty': 1,
                          'min_notional': None, 'settle_coin': 'BTC'})
    cfg = validate_config({'market_type': 'inverse', 'symbol': 'BTCUSD', 'side': 'long', 'capital': 10000,
                           'leverage': 1, 'lower': 50000, 'upper': 60000, 'rungs': 2})
    assert draft_guards(dict(cfg, venue='bybit')) is None
    # the one rung at 50,000 buys 5,000 contracts (0.1 BTC); the exit at 60,000 sells them —
    # each bar opens within the placement window of the rung it trades through (W1)
    bars = [{'o': 52000.0, 'h': 52500.0, 'l': 49000.0, 'c': 50500.0},          # trades through the buy
            {'o': 58000.0, 'h': 61000.0, 'l': 57500.0, 'c': 60500.0}]          # and through the sell
    r = backtest(cfg, inv, bars, fee_rate=0.0002, funding_rate_hourly=0.0)
    assert r['trips'] == 1 and r['entry_fills'] == 1 and r['held'] == 0.0
    coin = 5000.0 * (1 / 50000.0 - 1 / 60000.0)                                # 0.01667 BTC made
    assert abs(r['grid_profit'] - coin * 60000.0) < 1e-6                       # 1,000, stated in USD at the exit
    assert abs(r['fees'] - 2 * 5000.0 * 0.0002) < 1e-9                         # on the contracts, not × price
    lin = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001, 'price_tick': 0.1, 'min_qty': 0.001,
                         'min_notional': 5.0, 'settle_coin': 'USDT'})
    lcfg = validate_config({'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long', 'capital': 10000,
                            'leverage': 1, 'lower': 50000, 'upper': 60000, 'rungs': 2})
    l = backtest(lcfg, lin, bars, fee_rate=0.0002)
    q = 5000.0 / 50000.0                                                       # the linear rung: 0.1 BTC
    assert abs(l['grid_profit'] - q * 10000.0) < 1e-6                          # linear: the same trade, in quote (1,000 too)
    assert abs(l['fees'] - (q * 50000.0 + q * 60000.0) * 0.0002) < 1e-6       # on qty × price, as before (2.2)


# --- T10/T11: funding at the market's settlements; the margin gauges --------------------

def _t10():
    from gridgremlin.adapters import LinearAdapter
    from gridgremlin.config import validate_config
    adapter = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001, 'price_tick': 0.1,
                             'min_qty': 0.001, 'min_notional': 5.0, 'settle_coin': 'USDT'})
    cfg = validate_config({'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
                           'capital': 1000.0, 'leverage': 10, 'upper': 61000.0,
                           'lower': 59000.0, 'rungs': 21, 'spacing_type': 'fixed'})
    return cfg, adapter


def _fall(n, start=60050.0, step=100.0, t0=0, h=3_600_000):
    return [{'t': t0 + i * h, 'o': start - step * i, 'h': start - step * i + 20,
             'l': start - step * (i + 1), 'c': start - step * (i + 1) + 10} for i in range(n)]


def spec_T10_funding_is_the_markets_settlements_held_through():
    from gridgremlin.backtest import backtest
    cfg, a = _t10()
    bars = _fall(10)
    plain = backtest(cfg, a, bars)
    assert plain['funding'] == 0.0 and plain['funding_modelled'] is False
    events = [{'t': 8 * 3_600_000, 'rate': 0.001},                 # inside bar 7, held by then
              {'t': -5, 'rate': 0.5}, {'t': 99 * 3_600_000, 'rate': 0.5}]   # outside: never charged
    r = backtest(cfg, a, bars, funding=events)
    assert r['funding_modelled'] is True and r['funding'] > 0        # a long pays positive funding
    assert abs(r['net'] - (plain['net'] - r['funding'])) < 1e-9
    held_at = r['funding'] / 0.001                                  # the notional it was charged on
    assert 0 < held_at < cfg['capital'] * cfg['leverage'] * 1.2
    flat = backtest(cfg, a, bars, funding_rate_hourly=0.0001)        # the old flat rate still works
    assert flat['funding'] > 0 and flat['funding_modelled'] is True


def spec_T10_on_its_capital_alone_is_a_risk_line_never_a_stop():
    """D34 buys beyond capital from free balance, so the replay trades as
    decided; the line only says when the row alone would have met its
    maintenance margin."""
    from gridgremlin.backtest import backtest
    cfg, a = _t10()
    crash = _fall(40, step=400.0)
    r = backtest(cfg, a, crash)
    alone = r['alone_liquidation']
    assert alone is not None and 0 < alone['price'] < 60050.0 and alone['held'] > 0
    calm = backtest(cfg, a, _fall(3, step=10.0))
    assert calm['alone_liquidation'] is None
    assert len(r['equity_curve']) == 40                             # it kept trading after


def spec_T11_the_accounts_mmr_is_projected_from_the_exchanges_own_gauge():
    """The owner: "cant we just use MMR that the exchange shows?" — the
    account as it is now, plus the row at each bar's worst price: the peak,
    and the first bar it reaches 100% (Bybit liquidates there)."""
    from gridgremlin.backtest import backtest
    cfg, a = _t10()
    roomy = backtest(cfg, a, _fall(10), account={'equity': 100_000.0, 'mm': 5_000.0, 'label': 'demo'})
    am = roomy['account_mmr']
    assert abs(am['start'] - 0.05) < 1e-12 and am['peak'] > 0.05 and am['reaches_100'] is None
    assert am['label'] == 'demo'
    thin = backtest(cfg, a, _fall(40, step=400.0), account={'equity': 1_500.0, 'mm': 900.0})
    cross = thin['account_mmr']['reaches_100']
    assert cross is not None and thin['account_mmr']['peak'] >= 1.0 and cross['t'] is not None
    assert backtest(cfg, a, _fall(3))['account_mmr'] is None         # no account given: nothing claimed


def spec_T10_T11_the_verdict_says_funding_the_alone_line_and_the_accounts_mmr():
    from gridgremlin.backtest import backtest
    from panel.forms import verdict
    cfg, a = _t10()
    bars = _fall(40, step=400.0)
    out = backtest(cfg, a, bars, funding=[{'t': 3_600_000 * 5 + 1, 'rate': 0.001}],
                   account={'equity': 1_500.0, 'mm': 900.0, 'label': 'Bybit demo'})
    out.update(bars=len(bars), hold_benchmark=0.0, bar_minutes=60)
    page = verdict(dict(cfg), out)
    assert "funding (the market's own)" in page
    assert 'on its capital alone' in page and 'would have been liquidated at' in page
    assert 'account MMR' in page and 'Bybit demo now 60.0%' in page and 'reached 100% (liquidation)' in page
    out2 = backtest(cfg, a, _fall(3, step=10.0))
    out2.update(bars=3, hold_benchmark=0.0, bar_minutes=60)
    page2 = verdict(dict(cfg), out2)
    assert 'not modelled for this market' in page2 and 'never reached its maintenance margin' in page2
    assert 'account MMR' not in page2


def spec_T10_funding_is_read_only_for_a_bybit_futures_grid_and_unread_is_said():
    from gridgremlin.backtest_cli import window_funding
    bars = [{'t': 0, 'o': 1, 'h': 1, 'l': 1, 'c': 1}]
    for draft in ({'market_type': 'spot', 'symbol': 'BTCUSDT'},
                  {'market_type': 'linear', 'symbol': 'BTC', 'venue': 'hyperliquid'},
                  {'market_type': 'linear', 'symbol': 'BTCUSDT', 'strategy': 'martingale'}):
        assert window_funding(draft, bars, 60) is None
    assert window_funding({'market_type': 'linear', 'symbol': 'BTCUSDT'}, [], 60) is None
    # unreachable (the suite refuses the network, T6): None — said as not modelled, never as nothing
    assert window_funding({'market_type': 'linear', 'symbol': 'BTCUSDT'}, bars, 60) is None


def spec_T11_the_panel_reads_the_account_from_the_default_fleets_snapshot():
    import json
    import tempfile
    from pathlib import Path
    from panel.server import Handler
    d = Path(tempfile.mkdtemp())
    (d / 'configs').mkdir()
    (d / 'logs').mkdir()
    row = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long', 'capital': 100.0, 'leverage': 2,
           'upper': 70000.0, 'lower': 50000.0, 'rungs': 11}
    for name, account, eq, rate in (('sub', 'carry', 5000.0, 0.2), ('main', None, 100000.0, 0.03)):
        (d / 'configs' / f'watchdog.{name}.json').write_text(json.dumps({'snapshot': f'logs/s-{name}.jsonl'}))
        fleet = {'watchdog': f'configs/watchdog.{name}.json', 'bots': [row]}
        if account:
            fleet['account'] = account
        (d / 'configs' / f'fleet.{name}.json').write_text(json.dumps(fleet))
        (d / 'logs' / f's-{name}.jsonl').write_text(json.dumps({'t': 1, 'equity': eq, 'mm_rate': rate, 'bots': {}}) + '\n')

    class H(Handler):
        fleets = (str(d / 'configs' / 'fleet.sub.json'), str(d / 'configs' / 'fleet.main.json'))
        labels = ('sub', 'main')
    got = H._account_for(H, {'venue': 'bybit'})
    assert got == {'equity': 100000.0, 'mm': 3000.0, 'label': 'main'}        # the default account first
    assert H._account_for(H, {'venue': 'hyperliquid'}) is None              # no fleet on that venue
