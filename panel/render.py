"""The panel's renderer: the cards, the table, the strip and the side panel,
all from the readout's contract (§4: one renderer, two artefacts)."""
import http.server
import os
from pathlib import Path
import urllib.parse
import html
from gridgremlin.report import card_total, money_units
import json
import re
import secrets
import subprocess
import sys
import time
from panel.chart import _f

from .css import CSS
from .reference import KEEP_JS, STATE_WORDS

REFRESH_S = 15          # the readout hits venue APIs: poll gently


WATCHDOG_OFF_S = 3600   # no sweep for an hour: it is off, not late (D39)


def money(v, cls=True):
    if v is None:
        return '<td class="dim">—</td>'
    c = ' class="pos"' if (cls and v > 0) else (' class="neg"'
                                               if cls and v < 0 else '')
    return f'<td{c}>{v:,.2f}</td>'


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
    return (f'<div class="eqbox"><div class="dim eqlab"><span>low {lo:,.0f}</span><span>high {hi:,.0f}</span>'
            f'<b class="{cls}">{change:+,.0f} ({pct:+.1f}%)</b></div>{svg}</div>')


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


def equity_boxes(contract):
    """U63: the two windows under the exchange's box — a day and a week —
    or one quiet line while the snapshot file has nothing yet."""
    eq = contract.get('equity') or {}
    day, week = equity_svg(eq.get('24h'), 400, 60, labels=True), equity_svg(eq.get('7d'), 400, 60, labels=True)
    if not day and not week:
        return '<div class="dim">equity line: no history yet</div>'
    return ('<div class="eqrow">'
            + (f'<div><div class="dim">equity, 24 h</div>{day}</div>' if day else '')
            + (f'<div><div class="dim">equity, 7 d</div>{week}</div>' if week else '')
            + '</div>')


def run_rate(b, contract, capital=None, trade=False):
    """U64: what every grid product states — how long the bot has run in
    the figure's own span, its grid profit (realised after fees) per day,
    and that as a yearly rate on its investment. Bybit's way: grid profit /
    investment / days x 365, a run under a day counted as one day. Returns
    the line, or '' without fills or a span."""
    gen = contract.get('generated_ms')
    how = b.get('counted_from')
    start = (b.get('counted_since_ms') if how == 'flat' else
             b.get('first_ms') if how == 'cap' else
             gen - contract.get('window_hours', 24) * 3.6e6 if gen else None)
    if not gen or not start or not b.get('fills'):
        return ''
    days = max(1.0, (gen - start) / 8.64e7)
    shown = (gen - start) / 8.64e7
    net = b['realized'] - b['fees']
    per_day = net / days
    run = f'{shown:.1f} d' if shown >= 1 else f'{shown * 24:.0f} h'
    word = '' if trade else 'grid '          # a trade (D81) has no grid
    line = (f'running {run} · {word}profit <b class="{_num_cls(per_day)}">{per_day:+,.2f}</b>/day')
    if capital:
        apr = net / capital / days * 365 * 100
        line += f' · {word}APR <b class="{_num_cls(apr)}">{apr:+,.1f}%</b>'
    return f'<div class="rate">{line}</div>'


def settle(b, floor):
    """Stop now and you receive: the number every user reaches for and
    nobody ships. Position sold at mark, less the venue-shaped fee —
    an estimate and labelled as one."""
    if abs(b['position']) < 1e-12 or not b['mark']:
        return '<span class="dim">flat</span>'
    if b.get('inverse'):            # A4: a contract is one dollar
        quote = abs(b['position']) * (1.0 - (floor or 0.0))
    else:
        quote = abs(b['position']) * b['mark'] * (1.0 - (floor or 0.0))
    return f'~{quote:,.2f} quote'


def sweep_note(contract):
    wd = contract.get('watchdog') or {}
    ago = wd.get('swept_s_ago')
    if ago is None:
        return '<span class="dim">watchdog OFF</span>'
    if ago > WATCHDOG_OFF_S:
        return '<span class="dim">watchdog OFF</span>'
    if ago > 900:              # it should sweep every 5 minutes: it is late
        return (f'<span class="neg">watchdog late: swept {ago / 60:.0f} '
                'min ago</span>')
    return f'<span class="dim">watchdog swept {ago}s ago</span>'


def setup_button(draft, note, rungs=None, label='set up this bot &rarr;',
                 quiet=True):
    """U30: a verdict hands its exact draft to the advanced form — the
    panel's own reopen door — with the verdict's words as the note on top.
    Opens the form; a human still walks every gate."""
    from panel.setup import form_from_bot
    import html as _h
    row = {k: v for k, v in (draft or {}).items()
           if not k.startswith('_') and k not in ('rung_weights', 'seed')}
    if rungs is not None:
        row['rungs'] = rungs
        row.pop('rung_sizing', None)        # weights were set aside (T8)
    vals = form_from_bot(row)
    return ('<form method="post" action="/setup" style="display:inline">'
            '<input type="hidden" name="gg" value="1">'
            '<input type="hidden" name="how" value="reopen">'
            '<input type="hidden" name="values" value="'
            + _h.escape(json.dumps(vals), quote=True) + '">'
            '<input type="hidden" name="note" value="'
            + _h.escape(note, quote=True) + '">'
            f'<button{" class=quiet" if quiet else ""}>{label}</button></form>')


def windows_html(draft, out):
    """T9: the sweep read on two windows, the older week's choice tested on
    the newer, and how much of the window the price spent in the range.
    The table is the answer; the sentences say what it means."""
    w14, w7 = out['windows']['14d'], out['windows']['7d']
    head = (f"{draft.get('symbol')} {draft.get('side')} "
            f"{draft.get('lower')}–{draft.get('upper')} — grid counts compared "
            f"over 14 days and the last 7")
    if w14['best'] is None or w7['best'] is None:
        return (f'<h1>{head}</h1>' + refusal_box(
            'no step to name', 'every candidate gap sits inside the '
            'round-trip fee or under the venue\'s minimum for this range — '
            'widen the range or use fewer grids'))
    v7, v14 = out['visited']['7d'], out['visited']['14d']
    oos = out['oos']
    r14 = {r['rungs']: r for r in w14['rows']}
    r7 = {r['rungs']: r for r in w7['rows']}
    lo, hi = w14['plateau']
    rows = ''
    for n in sorted(set(r14) | set(r7)):
        a, b = r14.get(n), r7.get(n)
        if a and 'skipped' in a:
            rows += (f"<tr><td>{n}</td><td>{a['gap_pct']:.2f}%</td>"
                     f"<td class='dim' colspan='4'>{a['skipped']}</td></tr>")
            continue
        gap = (a or b)['gap_pct']
        mark = (' <b>&larr; 14d</b>' if n == w14['best'] else '') + \
               (' <b>&larr; 7d</b>' if n == w7['best'] else '')
        cls = ' class="pos"' if lo <= n <= hi else ''
        share = ('—' if not a or a.get('fee_share') is None
                 else f"{a['fee_share'] * 100:.0f}%")
        rows += (f"<tr{cls}><td>{n}{mark}</td><td>{gap:.2f}%</td>"
                 + (money(b['net']) if b and 'net' in b else
                    '<td class="dim">—</td>')
                 + (money(a['net']) if a and 'net' in a else
                    '<td class="dim">—</td>')
                 + f"<td>{share}</td>"
                 + (money(-a['max_drawdown'], cls=False) if a and 'net' in a
                    else '<td class="dim">—</td>')
                 + '<td>' + setup_button(
                     draft, _row_note(n, a, w14, oos), rungs=n,
                     label=f'set up with {n} grids &rarr;') + '</td></tr>')
    have = out.get('draft_rungs')
    if oos['holds'] is None:
        oos_s = ''
    else:
        verdict_s = ('the choice <b>holds up</b> out of sample.'
                     if oos['holds'] else
                     'the sweep is <b>fitting noise</b> here; hold any choice '
                     'loosely.')
        oos_s = (f"Chosen on the older week alone, <b>{oos['fit_rungs']} "
                 f"grids</b> netted {oos['fit_net_newer']:+,.2f} on the newer "
                 f"week against that week's own best of "
                 f"{oos['newer_best_net']:+,.2f} at {oos['newer_best']} — "
                 + verdict_s)
    visited = (f"The price closed inside your range on {v7:.0f}% of the last "
               f"7 days' candles and {v14:.0f}% of the 14 — "
               + ('a grid earns only where the price goes.'
                  if min(v7, v14) < 60 else
                  'the range was where the price was.'))
    return (f'<h1>{head}</h1>'
            f"<p>Over 14 days <b>{w14['best']} grids</b> made the most "
            f"(net {r14[w14['best']]['net']:+,.2f}; any of <b>{lo}–{hi}</b> "
            f"within 5%); over the last 7, <b>{w7['best']}</b> "
            f"(net {r7[w7['best']]['net']:+,.2f})"
            + (f"; the row has {have}" if have else '') + '. '
            'Nothing is applied here — type the number you choose into the '
            'form above.</p>'
            + (f'<p>{oos_s}</p>' if oos_s else '')
            + f'<p>{visited}</p>'
            + (f"<p class='dim'>every grid was sized equally for the sweep; "
               f"set aside: {', '.join(out['dropped'])}.</p>"
               if out.get('dropped') else '')
            + '<table><tr><th>grids</th><th>gap</th><th>net 7d</th>'
              '<th>net 14d</th><th>fees share</th><th>max drawdown</th>'
              '<th></th></tr>'
            + rows + '</table>'
            "<p class='dim'>score = grid profit − fees, the range exactly as "
            'you set it, the engine\'s own planner, fills on trade-through '
            'through 5-minute candles. Rows in the 14-day plateau are '
            'coloured. Two windows and an out-of-sample test are how a '
            'number earns trust; a sweep is still not a promise. A row\'s '
            'button opens the advanced form with that count and this '
            'page\'s verdict as its note; every gate still follows.</p>')


