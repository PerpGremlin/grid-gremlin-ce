# Specs for D165 (SPEC M27, T7b, U182): a DCA bot on a coin-margined (inverse)
# perpetual. Its orders are USD contracts, its average harmonic, its P&L and
# fees in the coin and stated in USD: the adapter's maths (A4), never a second.

from gridgremlin.adapters import InverseAdapter, LinearAdapter
from gridgremlin.config import ConfigError, validate_config
from gridgremlin.ladder import ladder_summary, plan_martingale
from gridgremlin.replay import backtest_martingale

INV = InverseAdapter({'symbol': 'BTCUSD', 'qty_step': 1.0, 'price_tick': 0.5,
                      'min_qty': 1.0, 'settle_coin': 'BTC'})
LIN = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001, 'price_tick': 0.1,
                     'min_qty': 0.001, 'min_notional': 5.0, 'settle_coin': 'USDT'})


def _cfg(**over):
    row = {'strategy': 'martingale', 'market_type': 'inverse', 'symbol': 'BTCUSD',
           'side': 'long', 'capital': 1000.0, 'leverage': 10,
           'base_order_size': 1000.0, 'safety_order_size': 1000.0,
           'order_size_multiplier': 2.0, 'deviation_pct': 0.01,
           'deviation_step_multiplier': 2.0, 'max_averaging_orders': 3,
           'take_profit_avg_pct': 0.01}
    row.update(over)
    return validate_config(row)


def _bars(*ohlc):
    return [{'t': i * 300_000, 'o': o, 'h': h, 'l': l, 'c': c}
            for i, (o, h, l, c) in enumerate(ohlc)]


def spec_M27_an_inverse_dca_is_a_row_on_bybit_only():
    """Accepted on Bybit, sized in USD; refused on Hyperliquid, which has no
    coin-margined market. SABOTAGE: drop the venue check and the row passes."""
    c = _cfg()
    assert c['market_type'] == 'inverse' and c['ladder_notional'] == 10000.0
    assert c['ladder_total_notional'] == 1000.0 + 1000.0 * (1 + 2 + 4)
    try:
        _cfg(venue='hyperliquid', symbol='BTC')
    except ConfigError as e:
        assert 'no coin-margined market' in str(e)
    else:
        raise AssertionError('an inverse DCA on Hyperliquid passed')


def spec_M27_its_orders_are_usd_contracts_whatever_the_price():
    """Each safety order's quantity is its dollars, at any price."""
    orders = plan_martingale(_cfg(), INV, 80000.0, 80000.0)
    assert [o['qty'] for o in orders] == [1000.0, 2000.0, 4000.0]
    assert [o['price'] for o in orders] == [79200.0, 77600.0, 74400.0]
    assert [o['side'] for o in orders] == ['Buy'] * 3
    short = plan_martingale(_cfg(side='short'), INV, 80000.0, 80000.0)
    assert [o['price'] for o in short] == [80800.0, 82400.0, 85600.0]
    assert [o['qty'] for o in short] == [1000.0, 2000.0, 4000.0]
    coin = plan_martingale(_cfg(size_in='coin', base_order_size=0.01,
                                safety_order_size=0.01), INV, 80000.0, 80000.0)
    assert coin[0]['qty'] == 792.0                       # D89: coins × price


def spec_T7b_the_rehearsal_averages_harmonically():
    """Two fills, $1,000 at 80,000 and $1,000 at 79,200: the average is
    2000 / (1000/80000 + 1000/79200), under the arithmetic 79,600. SABOTAGE:
    an arithmetic average on the pretend venue and `basis` is 79,600."""
    r = backtest_martingale(_cfg(), INV, _bars(
        (80000, 80000, 80000, 80000), (80000, 80000, 79000, 79100)), spread_bps=0.0)
    want = 2000.0 / (1000.0 / 80000.0 + 1000.0 / 79200.0)
    assert r['held'] == 2000.0 and abs(r['basis'] - want) < 1e-6, r['basis']


def spec_T7b_a_round_pays_in_the_coin_stated_in_usd():
    """The round's profit is the adapter's: contracts × (1/entry − 1/exit) in
    the coin, at the exit's price in USD. Fees are on the contracts' dollars.
    SABOTAGE: book the fill as linear (no `inverse=` to the ledger) and the
    profit is off by the price's factor; a fee of qty × price is 80,000 times
    over."""
    r = backtest_martingale(_cfg(), INV, _bars(
        (80000, 80000, 80000, 80000), (80000, 81000, 80000, 81000)), spread_bps=0.0)
    assert r['rounds'] == 1 and r['held'] == 0.0
    exit_at = 80000.0 * 1.01
    coin = 1000.0 * (1.0 / 80000.0 - 1.0 / exit_at)
    assert abs(r['grid_profit'] - coin * exit_at) < 1e-6, r['grid_profit']
    assert abs(r['grid_profit'] - 10.0) < 1e-6                       # 1% of $1,000
    assert 0.0 < r['fees'] < 2.0, r['fees']
    assert abs(r['net'] - (r['grid_profit'] - r['fees'])) < 1e-9
    assert abs(r['total'] - r['net']) < 1e-9


def spec_T7b_a_short_wins_when_the_price_falls():
    r = backtest_martingale(_cfg(side='short'), INV, _bars(
        (80000, 80000, 80000, 80000), (80000, 80000, 79000, 79000)))
    assert r['rounds'] == 1 and r['held'] == 0.0
    assert r['grid_profit'] > 0.0, r['grid_profit']


