"""M29, M31, G15b: a DCA round ends only on a flat its fills explain, an open
round keeps its coins past the history window, and the spot basis walk covers
a one-step holding. Through cycle(), on fakes that list their fills."""
import sys
import time

sys.path.insert(0, 'tests')
from spec_loop import FakeVenue
from spec_spot import ADA_SPEC, FakeSpotVenue

from gridgremlin.adapters import LinearAdapter, SpotAdapter
from gridgremlin.apply import rung_of
from gridgremlin.bot import Bot
from gridgremlin.bot_basis import BasisMixin
from gridgremlin.config import validate_config
from gridgremlin.events import Notifier

ADAPTER = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001,
                         'price_tick': 0.1, 'min_qty': 0.001,
                         'min_notional': 5.0, 'settle_coin': 'USDT'})
D = 86_400


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


class Listed(FakeVenue):
    """A perp venue whose fills are listed at once, with `blank` position
    reads to come (a lagging or empty answer under load)."""
    hosts_position_tp = False

    def __init__(self, clock):
        super().__init__()
        self.clock, self.fills, self.blank, self.markets = clock, [], 0, []

    def position_list(self, category, symbol):
        if self.blank:
            self.blank -= 1
            return {'list': []}
        return super().position_list(category, symbol)

    def fills_history(self, market_type, symbol, since_ms, until_ms):
        return [f for f in self.fills if since_ms <= f['time_ms'] <= until_ms]

    def _record(self, side, price, qty, link):
        self.fills.append({'exec_id': f'e{len(self.fills)}', 'side': side.lower(),
                           'price': price, 'qty': qty, 'fee': 0.0,
                           'time_ms': int(self.clock['t'] * 1000) - 1000 + len(self.fills),
                           'link_id': link or '', 'venue_closed': False,
                           'venue_kind': '', 'market_type': 'linear'})

    def _move(self, side, qty, price, idx=0):
        pos = self.position
        if pos and pos['side'] != side:
            left = round(float(pos['size']) - qty, 9)
            self.position = None if left <= 0 else dict(pos, size=str(left))
        elif pos:
            size = float(pos['size'])
            avg = (size * float(pos['avgPrice']) + qty * price) / (size + qty)
            self.position = dict(pos, size=str(size + qty), avgPrice=str(avg))
        else:
            self.position = {'positionIdx': idx, 'side': side, 'size': str(qty),
                             'avgPrice': str(price), 'leverage': '10',
                             'unrealisedPnl': '0'}

    def place_market(self, category, symbol, side, qty, position_idx=0,
                     reduce_only=False, link_id=None, borrow=False):
        self.markets.append((side, qty, link_id))
        self._record(side, self.mark, float(qty), link_id)
        self._move(side, float(qty), self.mark, position_idx)

    def fill(self, order):
        self.orders = [o for o in self.orders if o is not order]
        self._record(order['side'], order['price'], float(order['qty']),
                     order['link_id'])
        self._move(order['side'], float(order['qty']), order['price'],
                   order['position_idx'])


def _tranche_round(**over):
    clock = {'t': time.time()}
    venue, lines = Listed(clock), []
    bot = Bot(_tranche_cfg(**over), ADAPTER, venue, Notifier(sink=lines.append),
              gen_seed=1, clock=lambda: clock['t'])
    bot.cycle()                                    # base at market
    bot.cycle()                                    # tranches + ladder rest
    exits = sorted((o for o in venue.orders if o['reduce_only']),
                   key=lambda o: o['price'])
    venue.mark = exits[0]['price'] + 5
    venue.fill(exits[0])                           # tranche 1 fills
    clock['t'] += 5
    bot.cycle()
    bot.cycle()
    return bot, venue, lines, clock


def _exits(venue):
    return [o for o in venue.orders if o['reduce_only']]


# --- M29: a DCA round ends only on a flat its own fills explain ----------------

