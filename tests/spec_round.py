# Specs for SPEC M3-M6 — the martingale round against the fake venue.

from gridgremlin.adapters import LinearAdapter
from gridgremlin.bot import Bot
from gridgremlin.config import validate_config
from gridgremlin.events import Notifier

from spec_loop import FakeVenue

ADAPTER = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001,
                         'price_tick': 0.1, 'min_qty': 0.001,
                         'min_notional': 5.0, 'settle_coin': 'USDT'})


def _cfg(**over):
    row = {'strategy': 'martingale', 'market_type': 'linear',
           'symbol': 'BTCUSDT', 'side': 'long', 'capital': 1000.0,
           'leverage': 10, 'base_order_size': 1000.0,
           'safety_order_size': 1000.0, 'order_size_multiplier': 2.0,
           'deviation_pct': 0.01, 'deviation_step_multiplier': 2.0,
           'max_averaging_orders': 3, 'take_profit_avg_pct': 0.01}
    row.update(over)
    return validate_config(row)


def _bot(venue, lines, **over):
    return Bot(_cfg(**over), ADAPTER, venue, Notifier(sink=lines.append),
               gen_seed=1)


# --- the round opens: base at market, TP before anything rests (M3) ----------

def spec_M3_round_opens_base_then_tp_then_safety_ladder():
    venue, lines = FakeVenue(), []
    bot = _bot(venue, lines)
    first = bot.cycle()
    assert first == {'round_started': 1}
    assert venue.position and venue.orders == []       # base filled, nothing rests
    counts = bot.cycle()
    assert venue.tp_calls                              # M3: the TP exists...
    assert venue.position.get('takeProfit')
    safeties = [o for o in venue.orders if o['side'] == 'Buy']
    assert len(safeties) == 2 and counts['desired'] == 3   # -7% waits outside
    assert abs(venue.tp_calls[0] - 60000.0 * 1.01) < 0.11  # the window (W1);
    # M4: avg x (1+pct)


def spec_M4_tp_recomputes_when_fills_deepen():
    venue, lines = FakeVenue(), []
    bot = _bot(venue, lines)
    bot.cycle()
    bot.cycle()
    s1 = next(o for o in venue.orders if o['side'] == 'Buy')
    old_size = float(venue.position['size'])
    add = float(s1['qty'])
    new_avg = ((60000.0 * old_size + s1['price'] * add) / (old_size + add))
    venue.orders = [o for o in venue.orders if o is not s1]
    venue.position = {'positionIdx': 1, 'side': 'Buy',
                      'size': str(old_size + add), 'avgPrice': str(new_avg),
                      'takeProfit': venue.position['takeProfit'],
                      'leverage': '10', 'unrealisedPnl': '0'}
    bot.cycle()
    assert abs(venue.tp_calls[-1] - new_avg * 1.01) < 0.11   # followed the avg


# --- M3: a target the market ran through closes at target or better ----------

def spec_M3_through_market_closes_with_reduce_only_limit():
    venue, lines = FakeVenue(), []
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': '0.016',
                      'avgPrice': '59000', 'leverage': '10',
                      'unrealisedPnl': '0'}          # no TP on the venue
    venue.mark = 60000.0                             # target 59590 already met
    bot = _bot(venue, lines)
    result = bot.cycle()
    assert result == {'round': 'closing'}
    close = venue.orders[-1]
    assert close['side'] == 'Sell' and close['reduce_only']
    assert abs(close['price'] - 59000.0 * 1.01) < 0.11
    assert venue.tp_calls == [] if hasattr(venue, 'tp_calls') else True
    assert any(' tp ' in ln and 'already met' in ln for ln in lines)


# --- M6: restart adopts the resting TP, never rewrites a live round ----------

def spec_M6_restart_believes_the_venue_tp():
    venue, lines = FakeVenue(), []
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': '0.016',
                      'avgPrice': '59000', 'takeProfit': '59700',
                      'leverage': '10', 'unrealisedPnl': '0'}
    bot = _bot(venue, lines)                          # a fresh process
    bot.cycle()
    assert not getattr(venue, 'tp_calls', [])         # adopted, not rewritten


def spec_M6_a_holding_round_with_no_tp_still_gets_one():
    venue, lines = FakeVenue(), []
    venue.mark = 59000.0                              # target above mark: settable
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': '0.016',
                      'avgPrice': '59000', 'leverage': '10',
                      'unrealisedPnl': '0'}
    bot = _bot(venue, lines)
    bot.cycle()
    assert venue.tp_calls                             # never without an exit


# --- M5: repeat re-anchors from flat; off means done -------------------------

def spec_M5_repeat_reanchors_a_new_round_at_market():
    venue, lines = FakeVenue(), []
    bot = _bot(venue, lines, repeat=True)
    bot.cycle()                                       # round 1 base
    bot.cycle()                                       # TP + ladder
    venue.position = None                             # TP hit: flat
    venue.mark = 61000.0
    result = bot.cycle()
    assert result == {'round': 'cleanup'}             # H4b: E2 across rounds —
    assert venue.orders == []                         # stale ladder gone FIRST
    result = bot.cycle()
    assert result == {'round_started': 2}
    assert sum(' repeat ' in ln for ln in lines) == 1     # H4a: once, not 1/cycle
    assert float(venue.position['avgPrice']) == 61000.0   # anchored at market
    assert bot.alive


def spec_M5_repeat_off_round_complete_kills():
    venue, lines = FakeVenue(), []
    bot = _bot(venue, lines)
    bot.cycle()
    bot.cycle()
    venue.position = None                             # TP hit
    bot.cycle()
    assert bot.alive is False
    assert venue.orders == []                         # stale safeties cancelled
    assert any('round complete' in ln for ln in lines)


# --- D21: the venue-resting exit (HL-style, hosts_position_tp=False) ---------

class FakeHLRound(FakeVenue):
    hosts_position_tp = False

    def set_trading_stop(self, *a, **kw):
        raise AssertionError('a capability-less venue must never be asked')


def _hl_bot(venue, lines, **over):
    from gridgremlin.apply import make_botid
    cfg = _cfg(venue='hyperliquid', **over)
    return Bot(cfg, ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1)


def spec_D21_round_exit_rests_as_reduce_only_order():
    venue, lines = FakeHLRound(), []
    bot = _hl_bot(venue, lines)
    bot.cycle()                                        # base at market
    bot.cycle()                                        # TP + ladder
    tps = [o for o in venue.orders
           if o['reduce_only'] and o['side'] == 'Sell']
    assert len(tps) == 1
    assert abs(tps[0]['price'] - 60000.0 * 1.01) < 0.11
    assert tps[0]['link_id'].startswith('linBTCUSDTl-0-')   # rung 0 reserved
    assert any('TP resting' in ln for ln in lines)


def spec_D21_the_diff_never_cancels_the_round_exit():
    venue, lines = FakeHLRound(), []
    bot = _hl_bot(venue, lines)
    bot.cycle()
    bot.cycle()
    counts = bot.cycle()                               # steady state
    assert counts['cancels'] == 0
    assert sum(1 for o in venue.orders
               if o['reduce_only'] and o['side'] == 'Sell') == 1


def spec_D21_restart_adopts_the_resting_exit_by_identity():
    venue, lines = FakeHLRound(), []
    _hl_bot(venue, lines).cycle() or _hl_bot(venue, lines)
    first = _hl_bot(venue, lines)
    first.cycle()
    first.cycle()
    n_orders = len(venue.orders)
    fresh = _hl_bot(venue, lines)                      # a new process
    fresh.cycle()
    tps = [o for o in venue.orders
           if o['reduce_only'] and o['side'] == 'Sell']
    assert len(tps) == 1 and len(venue.orders) == n_orders   # M6: believed


def spec_D21_deepening_fill_refreshes_the_resting_exit():
    venue, lines = FakeHLRound(), []
    bot = _hl_bot(venue, lines)
    bot.cycle()
    bot.cycle()
    s1 = next(o for o in venue.orders
              if o['side'] == 'Buy' and not o['reduce_only'])
    old_size = float(venue.position['size'])
    add = float(s1['qty'])
    new_avg = (60000.0 * old_size + s1['price'] * add) / (old_size + add)
    venue.orders = [o for o in venue.orders if o is not s1]
    venue.position = dict(venue.position, size=str(old_size + add),
                          avgPrice=str(new_avg))
    bot.cycle()
    tps = [o for o in venue.orders
           if o['reduce_only'] and o['side'] == 'Sell']
    assert len(tps) == 1
    assert abs(tps[0]['price'] - ADAPTER.round_price(new_avg * 1.01)) < 0.11
    assert abs(float(tps[0]['qty']) - (old_size + add)) < 1e-9


# --- I5: the base order carries our identity ---------------------------------

def spec_I5_the_base_order_carries_an_owned_link():
    from gridgremlin.apply import rung_of
    venue, lines = FakeVenue(), []
    bot = _bot(venue, lines)
    assert bot.cycle() == {'round_started': 1}
    assert rung_of(venue.market_links[0], bot.botid) == 0


# --- D23: tranches — the same exit law, split into shares --------------------

def _tranche_cfg(**over):
    row = {'strategy': 'martingale', 'market_type': 'linear',
           'symbol': 'BTCUSDT', 'side': 'long', 'capital': 1000.0,
           'leverage': 10, 'base_order_size': 1000.0,
           'safety_order_size': 1000.0, 'order_size_multiplier': 2.0,
           'deviation_pct': 0.01, 'deviation_step_multiplier': 2.0,
           'max_averaging_orders': 3,
           'take_profit_tranches': [{'at_avg_pct': 0.01, 'share': 0.5},
                                    {'at_avg_pct': 0.02, 'share': 0.5}]}
    row.update(over)
    return validate_config(row)


def spec_D23_hosted_tranches_rest_on_the_conditional_book():
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(), ADAPTER, venue, Notifier(sink=lines.append),
              gen_seed=1)
    bot.cycle()                                    # base at market
    bot.cycle()                                    # tranches maintained
    book = venue.stop_orders('linear', 'BTCUSDT')
    assert len(book) == 2
    prices = sorted(float(o['triggerPrice']) for o in book)
    assert prices == [60600.0, 61200.0]            # +1% and +2% of 60000
    qtys = {o['qty'] for o in book}
    assert qtys == {'0.008'}                       # half of 0.016 each
    n = len(book)
    bot.cycle()                                    # level-triggered: no churn
    assert len(venue.stop_orders('linear', 'BTCUSDT')) == n


def spec_D23_tranches_reanchor_when_the_average_moves():
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(), ADAPTER, venue, Notifier(sink=lines.append),
              gen_seed=1)
    bot.cycle()
    bot.cycle()
    venue.position = dict(venue.position, size='0.032', avgPrice='59500')
    bot.cycle()                                    # deepen: re-anchored
    book = venue.stop_orders('linear', 'BTCUSDT')
    assert len(book) == 2
    assert sorted(float(o['triggerPrice']) for o in book) == [60095.0, 60690.0]
    assert {o['qty'] for o in book} == {'0.016'}


