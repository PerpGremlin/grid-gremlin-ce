"""The panel's renderer: the cards, the table, the strip and the side panel,
all from the readout's contract (§4: one renderer, two artefacts)."""
from gridgremlin.report import card_total
import html
import time
from .css import CSS
from .reference import KEEP_JS
from .card import card, pnl_parts, unpriced
from .drawings import equity_boxes
from .fleet_bits import sweep_note
from .html_bits import REFRESH_S, _num_cls, esc
from .nav import VIEWS, grouped, nav_panel
from .results import agent_box
from .strip_view import exchange_free, exchange_leverage, exchange_mmr, exchange_since_first, hero_strip, portfolio_total, tier_badge, venue_money
from .table import section


def cards_section(idx, label, contract, view='all', scripted=True):
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
    cards = '</div><div class="cards">'.join(
        (f'<div class="grp">{esc(title)}</div>' if title else '')
        + ''.join(card(idx, botid, b, contract, belief)
                  for botid, b in rows)
        for title, rows in grouped(contract, view))
    # U45: the exchange's money in a box of its own, under its name
    # U59: one link beside the count folds or opens this account's cards
    # alone; its word says which it will do next
    # U86: each exchange in a box of its own, edge to edge with the site's look
    return (f"<section class=\"fbox\"><h1 id=\"fleet{idx}\">{esc(label)} {tier_badge(contract)} — {len(contract['bots'])} bots "
            + (f'<a href="#" data-foldin="{idx}" class="tier">fold cards</a> '
               if scripted else '')               # an export has no script to run it
            # U87: the heading is the name; how fresh it is, a quiet line under it
            + f'<span class="meta">{sweep_note(contract)} <span class="dim">(read {age}s ago; '
            f'refreshes every {REFRESH_S}s)</span></span></h1>'
            + (f'<div class="refusal"><b>readout unavailable</b> — the engine\'s '
               f'readout of this fleet failed; the panel tries again on a later refresh.'
               f'<br>{html.escape(contract["unavailable"])}</div>'
               if contract.get('unavailable') else '') +
            f'<div class="pnl {_num_cls(total)}"><span class="dim">this '
            'exchange</span> <span class="big '
            f'{_num_cls(total)}">{total:+,.2f}</span> {venue_money(contract)} '
            '<span class="dim">after fees, each bot counted as its card says — most since it was '
            'last flat, so not the same window as the equity line below, which runs from the '
            'first snapshot with top-ups in</span>'                                  # U98
            f'<div class="parts">'
            f'{pnl_parts(net, sum(opened) if opened else None, funding)}'
            + (f' · portfolio rows <b class="{_num_cls(pfo)}">{pfo:+,.2f}</b>' if pfo else '')
            + f'</div>{left}{exchange_since_first(contract)}{exchange_leverage(contract)}'
            f'{exchange_mmr(contract)}{exchange_free(contract)}</div>'            # U66, U100
            f'{equity_boxes(contract, idx)}'                                          # U63
            f'{agent_box(contract)}'                                             # J5
            # U59: the account folds to its heading and its box; the side
            # panel folds or opens every account at once
            f'<details class="acct" data-k="acct:{idx}" open><summary>'
            f"{len(contract['bots'])} bots</summary>"
            f'<div class="cards">{cards}</div></details></section>')


# the panel on a phone (audit 2026-10-16); the showcase drops it, the site adds its own
VIEWPORT = '<meta name="viewport" content="width=device-width,initial-scale=1">'


def render(labelled, static=None, table=False, view='all', pane=None, notice=''):
    """One renderer, two artefacts (§4): the live page, or — with
    static=timestamp-text — a self-contained export: no refresh, no
    actions, provenance stamped. The numbers can never diverge because
    there is only one code path to diverge from. Two faces of the same
    contract: cards (the default) and the dense table (/table). `notice`:
    one line above the cards on the live page (F31: config files edited
    here and not in git yet), never in an export. `pane`: the right half's
    HTML — what the owner picked (D96, U78); nothing picked, how to pick."""
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
        if not table:                            # D96: the bots, and what was picked beside them
            from .detail import empty_pane
            body = f'<div class="split"><div class="bots">{body}</div>{pane or empty_pane()}</div>'
        body = f'<div class="page">{nav_panel(table, view)}<main>{body}</main></div>'
        chrome = KEEP_JS
    vp = '' if static else VIEWPORT
    return f"""<!doctype html><meta charset="utf-8">{vp}
<title>grid-gremlin</title><style>{CSS}</style>
{head}{hero_strip(labelled)}{f'<p class="neg">{notice}</p>' if notice and not static else ''}{body}
{chrome}
<p class="dim">this page renders the engine's own readout contract — it
cannot disagree with the terminal. It holds no keys; venue writes are the
engine's alone.</p>"""
