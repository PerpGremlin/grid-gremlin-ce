"""D161: the panel's shape for a retail trader — back to the overview at
once, a short side column with its view switches, new bot as a chooser,
no market readings, leverage on every card, and the bots' names."""
import copy
import re
import urllib.request

from spec_panel import CONTRACT, _everything, _serve
from spec_setup import _call, _served_fleet


def _nav(page):
    return page.split('<nav class="side">', 1)[1].split('</nav>', 1)[0]


def _get(base, path, cookie='gg=tok123'):
    req = urllib.request.Request(base + path, headers={'Cookie': cookie})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, r.read().decode()


# --- U139: back to the overview at once ----------------------------------------

def esc_problems(js):
    """What NAV_JS's Escape would get wrong. [] when none: it waits while a
    dialog is open or the cursor is in a field, and goes the way the name
    and "overview" go (the first data-home link)."""
    out = []
    if "e.key!=='Escape'" not in js:
        out.append('not on Escape')
    if "document.querySelector('dialog[open]')" not in js:
        out.append('fires while a dialog is open')
    if '(INPUT|TEXTAREA|SELECT)' not in js or 'isContentEditable' not in js:
        out.append('fires while typing in a field')
    if "document.querySelector('a[data-home]')" not in js or 'h.click()' not in js:
        out.append('not the overview link')
    return out


def spec_U139_the_name_and_overview_go_back_to_the_overview_keeping_the_arrangement():
    """The owner (2026-11-01): one click back to the default overview. The
    column's first entry is "overview" and the grid-gremlin name above it
    is a link to the same place: each drops a right-half pick (?show=,
    ?bot=) and keeps the arrangement; on the bots' page each swaps in place
    (data-pick). Escape does the same when no dialog is open and the cursor
    is in no field (driven once in headless Chrome: Esc in the chooser
    closed it and stayed; Esc in a form's box stayed; Esc elsewhere opened
    the overview). Sabotage: an Escape that ignores dialogs or fields is
    named."""
    from panel.nav import nav_panel, side_nav
    from panel.reference import KEEP_JS, NAV_JS
    nav = nav_panel(False, 'pairs')
    pages = nav.split('<h3>pages</h3>', 1)[1]
    assert nav.startswith('<nav class="side"><a href="/?view=pairs" data-pick class="ggname" data-home>grid-gremlin</a>')
    assert pages.startswith('<a href="/?view=pairs" data-home data-pick>overview</a>')
    assert 'show=' not in nav.split('class="ggname"')[0] and nav.count('data-home') == 2
    table = nav_panel(True, 'side')
    assert '<a href="/?view=side" data-home>overview</a>' in table            # the table goes to the cards
    assert side_nav().count('<a href="/" data-home>overview</a>') == 1 and 'class="ggname" data-home>grid-gremlin' in side_nav()
    assert NAV_JS in KEEP_JS and esc_problems(NAV_JS) == []
    for cut in ("document.querySelector('dialog[open]')", '(INPUT|TEXTAREA|SELECT)'):
        assert esc_problems(NAV_JS.replace(cut, 'false')), cut
    srv, base = _serve(CONTRACT)
    try:
        _, page = _get(base, '/?view=pairs&show=results')
        assert '<a href="/?view=pairs" data-home data-pick>overview</a>' in page
    finally:
        srv.shutdown()


# --- U140: a short side column ------------------------------------------------------

OLD_ROUTES = ('/', '/table', '/control', '/setup', '/setup?adv=grid', '/setup?adv=martingale',
              '/setup?kind=grid', '/setup?kind=dca', '/trade', '/rehearse', '/results', '/carry',
              '/key', '/new', '/?show=setup', '/?show=trade', '/?show=rehearse', '/?show=results',
              '/?show=carry', '/?show=control', '/?show=setup&kind=dca', '/?view=side', '/export')


def column_entries(nav):
    """The column's entries, in order: each link, choice or button outside
    the new-bot dialog (the arrange choice counted once)."""
    top = nav.split('<dialog', 1)[0]
    top = re.sub(r'<form\b[^>]*class="arrange".*?</form>', '<arrange>', top, flags=re.S)
    return re.findall(r'<a\b[^>]*>(.*?)</a>|<(arrange)>|<button\b[^>]*>(.*?)</button>', top)


