# Specs for SPEC F1-F6 — coverage both ways, the lock, snapshots incl. the
# dead, the mainnet absence, the watchdog's own validator and transitions.

import tempfile

from gridgremlin.config import ConfigError
from gridgremlin.main import (acquire_fleet_lock, check_watchdog_coverage,
                              refuse_mainnet, snapshot_row)
from gridgremlin.watchdog import (decide, evaluate, peak_equity,
                                  validate_watchdog)

WD = {'tag': 't', 'snapshot': 's.jsonl', 'state': 'st.json',
      'staleness_seconds': 1000, 'mm_rate_max': 0.5, 'equity_min': 1000,
      'equity_drawdown_max': 0.25, 're_alert_seconds': 1800,
      'assumes_sole_actor': True,
      'positions': {'botA': {'min': 0, 'max': 12.0}}}


def _wd(**over):
    d = dict(WD)
    d.update(over)
    return validate_watchdog(d)


def _refused(fn, *args, frag=''):
    try:
        fn(*args)
    except ConfigError as e:
        assert frag in str(e), str(e)
        return
    raise AssertionError(f'accepted, expected refusal with {frag!r}')


# --- F1: coverage, both ways -------------------------------------------------

def spec_F1_a_bot_without_its_own_bound_runs_under_the_account_guards():
    """D32: a per-bot bound is opt-in. The old rule (every bot listed)
    made a second file to keep in step by hand, and a fixed ceiling is
    breached by design once a slide may buy beyond capital."""
    wd = _wd()
    check_watchdog_coverage([('botA', 10.0), ('botB', 10.0)], wd)
    check_watchdog_coverage([('botB', None)], dict(wd, positions={}))


def spec_F1_a_stale_watchdog_entry_also_refuses():
    _refused(check_watchdog_coverage, [], _wd(), frag='stale entry')


# --- F2: ceilings pinned near the cap ----------------------------------------

def spec_F2_a_decorative_ceiling_refuses():
    _refused(check_watchdog_coverage, [('botA', 2.0)], _wd(),
             frag='ceiling_loose')           # 12.0 vs cap 2.0: decorative,
                                             # unless chosen by the switch
    _refused(check_watchdog_coverage, [('botA', 20.0)], _wd(),
             frag='below the cap')           # 12.0 below cap 20.0: absurd
    check_watchdog_coverage([('botA', 10.0)], _wd())   # 12.0 in [10, 15]: fine


def spec_F2_martingales_skip_the_cap_check_but_not_coverage():
    check_watchdog_coverage([('botA', None)], _wd())


# --- F3: one fleet process per account ---------------------------------------

def spec_F3_the_second_process_refuses():
    with tempfile.NamedTemporaryFile() as f:
        first = acquire_fleet_lock(f.name)
        _refused(acquire_fleet_lock, f.name, frag='one fleet per account')
        first.close()
        acquire_fleet_lock(f.name).close()   # released -> acquirable again


# --- F4: the dead are visible ------------------------------------------------

class _DeadBot:
    botid, alive, _last_pos = 'botA', False, 0.0


class _LiveBot:
    botid, alive, _last_pos = 'botB', True, 0.021


def spec_F4_snapshots_include_dead_bots():
    row = snapshot_row([_DeadBot(), _LiveBot()],
                       {'equity': 5000.0, 'mm_rate': 0.01}, now=123.0)
    assert row['bots']['botA'] == {'alive': False, 'position': None}  # F9
    assert row['bots']['botB']['alive'] is True


def spec_F4_dead_but_present_is_not_missing():
    cfg = _wd()
    row = {'t': 100.0, 'equity': 5000.0, 'mm_rate': 0.01,
           'bots': {'botA': {'alive': False, 'position': None}}}
    assert 'missing:botA' not in evaluate(cfg, row, now=100.0, peak=5000.0)
    gone = dict(row, bots={})
    assert 'missing:botA' in evaluate(cfg, gone, now=100.0, peak=5000.0)


# --- F7 (D25): mainnet is double-safetied ------------------------------------

def spec_F7_mainnet_needs_both_safeties():
    class _Client:
        env = 'mainnet'
    _refused(refuse_mainnet, _Client(), frag='double-safetied')
    try:
        refuse_mainnet(_Client(), fleet_allows=True)      # file alone: refuse
    except Exception as e:
        assert '--allow-mainnet' in str(e)
    else:
        raise AssertionError('the fleet file alone armed mainnet')
    try:
        refuse_mainnet(_Client(), run_allows=True)        # launch alone: refuse
    except Exception as e:
        assert 'allow_mainnet' in str(e)
    else:
        raise AssertionError('the launch flag alone armed mainnet')
    refuse_mainnet(_Client(), fleet_allows=True, run_allows=True)  # both: fires


def spec_F7_demo_and_testnet_never_consult_the_safeties():
    class _Demo:
        env = 'demo'
    refuse_mainnet(_Demo())                               # no safeties needed


# --- F6 and the watchdog's own validator -------------------------------------

