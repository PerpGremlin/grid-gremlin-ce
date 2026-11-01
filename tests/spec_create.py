# Specs for the create flow (D157, the retail pass's second part): quick
# setup's "How careful?" names the leverage it picks; the numbers a setup
# means show under its inputs and on the review page, from the engine's own
# functions; a bad value is refused before the review in the engine's words
# and nothing typed is lost; the advanced form in the platforms' order with
# an expert fold; the review page's leverage, estimated liquidation and the
# engine's own warning before the typed name; and the card's last jargon.
import html
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

MARK = 84905.14                    # spec_setup's faked public price


def _adapter(symbol='BTCUSDT'):
    from gridgremlin.adapters import LinearAdapter
    return LinearAdapter({'symbol': symbol, 'qty_step': 0.001, 'min_qty': 0.001,
                          'price_tick': 0.1, 'min_notional': 5.0, 'settle_coin': 'USDT'})


def _served():
    import spec_setup
    return spec_setup._served_fleet()


def _call(base, path, data=None):
    import spec_setup
    return spec_setup._call(base, path, data)


QUICK = {'how': 'quick', 'preset': 'sideways', 'fleet': '0', 'symbol': 'BTCUSDT',
         'capital': '1000', 'caution': 'balanced', 'then': 'gates'}


def _proposal(page):
    raw = re.search(r'name="proposal" value="([^"]*)"', page).group(1)
    return json.loads(html.unescape(raw))


def _row_text(page, label):
    """A numbers row's figure cell, tags out."""
    m = re.search(rf'<tr><td>{re.escape(label)}</td><td>(.*?)</td></tr>', page, re.S)
    return None if m is None else html.unescape(re.sub(r'<[^>]+>', '', m.group(1)))


# --- U120: "How careful?" says the leverage it picks ---------------------------

def _careful_says_its_row(page):
    """Each option's words against the row its value makes: the grid's and
    the DCA's leverage named, the value the bare word."""
    from panel.setup import CAUTION, quick_bot
    for c in CAUTION:
        m = re.search(rf'<option value="{c}"[^>]*>([^<]*)</option>', page)
        if m is None:
            return f'{c}: no option'
        words = html.unescape(m.group(1))
        grid = quick_bot({'preset': 'sideways', 'caution': c, 'symbol': 'BTCUSDT',
                          'capital': '1000'}, 'bybit', MARK)
        dca = quick_bot({'preset': 'dca_long', 'caution': c, 'symbol': 'BTCUSDT',
                         'capital': '1000'}, 'bybit', MARK)
        if f"{grid['leverage']:g}x leverage on a grid" not in words:
            return f'{c}: grid leverage not said ({words})'
        if f"{dca['leverage']:g}x on buy-the-dips" not in words:
            return f'{c}: DCA leverage not said ({words})'
        if f"{grid['rungs']} grids" not in words:
            return f'{c}: grid count not said ({words})'
    return None


def spec_U120_how_careful_names_the_leverage_it_picks():
    """The audit: "How careful?" silently picked grid 2x/5x/10x and DCA
    2x/3x/5x. Each option now says it, read from the same tables the preset
    reads, so the words and the row cannot part; the value posted is the
    bare word as before, and the values are unchanged."""
    from panel.setup import DCA_LEVERAGE, GRID_LEVERAGE, quick_page
    assert GRID_LEVERAGE == {'careful': 2, 'balanced': 5, 'bold': 10}       # the owner's: unchanged
    assert DCA_LEVERAGE == {'careful': 2, 'balanced': 3, 'bold': 5}
    page = quick_page(['demo'])
    assert _careful_says_its_row(page) is None, _careful_says_its_row(page)
    assert '<option value="balanced" selected>balanced — 5x leverage on a grid' in page
    base, _d, close = _served()
    try:                                   # the bare word still makes the row
        bold = _proposal(_call(base, '/setup', dict(QUICK, caution='bold')))['bot']
        assert bold['leverage'] == 10
    finally:
        close()


def spec_U120_the_check_catches_an_option_that_hides_its_leverage():
    """Sabotage: the old option text, and words that drift from the table,
    are both caught."""
    import panel.setup as ps
    old = ''.join(f'<option value="{c}">{c}</option>' for c in ps.CAUTION)
    assert 'grid leverage not said' in _careful_says_its_row(old)
    saved = ps.caution_words
    ps.caution_words = lambda c: saved(c).replace(f'{ps.GRID_LEVERAGE[c]}x', '3x')
    try:
        assert 'grid leverage not said' in _careful_says_its_row(ps.quick_page(['demo']))
    finally:
        ps.caution_words = saved


