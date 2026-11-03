"""U63: the account's equity over time, read from the fleet's own snapshot
file — the tail, once cold and then only what was appended."""
import json
import re
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
    from panel.position_view import position_page
    from panel.drawings import price_svg
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
    assert '<h3>price, 24 h' in page and page.index('price, 24 h') < page.index('class="cards one"')
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


def spec_H7b_the_tilt_is_rehearsed_with_the_regime_the_live_bot_would_have_read():
    """The rehearsal passed the planner no regimes, so a tilt rehearsed as
    neutral. Now the live reading is rebuilt from history: Wilder's ADX on
    closed 4h candles made from the hourly ones, turned into the planner's
    word and believed only after it has held — never a candle from after t."""
    import inspect
    import gridgremlin.portfolio_rehearse as pr
    H = 3_600_000
    # a long steady rise then a long steady fall, hourly
    ps = [100.0 + 0.5 * i for i in range(400)] + [300.0 - 0.5 * i for i in range(400)]
    bars = [{'t': i * H, 'c': p, 'h': p + 0.2, 'l': p - 0.2} for i, p in enumerate(ps)]
    f = pr.regime_from_bars(bars, hold_hours=24)
    seen = [(b['t'], f(b['t'] + H)) for b in bars]
    words = [w for _, w in seen]
    assert words[0] == 'range' and 'up' in words[:400] and words[-1] == 'down'
    first_up = next(t for t, w in seen if w == 'up')
    assert first_up >= 60 * 4 * H // 2                   # ADX needs its closed history before any word
    # no lookahead: the same function on the bars cut at any point agrees up to that point
    cut = 520
    g = pr.regime_from_bars(bars[:cut], hold_hours=24)
    assert [g(b['t'] + H) for b in bars[:cut]] == words[:cut]
    # the hold: the first 'down' comes at least 24 h after the fall's first down reading
    h0 = pr.regime_from_bars(bars, hold_hours=0)
    zero = [h0(b['t'] + H) for b in bars]
    d0 = next(i for i, w in enumerate(zero) if w == 'down')
    d24 = next(i for i, w in enumerate(words) if w == 'down')
    assert d24 - d0 >= 24
    src = inspect.getsource(pr.main)
    assert "regimes = {c: regime_from_bars(bars[c], cfg['regime']['hold_hours'])" in src


def spec_H3b_the_funding_rule_judges_the_markets_rate_as_a_yearly_figure_live_and_rehearsed():
    """The review (2026-10-09): the live rule compared a raw window sum over
    notional with `stand_down_below`, and the rehearsal never applied it.
    One figure now — received over the window as a yearly rate on what the
    short covers, judged only after a day — and the rehearsal uses it."""
    import inspect
    import gridgremlin.portfolio_bot as pb
    import gridgremlin.portfolio_rehearse as pr
    from gridgremlin.config import validate_config
    from gridgremlin.portfolio import trailing_yield
    assert abs(trailing_yield(10.0, 10_000.0, 7.0) - 10 / 10_000 * 365 / 7) < 1e-12
    assert trailing_yield(10.0, 10_000.0, 0.5) is None and trailing_yield(10.0, 0.0, 7.0) is None
    src = inspect.getsource(pb.PortfolioBot._trailing_funding)
    assert 'trailing_yield(' in src and 'market_funding_rates' in src   # the market, not the row's payments
    assert 'self._trailing_funding(now_ms)' in inspect.getsource(pb.PortfolioBot.cycle)
    H = 3_600_000
    row = validate_config({'strategy': 'portfolio', 'name': 't', 'venue': 'bybit', 'capital': 10000,
                           'assets': [{'coin': 'BTC', 'weight': 1.0}], 'risk': {'max_weight': 1.0},
                           'hedge': {'product': 'inverse', 'ratio': 1.0},
                           'rebalance': {'every_hours': 24, 'drift_pct': 0.05}})
    bars = {'BTC': [{'t': i * H, 'c': 100.0} for i in range(24 * 12)]}
    neg = {'BTC': [{'t': i * 8 * H, 'rate': -0.001} for i in range(36)]}
    pos = {'BTC': [{'t': i * 8 * H, 'rate': 0.001} for i in range(36)]}
    saved = pr.SPOT_FEE, pr.PERP_FEE
    pr.SPOT_FEE = pr.PERP_FEE = 0.0
    try:
        r_neg = pr.rehearse(row, bars, neg)
        r_pos = pr.rehearse(row, bars, pos)
    finally:
        pr.SPOT_FEE, pr.PERP_FEE = saved
    # paying funding, the hedge stands down after a day and STAYS down (judged on the market's
    # rates, not on payments that stop): about a day of it paid, not the 3.6% of twelve days
    assert -0.005 < r_neg['funding'] < 0 and r_pos['funding'] > 0.03


