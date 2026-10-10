"""N (D81): a single trade — a one-round DCA row with no safety orders, in
the fleet's trades file, joining a running fleet live."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from gridgremlin.config import ConfigError, validate_config
from gridgremlin.events import Notifier
from gridgremlin.trades import (TradeError, TradeWatch, add_trade, clear_trade,
                                load_trades, validate_trade)

ROW = {'symbol': 'BTCUSDT', 'side': 'long', 'capital': 500.0, 'leverage': 5,
       'take_profit_avg_pct': 0.015, 'stop': {'watch': 'mark_price', 'from_base_pct': 0.02}}


def _refused(fn, *a):
    try:
        fn(*a)
    except (ConfigError, TradeError) as e:
        return str(e)
    raise AssertionError(f'{a} was accepted')


def spec_L2_a_trade_is_a_one_round_dca_row_with_no_safety_orders():
    """The whole trade is its base order (capital x leverage unless stated),
    no safety ladder, repeat off; a DCA bot's ladder keys are refused by
    name, and the exit is still required (M3)."""
    cfg = validate_trade(dict(ROW))
    assert cfg['trade'] is True and cfg['max_averaging_orders'] == 0 and cfg['repeat'] is False
    assert cfg['base_order_size'] == 2500.0 and cfg['stop']['from_base_pct'] == 0.02
    assert validate_trade(dict(ROW, base_order_size=1000.0))['base_order_size'] == 1000.0
    assert 'repeat' in _refused(validate_trade, dict(ROW, repeat=True))
    assert 'safety_order_size' in _refused(validate_trade, dict(ROW, safety_order_size=100))
    assert 'max_averaging_orders' in _refused(validate_trade, dict(ROW, max_averaging_orders=2))
    no_exit = {k: v for k, v in ROW.items() if k != 'take_profit_avg_pct'}
    assert 'never without an exit' in _refused(validate_trade, no_exit)
    assert 'one-round DCA row' in _refused(validate_trade, dict(ROW, strategy='grid'))
    rec = validate_trade(dict(ROW, opened='2026-10-09T14:00:00Z', by='owner', reason='x'))
    assert rec['_record'] == {'opened': '2026-10-09T14:00:00Z', 'by': 'owner', 'reason': 'x'}
    # a DCA bot without the mark still needs its whole ladder
    assert 'required' in _refused(validate_config, dict(ROW, strategy='martingale'))


def spec_L2_a_trade_enters_places_only_its_exit_and_stands_down_at_its_take_profit():
    """The real Bot on the test venue: the base fills at market, the TP is
    set, no safety order ever rests, and the TP closing the position ends
    the trade (repeat off, M5)."""
    from gridgremlin.bot import Bot
    from spec_round import ADAPTER, FakeVenue
    venue, lines = FakeVenue(), []
    bot = Bot(validate_trade(dict(ROW, take_profit_avg_pct=0.01)), ADAPTER, venue,
              Notifier(sink=lines.append), gen_seed=1)
    assert bot.cycle() == {'round_started': 1}
    assert venue.position and venue.orders == []
    counts = bot.cycle()
    assert venue.tp_calls and abs(venue.tp_calls[0] - 60000.0 * 1.01) < 0.11
    assert [o for o in venue.orders if o['side'] == 'Buy'] == [] and counts['desired'] == 0
    venue.position = None                                     # the TP filled
    bot.cycle()
    assert bot.alive is False and any('round complete' in ln for ln in lines)


def spec_L3_the_trades_file_refuses_a_taken_market_side_and_clears_a_finished_trade():
    d = Path(tempfile.mkdtemp())
    path = d / 'trades-x.json'
    grid = validate_config({'market_type': 'linear', 'symbol': 'ETHUSDT', 'side': 'long', 'capital': 100.0, 'leverage': 5,
                            'upper': 3000.0, 'lower': 2000.0, 'rungs': 11})
    assert add_trade(path, [grid], dict(ROW)) == 'linBTCUSDTl'
    rows = json.loads(path.read_text())
    assert rows[0]['symbol'] == 'BTCUSDT' and rows[0]['by'] == 'owner' and rows[0]['opened'].endswith('Z')
    assert 'already in the file' in _refused(add_trade, path, [grid], dict(ROW))
    assert 'one position per side' in _refused(add_trade, path, [grid], dict(ROW, symbol='ETHUSDT'))
    assert add_trade(path, [grid], dict(ROW, side='short')) == 'linBTCUSDTs'
    trades, refused = load_trades(path)
    assert [t['side'] for t in trades] == ['long', 'short'] and refused == []
    tp = d / 'tombstones-x.json'
    tp.write_text(json.dumps({'linBTCUSDTl': {'reason': 'round complete (TP hit), repeat off'}}))
    assert clear_trade(path, 'linBTCUSDTl', tp)['side'] == 'long'
    assert json.loads(tp.read_text()) == {}                    # its tombstone goes with it
    assert [t['side'] for t in load_trades(path)[0]] == ['short']
    assert clear_trade(path, 'linXRPUSDTl') is None
    path.write_text('{bad')
    assert 'unreadable' in _refused(load_trades, path)
    path.write_text(json.dumps([dict(ROW, repeat=True), dict(ROW, side='short')]))
    ok, bad = load_trades(path)
    assert len(ok) == 1 and bad[0][0] == 0 and 'repeat' in bad[0][1]


def spec_L1_a_new_trade_joins_the_running_fleet_within_a_cycle():
    """The watch builds each new trade with the fleet's own builder and
    appends it to the running bots; an unchanged file costs one stat; a
    venue the fleet has no client for, a builder's refusal and a position
    another bot holds are each said and refused."""
    import os
    d = Path(tempfile.mkdtemp())
    path = d / 'trades-x.json'
    lines, bots, idents, built = [], [], [('linETHUSDTl', ('linear', 'ETHUSDT', 1))], []

    class B:
        def __init__(self, cfg):
            self.cfg, self.botid = cfg, f"lin{cfg['symbol']}{cfg['side'][0]}"

    def build(cfg):
        built.append(cfg['symbol'])
        if cfg['symbol'] == 'BADUSDT':
            raise ValueError('no such instrument')
        return B(cfg), ('linear', cfg['symbol'], 1 if cfg['side'] == 'long' else 2)

    w = TradeWatch(path, bots, idents, build, Notifier(sink=lines.append), {'bybit': object()})
    assert w.poll() is None                                   # no file yet: nothing
    path.write_text(json.dumps([dict(ROW)]))
    assert w.poll() == {'linBTCUSDTl': 'built'} and [b.botid for b in bots] == ['linBTCUSDTl']
    assert any('trade opened live: long BTCUSDT 500 at 5x (L1)' in ln for ln in lines)
    assert w.poll() is None and built == ['BTCUSDT']           # unchanged: one stat, no build
    path.write_text(json.dumps([dict(ROW), dict(ROW, symbol='BADUSDT'), dict(ROW, venue='hyperliquid', symbol='SOL')]))
    os.utime(path, (1, 2))
    out = w.poll()
    assert out == {'linBADUSDTl': 'refused', 'linSOLl': 'refused'} and len(bots) == 1
    assert any('trade not built: ValueError' in ln for ln in lines)
    assert any('does not trade — refused' in ln for ln in lines)
    w.identities.append(('other', ('linear', 'XRPUSDT', 1)))
    path.write_text(json.dumps([dict(ROW), dict(ROW, symbol='XRPUSDT')]))
    os.utime(path, (3, 4))
    assert w.poll() == {'linXRPUSDTl': 'refused'} and any("another bot's" in ln for ln in lines)


def spec_L1_the_fleet_file_watch_leaves_trades_alone():
    """A trade is not in the fleet file, so the file watch must not call it
    removed every time the file changes."""
    from gridgremlin.reload import FleetWatch
    d = Path(tempfile.mkdtemp())
    f = d / 'fleet.json'
    f.write_text(json.dumps({'bots': [{'market_type': 'linear', 'symbol': 'ETHUSDT', 'side': 'long', 'capital': 100.0, 'leverage': 5,
                                       'upper': 3000.0, 'lower': 2000.0, 'rungs': 11}]}))

    class T:
        botid, cfg = 'linBTCUSDTl', validate_trade(dict(ROW))
    lines = []
    w = FleetWatch(f, [T()], {}, Notifier(sink=lines.append))
    w.apply()
    assert not any('linBTCUSDTl' in ln and 'removed from the file' in ln for ln in lines)


def spec_L4_the_owners_command_builds_the_trade_from_plain_words():
    from gridgremlin.trade import build_row, _opts
    row = build_row('short', 'ethusdt', _opts(['--capital', '300', '--tp', '2', '--leverage', '3',
                                               '--stop', '1.5', '--trail', '0.4', '--trail-from', '1',
                                               '--maker']))
    assert row == {'symbol': 'ETHUSDT', 'side': 'short', 'capital': 300.0, 'take_profit_avg_pct': 0.02,
                   'leverage': 3.0, 'stop': {'watch': 'mark_price', 'from_base_pct': 0.015},
                   'trailing_stop_pct': 0.004, 'trailing_activation_pct': 0.01, 'start_order_type': 'maker'}
    validate_trade(row)                                         # the validator takes what the command builds
    assert 'required' in _refused(build_row, 'long', 'BTCUSDT', {'capital': '1'})
    assert 'long or short' in _refused(build_row, 'up', 'BTCUSDT', {'capital': '1', 'tp': '1'})
    assert 'needs a value' in _refused(_opts, ['--tp'])


def spec_L5_every_reader_sees_a_trade_as_the_bot_it_is():
    """The readout, the kept ledger, the digest, the market readings and the
    close command read the fleet with its open trades among its rows; a
    trade a config row already covers is not added twice; an unreadable
    trades file adds nothing (the engine refuses to build beside it)."""
    import inspect
    from gridgremlin import close, digest, kept_fills, market, report
    from gridgremlin.trades import with_trades
    d = Path(tempfile.mkdtemp())
    (d / 'configs').mkdir()
    f = d / 'configs' / 'fleet.x.json'
    grid = {'market_type': 'linear', 'symbol': 'ETHUSDT', 'side': 'long', 'capital': 100.0, 'leverage': 5,
            'upper': 3000.0, 'lower': 2000.0, 'rungs': 11}
    fleet = {'bots': [validate_config(grid)], 'account': 'default'}
    assert with_trades(f, fleet) is fleet                              # no file: the fleet as it was
    (d / 'logs').mkdir()
    (d / 'logs' / 'trades-x.json').write_text(json.dumps([dict(ROW), dict(ROW, symbol='ETHUSDT')]))
    out = with_trades(f, fleet)
    syms = [(c['symbol'], bool(c.get('trade'))) for c in out['bots']]
    assert syms == [('ETHUSDT', False), ('BTCUSDT', True)]               # ETHUSDT long is the grid's
    assert out['bots'][1]['account'] == 'default' and fleet['bots'] == [fleet['bots'][0]]
    (d / 'logs' / 'trades-x.json').write_text('{bad')
    assert with_trades(f, fleet) is fleet
    for mod in (report, kept_fills, digest, market, close):
        assert 'with_trades(' in inspect.getsource(mod), mod.__name__


def spec_L6_a_trades_card_says_it_is_a_trade_with_its_exit_and_offers_its_close():
    import copy
    from panel.render import kind_line
    from panel.server import render
    sys.path.insert(0, str(Path(__file__).parent))
    from spec_panel import CONTRACT
    t = {'market_type': 'linear', 'strategy': 'martingale', 'leverage': 3, 'trade': True,
         'tp_pct': 0.006, 'stop_pct': 0.006, 'trail_pct': None, 'opened': '2026-10-09T14:01:00Z', 'by': 'owner'}
    line = kind_line(t)
    assert line.startswith('trade on futures') and 'take profit +0.6%' in line and 'stop −0.6% at the mark' in line
    assert 'opened 2026-10-09 14:01 by owner' in line
    c = copy.deepcopy(CONTRACT)
    bot = 'linBTCUSDTl'                                   # a linear trade: spot is never offered a close
    c['bots'][bot] = dict(next(v for v in c['bots'].values() if v), side='long', strategy='martingale')
    c.setdefault('terms', {})[bot] = t
    c['watchdog']['belief']['bots'][bot] = {'alive': True, 'position': 1.0}
    html = render([('demo', c)])
    assert 'BTCUSDT long trade' in html
    assert f"href='/close?fleet=0&bot={bot}'>close trade</a>" in html
    c['watchdog']['belief']['bots'][bot] = {'alive': False, 'position': None}
    assert "<a href='/trade'>clear</a>" in render([('demo', c)])


def spec_L6_the_panels_trade_form_opens_refuses_with_the_typing_kept_and_clears():
    """The owner's door on the panel: the form, a refusal that keeps what was
    typed, a trade queued in the account's trades file through the bot
    validator, and the clear of an ended one by its typed name."""
    from spec_setup import _call, _served_fleet
    base, d, close = _served_fleet()
    try:
        page = _call(base, '/trade')
        assert '<h1>new trade' in page and 'name="tp"' in page and 'name="stop"' in page and 'no trades' in page
        for field in ('symbol', 'capital', 'leverage', 'tp', 'stop', 'trail', 'trail_from', 'maker'):
            assert f'name="{field}"' in page, field                    # the form reaches every trade term
        refused = _call(base, '/trade', {'action': 'open', 'fleet': '0', 'side': 'long', 'symbol': 'BTCUSDT',
                                         'capital': '200', 'leverage': '3'})
        assert 'trade refused' in refused and 'required' in refused and 'value="200"' in refused
        taken = _call(base, '/trade', {'action': 'open', 'fleet': '0', 'side': 'long', 'symbol': 'ETHUSDT',
                                       'capital': '200', 'tp': '1'})
        assert 'one position per side' in taken
        ok = _call(base, '/trade', {'action': 'open', 'fleet': '0', 'side': 'long', 'symbol': 'btcusdt',
                                    'capital': '200', 'leverage': '3', 'tp': '0.6', 'stop': '0.6', 'maker': '1'})
        assert 'linBTCUSDTl: queued' in ok
        rows = json.loads((d / 'logs' / 'trades-f.json').read_text())
        assert rows[0]['symbol'] == 'BTCUSDT' and rows[0]['start_order_type'] == 'maker' and rows[0]['by'] == 'owner'
        listed = _call(base, '/trade')
        assert 'linBTCUSDTl' in listed and 'long BTCUSDT 200 at 3x' in listed
        wrong = _call(base, '/trade', {'action': 'clear', 'fleet': '0', 'confirm': 'linXRPUSDTl'})
        assert 'not a trade' in wrong
        cleared = _call(base, '/trade', {'action': 'clear', 'fleet': '0', 'confirm': 'linBTCUSDTl'})
        assert 'linBTCUSDTl: cleared' in cleared and json.loads((d / 'logs' / 'trades-f.json').read_text()) == []
    finally:
        close()


def spec_L1_a_live_trade_sets_its_symbols_leverage_as_the_start_does():
    """The first live trade margined at the venue's old 10x while it stated
    3x: the live path skipped the start's per-symbol pass. It runs it now,
    for the trade's symbol, with every leg already there."""
    import gridgremlin.main as m
    seen = []
    saved = m.build_market_bot, m._ensure_symbol_capacity

    class Bot:
        def __init__(self, sym):
            self.cfg, self.botid = {'symbol': sym, 'venue': 'bybit'}, 'x'
    try:
        m.build_market_bot = lambda cfg, client, notifier, tombs, slide: (Bot(cfg['symbol']), ('linear', cfg['symbol'], 1))
        m._ensure_symbol_capacity = lambda bots, notifier: seen.append(sorted(b.cfg['symbol'] for b in bots))
        fleet = {'account': 'default', '_tombs': None, '_slide': None}
        others = [Bot('BTCUSDT'), Bot('ETHUSDT')]
        bot, ident = m.build_live_trade({'symbol': 'BTCUSDT', 'venue': 'bybit'}, fleet, {'bybit': object()}, others, None)
        assert ident == ('linear', 'BTCUSDT', 1) and seen == [['BTCUSDT', 'BTCUSDT']]   # the other BTC leg and the trade
    finally:
        m.build_market_bot, m._ensure_symbol_capacity = saved


