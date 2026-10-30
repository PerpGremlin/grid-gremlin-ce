# Specs for SPEC U78 — one bot's fills, each with what it realised (D96):
# the panel's right half when a bot is picked.

import json
import tempfile
from pathlib import Path

from gridgremlin.fill_list import fill_list
from gridgremlin.report import kept_books

DAY = 86_400_000
FLEET = {'bots': [{'venue': 'bybit', 'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long'}]}
B = 'linBTCUSDTl'


def _kf(t, eid, side='buy', price=100.0, qty=1.0, fee=0.1, link=f'{B}-1-a', **kw):
    return dict({'venue': 'bybit', 'market_type': 'linear', 'symbol': 'BTCUSDT', 'exec_id': eid,
                 'time_ms': t, 'side': side, 'price': price, 'qty': qty, 'fee': fee, 'link_id': link}, **kw)


FILLS = [_kf(DAY, 'a'), _kf(DAY + 1, 'b', qty=2.0, price=94.0),
         _kf(DAY + 2, 'c', side='sell', price=110.0, qty=1.5),
         _kf(DAY + 3, 'd', side='sell', price=90.0, qty=1.5, link='',
             venue_closed=True, venue_kind='liquidation')]


def spec_U78_each_fill_with_what_it_realised_summing_to_the_kept_history():
    """Every counted fill, oldest first, with the profit it realised by
    average cost and its fee; the running net after fees; a fill the venue
    made itself carries the venue's label. The realised column sums to the
    kept history the card shows — the same fills, the same walk."""
    got = fill_list({'fills': FILLS}, FLEET, B, held=0.0)
    assert got['whole'] and [r['time_ms'] for r in got['rows']] == [DAY, DAY + 1, DAY + 2, DAY + 3]
    r = got['rows']
    assert r[0]['entry'] and r[0]['realized'] == 0.0 and not r[2]['entry']
    avg = (100.0 + 2 * 94.0) / 3                                            # 96
    assert abs(r[2]['realized'] - (110.0 - avg) * 1.5) < 1e-9               # +21
    assert abs(r[3]['realized'] - (90.0 - avg) * 1.5) < 1e-9 and r[3]['kind'] == 'liquidation'
    assert abs(r[3]['net'] - (sum(x['realized'] for x in r) - 0.4)) < 1e-9
    with tempfile.TemporaryDirectory() as d:
        Path(d, 'demo.json').write_text(json.dumps({'version': 1, 'collected': {'bybit:linear:BTCUSDT': 5 * DAY},
                                                    'fills': FILLS}))
        books, _ = kept_books('fleet.demo.json', [], {('linear', 'BTCUSDT'): 'bybit'},
                              {B: ('linear', 'BTCUSDT')}, 0, set(), {B: 'buy'},
                              {('linear', 'BTCUSDT', 'sell'): B}, {}, set(), {B: 0.0}, root=d)
    card = books[B]
    assert abs(sum(x['realized'] for x in r) - card['realized']) < 1e-9
    assert abs(got['realized'] - card['realized']) < 1e-9 and abs(got['fees'] - card['fees']) < 1e-9


def spec_U78_a_fresh_start_opens_with_its_balance_and_no_start_is_said():
    """A fresh anchor's holding is the first row ('opening', no fee); a
    bot with no whole start lists its fills with realised unknown — never a
    figure against a position bought before the record."""
    kept = {'fills': FILLS[2:3], 'anchors': {B: {'kind': 'fresh', 'time_ms': DAY + 2 - 1,
                                                 'qty': 1.5, 'price': 100.0}}}
    got = fill_list(kept, FLEET, B)
    assert got['whole'] and got['rows'][0]['kind'] == 'opening' and got['rows'][0]['fee'] == 0.0
    assert abs(got['rows'][1]['realized'] - 15.0) < 1e-9
    blind = fill_list({'fills': FILLS[2:3]}, FLEET, B, held=None)
    assert not blind['whole'] and blind['realized'] is None and blind['rows'][0]['realized'] is None
    assert fill_list({'fills': FILLS}, FLEET, 'linETHUSDTl') is None              # not this fleet's


