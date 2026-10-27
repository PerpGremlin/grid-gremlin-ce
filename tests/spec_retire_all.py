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


def spec_D149_a_cleared_or_new_bot_starts_its_window_at_home():
    """The owner's hand-built grids (2026-10-22): BTC, ETH and SOL took the
    names of bots cleared that morning and inherited their slide offsets,
    so each window sat far below its range and placed nothing. Clearing a
    row forgets its offset; so does the panel's create or remove of a row.
    Sabotage: clearing without forgetting is caught."""
    import inspect
    import gridgremlin.main as gm
    import gridgremlin.retire as rt
    from gridgremlin.durable import state_path
    from gridgremlin.retire_all import retire_fleet
    from gridgremlin.slide_state import SlideState, forget
    with tempfile.TemporaryDirectory() as d:
        conf = Path(d) / 'configs'
        conf.mkdir()
        (Path(d) / 'logs').mkdir()
        f = conf / 'fleet.x.json'
        f.write_text(json.dumps({'bots': [
            {'venue': 'bybit', 'market_type': 'spot', 'symbol': 'BTCUSDT', 'side': 'long',
             'capital': 100, 'lower': 50000, 'upper': 60000, 'rungs': 5}]}))
        sp = state_path(str(f), json.loads(f.read_text()), 'slide_state')
        SlideState(str(sp)).set('spoBTCUSDTl', -21)
        SlideState(str(sp)).set('linETHUSDTl', -3)
        assert forget(sp, 'linETHUSDTl') == -3 and forget(sp, 'linETHUSDTl') is None
        venue = _Spot()
        real_open, real_running = rt.open_venue, gm.fleet_running
        try:
            rt.open_venue = lambda cfg, clients=None: (clients.setdefault('bybit', venue), None)
            gm.fleet_running = lambda *a, **k: False
            retire_fleet(f, clear=True)
        finally:
            rt.open_venue, gm.fleet_running = real_open, real_running
        assert SlideState(str(sp)).get('spoBTCUSDTl') == 0
    import panel.pages.create_flow as cf
    src = inspect.getsource(cf)
    assert "if mode in ('create', 'remove'):" in src and 'forget_bot(fleet_p, fleet_raw, botid)' in src


def spec_control_names_each_unit_by_its_account():
    """The owner (2026-10-22), reading control: "can we make the accounts
    match their names in the UI?" Each unit's line leads with the account's
    name as the cards show it, the unit to type beside it; retire all's
    choice names the account too. Without labels, the unit alone."""
    import subprocess
    from panel.routes import Handler
    h = Handler.__new__(Handler)
    h.fleets = ['configs/fleet.demo.json', 'configs/fleet.carry.json']
    h.labels = ('Bybit demo', 'Bybit demo subaccount 1')
    h.units, h.supervise = ('grid-gremlin3-demo', 'grid-gremlin3-carry'), False
    h._page = lambda body: body
    h._tombs_html = lambda: ''
    real = subprocess.run
    try:
        subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 3, 'inactive\n', '')
        page = h._control_page()
    finally:
        subprocess.run = real
    assert '<b>Bybit demo subaccount 1</b> <span class="dim">unit grid-gremlin3-carry</span>' in page
    assert '<b>Bybit demo</b> <span class="dim">unit grid-gremlin3-demo</span>' in page
    assert '>Bybit demo subaccount 1 — fleet.carry.json</option>' in h._retire_all_form()
    h.labels = ()
    assert '>fleet.carry.json</option>' in h._retire_all_form()


def spec_E2b_a_spot_exit_is_judged_as_an_exit_not_to_half_a_step():
    """The owner's spot grid on a borrow (2026-10-22) amended its four
    sells every cycle, ~3,000 an hour: spot exits carry no reduce-only
    flag, so they were judged as entries, to half a qty step, and every
    drift of the sellable by a step re-sized them. An exit now says so
    (`exit`) and is judged to the exit's band; a spot entry keeps D88's
    half step. Sabotage: dropping the exit's band brings the churn back."""
    from gridgremlin.apply import diff, matches
    step = 0.000001
    resting = {'side': 'Sell', 'reduce_only': False, 'price': 85031.6, 'qty': 0.174969,
               'link_id': 'spoBTCUSDTl-7-1', 'order_id': 'x'}
    exit_ = {'rung': 7, 'side': 'Sell', 'reduce_only': False, 'exit': True,
             'price': 85031.6, 'qty': 0.174917}
    assert matches(exit_, resting, qty_step=step)
    assert diff([exit_], [resting], 'spoBTCUSDTl', qty_step=step) == ([], [])
    entry = dict(exit_, exit=False, side='Sell')
    assert not matches(entry, resting, qty_step=step)                   # D88 stands for entries
    assert not matches(dict(exit_, qty=0.3), resting, qty_step=step)    # a grown holding still re-sizes
    import inspect
    from gridgremlin.ladder import plan_grid
    assert "'reduce_only': exits_ro, 'exit': True" in inspect.getsource(plan_grid)   # the grid marks its exits


