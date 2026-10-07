# Specs for SPEC X1-X6 — every stop path with its on-venue residue stated.

from gridgremlin.adapters import LinearAdapter
from gridgremlin.bot import Bot
from gridgremlin.config import ConfigError, validate_config
from gridgremlin.events import Notifier

from spec_loop import FakeVenue

ADAPTER = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001,
                         'price_tick': 0.1, 'min_qty': 0.001,
                         'min_notional': 5.0, 'settle_coin': 'USDT'})


def _cfg(**over):
    row = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
           'capital': 1000.0, 'leverage': 10, 'upper': 70000.0,
           'lower': 50000.0, 'rungs': 21, 'spacing_type': 'fixed'}
    row.update(over)
    return validate_config(row)


def _bot(venue, lines, **over):
    return Bot(_cfg(**over), ADAPTER, venue, Notifier(sink=lines.append),
               gen_seed=1)


def _holding(venue, size='0.021', avg='63000', **extra):
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': size,
                      'avgPrice': avg, 'leverage': '10',
                      'unrealisedPnl': '0', **extra}


# --- X2: the watch matrix ----------------------------------------------------

def spec_X2_mark_price_fires_on_the_losing_side_only():
    venue, lines = FakeVenue(mark=61000.0), []
    _holding(venue)
    bot = _bot(venue, lines, stop={'watch': 'mark_price', 'level': 58000})
    bot.cycle()
    assert bot.alive                                   # above the level: lives
    venue.mark = 57900.0
    bot.cycle()
    assert not bot.alive                               # crossed: fires


def spec_X2_account_equity_fires_on_the_shared_pool():
    venue, lines = FakeVenue(), []
    _holding(venue)
    bot = _bot(venue, lines, stop={'watch': 'account_equity', 'level': 2500})
    bot.cycle(equity=3000.0)
    assert bot.alive
    bot.cycle(equity=2400.0)
    assert not bot.alive


def spec_X2_equity_unknown_is_not_a_breach():
    venue, lines = FakeVenue(), []
    _holding(venue)
    bot = _bot(venue, lines, stop={'watch': 'account_equity', 'level': 2500})
    bot.cycle(equity=None)
    assert bot.alive                                   # absence never fires


def spec_X2_position_sl_respects_the_hand_placed_stop():
    venue, lines = FakeVenue(mark=61000.0), []
    _holding(venue, stopLoss='58000')                  # the operator's, on-venue
    bot = _bot(venue, lines, stop={'watch': 'position_sl'})
    bot.cycle()
    assert bot.alive
    venue.mark = 57950.0
    bot.cycle()
    assert not bot.alive
    kill = next(ln for ln in lines if ' kill ' in ln)
    assert 'yours, on the venue' in kill


def spec_X2_position_sl_with_no_venue_stop_never_fires():
    venue, lines = FakeVenue(mark=100.0), []           # mark in the basement
    _holding(venue)
    bot = _bot(venue, lines, stop={'watch': 'position_sl'})
    bot.cycle()
    assert bot.alive                                   # absence is not a breach


# --- X1/X5/X6: fire — flatten grid inventory, floor survives -----------------

def spec_X6_the_floor_core_survives_a_stop():
    venue, lines = FakeVenue(mark=57000.0), []
    _holding(venue, size='0.035')                      # 5 lots: 2 floored + 3 grid
    bot = _bot(venue, lines, min_position_base=0.014,
               stop={'watch': 'mark_price', 'level': 58000})
    bot.cycle()
    assert not bot.alive
    assert venue.position is not None                  # the stack lives
    assert abs(float(venue.position['size']) - 0.014) < 1e-9
    kill = next(ln for ln in lines if ' kill ' in ln)
    assert 'floor core 0.014 REMAINS' in kill          # X4: residue stated


def spec_X1_no_floor_flattens_everything_and_cancels():
    venue, lines = FakeVenue(mark=61000.0), []
    _holding(venue)
    bot = _bot(venue, lines, stop={'watch': 'mark_price', 'level': 58000})
    bot.cycle()                                        # ladder rests
    assert venue.orders
    venue.mark = 57000.0
    bot.cycle()
    assert venue.position is None                      # flat (D1: the off button)
    assert venue.orders == []                          # X5: owned orders cancelled
    kill = next(ln for ln in lines if ' kill ' in ln)
    assert 'position flat' in kill and 'nothing owned rests' in kill
    assert bot.cycle() is None                         # dead bots stay dead