def spec_U78_the_front_pages_right_half_is_what_was_picked():
    """D96: the bots on the left; a bot's name opens it on the right by an
    address (`/?fleet=N&bot=ID`), so the page's refresh keeps it live and a
    link works without script; nothing picked, a line saying how; the
    table keeps its width. The half lists the fills newest first."""
    from panel.detail import detail_pane
    from panel.html_bits import pick_link
    from panel.render import render
    assert pick_link(1, 'lin/BTC', 'x') == '<a class="bname" data-pick href="/?fleet=1&amp;bot=lin%2FBTC">x</a>'
    page = render([])
    assert '<div class="split">' in page and 'Pick a bot by its name' in page
    assert '<aside class="pane">' not in render([], table=True)
    contract = {'bots': {B: None}, 'terms': {B: {'quote': 'USDT'}}}
    pane = detail_pane(0, 'demo', B, contract, fill_list({'fills': FILLS}, FLEET, B, held=0.0))
    assert pane.index('liquidation') < pane.index('</span> entry</td>')        # newest first
    assert '4 fills since its record began' in pane and '<b class="on">fills</b>' in pane
    assert 'data-pick href="/?fleet=0&amp;bot=linBTCUSDTl&amp;show=numbers">numbers</a>' in pane
    assert 'X<script>' not in detail_pane(0, 'X<script>', B, contract, None)   # names escaped
    assert '<aside class="pane">' in render([], pane=pane) and pane in render([], pane=pane)


def spec_U78_a_pick_on_the_live_server_reads_the_fleet_as_the_readout_does():
    """The real server: `/?fleet=0&bot=ID` draws the right half from the
    fleet file read as the readout reads it (defaults filled — a row with
    no venue named is Bybit's) and the kept ledger beside it; an unknown
    bot is the empty half. Found on the box: a raw read lacked the venue."""
    import urllib.request
    from spec_panel import _serve
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / 'configs').mkdir()
        (Path(d) / 'logs' / 'fills').mkdir(parents=True)
        fleet = Path(d) / 'configs' / 'fleet.demo.json'
        (Path(d) / 'configs' / 'watchdog.demo.json').write_text(json.dumps({'positions': {B: {'max': 0.5}}}))
        fleet.write_text(json.dumps({'watchdog': str(Path(d) / 'configs' / 'watchdog.demo.json'),
                                     'bots': [{'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
                                               'capital': 1000, 'leverage': 5, 'lower': 80000,
                                               'upper': 90000, 'rungs': 11}]}))
        (Path(d) / 'logs' / 'fills' / 'demo.json').write_text(json.dumps({'version': 1, 'collected': {},
                                                                          'fills': FILLS}))
        contract = {'window_hours': 6.0, 'generated_ms': 0, 'unowned': {},
                    'watchdog': {'belief': {'bots': {B: {'position': 0.0}}}},
                    'bots': {B: {'fills': 4, 'realized': 0.0, 'fees': 0.0, 'bought': 0.0, 'sold': 0.0,
                                 'position': 0.0, 'avg_cost': 0.0, 'unreal_at_mark': 0.0, 'truncated': False,
                                 'mark': 100.0, 'side': 'long', 'strategy': 'grid', 'inverse': False}}}
        srv, base = _serve(contract)
        try:
            srv.RequestHandlerClass.fleets = (str(fleet),)

            def get(path):
                req = urllib.request.Request(base + path, headers={'Cookie': 'gg=tok123'})
                return urllib.request.urlopen(req).read().decode()
            page = get(f'/?fleet=0&bot={B}')
            assert '4 fills since its record began' in page and 'liquidation' in page
            assert 'data-pick href="/?fleet=0&amp;bot=linBTCUSDTl"' in page        # the card's name picks
            assert 'Pick a bot by its name' in get('/?fleet=0&bot=nobody')
            # U78b: the numbers tab draws the numbers page's body in the half
            num = get(f'/?fleet=0&bot={B}&show=numbers')
            assert '<b class="on">numbers</b>' in num and 'as the exchange shows it' in num
            assert 'class="cards one"' in num and '4 fills since' not in num
            assert '&larr; fleet' not in num                                     # the half, not the page
            assert 'as the exchange shows it' in get(f'/position?fleet=0&bot={B}')   # the page still stands
            # U78c: the edit door in the half — the same form, posting where it always did
            door = get(f'/?fleet=0&bot={B}&show=edit')
            assert '<b class="on">edit</b>' in door and '<form method="post" action="/setup">' in door
            assert 'value="80000"' in door and '<script nonce="' in door.split('<aside class="pane">')[1]
            assert door.count('<form method="post" action="/setup">') == 1            # the half's only
            assert '<form method="post" action="/setup">' in get(f'/edit?fleet=0&bot={B}')
            # U78d: the side panel's pages in the half — each the page's own body
            for name, mark in (('results', 'results since the first kept fill'),
                               ('setup', 'action="/setup"'), ('trade', '<form'),
                               ('rehearse', 'action="/rehearse"'), ('control', 'control')):
                half = get(f'/?show={name}').split('<aside class="pane">', 1)[1]
                assert mark in half and 'data-pick href="/">back</a>' in half, name
            assert 'Pick a bot by its name' in get('/?show=nonsense')                 # not a page: the empty half
            assert f'data-pick href="/?show=results">results</a>' in get('/')         # the menu opens the half
            assert 'results since the first kept fill' in get('/results')            # the page still stands
        finally:
            srv.shutdown()


