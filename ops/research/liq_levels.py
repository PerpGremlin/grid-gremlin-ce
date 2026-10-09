"""Research (2026-10-09, the owner's shower thought): when a knife stops at a
swing pivot, do the liquidation levels of positions opened at that pivot act
as targets? Measure, per timeframe and leverage, which side's liquidations
price reaches first after the pivot is CONFIRMED (no lookahead), against the
same race from random moments; test whether the retrace's turning point
clusters at fib ratios or at liquidation distances more than at shifted
control levels; then fit binned probabilities on the first 70% of history
and score them on the last 30%. Public klines only, no key, nothing live.

  python3 ops/research/liq_levels.py [--coins BTCUSDT,ETHUSDT,SOLUSDT]

The levels, by the owner's word, are the pure arithmetic: a position opened
at price P with leverage L is liquidated a move of 1/L away — 100x at 1%,
2x at 50% (maintenance margin, a per-venue detail, set to zero here so the
variable studied is leverage alone). At a pivot
LOW (after a drop) the shorts who sold the low liquidate ABOVE — the retrace
side — and the longs who bought it liquidate BELOW — the continuation side.
At a pivot HIGH, mirrored.
"""
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ops.research.fib_backtest import fetch                    # noqa: E402

MM = 0.0                         # the owner's arithmetic: liquidation a move of 1/L away
LEVERAGE = (2, 3, 4, 5, 7, 10, 15, 20, 25, 33, 50, 75, 100, 125)
FIBS = (0.236, 0.382, 0.5, 0.618, 0.786)
SHIFTED = tuple(round(f + 0.06, 3) for f in FIBS)     # a control the same width, not fib
BAND = 0.02                      # +/- of the leg for "landed at a level"
FEE_RT = 2 * 0.00055             # taker in and out
# name: minutes, days of history, pivot k each side, horizon in bars, impulse window
TFS = {'1m': (1, 30, 5, 240, 30), '15m': (15, 365, 4, 96, 24),
       '1h': (60, 730, 4, 168, 24), '4h': (240, 730, 3, 180, 20)}


def liq(p, lev, side):
    """Where a position opened at p liquidates: side 'long' below, 'short' above."""
    d = 1.0 / lev - MM
    return p * (1 - d) if side == 'long' else p * (1 + d)


def atr(bars, n=14):
    out, a = [None] * len(bars), None
    for i in range(1, len(bars)):
        b, pc = bars[i], bars[i - 1]['c']
        tr = max(b['h'] - b['l'], abs(b['h'] - pc), abs(b['l'] - pc))
        a = tr if a is None else (a * (n - 1) + tr) / n
        out[i] = a if i >= n else None
    return out


def rsi_series(closes, n=14):
    out, g, l = [None] * len(closes), 0.0, 0.0
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        up, dn = max(ch, 0.0), max(-ch, 0.0)
        if i <= n:
            g += up / n
            l += dn / n
            if i == n:
                out[i] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
            continue
        g, l = (g * (n - 1) + up) / n, (l * (n - 1) + dn) / n
        out[i] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    return out


def pivots(bars, k):
    """[(index, 'low'|'high')]: a bar whose low (high) is the strict extreme
    of the k bars either side. Known only at index + k."""
    out = []
    for i in range(k, len(bars) - k):
        lo, hi = bars[i]['l'], bars[i]['h']
        win = bars[i - k:i + k + 1]
        if lo < min(b['l'] for j, b in enumerate(win) if j != k):
            out.append((i, 'low'))
        if hi > max(b['h'] for j, b in enumerate(win) if j != k):
            out.append((i, 'high'))
    return out


def race(bars, start, horizon, up, down):
    """Which of two levels the bars touch first from `start`: 'up', 'down',
    'both' (the same bar — order unknown) or 'none'; with the bars taken."""
    last = min(start + horizon, len(bars)) - 1
    for j in range(start, last + 1):
        hu, hd = bars[j]['h'] >= up, bars[j]['l'] <= down
        if hu and hd:
            return 'both', j - start, bars[j]['c']
        if hu:
            return 'up', j - start, up
        if hd:
            return 'down', j - start, down
    return 'none', horizon, bars[last]['c']


