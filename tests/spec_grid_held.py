# Specs for SPEC G31-G34: what a grid holds, read right when the fill list lags
# the position, when its lots are one step, when its lattice reaches zero, and
# when its range was edited under a holding. Each was reproduced on the replay
# venue by the audit of 2026-11-05 before it was fixed.

import tempfile
from pathlib import Path

import gridgremlin.ladder as ladder
from gridgremlin.adapters import LinearAdapter
from gridgremlin.bot import RUNGS_LAG_SECONDS, Bot
from gridgremlin.config import validate_config
from gridgremlin.events import Notifier
from gridgremlin.fees import FEE_FLOOR_PCT
from gridgremlin.ladder import plan_grid
from gridgremlin.replay import BarVenue
from gridgremlin.tombstones import Tombstones

T0 = 1.8e9


def _adapter(step):
    return LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': step, 'price_tick': 0.1,
                          'min_qty': step, 'min_notional': 5.0, 'settle_coin': 'USDT'})


def _cfg(**over):
    row = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
           'capital': 1000.0, 'leverage': 1, 'lower': 50000.0, 'upper': 90000.0,
           'rungs': 9, 'spacing_type': 'fixed'}
    row.update(over)
    return validate_config(row)


class Lagging(BarVenue):
    """The replay venue as Bybit behaves: each fill is listed `lag` seconds
    after it happened, and a reduce-only order dies with the position."""

    def __init__(self, adapter, lag=0.0):
        super().__init__(adapter, 'long', 0.0002, 0.00055)
        self.lag, self.listed_at = lag, {}

    def _fill(self, side, qty, price, fee_rate, link_id='', kind=''):
        before = len(self.fills)
        q = super()._fill(side, qty, price, fee_rate, link_id, kind)
        if len(self.fills) > before:
            f = self.fills[-1]
            self.listed_at[f['exec_id']] = self.now + self.lag
            f['reduces'] = side != self.entry
        if not self.steps:
            self.orders = [o for o in self.orders if not o['reduce_only']]
        return q

    def fills_history(self, market_type, symbol, since_ms, until_ms):
        return [dict(f) for f in super().fills_history(market_type, symbol, since_ms, until_ms)
                if self.listed_at.get(f['exec_id'], 0) <= self.now]

    def hand_close(self):
        """The owner closes the position at market in the app: no link."""
        self._fill('Sell', self.held, self.price, self.fee_taker)


def _run(cfg, adapter, venue, seed=7):
    lines = []
    bot = Bot(cfg, adapter, venue, Notifier(sink=lines.append), gen_seed=seed,
              clock=lambda: venue.now)
    bot.tombs = Tombstones(Path(tempfile.mkdtemp()) / 't.json')

    def cycle(n=1):
        for _ in range(n):
            if bot.alive:
                bot.cycle()
            venue.now += 1
    return bot, lines, cycle


def _move(venue, price, cycle, n):
    venue.advance(price, venue.now + 1)
    cycle(n)


def _sells(venue):
    return sorted(o['price'] for o in venue.orders if o['side'] == 'Sell')


# --- G32: a flat the fills do not explain yet is held, not a trip -------------

def _hand_closed(lag):
    cfg, ad = _cfg(spacing_type='percent'), _adapter(0.0001)
    venue = Lagging(ad, lag)
    venue.advance(70500.0, T0)
    bot, lines, cycle = _run(cfg, ad, venue)
    cycle(2)
    _move(venue, 66000.0, cycle, int(lag) + 3)        # two lots, their exit rests
    assert venue.held > 0 and _sells(venue)
    venue.hand_close()                                # the exits die with it
    cycle(int(lag) + 10)
    _move(venue, 62000.0, cycle, 3)                   # the next dip
    return bot, venue, lines


def spec_G32_a_hand_close_behind_a_lagging_fill_list_is_never_a_trip():
    """Bybit cancels a reduce-only exit when the position closes, so a hand's
    close makes an exit link vanish exactly as an exit's fill does. With the
    fill list 3 s behind, the fast path read the silence as a trip: the bot
    lived and bought the next dip (audit 2026-11-05). Held until the fills say
    how it closed, it is D1's outside close: killed, nothing bought."""
    for lag in (0.0, 3.0):
        bot, venue, lines = _hand_closed(lag)
        assert not bot.alive and venue.held == 0.0, lag
        assert any('outside close (D1)' in ln for ln in lines), lag


