"""The pre-real-money review (2026-10-11): what it found stays fixed —
I7 (a part-filled order), X14a (the loss limit's window), F15d (the cap on
an unread wallet), M23a (the last tranche), M2a (a short coin ladder)."""
from gridgremlin.adapters import adapter_for

D = 86_400_000


def spec_I7_a_part_filled_order_matches_on_what_rests_and_is_never_amended():
    from gridgremlin.apply import matches
    from gridgremlin.bot_reconcile import ReconcileMixin
    # a spot exit for 0.01 that sold 0.004: the plan is now the 0.006 left
    want = {'side': 'Sell', 'reduce_only': False, 'price': 2000.0, 'qty': 0.006, 'rung': 5}
    rest = {'side': 'Sell', 'reduce_only': False, 'price': 2000.0, 'qty': 0.01,
            'cum_exec_qty': 0.004, 'link_id': 'spoETHUSDTl-5-1', 'order_id': 'x'}
    assert matches(want, rest, qty_step=0.00001)                       # left alone
    assert not matches(dict(want, qty=0.003), rest, qty_step=0.00001)
    # when it does need a new size it is cancelled and placed fresh — never
    # amended (Bybit's amend takes the new TOTAL, filled part included)
    calls = []

    class Client:
        def amend_order(self, *a): calls.append(('amend',) + a)
        def cancel_order(self, *a): calls.append(('cancel',) + a)
        def place_order(self, *a, **k): calls.append(('place',) + a)

    class Notify:
        def event(self, *a, **k): pass

    class Bot(ReconcileMixin):
        botid = 'spoETHUSDTl'
        cfg = {'market_type': 'spot', 'symbol': 'ETHUSDT'}
        adapter = adapter_for('spot', {'symbol': 'ETHUSDT', 'qty_step': 0.00001, 'price_tick': 0.01,
                                       'min_qty': 0.0001, 'min_notional': 1})
        client, notify, _backoff_until, _gen, _exit_side, _borrow = Client(), Notify(), 0.0, 0, 'Sell', False
        def _cooling(self, key, now): return False
        def _would_cross(self, want, bid, ask): return False
        def _make_link(self, rung): return f'spoETHUSDTl-{rung}-2'
        def _do_backoff(self, now): pass
    smaller = dict(want, qty=0.003)
    Bot()._reconcile([rest], [smaller], 1999.0, 2001.0, now=100.0)
    kinds = [c[0] for c in calls]
    assert 'amend' not in kinds and kinds == ['cancel', 'place'], kinds
    assert calls[1][4] == '0.003'                                       # the size the plan wants
    # an unfilled order's size change is still a plain amend
    calls.clear()
    Bot()._reconcile([dict(rest, cum_exec_qty=0.0)], [dict(want, qty=0.008)], 1999.0, 2001.0, now=100.0)
    assert [c[0] for c in calls] == ['amend']
    # in a backoff (B7) no create would follow, so the part-filled order rests as it is
    calls.clear()
    b = Bot(); b._backoff_until = 1e12
    b._reconcile([rest], [smaller], 1999.0, 2001.0, now=100.0)
    assert calls == []


def _loss_bot(fills, now):
    from gridgremlin.bot_stops import StopsMixin
    from gridgremlin.bot_basis import BasisMixin
    from gridgremlin.adapters import LinearAdapter

    class Client:
        def fills_history(self, mt, sym, a, b):
            return [f for f in fills if a <= f['time_ms'] <= b]

    class Bot(StopsMixin, BasisMixin):
        botid = 'linSOLUSDTl'
        _entry_side, _exit_side, _loss_cache, _history_capped_warned = 'Buy', 'Sell', None, False
        def __init__(self):
            self.client = Client()
            self.cfg = {'side': 'long', 'market_type': 'linear', 'symbol': 'SOLUSDT',
                        'max_loss_since_ms': now - 10 * D}
            self.adapter = object.__new__(LinearAdapter)
        def _now(self): return now / 1000
    return Bot()


def _fill(t, side, price, qty, link=''):
    return {'time_ms': t, 'side': side, 'price': price, 'qty': qty, 'fee': 0.0, 'link_id': link,
            'exec_id': f'{t}-{side}', 'venue_closed': not link, 'venue_kind': '' if link else 'TakeProfit'}


