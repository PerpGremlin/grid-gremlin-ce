# Specs for the real-money gates found by the audit before real money
# (2026-10-13): U79, E14, E15, U80, and the panel's close on Mainnet.

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


def spec_X15d_on_mainnet_the_panels_close_page_says_close_it_on_the_exchange():
    """D48: the close command has no way to Mainnet. On a fleet that may
    reach real money the panel's close page no longer runs it into a
    refusal: it says plainly the position is closed on the exchange."""
    from panel.server import Handler
    from spec_setup import _call, _served_fleet
    base, d, close = _served_fleet()
    saved = Handler.units
    Handler.units = ('some.service',)                                    # control armed (§12)
    try:
        fleet = json.loads((d / 'f.json').read_text())
        (d / 'f.json').write_text(json.dumps(dict(fleet, allow_mainnet=True)))
        page = _call(base, '/close?fleet=0&bot=linETHUSDTl')
        assert 'real money' in page and 'on the exchange' in page and 'close at market' not in page
    finally:
        Handler.units = saved
        close()
