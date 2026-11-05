"""D163 — the left half fits the screen: account tabs, the account box's
header row with its details folded, the cards as a grid (U170–U176).
Layout only: nothing here places, cancels or pages. Made-up figures."""
import copy
import json
import re
import threading
import time
import urllib.request

BOOK = {'fills': 3, 'realized': 5.0, 'fees': 1.0, 'bought': 9.0, 'sold': 0.0, 'position': 9.0,
        'avg_cost': 0.2, 'unreal_at_mark': -0.5, 'truncated': False, 'mark': 0.2, 'side': 'long',
        'strategy': 'grid', 'inverse': False, 'funding': 0.0}


def _contract(bots=('linADAUSDTl',), mmr=0.05, free=600.0, liq=None):
    now = int(time.time() * 1000)
    belief = {b: {'alive': True, 'position': 9.0} for b in bots}
    if liq:
        belief[bots[0]]['margin'] = {'liq': liq}
    return {'generated_ms': now, 'window_hours': 24.0, 'unowned': {}, 'fee_floors': {},
            'ranges': {}, 'bots': {b: dict(BOOK) for b in bots},
            'terms': {b: {'capital': 100.0, 'leverage': 2, 'quote': 'USDT', 'market_type': 'linear',
                          'strategy': 'grid', 'venue': 'bybit', 'notional': 200.0} for b in bots},
            'account': {'bybit': {'tier': 'demo', 'equity': 1000.0, 'notional': 1300.0, 'collateral': 1000.0,
                                  'available': free, 'positions': [],
                                  'wallet': {'USDT': {'balance': 1000.0, 'usd': 1000.0}}}},
            'equity': {'24h': [[time.time() - 3600 * (9 - i), 1000.0 + i] for i in range(10)]},
            'watchdog': {'swept_s_ago': 5, 'belief': {'age_s': 2, 'mm_rate': mmr, 'equity': 1000.0,
                                                      'available': free, 'tiers': {'bybit': 'demo'},
                                                      'bots': belief}}}


def _three():
    return [('Bybit demo', _contract(('linADAUSDTl', 'linXRPUSDTs'), liq=0.195)),
            ('subaccount 2 · paper', _contract(('linETHUSDTl',))),
            ('HL testnet', _contract(('linSOLUSDTl',)))]


def _boxes(page):
    return re.findall(r'<div class="acctbox" data-box="([^"]+)">', page)


# --- U170: a tab per account, and "all" ------------------------------------

def spec_U170_a_tab_per_account_and_all_each_with_its_count_and_a_red_dot():
    from panel.render import render
    page = render(_three())
    tabs = page.split('<nav class="acctabs" aria-label="accounts">', 1)[1].split('</nav>', 1)[0]
    keys = re.findall(r'data-acct="([^"]+)"', tabs)
    assert keys == ['all', 'bybit-demo', 'subaccount-2-paper', 'hl-testnet']
    assert 'Bybit demo <span class="n">2</span>' in tabs and 'all <span class="n">4</span>' in tabs
    assert 'subaccount 2 · paper <span class="n">1</span>' in tabs
    dots = [k for k, part in zip(keys, tabs.split('<a ')[1:]) if 'class="dot"' in part]
    assert dots == ['all', 'bybit-demo']           # the liquidation 2.5% away, and "all" with it
    assert 'href="/?acct=all" data-acct="all" class="tab pick"' in tabs     # none chosen: all
    # a lone account has no tabs; an export and the public page never do
    assert '<nav class="acctabs"' not in render(_three()[:1])
    assert '<nav class="acctabs"' not in render(_three(), static='then')
    assert '<nav class="acctabs"' not in render([(lb, dict(c, public=True)) for lb, c in _three()])


def spec_U170_sabotage_without_the_needs_a_look_reading_no_tab_is_red():
    import panel.render as r
    real = r.needs_look
    r.needs_look = lambda idx, contract, watch: []          # sabotage
    try:
        page = r.render(_three())
    finally:
        r.needs_look = real
    assert 'class="dot"' not in page.split('<nav class="acctabs"', 1)[1].split('</nav>', 1)[0]


