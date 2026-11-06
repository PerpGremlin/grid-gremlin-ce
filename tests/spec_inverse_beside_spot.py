# Specs for D169: a spot row and an inverse market on one coin share a wallet.
# The venue's cash log says which market moved the coin (measured 2026-11-02 on
# the demo key: an inverse fill and its funding each listed under the inverse
# symbol, and each equal to the spot row's move to the last digit). The replay
# venue holds one market, so this pair runs on the fake spot venue.

import time
from contextlib import contextmanager

import gridgremlin.bot_basis as bot_basis
from gridgremlin.adapters import SpotAdapter
from gridgremlin.bot import RUNGS_LAG_SECONDS, Bot
from gridgremlin.bot_constants import FUNDING_LAG_SECONDS, FUNDING_WINDOW_SECONDS
from gridgremlin.events import Notifier
from gridgremlin.exchange.errors import VenueError
from gridgremlin.main import mark_shared_coins

from spec_spot import ADA_SPEC, FakeSpotVenue, _spot_cfg


class Wallet(FakeSpotVenue):
    """The wallet with its cash log; the log may lag or refuse."""

    def __init__(self, base=0.0):
        super().__init__(mark=0.1950, base=base)
        self.log, self.log_reads, self.refuse = [], 0, None

    def cash_log(self, coin, since_ms, now_ms):
        self.log_reads += 1
        if self.refuse:
            raise self.refuse
        return [r for r in self.log if since_ms <= r['time_ms'] <= now_ms]

    def inverse_moves(self, change, listed=True, symbol='ADAUSD', kind='TRADE'):
        self.base += change
        if listed:
            self.list_move(change, symbol, kind)

    def list_move(self, change, symbol='ADAUSD', kind='TRADE'):
        self.log.append({'id': f'x{len(self.log)}', 'time_ms': int(time.time() * 1000) - 1000,
                         'symbol': symbol, 'category': 'inverse', 'type': kind,
                         'change': change})


def _pair(venue=None, beside=True, **over):
    venue, lines, later = venue or Wallet(), [], [0.0]
    bot = Bot(_spot_cfg(**over), SpotAdapter(ADA_SPEC), venue, Notifier(sink=lines.append),
              gen_seed=1, clock=lambda: time.time() + later[0])
    if beside:
        bot.beside_inverse = 'ADA'
    return bot, venue, lines, later


def _holding(bot, venue, fills=3):
    """Lots bought off the ladder; each buy's fee taken in the coin, so its own
    fills stand above the wallet and D58 reads the wallet."""
    bot.cycle()
    bot.cycle()
    for _ in range(fills):
        top = max((o for o in venue.orders if o['side'] == 'Buy'), key=lambda o: o['price'])
        venue.mark = top['price'] - 0.002
        venue.fill_order(top)
        venue.base -= 0.05 * float(top['qty']) / 100.0
        for _ in range(3):
            bot.cycle()


def _orders(venue):
    return sorted((o['side'], o['price'], o['qty']) for o in venue.orders)


FUNDING_HOUR = 1_794_240_000      # 16:00 UTC: one of Bybit's inverse funding hours


@contextmanager
def _clock_at(t):
    """Every clock (the bot's, the fake wallet's stamps) pinned at t and moved by
    hand: a wait judged by the hour must not depend on when the suite runs."""
    real, now = time.time, [t]
    time.time = lambda: now[0]
    try:
        yield now
    finally:
        time.time = real


def spec_D169_a_fee_and_funding_never_move_the_row():
    """Measured on the demo sub, 2026-11-02: the inverse bot's first fill and
    funding moved the spot row's position by exactly their log rows, each an
    urgent G26 warning. SABOTAGE: read the wallet as it stands and the position
    moves with each, D58's old way."""
    bot, venue, lines, _ = _pair()
    _holding(bot, venue)
    held, before = bot._last_pos, _orders(venue)
    assert held and bot._spot_seen[0] < bot._spot_seen[1]         # own above the wallet
    venue.inverse_moves(-2.5)                                     # its fee
    bot.cycle()
    venue.inverse_moves(1.5, kind='SETTLEMENT')                   # its funding
    bot.cycle()
    assert bot._last_pos == held and _orders(venue) == before
    assert not [ln for ln in lines if 'do not account' in ln or 'position ' + str(held) in ln]


def spec_D169_a_take_profit_booking_real_coins_is_not_the_rows():
    """A round closing in profit puts real coins in the wallet: the row never
    claims them, and it reads no outside hand. SABOTAGE: leave them out of what
    the log explains and the row freezes, then says an outside hand."""
    bot, venue, lines, later = _pair()
    _holding(bot, venue)
    held, before = bot._last_pos, _orders(venue)
    venue.inverse_moves(300.0)
    for _ in range(3):
        bot.cycle()
        later[0] += RUNGS_LAG_SECONDS
    assert bot._last_pos == held and _orders(venue) == before
    assert not [ln for ln in lines if 'outside hand' in ln]


