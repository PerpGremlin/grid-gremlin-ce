"""M4b, M32, M14b, M33: a DCA round's single exit follows its terms, a base just
sent waits for its fill to show, a restart judges how the round ended as the
live path does, and a spot round beside an inverse market sells only what the
wallet holds. Through cycle(), on fakes that list their fills (audit
2026-11-05)."""
import sys
import time

sys.path.insert(0, 'tests')
from spec_loop import FakeVenue
from spec_round_flat import ADAPTER, Listed, SpotListed

from gridgremlin.adapters import SpotAdapter
from gridgremlin.apply import rung_of
from gridgremlin.bot import Bot
from gridgremlin.bot_basis import BasisMixin
from gridgremlin.bot_constants import RUNGS_LAG_SECONDS
from gridgremlin.bot_round import RoundMixin
from gridgremlin.config import validate_config
from gridgremlin.events import Notifier
from spec_spot import ADA_SPEC


def _cfg(**over):
    row = {'strategy': 'martingale', 'market_type': 'linear',
           'symbol': 'BTCUSDT', 'side': 'long', 'capital': 1000.0,
           'leverage': 10, 'base_order_size': 1000.0,
           'safety_order_size': 1000.0, 'order_size_multiplier': 2.0,
           'deviation_pct': 0.01, 'deviation_step_multiplier': 2.0,
           'max_averaging_orders': 3, 'take_profit_avg_pct': 0.01}
    row.update(over)
    return validate_config(row)


def _bot(venue, lines, clock, **over):
    return Bot(_cfg(**over), ADAPTER, venue, Notifier(sink=lines.append),
               gen_seed=1, clock=lambda: clock['t'])


def _exit(venue):
    return [(o['price'], o['qty']) for o in venue.orders if o['reduce_only']]


# --- M4b: a single exit follows the round's terms -----------------------------

def _restart_after_a_safety_filled_while_down(clock, lines):
    venue = Listed(clock)
    bot = _bot(venue, lines, clock)
    bot.cycle()
    bot.cycle()
    assert _exit(venue) == [(60600.0, '0.016')], _exit(venue)
    so = next(o for o in venue.orders if not o['reduce_only'])
    venue.mark = so['price'] - 10
    venue.fill(so)                                 # while the process is down
    clock['t'] += 5
    bot = _bot(venue, lines, clock)                # a restart: no last position
    for _ in range(3):
        bot.cycle()
    return venue, bot


def spec_M4b_a_restart_moves_a_stale_exit_to_the_rounds_average_and_size():
    """Audit 2026-11-05: a safety filled while the process was down; the
    restart knew no last position, so no growth, and the exit rested at the
    old average's target for the base's size alone — half the round had no
    exit, and the other half sold 0.5% too high."""
    clock, lines = {'t': time.time()}, []
    venue, bot = _restart_after_a_safety_filled_while_down(clock, lines)
    avg = float(venue.position['avgPrice'])
    want = ADAPTER.round_price(avg * 1.01)
    assert _exit(venue) == [(want, venue.position['size'])], (_exit(venue), want)
    assert sum(1 for ln in lines if '(M4b)' in ln) == 1, lines


def spec_M4b_a_hosted_tp_follows_an_average_that_moved_without_growth():
    """A fee-adjusted average (or a partial exit's) moves the target with no
    growth in the holding: the venue's TP is set again to the new target, once,
    and left alone after."""
    venue, lines = FakeVenue(), []
    bot = Bot(_cfg(), ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1)
    bot.cycle()
    bot.cycle()
    assert venue.position['takeProfit'] == '60600'
    venue.position['avgPrice'] = '59990'           # the size unchanged
    bot.cycle()
    want = ADAPTER.fmt_price(ADAPTER.round_price(59990 * 1.01))
    assert float(venue.position['takeProfit']) == float(want), venue.position
    bot.cycle()
    bot.cycle()
    assert sum(1 for ln in lines if '(M4b)' in ln) == 1, lines


