"""D149: retire a whole fleet, and clear it to nothing (the owner,
2026-10-22: "we should set up an all clear/retire so we can wipe the UI
with nothing")."""
import json
import tempfile
from pathlib import Path


def _refused(fn, *a):
    from gridgremlin.config import ConfigError
    try:
        fn(*a)
    except ConfigError as e:
        return str(e)
    return ''


def spec_D149_an_empty_fleet_is_a_file_the_engine_will_not_run():
    """Any fleet file may hold no bots — the page shows nothing — but the
    engine refuses to start one, before any account write. A fleet whose
    every row is bad still refuses (D52)."""
    from gridgremlin.config import validate_fleet
    from gridgremlin.events import Notifier
    from gridgremlin.main import build_fleet
    assert validate_fleet({'bots': []})['bots'] == []
    assert 'every row refused' in _refused(validate_fleet, {'bots': [{'symbol': 'X'}]})
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / 'fleet.x.json'
        f.write_text(json.dumps({'bots': []}))
        assert 'nothing to run' in _refused(build_fleet, str(f), Notifier(sink=lambda *_: None))


def spec_D149_clearing_takes_each_row_with_its_watchdog_line():
    """A row and its watchdog line leave together (F1); every other key of
    either file is untouched. Sabotage: leaving the line is caught."""
    from gridgremlin.retire_all import clear_rows
    fleet = {'label': 'x', 'watchdog': 'wd.json', 'bots': [
        {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long'},
        {'market_type': 'linear', 'symbol': 'ETHUSDT', 'side': 'short'}]}
    wd = {'equity_min': 10, 'positions': {'linBTCUSDTl': {'max': 1}, 'linETHUSDTs': {'max': 2}}}
    f2, w2 = clear_rows(fleet, wd, {'linBTCUSDTl'})
    assert [b['symbol'] for b in f2['bots']] == ['ETHUSDT'] and f2['label'] == 'x'
    assert w2 == {'equity_min': 10, 'positions': {'linETHUSDTs': {'max': 2}}}
    f3, w3 = clear_rows(fleet, wd, {'linBTCUSDTl', 'linETHUSDTs'})
    assert f3['bots'] == [] and w3['positions'] == {}
    assert len(fleet['bots']) == 2 and len(wd['positions']) == 2        # the inputs untouched


class _Wallet:
    """A Bybit account's coins and spot markets, for the sell-down."""

    def __init__(self, coins):
        self.coins, self.sold = coins, []

    def wallet_balance(self):
        return {'list': [{'coin': [{'coin': c, 'walletBalance': str(q), 'borrowAmount': str(b)}
                                   for c, (q, b) in self.coins.items()]}]}

    def instruments_info(self, category, symbol):
        if symbol == 'XYZUSDT':
            raise KeyError(symbol)
        return {'lotSizeFilter': {'basePrecision': '0.0001', 'minOrderQty': '0.0001', 'minOrderAmt': '5'}}

    def tickers(self, category, symbol):
        return {'lastPrice': {'BTCUSDT': '80000', 'ETHUSDT': '2500', 'USDCUSDT': '1'}.get(symbol, '1')}

    def place_market(self, category, symbol, side, qty):
        self.sold.append((symbol, side, qty))


def spec_D149_the_sell_down_sells_every_coin_but_usdt():
    """Each coin above the venue's minimum is sold at market for USDT, its
    quantity floored to the lot; dust, a borrowed coin and a coin with no
    USDT market stay, each said; a dry run sells nothing."""
    from gridgremlin.retire_all import sell_down
    w = _Wallet({'USDT': (1000, 0), 'BTC': (0.123456, 0), 'ETH': (0.0001, 0),
                 'USDC': (50, 0), 'SOL': (3, 1), 'XYZ': (9, 0)})
    dry = sell_down(w, dry=True)
    assert w.sold == [] and {'coin': 'BTC', 'would_sell': '0.1234'} in dry
    out = sell_down(w)
    assert sorted(w.sold) == [('BTCUSDT', 'Sell', '0.1234'), ('USDCUSDT', 'Sell', '50.0000')]
    said = {r['coin']: r.get('left') for r in out if 'left' in r}
    assert said == {'ETH': 'dust under the minimum', 'SOL': 'borrowed — repay it first',
                    'XYZ': 'no XYZUSDT market'}


class _Spot:
    """A venue holding one spot row's resting orders."""

    def __init__(self):
        self.orders = [{'link_id': 'spoBTCUSDTl-1-5', 'order_id': 'a'},
                       {'link_id': 'someone-else', 'order_id': 'b'}]
        self.cancelled = []

    def read_symbol_truth(self, market_type, symbol):
        return {'orders': list(self.orders), 'positions': {}}

    def cancel_order(self, category, symbol, order_id):
        self.cancelled.append(order_id)
        self.orders = [o for o in self.orders if o['order_id'] != order_id]


def spec_D149_retire_all_retires_reads_back_and_clears():
    """With the fleet stopped: each row retired (a spot row tombstoned and
    only its own orders cancelled), the venue read back flat, and --clear
    takes every row, its watchdog line and its tombstone out — the fleet
    file is empty. A dry run writes nothing. Beside a running fleet it
    refuses before touching anything."""
    import gridgremlin.main as gm
    import gridgremlin.retire as rt
    from gridgremlin.retire_all import retire_fleet
    from gridgremlin.tombstones import Tombstones, path_for
    with tempfile.TemporaryDirectory() as d:
        conf = Path(d) / 'configs'
        conf.mkdir()
        (Path(d) / 'logs').mkdir()
        wd = conf / 'watchdog.x.json'
        wd.write_text(json.dumps({'equity_min': 10, 'positions': {'spoBTCUSDTl': {'max': 1}}}))
        f = conf / 'fleet.x.json'
        f.write_text(json.dumps({'watchdog': str(wd), 'bots': [
            {'venue': 'bybit', 'market_type': 'spot', 'symbol': 'BTCUSDT', 'side': 'long',
             'capital': 100, 'lower': 50000, 'upper': 60000, 'rungs': 5}]}))
        venue = _Spot()
        real_open, real_running = rt.open_venue, gm.fleet_running
        try:
            rt.open_venue = lambda cfg, clients=None: (clients.setdefault('bybit', venue), None)
            gm.fleet_running = lambda *a, **k: True
            assert 'stop it first' in retire_fleet(f, clear=True)['refused']
            assert venue.cancelled == []
            gm.fleet_running = lambda *a, **k: False
            dry = retire_fleet(f, dry=True, clear=True)
            assert dry['rows'][0]['orders'] == 1 and dry['cleared'] == ['spoBTCUSDTl']
            assert venue.cancelled == [] and json.loads(f.read_text())['bots']
            out = retire_fleet(f, clear=True)
            assert venue.cancelled == ['a'] and out['flat'] is True       # someone else's order stays
            assert out['cleared'] == ['spoBTCUSDTl']
            assert json.loads(f.read_text())['bots'] == []
            assert json.loads(wd.read_text())['positions'] == {}
            fleet = json.loads(f.read_text())
            assert not Tombstones(str(path_for(str(f), fleet))).has('spoBTCUSDTl')
        finally:
            rt.open_venue, gm.fleet_running = real_open, real_running


def spec_D149_the_panel_retires_all_after_a_dry_run_and_the_typed_name():
    """The control page offers retire all; the first press is a dry run
    (nothing sent), the act needs the fleet file's name typed; an empty
    fleet's section says so and links to setup."""
    from panel.render import cards_section
    from panel.routes import Handler
    calls, pages = [], []
    h = Handler.__new__(Handler)
    h.fleets, h.units, h.supervise = ['configs/fleet.demo.json'], ('grid-gremlin3-demo',), False
    h._page = lambda body: pages.append(body) or body
    h._run_retire_all = lambda fi, dry, sell, clear: calls.append((fi, dry, sell, clear)) or {
        'dry': dry, 'rows': [{'botid': 'linBTCUSDTl', 'kind': 'perp', 'orders': 2}],
        'cleared': ['linBTCUSDTl'], 'flat': True}
    assert 'action="/retire-all"' in h._retire_all_form() and 'dry run' in h._retire_all_form()
    page = h._retire_all_act({'fleet': '0', 'clear': '1'})
    assert calls == [(0, True, False, True)] and 'dry run' in page and 'would clear' in page
    assert 'name="go" value="1"' in page and 'name="clear" value="1"' in page
    page = h._retire_all_act({'fleet': '0', 'clear': '1', 'go': '1', 'confirm': 'fleet.demo'})
    assert len(calls) == 1 and 'not done' in page                       # the name, exactly
    page = h._retire_all_act({'fleet': '0', 'clear': '1', 'go': '1', 'confirm': 'fleet.demo.json'})
    assert calls[-1] == (0, False, False, True) and 'flat on the exchange' in page
    empty = {'window_hours': 24.0, 'generated_ms': 0, 'bots': {}, 'unowned': {}}
    assert 'no bots in this fleet' in cards_section(0, 'demo', empty)


def spec_D149_a_fleet_cleared_while_the_panel_runs_leaves_the_page():
    """The owner (2026-10-22), after the clear: the cards stayed. The panel
    served a stale readout while one refresh ran, and the refresh of an
    empty fleet returned nothing but never cached it, so the old cards were
    served for ever. The empty read is cached like any read. Sabotage: not
    caching it brings the old cards back."""
    import time
    from panel.routes import CACHE_TTL_S, Handler
    with tempfile.TemporaryDirectory() as d:
        f = str(Path(d) / 'fleet.x.json')
        Path(f).write_text(json.dumps({'bots': []}))
        h = Handler.__new__(Handler)
        h.hours = 24
        old = {'window_hours': 24, 'generated_ms': 0, 'bots': {'linBTCUSDTl': None}, 'unowned': {}}
        Handler._cache[f] = (time.time() - CACHE_TTL_S - 1, old)       # stale, from before the clear
        try:
            assert h._contract(f) is old                                # served at once while it refreshes
            for _ in range(100):
                if Handler._cache[f][1] is not old:
                    break
                time.sleep(0.02)
            assert h._contract(f)['bots'] == {}
        finally:
            Handler._cache.pop(f, None)


def spec_D149_leftover_tombstones_clear_from_the_dash():
    """The owner (2026-10-22): old tombstones of bots long gone from the
    file "need to be something we can do from the dash". Control lists, per
    fleet, the tombstones whose bot is no longer in its file, and clears
    them at once with the fleet file's name typed; a tombstone whose bot is
    still in the file is a stand-down and stays. Sabotage: clearing every
    tombstone is caught."""
    from gridgremlin.tombstones import Tombstones, path_for
    from panel.routes import Handler
    with tempfile.TemporaryDirectory() as d:
        conf = Path(d) / 'configs'
        conf.mkdir()
        (Path(d) / 'logs').mkdir()
        f = conf / 'fleet.demo.json'
        f.write_text(json.dumps({'bots': [{'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long'}]}))
        tp = path_for(str(f), json.loads(f.read_text()))
        t = Tombstones(str(tp))
        for b in ('linBTCUSDTl', 'linFARTCOINUSDTl', 'invBTCUSDl'):
            t.add(b, 'test')
        h = Handler.__new__(Handler)
        h.fleets, h.labels, h.units, h.supervise = [str(f)], ['demo'], ('grid-gremlin3-demo',), False
        h._page = lambda body: body
        page = h._tombs_html()
        assert "action='/clear-tombstones'" in page and '2 left from bots no longer in the fleet' in page
        assert page.count('no longer in the fleet</i>') == 2
        assert 'not cleared' in h._clear_orphans_act({'fleet': '0', 'confirm': 'demo'})
        done = h._clear_orphans_act({'fleet': '0', 'confirm': 'fleet.demo.json'})
        assert '2 tombstones cleared' in done
        left = json.loads(Path(tp).read_text())
        assert list(left) == ['linBTCUSDTl']                          # the stand-down stays
        assert "action='/clear-tombstones'" not in h._tombs_html()