def spec_F6_the_assumption_set_is_typed_not_prose():
    bare = dict(WD)
    del bare['assumes_sole_actor']
    _refused(validate_watchdog, bare, frag='assumes_sole_actor')


def spec_watchdog_config_is_refused_like_everything_else():
    _refused(validate_watchdog, dict(WD, staleness_secondss=5),
             frag='unknown key')
    _refused(validate_watchdog, dict(WD, positions=['botA']),
             frag='positions')
    bare = {k: v for k, v in WD.items() if k != 'positions'}
    assert validate_watchdog(bare)['positions'] == {}      # D32: opt-in
    assert evaluate(validate_watchdog(bare),
                    {'t': 100.0, 'equity': 10 ** 9, 'mm_rate': 0.0,
                     'bots': {'anyone': {'alive': True, 'position': 9e9}}},
                    100.0, None) == {}       # no bound, no position breach


# --- evaluate: the breach set ------------------------------------------------

def _row(**over):
    row = {'t': 1000.0, 'equity': 5000.0, 'mm_rate': 0.1,
           'bots': {'botA': {'alive': True, 'position': 5.0}}}
    row.update(over)
    return row


def spec_D56_the_account_cap_is_opt_in_and_judged_on_mm_rate_and_notional():
    """Owner 2026-10-05: "i dont want my acct to go above N MMR / notional
    USD … these should be opt-in." Either leg or both; none = no cap."""
    from gridgremlin.config import validate_fleet, ConfigError
    from gridgremlin.main import cap_verdict
    row = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
           'capital': 1000, 'lower': 80000, 'upper': 90000, 'rungs': 11}
    assert validate_fleet({'bots': [row]})['account_caps'] is None
    f = validate_fleet({'bots': [row], 'account_caps': {'mm_rate_max': 0.3,
                                                        'notional_max': 50000}})
    assert f['account_caps'] == {'mm_rate_max': 0.3, 'notional_max': 50000.0}
    for bad in ({}, {'mm_rate_max': 1.5}, {'notional_max': 0},
                {'margin': 0.3}, {'notional_max': float('nan')}):
        try:
            validate_fleet({'bots': [row], 'account_caps': bad})
        except ConfigError:
            continue
        raise AssertionError(f'{bad} was accepted')

    class B:
        def __init__(self, n, alive=True):
            self.notional_now, self.alive = n, alive
    bots = [B(30000.0), B(25000.0), B(99999.0, alive=False)]
    assert cap_verdict(None, 0.9, bots) is None                 # opt-in
    assert 'notional 55,000' in cap_verdict({'notional_max': 50000}, None, bots)
    assert cap_verdict({'notional_max': 60000}, None, bots) is None   # dead skip
    assert 'maintenance margin' in cap_verdict({'mm_rate_max': 0.3}, 0.31, bots)
    assert cap_verdict({'mm_rate_max': 0.3}, None, bots) is None   # unknown: no


def spec_F14_a_torn_watchdog_state_heals_and_says_so():
    """Audit 2026-10-05: the state was written in place and read with a
    bare json.loads; one torn write and every later tick failed, the fleet
    unwatched until a hand repaired the file. Now the write is atomic, and
    an unreadable file starts the memory again with one page saying so."""
    import json
    import tempfile
    from pathlib import Path
    import gridgremlin.watchdog as wd
    d = Path(tempfile.mkdtemp())
    snap, state = d / 'snap.jsonl', d / 'state.json'
    snap.write_text(json.dumps({'t': 10**10, 'equity': 5000.0, 'mm_rate': 0.1,
                                'bots': {}}) + '\n')
    cfg = dict(WD, snapshot=str(snap), state=str(state), positions={})
    (d / 'wd.json').write_text(json.dumps(cfg))
    state.write_text('{"_peak": 5000, "_al')                 # torn mid-write
    sent, saved = [], (wd.send_telegram, wd.load_env, wd.time.time)
    try:
        wd.send_telegram, wd.load_env = sent.append, (lambda: None)
        wd.time.time = lambda: 10**10
        assert wd.main([str(d / 'wd.json')]) == 0               # ran, healed
    finally:
        wd.send_telegram, wd.load_env, wd.time.time = saved
    assert any('state file unreadable' in s for s in sent)
    assert json.loads(state.read_text()) == {'_peak': 5000.0, '_alerts': {}}
    assert not list(d.glob('.state.json.*'))                  # no temp left


