# Specs for the real-money gates found by the audit before real money
# (2026-10-13): U79, E14, E15, U80, and closing on Mainnet (D97).

import json
import os
import tempfile
from pathlib import Path


def spec_U79_a_fleet_that_may_reach_mainnet_is_asked_as_mainnet_before_any_readout():
    """D64's check read only the readout the panel held, so after a restart,
    on a direct post, or with a failed readout, a real-money edit went
    through unasked. The fleet file's own switch decides first (read by the
    engine's helper; the panel never names it); an unreadable file asks
    more; a fleet without the switch is play money until a readout says
    otherwise."""
    from panel.routes import Handler
    h = Handler.__new__(Handler)
    with tempfile.TemporaryDirectory() as d:
        real, play = Path(d) / 'real.json', Path(d) / 'play.json'
        real.write_text(json.dumps({'allow_mainnet': True, 'bots': []}))
        play.write_text(json.dumps({'bots': []}))
        for p in (real, play):
            Handler._cache.pop(str(p), None)
        assert h._mainnet(real, 'bybit') is True                         # no readout held: still asked
        assert h._mainnet(play, 'bybit') is False
        assert h._mainnet(Path(d) / 'gone.json', 'bybit') is True        # unreadable: ask more


def spec_U79_a_trade_on_mainnet_asks_for_its_capital_twice():
    """L5: a trade is a bot, so D64's second typing applies to it: on a
    fleet that may reach Mainnet the trade is refused until the investment
    is typed again, and queued when it matches; play money is never asked."""
    from spec_setup import _call, _served_fleet
    base, d, close = _served_fleet()
    try:
        fleet = json.loads((d / 'f.json').read_text())
        (d / 'f.json').write_text(json.dumps(dict(fleet, allow_mainnet=True)))
        form = {'action': 'open', 'fleet': '0', 'side': 'long', 'symbol': 'btcusdt',
                'capital': '200', 'leverage': '3', 'tp': '0.6'}
        refused = _call(base, '/trade', form)
        assert 'trade refused' in refused and 'a second time' in refused
        assert not (d / 'logs' / 'trades-f.json').exists() or json.loads((d / 'logs' / 'trades-f.json').read_text()) == []
        wrong = _call(base, '/trade', dict(form, retype_capital='2000'))
        assert 'trade refused' in wrong
        ok = _call(base, '/trade', dict(form, retype_capital='200'))
        assert 'linBTCUSDTl: queued' in ok
    finally:
        close()


def spec_E14_a_network_flag_is_true_false_or_unset_never_a_guess():
    """`BYBIT_DEMO=1` and `"true "` read as real money before; now true,
    1, yes (any case, spaces trimmed) are true, empty/false/0/no are false,
    and anything else is refused by name."""
    from gridgremlin.exchange.bybit.client import detect_env
    saved = {k: os.environ.pop(k, None) for k in ('BYBIT_DEMO', 'BYBIT_TESTNET')}
    try:
        for v, want in (('true', 'demo'), ('1', 'demo'), (' TRUE ', 'demo'), ('yes', 'demo')):
            os.environ['BYBIT_DEMO'] = v
            assert detect_env() == want, v
        os.environ['BYBIT_DEMO'] = ''
        os.environ['BYBIT_TESTNET'] = '1'
        assert detect_env() == 'testnet'
        os.environ['BYBIT_TESTNET'] = 'false'
        assert detect_env() == 'mainnet'                                  # neither said: D25 decides
        os.environ['BYBIT_DEMO'] = 'ture'
        try:
            detect_env()
            raise AssertionError('a typo read as a network')
        except ValueError as e:
            assert 'BYBIT_DEMO' in str(e)
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


