"""D78, SPEC family H — the portfolio row: the gate (H1) and the plan (H3),
pure, with hand numbers."""
from gridgremlin.config import ConfigError, validate_config
from gridgremlin.portfolio import hedge_ratio, plan_portfolio, validate_portfolio

ROW = {'strategy': 'portfolio', 'name': 'carry', 'capital': 90000,
       'assets': [{'coin': 'BTC', 'weight': 0.4}, {'coin': 'ETH', 'weight': 0.3},
                  {'coin': 'SOL', 'weight': 0.3}],
       'hedge': {'product': 'inverse', 'ratio': 1.0},
       'rebalance': {'cash_reserve': 0}}          # hand numbers: no fee reserve (pinned in its own spec)
PX = {'BTC': 60000.0, 'ETH': 3000.0, 'SOL': 150.0}
DAY = 24 * 3_600_000


def _row(**over):
    r = dict(ROW)
    r.update(over)
    return r


def _refused(row, *fragments):
    try:
        validate_config(row)
    except ConfigError as e:
        for frag in fragments:
            assert frag in str(e), f'expected {frag!r} in {str(e)!r}'
        return str(e)
    raise AssertionError(f'accepted, expected refusal: {fragments}')


def spec_H1_the_row_is_its_assets_hedges_clock_and_risk_with_stated_defaults():
    cfg = validate_config(_row())
    assert cfg['strategy'] == 'portfolio' and cfg['botid'] == 'pfocarry'
    assert cfg['venue'] == 'bybit' and cfg['account'] is None      # the fleet's, once in one
    assert [a['coin'] for a in cfg['assets']] == ['BTC', 'ETH', 'SOL']
    assert cfg['hedges'] == {c: {'product': 'inverse', 'ratio': 1.0} for c in ('BTC', 'ETH', 'SOL')}
    assert cfg['rebalance'] == {'every_hours': 24.0, 'drift_pct': 0.05, 'min_notional': 0.0, 'cash_reserve': 0.0}
    assert validate_config({k: v for k, v in _row().items() if k != 'rebalance'})['rebalance']['cash_reserve'] == 0.003
    assert cfg['funding_rule'] == {'stand_down_below': 0.0, 'trailing_days': 7.0}
    assert cfg['risk'] == {'margin_floor_pct': 0.4, 'basis_stop_pct': 0.01, 'max_weight': 0.5}
    assert 'regime' not in cfg and 'margin' not in cfg and cfg['short_products'] == {}
    per = validate_config(_row(hedge={'BTC': {'product': 'usdt', 'ratio': 0.7}, 'SOL': {'ratio': 0}}))
    assert per['hedges'] == {'BTC': {'product': 'usdt', 'ratio': 0.7}, 'ETH': {'product': 'inverse', 'ratio': 1.0},
                             'SOL': {'product': 'inverse', 'ratio': 0.0}}
    short = validate_config(_row(assets=[{'coin': 'BTC', 'weight': 0.5}, {'coin': 'ETH', 'weight': -0.5}],
                                 hedge={'ETH': {'product': 'usdt'}}))
    assert list(short['hedges']) == ['BTC'] and short['short_products'] == {'ETH': 'usdt'}
    tilted = validate_config(_row(regime={'tilt': 0.3, 'hold_hours': 24}))
    assert tilted['regime'] == {'tilt': 0.3, 'hold_hours': 24.0, 'source': 'structure'}
    lev = validate_config(_row(spot_borrow=True, margin={'spot_leverage': 1.5},
                               assets=[{'coin': 'BTC', 'weight': 0.5}, {'coin': 'ETH', 'weight': 0.5},
                                       {'coin': 'SOL', 'weight': 0.5}]))
    assert lev['margin'] == {'spot_leverage': 1.5, 'borrow_apr_max': 0.08}
    loss = validate_config(_row(risk={'max_loss': 500, 'max_loss_since': '2026-10-10T00:00:00Z'}))
    assert loss['risk']['max_loss'] == 500.0 and loss['risk']['max_loss_since_ms'] == 1791590400000
    assert validate_portfolio(_row())['botid'] == 'pfocarry'                 # the module's own door