def spec_D169_a_liquidation_sized_loss_keeps_the_book_and_trims_the_sells():
    """The wallet falls under the row's book: the book stands, and the sells are
    trimmed to the coins there are, nearest first, said once. On margin spot a
    sell past them would borrow the coin. SABOTAGE: drop the trim and the resting
    sells stand above the wallet; say it each read and the phone rings."""
    bot, venue, lines, _ = _pair()
    _holding(bot, venue, fills=3)
    held = bot._last_pos
    sells = [o for o in venue.orders if o['side'] == 'Sell']
    assert len(sells) >= 2
    lowest = min(o['price'] for o in sells)
    left = float(next(o for o in sells if o['price'] == lowest)['qty']) + 2.0
    venue.inverse_moves(left - venue.base)
    for _ in range(3):
        bot.cycle()
    assert bot._last_pos == held                                  # the book as it was
    sells = [o for o in venue.orders if o['side'] == 'Sell']
    assert sum(float(o['qty']) for o in sells) <= left + 1e-9
    assert any(o['price'] == lowest for o in sells)               # nearest kept
    assert sum('trimmed to it' in ln for ln in lines) == 1
    assert not [ln for ln in lines if 'position closed' in ln]    # never a false D1


def spec_D169_a_flatten_never_sells_past_the_wallet():
    """A stop's market sell at the row's book would borrow the difference.
    SABOTAGE: drop the cap and it sells the whole book."""
    bot, venue, lines, _ = _pair()
    _holding(bot, venue, fills=2)
    venue.inverse_moves(5.0 - venue.base)
    bot.cycle()
    sold = []
    venue.place_market = lambda cat, sym, side, qty, idx, **k: sold.append(float(qty)) or {}
    truth = venue.read_symbol_truth('spot', 'ADAUSDT')
    bot._execute_stop(truth, bot._last_pos, 'a test stop', flatten=True)
    assert sold and max(sold) <= 5.0


def spec_D169_a_move_the_log_has_not_listed_freezes_the_row():
    """The wallet read first, the log a moment behind: nothing moves until it is
    listed, then the row runs on with nothing said. SABOTAGE: judge without the
    freeze and the position moves on the unlisted row."""
    bot, venue, lines, _ = _pair()
    _holding(bot, venue)
    held, before = bot._last_pos, _orders(venue)
    venue.inverse_moves(-3.0, listed=False)
    out = bot.cycle()
    assert out == {'lagging': 'own fill in flight (D58)'} and bot._last_pos == held
    assert _orders(venue) == before
    venue.list_move(-3.0)
    assert bot.cycle() != {'lagging': 'own fill in flight (D58)'}
    assert bot._last_pos == held and not [ln for ln in lines if 'outside hand' in ln]


def spec_D169_a_move_nothing_explains_is_said_once_past_the_wait():
    """Coins gone that no market listed: a hand. Frozen for G26's wait, said once
    and urgent, then taken as they stand. SABOTAGE: never give up and the row
    stays frozen; say it each read and the phone rings."""
    with _clock_at(FUNDING_HOUR + 2 * 3600):      # no funding near: G26's wait
        _a_move_nothing_explains()


def _a_move_nothing_explains():
    bot, venue, lines, later = _pair()
    _holding(bot, venue)
    venue.base -= 3.0
    bot.cycle()
    later[0] += RUNGS_LAG_SECONDS - 2.0
    assert bot.cycle() == {'lagging': 'own fill in flight (D58)'}
    assert not [ln for ln in lines if 'outside hand' in ln]
    later[0] += 3.0
    for _ in range(3):
        assert bot.cycle() != {'lagging': 'own fill in flight (D58)'}
    assert sum('outside hand' in ln for ln in lines) == 1


def spec_D169_a_log_that_cannot_be_read_freezes_as_D158_does():
    """Never a guess at the position. Said once past the wait with the exchange's
    words, on the card's frozen clock, its end said. SABOTAGE: read on without the
    log and the position moves; swallow it and the row is frozen in silence."""
    bot, venue, lines, later = _pair()
    _holding(bot, venue)
    held, before = bot._last_pos, _orders(venue)
    venue.refuse = VenueError('retCode 10016: system error')
    venue.inverse_moves(-3.0)
    assert bot.cycle() == {'lagging': 'own fill in flight (D58)'}
    assert _orders(venue) == before and bot._last_pos == held
    assert not [ln for ln in lines if 'could not be read' in ln]
    later[0] += RUNGS_LAG_SECONDS + 1.0
    assert bot.cycle() == {'lagging': 'own fill in flight (D58)'}
    assert sum("cash log could not be read" in ln and '10016' in ln for ln in lines) == 1
    assert bot._rungs_fail_since is not None                      # the card's (G28)
    venue.refuse = None
    assert bot.cycle() != {'lagging': 'own fill in flight (D58)'}
    assert bot._last_pos == held and bot._rungs_fail_since is None
    assert sum('cash log readable again' in ln for ln in lines) == 1