# --- X3: server-side — the venue holds it, sized to the scope ----------------

def spec_X3_server_side_rests_on_the_venue_sized_to_inventory():
    venue, lines = FakeVenue(mark=63000.0), []
    _holding(venue, size='0.035')
    bot = _bot(venue, lines, min_position_base=0.014,
               stop={'watch': 'mark_price', 'level': 58000,
                     'server_side': True})
    bot.cycle()
    level, size = venue.sl_calls[0]
    assert level == 58000.0
    assert abs(size - 0.021) < 1e-9                    # partial: X6's scope
    assert venue.position['stopLoss'] == '58000'       # survives this process
    bot.cycle()
    assert len(venue.sl_calls) == 1                    # the venue already agrees


def spec_X3_server_side_resizes_as_the_position_grows():
    venue, lines = FakeVenue(mark=63000.0), []
    _holding(venue, size='0.021')
    bot = _bot(venue, lines,
               stop={'watch': 'mark_price', 'level': 58000,
                     'server_side': True})
    bot.cycle()
    _holding(venue, size='0.028',                      # a fill deepened it
             stopLoss=venue.position['stopLoss'])
    bot.cycle()
    assert len(venue.sl_calls) == 1                    # full-mode: level unchanged


def spec_X3_refusals():
    for stop in ({'watch': 'account_equity', 'level': 2500, 'server_side': True},
                 {'watch': 'position_sl', 'server_side': True}):
        try:
            _cfg(stop=stop)
        except ConfigError as e:
            assert 'server_side' in str(e)
        else:
            raise AssertionError(f'accepted: {stop}')
    try:
        _cfg(market_type='spot', side='long', leverage=None,
             stop={'watch': 'mark_price', 'level': 1500, 'server_side': True})
    except ConfigError as e:
        assert 'hosts' in str(e)
    else:
        raise AssertionError('spot server-side stop accepted')


# --- the martingale's stop: whole position (no floor concept) ----------------

def spec_X6_martingale_stop_flattens_the_whole_round():
    venue, lines = FakeVenue(mark=59000.0), []
    _holding(venue, size='0.016', avg='60000')
    mcfg = validate_config({'strategy': 'martingale', 'market_type': 'linear',
                            'symbol': 'BTCUSDT', 'side': 'long',
                            'capital': 1000.0, 'leverage': 10,
                            'base_order_size': 500.0, 'safety_order_size': 250.0,
                            'deviation_pct': 0.01, 'max_averaging_orders': 2,
                            'take_profit_avg_pct': 0.01,
                            'stop': {'watch': 'mark_price', 'level': 59500}})
    bot = Bot(mcfg, ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1)
    bot.cycle()
    assert not bot.alive and venue.position is None


# --- I5: the flatten order carries our identity ------------------------------

def spec_I5_the_flatten_order_carries_an_owned_link():
    from gridgremlin.apply import rung_of
    venue, lines = FakeVenue(mark=61000.0), []
    _holding(venue)
    bot = _bot(venue, lines, stop={'watch': 'mark_price', 'level': 58000})
    bot.cycle()
    venue.mark = 57000.0
    bot.cycle()
    assert not bot.alive
    assert rung_of(venue.market_links[-1], bot.botid) == 0


# --- X7: a fired stop survives the process -----------------------------------

def spec_X7_tombstone_lands_BEFORE_the_flatten():
    import tempfile
    from pathlib import Path as _P
    from gridgremlin.tombstones import Tombstones
    tmp = _P(tempfile.mkdtemp()) / 'tombs.json'
    order = []

    class Sequenced(FakeVenue):
        def place_market(self, *a, **kw):
            order.append('flatten')
            return super().place_market(*a, **kw)

    class Watching(Tombstones):
        def add(self, botid, reason):
            order.append('tombstone')
            super().add(botid, reason)

    venue, lines = Sequenced(mark=61000.0), []
    _holding(venue)
    bot = _bot(venue, lines, stop={'watch': 'mark_price', 'level': 58000})
    bot.tombs = Watching(tmp)
    bot.cycle()
    venue.mark = 57000.0
    bot.cycle()
    assert order[:2] == ['tombstone', 'flatten']   # durable FIRST
    fresh = Tombstones(tmp)                        # a new process
    assert fresh.has(bot.botid)
    assert 'mark_price' in fresh.reason(bot.botid)


