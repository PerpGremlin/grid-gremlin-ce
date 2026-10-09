"""Two processes on one file (the 2026-10-08 audit, gap (e)): the engine and
the panel are separate processes, and every local durable fact they share
is changed under one lock and re-read inside it (X7b, G22, L3). Here two
real processes write the same tombstone, slide-state and trades files at
once; every write of both must survive."""
import json
import multiprocessing as mp
import tempfile
from pathlib import Path

N = 40


def _tombs(path, who):
    from gridgremlin.tombstones import Tombstones
    t = Tombstones(path)
    for i in range(N):
        t.add(f'{who}{i}', 'stop')


def _slides(path, who):
    from gridgremlin.slide_state import SlideState
    s = SlideState(path)
    for i in range(N):
        s.set(f'{who}{i}', i)


def _trades(path, who):
    from gridgremlin.trades import add_trade
    syms = [f'{who}{i}USDT' for i in range(N // 4)]
    for s in syms:
        add_trade(path, [], {'symbol': s, 'side': 'long', 'capital': 10.0, 'take_profit_avg_pct': 0.01})


def _race(target, path):
    ctx = mp.get_context('fork')
    ps = [ctx.Process(target=target, args=(str(path), who)) for who in ('A', 'B')]
    for p in ps:
        p.start()
    for p in ps:
        p.join(60)
        assert p.exitcode == 0, (target.__name__, p.exitcode)


def spec_X7b_two_processes_on_one_tombstone_file_lose_nothing():
    path = Path(tempfile.mkdtemp()) / 'tombstones-x.json'
    _race(_tombs, path)
    rows = json.loads(path.read_text())
    assert set(rows) == {f'{w}{i}' for w in 'AB' for i in range(N)}


def spec_G22_two_processes_on_one_slide_file_lose_nothing():
    path = Path(tempfile.mkdtemp()) / 'slide_state-x.json'
    _race(_slides, path)
    rows = json.loads(path.read_text())
    assert rows == {f'{w}{i}': i for w in 'AB' for i in range(N)}


def spec_L3_two_processes_on_one_trades_file_lose_nothing():
    path = Path(tempfile.mkdtemp()) / 'trades-x.json'
    _race(_trades, path)
    rows = json.loads(path.read_text())
    assert sorted(r['symbol'] for r in rows) == sorted(f'{w}{i}USDT' for w in 'AB' for i in range(N // 4))