def spec_U140_the_column_is_short_and_every_old_address_still_answers():
    """The owner: too many side-column buttons; use toggles. About 23
    entries become: the name, overview, new bot, control, results (the
    snapshot export inside it), key; then one view block — cards or table,
    arrange, accounts, size in, leverage — and theme. The other pages wear
    the same list (side_nav). New trade, carry, rehearse and export leave
    the column; every address they had still answers."""
    from panel.nav import nav_panel, side_nav
    words = [a or b or c for a, b, c in column_entries(nav_panel(False, 'all'))]
    assert words == ['grid-gremlin', 'overview', 'new bot', 'control', 'results', 'key',
                     'layout: cards', 'arrange', 'accounts: full', 'size in: all', 'leverage: now', 'theme'], words
    other = [a or b or c for a, b, c in column_entries(_nav(side_nav() + '</nav>'))]
    assert other == ['grid-gremlin', 'overview', 'new bot', 'control', 'results', 'key', '&larr; back',
                     'the bots as a table', 'arrange', 'accounts: full', 'size in: all', 'leverage: now',
                     'theme'], other
    for nav in (nav_panel(False, 'all'), nav_panel(True, 'all'), side_nav()):
        top = nav.split('<dialog', 1)[0]
        for gone in ('/trade', '/carry', '/rehearse', '/export', 'show=trade', 'show=carry', 'show=rehearse'):
            assert gone not in top, gone
    base, d, close = _served_fleet()
    try:
        for path in OLD_ROUTES:
            code, page = _get(base, path, cookie='gg=tok')
            assert code == 200, path
        _, results = _get(base, '/results', cookie='gg=tok')
        assert '<a href="/export">export snapshot</a>' in results.split('<main>', 1)[1]
    finally:
        close()


# --- U141: the view switches, one each ------------------------------------------------

def spec_U141_each_view_switch_is_one_control_naming_what_is_on():
    """Cards/table one switch; arrange one choice that goes on change (a go
    button without script); accounts full/folded, size in (all → coins →
    value → cost) and leverage (now / if all filled) one button each,
    naming what is on, as theme does — over the same ggFold, ggSize and
    ggLev the page already had (driven once in headless Chrome: four size
    presses came back to all, one more said coins and set only-coin; the
    leverage and accounts buttons flipped and folded)."""
    from panel.nav import view_block
    from panel.reference import NAV_JS
    cards = view_block(False, 'side', '/')
    assert '<a href="/table?view=side" class="tog" title="show the bots as a table">layout: cards</a>' in cards
    assert '<form method="get" action="/" class="arrange">' in cards and '<select name="view" data-go>' in cards
    assert '<option value="side" selected>longs / shorts</option>' in cards
    assert '<noscript><button class="quiet">go</button></noscript>' in cards
    assert cards.count('data-tog=') == 3
    table = view_block(True, 'side', '/table')
    assert 'layout: table' in table and 'action="/table"' in table and 'data-tog="acct"' not in table
    assert "STEP=['all','coin','value','cost']" in NAV_JS
    assert "ggSize(STEP[(STEP.indexOf(size())+1)%STEP.length])" in NAV_JS
    assert "ggLev(lev()==='now'?'filled':'now')" in NAV_JS and "ggFold(fold()==='open'?'folded':'open','acct')" in NAV_JS
    assert "s.matches('select[data-go]')&&s.form)s.form.submit()" in NAV_JS


# --- U142: new bot is a chooser -------------------------------------------------------

def chooser_problems(dialog):
    """What the new-bot chooser lacks: each of the five kinds, a plain line
    for each, a way to close. [] when none."""
    from panel.nav import NEW_KINDS
    out = []
    for _, words, page, half, line in NEW_KINDS:
        if f'>{words}</a> <span class="dim">{line}</span>' not in dialog:
            out.append(f'{words} missing')
    if 'data-cancel' not in dialog:
        out.append('no cancel')
    return out


def spec_U142_new_bot_opens_a_chooser_straight_to_each_kinds_creator():
    """The owner: "new bot" opens a pop-up; pick the kind, then straight to
    that bot's creator. Grid, DCA, the carry bot as "Portfolio Bot", a
    single trade and a rehearsal, one plain line each. On the bots' page a
    choice opens in the right half; elsewhere it is the page. Without
    script "new bot" is /new, the same five as links. Grid and DCA open the
    quick setup with that kind's presets alone. Sabotage: a chooser that
    lost a kind is named."""
    from panel.nav import NEW_KINDS, nav_panel, new_dialog, new_page, side_nav
    from panel.reference import NAV_JS
    assert [w for _, w, _, _, _ in NEW_KINDS] == ['Grid', 'DCA', 'Portfolio Bot', 'Single trade',
                                                   'Rehearse a grid first']
    half, page = new_dialog(True), new_dialog(False)
    assert chooser_problems(half) == [] and chooser_problems(page) == []
    assert '<a data-pick href="/?show=setup&amp;kind=grid">Grid</a>' in half
    assert '<a href="/setup?adv=carry">Portfolio Bot</a>' in page
    assert half in nav_panel(False, 'all') and page in side_nav() and new_dialog(False) in nav_panel(True, 'all')
    assert '<a href="/new" data-new>new bot</a>' in nav_panel(False, 'all')
    assert chooser_problems(half.replace('>DCA</a>', '>dca</a>')) == ['DCA missing']
    assert chooser_problems(half.replace(' data-cancel', '')) == ['no cancel']
    assert all(f'href="{p}"' in new_page() for _, _, p, _, _ in NEW_KINDS)
    assert "d.showModal()" in NAV_JS and "c.closest('a[data-new]')" in NAV_JS
    base, d, close = _served_fleet()
    try:
        grid = _call(base, '/setup?kind=grid')
        assert 'set up a grid bot' in grid and 'value="sideways" checked' in grid
        assert 'value="dca_long"' not in grid and 'href="/setup?adv=grid"' in grid and 'adv=martingale' not in grid
        dca = _call(base, '/setup?kind=dca')
        assert 'value="dca_long" checked' in dca and 'value="sideways"' not in dca
        assert '/setup?adv=martingale' in dca and 'adv=carry' not in dca.split('<main>', 1)[1].split('<dialog')[0]
        assert 'value="sideways" checked' in _call(base, '/setup')            # the plain door, unchanged
        assert 'set up a DCA bot' in _call(base, '/?show=setup&kind=dca')        # in the half
        nopage = _call(base, '/new')
        assert '<h1>new bot' in nopage and nopage.count('<ul class="kinds">') >= 2
    finally:
        close()