def _row_note(n, a, w14, oos):
    """U30: the words that travel with a chosen count."""
    lo, hi = w14['plateau']
    where = ('the 14-day best' if n == w14['best'] else
             'inside the 14-day plateau' if lo <= n <= hi else
             'outside the 14-day plateau')
    verdict_s = ('' if oos.get('holds') is None else
                 '; the older week\'s choice holds up out of sample'
                 if oos['holds'] else
                 '; the sweep was fitting noise — hold this loosely')
    net = f", net {a['net']:+,.2f} over 14 days" if a and 'net' in a else ''
    return (f'from a comparison of grid counts over 14 days: {n} grids, '
            f'{where}{net}{verdict_s}')


def sweep_html(draft, out):
    """T8 (D50): the whole table is the answer; the best is named, the
    plateau says how much the choice matters; nothing is applied."""
    head = (f"{draft.get('symbol')} {draft.get('side')} "
            f"{draft.get('lower')}–{draft.get('upper')} — grid counts compared "
            f"over {out['bars']} candles of {out.get('bar_minutes', 5)} min")
    if out['best'] is None:
        return (f'<h1>{head}</h1>' + refusal_box(
            'no step to name', 'every candidate gap sits inside the '
            'round-trip fee for this range — widen the range or use fewer '
            'grids'))
    lo, hi = out['plateau']
    best = next(r for r in out['rows'] if r['rungs'] == out['best'])
    rows = ''
    for r in out['rows']:
        if 'skipped' in r:
            rows += (f"<tr><td>{r['rungs']}</td><td>{r['gap_pct']:.2f}%</td>"
                     f"<td class='dim' colspan='4'>{r['skipped']}</td></tr>")
            continue
        share = ('—' if r['fee_share'] is None
                 else f"{r['fee_share'] * 100:.0f}%")
        mark = ' <b>&larr; best</b>' if r['rungs'] == out['best'] else ''
        cls = ' class="pos"' if lo <= r['rungs'] <= hi else ''
        rows += (f"<tr{cls}><td>{r['rungs']}{mark}</td>"
                 f"<td>{r['gap_pct']:.2f}%</td>{money(r['net'])}"
                 f"<td>{r['trips']}</td><td>{share}</td>"
                 f"{money(-r['max_drawdown'], cls=False)}</tr>")
    have = out.get('draft_rungs')
    return (f'<h1>{head}</h1>'
            f"<p><b>{out['best']} grids</b> (gap {best['gap_pct']:.2f}%) "
            f"made the most over this window, net {best['net']:+,.2f}. "
            f"Any of <b>{lo}–{hi}</b> lands within 5% of it"
            + (f"; the row has {have}" if have else '') + '. '
            'Nothing is applied here — type the number you choose into the '
            'form above.</p>'
            + (f"<p class='dim'>every grid was sized equally for the sweep; "
               f"set aside: {', '.join(out['dropped'])}.</p>"
               if out.get('dropped') else '')
            + '<table><tr><th>grids</th><th>gap</th><th>net</th><th>trips'
            '</th><th>fees share</th><th>max drawdown</th></tr>'
            + rows + '</table>'
            "<p class='dim'>score = grid profit − fees over this window, "
            'the range exactly as you set it, the engine\'s own planner, '
            'fills on trade-through through 5-minute candles. Rows in the '
            'plateau are coloured. Window shown, never annualised; a '
            'sweep is not a promise — same candles are never same fills.'
            '</p>')


COLS = ('<colgroup><col style="width:10%"><col style="width:5%">'
        '<col style="width:4%"><col style="width:7%"><col style="width:5%">'
        '<col style="width:6%">'                            # D63: funding
        '<col style="width:10%"><col style="width:7%"><col style="width:7%">'
        '<col style="width:6%"><col style="width:6%"><col style="width:8%">'
        '<col style="width:7%"><col style="width:8%"><col style="width:8%">'
        '<col style="width:6%"></colgroup>')


def ladder_box(idx, botid, terms, open_=False):
    """U52 (the 3Commas summary box, owner: "what am I actually risking
    with this row"): a DCA card folds a table of its ladder — each step's
    fill, size, total committed, average entry and the bounce take-profit
    then needs — and says, in one line, the drop the ladder covers. From
    the contract's terms; percentages, so true before a round and after."""
    rows = (terms or {}).get('ladder')
    if not rows:
        return ''
    def pct(v):
        return '—' if v is None else f'{v * 100:+.2f}%'
    def amount(v):
        return f'{v:,.0f}' if abs(v) >= 1000 else f'{v:,.6g}'
    last = rows[-1]
    body = ''.join(
        f'<tr><td>{"base" if r["step"] == 0 else r["step"]}</td>'
        f'<td>{pct(r["fill_pct"])}</td><td>{amount(r["notional"])}</td>'
        f'<td>{amount(r["committed"])}</td><td>{pct(r["avg_pct"])}</td>'
        f'<td>{pct(r["to_tp_pct"])}</td></tr>' for r in rows)
    return (f'<details{" open" if open_ else ""} data-k="{idx}:{botid}:ladder"><summary>the ladder: '
            f'covers a move of <b>{pct(last["fill_pct"])}</b>, then '
            f'{amount(last["committed"])} committed at an average of '
            f'{pct(last["avg_pct"])}</summary><table><tr><th>step</th>'
            '<th>fills at</th><th>size</th><th>committed</th><th>average</th>'
            f'<th>to take-profit</th></tr>{body}</table>'
            '<div class="dim">from the base price; size and committed in '
            f'{(terms or {}).get("quote") or "quote"}</div></details>')


def kind_line(terms):
    """U36 (owner: "a lay person may just see a dca bot and not understand
    the mathematics of leverage and martingale-style mechanics"): what kind
    of thing this bot is, in one line — the market, the leverage, and for a
    DCA whether its add-ons grow — with a hover on the one word that needs
    one. None when the contract does not say."""
    if not terms or not terms.get('market_type'):
        return None
    mt = terms['market_type']
    market = {'linear': 'futures, USDT/USDC-margined',
              'inverse': 'futures, coin-margined (inverse)',
              'spot': 'spot'}.get(mt, mt)
    if mt == 'spot' and terms.get('spot_borrow'):
        market = 'spot on margin (borrowed)'
    lev = terms.get('leverage') or 1.0
    lev_s = (f'{lev:g}x leverage' if lev != 1 else
             ('no leverage' if mt == 'spot' else '1x, no leverage'))
    if terms.get('trade'):                                          # L6 (D81)
        parts = [f"take profit +{terms['tp_pct'] * 100:g}%" if terms.get('tp_pct') else 'take profit in tranches']
        if terms.get('stop_pct'):
            parts.append(f"stop −{terms['stop_pct'] * 100:g}% at the mark")
        if terms.get('trail_pct'):
            parts.append(f"trailing {terms['trail_pct'] * 100:g}%")
        who = (f" · opened {terms['opened'][:16].replace('T', ' ')} by {terms.get('by', '?')}"
               if terms.get('opened') else '')
        return f'trade on {market} · {lev_s} · ' + ' · '.join(parts) + who
    if terms.get('strategy') == 'martingale':
        k, n = terms.get('multiplier') or 1.0, terms.get('add_ons')
        grows = (f'<span class="st" title="each add-on order is {k:g}× the '
                 'one before, so the average entry chases the price — and '
                 'the position grows fast on the way down; the loss limit '
                 'and the stop are what bound it">martingale-style</span>: '
                 f'each add-on {k:g}× the last' if k and k != 1 else
                 'equal add-ons')
        return (f'DCA on {market} · {lev_s} · {grows}'
                + (f', up to {n}' if n else ''))
    return f'grid on {market} · {lev_s}'


def _plain_name(botid, contract, b):
    """'BTCUSDT long grid' from the botid and the contract — the name a
    person says; the botid stays on the card for the confirm box."""
    side = (b or {}).get('side') or ('short' if botid.endswith('s')
                                     else 'long')
    kind = (b or {}).get('strategy') or (
        'grid' if botid in (contract.get('ranges') or {}) else 'martingale')
    market = {'inv': ' inverse', 'spo': ' spot'}.get(botid[:3], '')
    if ((contract.get('terms') or {}).get(botid) or {}).get('trade'):
        return f"{botid[3:-1]} {side} trade{market}"                # L6
    return (f"{botid[3:-1]} {side} "
            f"{'grid' if kind == 'grid' else 'DCA'}{market}")


