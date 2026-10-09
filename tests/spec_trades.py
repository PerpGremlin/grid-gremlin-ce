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