def spec_X14a_the_loss_limit_sees_the_venues_closes_over_the_whole_window():
    now = 40 * D
    # a liquidation three days ago: the old two-day window lost it, the loss read 0
    liq = [_fill(now - 3 * D, 'buy', 100, 10, 'linSOLUSDTl-0-a'), _fill(now - 3 * D + 1, 'sell', 80, 10)]
    realised, _ = _loss_bot(liq, now)._bot_result({'mark': 81}, 0.0, None, now / 1000)
    assert realised == -200.0, realised
    # two hosted take-profits, five days and minutes ago: +2, never a phantom loss
    tps = [_fill(now - 5 * D, 'buy', 100, 1, 'linSOLUSDTl-0-a'), _fill(now - 5 * D + 1, 'sell', 101, 1),
           _fill(now - 1000, 'buy', 80, 1, 'linSOLUSDTl-0-b'), _fill(now - 500, 'sell', 81, 1)]
    realised, _ = _loss_bot(tps, now)._bot_result({'mark': 81}, 0.0, None, now / 1000)
    assert realised == 2.0, realised


def spec_F15d_an_unread_wallet_keeps_the_cap_and_no_equity_is_capped():
    from gridgremlin.main import cap_holds, cap_verdict
    held = 'account leverage 3.10x >= 3x'
    assert cap_holds(held, None, {'equity': None, 'mm_rate': None, 'unread': True}) == held
    assert cap_holds(held, None, {'equity': None, 'mm_rate': 0.1}) == held         # read, no equity
    assert cap_holds(held, None, {'equity': 900.0, 'mm_rate': 0.1}) is None        # a read clears it
    assert cap_holds(None, None, {'equity': None, 'unread': True}) is None          # nothing to hold

    class B:
        alive, notional_now = True, 500.0
    caps = {'effective_leverage_max': 3.0}
    assert 'no room' in cap_verdict(caps, 0.1, [B()], equity=0.0)                   # zero was falsy
    assert cap_verdict(caps, 0.1, [B()], equity=None) is None                       # unknown judges nothing
    assert cap_verdict(caps, 0.1, [B()], equity=1000.0) is None


def spec_M23a_the_last_tranche_never_sells_more_than_is_held():
    from gridgremlin.ladder import last_lot
    sp = adapter_for('spot', {'symbol': 'ETHUSDT', 'qty_step': 0.00001, 'price_tick': 0.01,
                              'min_qty': 0.0001, 'min_notional': 1})
    held = 0.01234 * (1 - 0.001)                                   # a buy net of its fee, off the grid
    assert last_lot(sp, held) <= held and last_lot(sp, held) == 0.01232
    ln = adapter_for('linear', {'symbol': 'X', 'qty_step': 0.01, 'price_tick': 0.1, 'min_qty': 0.01})
    assert last_lot(ln, 3.19 - 1.59) == 1.6                        # M23: float noise still rounds up


def spec_M2a_a_short_coin_ladder_is_priced_where_its_orders_fill():
    from gridgremlin.config import validate_config
    from gridgremlin.ladder import ladder_fits
    row = {'strategy': 'martingale', 'market_type': 'linear', 'symbol': 'SOLUSDT', 'side': 'short',
           'capital': 100.0, 'leverage': 1, 'size_in': 'coin', 'base_order_size': 0.25,
           'safety_order_size': 0.25, 'order_size_multiplier': 1.0, 'deviation_pct': 0.1,
           'deviation_step_multiplier': 1.0, 'max_averaging_orders': 3, 'take_profit_avg_pct': 0.01}
    short = validate_config(row)
    long_ = validate_config(dict(row, side='long'))
    # one coin over four orders at mark 100: the long buys below the mark and
    # fits; the short's safety orders sell at 110, 120, 130 — 115 of capital
    assert ladder_fits(long_, 100.0)
    assert not ladder_fits(short, 100.0)
    assert ladder_fits(short, 86.0)                                 # 0.25 * 86 * (1 + 1.1 + 1.2 + 1.3) = 98.9
