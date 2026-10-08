# Specs for SPEC T7 — the martingale's rehearsal: the real Bot against a
# venue made of candles.

from gridgremlin.adapters import LinearAdapter
from gridgremlin.config import validate_config
from gridgremlin.replay import BarVenue, backtest_martingale, refuse_replay

ADAPTER = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001,
                         'price_tick': 0.1, 'min_qty': 0.001,
                         'min_notional': 5.0, 'settle_coin': 'USDT'})
MAKER, TAKER = 0.0002, 0.00055


def _cfg(**over):
    row = {'strategy': 'martingale', 'market_type': 'linear',
           'symbol': 'BTCUSDT', 'side': 'long', 'capital': 1000.0,
           'leverage': 10, 'base_order_size': 1000.0,
           'safety_order_size': 1000.0, 'order_size_multiplier': 2.0,
           'deviation_pct': 0.01, 'deviation_step_multiplier': 2.0,
           'max_averaging_orders': 3, 'take_profit_avg_pct': 0.01}
    row.update(over)
    return validate_config(row)


def _bars(*ohlc):
    return [{'t': i * 300_000, 'o': o, 'h': h, 'l': l, 'c': c}
            for i, (o, h, l, c) in enumerate(ohlc)]


def spec_T7_one_round_is_the_engines_own_arithmetic():
    """Base at market on the first candle, take profit 1% above the average
    on the second. Every number is recomputed here by hand."""
    r = backtest_martingale(_cfg(), ADAPTER, _bars(
        (60000, 60050, 59950, 60000), (60000, 60700, 59990, 60650)))
    entry = 60000 + 60000 * 1.0 / 20_000            # half of a 1bp spread
    qty = 0.016                                     # 1000 / 60000, floored
    target = ADAPTER.round_price(entry * 1.01)
    assert r['rounds'] == 1 and r['held'] == 0 and r['so_fills'] == 0
    assert abs(r['grid_profit'] - (target - entry) * qty) < 1e-6
    assert abs(r['fees'] - (entry + target) * qty * TAKER) < 1e-6
    assert abs(r['net'] - (r['grid_profit'] - r['fees'])) < 1e-12
    assert abs(r['total'] - r['net']) < 1e-9        # flat: nothing open
    assert 'round complete' in r['ended']           # repeat off (M5)
    assert r['bars_run'] == 2 and len(r['equity_curve']) == 2


def spec_T7_safety_orders_fill_on_the_way_and_the_target_follows_the_average():
    """Down through the first two safety orders (-1%, -3%), then back: the
    take profit sits 1% above the NEW average (M4), and the safeties filled
    as resting orders at their own prices, at the maker fee."""
    r = backtest_martingale(_cfg(repeat=True), ADAPTER, _bars(
        (60000, 60010, 59990, 60000),
        (60000, 60000, 58000, 58100),               # through 59,403 and 58,203
        (58100, 59500, 58050, 59400)))              # and up through the TP
    assert r['max_depth'] == 2 and r['so_fills'] >= 2
    assert r['rounds'] == 1 and r['stops'] == 0
    # 0.016 at ~60,003, 0.016 at 59,400, 0.034 at 58,200: average ~58,928.9,
    # sold 1% above it — the round's profit is 1% of what it cost
    cost = 0.016 * 60003 + 0.016 * 59400.0 + 0.034 * 58200.0
    assert abs(r['grid_profit'] - cost * 0.01) < 0.5
    assert r['held'] > 0 and r['ended'] is None     # repeat: a new round is in


def spec_T7_a_candle_that_holds_both_puts_the_stop_before_the_target():
    """One candle spans the stop and the take profit. The walk goes to the
    adverse extreme first, so the round is stopped, never flattered."""
    cfg = _cfg(stop={'watch': 'mark_price', 'from_base_pct': 0.10})
    r = backtest_martingale(cfg, ADAPTER, _bars(
        (60000, 60010, 59990, 60000),
        (60000, 62000, 53000, 61000)))              # -11.7% and +3.3%
    assert r['stops'] == 1 and r['net'] < 0 and r['held'] == 0
    assert 'stop fired' in r['ended']
    short = backtest_martingale(
        _cfg(side='short', stop={'watch': 'mark_price',
                                 'from_base_pct': 0.10}),
        ADAPTER, _bars((60000, 60010, 59990, 60000),
                       (60000, 67000, 58000, 59000)))
    assert short['stops'] == 1 and short['net'] < 0  # a short sees the high


