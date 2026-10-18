"""Navigation: the page links, the side column, the fleet page's side panel, the views and groupings. Out of render.py (D91 step 3)."""
from .html_bits import coin_of


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


SIZE_VIEWS = (('all', 'all'), ('coin', 'coins'), ('value', 'value'),
              ('cost', 'cost'))


HALF = (('control', 'control'), ('setup', 'new bot'), ('trade', 'new trade'),
        ('rehearse', 'rehearse a grid'), ('results', 'results'), ('carry', 'carry'))


def page_links(table=False, view='all'):
    """U60: every page of the panel, as links — the side panel's first
    block on the fleet page, a bar across the top of every other page."""
    q = '' if view == 'all' else f'?view={view}'
    return ((f'<a href="/{q}">cards</a>' if table else f'<a href="/table{q}">table</a>')
            + (''.join(f'<a href="/{k}">{w}</a>' for k, w in HALF) if table else    # U78d: the half
               ''.join(f'<a data-pick href="/?show={k}">{w}</a>' for k, w in HALF))
            + '<a href="/export">export snapshot</a><a href="/key">key</a>')


def side_nav():
    """U60: the column every page outside the fleet page wears, the fleet
    page's own shape — the pages, a way back, the one warning a form
    needs, the theme. Opens the page grid; PAGE_END closes it."""
    return ('<div class="page"><nav class="side"><h3>pages</h3>'
            '<a href="/">back to your bots</a><a href="/table">table</a>'
            '<a href="/control">control</a><a href="/setup">new bot</a><a href="/trade">new trade</a>'
            '<a href="/rehearse">rehearse a grid</a><a href="/results">results</a><a href="/carry">carry</a>'
            '<a href="/export">export snapshot</a>'
            '<a href="/key">key</a><a href="#" data-back>&larr; back</a>'
            '<span class="dim">leaving a form saves nothing</span>'
            '<button class="quiet theme" data-theme>theme</button></nav><main>')


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
    # U58's switch for every card's lower half went with U68: a slim card
    # has nothing to fold; the numbers live on the position's page (U56)
    numbers = ('' if table else
               # U59: every account's cards behind its heading and its box
               '<h3>accounts</h3><a href="#" data-fold="open" data-cls="acct">full</a>'
               '<a href="#" data-fold="folded" data-cls="acct">folded</a>')
    # U44: what a holding is said in, as Bybit's preference
    size = ''.join(f'<a href="#" data-size="{k}">{w}</a>'
                   for k, w in SIZE_VIEWS)
    # R19: the account's leverage now, or as if every order filled
    lev = ('<a href="#" data-lev="now">now</a>'
           '<a href="#" data-lev="filled">if all filled</a>')
    return (f'<nav class="side"><h3>pages</h3>{pages}<h3>arrange</h3>{arrange}'
            f'{numbers}<h3>size in</h3>{size}<h3>leverage</h3>{lev}'
            '<button class="quiet theme" data-theme>theme</button></nav>')
