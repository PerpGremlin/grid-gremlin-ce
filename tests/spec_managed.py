"""D164 — managed trades (L9–L13, U179–U180): a perpetual position no bot
covers, adopted and managed from the panel. Fake venues throughout: no
spec here reaches an exchange. Made-up figures."""
import json
import tempfile
import time
from pathlib import Path

from gridgremlin.adapters import LinearAdapter
from gridgremlin.exchange.errors import VenueError

ADAPTER = LinearAdapter({'symbol': 'ETHUSDT', 'qty_step': 0.01, 'price_tick': 0.01,
                         'min_qty': 0.01, 'min_notional': 5.0, 'settle_coin': 'USDT'})
KEY = 'bybit:linear:ETHUSDT:short'
POS = {'market': 'linear', 'symbol': 'ETHUSDT', 'side': 'short', 'size': 2.0, 'entry': 3000.0,
       'mark': 2990.0, 'upnl': 20.0, 'leverage': 10.0}
NOBODY = set()                                               # no bot runs ETHUSDT short
A_BOT = {('bybit', 'linear', 'ETHUSDT', 'short')}            # a bot runs it


class _Venue:
    """What a managed trade touches: truth, a market order, the conditional
    book. A position is {idx: {side, size, avg_entry}}; Bybit hedge mode."""

    def __init__(self, positions, mark=2990.0, env='demo'):
        self.positions, self.mark, self.env = positions, mark, env
        self.orders, self.stops, self.cancels, self.book, self.n = [], [], [], [], 0

    def read_symbol_truth(self, market_type, symbol, funding_interval=480.0):
        return {'mark': self.mark, 'positions': {i: dict(p) for i, p in self.positions.items()}}

    def place_market(self, market_type, symbol, side, qty, position_idx=0, reduce_only=False,
                     link_id=None, borrow=False):
        self.orders.append((side, qty, position_idx, reduce_only, link_id))
        idx = 2 if side == 'Buy' else 1                     # a reduce-only buy closes the short
        left = self.positions[idx]['size'] - float(qty)
        if left <= 1e-12:
            del self.positions[idx]
        else:
            self.positions[idx]['size'] = left

    def set_trading_stop(self, category, symbol, position_idx, take_profit=None, stop_loss=None,
                         sl_size=None, tp_size=None, trailing_stop=None, active_price=None):
        self.stops.append({'idx': position_idx, 'tp': take_profit, 'sl': stop_loss,
                           'tp_size': tp_size, 'sl_size': sl_size})
        for kind, px, q in (('PartialTakeProfit', take_profit, tp_size),
                            ('PartialStopLoss', stop_loss, sl_size)):
            if px is not None:
                self.n += 1
                self.book.append({'orderId': f'o{self.n}', 'positionIdx': position_idx,
                                  'stopOrderType': kind, 'qty': q})

    def stop_orders(self, category, symbol):
        return [dict(o) for o in self.book]

    def cancel_order(self, category, symbol, order_id):
        self.cancels.append(order_id)
        if not any(o['orderId'] == order_id for o in self.book):
            raise VenueError('not resting', kind='gone')
        self.book = [o for o in self.book if o['orderId'] != order_id]


def _short(size=2.0, entry=3000.0):
    return {2: {'side': 'Sell', 'size': size, 'avg_entry': entry}}


def _adopted(d, run=NOBODY, pos=POS):
    from gridgremlin.managed import adopt
    path = Path(d) / 'managed-x.json'
    adopt(path, 'bybit', pos, run)
    return path, json.loads(path.read_text())[KEY]


# --- L9: adopting is a record only -------------------------------------------

def spec_L9_adopting_places_no_order_and_sets_no_exit():
    """The record says what was adopted and when; it has no exits. adopt()
    takes no client, so it cannot reach a venue at all."""
    import inspect
    from gridgremlin.managed import adopt
    assert not {'client', 'adapter'} & set(inspect.signature(adopt).parameters)
    with tempfile.TemporaryDirectory() as d:
        path, rec = _adopted(d)
        assert rec['tp'] is None and rec['sl'] is None and rec['orders'] == []
        assert rec['size'] == 2.0 and rec['entry'] == 3000.0 and rec['by'] == 'owner' and rec['adopted']
        try:
            _adopted(d)
            raise AssertionError('adopted twice')
        except Exception as e:                                          # noqa: BLE001
            assert 'already managed' in str(e)