def spec_U91_a_month_and_the_whole_history_with_their_sharpe_and_every_low_kept():
    """The owner (2026-10-14): the 30-day and all-time equity "are a superb
    idea", and a Sharpe ratio "for lulz". The whole file is read once and
    then only what was appended; each step of a thinned line keeps its
    lowest, highest and last, so no box hides a dip (the week's box hid
    a low the old way); the Sharpe ratio is the daily one on a year's
    scale, none under ten days. Sabotage: keeping only each step's last
    loses the dip."""
    import math
    from gridgremlin.equity_series import extremes, history, long_windows, sharpe
    d = Path(tempfile.mkdtemp())
    p = d / 'snapshots-x.jsonl'
    now = 2_000_000_000.0
    dip = now - 3 * DAY + 1234
    _rows(p, now - 40 * DAY, 40 * 24 * 12, step=300,
          equity=lambda i: 50.0 if now - 40 * DAY + i * 300 == dip - 1234 else 1000.0 * (1.001 ** (i // 288)) * (1 + 0.002 * (-1) ** (i // 288)))
    cache = {}
    pts = history(p, cache)
    assert cache['size'] == p.stat().st_size and len(pts) <= 40 * 24 * 3
    w = long_windows(p, now, cache)
    assert set(w) == {'30d', 'all', 'sharpe', 'trust'}
    assert min(e for _, e in w['all']) == 50.0 and min(e for _, e in w['30d']) == 50.0   # the dip survives
    assert min(e for _, e in equity_windows(p, now)['7d']) == 50.0
    _rows(p, now, 3, step=300, equity=lambda i: 7777.0)                # appended: read alone
    assert history(p, cache)[-1] == (now + 600, 7777.0)
    assert extremes([(0.0, 5.0), (10.0, 1.0), (20.0, 9.0), (30.0, 4.0)], 100.0) == [(10.0, 1.0), (20.0, 9.0), (30.0, 4.0)]
    days = [(k * DAY, 100.0 * (1.01 if k % 2 else 1.0) * 1.001 ** k) for k in range(12)]
    rets = [b / a - 1 for (_, a), (_, b) in zip(days, days[1:])]
    m = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1))
    assert abs(sharpe(days) - m / sd * math.sqrt(365)) < 1e-9
    assert sharpe(days[:10]) is None                                    # nine returns: too few


def spec_U91_the_box_draws_four_lines_and_names_each_sharpe():
    from panel.drawings import equity_boxes
    line = [[0.0, 100.0], [3600.0, 101.0]]
    html = equity_boxes({'equity': {'24h': line, '7d': line, '30d': line, 'all': line,
                                    'sharpe': {'30d': -4.8, 'all': None}}})
    for word in ('equity, 24 h', 'equity, 7 d', 'equity, 30 d · Sharpe <b class="neg">-4.80</b>',
                 'equity, all time · Sharpe — (under ten days) · since 01 Jan'):
        assert word in html, word
    assert equity_boxes({}) == '<div class="dim">equity line: no history yet</div>'
    assert 'divided by how much the days swing' in html and 'Above 1 is good; below 0 lost money' in html
    assert "Credits: the Sharpe ratio is William F. Sharpe's" in html and 'Bailey and Marcos López de Prado' in html
    assert 'eqnote' not in equity_boxes({'equity': {'24h': line}})      # no Sharpe shown, no note


def spec_U103_one_window_at_a_time_its_heading_steps_to_the_next():
    """The owner (2026-10-21): the 24 h, 7 d, 30 d and all-time lines as a
    switch, click to move to the next. One radio per window drawn, the
    first checked; each heading is the label for the next, the last
    wrapping to the first; the CSS shows only the checked one; names are
    per account so two accounts switch apart; no script, so an export
    switches alike; the panel keeps the pick across its refresh.
    A single window draws no switch."""
    import re
    from panel.css import CSS
    from panel.drawings import equity_boxes
    from panel.reference import KEEP_JS as SCRIPT
    line = [[0.0, 100.0], [3600.0, 101.0]]
    html = equity_boxes({'equity': {'24h': line, '7d': line, 'all': line}}, 2)
    assert re.findall(r'<input type="radio" name="eq-2" id="eq-2-(\w+)" class="rsel eqpick"( checked)?>', html) == \
        [('24h', ' checked'), ('7d', ''), ('all', '')]
    assert re.findall(r'<label for="eq-2-(\w+)" class="eqnext">equity, ([\w ]+?)(?: ·[^<]*)? <span', html) == \
        [('7d', '24 h'), ('all', '7 d'), ('24h', 'all time')]
    assert html.count('class="eqwin"') == 3 and 'name="eq-0"' not in equity_boxes({'equity': {'24h': line, '7d': line}}, 1)
    assert '.eqsw>.eqwin{display:none}' in CSS
    for n in range(1, 5):
        assert f'.eqsw>input:nth-of-type({n}):checked~.eqwin:nth-of-type({n}){{display:block}}' in CSS
    assert "S.setItem('gg-eq:'+r.name,r.id)" in SCRIPT and 'eqs(document);top();' in SCRIPT
    one = equity_boxes({'equity': {'24h': line}})
    assert '<label' not in one and 'checked' in one and 'equity, 24 h</div>' in one


def spec_U91b_a_sharpe_never_shows_alone():
    """The researcher's Sharpe study: +1.7 on paper is not yet told from
    luck. Beside every Sharpe, the chance the true one is above zero and
    the further days needed to reach 95% (skew and fat tails counted),
    agreeing with the study's own formulas; "never, at this rate" when the
    Sharpe is at or below zero. Sabotage: dropping the skew term
    disagrees with the study."""
    from gridgremlin.equity_series import trust
    from panel.drawings import equity_boxes
    pts = [(k * DAY, 100.0 * (1.02 if k % 3 == 0 else 0.995) ** 1 * 1.003 ** k) for k in range(40)]
    t = trust(pts)
    # the study's own psr() and min_trl() on this series (research/sharpe.py,
    # 2026-10-14), pinned so the public edition, which has no research, checks it too
    assert abs(t['likely'] - 0.831336803320458) < 1e-12
    assert abs(t['more'] - 73.70187241719879) < 1e-9
    down = [(k * DAY, 100.0 * 0.997 ** k * (1.01 if k % 2 else 1.0)) for k in range(40)]
    assert trust(down)['more'] is None and trust(pts[:10]) is None
    line = [[0.0, 100.0], [3600.0, 101.0]]
    html = equity_boxes({'equity': {'all': line, 'sharpe': {'all': -1.84},
                                    'trust': {'all': {'likely': 0.169, 'more': None}}}})
    assert '17% likely above zero · never, at this rate' in html
    html = equity_boxes({'equity': {'all': line, 'sharpe': {'all': 1.67},
                                    'trust': {'all': {'likely': 0.761, 'more': 279.8}}}})
    assert '76% likely above zero · about 280 more days to tell from luck' in html


def spec_H8c_an_inverse_legs_realised_stays_in_the_coin():
    """Closed at a loss, an inverse short owes coins, not a fixed sum: booked in
    quote it was a debt at no interest, and the book grew against its equity
    (found by the carry take-profit study, 2026-11-02). SABOTAGE: book the close
    in quote and the coins read nothing; book funding in quote and it misses too."""
    import gridgremlin.portfolio_rehearse as pr
    leg = pr._Leg(True)
    leg.trade('sell', 1.0, 100.0)                     # 100 contracts at 100
    assert abs(leg.funding(0.01, 100.0) - 1.0) < 1e-9
    assert abs(leg.real_coins - 0.01) < 1e-12 and leg.real == 0.0
    leg.trade('buy', 0.5, 200.0)                      # all 100 closed at 200
    assert leg.qty == 0.0 and leg.real == 0.0
    assert abs(leg.real_coins - (0.01 + 100 * (1 / 200 - 1 / 100))) < 1e-12
    lin = pr._Leg(False)
    lin.trade('sell', 1.0, 100.0)
    assert lin.funding(0.01, 100.0) == 1.0 and lin.real_coins == 0.0   # linear: in quote, as before
    lin.trade('buy', 1.0, 200.0)
    assert lin.real == -100.0 and lin.real_coins == 0.0


def spec_H8c_the_coins_it_earned_are_in_the_book_and_its_equity():
    """A flat price and funding paid to the short, in the coin. They are the
    row's worth, so equity rises by what was paid, and coins the planner can see,
    so the hedge grows to cover them. SABOTAGE: leave them out of equity and the
    row earns nothing; out of the book and the hedge never moves."""
    import gridgremlin.portfolio_rehearse as pr
    from gridgremlin.config import validate_config
    row = validate_config({'strategy': 'portfolio', 'name': 't', 'venue': 'bybit', 'capital': 10000,
                           'assets': [{'coin': 'BTC', 'weight': 1.0}], 'risk': {'max_weight': 1.0},
                           'hedge': {'product': 'inverse', 'ratio': 1.0},
                           'rebalance': {'every_hours': 24, 'drift_pct': 0.05}})
    saved = pr.SPOT_FEE, pr.PERP_FEE
    pr.SPOT_FEE = pr.PERP_FEE = 0.0
    try:
        H, hours = 3_600_000, 30 * 24
        bars = {'BTC': [{'t': i * H, 'c': 100.0} for i in range(hours + 1)]}
        rates = [{'t': i * 8 * H, 'rate': 0.002} for i in range(hours // 8 + 1)]
        seen, plan = [], pr.plan_portfolio

        def watching(cfg, book, *a, **k):
            seen.append(book['coins']['BTC'])
            return plan(cfg, book, *a, **k)
        pr.plan_portfolio = watching
        r = pr.rehearse(row, bars, {'BTC': rates})
        assert r['funding'] > 0.1
        assert abs(r['equity'] - 1.0 - r['funding']) < 0.01, (r['equity'], r['funding'])
        assert seen[-1] > seen[1] * (1 + 0.5 * r['funding']), (seen[1], seen[-1])
    finally:
        pr.plan_portfolio = plan
        pr.SPOT_FEE, pr.PERP_FEE = saved


# --- U190: the bot's own levels on its price chart ----------------------------

def _u190_series(mid=100.0, amp=1.0):
    return [(1000.0 + 60 * i, mid + amp * ((i % 9) - 4) / 4) for i in range(120)]


def spec_U190_the_plan_is_kept_with_its_exits_and_what_rests():
    """The engine says each planned price, whether it is an exit and whether it
    rests or waits. SABOTAGE: leave the view unset and the chart has nothing;
    mark every order resting and a far rung reads as placed."""
    from gridgremlin.bot import Bot
    from gridgremlin.events import Notifier
    from spec_pairing import ADAPTER, _cfg
    from spec_loop import FakeVenue
    venue = FakeVenue(mark=60500.0)
    bot = Bot(_cfg(), ADAPTER, venue, Notifier(sink=lambda ln: None), gen_seed=1)
    assert bot.levels_view is None
    bot.cycle()
    orders = bot.levels_view['orders']
    assert orders and all(o[1] == 'Buy' and not o[2] for o in orders)   # flat: entries alone
    resting = {o[0] for o in orders if o[3]}
    assert resting == {o['price'] for o in venue.orders}                # what is placed is what rests
    assert any(not o[3] for o in orders)                                # W1: the rest wait
    assert [abs(o[0] - 60500.0) for o in orders] == sorted(abs(o[0] - 60500.0) for o in orders)


def spec_U190_a_dcas_ladder_stays_where_the_round_put_it():
    """The creation chart works a ladder out from today's price; a running round's
    is where it began. Here the mark moves and the planned add-ons do not.
    SABOTAGE: build them from the mark and they follow it."""
    from gridgremlin.bot import Bot
    from gridgremlin.events import Notifier
    from spec_round import ADAPTER, FakeVenue, _cfg
    venue = FakeVenue()
    bot = Bot(_cfg(), ADAPTER, venue, Notifier(sink=lambda ln: None), gen_seed=1)
    bot.cycle()
    bot.cycle()
    first = sorted(o[0] for o in bot.levels_view['orders'] if not o[2])
    assert first
    venue.mark *= 1.002
    bot.cycle()
    assert sorted(o[0] for o in bot.levels_view['orders'] if not o[2]) == first


def spec_U190_the_cap_keeps_the_nearest_and_says_how_many_it_left():
    """A row of thousands of rungs must not fill the file. SABOTAGE: no cap and
    the view is the whole plan; cap from the far end and the next order is lost."""
    from gridgremlin.live_levels import MAX_ORDERS, levels_view
    desired = [{'price': 100.0 + i, 'side': 'Sell', 'rung': i} for i in range(MAX_ORDERS + 25)]
    view = levels_view(desired, {(0, 'Sell')}, 99.0, 'Sell', 90.0)
    assert len(view['orders']) == MAX_ORDERS and view['more'] == 25
    assert view['orders'][0] == [100.0, 'Sell', True, True] and view['stop'] == 90.0


def spec_U190_the_file_is_replaced_and_an_old_one_draws_nothing():
    """Replaced, never appended: the snapshot file already runs to 100 MB. A fleet
    that stopped writing has no live plan. SABOTAGE: read any age and a stopped
    fleet's orders are drawn as live; a torn file must read as none."""
    import tempfile
    from pathlib import Path
    from gridgremlin.live_levels import STALE_S, path_for, read, write

    class B:
        botid, alive, levels_view = 'x', True, {'orders': [[1.0, 'Buy', False, True]], 'more': 0, 'stop': None}

    class Dead(B):
        botid, alive = 'dead', False
    with tempfile.TemporaryDirectory() as d:
        snap = Path(d) / 'snapshots-x.jsonl'
        write(snap, [B(), Dead()], 1000.0)
        write(snap, [B(), Dead()], 1001.0)
        assert list(read(snap, 1001.0)) == ['x']
        assert read(snap, 1001.0 + STALE_S + 1) == {}
        path_for(snap).write_text('{torn')
        assert read(snap) == {}
        assert read(Path(d) / 'none.jsonl') == {}


def spec_U190_far_levels_are_named_and_never_squash_the_line():
    """A rung 40% away would flatten the day's line against the edge. The chart
    reaches for what is near and names the rest beneath. SABOTAGE: scale to every
    level and the line's height collapses; drop the words and a level vanishes."""
    import re
    from panel.drawings import level_lines, price_svg
    bl = {'levels': {'orders': [[103.0, 'Sell', True, True], [60.0, 'Buy', False, False],
                                [58.0, 'Buy', False, False]], 'more': 0, 'stop': 40.0},
          'exits': {'at': 'position', 'prices': [97.5]}}
    lines, note = level_lines(bl, 99.0)
    assert note == ''
    svg = price_svg(_u190_series(), None, None, (), levels=lines)
    assert 'TP 103' in svg and 'TP 97.5' in svg and 'avg 99' in svg and 'stroke-dasharray="2 3"' in svg
    assert '2 orders below, nearest 60' in svg and 'stop below, nearest 40' in svg
    pts = re.search(r'<polyline points="([^"]+)"', svg).group(1).split()
    ys = [float(p.split(',')[1]) for p in pts]
    assert max(ys) - min(ys) > 240 * 0.25                                # a quarter of the height


def spec_U190_what_there_is_no_plan_for_says_so():
    """A stopped row draws no orders; a fleet not restarted yet says when they
    come, and keeps the window it always drew. SABOTAGE: draw a stopped row's plan
    and it reads as live."""
    from panel.drawings import level_lines, price_svg
    plan = {'levels': {'orders': [[99.0, 'Buy', False, True]], 'more': 3, 'stop': None}}
    assert level_lines(plan, stopped=True) == ([], 'stopped: no orders to draw')
    assert level_lines(dict(plan, alive=False))[1] == 'stopped: no orders to draw'
    lines, note = level_lines(plan)
    assert lines[0][1] == 'order' and note == '3 further orders not drawn'
    assert level_lines({'alive': True})[0] == [] and 'next restart' in level_lines({'alive': True})[1]
    old = price_svg(_u190_series(), {'lower': 99.0, 'upper': 101.0, 'rungs': 5}, None, (),
                    note='its orders are drawn from its fleet\'s next restart')
    assert 'rungs of the window' in old and 'next restart' in old


# --- U191: the price chart's windows ------------------------------------------

def _u191_rows(tmp, now, hours=30):
    """A mark every 76 s, as the box writes them."""
    p = Path(tmp) / 'snapshots-x.jsonl'
    n = int(hours * 3600 / 76)
    with open(p, 'w') as f:
        for i in range(n):
            f.write(json.dumps({'t': now - (n - 1 - i) * 76, 'equity': 1000.0,
                                'bots': {'linBTCUSDTl': {'mark': 60000.0 + i}}}) + '\n')
    return p


def spec_U191_each_window_holds_its_own_span():
    """1 h and 4 h are their spans, not the day cut short, and each still ends at
    the latest price. SABOTAGE: drop a window, or give it the day's span."""
    from gridgremlin.equity_series import price_windows
    now = 2_000_000_000.0
    w = price_windows(str(_u191_rows(tempfile.mkdtemp(), now)), 'linBTCUSDTl', now)
    assert list(w) == ['1h', '4h', '24h', '7d']
    for key, span in (('1h', 3600), ('4h', 4 * 3600), ('24h', 86400)):
        assert now - span <= w[key][0][0] <= now - span + 600, key
        assert w[key][-1][0] == now, key
    assert 45 <= len(w['1h']) <= 48                         # every row of the hour: none thinned away
    assert 110 <= len(w['4h']) <= 125


def spec_U191_one_window_shows_and_the_day_opens():
    """A radio for each window, the day checked, every other window a label for
    its radio, and CSS showing only the checked one. SABOTAGE: check the first
    radio, drop a label's target, or remove a CSS rule."""
    from panel.css import CSS
    from panel.drawings import price_boxes
    series = [(1000.0 + 60 * i, 100.0 + i) for i in range(5)]
    out = price_boxes({k: series for k in ('1h', '4h', '24h', '7d')}, None, None, (), name='px-0-b')
    radios = re.findall(r'<input type="radio" name="px-0-b" id="(px-0-b-\w+)" class="rsel eqpick"( checked)?>', out)
    assert [r[0] for r in radios] == [f'px-0-b-{k}' for k in ('1h', '4h', '24h', '7d')]
    assert [r[0] for r in radios if r[1]] == ['px-0-b-24h']
    assert out.count('class="pxwin"') == out.count('<svg class="px"') == 4
    for k, word in (('1h', '1 h'), ('4h', '4 h'), ('24h', '24 h'), ('7d', '7 d')):
        assert out.count(f'<label for="px-0-b-{k}">{word}</label>') == 3     # from the three other windows
        assert out.count(f'<b>{word}</b>') == 1
    assert '.pxsw>.pxwin{display:none}' in CSS
    for i in range(1, 5):
        assert f'.pxsw>input:nth-of-type({i}):checked~.pxwin:nth-of-type({i}){{display:block}}' in CSS


def spec_U191_only_the_windows_with_a_line_are_offered():
    """A young bot has no empty tab, a window with no line opens nothing, and one
    window has no switch. SABOTAGE: offer every window, or open on the 24 h always."""
    from panel.drawings import price_boxes
    series = [(1000.0, 100.0), (1060.0, 101.0)]
    out = price_boxes({'1h': series, '4h': [[1000.0, 100.0]], '24h': None, '7d': series}, None, None, ())
    assert 'px-4h' not in out and 'px-24h' not in out and out.count('<svg class="px"') == 2
    assert re.search(r'id="px-1h" class="rsel eqpick" checked', out)         # the day is missing: the first opens
    lone = price_boxes({'24h': series}, None, None, ())
    assert 'pxpick' not in lone and '<h3>price, 24 h</h3><svg class="px"' in lone
    assert 'it starts with the fleet' in price_boxes({'24h': None}, None, None, ())
    assert 'it starts with the fleet' in price_boxes(None, None, None, ())


def spec_U191_every_bot_has_its_own_switch():
    """Two bots on one page (the public one) never share a radio, or a click moves
    the other's chart; bad text in a name stays text. SABOTAGE: the fixed default name."""
    from panel.position_view import position_body
    series = [(1000.0, 100.0), (1060.0, 101.0)]
    w = {k: series for k in ('1h', '4h', '24h', '7d')}
    def body(idx, bot):
        return position_body(idx, bot, {'bots': {bot: None}, 'terms': {}, 'generated_ms': 0, 'window_hours': 24},
                             {bot: {}}, w, ())
    a, b, other = body(0, 'linBTCUSDTl'), body(0, 'linETHUSDTl'), body(1, 'linBTCUSDTl')
    ids = [set(re.findall(r'id="(px-[^"]+)"', x)) for x in (a, b, other)]
    assert all(len(s) == 4 for s in ids) and not ids[0] & ids[1] and not ids[0] & ids[2]
    assert '<script' not in body(0, 'x"><script>')


def spec_U190_a_portfolio_bot_has_no_chart_to_mark():
    """Its page stays as it is. SABOTAGE: drop its guard and it reads a window it
    does not have."""
    from panel.position_view import position_body
    assert 'price, 24 h' not in position_body(0, 'pfox', {'terms': {'pfox': {'strategy': 'portfolio'}},
                                                          'bots': {}}, {'pfox': {}}, {}, ())


def spec_U190_the_readout_carries_the_plan_to_the_page():
    """The file reaches the belief the page reads, for the bots the snapshot names.
    The engine's loop writes it beside the snapshot. SABOTAGE: drop the read from
    the readout, or the write from the loop, and the chart stays empty."""
    import inspect
    import json
    import tempfile
    import time
    from pathlib import Path
    from gridgremlin import main as engine
    from gridgremlin.live_levels import path_for
    from gridgremlin.report import _watchdog_view
    with tempfile.TemporaryDirectory() as d:
        snap, wd = Path(d) / 'snapshots-x.jsonl', Path(d) / 'watchdog.json'
        snap.write_text(json.dumps({'t': time.time(), 'bots': {'x': {'alive': True}}}) + '\n')
        wd.write_text(json.dumps({'snapshot': str(snap), 'positions': {}}))
        view = {'orders': [[1.0, 'Buy', False, True]], 'more': 0, 'stop': None}
        path_for(snap).write_text(json.dumps({'t': time.time(), 'bots': {'x': view, 'gone': view}}))
        bots = _watchdog_view({'watchdog': str(wd)})['belief']['bots']
        assert bots == {'x': {'alive': True, 'levels': view}}
    assert 'live_levels.write(snapshot, bots,' in inspect.getsource(engine)


def spec_U190_a_broken_chart_never_costs_a_cycle():
    """The view is worked out inside the trading cycle. A failure there leaves
    the chart empty and the orders placed. SABOTAGE: let it raise and the bot
    loses every cycle over a drawing; catch less in the fleet's write and a value
    JSON refuses ends the cycle."""
    import inspect
    from gridgremlin.adapters import LinearAdapter
    from gridgremlin.bot import Bot
    from gridgremlin.config import validate_config
    from gridgremlin.events import Notifier
    from gridgremlin.main import run
    from spec_loop import FakeVenue
    adapter = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001, 'price_tick': 0.1,
                             'min_qty': 0.001, 'min_notional': 5.0, 'settle_coin': 'USDT'})
    cfg = validate_config({'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
                           'capital': 1000.0, 'leverage': 10, 'upper': 70000.0, 'lower': 50000.0,
                           'rungs': 21, 'spacing_type': 'fixed'})
    bot = Bot(cfg, adapter, FakeVenue(mark=60000.0), Notifier(sink=[].append), gen_seed=1)
    bot.cycle()
    assert bot.levels_view and bot.levels_view['orders']          # it does draw
    def broken(truth):
        raise KeyError('a missing field')
    bot._stop_now = broken
    bot.cycle()
    assert bot.levels_view is None and bot.alive
    src = inspect.getsource(run)
    assert 'live_levels.write(snapshot, bots, time.time())' in src
    after = src.split('live_levels.write(snapshot, bots, time.time())', 1)[1]
    assert after.lstrip().startswith('# U190') and 'except Exception:' in after.split('\n')[1]