def spec_F13_one_unknown_equity_row_is_a_blip_not_a_page():
    """2026-10-05: the HL fleet's wallet read lost one cycle in ~850 to the
    rate limit (E9: the cycle runs with unknown equity); each such cycle
    writes one null-equity snapshot row, and the watchdog paged on it and
    announced the recovery five minutes later. A blip beside known rows
    is judged on the newest known figure; only a whole staleness window
    of unknowns is the breach it was meant to be."""
    cfg = _wd()
    null = _row(t=1000.0, equity=None)
    known = [_row(t=700.0), _row(t=900.0, equity=4800.0)]
    out = evaluate(cfg, null, now=1000.0, peak=5000.0, recent=known)
    assert 'equity_unknown' not in out
    assert 'equity' not in out                       # 4800 clears 1000
    low = [_row(t=900.0, equity=900.0)]
    assert 'equity' in evaluate(cfg, null, 1000.0, 5000.0, recent=low)
    dark = [_row(t=700.0, equity=None), _row(t=900.0, equity=None)]
    assert 'equity_unknown' in evaluate(cfg, null, 1000.0, 5000.0, recent=dark)
    old = [_row(t=1000.0 - cfg['staleness_seconds'] - 1)]   # outside the window
    assert 'equity_unknown' in evaluate(cfg, null, 1000.0, 5000.0, recent=old)
    assert 'equity_unknown' in evaluate(cfg, null, 1000.0, 5000.0)  # alone


def spec_evaluate_stale_mmr_equity_and_bounds():
    cfg = _wd()
    assert evaluate(cfg, None, 0, None) == {'nosnap': 'no readable snapshot row'}
    assert 'stale' in evaluate(cfg, _row(), now=2500.0, peak=5000.0)
    assert 'mmr' in evaluate(cfg, _row(mm_rate=0.6), 1000.0, 5000.0)
    assert 'equity' in evaluate(cfg, _row(equity=900.0), 1000.0, 5000.0)
    bots = {'botA': {'alive': True, 'position': 13.0}}
    assert 'pos:botA' in evaluate(cfg, _row(bots=bots), 1000.0, 5000.0)
    assert evaluate(cfg, _row(), 1000.0, 5000.0) == {}


def spec_evaluate_drawdown_measures_from_the_peak():
    cfg = _wd()
    assert 'drawdown' in evaluate(cfg, _row(equity=3000.0), 1000.0, peak=5000.0)
    assert 'drawdown' not in evaluate(cfg, _row(equity=4000.0), 1000.0, 5000.0)


def spec_peak_equity_none_is_unknown_never_zero():
    # v2's falsy sentinel silently disabled the drawdown check (M30)
    assert peak_equity(None, None) is None
    assert peak_equity(None, 5000.0) == 5000.0
    assert peak_equity(5000.0, None) == 5000.0
    assert peak_equity(5000.0, 6000.0) == 6000.0
    assert peak_equity(6000.0, 5000.0) == 6000.0       # monotone


# --- decide: page, remind, recover -------------------------------------------

def spec_decide_pages_new_reminds_on_interval_announces_recovery():
    pages, state = decide({}, {'mmr': 'x'}, now=0.0, re_alert_seconds=1800)
    assert pages == ['mmr: x']
    pages, state = decide(state, {'mmr': 'x'}, now=60.0, re_alert_seconds=1800)
    assert pages == []                                  # inside the interval
    pages, state = decide(state, {'mmr': 'x'}, now=1900.0, re_alert_seconds=1800)
    assert pages == ['still breached — mmr: x']
    pages, state = decide(state, {}, now=2000.0, re_alert_seconds=1800)
    assert pages == ['recovered: mmr'] and state == {}


# --- E7 at the loop: a failed read costs a cycle, never the process ----------
# Two overnight TLS resets each killed the HL unit (2026-08-05); systemd
# restarted it, but a restart resets in-memory state and fires the alarm.

def spec_E7_a_failed_read_costs_a_cycle_never_the_process():
    from gridgremlin import main as m
    from gridgremlin.events import Notifier
    calls = {'n': 0}

    class Flaky:
        env = 'demo'

        def read_wallet(self):
            calls['n'] += 1
            if calls['n'] == 2:
                raise OSError('[Errno 104] Connection reset by peer')
            return {'equity': 1000.0, 'mm_rate': 0.01}

    class IdleBot:
        alive = True
        cfg = {'venue': 'bybit'}
        botid = 'idle'

        def cycle(self, equity=None):
            return None

    events = []
    saved = (m.build_fleet, m.make_notifier, m.load_env, m.acquire_fleet_lock)
    m.build_fleet = lambda p, notif, **kw: ({'notify_orders': False,
                                             'poll_seconds': 0},
                                            {'bybit': Flaky()}, [IdleBot()])
    m.make_notifier = lambda: Notifier(sink=events.append)
    m.load_env = lambda: None
    m.acquire_fleet_lock = lambda path: open('/dev/null')
    try:
        rc = m.run('ignored', cycles=3, poll_seconds=0)
    finally:
        m.build_fleet, m.make_notifier, m.load_env, m.acquire_fleet_lock = saved
    # audit 2026-08-07 MED: one venue's failed wallet read no longer
    # loses the CYCLE — bots still run (with unknown equity, E9), and the
    # weather event names the error
    assert rc == 0 and calls['n'] == 3
    assert any('wallet read failed' in e for e in events)
    # no 'cycle lost' and no recovery banner: nothing was lost to recover
    assert not any('cycle' in e and 'lost' in e for e in events)