def spec_M4b_a_part_filled_exit_is_left_to_fill():
    """The guard's other half: an exit part-filled reads short of a holding
    the position read has not brought down yet — that is the fill, and the
    exit keeps its place in the queue."""
    clock, lines = {'t': time.time()}, []
    venue = Listed(clock)
    bot = _bot(venue, lines, clock)
    bot.cycle()
    bot.cycle()
    tp = next(o for o in venue.orders if o['reduce_only'])
    tp['cum_exec_qty'] = 0.008                     # the position not read down yet
    before = list(venue.orders)
    bot.cycle()
    assert venue.orders == before and not any('(M4b)' in ln for ln in lines)


def spec_M4b_sabotage_reprice_on_growth_only_leaves_the_exit_stale():
    """The sabotage: the old reading (re-priced only when the holding grew)
    and the restart leaves the exit at the old target and the base's size."""
    real = RoundMixin._exit_off_terms
    RoundMixin._exit_off_terms = lambda self, *a: (False, False)
    try:
        clock, lines = {'t': time.time()}, []
        venue, bot = _restart_after_a_safety_filled_while_down(clock, lines)
    finally:
        RoundMixin._exit_off_terms = real
    assert _exit(venue) == [(60600.0, '0.016')], _exit(venue)


# --- M32: a base just sent waits for its fill to show -------------------------

def spec_M32_a_lagging_read_after_a_market_base_buys_no_second_base():
    """Audit 2026-11-05: after a market base filled, a position read that had
    not caught up read flat, and the bot bought a second base. It waits; the
    next read shows the position and the round goes on, one base bought."""
    clock, lines = {'t': time.time()}, []
    venue = Listed(clock)
    bot = _bot(venue, lines, clock)
    assert bot.cycle() == {'round_started': 1}
    venue.blank = 2
    assert bot.cycle() == {'round': 'base_pending'}
    clock['t'] += 5
    assert bot.cycle() == {'round': 'base_pending'}
    clock['t'] += 5
    bot.cycle()
    assert len(venue.markets) == 1 and venue.position['size'] == '0.016'
    assert _exit(venue) == [(60600.0, '0.016')]


def spec_M32_a_base_that_never_landed_opens_again_past_the_wait():
    """An ambiguous base that never landed: no fill of it is listed, and past
    RUNGS_LAG_SECONDS the round opens again — said, never silent."""
    clock, lines = {'t': time.time()}, []

    class Lost(Listed):
        lost = 1

        def place_market(self, *a, **k):
            if self.lost:
                self.lost -= 1
                raise OSError('timed out')
            return super().place_market(*a, **k)
    venue = Lost(clock)
    bot = _bot(venue, lines, clock)
    assert bot.cycle() == {'round': 'ambiguous'}
    assert bot.cycle() == {'round': 'base_pending'}
    clock['t'] += RUNGS_LAG_SECONDS + 1
    assert bot.cycle() == {'round_started': 1}
    assert len(venue.markets) == 1 and any('never landed' in ln for ln in lines)


def spec_M32_a_base_filled_but_never_shown_is_judged_never_bought_again():
    """The fills list the base, but no read ever shows the position: past the
    wait the flat is a round that held, judged by M14 — held open, urgent —
    and no second base is bought."""
    clock, lines = {'t': time.time()}, []
    venue = Listed(clock)
    bot = _bot(venue, lines, clock, repeat=True)
    bot.cycle()
    venue.blank = 1000
    bot.cycle()
    clock['t'] += RUNGS_LAG_SECONDS + 1
    assert bot.cycle() == {'round': 'base_unseen'}
    for _ in range(5):
        bot.cycle()
    assert len(venue.markets) == 1 and bot.alive, venue.markets
    assert any('never showed it' in ln for ln in lines)


