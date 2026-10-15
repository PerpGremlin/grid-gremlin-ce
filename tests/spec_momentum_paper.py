"""SPEC Q: the paper momentum book (D134), on a hand-built market with
known answers. No network: the market is a pair of functions."""

D = 86_400_000
W = 7 * D


def _mp():
    import gridgremlin.momentum_paper as mp
    return mp


def _world(mp, monday, n=25, weeks=3, gone=None):
    """n coins, candles from 70 days before `monday` to `weeks` Mondays
    after. Coin k trades value 1000 - k a day (so C00 ranks first) and,
    over the 4 weeks before each Monday, rises k% (so C24 is strongest).
    Within each week coin k moves (k - 12)%. `gone` = {coin: last day}."""
    coins = {}
    for k in range(n):
        sym, days = f'C{k:02d}USDT', {}
        price = 100.0
        for d in range(monday - 70 * D, monday + weeks * W + D, D):
            if gone and sym in gone and d > gone[sym]:
                break
            step = (1 + (k - 12) / 100) ** (1 / 7) if d >= monday else (1 + k / 100) ** (1 / 28)
            o, price = price, price * step
            days[d] = (o, price, 1000.0 - k)
        coins[sym] = days
    return coins


def spec_Q1_the_book_is_the_studys_fixed_setting():
    """The 20 most traded with 60 days of candles, ranked by their last
    4 weeks: long the top fifth (4 coins), short the bottom fifth, 12.5%
    each. Funding a long pays; the fee on every change of weight."""
    mp = _mp()
    monday = mp.day_ms('2026-10-19')
    coins = _world(mp, monday)
    wk = mp.form(coins, monday)
    assert wk['universe'] == [f'C{k:02d}USDT' for k in range(20)]
    assert sorted(s for s, x in wk['weights'].items() if x > 0) == ['C16USDT', 'C17USDT', 'C18USDT', 'C19USDT']
    assert sorted(s for s, x in wk['weights'].items() if x < 0) == ['C00USDT', 'C01USDT', 'C02USDT', 'C03USDT']
    assert all(abs(abs(x) - 0.125) < 1e-12 for x in wk['weights'].values())
    w = {'A': 0.25, 'B': 0.25, 'C': -0.25, 'D': -0.25}
    net, fee, paid = mp.week_pnl(w, {}, {'A': 0.04, 'B': 0.0, 'C': -0.02, 'D': 0.0},
                                 {'A': 0.001, 'C': 0.002})
    assert abs(fee - 0.00055) < 1e-12                         # the whole book, once
    assert abs(paid - (0.25 * 0.001 - 0.25 * 0.002)) < 1e-12  # a short is paid a positive rate
    assert abs(net - (0.015 - 0.00055 - paid)) < 1e-12


def spec_Q1_a_monday_never_reads_a_later_candle():
    """The book formed at a Monday is the same whatever candles came
    after it: a late run forms the week the Monday itself would have."""
    mp = _mp()
    monday = mp.day_ms('2026-10-19')
    coins = _world(mp, monday)
    cut = {s: {d: v for d, v in days.items() if d <= monday} for s, days in coins.items()}
    a, b = mp.form(coins, monday), mp.form(cut, monday)
    assert a['weights'] == b['weights'] and a['universe'] == b['universe']
    # a coin with no candle the day before is not in the week; one with no
    # Sunday close has no score
    gap = dict(coins, C05USDT={d: (o, c, 10 * v) for d, (o, c, v) in coins['C05USDT'].items() if d != monday - D})
    assert 'C05USDT' not in mp.universe(gap, monday) and 'C20USDT' in mp.universe(gap, monday)
    assert mp.signal(gap['C05USDT'], monday) is None and mp.signal(coins['C05USDT'], monday) is not None


def _market(coins):
    def coins_at(monday, symbols):
        return {s: coins[s] for s in (coins if symbols is None else symbols) if s in coins}

    def funding_at(monday, symbols):
        return {s: [(monday + D, 0.0001)] for s in symbols}
    return coins_at, funding_at