def spec_F5_no_repo_fleet_file_ever_carries_the_mainnet_flag():
    import json
    from pathlib import Path
    configs = Path(__file__).resolve().parent.parent / 'configs'
    checked = 0
    for f in sorted(configs.glob('*.json')):
        data = json.loads(f.read_text())
        assert not (isinstance(data, dict) and data.get('allow_mainnet')), \
            f'{f.name} carries allow_mainnet — the armour ships OFF (F5/F7)'
        checked += 1
    assert checked >= 4                    # both fleets, both watchdogs


def spec_E7_a_malformed_venue_response_also_costs_only_the_cycle():
    from gridgremlin import main as m
    from gridgremlin.events import Notifier
    calls = {'n': 0}

    class Malformed:
        env = 'demo'

        def read_wallet(self):
            calls['n'] += 1
            if calls['n'] == 2:
                raise ValueError('Expecting value: line 1 column 1 (char 0)')
            if calls['n'] == 3:
                raise IndexError('list index out of range')
            return {'equity': 1000.0, 'mm_rate': 0.01}

    class IdleBot:
        alive = True
        cfg = {'venue': 'bybit'}
        botid = 'idle'

        def cycle(self, equity=None):
            return None

    events = []
    saved = (m.build_fleet, m.make_notifier, m.load_env, m.acquire_fleet_lock)
    m.build_fleet = lambda p, notif, **kw: ({'notify_orders': False,
                                             'poll_seconds': 0},
                                            {'bybit': Malformed()},
                                            [IdleBot()])
    m.make_notifier = lambda: Notifier(sink=events.append)
    m.load_env = lambda: None
    m.acquire_fleet_lock = lambda path: open('/dev/null')
    try:
        rc = m.run('ignored', cycles=4, poll_seconds=0)
    finally:
        m.build_fleet, m.make_notifier, m.load_env, m.acquire_fleet_lock = saved
    assert rc == 0 and calls['n'] == 4          # both bad cycles lost, not fatal
    assert any('ValueError' in e for e in events)


# --- F8 (D27): the preflight — probe, metadata, tolerance --------------------

def spec_F8_the_verdict_honours_the_tolerance():
    from gridgremlin.main import preflight_verdict
    preflight_verdict([], 0)                          # nothing failed: fine
    preflight_verdict([('botA', 'x')], 1)             # within tolerance
    try:
        preflight_verdict([('botA', 'collateral'), ('botB', 'y')], 1)
    except Exception as e:
        assert 'botA' in str(e) and 'botB' in str(e) and 'tolerance 1' in str(e)
    else:
        raise AssertionError('over-tolerance failures did not refuse')


def spec_D52_no_tolerance_means_the_rest_run_unless_nothing_would():
    from gridgremlin.main import preflight_verdict
    preflight_verdict([('botA', 'x'), ('botB', 'y')], None, total=3)  # one runs
    preflight_verdict([], None, total=0)
    try:
        preflight_verdict([('botA', 'x'), ('botB', 'y')], None, total=2)
    except Exception as e:
        assert 'nothing would run' in str(e) and 'botA' in str(e)
    else:
        raise AssertionError('a fleet with every bot failed did not refuse')


def _probe_bot(venue):
    import sys
    from pathlib import Path as _P
    sys.path.insert(0, str(_P(__file__).parent))
    from spec_loop import ADAPTER, _cfg
    from gridgremlin.bot import Bot
    from gridgremlin.events import Notifier
    return Bot(_cfg(), ADAPTER, venue, Notifier(sink=lambda l: None),
               gen_seed=1)


def spec_F8_the_probe_rests_far_post_only_then_cancels():
    from spec_loop import FakeVenue
    from gridgremlin.main import probe_bot
    venue = FakeVenue(mark=60000.0)
    bot = _probe_bot(venue)
    assert probe_bot(bot) is None                     # the rehearsal passed
    assert venue.orders == []                         # and left NOTHING behind
    assert venue.market_links == [] if hasattr(venue, 'market_links') else True


def spec_F8_the_probe_meets_the_venues_minimum_after_rounding():
    """Live 2026-10-02: a 14.2 coin with a 0.1 step. 5% over the 5 minimum
    at the far price is 0.528 coins, rounded DOWN to 0.5: 4.97, refused,
    and tolerance 0 stopped the whole fleet. The probe steps up until the
    venue's own rule holds."""
    from spec_loop import FakeVenue
    from gridgremlin.adapters import LinearAdapter
    from gridgremlin.bot import Bot
    from gridgremlin.config import validate_config
    from gridgremlin.events import Notifier
    from gridgremlin.exchange.errors import VenueError
    from gridgremlin.main import probe_bot
    adapter = LinearAdapter({'symbol': 'LINKUSDT', 'qty_step': 0.1,
                             'min_qty': 0.1, 'price_tick': 0.001,
                             'min_notional': 5.0, 'settle_coin': 'USDT'})
    seen = []

    class Strict(FakeVenue):
        def place_order(self, category, symbol, side, qty, price, *a, **kw):
            seen.append(float(qty) * float(price))
            if float(qty) * float(price) < 5.0:
                raise VenueError('retCode 110094: Order does not meet '
                                 'minimum order value 5USDT', kind='other')
            return super().place_order(category, symbol, side, qty, price,
                                       *a, **kw)
    cfg = validate_config({'market_type': 'linear', 'symbol': 'LINKUSDT',
                           'side': 'long', 'capital': 400, 'lower': 12.0,
                           'upper': 16.0, 'rungs': 11})
    venue = Strict(mark=14.2)
    bot = Bot(cfg, adapter, venue, Notifier(sink=lambda l: None), gen_seed=1)
    assert probe_bot(bot) is None
    assert 5.0 <= seen[0] < 6.5 and venue.orders == []     # just enough


