"""U71: one coin's page — its market data over time, a chart for each kind
(K13): open interest, basis, the book's spread, depth and imbalance, retail
and top traders' long share, perpetual and spot taker flow — each with the
price faint behind it, over a day, a week or a month. Display only, from the
kept series; no venue is read here and nothing here decides anything."""
import html
import math
import time

from common.venues import VENUE_WORD as _VENUES
from gridgremlin.marketdata import SERIES, series

from .render import _num_cls

W, H, PAD_L, PAD_R, PAD_Y = 900, 170, 64, 10, 14
SPANS = (('24h', '24 hours', 1), ('7d', '7 days', 7), ('30d', '30 days', 30))
VENUE_COLOUR = {'bybit': 'var(--wild)', 'binance': 'var(--calm)', 'okx': 'var(--s3)'}
VENUE_WORD = dict(_VENUES, binance_accounts='Binance, by accounts',      # the venues' names (common, D91)
                  binance_positions='Binance, by position size',          # and the series' own labels
                  okx_positions='OKX, by position size', bybit_inverse='Bybit inverse')

# (heading, the series on it, how it is drawn, what it says)
CHARTS = (
    ('open interest', ('oi.bybit', 'oi.binance', 'oi.okx'), 'lines',
     'Money in open perpetual positions. Rising with the price: new longs; rising against it: new shorts; falling: positions closing.'),
    ('basis, perpetual over spot', ('basis.bybit',), 'lines',
     'How far the perpetual trades above the spot index. Above zero, longs pay up to hold: crowding; below, shorts do.'),
    ('top traders — share long', ('top.binance_accounts', 'top.binance_positions', 'top.okx_positions'), 'share',
     'The biggest accounts by margin (Binance\'s top 20%; OKX\'s elite). By position size weighs each by how much it holds.'),
    ('retail — share of all accounts long', ('retail.bybit', 'retail.binance', 'retail.okx'), 'share',
     'Every account counted once, whatever its size. Retail leaning hard one way while the top traders lean the other is the divergence to watch.'),
    ('perpetual taker flow, buys − sells', ('taker.binance', 'taker.okx'), 'bars',
     'Market orders that crossed the spread each hour on the perpetuals: aggressive buying above the line, selling below.'),
    ('spot net flow, taker buys − sells', ('spot.binance', 'spot.okx'), 'bars',
     'The same on spot: real coins bought or sold aggressively. Spot leading the perpetuals is demand; the perpetuals alone is leverage.'),
    ('funding, a year, paid by longs', ('funding.bybit', 'funding.bybit_inverse', 'funding.binance', 'funding.okx'), 'lines',
     'What longs paid shorts at each settlement, as a yearly rate (negative: shorts paid longs). The carry trade earns it on '
     'the short; a grid long pays it. Bybit\'s inverse dashed.'),
    ('bid–ask spread', ('spread.bybit', 'spread.binance'), 'lines',
     'The gap between the best bid and ask, in hundredths of a percent. Recorded hourly from the first reading.'),
    ('book depth within 1% of the mid', ('depth.bybit', 'depth.binance'), 'lines',
     'Resting orders within 1% either side: what a market order can fill against before the price moves 1%. Recorded hourly.'),
    ('book imbalance, bids − asks over both', ('imbalance.bybit', 'imbalance.binance'), 'share0',
     'Within 1% of the mid: above zero more bids rest than asks. Easy to fake with orders that are pulled. Recorded hourly.'),
)


def _venue(name):
    return name.split('.', 1)[1]


def _fmt(v, unit):
    if v is None:
        return '—'
    if unit == 'USD':
        a = abs(v)
        return (f'{v / 1e9:,.2f}B' if a >= 1e9 else f'{v / 1e6:,.1f}M' if a >= 1e6
                else f'{v / 1e3:,.0f}k' if a >= 1e3 else f'{v:,.0f}')
    if unit == 'share':
        return f'{v:.1%}'
    if unit == '%':
        return f'{v:+.3f}%'
    if unit == 'apr':
        return f'{v * 100:+.1f}%/yr'
    if unit == 'bps':
        return f'{v:.2f}'
    return f'{v:,.4g}'