def spec_M29_one_blank_read_after_a_tranche_never_ends_the_round():
    """Audit 2026-11-05: after tranche 1 filled, one empty position read found
    that tranche's fill, read it as our exit, and ended the round — repeat
    off, the bot stood down with half its coins held and no exit; repeat on,
    it cancelled the exit and bought a new base on top of them. The round's
    fills still hold the second half: the read waits, the next read shows the
    position, and the round goes on with its exit resting."""
    for repeat in (False, True):
        bot, venue, lines, clock = _tranche_round(repeat=repeat)
        held, exits, n = venue.position['size'], _exits(venue), len(venue.markets)
        assert held == '0.008' and len(exits) == 1, (held, exits)
        venue.blank = 1
        out = bot.cycle()
        assert out == {'confirming_close': 'the fills do not explain the '
                                           'flat yet (M29)'}, out
        assert bot.alive and _exits(venue) == exits, repeat
        clock['t'] += 5
        bot.cycle()
        bot.cycle()
        assert bot.alive and venue.position['size'] == held, repeat
        assert _exits(venue) == exits and len(venue.markets) == n, repeat
        assert not any('round complete' in ln or 're-anchors' in ln
                       for ln in lines), repeat


def spec_M29_our_last_tranche_filling_still_ends_the_round_at_once():
    """The guard's other half: the last tranche fills, the fills explain the
    flat in full, and the round ends on that read — repeat off, it stands
    down; nothing waits."""
    bot, venue, lines, clock = _tranche_round()
    venue.mark = _exits(venue)[0]['price'] + 5
    venue.fill(_exits(venue)[0])
    clock['t'] += 5
    assert bot.cycle() == {'round': 'complete'}
    assert not bot.alive and venue.position is None


def spec_M29_a_flat_its_fills_never_explain_is_held_open_past_the_wait():
    """Reads stay empty while the fills hold coins: past RUNGS_LAG_SECONDS the
    round is held open, said once and urgently — never ended, nothing
    placed or cancelled."""
    from gridgremlin.bot_constants import RUNGS_LAG_SECONDS
    bot, venue, lines, clock = _tranche_round()
    exits = _exits(venue)
    venue.blank = 1000
    assert bot.cycle()['confirming_close']
    clock['t'] += RUNGS_LAG_SECONDS + 1
    assert bot.cycle() == {'round': 'unaccounted'}
    assert bot.cycle() == {'round': 'unaccounted'}
    said = [ln for ln in lines if 'holding this round open' in ln and 'M29' in ln]
    assert len(said) == 1 and bot.alive and _exits(venue) == exits, said


def spec_M29_a_restarts_first_blank_read_never_ends_the_round():
    """The restart path: a new process knows no last position, and a flat
    first read while our rungs rested counted as a round that completed
    while it was down — repeat off, it killed the bot; repeat on, it
    cancelled the round's orders as cleanup. The fills still hold coins:
    it waits, the next read shows the position, and the round goes on."""
    for repeat in (False, True):
        bot, venue, lines, clock = _tranche_round(repeat=repeat)
        orders, n = list(venue.orders), len(venue.markets)
        bot = Bot(_tranche_cfg(repeat=repeat), ADAPTER, venue,
                  Notifier(sink=lines.append), gen_seed=1,
                  clock=lambda: clock['t'])        # a restart
        venue.blank = 1
        out = bot.cycle()
        assert out == {'confirming_close': 'the fills do not explain the '
                                           'flat yet (M29)'}, (repeat, out)
        assert bot.alive and venue.orders == orders, repeat
        clock['t'] += 5
        bot.cycle()
        bot.cycle()
        assert bot.alive and venue.position['size'] == '0.008', repeat
        assert _exits(venue) and len(venue.markets) == n, repeat
        assert not any('round complete' in ln or 're-anchors' in ln
                       for ln in lines), repeat


def spec_M29_a_round_that_ended_while_down_still_ends_at_restart():
    """The other half: the last tranche filled while the process was down;
    the fills explain the flat, and the restart's first read ends the round
    (repeat off: it stands down)."""
    bot, venue, lines, clock = _tranche_round()
    venue.fill(_exits(venue)[0])
    clock['t'] += 5
    bot = Bot(_tranche_cfg(), ADAPTER, venue, Notifier(sink=lines.append),
              gen_seed=1, clock=lambda: clock['t'])
    assert bot.cycle() == {'round': 'complete'} and not bot.alive


def spec_M29_sabotage_one_account_of_a_close_ends_the_round_again():
    """The sabotage: a flat taken as explained by any one exit fill (the
    old reading) and the blank read after tranche 1 ends the round — the
    bot stands down with coins held."""
    real = BasisMixin._round_flat_explained
    BasisMixin._round_flat_explained = lambda self: True
    try:
        bot, venue, lines, clock = _tranche_round()
        venue.blank = 1
        bot.cycle()
    finally:
        BasisMixin._round_flat_explained = real
    assert not bot.alive and float(venue.position['size']) > 0