# --- U143: no market readings in the panel -----------------------------------------------

def market_problems(page):
    """Any market reading the panel draws (D161 took them out). [] when none."""
    out = []
    for word, why in (('the markets</h3>', 'the overview\'s markets'), ('class="ov moods"', 'the moods table'),
                      ('ADX', 'a regime line'), ('fear &amp; greed', 'fear and greed'),
                      ('>market ranging', 'a card\'s market line')):
        if word in page:
            out.append(why)
    return out


def spec_U143_the_panel_draws_no_market_reading_and_the_engine_still_reads_it():
    """The owner: remove "the markets" from the panel; indicators belong to
    the site; the panel is the bots and their trades. The overview has no
    markets section and a card no regime line; a thin book stays as a
    warning about the bot. The engine's own reading is untouched: the
    readout still carries it and the tilt fleet's regime gate still reads
    ggdata.market. Sabotage: a moods table put back is named."""
    import inspect
    from gridgremlin import portfolio_bot, report
    from panel.overview import overview_pane
    import panel.overview as ov
    c = copy.deepcopy(CONTRACT)
    c['market'] = {'spoADAUSDTl': {'line': 'ranging · ADX 18 · ATR 1.2%/4h', 'thin': True,
                                   'regime': 'ranging', 'age_s': 30}}
    pane = overview_pane([('demo', c)])
    page = _everything(c)
    assert market_problems(pane) == [] and market_problems(page) == [] and not hasattr(ov, 'moods_html')
    assert 'order book thin for this size' in pane and 'order book thin for this size' in page
    assert market_problems(pane + '<h3>the markets</h3><table class="ov moods">') == [
        "the overview's markets", 'the moods table']
    assert "'market': _market_for(key_of, venue_of, now_ms)" in inspect.getsource(report.main)
    assert 'from ggdata.market import latest' in inspect.getsource(portfolio_bot)
    srv, base = _serve(c)
    try:
        _, live = _get(base, '/')
        assert market_problems(live) == [] and 'the markets' not in live
    finally:
        srv.shutdown()


# --- U144: leverage on every card ---------------------------------------------------------

def spec_U144_every_card_says_its_leverage_set_and_in_use():
    """The owner: cards show the bot's leverage — set (the row's, else the
    exchange's) and in use (the position at the mark over the bot's own
    money); an inverse book in its $1 contracts; a spot bot 1x set unless
    it borrows; a carry bot its spot's and, when hedged, its perpetuals'.
    Display only. Sabotage: in use counted from the most it may put in the
    market, not what it holds, says 10x for a bot holding 1x."""
    from panel.card import leverage_line, portfolio_leverage
    lin = leverage_line({'leverage': 10.0, 'capital': 1000.0, 'market_type': 'linear',
                         'notional': 10000.0}, None, 0.01, 100000.0)
    assert 'set <b>10x</b> · in use <b>1x</b>' in lin
    assert 'in use <b>0.5x</b>' in leverage_line({'leverage': 3.0, 'capital': 1000.0}, None, -500.0, 100.0,
                                                  inverse=True)
    assert 'set <b>1x</b>' in leverage_line({'market_type': 'spot', 'capital': 100.0}, None, 1.0, 50.0)
    assert 'set <b>2.5x</b> · in use <b>1.25x</b>' in leverage_line(
        {'market_type': 'spot', 'spot_borrow': True, 'spot_leverage': 2.5, 'capital': 100.0}, None, 2.5, 50.0)
    assert 'set <b>5x</b> · in use <b>—</b>' in leverage_line({}, {'leverage': 5.0}, 1.0, None)
    wrong = leverage_line({'leverage': 10.0, 'capital': 1000.0, 'market_type': 'linear'}, None,
                          10000.0 / 100000.0, 100000.0)
    assert 'in use <b>10x</b>' in wrong                                   # what the sabotage would say for 0.01
    assert wrong != lin
    view = {'leverage': 1.8, 'stack_value': 1800.0, 'cash': -800.0,
            'legs': [{'kind': 'hedge', 'size': 0.01, 'mark': 100000.0, 'leverage': 3.0, 'inverse': False},
                     {'kind': 'hedge', 'size': 800.0, 'mark': 2000.0, 'leverage': 3.0, 'inverse': True},
                     {'kind': 'hedge', 'size': 0.0, 'closed': True}]}
    p = portfolio_leverage({'spot_leverage': 2.0, 'hedges': {'BTC': {}}}, view)
    assert 'spot set <b>2x</b> · in use <b>1.8x</b> · perps set <b>3x</b> · in use <b>1.8x</b>' in p
    assert 'perps' not in portfolio_leverage({'spot_leverage': 1.0}, {'leverage': 1.0})   # unhedged
    page = _everything(CONTRACT)
    assert page.count('class="dim lev2"') >= len(CONTRACT['bots'])           # every card


