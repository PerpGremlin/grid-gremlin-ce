# Specs for SPEC T15: the backtester ends a row where its stop or loss limit
# ends the bot (X1, X6, X8, X9, X12, X13, X14), and says what it cannot judge.

from gridgremlin.adapters import LinearAdapter
from gridgremlin.backtest import backtest
from gridgremlin.config import validate_config
from gridgremlin.ladder import stop_level_for

ADAPTER = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001,
                         'price_tick': 0.1, 'min_qty': 0.001,
                         'min_notional': 5.0, 'settle_coin': 'USDT'})
MINUTE = 1 / 60.0


def _cfg(**over):
    row = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
           'capital': 1000.0, 'leverage': 10, 'upper': 70000.0,
           'lower': 50000.0, 'rungs': 21, 'spacing_type': 'fixed', 'slide': None}
    row.update(over)
    return validate_config(row)


def _bar(o, h, l, c, t=None):
    b = {'o': o, 'h': h, 'l': l, 'c': c}
    if t is not None:
        b['t'] = t
    return b


def _run(stop=None, bars=(), **over):
    if stop:
        over['stop'] = stop
    return backtest(_cfg(**over), ADAPTER, list(bars), bar_hours=MINUTE)


BOUGHT = [_bar(60000, 60100, 58995, 59500)]           # one lot, at 59000
STOP = {'watch': 'mark_price', 'level': 49000}


def spec_T15_a_touch_flattens_at_the_level_and_nothing_trades_after():
    r = _run(STOP, BOUGHT + [_bar(52000, 52100, 48000, 48500),
                             _bar(48500, 70000, 48400, 69000)])
    s = r['stopped']
    assert s['price'] == 49000 and s['action'] == 'flatten', s
    assert r['held'] == 0.0 and r['trips'] == 0       # the 70000 bar traded nothing
    assert r['entry_fills'] == 3                       # 59000, then 51000 and 50000 above it
    # the flatten pays the taker fee on what it sold, at the stop's price
    bars = BOUGHT + [_bar(52000, 52100, 48000, 48500)]
    kept = _run(dict(STOP, action='leave_position'), bars)['held']
    free = backtest(_cfg(stop=STOP), ADAPTER, bars, bar_hours=MINUTE, stop_fee=0.0)
    paid = _run(STOP, bars)['fees'] - free['fees']
    assert kept > 0 and abs(paid - kept * 49000 * 0.00055) < 1e-6
    # the firing bar's high reached the 60000 exit, but which came first is
    # unknown: the exit waits, the stop sells the lot (no trip)
    both = _run(STOP, BOUGHT + [_bar(58000, 60500, 48000, 48500)])
    assert both['stopped'] and both['trips'] == 0
    assert _run(None, BOUGHT + [_bar(58000, 60500, 48000, 48500)])['trips'] == 1
    gap = _run(STOP, BOUGHT + [_bar(48500, 48600, 48000, 48200)])
    assert gap['stopped']['price'] == 48500            # opened past it: the open


def spec_T15_the_cool_down_counts_whole_closes_and_resets_on_recovery():
    closes = [48900, 48900, 48900, 49100, 48900, 48900, 48900, 48900, 48900]
    bars = BOUGHT + [_bar(52000, 52000, 49001, 52000)] + [
        _bar(c, c + 50, c - 50, c) for c in closes]
    r = _run(dict(STOP, confirm_seconds=300), bars)
    assert r['stopped']['price'] == 48900
    assert 'held 300s' in r['stopped']['reason']
    # four closes past it, then the recovery: no stop
    short = _run(dict(STOP, confirm_seconds=300), bars[:2] + bars[2:7])
    assert short['stopped'] is None and short['held'] > 0
    # five closes past the level fire on the fifth, as grid_eth's minute rule
    first = [i for i in range(len(bars)) if
             _run(dict(STOP, confirm_seconds=300), bars[:i + 1])['stopped']]
    assert first[0] == len(bars) - 1


def spec_T15_the_emergency_level_overrides_the_cool_down():
    r = _run(dict(STOP, confirm_seconds=3600, emergency_pct=0.02),
             BOUGHT + [_bar(50000, 50000, 47000, 49500)])
    assert abs(r['stopped']['price'] - 48020) < 1e-6
    assert 'emergency' in r['stopped']['reason']
    held = _run(dict(STOP, confirm_seconds=3600, emergency_pct=0.02),
                BOUGHT + [_bar(50000, 50000, 48500, 49500)])
    assert held['stopped'] is None                     # past the stop, not the emergency