def spec_X7_external_close_also_tombstones():
    import tempfile
    from pathlib import Path as _P
    from gridgremlin.tombstones import Tombstones
    tmp = _P(tempfile.mkdtemp()) / 'tombs.json'
    venue, lines = FakeVenue(), []
    bot = _bot(venue, lines)
    bot.tombs = Tombstones(tmp)
    bot.cycle()
    buy = next(o for o in venue.orders if o['side'] == 'Buy')
    venue.fill(buy['order_id'], buy['price'])
    bot.cycle()                                    # holding now
    venue.position = None                          # owner closes it by hand
    for _ in range(3):                             # E9: confirmed, not guessed
        bot.cycle()
    assert not bot.alive
    assert Tombstones(tmp).has(bot.botid)


# --- audit H2/H3: the conditional book is resized and respected --------------

def spec_X3_partial_SL_resizes_when_the_position_grows():
    venue, lines = FakeVenue(mark=61000.0), []
    _holding(venue, size='0.035')
    bot = _bot(venue, lines, min_position_base=0.014,
               stop={'watch': 'mark_price', 'level': 58000,
                     'server_side': True})
    bot.cycle()
    assert venue.sl_calls[-1] == (58000.0, 0.021)     # sized to inventory
    venue.position = dict(venue.position, size='0.060')   # grows, SL kept
    bot.cycle()
    assert venue.sl_calls[-1] == (58000.0, 0.046)     # H2: RE-SIZED
    book = venue.stop_orders('linear', 'BTCUSDT')
    sls = [o for o in book if 'StopLoss' in o['stopOrderType']]
    assert len(sls) == 1                              # stale one CANCELLED
    n = len(venue.sl_calls)
    bot.cycle()
    assert len(venue.sl_calls) == n                   # level+size agree: quiet


def spec_I1_foreign_conditionals_are_never_cancelled():
    row = {'strategy': 'martingale', 'market_type': 'linear',
           'symbol': 'BTCUSDT', 'side': 'long', 'capital': 1000.0,
           'leverage': 10, 'base_order_size': 1000.0,
           'safety_order_size': 1000.0, 'order_size_multiplier': 2.0,
           'deviation_pct': 0.01, 'deviation_step_multiplier': 2.0,
           'max_averaging_orders': 3,
           'take_profit_tranches': [{'at_avg_pct': 0.01, 'share': 0.5},
                                    {'at_avg_pct': 0.02, 'share': 0.5}]}
    venue, lines = FakeVenue(), []
    bot = Bot(validate_config(row), ADAPTER, venue,
              Notifier(sink=lines.append), gen_seed=1)
    # an operator's manual TP on the OTHER index — and one on no index
    venue.stop_book = [{'orderId': 'yours1', 'stopOrderType': 'TakeProfit',
                        'triggerPrice': '65000', 'qty': '0.5',
                        'positionIdx': 2},
                       {'orderId': 'yours2', 'stopOrderType': 'TakeProfit',
                        'triggerPrice': '64000', 'qty': '0.5',
                        'positionIdx': 0}]
    bot.cycle()                                       # base
    bot.cycle()                                       # tranches maintained
    ids = {o['orderId'] for o in venue.stop_orders('linear', 'BTCUSDT')}
    assert {'yours1', 'yours2'} <= ids                # H3: untouched


# --- audit M3: the tombstone fails CLOSED, and never blocks the stop ---------

def spec_X7_a_corrupt_tombstone_file_refuses_never_revives():
    import tempfile
    from pathlib import Path as _P
    from gridgremlin.tombstones import Tombstones, TombstoneError
    tmp = _P(tempfile.mkdtemp()) / 'tombs.json'
    tmp.write_text('{not json')
    try:
        Tombstones(tmp)
    except TombstoneError as e:
        assert 'deliberately' in str(e)
    else:
        raise AssertionError('a corrupt tombstone file was swallowed')