# --- U171: ?acct= filters on the server -------------------------------------

def spec_U171_acct_shows_that_account_alone_and_the_links_keep_it():
    from panel.render import render
    page = render(_three(), acct='subaccount-2-paper', query={'acct': 'subaccount-2-paper', 'view': 'side',
                                                              'bot': 'x', 'csrf': 'no'})
    assert _boxes(page) == ['subaccount-2-paper']
    assert 'id="fleet1"' in page and 'id="fleet0"' not in page        # the box keeps its own index
    assert 'data-acct="subaccount-2-paper" class="tab pick"' in page
    assert 'href="/?view=side&amp;bot=x&amp;acct=hl-testnet"' in page    # the view and the pick ride along
    assert 'csrf' not in page.split('acctabs', 1)[1].split('</nav>', 1)[0]
    assert '<input type="hidden" name="acct" value="subaccount-2-paper">' in page   # arrange keeps the tab
    assert _boxes(render(_three(), acct='all')) == ['bybit-demo', 'subaccount-2-paper', 'hl-testnet']
    assert len(_boxes(render(_three(), acct='nobody'))) == 3          # a name no account has: all
    assert len(_boxes(render(_three(), acct='hl-testnet', static='then'))) == 3   # an export: everything
    table = render(_three(), table=True, acct='hl-testnet')
    assert _boxes(table) == ['hl-testnet'] and 'href="/table?acct=all"' in table


def spec_U171_sabotage_a_chooser_that_ignores_the_address_shows_every_account():
    import panel.render as r
    real = r.chosen_acct
    r.chosen_acct = lambda labelled, acct: 'all'           # sabotage
    try:
        page = r.render(_three(), acct='hl-testnet')
    finally:
        r.chosen_acct = real
    assert _boxes(page) != ['hl-testnet']


# --- U172: the choice survives the swap --------------------------------------

def _serve(labelled, route_render=None):
    import http.server
    import tempfile
    from pathlib import Path
    from panel.server import Handler

    class H(Handler):
        def _labelled(self):
            return labelled

        def _kept_tails(self):
            return {}
    fp = Path(tempfile.mkdtemp()) / 'f.json'
    fp.write_text('{"bots": [{"x": 1}]}')
    H.token, H.fleets, H.labels = 'tok', (str(fp),) * len(labelled), tuple(lb for lb, _ in labelled)
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
    H.host_ok = f'127.0.0.1:{srv.server_port}'
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f'http://{H.host_ok}'


def _get(base, path):
    req = urllib.request.Request(base + path, headers={'Cookie': 'gg=tok'})
    return urllib.request.urlopen(req, timeout=10).read().decode()


def spec_U172_the_tab_rides_the_address_the_refresh_and_the_browser_tab():
    """The server reads `?acct=` on every answer, so the refresh — which
    fetches the page's own address — keeps the tab; the script keeps the
    choice per browser tab (gg-acct), carries it on every in-page pick,
    and gives it back to an address that names none."""
    from panel.reference import KEEP_JS
    srv, base = _serve(_three())
    try:
        assert _boxes(_get(base, '/?acct=hl-testnet')) == ['hl-testnet']
        assert _boxes(_get(base, '/?acct=hl-testnet&bot=linSOLUSDTl&fleet=2')) == ['hl-testnet']
        assert len(_boxes(_get(base, '/'))) == 3
        assert _boxes(_get(base, '/table?acct=bybit-demo')) == ['bybit-demo']
    finally:
        srv.shutdown()
    assert "swap(location.href,1)" in KEEP_JS                                # the refresh: the address as it is
    assert "S.setItem('gg-acct',k)" in KEEP_JS and "tu.searchParams.set('acct',k)" in KEEP_JS
    assert "if(here.get('acct')&&!u.searchParams.has('acct'))u.searchParams.set('acct',here.get('acct'))" in KEEP_JS
    assert "k=S.getItem('gg-acct')" in KEEP_JS and "b.hidden=b.dataset.box!==k" in KEEP_JS
    assert "history.replaceState(null,'',location.pathname+'?'+q.toString()" in KEEP_JS


