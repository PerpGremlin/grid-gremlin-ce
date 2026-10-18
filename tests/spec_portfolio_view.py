"""D78, H6 (the card) and H7 (the rehearsal)."""
import json
import tempfile
from pathlib import Path

from gridgremlin.config import validate_config
from gridgremlin.portfolio_rehearse import rehearse
from panel.render import cards_section
from panel.nav import grouped
from panel.strip_view import hero_strip, portfolio_total

VIEW = {'stack': {'BTC': {'coins': 0.75, 'value': 45000.0}, 'ETH': {'coins': 15.0, 'value': 45000.0}},
        'stack_value': 90000.0, 'cash': 120.5, 'parked': 0.0,
        'assets': [{'coin': 'BTC', 'weight': 0.5, 'actual': 0.5, 'ratio': 1.0, 'hedged': 0.75, 'short': 0.0,
                    'regime': 'up', 'unwound': False},
                   {'coin': 'ETH', 'weight': 0.5, 'actual': 0.5, 'ratio': 1.0, 'hedged': 15.0, 'short': 0.0,
                    'regime': None, 'unwound': True}],
        'carry': {'total': 812.4, 'trailing': 96.2}, 'total': 1010.0, 'tilt': 150.6, 'basis': 47.0,
        'unreal': -30.0, 'realised': 12.0, 'value': 91010.0, 'anchor': 90000.0,
        'last_tick_ms': 0, 'next_tick_ms': 3_600_000 * 20, 'delevered': 0}
CONTRACT = {'window_hours': 6.0, 'generated_ms': 0, 'unowned': {}, 'ranges': {}, 'fee_floors': {},
            'terms': {'pfocarry': {'strategy': 'portfolio', 'quote': 'USDT', 'venue': 'bybit', 'capital': 90000,
                                   'assets': VIEW['assets'], 'hedges': {'BTC': {'product': 'inverse', 'ratio': 1.0},
                                                                        'ETH': {'product': 'usdt', 'ratio': 1.0}},
                                   'rebalance': {'every_hours': 24}, 'regime': {'tilt': 0.3, 'hold_hours': 24}},
                      'linDOGEs': {'strategy': 'grid', 'quote': 'USDT', 'market_type': 'linear'}},
            'watchdog': {'ceilings': {}, 'swept_s_ago': 4,
                         'belief': {'age_s': 3, 'bots': {'pfocarry': {'alive': True, 'position': 90000.0,
                                                                       'portfolio': VIEW},
                                                         'linDOGEs': {'alive': True, 'position': 0.0}}}},
            'bots': {'linDOGEs': {'fills': 1, 'realized': 10.0, 'fees': 1.0, 'bought': 0.0, 'sold': 0.0,
                                  'position': 0.0, 'avg_cost': 0.0, 'unreal_at_mark': 0.0, 'truncated': False,
                                  'mark': 0.2, 'side': 'short', 'strategy': 'grid', 'inverse': False},
                     'pfocarry': None}}


