"""D86 show mode (SPEC U77): the showcase says only what the private side
allowed, by allowlist; it serves GET alone, links nowhere, and never shows
a fleet's own figures."""
import json
import threading
import urllib.error
import urllib.request

PLANT = 987654.321                                   # a figure that must never appear


def _contract(tier='demo'):
    book = {'realized': 30.0, 'fees': 5.0, 'funding': -1.0, 'unreal_at_mark': 6.0, 'strategy': 'grid',
            'trips': 12, 'first_ms': 0, 'position': PLANT, 'avg_cost': PLANT, 'secret_new_field': PLANT}
    dca = dict(book, strategy='martingale', rounds=3, trips=None)
    return {'generated_ms': 3 * 86_400_000, 'window_hours': 24.0,
            'account': {'bybit': {'equity': PLANT, 'collateral': PLANT, 'tier': tier}},
            'bots': {'linBTCUSDTl': book, 'linETHUSDTs': dca, 'linSOLUSDTl': None},
            'terms': {'linBTCUSDTl': {'capital': 1000.0, 'leverage': 5, 'quote': 'USDT',
                                      'market_type': 'linear', 'strategy': 'grid', 'notional': PLANT},
                      'linETHUSDTs': {'capital': 500.0, 'leverage': 3, 'quote': 'USDT',
                                      'market_type': 'linear', 'strategy': 'martingale'},
                      'linSOLUSDTl': {'capital': 250.0, 'market_type': 'linear', 'strategy': 'grid'}},
            'since_first': {}, 'watchdog': {'belief': {'tiers': {'bybit': tier}}}}


def spec_U77_the_show_file_is_an_allowlist():
    from gridgremlin.show import build
    data = build(['configs/fleet.x.json'], read=lambda f: _contract(), now=1.0)
    text = json.dumps(data)
    assert str(PLANT) not in text and '987654' not in text and 'secret_new_field' not in text
    bots = data['accounts'][0]['bots']
    assert {tuple(sorted(b)) for b in bots} == {('coin', 'days', 'kind', 'market', 'return_pct',
                                                 'side', 'state', 'trips')}
    btc, eth, sol = bots
    assert btc['coin'] == 'BTC' and btc['return_pct'] == 3.0 and btc['days'] == 3.0 and btc['trips'] == 12
    assert eth['kind'] == 'DCA' and eth['side'] == 'short' and eth['trips'] == 3
    assert sol['state'] == 'not started' and sol['return_pct'] is None
    assert data['accounts'][0]['return_pct'] == 4.0                    # (30 + 30) / 1500
    assert data['accounts'][0]['network'] == 'paper (exchange demo)'
    # with --amounts the money and the leverage come, and still nothing unnamed
    full = build(['configs/fleet.x.json'], amounts=True, read=lambda f: _contract(), now=1.0)
    b0 = full['accounts'][0]['bots'][0]
    assert b0['capital'] == 1000.0 and b0['total'] == 30.0 and b0['leverage'] == 5
    assert str(PLANT) not in json.dumps(full)


def spec_U77_real_money_is_refused():
    from gridgremlin.show import build
    data = build(['configs/fleet.real.json'], read=lambda f: _contract('mainnet'), now=1.0)
    assert data['accounts'] == [] and 'mainnet' in data['refused'][0] and 'paper only' in data['refused'][0]


def spec_U77b_a_network_it_cannot_name_is_refused_too():
    """Fail closed (the review, 2026-10-11): no snapshot and a failed account
    read leave no tier — that fleet is not paper until it says so."""
    from gridgremlin.show import build
    c = _contract()
    c['account'] = {}
    c['watchdog'] = {'belief': {}}
    data = build(['configs/fleet.x.json'], read=lambda f: c, now=1.0)
    assert data['accounts'] == [] and 'unknown' in data['refused'][0]
    odd = _contract('staging')
    assert build(['configs/fleet.x.json'], read=lambda f: odd, now=1.0)['accounts'] == []


def spec_U77_the_market_table_is_an_allowlist_too():
    from showcase.page import page
    reading = {'t': 0, 'markets': {'bybit:linear:BTCUSDT': {
        'symbol': 'BTCUSDT', 'price': 80000.0, 'change_24h_pct': 1.2, 'regime': 'ranging',
        'funding_8h_pct': 0.01, 'long_pct': 61.0, 'oi_change_24h_pct': -2.0,
        'committed': PLANT, 'thin': True}},
        'hmm': {'BTC': {'two_states': True, 'state': 'calm'}}, 'fear_greed': {'score': 61, 'label': 'Greed'}}
    html = page(None, reading, now=600)
    assert '987,654' not in html and '987654' not in html and 'thin' not in html
    assert '80,000' in html and 'ranging' in html and 'calm' in html and 'fear &amp; greed 61' in html
    assert 'No bots to show yet' in html


def _serve(tmp):
    import http.server
    from showcase.server import Showcase
    from gridgremlin.show import build

    class S(Showcase):
        show_path = tmp / 'show.json'
        market_path = tmp / 'market.jsonl'
    S.show_path.write_text(json.dumps(build(['configs/fleet.x.json'], read=lambda f: _contract(), now=1.0)))
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), S)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f'http://127.0.0.1:{srv.server_port}'


