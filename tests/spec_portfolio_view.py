"""D78, H6 (the card) and H7 (the rehearsal)."""
import json
import tempfile
from pathlib import Path

from gridgremlin.config import validate_config
from gridgremlin.portfolio_rehearse import rehearse
from panel.render import cards_section, grouped, hero_strip, portfolio_total

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
    from panel.render import position_page
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
    from gridgremlin.market import markets_of
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
    from panel.render import MMR_WARN, exchange_mmr, hero_strip
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


def spec_U67_the_fleet_page_has_a_markets_half_from_the_readings():
    """The owner: half the screen for the bots, half for what helps a trader
    navigate. The tiles come from the newest market reading (D67) and the
    hidden model's (K10); display only."""
    from panel.markets import calm_wild, coins_of, market_column, mini_chart
    from panel.render import render
    row = {'t': 1000.0, 'fear_greed': {'score': 64, 'label': 'Greed', 'avg_7d': 67, 'avg_30d': 66},
           'markets': {
               'bybit:linear:BTCUSDT': {'symbol': 'BTCUSDT', 'price': 82908.1, 'change_24h_pct': -0.35,
                                        'committed': 3_000_000, 'regime': 'leaning down', 'adx_4h': 30.2,
                                        'funding_8h_pct': -0.0015, 'oi_change_24h_pct': 0.5, 'long_pct': 63,
                                        'crowding': 'leaning long', 'depth_1pct': 16.7e6, 'atr_pct_4h': 0.86},
               'bybit:spot:BTCUSDT': {'symbol': 'BTCUSDT', 'price': 82900.0, 'committed': 0},
               'bybit:linear:ADAUSDT': {'symbol': 'ADAUSDT', 'price': 0.71, 'committed': 2_000}},
           'hmm': {'BTC': {'two_states': True, 'state': 'calm', 'p_wild': 0.07, 'spell_h': 24,
                           'sd_day': [0.011, 0.036], 'typical_spell_h': [12, 4],
                           'closes_48h': [100 + i for i in range(48)], 'p_wild_48h': [0.0] * 40 + [0.6] * 8},
                   'ADA': {'two_states': False, 'state': 'one regime', 'sd_day': [0.03]}}}
    assert coins_of(row) == ['BTC', 'ADA']                               # the most capital first
    import re
    html_ = market_column(row, now=1000.0 + 13 * 60)
    col = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html_))           # the text a reader sees
    assert 'read 13 min ago' in col and 'fear &amp; greed 64 (Greed)' in col
    assert html_.index('<b>BTC</b>') < html_.index('<b>ADA</b>')
    assert '82,908.1' in col and '-0.35%' in col and 'leaning down' in col and 'ADX 30' in col
    assert '7% wild · 24 h in, typical 12 h' in col and 'calm ±1.1%/day · wild ±3.6%/day' in col
    assert '-1.6%/yr' in col and '63% of accounts long (leaning long)' in col and 'depth ±1% 16.7M' in col
    assert '<b>one regime</b>' in html_ and 'no distinct wild state' in col   # ADA: no wild state named
    assert mini_chart([1, 2, 3], [0.0, 0.9, 0.0]).count('<rect') == 1 and mini_chart([5], []) == ''
    assert 'unread' in calm_wild({'unread': 'no route'}) and 'not read yet' in calm_wild(None)
    assert 'no market reading yet' in market_column(None)
    page = render([], market=row)
    assert '<div class="split">' in page and '<aside class="markets">' in page
    assert '<aside class="markets">' not in render([], table=True, market=row)      # the table keeps its width
