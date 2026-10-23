"""The front page's right half (D96, U78): what the owner picked on the
left, beside the bots — one bot's fills, newest first, each with what it
realised; nothing picked, a line saying how. The pick lives in the address
(`/?fleet=N&bot=ID`), so the page's own refresh keeps the half live and a
link works without script."""
import time

from .card import _plain_name
from .html_bits import _num_cls, esc, qarg, units_of

SHOWN = 200                 # rows drawn; older ones counted, not drawn


PAGES = {'setup': 'new bot', 'trade': 'new trade', 'rehearse': 'rehearse a grid',
         'results': 'results', 'carry': 'carry', 'control': 'control'}


def page_pane(name, body):
    """U78d: one of the panel's pages in the right half, under its name."""
    return (f'<aside class="pane"><h2>{esc(PAGES[name])} <a class="plain" data-pick href="/">back</a></h2>'
            f'{body}</aside>')


def empty_pane():
    return ('<aside class="pane"><p class="dim">Pick a bot by its name: its fills '
            'and what each one made open here.</p></aside>')


def _n(v, f=',.6g'):
    return '—' if v is None else format(v, f)


def _signed(v):
    if v is None:
        return '<td class="dim">—</td>'
    if abs(v) < 5e-5:              # float dust (+1.455e-11) is nothing made
        v = 0.0
    return f'<td class="{_num_cls(v)}">{v:+,.4g}</td>' if abs(v) < 1 else \
        f'<td class="{_num_cls(v)}">{v:+,.2f}</td>'


TABS = (('fills', 'fills'), ('numbers', 'numbers'), ('edit', 'edit'))


def detail_pane(idx, label, botid, contract, listing, show='fills', numbers='', shown=SHOWN):
    """U78: the picked bot — its name and fleet, a tab per view (U78b), and
    the view: its fills newest first with what its kept record realised and
    paid in fees (`listing`, gridgremlin.fill_list's answer; None: no kept
    record), or the body given (`numbers`: the numbers page's, or the edit
    door's)."""
    b = (contract.get('bots') or {}).get(botid)
    terms = (contract.get('terms') or {}).get(botid) or {}
    quote, _ = units_of(botid, terms)
    name = (botid[3:] + ' portfolio' if terms.get('strategy') == 'portfolio'
            else _plain_name(botid, contract, b))
    show = show if show in dict(TABS) else 'fills'
    tabs = ' '.join(f'<b class="on">{word}</b>' if key == show else
                    f'<a data-pick href="/?fleet={idx}&amp;bot={qarg(botid)}&amp;show={key}">{word}</a>'
                    for key, word in TABS)
    head = (f'<h2>{esc(name)} <span class="dim">{esc(label)}</span> '
            f'<a class="plain" data-pick href="/">back</a></h2>'
            f'<p class="ptabs">{tabs}</p>')
    if show in ('numbers', 'edit'):
        return f'<aside class="pane">{head}{numbers}</aside>'
    if terms.get('strategy') == 'portfolio':
        return (f'<aside class="pane">{head}<p class="dim">A portfolio row: its legs and their '
                'books are under numbers.</p></aside>')
    if not listing or not listing['rows']:
        return f'<aside class="pane">{head}<p class="dim">No fills kept for this bot yet.</p></aside>'
    rows = listing['rows']
    if listing['whole']:
        net = listing['realized'] - listing['fees']
        summary = (f'<p>{len(rows)} fills since its record began · realised '
                   f'<b class="{_num_cls(listing["realized"])}">{listing["realized"]:+,.2f}</b> · fees '
                   f'{listing["fees"]:,.2f} · after fees <b class="{_num_cls(net)}">{net:+,.2f}</b> '
                   f'<span class="dim">{esc(quote)}, by average cost as the exchange counts it; '
                   '"total" is after fees, so far; funding is under numbers</span></p>')
    else:
        summary = (f'<p>{len(rows)} fills · fees {listing["fees"]:,.2f} {esc(quote)}</p>'
                   '<p class="dim">Its record has no whole start yet (it began mid-position), '
                   'so what each fill made is not worked out — never guessed.</p>')
    body = []
    for r in reversed(rows[-shown:]):
        what = ('opening balance' if r['kind'] == 'opening'
                else ('entry' if r['entry'] else 'exit') + (f' · {esc(r["kind"])}' if r['kind'] else ''))
        body.append(f'<tr><td>{time.strftime("%m-%d<br>%H:%M", time.gmtime(r["time_ms"] / 1000))}</td>'
                    f'<td><span class="{"pos" if r["side"] == "buy" else "neg"}">{r["side"]}</span> {what}</td>'
                    f'<td>{_n(r["qty"])}<br><span class="dim">@ {_n(r["price"])}</span></td>'
                    f'<td>{_n(r["fee"], ",.4g")}</td>'
                    f'{_signed(r["realized"])}{_signed(r["net"])}</tr>')
    older = (f'<p class="dim">{len(rows) - shown} older fills not drawn.</p>'
             if len(rows) > shown else '')
    # U109: six columns that fit the half — the side with its role, the
    # size at its price
    return (f'<aside class="pane">{head}{summary}<table class="fills bot"><tr><th>UTC</th><th>side</th>'
            '<th>qty @ price</th><th>fee</th><th>made</th><th>total</th></tr>'
            f'{"".join(body)}</table>{older}</aside>')