def _side_tag(botid):
    """U15: long or short at a glance — a coloured tag, the same on the
    card and in the table."""
    side = 'short' if botid.endswith('s') else 'long'
    return f'<span class="side {side}">{side.upper()}</span> '


def state_tag(state, cls=''):
    """U35: the state word with its meaning on hover and its own colour."""
    import html as _h
    slug = state.lower().replace(' ', '-')
    return (f'<span class="{cls} st st-{slug}" title="'
            f'{_h.escape(STATE_WORDS.get(state, ""), quote=True)}">'
            f'{state}</span>')


def orders_line(ov):
    """U35: what rests and what waits, in words, from the engine's own
    snapshot (V15). None when the engine has not said."""
    if not ov:
        return None
    r, w = ov.get('resting') or {}, ov.get('waiting') or {}
    pct = (ov.get('within_pct') or 0.0) * 100

    def n(k, word):
        v = (k or {}).get(word + 's', 0)
        return f'{v} {word}{"" if v == 1 else "s"}'
    rest = ', '.join(x for x in (n(r, 'buy') if r.get('buys') else '',
                                 n(r, 'sell') if r.get('sells') else '') if x)
    wait = ', '.join(x for x in (n(w, 'buy') if w.get('buys') else '',
                                 n(w, 'sell') if w.get('sells') else '') if x)
    out = f'resting: {rest}' if rest else 'nothing resting'
    if wait:
        near = w.get('nearest')
        out += (f' · waiting: {wait} — placed when the price comes within '
                f'{pct:g}% of them'
                + (f' (the nearest at {near:,.6g})' if near else ''))
    return out


def tidy(page):
    """U46: links are buttons now — the " · " that separated them as text
    only crowds the row. Dropped wherever it stands between two of them."""
    import re
    return re.sub(r'(</a>|<b class="on">[^<]*</b>)\s*(?:·|&middot;)\s*'
                  r'(?=<a\b|<b class="on">)', r'\1 ', page)


def _num_cls(v):
    return 'pos' if v > 0 else 'neg' if v < 0 else 'dim'


