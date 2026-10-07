# Composition glue (like main.py — venue names are allowed here, A6): fresh
# venue bars into the pure backtest core.
#   python3 -m gridgremlin.backtest_cli <fleet.json> --bot <botid>
#           [--days 7] [--bar-minutes 60] [--fee 0.0002] [--funding 0]
import json
import sys
import time
from pathlib import Path

from .adapters import adapter_for
from .apply import make_botid
from .backtest import backtest
from .config import validate_fleet


def rehearse(draft, bars, adapter, fee=0.0002, bar_minutes=60):
    """§9: a draft config replayed over real bars, returning the same
    vocabulary as the readout plus the hold benchmark — what the same
    capital did just sitting there. Pure: candles in, verdict out."""
    if draft['strategy'] == 'martingale':      # T7: the real Bot, replayed
        from .replay import backtest_martingale
        r = backtest_martingale(draft, adapter, bars, fee_maker=fee,
                                bar_minutes=bar_minutes)
    else:
        r = backtest(draft, adapter, bars, fee_rate=fee,
                     funding_rate_hourly=0.0, bar_hours=bar_minutes / 60.0)
    r['bar_minutes'] = bar_minutes
    first_o, last_c = bars[0]['o'], bars[-1]['c']
    sign = 1.0 if draft['side'] == 'long' else -1.0
    r['hold_benchmark'] = draft['capital'] * sign * (last_c / first_o - 1.0)
    r['bars'] = len(bars)
    r['first_open'], r['last_close'] = first_o, last_c
    return r


SWEEP_STEP = 8          # T8: the coarse pass (5, 13, 21 … 77); the best is
                        # then refined by 4 and by 2 — 14 replays, not 22
                        # (a 30-day sweep took 293 s on the one-core box)
PLATEAU = 0.95          # within 5% of the best net is "as good"


