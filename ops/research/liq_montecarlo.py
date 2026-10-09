"""Research (2026-10-09): the liquidation-level study, Monte Carlo'd.

Three tests on top of ops/research/liq_levels.py:

1. The null market. Each coin's real bars are rebuilt into fake price paths
   by block bootstrap — whole bars as ratios to the previous close (open,
   high, low, close), drawn in blocks of BLOCK bars — which keeps each bar's
   shape and short-range volatility clustering and destroys everything
   longer. The same pivot pipeline runs on hundreds of fake markets; where
   the real market sits in that cloud says whether the "knife stopped"
   effect is structure or just the geometry of a random walk.
2. Bootstrap intervals on the real pivot trade's expected value and on
   pivot minus random, per timeframe and leverage.
3. Ruin curves: 200-trade sequences resampled from the real pivot trades,
   each trade risking a fixed share of equity as margin, per leverage.

  python3 ops/research/liq_montecarlo.py [--sims 120] [--workers 22]
"""
import random
import sys
import time
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ops.research.fib_backtest import fetch                    # noqa: E402
from ops.research import liq_levels as L                       # noqa: E402

COINS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT')
LEV = (5, 10, 25, 50, 100)
BLOCK = 50
RISK = 0.10                      # margin per trade, as a share of equity
TRADES, PATHS = 200, 5000
SIMS = {'1m': 66, '15m': 120, '1h': 120, '4h': 240}


def synth(bars, rng):
    """A fake path from the real bars' shapes, block-bootstrapped."""
    rel = []
    for prev, b in zip(bars, bars[1:]):
        pc = prev['c']
        rel.append((b['o'] / pc, b['h'] / pc, b['l'] / pc, b['c'] / pc, b['v']))
    out, c, t = [], bars[0]['c'], bars[0]['t']
    step = bars[1]['t'] - bars[0]['t']
    while len(out) < len(bars) - 1:
        s = rng.randrange(0, len(rel) - BLOCK)
        for o, h, l, cc, v in rel[s:s + BLOCK]:
            t += step
            out.append({'t': t, 'o': c * o, 'h': c * h, 'l': c * l, 'c': c * cc, 'v': v})
            c = c * cc
            if len(out) >= len(bars) - 1:
                break
    return out


def stats(evs):
    """Per leverage, from pivot events: P(retrace first | decided), the
    trade's mean P&L after fees, and the share of retraces reaching 1/L."""
    out = {}
    pv = [e for e in evs if e['pivot']]
    # (the trade's liquidated share rides along: the ruin curve's raw material)
    ext = [e['retrace_pct'] for e in pv if 'retrace_pct' in e]
    for lev in LEV:
        rows = [e['races'][lev] for e in pv]
        r = sum(1 for x in rows if x[0] == 'retrace')
        c = sum(1 for x in rows if x[0] == 'continue')
        pnl = [x[2] - L.FEE_RT for x in rows if x[3] != 'pre']
        out[lev] = {'p': r / (r + c) if r + c else None,
                    'ev': sum(pnl) / len(pnl) if pnl else None,
                    's': sum(1 for x in ext if x >= 1.0 / lev) / len(ext) if ext else None}
    return out


def _run(job):
    """One fake market (all coins) for one timeframe — a worker's unit."""
    tf, seed = job
    mins, days, k, horizon, window = L.TFS[tf]
    rng = random.Random(seed)
    end = int(time.time() * 1000) // 86_400_000 * 86_400_000
    evs = []
    for c in COINS:
        real = fetch(c, mins, end - days * 86_400_000, end)
        bars = synth(real, rng)
        a, rs = L.atr(bars), L.rsi_series([b['c'] for b in bars])
        evs += L.events(bars, k, horizon, window, a, rs, rng, random_n=0)
    return tf, stats(evs)


def real_events(tf):
    mins, days, k, horizon, window = L.TFS[tf]
    rng = random.Random(7)
    end = int(time.time() * 1000) // 86_400_000 * 86_400_000
    evs = []
    for c in COINS:
        bars = fetch(c, mins, end - days * 86_400_000, end)
        a, rs = L.atr(bars), L.rsi_series([b['c'] for b in bars])
        evs += L.events(bars, k, horizon, window, a, rs, rng)
    return evs


def pctile(x, xs):
    xs = [v for v in xs if v is not None]
    return sum(1 for v in xs if v < x) / len(xs) if xs and x is not None else None


def boot_ci(xs, n=1000, rng=None):
    rng = rng or random.Random(11)
    if not xs:
        return None, None
    means = sorted(sum(rng.choices(xs, k=len(xs))) / len(xs) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n)]