def card(idx, botid, b, contract, belief, full=False):
    """One bot, one card: its state in a word, what it made, where the
    price sits in its range. Everything the table row said is still here;
    the numbers live on the position's own page (U56), where `full` lays
    them open below the exchange's view of the position."""
    if ((contract.get('terms') or {}).get(botid) or {}).get('strategy') == 'portfolio':
        return portfolio_card(idx, botid, contract, belief, full=full)       # D78/H6
    rng = (contract.get('ranges') or {}).get(botid)
    ceil = ((contract.get('watchdog') or {}).get('ceilings') or {}).get(botid)
    money_coin, margin_coin = units_of(botid, (contract.get('terms') or {}).get(botid))   # U53
    links = (('' if full else f"<a href='/position?fleet={idx}&bot={botid}'>numbers</a> · ")
             + f"<a href='/edit?fleet={idx}&bot={botid}'>edit</a> · "
             f"<a href='/setup?fleet={idx}&copy={botid}'>copy</a> · "
             f"<a href='/edit?fleet={idx}&bot={botid}&mode=remove'>remove"
             '</a>')
    if b is None:
        # no fills in the window — the engine's own belief fills in, and
        # says so (the snapshot is the bot's belief, not the venue)
        bl = belief.get(botid, {})
        pos = bl.get('position') or 0.0
        state = ('DEAD' if bl.get('alive') is False else
                 'HOLDING' if abs(pos) > 1e-12 else
                 'NOT STARTED' if botid not in belief else 'RESTING')  # U34
        head = ('<span class="big dim">waits for the fleet\'s restart</span>'
                if botid not in belief else
                '<span class="big dim">no fills</span>'
                + (f' <span class="dim">— {orders_line(bl.get("orders"))}'
                   '</span>' if bl.get('orders') else ''))          # U35
        kept = since_first_line(contract, botid)                  # R18
        if kept:
            head += f'<div class="pnl">{kept}</div>'
        held = (f'holding {pos:.10g} (belief)' if abs(pos) > 1e-12
                else 'holding nothing')
        mark = (contract.get('marks') or {}).get(botid)             # U57: a quiet bot has a price too
        more, note = '', ''
        limit = (f'{abs(pos) / ceil * 100:.0f}% of {ceil:,.4g}' if ceil
                 else 'no limit')
    else:
        pos, mark = b['position'], b['mark']
        state = ('DEAD' if (belief.get(botid) or {}).get('alive') is False
                 else 'HOLDING' if abs(pos) > 1e-12 else 'FLAT')
        total = card_total(b)                                   # D63
        note = ' *' if b['truncated'] else ''
        coin = ''
        if b.get('settle'):            # R11: an inverse bot says both, as
            st = b['settle']           # the exchange does
            coin_total = (st['realized'] - st['fees']
                          + (st.get('funding') or 0.0)
                          + (st['unreal'] or 0.0))
            coin = (f' <span class="{_num_cls(coin_total)}">'
                    f"{coin_total:+.6f} {st['coin']}</span>")
        if b.get('counted_from') == 'flat':                   # R14
            days = (contract['generated_ms'] - b['counted_since_ms']) / 8.64e7
            span = (f'since it was last flat, {days:.1f} d'
                    if days >= 1 else f'since it was last flat, {days * 24:.0f} h')
        elif b.get('counted_from') == 'cap':
            # the cap is how far back it LOOKED; the figure is the fills it
            # found — say where they start when that is later (2026-10-06:
            # a "last 30 d" card counted 4.4 days)
            first = b.get('first_ms')
            days = ((contract['generated_ms'] - first) / 8.64e7
                    if first else None)
            span = ('never flat in 30 d; its fills start '
                    + (f'{days:.1f} d ago' if days is not None and days < 29
                       else '30 d ago')
                    + (' *' if b['truncated'] else ''))
        else:
            span = f"last {contract['window_hours']:g}h"
        # U45: the money in its own box — the total, then what it is made of
        net = b['realized'] - b['fees']
        head = (f'<div class="pnl {_num_cls(total)}">'
                f'<span class="big {_num_cls(total)}">{total:+,.2f}</span> '
                f'{money_coin}{coin} <span class="dim">after fees, {span}</span>'
                f'<div class="parts">'
                f'{pnl_parts(net, b["unreal_at_mark"], b.get("funding"))}'
                f'</div>{run_rate(b, contract, ((contract.get("terms") or {}).get(botid) or {}).get("capital"), bool(((contract.get("terms") or {}).get(botid) or {}).get("trade")))}'
                f'{since_first_line(contract, botid)}</div>')
        held = holding_html(pos, b['avg_cost'], mark, botid,
                            bool(b.get('inverse')), quote=money_coin)   # U44/U53
        floor = (contract.get('fee_floors') or {}).get(botid)
        unreal = b['unreal_at_mark']
        limit = (f'{abs(pos) / ceil * 100:.0f}% of {ceil:,.4g}' if ceil
                 else 'no limit')
        more = (
            '<div class="numbers"><h3>the numbers</h3><table>'
            f"<tr><td>fills</td><td>{b['fills']}</td></tr>"
            + (f"<tr><td>per trip after fees ({b['gap_trips'] or b['trips']}"
               f" trips; {b['per_trip']:+,.2f} before)</td>"
               f"{money(b.get('per_trip_net'))}</tr>"
               if b.get('per_trip') is not None else '')            # R12
            + f"<tr><td>realized</td>{money(b['realized'])}</tr>"
            f"<tr><td>fees</td>{money(b['fees'], cls=False)}</tr>"
            f"<tr><td>funding</td>{money(b.get('funding'))}</tr>"   # D63
            f'<tr><td>unreal</td>{money(unreal)}</tr>'
            f"<tr><td>bought</td><td>{b['bought']:,.4g}</td></tr>"
            f"<tr><td>sold</td><td>{b['sold']:,.4g}</td></tr>"
            + (f"<tr><td colspan='2' class='wide'><b>orders</b> — "
               f"{orders_line((belief.get(botid) or {}).get('orders'))}"
               '</td></tr>'
               if (belief.get(botid) or {}).get('orders') else '')  # U35/U37
            + f'<tr><td>stop-now est.</td><td>{settle(b, floor)}</td></tr>'
            f'<tr><td>watcher</td><td>{limit}</td></tr>'
            + (f"<tr><td>in the coin itself</td><td>realized "
               f"{b['settle']['realized']:+.6f}, fees "
               f"{b['settle']['fees']:.6f}, funding "
               + ('—' if b['settle'].get('funding') is None else
                  f"{b['settle']['funding']:+.6f}") + ', unreal '
               + ('—' if b['settle']['unreal'] is None else
                  f"{b['settle']['unreal']:+.6f}") + '</td></tr>'
               if b.get('settle') else '')
            + '</table></div>')
    more += ladder_box(idx, botid, (contract.get('terms') or {}).get(botid), open_=True)   # U52
    if not full:
        more = ''                                 # U56: the numbers are the page's
    capped = (belief.get(botid) or {}).get('capped')
    if capped:
        # D56/D70: the account's cap holds this bot back — a flat one
        # opens nothing, a holding one adds nothing
        held += ('</div><div class="neg">'
                 + (f'capped: {capped} — adds nothing, exits run' if pos else
                    f'waiting: {capped} — opens nothing until it clears'))
    mv = (belief.get(botid) or {}).get('margin')
    if mv and mv.get('liq') and mark:
        # V17: where the exchange says this position is liquidated, and how
        # far the mark is from it (2026-10-06: HYPE, isolated, went with no
        # line on its card saying how close it stood)
        away = abs(mark - mv['liq']) / mark * 100
        held += (f'</div><div class="{"neg" if away < 5 else "dim"}">'
                 f"liquidates at {mv['liq']:,.6g} · {away:.1f}% away")
    mkt = (contract.get('market') or {}).get(botid)
    if mkt and mkt.get('line'):
        # D67: the market's regime beside the bot that trades it; red when
        # the book is thin for this fleet
        age = mkt.get('age_s') or 0
        held += (f'</div><div class="{"neg" if mkt.get("thin") else "dim"}">'
                 f"market {mkt['line']}"
                 + (' · THIN for this fleet' if mkt.get('thin') else '')
                 + (f' · read {age // 3600} h ago' if age >= 7200 else ''))
    if mv and (mv.get('im') is not None or mv.get('mm') is not None):
        # V14: the exchange's own margin on this position, from the
        # engine's last snapshot
        parts = []
        # U53: two decimals for a dollar coin; a margin held in the coin
        # itself is small (MM 0.0012 BTC read as 0.00) — six figures
        fmt = ',.2f' if margin_coin in ('USDT', 'USDC', 'USD') else ',.6g'
        if mv.get('im') is not None:
            parts.append(f"IM {mv['im']:{fmt}} {margin_coin}")
        if mv.get('mm') is not None:
            parts.append(f"MM {mv['mm']:{fmt}} {margin_coin}")
        if mv.get('leverage'):
            parts.append(f"at {mv['leverage']:g}x on the exchange")
        held += '</div><div class="dim">margin ' + ' · '.join(parts)
    terms = (contract.get('terms') or {}).get(botid)
    kind = kind_line(terms)
    if kind:
        held = f'{kind}</div><div class="dim">' + held       # U36, first,
                                     # its own line ("leverageholding", U46)
    if terms and terms.get('capital'):
        lev = terms.get('leverage') or 1.0
        def amount(v):                 # 46,600 and 3,495,000, never 3.5e+06
            return f'{v:,.0f}' if abs(v) >= 1000 else f'{v:,.6g}'
        held += (f'</div><div class="dim">investment {amount(terms["capital"])} {money_coin}'
                 + (f' at <b>{lev:g}x</b>' if lev != 1 else '')
                 + (f' · up to {amount(terms["notional"])} {money_coin} in the market'
                    if terms.get('notional') else ''))
    rec = (terms or {}).get('spot')
    if rec:
        # D76: the shared wallet against this bot's book — what is not
        # this bot's, how much the inverse books on the coin account for,
        # and what is left that nothing explains
        coin = terms.get('coin') or coin_of(botid)
        def c(v):
            return '—' if v is None else f'{v:,.6g}'
        line = (f"wallet {c(rec['wallet'])} {coin} · this bot's book {c(rec['book'])}"
                f" · {c(rec['outside'])} not this bot's")
        if rec.get('explained') is not None:
            line += (f" — the inverse books' P&amp;L and fees since "
                     f"{terms.get('holding_since', '')[:10]} account for "
                     f"{c(rec['explained'])}; {c(rec['unexplained'])} unexplained"
                     ' (funding not counted)')
        bad = rec.get('unexplained') is not None and abs(rec['unexplained']) > abs(rec['outside']) * 0.5 + 1e-9
        held += f'</div><div class="{"neg" if bad else "dim"}">{line}'
    where = ''
    slid = ''
    if rng and (belief.get(botid) or {}).get('offset') and rng.get('rungs', 0) > 1:
        # U57: the window as it has slid (G17): the home lattice's gap times
        # the offset, so the card judges the price against the window the
        # bot trades, not the home it started from
        gap = (rng['upper'] - rng['lower']) / (rng['rungs'] - 1)
        off = belief[botid]['offset']
        rng = dict(rng, lower=rng['lower'] + off * gap, upper=rng['upper'] + off * gap)
        slid = f' · window slid {off:+d} rungs from home'
    if rng and mark:
        lo, hi = rng['lower'], rng['upper']
        if lo <= mark <= hi:
            place = (f'{(mark - lo) / mark * 100:.1f}% above the bottom, '
                     f'{(hi - mark) / mark * 100:.1f}% below the top')
        else:
            place = ('<span class="neg">price is OUTSIDE the range ('
                     + ('above' if mark > hi else 'below') + ')</span>')
        where = (f'<div class="rng"><span class="dim">{lo:,.6g}</span>'
                 f'{strip(rng, mark, "100%")}'
                 f'<span class="dim">{hi:,.6g}</span></div>'
                 f'<div class="dim">price {mark:,.6g} — {place}{slid}</div>')
    elif rng:
        where = (f"<div class=\"dim\">range {rng['lower']:,.6g} to "
                 f"{rng['upper']:,.6g}</div>")
    loss = (belief.get(botid) or {}).get('loss')
    if loss and loss.get('limit'):
        # X14: the engine's own count, from its last snapshot
        down = max(0.0, -loss['result'])
        used = down / loss['limit']
        held += (f'</div><div class="{"neg" if used >= 0.75 else "dim"}">'
                 f"loss limit: down {down:,.2f} of {loss['limit']:,.6g} "
                 f'{money_coin} ({used:.0%} used)')
    cls = 'neg' if state == 'DEAD' else 'dim'
    side = 'short' if botid.endswith('s') else 'long'
    flat = (abs(pos) <= 1e-12 if b is not None else
            (belief.get(botid) or {}).get('position') == 0)   # unknown ≠ flat
    is_trade = bool(((contract.get('terms') or {}).get(botid) or {}).get('trade'))
    if is_trade and state != 'DEAD' and not flat and not botid.startswith('spo'):
        # L6: a live trade can be ended early from its card — the close page
        # asks for its name and sends one reduce-only market order
        links += (f" · <a href='/close?fleet={idx}&bot={botid}'>close trade</a>")
    elif is_trade and state == 'DEAD':
        links += " · <a href='/trade'>clear</a>"
    if state == 'DEAD' and not botid.startswith('spo') and not flat:
        # X15: what a stopped bot left open can be closed from here — and
        # only then: a bot known to have stood down flat has nothing to
        # close (HL AVAX after its last round, 2026-10-06: the door led to
        # "nothing"); a holding the panel cannot see is still offered —
        # the close page asks the exchange itself
        links += (f" · <a href='/close?fleet={idx}&bot={botid}'>close "
                  'position</a>')
    # U58: the lines under the bar fold behind one word, so a card can be
    # small; the click is remembered per card, and the side panel folds or
    # opens every card at once (the owner, 2026-10-09: "toggle all so it
    # can be bigger and smaller"). The numbers stay the page's (U56).
    return (f'<div class="card {side}"><div>'
            f'<span class="side {side}">{side.upper()}</span> <b>'
            f'{_plain_name(botid, contract, b)}</b>{note} '
            f'{state_tag(state, cls)}</div>'
            f'<div>{head}</div>{where}{fold(idx, botid, f'<div class="dim">{held}</div>')}{more}'
            f'<div class="dim foot"><span>{botid}</span><span>{links}</span></div></div>')


def fold(idx, botid, inner, word='details'):
    """U58: a card's lower half behind a summary word — open by default,
    remembered per card by the page's script, folded or opened for every
    card by the side panel's switch. An export (no script) shows it open."""
    return (f'<details class="fold" data-k="{idx}:{botid}:fold" open>'
            f'<summary>{word}</summary>{inner}</details>')


VIEWS = (('all', 'as listed'), ('side', 'longs / shorts'),
         ('pairs', 'pairs'), ('strategy', 'by strategy'), ('market', 'by coin'))
STRATEGY_WORDS = {'grid': 'grids', 'martingale': 'DCA', 'pair': 'pairs — rebalancing',
                  'portfolio': 'portfolios — hedged, rebalanced'}
PRODUCT_WORDS = {'spo': 'spot', 'lin': 'perp', 'inv': 'inverse'}