# --- U121: the review page's leverage, liquidation and the engine's warning ---

def _engine_liquidation(proposal):
    """The engine's own figure for the reviewed row: the backtest's
    `alone_liquidation` (T10, the rehearsal's) over the same steady move."""
    from gridgremlin.backtest import backtest
    from gridgremlin.config import validate_config
    from panel.consequence import steady_move
    cfg = validate_config(json.loads(json.dumps(proposal['bot'])))
    r = backtest(cfg, _adapter(cfg['symbol']), steady_move(MARK, cfg['side'] == 'long'))
    return r['alone_liquidation']['price']


def _liquidation_said(page):
    m = re.search(r'Est\. liquidation price</td><td><b class="neg">([0-9,.]+)</b>', page)
    return None if m is None else float(m.group(1).replace(',', ''))


def spec_U121_the_review_shows_the_engines_liquidation_before_the_typed_name():
    """The audit's seventh: the review page gave margin in use but no
    liquidation price, and the engine's slide-leverage warning reached only
    its log. The review now shows leverage, the estimated liquidation price
    — the backtest's own figure for this row, the rehearsal's — and the
    engine's build warnings, all before the box the name is typed in.
    Display only (D29): the row and the gate are as they were."""
    from panel.consequence import _p
    base, _d, close = _served()
    try:
        for preset, side in (('sideways', 'long'), ('falling', 'short')):
            page = _call(base, '/setup', dict(QUICK, preset=preset))
            assert 'gates passed' in page, page[:400]
            engine = _engine_liquidation(_proposal(page))
            said = _liquidation_said(page)
            assert said is not None and _p(engine) == f'{said:,.0f}', (preset, said, engine)
            box = page.index('leverage and liquidation')
            assert box < page.index('Est. liquidation price') < page.index('name="confirm"')
            assert _row_text(page, 'Leverage').startswith('5x — 1,000 USDT trades up to 5,000 USDT')
        # the engine's own warning, for a slide row above its line, and
        # nothing capped: the row keeps its 25x and the gate passes
        from gridgremlin.config import slide_leverage_warning, validate_config
        from panel.html_bits import uncoded
        from panel.setup import form_from_bot
        row = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long', 'capital': 1000,
               'leverage': 25, 'lower': 80000, 'upper': 90000, 'rungs': 21,
               'slide': {'trigger_rungs': 2, 'max_rungs': 20, 'confirm_seconds': 900,
                         'ref_position': 0.5}}
        form = dict(form_from_bot(row), how='advanced', fleet='0')
        page = _call(base, '/setup', form)
        assert 'gates passed' in page, page[:600]
        warn = uncoded(slide_leverage_warning(validate_config(json.loads(json.dumps(row)))))
        said = page.index('the engine warns:')
        assert html.escape(warn) in page and said < page.index('name="confirm"')
        assert _proposal(page)['bot']['leverage'] == 25
    finally:
        close()


def spec_U121_a_figure_that_is_not_the_engines_is_caught():
    """Sabotage: a review page whose liquidation is not the backtest's is
    told apart from the engine's figure."""
    import panel.consequence as pcq
    saved = pcq.backtest

    def off(*a, **k):
        r = saved(*a, **k)
        if r.get('alone_liquidation'):
            r['alone_liquidation'] = dict(r['alone_liquidation'],
                                          price=r['alone_liquidation']['price'] * 0.9)
        return r
    base, _d, close = _served()
    pcq.backtest = off
    try:
        page = _call(base, '/setup', QUICK)
        assert pcq._p(_engine_liquidation(_proposal(page))) != f'{_liquidation_said(page):,.0f}'
    finally:
        pcq.backtest = saved
        close()


