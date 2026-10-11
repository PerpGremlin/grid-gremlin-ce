"""Bybit's liquidation stream (D84), with a fake line."""
import json
import tempfile

from gridgremlin.liqstream import PING_S, URL, listen, parse


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
