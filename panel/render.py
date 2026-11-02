"""The panel's renderer: the cards, the table, the strip and the side panel,
all from the readout's contract (§4: one renderer, two artefacts)."""
from gridgremlin.report import card_total
import html
import re
import time
import urllib.parse
from .css import CSS
from .reference import KEEP_JS, THEME_JS
from .card import card, not_whole, pnl_parts, unpriced
from .drawings import equity_boxes
from .fleet_bits import sweep_note
from .html_bits import REFRESH_S, _num_cls, esc, qarg
from .nav import VIEWS, grouped, nav_panel
from .results import agent_box
from .strip_view import (FREE_WARN, MMR_WARN, SINCE_WORDS, account_change_lines, account_lines,
                         exchange_free, exchange_leverage, exchange_mmr, exchange_since_first, free_share,
                         hero_strip, portfolio_total, tier_badge, venue_money)
from .table import section


ACCOUNT_PNL_NOTE = ('this account\'s bots after fees, each counted as its card says: most '
                    'since it was last flat, so not the same window as the equity line below, '
                    'which runs from the first snapshot with top-ups in')


def acct_key(label):
    """D163: an account's tab key in `?acct=` — its name in lower case, each
    run of other characters one dash ("Bybit demo" → bybit-demo)."""
    return re.sub(r'[^a-z0-9]+', '-', str(label).lower()).strip('-') or 'account'


def needs_look(idx, contract, watch):
    """D163: what needs a look on one account, [(botid or None, words)] —
    the overview's own list (U85) for its bots and its readout, its MMR when
    red (U66), its free share when red (U100). Shown in the box, never folded."""
    out = [(botid, words) for i, botid, _, words in watch if i == idx]
    belief = (contract.get('watchdog') or {}).get('belief') or {}
    rate = belief.get('mm_rate')
    if rate is not None and rate >= MMR_WARN:
        out.append((None, f'account MMR {rate:.1%}: the exchange liquidates at 100%'))
    got = free_share(belief)
    if got is not None and got[1] < FREE_WARN:
        out.append((None, f'free to trade only {got[1]:.0%} of equity'))
    return out


def _look_html(idx, look):
    if not look:
        return ''
    return ('<ul class="watch look">' + ''.join(
        '<li>' + (f'<a class="bname" data-pick href="/?fleet={idx}&amp;bot={qarg(botid)}">{words}</a>'
                  if botid else words) + '</li>' for botid, words in look) + '</ul>')


def head_cells(contract):
    """D163: the account box's header numbers beside its name and its Total
    P&L — equity, account leverage (now, or if every order filled: R19's
    switch), available to trade (U100's own figure and colour); "—" unread."""
    from gridgremlin.report import account_leverage
    belief = (contract.get('watchdog') or {}).get('belief') or {}
    levs = account_leverage(contract)
    eq = belief.get('equity')
    if eq is None:
        eqs = [a['equity'] for a in levs.values() if a.get('equity') is not None]
        eq = sum(eqs) if eqs else None
    money = venue_money(contract)
    now = [a['now'] for a in levs.values()]
    lev_now = ('—' if not now or any(v is None for v in now)
               else ' · '.join(f'{v:.2f}x' for v in now))
    fill = [(a['fall'], a['rise']) for a in levs.values()]
    lev_fill = ('—' if not fill or any(None in f for f in fill) else
                ' · '.join(f'{f:.2f}x on a fall, {r:.2f}x on a rise' for f, r in fill))
    got = free_share(belief)
    free = ('—' if got is None else
            f'<b class="{"neg" if got[1] < FREE_WARN else ""}">{got[0]:,.2f}</b> {money} '
            f'<span class="dim">({got[1]:.0%})</span>')
    return ('<span class="hc"><span class="dim">equity</span> '
            + ('—' if eq is None else f'<b>{eq:,.2f}</b> {money}') + '</span>'
            '<span class="hc"><span class="dim">account leverage</span> '
            f'<b class="lev-now">{lev_now}</b><b class="lev-filled">{lev_fill} if all filled</b></span>'
            f'<span class="hc"><span class="dim">available to trade</span> {free}</span>')