def spec_M32_sabotage_no_wait_and_a_lagging_read_buys_a_second_base():
    real = RoundMixin._base_landing
    RoundMixin._base_landing = lambda self: None
    try:
        clock, lines = {'t': time.time()}, []
        venue = Listed(clock)
        bot = _bot(venue, lines, clock)
        bot.cycle()
        venue.blank = 1
        bot.cycle()
    finally:
        RoundMixin._base_landing = real
    assert len(venue.markets) == 2, venue.markets


# --- M14b: a restart judges how the round ended -------------------------------

def _ended_while_down(kind, link='', closed=True, **over):
    """A round open with its safeties resting; while the process is down the
    position closes by `kind`, the rungs left resting; then a restart."""
    clock, lines = {'t': time.time()}, []
    venue = Listed(clock)
    bot = _bot(venue, lines, clock, **over)
    bot.cycle()
    bot.cycle()
    venue.orders = [o for o in venue.orders if not o['reduce_only']]
    venue._record('Sell', 55000.0, 0.016, link)
    venue.fills[-1].update(venue_closed=closed, venue_kind=kind)
    venue.position = None
    clock['t'] += 600
    bot = _bot(venue, lines, clock, **over)
    return bot, venue, lines


def spec_M14b_a_liquidation_while_down_with_rungs_resting_stands_down():
    """Audit 2026-11-05: rungs resting over a flat at a restart were judged by
    M29 alone; a liquidation's fill explains the flat, so the round read as
    completed — repeat on, it cleaned up and bought the next base into what
    had just liquidated it. The restart asks M14 as the live path does."""
    bot, venue, lines = _ended_while_down('liquidation', repeat=True)
    assert bot.cycle() == {'round': 'liquidation'}
    assert not bot.alive and venue.markets[-1][2].endswith('-0-2')
    assert len(venue.markets) == 1 and not venue.orders


def spec_M14b_an_outside_close_while_down_stands_down_as_live_does():
    bot, venue, lines = _ended_while_down('', closed=False, repeat=True)
    assert bot.cycle() == {'round': 'an outside close'}
    assert not bot.alive and len(venue.markets) == 1


def spec_M14b_our_exit_while_down_still_completes_the_round():
    """The guard's other half: the round's own exit filled while down — the
    restart reads an exit and the round completes (repeat off: it stands
    down as complete, not for an outside hand)."""
    clock, lines = {'t': time.time()}, []
    venue = Listed(clock)
    bot = _bot(venue, lines, clock)
    bot.cycle()
    bot.cycle()
    venue.mark = 60700.0
    venue.fill(next(o for o in venue.orders if o['reduce_only']))
    clock['t'] += 600
    bot = _bot(venue, lines, clock)
    assert bot.cycle() == {'round': 'complete'}


def spec_M14b_sabotage_judged_by_M29_alone_and_the_restart_re_enters():
    """The sabotage: a restart that does not ask how the round ended (the
    venue's account read as our exit) and the liquidated round is cleaned up
    and bought again."""
    real = BasisMixin._how_round_ended
    BasisMixin._how_round_ended = (lambda self, days=2: 'exit' if days != 2
                                   else real(self, days))
    try:
        bot, venue, lines = _ended_while_down('liquidation', repeat=True)
        bot.cycle()
        bot.cycle()
    finally:
        BasisMixin._how_round_ended = real
    assert bot.alive and len(venue.markets) == 2, venue.markets


# --- M33: D169's wallet bounds a DCA round's exits ----------------------------

class InverseWallet(SpotListed):
    """Spot on a clock beside an inverse market on the coin: its P&L moves the
    wallet, and the cash log lists it."""

    def __init__(self, clock):
        super().__init__(clock)
        self.log = []

    def cash_log(self, coin, since_ms, now_ms):
        return [r for r in self.log if since_ms <= r['time_ms'] <= now_ms]

    def inverse_loss(self, change):
        self.base += change
        self.log.append({'id': f'x{len(self.log)}',
                         'time_ms': int(self.clock['t'] * 1000) - 1000,
                         'symbol': 'ADAUSD', 'category': 'inverse',
                         'type': 'TRADE', 'change': change})