# --- M31: an open round keeps its coins past the history window ----------------

class SpotListed(FakeSpotVenue):
    """Spot on a clock: the wallet is the position, fills stamped by it."""
    hosts_position_tp = False

    def __init__(self, clock):
        super().__init__(mark=0.2, base=0.0)
        self.clock, self.markets, self.reads = clock, [], 0

    def fills_history(self, market_type, symbol, since_ms, until_ms):
        self.reads += 1
        return super().fills_history(market_type, symbol, since_ms, until_ms)

    def record_fill(self, side, price, qty, link_id):
        self.fill_log.append({'exec_id': f'e{len(self.fill_log)}', 'side': side,
                              'price': price, 'qty': qty, 'fee': 0.0,
                              'time_ms': int(self.clock['t'] * 1000) - 1000
                              + len(self.fill_log),
                              'link_id': link_id, 'venue_closed': False,
                              'venue_kind': '', 'market_type': 'spot'})

    def place_market(self, category, symbol, side, qty, position_idx=0,
                     reduce_only=False, link_id=None, borrow=False):
        q = float(qty)
        self.markets.append((side, qty, link_id))
        self.base += q if side == 'Buy' else -q
        self.record_fill(side.lower(), self.mark, q, link_id)

    def place_order(self, category, symbol, side, qty, price, link_id,
                    position_idx=0, reduce_only=False, post_only=True,
                    borrow=False):
        return FakeVenue.place_order(self, category, symbol, side, qty, price,
                                     link_id, position_idx, reduce_only,
                                     post_only, borrow)


def _spot_dca(venue, clock, lines):
    cfg = validate_config({'strategy': 'martingale', 'market_type': 'spot',
                           'symbol': 'ADAUSDT', 'side': 'long',
                           'capital': 1000.0, 'base_order_size': 100.0,
                           'safety_order_size': 100.0,
                           'order_size_multiplier': 1.0,
                           'deviation_step_multiplier': 1.0,
                           'deviation_pct': 0.01, 'max_averaging_orders': 3,
                           'take_profit_avg_pct': 0.01, 'repeat': True})
    return Bot(cfg, SpotAdapter(ADA_SPEC), venue, Notifier(sink=lines.append),
               gen_seed=1, clock=lambda: clock['t'])


def _old_round(lines):
    """A base, then safety 1 fourteen days on; then the clock moves on."""
    clock = {'t': time.time() - 60 * D}
    venue = SpotListed(clock)
    bot = _spot_dca(venue, clock, lines)
    for _ in range(3):
        bot.cycle()
    so1 = next(o for o in venue.orders if rung_of(o['link_id'], bot.botid) == 1)
    clock['t'] += 14 * D
    venue.mark = so1['price'] - 0.0005
    venue.fill_order(so1)
    for _ in range(3):
        bot.cycle()
    return bot, venue, clock


def _sells(venue):
    return [float(o['qty']) for o in venue.orders if o['side'] == 'Sell']


def spec_M31_a_spot_round_older_than_the_window_keeps_its_coins():
    """Audit 2026-11-05: 30 days on, the base fell out of the fills window, the
    holding (D58: the bot's own fills) lost its coins and the exit sold only
    the safety's; 50 days on, a restart read the round as flat and bought a
    new base on top of them. Read back to its base, the round holds what it
    bought — live, and across a restart — and buys nothing new."""
    lines = []
    bot, venue, clock = _old_round(lines)
    full, n = venue.base, len(venue.markets)
    assert _sells(venue) == [full]
    clock['t'] += 20 * D                           # the base is 34 days old
    for _ in range(2):
        bot.cycle()
    assert bot._last_pos == full and _sells(venue) == [full], _sells(venue)
    clock['t'] += 20 * D                           # every fill past the window
    for _ in range(3):
        bot.cycle()
    assert bot._last_pos == full and _sells(venue) == [full]
    bot = _spot_dca(venue, clock, lines)            # a restart
    for _ in range(3):
        bot.cycle()
    assert bot._last_pos == full and _sells(venue) == [full], _sells(venue)
    assert len(venue.markets) == n, venue.markets[n:]
    assert any('read from its base (M31)' in ln for ln in lines)


