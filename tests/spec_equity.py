"""U63: the account's equity over time, read from the fleet's own snapshot
file — the tail, once cold and then only what was appended."""
import json
import tempfile
import time
from pathlib import Path

from gridgremlin.equity_series import (DAY, downsample, equity_windows,
                                       read_tail, snapshot_path, windows)


def _rows(path, start, n, step=60, equity=lambda i: 1000.0 + i, gap=None):
    with open(path, 'a') as f:
        for i in range(n):
            f.write(json.dumps({'t': start + i * step, 'equity': equity(i), 'bots': {}}) + '\n')


def spec_U63_the_tail_is_read_once_cold_and_then_only_what_was_appended():
    """A 40 MB history must not be read whole every refresh: the cold read
    walks back from the end only until a line is older than asked; the
    next call reads the appended bytes alone; a file that shrank starts
    cold again; a torn line and an unpriced row are skipped."""
    d = Path(tempfile.mkdtemp())
    p = d / 'snapshots-x.jsonl'
    now = 2_000_000_000.0
    _rows(p, now - 10 * DAY, 10 * 24 * 6, step=600)          # ten days, one row per 10 min
    cache = {}
    pts = read_tail(p, now - 2 * DAY, cache)
    assert pts and all(p[0] >= now - 2 * DAY for p in pts) and len(pts) == 2 * 24 * 6
    assert cache['size'] == p.stat().st_size
    with open(p, 'a') as f:
        f.write('{"t": ' + str(now - 100) + ', "equity": null}\n')      # E9: unpriced
        f.write('{torn line\n')
        f.write(json.dumps({'t': now - 50, 'equity': 2222.0}) + '\n')
    size_before = cache['size']
    pts2 = read_tail(p, now - 2 * DAY, cache)
    assert pts2[-1] == (now - 50, 2222.0, {}) and len(pts2) == len(pts) + 1
    assert cache['size'] > size_before
    # the window moves: older points drop out on the next call
    pts3 = read_tail(p, now - DAY, cache)
    assert all(p[0] >= now - DAY for p in pts3) and len(pts3) < len(pts2)
    # the file shrank (a hand): cold again, no error
    p.write_text(json.dumps({'t': now - 10, 'equity': 5.0}) + '\n')
    assert read_tail(p, now - DAY, cache) == [(now - 10, 5.0, {})]
    assert read_tail(d / 'none.jsonl', now - DAY, cache) == [] and cache == {}


def spec_U63_the_windows_are_downsampled_and_found_by_the_fleets_own_files():
    pts = [(float(i * 60), float(i)) for i in range(600)]
    assert len(downsample(pts, 300.0)) == 120 and downsample(pts, 300.0)[0] == (240.0, 4.0)   # the last of each bucket
    now = 7 * DAY + 600 * 60
    series = [(now - 7 * DAY + i * 60, float(i)) for i in range(7 * 24 * 60)]
    w = windows(series, now)
    assert set(w) == {'24h', '7d'} and len(w['24h']) <= 289 and len(w['7d']) <= 337
    assert all(t >= now - DAY for t, _ in w['24h'])
    d = Path(tempfile.mkdtemp())
    (d / 'configs').mkdir()
    (d / 'logs').mkdir()
    (d / 'configs' / 'watchdog.x.json').write_text(json.dumps({'snapshot': 'logs/snapshots-x.jsonl'}))
    (d / 'configs' / 'fleet.x.json').write_text(json.dumps({'watchdog': 'configs/watchdog.x.json', 'bots': []}))
    assert snapshot_path(d / 'configs' / 'fleet.x.json') == str(d / 'logs' / 'snapshots-x.jsonl')
    (d / 'configs' / 'fleet.y.json').write_text(json.dumps({'bots': []}))
    assert snapshot_path(d / 'configs' / 'fleet.y.json') is None
    assert equity_windows(None, now) is None
    assert equity_windows(str(d / 'logs' / 'snapshots-x.jsonl'), now) is None       # no file yet
    _rows(d / 'logs' / 'snapshots-x.jsonl', now - 3600, 60)
    assert len(equity_windows(str(d / 'logs' / 'snapshots-x.jsonl'), now)['24h']) == 12