def spec_L9_spot_and_a_side_a_bot_runs_are_not_adopted():
    from gridgremlin.managed import ManagedError, adopt
    with tempfile.TemporaryDirectory() as d:
        for pos, run, said in ((dict(POS, market='spot'), NOBODY, 'perpetual futures only'),
                               (POS, A_BOT, 'nothing is uncovered')):
            try:
                adopt(Path(d) / 'm.json', 'bybit', pos, run)
                raise AssertionError('adopted')
            except ManagedError as e:
                assert said in str(e), e
        assert not (Path(d) / 'm.json').exists()


def spec_L9_a_record_of_a_position_since_closed_or_added_to_is_not_current():
    from gridgremlin.managed import current
    rec = {'entry': 3000.0}
    assert current(rec, {'size': 1.0, 'entry': 3000.0})                 # a part closed: the entry stays
    assert not current(rec, {'size': 3.0, 'entry': 3010.0})             # an add moved it
    assert not current(rec, {'size': 0.0, 'entry': 3000.0})             # closed
    assert not current(None, POS)


# --- L10: the managed quantity is the uncovered part ---------------------------

def spec_L10_the_managed_quantity_is_the_position_less_the_bots_share():
    from gridgremlin.managed import bot_shares, uncovered
    assert uncovered(2.0, []) == 2.0
    assert abs(uncovered(2.0, [1.5]) - 0.5) < 1e-12
    assert uncovered(2.0, [1.5, 0.7]) == 0.0                            # never below nothing
    assert uncovered(2.0, [None]) == 0.0                                # unknown: nothing managed
    assert uncovered(-2.0, [-0.5]) == 1.5                               # sizes, not signs
    # I2: a bot's holding is its side's whole position, so a side a bot runs
    # leaves nothing uncovered; a side no bot runs is uncovered whole
    assert bot_shares(A_BOT, 'bybit', 'linear', 'ETHUSDT', 'short', 2.0) == [2.0]
    assert bot_shares(A_BOT, 'bybit', 'linear', 'ETHUSDT', 'long', 2.0) == []
    assert uncovered(2.0, bot_shares(A_BOT, 'bybit', 'linear', 'ETHUSDT', 'short', 2.0)) == 0.0


def spec_L10_a_bots_share_is_never_closed_or_protected():
    """With a bot on the side, a close or an exit sends nothing; on a side
    no bot runs, both act on the whole (uncovered) position."""
    from gridgremlin.managed import ManagedError, close_part, set_exits
    with tempfile.TemporaryDirectory() as d:
        path, rec = _adopted(d)
        venue = _Venue(_short())
        for act in (lambda: close_part(path, KEY, rec, venue, ADAPTER, A_BOT, 0.5),
                    lambda: close_part(path, KEY, rec, venue, ADAPTER, A_BOT),
                    lambda: set_exits(path, KEY, rec, venue, ADAPTER, A_BOT, tp=2900.0, sl=3100.0)):
            try:
                act()
                raise AssertionError('acted on a bot\'s side')
            except ManagedError as e:
                assert 'nothing uncovered' in str(e) and 'I2' in str(e), e
        assert venue.orders == [] and venue.stops == [] and venue.positions[2]['size'] == 2.0


def spec_L10_sabotage_without_the_subtraction_the_bots_share_is_closed():
    """Remove the subtraction (the uncovered part is the whole position)
    and the spec above fails: the bot's position is closed."""
    import gridgremlin.managed as m
    with tempfile.TemporaryDirectory() as d:
        path, rec = _adopted(d)
        venue = _Venue(_short())
        saved = m.uncovered
        m.uncovered = lambda size, shares: abs(size)
        try:
            m.close_part(path, KEY, rec, venue, ADAPTER, A_BOT)
        finally:
            m.uncovered = saved
    assert venue.orders and 2 not in venue.positions                 # the bot's share, gone: caught


# --- L11: the exits ----------------------------------------------------------

