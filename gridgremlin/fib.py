"""Fibonacci structure, pure (research toward a signal layer, 2026-10-08).

The owner's design: read the trend on the daily, find the pivot where it
flipped, draw retracements and extensions from that impulse; each lower
timeframe's own impulse sits inside the higher one's retracement, and
every level that agrees across timeframes is confluence; the trade is the
REACTION at a confluent zone on the 15m, never the level alone.

Nothing here reads a venue or decides anything; the backtest in
ops/research/ feeds it bars and judges the result. Bars are dicts with
t (ms), o, h, l, c and, where the anchored VWAP is wanted, v.
"""

RETRACEMENTS = (0.236, 0.382, 0.5, 0.618, 0.786)
EXTENSIONS = (1.0, 1.272, 1.618)


def wilder_atr(bars, n=14):
    """Average true range, Wilder's smoothing; None until n bars."""
    out, prev_close, acc = [], None, None
    for i, b in enumerate(bars):
        tr = (b['h'] - b['l'] if prev_close is None else
              max(b['h'] - b['l'], abs(b['h'] - prev_close), abs(b['l'] - prev_close)))
        prev_close = b['c']
        if i < n:
            acc = tr if acc is None else acc + tr
            out.append(None if i < n - 1 else acc / n)
            if i == n - 1:
                acc = acc / n
            continue
        acc = (acc * (n - 1) + tr) / n
        out.append(acc)
    return out


def rsi(closes, n=14):
    """Wilder's RSI; None until n+1 closes."""
    out, gain, loss = [None] * len(closes), None, None
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        g, l = max(d, 0.0), max(-d, 0.0)
        if i <= n:
            gain = g if gain is None else gain + g
            loss = l if loss is None else loss + l
            if i == n:
                gain, loss = gain / n, loss / n
                out[i] = 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
            continue
        gain = (gain * (n - 1) + g) / n
        loss = (loss * (n - 1) + l) / n
        out[i] = 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
    return out


def zigzag(bars, atr, k=3.0):
    """Swings by an ATR-scaled reversal: a high is a swing once price has
    fallen k ATRs from it, a low once it has risen k ATRs. Each swing says
    at which bar it was CONFIRMED, so a reader at time t uses only what it
    could have known. Returns [{'i', 'p', 'kind': 'H'|'L', 'confirmed'}]."""
    swings = []
    if not bars:
        return swings
    dir_, ext_i = None, 0
    ext_p = bars[0]['h']
    lo_i, lo_p = 0, bars[0]['l']
    for i, b in enumerate(bars):
        a = atr[i] if i < len(atr) else None
        if a is None:
            continue
        band = k * a
        if dir_ is None:
            if b['h'] > ext_p:
                ext_i, ext_p = i, b['h']
            if b['l'] < lo_p:
                lo_i, lo_p = i, b['l']
            if ext_p - b['l'] >= band and ext_i >= lo_i:
                swings.append({'i': ext_i, 'p': ext_p, 'kind': 'H', 'confirmed': i})
                dir_, ext_i, ext_p = 'down', i, b['l']
            elif b['h'] - lo_p >= band and lo_i >= ext_i:
                swings.append({'i': lo_i, 'p': lo_p, 'kind': 'L', 'confirmed': i})
                dir_, ext_i, ext_p = 'up', i, b['h']
            continue
        if dir_ == 'up':
            if b['h'] > ext_p:
                ext_i, ext_p = i, b['h']
            elif ext_p - b['l'] >= band:
                swings.append({'i': ext_i, 'p': ext_p, 'kind': 'H', 'confirmed': i})
                dir_, ext_i, ext_p = 'down', i, b['l']
        else:
            if b['l'] < ext_p:
                ext_i, ext_p = i, b['l']
            elif b['h'] - ext_p >= band:
                swings.append({'i': ext_i, 'p': ext_p, 'kind': 'L', 'confirmed': i})
                dir_, ext_i, ext_p = 'up', i, b['h']
    return swings


def known_by(swings, bar_i):
    """The swings a reader at bar `bar_i` could have known."""
    return [s for s in swings if s['confirmed'] <= bar_i]