def spec_X7_a_failed_tombstone_write_never_blocks_the_flatten():
    class BrokenDisk:
        def add(self, botid, reason):
            raise OSError(30, 'Read-only file system')
    venue, lines = FakeVenue(mark=61000.0), []
    _holding(venue)
    bot = _bot(venue, lines, stop={'watch': 'mark_price', 'level': 58000})
    bot.tombs = BrokenDisk()
    bot.cycle()
    venue.mark = 57000.0
    bot.cycle()
    assert not bot.alive and venue.position is None   # the stop STILL executed
    assert any('tombstone write FAILED' in ln for ln in lines)


# --- X12: the candle-close cool-down and the emergency level (D33) -----------

def _clocked(venue, lines, clock, **over):
    return Bot(_cfg(**over), ADAPTER, venue, Notifier(sink=lines.append),
               gen_seed=1, clock=lambda: clock['t'])


def spec_X12_a_wick_inside_the_candle_never_fires_the_stop():
    """Altrady's "Candle Close": only the mark at the interval boundary is
    compared with the level."""
    venue, lines, clock = FakeVenue(mark=63000.0), [], {'t': 900.0 * 100 + 5}
    _holding(venue)
    bot = _clocked(venue, lines, clock,
                   stop={'watch': 'mark_price', 'level': 58000,
                         'confirm_candle': '15m'})
    bot.cycle()
    venue.mark = 57000.0                           # a wick, mid-candle
    clock['t'] += 300
    bot.cycle()
    assert bot.alive and venue.position is not None
    assert sum('waiting for the 15m candle' in ln for ln in lines) == 1
    venue.mark = 59000.0                           # back above before the
    clock['t'] += 600                              # close: the boundary sees
    bot.cycle()                                    # 59,000
    assert bot.alive
    venue.mark = 57500.0                           # and a close below it
    clock['t'] += 900
    bot.cycle()
    assert not bot.alive and venue.position is None
    assert any('at the 15m close' in ln for ln in lines)


def spec_X12_a_restart_waits_for_the_next_close():
    """The first cycle of a process has seen no boundary: below the level
    at start-up is a wick until a candle closes there."""
    venue, lines, clock = FakeVenue(mark=57000.0), [], {'t': 900.0 * 100 + 5}
    _holding(venue)
    bot = _clocked(venue, lines, clock,
                   stop={'watch': 'mark_price', 'level': 58000,
                         'confirm_candle': '15m'})
    bot.cycle()
    assert bot.alive
    clock['t'] += 900
    bot.cycle()
    assert not bot.alive


def spec_X12_the_emergency_level_overrides_the_cool_down():
    venue, lines, clock = FakeVenue(mark=63000.0), [], {'t': 900.0 * 100 + 5}
    _holding(venue)
    bot = _clocked(venue, lines, clock,
                   stop={'watch': 'mark_price', 'level': 58000,
                         'confirm_candle': '15m', 'emergency_pct': 0.05})
    bot.cycle()
    venue.mark = 55200.0                           # past 58,000, not 55,100
    clock['t'] += 60
    bot.cycle()
    assert bot.alive
    venue.mark = 55000.0                           # past the emergency level
    clock['t'] += 60
    bot.cycle()
    assert not bot.alive and venue.position is None
    assert any('emergency level 55100 crossed' in ln for ln in lines)


def spec_X12_the_venue_holds_the_emergency_level_not_the_stops_own():
    """Two levels: the engine waits at 58,000; the venue rests the hard one
    5% further out, sized like X3's, and survives this process."""
    venue, lines, clock = FakeVenue(mark=63000.0), [], {'t': 1000.0}
    _holding(venue, size='0.035')
    bot = _clocked(venue, lines, clock, min_position_base=0.014,
                   stop={'watch': 'mark_price', 'level': 58000,
                         'confirm_seconds': 30, 'emergency_pct': 0.05})
    bot.cycle()
    level, size = venue.sl_calls[0]
    assert level == 55100.0 and abs(size - 0.021) < 1e-9
    assert any('emergency stop resting at 55100' in ln for ln in lines)
    bot.cycle()
    assert len(venue.sl_calls) == 1                # the venue already agrees