def spec_Q2_weeks_form_settle_and_freeze_in_order():
    """Week 1 forms 15 minutes after START's open and settles 15 minutes
    after the next Monday's; a run that missed Mondays catches up in
    order, each formed from its own candles and marked late; a settled
    week is never rewritten by a later run; the first week pays the fee
    on the whole book, a held week only on what changed."""
    mp = _mp()
    start = mp.day_ms(mp.START)
    coins = _world(mp, start)
    book = {'setting': mp.setting(), 'weeks': []}
    assert mp.step(book, start + 10 * 60_000, *_market(coins)) == []
    assert mp.step(book, start + 20 * 60_000, *_market(coins)) == ['formed 2026-10-19']
    assert 'late' not in book['weeks'][0] and 'net' not in book['weeks'][0]
    said = mp.step(book, start + 2 * W + D + 60_000, *_market(coins))
    assert said[0].startswith('settled 2026-10-19') and said[1:] == [
        'formed 2026-10-26 (late)', said[2], 'formed 2026-11-02 (late)']
    assert said[2].startswith('settled 2026-10-26')
    w1, w2 = book['weeks'][0], book['weeks'][1]
    assert abs(w1['fee'] - 0.00055) < 1e-12 and w2['fee'] < w1['fee']
    assert abs(w1['gross'] - w1['net'] - w1['fee'] - w1['funding']) < 1e-12
    assert len(w1['rets']) == 20                     # every member: random books score on them
    frozen = dict(w1)
    mp.step(book, start + 2 * W + 2 * D, *_market({s: {} for s in coins}))
    assert book['weeks'][0] == frozen


def spec_Q3_a_coin_gone_mid_week_closes_at_its_last_close_seen():
    """A held coin the venue stops answering for is closed at the last
    close a daily run kept, not at zero and not at its Monday open."""
    mp = _mp()
    start = mp.day_ms(mp.START)
    coins = _world(mp, start)
    book = {'setting': mp.setting(), 'weeks': []}
    mp.step(book, start + 20 * 60_000, *_market(coins))
    held = 'C19USDT'
    assert book['weeks'][0]['weights'][held] > 0
    mp.step(book, start + 3 * D + 60_000, *_market(coins))          # a daily run sees it
    seen = book['weeks'][0]['last'][held][1]
    later = dict(coins)
    later[held] = {}                                                # then the venue forgets it
    mp.step(book, start + W + D, *_market(later))
    r = book['weeks'][0]['rets'][held]
    assert abs(r - (seen / book['weeks'][0]['opens'][held] - 1)) < 1e-12 and r != 0


def spec_Q4_the_setting_is_fixed():
    """A ledger written for another setting is refused, never re-scored:
    a new setting is a new book (D134)."""
    import json
    import tempfile
    from pathlib import Path
    mp = _mp()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / 'book.json'
        p.write_text(json.dumps({'setting': dict(mp.setting(), weeks=8), 'weeks': []}))
        try:
            mp.load(p)
        except ValueError as e:
            assert 'fixed' in str(e)
        else:
            raise AssertionError('a changed setting was accepted')
        assert mp.load(Path(tmp) / 'none.json')['weeks'] == []


def spec_Q5_the_paper_book_sends_nothing():
    """Paper means paper: the module imports no venue code, reads with
    plain GETs, and never holds a key."""
    import ast
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / 'gridgremlin' / 'momentum_paper.py').read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] + [getattr(node, 'module', None) or '']
            assert not any('exchange' in n for n in names), names
        if isinstance(node, ast.Call) and getattr(node.func, 'attr', '') == 'urlopen':
            assert len(node.args) == 1 and not node.keywords or all(k.arg == 'timeout' for k in node.keywords)
    for word in ('.env', 'API_KEY', 'SECRET', 'Request('):
        assert word not in src, word