def spec_L11_exits_are_sized_to_the_uncovered_part_and_replace_only_their_own():
    from gridgremlin.managed import set_exits
    with tempfile.TemporaryDirectory() as d:
        path, rec = _adopted(d)
        venue = _Venue(_short())
        venue.book.append({'orderId': 'theirs', 'positionIdx': 2, 'stopOrderType': 'PartialStopLoss',
                           'qty': '1'})                              # set on the exchange by hand
        got = set_exits(path, KEY, rec, venue, ADAPTER, NOBODY, tp=2800.0, sl=3150.0)
        assert venue.stops == [{'idx': 2, 'tp': '2800', 'sl': '3150', 'tp_size': '2', 'sl_size': '2'}]
        assert got['sized'] == 2.0 and venue.orders == []           # no market order
        rec = json.loads(path.read_text())[KEY]
        assert rec['tp'] == 2800.0 and rec['sl'] == 3150.0 and sorted(rec['orders']) == ['o1', 'o2']
        set_exits(path, KEY, rec, venue, ADAPTER, NOBODY, tp=2850.0, sl=None)    # the stop off
        assert venue.cancels == ['o1', 'o2']                         # its own, never 'theirs'
        assert {o['orderId'] for o in venue.book} == {'theirs', 'o3'}
        rec = json.loads(path.read_text())[KEY]
        assert rec['sl'] is None and rec['orders'] == ['o3']


def spec_L11_an_exit_on_the_wrong_side_of_the_mark_or_a_moved_position_is_refused():
    from gridgremlin.managed import ManagedError, set_exits
    with tempfile.TemporaryDirectory() as d:
        path, rec = _adopted(d)
        for venue, kw, said in ((_Venue(_short()), {'tp': 3050.0}, 'below the mark'),
                                (_Venue(_short()), {'sl': 2900.0}, 'above the mark'),
                                (_Venue(_short(3.0, 3005.0)), {'tp': 2800.0}, 'not the one adopted')):
            try:
                set_exits(path, KEY, rec, venue, ADAPTER, NOBODY, **kw)
                raise AssertionError(kw)
            except ManagedError as e:
                assert said in str(e), e
            assert venue.stops == []


def spec_L11_hyperliquid_sets_no_exits():
    from gridgremlin.managed import ManagedError, set_exits
    try:
        set_exits('/nonexistent', 'hyperliquid:linear:ETH:short', {}, _Venue({}, env='testnet'),
                  ADAPTER, NOBODY, tp=1.0)
        raise AssertionError('set')
    except ManagedError as e:
        assert 'Hyperliquid' in str(e)


# --- L12: a close of part or all, never more than the uncovered part ----------

def spec_L12_a_close_is_one_reduce_only_order_bounded_by_the_uncovered_part():
    from gridgremlin.managed import ManagedError, close_part
    with tempfile.TemporaryDirectory() as d:
        path, rec = _adopted(d)
        venue = _Venue(_short())
        try:
            close_part(path, KEY, rec, venue, ADAPTER, NOBODY, 2.5)
            raise AssertionError('closed more than its part')
        except ManagedError as e:
            assert 'more than the uncovered 2' in str(e)
        assert venue.orders == []
        got = close_part(path, KEY, rec, venue, ADAPTER, NOBODY, 0.5)
        assert venue.orders == [('Buy', '0.5', 2, True, None)]       # reduce-only, no bot's link (I1)
        assert got['closed'] == 0.5 and got['left'] == 1.5 and KEY in json.loads(path.read_text())
        close_part(path, KEY, rec, venue, ADAPTER, NOBODY)           # the rest
        assert venue.orders[-1][:2] == ('Buy', '1.5') and 2 not in venue.positions
        assert KEY not in json.loads(path.read_text())               # all closed: the record goes


def spec_E6e_managed_an_unanswered_cancel_keeps_the_record():
    """E6e, the one caller a raw timeout guarded by accident: after the last
    close, a cancel of the trade's exits with no answer used to raise (an
    OSError) and the record stayed; as an ambiguous VenueError the old
    `except VenueError: pass` would drop the record while its exits may
    still rest. It still raises, the record kept; a plain refusal is
    passed over as before. SABOTAGE: `pass` back for every VenueError -> red."""
    from gridgremlin.managed import close_part, set_exits
    for err, kept in ((VenueError('bybit: no answer (TimeoutError)', ambiguous=True), True),
                      (VenueError('bybit: retCode 10001: params', kind='other'), False)):
        with tempfile.TemporaryDirectory() as d:
            path, rec = _adopted(d)
            venue = _Venue(_short())
            set_exits(path, KEY, rec, venue, ADAPTER, NOBODY, tp=2800.0, sl=3150.0)
            rec = json.loads(path.read_text())[KEY]

            def cancel(category, symbol, order_id, err=err):
                raise err
            venue.cancel_order = cancel
            try:
                close_part(path, KEY, rec, venue, ADAPTER, NOBODY)
                raised = False
            except VenueError:
                raised = True
            assert 2 not in venue.positions                          # the close itself went
            assert raised is kept and (KEY in json.loads(path.read_text())) is kept, err