def spec_T7_the_venue_fills_in_the_order_the_price_reaches_things():
    """A stop resting ABOVE a buy order fires before that buy fills when
    the price falls through both in one step."""
    v = BarVenue(ADAPTER, 'long', MAKER, TAKER)
    v.advance(60000.0, 0)
    v.place_market('linear', 'BTCUSDT', 'Buy', '0.010', 1)
    v.place_order('linear', 'BTCUSDT', 'Buy', '0.010', '59000', 'x-1-1', 1)
    v.set_trading_stop('linear', 'BTCUSDT', 1, stop_loss='59500',
                       sl_size='0.010')
    v.advance(58000.0, 60)                          # through both at once
    kinds = [(f['side'], f['price']) for f in v.fills[1:]]
    assert kinds == [('sell', 59500.0), ('buy', 59000.0)]
    assert abs(v.held - 0.010) < 1e-12              # the stop sold the first
    assert v.fills[1]['venue_closed']
    assert v.fills[1]['venue_kind'] == 'PartialStopLoss'
    assert v.fills[2]['fee'] == 0.010 * 59000 * MAKER    # rested: maker
    up = BarVenue(ADAPTER, 'long', MAKER, TAKER)
    up.advance(60000.0, 0)
    up.place_order('linear', 'BTCUSDT', 'Buy', '0.010', '59000', 'x-1-1', 1)
    up.advance(59000.0, 60)                         # a touch is not a fill
    assert up.fills == [] and len(up.orders) == 1


def spec_T7_fills_are_never_stamped_in_the_bots_future():
    """The bot asks for fills "until now": a stamp past it hid every close
    and M14 waited on an account that was already there."""
    v = BarVenue(ADAPTER, 'long', MAKER, TAKER)
    v.advance(60000.0, 1000.0)
    for _ in range(5):
        v.place_market('linear', 'BTCUSDT', 'Buy', '0.001', 1)
    stamps = [f['time_ms'] for f in v.fills]
    assert stamps == sorted(set(stamps)) and max(stamps) <= 1_000_000
    assert len(v.fills_history('linear', 'BTCUSDT', 0, 1_000_000)) == 5


def spec_T7_the_limits_end_a_rehearsal_as_they_end_a_bot():
    """The loss limit (X14) and the round limit (M18) run on the pretend
    venue's own fills, through the live code."""
    since = '1970-01-01T00:00:00Z'
    falling = _bars((60000, 60010, 59990, 60000), (60000, 60000, 57000, 57100),
                    (57100, 57200, 54000, 54100), (54100, 54200, 53000, 53050))
    r = backtest_martingale(_cfg(max_loss=100, max_loss_since=since),
                            ADAPTER, falling)
    assert 'max_loss 100 reached' in r['ended'] and r['held'] == 0
    assert r['net'] <= -100 and r['bars_run'] == 2  # at the first walk point
                                                    # past the limit
    p, stairs = 60000.0, [(60000, 60010, 59990, 60000)]
    for _ in range(4):                              # each candle climbs 1.2%:
        stairs.append((p, p * 1.012, p - 10, p * 1.012))   # one round each
        p *= 1.012
    r = backtest_martingale(
        _cfg(repeat=True, max_rounds=2, max_rounds_since=since), ADAPTER,
        _bars(*stairs))
    assert r['rounds'] == 2 and 'max_rounds reached: 2 of 2' in r['ended']
    assert r['held'] == 0 and r['bars_run'] == 3    # and it opened no third


def spec_T7_a_position_left_open_is_valued_to_the_end():
    """X13 in rehearsal: the bot stands down, the position rides on, and
    the last candle prices it."""
    cfg = _cfg(stop={'watch': 'mark_price', 'from_base_pct': 0.10,
                     'action': 'leave_position'})
    r = backtest_martingale(cfg, ADAPTER, _bars(
        (60000, 60010, 59990, 60000), (60000, 60000, 53000, 53500),
        (53500, 53600, 50000, 50100)))
    assert 'LEFT OPEN' in r['ended'] and r['held'] > 0 and r['bars_run'] == 3
    assert r['total'] < r['equity_curve'][1]        # it kept falling


def spec_T7_what_cannot_be_rehearsed_is_refused_by_name():
    assert 'yourself' in refuse_replay(_cfg(stop={'watch': 'position_sl'}))
    assert refuse_replay(_cfg(trailing_stop_pct=0.01)) is None   # modelled
    assert refuse_replay(_cfg()) is None