def spec_D23_the_hostless_venue_gets_a_tranche_ladder():
    venue, lines = FakeHLRound(), []
    bot = Bot(_tranche_cfg(), ADAPTER, venue, Notifier(sink=lines.append),
              gen_seed=1)
    bot.cycle()
    bot.cycle()
    from gridgremlin.apply import rung_of
    exits = [o for o in venue.orders
             if o['reduce_only'] and o['side'] == 'Sell'
             and rung_of(o['link_id'], bot.botid) == 0]
    assert len(exits) == 2
    assert sorted(o['price'] for o in exits) == [60600.0, 61200.0]
    n = len(venue.orders)
    bot.cycle()                                    # adopted by identity
    assert len(venue.orders) == n


def spec_D23_trailing_rides_the_venue_once_per_round():
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(take_profit_tranches=None,
                           take_profit_avg_pct=0.01,
                           trailing_stop_pct=0.01),
              ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1)
    bot.cycle()
    bot.cycle()
    assert venue.trail_calls == [600.0]            # 1% of the 60000 basis
    bot.cycle()                                    # venue holds it: no re-set
    assert venue.trail_calls == [600.0]


# --- M12/M13: reinvest and the venue-anchored cooldown -----------------------

def _histfills(*rows):
    out = []
    for t, side, price, qty, fee, link in rows:
        out.append({'time_ms': t, 'side': side, 'price': price, 'qty': qty,
                    'fee': fee, 'link_id': link, 'symbol': 'BTCUSDT',
                    'exec_id': f'h{t}'})
    return out


def spec_M13_cooldown_anchors_to_the_venue_TP_fill():
    venue, lines = FakeVenue(), []
    clock = {'t': 1_000_000.0}
    bot = Bot(_cfg(repeat=True, repeat_cooldown_seconds=300.0), ADAPTER,
              venue, Notifier(sink=lines.append), gen_seed=1,
              clock=lambda: clock['t'])
    link = f'{bot.botid}-0-x'
    venue.fills_history = lambda mt, sym, a, b: _histfills(
        (999_900_000, 'sell', 60600.0, 0.016, 0.1, link))   # TP filled t=999900
    bot._last_pos = 0.016                          # a round just closed
    assert bot.cycle() == {'round': 'cooling'}     # 999900+300 > 1000000? no...
    clock['t'] = 999_900.0 + 299.0
    bot._last_pos = 0.016
    bot._cool_until = None
    assert bot.cycle() == {'round': 'cooling'}
    clock['t'] = 999_900.0 + 301.0
    bot._last_pos = 0.016
    bot._cool_until = None
    r = bot.cycle()
    assert r == {'round_started': 2} or 'round_started' in r


def spec_M12_reinvest_scales_the_base_from_lifetime_fills():
    venue, lines = FakeVenue(), []
    bot = Bot(_cfg(repeat=True, reinvest=True), ADAPTER, venue,
              Notifier(sink=lines.append), gen_seed=1)
    import time as _t
    link = f'{bot.botid}-1-x'
    now_ms = int(_t.time() * 1000)
    # one closed round INSIDE the 30d window: bought 0.1 @ 50000, sold 0.1 @
    # 51000 -> +100 net on capital 1000 -> factor 1.1
    venue.fills_history = lambda mt, sym, a, b: _histfills(
        (now_ms - 2_000, 'buy', 50000.0, 0.1, 0.0, link),
        (now_ms - 1_000, 'sell', 51000.0, 0.1, 0.0, link))
    bot.cycle()                                    # opens round 1, scaled
    qty = float(venue.position['size'])
    base = 1000.0 / 60000.0                        # unscaled base qty
    assert abs(qty - ADAPTER.round_qty(base * 1.1)) < 1e-9
    assert abs(bot._scale - 1.1) < 1e-9            # lazy-derived, silently —
    # the ship event belongs to round COMPLETIONS (H4a: once per round)


def spec_M12_the_factor_caps_at_the_watchdog_headroom():
    venue, lines = FakeVenue(), []
    bot = Bot(_cfg(repeat=True, reinvest=True), ADAPTER, venue,
              Notifier(sink=lines.append), gen_seed=1)
    link = f'{bot.botid}-1-x'
    venue.fills_history = lambda mt, sym, a, b: _histfills(
        (1_000, 'buy', 50000.0, 0.1, 0.0, link),
        (2_000, 'sell', 60000.0, 0.1, 0.0, link))  # +1000 on 1000 = x2 raw
    fills = bot._own_fills()
    assert bot._reinvest_scale(fills) == 1.2       # capped (F2 headroom)


def spec_M12_losses_shrink_never_grow():
    venue, lines = FakeVenue(), []
    bot = Bot(_cfg(repeat=True, reinvest=True), ADAPTER, venue,
              Notifier(sink=lines.append), gen_seed=1)
    link = f'{bot.botid}-1-x'
    venue.fills_history = lambda mt, sym, a, b: _histfills(
        (1_000, 'buy', 50000.0, 0.1, 0.0, link),
        (2_000, 'sell', 48000.0, 0.1, 0.0, link))  # -200 on 1000
    assert abs(bot._reinvest_scale(bot._own_fills()) - 0.8) < 1e-9


def spec_M10_a_passed_tranche_is_done_the_rest_renormalise():
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(), ADAPTER, venue, Notifier(sink=lines.append),
              gen_seed=1)
    bot.cycle()                                    # base fills at 60000
    venue.mark = 60800.0                           # past t1, before t2
    venue.position = dict(venue.position, size='0.008')   # t1 fired: half gone
    bot.cycle()
    tps = [o for o in venue.stop_orders('linear', 'BTCUSDT')
           if 'TakeProfit' in o['stopOrderType']]
    assert len(tps) == 1                           # t1 is NOT re-placed
    assert float(tps[0]['triggerPrice']) == 61200.0
    assert tps[0]['qty'] == '0.008'                # whole remainder, renormalised


def spec_M10_blown_through_closes_at_target_or_better():
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(), ADAPTER, venue, Notifier(sink=lines.append),
              gen_seed=1)
    bot.cycle()
    venue.mark = 62000.0                           # past BOTH targets
    r = bot.cycle()
    assert r == {'round': 'closing'}               # M3: never without an exit
    sells = [o for o in venue.orders
             if o['side'] == 'Sell' and o['reduce_only']]
    assert sells and sells[-1]['price'] == 61200.0     # deepest target, or better
    assert any('every tranche target met' in ln for ln in lines)


# --- the 2026-08-06 audit: the three martingale HIGHs, pinned --------------

def spec_M12_a_total_loss_refuses_the_next_round():
    """0.0 is a real factor, not 'unset' — truthiness re-entered at FULL
    size after the capital was gone (audit H1)."""
    venue, lines = FakeVenue(), []
    bot = Bot(_cfg(repeat=True, reinvest=True), ADAPTER, venue,
              Notifier(sink=lines.append), gen_seed=1)
    link = f'{bot.botid}-1-x'
    import time as _t
    now = int(_t.time() * 1000)
    venue.fills_history = lambda mt, sym, a, b: _histfills(
        (now - 2000, 'buy', 60000.0, 1.0, 0.0, link),
        (now - 1000, 'sell', 59000.0, 1.0, 0.0, link))   # -1000 on capital 1000
    assert bot._reinvest_scale(bot._own_fills()) == 0.0
    assert bot.cycle() == {'round': 'capital_exhausted'}
    assert venue.position is None                        # nothing opened
    assert any('consumed the capital' in ln for ln in lines)


def spec_M10_a_fired_tranche_stays_fired_when_mark_retreats():
    """'Passed' is monotone within a round — measured against the best mark
    the round has seen (audit H2)."""
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(), ADAPTER, venue, Notifier(sink=lines.append),
              gen_seed=1)
    bot.cycle()                                    # base at 60000
    venue.mark = 60800.0                           # t1 (+1%) passed
    venue.position = dict(venue.position, size='0.008')
    bot.cycle()
    venue.mark = 60300.0                           # price RETREATS below t1
    bot.cycle()
    book = venue.stop_orders('linear', 'BTCUSDT')
    tps = [o for o in book if 'TakeProfit' in o['stopOrderType']]
    assert len(tps) == 1                           # t1 does NOT resurrect
    assert float(tps[0]['triggerPrice']) == 61200.0


def spec_M14_a_liquidated_round_stands_down_instead_of_re_entering():
    """A forced close is not a completed round (audit H3)."""
    venue, lines = FakeVenue(), []
    bot = Bot(_cfg(repeat=True), ADAPTER, venue,
              Notifier(sink=lines.append), gen_seed=1)
    bot.cycle()                                    # round 1 opens
    bot.cycle()
    import time as _t
    now = int(_t.time() * 1000)
    venue.fills_history = lambda mt, sym, a, b: [
        {'time_ms': now - 500, 'side': 'sell', 'price': 54000.0, 'qty': 0.016,
         'fee': 0.0, 'link_id': '', 'symbol': 'BTCUSDT', 'exec_id': 'liq',
         'market_type': 'linear', 'venue_closed': True,
         'venue_kind': 'liquidation'}]
    venue.position = None                          # wiped out
    r = bot.cycle()
    assert r == {'round': 'liquidation'}
    assert not bot.alive                           # D1: stands down
    assert not venue.position                      # never re-entered


def spec_M15_the_round_anchor_is_recovered_from_the_venue():
    """A restart mid-round must not re-anchor on the average entry: that
    deepens every remaining rung AND un-suppresses rungs that already
    filled, pushing past the validated capital (audit 2026-08-06)."""
    from gridgremlin.ladder import anchor_from_rung
    cfg = _cfg()
    anchor = 60000.0
    from gridgremlin.ladder import martingale_schedule
    _, cumdev = martingale_schedule(cfg)[1]
    resting = anchor * (1.0 - cumdev)                  # rung 1's true price
    assert abs(anchor_from_rung(cfg, resting, 1) - anchor) < 1e-6
    assert anchor_from_rung(cfg, resting, 0) is None   # rung 0 is the exit
    venue, lines = FakeVenue(), []
    bot = Bot(cfg, ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1)
    bot.cycle()                                        # base
    bot.cycle()                                        # ladder rests
    fresh = Bot(cfg, ADAPTER, venue, Notifier(sink=lines.append), gen_seed=2)
    fresh._last_pos = float(venue.position['size'])
    fresh.cycle()                                      # the restart
    assert fresh._anchor is not None
    assert abs(fresh._anchor - 60000.0) < 1.0          # recovered, not guessed
    assert any('anchor recovered' in ln for ln in lines)