def structure(swings):
    """The trend by structure and the pivot where it began. Up while
    highs and lows both rise, down while both fall; the pivot is the
    earliest swing of the unbroken chain — a low for an up trend, a high
    for a down trend. (trend, pivot, extreme) or (None, None, None)."""
    if len(swings) < 3:
        return None, None, None
    highs = [s for s in swings if s['kind'] == 'H']
    lows = [s for s in swings if s['kind'] == 'L']
    if len(highs) < 2 or len(lows) < 2:
        return None, None, None
    up = highs[-1]['p'] > highs[-2]['p'] and lows[-1]['p'] > lows[-2]['p']
    down = highs[-1]['p'] < highs[-2]['p'] and lows[-1]['p'] < lows[-2]['p']
    if not up and not down:
        return None, None, None
    kind = 'L' if up else 'H'
    chain = [s for s in swings if s['kind'] == kind]
    pivot = chain[-1]
    for j in range(len(chain) - 1, 0, -1):
        ok = chain[j]['p'] > chain[j - 1]['p'] if up else chain[j]['p'] < chain[j - 1]['p']
        if not ok:
            break
        pivot = chain[j - 1]
    extremes = [s for s in swings if s['kind'] == ('H' if up else 'L') and s['i'] > pivot['i']]
    if not extremes:
        return None, None, None
    extreme = max(extremes, key=lambda s: s['p']) if up else min(extremes, key=lambda s: s['p'])
    return ('up' if up else 'down'), pivot, extreme


def fib_levels(pivot, extreme):
    """Retracements from the extreme back toward the pivot, and
    extensions of the impulse beyond it: {ratio: price}. Either side."""
    span = extreme - pivot
    out = {r: extreme - span * r for r in RETRACEMENTS}
    out.update({e: pivot + span * e for e in EXTENSIONS})
    return out


def retraced(pivot, extreme, price):
    """How far price has come back from the extreme toward the pivot, as a
    fraction of the impulse: 0 at the extreme, 1 at the pivot; beyond the
    extreme is negative."""
    span = extreme - pivot
    return 0.0 if span == 0 else (extreme - price) / span


def anchored_vwap(bars, start_i, end_i):
    """Volume-weighted average price from `start_i` through `end_i`
    (typical price × volume); None without volume."""
    pv = vol = 0.0
    for b in bars[start_i:end_i + 1]:
        v = b.get('v')
        if v is None:
            return None
        pv += (b['h'] + b['l'] + b['c']) / 3 * v
        vol += v
    return pv / vol if vol else None


def confluence(levels, band):
    """Cluster levels that sit within `band` of a neighbour; a zone's score
    is its members' weights summed. `levels`: [(price, weight, label)].
    Returns zones [{'lo', 'hi', 'mid', 'score', 'members'}], by price."""
    zones = []
    for price, weight, label in sorted(levels):
        if zones and price - zones[-1]['hi'] <= band:
            z = zones[-1]
            z['hi'] = price
            z['score'] += weight
            z['members'].append(label)
            z['mid'] = (z['lo'] + z['hi']) / 2
        else:
            zones.append({'lo': price, 'hi': price, 'mid': price,
                          'score': weight, 'members': [label]})
    return zones


def turned_up(rsi_values, i, floor=40.0, lookback=6, lift=3.0):
    """The 15m trigger: RSI touched below `floor` within `lookback` bars
    and now sits `lift` above that low — momentum turning, not just low."""
    window = [v for v in rsi_values[max(0, i - lookback):i + 1] if v is not None]
    if len(window) < 2 or rsi_values[i] is None:
        return False
    low = min(window)
    return low < floor and rsi_values[i] >= low + lift


def turned_down(rsi_values, i, ceiling=60.0, lookback=6, drop=3.0):
    window = [v for v in rsi_values[max(0, i - lookback):i + 1] if v is not None]
    if len(window) < 2 or rsi_values[i] is None:
        return False
    high = max(window)
    return high > ceiling and rsi_values[i] <= high - drop
