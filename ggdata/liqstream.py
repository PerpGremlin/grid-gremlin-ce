"""D84: the liquidations Bybit and Binance publish only as a stream, as they
happen. One long-running process, one line per venue:

- Bybit: subscribed to `allLiquidation.<coin>USDT` for each coin, a ping
  every 18 seconds; `S` Buy is a long liquidated.
- Binance (K15b): `!forceOrder@arr` on the current address
  (`fstream.binance.com/market/ws/…`; the old `/ws/…` is retired and silent),
  every symbol, kept for the coins watched and their USDT perpetual only;
  the order's `S` SELL is a long liquidated. Binance sends at most one
  liquidation per symbol each second (its own limit), so a burst is
  undercounted there — a floor, not the total.

Each line reconnects with a growing pause when it drops; a line that fails
any other way stops the process, so systemd restarts it whole. Each
liquidation is appended beside the collector's (K14) in
`logs/collect/<coin>/liq-<day>.jsonl`, marked with its venue. Keyless;
display only — no bot reads it.

  python3 -m ggdata.liqstream [--coins BTC,ETH,…]
"""
from common.symbols import coin_of
import json
import signal
import sys
import time
from pathlib import Path

URL = 'wss://stream.bybit.com/v5/public/linear'
BINANCE_URL = 'wss://fstream.binance.com/market/ws/!forceOrder@arr'
PING_S = 18
DIR = 'logs/collect'


def parse(message, coins=None):
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


def parse_binance(message, coins):
    """A Binance forceOrder message -> [(coin, row)], for the coins watched
    and their USDT perpetual only (the stream carries every symbol). The
    order's `S` is the forced order's side: SELL closes a long; `z` the
    coins filled at the average `ap`, `T` the time."""
    try:
        o = json.loads(message)['o']
        sym = o['s']
        coin = coin_of(sym)
        if sym != f'{coin}USDT' or coin not in coins:
            return []
        qty = float(o.get('z') or 0) or float(o['q'])
        px = float(o.get('ap') or 0) or float(o['p'])
        return [(coin, {'ts': int(o['T']), 'side': 'long' if o['S'] == 'SELL' else 'short',
                        'px': px, 'coins': qty, 'usd': qty * px, 'venue': 'binance'})]
    except (KeyError, TypeError, ValueError, AttributeError):
        return []


# each venue's line: its address, what it is sent first, its heartbeat, its reader
VENUES = {
    'bybit': {'name': 'Bybit', 'url': URL, 'ping': '{"op":"ping"}', 'parse': parse,
              'hello': lambda coins: json.dumps({'op': 'subscribe',
                                                 'args': [f'allLiquidation.{c}USDT' for c in coins]})},
    'binance': {'name': 'Binance', 'url': BINANCE_URL, 'ping': None, 'parse': parse_binance,
                'hello': None},                   # one stream of every symbol; Binance pings us
}


def write(rows, root=None):
    """Append each (coin, row) to the coin's day file."""
    root = Path(root or DIR)
    for coin, row in rows:
        d = root / coin
        d.mkdir(parents=True, exist_ok=True)
        day = time.strftime('%Y-%m-%d', time.gmtime(row['ts'] / 1000))
        with open(d / f'liq-{day}.jsonl', 'a') as f:
            f.write(json.dumps(row) + '\n')


def listen(coins, connect, root=None, stop=lambda: False, clock=time.time, log=print, sleep=time.sleep,
           venue='bybit'):
    """One venue's line: subscribe, read, write, ping; on a dropped line wait
    and reconnect — 1 s, doubling to 60 s, back to 1 s after a minute
    connected. Returns when `stop()` says so."""
    v = VENUES[venue]
    wanted = set(coins)
    pause = 1.0
    while not stop():
        started = clock()
        try:
            ws = connect(v['url'])
            if v['hello']:
                ws.send_text(v['hello'](coins))
            log(f"liqstream: listening for {len(coins)} coins on {v['name']}")
            last_ping = clock()
            while not stop():
                msg = ws.recv_text(timeout=5)
                if msg:
                    rows = v['parse'](msg, wanted)
                    if rows:
                        write(rows, root)
                if v['ping'] and clock() - last_ping >= PING_S:
                    ws.send_text(v['ping'])
                    last_ping = clock()
            ws.close()
            return
        except OSError as e:
            log(f"liqstream: {v['name']} line dropped ({type(e).__name__}: {e}) — again in {pause:.0f} s")
        if clock() - started > 60:
            pause = 1.0
        sleep(pause)
        pause = min(60.0, pause * 2)


def main(argv):
    import threading
    from .market import coins_to_watch
    from .ws import WebSocket
    coins = coins_to_watch(argv)
    stopping = {'now': False}
    failed = []

    def on_term(*_):
        stopping['now'] = True
    signal.signal(signal.SIGTERM, on_term)

    def line(venue):
        try:
            listen(coins, WebSocket.connect, stop=lambda: stopping['now'],
                   log=lambda s: print(s, flush=True), venue=venue)
        except BaseException as e:                   # noqa: BLE001 — one line down stops both: systemd restarts
            failed.append(f'{venue}: {type(e).__name__}: {e}')
            stopping['now'] = True
    lines = [threading.Thread(target=line, args=(v,), name=v) for v in VENUES]
    for t in lines:
        t.start()
    for t in lines:
        t.join()
    if failed:
        print(f'liqstream: stopped — {"; ".join(failed)}', flush=True)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