def spec_M11_trailing_waits_for_the_first_tranche():
    """A trail tighter than the first tranche closed rounds before they
    could take profit — 30 live rounds averaging a small loss (2026-08-06)."""
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(trailing_stop_pct=0.008), ADAPTER, venue,
              Notifier(sink=lines.append), gen_seed=1)
    bot.cycle()                                   # base at 60000
    bot.cycle()                                   # tranches rest
    assert not getattr(venue, 'trail_calls', [])  # NOT armed yet
    venue.mark = 60800.0                          # t1 (+1%) fires
    venue.position = dict(venue.position, size='0.008')
    bot.cycle()
    assert venue.trail_calls                      # now it rides


def spec_M10_a_near_miss_defers_the_write_and_never_fires_the_round():
    """The guard band defers PLACEMENT (a TP written inside the band is
    refused by the venue) — it must not retire the tranche. The first cut
    folded the guard into "passed": a ~5bps near-miss cancelled t1's TP
    and armed the trail with zero profit taken, M11's bug reborn (audit
    2026-08-07 H4). Retirement is strict: the mark must CLEAR the target."""
    from gridgremlin.ladder import guard_band
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(), ADAPTER, venue, Notifier(sink=lines.append),
              gen_seed=1)
    bot.cycle()
    guard = guard_band(venue.mark - 0.5, venue.mark + 0.5)
    basis = 60000.0
    # mark a hair BELOW t1 (inside the band): t1 is NOT passed — it stays
    near = bot._round_targets(basis, 0.016, mark=60600.0 - guard / 2)
    assert any(abs(p - 60600.0) < 1e-9 for p, _ in near), near
    # and once the mark genuinely clears it, it retires — monotonically
    bot._round_targets(basis, 0.016, mark=60601.0)
    after = bot._round_targets(basis, 0.016, mark=60000.0)
    assert not any(abs(p - 60600.0) < 1e-9 for p, _ in after)


def spec_M3_a_covered_round_does_not_stack_another_exit():
    """Once the high-water passes every tranche, the exits placed earlier
    are still resting and will fill. Adding another reduce-only order on
    top is refused for capacity (110017) and warned every cycle forever —
    67 of them in ten minutes, live 2026-08-06."""
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(), ADAPTER, venue, Notifier(sink=lines.append),
              gen_seed=1)
    bot.cycle()                                   # base
    bot.cycle()                                   # tranches rest on the book
    resting = len(venue.stop_orders('linear', 'BTCUSDT'))
    assert resting == 2
    venue.mark = 62000.0                          # mark blows past both
    for _ in range(3):
        bot.cycle()                               # covered: nothing stacked
    assert not any('truncated' in ln or ' tp:' in ln for ln in lines)
    assert len(venue.stop_orders('linear', 'BTCUSDT')) == resting
    # but with NOTHING resting, the remainder genuinely does get closed
    venue.stop_book = []
    r = bot.cycle()
    assert r == {'round': 'closing'}
    assert any('every tranche target met' in ln for ln in lines)


def spec_M14_a_lagging_close_account_is_awaited_not_judged():
    """Live 2026-08-06: a hosted TP closed the round, and 3s later the fill
    list had not yet published it — the newest visible fill on the shared
    symbol belonged to the OTHER side's bot. The bot judged 'an outside
    close' and tombstoned itself, healthy. The account is awaited, and
    another bot's fills are never evidence about ours."""
    import time as _t
    venue, lines = FakeVenue(), []
    bot = Bot(_cfg(repeat=True), ADAPTER, venue, Notifier(sink=lines.append),
              gen_seed=1)
    now_ms = int(_t.time() * 1000)
    fills = [
        {'side': 'buy', 'price': 60000.0, 'qty': 0.016, 'fee': 0.1,
         'time_ms': now_ms - 20_000, 'link_id': f'{bot.botid}-0-1',
         'venue_closed': False, 'venue_kind': ''},        # our entry
        {'side': 'buy', 'price': 60500.0, 'qty': 0.01, 'fee': 0.1,
         'time_ms': now_ms - 1_000, 'link_id': 'linBTCUSDTs-3-9',
         'venue_closed': False, 'venue_kind': ''},        # the OTHER bot
    ]
    venue.fills_history = lambda mt, sym, a, b: list(fills)
    bot._last_pos = 0.016                       # position just vanished
    assert bot.cycle() == {'confirming_close': 1}
    assert bot.alive
    # the venue's account arrives: OUR hosted TP closed it
    fills.append({'side': 'sell', 'price': 60600.0, 'qty': 0.016, 'fee': 0.1,
                  'time_ms': now_ms - 500, 'link_id': '',
                  'venue_closed': True, 'venue_kind': 'TakeProfit'})
    bot._last_pos = 0.016
    r = bot.cycle()
    assert bot.alive, 'stood down on its own hosted take-profit'
    assert 'confirming_close' not in (r or {})
    assert not any('kill' in ln for ln in lines)


def spec_M14_silence_never_kills_a_round():
    """Audit 2026-08-07 H3: three cycles of fills-endpoint failure killed
    and tombstoned a healthy bot — and on a spuriously-flat read would
    have cancelled every order around a REAL position. Silence holds the
    round open; only a venue account of the close judges it."""
    import tempfile
    from pathlib import Path as _P
    from gridgremlin.tombstones import Tombstones
    from gridgremlin.exchange.errors import VenueError
    venue, lines = FakeVenue(), []
    bot = Bot(_cfg(repeat=True), ADAPTER, venue, Notifier(sink=lines.append),
              gen_seed=1)
    bot.tombs = Tombstones(_P(tempfile.mkdtemp()) / 'tombs.json')

    def raising(mt, sym, a, b):
        raise VenueError('fills endpoint down', kind='other')
    venue.fills_history = raising
    for _ in range(8):
        bot._last_pos = 0.016
        bot.cycle()
    assert bot.alive, 'killed on endpoint silence'
    assert not bot.tombs.has(bot.botid)
    assert not any('] kill' in ln for ln in lines)   # the EVENT, not prose


def spec_M14_a_liquidation_survives_a_restart():
    """Audit 2026-08-07 H2 (money): a liquidation while the process was
    down leaves no tombstone — the fill history is the only witness, and
    the restarted bot asked nobody before re-entering."""
    import time as _t
    venue, lines = FakeVenue(), []
    bot = Bot(_cfg(repeat=True), ADAPTER, venue, Notifier(sink=lines.append),
              gen_seed=1)
    now_ms = int(_t.time() * 1000)
    venue.fills_history = lambda mt, sym, a, b: [
        {'side': 'buy', 'price': 60000.0, 'qty': 0.016, 'fee': 0.1,
         'time_ms': now_ms - 600_000, 'link_id': f'{bot.botid}-0-1',
         'venue_closed': False, 'venue_kind': ''},
        {'side': 'sell', 'price': 55000.0, 'qty': 0.016, 'fee': 0.1,
         'time_ms': now_ms - 300_000, 'link_id': '',
         'venue_closed': True, 'venue_kind': 'liquidation'}]
    r = bot.cycle()                      # fresh process, flat venue
    assert r == {'round': 'liquidation'}, r
    assert not bot.alive
    assert not any('round 1: base' in ln for ln in lines)


def spec_M15_the_deepest_round_restart_places_no_new_safeties():
    """Every safety filled, nothing resting to invert: the fallback
    anchor (average entry) is the exact re-anchoring M15 forbids — it
    deepens rungs past validated capital. The bot holds, keeps exits,
    places no safeties, and says so once (audit 2026-08-07 MED)."""
    import time as _t
    venue, lines = FakeVenue(), []
    bot = Bot(_cfg(repeat=True), ADAPTER, venue, Notifier(sink=lines.append),
              gen_seed=1)
    now_ms = int(_t.time() * 1000)
    venue.fills_history = lambda mt, sym, a, b: [
        {'side': 'buy', 'price': 60000.0, 'qty': 0.048, 'fee': 0.1,
         'time_ms': now_ms - 60_000, 'link_id': f'{bot.botid}-0-9',
         'venue_closed': False, 'venue_kind': ''}]
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': '0.048',
                      'avgPrice': '58000', 'leverage': '10',
                      'unrealisedPnl': '0'}
    venue.mark = 57500.0            # below the TP: the round is still OPEN
    bot.cycle()                     # fresh process, mid-round, no orders
    entries = [o for o in venue.orders if o['side'] == 'Buy'
               and not o['reduce_only']]
    assert entries == [], f'new safeties placed anchorless: {entries}'
    assert sum('placing no new safeties' in ln for ln in lines) == 1
    bot.cycle()
    assert sum('placing no new safeties' in ln for ln in lines) == 1


# --- R10 reaches M14: a counterparty's liquidation stamp is our EXIT --------

def spec_R10_a_counterparty_stamped_exit_reads_as_exit_not_liquidation():
    """The 48-day run: our resting exit filled against someone else's
    liquidation and M14 stood the bot down as liquidated. Through the real
    HL truth read, the same fill is our exit; only OUR address in the stamp
    is a liquidation (JOURNAL 2026-09-25 post-mortem)."""
    from gridgremlin.exchange.hyperliquid import truth as hl
    from gridgremlin.exchange.hyperliquid.signing import link_to_cloid
    import time as _t
    ours, other = '0x' + 'a' * 40, '0x' + 'b' * 40
    venue, lines = FakeVenue(), []
    bot = _bot(venue, lines)
    bot.cycle()                                    # round opens
    now = int(_t.time() * 1000)

    def raw(who):
        stamp = {'liquidatedUser': who, 'markPx': '54100', 'method': 'market'}
        return [{'coin': 'BTCUSDT', 'px': '60000', 'sz': '0.016', 'side': 'B',
                 'time': now - 2000, 'tid': 1, 'fee': '0.1',
                 'cloid': link_to_cloid(f'{bot.botid}-0-aa')},
                {'coin': 'BTCUSDT', 'px': '60600', 'sz': '0.016', 'side': 'A',
                 'time': now - 500, 'tid': 2, 'fee': '0.1', 'crossed': False,
                 'cloid': link_to_cloid(f'{bot.botid}-0-aa'),
                 'liquidation': stamp}]

    venue.fills_history = lambda mt, sym, a, b: hl.read_fills(
        raw(other), {'BTCUSDT'}, ours)
    assert bot._how_round_ended() == 'exit'
    venue.fills_history = lambda mt, sym, a, b: hl.read_fills(
        raw(ours), {'BTCUSDT'}, ours)
    assert bot._how_round_ended() == 'liquidation'


# --- M16: the maker base (D37) -----------------------------------------------

def _maker_bot(venue, lines, t, **over):
    return Bot(_cfg(start_order_type='maker', **over), ADAPTER, venue,
               Notifier(sink=lines.append), gen_seed=1, clock=lambda: t[0])