def spec_U121_a_dca_liquidation_is_where_its_own_investment_runs_out():
    """The backtest cannot replay a DCA bot, so its estimate is the what-if's
    straight move (the engine's schedule, the adapter's money) held to the
    backtest's maintenance rate: at the price said, the investment plus the
    full ladder's loss is the maintenance margin. A stop that closes it
    first is said instead; spot has none."""
    from gridgremlin.backtest import MM_RATE
    from gridgremlin.config import validate_config
    from panel.consequence import liquidation
    from panel.whatif import entries, whatif
    ad = _adapter()
    row = {'strategy': 'martingale', 'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
           'capital': 1000, 'leverage': 3, 'base_order_size': 120, 'safety_order_size': 120,
           'order_size_multiplier': 1.5, 'deviation_pct': 0.01, 'deviation_step_multiplier': 1.4,
           'max_averaging_orders': 5, 'take_profit_avg_pct': 0.01}
    cfg = validate_config(dict(row))
    liq = liquidation(cfg, ad, MARK)
    r = whatif(cfg, ad, entries(cfg, ad, MARK), MARK, liq['move'])
    assert r['filled'] == r['orders'] == 6
    left = cfg['capital'] + r['pnl'] - ad.notional(r['held'], r['price']) * MM_RATE
    assert abs(left) < 1e-6 * cfg['capital'], left
    short = validate_config(dict(row, side='short'))
    up = liquidation(short, ad, MARK)
    assert up['price'] > MARK
    stopped = validate_config(dict(row, stop={'watch': 'mark_price', 'level': 60000}))
    assert liquidation(stopped, ad, MARK) == {
        'price': None, 'why': 'its stop loss closes it at 60,000 first'}
    grid = validate_config({'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
                            'capital': 1000, 'leverage': 10, 'lower': 80000, 'upper': 90000,
                            'rungs': 11, 'max_loss': 100, 'max_loss_since': '2026-10-31T00:00:00Z'})
    assert liquidation(grid, ad, MARK)['why'].startswith('its loss limit closes it at')


# --- U122: the numbers under the inputs, and the engine's refusal before review -

def spec_U122_the_form_shows_what_the_setup_means_as_it_is_typed():
    """Bybit and Pionex put profit per grid, order size, the least money
    and an estimated liquidation under the inputs. Both doors carry the box
    and the script that asks the server for it (the panel's own nonce), and
    the server answers from the engine's functions: the least investment
    is the smallest the engine's placeable check accepts, the order size the
    engine's lot, the profit each gap less the maker fee on both legs, and
    what the account has free from its last readout, red when the bot asks
    for more."""
    from gridgremlin.config import ConfigError, check_placeable, validate_config
    from gridgremlin.fees import BYBIT_MAKER
    from gridgremlin.ladder import grid_rungs, lot
    from panel.server import Handler
    base, d, close = _served()
    try:
        for path in ('/setup', '/setup?adv=grid', '/setup?adv=martingale'):
            page = _call(base, path)
            assert '<div id="numbers">' in page and "fetch('/numbers'" in page, path
            assert re.search(r'<script nonce="[^"]+">\(function\(\)\{\s*var box=document'
                             r"\.getElementById\('numbers'\)", page), path
        adv = {'how': 'advanced', 'strategy': 'grid', 'fleet': '0', 'symbol': 'BTCUSDT',
               'side': 'long', 'market_type': 'linear', 'capital': '1000', 'leverage': '5',
               'lower': '80000', 'upper': '90000', 'rungs': '11'}
        Handler._cache[str(d / 'f.json')] = (time.time(), {
            'bots': {}, 'watchdog': {'belief': {'available': 2500.0, 'equity': 5000.0}},
            'terms': {'x': {'quote': 'USDT'}}})
        got = _call(base, '/numbers', adv)
        assert 'class="refusal"' not in got, got
        raw = dict({k: float(adv[k]) for k in ('capital', 'leverage', 'lower', 'upper')},
                   market_type='linear', symbol='BTCUSDT', side='long', rungs=11)
        cfg = validate_config(dict(raw))
        ad = _adapter()
        least = float(_row_text(got, 'Least investment that works').split(' USDT')[0].replace(',', ''))

        def placeable(c):
            try:
                check_placeable(validate_config(dict(raw, capital=c)), ad)
                return True
            except ConfigError:
                return False
        assert placeable(least) and not placeable(least * 0.99), least
        q = lot(cfg, ad, MARK)
        assert _row_text(got, 'Size per order').startswith(f'{q:.10g} coins')
        p = grid_rungs(cfg, ad)
        gaps = [(p[i + 1] - p[i]) * q - (p[i] + p[i + 1]) * q * BYBIT_MAKER for i in range(10)]
        pct = [g / (p[i] * q) for i, g in enumerate(gaps)]
        said = _row_text(got, 'Profit per grid level')
        span = (f'{min(pct):.2%}' if max(pct) - min(pct) < 5e-5 else
                f'{min(pct):.2%} – {max(pct):.2%}')
        assert said.startswith(f'{span} after fees'), (said, span)
        fixed = _call(base, '/numbers', dict(adv, spacing_type='fixed'))
        assert ' – ' in _row_text(fixed, 'Profit per grid level').split(' after')[0]
        assert 'free to trade 2,500 USDT' in _row_text(got, 'Least investment that works')
        big = _call(base, '/numbers', dict(adv, capital='3000'))
        assert 'free to trade <b class="neg">2,500 USDT</b> — more than the account has free' in big
    finally:
        Handler._cache.pop(str(d / 'f.json'), None)
        close()