def events(bars, k, horizon, window, a, rs, rng, random_n=None):  # noqa: C901
    """Pivot events and as many random ones. Each: the pivot's price and kind,
    when it became known, its features, and per leverage the race outcome
    with 'retrace' meaning the side against the move that made the pivot."""
    vols = [b['v'] for b in bars]
    out = []
    piv = pivots(bars, k)
    picks = [(i, kind, i + k, True) for i, kind in piv]
    n = random_n if random_n is not None else len(picks)
    for _ in range(n):
        e = rng.randrange(window + 50, len(bars) - horizon - 1)
        drop = bars[e]['c'] < bars[e - window]['c']
        picks.append((e, 'low' if drop else 'high', e, False))
    for i, kind, known, is_pivot in picks:
        if known + 1 >= len(bars) or i < window + 50 or a[i] is None or rs[i] is None:
            continue
        if is_pivot:
            p0 = bars[i]['l'] if kind == 'low' else bars[i]['h']
        else:
            # the fair control: from a random moment, the extreme of the last
            # 2k+1 bars — the same geometry as a pivot, without knowing the
            # knife stopped (the extreme may be the bar just closed)
            win = bars[i - 2 * k:i + 1]
            p0 = min(b['l'] for b in win) if kind == 'low' else max(b['h'] for b in win)
        if kind == 'low':
            ext = max(b['h'] for b in bars[i - window:i + 1])
            leg = ext - p0
        else:
            ext = min(b['l'] for b in bars[i - window:i + 1])
            leg = p0 - ext
        med = sorted(vols[i - 50:i])[25] or 1e-12
        ev = {'pivot': is_pivot, 'kind': kind, 'p0': p0, 'i': i, 'known': known,
              'impulse': leg / a[i] if a[i] else 0.0,
              'vol': vols[i] / med,
              'rsi': rs[i] if kind == 'low' else 100 - rs[i],     # mirrored: low = exhaustion
              'races': {}}
        for lev in LEVERAGE:
            hi_l, lo_l = liq(p0, lev, 'short'), liq(p0, lev, 'long')
            seen = bars[i + 1:known + 1]
            pre = ('up' if any(b['h'] >= hi_l for b in seen) else '') + \
                  ('down' if any(b['l'] <= lo_l for b in seen) else '')
            res, took, exit_px = race(bars, known + 1, horizon, hi_l, lo_l)
            retr = 'up' if kind == 'low' else 'down'
            if pre:
                outcome = 'pre'
            elif res in ('none', 'both'):
                outcome = res
            else:
                outcome = 'retrace' if res == retr else 'continue'
            entry = bars[known]['c']
            # the trade from the known bar toward the retrace side: take profit at the
            # retrace side's liquidations; its stop is its OWN liquidation, a move of 1/L
            # from its own entry — always nearer than the pivot's continuation level, so
            # it is what ends a losing trade; closed at the horizon otherwise, marked at
            # its real exit. Its outcome is apart from the market-structure race above.
            sign = 1.0 if retr == 'up' else -1.0
            if retr == 'up':
                t_up, t_dn = hi_l, liq(entry, lev, 'long')
            else:
                t_up, t_dn = liq(entry, lev, 'short'), lo_l
            if (retr == 'up' and entry >= t_up) or (retr == 'down' and entry <= t_dn):
                t_res, exit_px = 'pre', entry          # the target was taken before the entry
            else:
                t_res, _t, exit_px = race(bars, known + 1, horizon, t_up, t_dn)
            pnl = sign * (exit_px - entry) / entry
            t_out = ('target' if t_res == retr else 'liquidated' if t_res in ('up', 'down')
                     else t_res)
            ev['races'][lev] = (outcome, took, pnl, t_out)
        if leg > 0:                                            # the retrace's turning point
            nxt = known + 1
            best, j = p0, nxt
            while j < min(nxt + horizon, len(bars)):
                b = bars[j]
                if (kind == 'low' and b['l'] < p0) or (kind == 'high' and b['h'] > p0):
                    break
                best = max(best, b['h']) if kind == 'low' else min(best, b['l'])
                j += 1
            ev['retrace_frac'] = abs(best - p0) / leg
            ev['retrace_pct'] = abs(best - p0) / p0
        out.append(ev)
    return out