def ruin(rets, rng):
    """5,000 paths of 200 trades resampled from `rets` (return on margin,
    floored at -1: a liquidation), each risking RISK of equity."""
    finals, dds, ruined = [], [], 0
    for _ in range(PATHS):
        eq, peak, dd = 1.0, 1.0, 0.0
        for _ in range(TRADES):
            eq *= 1 + RISK * rng.choice(rets)
            peak = max(peak, eq)
            dd = max(dd, 1 - eq / peak)
            if eq < 0.1:
                break
        finals.append(eq)
        dds.append(dd)
        ruined += eq < 0.1
    finals.sort()
    dds.sort()
    return finals[PATHS // 10], finals[PATHS // 2], finals[9 * PATHS // 10], dds[PATHS // 2], ruined / PATHS


def main(argv):
    sims = int(argv[argv.index('--sims') + 1]) if '--sims' in argv else None
    workers = int(argv[argv.index('--workers') + 1]) if '--workers' in argv else 22
    tfs = argv[argv.index('--tfs') + 1].split(',') if '--tfs' in argv else list(SIMS)
    plan = {tf: (sims or n) for tf, n in SIMS.items() if tf in tfs}
    jobs = [(tf, 1000 + i) for tf, n in plan.items() for i in range(n)]
    t0 = time.time()
    with Pool(workers) as pool:
        null = {}
        for tf, st in pool.imap_unordered(_run, jobs, chunksize=1):
            null.setdefault(tf, []).append(st)
    out = [f'# Monte Carlo: {sum(plan.values())} fake markets ({", ".join(f"{tf} {n}" for tf, n in plan.items())}), '
           f'block {BLOCK} bars, {workers} workers, {time.time() - t0:.0f} s']
    rng = random.Random(3)
    for tf in plan:
        evs = real_events(tf)
        real = stats(evs)
        out.append(f'\n## {tf}: the real market against {len(null[tf])} fake markets built from its own bars')
        out.append(f"{'lev':>4} | {'P(retr) real':>12} {'fake mean':>9} {'pctile':>7} | {'reach 1/L real':>14} "
                   f"{'fake mean':>9} {'pctile':>7} | {'EV real':>8} {'fake mean':>9} {'pctile':>7}")
        for lev in LEV:
            fk = [s[lev] for s in null[tf]]
            row = [f'{lev:>3}x']
            for key, fmt in (('p', '.1%'), ('s', '.1%'), ('ev', '+.3%')):
                xs = [f[key] for f in fk if f[key] is not None]
                mean = sum(xs) / len(xs) if xs else None
                pc = pctile(real[lev][key], xs)
                row.append(f"| {format(real[lev][key], fmt) if real[lev][key] is not None else '—':>12} "
                           f"{format(mean, fmt) if mean is not None else '—':>9} "
                           f"{format(pc, '.0%') if pc is not None else '—':>7}")
            out.append(' '.join(row))
        out.append(f'\n## {tf}: bootstrap 95% intervals on the trade after fees (real market)')
        for lev in LEV:
            pv = [e['races'][lev][2] - L.FEE_RT for e in evs if e['pivot'] and e['races'][lev][3] != 'pre']
            rd = [e['races'][lev][2] - L.FEE_RT for e in evs if not e['pivot'] and e['races'][lev][3] != 'pre']
            lo, hi = boot_ci(pv, rng=rng)
            m = len(min(pv, rd, key=len))
            diffs = [a - b for a, b in zip(rng.sample(pv, m), rng.sample(rd, m))] if m else []
            dlo, dhi = boot_ci(diffs, rng=rng)
            out.append(f"{lev:>3}x pivot EV {sum(pv) / len(pv):+.3%} [{lo:+.3%}, {hi:+.3%}] · "
                       f"pivot − random {sum(diffs) / len(diffs) if diffs else 0:+.3%} "
                       f"[{dlo:+.3%}, {dhi:+.3%}]" if pv and diffs else f'{lev:>3}x —')
        out.append(f'\n## {tf}: 200 trades resampled from the real pivot trades, {RISK:.0%} of equity as margin each, '
                   f'{PATHS} paths')
        out.append(f"{'lev':>4} {'p10 final':>10} {'median':>8} {'p90':>8} {'median maxDD':>13} {'ruined':>7}")
        for lev in LEV:
            # return on margin; a liquidation is -1 (its own 1/L move), fees on the notional
            rets = [max(-1.0, (e['races'][lev][2] - L.FEE_RT) * lev) for e in evs
                    if e['pivot'] and e['races'][lev][3] != 'pre']
            if not rets:
                continue
            p10, med, p90, dd, rr = ruin(rets, rng)
            out.append(f'{lev:>3}x {p10:>10.2f} {med:>8.2f} {p90:>8.2f} {dd:>13.0%} {rr:>7.1%}')
    print('\n'.join(out))


if __name__ == '__main__':
    main(sys.argv[1:])