def grouped(contract, view='all'):
    """U12: the venue's bots arranged for reading — [(heading, [(botid,
    b)])]. 'all' is the fleet file's own order under no heading; 'side'
    is the longs, then the shorts; 'pairs' puts a market's long beside its
    short (a pair is one market held both ways), then the rest. An
    arrangement only: every bot appears exactly once in every view."""
    items = list(contract['bots'].items())
    if view == 'side':
        groups = [('longs', [x for x in items if not x[0].endswith('s')]),
                  ('shorts', [x for x in items if x[0].endswith('s')])]
    elif view == 'pairs':
        ids = {botid for botid, _ in items}
        both = {botid[:-1] for botid in ids
                if botid[:-1] + 'l' in ids and botid[:-1] + 's' in ids}
        first = {}
        for n, (botid, _) in enumerate(items):
            first.setdefault(botid[:-1], n)
        paired = sorted((x for x in items if x[0][:-1] in both),
                        key=lambda x: (first[x[0][:-1]], x[0][-1]))
        groups = [('pairs — one market, long and short', paired),
                  ('on their own', [x for x in items
                                    if x[0][:-1] not in both])]
    elif view == 'strategy':
        # U54 (owner: "separate every strategy type on the dash"): one
        # heading per kind, in the order the kinds first appear
        terms = contract.get('terms') or {}
        def kind(botid, b):
            k = (b or {}).get('strategy') or (terms.get(botid) or {}).get('strategy')
            return k or ('grid' if botid in (contract.get('ranges') or {}) else 'martingale')
        order, by = [], {}
        for botid, b in items:
            k = kind(botid, b)
            if k not in by:
                order.append(k)
            by.setdefault(k, []).append((botid, b))
        groups = [(STRATEGY_WORDS.get(k, k), by[k]) for k in order]
    elif view == 'market':
        # U54: one coin across its products — spot, perp, inverse, each
        # side — so what shares a wallet or an index sits together
        order, by = [], {}
        pterms = contract.get('terms') or {}
        for botid, b in items:
            c = ('portfolios' if (pterms.get(botid) or {}).get('strategy') == 'portfolio'
                 else coin_of(botid))
            if c not in order:
                order.append(c)
            by.setdefault(c, []).append((botid, b))
        groups = [(c if c == 'portfolios' else
                   f'{c} — ' + ', '.join(sorted({PRODUCT_WORDS.get(x[0][:3], x[0][:3]) for x in by[c]})), by[c])
                  for c in order]
    else:
        return [('', items)]
    return [(title, rows) for title, rows in groups if rows]


def pnl_parts(net, unreal, funding=0.0):
    """U45: what a total is made of — banked after fees, funding paid or
    received (D63, its own line; — when it could not be read), and still
    open."""
    def part(v):
        return ('—' if v is None else
                f'<b class="{_num_cls(v)}">{v:+,.2f}</b>')
    return (f'realised after fees {part(net)} · funding {part(funding)} · '
            f'open {part(unreal)}')


def _day(ms):
    return time.strftime('%Y-%m-%d', time.gmtime(ms / 1000))


def since_first_total(sf):
    """R18: a kept book's whole result, or None when it cannot be whole
    (the ledger behind the window, or an unknown mark on an open book)."""
    if (not sf or sf.get('behind') is not None or not sf.get('whole', True)
            or sf.get('realized') is None):
        return None
    if sf['unreal_at_mark'] is None and abs(sf.get('position') or 0) > 1e-12:
        return None
    return card_total(sf)                                       # D63


def since_first_line(contract, botid):
    """R18: the line under a card's money — since the bot first traded,
    from the kept ledger. Nothing when no ledger is kept; a ledger behind
    the readout's window says so and shows no number."""
    if 'since_first' not in contract:
        return ''
    sf = contract['since_first'].get(botid)
    if not sf or not sf.get('fills'):
        return '<div class="parts">kept history: nothing kept yet</div>'
    if sf.get('behind') is not None:
        when = (f"kept to {_day(sf['behind'])}" if sf['behind']
                else 'not collected yet')
        return ('<div class="parts">kept history: the ledger is behind '
                f'— {when}</div>')
    if not sf.get('whole', True):
        return ('<div class="parts">kept history: no clean start yet — it '
                'held through the whole record, so nothing is summed</div>')
    total = since_first_total(sf)
    rounds = (f"{sf['rounds']} rounds" if sf.get('strategy') == 'martingale'
              else f"{sf['trips']} trips")
    star = ' *' if sf.get('truncated') else ''
    shown = ('—' if total is None else
             f'<b class="{_num_cls(total)}">{total:+,.2f}</b>')
    op = sf.get('opened')
    since = (f'fresh from {_day(op["time_ms"])} (opened holding '
             f'{op["qty"]:,.10g} at {op["price"]:,.6g})' if op
             else f'since {_day(sf["first_ms"])}')
    return (f'<div class="parts">kept history, {since}'
            f' {shown}{star} · {rounds}</div>')


def exchange_leverage(contract):
    """R19: the account's leverage, the owner's measure, in the exchange box."""
    from gridgremlin.report import leverage_lines
    return ''.join(f'<div class="parts lev-now">{now}</div>'
                   f'<div class="parts lev-filled">{filled}</div>'
                   for now, filled in leverage_lines(contract).values())


def exchange_since_first(contract):
    """R18: the exchange box's kept line — every bot's whole result summed;
    a bot whose figure cannot be whole is named as left out, never
    silently dropped from the sum."""
    if 'since_first' not in contract:
        return ''
    whole, out = 0.0, 0
    for sf in contract['since_first'].values():
        if not sf or not sf.get('fills'):
            continue
        t = since_first_total(sf)
        if t is None:
            out += 1
        else:
            whole += t
    left = f' <span class="dim">({out} bot(s) left out: not whole)</span>' \
        if out else ''
    return ('<div class="parts">kept history '
            f'<b class="{_num_cls(whole)}">{whole:+,.2f}</b>{left}</div>')


TIER_NAMES = {('bybit', 'demo'): 'Demo Trading', ('bybit', 'testnet'): 'Testnet',
              ('bybit', 'mainnet'): 'Mainnet',
              ('hyperliquid', 'testnet'): 'Testnet',
              ('hyperliquid', 'mainnet'): 'Mainnet'}


def contract_tiers(contract):
    """D65: each venue's network — first as the running fleet connected to
    it (its snapshot), else as the readout's own client did."""
    belief = ((contract.get('watchdog') or {}).get('belief') or {})
    tiers = dict(belief.get('tiers') or {})
    for venue, fig in (contract.get('account') or {}).items():
        if venue not in tiers and fig and fig.get('tier'):
            tiers[venue] = fig['tier']
    return tiers


def tier_badge(contract):
    """D65: the exchange's own name for the network, on every fleet's
    heading; Mainnet in red. A link to what the networks mean."""
    out = []
    for venue, env in sorted(contract_tiers(contract).items()):
        name = TIER_NAMES.get((venue, env), env)
        cls = 'tier-main' if env == 'mainnet' else 'tier-test'
        out.append(f'<a class="tier {cls}" href="/trading" title="what this '
                   f'means">{name}</a>')
    return ' '.join(out)


def portfolio_total(contract):
    """H6: what the fleet's portfolio rows have made since their anchors,
    from their own snapshots — counted into the exchange's total like any
    card (D63). A row the engine has not valued counts nothing."""
    belief = ((contract.get('watchdog') or {}).get('belief') or {}).get('bots', {})
    return sum((bl.get('portfolio') or {}).get('total') or 0.0
               for bl in belief.values() if bl.get('alive') is not False)