def _base(venue):
    return [o for o in venue.orders
            if o['side'] == 'Buy' and not o['reduce_only']
            and o['link_id'].split('-')[-2] == '0']


def spec_M16_the_base_rests_post_only_at_the_best_bid():
    from gridgremlin.apply import rung_of
    venue, lines, t = FakeVenue(), [], [0.0]
    bot = _maker_bot(venue, lines, t)
    assert bot.cycle() == {'round_started': 1}
    assert not getattr(venue, 'market_links', None)      # no taker entry
    [base] = venue.orders
    assert base['side'] == 'Buy' and base['post_only'] and not base['reduce_only']
    assert base['price'] == 59999.5                      # the bid, not the ask
    assert rung_of(base['link_id'], bot.botid) == 0
    assert bot.cycle() == {'round': 'entering'}
    assert venue.orders == [base]                        # nothing else yet
    assert not getattr(venue, 'tp_calls', None)


def spec_M16_a_short_rests_at_the_best_ask():
    venue, lines, t = FakeVenue(), [], [0.0]
    bot = _maker_bot(venue, lines, t, side='short')
    bot.cycle()
    [base] = venue.orders
    assert base['side'] == 'Sell' and base['price'] == 60000.5


def spec_M16_the_filled_base_anchors_the_round_at_its_own_price():
    venue, lines, t = FakeVenue(), [], [0.0]
    bot = _maker_bot(venue, lines, t)
    bot.cycle()
    venue.fill(venue.orders[0]['order_id'], 59999.5)
    bot.cycle()
    assert venue.tp_calls                                # M3 as before
    safeties = [o for o in venue.orders if o['side'] == 'Buy']
    assert safeties and safeties[0]['price'] == ADAPTER.round_price(
        59999.5 * 0.99)                                  # anchored at the fill


def spec_M16_the_base_keeps_its_queue_until_the_book_leaves_it():
    venue, lines, t = FakeVenue(), [], [0.0]
    bot = _maker_bot(venue, lines, t)
    bot.cycle()
    first = venue.orders[0]
    t[0] = 500.0                                         # long past 40s, but
    assert bot.cycle() == {'round': 'entering'}          # still the best bid:
    assert venue.orders == [first]                       # the queue is kept
    venue.mark = 60100.0                                 # the book walks away
    assert bot.cycle() == {'round': 'requoted'}
    [second] = venue.orders
    assert second['price'] == 60099.5 and second['post_only']
    assert second['qty'] == first['qty']
    venue.mark = 60200.0                                 # walks again, but the
    t[0] = 539.0                                         # new quote has rested
    assert bot.cycle() == {'round': 'entering'}          # under 40s
    assert venue.orders == [second]
    t[0] = 540.0
    assert bot.cycle() == {'round': 'requoted'}
    assert venue.orders[0]['price'] == 60199.5


def spec_M16_a_partial_fill_holds_its_tp_and_the_ladder_waits():
    venue, lines, t = FakeVenue(), [], [0.0]
    bot = _maker_bot(venue, lines, t)
    bot.cycle()
    base = venue.orders[0]
    base['cum'] = 0.009                                  # of 0.016
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': '0.009',
                      'avgPrice': '59999.5', 'leverage': '10',
                      'unrealisedPnl': '0'}
    assert bot.cycle() == {'round': 'entering'}
    assert venue.tp_calls                                # M3: never without
    assert venue.orders == [base]                        # no safety yet
    venue.mark = 60100.0
    t[0] = 40.0
    assert bot.cycle() == {'round': 'requoted'}
    [rest] = venue.orders
    assert float(rest['qty']) == 0.007 and rest['price'] == 60099.5


def spec_M16_a_restart_mid_entry_adopts_the_base_and_never_kills():
    # the sabotage this guards: the round-complete check counted any owned
    # order on a fresh start — a resting base read as a finished round
    venue, lines, t = FakeVenue(), [], [0.0]
    _maker_bot(venue, lines, t).cycle()
    [base] = venue.orders
    bot = _maker_bot(venue, lines, t)                    # a fresh process
    assert bot.cycle() == {'round': 'entering'}
    assert bot.alive and venue.orders == [base]          # adopted, untouched


def spec_M16_an_unfilled_entry_expires_and_stands_down():
    venue, lines, t = FakeVenue(), [], [0.0]
    bot = _maker_bot(venue, lines, t, start_order_expire_seconds=120)
    bot.cycle()
    t[0] = 119.0
    bot.cycle()
    assert bot.alive
    t[0] = 120.0
    assert bot.cycle() == {'round': 'expired'}
    assert not bot.alive and venue.orders == []
    assert any('entry expired' in ln for ln in lines)


def spec_M16_a_partial_fill_never_expires():
    venue, lines, t = FakeVenue(), [], [0.0]
    bot = _maker_bot(venue, lines, t, start_order_expire_seconds=120)
    bot.cycle()
    venue.orders[0]['cum'] = 0.009
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': '0.009',
                      'avgPrice': '59999.5', 'leverage': '10',
                      'unrealisedPnl': '0'}
    t[0] = 500.0
    bot.cycle()
    assert bot.alive                                     # a round, not an entry


# --- M17 (D38): the stop steps up the tranche ladder -----------------------

THREE = [{'at_avg_pct': 0.01, 'share': 0.4}, {'at_avg_pct': 0.02, 'share': 0.3},
         {'at_avg_pct': 0.03, 'share': 0.3}]


def _sl_book(venue):
    return [o for o in venue.stop_orders('linear', 'BTCUSDT')
            if 'StopLoss' in o['stopOrderType']]


def spec_M17_no_stop_rests_before_the_first_tranche_fills():
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(breakeven_ladder=True), ADAPTER, venue,
              Notifier(sink=lines.append), gen_seed=1)
    bot.cycle()                                    # base at 60000
    bot.cycle()                                    # tranches rest
    assert _sl_book(venue) == []


def spec_M17_tp1_moves_the_stop_to_breakeven_plus_fees():
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(breakeven_ladder=True), ADAPTER, venue,
              Notifier(sink=lines.append), gen_seed=1)
    bot.cycle()
    bot.cycle()
    venue.mark = 60800.0                           # t1 (+1%) fired
    venue.position = dict(venue.position, size='0.008')
    bot.cycle()
    sl = _sl_book(venue)
    assert len(sl) == 1
    assert float(sl[0]['triggerPrice']) == 60060.0   # avg + G6's 0.1%
    assert sl[0]['qty'] == '0.008'                   # what is still held
    n = len(venue.sl_calls)
    bot.cycle()                                    # level-triggered: no churn
    assert len(venue.sl_calls) == n


def spec_D56_at_the_cap_entries_pause_and_exits_keep_working():
    """A capped account adds no exposure: a grid's resting buys are
    withdrawn and no new one rests, its sells stay; a martingale opens no
    new round and places no safety; a seed waits. Lifted, all resumes."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from spec_loop import FakeVenue as GV, _cfg as gcfg, ADAPTER as GA
    venue, lines = GV(), []
    grid = Bot(gcfg(), GA, venue, Notifier(sink=lines.append), gen_seed=1)
    grid.cycle()
    assert any(o['side'] == 'Buy' for o in venue.orders)
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': '0.05',
                      'avgPrice': '59000', 'leverage': '10',
                      'unrealisedPnl': '0'}
    grid._basis_cache = None
    grid.cycle()
    sells = [o for o in venue.orders if o['side'] == 'Sell']
    grid.capped = 'notional 1 >= 1'
    grid.cycle()
    assert not any(o['side'] == 'Buy' for o in venue.orders)   # withdrawn
    assert [o['order_id'] for o in venue.orders if o['side'] == 'Sell'] == \
        [o['order_id'] for o in sells]                          # exits stay
    assert abs(grid.notional_now - 0.05 * venue.mark) < 1e-6
    grid.capped = None
    grid.cycle()
    assert any(o['side'] == 'Buy' for o in venue.orders)        # resumes
    mv = FakeVenue()
    mg = Bot(_cfg(), ADAPTER, mv, Notifier(sink=lambda l: None), gen_seed=1)
    mg.capped = 'maintenance margin 31% >= 30%'
    assert mg.cycle() == {'round': 'capped'} and mv.position is None
    mg.capped = None
    assert mg.cycle() == {'round_started': 1}


def spec_D55_the_first_step_sits_where_the_owner_chose():
    """Owner 2026-10-05: breakeven offsets "should be an option, the user
    should be able to choose how to take the hit." The first step from the
    average: below zero gives room at a small loss, zero is breakeven
    before fees, above locks a profit; blank keeps G6's fee floor. Later
    steps still climb to the previous tranche's price."""
    for off, want in ((-0.002, 59880.0), (0.0, 60000.0), (0.003, 60180.0),
                      (None, 60060.0)):
        venue, lines = FakeVenue(), []
        over = {'breakeven_ladder': True}
        if off is not None:
            over['breakeven_offset_pct'] = off
        bot = Bot(_tranche_cfg(**over), ADAPTER, venue,
                  Notifier(sink=lines.append), gen_seed=1)
        bot.cycle()
        bot.cycle()
        venue.mark = 60800.0                       # t1 (+1%) fired
        venue.position = dict(venue.position, size='0.008')
        bot.cycle()
        sl = _sl_book(venue)
        assert float(sl[0]['triggerPrice']) == want, (off, sl)
    short = Bot(_tranche_cfg(side='short', breakeven_ladder=True,
                             breakeven_offset_pct=0.003), ADAPTER,
                FakeVenue(), Notifier(sink=lambda l: None), gen_seed=1)
    assert short._breakeven_level(60000.0, 1) == 59820.0    # profit: below
    assert short._breakeven_level(60000.0, 2) == 59400.0    # step 2 unchanged


def spec_M17_tp2_moves_the_stop_to_tp1_and_resizes():
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(breakeven_ladder=True, take_profit_tranches=THREE),
              ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1)
    bot.cycle()
    bot.cycle()
    venue.mark = 60700.0
    venue.position = dict(venue.position, size='0.010')
    bot.cycle()                                    # step 1: breakeven
    venue.mark = 61300.0                           # t2 (+2%) fired
    venue.position = dict(venue.position, size='0.005')
    bot.cycle()
    sl = _sl_book(venue)
    assert len(sl) == 1                            # the old step is cleared
    assert float(sl[0]['triggerPrice']) == 60600.0     # TP1's price
    assert sl[0]['qty'] == '0.005'


def spec_M17_a_short_steps_below_its_average():
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(breakeven_ladder=True, side='short'), ADAPTER,
              venue, Notifier(sink=lines.append), gen_seed=1)
    bot.cycle()
    bot.cycle()
    venue.mark = 59200.0                           # t1 (-1%) fired
    venue.position = dict(venue.position, size='0.008')
    bot.cycle()
    assert float(_sl_book(venue)[0]['triggerPrice']) == 59940.0