def _refused_live(got, why):
    return 'class="refusal"' in got and html.escape(why) in got


def spec_U122_a_bad_value_is_refused_in_the_engines_words_before_the_review():
    """A bad value was refused only after "Next": the review's gates. The
    form's box now asks the same gates as it is typed — the engine's
    validators, the market's smallest order, the whole fleet's gate — and
    shows the refusal verbatim (P3); nothing is sent anywhere, so nothing
    typed is lost. Settings still missing are named, all at once. A refusal
    at the review's gate comes back as typed: the quick form as the quick
    form, the advanced form with its own unit."""
    from gridgremlin.config import ConfigError, validate_config
    base, _d, close = _served()
    try:
        adv = {'how': 'advanced', 'strategy': 'grid', 'fleet': '0', 'symbol': 'BTCUSDT',
               'side': 'long', 'market_type': 'linear', 'capital': '1000',
               'lower': '90000', 'upper': '80000', 'rungs': '11'}
        try:
            validate_config({'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
                             'capital': 1000, 'lower': 90000, 'upper': 80000, 'rungs': 11})
        except ConfigError as e:
            why = str(e)
        assert _refused_live(_call(base, '/numbers', adv), why)
        miss = _call(base, '/numbers', {'how': 'advanced', 'strategy': 'grid', 'fleet': '0',
                                        'symbol': 'BTCUSDT'})
        assert 'Lowest price; Highest price; Number of grids or Gap between grids (%)' in miss
        # the whole fleet's gate: the seed fleet already trades ETHUSDT long
        dup = _call(base, '/numbers', dict(adv, symbol='ETHUSDT', lower='2500', upper='2900'))
        assert 'class="refusal"' in dup and 'already in this fleet' in dup
        # the market's smallest order, for a DCA (the review's own check)
        dca = {'how': 'advanced', 'strategy': 'martingale', 'fleet': '0', 'symbol': 'BTCUSDT',
               'side': 'long', 'market_type': 'linear', 'capital': '1000', 'leverage': '3',
               'base_order_size': '20', 'safety_order_size': '50', 'max_averaging_orders': '3',
               'deviation_pct': '1', 'take_profit_avg_pct': '1'}
        got = _call(base, '/numbers', dca)
        assert 'class="refusal"' in got and "under this market&#x27;s smallest order" in got
        # a gate refusal comes back as typed: size in position size, not
        # the collateral it was turned into
        back = _call(base, '/setup', dict(adv, symbol='ETHUSDT', lower='2500', upper='2900',
                                          capital='5000', size_unit='notional', leverage='5'))
        assert 'class="refusal"' in back and 'already in this fleet' in back
        assert 'name="capital" value="5000"' in back and '<option value="notional" selected>' in back
    finally:
        close()


def spec_U122_a_live_check_that_skips_a_gate_is_caught():
    """Sabotage: with the order-minimum question dropped from the live
    check, the too-small DCA order is no longer refused under the inputs."""
    import panel.create as pc
    saved = pc.order_minimum_problem
    base, _d, close = _served()
    pc.order_minimum_problem = lambda *a: None
    try:
        got = _call(base, '/numbers', {
            'how': 'advanced', 'strategy': 'martingale', 'fleet': '0', 'symbol': 'BTCUSDT',
            'side': 'long', 'market_type': 'linear', 'capital': '1000', 'leverage': '3',
            'base_order_size': '20', 'safety_order_size': '50', 'max_averaging_orders': '3',
            'deviation_pct': '1', 'take_profit_avg_pct': '1'})
        assert 'smallest order' not in got
    finally:
        pc.order_minimum_problem = saved
        close()


# --- U123: the advanced form in the platforms' order, an expert fold ----------

def _order_of(page, names):
    return [page.index(f'name="{n}"') for n in names]


