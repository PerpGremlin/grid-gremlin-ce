"""U73: how a grid fits the market it would trade — on the review page,
beside the what-if. The grid's own levels (the engine's lattice) walked
along the last month's candles: how often the price crossed a grid, so how
many round trips and roughly what they would have made after fees; how
much of the month the price sat inside the range; the funding at full size
and the coin's calm-or-wild reading. Display only; an estimate, said so."""
import bisect
import html

from gridgremlin.fees import BYBIT_MAKER
from gridgremlin.ladder import lattice_price

from .render import _num_cls


def _path(bar):
    """A candle's likeliest path: to the nearer extreme first."""
    o, h, low, c = bar['o'], bar['h'], bar['l'], bar['c']
    return (o, h, low, c) if abs(h - o) <= abs(o - low) else (o, low, h, c)


def fit_numbers(cfg, bars, fee=BYBIT_MAKER):
    """A validated grid against candles (oldest first, each {t, o, h, l, c}):
    the gap between grids, what one round trip nets after two maker fees,
    the grid crossings, round trips a day, an estimated grid profit a day
    and its yearly rate on the investment, and the share of candles that
    closed inside the range."""
    n = cfg['rungs']
    levels = [lattice_price(cfg, j) for j in range(n)]
    mid = levels[n // 2]
    gap = (levels[n // 2 + 1] - mid) / mid if n > 2 else (cfg['upper'] - cfg['lower']) / cfg['lower']
    per_rung = cfg['ladder_notional'] / n
    net = per_rung * (gap - 2 * fee)
    # the grid's own walk: a long buys when the price falls through a level
    # it does not hold and sells that piece when the price reaches the level
    # above (a short the mirror) — a wiggle across one level completes
    # nothing (2026-10-11: counting crossings claimed twice to twenty times
    # the rehearsal's round trips, worse the finer the candles)
    long = cfg.get('side', 'long') != 'short'
    held, crossings = set(), 0
    for b in bars:
        pts = _path(b)
        for a, z in zip(pts, pts[1:]):
            if z < a:                                  # falling: levels in (z, a], highest first
                for j in range(bisect.bisect_right(levels, a) - 1, bisect.bisect_right(levels, z) - 1, -1):
                    if long and j < n - 1:
                        held.add(j)                    # bought at j, to sell at j + 1
                    elif not long and j + 1 in held:
                        held.discard(j + 1)
                        crossings += 1                 # a short's piece sold at j + 1, bought back at j
            elif z > a:                                # rising: levels in [a, z), lowest first
                for j in range(bisect.bisect_left(levels, a), bisect.bisect_left(levels, z)):
                    if long and j - 1 in held:
                        held.discard(j - 1)
                        crossings += 1                 # bought at j - 1, sold at j
                    elif not long and j > 0:
                        held.add(j)                    # sold short at j, to buy back at j - 1
    days = ((bars[-1]['t'] - bars[0]['t']) / 86_400_000 + (bars[1]['t'] - bars[0]['t']) / 86_400_000
            if len(bars) > 1 else 0.0)
    trips = crossings / days if days else 0.0
    inside = sum(1 for b in bars if cfg['lower'] <= b['c'] <= cfg['upper']) / len(bars) if bars else 0.0
    per_day = trips * net
    capital = cfg.get('capital') or 0.0
    return {'gap': gap, 'per_rung': per_rung, 'net_trip': net, 'days': days,
            'trips': crossings, 'trips_day': trips, 'per_day': per_day, 'apr': per_day * 365 / capital if capital else None,
            'inside': inside, 'fee': fee}


def fit_section(cfg, bars, row=None):
    """The section for the review page; a grid only (a DCA has no lattice)."""
    if cfg.get('strategy') == 'martingale' or not bars or len(bars) < 2:
        return ''
    f = fit_numbers(cfg, bars)
    sym = cfg['symbol']
    coin = sym[:-4] if sym.endswith('USDT') else sym[:-4] if sym.endswith('PERP') else sym[:-3] if sym.endswith('USD') else sym
    lines = []
    m = ((row or {}).get('markets') or {}).get(f"bybit:{cfg.get('market_type', 'linear')}:{sym}") or {}
    f8 = m.get('funding_8h_pct')
    if f8 is not None and cfg.get('market_type') != 'spot':
        full = cfg['ladder_notional']
        sign = 1 if cfg.get('side') == 'short' else -1          # longs pay positive funding
        day = sign * full * f8 / 100 * 3
        lines.append(f'<tr><td>funding a day if every buy filled ({full:,.0f} held, {f8:+.4f}% / 8 h now)</td>'
                     f'<td class="num {_num_cls(day)}">{day:+,.2f}</td></tr>')
    h = ((row or {}).get('hmm') or {}).get(coin)
    if h and h.get('two_states'):
        lines.append(f'<tr><td>the market now (the hidden model)</td><td><b class="{h["state"]}">{h["state"]}</b> '
                     f'· {h["p_wild"]:.0%} wild · calm ±{h["sd_day"][0]:.1%}/day, wild ±{h["sd_day"][1]:.1%}/day</td></tr>')
    warn = ''
    if f['net_trip'] <= 0:
        warn = (f'<p class="neg">A grid {f["gap"]:.2%} apart earns less than the two fees it pays '
                f'({2 * f["fee"]:.2%}): every round trip loses. Fewer grids, or a wider range.</p>')
    elif f['inside'] < 0.5:
        warn = (f'<p class="neg">The price closed inside this range only {f["inside"]:.0%} of the last month: '
                'a grid earns only while the price is inside it.</p>')
    return ('<h2 class="dim">how it fits this market</h2>' + warn
            + '<table class="cwtab">'
            f'<tr><td>gap between grids</td><td class="num">{f["gap"]:.2%}</td></tr>'
            f'<tr><td>a round trip nets, after two maker fees ({f["fee"]:.3%} each) on {f["per_rung"]:,.2f}</td>'
            f'<td class="num {_num_cls(f["net_trip"])}">{f["net_trip"]:+,.3f}</td></tr>'
            f'<tr><td>round trips over the last {f["days"]:.0f} days (bought a level, sold the one above)</td><td class="num">{f["trips"]:,}</td></tr>'
            f'<tr><td>round trips a day, at that pace</td><td class="num">{f["trips_day"]:,.1f}</td></tr>'
            f'<tr><td><b>grid profit a day, estimated</b></td><td class="num"><b class="{_num_cls(f["per_day"])}">{f["per_day"]:+,.2f}</b></td></tr>'
            + (f'<tr><td>that as a year on the investment, grid profit only</td><td class="num {_num_cls(f["apr"])}">{f["apr"]:+.0%}</td></tr>'
               if f['apr'] is not None else '')
            + f'<tr><td>the last month inside the range</td><td class="num">{f["inside"]:.0%} of 4-hour closes</td></tr>'
            + ''.join(lines) + '</table>'
            '<p class="dim">An estimate: the grid\'s own levels walked along the last month\'s 4-hour candles '
            '(open → nearer extreme → the other → close), a piece bought at a level and sold at the one above. '
            'Checked against the engine\'s rehearsal on four grids (2026-10-11): round trips within 12%; the '
            'profit runs above what the rehearsal realised. Grid profit only — what the held coins gain or lose '
            'when the price leaves the range is the what-if\'s, above. <b>rehearse</b> below replays the real bot. '
            'Not a forecast.</p>')