def spec_L6_a_trades_rate_line_says_profit_not_grid_profit():
    from panel.render import run_rate
    gen = 10 * 86_400_000
    b = {'fills': 2, 'realized': 3.0, 'fees': 0.14, 'counted_from': 'flat', 'counted_since_ms': gen - 86_400_000}
    t = run_rate(b, {'generated_ms': gen, 'window_hours': 24}, 200.0, trade=True)
    assert 'grid' not in t and ' profit <b' in t and ' APR <b' in t
    assert 'grid profit' in run_rate(b, {'generated_ms': gen, 'window_hours': 24}, 200.0)


# --- L7: the close request -------------------------------------------------------------

def spec_L7_a_close_request_rides_in_the_trades_record_and_the_first_stands():
    from gridgremlin.tombstones import Tombstones
    from gridgremlin.trades import request_close, trade_status
    d = Path(tempfile.mkdtemp())
    path = d / 'trades-x.json'
    add_trade(path, [], dict(ROW))
    tombs = Tombstones(str(d / 'tombstones-x.json'))
    assert trade_status(path, 'linBTCUSDTl', tombs) == 'live' and trade_status(path, 'linXRPUSDTl', tombs) is None
    req = request_close(path, 'linBTCUSDTl', 'owner', 'done for the day')
    assert req['by'] == 'owner' and req['t'].endswith('Z')
    assert request_close(path, 'linBTCUSDTl', 'agent', 'later')['by'] == 'owner'   # the first stands
    trades, refused = load_trades(path)
    assert refused == [] and trades[0]['_record']['close']['reason'] == 'done for the day'
    assert 'close' not in trades[0] and 'nothing to close' in _refused(request_close, path, 'linXRPUSDTl', 'x')
    tombs.add('linBTCUSDTl', 'closed on request')
    assert trade_status(path, 'linBTCUSDTl', tombs) == 'ended'