def _tmp_fleet(d, bots, wd_positions=None):
    """configs/fleet.x.json and its watchdog in a fresh tree under `d`."""
    conf = Path(d) / 'configs'
    conf.mkdir()
    (Path(d) / 'logs').mkdir()
    wd = conf / 'watchdog.x.json'
    wd.write_text(json.dumps({'equity_min': 10, 'positions': wd_positions or {}}))
    f = conf / 'fleet.x.json'
    f.write_text(json.dumps({'watchdog': str(wd), 'bots': bots}))
    return f, wd


SPOT_ROW = {'venue': 'bybit', 'market_type': 'spot', 'symbol': 'BTCUSDT', 'side': 'long',
            'capital': 100, 'lower': 50000, 'upper': 60000, 'rungs': 5}


class _Sticky(_Spot):
    """A cancel the venue acknowledges while the order still rests."""

    def cancel_order(self, category, symbol, order_id):
        self.cancelled.append(order_id)


def _retiring(venue, fn):
    """`fn()` with the venue faked and the fleet read as stopped."""
    import gridgremlin.main as gm
    import gridgremlin.retire as rt
    real_open, real_running = rt.open_venue, gm.fleet_running
    try:
        rt.open_venue = lambda cfg, clients=None: (clients.setdefault('bybit', venue), None)
        gm.fleet_running = lambda *a, **k: False
        return fn()
    finally:
        rt.open_venue, gm.fleet_running = real_open, real_running


def spec_D149_a_clear_waits_for_a_flat_venue():
    """The reviewer (2026-10-27): a cancel acknowledged while the order
    still rests read back not flat, and --clear took the row, its watchdog
    line and its tombstone out anyway; a new bot of the same name then
    adopted the order by its link. The clear happens only over a flat
    read-back; otherwise every row, tombstone and record stays and the
    answer says what is left. Sabotage: clearing over `left` is caught."""
    from gridgremlin.retire_all import retire_fleet
    from gridgremlin.tombstones import Tombstones, path_for
    with tempfile.TemporaryDirectory() as d:
        f, wd = _tmp_fleet(d, [SPOT_ROW], {'spoBTCUSDTl': {'max': 1}})
        out = _retiring(_Sticky(), lambda: retire_fleet(f, clear=True))
        assert out['flat'] is False and out['left'][0]['orders'] == ['spoBTCUSDTl-1-5']
        assert out['cleared'] == [] and 'not flat' in out['not_cleared']
        assert json.loads(f.read_text())['bots'] == [SPOT_ROW]
        assert json.loads(wd.read_text())['positions'] == {'spoBTCUSDTl': {'max': 1}}
        assert Tombstones(str(path_for(str(f), json.loads(f.read_text())))).has('spoBTCUSDTl')


def spec_D149_a_fleet_with_refused_rows_is_not_cleared():
    """Retire walks the rows the engine accepts; a row it refuses (D52) is
    not retired, so clearing it would leave what it holds unmanaged. A
    clear is refused, naming the row, before anything is touched; a retire
    without the clear says which rows it did not retire. Sabotage:
    dropping the refusal clears the refused row."""
    from gridgremlin.retire_all import retire_fleet
    bad = dict(SPOT_ROW, symbol='ETHUSDT', bogus_key=1)
    with tempfile.TemporaryDirectory() as d:
        f, _ = _tmp_fleet(d, [SPOT_ROW, bad])
        venue = _Spot()
        out = _retiring(venue, lambda: retire_fleet(f, clear=True))
        assert 'cannot be cleared' in out['refused'] and 'bogus_key' in out['refused'], out
        assert venue.cancelled == [] and len(json.loads(f.read_text())['bots']) == 2
        out = _retiring(venue, lambda: retire_fleet(f))
        assert venue.cancelled == ['a'] and 'bogus_key' in ' '.join(out['not_retired'])