def spec_T7_the_draft_door_serves_both_kinds_and_honours_the_days():
    """`--days` was parsed, removed, and then asked for again: every draft
    ran the default seven days whatever was typed."""
    import io
    import json
    import sys
    import gridgremlin.backtest_cli as cli
    seen = {}
    saved, saved_in, saved_out = cli.run_draft, sys.stdin, sys.stdout
    try:
        cli.run_draft = lambda raw, days, bar, fee, **kw: \
            seen.update(days=days, bar=bar, fee=fee) or {'ok': 1}
        sys.stdin, sys.stdout = io.StringIO('{}'), io.StringIO()
        cli.main(['--draft', '--days', '3', '--fee', '0.0004'])
    finally:
        cli.run_draft, sys.stdin, sys.stdout = saved, saved_in, saved_out
    assert seen == {'days': 3.0, 'bar': 60, 'fee': 0.0004}
    r = cli.rehearse(_cfg(), _bars((60000, 60050, 59950, 60000),
                                   (60000, 60700, 59990, 60650)), ADAPTER,
                     bar_minutes=5)
    assert r['strategy'] == 'martingale' and r['rounds'] == 1
    assert r['bars'] == 2 and r['bar_minutes'] == 5
    assert abs(r['hold_benchmark'] - 1000.0 * (60650 / 60000 - 1)) < 1e-9
    assert cli.draft_guards(_cfg()) is None         # no longer "grids only"
    assert json.dumps(r)                            # the panel reads JSON


def spec_M3_a_remainder_close_is_placed_once_and_left_resting():
    # pins: M20
    """Found by the first rehearsal, 2026-10-03, in the LIVE engine: a
    tranche fills, the price falls back and a safety order fills. Every
    re-anchored target is now behind the round's best mark, so the bot
    closes the remainder with one resting reduce-only limit — which, on a
    venue that hosts the TP, it did not count as cover (it looked only at
    the conditional book) and its own ladder diff then cancelled. It was
    placed again every cycle, and the fill was announced every cycle."""
    from gridgremlin.bot import Bot
    from gridgremlin.events import Notifier
    cfg = _cfg(take_profit_avg_pct=None, repeat=True, take_profit_tranches=[
        {'at_avg_pct': 0.008, 'share': 0.5},
        {'at_avg_pct': 0.016, 'share': 0.5}])
    venue, lines = BarVenue(ADAPTER, 'long', MAKER, TAKER), []
    bot = Bot(cfg, ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1,
              clock=lambda: venue.now)

    def run(price, cycles=6):
        venue.advance(price, venue.now + 60)
        for _ in range(cycles):
            bot.cycle()
            venue.now += 1
    run(60000.0)                                   # base, tranches resting
    run(60600.0)                                   # tranche 1 (60,483) fills
    assert abs(venue.held - 0.008) < 1e-9
    run(59300.0, cycles=12)                        # safety 1 (59,403) fills
    # M22: the average moved, so the gauge starts again — both tranches
    # are live from the new average; nothing is "met" and no remainder
    # close is placed (before M22 the round's old high retired them)
    assert not [ln for ln in lines if 'every tranche target met' in ln]
    assert len([o for o in venue.stop_book
                if 'TakeProfit' in o['stopOrderType']]) == 2
    grew = [ln for ln in lines if ' fill ' in ln and '0.008 ->' in ln]
    assert len(grew) == 1                          # the fill is said once
    # now every target IS passed by the gauge and the venue holds no exit
    # (it lost them): the remainder close is placed once, then rests
    venue.stop_book = [o for o in venue.stop_book
                       if 'TakeProfit' not in o['stopOrderType']]
    bot._round_hwm = 61000.0
    run(59350.0, cycles=12)
    said = [ln for ln in lines if 'every tranche target met' in ln]
    exits = [o for o in venue.orders if o['reduce_only']]
    assert len(said) == 1, len(said)               # placed once
    assert len(exits) == 1                         # and still resting
    assert [o for o in venue.orders if not o['reduce_only']]   # the ladder
    assert bot.alive                               # below it still rests