def spec_D96_the_market_pages_stay_gone():
    """D96 step 2: the market is the site's. The markets half and its tabs
    (U67, U72, and U70 before them), a coin's page (U71) with its heatmap
    and liquidations (U74), and the hidden model's working (K11) are gone
    from the panel — no module, no link, and their old addresses land on
    the front page. The trading server no longer pulls the collected data
    (no unit template, no reader). The hourly reading the bots trade on,
    and the carry page, stay."""
    import importlib.util
    import urllib.request
    from spec_panel import CONTRACT, _serve
    from panel.nav import page_links, side_nav
    for gone in ('panel.markets', 'panel.asset', 'ggdata.collected'):
        assert importlib.util.find_spec(gone) is None, gone
    root = Path(__file__).resolve().parents[1]
    assert not list((root / 'ops' / 'systemd').glob('collect-pull*'))
    for nav in (side_nav(), page_links(), page_links(table=True)):            # both menus
        assert '/asset' not in nav and '/calm-wild' not in nav and ('/carry' in nav or 'show=carry' in nav)
    assert importlib.util.find_spec('ggdata.market') is not None                # the bots' reading stays
    srv, base = _serve(CONTRACT)
    try:
        for path in ('/asset?coin=BTC', '/calm-wild?coin=BTC'):
            page = urllib.request.urlopen(urllib.request.Request(base + path, headers={'Cookie': 'gg=tok123'})).read().decode()
            assert '<title>grid-gremlin</title>' in page and 'Pick a bot by its name' in page, path
    finally:
        srv.shutdown()