def portfolio_card(idx, botid, contract, belief, full=False):
    """H6: the portfolio's card — the stack's value and coins, one line per
    asset (weight target → actual, hedge ratio target → actual, coins
    hedged, the regime word when the tilt is on), and three money lines
    that never mix: carry, tilt, basis & shape."""
    import html as _h
    terms = (contract.get('terms') or {}).get(botid) or {}
    bl = belief.get(botid) or {}
    v = bl.get('portfolio') or {}
    q = terms.get('quote') or 'USDT'
    links = (('' if full else f"<a href='/position?fleet={idx}&bot={botid}'>numbers</a> ")
             + f"<a href='/edit?fleet={idx}&bot={botid}'>edit</a> "
             f"<a href='/edit?fleet={idx}&bot={botid}&mode=remove'>remove</a>")
    state = ('DEAD' if bl.get('alive') is False else 'NOT STARTED' if botid not in belief
             else 'HOLDING' if (v.get('stack_value') or 0) > 0 else 'RESTING')
    name = f"{botid[3:]} portfolio"
    kind = (f"{len(terms.get('assets') or [])} assets · hedged on "
            + ', '.join(sorted({h['product'] for h in (terms.get('hedges') or {}).values()}) or ['nothing'])
            + f" · rebalanced every {(terms.get('rebalance') or {}).get('every_hours', 24):g} h"
            + (f" · tilt {terms['regime']['tilt']:.0%} with the regime" if terms.get('regime') else ' · neutral'))
    facts = ''
    if not v:
        head = ('<span class="big dim">waits for the fleet\'s restart</span>' if botid not in belief
                else '<span class="big dim">not yet valued</span>')
        body = ''
    else:
        total = v.get('total') or 0.0
        carry, tilt, basis = v.get('carry', {}).get('total') or 0.0, v.get('tilt') or 0.0, v.get('basis') or 0.0
        head = (f'<div class="pnl {_num_cls(total)}"><span class="big {_num_cls(total)}">{total:+,.2f}</span> {q} '
                f'<span class="dim">since its anchor, after fees</span><div class="parts">'
                f'carry <b class="{_num_cls(carry)}">{carry:+,.2f}</b> · '
                f'tilt <b class="{_num_cls(tilt)}">{tilt:+,.2f}</b> · '
                f'basis &amp; shape <b class="{_num_cls(basis)}">{basis:+,.2f}</b>'
                + (f' · interest <b class="neg">−{v["interest"]:,.2f}</b>' if v.get('interest') else '')
                + '</div></div>')
        rows = ''
        for a in v.get('assets') or []:
            w, act = a.get('weight') or 0.0, a.get('actual') or 0.0
            hedged, coins = a.get('hedged') or 0.0, (v.get('stack') or {}).get(a['coin'], {}).get('coins') or 0.0
            ratio_act = (hedged / coins) if coins else 0.0
            note = ('unwound (basis)' if a.get('unwound') else
                    f"regime {a['regime']}" if a.get('regime') else '')
            rows += (f"<tr><td>{a['coin']}</td>"
                     + (f"<td>{w:.0%} → {act:.0%}</td>" if w > 0 else f"<td>short {abs(w):.0%}</td>")
                     + (f"<td>{a.get('ratio') or 0:g} → {ratio_act:.2f}</td><td>{hedged:,.6g}</td>"
                        if w > 0 else f"<td>—</td><td>{a.get('short') or 0.0:,.6g}</td>")
                     + f"<td>{coins:,.6g}</td><td class='dim'>{_h.escape(note)}</td></tr>")
        nxt = v.get('next_tick_ms')
        due = ''
        if nxt:
            left = (nxt - contract['generated_ms']) / 3.6e6
            due = f"next tick in {left:.1f} h" if left > 0 else 'tick due'
        facts = (f"<div class=\"dim\">stack <b>{v.get('stack_value') or 0:,.2f}</b> {q}"
                f" · cash {v.get('cash') or 0:,.2f}"
                + (f" · parked {v['parked']:,.2f}" if v.get('parked') else '')
                + (f" · borrowed <b>{v['borrowed']:,.2f}</b> ({v['leverage']:.2f}× the equity"
                   + (f", {v['borrow_apr']:.2%}/yr" if v.get('borrow_apr') is not None else '')
                   + (f", interest paid {v['interest']:,.2f}" if v.get('interest') else '') + ')'
                   if v.get('borrowed') and v.get('leverage') else '')
                + (f" · shorts cut {v['delevered']}×" if v.get('delevered') else '')
                + (f" · {due}" if due else '') + '</div>')
        body = (f'<table><tr><th>asset</th><th>weight</th><th>hedge ratio</th>'
                f'<th>coins hedged</th><th>coins held</th><th></th></tr>{rows}</table>'
                + (('<div class="numbers"><h3>the numbers</h3><table>'
                f"<tr><td>value</td>{money(v.get('value'), cls=False)}</tr>"
                f"<tr><td>anchor</td>{money(v.get('anchor'), cls=False)}</tr>"
                f"<tr><td>shorts, open</td>{money(v.get('unreal'))}</tr>"
                f"<tr><td>shorts, realised after fees</td>{money(v.get('realised'))}</tr>"
                f"<tr><td>funding, trailing window</td>{money((v.get('carry') or {}).get('trailing'))}</tr>"
                + (f"<tr><td>loss limit</td><td>{bl['loss']['result']:,.2f} of {bl['loss']['limit']:,.2f}</td></tr>"
                   if bl.get('loss') else '')
                + '</table></div>') if full else ''))
    cls = 'neg' if state == 'DEAD' else 'dim'
    # H6: the portfolio's card spans the cards' row — six columns of assets
    # and three money lines ran past a 21em card's border (the owner, 2026-10-08)
    # U55: three cards wide, not the page; the money and the facts side by
    # side, the assets below, the footer aligned with every other card's
    return (f'<div class="card pfo"><div><span class="side pfo">PORTFOLIO</span> <b>{name}</b> '
            f'{state_tag(state, cls)}</div><div class="dim">{kind}</div>'
            f'<div class="two"><div>{head}</div><div>{facts}</div></div>'
            + (fold(idx, botid, body, word='assets') if body else '')          # U58
            + f'<div class="dim foot"><span>{botid}</span><span>{links}</span></div></div>')


def exchange_table(botid, b, belief, terms):
    """U56 (the owner: "reads the data directly shown from the position
    when viewed in the Bybit dashboard"): the position as the exchange's
    own panel lays it out — symbol, side, size, value, entry, mark,
    liquidation, margin, leverage, open and closed P&L — from the readout's
    book and the engine's snapshot of the venue's margin (V14/V17)."""
    bl = belief.get(botid) or {}
    mv = bl.get('margin') or {}
    money_coin, margin_coin = units_of(botid, terms)
    pos = (b or {}).get('position') if b else bl.get('position')
    mark = (b or {}).get('mark')
    side = 'short' if botid.endswith('s') else 'long'
    symbol = (terms or {}).get('symbol') or botid[3:-1]

    def n(v, f=',.6g'):
        return '—' if v is None else f'{v:{f}}'
    inverse = bool((b or {}).get('inverse'))
    qty = None if pos is None else abs(pos)
    value = None if qty is None or not mark else (qty if inverse else qty * mark)
    fmt = ',.2f' if margin_coin in ('USDT', 'USDC', 'USD') else ',.6g'
    rows = [('symbol', symbol), ('side', side.upper()),
            ('size', f"{n(qty)} {'USD' if inverse else coin_of(botid)}"),
            ('value', f'{n(value, ",.2f")} {money_coin}'),
            ('entry price', n((b or {}).get('avg_cost') or None)),
            ('mark price', n(mark)),
            ('liq. price', n(mv.get('liq'))),
            ('initial margin', f"{n(mv.get('im'), fmt)} {margin_coin}" if mv.get('im') is not None else '—'),
            ('maint. margin', f"{n(mv.get('mm'), fmt)} {margin_coin}" if mv.get('mm') is not None else '—'),
            ('leverage', f"{mv['leverage']:g}×" if mv.get('leverage') else '—'),
            ('unrealised P&amp;L', f"{n((b or {}).get('unreal_at_mark'), '+,.2f')} {money_coin}"),
            ('realised, after fees', f"{n(((b or {}).get('realized') or 0) - ((b or {}).get('fees') or 0), '+,.2f')} {money_coin}"
                                      if b else '—'),
            ('funding', f"{n((b or {}).get('funding'), '+,.2f')} {money_coin}" if b else '—')]
    return ('<div class="scroll"><table class="xch"><tr>' + ''.join(f'<th>{k}</th>' for k, _ in rows) + '</tr><tr>'
            + ''.join(f'<td>{v}</td>' for _, v in rows) + '</tr></table></div>')


def position_page(idx, label, botid, contract, belief, prices=None, fills=()):
    """U56: one position, one page — the exchange's view first, then the
    price with its levels and fills (U65), then the card with every number
    laid open."""
    terms = (contract.get('terms') or {}).get(botid)
    b = (contract.get('bots') or {}).get(botid)
    xch = ('' if (terms or {}).get('strategy') == 'portfolio'
           else f'<h3>as the exchange shows it</h3>{exchange_table(botid, b, belief, terms)}')
    if (terms or {}).get('strategy') != 'portfolio':
        rng = (contract.get('ranges') or {}).get(botid)
        off = (belief.get(botid) or {}).get('offset')
        if rng and off and rng.get('rungs', 0) > 1:
            gap = (rng['upper'] - rng['lower']) / (rng['rungs'] - 1)
            rng = dict(rng, lower=rng['lower'] + off * gap, upper=rng['upper'] + off * gap)
        liq = ((belief.get(botid) or {}).get('margin') or {}).get('liq')
        xch += price_boxes(prices, rng, liq, fills)
    return (f'<h1>{label} · {_plain_name(botid, contract, b) if (terms or {}).get("strategy") != "portfolio" else botid[3:] + " portfolio"}</h1>'
            f'{xch}<div class="cards one">{card(idx, botid, b, contract, belief, full=True)}</div>'
            '<p><a href="/">&larr; fleet</a></p>')


def hero_strip(labelled):
    """U50 (the owner: the exchange boxes "get lost while scrolling"): a
    strip pinned to the top of the page, one row per fleet — its name and
    network, the exchange's total after fees, bots and how many are dead,
    the account's leverage now — read from the same contract as the box
    below, so the two can never disagree; the name jumps to the box."""
    from gridgremlin.report import account_leverage
    lines = []
    for idx, (label, c) in enumerate(labelled):
        live = [b for b in c['bots'].values() if b is not None]
        total = sum(card_total(b) for b in live) + portfolio_total(c)       # H6
        belief = ((c.get('watchdog') or {}).get('belief') or {}).get('bots', {})
        dead = sum(1 for bl in belief.values() if bl.get('alive') is False)
        levs = [a['now'] for a in account_leverage(c).values()]
        lev = ('leverage —' if not levs or any(v is None for v in levs) else
               'leverage ' + ' · '.join(f'{v:.2f}x' for v in levs))
        # six cells per fleet in one grid, so every column lines up whatever
        # the words' lengths (the owner: "so it looks squared")
        spark = equity_svg(((c.get('equity') or {}).get('24h')), 120, 18)       # U63
        lines.append(
            f'<div class="fleet"><a href="#fleet{idx}">{label}</a>{tier_badge(c)}'
            f'<span class="big num {_num_cls(total)}">{total:+,.2f} '
            f'<span class="dim">{venue_money(c)}</span></span>'
            f'<span class="dim num">{len(c["bots"])} bots</span>'
            + (f'<b class="neg num">{dead} dead</b>' if dead else '<span></span>')
            + f'<span class="dim">{lev}</span>'
            + (f'<span class="spark" title="equity, 24 h">{spark}</span>' if spark else '<span></span>')
            + '</div>')
    return '<div class="hero">' + ''.join(lines) + '</div>'


