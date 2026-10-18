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
    assert pane.index('liquidation') < pane.index('<td>entry</td>')            # newest first
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
                assert mark in half and 'data-pick href="/">close</a>' in half, name
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