def chart(lines, price, t0, t1, kind, unit):
    """One chart: each venue's line (or the venues' summed bars), the price
    faint behind on its own scale, the y range labelled, a midline where it
    means something (0, or 50% long)."""
    pts = [v for s in lines.values() for _, v in s]
    if kind == 'bars':
        summed = {}
        for s in lines.values():
            for t, v in s:
                summed[t] = summed.get(t, 0.0) + v
        pts = list(summed.values())
    if not pts:
        return '<p class="dim">nothing kept for this span yet</p>'
    lo, hi = min(pts), max(pts)
    if kind == 'share':
        lo, hi = min(lo, 0.5), max(hi, 0.5)
    if kind in ('bars', 'share0') or unit in ('%', 'apr'):
        lo, hi = min(lo, 0.0), max(hi, 0.0)
    if hi == lo:
        hi, lo = hi + (abs(hi) or 1) * 0.01, lo - (abs(lo) or 1) * 0.01
    pw, ph = W - PAD_L - PAD_R, H - 2 * PAD_Y
    span = (t1 - t0) or 1

    def x(t):
        return PAD_L + (t - t0) / span * pw

    def y(v):
        return PAD_Y + (hi - v) / (hi - lo) * ph

    out = []
    mid = 0.5 if kind == 'share' else 0.0 if (kind in ('bars', 'share0') or unit in ('%', 'apr')) else None
    if mid is not None and lo <= mid <= hi:
        out.append(f'<line x1="{PAD_L}" x2="{W - PAD_R}" y1="{y(mid):.1f}" y2="{y(mid):.1f}" '
                   'stroke="var(--line)" stroke-dasharray="4 3"/>')
    pp = [(t, v) for t, v in price if t0 <= t <= t1]
    if len(pp) > 1:                                 # the price, faint, on its own scale
        plo, phi = min(v for _, v in pp), max(v for _, v in pp)
        pr = (phi - plo) or 1
        out.append('<polyline fill="none" stroke="var(--dim)" stroke-opacity=".45" stroke-width="1" '
                   'vector-effect="non-scaling-stroke" points="'
                   + ' '.join(f'{x(t):.1f},{PAD_Y + (phi - v) / pr * ph:.1f}' for t, v in pp) + '"/>')
    if kind == 'bars':
        bw = max(1.0, pw / max(1, span / 3_600_000) * 0.8)
        z = y(0.0)
        for t, v in sorted(summed.items()):
            yy = y(v)
            out.append(f'<rect x="{x(t) - bw / 2:.1f}" y="{min(yy, z):.1f}" width="{bw:.1f}" '
                       f'height="{abs(z - yy):.1f}" fill="var({"--pos" if v >= 0 else "--neg"})" fill-opacity=".8"/>')
    else:
        for name, s in lines.items():
            if len(s) == 1:
                t, v = s[0]
                out.append(f'<circle cx="{x(t):.1f}" cy="{y(v):.1f}" r="3" fill="{VENUE_COLOUR.get(_venue(name).split("_")[0], "var(--fg)")}"/>')
            elif s:
                out.append(f'<polyline fill="none" stroke="{VENUE_COLOUR.get(_venue(name).split("_")[0], "var(--fg)")}" '
                           f'stroke-width="1.6" vector-effect="non-scaling-stroke"'
                           + (' stroke-dasharray="5 3"' if name.endswith(('accounts', 'inverse')) else '')
                           + ' points="' + ' '.join(f'{x(t):.1f},{y(v):.1f}' for t, v in s) + '"/>')
    out.append(f'<text x="{PAD_L - 6}" y="{PAD_Y + 4}" text-anchor="end" class="ax">{_fmt(hi, unit)}</text>'
               f'<text x="{PAD_L - 6}" y="{H - PAD_Y + 4}" text-anchor="end" class="ax">{_fmt(lo, unit)}</text>')
    return (f'<svg class="achart" viewBox="0 0 {W} {H}" width="100%" preserveAspectRatio="none" role="img">'
            + ''.join(out) + '</svg>')


def legend(lines, kind, unit):
    parts = []
    for name, s in lines.items():
        last = s[-1][1] if s else None
        colour = VENUE_COLOUR.get(_venue(name).split('_')[0], 'var(--fg)')
        parts.append(f'<span class="lg"><i style="background:{colour}"></i>{html.escape(VENUE_WORD.get(_venue(name), _venue(name)))} '
                     f'<b class="{_num_cls(last) if kind == "bars" else ""}">{_fmt(last, unit)}</b></span>')
    if kind == 'bars':
        tot = sum(s[-1][1] for s in lines.values() if s)
        parts.append(f'<span class="lg">last hour together <b class="{_num_cls(tot)}">{_fmt(tot, unit)}</b></span>')
    return '<div class="legend">' + ''.join(parts) + '<span class="lg dim">grey: the price</span></div>'


HEAT_COLS, HEAT_ROWS = 48, 60


