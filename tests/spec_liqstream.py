"""Bybit's liquidation stream (D84), with a fake line."""
import json
import tempfile

from ggdata.liqstream import PING_S, URL, listen, parse


def spec_D84_bybits_liquidations_are_recorded_as_they_stream():
    """Bybit publishes its liquidations only as a stream and keeps none. The
    recorder subscribes for every coin, reads each message (Bybit's `S` is
    the position side: Buy is a long liquidated), writes it beside the
    collector's rows marked `venue: bybit`, pings every 18 s, and on a
    dropped line waits and reconnects — 1 s, doubling, capped at 60."""
    msg = json.dumps({'topic': 'allLiquidation.BTCUSDT', 'type': 'snapshot', 'ts': 1800000000000,
                      'data': [{'T': 1800000000000, 's': 'BTCUSDT', 'S': 'Buy', 'v': '0.5', 'p': '80000'},
                               {'T': 1800000000500, 's': 'BTCUSDT', 'S': 'Sell', 'v': '0.1', 'p': '81000'}]})
    rows = parse(msg)
    assert rows[0] == ('BTC', {'ts': 1800000000000, 'side': 'long', 'px': 80000.0, 'coins': 0.5,
                               'usd': 40000.0, 'venue': 'bybit'})
    assert rows[1][1]['side'] == 'short'
    assert parse('{"op":"pong"}') == [] and parse('not json') == []
    clock = {'t': 0.0}
    sent, sleeps, made = [], [], []

    class Line:
        def __init__(self, script):
            self.script = list(script)
        def send_text(self, t):
            sent.append(t)
        def recv_text(self, timeout=None):
            clock['t'] += 6
            if not self.script:
                raise OSError('dropped')
            return self.script.pop(0)
        def close(self):
            pass

    lines = [OSError('refused'), OSError('refused'), Line([msg, None, None, None, msg])]
    def connect(url):
        assert url == URL
        made.append(url)
        x = lines.pop(0) if lines else None
        if x is None:
            raise StopIteration
        if isinstance(x, Exception):
            raise x
        return x
    root = tempfile.mkdtemp()
    try:
        listen(['BTC', 'ETH'], connect, root=root, clock=lambda: clock['t'],
               sleep=lambda s: (sleeps.append(s), clock.__setitem__('t', clock['t'] + s)), log=lambda s: None)
    except StopIteration:
        pass
    assert sleeps[:2] == [1.0, 2.0]                                    # a growing pause
    assert json.loads(sent[0]) == {'op': 'subscribe', 'args': ['allLiquidation.BTCUSDT', 'allLiquidation.ETHUSDT']}
    assert '{"op":"ping"}' in sent                                     # the heartbeat
    from pathlib import Path
    files = list(Path(root).glob('BTC/liq-*.jsonl'))
    lines_out = [json.loads(l) for f in files for l in f.read_text().splitlines()]
    assert len(lines_out) == 4 and {r['venue'] for r in lines_out} == {'bybit'}
    assert PING_S == 18


def spec_K14b_coins_named_on_the_command_line_win():
    """The data server (D93) has no fleets and so no market reading: the
    collector and the stream take `--coins` when named, else the reading's
    coins, else BTC, ETH and SOL. An empty list is refused, not read as
    none."""
    from ggdata.market import coins_to_watch
    with tempfile.TemporaryDirectory() as d:
        path = f'{d}/market.jsonl'
        assert coins_to_watch([], path) == ['BTC', 'ETH', 'SOL']
        with open(path, 'w') as f:
            f.write(json.dumps({'hmm': {'XRP': {}, 'SUI': {}}}) + '\n')
        assert coins_to_watch([], path) == ['XRP', 'SUI']
        assert coins_to_watch(['--coins', 'btc, eth,xaut'], path) == ['BTC', 'ETH', 'XAUT']
        for bad in (['--coins'], ['--coins', ' , ']):
            try:
                coins_to_watch(bad, path)
                raise AssertionError(f'{bad} accepted')
            except SystemExit as e:
                assert '--coins' in str(e)