def spec_T15_a_candle_stop_judges_only_its_closes():
    t0 = 1_700_000_100_000 - (1_700_000_100_000 % 300_000)   # on a 5-minute boundary
    bars = [_bar(60000, 60100, 58995, 59500, t0)] + [
        _bar(48900, 48950, 48850, 48900, t0 + 60_000 * k) for k in range(1, 6)]
    r = _run(dict(STOP, confirm_candle='5m'), bars)
    # the bar starting at minute 4 closes the candle: the fifth bar, index 4
    fired_at = [i for i in range(len(bars))
                if _run(dict(STOP, confirm_candle='5m'), bars[:i + 1])['stopped']]
    assert r['stopped'] and fired_at[0] == 4, fired_at
    assert '5m close' in r['stopped']['reason']


def spec_T15_leave_position_keeps_the_holding_to_the_end():
    r = _run(dict(STOP, action='leave_position'),
             BOUGHT + [_bar(52000, 52100, 48000, 48500),
                       _bar(48500, 70000, 48400, 69000)])
    assert r['stopped']['action'] == 'leave_position'
    assert r['held'] > 0 and r['trips'] == 0           # held, marked, never sold
    assert r['total'] > 0                              # the last close is far above


def spec_T15_the_loss_limit_flattens_where_it_is_reached_whatever_the_action():
    r = _run({'watch': 'mark_price', 'level': 30000, 'action': 'leave_position'},
             BOUGHT + [_bar(59500, 59500, 40000, 45000)],
             max_loss=50.0, max_loss_since='2026-10-01T00:00:00Z')
    s = r['stopped']
    assert s['reason'].startswith('max_loss') and s['action'] == 'flatten'
    assert 40000 < s['price'] < 59500 and r['held'] == 0.0
    assert -51.5 < r['total'] < -50.0                  # the limit, plus the flatten's fee


def spec_T15_the_floor_core_survives_the_flatten():
    r = _run(STOP, [_bar(60000, 60100, 50500, 52000),
                    _bar(52000, 52100, 48000, 48500)], min_position_base=0.01)
    assert r['stopped']['action'] == 'flatten'
    assert abs(r['held'] - 0.01) < 1e-9                # X6: grid inventory only


def spec_T15_what_it_cannot_judge_it_says():
    r = _run({'watch': 'position_sl'}, BOUGHT)
    assert r['stopped'] is None and 'position_sl' in r['stop_not_modelled'][0]
    r = _run({'watch': 'account_equity', 'level': 500}, BOUGHT)
    assert 'account' in r['stop_not_modelled'][0]
    acct = backtest(_cfg(stop={'watch': 'account_equity', 'level': 990}), ADAPTER,
                    BOUGHT + [_bar(59500, 59500, 40000, 45000)], bar_hours=MINUTE,
                    account={'equity': 1000.0, 'mm': 0.0})
    assert acct['stop_not_modelled'] == [] and acct['stopped']['price'] > 40000


def spec_T15_a_slide_rows_stop_follows_the_window():
    slide = {'trigger_rungs': 2, 'max_rungs': 100, 'confirm_seconds': 0}
    stop = {'watch': 'mark_price', 'rungs_beyond': 2}
    bars = [_bar(60000, 60100, 59900, 60000), _bar(74000, 74100, 73900, 74000),
            _bar(74000, 74100, 60000, 61000)]
    r = _run(stop, bars, slide=slide)
    cfg = _cfg(stop=stop, slide=slide)
    assert r['slides'] >= 1 and r['stopped'], r['stopped']
    assert r['stopped']['price'] == stop_level_for(cfg, r['offset'])
    assert r['stopped']['price'] > stop_level_for(cfg, 0)     # higher than home's


def spec_T15_the_panel_and_the_cli_say_what_the_stop_did():
    from panel.forms import verdict
    from gridgremlin.backtest_cli import stop_words
    cfg = _cfg(stop=STOP)
    bars = [dict(b, t=3_600_000 * i) for i, b in enumerate(
        BOUGHT + [_bar(52000, 52100, 48000, 48500)])]
    out = backtest(cfg, ADAPTER, bars, bar_hours=MINUTE)
    out.update(bars=len(bars), hold_benchmark=0.0, bar_minutes=1)
    page = verdict(dict(cfg), out)
    assert '<td>stop</td>' in page and 'fired (mark_price 49000) at 49,000' in page
    assert 'not the mark' in page and '01 Jan 01:00 UTC' in page
    calm = backtest(cfg, ADAPTER, BOUGHT, bar_hours=MINUTE)
    assert stop_words(cfg, calm).startswith('never fired')
    assert stop_words(_cfg(), calm) is None                      # no stop, no line
    kept = backtest(_cfg(stop={'watch': 'position_sl'}), ADAPTER, BOUGHT, bar_hours=MINUTE)
    assert 'not modelled: the stop-loss you keep' in stop_words(_cfg(stop={'watch': 'position_sl'}), kept)


# --- T15b: a mark stop on the mark's own candles ------------------------------

def _timed(bars):
    return [dict(b, t=i * 60_000) for i, b in enumerate(bars)]


