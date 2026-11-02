# Specs for D168 (SPEC U184-U188): the DCA creators do the ladder's arithmetic.
# Investment, leverage, add-ons and a shape give the orders, in the row's own
# keys; typed orders stay the person's, told when they stop matching the money;
# the orders show as a table on the form and the review.
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gridgremlin.adapters import InverseAdapter, LinearAdapter
from gridgremlin.backtest import MM_RATE
from gridgremlin.config import validate_config
from panel.consequence import ladder_html, liquidation, numbers
from panel.create import order_minimum_problem
from panel.dca_ladder import (DEFAULT_SHAPE, LADDER_SHARE, OWN, SHAPES, fit_words, inferred_shape,
                              ladder_total, order_unit, resolve_ladder, shape_of)
from panel.setup import (advanced_page, bot_from_form, form_from_bot, missing_required, quick_bot,
                         quick_page)

MARK = 84905.14
LIN = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001, 'min_qty': 0.001,
                     'price_tick': 0.1, 'min_notional': 5.0, 'settle_coin': 'USDT'})
INV = InverseAdapter({'symbol': 'BTCUSD', 'qty_step': 1.0, 'price_tick': 0.5,
                      'min_qty': 1.0, 'settle_coin': 'BTC'})


def _form(**over):
    form = {'strategy': 'martingale', 'symbol': 'BTCUSDT', 'side': 'long',
            'market_type': 'linear', 'capital': '10000', 'leverage': '3',
            'max_averaging_orders': '6', 'deviation_pct': '1.5',
            'take_profit_avg_pct': '1', 'ladder_shape': 'gentle'}
    form.update(over)
    return form


def _row(**over):
    return bot_from_form(resolve_ladder(_form(**over)), 'bybit')


# --- U184: the shape gives the orders --------------------------------------------

def spec_U184_every_shape_spends_the_money_and_the_engine_takes_it():
    """Base + add-ons within investment x leverage (M2), all but the share
    kept for fees, whatever the market, shape and count, and growing by the
    shape's own factors. SABOTAGE: a ladder that ignores the size factor is
    refused by M2 or leaves money idle."""
    for shape, (k, step) in SHAPES.items():
        for n in (1, 2, 5, 9):
            for market, symbol in (('linear', 'BTCUSDT'), ('inverse', 'BTCUSD')):
                row = _row(ladder_shape=shape, max_averaging_orders=str(n), market_type=market,
                           symbol=symbol, deviation_pct='0.5')
                cfg = validate_config(json.loads(json.dumps(row)))
                room = 10000.0 * 3
                assert cfg['ladder_total_notional'] <= room * LADDER_SHARE * 1.001, (shape, n)
                assert cfg['ladder_total_notional'] >= room * LADDER_SHARE * 0.99, (shape, n)
                assert cfg['order_size_multiplier'] == k
                assert cfg['deviation_step_multiplier'] == step
                assert cfg['base_order_size'] == cfg['safety_order_size']


def spec_U184_it_keeps_the_share_for_fees_and_replaces_what_was_in_the_boxes():
    """The worked-out size is the quick setup's (one function), and anything
    typed gives way to the shape. SABOTAGE: spend it all and the share is gone;
    keep the typed box and the shape did nothing."""
    k = SHAPES['gentle'][0]
    want = 10000.0 * 3 * 0.98 / (1 + sum(k ** i for i in range(6)))
    assert abs(order_unit(10000.0, 3.0, 6, k) - want) < want * 1e-3
    got = resolve_ladder(_form(base_order_size='7', safety_order_size='7'))
    assert got['base_order_size'] == got['safety_order_size'] != '7'
    bot = quick_bot({'preset': 'dca_long', 'symbol': 'BTCUSDT', 'capital': '10000',
                     'caution': 'balanced'}, 'bybit', MARK)
    assert bot['base_order_size'] == order_unit(10000.0, 3, 5, 1.5)   # the quick setup's unchanged
    assert bot['order_size_multiplier'] == 1.5 and bot['deviation_step_multiplier'] == 1.4


def spec_U184_margin_spot_reads_its_own_leverage():
    """Spot's multiple is spot_leverage, with the switch; without the switch
    it is 1x. SABOTAGE: read 'leverage' and a margin spot ladder is a third of
    what it could be."""
    plain = resolve_ladder(_form(market_type='spot', leverage=''))
    margin = resolve_ladder(_form(market_type='spot', leverage='', spot_borrow='1',
                                  spot_leverage='3'))
    assert abs(float(margin['base_order_size']) / float(plain['base_order_size']) - 3.0) < 0.01
    assert validate_config(bot_from_form(margin, 'bybit'))['ladder_total_notional'] <= 30000.0