def spec_U109_the_right_halfs_tables_fit_the_half():
    """The owner: "make the tiles and data that isnt cards fit the half of
    the screen it is in". Latest trades ran past its box (price and size
    behind a sideways scroll) and a bot's fills lost their totals at 1100
    wide: four columns and six now, two lines a row, the fills' text
    scaled to the pane; float dust reads +0, not +1.455e-11."""
    import re
    from panel.css import CSS
    from panel.detail import _signed, detail_pane
    from panel.overview import trades_html
    contract = {'bots': {B: None}, 'terms': {B: {'quote': 'USDT'}}}
    tails = {0: [{'link_id': f'{B}-1', 'time_ms': DAY, 'side': 'buy', 'price': 94.0, 'qty': 2.0}]}
    trades = trades_html(tails, [('Bybit demo subaccount 1', contract)])
    assert len(re.findall(r'<th>', trades)) == 4, trades
    assert '<br><span class="dim">Bybit demo subaccount 1</span>' in trades
    assert 'buy</span> entry' in trades and '2<br><span class="dim">@ 94' in trades
    pane = detail_pane(0, 'demo', B, contract, fill_list({'fills': FILLS}, FLEET, B, held=0.0))
    head = pane[pane.index('<table class="fills bot">'):]
    head = head[:head.index('</tr>')]
    assert head.count('<th>') == 6, head
    assert '<br>' in pane[pane.index('<td>', pane.index('fills bot')):][:40]   # date over time
    assert '+1.455e-11' not in _signed(1.455e-11) and '+0' in _signed(1.455e-11)
    assert '.pane{container-type:inline-size}' in CSS and 'cqi' in CSS


def spec_R18c_a_bot_removed_from_its_fleet_ends_its_record_and_a_new_one_starts_clean():
    """The owner (2026-10-23): a hand-built BTC grid read the soak bot's
    fills and realised — retired and cleared the day before under the same
    name. A row taken out of its fleet ends its bot's record
    (`cut`: the remove, the clear, the orphans' clear, or by hand); the
    fills stay kept, the anchor goes, and a new bot on that coin and side
    counts from its own first fill — the list, the card and the collector's
    new anchor alike."""
    from gridgremlin.kept_fills import cut, settle_anchors
    old = [_kf(DAY, 'o1', price=100.0), _kf(DAY + 5, 'o2', side='sell', price=200.0)]   # +100, flat
    new = [_kf(3 * DAY, 'n1', price=150.0, link=f'{B}-9-a')]
    with tempfile.TemporaryDirectory() as d:
        p = Path(d, 'demo.json')
        p.write_text(json.dumps({'version': 1, 'collected': {'bybit:linear:BTCUSDT': 4 * DAY},
                                 'fills': old + new, 'anchors': {B: {'kind': 'clean', 'time_ms': DAY}}}))
        before = fill_list(json.loads(p.read_text()), FLEET, B, held=1.0)
        assert len(before['rows']) == 3 and abs(before['realized'] - 100.0) < 1e-9   # heir to the old bot
        assert cut('fleet.demo.json', [B], 2 * DAY, root=d) == p
        kept = json.loads(p.read_text())
        assert kept['cuts'] == {B: 2 * DAY} and B not in kept['anchors'] and len(kept['fills']) == 3
        got = fill_list(kept, FLEET, B, held=1.0)
        assert got['whole'] and [r['time_ms'] for r in got['rows']] == [3 * DAY] and got['realized'] == 0.0
        books, _ = kept_books('fleet.demo.json', [], {('linear', 'BTCUSDT'): 'bybit'},
                              {B: ('linear', 'BTCUSDT')}, 0, set(), {B: 'buy'},
                              {('linear', 'BTCUSDT', 'sell'): B}, {}, set(), {B: 1.0}, root=d)
        assert books[B]['fills'] == 1 and books[B]['realized'] == 0.0
        settled = settle_anchors(FLEET, kept, 4 * DAY, {B: 1.0}, lambda c: 150.0)
        assert settled['anchors'][B] == {'kind': 'clean', 'time_ms': 3 * DAY}
        # an anchor older than the cut is not the new bot's, even if a writer kept it
        stale = dict(kept, anchors={B: {'kind': 'clean', 'time_ms': DAY}})
        assert len(fill_list(stale, FLEET, B, held=1.0)['rows']) == 1