def spec_L7_the_fleet_hands_a_close_request_to_the_running_trade_once_restart_included():
    import os
    from gridgremlin.trades import request_close
    d = Path(tempfile.mkdtemp())
    path = d / 'trades-x.json'
    add_trade(path, [], dict(ROW))

    class B:
        botid, alive, close_request = 'linBTCUSDTl', True, None
    bot, lines = B(), []
    w = TradeWatch(path, [bot], [], None, Notifier(sink=lines.append), {'bybit': object()})
    assert bot.close_request is None
    request_close(path, 'linBTCUSDTl', 'owner', 'enough')
    os.utime(path, (5, 6))
    w.poll()
    assert bot.close_request['by'] == 'owner' and sum('close requested by owner' in ln for ln in lines) == 1
    os.utime(path, (7, 8))
    w.poll()
    assert sum('close requested' in ln for ln in lines) == 1                # once
    fresh = B()                                                             # a restart: the request stands
    TradeWatch(path, [fresh], [], None, Notifier(sink=lines.append), {'bybit': object()})
    assert fresh.close_request['reason'] == 'enough'


def spec_L7_a_trade_asked_to_close_flattens_under_its_own_link_and_stands_down():
    """Sabotage: a bot that ignores close_request keeps its position and
    lives — this spec then fails on the market order and the tombstone."""
    from gridgremlin.bot import Bot
    from gridgremlin.tombstones import Tombstones
    from spec_round import ADAPTER, FakeVenue
    venue, lines = FakeVenue(), []
    tombs = Tombstones(str(Path(tempfile.mkdtemp()) / 't.json'))
    bot = Bot(validate_trade(dict(ROW, take_profit_avg_pct=0.01)), ADAPTER, venue,
              Notifier(sink=lines.append), gen_seed=1, tombstones=tombs)
    bot.cycle()
    bot.cycle()
    assert venue.position and bot.alive
    bot.close_request = {'t': 'now', 'by': 'owner', 'reason': 'enough'}
    assert bot.cycle() is None
    assert venue.position is None and bot.alive is False
    assert tombs.has('linBTCUSDTl') and 'closed on request by owner: enough (L7)' in Path(tombs.path).read_text()
    assert venue.orders == []