def spec_H6_the_card_says_the_three_truths_and_the_exchange_counts_the_row():
    from panel.position_view import position_page
    html = cards_section(0, 'demo', CONTRACT) + position_page(           # U68: the facts are the page's
        0, 'demo', 'pfocarry', CONTRACT, CONTRACT['watchdog']['belief']['bots'])
    assert 'carry portfolio' in html and 'PORTFOLIO' in html
    assert '<div class="card pfo">' in html and '<div class="two"><div>' in html   # two columns inside
    from panel.reference import KEY
    assert 'carry / tilt / basis &amp; shape' in KEY and 'window slid N rungs' in KEY and 'numbers (button)' in KEY
    assert '<div class="dim foot"><span>pfocarry</span>' in html             # the footer every card shares
    from panel.css import CSS
    assert '.card.pfo{grid-column:1/-1;justify-self:start;width:100%;max-width:calc(63em' in CSS   # three cards wide, not the page
    assert '.card .foot{margin-top:auto' in CSS and '.card.pfo .two{display:grid;grid-template-columns:1fr 1fr' in CSS
    assert 'class="dim foot"><span>linDOGEs</span>' in html                 # the grid card's footer, the same shape
    assert '2 assets · hedged on inverse, usdt · rebalanced every 24 h · tilt 30% with the regime' in html
    assert '+1,010.00</span> USDT' in html and 'since its anchor' in html
    assert 'carry <b class="pos">+812.40</b>' in html and 'tilt <b class="pos">+150.60</b>' in html
    assert 'basis &amp; shape <b class="pos">+47.00</b>' in html
    assert '<td>BTC</td><td>50% → 50%</td><td>1 → 1.00</td><td>0.75</td><td>0.75</td>' in html
    assert 'regime up' in html and 'unwound (basis)' in html
    assert 'stack <b>90,000.00</b> USDT · cash 120.50 · next tick in 20.0 h' in html
    assert "mode=remove'>remove</a>" in html and 'copy=' not in html.split('carry portfolio')[1].split('</div></div>')[0]
    # the exchange's total: the grid's 9.00 plus the row's 1,010.00
    assert portfolio_total(CONTRACT) == 1010.0 and '+1,019.00</span> USDT' in html
    assert '+1,019.00' in hero_strip([('demo', CONTRACT)])
    # the views: a portfolio under its own heading, present exactly once in every view
    assert [t for t, _ in grouped(CONTRACT, 'strategy')] == ['grids', 'portfolios — hedged, rebalanced']
    assert [t for t, _ in grouped(CONTRACT, 'market')] == ['DOGE — perp', 'portfolios']
    for view in ('all', 'side', 'pairs', 'strategy', 'market'):
        assert sorted(b for _, rows in grouped(CONTRACT, view) for b, _ in rows) == ['linDOGEs', 'pfocarry']
    # a row the engine has not valued: the card says so, counts nothing
    quiet = json.loads(json.dumps(CONTRACT))
    quiet['watchdog']['belief']['bots']['pfocarry'] = {'alive': True, 'position': 0.0}
    assert 'not yet valued' in cards_section(0, 'demo', quiet) and portfolio_total(quiet) == 0.0
    del quiet['watchdog']['belief']['bots']['pfocarry']
    assert "waits for the fleet's restart" in cards_section(0, 'demo', quiet)


def _bars(n_hours, p0, drift, wobble, seed):
    """A deterministic walk: no randomness, a drift and a sine wobble. The
    first day is flat: the research harness hedges at its first daily
    check, the engine at once, and a flat first day makes the two one."""
    import math
    out, t0 = [], 1_700_000_000_000
    for i in range(n_hours):
        j = max(i - 24, 0)
        p = p0 * (1 + drift * j / n_hours) * (1 + wobble * math.sin(j / 37.0 + seed)) / (1 + wobble * math.sin(seed))
        out.append({'t': t0 + i * 3_600_000, 'c': p})
    return out


def spec_H2_the_market_readings_cover_the_rows_legs():
    from gridgremlin.market_list import markets_of
    tmp = Path(tempfile.mkdtemp())
    fleet = {'bots': [{'strategy': 'portfolio', 'name': 'carry', 'capital': 90000,
                       'assets': [{'coin': 'BTC', 'weight': 0.5}, {'coin': 'ETH', 'weight': 0.5}],
                       'hedge': {'BTC': {'product': 'inverse'}, 'ETH': {'product': 'usdt', 'ratio': 0.5}}}]}
    (tmp / 'f.json').write_text(json.dumps(fleet))
    m = markets_of([str(tmp / 'f.json')])
    assert m == {('bybit', 'spot', 'BTCUSDT'): 45000.0, ('bybit', 'inverse', 'BTCUSD'): 45000.0,
                 ('bybit', 'spot', 'ETHUSDT'): 45000.0, ('bybit', 'linear', 'ETHUSDT'): 22500.0}