def spec_U65_the_snapshot_carries_each_bots_price_and_the_page_draws_it_with_levels_and_fills():
    """The owner's fourth (2026-10-09): a price line per position with the
    bot's levels and fills. The engine's per-minute snapshot carries each
    live bot's last mark (F4) — the only price history at grid
    resolution; the fills come from the kept ledger by the link's prefix
    (I1); the window's rungs and liquidation from the contract. Nothing
    without two points; a quiet line until the snapshots carry it."""
    import time
    from types import SimpleNamespace
    from gridgremlin.equity_series import bot_fills, mark_windows, price_windows
    from gridgremlin.main import snapshot_row
    from panel.render import position_page, price_svg
    alive = SimpleNamespace(botid='linBTCUSDTl', alive=True, _last_pos=0.5, _last_mark=60000.0, offset=0)
    dead = SimpleNamespace(botid='linETHUSDTs', alive=False, _last_pos=None, _last_mark=3000.0, offset=0)
    row = snapshot_row([alive, dead], {'equity': 1000.0, 'mm_rate': 0.1}, 5.0)
    assert row['bots']['linBTCUSDTl']['mark'] == 60000.0 and 'mark' not in row['bots']['linETHUSDTs']
    d = Path(tempfile.mkdtemp())
    p = d / 'snapshots-x.jsonl'
    now = 2_000_000_000.0
    with open(p, 'w') as f:
        for i in range(120):
            f.write(json.dumps({'t': now - 7200 + i * 60, 'equity': None if i == 5 else 1000.0,
                                'bots': {'linBTCUSDTl': {'mark': 60000.0 + i}, 'linETHUSDTs': {'alive': False}}}) + '\n')
    w = price_windows(str(p), 'linBTCUSDTl', now)
    assert w['24h'][-1] == [now - 7200 + 119 * 60, 60119.0] and 24 <= len(w['24h']) <= 25   # 5-min buckets
    assert price_windows(str(p), 'linETHUSDTs', now) is None and mark_windows([], 'x', now) is None
    assert price_windows(None, 'x', now) is None
    led = d / 'demo.json'
    led.write_text(json.dumps({'fills': [
        {'link_id': 'linBTCUSDTl-3-17', 'time_ms': int((now - 3600) * 1000), 'price': 60050.0, 'side': 'buy'},
        {'link_id': 'linBTCUSDTs-3-17', 'time_ms': int((now - 3600) * 1000), 'price': 60050.0, 'side': 'sell'},
        {'link_id': 'linBTCUSDTl-4-17', 'time_ms': int((now - 9 * 86400) * 1000), 'price': 1.0, 'side': 'sell'}]}))
    fills = bot_fills(led, 'linBTCUSDTl', int((now - 7 * 86400) * 1000))
    assert fills == [(now - 3600, 60050.0, 'buy')] and bot_fills(d / 'none.json', 'x', 0) == []
    svg = price_svg(w['24h'], {'lower': 60000.0, 'upper': 60200.0, 'rungs': 5}, 59000.0, fills)
    assert svg.startswith('<svg class="px"') and svg.count('<circle') == 1 and 'fill="var(--pos)"' in svg
    assert 'liquidation at 59,000, below the chart' in svg and '1 buys' in svg and '0 sells' in svg
    on = price_svg(w['24h'], None, 60060.0, ())
    assert 'stroke="var(--neg)"' in on and 'liq 60,060' in on
    assert price_svg([[1, 2]]) == '' and price_svg(None) == ''
    c = {'bots': {'linBTCUSDTl': None}, 'ranges': {'linBTCUSDTl': {'lower': 60000.0, 'upper': 60200.0, 'rungs': 5}},
         'terms': {}, 'generated_ms': int(now * 1000), 'window_hours': 24}
    belief = {'linBTCUSDTl': {'alive': True, 'position': 0.5, 'margin': {'liq': 59000.0}}}
    page = position_page(0, 'demo', 'linBTCUSDTl', c, belief, w, fills)
    assert '<h3>price, 24 h</h3><svg class="px"' in page and page.index('price, 24 h') < page.index('class="cards one"')
    quiet = position_page(0, 'demo', 'linBTCUSDTl', c, belief)
    assert 'it starts with the fleet' in quiet and '<svg class="px"' not in quiet


def spec_H8_the_rehearsal_holds_a_ratio_one_book_dollar_neutral_and_averages_inverse_entries_harmonically():
    """The return-split audit's controls: with fees and funding off, a
    ratio-1 inverse-hedged book on a doubling, a halving, and a doubling
    and back ends worth exactly what it started with. Before the fix the
    rehearsal reported x0.832, x0.886 and x1.066 on these paths and the
    true book drifted to a net short of nearly twice its equity."""
    import gridgremlin.portfolio_rehearse as pr
    from gridgremlin.config import validate_config
    leg = pr._Leg(True)
    leg.trade('sell', 1.0, 100.0)                     # 100 contracts at 100
    leg.trade('sell', 0.5, 200.0)                     # 100 more at 200
    assert abs(leg.entry - 400.0 / 3) < 1e-9 and abs(leg.open_coins(200.0) - (-0.5)) < 1e-9
    row = validate_config({'strategy': 'portfolio', 'name': 't', 'venue': 'bybit', 'capital': 10000,
                           'assets': [{'coin': 'BTC', 'weight': 1.0}], 'risk': {'max_weight': 1.0},
                           'hedge': {'product': 'inverse', 'ratio': 1.0},
                           'rebalance': {'every_hours': 24, 'drift_pct': 0.05}})
    saved = pr.SPOT_FEE, pr.PERP_FEE
    pr.SPOT_FEE = pr.PERP_FEE = 0.0
    try:
        hours = 30 * 24
        paths = {'x2': [100.0 * (1 + i / hours) for i in range(hours + 1)],
                 'x0.5': [100.0 * (1 - 0.5 * i / hours) for i in range(hours + 1)]}
        paths['x2 and back'] = paths['x2'] + paths['x2'][::-1]
        for name, ps in paths.items():
            bars = {'BTC': [{'t': i * 3_600_000, 'c': p} for i, p in enumerate(ps)]}
            r = pr.rehearse(row, bars, {'BTC': []})
            # within half a percent: the 0.3% cash reserve, spent on spot at a later tick, is
            # inside the 5% drift band and rides unhedged — the band's own slack, not a drift
            assert abs(r['equity'] - 1.0) < 0.005, (name, r['equity'])
    finally:
        pr.SPOT_FEE, pr.PERP_FEE = saved