def venue_money(contract):
    """U53: what an exchange's total is counted in — its bots' money
    coins, joined when they differ (USDT/USDC at par is the venue's own
    convention on a unified account)."""
    terms = (contract.get('terms') or {}).values()
    coins = sorted({t['quote'] for t in terms if t and t.get('quote')})
    if not coins:
        coins = sorted({units_of(b, None)[0] for b in contract.get('bots') or {}})
    return '/'.join(coins) if coins else 'quote'


def cards_section(idx, label, contract, view='all', scripted=True):
    age = max(0, int(time.time() - contract['generated_ms'] / 1000))
    belief = ((contract.get('watchdog') or {}).get('belief')
              or {}).get('bots', {})
    live = [b for b in contract['bots'].values() if b is not None]
    net = sum(b['realized'] - b['fees'] for b in live)
    funded = [b.get('funding') for b in live]                     # D63
    funding = (None if any(f is None for f in funded)
               else sum(funded))
    opened = [b['unreal_at_mark'] for b in live
              if b['unreal_at_mark'] is not None]
    total = sum(card_total(b) for b in live) + portfolio_total(contract)    # H6
    cards = '</div><div class="cards">'.join(
        (f'<div class="grp">{title}</div>' if title else '')
        + ''.join(card(idx, botid, b, contract, belief)
                  for botid, b in rows)
        for title, rows in grouped(contract, view))
    # U45: the exchange's money in a box of its own, under its name
    # U59: one link beside the count folds or opens this account's cards
    # alone; its word says which it will do next
    return (f"<h1 id=\"fleet{idx}\">{label} {tier_badge(contract)} — {len(contract['bots'])} bots "
            + (f'<a href="javascript:ggFoldIn({idx})" data-foldin="{idx}" class="tier">fold cards</a> '
               if scripted else '')               # an export has no script to run it
            +             f'{sweep_note(contract)} <span class="dim">(read {age}s ago; '
            f'refreshes every {REFRESH_S}s)</span></h1>'
            f'<div class="pnl {_num_cls(total)}"><span class="dim">this '
            'exchange</span> <span class="big '
            f'{_num_cls(total)}">{total:+,.2f}</span> {venue_money(contract)} '
            '<span class="dim">after fees, each bot counted as its card says</span>'
            f'<div class="parts">'
            f'{pnl_parts(net, sum(opened) if opened else None, funding)}'
            f'</div>{exchange_since_first(contract)}{exchange_leverage(contract)}</div>'
            f'{equity_boxes(contract)}'                                          # U63
            f'{agent_box(contract)}'                                             # J5
            # U59: the account folds to its heading and its box; the side
            # panel folds or opens every account at once
            f'<details class="acct" data-k="acct:{idx}" open><summary>'
            f"{len(contract['bots'])} bots</summary>"
            f'<div class="cards">{cards}</div></details>')


def section(idx, label, contract, view='all'):
    age = max(0, int(time.time() - contract['generated_ms'] / 1000))
    rows = []
    belief = ((contract.get('watchdog') or {}).get('belief')
              or {}).get('bots', {})
    ordered = []
    for title, members in grouped(contract, view):
        if title:
            ordered.append((None, title))
        ordered += members
    for botid, b in ordered:
        if botid is None:                      # U12: a group's heading row
            rows.append(f'<tr><th colspan="15" class="grp">{b}</th></tr>')
            continue
        if b is None:
            # no fills in the window — the engine's own belief fills in,
            # and says so (the snapshot is the bot's belief, not the venue)
            bl = belief.get(botid, {})
            alive = bl.get('alive')
            pos = bl.get('position') or 0.0
            state = ('DEAD' if alive is False else
                     'HOLDING' if abs(pos) > 1e-12 else 'RESTING')
            cls = 'neg' if state == 'DEAD' else 'dim'
            wd0 = contract.get('watchdog') or {}
            ceil0 = (wd0.get('ceilings') or {}).get(botid)
            watch0 = (f'<td class="dim">{abs(pos) / ceil0 * 100:.0f}% of '
                      f'{ceil0:,.4g}</td>' if ceil0
                      else '<td class="dim">no limit</td>')
            rows.append(
                f'<tr><td>{_side_tag(botid)}{botid}</td>'
                f'<td class="{cls}">{state}</td>'
                f'<td class="dim">0</td><td class="dim">no fills</td>'
                f'<td class="dim">—</td><td class="dim">—</td>'   # D63
                f'<td class="dim">'
                + (f'{pos:.10g} (belief)' if abs(pos) > 1e-12 else '—')
                + '</td><td class="dim">—</td><td class="dim">—</td>'
                  '<td class="dim">—</td><td class="dim">—</td>'
                  '<td class="dim">—</td><td class="dim">—</td>'
                  '<td class="dim">—</td>'
                + watch0
                + f"<td class='dim'><a href='/edit?fleet={idx}&bot={botid}'>"
                  f"edit</a> <a href='/edit?fleet={idx}&bot={botid}"
                  f"&mode=remove'>remove</a> "
                  f"<a href='/setup?fleet={idx}&copy={botid}'>copy</a>"
                  "</td></tr>")
            continue
        state = ('HOLDING' if abs(b['position']) > 1e-12 else 'FLAT')
        openat = (f"{b['position']:.10g} @ {b['avg_cost']:.6g}"
                  if abs(b['position']) > 1e-12 else '—')
        total = card_total(b)                                   # D63
        note = ' *' if b['truncated'] else ''
        rng = contract.get('ranges', {}).get(botid)
        floor = contract.get('fee_floors', {}).get(botid)
        wd = contract.get('watchdog') or {}
        ceil = (wd.get('ceilings') or {}).get(botid)
        if ceil:
            used = abs(b['position']) / ceil * 100
            wcls = ' class="neg"' if used >= 100 else ''
            watch = f'<td{wcls}>{used:.0f}% of {ceil:,.4g}</td>'
        else:
            watch = '<td class="dim">no limit</td>'
        edge = ''
        if rng and b['mark']:
            edge = (f"<td>{strip(rng, b['mark'])}</td>"
                    f"<td class='dim'>{(b['mark'] - rng['lower']) / b['mark'] * 100:.1f}%"
                    f" / {(rng['upper'] - b['mark']) / b['mark'] * 100:.1f}%</td>")
        else:
            edge = '<td class="dim">—</td><td class="dim">—</td>'
        rows.append(
            f'<tr><td>{_side_tag(botid)}{botid}{note}</td>'
            f'<td class="dim">{state}</td>'
            f"<td>{b['fills']}</td>{money(b['realized'])}"
            f"{money(b['fees'], cls=False)}{money(b.get('funding'))}"
            f"<td>{openat}</td>"
            f"{money(b['unreal_at_mark'])}{money(total)}"
            f"<td>{b['bought']:,.4g}</td><td>{b['sold']:,.4g}</td>"
            f"{edge}<td>{settle(b, floor)}</td>{watch}"
            f"<td class='dim'><a href='/edit?fleet={idx}&bot={botid}'>edit"
            f"</a> <a href='/edit?fleet={idx}&bot={botid}&mode=remove'>"
            f"remove</a> <a href='/setup?fleet={idx}&copy={botid}'>copy</a>"
            "</td></tr>")
    return f"""
<h1 id="fleet{idx}">{label} {tier_badge(contract)} — last {contract['window_hours']:g}h {sweep_note(contract)}
<span class="dim">(read {age}s ago; refreshes every {REFRESH_S}s)</span></h1>
<div class="scroll"><table class="fleet">{COLS}
<tr><th>bot</th><th>state</th><th>fills</th><th>realized</th>
<th>fees</th><th>funding</th><th>open@avg</th><th>unreal</th><th>total</th>
<th>bought</th><th>sold</th><th>range</th><th>edge lo/hi</th>
<th>stop-now est.</th><th>watcher</th><th></th></tr>
{''.join(rows)}</table></div>
"""


def named(typed, botid):
    """U18: the typed name is the decision; its capitals are not. A bot's
    name is one spelling, so the comparison ignores case and stray space."""
    return bool(botid) and (typed or '').strip().lower() == botid.lower()


def refusal_box(title, why, extra=''):
    """U11: a refusal is the first thing on the page, boxed, in plain
    words: what happened (nothing was saved), the engine's reason, and
    what to do about it."""
    import html as _html
    return (f'<div class="refusal"><b>{_html.escape(title)}</b> — nothing '
            f'was saved.<br>{_html.escape(str(why))}{extra}</div>')


def coin_of(botid):
    """The coin a bot's position is counted in, from its id: linBTCUSDTl ->
    BTC, linBTCPERPl -> BTC, invBTCUSDl -> BTC, linSOLl (Hyperliquid) ->
    SOL."""
    core = botid[3:-1] if len(botid) > 4 else botid
    for quote in ('USDT', 'USDC', 'PERP', 'USD'):
        if core.endswith(quote) and len(core) > len(quote):
            return core[:-len(quote)]
    return core