def heatmap(coin, now, collect_root=None):
    """U74: the book over the last day (D84) — time across, price up the
    side, each cell shaded by the resting size there (bids below the price
    in one colour, asks above in the other, on a log scale), the price line
    over it. Empty until the collector has run."""
    from gridgremlin.collector import read_days
    rows = read_days(coin, 'book', now - 86400, collect_root)
    if not rows:
        return ('<p class="dim">nothing collected for this coin yet — the collector (D84) records '
                'the books every five minutes once its timer is started</p>')
    mid_now = rows[-1]['mid']
    lo, hi = mid_now * 0.95, mid_now * 1.05
    t0, t1 = now - 86400, now
    grid = {}
    for r in rows:
        col = min(HEAT_COLS - 1, int((r['t'] - t0) / 86400 * HEAT_COLS))
        for side in ('bids', 'asks'):
            for k, usd in r[side].items():
                p = r['ref'] * (1 + (int(k) + 0.5) * r['band'])
                if lo <= p <= hi:
                    row_i = min(HEAT_ROWS - 1, int((hi - p) / (hi - lo) * HEAT_ROWS))
                    key = (col, row_i, side)
                    grid[key] = max(grid.get(key, 0.0), usd)
    if not grid:
        return '<p class="dim">the collected books hold nothing within ±5% of the price</p>'
    vmax = math.log10(max(grid.values()) + 1)
    vmin = math.log10(min(grid.values()) + 1)
    cw, ch = W / HEAT_COLS, 240 / HEAT_ROWS
    cells = []
    for (col, row_i, side), usd in grid.items():
        a = (math.log10(usd + 1) - vmin) / ((vmax - vmin) or 1)
        cells.append(f'<rect x="{col * cw:.1f}" y="{row_i * ch:.1f}" width="{cw + 0.4:.1f}" height="{ch + 0.4:.1f}" '
                     f'fill="var({"--pos" if side == "bids" else "--neg"})" fill-opacity="{0.08 + 0.85 * a:.2f}"/>')
    line = ' '.join(f'{(r["t"] - t0) / 86400 * W:.1f},{(hi - r["mid"]) / (hi - lo) * 240:.1f}' for r in rows)
    biggest = sorted(grid.items(), key=lambda kv: -kv[1])[:1]
    (bc, br, bs), bu = biggest[0]
    wall_p = hi - (br + 0.5) * (hi - lo) / HEAT_ROWS
    return (f'<svg class="achart" viewBox="0 0 {W} 240" width="100%" preserveAspectRatio="none" style="height:240px" role="img">'
            + ''.join(cells)
            + f'<polyline fill="none" stroke="var(--fg)" stroke-width="1.4" vector-effect="non-scaling-stroke" points="{line}"/>'
            f'<text x="4" y="12" class="ax">{_fmt(hi, "")}</text><text x="4" y="236" class="ax">{_fmt(lo, "")}</text></svg>'
            f'<p class="dim">The last day, {len(rows)} snapshots of Coinbase\'s whole spot book and OKX\'s deep perpetual '
            f'book, in 0.1% bands across ±5% of the price. Green: bids resting below; red: asks resting above; the deeper '
            f'the colour, the more rests there (log scale). The largest band now: {"bids" if bs == "bids" else "asks"} '
            f'near {wall_p:,.6g}, {_fmt(bu, "USD")}.</p>')