def spec_U184_blank_leverage_and_unreadable_money_are_said_by_the_gates():
    """A blank leverage is the engine's 1x. No investment yet: no sizes, so the
    usual refusal names it, and the growth still fills. Sizes in coins cannot
    be worked out here (D89): the form keeps them."""
    assert abs(float(resolve_ladder(_form(leverage=''))['base_order_size']) * 3
               / float(resolve_ladder(_form())['base_order_size']) - 1) < 0.01
    none = resolve_ladder(_form(capital=''))
    assert none['base_order_size'] == '' and none['order_size_multiplier'] == '1.25'
    assert resolve_ladder(_form(capital='', base_order_size='7'))['base_order_size'] == ''
    coin = _form(size_in='coin', base_order_size='1')
    assert resolve_ladder(coin) is coin
    assert 'First order size' in missing_required('martingale', _form(size_in='coin'))


def spec_U184_a_shape_needs_no_sizes_typed_own_orders_still_do():
    """SABOTAGE: require the sizes under a shape and a blank form is refused;
    drop the requirement for own orders and the engine's refusal comes late."""
    assert missing_required('martingale', _form()) == []
    miss = missing_required('martingale', _form(ladder_shape=OWN))
    assert 'First order size' in miss and 'First add-on order size' in miss
    assert 'First order size' in missing_required('martingale', {k: v for k, v in _form().items()
                                                                if k != 'ladder_shape'})


# --- U185: the choice on the form --------------------------------------------------

def spec_U185_a_new_form_starts_on_a_shape_and_a_form_with_orders_keeps_them():
    """Blank: the default, its sizes saying they are worked out, with no star.
    Typed orders: own. Orders exactly a shape: that shape, so "change something"
    from the review comes back as it went. An edit stays on its own orders, a
    running bot's sizes changing only when he picks. SABOTAGE: infer on an edit
    and raising a live bot's investment resizes its orders unasked."""
    assert shape_of({}) == DEFAULT_SHAPE
    assert shape_of({'base_order_size': '50', 'safety_order_size': '50', 'capital': '1000',
                     'max_averaging_orders': '3'}) == OWN
    worked = form_from_bot(_row(ladder_shape='steep'))
    assert shape_of(worked) == 'steep'
    assert shape_of(worked, edit=True) == OWN
    assert shape_of(dict(worked, ladder_shape='even'), edit=True) == 'even'
    page = advanced_page('martingale', {}, ['Bybit demo'], 0)
    head = page.partition('class="adv"')[0]
    assert head.count('name="ladder_shape"') == 1
    assert re.search(r'<option value="gentle" selected>', head)
    assert head.index('name="ladder_shape"') < head.index('name="base_order_size"')
    assert 'First order size *' not in head and 'placeholder="worked out for you"' in head
    own = advanced_page('martingale', {'ladder_shape': OWN}, ['Bybit demo'], 0)
    assert 'First order size *' in own and 'worked out for you' not in own
    assert 'name="ladder_shape"' not in advanced_page('grid', {}, ['Bybit demo'], 0)


def spec_U185_the_row_never_holds_a_shape_and_round_trips():
    """A shape is the form's: the row holds the engine's keys, and form and row
    round-trip (U19). SABOTAGE: write the shape to the row and the engine
    refuses the key."""
    row = _row(ladder_shape='steep')
    assert 'ladder_shape' not in row and validate_config(json.loads(json.dumps(row)))
    assert bot_from_form(form_from_bot(row), 'bybit') == row
    assert inferred_shape(row) == 'steep'
    typed = bot_from_form(dict(_form(ladder_shape=OWN), base_order_size='100',
                               safety_order_size='100'), 'bybit')
    assert bot_from_form(resolve_ladder(form_from_bot(typed)), 'bybit') == typed
    assert inferred_shape(typed) is None