# --- L13: Demo and Testnet only ------------------------------------------------

def spec_L13_mainnet_is_refused_whatever_the_fleet_file_says():
    from gridgremlin.managed import ManagedError, close_part, main, set_exits
    with tempfile.TemporaryDirectory() as d:
        path, rec = _adopted(d)
        venue = _Venue(_short(), env='mainnet')
        for act in (lambda: close_part(path, KEY, rec, venue, ADAPTER, NOBODY),
                    lambda: set_exits(path, KEY, rec, venue, ADAPTER, NOBODY, tp=2800.0)):
            try:
                act()
                raise AssertionError('Mainnet reached')
            except ManagedError as e:
                assert 'Demo or Testnet only' in str(e)
        assert venue.orders == [] and venue.stops == []
    assert main(['f.json', 'close', KEY, '--allow-mainnet']) == 2         # no flag opens it


def spec_L13_the_panel_refuses_an_account_that_may_reach_mainnet():
    from panel.routes import Handler
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / 'fleet.x.json'
        f.write_text(json.dumps({'allow_mainnet': True, 'bots': []}))
        h = Handler.__new__(Handler)
        h.fleets, h.labels = (str(f),), ('x',)
        shown = []
        h._page = shown.append
        h._contract = lambda fleet: (_ for _ in ()).throw(AssertionError('read past the gate'))
        h._manage_post({'fleet': '0', 'key': KEY, 'action': 'adopt', 'confirm': 'linETHUSDTs'})
        assert 'Demo or Testnet only' in shown[-1]
        assert not (Path(d) / 'logs').exists()


# --- the account's own bots, across its fleet files ----------------------------

def spec_L10_every_fleet_on_the_account_counts_as_a_bot_on_the_side():
    from spec_setup import _shipped_rows
    from gridgremlin.managed import account_run
    row = next(r for r in _shipped_rows() if r.get('market_type', 'linear') == 'linear'
               and r.get('venue', 'bybit') == 'bybit')
    with tempfile.TemporaryDirectory() as d:
        cfg = Path(d) / 'configs'
        cfg.mkdir()
        (cfg / 'fleet.a.json').write_text(json.dumps({'bots': []}))
        (cfg / 'fleet.b.json').write_text(json.dumps({'bots': [row]}))                 # same account
        (cfg / 'fleet.c.json').write_text(json.dumps({'account': 'other', 'bots': [dict(row, side='short' if row['side'] == 'long' else 'long')]}))
        run = account_run(cfg / 'fleet.a.json')
        assert ('bybit', 'linear', row['symbol'], row['side']) in run
        assert not any(s != row['side'] for _, _, sym, s in run if sym == row['symbol'])
        (cfg / 'fleet.d.json').write_text('{not json')
        try:
            account_run(cfg / 'fleet.a.json')
            raise AssertionError('an unreadable fleet beside it was ignored')
        except Exception as e:                                               # noqa: BLE001
            assert 'fleet.d.json' in str(e)


# --- U179–U180: the panel ------------------------------------------------------

def _contract(managed=None, age_s=5):
    return {'generated_ms': int((time.time() - age_s) * 1000),
            'account': {'bybit': {'tier': 'demo', 'positions': [POS]}},
            'account_change': {'bybit': {'windows': {}, 'not_from_a_bot': [POS]}},
            'managed': managed or {}}


def spec_U179_each_position_no_bot_runs_links_to_its_trade_manager():
    from panel.strip_view import account_change_lines
    out = account_change_lines(_contract(), idx=1)
    assert '<a href="/manage?fleet=1&amp;key=bybit%3Alinear%3AETHUSDT%3Ashort">manage</a>' in out, out
    assert '<form' not in out                                             # a link; the writes are its page's
    done = account_change_lines(_contract({KEY: {'entry': 3000.0, 'tp': 2800.0, 'sl': None}}), idx=1)
    assert '>managed</a> · TP 2,800 · SL —' in done
    stale = account_change_lines(_contract({KEY: {'entry': 3100.0, 'tp': 2800.0}}), idx=1)
    assert '>manage</a>' in stale and 'TP' not in stale                   # another position's record
    assert '/manage' not in account_change_lines(_contract())             # no index (an export): no link