def spec_U172_sabotage_a_route_that_drops_the_tab_serves_every_account():
    import panel.routes as routes
    real = routes.render
    routes.render = lambda *a, **k: real(*a, **dict(k, acct=None))      # sabotage
    srv, base = _serve(_three())
    try:
        assert len(_boxes(_get(base, '/?acct=hl-testnet'))) == 3
    finally:
        srv.shutdown()
        routes.render = real


# --- U173: the header row ----------------------------------------------------

def _changed():
    """An account with D162's changes on it (spec_account_change's world)."""
    from spec_account_change import _panel_contract
    return dict(_contract(), account_change=_panel_contract()['account_change'])


def spec_U173_the_box_header_holds_the_name_and_the_five_numbers():
    """The name and the network, Total P&L, equity, account leverage (now,
    or if all filled), available to trade, and the since switch — one row,
    before anything folded."""
    from panel.render import cards_section
    c = _changed()
    box = cards_section(0, 'Bybit demo', c)
    head = box.split('<div class="acchead">', 1)[1].split('<details', 1)[0]
    assert '<h1 id="fleet0">Bybit demo' in head and 'Demo Trading' in head
    assert 'Total P&amp;L</span> <span class="big' in head
    assert '<span class="dim">equity</span> <b>1,000.00</b> USDT' in head
    assert '<span class="dim">account leverage</span> <b class="lev-now">1.30x</b>' in head
    assert 'class="lev-filled">' in head
    assert '<span class="dim">available to trade</span> <b class="">600.00</b> USDT' in head
    assert 'data-tog="since"' in head and box.count('data-tog="since"') == 1   # one switch, in the header
    free = cards_section(0, 'x', _contract(free=100.0))
    assert '<b class="neg">100.00</b>' in free.split('<details', 1)[0]         # U100's red, kept


def spec_U173_sabotage_without_the_head_cells_the_numbers_are_folded_away():
    import panel.render as r
    real = r.head_cells
    r.head_cells = lambda contract: ''                     # sabotage
    try:
        box = r.cards_section(0, 'x', _contract())
    finally:
        r.head_cells = real
    assert 'available to trade' not in box.split('<details', 1)[0]


# --- U174: the details, folded and remembered ---------------------------------

def folded(box):
    """The details sit in one <details class="acctd"> with no `open`, kept
    by its data-k (V12), and nothing of them stands outside it."""
    m = re.search(r'<details class="acctd" data-k="acctd:\d+"( open)?>', box)
    if m is None or m.group(1):
        return False
    before, inside = box.split(m.group(0), 1)
    inside = inside.split('<details class="acct"', 1)[0]
    for part in ('acctlines', 'acctchg', 'class="eqrow eqsw"', 'account MMR', 'free to trade <b'):
        if part in before or part not in inside:
            return False
    return True


def spec_U174_balances_changes_equity_and_the_other_lines_are_folded_by_default():
    from panel.render import cards_section
    from panel.reference import KEEP_JS
    box = cards_section(0, 'Bybit demo', _changed())
    assert folded(box), box[:2000]
    assert "scope.querySelectorAll('details[data-k]')" in KEEP_JS            # remembered per browser tab
    assert '<details class="acct" data-k="acct:0" open>' in box               # the cards stay open


def spec_U174_sabotage_an_open_fold_or_a_line_left_outside_is_caught():
    from panel.render import cards_section
    box = cards_section(0, 'Bybit demo', _changed())
    assert not folded(box.replace('<details class="acctd" data-k="acctd:0">',
                                  '<details class="acctd" data-k="acctd:0" open>'))
    moved = re.search(r'<div class="parts acctlines">.*?</div></div>', box, re.S).group(0)
    assert not folded(box.replace(moved, '').replace('<details class="acctd"', moved + '<details class="acctd"'))


# --- U175: what needs a look is never folded ----------------------------------