def spec_T7_the_pretend_venue_trails_as_the_real_one_does():
    """The venue's trailing stop: armed at its activation price, following
    the best price since, closing a fixed distance behind it."""
    v = BarVenue(ADAPTER, 'long', MAKER, TAKER)
    v.advance(60000.0, 0)
    v.place_market('linear', 'BTCUSDT', 'Buy', '0.010', 1)
    v.set_trading_stop('linear', 'BTCUSDT', 1, trailing_stop='600',
                       active_price='60600')
    v.advance(59000.0, 60)                         # not armed: no stop
    assert v.steps and len(v.fills) == 1
    v.advance(61000.0, 120)                        # armed, best 61,000
    v.advance(60500.0, 180)                        # 60,400 not reached
    assert v.steps
    v.advance(60300.0, 240)
    assert not v.steps and v.fills[-1]['price'] == 60400.0
    assert v.fills[-1]['venue_kind'] == 'TrailingStop'
    now = BarVenue(ADAPTER, 'long', MAKER, TAKER)  # no activation: at once
    now.advance(60000.0, 0)
    now.place_market('linear', 'BTCUSDT', 'Buy', '0.010', 1)
    now.set_trading_stop('linear', 'BTCUSDT', 1, trailing_stop='600')
    now.advance(59300.0, 60)
    assert not now.steps and now.fills[-1]['price'] == 59400.0


def spec_T7_a_trailing_round_is_rehearsed_end_to_end():
    r = backtest_martingale(
        _cfg(repeat=True, deviation_pct=0.05, take_profit_avg_pct=0.05,
             trailing_stop_pct=0.01, trailing_activation_pct=0.005),
        ADAPTER, _bars((60000, 60010, 59990, 60000),
                       (60000, 61000, 59990, 60900),   # armed, best 61,000
                       (60900, 60950, 60200, 60250)))  # back through 60,400
    # round 1 leaves at 60,400 (about +6.3 on 0.016); the next round opens
    # there and is trailed out again as the candle keeps falling
    assert r['rounds'] == 2 and r['stops'] == 0
    assert 0 < r['grid_profit'] < 0.016 * 600


def spec_T7_the_pretend_venue_takes_the_rows_venue_shape():
    """A Hyperliquid row rehearses against a venue that hosts no position
    TP/SL (D21): the engine's trail and resting exits run, not Bybit's.
    Until 2026-10-03 every rehearsal wore Bybit's shape."""
    bars = _bars((60000, 60010, 59990, 60000), (60000, 60700, 59990, 60650))
    hl = backtest_martingale(_cfg(venue='hyperliquid', symbol='BTC'),
                             ADAPTER, bars)
    by = backtest_martingale(_cfg(), ADAPTER, bars)
    assert hl['hosts_position_tp'] is False and by['hosts_position_tp'] is True
    assert hl['rounds'] == by['rounds'] == 1        # both take the profit


# --- D59: a DCA bot on margin spot ---------------------------------------------

def spec_D59_a_spot_dca_bot_rests_its_exit_as_a_sell_and_turns_rounds():
    """Owner 2026-10-05: a light margin-spot fleet — BTC a spot DCA bot.
    Spot has no position TP and no reduce-only: the round's exit rests as a
    plain sell the bot recognises as its own, safety orders buy on borrow,
    and rounds turn on real price paths exactly as on a perp."""
    from gridgremlin.adapters import SpotAdapter
    from gridgremlin.config import ConfigError
    spot = SpotAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.000001,
                        'min_qty': 0.000048, 'price_tick': 0.1,
                        'min_notional': 1.0})
    row = {'market_type': 'spot', 'spot_borrow': True, 'spot_leverage': 10,
           'leverage': None, 'repeat': True}
    cfg = _cfg(**row)
    assert cfg['leverage'] == 10 and cfg['market_type'] == 'spot'
    lines = []
    import gridgremlin.replay as R
    orig = R.Notifier

    class N(orig):
        def __init__(self, *a, **k):
            super().__init__(sink=lines.append)
    R.Notifier = N
    try:
        r = backtest_martingale(cfg, spot, _bars(
            (60000, 60050, 59950, 60000), (60000, 60010, 59300, 59350),
            (59350, 60300, 59340, 60250), (60250, 60900, 60200, 60800),
            (60800, 60850, 60100, 60200), (60200, 61500, 60150, 61400)))
    finally:
        R.Notifier = orig
    assert r['hosts_position_tp'] is False          # spot: a resting sell
    assert r['rounds'] >= 2 and r['so_fills'] >= 1
    assert not [l for l in lines if ' warn ' in l], [l for l in lines if ' warn ' in l]
    assert sum('tranche' not in l and 'round TP resting' in l for l in lines) \
        <= r['rounds'] + 1                          # placed once per round
    for bad, frag in (({'side': 'short'}, 'long this phase'),
                      ({'leverage': 5}, "not 'leverage'"),
                      ({'spot_borrow': False}, 'half a directive'),
                      ({'venue': 'hyperliquid'}, 'Bybit')):
        try:
            _cfg(**dict(row, **bad))
        except ConfigError as e:
            assert frag in str(e), (bad, str(e))
        else:
            raise AssertionError(f'{bad} was accepted')
