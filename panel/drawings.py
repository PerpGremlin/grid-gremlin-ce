"""The SVG drawings: the range strip, the equity line, the price line with its levels and fills (U63, U65). Out of render.py (D91 step 3)."""
import time

from .html_bits import _num_cls



def strip(rng, mark, width='120'):
    """The range as a picture: bar, rung ticks, mark dot. Inline SVG,
    server-side, no scripts — a glance instead of arithmetic."""
    if not rng or not mark:
        return ''
    lo, hi = rng['lower'], rng['upper']
    span = hi - lo or 1.0
    x = max(0.0, min(1.0, (mark - lo) / span)) * 100
    ticks = ''.join(
        f'<line x1="{lo_x:.1f}" y1="3" x2="{lo_x:.1f}" y2="9" '
        'stroke="var(--line)"/>'
        for i in range(rng.get('rungs') or 0)
        for lo_x in [i / max(1, (rng['rungs'] - 1)) * 100])
    return (f'<svg width="{width}" height="12" viewBox="0 0 100 12" '
            f'preserveAspectRatio="none"><rect x="0" y="4" width="100" '
            f'height="4" fill="var(--line)"/>{ticks}'
            f'<circle cx="{x:.1f}" cy="6" r="3" fill="var(--accent)"/></svg>')