def spec_X12_a_venue_that_cannot_hold_it_leaves_it_to_the_engine():
    venue, lines, clock = FakeVenue(mark=63000.0), [], {'t': 1000.0}
    _holding(venue)
    bot = Bot(_cfg(venue='hyperliquid',
                   stop={'watch': 'mark_price', 'level': 58000,
                         'confirm_seconds': 30, 'emergency_pct': 0.05}),
              ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1,
              clock=lambda: clock['t'])
    bot.cycle()
    assert not getattr(venue, 'sl_calls', [])      # nothing written
    venue.mark = 55000.0
    bot.cycle()
    assert not bot.alive                           # still overrides, bot-side


def spec_X12_refusals():
    base = {'watch': 'mark_price', 'level': 58000}
    for stop, frag in (
            (dict(base, confirm_candle='7m'), 'confirm_candle'),
            (dict(base, confirm_candle='15m', confirm_seconds=30),
             'by time or by candle close'),
            (dict(base, emergency_pct=0.05), 'overrides a cool-down'),
            (dict(base, confirm_candle='15m', server_side=True),
             'server_side'),
            ({'watch': 'account_equity', 'level': 500,
              'confirm_candle': '15m'}, 'watch: mark_price')):
        try:
            _cfg(stop=stop)
        except ConfigError as e:
            assert frag in str(e), (frag, str(e))
        else:
            raise AssertionError(f'accepted: {stop}')


# --- X13: the stop that leaves the position (D43) ----------------------------

def spec_X13_leave_position_cancels_and_stands_down_but_sells_nothing():
    """3Commas' "stop bot, leave the position": opt-in. Orders go, the bot
    goes, the tombstone lands — the position is not touched, and the kill
    line says so in words nobody can miss."""
    venue, lines = FakeVenue(mark=63000.0), []
    _holding(venue)
    bot = _bot(venue, lines,
               stop={'watch': 'mark_price', 'level': 58000,
                     'action': 'leave_position'})
    bot.cycle()
    assert venue.orders                                # the ladder rests
    venue.mark = 57900.0
    bot.cycle()
    assert not bot.alive and venue.orders == []
    assert venue.position is not None                  # nothing sold
    assert float(venue.position['size']) == 0.021
    assert not getattr(venue, 'market_links', [])      # no market order
    kill = next(ln for ln in lines if ' kill ' in ln)
    assert 'nothing sold' in kill and 'LEFT OPEN' in kill
    assert 'UNPROTECTED' in kill


def spec_X13_the_default_still_flattens():
    """The sabotage half: the same script without the opt-in (X1)."""
    venue, lines = FakeVenue(mark=63000.0), []
    _holding(venue)
    bot = _bot(venue, lines, stop={'watch': 'mark_price', 'level': 58000})
    bot.cycle()
    venue.mark = 57900.0
    bot.cycle()
    assert not bot.alive and venue.position is None


def spec_X13_refused_beside_a_stop_the_venue_holds():
    for stop in ({'watch': 'mark_price', 'level': 58000, 'server_side': True,
                  'action': 'leave_position'},
                 {'watch': 'position_sl', 'action': 'leave_position'},
                 {'watch': 'mark_price', 'level': 58000,
                  'confirm_seconds': 30, 'emergency_pct': 0.05,
                  'action': 'leave_position'}):
        try:
            _cfg(stop=stop)
        except ConfigError as e:
            assert 'nothing left to leave' in str(e), str(e)
        else:
            raise AssertionError(f'accepted: {stop}')
    ok = _cfg(stop={'watch': 'account_equity', 'level': 500,
                    'action': 'leave_position'})
    assert ok['stop']['action'] == 'leave_position'


# --- X14: the most this bot may lose (D47) -----------------------------------

_LOSS_SINCE = '2026-10-02T14:30:00Z'
_LOSS_MS = 1790951400000


