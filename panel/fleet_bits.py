"""A fleet section's heading pieces: the watchdog's sweep, the setup button, the windows line. Out of render.py (D91 step 3)."""
import json
from .html_bits import WATCHDOG_OFF_S, money, refusal_box


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
               (' <b>&larr; 7d</b>' if n == w7['best'] else '') + \
               (" <span class='neg'>stopped</span>" if a and a.get('stopped')
                else '')                                                 # T15
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
            "<p class='dim'>score = net: realised at average cost (stop-outs "
            "in) less fees; fees share = fees over the matched trips' grid "
            "profit. The range exactly as "
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
        mark = (' <b>&larr; best</b>' if r['rungs'] == out['best'] else '') + \
            (" <span class='neg'>stopped</span>" if r.get('stopped') else '')   # T15
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
            "<p class='dim'>score = net over this window: realised at "
            "average cost (stop-outs in) less fees; fees share = fees over "
            "the matched trips' grid profit. "
            'the range exactly as you set it, the engine\'s own planner, '
            'fills on trade-through through 5-minute candles. Rows in the '
            'plateau are coloured. Window shown, never annualised; a '
            'sweep is not a promise — same candles are never same fills.'
            '</p>')