def spec_F8_a_refusing_venue_names_the_reason():
    from spec_loop import FakeVenue
    from gridgremlin.main import probe_bot
    from gridgremlin.exchange.errors import VenueError

    class Refusing(FakeVenue):
        def place_order(self, *a, **kw):
            raise VenueError('retCode 170037: ADA has not opened collateral '
                             'settings', kind='other')
    reason = probe_bot(_probe_bot(Refusing(mark=60000.0)))
    assert reason and '170037' in reason


def spec_F8_margin_trading_metadata_is_captured():
    from gridgremlin.exchange.bybit.truth import parse_instrument
    info = {'symbol': 'ADAUSDT', 'status': 'Trading', 'baseCoin': 'ADA',
            'marginTrading': 'none',
            'priceFilter': {'tickSize': '0.0001'},
            'lotSizeFilter': {'basePrecision': '0.01', 'minOrderQty': '0.01',
                              'minOrderAmt': '5'}}
    assert parse_instrument('spot', info)['margin_trading'] == 'none'


def spec_C5_an_unplaceable_row_builds_dead_and_the_rest_start():
    """D52 for C5: dust rungs mark the row for the preflight's dead-and-
    visible door, named by symbol and side, instead of raising out of the
    build (2026-10-06: one HYPE row held five HL bots in a restart loop)."""
    from gridgremlin.adapters import LinearAdapter
    from gridgremlin.config import validate_config
    from gridgremlin.main import placeable_or_dead
    spec = {'symbol': 'BTCUSDT', 'qty_step': 0.001, 'price_tick': 0.1,
            'min_qty': 0.001, 'min_notional': 5.0, 'settle_coin': 'USDT'}
    row = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
           'upper': 70000.0, 'lower': 50000.0}
    good = validate_config({**row, 'capital': 1000.0, 'leverage': 10,
                            'rungs': 21})
    placeable_or_dead(good, LinearAdapter(spec))
    assert '_preflight_fail' not in good
    dust = validate_config({**row, 'capital': 2.0, 'leverage': 1,
                            'rungs': 30})
    placeable_or_dead(dust, LinearAdapter(spec))          # must not raise
    assert 'cannot place a single order' in dust['_preflight_fail']
    assert dust['_preflight_fail'].startswith('BTCUSDT long:')


def spec_F2_a_loose_ceiling_is_chosen_never_defaulted():
    """Beyond 1.5x the cap a watcher is decorative — allowed only with
    ceiling_loose: true beside the max (the allow_mainnet double-switch
    shape, owner decision 2026-08-08), so the file records the choice.
    Below the cap is refused outright: a healthy grid would trip it."""
    from gridgremlin.config import ConfigError
    from gridgremlin.main import check_watchdog_coverage
    wd = {'positions': {'b1': {'min': 0, 'max': 300.0}}}
    try:
        check_watchdog_coverage([('b1', 100.0)], wd)
        assert False, 'a 3x ceiling passed without the switch'
    except ConfigError as e:
        assert 'ceiling_loose' in str(e)
    wd['positions']['b1']['ceiling_loose'] = True
    check_watchdog_coverage([('b1', 100.0)], wd)      # chosen: accepted
    wd['positions']['b1']['max'] = 90.0
    try:
        check_watchdog_coverage([('b1', 100.0)], wd)
        assert False, 'a below-cap ceiling passed'
    except ConfigError as e:
        assert 'below the cap' in str(e)


def spec_G7_half_a_lot_held_still_suppresses_its_entry():
    """round() at exactly 0.5 lot suppressed nothing — the entry re-armed
    with half its lot unexited. Any of the lot held suppresses."""
    from gridgremlin.ladder import lots_held
    assert lots_held(0.5, 1.0) == 1
    assert lots_held(0.0, 1.0) == 0
    assert lots_held(1.0, 1.0) == 1
    assert lots_held(1.5, 1.0) == 2