def spec_D149_open_trades_retire_and_clear_with_their_fleet():
    """A trade (D81) is a bot of its fleet, kept in logs/trades-<fleet>.json:
    retire all retired the rows and left the trade's position open, and an
    emptied fleet is one the engine will not run, so nothing managed it.
    Each open trade is retired with the rows and read back; the clear takes
    its row out of the trades file. Sabotage: walking the rows alone leaves
    the trade."""
    import gridgremlin.retire as rt
    from gridgremlin.durable import state_path
    from gridgremlin.retire_all import retire_fleet
    from gridgremlin.trades import load_trades
    retired = []

    def fake_retire(cfg, client, adapter, tombs, reason, dry=False):
        from gridgremlin.apply import row_botid
        retired.append(row_botid(cfg))
        if not dry:
            tombs.add(row_botid(cfg), reason)
        return {'botid': row_botid(cfg), 'tombstoned': not dry}
    with tempfile.TemporaryDirectory() as d:
        f, _ = _tmp_fleet(d, [SPOT_ROW])
        tp = state_path(str(f), json.loads(f.read_text()), 'trades')
        tp.write_text(json.dumps([{'market_type': 'linear', 'symbol': 'SOLUSDT', 'side': 'long',
                                   'capital': 50, 'leverage': 5, 'take_profit_avg_pct': 0.015,
                                   'venue': 'bybit'}]))
        assert load_trades(tp)[0]
        real = rt.retire_bot
        try:
            rt.retire_bot = fake_retire
            out = _retiring(_Spot(), lambda: retire_fleet(f, clear=True))
        finally:
            rt.retire_bot = real
        assert retired == ['linSOLUSDTl'] and out['flat'] is True, out
        assert out['cleared'] == ['linSOLUSDTl', 'spoBTCUSDTl']
        assert load_trades(tp) == ([], []) and json.loads(f.read_text())['bots'] == []


class _Leg:
    def position_idx(self, side, reduce_only):
        return 2


class _Portfolio:
    """A portfolio bot whose flatten left its BTCUSD short open."""

    def __init__(self):
        self.legs = {'spot': {}, 'hedge': {'BTC': {'market_type': 'inverse', 'symbol': 'BTCUSD',
                                                   'adapter': _Leg()}}, 'short': {}}
        self.client = self

    def read_symbol_truth(self, market_type, symbol):
        return {'orders': [], 'positions': {2: {'side': 'Sell', 'size': 500.0}}, 'mark': 80000}

    def flatten_now(self, reason, tombstone=True):
        return {'BTC': 0.0, 'USDT': 1000.0}                 # the wallet, clean

    def _short_size(self, truth, leg):
        from gridgremlin.portfolio_bot import PortfolioBot
        return PortfolioBot._short_size(self, truth, leg)


PORTFOLIO_ROW = {'strategy': 'portfolio', 'name': 'carry', 'venue': 'bybit', 'capital': 300,
                 'assets': [{'coin': 'BTC', 'weight': 0.5}, {'coin': 'ETH', 'weight': 0.5}],
                 'hedge': {'product': 'inverse', 'ratio': 1.0},
                 'rebalance': {'every_hours': 24, 'drift_pct': 0.05, 'min_notional': 20},
                 'risk': {'max_loss': 60, 'max_loss_since': '2026-10-08T00:00:00Z',
                          'margin_floor_pct': 0.4, 'basis_stop_pct': 0.01, 'max_weight': 0.5}}


