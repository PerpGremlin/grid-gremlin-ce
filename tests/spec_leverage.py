# Specs for SPEC R19 — account leverage as each exchange states it, and as
# if every bot's ladder had filled.

import copy
import time

from gridgremlin.report import account_leverage, leverage_lines


def _contract():
    return {
        'bots': {'linBTCUSDTl': {'position': 2.0, 'mark': 50_000.0},
                 'invBTCUSDl': {'position': 10_000.0, 'inverse': True},
                 'linADAUSDTl': {'position': 0.0, 'mark': 0.27},
                 'linSOLl': None},
        'terms': {'linBTCUSDTl': {'venue': 'bybit', 'notional': 150_000.0},
                  'invBTCUSDl': {'venue': 'bybit', 'notional': 8_000.0},
                  'linADAUSDTl': {'venue': 'bybit', 'notional': 5_000.0},
                  'spoETHUSDTl': {'venue': 'bybit', 'notional': None},
                  'linSOLl': {'venue': 'hyperliquid', 'notional': 900.0}},
        'account': {
            'bybit': {'notional': 120_000.0, 'equity': 40_000.0,
                      'collateral': 40_000.0},
            'hyperliquid': {'notional': 1_604.18, 'equity': 603.16,
                            'collateral': 1_100.9}}}


def spec_R19c_now_is_over_the_whole_collateral():
    """R19c (owner 2026-11-10): now is the account's positions over its
    whole collateral, the base the MMR and the if-filled line use. On a
    unified Hyperliquid account the exchange's account value is only the
    USDC held as perp margin (the headline said about twice the
    account's real leverage); that figure stays beside it, named as Hyperliquid's own. On
    Bybit, whose margin balance is its collateral, nothing changes.
    Sabotage: now over the account value again reads 2.66x here."""
    lev = account_leverage(_contract())
    assert abs(lev['hyperliquid']['now'] - 1_604.18 / 1_100.9) < 1e-9
    assert abs(lev['hyperliquid']['venue_now'] - 1_604.18 / 603.16) < 1e-9
    assert lev['bybit']['now'] == lev['bybit']['venue_now'] == 3.0
    now, _ = leverage_lines(_contract())['bybit']
    assert now == 'account leverage 3.00x (120k in positions on 40k)'
    gone = _contract()
    gone['account']['bybit'] = dict(gone['account']['bybit'], equity=None, collateral=None)
    assert account_leverage(gone)['bybit']['now'] is None   # unknown, not zero
    half = _contract()
    half['account']['hyperliquid'] = dict(half['account']['hyperliquid'], collateral=None)
    assert abs(account_leverage(half)['hyperliquid']['now'] - 1_604.18 / 603.16) < 1e-9


def spec_R19_if_every_order_filled_is_said_per_direction():
    """A long's ladder fills on a fall, a short's on a rise; one market
    cannot do both, so the two are never summed (the demo read 38.9x so).
    Each bot adds its most in the market less what it holds — a bot past
    its most adds nothing — over the whole collateral: on a unified
    Hyperliquid account the account value is only the margin held so far."""
    c = _contract()
    c['terms']['linBTCUSDTs'] = {'venue': 'bybit', 'notional': 30_000.0}
    lev = account_leverage(c)
    b = lev['bybit']
    # fall, the longs: BTC 150k - 100k = 50k; inverse 10k held > 8k -> 0; ADA 5k
    assert b['fall_notional'] == 120_000.0 + 50_000.0 + 0.0 + 5_000.0
    assert b['rise_notional'] == 120_000.0 + 30_000.0    # the short alone
    assert b['fall'] == 175_000.0 / 40_000.0 and b['unsized'] == 1
    h = lev['hyperliquid']
    assert abs(h['fall'] - (1_604.18 + 900.0) / 1_100.9) < 1e-9
    assert abs(h['rise'] - 1_604.18 / 1_100.9) < 1e-9    # no HL short here
    now, filled = leverage_lines(_contract())['hyperliquid']
    assert now == ("account leverage 1.46x (1,604 in positions on 1,101 collateral; "
                   "Hyperliquid's own figure 2.66x, on the 603 it holds as perp margin)")
    assert filled == ('if every order filled: 2.27x on a fall (2,504), '
                      '1.46x on a rise (1,604), on 1,101 collateral')
    assert '1 bots unsized' in leverage_lines(_contract())['bybit'][1]
    assert leverage_lines({'bots': {}, 'account': {'bybit': None}}) == {}


def spec_R19_every_surface_says_it_the_same_way():
    from gridgremlin import phone
    from panel.server import render
    import spec_panel
    c = copy.deepcopy(spec_panel.CONTRACT)
    c.update({k: v for k, v in _contract().items() if k == 'account'})
    c['terms'] = {}
    now, filled = leverage_lines(c)['bybit']
    page = render([('demo', c)])
    assert f'<div class="parts lev-now">{now}</div>' in page
    assert f'<div class="parts lev-filled">{filled}</div>' in page
    assert 'ggLev' in page and 'data-tog="lev">leverage: now</button>' in page   # the switch (D161: one toggle)

    class Box(phone.Box):
        def readout(self, fp):
            return c

        def snapshot(self, fp):
            return {'t': time.time(), 'equity': 40_000.0, 'bots': {}}

        def watchdog(self, fp):
            return {}, {}
    risk = phone.answer(Box(['configs/fleet.demo.json']), '/risk')
    assert now in risk and filled in risk


def spec_R19b_a_fleet_of_portfolio_rows_alone_still_reads_its_account():
    """R19b (2026-11-01): the account read went by the grid/DCA/trade rows'
    venues only, so the slow subaccount (one Portfolio Bot) read none — its
    balances "not read", nothing recorded (D162). Each Portfolio Bot's venue
    is read too, once. Sabotage: the rows' venues alone miss it."""
    from gridgremlin.report import account_venues
    pfo = {'bots': [{'strategy': 'portfolio', 'name': 'basket'}]}
    assert account_venues(pfo, {}) == ['bybit']
    both = {'bots': [{'strategy': 'grid', 'symbol': 'BTCUSDT'},
                     {'strategy': 'portfolio', 'name': 'b', 'venue': 'bybit'}]}
    assert account_venues(both, {'bybit': [object()]}) == ['bybit']        # once
    assert account_venues({'bots': []}, {'hyperliquid': [object()]}) == ['hyperliquid']
    assert list({}) == []                                    # sabotage: rows alone read nothing