def _spot_round(tranches):
    clock, lines = {'t': time.time()}, []
    venue = InverseWallet(clock)
    exits = ({'take_profit_tranches': [{'at_avg_pct': 0.01, 'share': 0.5},
                                       {'at_avg_pct': 0.02, 'share': 0.5}]}
             if tranches else {'take_profit_avg_pct': 0.01})
    cfg = validate_config({'strategy': 'martingale', 'market_type': 'spot',
                           'symbol': 'ADAUSDT', 'side': 'long',
                           'capital': 1000.0, 'base_order_size': 100.0,
                           'safety_order_size': 100.0,
                           'order_size_multiplier': 1.0,
                           'deviation_step_multiplier': 1.0,
                           'deviation_pct': 0.01, 'max_averaging_orders': 3,
                           'spot_borrow': True, 'spot_leverage': 2, **exits})
    bot = Bot(cfg, SpotAdapter(ADA_SPEC), venue, Notifier(sink=lines.append),
              gen_seed=1, clock=lambda: clock['t'])
    bot.beside_inverse = 'ADA'
    return bot, venue, lines, clock


def _sells(venue):
    return sorted((o['price'], float(o['qty'])) for o in venue.orders
                  if o['side'] == 'Sell')


def spec_M33_a_dca_rounds_tranches_sell_no_more_than_the_wallet():
    """Audit 2026-11-05: a spot DCA beside an inverse market sized its exits
    from its own fills, each capped alone: the inverse market took the wallet
    to 300 and the two tranches still asked to sell 500 — on margin spot the
    rest is borrowed and sold short. The tranches are trimmed to the wallet
    together, nearest first, said once; the book stands."""
    bot, venue, lines, clock = _spot_round(tranches=True)
    bot.cycle()                                    # the base, 500
    venue.inverse_loss(-200.0)                     # the wallet now 300
    for _ in range(4):
        bot.cycle()
    assert _sells(venue) == [(0.202, 250.0), (0.204, 50.0)], _sells(venue)
    assert bot._last_pos == 500.0
    assert sum(1 for ln in lines if 'trimmed to it' in ln) == 1, lines


def spec_M33_resting_tranches_are_trimmed_when_the_wallet_falls():
    bot, venue, lines, clock = _spot_round(tranches=True)
    for _ in range(3):
        bot.cycle()
    assert _sells(venue) == [(0.202, 250.0), (0.204, 250.0)]
    venue.inverse_loss(-400.0)                     # the wallet now 100
    for _ in range(3):
        bot.cycle()
    assert _sells(venue) == [(0.202, 100.0)], _sells(venue)


def spec_M33_a_single_exit_follows_the_wallet_down_and_rests_none_at_zero():
    """The single exit is trimmed as the tranches are; a wallet emptied by the
    inverse market leaves no sell resting and no refusal every cycle (it was
    'qty zero refused', urgent, once a second)."""
    bot, venue, lines, clock = _spot_round(tranches=False)
    for _ in range(3):
        bot.cycle()
    assert _sells(venue) == [(0.202, 500.0)]
    venue.inverse_loss(-400.0)
    bot.cycle()
    assert _sells(venue) == [(0.202, 100.0)], _sells(venue)
    venue.inverse_loss(-100.0)                     # the wallet empty
    for _ in range(3):
        bot.cycle()
    assert _sells(venue) == [] and bot.alive
    assert not any('refused' in ln for ln in lines), lines


def spec_M33_sabotage_no_trim_and_the_tranches_ask_past_the_wallet():
    real = BasisMixin._exits_to_wallet
    BasisMixin._exits_to_wallet = lambda self, desired: desired
    try:
        bot, venue, lines, clock = _spot_round(tranches=True)
        bot.cycle()
        venue.inverse_loss(-200.0)
        for _ in range(3):
            bot.cycle()
    finally:
        BasisMixin._exits_to_wallet = real
    assert sum(q for _, q in _sells(venue)) == 500.0, _sells(venue)