# --- U145: the names, as the card and the box say them ---------------------------------------

def spec_U145_the_card_and_the_confirm_say_one_name_for_each_market():
    """The owner's examples: BTCUSDT Futures Grid, BTCUSD Inverse Futures
    Grid, BTCUSDC Futures DCA, ETHUSDT Margined Spot DCA, ETHUSDT Spot DCA;
    a trade spells its futures type; a carry bot is "<name> Portfolio Bot".
    The card says the name with its side as a tag; a list with no tag says
    the side in words; the box takes the name with its side or the short
    form."""
    from panel.card import _plain_name
    from panel.html_bits import accepts, plain_name
    rows = [({'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long'}, 'BTCUSDT Futures Grid'),
            ({'market_type': 'inverse', 'symbol': 'BTCUSD', 'side': 'short'}, 'BTCUSD Inverse Futures Grid'),
            ({'market_type': 'linear', 'symbol': 'BTCUSDC', 'side': 'long', 'strategy': 'martingale'},
             'BTCUSDC Futures DCA'),
            ({'market_type': 'spot', 'symbol': 'ETHUSDT', 'side': 'long', 'strategy': 'martingale',
              'spot_borrow': True}, 'ETHUSDT Margined Spot DCA'),
            ({'market_type': 'spot', 'symbol': 'ETHUSDT', 'side': 'long', 'strategy': 'martingale'},
             'ETHUSDT Spot DCA'),
            ({'market_type': 'linear', 'symbol': 'SOLUSDT', 'side': 'short', 'trade': True},
             'SOLUSDT Perpetual Futures Trade'),
            ({'strategy': 'portfolio', 'name': 'basket'}, 'basket Portfolio Bot')]
    for row, said in rows:
        assert plain_name(row) == said, (row, said)
    assert accepts('spoETHUSDTl', dict(rows[3][0], venue='bybit')) == [
        'spoethusdtl', 'ethusdt margined spot dca long', 'ethusdt dca long']
    c = copy.deepcopy(CONTRACT)
    c.setdefault('terms', {})['spoADAUSDTl'] = {'market_type': 'spot', 'spot_borrow': True, 'capital': 100.0}
    assert _plain_name('spoADAUSDTl', c, None) == 'ADAUSDT Margined Spot Grid'
    assert _plain_name('spoADAUSDTl', c, None, side=True) == 'ADAUSDT Margined Spot Grid long'
    page = _everything(c)
    assert '<span class="side long">LONG</span> <b><a class="bname" data-pick' in page
    assert 'ADAUSDT Margined Spot Grid</a></b>' in page


def spec_U183_theme_sits_at_the_foot_of_the_column():
    """The column runs the screen's height with theme last, pushed to its foot,
    at desktop width only (driven in headless Chrome at both widths). SABOTAGE:
    without the auto margin it follows the view block again; a link after it
    leaves the foot."""
    from panel.css import CSS
    from panel.nav import nav_panel
    wide = CSS.split('@media(min-width:60.01em){nav.side{', 1)[1]
    assert wide.startswith('display:flex;flex-direction:column;height:calc(100vh - var(--hero) - 2*var(--gap))}')
    assert 'nav.side>button.theme{margin-top:auto;align-self:flex-start}' in wide
    nav = nav_panel(False, 'pairs')
    after = nav.split('data-theme>theme</button>', 1)[1]
    assert '<a ' not in after.split('<dialog', 1)[0] and '<form' not in after.split('<dialog', 1)[0]