def spec_T15b_a_mark_stop_reads_the_marks_candles_not_the_trades():
    """The mark dips through 49000 while the trades hold above it: it fires,
    and the firing bar is never cut below the trades' own low. The trades dip
    through while the mark holds: it does not. Sabotage: judge on `bar`
    instead of the mark's bar, and both halves go red."""
    trades = _timed(BOUGHT + [_bar(52000, 52100, 49500, 50000)])
    marks = _timed(BOUGHT + [_bar(52000, 52100, 48800, 49900)])
    cfg = _cfg(stop=STOP)
    r = backtest(cfg, ADAPTER, trades, bar_hours=MINUTE, mark_bars=marks)
    assert r['stopped'] and r['stopped']['price'] == 49000
    assert r['stop_judged'] == {'on': 'mark', 'trade_bars': 0}
    assert r['entry_fills'] == 3                    # 59000, 51000, 50000: not below 49500
    calm = backtest(cfg, ADAPTER, _timed(BOUGHT + [_bar(52000, 52100, 48800, 49900)]),
                    bar_hours=MINUTE, mark_bars=_timed(BOUGHT + [_bar(52000, 52100, 49500, 50000)]))
    assert calm['stopped'] is None
    assert backtest(cfg, ADAPTER, trades, bar_hours=MINUTE)['stopped'] is None   # on trades: no
    # a rung every 250 puts 49250 between the stop and the trades' low: the
    # cut bar fills what the trades reached, no deeper (sabotage: cut at the level)
    fine = dict(lower=45000.0, rungs=101)
    deep_t = _timed(BOUGHT + [_bar(51000, 51100, 49500, 50000)])
    deep_m = _timed(BOUGHT + [_bar(51000, 51100, 48800, 49900)])
    cut = backtest(_cfg(stop=STOP, **fine), ADAPTER, deep_t, bar_hours=MINUTE, mark_bars=deep_m)
    free = backtest(_cfg(**fine), ADAPTER, deep_t, bar_hours=MINUTE)
    assert cut['stopped'] and cut['entry_fills'] == free['entry_fills'] > 2
    closes = backtest(_cfg(stop=dict(STOP, confirm_candle='1m')), ADAPTER, trades,
                      bar_hours=MINUTE, mark_bars=marks)
    assert closes['stopped'] is None                # the mark closed above it


def spec_T15b_a_bar_with_no_mark_is_judged_on_trades_and_counted_and_said():
    from gridgremlin.backtest_cli import stop_words
    trades = _timed(BOUGHT + [_bar(52000, 52100, 48000, 48500)])
    r = backtest(_cfg(stop=STOP), ADAPTER, trades, bar_hours=MINUTE, mark_bars=trades[:1])
    assert r['stopped'] and r['stop_judged'] == {'on': 'mark', 'trade_bars': 1}
    assert 'judged on the mark price; 1 candle without one on trade prices' in stop_words(_cfg(stop=STOP), r)
    whole = backtest(_cfg(stop=STOP), ADAPTER, trades, bar_hours=MINUTE, mark_bars=trades)
    assert 'judged on the mark price, as the bot watches it' in stop_words(_cfg(stop=STOP), whole)
    plain = backtest(_cfg(stop=STOP), ADAPTER, trades, bar_hours=MINUTE)
    assert plain['stop_judged'] == {'on': 'trade', 'trade_bars': 2}
    assert "not the mark" in stop_words(_cfg(stop=STOP), plain)
    assert _run(None, trades)['stop_judged'] is None


def spec_T15b_mark_candles_are_fetched_only_for_a_bybit_grid_watching_the_mark():
    from ggdata.candles import candles
    from gridgremlin.backtest_cli import mark_bars_for
    asked = []

    def fetch(url):
        asked.append(url)
        return {'result': {'list': [['60000', '1', '2', '0.5', '1.5']]}}
    got = candles('bybit', 'linear', 'BTCUSDT', 1, 0, 60_000, fetch=fetch, price='mark')
    assert '/v5/market/mark-price-kline?' in asked[0] and got[0]['v'] == 0.0
    for bad in (lambda: candles('hyperliquid', 'linear', 'BTC', 1, 0, 1, price='mark'),
                lambda: candles('bybit', 'linear', 'BTCUSDT', 1, 0, 1, price='index')):
        try:
            bad()
            raise AssertionError('accepted')
        except ValueError:
            pass
    bars = _timed(BOUGHT)
    assert mark_bars_for(_cfg(stop=STOP), bars, 1, fetch=fetch)
    assert mark_bars_for(_cfg(), bars, 1, fetch=fetch) is None                      # no stop
    assert mark_bars_for(_cfg(stop={'watch': 'account_equity', 'level': 1}), bars, 1, fetch=fetch) is None
    assert mark_bars_for(dict(_cfg(stop=STOP), venue='hyperliquid'), bars, 1, fetch=fetch) is None

    def down(url):
        raise OSError('unreachable')
    assert mark_bars_for(_cfg(stop=STOP), bars, 1, fetch=down) is None             # said, never fatal