def spec_G32_our_exit_behind_a_lagging_fill_list_is_still_a_trip():
    """The bound's other half: our own exit filling to flat, listed 3 s late,
    waits those seconds and is a trip — the bot lives and buys the next dip."""
    cfg, ad = _cfg(), _adapter(0.0001)
    venue = Lagging(ad, 3.0)
    venue.advance(71000.0, T0)
    bot, lines, cycle = _run(cfg, ad, venue)
    cycle(2)
    _move(venue, 69000.0, cycle, 8)                   # one lot at 70k
    assert venue.held > 0 and _sells(venue) == [75000.0]
    _move(venue, 75500.0, cycle, 1)                   # its exit fills: flat
    assert venue.held == 0.0
    out = bot.cycle()
    assert out == {'confirming_flat': 'no account of the closing fill yet (G32)'}
    cycle(8)
    assert bot.alive
    _move(venue, 69000.0, cycle, 8)
    assert bot.alive and venue.held > 0


def spec_G32_no_account_past_the_wait_is_an_unaccounted_hand():
    """A fill list that never explains the flat ends the wait at
    RUNGS_LAG_SECONDS, as E9/M14's slow path does: an unaccounted hand, D1."""
    bot, venue, lines = _hand_closed(RUNGS_LAG_SECONDS + 10)
    assert not bot.alive and venue.held == 0.0
    assert any('unaccounted hand' in ln and 'G32' in ln for ln in lines)


def spec_G32_sabotage_a_wait_of_nothing_kills_our_own_trip():
    """The sabotage half of the bound: no wait at all, and our own exit listed
    3 s late reads as an unaccounted hand — the healthy bot is killed."""
    import gridgremlin.bot as bot_module
    real = bot_module.RUNGS_LAG_SECONDS
    bot_module.RUNGS_LAG_SECONDS = 0.0
    try:
        cfg, ad = _cfg(), _adapter(0.0001)
        venue = Lagging(ad, 3.0)
        venue.advance(71000.0, T0)
        bot, lines, cycle = _run(cfg, ad, venue)
        cycle(2)
        _move(venue, 69000.0, cycle, 8)
        _move(venue, 75500.0, cycle, 8)
    finally:
        bot_module.RUNGS_LAG_SECONDS = real
    assert not bot.alive and any('unaccounted hand' in ln for ln in lines)


# --- G31: a fixed lattice's block never reaches a price of zero ---------------

def _zero_case():
    # 50k..90k in 5 rungs: a 10k step, so rung -5 is exactly 0
    cfg, ad = _cfg(rungs=5), _adapter(0.0001)
    held = sum(ad.round_qty(200 / p) for p in (80000, 70000, 60000))
    return cfg, ad, held


def spec_G31_a_fixed_lattice_block_never_reaches_a_price_of_zero():
    """Three lots bought 80k, 70k, 60k (average 70k), the mark at 55k, no fill
    account: the block search tried counts whose block ran past the lattice's
    zero, and a lot there (notional / 0) raised ZeroDivisionError every cycle —
    a bot stuck with no exit (audit 2026-11-05). Each lot's exit now rests one
    rung above it."""
    cfg, ad, held = _zero_case()
    plan = plan_grid(cfg, ad, 55000.0, held_base=held, basis=70000.0, bid=54999, ask=55001)
    exits = sorted((o['price'], o['qty']) for o in plan if o.get('exit'))
    assert exits == [(70000.0, 0.0033), (80000.0, 0.0028), (90000.0, 0.0025)]


def spec_G31_lots_older_than_the_history_window_still_get_their_exit():
    """The bot's half: those fills 31 days old (past HISTORY_WINDOW_DAYS), the
    process restarted — it cycles, and an exit rests."""
    cfg, ad, _ = _zero_case()
    venue = Lagging(ad)
    venue.advance(85000.0, T0)
    for p in (80000, 70000, 60000):
        venue.price = p + 1
        venue.place_order('linear', 'BTCUSDT', 'Buy', ad.fmt_qty(ad.round_qty(200 / p)),
                          str(p), f'linBTCUSDTl-{(p - 50000) // 10000}-1', 1)
        venue.advance(p - 1, venue.now + 1)
    venue.advance(55000.0, venue.now + 31 * 86400)
    bot, lines, cycle = _run(cfg, ad, venue)
    for _ in range(3):
        bot.cycle()
        venue.now += 1
    assert bot.alive and _sells(venue) and min(_sells(venue)) >= 70000.0


