"""J2 (D80): the agent's working program — the arithmetic of TA in code."""
import json

from gridgremlin.agent_tools import (bb_width_pct, block, day_range, ema, rsi,
                                     session_name, session_start_ms, swings, tf_reading, vwap)


def _c(t, o, h, l, c, v=1.0):
    return {'t': t, 'o': o, 'h': h, 'l': l, 'c': c, 'v': v}


def spec_J2_the_indicators_are_computed_in_code_by_their_textbook_rules():
    """Hand-checked figures: the model reads them, it never works them out."""
    assert ema([1, 2, 3], 3) == 2.0 and ema([1, 2], 3) is None
    assert abs(ema([2, 4, 6, 8], 3) - 6.0) < 1e-12                     # seed 4, then 8*.5 + 4*.5
    assert rsi([1, 2, 3, 4, 5], 4) == 100.0 and rsi([1, 2], 4) is None
    assert abs(rsi([5, 4, 5, 4, 5], 4) - 50.0) < 1e-9                   # equal gains and losses
    assert abs(bb_width_pct([10.0] * 20) - 0.0) < 1e-12
    w = bb_width_pct([9.0, 11.0] * 10)                                  # sd 1, mean 10 → 4 * 1 / 10
    assert abs(w - 40.0) < 1e-9 and bb_width_pct([1.0] * 5) is None
    cs = [_c(i, 1, h, l, 1) for i, (h, l) in enumerate(
        [(1, 1), (2, 1), (5, 1), (2, 1), (1, 0), (2, 1), (2, 1), (3, 2), (2, 1)])]
    hi, lo = swings(cs, k=2)
    assert hi == [5] and lo == [0]
    flat = [_c(i, 1, h, 1, 1) for i, h in enumerate([1, 1, 4, 4, 1, 1, 1])]
    assert swings(flat, k=1)[0] == [4]                                  # a flat top is one level
    assert abs(vwap([_c(0, 0, 3, 1, 2, 1), _c(10, 0, 6, 2, 4, 3)], 0) - 3.5) < 1e-12   # (2*1 + 4*3) / 4
    assert vwap([_c(0, 0, 3, 1, 2, 1)], 5) is None
    day = 20_000 * 86_400_000
    assert day_range([_c(day - 1, 0, 99, 1, 5), _c(day + 5, 0, 10, 4, 5), _c(day + 9, 0, 12, 7, 5)], day + 10) == (12, 4)
    assert session_start_ms(day + 9 * 3_600_000) == day + 8 * 3_600_000 and session_name(day + 9 * 3_600_000) == 'Europe'
    assert session_name(day + 17 * 3_600_000) == 'US' and session_name(day + 3_600_000) == 'Asia'
    r = tf_reading([_c(i, 1, 1 + i, i, 0.5 + i) for i in range(260)])
    assert r['above'] == [9, 21, 50, 200] and r['rsi'] == 100.0 and r['regime'] == 'trending up'


def spec_J2_the_block_reads_public_data_and_says_what_it_could_not_read():
    """One market, plain text: the market's state, each timeframe, the
    session VWAP and the day's range; a figure that cannot be read is said
    in its place, never guessed. No key anywhere."""
    day = 20_000 * 86_400_000
    now = day + 9 * 3_600_000
    calls = []

    def fetch(url):
        calls.append(url)
        assert 'api_key' not in url and 'sign' not in url
        if '/market/kline' in url:
            if 'interval=60' in url:
                raise OSError('timed out')
            rows = [[str(now - (300 - i) * 300_000), '100', '101', '99', str(100 + i * 0.01), '5', '500']
                    for i in range(300)]
            return {'result': {'list': rows[::-1]}}
        if '/market/tickers' in url:
            return {'result': {'list': [{'lastPrice': '103', 'price24hPcnt': '0.01', 'turnover24h': '1e9',
                                         'openInterest': '1000', 'fundingRate': '0.0001', 'fundingIntervalHour': '8'}]}}
        raise OSError('no route')
    text = block('BTCUSDT', ('5m', '1h'), fetch=fetch, now_ms=now)
    assert text.startswith('== BTCUSDT (linear) · ') and 'Europe session' in text
    assert 'price 103.00 · 24h +1.00% · funding +0.0100%/8h' in text
    assert 'unread:' in text                                            # oi, ratio, book: said, not guessed
    assert ' 5m: EMA9/21/50/200 ' in text and ' 1h: unread (OSError)' in text
    assert 'session VWAP ' in text and '(since 08:00 UTC)' in text
    assert all(u.startswith('https://api.bybit.com/v5/market/') for u in calls)
