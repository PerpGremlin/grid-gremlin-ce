"""U71: one coin's page — its market data over time, a chart for each kind
(K13): open interest, basis, the book's spread, depth and imbalance, retail
and top traders' long share, perpetual and spot taker flow — each with the
price faint behind it, over a day, a week or a month. Display only, from the
kept series; no venue is read here and nothing here decides anything."""
import html
import time

from gridgremlin.marketdata import SERIES, series

from .render import _num_cls

W, H, PAD_L, PAD_R, PAD_Y = 900, 170, 64, 10, 14
SPANS = (('24h', '24 hours', 1), ('7d', '7 days', 7), ('30d', '30 days', 30))
VENUE_COLOUR = {'bybit': 'var(--wild)', 'binance': 'var(--calm)', 'okx': 'var(--s3)'}
VENUE_WORD = {'bybit': 'Bybit', 'binance': 'Binance', 'okx': 'OKX',
              'binance_accounts': 'Binance, by accounts', 'binance_positions': 'Binance, by position size',
              'okx_positions': 'OKX, by position size'}

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
    if kind in ('bars', 'share0') or unit == '%':
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
    mid = 0.5 if kind == 'share' else 0.0 if (kind in ('bars', 'share0') or unit == '%') else None
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
                           + (' stroke-dasharray="5 3"' if name.endswith('accounts') else '')
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


def asset_page(coin, coins, span='7d', now=None, root=None, unread=None):
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
    return head + ''.join(body) + '<p class="dim">Display only — no bot reads this.</p>'