def spec_L7_the_panels_close_trade_asks_the_fleet_for_a_running_trade():
    from panel.server import Handler
    from spec_setup import _call, _served_fleet
    base, d, close = _served_fleet()
    saved = Handler.units
    try:
        Handler.units = ('some.service',)
        assert 'linBTCUSDTl: queued' in _call(base, '/trade', {
            'action': 'open', 'fleet': '0', 'side': 'long', 'symbol': 'BTCUSDT',
            'capital': '200', 'leverage': '3', 'tp': '0.6', 'stop': '0.6'})
        page = _call(base, '/close?fleet=0&bot=linBTCUSDTl')
        assert 'close trade linBTCUSDTl' in page and 'sent by the trade itself' in page
        assert 'not closed' in _call(base, '/close', {'fleet': '0', 'bot': 'linBTCUSDTl', 'confirm': 'yes'})
        done = _call(base, '/close', {'fleet': '0', 'bot': 'linBTCUSDTl', 'confirm': 'linBTCUSDTl'})
        assert 'linBTCUSDTl: close requested' in done
        row = json.loads((d / 'logs' / 'trades-f.json').read_text())[0]
        assert row['close']['by'] == 'owner' and row['close']['reason'] == 'close trade on the panel'
    finally:
        Handler.units = saved
        close()