def liquidations(coin, now, days=1, collect_root=None):
    """U74: OKX's liquidations of the coin (D84) — each hour's longs and
    shorts wiped out, as bars (longs below the line, shorts above), and the
    largest ones in a list."""
    from gridgremlin.collector import read_days
    rows = read_days(coin, 'liq', now - days * 86400, collect_root)
    if not rows:
        return ('<p class="dim">no liquidations recorded for this coin yet — the collector (D84) reads '
                'OKX\'s every five minutes once its timer is started</p>')
    hours = days * 24
    t0 = now - days * 86400
    buckets = [[0.0, 0.0] for _ in range(hours)]
    for r in rows:
        h = min(hours - 1, int((r['ts'] / 1000 - t0) / 3600))
        buckets[h][0 if r['side'] == 'long' else 1] += r['usd']
    top = max(max(b) for b in buckets) or 1.0
    bw = W / hours
    bars = []
    for h, (lg, sh) in enumerate(buckets):
        if sh:
            bars.append(f'<rect x="{h * bw:.1f}" y="{80 - sh / top * 76:.1f}" width="{max(1.0, bw * 0.8):.1f}" '
                        f'height="{sh / top * 76:.1f}" fill="var(--pos)"/>')
        if lg:
            bars.append(f'<rect x="{h * bw:.1f}" y="80" width="{max(1.0, bw * 0.8):.1f}" '
                        f'height="{lg / top * 76:.1f}" fill="var(--neg)"/>')
    tl, ts_ = sum(b[0] for b in buckets), sum(b[1] for b in buckets)
    by_venue = {}
    for r in rows:
        v = r.get('venue') or 'okx'
        by_venue[v] = by_venue.get(v, 0.0) + r['usd']
    venues = ' · '.join(f'{VENUE_WORD.get(v, v)} {_fmt(u, "USD")}' for v, u in sorted(by_venue.items(), key=lambda kv: -kv[1]))
    big = sorted(rows, key=lambda r: -r['usd'])[:8]
    items = ''.join(f'<tr><td>{time.strftime("%m-%d %H:%M", time.gmtime(r["ts"] / 1000))} UTC</td>'
                    f'<td>{html.escape(VENUE_WORD.get(r.get("venue") or "okx", r.get("venue") or "okx"))}</td>'
                    f'<td class="{"neg" if r["side"] == "long" else "pos"}">{r["side"]}</td>'
                    f'<td class="num">{r["px"]:,.6g}</td><td class="num">{_fmt(r["usd"], "USD")}</td></tr>' for r in big)
    return (f'<div class="legend"><span class="lg"><i style="background:var(--neg)"></i>longs liquidated '
            f'<b>{_fmt(tl, "USD")}</b></span><span class="lg"><i style="background:var(--pos)"></i>shorts liquidated '
            f'<b>{_fmt(ts_, "USD")}</b></span><span class="lg dim">{len(rows)} orders, the last {days * 24} h — {venues}</span></div>'
            f'<svg class="achart" viewBox="0 0 {W} 160" width="100%" preserveAspectRatio="none" style="height:160px" role="img">'
            f'<line x1="0" x2="{W}" y1="80" y2="80" stroke="var(--line)"/>' + ''.join(bars) + '</svg>'
            '<div class="scroll"><table class="cwtab"><tr><th>when</th><th>venue</th><th>position</th><th>price</th><th>size</th></tr>'
            f'{items}</table></div><p class="dim">A long liquidated is a forced sell (the price fell to it); a short, a '
            'forced buy. OKX read every five minutes; Bybit recorded live from its stream (when the stream unit runs). '
            'Binance\'s futures stream is closed to this server\'s country.</p>')


def asset_page(coin, coins, span='7d', now=None, root=None, unread=None, collect_root=None):
    now = time.time() if now is None else now
    days = dict((k, d) for k, _, d in SPANS).get(span, 7)
    span = span if span in dict((k, w) for k, w, _ in SPANS) else '7d'
    t1 = int(now * 1000)
    t0 = t1 - days * 86_400_000
    names = ['price'] + [n for _, ns, _, _ in CHARTS for n in ns]
    kept = series(coin, names, t0, root)
    e = html.escape
    picker = ' · '.join(f'<b class="on">{e(c)}</b>' if c == coin else f'<a href="/asset?coin={e(c)}&span={span}">{e(c)}</a>'
                        for c in coins)
    spans = ' · '.join(f'<b class="on">{w}</b>' if k == span else f'<a href="/asset?coin={e(coin)}&span={k}">{w}</a>'
                       for k, w, _ in SPANS)
    price = kept.get('price') or []
    head = (f'<h1>{e(coin)} <span class="dim">market data</span></h1><p>{picker}</p><p>{spans}</p>')
    if not price:
        return head + ('<p class="dim">nothing kept for this coin yet — the hourly market job fills '
                       'logs/series/ from its next run</p>')
    p0, p1 = price[0][1], price[-1][1]
    head += (f'<p><b class="num">{p1:,.6g}</b> <span class="{_num_cls(p1 - p0)}">{(p1 / p0 - 1) * 100:+.2f}%</span> '
             f'<span class="dim">over {dict((k, w) for k, w, _ in SPANS)[span]} · Bybit\'s perpetual · '
             'Bybit, Binance and OKX public data, kept hourly</span></p>')
    body = []
    for heading, ns, kind, says in CHARTS:
        lines = {n: kept.get(n) or [] for n in ns}
        unit = SERIES[ns[0]][1]
        miss = [VENUE_WORD.get(_venue(n), _venue(n)) for n in ns if (unread or {}).get(n)]
        body.append(f'<section class="achart-box" id="{e(ns[0].split(".")[0])}"><h2>{e(heading)}</h2>'
                    f'{legend(lines, kind, unit)}{chart(lines, price, t0, t1, kind, unit)}'
                    f'<p class="dim">{e(says)}'
                    + (f' Not read this hour: {e(", ".join(miss))}.' if miss else '') + '</p></section>')
    days = 1 if span == '24h' else 7
    body.append(f'<section class="achart-box" id="heatmap"><h2>liquidity heatmap</h2>'
                f'{heatmap(coin, now, collect_root)}</section>')
    body.append(f'<section class="achart-box" id="liquidations"><h2>liquidations</h2>'
                f'{liquidations(coin, now, days, collect_root)}</section>')
    return head + ''.join(body) + '<p class="dim">Display only — no bot reads this.</p>'