def spec_D169_a_restart_rederives_it_from_the_log():
    """Nothing is kept: a new process reads the same window and holds the same.
    SABOTAGE: count only what this process saw and the restart's position falls
    by what the inverse market paid before it."""
    bot, venue, lines, _ = _pair()
    _holding(bot, venue)
    held = bot._last_pos
    venue.inverse_moves(-3.0)
    bot.cycle()
    again, _, _, _ = _pair(venue=venue)
    again.cycle()
    assert again._last_pos == held


def spec_D169_a_new_inverse_bot_beside_a_holding_changes_nothing():
    """It joins at a restart with the row's coins already there and its own moves
    still to come; and with the market gone the row reads D58 again, a retired
    bot's leftover coins not its own. SABOTAGE: a row with no inverse market still
    subtracting would read the leftover as less of its own."""
    bot, venue, lines, _ = _pair(beside=False)
    _holding(bot, venue)
    held = bot._last_pos
    joined, _, _, _ = _pair(venue=venue)
    joined.cycle()
    assert joined._last_pos == held
    venue.inverse_moves(40.0)                                     # it books, then retires
    joined.cycle()
    assert joined._last_pos == held
    retired, _, _, _ = _pair(venue=venue, beside=False)
    retired.cycle()
    assert retired._last_pos == bot._spot_seen[1]                 # its own fills, no more


def spec_D169_a_fleet_with_no_pair_reads_nothing_more():
    """The log is read only for a row that shares, and only when the wallet moved.
    SABOTAGE: read it each cycle, or for every spot row, and the count shows."""
    bot, venue, lines, _ = _pair(beside=False)
    _holding(bot, venue)
    venue.base -= 0.01
    bot.cycle()
    assert venue.log_reads == 0 and bot._spot_sell_cap is None
    shared, venue, _, _ = _pair()
    _holding(shared, venue)
    reads = venue.log_reads
    for _ in range(5):
        shared.cycle()
    assert venue.log_reads == reads


class _Row:
    def __init__(self, cfg=None, market=None, settle=None, coin=None, legs=None):
        self.cfg, self.wallet_coin, self.beside_inverse = cfg or {}, coin, None
        self.notify = Notifier(sink=lambda ln: None)
        self.botid = 'x'
        if market:
            self.adapter = type('A', (), {'market_type': market, 'settle_coin': settle})()
        if legs:
            self.legs = legs


def spec_D169_who_shares_a_coin():
    """A long spot row beside an inverse grid, DCA or trade, or a Portfolio Bot's
    inverse leg. Not beside a linear market, another coin, nor a short spot row (a
    borrowed coin, not a holding). SABOTAGE: mark by market alone and BTC's row
    reads ETH's."""
    spot = lambda: _Row({'side': 'long'}, market='spot', coin='BTC')
    a, inv = spot(), _Row({'side': 'short'}, market='inverse', settle='BTC')
    mark_shared_coins([a, inv])
    assert a.beside_inverse == 'BTC' and inv.beside_inverse is None
    b = spot()
    mark_shared_coins([b, _Row(market='linear', settle='USDT')])
    assert b.beside_inverse is None
    c = spot()
    mark_shared_coins([c, _Row(market='inverse', settle='ETH')])
    assert c.beside_inverse is None
    d = spot()
    mark_shared_coins([d, _Row(legs={'hedge': {'BTC': {'market_type': 'inverse'}}, 'short': {}})])
    assert d.beside_inverse == 'BTC'
    e = spot()
    mark_shared_coins([e, _Row(legs={'hedge': {'BTC': {'market_type': 'linear'}}, 'short': {}})])
    assert e.beside_inverse is None
    f = _Row({'side': 'short'}, market='spot', coin='BTC')
    mark_shared_coins([f, _Row(market='inverse', settle='BTC')])
    assert f.beside_inverse is None