def spec_E15_an_account_never_borrows_another_accounts_keys():
    """In a process reading several fleets, selecting a fully keyed account
    and then one with only a Hyperliquid subaccount left the first one's
    Bybit keys in place under the standard names. Every account now starts
    from the defaults, and an account with no Bybit keys has none."""
    from gridgremlin.exchange import env
    names = ('BYBIT_API_KEY', 'BYBIT_API_SECRET', 'BYBIT_DEMO', 'BYBIT_TESTNET', 'HL_ACCOUNT_ADDRESS',
             'HL_SUBACCOUNT', 'BYBIT_LIVE_API_KEY', 'BYBIT_LIVE_API_SECRET', 'HL_SIDE_SUBACCOUNT')
    saved = {k: os.environ.get(k) for k in names}
    saved_defaults = env._defaults
    try:
        for k in names:
            os.environ.pop(k, None)
        os.environ.update({'BYBIT_API_KEY': 'default-key', 'BYBIT_API_SECRET': 'default-secret',
                           'BYBIT_DEMO': 'true', 'BYBIT_LIVE_API_KEY': 'live-key',
                           'BYBIT_LIVE_API_SECRET': 'live-secret', 'HL_SIDE_SUBACCOUNT': '0xabc'})
        env._defaults = None
        env.select_account('live')
        assert os.environ['BYBIT_API_KEY'] == 'live-key'
        env.select_account('side')
        assert 'BYBIT_API_KEY' not in os.environ and os.environ['HL_SUBACCOUNT'] == '0xabc'
        env.select_account('default')
        assert os.environ['BYBIT_API_KEY'] == 'default-key' and os.environ['BYBIT_DEMO'] == 'true'
    finally:
        env._defaults = saved_defaults
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


def spec_U80_a_fleet_is_read_by_the_copy_it_lives_in():
    """The panel and the phone ran the readout from their own checkout and
    its .env, so the pinned live copy's fleet would be read by the main
    copy's code and keys. A tool for a fleet now runs from the checkout
    the fleet file lives in; a file outside any checkout runs from this
    code, as before."""
    from gridgremlin.durable import fleet_home
    here = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as d:
        live = Path(d) / 'live'
        (live / 'gridgremlin').mkdir(parents=True)
        (live / 'gridgremlin' / '__init__.py').write_text('')
        (live / 'configs').mkdir()
        assert fleet_home(live / 'configs' / 'fleet.live.json') == live
        assert fleet_home(Path(d) / 'loose.json') == here
    assert fleet_home(here / 'configs' / 'fleet.demo.json') == here
    for f in ('panel/routes.py', 'panel/pages/control.py', 'gridgremlin/archive.py'):
        src = (here / f).read_text()
        assert 'cwd=str(fleet_home(' in src, f


def spec_D97_the_close_command_reaches_mainnet_only_with_both_halves():
    """D97 (was D48's "never mainnet"): on Mainnet the close command needs
    the fleet file's switch AND `--allow-mainnet` on this command; either
    alone refuses, naming what is missing, before any order. Sabotage: the
    file half read as true always lets the flag alone through."""
    import gridgremlin.exchange.bybit.client as bc
    from gridgremlin import close
    from gridgremlin.edition import real_money_refused

    class Mainnet:
        env = 'mainnet'

        def instruments_info(self, cat, sym):
            raise RuntimeError('past the gate')
    saved = bc.WriteClient
    bc.WriteClient = Mainnet
    try:
        with tempfile.TemporaryDirectory() as d:
            wd = Path(d) / 'wd.json'
            wd.write_text(json.dumps({'tag': 't', 'snapshot': 's', 'state': 'st', 'staleness_seconds': 9,
                                      'mm_rate_max': 0.5, 'equity_min': 10, 're_alert_seconds': 9,
                                      'assumes_sole_actor': True}))
            from spec_setup import _shipped_rows
            row = next(r for r in _shipped_rows() if r['symbol'] == 'ETHUSDT' and r['side'] == 'long')

            def run(fleet_switch, flag):
                f = Path(d) / 'f.json'
                f.write_text(json.dumps(dict({'watchdog': str(wd), 'bots': [row]},
                                             **({'allow_mainnet': True} if fleet_switch else {}))))
                import contextlib
                import io
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    close.main([str(f), 'linETHUSDTl', '--dry'] + (['--allow-mainnet'] if flag else []))
                return json.loads(buf.getvalue())['refused']
            if real_money_refused():                                       # the public edition: flatly
                assert real_money_refused() in run(True, True)
                return
            assert 'allow_mainnet' in run(False, True) and '--allow-mainnet' not in run(False, True)
            assert '--allow-mainnet' in run(True, False)
            assert 'past the gate' in run(True, True)
    finally:
        bc.WriteClient = saved