def spec_U123_the_advanced_form_asks_in_the_platforms_order_and_folds_the_expert():
    """Coin, direction, range, levels, leverage, money — Bybit's order —
    above the fold; the alarm's position limit, which opened the form with
    no unit, sits in a second Expert fold with its unit, beside the risk
    profile, the jitter guard, how each piece is sold, the placement window,
    where the price lands after a move, the auto-filled stamps and the first
    order's timers. Every field is posted once, so a row and its form
    round-trip as before (U2, U19, U116)."""
    from panel.setup import ESSENTIAL, EXPERT, advanced_page, fields
    grid = advanced_page('grid', {}, ['demo'], 0)
    assert _order_of(grid, ('symbol', 'market_type', 'side', 'lower', 'upper', 'rungs',
                            'leverage', 'capital')) == sorted(_order_of(grid, ESSENTIAL['grid']))
    dca = advanced_page('martingale', {}, ['demo'], 0)
    order = _order_of(dca, ('symbol', 'side', 'deviation_pct', 'max_averaging_orders',
                            'leverage', 'capital', 'base_order_size'))
    assert order == sorted(order)
    for strategy, page in (('grid', grid), ('martingale', dca)):
        head, _, expert = page.partition('<details class="expert">')
        assert 'Position limit for the alarm (coins)' in expert and 'name="ceiling"' not in head
        for n in EXPERT:
            if any(f[0] == n for f in fields(strategy)):
                assert f'name="{n}"' in expert and f'name="{n}"' not in head, (strategy, n)
        for n, *_ in fields(strategy):
            assert len(re.findall(rf'name="{n}"', page)) == 1, (strategy, n)
    # a value set in the fold opens it, as Advanced does
    assert '<details class="expert" open>' in advanced_page('grid', {'ceiling': '3'}, ['demo'], 0)


def spec_U123_what_cannot_apply_is_hidden():
    """The mid price applies to the reversal preset alone, so it shows only
    when that preset is picked (by the page's style, no script); the carry
    bot is another product, set apart from the grid and DCA doors and shown
    only where an account can hold one (Bybit)."""
    from panel.css import CSS
    from panel.setup import quick_page
    page = quick_page(['demo'])
    assert '<tr class="only-reversal"><td>Mid price</td>' in page
    assert ('tr.only-reversal{display:none}' in CSS and
            'form:has(input[name=preset][value=reversal]:checked) tr.only-reversal' in CSS)
    doors = page.split('or start from a blank advanced form', 1)[1].split('</p>', 1)[0]
    assert 'adv=grid' in doors and 'adv=martingale' in doors and 'adv=carry' not in doors
    assert 'adv=carry' in page and 'adv=carry' not in quick_page(['hl'], carry=False)


# --- U124: the card's last jargon ---------------------------------------------

OLD_WORDS = ('(belief)', 'watchdog swept', 'watchdog OFF', 'kept history', 'readout unavailable',
             'THIN for this fleet', 'rungs from home', 'the ledger is behind')


def spec_U124_the_card_and_account_box_speak_a_persons_words():
    """The words the audit named that part one left: "(belief)", "watchdog
    swept", "kept history", "readout unavailable", "THIN for this fleet",
    "window slid N rungs from home". They read estimated, safety checks, all-
    time, couldn't load, order book thin for this size, and range moved up
    or down N levels; the key says each."""
    import copy
    from spec_panel import CONTRACT
    from panel.card import since_first_line
    from panel.fleet_bits import sweep_note
    from panel.reference import KEY
    from panel.server import render
    c = copy.deepcopy(CONTRACT)
    c['watchdog']['belief']['bots']['spoADAUSDTl'] = {'alive': True, 'position': 910.57, 'offset': 2}
    c['market'] = {'spoADAUSDTl': {'line': 'ranging', 'thin': True, 'regime': 'ranging', 'age_s': 30}}
    c['unavailable'] = 'boom'
    page = render([('demo', c)]) + render([('demo', c)], table=True)
    for old in OLD_WORDS:
        assert old not in page, old
    assert 'range moved up 2 levels from where it started' in page
    assert 'order book thin for this size' in page and "couldn't load this account" in page
    assert 'safety checks' in page
    from panel.card import card
    held = card(0, 'linDOGEs', None, c, c['watchdog']['belief']['bots'])
    assert 'holding 730 (estimated)' in held and '(belief)' not in held
    sf = {'fills': 3, 'realized': 1.0, 'fees': 0.1, 'unreal_at_mark': 0.0, 'position': 0.0,
          'trips': 1, 'strategy': 'grid', 'first_ms': 86_400_000, 'truncated': False, 'behind': 0}
    assert 'all-time: the record is behind' in since_first_line({'since_first': {'x': sf}}, 'x')
    assert sweep_note({}) == '<span class="dim">safety checks: not running</span>'
    for word in ('(estimated)', 'all-time', 'safety checks', 'order book thin for this size',
                 'range moved up / down N levels', 'est. liquidation price',
                 'least investment that works', 'profit per grid level'):
        assert word in KEY, word