def spec_U110_the_right_half_scrolls_on_its_own_and_the_refresh_keeps_its_place():
    """The owner (2026-10-23): the carry bot's numbers could not be
    scrolled — the page's refresh redraws the half every few seconds, which
    put it back at its top, and a wheel at its end ran on into the left.
    The refresh keeps each half's scroll (a pick still opens at its top),
    and the half keeps its wheel to itself."""
    from panel.css import CSS
    from panel.reference import KEEP_JS
    assert 'swap(location.href,1)' in KEEP_JS and 'function swap(url,keep)' in KEEP_JS
    assert "if(keep)['.pane','nav.side']" in KEEP_JS and 'e.scrollTop=at[q]' in KEEP_JS
    assert 'swap(u.href)' in KEEP_JS                                        # a pick: no keep, its top
    i = CSS.index('.pane{position:sticky')
    pane = CSS[i:CSS.index('}', i)]
    assert 'overscroll-behavior:contain' in pane and 'overflow:auto' in pane


# --- U113: a grid's fills say each trip, not the average ---------------------

GRID = {'lower': 90.0, 'upper': 110.0, 'rungs': 21, 'spacing_type': 'linear'}      # rung j at 90 + j


def _grid(side):
    sym = 'BTCUSDT' if side == 'long' else 'ETHUSDT'
    bot = f"lin{sym}{side[0]}"
    fleet = {'bots': [dict(GRID, venue='bybit', market_type='linear', symbol=sym, side=side)]}
    return bot, sym, fleet


def _gf(bot, sym, t, side, rung, price, qty=1.0, fee=0.01, **kw):
    return dict({'venue': 'bybit', 'market_type': 'linear', 'symbol': sym, 'exec_id': f'{bot}{t}',
                 'time_ms': DAY + t, 'side': side, 'price': price, 'qty': qty, 'fee': fee,
                 'link_id': f'{bot}-{rung}-a{t}'}, **kw)


def _ladder(side):
    """The owner's case (2026-10-30): bought down three rungs, sold one up
    — or a short's mirror. Four entries at 0.01 fee, one exit at 0.02."""
    bot, sym, fleet = _grid(side)
    e, x = ('buy', 'sell') if side == 'long' else ('sell', 'buy')
    step = -1 if side == 'long' else 1
    fills = [_gf(bot, sym, i, e, 10 + step * i, 100.0 + step * i) for i in range(4)]
    fills.append(_gf(bot, sym, 4, x, 10 + step * 2, 100.0 + step * 2, fee=0.02))
    kept = {'fills': fills, 'anchors': {bot: {'kind': 'clean', 'time_ms': DAY - 1}}}
    return bot, fleet, kept


def _made(pane):
    """The newest row's "made" cell (the exit's)."""
    row = pane[pane.index('<tr><td>', pane.index('fills bot')):]
    return row[:row.index('</tr>')].split('<td')[5]


def spec_U113_a_grid_exit_shows_its_trip_not_the_average():
    """A long grid that bought down three rungs and sold one rung up made a
    rung's gap on that trip, though the exchange's average-cost realised
    reads a loss: its "made" is the gap less both legs' fees (the entry
    fill's own fee, the exit's), the entry it was matched to under it; the
    entries show nothing made."""
    from panel.detail import detail_pane
    bot, fleet, kept = _ladder('long')
    got = fill_list(kept, fleet, bot, held=3.0)
    ex = got['rows'][-1]
    assert abs(ex['realized'] - (98.0 - 98.5)) < 1e-9                       # the exchange's: a loss
    assert ex['own'] == 97.0 and abs(ex['trip'] - (1.0 - 0.02 - 0.01)) < 1e-9   # the trip: a gain
    assert got['per_trip'] and got['trips'] == 1 and got['unmatched'] == 0
    assert all(r.get('own') is None and r['trip_net'] == 0.0 for r in got['rows'][:4])
    contract = {'bots': {bot: None}, 'terms': {bot: {'quote': 'USDT'}}}
    pane = detail_pane(0, 'demo', bot, contract, got)
    assert '+0.97<br><span class="dim">vs 97</span>' in _made(pane), _made(pane)
    assert 'grid profit <b class="pos">+0.97</b> over 1 trip,' in pane
    assert "average-cost realised -0.50" in pane and 'open position' in pane
    head = pane[pane.index('<table class="fills bot">'):]
    assert head[:head.index('</tr>')].count('<th>') == 6                     # U109's fit


