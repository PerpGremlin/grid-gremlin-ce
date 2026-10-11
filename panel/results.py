"""The results page (R24) and the agent's box. Out of render.py (D91 step 3)."""
import html
from .drawings import equity_svg
from .html_bits import _num_cls


def _result_row(botid, b, gone=False):
    """R24: one bot's line — its curve since its first kept fill, what it
    made after fees, its fills, from when; an inverse book in its coin."""
    import time as _t
    coin = (b.get('settle') or {}).get('coin')
    pts = [(t / 1000.0, v) for t, v in (b.get('series') or [])]
    net = pts[-1][1] if pts else None
    unit = f' {coin}' if coin else ''
    first = b.get('first_ms')
    since = _t.strftime('%d %b %Y', _t.gmtime(first / 1000)) if first else '—'
    tail = ''
    if gone:
        tail = (f" · market left the fleet; last fill "
                f"{_t.strftime('%d %b %Y', _t.gmtime(b['last_ms'] / 1000))}"
                ' · its linked fills only (a venue-made close is not counted)')
    elif b.get('whole') is False:
        tail = ' · the record is not whole (a gap in collection) — not summed'
    figure = ('—' if net is None else
              f'<span class="{_num_cls(net)}">{net:+,.{6 if coin else 2}f}{html.escape(unit)}</span>')
    return (f'<tr><td>{html.escape(botid)}</td><td style="width:40%">{equity_svg(pts, width=240, height=28)}</td>'
            f'<td>{figure}</td><td>{b.get("fills", 0)}</td><td class="dim">since {since}{tail}</td></tr>')


def results_page(labelled):
    """R24: every bot's results since its first kept fill, as a curve —
    each account's bots, then the bots whose market has left the fleet
    (their fills are kept and still said). Realized after fees, from the
    kept ledger; the cards say the live position."""
    parts = ['<h1>results since the first kept fill</h1>'
             '<p class="say">What each bot has made after fees since the ledger first saw it '
             '(realized: the open position is on its card). A bot whose market has left the '
             'fleet is still listed, under its account.</p>']
    head = ('<table><tr class="dim"><td>bot</td><td>curve</td><td>made after fees</td>'
            '<td>fills</td><td>since</td></tr>')
    for label, c in labelled:
        sf = {b: v for b, v in (c.get('since_first') or {}).items() if v}
        gone = c.get('gone') or {}
        if not sf and not gone:
            parts.append(f'<h2>{html.escape(label)}</h2><p class="dim">nothing kept yet</p>')
            continue
        rows = ''.join(_result_row(b, v) for b, v in sorted(sf.items()))
        parts.append(f'<h2>{html.escape(label)}</h2>{head}{rows}</table>')
        if gone:
            parts.append(f'<h3 class="dim">{html.escape(label)}: markets that left the fleet</h3>'
                         + head + ''.join(_result_row(b, v, gone=True) for b, v in sorted(gone.items()))
                         + '</table>')
    return ''.join(parts)


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