def spec_U175_needs_a_look_stands_in_the_box_never_folded():
    from panel.render import cards_section
    box = cards_section(0, 'Bybit demo', _contract(('linADAUSDTl',), mmr=0.62, free=50.0, liq=0.195))
    shown = box.split('<details class="acctd"', 1)[0]
    assert '<ul class="watch look">' in shown
    assert 'liquidates 2.5% away' in shown and 'href="/?fleet=0&amp;bot=linADAUSDTl"' in shown
    assert 'account MMR 62.0%' in shown and 'free to trade only 5% of equity' in shown
    quiet = cards_section(0, 'x', _contract())
    assert 'watch look' not in quiet                           # nothing to say, nothing drawn


def spec_U175_sabotage_without_the_reading_the_box_says_nothing():
    import panel.render as r
    real = r.needs_look
    r.needs_look = lambda idx, contract, watch: []             # sabotage
    try:
        box = r.cards_section(0, 'x', _contract(mmr=0.62, liq=0.195))
    finally:
        r.needs_look = real
    assert 'liquidates' not in box.split('<details class="acctd"', 1)[0]


# --- U176: the cards fill the width; nothing scrolls sideways ------------------

def grid_rules(css):
    """The layout D163 asks for, as rules the stylesheet must hold."""
    need = ('.cards{grid-template-columns:repeat(auto-fill,minmax(min(18em,100%),1fr))',
            '.cards .card.pfo.slim{grid-column:auto',
            '.acctchg{overflow-x:auto',
            '@media(max-width:40em){.acctabs{flex-wrap:nowrap;overflow-x:auto',
            '.acchead{display:flex;flex-wrap:wrap')
    return [r for r in need if r not in css]


def spec_U176_the_cards_are_a_grid_as_many_a_row_as_fit():
    from panel.css import CSS
    from panel.render import render
    assert grid_rules(CSS) == []
    assert '.cards{display:grid' in CSS
    page = render(_three())
    assert page.count('<div class="cards">') == 3


def spec_U176_sabotage_a_stylesheet_without_the_grid_is_caught():
    from panel.css import CSS
    bad = CSS.replace('repeat(auto-fill,minmax(min(18em,100%),1fr))', 'minmax(0,1fr)')
    assert grid_rules(bad) != []


# --- U177: the strip folds into the tabs --------------------------------------

def _strip_world():
    """Three accounts with every strip figure lit: a stopped and a frozen
    bot, an unpriced and a not-whole book, a red MMR and free share, an old
    engine snapshot, a 24 h equity line."""
    a, b, c = (lb_c[1] for lb_c in _three())
    a['watchdog']['belief']['bots']['linXRPUSDTs']['alive'] = False
    a['watchdog']['belief']['age_s'] = 1800
    b['bots']['linETHUSDTl'] = dict(BOOK, unreal_at_mark=None)
    b['watchdog']['belief'].update(mm_rate=0.62, available=50.0)
    c['bots']['linSOLUSDTl'] = dict(BOOK, whole=False)
    c['watchdog']['belief']['bots']['linSOLUSDTl']['frozen_since'] = 1
    return [('Bybit demo', a), ('subaccount 2 · paper', b), ('HL testnet', c)]


def strip_moved(page, labelled):
    """What of the strip did not move into the tabs — [] when the page's
    pinned strip is the tab row alone (no per-account row above it) and
    each account's tab holds every figure its strip row would show: the
    network, the total with its unpriced and not-whole notes, stopped or
    frozen, the leverage line, the equity line, and the bot count."""
    import html as _h
    from panel.render import acct_key
    from panel.strip_view import STRIP_CELLS, strip_cells, tier_badge
    lost = []
    hero = page.split('<div class="hero', 1)[1].split('<div class="page">', 1)[0]
    if '<div class="fleet">' in hero:
        lost.append('a strip row above the tabs')
    if not hero.startswith(' tabbed"><nav class="acctabs"') or page.count('<nav class="acctabs"') != 1:
        lost.append('the tabs are not the strip')
    for lb, c in labelled:
        key = acct_key(lb)
        at = hero.find(f'data-acct="{key}"')
        tab = hero[at:hero.find('</a>', at)] if at >= 0 else ''
        cells = strip_cells(c)
        want = [cells[k] for k in STRIP_CELLS if k != 'bots' and cells[k] != '<span></span>']
        want += [re.sub(r'<a class="(tier[^"]*)" href="/trading" title="what this means">(.*?)</a>',
                        r'<span class="\1">\2</span>', tier_badge(c)),
                 f'{_h.escape(lb, quote=False)} <span class="n">{len(c["bots"])}</span>']
        lost += [f'{lb}: {w[:60]}' for w in want if w not in tab]
    return lost


