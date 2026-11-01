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


# D161 (2026-11-01): what "new bot" offers — each kind straight to its own
# creator, one plain line each. (key, words, its page, its half, the line)
NEW_KINDS = (
    ('grid', 'Grid', '/setup?kind=grid', '/?show=setup&kind=grid',
     'a ladder of buy and sell orders around the price: buys the dips, sells the rises'),
    ('dca', 'DCA', '/setup?kind=dca', '/?show=setup&kind=dca',
     'buys more as the price falls, sells the lot on a bounce'),
    ('carry', 'Portfolio Bot', '/setup?adv=carry', '/?show=setup&adv=carry',
     'coins on spot, each hedged on its perpetual: collects the funding'),
    ('trade', 'Single trade', '/trade', '/?show=trade',
     'one long or short with its own take profit and stop'),
    ('rehearse', 'Rehearse a grid first', '/rehearse', '/?show=rehearse',
     'runs a grid on past prices: nothing is placed'),
)


# the pages the column links (D161): the rest are reached from these
HALF = (('control', 'control'), ('results', 'results'))


def _choices(half):
    return ''.join(
        f'<li><a{" data-pick" if half else ""} href="{(hl if half else page).replace("&", "&amp;")}">'
        f'{words}</a> <span class="dim">{line}</span></li>'
        for _, words, page, hl, line in NEW_KINDS)


def new_page():
    """D161: "new bot" without script — the same five choices as links."""
    return ('<h1>new bot <span class="dim">— pick what kind</span></h1>'
            f'<ul class="kinds">{_choices(False)}</ul>')


def new_dialog(half):
    """D161 (the owner: "new bot" opens a pop-up — pick the kind, then
    straight to its creator): the chooser, in D159's style. Escape or
    cancel closes it; a choice opens that kind's creator (in the right half
    on the bots' page). Never opens without script: "new bot" is then a
    link to the same list as a page."""
    return ('<dialog class="ggnew" aria-label="new bot">'
            '<p class="what">New bot: what kind?</p>'
            f'<ul class="kinds">{_choices(half)}</ul>'
            '<p class="dlgbtn"><button type="button" class="quiet" data-cancel>cancel</button></p>'
            '</dialog>')


def page_links(table=False, view='all'):
    """U60, D161: the column's pages — overview first, then new bot,
    control, results (the snapshot export is inside it), the key. On the
    bots' page (cards) a page opens in the right half."""
    q = '' if view == 'all' else f'?view={view}'
    half = not table
    pick = ' data-pick' if half else ''
    return (f'<a href="/{q}" data-home{pick}>overview</a>'
            '<a href="/new" data-new>new bot</a>'
            + ''.join(f'<a{pick} href="{"/?show=" + k if half else "/" + k}">{w}</a>' for k, w in HALF)
            + '<a href="/key">key</a>')


def view_block(table=False, view='all', here='/'):
    """D161: the view switches, one control each, every one naming what is
    on now (as theme does): cards or table; arrange (a choice that goes on
    change, a go button without script); accounts full or folded (cards
    only); size in, stepping all → coins → value → cost; leverage now or
    as if every order filled. table=None: a page that is not the bots'."""
    q = '' if view == 'all' else f'?view={view}'
    layout = ('<a href="/table" class="tog">the bots as a table</a>' if table is None else
              f'<a href="/table{q}" class="tog" title="show the bots as a table">layout: cards</a>'
              if not table else
              f'<a href="/{q}" class="tog" title="show the bots as cards">layout: table</a>')
    opts = ''.join(f'<option value="{k}"{" selected" if k == view else ""}>{w}</option>'
                   for k, w in VIEWS)
    arrange = (f'<form method="get" action="{here}" class="arrange"><label>arrange '
               f'<select name="view" data-go>{opts}</select></label>'
               '<noscript><button class="quiet">go</button></noscript></form>')
    # U59: every account's cards behind its heading and its box
    accounts = ('' if table else
                '<button type="button" class="quiet tog" data-tog="acct">accounts: full</button>')
    # U44: what a holding is said in; R19: the leverage now, or if all filled
    return (f'<h3>view</h3>{layout}{arrange}{accounts}'
            '<button type="button" class="quiet tog" data-tog="size">size in: all</button>'
            '<button type="button" class="quiet tog" data-tog="lev">leverage: now</button>')


TITLE = '<a href="/" class="ggname" data-home>grid-gremlin</a>'


def side_nav():
    """U60, D161: the column every page outside the bots' page wears — the
    same short list as the bots' page: the name and overview back to the
    bots, new bot, control, results, the key, a way back, the one warning a
    form needs, the view, the theme. Opens the page grid; PAGE_END closes
    it."""
    return ('<div class="page"><nav class="side">' + TITLE + '<h3>pages</h3>'
            + page_links(table=True)
            + '<a href="#" data-back>&larr; back</a>'
            '<span class="dim">leaving a form saves nothing</span>'
            + view_block(table=None, here='/')
            + '<button class="quiet theme" data-theme>theme</button>'
            + new_dialog(False) + '</nav><main>')


PAGE_END = '</main></div>'


def nav_panel(table, view):
    """U51, D161: the bots' page's column, pinned while the page scrolls:
    the name and overview (each back to the overview, the arrangement
    kept), new bot, control, results, key; then the view block and the
    theme. The live page only; the export has no actions to offer."""
    here = '/table' if table else '/'
    title = TITLE.replace('href="/"', f'href="/{"" if view == "all" else "?view=" + view}"'
                          + ('' if table else ' data-pick'))
    return (f'<nav class="side">{title}<h3>pages</h3>{page_links(table, view)}'
            f'{view_block(table, view, here)}'
            '<button class="quiet theme" data-theme>theme</button>'
            f'{new_dialog(not table)}</nav>')