def spec_H1_every_shape_the_design_refuses_is_refused_by_name():
    _refused(_row(name=None), "'name' is required")
    _refused(_row(name='Carry!'), "'name'")
    _refused(_row(assets=[{'coin': 'BTC', 'weight': 0.5}, {'coin': 'BTC', 'weight': 0.5}]), 'named twice')
    _refused(_row(assets=[{'coin': 'BTC', 'weight': 0.4}, {'coin': 'ETH', 'weight': 0.4}]), "sum to 0.8, not 1")
    _refused(_row(assets=[{'coin': 'BTC', 'weight': 0.0}, {'coin': 'ETH', 'weight': 1.0}]), 'weight of zero')
    _refused(_row(assets=[{'coin': 'BTC', 'weight': 0.6}, {'coin': 'ETH', 'weight': 0.4}]), "above 'max_weight'")
    _refused(_row(hedge={'DOGE': {'ratio': 1}}), 'not in')
    _refused(_row(assets=[{'coin': 'BTC', 'weight': 0.5}, {'coin': 'ETH', 'weight': -0.5}],
                  hedge={'ETH': {'ratio': 1}}), 'its own hedge')
    _refused(_row(hedge={'product': 'spot'}), "'product'")
    _refused(_row(hedge={'ratio': 4}), "'ratio'")
    _refused(_row(regime={'tilt': 0.3}), "'hold_hours' is required")
    _refused(_row(regime={'hold_hours': 24}), "'tilt' is required")
    _refused(_row(margin={'spot_leverage': 2}), "'spot_borrow': true")
    _refused(_row(spot_borrow=True, margin={'spot_leverage': 2}), 'sum to 1, not 2')
    _refused(_row(risk={'max_loss': 100}), 'travel together')
    _refused(_row(rebalance={'drift_pct': 0}), "'drift_pct'")
    _refused(_row(account='Main Account'), "'account'")
    _refused(_row(symbol='BTCUSDT'), 'unknown key')
    _refused(_row(funding_rule={'stand_down_below': 2}), "'stand_down_below'")


def spec_H3_between_ticks_nothing_is_wanted_and_at_a_tick_the_weights_then_the_hedges():
    cfg = validate_config(_row())
    book = {'coins': {'BTC': 1.0, 'ETH': 10.0}, 'hedged': {}, 'cash': 0.0}
    quiet = plan_portfolio(cfg, book, PX, now_ms=DAY, last_tick_ms=DAY - 3_600_000)
    assert quiet == {'tick': False, 'orders': [], 'targets': {}}
    plan = plan_portfolio(cfg, book, PX, now_ms=DAY, last_tick_ms=0)
    assert plan['tick']
    # the stack is 60,000 + 30,000 = 90,000: BTC wants 36,000 (has 60,000, 27% out),
    # ETH wants 27,000 (has 30,000, 3% — inside the drift), SOL wants 27,000 (has none)
    by = {(o['leg'], o['side']): o for o in plan['orders']}
    assert abs(by[(('spot', 'BTC'), 'sell')]['coins'] - 0.4) < 1e-9
    assert (('spot', 'ETH'), 'sell') not in by and (('spot', 'ETH'), 'buy') not in by
    assert abs(by[(('spot', 'SOL'), 'buy')]['coins'] - 180.0) < 1e-9
    # then every hedge to ratio 1 of what is held after the weights moved
    assert abs(by[(('hedge', 'BTC'), 'sell')]['coins'] - 0.6) < 1e-9
    assert abs(by[(('hedge', 'ETH'), 'sell')]['coins'] - 10.0) < 1e-9
    assert abs(by[(('hedge', 'SOL'), 'sell')]['coins'] - 180.0) < 1e-9
    assert [o['why'] for o in plan['orders']] == ['weight', 'weight', 'hedge', 'hedge', 'hedge']
    assert plan['targets']['BTC'] == {'weight_value': 36000.0, 'ratio': 1.0, 'hedge_coins': 0.6}
    # a book already at its weights and hedges wants nothing
    settled = {'coins': {'BTC': 0.6, 'ETH': 9.0, 'SOL': 180.0}, 'hedged': {'BTC': 0.6, 'ETH': 9.0, 'SOL': 180.0}}
    assert plan_portfolio(cfg, settled, PX, DAY, 0)['orders'] == []