def spec_U177_the_strip_draws_no_account_rows_each_tab_carries_its_figures():
    """The owner's complaint was scrolling and blank space; the strip's
    five rows stood above the tabs. With tabs, the tabs are the pinned
    strip: one row, each account's strip figures in its own tab, nothing
    lost — on the cards and on the table face alike."""
    from panel.render import render
    world = _strip_world()
    for page in (render(world), render(world, table=True), render(world, acct='hl-testnet')):
        assert strip_moved(page, world) == [], strip_moved(page, world)
    page = render(world)
    hero = page.split('<div class="hero tabbed">', 1)[1].split('<div class="page">', 1)[0]
    for said in ('1 stopped', '1 frozen', '+ 1 unpriced', '+ 1 not whole', 'MMR <b class="neg">62.0%</b>',
                 'free <b class="neg">5%</b>', 'engine read 30 min ago', 'class="spark"'):
        assert said in hero, said
    assert '<a ' not in hero.replace('<a href=', '', 4)           # no link inside a tab
    assert page.index('<div class="hero tabbed">') < page.index('<div class="page">')
    from panel.css import CSS
    assert '.hero.tabbed .acctabs{flex-wrap:nowrap;overflow-x:auto' in CSS   # one row; it scrolls, never the page


def spec_U177_the_public_page_the_export_and_a_lone_account_keep_the_strip_rows():
    """The public page (U153: no account lines, no tabs), an export and a
    lone account have no tabs: their strip is U50's rows, exactly as before."""
    from panel.render import render
    from panel.strip_view import hero_strip
    world = _strip_world()
    pub = [(lb, dict(c, public=True)) for lb, c in world]
    for page, rows in ((render(pub), hero_strip(pub)), (render(world, static='then'), hero_strip(world)),
                       (render(world[:1]), hero_strip(world[:1], True))):
        assert rows in page and '<nav class="acctabs"' not in page and '"hero tabbed"' not in page
        assert rows.count('<div class="fleet">') == page.count('<div class="fleet">') >= 1
    assert 'acctlines' not in render(pub)


def spec_U177_sabotage_a_tab_without_the_strip_figures_is_caught():
    import panel.render as r
    world = _strip_world()
    real = r.tab_figures
    r.tab_figures = lambda c: ''                                    # sabotage: the figures dropped
    try:
        bare = r.render(world)
    finally:
        r.tab_figures = real
    assert strip_moved(bare, world) != []
    page = r.render(world)
    assert strip_moved(page.replace('1 frozen', ''), world) != []        # one figure lost is caught
    from panel.strip_view import hero_strip
    rows = page.replace('<div class="hero tabbed">', hero_strip(world, True) + '<div class="hero tabbed">', 1)
    assert strip_moved(rows, world) != []                                # the rows back above the tabs


def spec_U192_the_strip_and_the_account_line_never_widen_the_page():
    # the seven-column strip needs about 1,076 px; between the phone layout and that it
    # scrolled the whole page (308 px at 768), and the account line 17 px at 390
    from panel.css import CSS
    assert '@media(min-width:40.01em) and (max-width:70em){.hero:not(.tabbed){overflow-x:auto}}' in CSS
    assert '@media(max-width:40em){.acchead .hc{white-space:normal}}' in CSS
    assert CSS.index('.acchead .hc{white-space:nowrap}') < CSS.index('@media(max-width:40em){.acchead .hc')