def spec_D149_a_portfolio_row_is_read_back_leg_by_leg():
    """A portfolio's flatten answers with wallet balances, so a clean
    wallet over an open hedge read flat and the clear forgot the row's book
    and its loan. Each hedge and short leg's position is read back into
    `left`; not flat, nothing is forgotten. Sabotage: skipping the legs'
    read-back reads flat."""
    import gridgremlin.exchange.bybit.client as bc
    import gridgremlin.main as gm
    from gridgremlin.durable import state_path
    from gridgremlin.portfolio_state import PortfolioState
    from gridgremlin.retire_all import retire_fleet
    with tempfile.TemporaryDirectory() as d:
        f, _ = _tmp_fleet(d, [PORTFOLIO_ROW])
        sp = state_path(str(f), json.loads(f.read_text()), 'portfolio_state')
        PortfolioState(str(sp)).set('pfocarry', {'anchor_value': 300.0, 'loan': 100.0})
        real = gm.fleet_running, gm.build_portfolio, gm.refuse_mainnet, bc.WriteClient
        try:
            gm.fleet_running = lambda *a, **k: False
            gm.build_portfolio = lambda cfg, client, n, state, tombs: (_Portfolio(), [])
            gm.refuse_mainnet = lambda *a, **k: None
            bc.WriteClient = lambda: object()
            out = retire_fleet(f, clear=True)
        finally:
            gm.fleet_running, gm.build_portfolio, gm.refuse_mainnet, bc.WriteClient = real
        assert out['flat'] is False and out['cleared'] == [], out
        assert out['left'] == [{'botid': 'pfocarry', 'legs': [
            {'leg': 'hedge BTC', 'symbol': 'BTCUSD', 'held': 500.0}]}]
        assert PortfolioState(str(sp)).get('pfocarry')['loan'] == 100.0
        assert json.loads(f.read_text())['bots'] == [PORTFOLIO_ROW]


def spec_F3_retire_all_holds_the_fleets_prelock():
    """The reviewer (2026-10-27): fleet_running asks the lock and lets it
    go, so an engine could start on the file during a retire of minutes.
    The retire holds the fleet's own prelock throughout, as the engine's
    start does; an engine starting meanwhile is refused (F3), and a
    prelock already held refuses the retire. Sabotage: not taking it lets
    the engine's lock through."""
    from gridgremlin.config import ConfigError
    from gridgremlin.durable import logs_dir
    from gridgremlin.main import acquire_fleet_lock
    from gridgremlin.retire_all import retire_fleet
    with tempfile.TemporaryDirectory() as d:
        f, _ = _tmp_fleet(d, [SPOT_ROW])
        pre = str(logs_dir(f) / f'{f.resolve().name}.prelock')
        tried = []

        class _Racing(_Spot):
            def cancel_order(self, category, symbol, order_id):
                try:
                    acquire_fleet_lock(pre).close()
                    tried.append('started')
                except ConfigError:
                    tried.append('refused')
                super().cancel_order(category, symbol, order_id)
        out = _retiring(_Racing(), lambda: retire_fleet(f))
        assert tried == ['refused'] and out['flat'] is True, (tried, out)
        acquire_fleet_lock(pre).close()                      # let go after
        held = acquire_fleet_lock(pre)
        try:
            out = _retiring(_Spot(), lambda: retire_fleet(f))
            assert 'starting on this file' in out['refused']
        finally:
            held.close()


def spec_X16_a_removed_bot_leaves_nothing_under_its_name():
    """Every local fact a bot keeps under its name — each state kind, its
    retire request and the kept ledger's record — is forgotten by one
    helper, so a new bot of the same name starts at first sight: no slide
    offset, no pending request, no tombstone, no fills, no carry book. A
    neighbour's facts stay; a live trade's row stays (its position is
    open). The list is every STATE_KIND plus the two files
    beside them, so a new kind cannot be missed. Sabotage: forgetting any
    one kind is caught."""
    from gridgremlin.durable import STATE_KINDS, state_path
    from gridgremlin.forget import FORGETS, forget_bot
    from gridgremlin.kept_fills import anchor_of, load
    from gridgremlin.portfolio_state import PortfolioState
    from gridgremlin.retire import load_requests, request, requests_path
    from gridgremlin.slide_state import SlideState
    from gridgremlin.tombstones import Tombstones
    assert set(FORGETS) == set(STATE_KINDS) | {'retire_requests', 'kept_fills'}
    with tempfile.TemporaryDirectory() as d:
        f, _ = _tmp_fleet(d, [])
        raw = json.loads(f.read_text())
        sp = lambda k: str(state_path(str(f), raw, k))       # noqa: E731
        for b in ('linSOLUSDTl', 'linETHUSDTl', 'linXRPUSDTl'):
            SlideState(sp('slide_state')).set(b, -4)
            request(requests_path(f), b, 'close', 'owner')
            PortfolioState(sp('portfolio_state')).set(b, {'anchor_value': 1.0})
        Tombstones(sp('tombstones')).add('linSOLUSDTl', 'ended')
        Tombstones(sp('tombstones')).add('linXRPUSDTl', 'stood down')
        trade = {'market_type': 'linear', 'side': 'long', 'capital': 50, 'leverage': 5,
                 'take_profit_avg_pct': 0.015, 'venue': 'bybit'}
        Path(sp('trades')).write_text(json.dumps([dict(trade, symbol='SOLUSDT'),
                                                  dict(trade, symbol='ETHUSDT')]))
        kp = Path(d) / 'logs' / 'fills' / 'x.json'
        kp.parent.mkdir()
        kp.write_text(json.dumps({'fills': [], 'anchors': {
            b: {'time_ms': 1, 'qty': 1.0, 'price': 1.0} for b in ('linSOLUSDTl', 'linETHUSDTl')}}))
        said = forget_bot(f, raw, 'linSOLUSDTl', at_ms=5)
        assert set(said) == set(FORGETS), said               # every kind held it, every kind forgot it
        assert SlideState(sp('slide_state')).get('linSOLUSDTl') == 0
        assert 'linSOLUSDTl' not in load_requests(requests_path(f))
        assert not Tombstones(sp('tombstones')).has('linSOLUSDTl')
        assert PortfolioState(sp('portfolio_state')).get('linSOLUSDTl') == {}   # a first sight
        assert [r['symbol'] for r in json.loads(Path(sp('trades')).read_text())] == ['ETHUSDT']
        assert anchor_of(load(kp), 'linSOLUSDTl') is None and load(kp)['cuts']['linSOLUSDTl'] == 5
        # the neighbour's facts stay
        assert SlideState(sp('slide_state')).get('linXRPUSDTl') == -4
        assert Tombstones(sp('tombstones')).has('linXRPUSDTl')
        assert anchor_of(load(kp), 'linETHUSDTl') is not None
        # a live trade (no tombstone) keeps its row
        said = forget_bot(f, raw, 'linETHUSDTl')
        assert said['trades'] == 'a live trade — its row kept'
        assert [r['symbol'] for r in json.loads(Path(sp('trades')).read_text())] == ['ETHUSDT']