def spec_D97_the_operator_types_the_size_they_read():
    """`--expect`: the venue must hold exactly the size typed, or nothing
    is sent; the panel's argv carries the run half only for real money."""
    from gridgremlin.close import close_position, command
    from spec_stops import ADAPTER, _CloseVenue, _short_row
    venue = _CloseVenue({2: {'side': 'Sell', 'size': 0.021, 'avg_entry': 11.2}})
    wrong = close_position(_short_row(), venue, ADAPTER, True, expect=0.012)
    assert 'not the 0.012 typed' in wrong['refused'] and venue.orders == []
    done = close_position(_short_row(), venue, ADAPTER, True, expect=0.021)
    assert done['closed'] == 0.021 and len(venue.orders) == 1
    assert command('f.json', 'b', real_money=True)[-1] == '--allow-mainnet'
    assert '--allow-mainnet' not in command('f.json', 'b', dry=True, expect=0.5)
    assert command('f.json', 'b', expect=0.5)[-2:] == ['--expect', '0.5']


def spec_D97_on_mainnet_the_panels_close_asks_for_the_size_a_second_time():
    """The panel's close page on a real-money fleet asks for the bot's name
    and the size typed again; without the size nothing runs, with it the
    engine is asked to close exactly that. Play money asks the name only."""
    from panel.server import Handler
    from spec_setup import _call, _served_fleet
    base, d, close = _served_fleet()
    saved_units, saved_run = Handler.units, Handler._run_close
    calls = []

    def fake(self, fi, botid, dry, expect=None):
        calls.append((dry, expect))
        return {'botid': botid, 'side': 'long', 'symbol': 'ETHUSDT', 'held': 0.25,
                'avg_entry': 2500.0, 'mark': 2600.0, 'closed': 0.25, 'left': 0.0}
    Handler.units, Handler._run_close = ('some.service',), fake          # control armed (§12)
    try:
        play = _call(base, '/close?fleet=0&bot=linETHUSDTl')
        assert 'close at market' in play and 'a second time' not in play
        fleet = json.loads((d / 'f.json').read_text())
        (d / 'f.json').write_text(json.dumps(dict(fleet, allow_mainnet=True)))
        page = _call(base, '/close?fleet=0&bot=linETHUSDTl')
        assert 'real money' in page and 'type the size a second time' in page
        calls.clear()
        form = {'gg': '1', 'fleet': '0', 'bot': 'linETHUSDTl', 'confirm': 'linETHUSDTl'}
        refused = _call(base, '/close', form)
        assert 'not closed' in refused and calls == []
        _call(base, '/close', dict(form, size='0.25'))
        assert calls == [(False, 0.25)]
    finally:
        Handler.units, Handler._run_close = saved_units, saved_run
        close()
    src = (Path(__file__).resolve().parents[1] / 'panel' / 'pages' / 'control.py').read_text()
    assert "real_money=self._mainnet(fleet, 'bybit')" in src


def spec_U80b_a_fleet_in_another_copy_never_inherits_this_copys_venue_keys():
    """The audit of 2026-10-13: the phone's unit loads the main .env, and
    `load_env` lets the process environment win, so the live copy's readout
    read the demo account. A tool for a fleet in another checkout runs with
    every BYBIT_*/HL_* name dropped (its own .env supplies them); a fleet
    here keeps the environment whole. Sabotage: returning the environment
    unchanged leaves the demo key in the live child's environment."""
    from gridgremlin.durable import fleet_env
    here = Path(__file__).resolve().parents[1]
    environ = {'BYBIT_API_KEY': 'demo-key', 'BYBIT_DEMO': 'true', 'HL_TESTNET': 'true',
               'TELEGRAM_CHAT_ID': '1', 'PATH': '/usr/bin'}
    with tempfile.TemporaryDirectory() as d:
        live = Path(d) / 'live'
        (live / 'gridgremlin').mkdir(parents=True)
        (live / 'gridgremlin' / '__init__.py').write_text('')
        (live / 'configs').mkdir()
        got = fleet_env(live / 'configs' / 'fleet.live.json', environ)
        assert got == {'TELEGRAM_CHAT_ID': '1', 'PATH': '/usr/bin'}
    assert fleet_env(here / 'configs' / 'fleet.demo.json', environ) == environ
    for f in ('panel/routes.py', 'panel/pages/control.py', 'gridgremlin/archive.py'):
        assert 'env=fleet_env(' in (here / f).read_text(), f


