"""Research (2026-10-09): does a multi-timeframe Fibonacci confluence entry
beat the same ladder on fixed-percent levels? Pure measurement — nothing
here touches a venue with a key or any running code.

  python3 ops/research/fib_backtest.py [--days 365] [--coins BTCUSDT,ETHUSDT,SOLUSDT]

Public klines (no key) are fetched once per coin and timeframe into
logs/research/ and reused. The strategy under test and its control share
the trigger (daily trend by structure; 15m RSI turning from an extreme)
and the ladder shape (base + two adds, stop, three target tranches, the
stop to breakeven after the first target); they differ only in WHERE the
levels sit: fib confluence zones across D/4h/1h/15m, or fixed percents.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from gridgremlin.fib import (anchored_vwap, confluence, fib_levels, known_by, rsi,  # noqa: E402
                             structure, turned_down, turned_up, wilder_atr, zigzag)

HOST = 'https://api.bybit.com'
STORE = ROOT / 'logs' / 'research'
TFS = {'D': 1440, '4h': 240, '1h': 60, '15m': 15, '5m': 5}
WEIGHT = {'D': 4, '4h': 3, '1h': 2, '15m': 1}
MAKER, TAKER = 0.0002, 0.00055


def fetch(symbol, minutes, start_ms, end_ms):
    """Public klines with volume, oldest first, cached by coin/interval."""
    STORE.mkdir(parents=True, exist_ok=True)
    cache = STORE / f'{symbol}-{minutes}m-{start_ms // 86_400_000}-{end_ms // 86_400_000}.json'
    if cache.exists():
        return json.loads(cache.read_text())
    bars, cursor, step = [], start_ms, minutes * 60_000 * 1000
    interval = 'D' if minutes == 1440 else str(minutes)
    while cursor < end_ms:
        q = urllib.parse.urlencode({'category': 'linear', 'symbol': symbol, 'interval': interval,
                                    'start': cursor, 'end': min(cursor + step, end_ms), 'limit': 1000})
        req = urllib.request.Request(f'{HOST}/v5/market/kline?{q}', headers={'User-Agent': 'grid-gremlin research'})
        with urllib.request.urlopen(req, timeout=30) as r:
            rows = json.load(r)['result'].get('list', [])
        bars.extend({'t': int(x[0]), 'o': float(x[1]), 'h': float(x[2]), 'l': float(x[3]),
                     'c': float(x[4]), 'v': float(x[5])} for x in rows)
        cursor += step
        time.sleep(0.15)
    seen, out = set(), []
    for b in sorted(bars, key=lambda b: b['t']):
        if b['t'] not in seen:
            seen.add(b['t'])
            out.append(b)
    cache.write_text(json.dumps(out))
    return out


class TF:
    """One timeframe's bars with its ATR and swings, read without
    lookahead: a bar is usable once the next has opened."""

    def __init__(self, name, bars, k=3.0):
        self.name, self.bars, self.minutes = name, bars, TFS[name]
        self.atr = wilder_atr(bars, 14)
        self.swings = zigzag(bars, self.atr, k)
        self.closes = [b['c'] for b in bars]
        self._j = 0

    def closed_index(self, t_ms):
        """The last bar whose close time is <= t_ms (none: -1)."""
        end = self.minutes * 60_000
        while self._j + 1 < len(self.bars) and self.bars[self._j + 1]['t'] + end <= t_ms:
            self._j += 1
        return self._j if self.bars[self._j]['t'] + end <= t_ms else self._j - 1

    def state(self, t_ms):
        j = self.closed_index(t_ms)
        if j < 20:
            return None
        trend, pivot, extreme = structure(known_by(self.swings, j))
        if trend is None:
            return None
        return {'j': j, 'trend': trend, 'pivot': pivot['p'], 'extreme': extreme['p'],
                'atr': self.atr[j], 'levels': fib_levels(pivot['p'], extreme['p']),
                # the volume-weighted price since the trend began (research: a
                # zone the aVWAP sits in has weight of its own)
                'avwap': anchored_vwap(self.bars, pivot['i'], j)}


def zones_at(states, side, band):
    levels = []
    for name, st in states.items():
        if not st or st['trend'] != side:
            continue
        for r, p in st['levels'].items():
            if r < 1.0:                                   # retracements only
                levels.append((p, WEIGHT[name], f'{name} {r}'))
    return confluence(levels, band)


DAY = {'trend': '4h', 'ext': '1h', 'hold_h': 24, 'fixed': (0.01, 0.02, 0.03, 0.01, 0.02, 0.03),
       'width': 0.05, 'band': 0.35, 'tfs': ('4h', '1h', '15m')}
SWING = {'trend': 'D', 'ext': '4h', 'hold_h': 240, 'fixed': (0.025, 0.05, 0.08, 0.025, 0.05, 0.075),
         'width': 0.12, 'band': 0.35, 'tfs': ('D', '4h', '1h', '15m')}


def simulate(bars15, tfs, mode, min_score=6, max_hold_bars=None, stop_atr=1.0, shape=SWING,
             base_minutes=15, hold_h=None, vwap=False):
    """Walk the base bars (15m, or 5m with --trigger 5m). mode: 'fib' or
    'fixed'; shape: SWING (the daily trend, holds for days) or DAY (the 4h
    trend, a day at most); vwap: the zone must hold the ext timeframe's
    anchored VWAP. Returns rounds."""
    hold_h = shape['hold_h'] if hold_h is None else hold_h
    max_hold_bars = (hold_h * 60 // base_minutes) if max_hold_bars is None else max_hold_bars
    r15 = rsi([b['c'] for b in bars15], 14)
    rounds, pos = [], None
    for i, b in enumerate(bars15):
        t = b['t'] + base_minutes * 60_000       # this bar has closed
        if pos:
            pos = _advance(pos, b, i, rounds, max_hold_bars)
            continue
        if i < 100:
            continue
        states = {name: tf.state(t) for name, tf in tfs.items() if name in shape['tfs']}
        d = states[shape['trend']]
        if not d:
            continue
        side = d['trend']
        trig = turned_up(r15, i) if side == 'up' else turned_down(r15, i)
        if not trig:
            continue
        atr4 = (states.get(shape['ext']) or {}).get('atr') or (states.get('15m') or {}).get('atr')
        if not atr4:
            continue
        close = b['c']
        if mode == 'fib':
            zones = zones_at(states, side, band=shape['band'] * atr4)
            inzone = [z for z in zones if z['lo'] - 0.25 * atr4 <= close <= z['hi'] + 0.25 * atr4
                      and z['score'] >= min_score]
            if not inzone:
                continue
            here = inzone[0]
            if vwap:
                av = (states.get(shape['ext']) or {}).get('avwap')
                if av is None or not (here['lo'] - 0.5 * atr4 <= av <= here['hi'] + 0.5 * atr4):
                    continue
            deeper = ([z for z in zones if z['hi'] < here['lo']][-2:] if side == 'up'
                      else [z for z in zones if z['lo'] > here['hi']][:2])
            if len(deeper) < 2:
                continue
            adds = [z['mid'] for z in (reversed(deeper) if side == 'up' else deeper)]
            far = adds[-1]
            if abs(far - close) / close > shape['width']:
                continue                              # a ladder wider than this is not this trade
            stop = far - stop_atr * atr4 if side == 'up' else far + stop_atr * atr4
            ext = (states.get(shape['ext']) or d)['levels']
            targets = [ext[1.0], ext[1.272], ext[1.618]]
            f = shape['fixed']
            if side == 'up' and not (targets[0] > close):
                targets = [close * (1 + f[3]), close * (1 + f[4]), close * (1 + f[5])]
            if side == 'down' and not (targets[0] < close):
                targets = [close * (1 - f[3]), close * (1 - f[4]), close * (1 - f[5])]
            label = ','.join(here['members'])
        else:
            sgn = 1 if side == 'up' else -1
            f = shape['fixed']
            adds = [close * (1 - sgn * f[0]), close * (1 - sgn * f[1])]
            stop = close * (1 - sgn * f[2])
            targets = [close * (1 + sgn * f[3]), close * (1 + sgn * f[4]), close * (1 + sgn * f[5])]
            label = 'fixed'
        pos = {'side': side, 'open_i': i, 'legs': [(close, 1.0)], 'adds': list(adds),
               'stop': stop, 'targets': list(targets), 'shares': [0.4, 0.3, 0.3],
               'closed': [], 'fees': MAKER, 'label': label, 'be': False,
               'base_minutes': base_minutes}
    return rounds


def _advance(pos, b, i, rounds, max_hold):
    sgn = 1 if pos['side'] == 'up' else -1
    hit = (lambda p: b['l'] <= p) if sgn == 1 else (lambda p: b['h'] >= p)
    reached = (lambda p: b['h'] >= p) if sgn == 1 else (lambda p: b['l'] <= p)
    # adds (maker)
    while pos['adds'] and hit(pos['adds'][0]):
        pos['legs'].append((pos['adds'].pop(0), 1.0))
        pos['fees'] += MAKER
    units = sum(u for _, u in pos['legs'])
    avg = sum(p * u for p, u in pos['legs']) / units
    # stop (taker) — judged before targets inside one bar: the cautious order
    if hit(pos['stop']):
        remaining = 1.0 - sum(s for _, s in pos['closed'])
        pos['closed'].append((pos['stop'], remaining))
        pos['fees'] += TAKER
        return _close(pos, i, rounds, 'be' if pos['be'] else 'stop')
    while pos['targets'] and reached(pos['targets'][0]):
        share = pos['shares'].pop(0)
        pos['closed'].append((pos['targets'].pop(0), share))
        pos['fees'] += MAKER
        if not pos['be']:
            pos['be'], pos['stop'] = True, avg                 # breakeven ladder
    if not pos['targets']:
        return _close(pos, i, rounds, 'targets')
    if i - pos['open_i'] >= max_hold:
        remaining = 1.0 - sum(s for _, s in pos['closed'])
        pos['closed'].append((b['c'], remaining))
        pos['fees'] += TAKER
        return _close(pos, i, rounds, 'time')
    return pos


def _close(pos, i, rounds, how):
    sgn = 1 if pos['side'] == 'up' else -1
    units = sum(u for _, u in pos['legs'])
    avg = sum(p * u for p, u in pos['legs']) / units
    exit_avg = sum(p * s for p, s in pos['closed']) / sum(s for _, s in pos['closed'])
    gross = sgn * (exit_avg - avg) / avg
    net = gross - pos['fees'] * 2 / max(units, 1)        # fees as a fraction of committed
    rounds.append({'side': pos['side'], 'open_i': pos['open_i'], 'close_i': i, 'how': how,
                   'units': units, 'pnl': net, 'label': pos['label'],
                   'close_h': (i - pos['open_i']) * pos.get('base_minutes', 15) / 60})
    return None


def report(symbol, rounds, days, mode):
    n = len(rounds)
    if not n:
        return f'{symbol:8} {mode:5} rounds 0'
    wins = [r for r in rounds if r['pnl'] > 0]
    pf = (sum(r['pnl'] for r in wins) / -sum(r['pnl'] for r in rounds if r['pnl'] <= 0)
          if any(r['pnl'] <= 0 for r in rounds) else float('inf'))
    eq, peak, dd = 1.0, 1.0, 0.0
    for r in rounds:
        eq *= 1 + r['pnl'] * (r['units'] / 3)             # a third of capital per unit
        peak = max(peak, eq)
        dd = max(dd, 1 - eq / peak)
    hold = sum(r['close_h'] for r in rounds) / n
    how = {k: sum(1 for r in rounds if r['how'] == k) for k in ('targets', 'be', 'stop', 'time')}
    longs = [r for r in rounds if r['side'] == 'up']
    shorts = [r for r in rounds if r['side'] == 'down']
    side = (f"L {len(longs)}:{sum(r['pnl'] for r in longs):+.1%}" if longs else 'L 0') + ' ' + \
           (f"S {len(shorts)}:{sum(r['pnl'] for r in shorts):+.1%}" if shorts else 'S 0')
    return (f"{symbol:8} {mode:5} rounds {n:3} ({n / days * 30:4.1f}/mo)  win {len(wins) / n:5.1%}  "
            f"avg {sum(r['pnl'] for r in rounds) / n:+6.2%}  PF {pf:4.2f}  equity x{eq:5.2f}  "
            f"maxDD {dd:5.1%}  hold {hold:4.0f}h  tgt/be/stop/time {how['targets']}/{how['be']}/{how['stop']}/{how['time']}  {side}")


def main(argv):
    days = int(argv[argv.index('--days') + 1]) if '--days' in argv else 365
    coins = (argv[argv.index('--coins') + 1].split(',') if '--coins' in argv
             else ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'])
    end = int(time.time() * 1000) // 86_400_000 * 86_400_000
    start = end - (days + 40) * 86_400_000               # warm-up for the daily
    trigger = argv[argv.index('--trigger') + 1] if '--trigger' in argv else '15m'
    base_minutes = TFS[trigger]
    struct_tfs = ('D', '4h', '1h', '15m')
    for symbol in coins:
        bars = {name: fetch(symbol, m, start, end) for name, m in TFS.items()
                if name in struct_tfs or name == trigger}
        tfs = {name: TF(name, bars[name]) for name in struct_tfs}
        cut = end - days * 86_400_000
        base = [b for b in bars[trigger] if b['t'] >= cut]
        shape = DAY if '--daytrade' in argv else SWING
        use_vwap = '--vwap' in argv

        def run(mode, **kw):
            for tf in tfs.values():
                tf._j = 0
            return simulate(base, tfs, mode, shape=shape, base_minutes=base_minutes, vwap=use_vwap, **kw)
        for mode in ('fib', 'fixed'):
            print(report(symbol, run(mode), days, f'{mode}/{trigger}' + ('+v' if use_vwap else '')), flush=True)
        if '--layers' in argv:
            # the owner: three BTC products, each trading one timeframe's regime
            # exclusively — swing / day / intraday as thirds of one account. Do
            # the layers diversify, or lose on the same days?
            INTRA = dict(DAY, hold_h=8)
            lenses = (('swing', SWING, 3, 240), ('day', DAY, 3, 24), ('intra', INTRA, 3, 8))
            per, curves = {}, {}
            day_ms = 86_400_000
            for name, shp, s, h in lenses:
                for tf in tfs.values():
                    tf._j = 0
                r = simulate(base, tfs, 'fib', min_score=s, stop_atr=1.0, shape=shp,
                             base_minutes=base_minutes, hold_h=h, vwap=True)
                per[name] = r
                print('  ' + report(symbol, r, days, name), flush=True)
                # a daily equity curve for the layer: a round's P&L lands on its close day
                eq, by_day = 1.0, {}
                for x in r:
                    by_day.setdefault(base[x['close_i']]['t'] // day_ms, []).append(x['pnl'] * x['units'] / 3)
                curves[name] = by_day
            days_all = sorted({d for c in curves.values() for d in c})
            eqs = {n: 1.0 for n in curves}
            comb, peak, dd, path = 1.0, 1.0, 0.0, []
            for d in days_all:
                for n, c in curves.items():
                    for p in c.get(d, ()):
                        eqs[n] *= 1 + p
                comb = sum(eqs.values()) / len(eqs)
                peak = max(peak, comb)
                dd = max(dd, 1 - comb / peak)
                path.append(comb)
            # overlap: bars where two or more layers hold, same side or opposite
            held = {n: {} for n in curves}
            for n, r in per.items():
                for x in r:
                    for i in range(x['open_i'], x['close_i'] + 1, 12):
                        held[n][i] = x['side']
            idx = set().union(*(h.keys() for h in held.values()))
            two = same = opp = 0
            for i in idx:
                sides = [h[i] for h in held.values() if i in h]
                if len(sides) >= 2:
                    two += 1
                    if len(set(sides)) == 1:
                        same += 1
                    else:
                        opp += 1
            print(f"  {symbol:8} layers combined (thirds): equity x{comb:.2f}  maxDD {dd:.1%}  "
                  f"layers alone: " + ' '.join(f"{n} x{e:.2f}" for n, e in eqs.items())
                  + f"  | hours with 2+ layers on: {two} (same side {same}, opposite {opp})", flush=True)
        if '--walkforward' in argv:
            # the owner: "give each ticker a regime TF to trade and focus on" —
            # chosen by a rule on the first half of the year, judged on the second
            mid = cut + (end - cut) // 2
            h1 = [b for b in base if b['t'] < mid]
            h2 = [b for b in base if b['t'] >= mid]
            grid = [(s, h, v) for s in (3, 5) for h in (4, 8, 24) for v in (False, True)]

            def equity(rounds):
                eq = 1.0
                for r in rounds:
                    eq *= 1 + r['pnl'] * (r['units'] / 3)
                return eq, len(rounds)
            picks = []
            for s, h, v in grid:
                for tf in tfs.values():
                    tf._j = 0
                r = simulate(h1, tfs, 'fib', min_score=s, stop_atr=1.0, shape=shape,
                             base_minutes=base_minutes, hold_h=h, vwap=v)
                eq, n = equity(r)
                if n >= 6:                                   # a pick needs a sample
                    picks.append((eq, s, h, v))
            if picks:
                eq1, s, h, v = max(picks)
                for tf in tfs.values():
                    tf._j = 0
                r2 = simulate(h2, tfs, 'fib', min_score=s, stop_atr=1.0, shape=shape,
                              base_minutes=base_minutes, hold_h=h, vwap=v)
                print(f"  {symbol:8} walk-forward: H1 picked s{s} h{h}{'v' if v else ''} (x{eq1:.2f}); H2 -> "
                      + report(symbol, r2, days // 2, 'H2'), flush=True)
        if '--sweep' in argv:
            for min_score in (3, 5):
                for hold_h in (4, 8, 24):
                    for v in (False, True):
                        for tf in tfs.values():
                            tf._j = 0
                        r = simulate(base, tfs, 'fib', min_score=min_score, stop_atr=1.0, shape=shape,
                                     base_minutes=base_minutes, hold_h=hold_h, vwap=v)
                        print('  ' + report(symbol, r, days, f's{min_score}h{hold_h}{"v" if v else ""}'), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