def spec_D169_every_close_a_round_sends_is_capped():
    """A DCA row's closes are single orders outside the plan: each goes through
    the cap, read from the source. A row that shares no coin has no cap and sends
    its size unchanged. SABOTAGE: a site that skips it is named."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / 'gridgremlin'
    for name in ('bot_round.py', 'bot_stops.py'):
        lines = (root / name).read_text().split('\n')
        for i, line in enumerate(lines):
            if 'self._exit_side,' in line and 'fmt_qty' in lines[i + 1]:
                assert '_wallet_capped' in lines[i + 1], (name, i + 2, lines[i + 1])
    bot, venue, lines, _ = _pair(beside=False)
    assert bot._wallet_capped(7.0) == 7.0
    bot._spot_sell_cap = 5.0
    assert bot._wallet_capped(7.0) == 5.0 and bot._wallet_capped(3.0) == 3.0


def spec_D169_coins_above_its_own_fills_are_never_the_rows():
    """A hand's stack sits in the wallet beside the row's lots (D58): the row
    reads no more than its own fills, the inverse market's rows or no. SABOTAGE:
    drop the bound and the row counts the stack as its own, and sells it."""
    bot, venue, lines, _ = _pair()
    held, lagging = bot._spot_beside_inverse(5.0, 1.0, bot.adapter.qty_step, None)
    assert (held, lagging) == (1.0, False)


def spec_D169_only_an_inverse_markets_rows_are_kept_apart():
    """Another spot market on the coin took half the wallet. Those coins are
    gone from what this row can hold, so it reads what is there. SABOTAGE: add
    back every market's rows and it reads coins that have left the wallet."""
    bot, venue, lines, _ = _pair()
    venue.log.append({'id': 'other', 'time_ms': int(time.time() * 1000) - 1000,
                      'symbol': 'ADAUSDC', 'category': 'spot', 'type': 'TRADE', 'change': -50.0})
    held, _ = bot._spot_beside_inverse(50.0, 100.0, bot.adapter.qty_step, None)
    assert held == 50.0


def _funding_move(after, wait, listed_at=None):
    """The wallet moves `after` seconds past a funding hour, its log row a while
    behind; `wait` seconds on, how often has an outside hand been said?"""
    with _clock_at(FUNDING_HOUR + after) as now:
        bot, venue, lines, _ = _pair()
        _holding(bot, venue)
        held = bot._last_pos
        venue.inverse_moves(-3.0, listed=False, kind='SETTLEMENT')
        assert bot.cycle() == {'lagging': 'own fill in flight (D58)'}
        if listed_at is not None:
            now[0] += listed_at
            bot.cycle()
            venue.list_move(-3.0, kind='SETTLEMENT')
            now[0] += wait - listed_at
        else:
            now[0] += wait
        bot.cycle()
        bot.cycle()
        return bot._last_pos == held, sum('outside hand' in ln for ln in lines)


def spec_D169_a_funding_move_waits_for_its_late_log_row():
    """Measured 2026-11-05: the inverse funding moved the wallet 5 s past the
    hour and its SETTLEMENT row listed at +91 s and +112 s, so G26's 60 s rang the
    phone at every funding. A move begun within FUNDING_WINDOW_SECONDS of a
    funding hour waits FUNDING_LAG_SECONDS: at +112 s it is still frozen, nothing
    said, and its row explains it when it lists. SABOTAGE below."""
    kept, said = _funding_move(after=5, wait=150, listed_at=112)
    assert kept and said == 0


def spec_D169_an_unlisted_funding_move_is_said_once_past_the_longer_wait():
    """The longer wait still ends: no row by FUNDING_LAG_SECONDS and it is an
    outside hand, said once, as G26's wait says it."""
    _, said = _funding_move(after=5, wait=FUNDING_LAG_SECONDS - 10)
    assert said == 0
    _, said = _funding_move(after=5, wait=FUNDING_LAG_SECONDS + 1)
    assert said == 1


def spec_D169_away_from_a_funding_hour_the_wait_stays_G26s():
    """Two hours from any funding, or just past the window, a move nobody listed
    is said past 60 s, as before: the longer wait is the funding's only."""
    _, said = _funding_move(after=2 * 3600, wait=RUNGS_LAG_SECONDS + 1)
    assert said == 1
    _, said = _funding_move(after=FUNDING_WINDOW_SECONDS + 1, wait=RUNGS_LAG_SECONDS + 1)
    assert said == 1


def spec_D169_sabotage_the_funding_wait_at_G26s_rings_at_every_funding():
    """The sabotage half: the wait at G26's 60 s everywhere, and the measured
    +112 s row is said as an outside hand, urgent, at every funding."""
    real = bot_basis._inverse_wait
    bot_basis._inverse_wait = lambda since: RUNGS_LAG_SECONDS
    try:
        _, said = _funding_move(after=5, wait=150, listed_at=112)
    finally:
        bot_basis._inverse_wait = real
    assert said == 1