def _handler(d, armed=True, fleet=None):
    from panel.routes import Handler
    f = Path(d) / 'configs' / 'fleet.x.json'
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(fleet or {'bots': []}))
    h = Handler.__new__(Handler)
    h.fleets, h.labels = (str(f),), ('demo',)
    h.units = ('gg-x',) if armed else ()
    shown, runs = [], []
    h._page = shown.append
    h._deny = lambda code, why: shown.append(f'{code} {why}')
    h._contract = lambda fleet: _contract()
    h._run_managed = lambda fi, action, key, **kw: runs.append((action, key, kw)) or (
        {'key': key, 'sized': 2.0, 'tp': kw.get('tp'), 'sl': kw.get('sl')} if action == 'exits'
        else {'key': key, 'closed': kw.get('qty') or 2.0, 'left': 0.0})
    return h, f, shown, runs


def spec_U180_the_trade_manager_names_the_market_fully_and_every_write_is_typed():
    from gridgremlin.managed import managed_path
    with tempfile.TemporaryDirectory() as d:
        h, f, shown, runs = _handler(d)
        h.path = f'/manage?fleet=0&key={KEY}'
        h._manage_page()
        page = shown[-1]
        assert 'ETHUSDT Perpetual Futures Trade · SHORT' in page and 'not covered by a bot <b>2</b>' in page
        assert 'Adopting places no order' in page and 'class="ggconfirm"' in page     # D159's pop-up
        h._manage_post({'fleet': '0', 'key': KEY, 'action': 'adopt', 'confirm': 'yes'})
        assert 'not done' in shown[-1] and not managed_path(f).exists()           # a click is not a decision
        h._manage_post({'fleet': '0', 'key': KEY, 'action': 'adopt',
                        'confirm': 'ETHUSDT Perpetual Futures Trade short'})
        assert 'No order was placed' in shown[-1] and runs == []                  # L9: no command run
        assert KEY in json.loads(managed_path(f).read_text())
        h._manage_page()
        page = shown[-1]
        assert 'set exits' in page and 'close at market' in page and page.count('class="ggconfirm"') == 2
        h._manage_post({'fleet': '0', 'key': KEY, 'action': 'exits', 'tp': '2,800', 'sl': ''})
        assert 'not done' in shown[-1] and runs == []
        h._manage_post({'fleet': '0', 'key': KEY, 'action': 'exits', 'tp': '2,800', 'sl': '',
                        'confirm': 'linETHUSDTs'})
        assert runs[-1] == ('exits', KEY, {'tp': 2800.0, 'sl': None}) and 'exits set' in shown[-1]
        h._manage_post({'fleet': '0', 'key': KEY, 'action': 'close', 'qty': '2.5',
                        'confirm': 'ETHUSDT trade short'})
        assert 'more than the 2 no bot covers' in shown[-1] and len(runs) == 1
        h._manage_post({'fleet': '0', 'key': KEY, 'action': 'close', 'qty': '0.5',
                        'confirm': 'ETHUSDT trade short'})
        assert runs[-1] == ('close', KEY, {'qty': 0.5})


def spec_U180_venue_writes_need_control_and_a_bots_side_is_not_managed():
    from spec_setup import _shipped_rows
    row = next(r for r in _shipped_rows() if r.get('market_type', 'linear') == 'linear'
               and r.get('venue', 'bybit') == 'bybit')
    with tempfile.TemporaryDirectory() as d:
        h, f, shown, runs = _handler(d, armed=False)
        h._manage_post({'fleet': '0', 'key': KEY, 'action': 'adopt', 'confirm': 'linETHUSDTs'})
        h._manage_post({'fleet': '0', 'key': KEY, 'action': 'close', 'confirm': 'linETHUSDTs'})
        assert shown[-1].startswith('404') and runs == []
    with tempfile.TemporaryDirectory() as d:
        pos = dict(POS, symbol=row['symbol'], side=row['side'])
        key = f"bybit:linear:{row['symbol']}:{row['side']}"
        h, f, shown, runs = _handler(d, fleet={'bots': [row]})
        h._contract = lambda fleet: dict(_contract(), account={'bybit': {'tier': 'demo', 'positions': [pos]}})
        h.path = f'/manage?fleet=0&key={key}'
        h._manage_page()
        assert 'not covered by a bot <b>0</b>' in shown[-1] and 'manage it' not in shown[-1]
        h._manage_post({'fleet': '0', 'key': key, 'action': 'adopt', 'confirm': f"lin{row['symbol']}{row['side'][0]}"})
        assert 'nothing is uncovered' in shown[-1]