def spec_T7b_a_linear_rehearsal_is_unchanged():
    """The same walk on a linear row keeps its own maths: 1,000 notional at
    80,000 floors to 0.012 BTC, sold 1% up."""
    cfg = _cfg(market_type='linear', symbol='BTCUSDT')
    r = backtest_martingale(cfg, LIN, _bars(
        (80000, 80000, 80000, 80000), (80000, 81000, 80000, 81000)), spread_bps=0.0)
    assert r['rounds'] == 1
    assert abs(r['grid_profit'] - 0.012 * 800.0) < 1e-6, r['grid_profit']


def spec_M27_the_loss_limit_reads_an_inverse_rounds_dollars():
    """max_loss in USD on a fall: closes the position and stops, as linear."""
    cfg = _cfg(max_loss=50, max_loss_since='2020-01-01T00:00:00Z')
    r = backtest_martingale(cfg, INV, _bars(
        (80000, 80000, 80000, 80000), (80000, 80000, 70000, 70000),
        (70000, 70000, 60000, 60000)))
    assert r['held'] == 0.0 and r['ended'], r
    assert 'loss' in r['ended'], r['ended']


def spec_M27_the_summarys_average_is_the_coin_weighted_one():
    """U52's ladder box is in fractions of the base price: dollars over coins,
    already harmonic. Base and one add-on at -1%."""
    rows = ladder_summary(_cfg(max_averaging_orders=1))
    assert abs(rows[1]['avg_pct'] - (2.0 / (1.0 + 1.0 / 0.99) - 1.0)) < 1e-12


def spec_U182_the_preview_counts_contracts():
    """Each order's quantity on review is its contracts, since the review
    calls them contracts. SABOTAGE: notional / price, and they read as coins."""
    from panel.create import martingale_preview, order_minimum_problem
    rows, cum = martingale_preview(_cfg(), 80000.0)
    assert [r['qty'] for r in rows] == [1000.0, 1000.0, 2000.0, 4000.0] and cum == 8000.0
    assert order_minimum_problem(_cfg(), INV, 80000.0) is None
    too_small = dict(_cfg(), base_order_size=0.4)
    assert 'smallest order' in order_minimum_problem(too_small, INV, 80000.0)


def spec_U182_a_long_is_liquidated_sooner_when_its_collateral_is_the_coin():
    """Coin-margined, the investment is coins and falls with the price it is
    long of, so the estimate sits nearer than the same row in USDT. A short's
    coins rise as it loses: at 1x it holds to the end of the path. SABOTAGE:
    a constant investment and the short at 1x meets a level."""
    from panel.consequence import liquidation
    inv = liquidation(_cfg(), INV, 80000.0)
    usd = liquidation(_cfg(market_type='linear', symbol='BTCUSDT'), LIN, 80000.0)
    assert inv['price'] and usd['price'] and inv['price'] > usd['price'], (inv, usd)
    got = liquidation(_cfg(side='short', leverage=1, capital=8000.0), INV, 80000.0)
    assert got['price'] is None, got


def spec_U182_a_quick_dca_on_btcusd_is_an_inverse_row():
    """The quick setup's refusal is gone: the market the symbol is listed as is
    the row's. SABOTAGE: 'linear' hard-coded in the DCA branch and the row is a
    USDT perpetual's, which A8 refuses on BTCUSD."""
    from panel.setup import quick_bot
    bot = quick_bot({'preset': 'dca_long', 'caution': 'balanced', 'symbol': 'BTCUSD',
                     'capital': '1000'}, 'bybit', 80000.0, market_type='inverse')
    assert bot['market_type'] == 'inverse' and bot['strategy'] == 'martingale'
    cfg = validate_config({k: v for k, v in bot.items() if not k.startswith('_')})
    assert cfg['ladder_total_notional'] <= cfg['ladder_notional']


def spec_U182_the_form_offers_it_and_says_usd():
    """The DCA form's market type offers inverse; the order sizes carry U160's
    USD words."""
    from panel.setup import INVERSE_WORDS, MARTINGALE
    row = next(r for r in MARTINGALE['The basics'] if r[0] == 'market_type')
    assert row[2] == 'choice:linear|inverse|spot'
    assert 'in USD' in INVERSE_WORDS['base_order_size'][1]
    assert 'in USD' in INVERSE_WORDS['safety_order_size'][1]


def spec_U182_the_review_says_usd_and_the_owners_name():
    """The sentence's orders in USD; the bot named as he named it."""
    from panel.html_bits import plain_name
    from panel.setup import sentence
    said = sentence(_cfg(), 80000.0)
    said = said if isinstance(said, str) else ' '.join(said)
    assert 'opens with 1,000 USD' in said and '8,000 USD in total' in said, said
    assert 'your BTC is the collateral' in said, said
    assert plain_name(_cfg()).startswith('BTCUSD Inverse Futures DCA'), plain_name(_cfg())


def spec_M27_its_coin_is_switched_on_as_collateral_at_build():
    """The unified account refuses an inverse order (110101) until its coin is
    collateral. SABOTAGE: drop the inverse branch and the first order is refused
    on the venue."""
    from gridgremlin.main import collateral_coin
    spec = {'settle_coin': 'BTC', 'base_coin': 'BTC'}
    assert collateral_coin(_cfg(), spec) == 'BTC'
    assert collateral_coin(_cfg(market_type='linear', symbol='BTCUSDT'), spec) is None
    assert collateral_coin({'market_type': 'inverse', 'strategy': 'grid'}, spec) is None
    assert collateral_coin({'market_type': 'spot', 'strategy': 'martingale',
                            'spot_borrow': True}, spec) == 'BTC'