def spec_U113_a_short_grid_mirrors_it():
    """A short that sold up three rungs and bought one back: the same gap,
    the same fees, the same loss by average cost."""
    bot, fleet, kept = _ladder('short')
    got = fill_list(kept, fleet, bot, held=3.0)
    ex = got['rows'][-1]
    assert abs(ex['realized'] - (-0.5)) < 1e-9 and ex['own'] == 103.0
    assert abs(ex['trip'] - 0.97) < 1e-9 and abs(got['trip_total'] - 0.97) < 1e-9


def spec_U113_the_two_figures_reconcile_through_the_open_average():
    """R12's identity, asserted: the trips' gross less the average-cost
    realised is what the open lots cost beyond the book's average, times
    the position — the loss the exchange printed sits in the remainder."""
    for side in ('long', 'short'):
        bot, fleet, kept = _ladder(side)
        got = fill_list(kept, fleet, bot, held=3.0)
        sign = 1.0 if side == 'long' else -1.0
        lots = [100.0, 99.0, 98.0] if side == 'long' else [100.0, 101.0, 102.0]   # the lots still held
        book_avg = sum(lots + [97.0 if side == 'long' else 103.0]) / 4
        shift = (sum(lots) / 3 - book_avg) * 3 * sign
        assert abs(got['trip_gross'] - got['realized'] - shift) < 1e-9, side
        assert abs(got['trip_total'] - (got['trip_gross'] - 0.03)) < 1e-9   # both legs' fees


def spec_U113_an_exit_with_no_entry_to_match_says_so():
    """A venue's close carries no link, so no rung: no entry it closed is
    known, and its "made" is "—" with a title, never a guess; the summary
    counts it out."""
    from panel.detail import detail_pane
    bot, fleet, kept = _ladder('long')
    kept['fills'].append(_gf(bot, 'BTCUSDT', 5, 'sell', 0, 95.0, qty=3.0, link_id='',
                             venue_closed=True, venue_kind='liquidation'))
    got = fill_list(kept, fleet, bot, held=0.0)
    last = got['rows'][-1]
    assert last['own'] is None and last['trip'] is None and got['unmatched'] == 1
    assert abs(got['trip_total'] - 0.97) < 1e-9                             # left out, not guessed
    pane = detail_pane(0, 'demo', bot, {'bots': {bot: None}, 'terms': {bot: {'quote': 'USDT'}}}, got)
    assert 'title="no entry this exit can be matched to' in _made(pane) and '>—</td>' in _made(pane)
    assert '1 exit with no entry to match' in pane


def spec_U113_a_martingale_keeps_the_average():
    """A DCA's exit closes the round's average — that is its trip — so it
    keeps the realised column as before (no lattice, no per-trip)."""
    got = fill_list({'fills': FILLS}, FLEET, B, held=0.0)
    assert not got['per_trip'] and 'own' not in got['rows'][2]


def spec_U113_sabotage_made_falling_back_to_realised_is_caught():
    """Were "made" the average-cost figure again, the owner's case reads a
    loss and the check above fails."""
    import panel.detail as d
    bot, fleet, kept = _ladder('long')
    got = fill_list(kept, fleet, bot, held=3.0)
    contract = {'bots': {bot: None}, 'terms': {bot: {'quote': 'USDT'}}}
    real = d._trip
    d._trip = lambda r: d._signed(r['realized'])                            # the old column
    try:
        made = _made(d.detail_pane(0, 'demo', bot, contract, got))
    finally:
        d._trip = real
    assert '+0.97' not in made and '-0.5' in made