def spec_M17_a_restart_adopts_the_venue_step_and_never_loosens():
    venue, lines = FakeVenue(), []
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': '0.005',
                      'avgPrice': '60000', 'leverage': '10',
                      'unrealisedPnl': '0'}
    venue.mark = 60900.0                           # BELOW t2: no fills to say
    venue.set_trading_stop('linear', 'BTCUSDT', 1, stop_loss='60600',
                           sl_size='0.005')        # step 2, from before
    bot = Bot(_tranche_cfg(breakeven_ladder=True, take_profit_tranches=THREE),
              ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1)
    n = len(venue.sl_calls)
    bot.cycle()
    assert len(venue.sl_calls) == n                # adopted, not rewritten
    assert bot._be_level == 60600.0                # not t1 resurrected below


def spec_M17_the_venue_fires_its_own_stop_the_engine_stays_out():
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(breakeven_ladder=True), ADAPTER, venue,
              Notifier(sink=lines.append), gen_seed=1)
    bot.cycle()
    bot.cycle()
    venue.mark = 60800.0
    venue.position = dict(venue.position, size='0.008')
    bot.cycle()                                    # the stop rests at 60060
    venue.mark = 60050.0                           # through it
    assert bot.cycle() == {'round': 'breakeven'}
    assert not getattr(venue, 'market_links', [])[1:]   # base only: no close


def spec_M17_nothing_resting_and_through_closes_the_round_at_market():
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(breakeven_ladder=True), ADAPTER, venue,
              Notifier(sink=lines.append), gen_seed=1)
    bot.cycle()
    bot.cycle()
    venue.mark = 60800.0
    venue.position = dict(venue.position, size='0.008')
    bot.cycle()
    venue.stop_book = [o for o in venue.stop_book  # the venue lost it
                       if 'StopLoss' not in o['stopOrderType']]
    assert venue.stop_orders('linear', 'BTCUSDT')  # TP2 still rests
    venue.mark = 60050.0
    assert bot.cycle() == {'round': 'breakeven'}
    assert venue.position is None                  # closed what was held
    assert venue.stop_orders('linear', 'BTCUSDT') == []    # TP2 cleared too
    assert bot.alive
    assert any('the bot does not' in ln for ln in lines)


def spec_M17_the_hostless_venue_watches_the_mark_and_ends_the_round_only():
    venue, lines = FakeHLRound(), []
    bot = Bot(_tranche_cfg(breakeven_ladder=True, venue='hyperliquid',
                           repeat=True),
              ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1)
    bot.cycle()
    bot.cycle()                                    # two exits rest
    t1 = next(o for o in venue.orders
              if o['reduce_only'] and o['price'] == 60600.0)
    venue.orders.remove(t1)                        # t1 filled
    venue.mark = 60800.0
    venue.position = dict(venue.position, size='0.008')
    bot.cycle()
    assert bot._be_level == 60060.0
    venue.mark = 60100.0                           # above the step: holds
    assert bot.cycle() != {'round': 'breakeven'}
    venue.mark = 60050.0
    assert bot.cycle() == {'round': 'breakeven'}
    assert venue.position is None
    from gridgremlin.apply import rung_of
    assert rung_of(venue.market_links[-1], bot.botid) == 0     # our exit
    assert not [o for o in venue.orders if o['reduce_only']]   # E2: cleared
    bot.cycle()                                    # flat: M5 decides
    assert bot.alive
    assert any('round 2 re-anchors' in ln for ln in lines)
    assert bot._be_level is None                   # round-scoped


def spec_M17_a_restart_re_steps_from_the_rounds_exit_fills():
    """The step count lived in the round's best mark, in memory — a restart
    after t1 filled and price fell back re-placed t1 and forgot the stop."""
    venue, lines = FakeHLRound(), []
    cfg = _tranche_cfg(breakeven_ladder=True, venue='hyperliquid')
    from gridgremlin.apply import make_botid
    link = f"{make_botid('linear', 'BTCUSDT', 'long')}-0-x"
    import time as _t
    now = int(_t.time() * 1000)
    venue.fills_history = lambda mt, sym, a, b: _histfills(
        (now - 9000, 'sell', 59000.0, 0.016, 0.0, link),   # last round's close
        (now - 5000, 'buy', 60000.0, 0.016, 0.0, link),    # this round's base
        (now - 3000, 'sell', 60600.0, 0.008, 0.0, link))   # t1 filled
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': '0.008',
                      'avgPrice': '60000', 'leverage': '10',
                      'unrealisedPnl': '0'}
    venue.mark = 60300.0                           # fell back below t1
    bot = Bot(cfg, ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1)
    bot.cycle()
    exits = sorted(o['price'] for o in venue.orders if o['reduce_only'])
    assert exits == [61200.0]                      # t1 is NOT resurrected
    assert bot._be_level == 60060.0                # the step survived


def spec_M25_a_filled_tranche_is_done_while_the_mark_lags_it():
    """HL's markPx sat under a filled TP1 for 286 cycles: t1 read as
    unfired, the remainder re-split into halves, and the half under the
    venue's minimum was refused every cycle with no exit resting (live,
    2026-10-05). The round's own exit fill is a price it reached."""
    venue, lines = FakeHLRound(), []
    bot = Bot(_tranche_cfg(breakeven_ladder=True, venue='hyperliquid'),
              ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1)
    bot.cycle()
    bot.cycle()                                    # two exits rest
    t1 = next(o for o in venue.orders
              if o['reduce_only'] and o['price'] == 60600.0)
    venue.orders.remove(t1)                        # t1 filled on a trade...
    link = t1['link_id']
    import time as _t
    now = int(_t.time() * 1000)
    venue.fills_history = lambda mt, sym, a, b: _histfills(
        (now - 5000, 'buy', 60000.0, 0.016, 0.0, link),
        (now - 1000, 'sell', 60600.0, 0.008, 0.0, link))
    venue.position = dict(venue.position, size='0.008')
    venue.mark = 60550.0                           # ...the mark never got there
    bot.cycle()
    exits = [(o['price'], o['qty']) for o in venue.orders if o['reduce_only']]
    assert exits == [(61200.0, '0.008')]           # t1 not re-placed; t2 whole
    assert bot._be_level == 60060.0                # and the ladder stepped


def spec_M17_a_restart_that_fires_at_once_still_ends_a_round():
    """The early return skipped the round latch: a restart that fired the
    step at once read the flat as never-opened, and with repeat off it
    opened a new round instead of standing down."""
    venue, lines = FakeHLRound(), []
    cfg = _tranche_cfg(breakeven_ladder=True, venue='hyperliquid')
    from gridgremlin.apply import make_botid
    link = f"{make_botid('linear', 'BTCUSDT', 'long')}-0-x"
    import time as _t
    now = int(_t.time() * 1000)
    venue.fills_history = lambda mt, sym, a, b: _histfills(
        (now - 5000, 'buy', 60000.0, 0.016, 0.0, link),
        (now - 3000, 'sell', 60600.0, 0.008, 0.0, link))
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': '0.008',
                      'avgPrice': '60000', 'leverage': '10',
                      'unrealisedPnl': '0'}
    venue.mark = 60000.0                           # already through 60060
    bot = Bot(cfg, ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1)
    assert bot.cycle() == {'round': 'breakeven'}
    bot.cycle()
    assert not bot.alive                           # repeat off: stands down
    assert venue.position is None                  # and opened nothing


# --- X9-X11, D33, D41: the timeout, the round-ending stop, the round limit ---

def _clocked(venue, lines, clock, **over):
    return Bot(_cfg(**over), ADAPTER, venue, Notifier(sink=lines.append),
               gen_seed=1, clock=lambda: clock['t'])


def spec_X9_the_stop_waits_out_its_timeout_and_a_recovery_resets_it():
    """3Commas' SL timeout: the timer starts when the price reaches the
    stop; a recovery before it expires calls the stop off."""
    venue, lines, clock = FakeVenue(), [], {'t': 1000.0}
    bot = _clocked(venue, lines, clock,
                   stop={'watch': 'mark_price', 'level': 55000,
                         'confirm_seconds': 30})
    bot.cycle()
    bot.cycle()                                    # holding, ladder resting
    venue.mark = 54900.0                           # through the level
    bot.cycle()
    assert bot.alive and venue.position is not None        # not on a touch
    assert sum('must hold 30s' in ln for ln in lines) == 1
    clock['t'] += 20
    bot.cycle()
    assert bot.alive                               # 20s: still waiting
    assert sum('must hold 30s' in ln for ln in lines) == 1     # said once
    venue.mark = 55100.0                           # recovered
    clock['t'] += 5
    bot.cycle()
    assert bot._stop_since is None
    assert any('recovered past the stop level' in ln for ln in lines)
    venue.mark = 54900.0                           # crossed again: a NEW clock
    clock['t'] += 5
    bot.cycle()
    clock['t'] += 29
    bot.cycle()
    assert bot.alive
    clock['t'] += 2                                # 31s past the level
    bot.cycle()
    assert not bot.alive and venue.position is None
    assert any('stop fired' in ln and 'held 30s' in ln for ln in lines)


def spec_X9_without_a_timeout_the_stop_fires_on_the_touch():
    """The sabotage half: the same script with no confirm_seconds."""
    venue, lines, clock = FakeVenue(), [], {'t': 1000.0}
    bot = _clocked(venue, lines, clock,
                   stop={'watch': 'mark_price', 'level': 55000})
    bot.cycle()
    bot.cycle()
    venue.mark = 54900.0
    bot.cycle()
    assert not bot.alive and venue.position is None


def spec_X10_the_percent_stop_sits_under_each_rounds_own_base():
    venue, lines = FakeVenue(), []
    bot = _bot(venue, lines,
               stop={'watch': 'mark_price', 'from_base_pct': 0.10})
    bot.cycle()                                    # base at 60,000
    bot.cycle()
    venue.mark = 54100.0                           # -9.8%: holds
    bot.cycle()
    assert bot.alive
    venue.mark = 53900.0                           # past 54,000
    bot.cycle()
    assert not bot.alive and venue.position is None
    assert any('10.0000% from the base order at 60000' in ln for ln in lines)


def spec_X10_flat_has_no_base_and_so_no_stop():
    venue, lines = FakeVenue(mark=100.0), []
    bot = _bot(venue, lines,
               stop={'watch': 'mark_price', 'from_base_pct': 0.10})
    assert bot._stop_hit({'mark': 1.0, 'positions': {}}, None) is None