def spec_H3_funding_buys_spot_pro_rata_and_dust_is_left():
    cfg = validate_config(_row(rebalance={'min_notional': 500, 'cash_reserve': 0}))
    book = {'coins': {'BTC': 0.6, 'ETH': 9.0, 'SOL': 180.0}, 'hedged': {'BTC': 0.6, 'ETH': 9.0, 'SOL': 180.0},
            'cash': 9000.0}
    plan = plan_portfolio(cfg, book, PX, DAY, 0)
    buys = [o for o in plan['orders'] if o['why'] == 'cash buys spot']
    assert [(o['leg'][1], round(o['coins'] * PX[o['leg'][1]])) for o in buys] == [('BTC', 3600), ('ETH', 2700), ('SOL', 2700)]
    # the hedges follow the bigger holding only where the drift is past 5% — 3,600 on 36,000 is 10%
    hedges = [o for o in plan['orders'] if o['why'] == 'hedge']
    assert [o['leg'][1] for o in hedges] == ['BTC', 'ETH', 'SOL'] and all(o['side'] == 'sell' for o in hedges)
    dust = {'coins': {'BTC': 0.6, 'ETH': 9.0, 'SOL': 180.0}, 'hedged': {'BTC': 0.6, 'ETH': 9.0, 'SOL': 180.0},
            'cash': 30.0}                                           # 12 / 9 / 9 quote: under 500
    assert plan_portfolio(cfg, dust, PX, DAY, 0)['orders'] == []


def spec_H3_the_regime_leans_the_hedge_and_the_funding_rule_stands_it_down():
    cfg = validate_config(_row(regime={'tilt': 0.3, 'hold_hours': 24}))
    assert hedge_ratio(cfg, 'BTC', 'up') == 0.7 and hedge_ratio(cfg, 'BTC', 'down') == 1.3
    assert hedge_ratio(cfg, 'BTC', 'range') == 1.0 and hedge_ratio(cfg, 'BTC', None) == 1.0
    assert hedge_ratio(cfg, 'BTC', 'up', funding_trailing=-0.001) == 0.0      # paying to be hedged: no
    assert hedge_ratio(cfg, 'BTC', 'up', funding_trailing=0.0) == 0.7          # at the floor: held
    assert hedge_ratio(validate_config(_row()), 'BTC', 'up') == 1.0            # no regime: no lean
    assert hedge_ratio(cfg, 'DOGE') == 0.0                                      # not an asset
    book = {'coins': {'BTC': 0.6, 'ETH': 9.0, 'SOL': 180.0}, 'hedged': {'BTC': 0.6, 'ETH': 9.0, 'SOL': 180.0}}
    plan = plan_portfolio(cfg, book, PX, DAY, 0, regimes={'BTC': 'up', 'ETH': 'down'},
                          funding_trailing={'SOL': -0.002})
    by = {o['leg'][1]: o for o in plan['orders']}
    assert by['BTC']['side'] == 'buy' and abs(by['BTC']['coins'] - 0.18) < 1e-9     # 0.6 -> 0.42
    assert by['ETH']['side'] == 'sell' and abs(by['ETH']['coins'] - 2.7) < 1e-9     # 9 -> 11.7
    assert by['SOL']['side'] == 'buy' and abs(by['SOL']['coins'] - 180.0) < 1e-9 \
        and by['SOL']['why'] == 'funding stood the hedge down'


def spec_H3_an_outright_short_is_sized_from_the_stack_and_never_hedged():
    cfg = validate_config(_row(assets=[{'coin': 'BTC', 'weight': 0.5}, {'coin': 'ETH', 'weight': -0.5}]))
    # a 60,000 stack: half long BTC (0.5 coins), half short ETH — that half's cash is the short's margin
    book = {'coins': {'BTC': 0.5}, 'hedged': {'BTC': 0.5}, 'shorts': {}, 'cash': 30000.0}
    plan = plan_portfolio(cfg, book, PX, DAY, 0)
    by = {o['leg']: o for o in plan['orders']}
    assert by[('short', 'ETH')]['side'] == 'sell' and abs(by[('short', 'ETH')]['coins'] - 10.0) < 1e-9
    assert by[('short', 'ETH')]['why'] == 'outright short' and ('hedge', 'ETH') not in by
    assert plan['targets']['ETH'] == {'short_coins': 10.0}
    assert ('spot', 'BTC') not in {o['leg'] for o in plan['orders']}           # the cash is not swept into BTC
    held = {'coins': {'BTC': 0.5}, 'hedged': {'BTC': 0.5}, 'shorts': {'ETH': 10.0}, 'cash': 30000.0}
    assert plan_portfolio(cfg, held, PX, DAY, 0)['orders'] == []