def spec_U185_typing_an_order_switches_to_your_own_and_the_script_fills_the_boxes():
    """The page's script fills the boxes from the server's answer and a person
    typing into one switches the choice to their own; a form with no script is
    worked out at the review. The quick form offers shapes for a DCA only.
    SABOTAGE: drop the listener and the next answer overwrites what was typed."""
    page = advanced_page('martingale', {}, ['Bybit demo'], 0)
    assert "shape.value='own'" in page and "querySelector('[data-fill]')" in page
    for name in ('base_order_size', 'safety_order_size', 'order_size_multiplier',
                 'deviation_step_multiplier'):
        assert f"'{name}'" in page, name
    quick = quick_page(['Bybit demo'], kind='dca')
    assert '<tr class="only-dca">' in quick and 'as "How careful?" says' in quick
    assert 'name="ladder_shape"' not in quick_page(['Bybit demo'], kind='grid')
    bot = quick_bot({'preset': 'dca_long', 'symbol': 'BTCUSDT', 'capital': '10000',
                     'caution': 'balanced', 'ladder_shape': 'even'}, 'bybit', MARK)
    assert bot['order_size_multiplier'] == 1.0 and bot['deviation_step_multiplier'] == 1.0
    assert bot['base_order_size'] == order_unit(10000.0, 3, 5, 1.0)


# --- U186: typed orders against the money --------------------------------------------

def spec_U186_it_says_when_the_orders_stop_matching_the_money():
    """Too much, idle, or worked out; nothing to say when typed orders use it
    all. SABOTAGE: swap the comparison and an overdrawn ladder reads as idle."""
    typed = dict(_row(), base_order_size=20000.0, safety_order_size=20000.0)
    assert 'too much' in fit_words(typed)
    idle = dict(_row(), base_order_size=100.0, safety_order_size=100.0)
    assert 'would sit unused' in fit_words(idle)
    assert fit_words(_row()).startswith('Worked out for you')
    full = dict(_row(ladder_shape='even'), base_order_size=4250.0, safety_order_size=4200.0)
    assert ladder_total(full) > 29000 and fit_words(full) is None
    assert fit_words(dict(_row(), size_in='coin')) is None      # D89: no price here


def spec_U186_an_order_under_the_minimum_says_what_would_fund_the_ladder():
    """Under the market's smallest: refused, naming the investment this
    ladder's shape needs, which then clears it. SABOTAGE: a wrong scale and the
    named investment is still refused."""
    row = _row(capital='20', ladder_shape='steep')
    cfg = validate_config(json.loads(json.dumps(row)))
    said = order_minimum_problem(cfg, LIN, MARK)
    assert said and 'use fewer add-ons' in said
    least = float(re.search(r'needs an investment of about ([\d.e+]+)', said).group(1))
    enough = validate_config(json.loads(json.dumps(_row(capital=f'{least * 1.02:g}',
                                                        ladder_shape='steep'))))
    assert order_minimum_problem(enough, LIN, MARK) is None


# --- U187: the table -----------------------------------------------------------------

def _rows(cfg, adapter=LIN):
    return numbers(cfg, adapter, MARK)['ladder']


def spec_U187_each_order_with_its_running_invested_average_and_liquidation():
    """Prices step by the schedule; invested is the money over the leverage,
    ending at the ladder's total; the average lies between the first and last
    order; the last order's liquidation is the review's estimate for the full
    ladder, within the fees it leaves out. SABOTAGE: a plain average of prices,
    or invested not divided by leverage, fails."""
    cfg = validate_config(json.loads(json.dumps(_row(max_averaging_orders='3'))))
    rows = _rows(cfg)
    assert len(rows) == 4 and rows[0]['price'] == MARK and rows[1]['price'] < MARK
    assert abs(rows[-1]['invested'] - cfg['ladder_total_notional'] / 3) < 1e-6
    money = sum(r['notional'] for r in rows)
    coins = sum(r['notional'] / r['price'] for r in rows)
    assert abs(rows[-1]['avg'] - money / coins) < 1e-6 and rows[-1]['price'] < rows[-1]['avg'] < MARK
    full = liquidation(cfg, LIN, MARK)['price']
    assert abs(rows[-1]['liq'] / full - 1.0) < 0.02, (rows[-1]['liq'], full)
    assert rows[0]['liq'] is None and all(r['reached'] for r in rows)   # small: none yet


def spec_U187_a_short_mirrors_and_spot_has_no_liquidation():
    short = validate_config(json.loads(json.dumps(_row(side='short', max_averaging_orders='3'))))
    rows = _rows(short)
    assert rows[1]['price'] > MARK and rows[0]['liq'] > rows[0]['price']
    assert abs(rows[-1]['liq'] / liquidation(short, LIN, MARK)['price'] - 1.0) < 0.02
    spot = validate_config(json.loads(json.dumps(_row(market_type='spot', leverage=''))))
    assert all(r['liq'] is None for r in _rows(spot))
    assert 'Liquidation' not in ladder_html(spot, {'ladder': _rows(spot)})