def spec_K15b_binances_liquidations_stream_beside_bybits():
    """Binance's futures liquidations (`!forceOrder@arr`, every symbol, on the
    current `/market/ws/` address) are a second line in the same process:
    kept for the coins watched and their USDT perpetual only, SELL a long
    liquidated, the filled coins at the average price, marked `venue:
    binance`. Nothing is sent to subscribe and no app ping (Binance pings;
    the client answers)."""
    from ggdata.liqstream import BINANCE_URL, parse_binance

    def msg(sym, side, z='0.5', ap='80000', q='0.5', p='79000'):
        return json.dumps({'e': 'forceOrder', 'E': 1800000000100,
                           'o': {'s': sym, 'S': side, 'q': q, 'p': p, 'ap': ap, 'z': z, 'X': 'FILLED',
                                 'T': 1800000000000}})
    watched = {'BTC', 'ETH'}
    assert parse_binance(msg('BTCUSDT', 'SELL'), watched) == [
        ('BTC', {'ts': 1800000000000, 'side': 'long', 'px': 80000.0, 'coins': 0.5, 'usd': 40000.0,
                 'venue': 'binance'})]
    assert parse_binance(msg('ETHUSDT', 'BUY'), watched)[0][1]['side'] == 'short'
    assert parse_binance(msg('BTCUSDT', 'SELL', z='0', ap='0'), watched)[0][1]['px'] == 79000.0   # unfilled: the order's own
    for other in ('SOLUSDT', 'BTCUSDC', 'BTCUSDT_261225'):                   # not watched, not the USDT perp
        assert parse_binance(msg(other, 'SELL'), watched) == []
    assert parse_binance('{"result":null,"id":1}', watched) == [] and parse_binance('nope', watched) == []
    assert BINANCE_URL == 'wss://fstream.binance.com/market/ws/!forceOrder@arr'

    sent, made = [], []

    class Line:
        def __init__(self):
            self.script = [msg('BTCUSDT', 'SELL'), None, msg('SOLUSDT', 'BUY'), msg('ETHUSDT', 'BUY')]
        def send_text(self, t):
            sent.append(t)
        def recv_text(self, timeout=None):
            if not self.script:
                raise StopIteration
            return self.script.pop(0)
        def close(self):
            pass

    def connect(url):
        made.append(url)
        return Line()
    root = tempfile.mkdtemp()
    try:
        listen(['BTC', 'ETH'], connect, root=root, log=lambda s: None, sleep=lambda s: None, venue='binance')
    except StopIteration:
        pass
    from pathlib import Path
    assert made == [BINANCE_URL] and sent == []                        # no subscribe, no app ping
    got = {f.parent.name: [json.loads(l) for l in f.read_text().splitlines()] for f in Path(root).glob('*/liq-*.jsonl')}
    assert set(got) == {'BTC', 'ETH'} and all(r['venue'] == 'binance' for rs in got.values() for r in rs)


def spec_D93_the_trading_server_pulls_the_collected_data_read_only():
    """The trading server reads what the data server collects by pulling it:
    the source is the data server, the destination its own logs/collect;
    the collector's own watermark stays behind; no agent forwarded; the key
    named, batch mode (never a prompt); every five minutes after the
    collector's run."""
    from pathlib import Path
    ops = Path(__file__).resolve().parents[1] / 'ops'
    svc = (ops / 'systemd' / 'collect-pull.service.template').read_text()
    line = next(ln for ln in svc.splitlines() if ln.startswith('ExecStart='))
    assert line.startswith('ExecStart=/usr/bin/rsync -a --delete ')
    assert line.endswith(' {{DATA_HOST}}:./ {{REPO_DIR}}/logs/collect/')     # from there, to here
    assert '--exclude state.json' in line
    assert '-i %h/.ssh/gg-data-pull' in line and 'BatchMode=yes' in line and 'IdentitiesOnly=yes' in line
    assert 'ForwardAgent' not in svc and ' -A' not in line
    timer = (ops / 'systemd' / 'collect-pull.timer.template').read_text()
    assert 'OnCalendar=*:0/5:50' in timer
    readme = (ops / 'README.md').read_text()
    assert 'restrict,command="/usr/bin/rrsync -ro' in readme