def spec_H3_the_cash_step_keeps_a_reserve_for_the_buys_own_fees():
    """Three restarts on the carry fleet (2026-10-10): the cash split three
    ways to the cent, the first two buys' fees left the third refused."""
    from gridgremlin.portfolio import CASH_RESERVE
    cfg = validate_config({k: v for k, v in _row().items() if k != 'rebalance'})     # the default reserve
    book = {'coins': {'BTC': 0.6, 'ETH': 9.0, 'SOL': 180.0}, 'hedged': {'BTC': 0.6, 'ETH': 9.0, 'SOL': 180.0},
            'cash': 30930.31}
    plan = plan_portfolio(cfg, book, PX, DAY, 0)
    spent = sum(o['coins'] * PX[o['leg'][1]] for o in plan['orders'] if o['why'] == 'cash buys spot')
    assert abs(spent - 30930.31 * (1 - CASH_RESERVE)) < 1e-6 and 0.002 <= CASH_RESERVE <= 0.005
    assert spent + 3 * 0.001 * spent / 3 < 30930.31                       # fees at 0.1% per buy fit inside


def spec_H3_with_margin_the_targets_are_weight_times_equity_and_the_cash_goes_negative():
    """H1's margin, levered by the planner: weights summing to spot_leverage,
    each target weight × equity, the coins held spot_leverage × equity, the
    quote beyond the cash lent by the venue (a negative cash pot)."""
    cfg = validate_config(_row(spot_borrow=True, margin={'spot_leverage': 1.5}, rebalance={'cash_reserve': 0},
                               assets=[{'coin': 'BTC', 'weight': 0.75}, {'coin': 'ETH', 'weight': 0.75}],
                               risk={'max_weight': 0.75}))
    px = {'BTC': 60000.0, 'ETH': 3000.0}
    plan = plan_portfolio(cfg, {'coins': {}, 'hedged': {}, 'cash': 100000.0}, px, DAY, None)
    buys = {}
    for o in plan['orders']:
        if o['leg'][0] == 'spot':
            buys[o['leg'][1]] = buys.get(o['leg'][1], 0.0) + o['coins'] * px[o['leg'][1]]
    assert {c: round(v) for c, v in buys.items()} == {'BTC': 75000, 'ETH': 75000}      # 150,000 of spot on 100,000
    hedges = {o['leg'][1]: round(o['coins'] * px[o['leg'][1]]) for o in plan['orders'] if o['leg'][0] == 'hedge'}
    assert hedges == {'BTC': 75000, 'ETH': 75000}                                      # hedged one for one
    # the book a read later: the coins, and the loan as a negative cash — equity 100,000, nothing wanted
    book = {'coins': {'BTC': 1.25, 'ETH': 25.0}, 'hedged': {'BTC': 1.25, 'ETH': 25.0}, 'cash': -50000.0}
    assert plan_portfolio(cfg, book, px, 2 * DAY, DAY)['orders'] == []
    # the price halves: equity 25,000 (75,000 of coins, −50,000 owed), the targets 18,750 each — the
    # weight step sells spot (repaying) and the hedges follow
    half = {'BTC': 30000.0, 'ETH': 1500.0}
    plan = plan_portfolio(cfg, book, half, 3 * DAY, DAY)
    sells = {o['leg'][1]: round(o['coins'] * half[o['leg'][1]]) for o in plan['orders'] if o['leg'][0] == 'spot'}
    assert sells == {'BTC': 18750, 'ETH': 18750} and all(o['side'] == 'sell' for o in plan['orders'] if o['leg'][0] == 'spot')