def _lossy(venue, lines, clock, **over):
    return Bot(_cfg(max_loss=50, max_loss_since=_LOSS_SINCE, **over),
               ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1,
               clock=lambda: clock['t'])


def _fills(bot, *rows):
    return [{'time_ms': t, 'side': side, 'price': price, 'qty': qty,
             'fee': fee, 'link_id': f'{bot.botid}-3-x', 'symbol': 'BTCUSDT',
             'exec_id': f'e{t}'} for t, side, price, qty, fee in rows]


def spec_X14_an_open_loss_alone_reaches_the_limit():
    """Holding 0.021 from 63,000: down 50 at 60,619."""
    venue, lines, clock = FakeVenue(mark=63000.0), [], {'t': 2e9}
    _holding(venue)
    bot = _lossy(venue, lines, clock)
    bot.cycle()
    venue.mark = 60700.0                           # down 48.30
    bot.cycle()
    assert bot.alive and venue.position is not None
    venue.mark = 60600.0                           # down 50.40
    bot.cycle()
    assert not bot.alive and venue.position is None and venue.orders == []
    kill = next(ln for ln in lines if ' kill ' in ln)
    assert 'max_loss 50 reached: this bot is down 50.4 since' in kill
    assert 'open -50.4' in kill and 'flattened 0.021' in kill


def spec_X14_closed_and_open_losses_count_together_after_fees():
    venue, lines, clock = FakeVenue(mark=63000.0), [], {'t': 2e9}
    _holding(venue)
    bot = _lossy(venue, lines, clock)
    venue.fills_history = lambda mt, sym, a, b: _fills(
        bot,
        (_LOSS_MS - 5000, 'buy', 70000.0, 0.01, 0.0),      # before the
        (_LOSS_MS - 4000, 'sell', 50000.0, 0.01, 0.0),     # moment: not ours
        (_LOSS_MS + 1000, 'buy', 60000.0, 0.01, 1.0),
        (_LOSS_MS + 2000, 'sell', 57000.0, 0.01, 1.0),     # -30, -2 fees
        (_LOSS_MS + 3000, 'sell', 40000.0, 0.01, 0.0))     # older holding:
    venue.mark = 62200.0                           # realises nothing here
    bot.cycle()                                    # -32 closed, -16.8 open
    assert bot.alive
    assert abs(bot._loss_cache[2] + 32.0) < 1e-9
    venue.mark = 62100.0                           # -32 - 18.9 = -50.9
    bot.cycle()
    assert not bot.alive and venue.position is None
    assert any('realised -32 after fees' in ln for ln in lines)


def spec_X14_the_limit_closes_even_where_the_stop_would_leave():
    """'The most this bot may lose' cannot leave the loss running."""
    venue, lines, clock = FakeVenue(mark=63000.0), [], {'t': 2e9}
    _holding(venue)
    bot = _lossy(venue, lines, clock,
                 stop={'watch': 'mark_price', 'level': 50000,
                       'action': 'leave_position'})
    bot.cycle()
    venue.mark = 60600.0
    bot.cycle()
    assert not bot.alive and venue.position is None


def spec_X14_unknown_is_never_a_breach_and_the_fills_are_read_gently():
    from gridgremlin.exchange.errors import VenueError
    venue, lines, clock = FakeVenue(mark=63000.0), [], {'t': 2e9}
    _holding(venue)
    bot = _lossy(venue, lines, clock)
    calls = []

    def down(mt, sym, a, b):
        calls.append(1)
        raise VenueError('down', 'transient')
    venue.fills_history = down
    venue.mark = 50000.0                           # far past the limit
    assert bot._max_loss_hit({'mark': 50000.0}, 0.021, 63000.0, 2e9) is None
    venue.fills_history = lambda mt, sym, a, b: calls.append(1) or []
    n = len(calls)
    for _ in range(5):                             # same holding, same
        bot._bot_result({'mark': 62900.0}, 0.021, 63000.0, 2e9 + 5)   # minute
    assert len(calls) - n <= 2                     # linked + all, once
    bot._bot_result({'mark': 62900.0}, 0.028, 63000.0, 2e9 + 6)   # a fill
    assert len(calls) - n <= 4                     # re-read on the change