def share(xs):
    return f'{xs:.0%}' if xs is not None else '—'


def table(evs, tf):
    lines = [f'\n## {tf}: which side\'s liquidations price reaches first, from the moment the pivot is known',
             f"{'lev':>4} {'set':>7} {'n':>6} {'retrace':>8} {'contin.':>8} {'none':>6} {'pre':>6} "
             f"{'P(retr|decided)':>16} {'bars to hit':>11} {'EV/trade':>9}"]
    for lev in LEVERAGE:
        for label, sel in (('pivots', True), ('random', False)):
            rows = [e['races'][lev] for e in evs if e['pivot'] == sel]
            n = len(rows)
            if not n:
                continue
            c = {k: sum(1 for r in rows if r[0] == k) for k in ('retrace', 'continue', 'none', 'pre', 'both')}
            dec = c['retrace'] + c['continue']
            p = c['retrace'] / dec if dec else None
            took = sorted(r[1] for r in rows if r[0] in ('retrace', 'continue'))
            med = took[len(took) // 2] if took else None
            # a trade from the known bar toward the retrace side, stop at the continuation side
            evs_r = [r[2] - FEE_RT for r in rows if r[3] != 'pre']
            ev = sum(evs_r) / len(evs_r) if evs_r else None
            lines.append(f"{lev:>3}x {label:>7} {n:>6} {c['retrace'] / n:>8.0%} {c['continue'] / n:>8.0%} "
                         f"{c['none'] / n:>6.0%} {c['pre'] / n:>6.0%} {share(p):>16} "
                         f"{(str(med) if med is not None else '—'):>11} "
                         f"{(f'{ev:+.3%}' if ev is not None else '—'):>9}")
    return lines


def clustering(evs, tf):
    pv = [e for e in evs if e['pivot'] and 'retrace_frac' in e and 0.05 < e['retrace_frac'] < 1.0]
    if len(pv) < 50:
        return [f'{tf}: too few retraces for the clustering test']

    def near(levels, key, band):
        return sum(1 for e in pv if any(abs(e[key] - x) <= band for x in levels)) / len(pv)
    fib, ctrl = near(FIBS, 'retrace_frac', BAND), near(SHIFTED, 'retrace_frac', BAND)
    liqd = [1.0 / L - MM for L in LEVERAGE if 1.0 / L - MM > 0]
    band_pct = 0.0015
    lq = near(liqd, 'retrace_pct', band_pct)
    # density-matched: the mean of levels 15% inside and 15% outside each distance
    lq_ctrl = (near([d * 0.85 for d in liqd], 'retrace_pct', band_pct)
               + near([d * 1.15 for d in liqd], 'retrace_pct', band_pct)) / 2
    return [f'{tf}: retrace turning points within ±{BAND:.0%} of the leg — at fib ratios {fib:.1%}, '
            f'at shifted controls {ctrl:.1%} (n {len(pv)}); within ±{band_pct:.2%} of price — at '
            f'liquidation distances {lq:.1%}, at 0.85x/1.15x those distances {lq_ctrl:.1%}']


def curve(evs, tf):
    """The distribution the owner means: how far a retrace travels from the
    pivot before the knife makes a new extreme (within the horizon), as the
    share of pivots that reach each 1/L distance — a survival curve —
    against the same measure from random moments; then its percentiles."""
    def ext(sel):
        return sorted(e['retrace_pct'] for e in evs if e['pivot'] == sel and 'retrace_pct' in e)
    pv, rd = ext(True), ext(False)
    if not pv or not rd:
        return [f'{tf}: no retraces measured']
    lines = [f'\n## {tf}: how far the retrace travels before a new extreme — share reaching each 1/L distance',
             f"{'lev':>4} {'1/L':>6} {'pivots':>8} {'random':>8} {'lift':>6}"]
    for lev in LEVERAGE:
        d = 1.0 / lev
        sp = sum(1 for x in pv if x >= d) / len(pv)
        sr = sum(1 for x in rd if x >= d) / len(rd)
        lines.append(f"{lev:>3}x {d:>6.2%} {sp:>8.1%} {sr:>8.1%} {(sp / sr if sr else float('nan')):>6.2f}")

    def pct(xs, q):
        return xs[min(len(xs) - 1, int(q * len(xs)))]
    lines.append('percentiles of the retrace (pivots | random): ' + ' · '.join(
        f'p{int(q * 100)} {pct(pv, q):.2%} | {pct(rd, q):.2%}' for q in (0.25, 0.5, 0.75, 0.9, 0.99)))
    return lines


def bins(e):
    imp = 'imp<3' if e['impulse'] < 3 else 'imp3-6' if e['impulse'] < 6 else 'imp6+'
    vol = 'vol<1.5' if e['vol'] < 1.5 else 'vol1.5-3' if e['vol'] < 3 else 'vol3+'
    rsi = 'rsi<30' if e['rsi'] < 30 else 'rsi30-50' if e['rsi'] < 50 else 'rsi50+'
    return (imp, vol, rsi)


def model(evs, tf):
    """Binned P(retrace first | decided), smoothed toward the base rate, fit on
    the first 70% of pivots in time and scored (Brier) on the last 30%."""
    lines = [f'\n## {tf}: the binned model, fit on the first 70%, scored on the last 30%']
    pv = sorted((e for e in evs if e['pivot']), key=lambda e: e['known'])
    cut = int(len(pv) * 0.7)
    for lev in LEVERAGE:
        def decided(es):
            return [(bins(e), e['races'][lev][0] == 'retrace') for e in es
                    if e['races'][lev][0] in ('retrace', 'continue')]
        tr, te = decided(pv[:cut]), decided(pv[cut:])
        if len(tr) < 60 or len(te) < 30:
            continue
        base = sum(y for _, y in tr) / len(tr)
        cells, alpha = {}, 20.0
        for b, y in tr:
            s, n = cells.get(b, (0, 0))
            cells[b] = (s + y, n + 1)
        pred = {b: (s + alpha * base) / (n + alpha) for b, (s, n) in cells.items()}
        brier_m = sum((pred.get(b, base) - y) ** 2 for b, y in te) / len(te)
        brier_b = sum((base - y) ** 2 for _, y in te) / len(te)
        test_base = sum(y for _, y in te) / len(te)
        best = sorted(((p, b) for b, p in pred.items() if cells[b][1] >= 30), reverse=True)[:2]
        held = []
        for p, b in best:
            ys = [y for bb, y in te if bb == b]
            held.append(f"{'/'.join(b)}: train {p:.0%} -> test {(sum(ys) / len(ys)) if ys else float('nan'):.0%} (n {len(ys)})")
        skill = 1 - brier_m / brier_b if brier_b else 0.0
        lines.append(f"{lev:>3}x base {base:.0%} (test {test_base:.0%}) · Brier model {brier_m:.4f} vs base "
                     f"{brier_b:.4f} · skill {skill:+.1%} · best cells " + ('; '.join(held) or '—'))
    return lines


def main(argv):
    coins = argv[argv.index('--coins') + 1].split(',') if '--coins' in argv else ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
    rng = random.Random(7)
    end = int(time.time() * 1000) // 86_400_000 * 86_400_000
    out = [f'# Liquidation levels from pivots — {", ".join(coins)} · MM {MM:.1%} · '
           f'fees {FEE_RT:.2%} a round trip']
    for tf, (mins, days, k, horizon, window) in TFS.items():
        evs = []
        span = []
        for c in coins:
            bars = fetch(c, mins, end - days * 86_400_000, end)
            span.append(len(bars))
            a, rs = atr(bars), rsi_series([b['c'] for b in bars])
            evs += events(bars, k, horizon, window, a, rs, rng)
        out.append(f'\n# {tf} — {days} days, pivots k={k}, horizon {horizon} bars, bars per coin {span}')
        out += table(evs, tf)
        out += curve(evs, tf)
        out += ['', *clustering(evs, tf)]
        out += model(evs, tf)
    print('\n'.join(out))


if __name__ == '__main__':
    main(sys.argv[1:])