def units_of(botid, terms):
    """U53: (money coin, margin coin) for a card — from the contract's
    terms; a contract without them answers from the bot's own name."""
    if terms and terms.get('quote'):
        return terms['quote'], terms.get('margin_coin') or terms['quote']
    mt = {'lin': 'linear', 'inv': 'inverse', 'spo': 'spot'}.get(botid[:3], 'linear')
    u = money_units(None, mt, botid[3:-1])
    return u['quote'], u['margin_coin']


def holding_html(pos, avg, mark, botid, inverse=False, quote=None):
    """U44 (owner 2026-10-05: "users can see the value, cost, asset … bybit
    lets you choose these as user preferences"): a holding said three ways
    at once — the coins, what they are worth at the mark, what they cost at
    the average — each in its own span; the page's "size in" switch shows
    one or all, remembered per browser tab. An inverse position is counted
    in dollars by the venue: its coins are dollars / price."""
    if abs(pos) <= 1e-12:
        return 'holding nothing'
    coin = coin_of(botid)
    if inverse:
        coins = abs(pos) / mark if mark else None
        value, cost = abs(pos), abs(pos)            # $1 contracts
        cost_coins = abs(pos) / avg if avg else None
    else:
        coins = abs(pos)
        value = abs(pos) * mark if mark else None
        cost = abs(pos) * avg if avg else None
        cost_coins = None

    def n(v):
        return '—' if v is None else (f'{v:,.0f}' if abs(v) >= 1000
                                      else f'{v:,.6g}')
    sign = '-' if pos < 0 else ''
    if quote is None:                       # U53: from the bot's own name
        quote = units_of(botid, None)[0]
    q = f' {quote}' if quote else ''
    parts = [f'<span class="u-coin">{sign}{n(coins)} {coin}</span>',
             f'<span class="u-value">worth {n(value)}{q}</span>',
             f'<span class="u-cost">cost {n(cost)}{q}'
             + (f' ({n(cost_coins)} {coin})' if cost_coins else '')
             + f' @ {avg:.6g}</span>']
    return 'holding ' + '<span class="u-sep"> · </span>'.join(parts)


SIZE_VIEWS = (('all', 'all'), ('coin', 'coins'), ('value', 'value'),
              ('cost', 'cost'))


def page_links(table=False, view='all'):
    """U60: every page of the panel, as links — the side panel's first
    block on the fleet page, a bar across the top of every other page."""
    q = '' if view == 'all' else f'?view={view}'
    return ((f'<a href="/{q}">cards</a>' if table else f'<a href="/table{q}">table</a>')
            + '<a href="/control">control</a><a href="/setup">set up a bot</a><a href="/trade">new trade</a>'
              '<a href="/rehearse">rehearse a grid</a><a href="/export">export '
              'snapshot</a><a href="/key">key</a>')


def side_nav():
    """U60: the column every page outside the fleet page wears, the fleet
    page's own shape — the pages, a way back, the one warning a form
    needs, the theme. Opens the page grid; PAGE_END closes it."""
    return ('<div class="page"><nav class="side"><h3>pages</h3>'
            '<a href="/">back to your bots</a><a href="/table">table</a>'
            '<a href="/control">control</a><a href="/setup">new bot</a><a href="/trade">new trade</a>'
            '<a href="/rehearse">rehearse a grid</a><a href="/export">export snapshot</a>'
            '<a href="/key">key</a><a href="javascript:history.back()">&larr; back</a>'
            '<span class="dim">leaving a form saves nothing</span>'
            '<button class="quiet theme" onclick="document.documentElement.'
            'classList.toggle(\'light\')">theme</button></nav><main>')


PAGE_END = '</main></div>'


def nav_panel(table, view):
    """U51 (the owner: the links at the bottom and the switches at the top
    "may be better as a side panel"): every page link and every view
    switch in one panel beside the cards, pinned while the page scrolls —
    pages, arrange, numbers (cards only: nothing folds in the table),
    size in, leverage, theme. The live page only; the export has no
    actions to offer."""
    here = '/table' if table else '/'
    pages = page_links(table, view)
    arrange = ''.join(
        f'<b class="on">{words}</b>' if key == view else
        f'<a href="{here}{"" if key == "all" else "?view=" + key}">{words}</a>'
        for key, words in VIEWS)
    # U58: every card's lower half, folded or open at once — where U22's
    # show-all switch was; the numbers themselves live on the position's
    # page (U56)
    numbers = ('' if table else
               '<h3>cards</h3><a href="javascript:ggFold(\'open\',\'fold\')" data-fold="open" data-cls="fold">full</a>'
               '<a href="javascript:ggFold(\'folded\',\'fold\')" data-fold="folded" data-cls="fold">folded</a>'
               # U59: every account's cards behind its heading and its box
               '<h3>accounts</h3><a href="javascript:ggFold(\'open\',\'acct\')" data-fold="open" data-cls="acct">full</a>'
               '<a href="javascript:ggFold(\'folded\',\'acct\')" data-fold="folded" data-cls="acct">folded</a>')
    # U44: what a holding is said in, as Bybit's preference
    size = ''.join(f'<a href="javascript:ggSize(\'{k}\')" data-size="{k}">{w}</a>'
                   for k, w in SIZE_VIEWS)
    # R19: the account's leverage now, or as if every order filled
    lev = ('<a href="javascript:ggLev(\'now\')" data-lev="now">now</a>'
           '<a href="javascript:ggLev(\'filled\')" data-lev="filled">if all filled</a>')
    return (f'<nav class="side"><h3>pages</h3>{pages}<h3>arrange</h3>{arrange}'
            f'{numbers}<h3>size in</h3>{size}<h3>leverage</h3>{lev}'
            '<button class="quiet theme" onclick="document.documentElement.'
            'classList.toggle(\'light\')">theme</button></nav>')


def _open_pnl(p):
    v = p.get('open_pnl')
    return '—' if v is None else f'<span class="{_num_cls(v)}">{v:+,.2f}</span>'


def agent_box(contract):
    """J5: an agent fleet's score and its open paper positions, from the
    readout contract; nothing for any other fleet."""
    a = contract.get('agent')
    if not a:
        return ''
    if a.get('error'):
        return f'<div class="pnl"><span class="dim">agent</span> {html.escape(a["error"])}</div>'
    rows = ''.join(
        f"<tr><td>{html.escape(str(p['id']))}</td><td>{html.escape(p['side'])} {html.escape(p['market'])}</td>"
        f"<td>{p['notional']:,.2f}</td><td>{p['entry']:,.6g}</td><td>{p['stop']:,.6g} / {p['tp']:,.6g}</td>"
        f"<td>{'—' if p.get('mark') is None else format(p['mark'], ',.6g')}</td>"
        f"<td>{_open_pnl(p)}</td>"
        f"<td class='dim'>{html.escape(str(p.get('reason') or ''))[:80]}</td></tr>"
        for p in a['open'])
    table = ('<table><tr class="dim"><td>id</td><td>position</td><td>notional</td><td>entry</td>'
             f'<td>stop / take profit</td><td>mark</td><td>open</td><td>reason</td></tr>{rows}</table>'
             if rows else '<p class="dim">no open paper position</p>')
    words = '<br>'.join(html.escape(ln) for ln in a['text'].splitlines())
    return (f'<div class="pnl"><span class="dim">agent · {"paper" if a["paper"] else "live"} · '
            f'{html.escape(", ".join(a["markets"]))} · day-loss limit {a["max_loss_day"]:,.6g}</span>'
            f'<div class="parts">{words}</div>{table}</div>')


def render(labelled, static=None, table=False, view='all'):
    """One renderer, two artefacts (§4): the live page, or — with
    static=timestamp-text — a self-contained export: no refresh, no
    actions, provenance stamped. The numbers can never diverge because
    there is only one code path to diverge from. Two faces of the same
    contract: cards (the default) and the dense table (/table)."""
    face = section if table else cards_section
    if view not in dict(VIEWS):
        view = 'all'
    body = ''.join(face(i, lb, c, view, scripted=not static) if not table else face(i, lb, c, view)
                   for i, (lb, c) in enumerate(labelled))
    if static:
        head = ''
        chrome = (f'<p class="dim">exported {static} — a snapshot, '
                  'not a live view; the fleet has moved since.</p>')
    else:                                        # U51: the side panel
        # U61: the page refreshes in place — the script fetches this same
        # URL and swaps the strip and the cards, so nothing flickers and
        # nothing the reader opened or scrolled to moves; without script,
        # the old whole-page refresh
        head = (f'<meta name="gg-refresh" content="{REFRESH_S}">'
                f'<noscript><meta http-equiv="refresh" content="{REFRESH_S}"></noscript>')
        body = f'<div class="page">{nav_panel(table, view)}<main>{body}</main></div>'
        chrome = KEEP_JS
    return f"""<!doctype html><meta charset="utf-8">
<title>grid-gremlin</title><style>{CSS}</style>
{head}{hero_strip(labelled)}{body}
{chrome}
<p class="dim">this page renders the engine's own readout contract — it
cannot disagree with the terminal. It holds no keys; venue writes are the
engine's alone.</p>"""
