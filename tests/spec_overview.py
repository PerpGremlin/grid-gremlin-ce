"""U85: the front page's right half with nothing picked — the whole book."""
import json
import tempfile
import urllib.request
from pathlib import Path

L, S, I, P = 'linBTCUSDTl', 'linETHUSDTs', 'invBTCUSDl', 'pfocarry'


def _contract():
    return {'generated_ms': 0, 'window_hours': 24.0,
            'bots': {L: {'position': 2.0, 'mark': 100.0}, S: {'position': -3.0, 'mark': 10.0},
                     I: {'position': 500.0, 'mark': 100.0, 'inverse': True}, P: None},
            'terms': {P: {'strategy': 'portfolio'}},
            'ranges': {L: {'lower': 50.0, 'upper': 90.0, 'rungs': 5}},
            'market': {L: {'line': 'ranging · ADX 19', 'thin': False},
                       S: {'line': 'trending down · ADX 30', 'thin': True}},
            'watchdog': {'belief': {'bots': {
                L: {'alive': True, 'offset': 2, 'margin': {'liq': 95.0}},
                S: {'alive': False}, I: {'alive': True}, P: {'alive': True}}}}}


def spec_U85_the_overview_says_what_needs_a_look():
    """Every account's warnings at once, the card's own thresholds: a
    stopped bot, liquidation within 10%, a thin book, a price judged
    against its SLID window (G17: home 50–90 slid two 10-wide rungs is
    70–110, so 100 is inside). A quiet book says so. Sabotage: judging
    the home window flags BTC 'above its range'."""
    from panel.overview import overview_pane, watch_list
    said = {botid: words for _, botid, _, words in watch_list([('demo', _contract())])}
    assert 'liquidates 5.0% away' in said[L] and 'range' not in said[L]
    assert 'stopped' in said[S] and 'thin market' in said[S]
    assert I not in said and P not in said
    quiet = {'generated_ms': 0, 'bots': {L: {'position': 0.0, 'mark': 70.0}},
             'ranges': {L: {'lower': 50.0, 'upper': 90.0, 'rungs': 5}},
             'watchdog': {'belief': {'bots': {L: {'alive': True}}}}}
    pane = overview_pane([('demo', quiet)])
    assert 'Nothing needs you now.' in pane and '1 bots: 1 running · 0 holding' in pane


def spec_U85_long_and_short_by_coin_leave_the_hedged_rows_apart():
    """Linear at the mark, inverse in its $1 contracts, a short negative;
    a portfolio row is named, not counted as a long. Sabotage: valuing the
    inverse book at the mark makes BTC 50,200."""
    from panel.overview import exposure, exposure_html
    book, hedged = exposure([('demo', _contract())])
    assert book == {'BTC': [700.0, 0.0], 'ETH': [0.0, -30.0]} and hedged == ['demo']
    html = exposure_html([('demo', _contract())])
    assert 'Not counted: the hedged portfolio rows (demo)' in html and '+700.00' in html


def spec_U85_latest_trades_are_the_bots_own_newest_first():
    """Fills are owned by their link's prefix and its dash (an id that
    begins another never takes its fills); another hand's fill is not
    shown; newest first, twenty at most. Sabotage: dropping the dash gives
    the longer id's fill to the shorter."""
    from panel.overview import TRADES_SHOWN, recent_trades
    c = _contract()
    fills = ([{'time_ms': t, 'link_id': f'{L}-{t}-1', 'side': 'buy', 'price': 1, 'qty': 1}
              for t in range(30)]
             + [{'time_ms': 99, 'link_id': '', 'side': 'sell', 'price': 1, 'qty': 1}])
    rows = recent_trades({0: fills}, [('demo', c)])
    assert len(rows) == TRADES_SHOWN and rows[0][0] == 29 and all(r[3] == L for r in rows)
    c['bots']['linBTCUSDTlx'] = None
    (row,) = recent_trades({0: [{'time_ms': 1, 'link_id': 'linBTCUSDTlx-1-1'}]}, [('demo', c)])
    assert row[3] == 'linBTCUSDTlx'


def spec_U85_the_front_page_opens_on_the_overview_and_reads_the_ledger_once():
    """The live page's empty half is the overview, with the latest kept
    fills; the ledger is read again only when its file changes (the box's
    CPU). A picked bot and the table are unchanged."""
    from spec_panel import CONTRACT, _serve
    from panel.server import Handler
    srv, base = _serve(CONTRACT)
    try:
        H = srv.RequestHandlerClass
        with tempfile.TemporaryDirectory() as d:
            fleet = Path(d) / 'configs' / 'fleet.demo.json'
            fleet.parent.mkdir()
            fleet.write_text('{"bots": [{"x": 1}]}')
            (Path(d) / 'logs' / 'fills').mkdir(parents=True)
            ledger = Path(d) / 'logs' / 'fills' / 'demo.json'
            ledger.write_text(json.dumps({'fills': [{'time_ms': 5, 'link_id': 'a-1'}]}))
            H.fleets = (str(fleet),)
            Handler._tails.clear()
            get = (lambda p: urllib.request.urlopen(urllib.request.Request(
                base + p, headers={'Cookie': 'gg=tok123'})).read().decode())
            page = get('/')
            assert '<h2>overview</h2>' in page and 'Pick a bot by its name' in page
            assert '<h2>overview</h2>' not in get('/table')
            (got,) = Handler._tails.values()
            Handler._tails[str(ledger)] = (got[0], [{'time_ms': 7, 'link_id': 'cached'}])
            h = H.__new__(H)
            assert h._kept_tails() == {0: [{'time_ms': 7, 'link_id': 'cached'}]}    # unchanged file: not re-read
            ledger.write_text(json.dumps({'fills': [{'time_ms': 9, 'link_id': 'b-1'}]}))
            import os
            os.utime(ledger, (got[0] + 5, got[0] + 5))
            assert h._kept_tails() == {0: [{'time_ms': 9, 'link_id': 'b-1'}]}
    finally:
        srv.shutdown()
        Handler._tails.clear()