def cards_section(idx, label, contract, view='all', scripted=True, watch=None):
    age = max(0, int(time.time() - contract['generated_ms'] / 1000))
    belief = ((contract.get('watchdog') or {}).get('belief')
              or {}).get('bots', {})
    live = [b for b in contract['bots'].values()                 # an inverse book with no
            if b is not None and b.get('realized') is not None]    # mark has no dollars yet
    net = sum(b['realized'] - b['fees'] for b in live)
    funded = [b.get('funding') for b in live]                     # D63
    funding = (None if any(f is None for f in funded)
               else sum(funded))
    opened = [b['unreal_at_mark'] for b in live
              if b['unreal_at_mark'] is not None]
    pfo = portfolio_total(contract)
    total = sum(card_total(b) for b in live) + pfo                          # H6
    # U95: the books whose open part is not priced are named, never a silent 0
    gap = sum(1 for b in contract['bots'].values() if unpriced(b))
    left = (f'<div class="parts neg">{gap} bot{"s" if gap != 1 else ""} holding a position '
            'not priced (mark unread): their open part is not in this total</div>'
            if gap else '')
    cut = sum(1 for b in contract['bots'].values() if not_whole(b))       # R14c
    left += (f'<div class="parts neg">{cut} bot{"s" if cut != 1 else ""} never flat since '
             'its record began: not whole, not in this total</div>' if cut else '')
    cards = '</div><div class="cards">'.join(
        (f'<div class="grp">{esc(title)}</div>' if title else '')
        + ''.join(card(idx, botid, b, contract, belief)
                  for botid, b in rows)
        for title, rows in grouped(contract, view))
    if watch is None:
        from .overview import watch_list
        watch = [(idx, *w[1:]) for w in watch_list([(label, contract)])]
    own = scripted and not contract.get("public")     # U138, U153: the live panel's only
    change = account_change_lines(contract, switch=False) if own else ''
    since = (('<button type="button" class="quiet tog" data-tog="since">since: '
              + ''.join(f'<span class="s{k}">{w}</span>' for k, w in SINCE_WORDS) + '</button>')
             if change else '')
    # U45: the exchange's money in a box of its own, under its name
    # U59: one link beside the count folds or opens this account's cards
    # alone; its word says which it will do next
    # U86: each exchange in a box of its own, edge to edge with the site's look
    # D163: the name, the badge and the numbers in one row across the box;
    # what needs a look under it, never folded; every other line folded
    return (f"<section class=\"fbox\"><div class=\"acchead\"><h1 id=\"fleet{idx}\">{esc(label)} {tier_badge(contract)} — {len(contract['bots'])} bots "
            + (f'<a href="#" data-foldin="{idx}" class="tier">fold cards</a> '
               if scripted else '')               # an export has no script to run it
            # U87: the heading is the name; how fresh it is, a quiet line under it
            + ('<span class="tier neg">stopped</span> ' if contract.get('stopped') else '')   # U104
            + f'<span class="meta">{sweep_note(contract)} <span class="dim">(read {age}s ago; '
            f'refreshes every {REFRESH_S}s)</span></span></h1>'
            # D157: the headline in the platforms' words; the caveat (U98) on hover
            f'<div class="pnl {_num_cls(total)}"><span class="dim st" title="{ACCOUNT_PNL_NOTE}">'
            'Total P&amp;L</span> <span class="big '
            f'{_num_cls(total)}">{total:+,.2f}</span> {venue_money(contract)} '
            '<span class="dim">after fees</span></div>'
            f'{head_cells(contract)}{since}</div>'
            + (f'<div class="refusal"><b>couldn\'t load this account</b> — reading '
               f'it failed; the panel tries again on a later refresh.'
               f'<br>{html.escape(contract["unavailable"])}</div>'
               if contract.get('unavailable') else '')
            + f'{left}{_look_html(idx, needs_look(idx, contract, watch))}'
            # D163: folded by default, the click remembered (data-k, V12)
            f'<details class="acctd" data-k="acctd:{idx}"><summary>account details '
            '<span class="dim">— P&amp;L parts, leverage, MMR, '
            + ('balances, what changed, ' if own else '') + 'equity</span></summary>'
            f'<div class="parts">'
            f'{pnl_parts(net, sum(opened) if opened else None, funding)}'
            + (f' · portfolio rows <b class="{_num_cls(pfo)}">{pfo:+,.2f}</b>' if pfo else '')
            + f'</div>{exchange_since_first(contract)}{exchange_leverage(contract)}'
            f'{exchange_mmr(contract)}{exchange_free(contract)}{account_lines(contract) + change if own else ""}'   # U66, U100; U138 the live panel's only; U153 never the public page
            f'{equity_boxes(contract, idx)}'                                          # U63
            f'{agent_box(contract)}</details>'                                   # J5
            # U59: the account folds to its heading and its box; the side
            # panel folds or opens every account at once
            f'<details class="acct" data-k="acct:{idx}" open><summary>'
            f"{len(contract['bots'])} bots</summary>"
            + (f'<div class="cards">{cards}</div>' if contract['bots'] else
               '<p class="dim">no bots in this fleet — <a href="/setup">set one up</a>; '
               'it starts with its account\'s engine</p>')   # D149
            + '</details></section>')