def spec_U187_a_coin_margined_ladder_is_in_usd_with_its_harmonic_average():
    """D165: sizes in USD, the average harmonic, the investment coins worth
    what the coin is. SABOTAGE: an arithmetic average, or the linear formula's
    liquidation, misses both."""
    cfg = validate_config(json.loads(json.dumps(_row(market_type='inverse', symbol='BTCUSD',
                                                     max_averaging_orders='3'))))
    rows = _rows(cfg, INV)
    money = sum(r['notional'] for r in rows)
    assert abs(rows[-1]['avg'] - money / sum(r['notional'] / r['price'] for r in rows)) < 1e-6
    assert abs(rows[-1]['liq'] / liquidation(cfg, INV, MARK)['price'] - 1.0) < 0.02
    # the balance at that price, exactly: the coins' worth, P&L, less maintenance
    p, a = rows[-1]['liq'], rows[-1]['avg']
    assert abs(10000.0 * p / MARK + money * (p / a - 1.0) - money * MM_RATE) < 1e-6
    got = ladder_html(cfg, {'ladder': rows}, 'USDT')
    assert 'Size USD' in got and 'USDT' not in got


def spec_U187_an_order_past_the_liquidation_says_it_never_fills():
    """Deep add-ons at high leverage: the position is liquidated before the
    order is reached, and the row says so. SABOTAGE: compare the wrong way and
    every row reads reachable."""
    cfg = validate_config(json.loads(json.dumps(_row(leverage='50', max_averaging_orders='5',
                                                     deviation_pct='5', ladder_shape='even'))))
    rows = _rows(cfg)
    assert any(not r['reached'] for r in rows) and rows[0]['reached']
    assert 'liquidated before this fills' in ladder_html(cfg, {'ladder': rows})


# --- U188: the form and the review, through the panel ----------------------------------

def _served():
    import spec_setup
    return spec_setup._served_fleet()


def _call(base, path, data=None):
    import spec_setup
    return spec_setup._call(base, path, data)


ADV = dict(_form(), how='advanced', fleet='0')


def spec_U188_the_live_answer_fills_the_boxes_and_shows_the_table():
    """Everything else filled: the table, the words and the worked-out values
    for the script. With a required field blank the boxes still fill. Own
    orders: no fill, and the words said. SABOTAGE: fill under own orders and the
    typed sizes are overwritten."""
    base, d, close = _served()
    try:
        got = _call(base, '/numbers', ADV)
        assert 'class="refusal"' not in got, got
        unit = order_unit(10000.0, 3.0, 6, 1.25)
        assert f'data-base_order_size="{unit:.10g}"' in got and 'data-order_size_multiplier="1.25"' in got
        assert 'class="ladder"' in got and 'Add-on 6' in got and 'Worked out for you' in got
        early = _call(base, '/numbers', dict(ADV, take_profit_avg_pct=''))
        assert 'data-fill' in early and 'the numbers show here once' in early
        own = dict(ADV, ladder_shape=OWN, base_order_size='100', safety_order_size='100')
        got = _call(base, '/numbers', own)
        assert 'data-fill' not in got and 'would sit unused' in got
        over = dict(own, base_order_size='40000', safety_order_size='40000')
        got = _call(base, '/numbers', over)
        assert 'class="refusal"' in got and 'too much' in html.unescape(got)
    finally:
        close()


def spec_U188_with_no_script_the_review_works_it_out_and_shows_the_table():
    """A form sent with its size boxes blank reaches the review with the
    orders in its row and the table above the typed name. SABOTAGE: skip the
    server's working out and the review says the sizes are still needed."""
    base, d, close = _served()
    try:
        page = _call(base, '/setup', dict(ADV, then='gates'))
        assert 'still needed' not in page, page[:400]
        raw = re.search(r'name="proposal" value="([^"]*)"', page).group(1)
        bot = json.loads(html.unescape(raw))['bot']
        assert bot['base_order_size'] == order_unit(10000.0, 3.0, 6, 1.25)
        assert 'ladder_shape' not in bot
        assert 'class="ladder"' in page and page.index('class="ladder"') < page.index('name="proposal"')
    finally:
        close()