def equity_svg(points, width=120, height=18, labels=False):
    """U63: the account's equity as a line — one series, two pixels, the
    page's own ink: the accent for the line, the sign's colour only on the
    change it says. A sparkline for the strip (no labels), the box's chart
    with its low, its high and the change over the window, and a native
    tooltip per point (no script). Fewer than two points draw nothing."""
    pts = [(float(t), float(e)) for t, e in (points or [])]
    if len(pts) < 2:
        return ''
    lo, hi = min(e for _, e in pts), max(e for _, e in pts)
    t0, t1 = pts[0][0], pts[-1][0]
    span_e, span_t = (hi - lo) or 1.0, (t1 - t0) or 1.0
    W, H, pad = float(width), float(height), (3.0 if labels else 1.5)
    def xy(t, e):
        return (pad + (t - t0) / span_t * (W - 2 * pad),
                H - pad - (e - lo) / span_e * (H - 2 * pad))
    path = ' '.join(f'{x:.1f},{y:.1f}' for x, y in (xy(t, e) for t, e in pts))
    change = pts[-1][1] - pts[0][1]
    cls = 'pos' if change >= 0 else 'neg'
    body = (f'<polyline points="{path}" fill="none" stroke="var(--accent)" '
            'stroke-width="2" stroke-linejoin="round" stroke-linecap="round" '
            'vector-effect="non-scaling-stroke"/>')
    if labels:
        import time as _t
        step = max(1, len(pts) // 48)                   # a tooltip every few points, not every one
        hover = ''.join(
            f'<rect x="{xy(t, e)[0] - (W / len(pts)) / 2 * step:.1f}" y="0" '
            f'width="{(W / len(pts)) * step:.1f}" height="{H:.0f}" fill="transparent">'
            f'<title>{_t.strftime("%d %b %H:%M", _t.gmtime(t))} UTC · {e:,.2f}</title></rect>'
            for t, e in pts[::step])
        x1, y1 = xy(*pts[-1])
        body += (f'<line x1="{pad}" y1="{H - pad:.1f}" x2="{W - pad:.1f}" y2="{H - pad:.1f}" '
                 'stroke="var(--line)" stroke-width="1"/>'
                 f'<circle cx="{x1:.1f}" cy="{y1:.1f}" r="3" fill="var(--{cls})"/>' + hover)
    svg = (f'<svg class="eq" viewBox="0 0 {W:.0f} {H:.0f}" width="{"100%" if labels else width}" '
           f'height="{height}" preserveAspectRatio="none" role="img">{body}</svg>')
    if not labels:
        return svg
    pct = change / pts[0][1] * 100 if pts[0][1] else 0.0
    f = ',.0f' if hi - lo >= 100 else ',.2f'          # a small account's move is not rounded away
    return (f'<div class="eqbox"><div class="dim eqlab"><span>low {lo:{f}}</span><span>high {hi:{f}}</span>'
            f'<b class="{cls}">{change:+{f}} ({pct:+.1f}%)</b></div>{svg}</div>')


def price_svg(series, window=None, liq=None, fills=(), height=180):
    """U65: one position's price over the window, with the bot's own
    levels and fills — the price line in the accent, the window's rungs as
    faint lines and its edges dashed, buys and sells as ringed dots (a
    native tooltip each), liquidation in red when it is on the chart and
    named beneath when it is not. No script; nothing without two points."""
    import time as _t
    pts = [(float(t), float(p)) for t, p in (series or [])]
    if len(pts) < 2:
        return ''
    t0, t1 = pts[0][0], pts[-1][0]
    fs = [(t, p, s) for t, p, s in fills if t0 <= t <= t1]
    ys = [p for _, p in pts] + [p for _, p, _ in fs]
    lo, hi = min(ys), max(ys)
    pad_y = (hi - lo) * 0.08 or hi * 0.002 or 1.0
    lo, hi = lo - pad_y, hi + pad_y
    W, H, L, R, T, B = 800.0, float(height), 4.0, 64.0, 6.0, 18.0
    def x(t):
        return L + (t - t0) / ((t1 - t0) or 1.0) * (W - L - R)
    def y(p):
        return T + (hi - p) / ((hi - lo) or 1.0) * (H - T - B)
    parts = []
    if window:
        lw, uw, n = window['lower'], window['upper'], int(window.get('rungs') or 0)
        gap = (uw - lw) / (n - 1) if n > 1 else 0.0
        dash = ' stroke-dasharray="4 3"'
        for i in range(n):
            lv = lw + i * gap
            if lo <= lv <= hi:
                edge = i in (0, n - 1)
                parts.append(f'<line x1="{L}" x2="{W - R}" y1="{y(lv):.1f}" y2="{y(lv):.1f}" stroke="var(--line)" '
                             f'stroke-width="1"{dash if edge else ""}/>')
        for lv, word in ((lw, 'bottom'), (uw, 'top')):
            if lo <= lv <= hi:
                parts.append(f'<text x="{W - R + 4}" y="{y(lv) + 4:.1f}" class="ax">{word} {lv:,.6g}</text>')
    off = ''
    if liq:
        if lo <= liq <= hi:
            parts.append(f'<line x1="{L}" x2="{W - R}" y1="{y(liq):.1f}" y2="{y(liq):.1f}" stroke="var(--neg)" '
                         'stroke-width="1.5" stroke-dasharray="6 3"/>'
                         f'<text x="{W - R + 4}" y="{y(liq) + 4:.1f}" class="ax neg">liq {liq:,.6g}</text>')
        else:
            off = f' · liquidation at {liq:,.6g}, {"below" if liq < lo else "above"} the chart'
    path = ' '.join(f'{x(t):.1f},{y(p):.1f}' for t, p in pts)
    parts.append(f'<polyline points="{path}" fill="none" stroke="var(--accent)" stroke-width="2" '
                 'stroke-linejoin="round" stroke-linecap="round"/>')
    for t, p, s in fs:
        col = 'var(--pos)' if s == 'buy' else 'var(--neg)'
        parts.append(f'<circle cx="{x(t):.1f}" cy="{y(p):.1f}" r="4" fill="{col}" stroke="var(--bg)" stroke-width="2">'
                     f'<title>{s} {p:,.6g} · {_t.strftime("%d %b %H:%M", _t.gmtime(t))} UTC</title></circle>')
    step = max(1, len(pts) // 60)
    for t, p in pts[::step]:
        parts.append(f'<rect x="{x(t) - 6:.1f}" y="{T}" width="12" height="{H - T - B:.0f}" fill="transparent">'
                     f'<title>{_t.strftime("%d %b %H:%M", _t.gmtime(t))} UTC · {p:,.6g}</title></rect>')
    parts.append(f'<text x="{L}" y="{H - 4}" class="ax">{_t.strftime("%d %b %H:%M", _t.gmtime(t0))}</text>'
                 f'<text x="{W - R}" y="{H - 4}" class="ax" text-anchor="end">{_t.strftime("%d %b %H:%M", _t.gmtime(t1))} UTC</text>'
                 f'<text x="{W - R + 4}" y="{y(pts[-1][1]) + 4:.1f}" class="ax">{pts[-1][1]:,.6g}</text>')
    buys = sum(1 for f in fs if f[2] == 'buy')
    key = (f'<div class="dim pkey"><span class="k-line"></span>price · <span class="k-buy"></span>{buys} buys · '
           f'<span class="k-sell"></span>{len(fs) - buys} sells · rungs of the window{off}</div>')
    return (f'<svg class="px" viewBox="0 0 {W:.0f} {H:.0f}" width="100%" role="img" '
            f'aria-label="price with the bot\'s levels and fills">{"".join(parts)}</svg>{key}')


def price_boxes(prices, window, liq, fills):
    """U65: the day and the week of one position's price, or one quiet
    line until the snapshots carry it."""
    prices = prices or {}
    day = price_svg(prices.get('24h'), window, liq, fills)
    week = price_svg(prices.get('7d'), window, liq, fills)
    if not day and not week:
        return ('<p class="dim">price line: the engine has not recorded this bot\'s price yet '
                '(it starts with the fleet\'s next restart)</p>')
    return ((f'<h3>price, 24 h</h3>{day}' if day else '') + (f'<h3>price, 7 d</h3>{week}' if week else ''))


def equity_boxes(contract, idx=0):
    """U63: the windows under the exchange's box — a day and a week, and
    (U91) a month and the whole history, each long one with its Sharpe
    ratio (daily, on a year's scale) — or one quiet line while the snapshot
    file has nothing yet. U103: one window at a time; its heading is the
    switch to the next (radios and CSS, no script, so an export works
    the same)."""
    eq = contract.get('equity') or {}
    sh = eq.get('sharpe') or {}
    boxes = []
    for key, word in (('24h', '24 h'), ('7d', '7 d'), ('30d', '30 d'), ('all', 'all time')):
        svg = equity_svg(eq.get(key), 400, 60, labels=True)
        if not svg:
            continue
        if key in ('30d', 'all'):
            s = sh.get(key)
            pts = eq.get(key) or []
            days = (pts[-1][0] - pts[0][0]) / 86400 if len(pts) > 1 else 0
            word += (f' · Sharpe <b class="{_num_cls(s)}">{s:+.2f}</b>' if s is not None
                     else ' · Sharpe — (under ten days)' if days < 10
                     else ' · Sharpe — (no day-to-day movement)')
            tr = (eq.get('trust') or {}).get(key)
            if s is not None and tr:                # U91b: never a Sharpe alone
                word += (f' · {tr["likely"]:.0%} likely above zero · '
                         + (f'about {tr["more"]:,.0f} more days to tell from luck' if tr['more']
                            else 'told from luck' if tr['more'] == 0 else 'never, at this rate'))
            if key == 'all' and eq.get('all'):
                word += f' · since {time.strftime("%d %b", time.gmtime(eq["all"][0][0]))}'
        boxes.append((key, word.split(' · ')[0], word, svg))
    if not boxes:
        return '<div class="dim">equity line: no history yet</div>'
    note = (SHARPE_NOTE if 'sharpe' in eq else '')
    name = f'eq-{idx}'
    radios = ''.join(f'<input type="radio" name="{name}" id="{name}-{k}" class="rsel eqpick"'
                     f'{" checked" if i == 0 else ""}>' for i, (k, *_) in enumerate(boxes))
    wins = []
    for i, (key, short, word, svg) in enumerate(boxes):
        nk, nshort = boxes[(i + 1) % len(boxes)][:2]
        head = (f'<label for="{name}-{nk}" class="eqnext">equity, {word} '
                f'<span class="eqgo">{nshort} ▸</span></label>' if len(boxes) > 1
                else f'equity, {word}')
        wins.append(f'<div class="eqwin"><div class="dim">{head}</div>{svg}</div>')
    return f'<div class="eqrow eqsw">{radios}{"".join(wins)}</div>' + note


# U91b: the owner's rule for the site — every piece of maths in plain words
SHARPE_NOTE = ('<p class="dim eqnote">Sharpe: each day\'s gain or loss, averaged, divided by '
               'how much the days swing, then scaled to a year (times the square root of 365). '
               'Above 1 is good; below 0 lost money. "Likely above zero" is the chance the true '
               'figure is above zero, skew and big days counted, and the days are how many more '
               'it needs before that chance reaches 95%. Money added or taken out moves it too. '
               'Credits: the Sharpe ratio is William F. Sharpe\'s ("Mutual Fund Performance", 1966); '
               'the chance and the days are the probabilistic Sharpe ratio and minimum track '
               'record length of David H. Bailey and Marcos López de Prado ("The Sharpe Ratio '
               'Efficient Frontier", 2012).</p>')