def spec_X16_every_removal_path_forgets_the_whole_bot():
    """The panel's removals and creations each forgot a different few
    facts: retire's remove kept the slide offset, the edit page's remove
    kept the fills and the carry book, the carry create took the old
    book's anchor and loan, the orphans clear kept the request. Each calls
    the one helper now. A carry row removed and created again under its
    name starts at first sight. Sabotage: the edit page's remove without
    the helper keeps the old book."""
    import inspect
    import panel.pages.carry_flow as carry
    import panel.pages.create_flow as cf
    import panel.pages.fleet_admin as fa
    import panel.pages.retire as rp
    import gridgremlin.retire_all as ra
    for mod, at in ((cf, 'forget_bot(fleet_p, fleet_raw, botid)'),
                    (carry, 'forget_bot(fleet_p, fleet_raw, botid)'),
                    (rp, 'forget_bot(f, fleet_raw, botid)'),
                    (fa, 'forget_bot(f, raw, b)'),
                    (ra, 'forget_bot(fleet_path, raw, botid, at)')):
        assert at in inspect.getsource(mod), mod.__name__
    from gridgremlin.durable import state_path
    from gridgremlin.portfolio_state import PortfolioState
    from panel.routes import Handler
    with tempfile.TemporaryDirectory() as d:
        f, wd = _tmp_fleet(d, [PORTFOLIO_ROW])
        wd.write_text(json.dumps({'tag': 'x', 'snapshot': 'logs/snapshots-x.jsonl',
                                  'state': 'logs/watchdog-x.state.json', 'staleness_seconds': 1000,
                                  'mm_rate_max': 0.5, 'equity_min': 10, 'equity_drawdown_max': 0.25,
                                  're_alert_seconds': 86400, 'assumes_sole_actor': True,
                                  'positions': {}}))
        sp = state_path(str(f), json.loads(f.read_text()), 'portfolio_state')
        PortfolioState(str(sp)).set('pfocarry', {'anchor_value': 300.0, 'contributed': 50.0})
        h = Handler.__new__(Handler)
        h.fleets, h.units, h.supervise = [str(f)], (), False
        h._page = lambda body: body
        seen = h._seen(f.read_text(), wd.read_text())
        page = h._create_flow({'fleet': '0', 'confirm': 'pfocarry', 'proposal': json.dumps(
            {'mode': 'remove', 'orig': 'pfocarry', 'seen': seen})}, apply=True)
        assert 'written' in page, page
        assert json.loads(f.read_text())['bots'] == []
        assert PortfolioState(str(sp)).get('pfocarry') == {}            # the next carry row is fresh