# --- U160: a coin-margined (inverse) bot is sized in USD, and says so ----------

INV = {'how': 'advanced', 'strategy': 'grid', 'fleet': '0', 'symbol': 'BTCUSD',
       'side': 'long', 'market_type': 'inverse', 'capital': '1000', 'leverage': '2',
       'lower': '80000', 'upper': '90000', 'rungs': '11'}


def _served_inverse(asked=None):
    """The served panel, a BTCUSD inverse market beside the linear ones;
    `asked` collects the market of every price read."""
    import panel.create as pc
    from gridgremlin.adapters import InverseAdapter
    base, d, close = _served()
    linear = pc.public_adapter

    def adapter(cfg):
        if cfg.get('market_type') == 'inverse':
            return InverseAdapter({'symbol': cfg['symbol'], 'qty_step': 1, 'price_tick': 0.5,
                                   'min_qty': 1, 'settle_coin': 'BTC'})
        return linear(cfg)

    def mark(cfg):
        if asked is not None:
            asked.append(cfg.get('market_type'))
        return MARK
    pc.public_adapter, pc.public_mark = adapter, mark
    return base, d, close


def _inverse_said(form_page, numbers, review):
    """None when an inverse grid speaks USD everywhere its money is typed
    or shown, else what is missing."""
    from panel.setup import SIZE_UNITS_INVERSE
    coin = f'{1000 / MARK:.4g} BTC'
    if ('in USD — the dollar value you put up, not a count of coins; your BTC is the '
            'collateral') not in html.unescape(form_page):
        return 'the investment field does not say USD'
    if html.escape(SIZE_UNITS_INVERSE['collateral'].replace('{coin}', 'BTC')) not in form_page:
        return 'the size unit does not say USD'
    if 'Largest position (in USD contracts)' not in form_page:
        return 'the position cap still says coins'
    line = _row_text(numbers, 'Investment')
    if line is None or not line.startswith(f"1,000 USD ≈ {coin} at today's price"):
        return f'no coin line under the investment: {line}'
    if not (_row_text(numbers, 'Leverage') or '').startswith(
            '2x — 1,000 USD trades up to 2,000 USD'):
        return 'the leverage row is not in USD'
    if not (_row_text(review, 'Investment') or '').startswith(f'1,000 USD ≈ {coin}'):
        return 'the review does not state the investment in USD and its coin value'
    if f'Its investment is 1,000 USD (about {coin} at today' not in html.unescape(review):
        return 'the plain words do not say USD'
    return None


def _inverse_pages(base):
    from panel.setup import advanced_page
    return (advanced_page('grid', INV, ['demo']), _call(base, '/numbers', INV),
            _call(base, '/setup', INV))


def spec_U160_capital_from_on_an_inverse_market_is_in_usd():
    """The owner (2026-11-01) read "collateral (USDT …)" on a coin-margined
    grid and thought he had to type BTC. The engine sizes an inverse bot in
    USD: capital x leverage is the ladder's USD (config C4), and a contract
    is a dollar (InverseAdapter.qty_from_notional), so the full ladder is
    that many contracts. Each unit of the form turns into USD capital:
    collateral is the USD put up, position size the USD contracts over the
    leverage, coins their USD value at the inverse market's own price (a
    linear BTCUSD does not exist; it was asked for before)."""
    from gridgremlin.adapters import InverseAdapter
    from gridgremlin.config import validate_config
    from gridgremlin.ladder import grid_rungs, position_cap
    from panel.setup import capital_from, resolve_size, size_market
    cfg = validate_config({'market_type': 'inverse', 'symbol': 'BTCUSD', 'side': 'long',
                           'capital': 1000, 'leverage': 5, 'lower': 80000,
                           'upper': 90000, 'rungs': 10})
    ad = InverseAdapter({'symbol': 'BTCUSD', 'qty_step': 1, 'price_tick': 0.5,
                         'min_qty': 1, 'settle_coin': 'BTC'})
    assert cfg['ladder_notional'] == 5000.0
    assert position_cap(cfg, ad, grid_rungs(cfg, ad)) == 5000.0      # contracts = USD
    assert capital_from(1000.0, 'collateral', 5) == 1000.0
    assert capital_from(5000.0, 'notional', 5) == 1000.0
    assert abs(capital_from(0.1, 'coins', 2, mark=60000.0) - 3000.0) < 1e-9
    assert size_market({'market_type': 'inverse', 'symbol': ' btcusd'}, 'bybit') == {
        'venue': 'bybit', 'market_type': 'inverse', 'symbol': 'BTCUSD'}
    assert size_market({'market_type': 'linear', 'symbol': 'BTCUSDT'},
                       'bybit')['market_type'] == 'linear'
    f = resolve_size(dict(INV, capital='0.1', size_unit='coins'), lambda: 60000.0)
    assert f['capital'] == '3000' and f['size_unit'] == 'collateral'
    asked = []
    base, _d, close = _served_inverse(asked)
    try:                                   # the coins are priced on BTCUSD inverse
        got = _call(base, '/numbers', dict(INV, capital=f'{1000 / MARK:.10g}',
                                           size_unit='coins', leverage='1'))
        assert 'class="refusal"' not in got, got
        assert asked and set(asked) == {'inverse'}, asked
        assert (_row_text(got, 'Investment') or '').startswith('1,000 USD'), got
    finally:
        close()