def spec_X10_a_restart_reads_the_base_from_the_venues_fills():
    """The deepest round after a restart has no anchor (M15). The round's
    own base fill is still on the venue."""
    venue, lines = FakeVenue(), []
    bot = _bot(venue, lines,
               stop={'watch': 'mark_price', 'from_base_pct': 0.10})
    link = f'{bot.botid}-0-x'
    old = f'{bot.botid}-0-w'
    import time as _t
    now = int(_t.time() * 1000)
    venue.fills_history = lambda mt, sym, a, b: _histfills(
        (now - 90000, 'buy', 70000.0, 0.014, 0.0, old),    # an older round
        (now - 80000, 'sell', 70700.0, 0.014, 0.0, old),
        (now - 5000, 'buy', 60000.0, 0.016, 0.0, link),
        (now - 4000, 'buy', 59400.0, 0.016, 0.0, f'{bot.botid}-1-x'))
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': '0.032',
                      'avgPrice': '59700', 'leverage': '10',
                      'unrealisedPnl': '0'}
    venue.mark = 54100.0
    bot.cycle()
    assert bot.alive and bot._stop_base == 60000.0     # not 70,000
    venue.mark = 53900.0
    bot.cycle()
    assert not bot.alive


def _stopping(**over):
    return dict(repeat=True, stop={'watch': 'mark_price',
                                   'from_base_pct': 0.10,
                                   'action': 'end_round'}, **over)


def spec_X11_the_stop_ends_the_round_and_the_bot_goes_on():
    from gridgremlin.apply import rung_of
    from gridgremlin.bot import STOP_RUNG
    venue, lines = FakeVenue(), []
    bot = _bot(venue, lines, **_stopping())
    bot.cycle()
    bot.cycle()
    idx = ADAPTER.position_idx('Buy', False) or 0
    venue.stop_book = [{'orderId': 'theirs', 'stopOrderType': 'Stop',
                        'positionIdx': idx},
                       {'orderId': 'ours', 'positionIdx': idx,
                        'stopOrderType': 'PartialTakeProfit'}]
    venue.mark = 53900.0
    assert bot.cycle() == {'round': 'stopped'}
    assert venue.position is None and bot.alive            # closed, not dead
    assert [o['orderId'] for o in venue.stop_book] == ['theirs']    # I1
    assert rung_of(venue.market_links[-1], bot.botid) == STOP_RUNG
    assert any('the round ends, the bot does not' in ln for ln in lines)
    assert not any(' kill ' in ln for ln in lines)
    assert bot.cycle() == {'round': 'cleanup'}             # stale ladder first
    assert venue.orders == []
    assert bot.cycle() == {'round_started': 2}
    assert float(venue.position['avgPrice']) == 53900.0    # a new base, and
    venue.mark = 48600.0                                   # its own stop:
    bot.cycle()                                            # 53,900 x 0.9
    assert venue.position is not None                      # = 48,510
    venue.mark = 48500.0
    assert bot.cycle() == {'round': 'stopped'}


def spec_X11_the_default_stop_is_still_the_off_button():
    """The sabotage half: the same stop without the opt-in kills (D1)."""
    venue, lines = FakeVenue(), []
    bot = _bot(venue, lines, repeat=True,
               stop={'watch': 'mark_price', 'from_base_pct': 0.10})
    bot.cycle()
    bot.cycle()
    venue.mark = 53900.0
    bot.cycle()
    assert not bot.alive and venue.position is None
    assert any(' kill ' in ln for ln in lines)


def spec_X11_the_resting_exit_is_cancelled_before_the_close():
    """E2 on a venue that rests the round's exit as an order (D21)."""
    venue, lines = FakeHLRound(), []
    bot = Bot(_cfg(venue='hyperliquid', **_stopping()), ADAPTER, venue,
              Notifier(sink=lines.append), gen_seed=1)
    bot.cycle()
    bot.cycle()
    assert [o for o in venue.orders if o['reduce_only']]   # the TP rests
    venue.mark = 53900.0
    assert bot.cycle() == {'round': 'stopped'}
    assert not [o for o in venue.orders if o['reduce_only']]
    assert venue.position is None


def spec_D33_a_stopped_round_cools_by_the_stops_own_clock():
    """The closing fill carries STOP_RUNG, so the venue remembers how the
    round ended — across a restart too."""
    from gridgremlin.bot import STOP_RUNG
    venue, lines, clock = FakeVenue(), [], {'t': 1_000_000.0}
    over = _stopping(repeat_cooldown_seconds=60.0,
                     stop_cooldown_seconds=3600.0)
    bot = _clocked(venue, lines, clock, **over)
    stop_fill = _histfills(
        (999_000_000, 'buy', 60000.0, 0.016, 0.1, f'{bot.botid}-0-x'),
        (999_900_000, 'sell', 54000.0, 0.016, 0.1,
         f'{bot.botid}-{STOP_RUNG}-y'))
    venue.fills_history = lambda mt, sym, a, b: stop_fill
    assert bot.cycle() == {'round': 'cooling'}     # a restart, 100s after
    assert bot._cool_until == 999_900.0 + 3600.0   # the stop's hour, not 60s
    clock['t'] = 999_900.0 + 3601.0
    assert 'round_started' in bot.cycle()
    venue2, bot2 = FakeVenue(), None               # the same, after a TP
    bot2 = _clocked(venue2, lines, {'t': 1_000_000.0}, **over)
    venue2.fills_history = lambda mt, sym, a, b: _histfills(
        (999_000_000, 'buy', 60000.0, 0.016, 0.1, f'{bot2.botid}-0-x'),
        (999_900_000, 'sell', 60600.0, 0.016, 0.1, f'{bot2.botid}-0-y'))
    assert 'round_started' in bot2.cycle()         # 60s passed long ago


def _rounds(bot, n, since_ms, requote=False):
    """n finished rounds after since_ms, one before it."""
    rows = [(since_ms - 9000, 'buy', 60000.0, 0.016, 0.0, f'{bot.botid}-0-a'),
            (since_ms - 8000, 'sell', 60600.0, 0.016, 0.0, '')]
    for i in range(n):
        t = since_ms + i * 10_000
        rows.append((t + 1000, 'buy', 60000.0, 0.008, 0.0,
                     f'{bot.botid}-0-r{i}'))
        if requote:                                # a re-quoted maker base:
            rows.append((t + 2000, 'buy', 60001.0, 0.008, 0.0,   # 2 links,
                         f'{bot.botid}-0-q{i}'))                 # one round
        rows.append((t + 3000, 'buy', 59400.0, 0.016, 0.0,
                     f'{bot.botid}-1-r{i}'))
        rows.append((t + 5000, 'sell', 60300.0, 0.032, 0.0,
                     f'{bot.botid}-0-t{i}'))
    return _histfills(*rows)


_SINCE = '2026-10-02T14:30:00Z'
_SINCE_MS = 1790951400000


def spec_D41_the_bot_stands_down_after_its_last_round_finishes():
    """3Commas' maximum trade iterations: rounds OPENED are counted, the
    last one finishes, then the bot stops."""
    clock = {'t': _SINCE_MS / 1000.0 + 100.0}
    venue, lines = FakeVenue(), []
    bot = _clocked(venue, lines, clock, repeat=True, max_rounds=2,
                   max_rounds_since=_SINCE)
    venue.fills_history = lambda mt, sym, a, b: _rounds(bot, 1, _SINCE_MS)
    bot._last_pos = 0.016                          # round 1 just closed
    r = bot.cycle()
    assert bot.alive and 'round_started' in r      # 1 of 2: goes on
    venue.position = None
    venue.fills_history = lambda mt, sym, a, b: _rounds(bot, 2, _SINCE_MS)
    bot._last_pos = 0.016                          # round 2 just closed
    assert bot.cycle() == {'round': 'max_rounds'}
    assert not bot.alive and venue.position is None
    assert any('max_rounds reached: 2 of 2 rounds opened since '
               '2026-10-02T14:30:00Z' in ln for ln in lines)


def spec_D41_rounds_before_the_moment_and_requotes_are_not_counted():
    clock = {'t': _SINCE_MS / 1000.0 + 100.0}
    venue, lines = FakeVenue(), []
    bot = _clocked(venue, lines, clock, repeat=True, max_rounds=3,
                   max_rounds_since=_SINCE)
    venue.fills_history = lambda mt, sym, a, b: _rounds(bot, 2, _SINCE_MS,
                                                        requote=True)
    assert bot._rounds_opened() == 2               # not 3 (before), not 4


def spec_D41_a_restart_asks_the_venue_before_it_opens_a_round():
    """The count is the venue's: a process that comes back flat with the
    limit already reached opens nothing."""
    clock = {'t': _SINCE_MS / 1000.0 + 100.0}
    venue, lines = FakeVenue(), []
    bot = _clocked(venue, lines, clock, repeat=True, max_rounds=2,
                   max_rounds_since=_SINCE)
    venue.fills_history = lambda mt, sym, a, b: _rounds(bot, 2, _SINCE_MS)
    assert bot.cycle() == {'round': 'max_rounds'}
    assert not bot.alive and venue.position is None


def spec_D41_no_count_no_round():
    """Silence is never evidence: a venue that cannot be read opens
    nothing, and kills nothing."""
    from gridgremlin.exchange.errors import VenueError
    clock = {'t': _SINCE_MS / 1000.0 + 100.0}
    venue, lines = FakeVenue(), []
    bot = _clocked(venue, lines, clock, repeat=True, max_rounds=2,
                   max_rounds_since=_SINCE)

    def down(mt, sym, a, b):
        raise VenueError('down', 'transient')
    venue.fills_history = down
    assert bot._max_rounds_reached({'orders': []}) == {'round': 'uncounted'}
    assert bot.alive


def spec_D41_without_the_limit_the_same_history_goes_on():
    """The sabotage half."""
    clock = {'t': _SINCE_MS / 1000.0 + 100.0}
    venue, lines = FakeVenue(), []
    bot = _clocked(venue, lines, clock, repeat=True)
    venue.fills_history = lambda mt, sym, a, b: _rounds(bot, 2, _SINCE_MS)
    r = bot.cycle()
    assert bot.alive and 'round_started' in r


def _venue_stop_fills(bot, now):
    return _histfills(
        (now - 9000, 'buy', 60000.0, 0.016, 0.0, f'{bot.botid}-0-x'),
    ) + [{'time_ms': now - 2000, 'side': 'sell', 'price': 53000.0,
          'qty': 0.016, 'fee': 0.0, 'link_id': '', 'symbol': 'BTCUSDT',
          'exec_id': 'sl1', 'venue_closed': True, 'venue_kind': 'StopLoss'}]