def spec_D64b_nan_and_infinity_are_never_a_typed_number():
    """The audit of 2026-10-13: "nan" passed the second typing (D64) and the
    close's size (D97) — every comparison with nan is false. The one parser
    refuses nan and inf, so the retype asks again and the close sends
    nothing. Sabotage: letting float_or return nan passes the retype."""
    from common.fmt import float_or
    from gridgremlin.close import close_position
    from panel.create import retype_refusal
    from spec_stops import ADAPTER, _CloseVenue, _short_row
    for bad in ('nan', 'NaN', 'inf', '-inf', 'Infinity'):
        assert float_or(bad) is None, bad
        assert retype_refusal([('capital', None, 50000.0)], {'retype_capital': bad}), bad
    assert float_or('2.5') == 2.5
    venue = _CloseVenue({2: {'side': 'Sell', 'size': 0.021, 'avg_entry': 11.2}})
    out = close_position(_short_row(), venue, ADAPTER, True, expect=float_or('nan', -1.0))
    assert 'refused' in out and venue.orders == []


def spec_D25b_the_real_money_switch_is_json_true_or_nothing():
    """The audit of 2026-10-13: the file half of D25 read as truthiness, so
    "false" (a string) armed it. Only JSON true arms; false or absent is
    off; anything else is refused by name. The panel asks more of anything
    but false or absent. Sabotage: bool() of the value arms "false"."""
    from gridgremlin.config import ConfigError, may_reach_mainnet, validate_fleet
    from spec_setup import _shipped_rows
    wd = {'tag': 't', 'snapshot': 's', 'state': 'st', 'staleness_seconds': 9, 'mm_rate_max': 0.5,
          'equity_min': 10, 're_alert_seconds': 9, 'assumes_sole_actor': True}
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / 'wd.json').write_text(json.dumps(wd))
        row = next(r for r in _shipped_rows() if r['symbol'] == 'ETHUSDT' and r['side'] == 'long')
        base = {'watchdog': str(Path(d) / 'wd.json'), 'bots': [row]}
        assert validate_fleet(dict(base, allow_mainnet=True))['allow_mainnet'] is True
        assert validate_fleet(dict(base, allow_mainnet=False))['allow_mainnet'] is False
        assert validate_fleet(dict(base))['allow_mainnet'] is False
        for bad in ('false', 'true', 1, 0, None, 'yes'):
            try:
                validate_fleet(dict(base, allow_mainnet=bad))
                raise AssertionError(f'accepted {bad!r}')
            except ConfigError as e:
                assert 'allow_mainnet' in str(e) and 'true or false' in str(e)
    assert may_reach_mainnet({'allow_mainnet': 'false'}) is True       # malformed: ask more
    assert may_reach_mainnet({'allow_mainnet': False}) is False and may_reach_mainnet({}) is False


def spec_D98b_a_fleet_whose_every_bot_stood_down_exits_as_a_failure():
    """The audit of 2026-10-13: "all bots dead" returned 0, so the real-money
    unit (Restart=no, D98) went inactive, not failed, and OnFailure never
    paged. It exits non-zero now; a play-money unit restarts either way."""
    from gridgremlin import main as m
    assert m.ALL_DEAD_EXIT != 0
    src = (Path(__file__).resolve().parents[1] / 'gridgremlin' / 'main.py').read_text()
    i = src.index("print('all bots dead — fleet exits'")
    assert 'return ALL_DEAD_EXIT' in src[i:i + 120]
