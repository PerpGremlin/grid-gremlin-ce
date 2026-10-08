"""The Fibonacci structure, pure (research 2026-10-08): known answers on
hand-drawn series."""
from gridgremlin.fib import (anchored_vwap, confluence, fib_levels, known_by,
                             retraced, rsi, structure, turned_down, turned_up,
                             wilder_atr, zigzag)


def _bars(points, spread=0.5):
    return [{'t': i * 60000, 'o': p, 'h': p + spread, 'l': p - spread, 'c': p, 'v': 1.0}
            for i, p in enumerate(points)]


def spec_FIB_atr_and_rsi_are_wilders():
    bars = _bars([10, 11, 12, 11, 13, 12, 14, 13, 15, 14, 16, 15, 17, 16, 18, 17])
    a = wilder_atr(bars, n=14)
    assert a[12] is None and a[13] is not None and a[13] > 0
    assert abs(a[14] - (a[13] * 13 + max(1.0, abs(18.5 - 16), abs(17.5 - 16))) / 14) < 1e-12
    closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
              45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64]
    r = rsi(closes, 14)
    assert r[13] is None and abs(r[14] - 70.46) < 0.1          # the textbook series
    assert abs(r[15] - 66.25) < 0.1
    assert rsi([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15], 14)[14] == 100.0


def spec_FIB_swings_are_confirmed_by_an_atr_reversal_and_dated():
    pts = [0, 2, 4, 6, 8, 10, 8, 6, 5, 7, 9, 11, 12, 10, 8, 6, 7, 8]
    bars = _bars(pts, spread=0.0)
    atr = [1.0] * len(bars)                     # a flat ATR, k=3: a 3-point reversal
    sw = zigzag(bars, atr, k=3.0)
    assert [(s['kind'], s['p']) for s in sw] == [('H', 10.0), ('L', 5.0), ('H', 12.0)]
    assert [s['confirmed'] for s in sw] == [7, 10, 14]       # 10→7 falls 3; 5→8 rises 3; 12→8
    assert [s['p'] for s in known_by(sw, 9)] == [10.0]       # at bar 9 only the high is known


def spec_FIB_structure_finds_the_trend_and_the_pivot_that_began_it():
    sw = [{'i': 0, 'p': 100, 'kind': 'L', 'confirmed': 2},
          {'i': 3, 'p': 110, 'kind': 'H', 'confirmed': 5},
          {'i': 6, 'p': 105, 'kind': 'L', 'confirmed': 8},
          {'i': 9, 'p': 120, 'kind': 'H', 'confirmed': 11},
          {'i': 12, 'p': 112, 'kind': 'L', 'confirmed': 14}]
    trend, pivot, extreme = structure(sw)
    assert trend == 'up' and pivot['p'] == 100 and extreme['p'] == 120
    down = [dict(s, p=240 - s['p'], kind='H' if s['kind'] == 'L' else 'L') for s in sw]
    trend, pivot, extreme = structure(down)
    assert trend == 'down' and pivot['p'] == 140 and extreme['p'] == 120
    broken = sw + [{'i': 15, 'p': 118, 'kind': 'H', 'confirmed': 17}]   # a lower high
    assert structure(broken)[0] is None
    assert structure(sw[:2]) == (None, None, None)


def spec_FIB_levels_retracements_and_the_fraction_retraced():
    lv = fib_levels(100.0, 120.0)
    assert lv[0.5] == 110.0 and abs(lv[0.618] - 107.64) < 1e-9 and lv[1.0] == 120.0
    assert abs(lv[1.272] - 125.44) < 1e-9 and abs(lv[1.618] - 132.36) < 1e-9
    assert retraced(100.0, 120.0, 110.0) == 0.5 and retraced(100.0, 120.0, 122.0) < 0
    short = fib_levels(120.0, 100.0)                      # a down impulse
    assert short[0.5] == 110.0 and short[1.272] == 120.0 - 20 * 1.272
    assert retraced(120.0, 100.0, 105.0) == 0.25


def spec_FIB_confluence_clusters_levels_within_a_band_and_scores_them():
    z = confluence([(100.0, 4, 'D 0.5'), (100.4, 2, '1h 0.618'), (105.0, 1, '15m 0.786'),
                    (99.7, 3, '4h 0.382')], band=0.5)
    assert len(z) == 2
    assert z[0]['lo'] == 99.7 and z[0]['hi'] == 100.4 and z[0]['score'] == 9
    assert z[0]['members'] == ['4h 0.382', 'D 0.5', '1h 0.618'] and z[1]['score'] == 1
    assert confluence([], 1.0) == []


def spec_FIB_the_trigger_is_a_turn_not_a_low():
    r = [None] * 3 + [45, 38, 33, 35, 39, 41, 50, 62, 65, 61, 58]
    assert turned_up(r, 8) and turned_up(r, 7) and not turned_up(r, 5)    # at the low: no
    assert not turned_up(r, 9, lookback=1)                                # the low out of sight
    assert turned_down(r, 13) and not turned_down(r, 11)
    assert not turned_up([None, None], 1)


def spec_FIB_anchored_vwap_is_typical_price_weighted_by_volume():
    bars = [{'t': 0, 'o': 10, 'h': 12, 'l': 8, 'c': 10, 'v': 1.0},
            {'t': 1, 'o': 10, 'h': 14, 'l': 10, 'c': 12, 'v': 3.0}]
    assert anchored_vwap(bars, 0, 1) == (10 * 1 + 12 * 3) / 4
    assert anchored_vwap([{'t': 0, 'o': 1, 'h': 1, 'l': 1, 'c': 1}], 0, 0) is None
