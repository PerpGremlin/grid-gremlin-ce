"""The front page's right half (D96, U78): what the owner picked on the
left, beside the bots — one bot's fills, newest first, each with what it
realised; nothing picked, a line saying how. The pick lives in the address
(`/?fleet=N&bot=ID`), so the page's own refresh keeps the half live and a
link works without script."""
import time

from .card import _plain_name
from .html_bits import _num_cls, esc, qarg, units_of

SHOWN = 200                 # rows drawn; older ones counted, not drawn


def empty_pane():
    return ('<aside class="pane"><p class="dim">Pick a bot by its name: its fills '
            'and what each one made open here.</p></aside>')


def _n(v, f=',.6g'):
    return '—' if v is None else format(v, f)


def _signed(v):
    if v is None:
        return '<td class="dim">—</td>'
    return f'<td class="{_num_cls(v)}">{v:+,.4g}</td>' if abs(v) < 1 else \
        f'<td class="{_num_cls(v)}">{v:+,.2f}</td>'


def detail_pane(idx, label, botid, contract, listing):
    """U78: the picked bot — its name and fleet, what its kept record
    realised and paid in fees, then its fills newest first. `listing` is
    gridgremlin.fill_list's answer (None: no kept record to read)."""
    b = (contract.get('bots') or {}).get(botid)
    quote, _ = units_of(botid, (contract.get('terms') or {}).get(botid))
    head = (f'<h2>{esc(_plain_name(botid, contract, b))} <span class="dim">{esc(label)}</span> '
            f'<a class="plain" data-pick href="/">close</a></h2>'
            f'<p><a href="/position?fleet={idx}&amp;bot={qarg(botid)}">numbers</a> '
            f'<a href="/edit?fleet={idx}&amp;bot={qarg(botid)}">edit</a></p>')
    if ((contract.get('terms') or {}).get(botid) or {}).get('strategy') == 'portfolio':
        return (f'<aside class="pane">{head}<p class="dim">A portfolio row: its legs and their '
                'books are on its numbers page.</p></aside>')
    if not listing or not listing['rows']:
        return f'<aside class="pane">{head}<p class="dim">No fills kept for this bot yet.</p></aside>'
    rows = listing['rows']
    if listing['whole']:
        net = listing['realized'] - listing['fees']
        summary = (f'<p>{len(rows)} fills since its record began · realised '
                   f'<b class="{_num_cls(listing["realized"])}">{listing["realized"]:+,.2f}</b> · fees '
                   f'{listing["fees"]:,.2f} · after fees <b class="{_num_cls(net)}">{net:+,.2f}</b> '
                   f'<span class="dim">{esc(quote)}, by average cost as the exchange counts it; '
                   'funding is on the numbers page</span></p>')
    else:
        summary = (f'<p>{len(rows)} fills · fees {listing["fees"]:,.2f} {esc(quote)}</p>'
                   '<p class="dim">Its record has no whole start yet (it began mid-position), '
                   'so what each fill made is not worked out — never guessed.</p>')
    body = []
    for r in reversed(rows[-SHOWN:]):
        what = ('opening balance' if r['kind'] == 'opening'
                else ('entry' if r['entry'] else 'exit') + (f' · {esc(r["kind"])}' if r['kind'] else ''))
        body.append(f'<tr><td>{time.strftime("%m-%d %H:%M", time.gmtime(r["time_ms"] / 1000))}</td>'
                    f'<td class="{"pos" if r["side"] == "buy" else "neg"}">{r["side"]}</td><td>{what}</td>'
                    f'<td>{_n(r["price"])}</td><td>{_n(r["qty"])}</td><td>{_n(r["fee"], ",.4g")}</td>'
                    f'{_signed(r["realized"])}{_signed(r["net"])}</tr>')
    older = (f'<p class="dim">{len(rows) - SHOWN} older fills not drawn.</p>'
             if len(rows) > SHOWN else '')
    return (f'<aside class="pane">{head}{summary}<table class="fills"><tr><th>UTC</th><th>side</th>'
            '<th></th><th>price</th><th>qty</th><th>fee</th><th>made</th><th>after fees, so far</th></tr>'
            f'{"".join(body)}</table>{older}</aside>')