def spec_U77_the_showcase_serves_get_alone_and_links_nowhere():
    import tempfile
    from pathlib import Path
    srv, base = _serve(Path(tempfile.mkdtemp()))
    try:
        with urllib.request.urlopen(base + '/') as r:
            html, headers = r.read().decode(), r.headers
        assert "default-src 'none'" in headers['Content-Security-Policy']
        assert headers['Referrer-Policy'] == 'no-referrer' and 'Set-Cookie' not in headers
        for word in ('<a ', 'href', '<form', '<script', '/srv', 'logs/', 'configs/', 'token'):
            assert word not in html, word
        assert 'Paper money' in html and 'not' in html and 'financial advice' in html
        assert '+3.00%' in html and 'BTC' in html
        with urllib.request.urlopen(base + '/show.json') as r:
            served = json.loads(r.read())
        assert served['accounts'][0]['bots'][0]['coin'] == 'BTC'
        assert set(served) == {'generated_ms', 'amounts', 'accounts'}      # never the refused list
        for method, path, code in (('POST', '/', 405), ('PUT', '/', 405), ('DELETE', '/', 405),
                                   ('GET', '/edit?fleet=0', 404), ('GET', '/control', 404),
                                   ('GET', '/../logs/show/show.json', 404)):
            try:
                urllib.request.urlopen(urllib.request.Request(base + path, method=method, data=b'' if method != 'GET' else None))
                raise AssertionError(f'{method} {path} answered')
            except urllib.error.HTTPError as e:
                assert e.code == code, (method, path, e.code)
    finally:
        srv.shutdown()


def spec_U77_state_and_the_portfolio_come_from_the_fleets_own_snapshot():
    from gridgremlin.show import build
    c = _contract()
    c['bots']['pfocarry'] = None
    c['terms']['pfocarry'] = {'capital': 2000.0, 'strategy': 'portfolio', 'market_type': 'spot'}
    c['watchdog']['belief']['bots'] = {'pfocarry': {'alive': True, 'portfolio': {'total': 50.0, 'stack': PLANT}},
                                       'linETHUSDTs': {'alive': False}}
    c['since_first']['linSOLUSDTl'] = dict(c['bots']['linBTCUSDTl'])      # history, no window book
    data = build(['configs/fleet.x.json'], read=lambda f: c, now=1.0)
    bots = {b['coin'] + b['side']: b for b in data['accounts'][0]['bots']}
    pfo = bots['baskethedged']
    assert pfo['state'] == 'running' and pfo['return_pct'] == 2.5 and pfo['kind'] == 'portfolio'
    assert bots['ETHshort']['state'] == 'stopped' and bots['SOLlong']['state'] == 'stopped'
    assert data['accounts'][0]['return_pct'] == round((30 + 30 + 50) / 3500 * 100, 2)
    assert str(PLANT) not in json.dumps(data)


def spec_U77_a_coin_shows_once_from_its_usdt_perpetual():
    from showcase.page import page
    reading = {'t': 0, 'markets': {
        'bybit:linear:BTCPERP': {'symbol': 'BTCPERP', 'price': 1.0, 'long_pct': None},
        'bybit:linear:BTCUSDT': {'symbol': 'BTCUSDT', 'price': 80000.0, 'long_pct': 61.0}}}
    html = page(None, reading, now=0)
    assert html.count('<tr><td>BTC</td>') == 1 and '80,000' in html and 'BTCPERP' not in html


def spec_U77b_a_malformed_file_still_serves_a_page_and_idle_sockets_are_bounded():
    import socket
    import tempfile
    import time
    from pathlib import Path
    import showcase.server as sv
    tmp = Path(tempfile.mkdtemp())
    srv, base = _serve(tmp)
    try:
        for bad in ('[1, 2]', '{"accounts": [{"name": 1}]}', '{"accounts": "x", "generated_ms": "y"}'):
            (tmp / 'show.json').write_text(bad)
            with urllib.request.urlopen(base + '/') as r:
                assert r.status == 200 and 'grid-gremlin' in r.read().decode()
    finally:
        srv.shutdown()
    assert sv.Showcase.timeout and sv.Showcase.timeout <= 30
    # a crowd of half-sent requests: beyond the cap each is closed on arrival
    saved = sv.MAX_CONNECTIONS
    sv.MAX_CONNECTIONS = 3
    try:
        b = sv.BoundedServer(('127.0.0.1', 0), sv.Showcase)
        import threading
        threading.Thread(target=b.serve_forever, daemon=True).start()
        idle = [socket.create_connection(('127.0.0.1', b.server_port)) for _ in range(3)]
        for s_ in idle:
            s_.sendall(b'GET / HTTP/1.1\r\n')                       # never finished
        time.sleep(0.2)
        extra = socket.create_connection(('127.0.0.1', b.server_port))
        extra.settimeout(2)
        extra.sendall(b'GET / HTTP/1.1\r\nHost: x\r\n\r\n')
        assert extra.recv(100) == b''                                     # closed, not served
        for s_ in idle + [extra]:
            s_.close()
        time.sleep(0.3)                                                   # the idle handlers see EOF and end
        b.shutdown()
        b.server_close()
    finally:
        sv.MAX_CONNECTIONS = saved
