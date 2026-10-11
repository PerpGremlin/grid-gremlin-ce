"""D84: Bybit's liquidations, as they happen — the stream Bybit publishes and
never keeps. One long-running process: subscribed to `allLiquidation.<coin>USDT`
for every coin the market reading names, a ping every 18 seconds, reconnected
with a growing pause when the line drops. Each liquidation is appended beside
the collector's (K14) in `logs/collect/<coin>/liq-<day>.jsonl`, marked
`venue: bybit`. Keyless; display only — no bot reads it.

Binance's futures streams accept the connection and send nothing from the
box's country or the workstation's (measured 2026-10-11; its spot streams
and its futures web requests answer) — so Binance is not here.

  python3 -m ggdata.liqstream
"""
from common.symbols import coin_of
import json
import signal
import sys
import time
from pathlib import Path

URL = 'wss://stream.bybit.com/v5/public/linear'
PING_S = 18
DIR = 'logs/collect'


def parse(message):
    """A Bybit allLiquidation message -> [(coin, row)]. Bybit's `S` is the
    position side: Buy means a long was liquidated (a forced sell), Sell a
    short; `v` is the size in coins, `p` the bankruptcy price, `T` the time."""
    try:
        d = json.loads(message)
    except ValueError:
        return []
    if not str(d.get('topic', '')).startswith('allLiquidation.'):
        return []
    out = []
    for x in d.get('data') or []:
        try:
            sym = x['s']
            coin = coin_of(sym)
            coins, px = float(x['v']), float(x['p'])
            out.append((coin, {'ts': int(x['T']), 'side': 'long' if x['S'] == 'Buy' else 'short',
                               'px': px, 'coins': coins, 'usd': coins * px, 'venue': 'bybit'}))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def write(rows, root=None):
    """Append each (coin, row) to the coin's day file."""
    root = Path(root or DIR)
    for coin, row in rows:
        d = root / coin
        d.mkdir(parents=True, exist_ok=True)
        day = time.strftime('%Y-%m-%d', time.gmtime(row['ts'] / 1000))
        with open(d / f'liq-{day}.jsonl', 'a') as f:
            f.write(json.dumps(row) + '\n')


def listen(coins, connect, root=None, stop=lambda: False, clock=time.time, log=print, sleep=time.sleep):
    """Subscribe, read, write, ping; on a dropped line wait and reconnect —
    1 s, doubling to 60 s, back to 1 s after a minute connected. Returns
    when `stop()` says so."""
    pause = 1.0
    args = [f'allLiquidation.{c}USDT' for c in coins]
    while not stop():
        started = clock()
        try:
            ws = connect(URL)
            ws.send_text(json.dumps({'op': 'subscribe', 'args': args}))
            log(f'liqstream: subscribed to {len(args)} coins on Bybit')
            last_ping = clock()
            while not stop():
                msg = ws.recv_text(timeout=5)
                if msg:
                    rows = parse(msg)
                    if rows:
                        write(rows, root)
                if clock() - last_ping >= PING_S:
                    ws.send_text('{"op":"ping"}')
                    last_ping = clock()
            ws.close()
            return
        except OSError as e:
            log(f'liqstream: line dropped ({type(e).__name__}: {e}) — again in {pause:.0f} s')
        if clock() - started > 60:
            pause = 1.0
        sleep(pause)
        pause = min(60.0, pause * 2)


def main(argv):
    from .market import latest
    from .ws import WebSocket
    coins = list((latest() or {}).get('hmm') or {}) or ['BTC', 'ETH', 'SOL']
    stopping = {'now': False}

    def on_term(*_):
        stopping['now'] = True
    signal.signal(signal.SIGTERM, on_term)
    listen(coins, WebSocket.connect, stop=lambda: stopping['now'],
           log=lambda s: print(s, flush=True))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