def acct_tabs(labelled, chosen, watch, query=None, here='/'):
    """D163 (the owner, 2026-11-01: "maybe instead of scrolling we have tabs
    for each account on the left half"): "all", then one tab per account,
    each with its bot count and a red dot when something on it needs a look.
    Plain links (`?acct=`, the rest of the address kept), so they work with
    no script; KEEP_JS keeps the choice per browser tab as well."""
    keep = {k: v for k, v in (query or {}).items() if k in ('view', 'fleet', 'bot', 'show')}

    def href(key):
        return here + '?' + urllib.parse.urlencode({**keep, 'acct': key}).replace('&', '&amp;')

    def tab(key, words, n, red):
        return (f'<a href="{href(key)}" data-acct="{key}" class="tab{" pick" if key == chosen else ""}">'
                f'{words} <span class="n">{n}</span>'
                + ('<i class="dot" title="needs a look"></i>' if red else '') + '</a>')
    reds = [bool(needs_look(i, c, watch)) or bool(c.get('unavailable'))
            for i, (_, c) in enumerate(labelled)]
    return ('<nav class="acctabs" aria-label="accounts">'
            + tab('all', 'all', sum(len(c['bots']) for _, c in labelled), any(reds))
            + ''.join(tab(acct_key(lb), esc(lb), len(c['bots']), reds[i])
                      for i, (lb, c) in enumerate(labelled))
            + '</nav>')


def chosen_acct(labelled, acct):
    """D163: the tab `?acct=` names, or "all" for none, "all" or a name no
    account has."""
    keys = {acct_key(lb) for lb, _ in labelled}
    return acct if acct in keys else 'all'


# the panel on a phone (audit 2026-10-16); the showcase drops it, the site adds its own
VIEWPORT = '<meta name="viewport" content="width=device-width,initial-scale=1">'


def render(labelled, static=None, table=False, view='all', pane=None, notice='', acct=None, query=None):
    """One renderer, two artefacts (§4): the live page, or — with
    static=timestamp-text — a self-contained export: no refresh, no
    actions, provenance stamped. The numbers can never diverge because
    there is only one code path to diverge from. Two faces of the same
    contract: cards (the default) and the dense table (/table). `notice`:
    one line above the cards on the live page (F31: config files edited
    here and not in git yet), never in an export. `pane`: the right half's
    HTML — what the owner picked (D96, U78); nothing picked, how to pick.
    `acct` (D163): the account tab chosen (`?acct=`) — the live page shows
    that account alone; `query`, the rest of the address its tabs keep."""
    face = section if table else cards_section
    if view not in dict(VIEWS):
        view = 'all'
    # D163: tabs on the live page only — an export is one file, and the
    # public page (script-free, its own links) shows every account stacked
    tabs = not static and not any(c.get('public') for _, c in labelled)
    chosen = chosen_acct(labelled, acct) if tabs else 'all'
    from .overview import watch_list
    watch = watch_list(labelled)
    body = ''.join(f'<div class="acctbox" data-box="{acct_key(lb)}">'
                   + (face(i, lb, c, view, scripted=not static, watch=watch) if not table
                      else face(i, lb, c, view)) + '</div>'
                   for i, (lb, c) in enumerate(labelled)
                   if chosen in ('all', acct_key(lb)))
    if tabs and len(labelled) > 1:
        body = acct_tabs(labelled, chosen, watch, query, '/table' if table else '/') + body
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
        if not table:                            # D96: the bots, and what was picked beside them
            from .detail import empty_pane
            body = f'<div class="split"><div class="bots">{body}</div>{pane or empty_pane()}</div>'
        body = f'<div class="page">{nav_panel(table, view, chosen)}<main>{body}</main></div>'
        chrome = KEEP_JS
    vp = '' if static else VIEWPORT
    return f"""<!doctype html><meta charset="utf-8">{vp}
<title>grid-gremlin</title><style>{CSS}</style>{'' if static else THEME_JS}
{head}{hero_strip(labelled, tabs)}{f'<p class="neg">{notice}</p>' if notice and not static else ''}{body}
{chrome}
<p class="dim">this page renders the engine's own readout contract — it
cannot disagree with the terminal. It holds no keys; venue writes are the
engine's alone.</p>"""