def spec_U160_an_inverse_grid_says_usd_and_its_coin_line():
    """The money fields of an inverse grid say USD, the size units read as
    USD, the position cap counts USD contracts, a line under the investment
    gives its coin value at the price the box already read, and the review
    states the investment in USD and in its coin. The words follow the
    market type as it is changed (MONEY_JS). Display only: the row is the
    same row. Quick setups and DCA bots are linear or spot (the engine
    refuses an inverse DCA), so the advanced grid is the one door."""
    base, _d, close = _served_inverse()
    try:
        problem = _inverse_said(*_inverse_pages(base))
        assert problem is None, problem
        page = html.unescape(_call(base, '/setup?adv=grid'))
        assert "var mt=q('market_type');if(!mt)return;" in page
        assert 'data-inv="in USD — the dollar value you put up' in page
        bot = _proposal(_call(base, '/setup', INV))['bot']
        assert bot['capital'] == 1000 and bot['market_type'] == 'inverse'
    finally:
        close()


def spec_U160_linear_wording_is_unchanged():
    """A linear grid reads as it did: the investment's own help, the size
    units' own words, coins for the position cap, no coin line."""
    from panel.setup import SIZE_UNITS, advanced_page
    lin = dict(INV, symbol='BTCUSDT', market_type='linear')
    page = advanced_page('grid', lin, ['demo'])
    assert ('>what you put up (collateral), or the position size in USDT, or coins '
            "— converted at today's price and the leverage below</td>") in html.unescape(page)
    for _k, words in SIZE_UNITS:
        assert f'>{words}</option>' in page, words
    assert '>Largest position (in coins)</td>' in page
    base, _d, close = _served_inverse()
    try:
        got = _call(base, '/numbers', lin)
        assert _row_text(got, 'Investment') is None, got
        assert 'USD ≈' not in got and ' USD ' not in html.unescape(got)
    finally:
        close()


def spec_U160_sabotage_an_inverse_form_in_linear_words_is_caught():
    """Sabotage: with the inverse words dropped, and with the coin line
    dropped from the numbers, the check says what is missing."""
    import panel.consequence as pcq
    import panel.setup as ps
    base, _d, close = _served_inverse()
    saved_words, saved_rows = ps.INVERSE_WORDS, pcq.rows_html
    try:
        ps.INVERSE_WORDS = {}
        assert _inverse_said(*_inverse_pages(base)) == 'the investment field does not say USD'
        ps.INVERSE_WORDS = saved_words
        pcq.rows_html = lambda cfg, n, money='': saved_rows(
            dict(cfg, market_type='linear'), n, money)
        assert _inverse_said(*_inverse_pages(base)).startswith('no coin line')
    finally:
        ps.INVERSE_WORDS, pcq.rows_html = saved_words, saved_rows
        close()


# --- U161: the quick setup reads the market type from the symbol ---------------

def _info(symbol, kind):
    return {'symbol': symbol, 'status': 'Trading', 'contractType': kind,
            'priceFilter': {'tickSize': '0.5'},
            'lotSizeFilter': {'qtyStep': '1', 'minOrderQty': '1'}}


def _catalogue(category, symbol):
    """Bybit's public instruments as it answers them: a linear query for
    BTCUSD answers with the inverse contract (A8); SPOTONLY is listed on
    spot alone; anything else, an empty list."""
    if symbol == 'BTCUSDT' and category in ('linear', 'spot'):
        return _info(symbol, 'LinearPerpetual' if category == 'linear' else '')
    if symbol == 'BTCUSD' and category in ('linear', 'inverse'):
        return _info(symbol, 'InversePerpetual')
    if symbol == 'SPOTONLY' and category == 'spot':
        return _info(symbol, '')
    return [][0]