def sweep_rungs(raw, bars, adapter, fee=0.0002, bar_minutes=5,
                candidates=None, progress=None):
    """T8 (D50): the step optimiser is the rehearsal, swept. The range is
    the owner's; only `rungs` moves. Each candidate is the real planner
    over the same bars (T3/T6), scored by net = grid profit - fees (+
    funding). Every row is returned — the table is the answer, the best
    is named, and the plateau (within 5% of the best) says how much the
    choice matters. A gap that cannot clear the round-trip fee (G16) is
    skipped by name, never run. `raw` is the row as written: each
    candidate is validated on its own."""
    from .config import ConfigError, validate_config
    lower, upper = float(raw['lower']), float(raw['upper'])
    floor = 2.0 * fee                     # G16: one gap pays the fee twice
    cands = sorted(set(candidates or range(5, 78, SWEEP_STEP)))
    # what is written for ONE rung count cannot ride to another: a weights
    # list is one number per level, a seed names levels. The sweep sizes
    # every level equally and says what it set aside.
    PER_RUNG = ('rung_weights', 'rung_sizing', 'seed')
    dropped = [k for k in PER_RUNG if k in raw]
    base = {k: v for k, v in raw.items()
            if k not in PER_RUNG and not k.startswith('_')}

    def one(n):
        gap = (upper - lower) / (n - 1) / lower
        if gap <= floor:
            return {'rungs': n, 'gap_pct': gap * 100.0,
                    'skipped': 'the gap cannot clear the round-trip fee '
                               '(G16)'}
        try:
            cfg = validate_config(dict(base, rungs=n))
        except ConfigError as e:          # the engine's words, as a row
            return {'rungs': n, 'gap_pct': gap * 100.0, 'skipped': str(e)}
        # a level whose order is under the venue's minimum rests nothing —
        # the run would say 0 trips and nothing else (HL SOL, 2026-10-03)
        from .ladder import rung_notionals
        least = min(rung_notionals(cfg))
        q = adapter.round_qty(adapter.qty_from_notional(least, upper))
        if q <= 0 or not adapter.meets_minimum(q, upper):
            return {'rungs': n, 'gap_pct': gap * 100.0,
                    'skipped': f"a level's order ({least:.4g}) sits under the "
                               "venue's minimum — fewer levels or more "
                               'capital (F8)'}
        r = backtest(cfg, adapter, bars, fee_rate=fee,
                     funding_rate_hourly=0.0, bar_hours=bar_minutes / 60.0)
        share = (r['fees'] / r['grid_profit']) if r['grid_profit'] > 0 \
            else None
        return {'rungs': n, 'gap_pct': gap * 100.0, 'net': r['net'],
                'total': r['total'], 'trips': r['trips'], 'fees': r['fees'],
                'fee_share': share, 'max_drawdown': r['max_drawdown']}

    total = len([n for n in cands if n >= 2]) + 4      # the refinements
    done = 0

    def step(n):
        nonlocal done
        r = one(n)
        done += 1
        if progress:
            progress(f'replay {done} of about {total}',
                     min(done / total, 1.0))               # U26/U29
        return r

    rows = {n: step(n) for n in cands if n >= 2}
    scored = [r for r in rows.values() if 'net' in r]
    if not scored:
        return {'score': 'net', 'rows': list(rows.values()), 'best': None,
                'plateau': None, 'bars': len(bars),
                'bar_minutes': bar_minutes, 'dropped': dropped}
    for half in (SWEEP_STEP // 2, SWEEP_STEP // 4):            # refine ±4, ±2
        best = max((r for r in rows.values() if 'net' in r),
                   key=lambda r: r['net'])['rungs']
        for n in (best - half, best + half):
            if n >= 2 and n not in rows:
                rows[n] = step(n)
    scored = [r for r in rows.values() if 'net' in r]
    top = max(scored, key=lambda r: r['net'])
    near = [r['rungs'] for r in scored
            if top['net'] > 0 and r['net'] >= PLATEAU * top['net']] \
        or [top['rungs']]
    return {'score': 'net', 'rows': [rows[n] for n in sorted(rows)],
            'best': top['rungs'], 'plateau': [min(near), max(near)],
            'bars': len(bars), 'bar_minutes': bar_minutes,
            'dropped': dropped}


VENUES_WITH_CANDLES = ('bybit', 'hyperliquid')


WINDOWS_DAYS = 14        # T9: the page's sweep reads 14 days once and splits it


def visited_pct(bars, lower, upper):
    """T9: the share of candles whose close sat inside the range — a weak
    result is explained before the grid is blamed."""
    if not bars:
        return None
    inside = sum(1 for b in bars if lower <= b['c'] <= upper)
    return inside / len(bars) * 100.0


def score_rungs(raw, n, bars, adapter, fee=0.0002, bar_minutes=5):
    """One replay of one rung count over one window: its net."""
    from .config import validate_config
    base = {k: v for k, v in raw.items()
            if k not in ('rung_weights', 'rung_sizing', 'seed')
            and not k.startswith('_')}
    cfg = validate_config(dict(base, rungs=n))
    return backtest(cfg, adapter, bars, fee_rate=fee, funding_rate_hourly=0.0,
                    bar_hours=bar_minutes / 60.0)['net']


def sweep_windows(raw, bars, adapter, fee=0.0002, bar_minutes=5,
                  progress=None):
    """T9: the sweep read on two windows and tested out of sample. `bars`
    is the whole window (14 days); the newer half is the last 7. Three
    sweeps: the whole, the newer half, the older half. The count chosen
    on the OLDER half is then scored on the NEWER half against that half's
    own best: if it holds within a tenth, the choice travels; if not, the
    sweep is fitting noise and the page says so."""
    mid = len(bars) // 2
    older, newer = bars[:mid], bars[mid:]
    out = {'windows': {}, 'bars': len(bars), 'bar_minutes': bar_minutes}
    for wi, (name, part) in enumerate((('14d', bars), ('7d', newer),
                                       ('older7d', older))):
        def say(p, frac=None, name=name, wi=wi):
            if progress:
                progress(f'window {name}: {p}',
                         (wi + (frac or 0.0)) / 3.0 * 0.97)
        out['windows'][name] = sweep_rungs(raw, part, adapter, fee=fee,
                                           bar_minutes=bar_minutes,
                                           progress=say)
    lower, upper = float(raw['lower']), float(raw['upper'])
    out['visited'] = {'7d': visited_pct(newer, lower, upper),
                      '14d': visited_pct(bars, lower, upper)}
    fit = out['windows']['older7d']['best']
    newer_best = out['windows']['7d']['best']
    oos = {'fit_rungs': fit, 'newer_best': newer_best,
           'fit_net_newer': None, 'newer_best_net': None, 'holds': None}
    if fit is not None and newer_best is not None:
        if progress:
            progress('testing the older week\'s choice on the newer week',
                     0.98)
        rows = {r['rungs']: r for r in out['windows']['7d']['rows']}
        fit_net = (rows[fit]['net'] if fit in rows and 'net' in rows[fit]
                   else score_rungs(raw, fit, newer, adapter, fee,
                                    bar_minutes))
        best_net = rows[newer_best]['net']
        oos.update(fit_net_newer=fit_net, newer_best_net=best_net,
                   holds=(best_net <= 0 and fit_net >= best_net)
                   or (best_net > 0 and fit_net >= 0.9 * best_net))
    out['oos'] = oos
    out['dropped'] = out['windows']['14d'].get('dropped', [])
    return out


def draft_guards(draft):
    """The CLI's venue/strategy guards, one place, same words for every
    author (UI, file, agent) — a refusal is the engine speaking."""
    if draft.get('venue', 'bybit') not in VENUES_WITH_CANDLES:
        return "no kline fetcher for venue '%s' — one of %s" % (
            draft.get('venue'), ', '.join(VENUES_WITH_CANDLES))
    if draft.get('strategy', 'grid') == 'martingale':
        from .replay import refuse_replay
        return refuse_replay(draft)
    if draft.get('market_type') != 'linear':
        return ("the backtester's fee/PnL maths are linear-only — '%s' "
                'would return confident nonsense (A4)'
                % draft.get('market_type'))
    return None


def bars_and_adapter(cfg, bar_minutes, days):
    """Composition glue, by venue (A6): the market's own adapter from public
    data and its candles over the window. Raises LookupError for a market
    the venue does not list, OSError when it cannot be reached, ValueError
    for a bar length it has no candle for."""
    now = int(time.time() * 1000)
    since = now - int(days * 86_400_000)
    if cfg.get('venue') == 'hyperliquid':
        from .exchange.hyperliquid.adapters import HLPerpAdapter
        from .exchange.hyperliquid.klines import fetch_bars, fetch_instrument
        from .exchange.hyperliquid.truth import parse_instrument
        adapter = HLPerpAdapter(parse_instrument(fetch_instrument(cfg['symbol'])))
        return fetch_bars(cfg['symbol'], bar_minutes, since, now), adapter
    from .exchange.bybit.klines import fetch_bars, fetch_instrument
    from .exchange.bybit.truth import parse_instrument
    try:
        spec = fetch_instrument(cfg['market_type'], cfg['symbol'])
    except (IndexError, KeyError, TypeError):
        from .apply import not_listed
        raise LookupError(not_listed(
            cfg['symbol'], f"Bybit lists no such {cfg['market_type']} market "
                           '— its markets are named like BTCUSDT')) from None
    adapter = adapter_for(cfg['market_type'],
                          parse_instrument(cfg['market_type'], spec))
    return fetch_bars(cfg['market_type'], cfg['symbol'], bar_minutes,
                      since, now), adapter


def run_draft(raw, days, bar_minutes, fee, optimize=False, progress=None,
              windows=False):
    """--draft: validate a config that exists nowhere yet, fetch real
    bars, rehearse. Returns a dict; 'refused' carries the engine's own
    refusal text verbatim. With `optimize` (T8) the grid's rung count is
    swept instead, on 5-minute candles."""
    from .config import ConfigError, validate_config
    try:
        row = json.loads(raw)
        draft = validate_config(dict(row))
    except (ConfigError, ValueError) as e:
        return {'refused': str(e)}
    if optimize and draft.get('strategy') == 'martingale':
        return {'refused': 'the step is a grid\'s to find — a buy-the-dips '
                           'bot has its deviation and add-on orders, not '
                           'rungs; rehearse it instead (T8)'}
    why = draft_guards(draft)
    if why:
        return {'refused': why}
    if draft['strategy'] == 'martingale' or optimize:
        bar_minutes = MARTINGALE_BAR_MINUTES       # T7, and T8's sweep
    if windows:
        days = WINDOWS_DAYS                        # T9: one fetch, split
    # a draft is typed by a person: a market the venue does not list, or a
    # venue that cannot be reached, is a refusal in words — it used to be a
    # bare IndexError and "the rehearsal process died" (owner, 2026-10-02)
    if progress:
        progress('fetching candles', 0.02)                 # U26
    try:
        bars, adapter = bars_and_adapter(draft, bar_minutes, days)
    except (LookupError, ValueError) as e:
        return {'refused': str(e)}
    except OSError as e:
        who = ('Hyperliquid' if draft.get('venue') == 'hyperliquid'
               else 'Bybit')
        return {'refused': f"could not reach {who}'s public data ({e}) — "
                           'try again'}
    if not bars:
        return {'refused': 'no bars returned — check the symbol and window'}
    if optimize and windows:
        out = sweep_windows(row, bars, adapter, fee=fee,
                            bar_minutes=bar_minutes, progress=progress)
        out['draft_rungs'] = draft['rungs']
        return out
    if optimize:
        out = sweep_rungs(row, bars, adapter, fee=fee, bar_minutes=bar_minutes,
                          progress=progress)
        out['draft_rungs'] = draft['rungs']
        return out
    if progress:
        progress(f'replaying {len(bars)} candles', 0.5)
    return rehearse(draft, bars, adapter, fee=fee, bar_minutes=bar_minutes)


MARTINGALE_BAR_MINUTES = 5     # T7: a round turns on moves an hour hides


def main(argv):
    def opt(name, default):
        if name in argv:
            i = argv.index(name)
            v = argv[i + 1]
            del argv[i:i + 2]
            return v
        return default

    botid = opt('--bot', None)
    as_draft = '--draft' in argv
    if as_draft:
        argv.remove('--draft')
    optimize = '--optimize' in argv                 # T8
    if optimize:
        argv.remove('--optimize')
    windows = '--windows' in argv                   # T9
    if windows:
        argv.remove('--windows')
        optimize = True
    days = float(opt('--days', '7'))
    bar_minutes = int(opt('--bar-minutes', '60'))
    fee = float(opt('--fee', '0.0002'))
    funding = float(opt('--funding', '0'))
    if as_draft:
        # the options were parsed (and removed) above — asking opt() again
        # returned the DEFAULTS, so every draft ran 7 days whatever was
        # typed (found 2026-10-03)
        def say(p, frac=None):            # U26: progress on stderr, one
            print(json.dumps({'progress': p, 'frac': frac}), file=sys.stderr,
                  flush=True)
        out = run_draft(sys.stdin.read(), days, bar_minutes, fee,
                        optimize=optimize, progress=say, windows=windows)
        print(json.dumps(out))
        return 0 if 'refused' not in out else 1
    if len(argv) != 1 or not botid:
        print('usage: python3 -m gridgremlin.backtest_cli <fleet.json> '
              '--bot <botid> [--days 7] [--bar-minutes 60] [--fee 0.0002] '
              '[--funding 0] [--optimize] [--windows]   (or --draft, the row '
              'on stdin)')
        return 2
    raw_fleet = json.loads(Path(argv[0]).read_text())
    fleet = validate_fleet(json.loads(Path(argv[0]).read_text()))
    cfg = next((b for b in fleet['bots']
                if make_botid(b['market_type'], b['symbol'], b['side'])
                == botid), None)
    if cfg is None:
        known = [make_botid(b['market_type'], b['symbol'], b['side'])
                 for b in fleet['bots']]
        print(f'{botid}: not in this fleet — bots: {", ".join(known)}')
        return 2
    if cfg.get('venue') not in VENUES_WITH_CANDLES:
        print(f"{botid}: no kline fetcher for venue '{cfg.get('venue')}' — "
              f"one of {', '.join(VENUES_WITH_CANDLES)}")
        return 2
    dca = cfg.get('strategy') == 'martingale'
    if optimize and dca:
        print(f'{botid}: the step is a grid\'s to find — a buy-the-dips bot '
              'has its deviation and add-on orders, not rungs (T8)')
        return 2
    if optimize:
        bar_minutes = MARTINGALE_BAR_MINUTES           # T8: 5-minute candles
    if dca:
        from .replay import refuse_replay
        why = refuse_replay(cfg)
        if why:
            print(f'{botid}: {why}')
            return 2
        bar_minutes = MARTINGALE_BAR_MINUTES       # T7
    if cfg['market_type'] != 'linear':
        print(f"{botid}: the backtester's fee/PnL maths are linear-only — "
              f"'{cfg['market_type']}' would return confident nonsense (A4)")
        return 2
    try:
        bars, adapter = bars_and_adapter(cfg, bar_minutes, days)
    except (LookupError, ValueError) as e:
        print(f'{botid}: {e}')
        return 2
    if not bars:
        print('no bars returned — check the symbol and window')
        return 1
    if optimize:
        raw = next(b for b in raw_fleet['bots']
                   if make_botid(b['market_type'], b['symbol'], b['side'])
                   == botid)
        raw = {k: v for k, v in raw.items() if not k.startswith('_')}
        sw = sweep_rungs(raw, bars, adapter, fee=fee, bar_minutes=bar_minutes)
        print(f'{botid}: grid counts compared — {len(bars)} bars x {bar_minutes}m '
              f'over {days:g}d, range {cfg["lower"]:g}..{cfg["upper"]:g} as '
              f'set, score = net (T8/D50)')
        print(f"{'grids':>6}{'gap%':>7}{'net':>10}{'trips':>7}{'fees%':>7}"
              f"{'maxDD':>9}")
        for r in sw['rows']:
            if 'skipped' in r:
                print(f"{r['rungs']:>6}{r['gap_pct']:>7.2f}  {r['skipped']}")
                continue
            share = f"{r['fee_share'] * 100:>6.0f}%" if r['fee_share'] \
                is not None else f"{'—':>7}"
            mark = '  <- best' if r['rungs'] == sw['best'] else ''
            print(f"{r['rungs']:>6}{r['gap_pct']:>7.2f}{r['net']:>10.2f}"
                  f"{r['trips']:>7}{share}{r['max_drawdown']:>9.2f}{mark}")
        if sw['dropped']:
            print(f"  every grid sized equally for the sweep; set aside: "
                  f"{', '.join(sw['dropped'])}")
        if sw['best'] is not None:
            lo, hi = sw['plateau']
            print(f"  best {sw['best']} grids; {lo}..{hi} land within 5% of "
                  f"it; the row has {cfg['rungs']}. Nothing is applied — "
                  'type the number you choose into the form.')
        return 0
    if dca:
        r = rehearse(cfg, bars, adapter, fee=fee, bar_minutes=bar_minutes)
    else:
        r = backtest(cfg, adapter, bars, fee_rate=fee,
                     funding_rate_hourly=funding,
                     bar_hours=bar_minutes / 60.0)
    print(f'{botid}: {len(bars)} bars x {bar_minutes}m over {days:g}d')
    if dca:
        print(f"  {r['rounds']} rounds;  {r['so_fills']} add-on fills, "
              f"deepest {r['max_depth']};  {r['stops']} stop(s), "
              f"{r['max_hold_closes']} hold-limit close(s)")
        print(f"  ended: {r['ended'] or 'still running at the end'}")
    print(f"  {'round' if dca else 'grid'} profit {r['grid_profit']:,.2f}  fees {r['fees']:,.2f}  "
          f"funding {r['funding']:,.2f}  net {r['net']:,.2f}")
    print(f"  total (incl. open) {r['total']:,.2f}  "
          f"max drawdown {r['max_drawdown']:,.2f}")
    print(f"  {r['trips']} exit trips / {r['entry_fills']} entry fills;  "
          f"ends holding {r['held']:.10g}"
          + (f" @ {r['basis']:,.6g}" if r['basis'] else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