def spec_M2_a_schedule_compounding_past_100pct_is_refused():
    """deviation_pct < 1 per rung still compounds: 20% stepping x2 over 4
    safeties reaches 300% — negative prices, silently skipped rungs, and
    M15 inverting through them. Refused at the validator, with the
    arithmetic named."""
    from gridgremlin.config import ConfigError, validate_martingale
    row = {'strategy': 'martingale', 'market_type': 'linear',
           'symbol': 'XUSDT', 'side': 'long', 'capital': 1000,
           'base_order_size': 100, 'safety_order_size': 100,
           'order_size_multiplier': 1.5, 'deviation_pct': 0.2,
           'deviation_step_multiplier': 2.0, 'max_averaging_orders': 4,
           'take_profit_avg_pct': 0.01, 'repeat': False}
    try:
        validate_martingale(row)
        assert False, 'a 300% schedule validated'
    except ConfigError as e:
        assert 'compounds' in str(e) and '300%' in str(e)


def spec_E9_margin_projection_skips_on_unknown_equity_and_says_so():
    """Unknown equity is None, and summing None was a bare TypeError at
    build. The projection is optional; the build proceeds, named."""
    from gridgremlin.main import _project_margin

    class _C:
        def read_wallet(self):
            return {'equity': None}
    lines = []

    class _N:
        def event(self, kind, botid, text, urgent=False):
            lines.append(f'{kind}: {text}')
    _project_margin({'bybit': _C()}, [], _N())
    assert any('unknown is not zero' in ln for ln in lines)


# --- F9: the dead carry no position, and nobody bounds them -----------------
# The 48-day run: a killed bot's frozen last size sat in the snapshot and the
# watchdog paged "outside [0, 21.6]" every re-alert window for 48 days.

def spec_F9_a_dead_bot_is_visible_but_never_bounded():
    cfg = _wd()
    # sabotage: the pre-fix snapshot carried the last belief, 13 > max 12
    frozen = {'botA': {'alive': False, 'position': 13.0}}
    assert 'pos:botA' not in evaluate(cfg, _row(bots=frozen), 1000.0, 5000.0)
    nothing = {'botA': {'alive': False, 'position': None}}
    assert evaluate(cfg, _row(bots=nothing), 1000.0, 5000.0) == {}
    alive = {'botA': {'alive': True, 'position': 13.0}}
    assert 'pos:botA' in evaluate(cfg, _row(bots=alive), 1000.0, 5000.0)


def _range_review():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / 'ops' / 'retired' / 'range_review.py'
    spec = importlib.util.spec_from_file_location('range_review', path)
    rr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rr)
    return rr


def spec_F9_the_range_review_lists_the_dead_and_reviews_nobody_dead():
    import json
    from pathlib import Path
    rr = _range_review()
    d = Path(tempfile.mkdtemp())
    (d / 'configs').mkdir()
    (d / 'logs').mkdir()
    fleet = d / 'configs' / 'fleet.hl.testnet.json'
    grid = {'strategy': 'grid', 'venue': 'hyperliquid', 'market_type': 'linear',
            'symbol': 'AVAX', 'side': 'long', 'lower': 10.0, 'upper': 20.0,
            'rungs': 11}
    fleet.write_text(json.dumps({'bots': [grid, dict(grid, symbol='SOL')]}))
    snap = d / 'logs' / 'snapshots-hl-testnet.jsonl'      # the tag mapping
    older = json.dumps({'t': 1, 'bots': {'linAVAXl': {'alive': True,
                                                        'position': 25.0}}})
    newest = json.dumps({'t': 2, 'bots': {'linAVAXl': {'alive': False,
                                                         'position': None},
                                           'linSOLl': {'alive': True,
                                                       'position': 0.6}}})
    snap.write_text(older + '\n' + newest + '\n')
    assert rr.dead_bots(fleet) == {'linAVAXl'}           # the NEWEST row
    rr.hl_marks = lambda: {'AVAX': 25.0, 'SOL': 15.0}     # no network
    facts = rr.collect([str(fleet)])
    avax = next(l for l in facts.splitlines() if l.startswith('linAVAXl'))
    assert 'DEAD' in avax and 'IDLE' not in avax        # sabotage: was IDLE ABOVE
    assert 'up-range' in next(l for l in facts.splitlines()
                              if l.startswith('linSOLl'))
    snap.unlink()
    assert rr.dead_bots(fleet) == set()                   # unreadable = nobody
    snap.write_text('not json\n')
    assert rr.dead_bots(fleet) == set()


# --- F10: the review pages the facts ALWAYS; a missing judgement says why --
# 30 of the 48 days paged one line — the CLI's auth failure, exit 0, on
# stdout — as the review, and the fact sheet was dropped.