def spec_X12_a_venue_fired_stop_is_still_the_off_button():
    """The venue closed the round at the emergency level and the mark
    bounced before the next read. The fill says how it ended: with the
    default action that is D1 — stand down, never a new round."""
    import time as _t
    venue, lines = FakeVenue(), []
    bot = _bot(venue, lines, repeat=True,
               stop={'watch': 'mark_price', 'from_base_pct': 0.10,
                     'confirm_seconds': 30, 'emergency_pct': 0.02})
    bot.cycle()
    bot.cycle()
    now = int(_t.time() * 1000)
    venue.fills_history = lambda mt, sym, a, b: _venue_stop_fills(bot, now)
    venue.position = None                          # the venue's stop fired
    venue.mark = 59000.0                           # and the mark is back
    bot.cycle()
    assert not bot.alive and venue.position is None
    assert any('round ended by the venue-held stop' in ln for ln in lines)


def spec_X12_with_end_round_a_venue_fired_stop_ends_the_round_only():
    import time as _t
    venue, lines = FakeVenue(), []
    over = _stopping(stop_cooldown_seconds=3600.0)
    over['stop'] = dict(over['stop'], confirm_seconds=30, emergency_pct=0.02)
    bot = _bot(venue, lines, **over)
    bot.cycle()
    bot.cycle()
    now = int(_t.time() * 1000)
    venue.fills_history = lambda mt, sym, a, b: _venue_stop_fills(bot, now)
    venue.position = None
    venue.mark = 59000.0
    bot.cycle()
    assert bot.alive
    assert any('cooling 3600s from the stop' in ln for ln in lines)


def spec_X12_a_row_with_no_stop_on_the_venue_reads_it_as_before():
    """The sabotage half: without a hosted stop of our own, a venue
    stop-loss close is the operator's, and M14 reads it as it always did."""
    import time as _t
    venue, lines = FakeVenue(), []
    bot = _bot(venue, lines, repeat=True)
    bot.cycle()
    bot.cycle()
    now = int(_t.time() * 1000)
    venue.fills_history = lambda mt, sym, a, b: _venue_stop_fills(bot, now)
    venue.position = None
    bot.cycle()
    assert bot.alive


# --- M19: the maximum hold period (D44) --------------------------------------

def _held_round(venue, bot, t0_ms):
    venue.fills_history = lambda mt, sym, a, b: _histfills(
        (t0_ms - 50_000, 'buy', 61000.0, 0.016, 0.0, f'{bot.botid}-0-old'),
        (t0_ms - 40_000, 'sell', 61600.0, 0.016, 0.0, ''),
        (t0_ms, 'buy', 60000.0, 0.016, 0.0, f'{bot.botid}-0-x'),
        (t0_ms + 30_000, 'buy', 59400.0, 0.016, 0.0, f'{bot.botid}-1-x'))
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': '0.032',
                      'avgPrice': '59700', 'leverage': '10',
                      'unrealisedPnl': '0'}


def spec_M19_a_round_open_too_long_closes_at_market():
    """3Commas' maximum hold period: the counter starts when the round
    does — its first fill on the venue, so a restart cannot reset it —
    and the close is profit or loss."""
    clock = {'t': 2_000_000.0}
    venue, lines = FakeVenue(mark=59000.0), []
    bot = _clocked(venue, lines, clock, repeat=True, max_hold_seconds=3600)
    _held_round(venue, bot, int((clock['t'] - 3500) * 1000))
    bot.cycle()                                    # 3500 s in: holds
    assert venue.position is not None
    assert bot._round_t0 == clock['t'] - 3500      # this round's, not the
    clock['t'] += 101                              # older round's fill
    assert bot.cycle() == {'round': 'max_hold'}
    assert venue.position is None and bot.alive    # at a loss, and goes on
    from gridgremlin.apply import rung_of
    assert rung_of(venue.market_links[-1], bot.botid) == 0     # our exit
    assert any('max hold reached' in ln and 'limit 1.00h' in ln
               for ln in lines)


def spec_M19_the_clock_is_the_venues_across_a_restart():
    clock = {'t': 2_000_000.0}
    venue, lines = FakeVenue(mark=59000.0), []
    bot = _clocked(venue, lines, clock, repeat=True, max_hold_seconds=3600)
    _held_round(venue, bot, int((clock['t'] - 4000) * 1000))
    assert bot.cycle() == {'round': 'max_hold'}    # a new process, first
    assert venue.position is None                  # cycle: already overdue


def spec_M19_no_account_no_close_and_no_limit_no_clock():
    from gridgremlin.exchange.errors import VenueError
    clock = {'t': 2_000_000.0}
    venue, lines = FakeVenue(mark=59000.0), []
    bot = _clocked(venue, lines, clock, repeat=True, max_hold_seconds=3600)
    _held_round(venue, bot, int((clock['t'] - 4000) * 1000))

    def down(mt, sym, a, b):
        raise VenueError('down', 'transient')
    venue.fills_history = down
    assert bot._max_hold_reached({'orders': []}, 0.032, clock['t']) is None
    plain = _clocked(FakeVenue(mark=59000.0), lines, clock, repeat=True)
    _held_round(plain.client, plain, int((clock['t'] - 99_000) * 1000))
    plain.cycle()
    assert plain.client.position is not None       # the sabotage half
    assert 'max_hold_seconds' not in plain.cfg


def spec_M19_a_lagging_fill_list_never_ages_a_new_round():
    """Live 2026-10-02: round 2 opened, its base fill was not yet in the
    venue's list, and the walk took round 1's first fill as its start —
    the round was closed seconds after it opened. A walk that does not
    reach flat is no answer."""
    clock = {'t': 2_000_000.0}
    venue, lines = FakeVenue(mark=59000.0), []
    bot = _clocked(venue, lines, clock, repeat=True, max_hold_seconds=300)
    t1 = int((clock['t'] - 310) * 1000)            # round 1: opened 310 s
    lagging = _histfills(                          # ago, closed 5 s ago
        (t1, 'buy', 60000.0, 0.016, 0.0, f'{bot.botid}-0-a'),
        (t1 + 305_000, 'sell', 59900.0, 0.016, 0.0, f'{bot.botid}-0-b'))
    venue.fills_history = lambda mt, sym, a, b: lagging
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': '0.016',
                      'avgPrice': '59000', 'leverage': '10',
                      'unrealisedPnl': '0'}        # round 2, just opened
    bot.cycle()
    assert venue.position is not None              # not closed on a guess
    assert bot._round_t0 is None                   # and nothing cached
    listed = lagging + _histfills(
        (t1 + 308_000, 'buy', 59000.0, 0.016, 0.0, f'{bot.botid}-0-c'))
    venue.fills_history = lambda mt, sym, a, b: listed
    bot.cycle()                                    # the fill arrived
    assert venue.position is not None
    assert bot._round_t0 == (t1 + 308_000) / 1000.0    # round 2's own
    clock['t'] += 299
    assert bot.cycle() == {'round': 'max_hold'}    # 301 s after ITS start


# --- M21: the trailing stop the engine carries (D31) -------------------------

def _trail_bot(venue, lines, **over):
    cfg = dict(venue='hyperliquid', deviation_pct=0.05,
               take_profit_avg_pct=0.03, trailing_stop_pct=0.01, repeat=True)
    cfg.update(over)
    return Bot(_cfg(**cfg), ADAPTER, venue, Notifier(sink=lines.append),
               gen_seed=1)


def spec_M21_the_engine_trails_where_the_venue_cannot():
    """A fixed distance (1% of the average: 600) behind the best mark of
    the round. Firing closes the round at market and the bot goes on."""
    venue, lines = FakeHLRound(), []
    bot = _trail_bot(venue, lines)
    bot.cycle()
    bot.cycle()                                    # holding from 60,000
    assert any('trailing stop armed bot-side: 600 behind' in ln
               for ln in lines)
    venue.mark = 60900.0
    bot.cycle()                                    # best 60,900 -> 60,300
    venue.mark = 60400.0
    assert bot.cycle() != {'round': 'trailing'}
    assert venue.position is not None
    venue.mark = 60290.0
    assert bot.cycle() == {'round': 'trailing'}
    assert venue.position is None and bot.alive
    from gridgremlin.apply import rung_of
    assert rung_of(venue.market_links[-1], bot.botid) == 0     # our exit
    assert any('trailing stop 60300 crossed' in ln for ln in lines)
    assert not getattr(venue, 'trail_calls', [])   # nothing asked of the venue
    assert sum('armed bot-side' in ln for ln in lines) == 1    # said once


def spec_M21_no_activation_no_stop():
    venue, lines = FakeHLRound(), []
    bot = _trail_bot(venue, lines, trailing_activation_pct=0.01)
    bot.cycle()
    bot.cycle()
    venue.mark = 58000.0                           # far below, never armed:
    bot.cycle()                                    # there is no stop to hit
    assert venue.position is not None
    assert not any('armed bot-side' in ln for ln in lines)
    venue.mark = 60700.0                           # past 60,600: armed
    bot.cycle()
    venue.mark = 60150.0                           # 60,700 - 600 = 60,100
    bot.cycle()
    assert venue.position is not None
    venue.mark = 60090.0
    assert bot.cycle() == {'round': 'trailing'}


def spec_M21_a_restart_trails_from_what_the_venue_can_still_show():
    """E3: the best mark is never remembered. A new process starts its
    trail at the mark it finds (no exit fills to seed from here)."""
    venue, lines = FakeHLRound(), []
    bot = _trail_bot(venue, lines)
    bot.cycle()
    bot.cycle()
    venue.mark = 61500.0
    bot.cycle()                                    # the old process saw this
    venue.mark = 60500.0                           # (61,500 - 600 would have
    fresh = _trail_bot(venue, lines)               # fired at 60,900)
    fresh.cycle()
    assert venue.position is not None and fresh._trail_best == 60500.0
    venue.mark = 59890.0                           # 60,500 - 600
    assert fresh.cycle() == {'round': 'trailing'}


def spec_M21_a_plain_stop_wins_the_tie():
    """D31's second rule. Both levels are 60,300; the stop is judged first
    and it is the off button (X1), not a round's end."""
    venue, lines = FakeHLRound(), []
    bot = _trail_bot(venue, lines,
                     stop={'watch': 'mark_price', 'level': 60300})
    venue.mark = 60900.0
    bot.cycle()
    bot.cycle()
    venue.mark = 60290.0
    assert bot.cycle() is None and not bot.alive
    assert any(' kill ' in ln and 'stop fired' in ln for ln in lines)
    assert not any('trailing stop 6' in ln and 'crossed' in ln
                   for ln in lines)


def spec_M21_the_hosting_venue_is_given_the_activation_price():
    """Venue first (D31): Bybit holds the trail, and with an activation
    the venue is told where to arm it."""
    asked = []

    class Hosting(FakeVenue):
        def set_trading_stop(self, category, symbol, position_idx, **kw):
            asked.append(dict(kw))
            kw.pop('active_price', None)
            return super().set_trading_stop(category, symbol, position_idx,
                                            **kw)
    venue, lines = Hosting(), []
    bot = _bot(venue, lines, trailing_stop_pct=0.01,
               trailing_activation_pct=0.005)
    bot.cycle()
    bot.cycle()
    trail = next(kw for kw in asked if kw.get('trailing_stop'))
    assert trail == {'trailing_stop': '600', 'active_price': '60300'}
    assert any('riding the venue, 600 behind, armed from 60300' in ln
               for ln in lines)