def spec_H7_the_rehearsal_borrows_at_the_rows_rate():
    n = 24 * 60
    bars = {'BTC': _bars(n, 60000.0, 0.0, 0.0, 0.0), 'ETH': _bars(n, 3000.0, 0.0, 0.0, 0.0)}   # flat prices
    funding = {c: [{'t': b['t'], 'rate': 0.0001} for i, b in enumerate(bars[c])
                   if i == 0 or b['t'] // 28_800_000 != bars[c][i - 1]['t'] // 28_800_000] for c in bars}
    plain = validate_config({'strategy': 'portfolio', 'name': 'p', 'capital': 10000,
                             'assets': [{'coin': 'BTC', 'weight': 0.5}, {'coin': 'ETH', 'weight': 0.5}],
                             'hedge': {'product': 'inverse', 'ratio': 1.0}})
    lever = validate_config({'strategy': 'portfolio', 'name': 'l', 'capital': 10000, 'spot_borrow': True,
                             'margin': {'spot_leverage': 2.0, 'borrow_apr_max': 0.10}, 'risk': {'max_weight': 1.0},
                             'assets': [{'coin': 'BTC', 'weight': 1.0}, {'coin': 'ETH', 'weight': 1.0}],
                             'hedge': {'product': 'inverse', 'ratio': 1.0}})
    a, b = rehearse(plain, bars, funding), rehearse(lever, bars, funding)
    assert abs(b['funding'] - 2 * a['funding']) < 0.003                   # twice the stack, twice the carry
    # 60 days of interest on 10,000 borrowed at 10%: about 164, counted in the fees
    assert 0.014 < b['fees'] - a['fees'] - 0.001 < 0.020
    assert b['equity'] > a['equity']                                       # at these rates the lean pays


def spec_U66_every_accounts_box_and_the_strip_say_its_mmr():
    """The owner: "account MMR should be displayed for every account on the
    fleet page" — the exchange's own gauge, from the fleet's snapshot."""
    from panel.strip_view import MMR_WARN, exchange_mmr, hero_strip
    calm = {'watchdog': {'belief': {'mm_rate': 0.279, 'age_s': 60}}}
    line = exchange_mmr(calm)
    assert 'account MMR <b class="dim">27.9%</b>' in line and 'liquidates at 100%' in line
    assert 'min ago' not in line
    hot = exchange_mmr({'watchdog': {'belief': {'mm_rate': MMR_WARN + 0.01, 'age_s': 1800}}})
    assert 'class="neg"' in hot and 'as of 30 min ago' in hot
    assert exchange_mmr({}) == '' and exchange_mmr({'watchdog': {'belief': {}}}) == ''
    c = {'bots': {}, 'watchdog': {'belief': {'mm_rate': 0.035, 'bots': {}}}, 'terms': {}}
    strip = hero_strip([('Hyperliquid testnet', c)])
    assert 'MMR <b class="">3.5%</b>' in strip


def spec_U100_every_account_says_what_is_free_to_trade():
    """The owner (2026-10-19): "the users cannot see what they have left
    before they burn through their immediate margin" — the exchange's own
    available balance, from the fleet's snapshot, beside the MMR."""
    from gridgremlin.main import fleet_wallet, snapshot_row
    a = {'equity': 1000.0, 'mm_rate': 0.1, 'available': 300.0}
    b = {'equity': 500.0, 'mm_rate': 0.3, 'available': 100.0}
    assert fleet_wallet({'bybit': a, 'hyperliquid': b}) == {'equity': 1500.0, 'mm_rate': 0.3, 'available': 400.0}
    unread = {'equity': None, 'mm_rate': None, 'unread': True}
    assert fleet_wallet({'bybit': a, 'hyperliquid': unread})['available'] is None   # a part is not the whole
    from panel.strip_view import FREE_WARN, exchange_free, hero_strip
    assert snapshot_row([], {'equity': 1000.0, 'mm_rate': 0.1, 'available': 300.0}, 0)['available'] == 300.0
    assert 'available' not in snapshot_row([], {'equity': 1000.0, 'mm_rate': 0.1, 'available': None}, 0)
    assert 'available' not in snapshot_row([], {'equity': 1000.0, 'mm_rate': 0.1}, 0)
    calm = {'watchdog': {'belief': {'equity': 1000.0, 'available': 300.0, 'age_s': 60}},
            'terms': {'x': {'quote': 'USDT'}}}
    line = exchange_free(calm)
    assert 'free to trade <b class="dim">300.00</b> USDT' in line and '(30% of equity)' in line
    assert 'as of' not in line
    low = exchange_free({'watchdog': {'belief': {'equity': 1000.0, 'available': 1000.0 * FREE_WARN - 1,
                                                 'age_s': 1800}}})
    assert 'class="neg"' in low and 'as of 30 min ago' in low
    assert exchange_free({}) == '' and exchange_free({'watchdog': {'belief': {'equity': 1000.0}}}) == ''
    assert exchange_free({'watchdog': {'belief': {'equity': 0.0, 'available': 5.0}}}) == ''
    c = {'bots': {}, 'watchdog': {'belief': {'mm_rate': 0.035, 'equity': 200.0, 'available': 30.0,
                                             'bots': {}}}, 'terms': {}}
    assert 'free <b class="neg">15%</b>' in hero_strip([('Bybit demo', c)])
    import json
    from spec_setup import _call, _served_fleet
    base, d, close = _served_fleet()
    try:                                             # the snapshot, read through to the account's box
        wd = json.loads((d / 'wd.json').read_text())
        (d / 'wd.json').write_text(json.dumps(dict(wd, snapshot=str(d / 'snap.jsonl'))))
        (d / 'snap.jsonl').write_text(json.dumps({'t': 9e9, 'equity': 800.0, 'mm_rate': 0.1,
                                                  'available': 200.0, 'bots': {}}) + '\n')
        page = _call(base, '/')
        assert 'free to trade <b class="dim">200.00</b>' in page and '(25% of equity)' in page
    finally:
        close()


def spec_U66_a_cards_fold_aligns_its_headings_with_their_numbers():
    """The owner: in the numbers, with assets dropped down, "some headings
    are misaligned" — the info pages' `details td{text-align:left}` and its
    22em first column reached into a card's folds: numbers went left under
    right-aligned headings. A card's fold aligns both right, the first
    column left and as wide as it needs."""
    from panel.css import CSS
    assert ('.card details.fold td,.card details.fold th{text-align:right;white-space:nowrap;'
            'padding:.1em .4em}') in CSS
    assert '.card details.fold td:first-child,.card details.fold th:first-child{text-align:left;width:auto}' in CSS
    # two classes outrank the info pages' bare `details td` wherever each sits (specificity, not order)
    assert 'details td{text-align:left}' in CSS


def spec_H8b_a_portfolio_rows_hedge_books_rebuild_from_the_venues_fills():
    """The owner (2026-10-11): rebuild the carry row's books from the
    venue's fills — the stored realised figure kept the pre-H8 arithmetic.
    Every short leg's fills replayed through today's book: the inverse
    entry harmonic, realised in the coin; a disagreeing position refuses
    the apply."""
    from gridgremlin.portfolio_rebuild import compare, rebuild
    fills = [{'side': 'sell', 'price': 100.0, 'qty': 1000.0, 'fee': 0.0},
             {'side': 'sell', 'price': 125.0, 'qty': 1000.0, 'fee': 0.0},
             {'side': 'buy', 'price': 110.0, 'qty': 2000.0, 'fee': 0.0}]
    books = rebuild({'hedge:SOL': (fills, True)})
    b = books['hedge:SOL']
    avg = 2000.0 / (1000.0 / 100.0 + 1000.0 / 125.0)                        # harmonic: 111.11…
    assert b['position'] == 0.0 and abs(b['realized'] - 2000.0 * (1 / 110.0 - 1 / avg)) < 1e-12
    arithmetic = 2000.0 * (1 / 110.0 - 1 / 112.5)                           # the pre-H8 book's figure
    assert abs(arithmetic - b['realized']) > 0.1                            # the error the rebuild clears
    stored = {'hedge:SOL': {'position': 0.0, 'avg': 0.0, 'realized': arithmetic, 'fees': 0.0}}
    lines, bad = compare(stored, books)
    assert bad == [] and 'hedge:SOL: position 0 → 0' in lines[0] and 'realised' in lines[0]
    lin = rebuild({'hedge:BTC': ([{'side': 'sell', 'price': 80000.0, 'qty': 0.01, 'fee': 0.4},
                                  {'side': 'buy', 'price': 79000.0, 'qty': 0.004, 'fee': 0.16}], False)})['hedge:BTC']
    assert abs(lin['position'] - 0.006) < 1e-12 and abs(lin['realized'] - 4.0) < 1e-9 and abs(lin['fees'] - 0.56) < 1e-12
    _, bad = compare({'hedge:BTC': dict(lin, position=0.01)}, {'hedge:BTC': lin})
    assert bad == ['hedge:BTC']                                             # a fill unseen: refused


def spec_H9_the_carry_view_holds_each_coin_at_its_average_cost():
    """Buy 1 BTC at 100 (fee 0.1 quote, taken as 0.001 coin) and 1 at 120:
    1.999 coins cost 220. Sell 1 at 130 (fee 0.13): realised 130 − 110.055
    − 0.13; the rest keeps its average. A coin that arrives without a fill
    joins at the price of the moment; one that leaves takes the average."""
    from gridgremlin.portfolio_bot import spot_fill, spot_sync
    b = {'coins': 0.0, 'cost': 0.0, 'realized': 0.0, 'fees': 0.0}
    spot_fill(b, 'buy', 1.0, 100.0, 0.1)
    spot_fill(b, 'buy', 1.0, 120.0, 0.0)
    assert abs(b['coins'] - 1.999) < 1e-12 and abs(b['cost'] - 220.0) < 1e-12
    avg = 220.0 / 1.999
    spot_fill(b, 'sell', 1.0, 130.0, 0.13)
    assert abs(b['realized'] - (130.0 - avg - 0.13)) < 1e-9
    assert abs(b['cost'] / b['coins'] - avg) < 1e-9
    spot_sync(b, b['coins'] + 0.5, 140.0)                      # funding paid in the coin
    assert abs(b['cost'] - (0.999 * avg + 0.5 * 140.0)) < 1e-9
    before = b['cost'] / b['coins']
    spot_sync(b, b['coins'] / 2, 90.0)                        # the wallet's bound took half
    assert abs(b['cost'] / b['coins'] - before) < 1e-9


def spec_H9_the_full_card_shows_every_holding_the_loan_and_the_cash():
    """Spot coins with their floating P&L, each short with its open and
    realised P&L, the loan as a debt, spare stablecoins as collateral, and
    from when the costs count — on the full card only."""
    from panel.card import card
    view = dict(VIEW, borrowed=5000.0, leverage=1.5, borrow_apr=0.04, interest=12.5,
                spot={'BTC': {'coins': 0.75, 'price': 60000.0, 'value': 45000.0, 'cost': 42000.0,
                              'avg': 56000.0, 'floating': 3000.0, 'realized': 0.0, 'since_ms': 86_400_000}},
                legs=[{'kind': 'hedge', 'coin': 'BTC', 'symbol': 'BTCUSD', 'inverse': True, 'size': 45000.0,
                       'avg': 56000.0, 'mark': 60000.0, 'unreal': -3000.0, 'realized': 4.0}],
                stables={'USDC': 250.0, 'USDT': -5000.0})
    belief = {'pfocarry': {'alive': True, 'portfolio': view}}
    full = card(0, 'pfocarry', None, CONTRACT, belief, full=True)
    for words in ('what the account holds', 'BTC spot', '56,000', '3,000.00', 'BTCUSD hedge',
                  '−45,000 USD', '-3,000.00', 'loan', '−5,000.00 USDT', '4.00%/yr', 'USDC cash',
                  'collateral, counted in full', 'counted from 1970-01-02'):
        assert words in full, words
    assert 'USDT cash' not in full                            # a loan is not spare cash
    assert 'what the account holds' not in card(0, 'pfocarry', None, CONTRACT, belief, full=False)


def spec_H9b_spot_costs_rebuild_from_the_venues_record():
    """Bought 1 BTC at 100 and 1 at 120; the inverse hedge's funding paid
    0.01 BTC at 110; the hedge realised 0.02 BTC at 90 (its fee 0.001 BTC):
    the book holds 2.029 coins at 220 + 1.1 + 1.71 = 222.81. A replay that
    disagrees with the coins held by more than dust is refused."""
    from gridgremlin.portfolio_rebuild import hedge_coin_events, rebuild_spot, spot_compare
    events = [('fill', 'buy', 1.0, 100.0, 0.0), ('fill', 'buy', 1.0, 120.0, 0.0),
              ('coin', 0.01, 110.0), ('coin', 0.019, 90.0)]
    b = rebuild_spot(events)
    assert abs(b['coins'] - 2.029) < 1e-12 and abs(b['cost'] - (220.0 + 1.1 + 0.019 * 90.0)) < 1e-9
    hedge = hedge_coin_events([{'time_ms': 1, 'side': 'sell', 'price': 100.0, 'qty': 1000.0, 'fee': 0.001},
                               {'time_ms': 2, 'side': 'buy', 'price': 90.0, 'qty': 1000.0, 'fee': 0.0}])
    assert [t for t, _ in hedge] == [1, 2]
    assert abs(hedge[0][1][1] + 0.001) < 1e-12                    # the fee, in the coin
    assert abs(hedge[1][1][1] - 1000.0 * (1 / 90.0 - 1 / 100.0)) < 1e-12 and hedge[1][1][2] == 90.0
    lines, bad = spot_compare({'BTC': 2.029}, {'BTC': b}, {'BTC': 130.0})
    assert bad == [] and 'replayed 2.029 coins against 2.029 held' in lines[0]
    assert spot_compare({'BTC': 2.2}, {'BTC': b}, {'BTC': 130.0})[1] == ['BTC']


def spec_H9b_each_coin_shows_its_net_with_its_hedge():
    """The coins' floating P&L and the hedge's open P&L, side by side and
    summed: the pair's result; and a rebuilt book says so."""
    from panel.card import card
    view = dict(VIEW, spot={'BTC': {'coins': 0.75, 'price': 60000.0, 'value': 45000.0, 'cost': 48000.0,
                                    'avg': 64000.0, 'floating': -3000.0, 'realized': 0.0,
                                    'since_ms': 86_400_000, 'rebuilt': True}},
                legs=[{'kind': 'hedge', 'coin': 'BTC', 'symbol': 'BTCUSD', 'inverse': True, 'size': 48000.0,
                       'avg': 64000.0, 'mark': 60000.0, 'unreal': 3200.0, 'realized': 0.0}])
    full = card(0, 'pfocarry', None, CONTRACT, {'pfocarry': {'alive': True, 'portfolio': view}}, full=True)
    assert 'BTC net, with its hedge' in full and '>200.00<' in full
    assert "rebuilt from the exchange's own record since 1970-01-02" in full and 'counted from' not in full


def spec_H11_each_coin_shows_its_spot_and_hedge_leverage_up_to_the_venues():
    """The owner (2026-10-16): 'display spot leverage and hedge leverage per
    ticker. 1x for no leverage up to whatever can be set exchange side.'"""
    from gridgremlin.exchange.bybit.truth import parse_instrument
    from panel.position_view import position_page
    info = {'symbol': 'BTCUSD', 'status': 'Trading', 'priceFilter': {'tickSize': '0.5'},
            'lotSizeFilter': {'qtyStep': '1', 'minOrderQty': '1'}, 'settleCoin': 'BTC',
            'leverageFilter': {'minLeverage': '1', 'maxLeverage': '100.00'}}
    assert parse_instrument('inverse', info)['max_leverage'] == 100.0
    spot = dict(info, symbol='BTCUSDT', lotSizeFilter={'basePrecision': '0.000001', 'minOrderAmt': '1'})
    del spot['leverageFilter']
    assert parse_instrument('spot', spot)['max_leverage'] is None
    c = json.loads(json.dumps(CONTRACT))
    v = c['watchdog']['belief']['bots']['pfocarry']['portfolio']
    leg = {'inverse': True, 'size': 45000.0, 'avg': 60000.0, 'mark': 60000.0, 'unreal': 0.0, 'realized': 0.0}
    v['legs'] = [dict(leg, kind='hedge', coin='BTC', symbol='BTCUSD', leverage=100.0, max_leverage=100.0),
                 dict(leg, kind='hedge', coin='ETH', symbol='ETHUSD', leverage=10.0, max_leverage=None)]
    v.update(borrowed=1_080_000.0, leverage=7.3, spot_leverage_most=10.0)
    html = position_page(0, 'demo', 'pfocarry', c, c['watchdog']['belief']['bots'])
    assert "<th>leverage</th>" in html
    assert "<td>spot 7.30× <span class='dim'>of 10×</span> · hedge 100× <span class='dim'>of 100×</span></td>" in html
    assert "<td>spot 7.30× <span class='dim'>of 10×</span> · hedge 10×</td>" in html     # no ceiling read: none said
    v.update(borrowed=0.0, leverage=0.98, spot_leverage_most=1.0)          # no loan: 1×, of 1×
    html = position_page(0, 'demo', 'pfocarry', c, c['watchdog']['belief']['bots'])
    assert "spot 1.00× <span class='dim'>of 1×</span>" in html
    v.update(borrowed=120.0, leverage=None, spot_leverage_most=3.0)        # the engine's None: equity gone
    html = position_page(0, 'demo', 'pfocarry', c, c['watchdog']['belief']['bots'])
    assert "spot: loan exceeds equity" in html and "spot 1.00×" not in html   # never the calmest number (audit 10-16)