def spec_M31_the_reach_is_sought_once_then_read_on_from_where_it_ended():
    """Bounded: the seek back is once per process; each cycle after reads the
    fills from where the kept ones end, one read per question."""
    lines = []
    bot, venue, clock = _old_round(lines)
    clock['t'] += 40 * D
    bot.cycle()
    reads = venue.reads
    for _ in range(3):
        clock['t'] += 60
        bot.cycle()
    per_cycle = (venue.reads - reads) / 3
    assert per_cycle <= 3, per_cycle
    assert sum('read from its base (M31)' in ln for ln in lines) == 1


def spec_M31_sabotage_no_reach_and_the_round_loses_its_coins():
    """The sabotage: never seek past the window and the round 40 days on
    holds nothing — its exit gone, its coins no one's."""
    real = BasisMixin._seek_round_base
    BasisMixin._seek_round_base = lambda self, window_ms, fills: 0
    try:
        lines = []
        bot, venue, clock = _old_round(lines)
        full = venue.base
        clock['t'] += 40 * D
        bot = _spot_dca(venue, clock, lines)
        for _ in range(3):
            bot.cycle()
    finally:
        BasisMixin._seek_round_base = real
    assert bot._last_pos != full


# --- G15b: the spot basis walk covers the holding exactly ----------------------

class OneStep(FakeSpotVenue):
    """A coin whose dust is under one step."""

    def read_symbol_truth(self, market_type, symbol, funding_interval=480.0):
        from gridgremlin.exchange.bybit.truth import read_symbol_truth
        return read_symbol_truth(self, market_type, symbol, funding_interval,
                                 base_coin='ADA', dust=0.0001)


def _one_step():
    """Bybit's BTC step on a 315 USDT spot grid (x2) over 9 rungs: one lot,
    one step. Lots bought at 65k and 70k; the 70k one sold at 75k."""
    from spec_spot import _spot_cfg
    ad = SpotAdapter({'symbol': 'ADAUSDT', 'qty_step': 0.001, 'min_qty': 0.001,
                      'price_tick': 0.1, 'min_notional': 1.0})
    venue = OneStep(mark=71000.0, base=0.001)
    venue.record_fill('buy', 65000.0, 0.001, 'spoADAUSDTl-3-1')
    venue.record_fill('buy', 70000.0, 0.001, 'spoADAUSDTl-4-2')
    venue.record_fill('sell', 75000.0, 0.001, 'spoADAUSDTl-5-3')
    cfg = _spot_cfg(lower=50000.0, upper=90000.0, rungs=9, capital=315.0,
                    spacing_type='fixed',
                    stop={'watch': 'mark_price', 'level': 45000.0})
    return Bot(cfg, ad, venue, Notifier(sink=[].append), gen_seed=1), venue


def spec_G15b_a_one_step_spot_holding_gets_its_basis():
    """Audit 2026-11-05: the walk stopped at a slack of 2% and a step — for a
    one-step holding, the whole holding — at the first buy, which the newer
    sell had consumed: nothing covered, no basis, the holding's exit
    withheld. Covered exactly, as G33's walk, the held lot is the 65k one,
    and its exit rests above its cost."""
    bot, venue = _one_step()
    assert bot._derive_basis(0.001) == 65000.0
    bot._basis_cache = None
    bot.cycle()
    bot.cycle()
    sells = [o['price'] for o in venue.orders if o['side'] == 'Sell']
    assert sells and min(sells) >= 65000.0 * 1.0025, sells


def spec_M29_sabotage_no_confirmation_and_a_restarts_blank_read_kills():
    """The restart half's sabotage: no M29 confirmation and the restart's
    blank first read stands the bot down with its coins held."""
    from gridgremlin.bot_round import RoundMixin
    real = RoundMixin._confirm_round_flat
    RoundMixin._confirm_round_flat = lambda self: None
    try:
        bot, venue, lines, clock = _tranche_round()
        bot = Bot(_tranche_cfg(), ADAPTER, venue, Notifier(sink=lines.append),
                  gen_seed=1, clock=lambda: clock['t'])
        venue.blank = 1
        bot.cycle()
    finally:
        RoundMixin._confirm_round_flat = real
    assert not bot.alive and float(venue.position['size']) > 0