def spec_F10_facts_are_always_paged_and_a_failed_judgement_is_named():
    rr = _range_review()
    facts = 'linSOLl  10..20  mark 15  50% up-range'
    auth = 'Failed to authenticate: OAuth session expired and could not be refreshed'
    v, why = rr.verdict_or_reason(0, auth, '')
    assert v is None and 'authenticated' in why and 'token' in why  # sabotage
    v, why = rr.verdict_or_reason(1, '', 'boom')
    assert v is None and why.startswith('claude exit 1: boom')
    v, why = rr.verdict_or_reason(0, '', '')
    assert v is None and why
    v, why = rr.verdict_or_reason(0, 'linSOLl KEEP\n\nAll fine.', '')
    assert v == 'linSOLl KEEP\n\nAll fine.' and why == ''
    page = rr.compose(facts, None, 'claude not authenticated')
    assert facts in page and 'no judgement: claude not authenticated' in page
    page = rr.compose(facts, 'linSOLl KEEP', '')
    assert page.startswith('linSOLl KEEP') and facts in page
    v, why = rr.judge({'CLAUDE_BIN': '/nonexistent/claude'}, facts)
    assert v is None and 'TOKEN' in why
    v, why = rr.judge({'CLAUDE_BIN': '/nonexistent/claude',
                       'CLAUDE_CODE_OAUTH_TOKEN': 'x'}, facts)
    assert v is None and 'could not start' in why


# --- F11: the fleet logs are rotated, and the rotation matches the writer --

def spec_F11_the_fleet_log_the_unit_appends_to_is_the_one_rotated():
    from pathlib import Path
    ops = Path(__file__).resolve().parent.parent / 'ops'
    unit = (ops / 'systemd' / 'fleet.service.template').read_text()
    conf = (ops / 'logrotate.conf.template').read_text()
    assert 'StandardOutput=append:{{REPO_DIR}}/logs/fleet-{{FLEET}}.log' in unit
    assert '{{REPO_DIR}}/logs/fleet-*.log {' in conf
    assert 'copytruncate' in conf                 # the writer is never restarted
    assert 'size 100M' in conf and 'rotate 5' in conf
    assert 'snapshots' not in conf                # one history, never rotated
    svc = (ops / 'systemd' / 'logrotate.service.template').read_text()
    assert '--state {{REPO_DIR}}/logs/.logrotate.state' in svc   # no root
    assert 'ops/logrotate.conf' in svc


# --- F12: a running fleet takes an edited row's terms (D49) ------------------

def _watch_world(rows, lev_refusal=None, hl_refusal=None):
    import json
    import tempfile
    from pathlib import Path
    from gridgremlin.apply import make_botid
    from gridgremlin.config import validate_config
    from gridgremlin.reload import FleetWatch
    d = Path(tempfile.mkdtemp())
    (d / 'wd.json').write_text(json.dumps({
        'tag': 't', 'snapshot': 's', 'state': 'st', 'staleness_seconds': 9,
        'mm_rate_max': 0.5, 'equity_min': 10, 're_alert_seconds': 9,
        'assumes_sole_actor': True}))
    fleet = d / 'f.json'
    fleet.write_text(json.dumps({'watchdog': str(d / 'wd.json'),
                                 'bots': rows}))

    class Bot:
        def __init__(self, cfg):
            self.cfg = dict(validate_config(dict(cfg)),
                            funding_interval_minutes=480.0,
                            _tier_mm_rate=0.005)
            self.botid = make_botid(cfg['market_type'], cfg['symbol'],
                                    cfg['side'])
            self._loss_cache = ('x',)

    class Venue:
        env = 'demo'

        def __init__(self):
            self.calls = []

        def set_leverage(self, category, symbol, lev, sell=None):
            self.calls.append((category, symbol, lev))
            if lev_refusal:
                from gridgremlin.exchange.errors import VenueError
                raise VenueError(lev_refusal, kind='other')
    class HL:                                   # F12 on Hyperliquid
        env = 'testnet'

        def __init__(self):
            self.calls = []

        def _entry(self, coin):
            return ({'BTC': 0, 'ETH': 1}[coin], {'name': coin})

        def update_leverage(self, asset, leverage, is_cross=True):
            self.calls.append((asset, leverage))
            if hl_refusal:
                from gridgremlin.exchange.hyperliquid.client import HLError
                raise HLError(200, hl_refusal)
    lines, venue = [], Venue()
    venue.hl = HL()
    bots = [Bot(r) for r in rows]
    from gridgremlin.events import Notifier
    watch = FleetWatch(fleet, bots, {'bybit': venue, 'hyperliquid': venue.hl},
                       Notifier(sink=lines.append))
    return watch, bots, venue, lines, fleet


_HL = {'venue': 'hyperliquid', 'market_type': 'linear', 'symbol': 'BTC',
       'side': 'long', 'capital': 300, 'leverage': 5, 'lower': 80000,
       'upper': 90000, 'rungs': 21}