def spec_X14_without_the_limit_the_same_fall_changes_nothing():
    """The sabotage half."""
    venue, lines = FakeVenue(mark=63000.0), []
    _holding(venue)
    bot = _bot(venue, lines)
    bot.cycle()
    venue.mark = 60600.0
    bot.cycle()
    assert bot.alive and venue.position is not None


def spec_X14_the_limit_and_its_moment_travel_together():
    for row, frag in (({'max_loss': 50}, 'travel together'),
                      ({'max_loss_since': _LOSS_SINCE}, 'travel together'),
                      ({'max_loss': 0, 'max_loss_since': _LOSS_SINCE},
                       'max_loss'),
                      ({'max_loss': 50, 'max_loss_since': 'monday'},
                       'a moment like')):
        try:
            _cfg(**row)
        except ConfigError as e:
            assert frag in str(e), str(e)
        else:
            raise AssertionError(f'accepted: {row}')
    cfg = _cfg(max_loss=50, max_loss_since=_LOSS_SINCE)
    assert cfg['max_loss'] == 50.0 and cfg['max_loss_since_ms'] == _LOSS_MS
    assert 'max_loss' not in _cfg()


# --- X15: closing what a stopped bot left open (D48) -------------------------

class _CloseVenue:
    """Just what the close command touches: truth and one market order."""

    def __init__(self, positions, mark=11.1):
        self.positions, self.mark, self.orders = positions, mark, []

    def read_symbol_truth(self, market_type, symbol, funding_interval=480.0):
        return {'mark': self.mark, 'positions': {
            i: dict(p) for i, p in self.positions.items()}}

    def place_market(self, market_type, symbol, side, qty, position_idx=0,
                     reduce_only=False, link_id=None, borrow=False):
        self.orders.append((side, qty, position_idx, reduce_only))
        left = self.positions[position_idx]['size'] - float(qty)
        if left <= 1e-12:
            del self.positions[position_idx]
        else:
            self.positions[position_idx]['size'] = left


def _short_row(**over):
    return dict({'market_type': 'linear', 'symbol': 'BTCUSDT',
                 'side': 'short', 'venue': 'bybit'}, **over)


def spec_X15_a_stopped_bots_leftover_is_closed_with_one_reduce_only_order():
    from gridgremlin.close import close_position
    venue = _CloseVenue({1: {'side': 'Buy', 'size': 0.050, 'avg_entry': 11.0},
                         2: {'side': 'Sell', 'size': 0.021,
                             'avg_entry': 11.2}})
    seen = close_position(_short_row(), venue, ADAPTER, True, dry=True)
    assert seen['held'] == 0.021 and seen['side'] == 'short'
    assert venue.orders == []                          # looking sells nothing
    done = close_position(_short_row(), venue, ADAPTER, True)
    assert venue.orders == [('Buy', '0.021', 2, True)]     # exactly, and only
    assert done['closed'] == 0.021 and done['left'] == 0.0     # re-read (X4)
    assert venue.positions[1]['size'] == 0.050         # the long is not ours
    again = close_position(_short_row(), venue, ADAPTER, True)
    assert again['note'] == 'nothing to close' and len(venue.orders) == 1


def spec_X15_a_running_bot_and_a_spot_holding_are_refused():
    from gridgremlin.close import close_position
    venue = _CloseVenue({2: {'side': 'Sell', 'size': 0.021,
                             'avg_entry': 11.2}})
    alive = close_position(_short_row(), venue, ADAPTER, False)
    assert 'has not stood down' in alive['refused']
    spot = close_position(_short_row(market_type='spot', side='long'),
                          venue, ADAPTER, True)
    assert 'spot holding' in spot['refused']
    assert venue.orders == []


def spec_X15_the_close_command_has_no_way_to_mainnet():
    """The run half of D25's double gate is passed shut, and the command
    takes no flag that opens it."""
    import inspect
    import gridgremlin.close as cl
    src = inspect.getsource(cl)
    assert src.count('refuse_mainnet(client, False, False)') == 2
    assert 'HLVenueClient(allow_mainnet=False)' in src
    code = '\n'.join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith('#'))
    assert 'allow-mainnet' not in code and 'argv' in code