def spec_G31_sabotage_a_block_past_zero_raises_again():
    """The sabotage half: let the search price a block past zero and the plan
    raises ZeroDivisionError, as on main before the fix."""
    cfg, ad, held = _zero_case()
    real = ladder._priced
    ladder._priced = lambda cfg, block: True
    try:
        plan_grid(cfg, ad, 55000.0, held_base=held, basis=70000.0, bid=54999, ask=55001)
    except ZeroDivisionError:
        return
    finally:
        ladder._priced = real
    raise AssertionError('a block past zero was priced and nothing raised')


# --- G33: a lot of one step is named, never bought again while held ----------

def spec_G33_a_one_step_lot_is_never_bought_again_while_held():
    """1,000 USDT over 9 rungs of BTC on Bybit's 0.001 step: every lot is ONE
    step. The walk stopped at the caller's slack (2% and a step) — a whole lot —
    before reaching the lot, named nothing, and the held 70k rung was bought
    again on the next dip (audit 2026-11-05). Covered exactly, the lot is named
    and its rung stays suppressed."""
    cfg, ad = _cfg(), _adapter(0.001)
    venue = Lagging(ad)
    venue.advance(71000.0, T0)
    bot, lines, cycle = _run(cfg, ad, venue, seed=1)
    cycle(2)
    _move(venue, 69000.0, cycle, 3)                   # buys 70k (rung 4)
    _move(venue, 64000.0, cycle, 3)                   # buys 65k (rung 3)
    _move(venue, 70500.0, cycle, 3)                   # 65k's exit at 70k fills
    assert venue.held == 0.001 and bot._rungs_cache[2] == [4]
    assert 70000.0 not in [o['price'] for o in venue.orders if o['side'] == 'Buy']
    _move(venue, 69500.0, cycle, 3)
    buys = sum(1 for f in venue.fills if f['side'] == 'buy' and f['price'] == 70000.0)
    assert buys == 1 and venue.held == 0.001


# --- G34: an edited range never re-places a lot's exit below its cost ---------

def _relattice(lot_rung=None):
    row = dict(lower=50000.0, upper=90000.0)
    ad = _adapter(0.0001)
    venue = Lagging(ad)
    venue.advance(71000.0, T0)
    bot, _, cycle = _run(_cfg(**row), ad, venue, seed=1)
    cycle(2)
    _move(venue, 69000.0, cycle, 3)
    _move(venue, 66000.0, cycle, 3)                   # one lot at 70k, mark 66k
    assert [f['price'] for f in venue.fills] == [70000.0] and _sells(venue) == [75000.0]
    # the range narrowed on the edit page (a COLD key) and the fleet restarted:
    # 40k..72k in 9 rungs, where the link's rung 4 is 56k
    again, _, cycle = _run(_cfg(lower=40000.0, upper=72000.0), ad, venue, seed=99)
    if lot_rung:
        again._lot_rung = lot_rung
    cycle(3)
    return venue


def spec_G34_an_edited_range_never_rests_an_exit_below_the_lots_cost():
    """The lot's link names rung 4 of the lattice it was bought on; on the new
    one rung 4 is 56k, its exit beyond the ref displaced to 68k — a sell under
    the 70k lot (audit 2026-11-05). A lot not bought at its link's rung is
    re-named by its own price: its exit is the nearest rung clearing its cost
    and G6's fee floor, 72k."""
    venue = _relattice()
    assert _sells(venue) == [72000.0]
    assert min(_sells(venue)) >= 70000.0 * (1 + FEE_FLOOR_PCT)


def spec_G34_a_lot_bought_at_its_own_rung_keeps_it():
    """Without an edit nothing is re-named: a fill at its link's rung pairs
    from that rung, as G23 says."""
    cfg, ad = _cfg(), _adapter(0.0001)
    bot, _, _ = _run(cfg, ad, Lagging(ad))
    assert bot._lot_rung(4, 70000.0) == 4
    assert bot._lot_rung(ladder.SEED_RUNG, 70500.0) == ladder.SEED_RUNG
    assert bot._lot_rung(4, 74000.0) == 4                  # its exit 75k clears it
    assert bot._lot_rung(4, 76000.0) == 5                  # 75k would not: 80k


def spec_G34_sabotage_the_links_rung_trusted_sells_under_cost():
    """The sabotage half: trust the link's rung across the edit and the lot's
    exit rests at 68k, under its 70k cost."""
    venue = _relattice(lot_rung=lambda rung, price: rung)
    assert _sells(venue) == [68000.0]