def spec_M21_a_new_average_starts_the_trail_again():
    """Found in rehearsal: the round's best mark dated from before a safety
    order averaged the position down; it sat above the new activation, the
    trail armed at once and closed the round at a loss on the same cycle."""
    venue, lines = FakeHLRound(), []
    bot = _trail_bot(venue, lines, trailing_activation_pct=0.005)
    bot.cycle()
    bot.cycle()                                    # 0.016 from 60,000
    venue.mark = 60200.0                           # the round's best so far
    bot.cycle()
    venue.mark = 57500.0                           # the safety at 57,000 is
    venue.position = dict(venue.position, size='0.049',    # filled on the
                          avgPrice='58000')                 # way: avg 58,000
    assert bot.cycle() != {'round': 'trailing'}    # 60,200 is not ITS best
    assert venue.position is not None
    assert bot._trail_best == 57500.0 and bot._trail_basis == 58000.0
    venue.mark = 58400.0                           # past 58,290: armed
    bot.cycle()
    venue.mark = 57810.0                           # 58,400 - 580 = 57,820
    assert bot.cycle() == {'round': 'trailing'}


# --- M22: the gauge belongs to one average; a venue-fired stop ends the round

def spec_M22_a_safety_fill_starts_the_tranche_gauge_again():
    """Replay 2026-10-03: two safety fills with no tranche fired made the
    ladder believe one had — the new, lower targets sat under the round's
    old high — and the breakeven stop armed above the mark and closed the
    round at a loss. The gauge is the average's, not the round's."""
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(breakeven_ladder=True), ADAPTER, venue,
              Notifier(sink=lines.append), gen_seed=1)
    bot._last_pos = 0.016                            # mid-round, no seed
    t1 = bot._round_targets(60000.0, 0.016, mark=60700.0)
    assert len(t1) == 1 and bot._round_hwm == 60700.0   # t1 passed at +1%
    t2 = bot._round_targets(60000.0, 0.008, mark=60100.0)
    assert len(t2) == 1                              # same average: monotone
    t3 = bot._round_targets(59000.0, 0.024, mark=59000.0)   # a safety filled
    assert len(t3) == 2 and bot._round_hwm == 59000.0       # nothing passed
    t4 = bot._round_targets(59000.0, 0.024, mark=58900.0)
    assert len(t4) == 2 and bot._round_hwm == 59000.0       # monotone again


def spec_M22_a_venue_fired_stop_then_a_stray_fill_ends_the_round():
    """The venue fills in price order: the breakeven stop above a resting
    safety order fires first, the safety fills a moment later, and the
    position is never flat. Before: the bot read the net change as a
    continuing round and sold the stray as a 'remainder' above the mark.
    Now the venue's stop-loss fill after the base order is the evidence:
    the stray is closed at market under our link, the rest cancelled."""
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(breakeven_ladder=True, repeat=True), ADAPTER,
              venue, Notifier(sink=lines.append), gen_seed=1)
    bot.cycle()
    bot.cycle()
    venue.mark = 60800.0
    venue.position = dict(venue.position, size='0.008')
    bot.cycle()                                      # stop rests at 60060
    assert bot._be_level == 60060.0
    link0 = f'{bot.botid}-0-x'
    link1 = f'{bot.botid}-1-y'
    fills = _histfills((1_000, 'buy', 60000.0, 0.016, 0.1, link0),
                       (2_000, 'sell', 60600.0, 0.008, 0.1, ''),
                       (3_000, 'sell', 60060.0, 0.008, 0.1, ''),
                       (3_500, 'buy', 59400.0, 0.016, 0.1, link1))
    fills[1].update(venue_closed=True, venue_kind='PartialTakeProfit')
    fills[2].update(venue_closed=True, venue_kind='PartialStopLoss')
    venue.fills_history = lambda mt, sym, a, b: fills
    venue.stop_book = []                             # the venue fired it
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': '0.016',
                      'avgPrice': '59400', 'leverage': '10',
                      'unrealisedPnl': '0'}
    venue.mark = 59000.0
    n_orders = len(venue.orders)
    assert n_orders > 0
    out = bot.cycle()
    assert out == {'round': 'venue_stop'}
    assert venue.position is None                    # the stray is closed
    assert venue.orders == []                        # nothing of ours rests
    assert any('fired this round' in ln and 'stray' in ln for ln in lines)
    # a round with no venue stop fill is left alone
    quiet, lines2 = FakeVenue(), []
    b2 = Bot(_tranche_cfg(breakeven_ladder=True), ADAPTER, quiet,
             Notifier(sink=lines2.append), gen_seed=1)
    b2.cycle(); b2.cycle()
    quiet.mark = 60800.0
    quiet.position = dict(quiet.position, size='0.008')
    b2.cycle()
    quiet.fills_history = lambda mt, sym, a, b: _histfills(
        (1_000, 'buy', 60000.0, 0.016, 0.1, f'{b2.botid}-0-x'))
    quiet.mark = 60700.0
    assert b2.cycle() != {'round': 'venue_stop'} and quiet.position


# --- M23: the last tranche takes the remainder --------------------------------

def spec_M23_the_last_tranche_takes_what_rounding_leaves():
    """Replay 2026-10-03: 0.017 held, two halves rounded down to 0.008 each,
    0.001 left with no exit — a round that cannot end where the lot is
    bigger than the dust. The shares sum to the holding, always."""
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(), ADAPTER, venue, Notifier(sink=lines.append),
              gen_seed=1)
    bot._last_pos = 0.017
    t = bot._round_targets(60000.0, 0.017, mark=60000.0)
    assert [q for _, q in t] == [0.008, 0.009]
    assert abs(sum(q for _, q in t) - 0.017) < 1e-12
    even = bot._round_targets(60000.0, 0.016, mark=60000.0)
    assert [q for _, q in even] == [0.008, 0.008]           # unchanged
    three = Bot(_tranche_cfg(take_profit_tranches=THREE), ADAPTER, venue,
                Notifier(sink=lines.append), gen_seed=1)
    three._last_pos = 0.017
    t3 = three._round_targets(60000.0, 0.017, mark=60000.0)
    assert abs(sum(q for _, q in t3) - 0.017) < 1e-12 and t3[-1][1] >= 0.005


def spec_M23_the_remainder_is_the_nearest_lot_not_a_hair_under():
    """Replay 2026-10-04 (AVAX, lot 0.01): 3.19 held, the first half 1.59,
    and 3.19 - 1.59 is 1.5999999999999999 in a float — floored, the last
    tranche was 1.59 too and 0.01 was left with no exit; the round never
    closed and a safety order filled a second time. The rest of an
    on-grid holding is on the grid: the last share rounds to the nearest
    lot, never under it."""
    coarse = LinearAdapter({'symbol': 'AVAXUSDT', 'qty_step': 0.01,
                            'price_tick': 0.001, 'min_qty': 0.01,
                            'min_notional': 5.0})
    assert coarse.round_qty(3.19 - 1.59) == 1.59          # the hair
    assert coarse.nearest_qty(3.19 - 1.59) == 1.6
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(symbol='AVAXUSDT', base_order_size=35.0,
                           safety_order_size=35.0, capital=120.0,
                           leverage=3, max_averaging_orders=2,
                           order_size_multiplier=1.5,
                           deviation_step_multiplier=1.0),
              coarse, venue, Notifier(sink=lines.append), gen_seed=1)
    bot._last_pos = 3.19
    t = bot._round_targets(10.946, 3.19, mark=10.946)
    assert [q for _, q in t] == [1.59, 1.6]
    assert abs(sum(q for _, q in t) - 3.19) < 1e-12
    # nearest never INVENTS: a holding of 3.18 splits 1.59 and 1.59
    t2 = bot._round_targets(10.946, 3.18, mark=10.946)
    assert [q for _, q in t2] == [1.59, 1.59]


# --- M24: a tranche exit shrinks the holding, not the ladder -------------------

def spec_M24_a_tranche_fill_does_not_rearm_a_filled_safety():
    """Replay 2026-10-04: base and the first safety order filled, then the
    first tranche took half the position — and M1's cumulative-prefix
    suppression, reading the smaller holding as 'base only', placed safety
    order 1 again. It filled again: a round two rungs past its
    `max_averaging_orders`, more capital than M2 approved. The venue's
    fills say which rungs filled THIS round; those stay suppressed whatever
    is held."""
    from gridgremlin.apply import rung_of
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(), ADAPTER, venue, Notifier(sink=lines.append),
              gen_seed=1)
    bot.cycle()                                      # base at market
    bot.cycle()                                      # ladder + tranche TPs
    so1 = next(o for o in venue.orders
               if rung_of(o['link_id'], bot.botid) == 1)
    base_qty = float(venue.position['size'])
    so1_qty = float(so1['qty'])
    link0 = next(l for l in venue.market_links)
    # safety order 1 fills: the venue averages down
    venue.orders = [o for o in venue.orders if o is not so1]
    venue.position = dict(venue.position, size=str(base_qty + so1_qty),
                          avgPrice='59700')
    venue.mark = 59400.0
    hist = _histfills((1_000, 'buy', 60000.0, base_qty, 0.1, link0),
                      (2_000, 'buy', 59400.0, so1_qty, 0.1, so1['link_id']))
    venue.fills_history = lambda mt, sym, a, b: list(hist)
    bot.cycle()
    deeper = sorted(rung_of(o['link_id'], bot.botid) for o in venue.orders
                    if not o['reduce_only'])
    assert deeper and 1 not in deeper                # prefix: SO1 is held
    # the first tranche fills: half the position leaves at +1%
    venue.mark = 60400.0
    half = (base_qty + so1_qty) / 2.0
    venue.position = dict(venue.position, size=str(half))
    venue.stop_book = venue.stop_book[1:]
    hist.append(dict(_histfills((3_000, 'sell', 60297.0, half, 0.1, ''))[0],
                     venue_closed=True, venue_kind='PartialTakeProfit'))
    bot.cycle()
    bot.cycle()
    rungs = sorted(rung_of(o['link_id'], bot.botid) for o in venue.orders
                   if not o['reduce_only'])
    assert rungs == deeper, rungs                    # SO1 is NOT back
    assert 1 in bot._round_rungs
    # a new round starts clean: the set belongs to the round
    bot._round_rungs = {1, 2}
    bot._round_rungs_at = half
    assert bot._rungs_filled_this_round(half) == frozenset({1, 2})