def _with_catalogue(fetch, run):
    import panel.create as pc
    from gridgremlin.exchange.bybit import klines
    saved = klines.fetch_instrument
    klines.fetch_instrument = fetch
    pc._KINDS.clear()
    try:
        return run(pc)
    finally:
        klines.fetch_instrument = saved
        pc._KINDS.clear()


def spec_U161_the_quick_setup_reads_the_market_type_from_the_symbol():
    """The owner (2026-11-01) typed BTCUSD in the quick setup and met A8's
    "pick the inverse market type" on a form with no such field. The
    symbol now says it: the category whose public instruments list it,
    judged by A8's contractType check — BTCUSD inverse, BTCUSDT linear, a
    spot-only coin spot, an unknown one the not-listed refusal, a failed
    read raised as a failure, Hyperliquid linear without asking."""
    from gridgremlin.config import ConfigError

    def run(pc):
        assert pc.market_kind('bybit', 'BTCUSD') == 'inverse'
        assert pc.market_kind('bybit', 'BTCUSDT') == 'linear'
        assert pc.market_kind('bybit', 'SPOTONLY') == 'spot'
        try:
            pc.market_kind('bybit', 'NOSUCHUSDT')
            raise AssertionError('an unlisted symbol was given a market type')
        except ConfigError as e:
            assert 'NOSUCHUSDT: Bybit lists no such market' in str(e), e
        assert pc.market_kind('hyperliquid', 'BTCUSD') == 'linear'
    _with_catalogue(_catalogue, run)

    def down(category, symbol):
        raise OSError('network unreachable')

    def run_down(pc):
        try:
            pc.market_kind('bybit', 'BTCUSD')
            raise AssertionError('a failed read was taken for an answer')
        except OSError:
            pass
    _with_catalogue(down, run_down)


def spec_U161_a_quick_inverse_grid_says_its_market_and_usd():
    """BTCUSD in the quick grid: the box says the market ("BTCUSD —
    coin-margined (inverse) perpetual") and the investment in USD with its
    coin value; the review's row is an inverse row. A quick DCA on it is
    refused in words, naming the USDT perpetual (the engine runs a DCA on
    linear or spot only); a spot-only coin points to the advanced form."""
    from panel.setup import quick_bot
    base, _d, close = _served_inverse()
    q = dict(QUICK, symbol='BTCUSD')
    try:
        got = _call(base, '/numbers', q)
        assert 'BTCUSD — coin-margined (inverse) perpetual' in got, got
        assert 'class="refusal"' not in got, got
        assert (_row_text(got, 'Investment') or '').startswith('1,000 USD ≈ '), got
        assert re.search(r"≈ [0-9.]+ BTC at today's price", _row_text(got, 'Investment'))
        page = _call(base, '/setup', q)
        assert _proposal(page)['bot']['market_type'] == 'inverse', page[:600]
        assert (_row_text(page, 'Investment') or '').startswith('1,000 USD ≈ ')
        lin = _call(base, '/numbers', QUICK)
        assert 'BTCUSDT — USDT/USDC perpetual' in lin and _row_text(lin, 'Investment') is None
        dca = _call(base, '/numbers', dict(q, preset='dca_long'))
        assert 'class="refusal"' in dca and 'type BTCUSDT for the USDT perpetual' in dca, dca
    finally:
        close()
    try:
        quick_bot(dict(QUICK, symbol='SPOTONLY'), 'bybit', 1.0, 'spot')
        raise AssertionError('a spot-only coin made a quick perpetual bot')
    except ValueError as e:
        assert 'open the advanced form for a spot bot' in str(e)


def spec_U161_sabotage_without_the_contract_check_btcusd_reads_linear():
    """Sabotage: with A8's contractType check taken out of the instrument
    parse, a linear query for BTCUSD answers and the symbol reads linear —
    the dead end the owner met."""
    from gridgremlin.exchange.bybit import truth
    saved = truth.parse_instrument

    def blind(category, info):
        return saved(category, dict(info, contractType=''))
    truth.parse_instrument = blind
    try:
        assert _with_catalogue(_catalogue, lambda pc: pc.market_kind('bybit', 'BTCUSD')) \
            == 'linear'
    finally:
        truth.parse_instrument = saved