def spec_F12_hyperliquid_leverage_goes_to_the_venue_too():
    """Live 2026-10-04 15:35 UTC: the owner set two HL rows to 25x in the
    panel; the hot-apply resized both ladders to 25x while the venue still
    margined the positions at 5x (the engine never set it), so every rung
    was refused for margin and the fleet's free margin was nine dollars.
    The build asserts HL leverage on the venue; so does the hot-apply now,
    and a refusal applies nothing."""
    import json
    watch, bots, venue, lines, fleet = _watch_world([_HL])
    rows = json.loads(fleet.read_text())
    rows['bots'][0].update(leverage=25)
    fleet.write_text(json.dumps(rows))
    assert watch.apply() == {'linBTCl': 'applied'}
    assert venue.hl.calls == [(0, 25)]                 # the venue first
    assert bots[0].cfg['leverage'] == 25 and bots[0].cfg['ladder_notional'] == 7500
    assert not any('not set by the engine' in ln for ln in lines)
    watch, bots, venue, lines, fleet = _watch_world(
        [_HL], hl_refusal='Insufficient margin to place order')
    rows = json.loads(fleet.read_text())
    rows['bots'][0].update(leverage=25)
    fleet.write_text(json.dumps(rows))
    assert watch.apply() == {'linBTCl': 'refused'}
    assert bots[0].cfg['leverage'] == 5 and bots[0].cfg['ladder_notional'] == 1500
    assert any('REFUSED by the venue: Insufficient margin' in ln for ln in lines)


_GRID = {'venue': 'bybit', 'market_type': 'linear', 'symbol': 'BTCUSDT',
         'side': 'long', 'capital': 1000, 'leverage': 5, 'lower': 80000,
         'upper': 90000, 'rungs': 11, '_note': 'a note'}
_SHORT = dict(_GRID, side='short', leverage=3)


def spec_F12_a_changed_term_is_applied_live_and_leverage_goes_to_the_venue():
    import json
    watch, bots, venue, lines, fleet = _watch_world([_GRID, _SHORT])
    rows = json.loads(fleet.read_text())
    rows['bots'][0].update(leverage=10, capital=1500,
                           stop={'watch': 'mark_price', 'level': 70000})
    fleet.write_text(json.dumps(rows))
    assert watch.apply() == {'linBTCUSDTl': 'applied'}
    b = bots[0]
    assert b.cfg['leverage'] == 10 and b.cfg['capital'] == 1500
    assert b.cfg['ladder_notional'] == 15000           # re-derived (C4)
    assert b.cfg['stop']['level'] == 70000
    assert b.cfg['funding_interval_minutes'] == 480.0  # the build's carried
    assert b.cfg['_tier_mm_rate'] == 0.005
    assert b._loss_cache is None
    assert venue.calls == [('linear', 'BTCUSDT', 10)]  # the legs' max
    assert any('applied live from the file' in ln and "leverage 5 -> 10"
               in ln for ln in lines)
    assert bots[1].cfg['leverage'] == 3                # the other leg: as was
    assert watch.apply() == {}                         # nothing more to do


def spec_F12_a_venue_refusal_applies_nothing_and_says_the_venues_words():
    import json
    watch, bots, venue, lines, fleet = _watch_world(
        [_GRID], lev_refusal='retCode 110043: leverage not modified, '
                             'exceeds the risk limit')
    rows = json.loads(fleet.read_text())
    rows['bots'][0].update(leverage=100, capital=1500)
    fleet.write_text(json.dumps(rows))
    assert watch.apply() == {'linBTCUSDTl': 'refused'}
    assert bots[0].cfg['leverage'] == 5 and bots[0].cfg['capital'] == 1000
    assert any('REFUSED by the venue: retCode 110043' in ln for ln in lines)


def spec_F12_a_cold_change_waits_for_a_restart_and_so_do_new_and_removed_rows():
    import json
    watch, bots, venue, lines, fleet = _watch_world([_GRID, _SHORT])
    rows = json.loads(fleet.read_text())
    rows['bots'][0].update(upper=95000, leverage=10)   # a lattice change
    del rows['bots'][1]                                # the short removed
    rows['bots'].append(dict(_GRID, symbol='ETHUSDT', lower=2000,
                             upper=3000))              # a new row
    fleet.write_text(json.dumps(rows))
    assert watch.apply() == {'linBTCUSDTl': 'restart'}
    assert bots[0].cfg['leverage'] == 5 and venue.calls == []
    assert any('upper' in ln and 'waits for a restart' in ln
               for ln in lines)
    assert any('linBTCUSDTs: removed from the file' in ln for ln in lines)
    assert any('linETHUSDTl: new in the file' in ln for ln in lines)


def spec_F12_a_refused_file_changes_nothing():
    watch, bots, venue, lines, fleet = _watch_world([_GRID])
    fleet.write_text('{"bots": [{"symbol": 1}]}')
    assert watch.apply() == {}
    assert bots[0].cfg['leverage'] == 5
    assert any('refused' in ln and 'running on' in ln for ln in lines)


def spec_F12_the_watch_waits_for_the_write_to_settle_and_polls_cheaply():
    import json
    import os
    import time
    watch, bots, venue, lines, fleet = _watch_world([_GRID])
    now = time.time()
    assert watch.poll(now) is None                     # unchanged: nothing
    rows = json.loads(fleet.read_text())
    rows['bots'][0]['leverage'] = 10
    fleet.write_text(json.dumps(rows))
    os.utime(fleet, (now, now))
    assert watch.poll(now + 0.5) is None               # still settling
    assert watch.poll(now + 5) == {'linBTCUSDTl': 'applied'}
    assert watch.poll(now + 10) is None                # seen once
