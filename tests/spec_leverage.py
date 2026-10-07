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


def spec_R19_now_is_the_exchange_own_figure():
    """Hyperliquid's own ratio — its total position value over its account
    value (2.66x, 2026-10-06) — not a figure of ours; on Bybit, which states
    none, its own position values over its margin balance."""
    lev = account_leverage(_contract())
    assert abs(lev['hyperliquid']['now'] - 1_604.18 / 603.16) < 1e-9
    assert lev['bybit']['now'] == 3.0
    gone = _contract()
    gone['account']['bybit'] = dict(gone['account']['bybit'], equity=None)
    assert account_leverage(gone)['bybit']['now'] is None   # unknown, not zero


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
    assert now == 'account leverage 2.66x (1,604 in positions on 603)'
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
    assert 'ggLev' in page and 'data-lev="filled"' in page   # the switch

    class Box(phone.Box):
        def readout(self, fp):
            return c

        def snapshot(self, fp):
            return {'t': time.time(), 'equity': 40_000.0, 'bots': {}}

        def watchdog(self, fp):
            return {}, {}
    risk = phone.answer(Box(['configs/fleet.demo.json']), '/risk')
    assert now in risk and filled in risk
