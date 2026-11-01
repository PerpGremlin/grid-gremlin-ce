"""U148, U149: the Portfolio Bot's rehearsal — the carry calculator moved
inside the creation (the owner, 2026-11-01: "a function inside of the
creation, so users can see that, like the grid rehearsal"). One function
works it; the form, its live box, its review and the old `/carry` address
all reach that one; it saves nothing."""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DAY = 86_400_000
FORM = {'fleet': '0', 'name': 'basket', 'capital': '2000', 'assets': 'BTC 2, ETH 1, SOL -1',
        'hedge_ratio': '80', 'hedge_product': 'inverse', 'hedge_each': 'ETH usdc',
        'spot_leverage': '2', 'max_weight': '60'}
RATES = {('inverse', 'BTCUSD'): 0.06, ('linear', 'ETHPERP'): 0.09, ('linear', 'ETHUSDT'): 0.09, ('linear', 'SOLUSDT'): -0.02,
         ('inverse', 'ETHUSD'): 0.04}


def _settlements(now_ms):
    """Each market's 8-hourly settlements over 30 days at its yearly rate;
    a market not in RATES cannot be read."""
    return {k: [(now_ms - i * DAY // 3 - 1000, apr / 1095) for i in range(90)] for k, apr in RATES.items()}


def _reading(now_s):
    return {'t': now_s - 30, 'carry': {'borrow_apr': {'USDT': 0.05}}}


def _faked():
    """The panel's two reads faked: the venue's public funding record and
    the engine's market reading. Returns the undo."""
    import ggdata.market as gm
    import panel.pages.carry_flow as cf
    saved = cf.public_funding, gm.latest
    cf.public_funding = lambda mt, sym, days=30, now_ms=None: _settlements(int(time.time() * 1000)).get((mt, sym))
    gm.latest = lambda path=None: _reading(time.time())

    def undo():
        cf.public_funding, gm.latest = saved
    return undo


def _nums(page):
    """The worked year's figures, in order: every signed amount and percent."""
    return re.findall(r'[+-][\d,]+(?:\.\d+)?%?', page.split('Funding a short was paid', 1)[0])


def spec_U148_the_rehearsal_shows_the_one_calculators_numbers_for_the_form():
    """For a basket typed in the form — weights, a per-coin hedge at 80%,
    an outright short, 2x spot leverage — the rehearsal draws exactly what
    panel.carry.rehearsal computes for the row the form describes: each
    short leg's funding, the loan's interest, the fees, the net and the
    return on the investment, at 7 and 30 days; the funding that breaks
    even; the year at other funding rates. And the served form's live box
    answers the same."""
    import ggdata.market as gm
    from gridgremlin.portfolio import validate_portfolio
    from panel.carry import rehearsal, rehearsal_html
    from panel.carry_setup import funding_apr, row_from_form
    from spec_setup import _call, _served_fleet
    now = 100 * DAY
    got = _settlements(now)
    cfg = validate_portfolio(json.loads(json.dumps(row_from_form(FORM))))
    r = rehearsal(cfg, lambda mt, sym, d: funding_apr(got[(mt, sym)], now, d) if (mt, sym) in got else None, 0.05)
    assert [lg['symbol'] for lg in r['legs']] == ['BTCUSD', 'ETHPERP', 'SOLUSDT']
    assert abs(r['spot'] - 4000 * 0.75) < 1e-6 and abs(r['loan'] - 1000) < 1e-6      # longs 3/4 of a 2x stack
    funding = 4000 * 0.5 * 0.8 * 0.06 + 4000 * 0.25 * 0.8 * 0.09 + 4000 * 0.25 * -0.02
    fees = (3000 + 1000) * 0.35 / 100
    for d in (7, 30):
        y = r['years'][d]
        assert abs(y['funding'] - funding) < 1e-6 and abs(y['net'] - (funding - 50 - fees)) < 1e-6, y
        assert abs(y['on_own'] - y['net'] / 2000) < 1e-12
    assert abs(r['breakeven'] - (50 + fees) / r['short']) < 1e-12
    page = rehearsal_html(FORM, lambda w: {k: got.get(k) for k in w}, now, _reading(now / 1000))
    want = ([x for lg in r['legs'] for x in [f'{lg["apr"][d] * 100:+.2f}%' for d in (7, 30)]
             + [f'{lg["put"] * lg["apr"][d]:+,.0f}' for d in (7, 30)]]
            + [f'{-r["interest"]:+,.0f}'] * 2 + [f'{-r["fees"]:+,.0f}'] * 2
            + [f'{r["years"][d]["net"]:+,.0f}' for d in (7, 30)]
            + [f'{r["years"][d]["on_own"] * 100:+.1f}%' for d in (7, 30)])
    drawn = _nums(page.split('</table>', 1)[0])
    assert drawn == want, (drawn, want)
    assert f'breaks even: {r["breakeven"] * 100:.2f}% a year' in page
    for x, y in r['sensitivity']:
        assert f'<tr><td>{x * 100:.0f}%</td><td class="num"><span class="{"pos" if y["net"] > 0 else "neg"}">{y["net"]:+,.0f}' in page
    assert '<b>+6.00%</b>' in page and '<b>+9.00%</b>' in page and '>+4.00%<' in page   # the hedge chosen, in bold
    undo = _faked()
    base, d, close = _served_fleet()
    try:
        assert gm.latest()['carry']['borrow_apr']['USDT'] == 0.05
        live = _call(base, '/carry-rehearse', FORM)
        assert _nums(live.split('</table>', 1)[0]) == _nums(page.split('</table>', 1)[0]), live[:1500]
    finally:
        close()
        undo()


def _files(d):
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(Path(d).rglob('*')) if p.is_file()}


def spec_U148_rehearsing_saves_nothing():
    """The live box (POST /carry-rehearse) and the rehearse button without
    script (POST /setup-carry, step=rehearse) answer with the year worked
    and leave every file as it was — no fleet line, no backup, no state.
    The button sits after "Next", so Enter in a field still goes to
    review; the page comes back with the form as typed."""
    from spec_setup import _call, _served_fleet
    undo = _faked()
    base, d, close = _served_fleet()
    try:
        before = _files(d)
        page = _call(base, '/setup?adv=carry')
        assert page.index('Next: review the bot') < page.index('name="step" value="rehearse"')
        assert '<div id="rehearsal">' in page and "fetch('/carry-rehearse'" in page and 'setTimeout(ask,600)' in page
        live = _call(base, '/carry-rehearse', FORM)
        button = _call(base, '/setup-carry', dict(FORM, step='rehearse'))
        for answer in (live, button):
            assert 'on your own 2,000' in answer and 'gates passed' not in answer, answer[:800]
        assert 'set up a carry bot' in button and 'value="BTC 2, ETH 1, SOL -1"' in button
        assert _files(d) == before
        assert 'not yet: Investment' in _call(base, '/carry-rehearse', dict(FORM, capital='x'))
        assert _files(d) == before
    finally:
        close()
        undo()


class _NoFollow(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def spec_U149_the_old_carry_address_still_answers():
    """`/carry` (old links) opens the Portfolio Bot form with its query as
    the form's values and the rehearsal worked beside it; bare, the empty
    form; `/?show=carry` the same form in the right half. One coin at the
    whole basket, hedged in full, the stack's own part as the investment
    and the rest as spot leverage."""
    from spec_setup import _served_fleet
    undo = _faked()
    base, d, close = _served_fleet()
    try:
        opener = urllib.request.build_opener(_NoFollow)
        req = urllib.request.Request(base + '/carry?coin=eth&stack=40000&loan=20000&leg=linear&window=d90',
                                     headers={'Cookie': 'gg=tok'})
        try:
            opener.open(req)
            raise AssertionError('no redirect')
        except urllib.error.HTTPError as e:
            assert e.code == 303, e.code
            where = e.headers['Location']
        path, _, anchor = where.partition('#')
        q = dict(urllib.parse.parse_qsl(path.split('?', 1)[1]))
        assert anchor == 'carry-rehearse' and path.startswith('/setup?adv=carry&')
        assert q == {'adv': 'carry', 'assets': 'ETH 100', 'max_weight': '100', 'hedge_ratio': '100',
                     'hedge_product': 'usdt', 'capital': '20000', 'spot_leverage': '2'}, q
        page = urllib.request.urlopen(urllib.request.Request(base + where, headers={'Cookie': 'gg=tok'})).read().decode()
        assert 'value="ETH 100"' in page and 'value="20000"' in page
        assert '<b>+9.00%</b>' in page and 'on your own 20,000' in page            # worked at once, on ETHUSDT
        bare = urllib.request.urlopen(urllib.request.Request(base + '/carry', headers={'Cookie': 'gg=tok'})).read().decode()
        assert 'set up a carry bot' in bare and 'Type the coins and the investment' in bare
        half = urllib.request.urlopen(urllib.request.Request(base + '/?show=carry&coin=BTC',
                                                             headers={'Cookie': 'gg=tok'})).read().decode()
        assert '<aside class="pane">' in half and 'value="BTC 100"' in half and 'Rehearse it first' in half
    finally:
        close()
        undo()


def spec_U148_one_function_works_the_rehearsal_and_a_second_is_caught():
    """No duplicate implementation: the form, its live box, its review and
    the old address all reach panel.carry.rehearsal. Sabotage: that one
    function swapped for a stub — every place shows the stub's number, so
    none works the year on its own; and a second calculator in the panel's
    source (a module of its own using the fees or the sensitivity) is
    named."""
    import panel.carry as pcar
    from spec_setup import _call, _served_fleet
    real = pcar.rehearsal

    def stub(cfg, rate, borrow, **kw):
        r = real(cfg, rate, borrow, **kw)
        r['years'] = {d: dict(y, net=123_456.0) for d, y in r['years'].items()}
        return r
    undo = _faked()
    base, d, close = _served_fleet()
    pcar.rehearsal = stub
    try:
        for answer in (_call(base, '/carry-rehearse', FORM), _call(base, '/setup-carry', dict(FORM, step='rehearse')),
                       _call(base, '/setup-carry', FORM),                       # the review
                       _call(base, '/setup?adv=carry&' + urllib.parse.urlencode(FORM)),
                       urllib.request.urlopen(urllib.request.Request(base + '/carry?coin=BTC&stack=1000',
                                                                     headers={'Cookie': 'gg=tok'})).read().decode()):
            assert '+123,456' in answer, answer[:600]
    finally:
        pcar.rehearsal = real
        close()
        undo()
    root = Path(__file__).resolve().parents[1]
    sources = {str(p.relative_to(root)): p.read_text() for p in (root / 'panel').rglob('*.py')}
    assert calculator_copies(sources) == []
    sabotaged = dict(sources, **{'panel/pages/other.py': 'from panel.carry import FEES_PCT\nfees = stack * FEES_PCT / 100\n'})
    assert calculator_copies(sabotaged) == ['panel/pages/other.py']


def calculator_copies(sources):
    """The panel modules, other than panel/carry.py, that work a carry year
    themselves: one defining a year or rehearsal function, or using the
    calculator's fee share or sensitivity rates."""
    pat = re.compile(r'\bdef (year_of|rehearsal)\b|\bFEES_PCT\b|\bSENSITIVITY\b')
    return sorted(p for p, text in sources.items() if p != 'panel/carry.py' and pat.search(text))
