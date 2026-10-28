"""D78 — the hedged portfolio row against an outside tester's review
(2026-10-28): a degraded read decides nothing irreversible (E9), a flatten
sells what the shorts' close settled into the coin's wallet (H4, H8), a
floor trim is not bought back in the same read (H4), and a spot order the
venue filled only in part moves the cash by what it filled (H2)."""
from spec_portfolio_bot import DAY, Clock, _bot, _venue


def _degraded_once(venue, symbol):
    """The venue answers one EMPTY position list for `symbol` (under load,
    an account-type mismatch), then the truth again."""
    real = venue.read_symbol_truth
    left = [1]

    def read(mt, sym, *a, **k):
        t = real(mt, sym, *a, **k)
        if sym == symbol and left[0]:
            left[0] -= 1
            t = dict(t, positions={})
        return t
    venue.read_symbol_truth = read


def _hollow_once(venue):
    """One hollow wallet payload: equity unknown, no coins (E9)."""
    real = venue.read_wallet
    left = [1]

    def read():
        if left[0]:
            left[0] -= 1
            return {'equity': None, 'available': 0.0, 'mm_rate': None, 'im': None, 'coins': {}}
        return real()
    venue.read_wallet = read


def _hedged(row=None):
    venue, lines, clock = _venue(), [], Clock()
    venue.t_ms = int(clock.t * 1000)
    bot, tmp = _bot(venue, lines, row=row, clock=clock)
    bot.cycle()
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    bot.cycle()                                    # its fills in its books, as a live row's are
    return venue, lines, clock, bot, tmp


def _step(clock, venue, s=61):
    clock.t += s; venue.t_ms = int(clock.t * 1000)


# --- E9: one degraded read is not a fact -------------------------------------------

def spec_E9_one_empty_position_read_for_a_held_short_flattens_nothing():
    """BTC −10%, `max_loss` 3,000: one empty list for BTCUSD dropped the
    short's +4,500 from the value, read 'loss 4,500', flattened ETH and the
    stack and tombstoned the row — leaving the 45,000-contract short
    standing, naked, on a dead row. The short the row's own book holds is
    read once more before it is believed gone."""
    venue, lines, clock, bot, tmp = _hedged({'risk': {'max_loss': 3000,
                                                      'max_loss_since': '2026-01-01T00:00:00Z'}})
    for k in ('BTCUSDT', 'BTCUSD'):
        venue.marks[k] = 54000.0
    _degraded_once(venue, 'BTCUSD')
    _step(clock, venue)
    n = len(venue.orders)
    bot.cycle()
    assert bot.alive and len(venue.orders) == n, venue.orders[n:]
    assert not bot.tombs.has('pfocarry') and abs(bot._loss_now) < 1e-6
    assert venue.positions['BTCUSD'][0]['size'] == 45000.0


def spec_E9_one_empty_position_read_does_not_double_a_hedge():
    """The same read with no loss limit: H16 read BTC unhedged and sold
    another 40,500 contracts — 85,500 short against 0.75 BTC."""
    venue, lines, clock, bot, _ = _hedged()
    for k in ('BTCUSDT', 'BTCUSD'):
        venue.marks[k] = 54000.0
    _degraded_once(venue, 'BTCUSD')
    _step(clock, venue)
    n = len(venue.orders)
    bot.cycle()
    assert len(venue.orders) == n, venue.orders[n:]
    assert venue.positions['BTCUSD'][0]['size'] == 45000.0


def spec_E9_a_short_gone_on_both_reads_is_gone():
    """The re-read is once: an outside hand that lifted the hedge is seen
    on the same read (H4's loss limit and H16 act on it as before)."""
    venue, lines, clock, bot, _ = _hedged()
    venue.positions['BTCUSD'] = {}
    reads = []
    real = venue.read_symbol_truth
    venue.read_symbol_truth = lambda mt, sym, *a, **k: (reads.append(sym), real(mt, sym, *a, **k))[1]
    _step(clock, venue)
    n = len(venue.orders)
    bot.cycle()
    assert reads.count('BTCUSD') == 2 and reads.count('ETHUSD') == 1       # read again once, the held one alone
    assert [(o[1], o[2], o[3]) for o in venue.orders[n:]] == [('BTCUSD', 'Sell', 45000.0)]


def spec_E9_sabotage_without_the_re_read_one_empty_list_flattens_the_row():
    venue, lines, clock, bot, tmp = _hedged({'risk': {'max_loss': 3000,
                                                      'max_loss_since': '2026-01-01T00:00:00Z'}})
    for k in ('BTCUSDT', 'BTCUSD'):
        venue.marks[k] = 54000.0
    _degraded_once(venue, 'BTCUSD')
    bot._confirm_gone = lambda key, leg, truth: truth                     # the guard removed
    _step(clock, venue)
    assert bot.cycle() == {'flattened': True}
    assert venue.positions['BTCUSD'][0]['size'] == 45000.0                 # the naked short it leaves


def spec_E9_a_hollow_wallet_decides_nothing():
    """One hollow wallet answer at unchanged marks read 'loss 90,000',
    bought back both hedges, sold nothing (no coins in the payload) and
    died holding 0.75 BTC and 15 ETH unhedged. Unknown equity fires
    nothing, and the book keeps its cash and coins for the next read."""
    venue, lines, clock, bot, _ = _hedged({'risk': {'max_loss': 3000,
                                                    'max_loss_since': '2026-01-01T00:00:00Z'}})
    before = {k: bot.row[k] for k in ('cash', 'coins')}
    before['coins'] = dict(before['coins'])
    _hollow_once(venue)
    _step(clock, venue)
    n = len(venue.orders)
    assert bot.cycle() is None
    assert bot.alive and len(venue.orders) == n
    assert bot.row['cash'] == before['cash'] and bot.row['coins'] == before['coins']
    assert any('wallet read hollow' in ln and '(E9)' in ln for ln in lines)
    _step(clock, venue)
    bot.cycle()                                                             # the next read is whole
    assert bot.alive and len(venue.orders) == n and abs(bot.portfolio_view['value'] - 90000.0) < 1e-6


def spec_E9_a_hollow_wallet_on_the_first_read_is_not_a_first_sight():
    """A row's first read on a hollow wallet takes no anchor and keeps no
    row: the next whole read is its first sight."""
    venue, lines, clock = _venue(), [], Clock()
    venue.t_ms = int(clock.t * 1000)
    bot, _ = _bot(venue, lines, clock=clock)
    _hollow_once(venue)
    assert bot.cycle() is None and not venue.orders and not bot.state.get('pfocarry')
    _step(clock, venue)
    assert bot.cycle() == {'placed': 4, 'tick': True}
    assert bot.row['anchor_value'] == 90000.0


def spec_E9_a_moving_hedges_old_short_read_empty_once_does_not_close_the_move():
    """H17's old-leg read had the same exposure: one empty list for the old
    market closed the move, and the old short stood outside every book."""
    from spec_portfolio_bot import _moved
    venue, lines, clock, bot, row, _ = _moved(cap=5000)
    bot.cycle()                                                              # the first slice
    assert venue.positions['ETHUSD'][0]['size'] > 0
    _degraded_once(venue, 'ETHUSD')
    _step(clock, venue)
    bot.cycle()
    assert bot.row['moves']['ETH']['closed_ms'] is None
    assert not any("ETH's hedge moved" in ln for ln in lines)


def spec_E9_the_owners_flatten_on_a_hollow_wallet_refuses_and_places_nothing():
    from gridgremlin.exchange.errors import VenueError
    venue, lines, clock, bot, _ = _hedged()
    _hollow_once(venue)
    n = len(venue.orders)
    try:
        bot.flatten_now('flattened by the owner', tombstone=False)
        raise AssertionError('a hollow wallet flattened')
    except VenueError as e:
        assert 'hollow' in str(e) and '(E9)' in str(e)
    assert len(venue.orders) == n and bot.alive


# --- H4/H8: a flatten sells what the shorts' close settled ------------------------

def _settling(row=None):
    """The hedged row on a venue that settles an inverse close's realised
    coin into the coin's wallet, as Bybit does (H8)."""
    venue, lines, clock, bot, tmp = _hedged(row)
    venue.settles_coin = True
    return venue, lines, clock, bot, tmp


def _move(venue, f):
    for k in ('BTCUSDT', 'BTCUSD'):
        venue.marks[k] = 60000.0 * f
    for k in ('ETHUSDT', 'ETHUSD'):
        venue.marks[k] = 3000.0 * f


def _dust(venue):
    return venue.coins.get('BTC', 0.0) < 1e-5 and venue.coins.get('ETH', 0.0) < 1e-4


def spec_H4_review_the_owners_flatten_after_a_rally_sells_what_the_close_left_not_the_book():
    """+30%: the shorts' close took 0.173 BTC and 3.46 ETH from the wallets
    (their loss, settled in the coin), and the flatten asked to sell the
    whole 0.75 and 15 — refused, the coins left on a dead row."""
    venue, lines, clock, bot, _ = _settling()
    _move(venue, 1.3)
    bot.flatten_now('flattened by the owner', tombstone=False)
    assert _dust(venue), venue.coins
    assert all(not venue.positions.get(s) for s in ('BTCUSD', 'ETHUSD'))
    assert not any('NOT closed' in ln for ln in lines)


def spec_H4_review_the_owners_flatten_after_a_fall_sells_the_shorts_settled_coin_too():
    """−30%: the close settled 0.321 BTC and 6.43 ETH into the wallets, and
    the flatten sold the spot book alone — the coin left long, unhedged."""
    venue, lines, clock, bot, _ = _settling()
    _move(venue, 0.7)
    bot.flatten_now('flattened by the owner', tombstone=False)
    assert _dust(venue), venue.coins


def spec_H4_review_the_owners_flatten_counts_the_inverse_books_realised_coin():
    """A hedge trimmed before the flatten realised coin into the wallet; the
    cycle counts it among the row's coins (H8), the owner's flatten left it."""
    venue, lines, clock, bot, _ = _settling()
    _move(venue, 0.7)
    _step(clock, venue)
    venue.available_pct = 0.3                                               # a floor trim realises coin
    bot.cycle()
    venue.available_pct = 0.9
    _step(clock, venue)
    bot.cycle()                                                             # its fills in the books
    bot.flatten_now('flattened by the owner', tombstone=False)
    assert _dust(venue), venue.coins


def spec_H4_review_the_loss_limit_after_a_rally_sells_what_the_close_left():
    venue, lines, clock, bot, _ = _settling({'risk': {'max_loss': 3000,
                                                      'max_loss_since': '2026-01-01T00:00:00Z'}})
    venue.positions['ETHUSD'] = {}                                          # ETH's hedge lifted by an outside hand
    for k in ('BTCUSDT', 'BTCUSD'):
        venue.marks[k] = 78000.0
    for k in ('ETHUSDT', 'ETHUSD'):
        venue.marks[k] = 2700.0                                             # −4,500 on 15 ETH unhedged
    _step(clock, venue)
    assert bot.cycle() == {'flattened': True}
    assert _dust(venue), venue.coins
    kill = next(ln for ln in lines if ' kill ' in ln)
    assert 'NOT closed' not in kill, kill


def spec_H4_review_the_basis_stop_sells_what_its_hedges_close_left():
    """−30%, ETH's perp 2% over spot: the unwind sold the 15 spot ETH and
    left the 6 ETH its short's close settled — unhedged while unwound."""
    venue, lines, clock, bot, _ = _settling()
    _move(venue, 0.7)
    venue.marks['ETHUSD'] = 2100.0 * 1.02
    _step(clock, venue)
    bot.cycle()
    assert 'ETH' in bot.row['unwound'] and not venue.positions.get('ETHUSD')
    assert venue.coins.get('ETH', 0.0) < 1e-4, venue.coins
    sold = sum(o[3] for o in venue.orders if o[1] == 'ETHUSDT' and o[2] == 'Sell')
    assert abs(bot.row['parked']['ETH'] - sold * 2100.0) < 1e-6


def spec_H4_review_the_floor_trim_sells_its_share_of_every_coin_the_row_hedges():
    """−30%: the trim bought back a quarter of each short, which settled a
    quarter of its coin gain into the wallet, but sold a quarter of the spot
    book alone — the next read found the coin under-hedged."""
    venue, lines, clock, bot, _ = _settling()
    _move(venue, 0.7)
    _step(clock, venue)
    venue.available_pct = 0.3
    bot.cycle()
    btc = 0.75 + 45000.0 * (1 / 42000.0 - 1 / 60000.0)                      # the coins H8 hedges
    sell = next(o[3] for o in venue.orders if o[1] == 'BTCUSDT' and o[2] == 'Sell')
    assert abs(sell - 0.25 * btc) < 1e-5, (sell, 0.25 * btc)
    venue.available_pct = 0.9
    _step(clock, venue)
    n = len(venue.orders)
    bot.cycle()
    assert len(venue.orders) == n, venue.orders[n:]                         # neutral: nothing for H16 to sell


# --- H4: a floor trim is not bought back in the same read --------------------------

def spec_H4_review_a_floor_trim_is_not_bought_back_in_the_same_read():
    """The suite's 2× row under a drift trigger, a 10% trim: the plan later
    in the same read sized from the pre-cut coins plus the cut's proceeds
    in the cash — the stack counted twice — and bought 80% of the trim
    back: 1.6333 BTC and 98,000 contracts a leg where 1.5 and 90,000 were
    meant, the loan barely repaid. The trim moves the read's own views."""
    from spec_portfolio_bot import _levered
    for trigger in ('clock', 'drift'):
        lines, clock = [], Clock()
        venue, bot, _ = _levered(lines, clock, trigger)
        bot.cycle()                                                         # 2× on 100k: 1.6667 BTC, 33.333 ETH
        venue.available_pct, venue.im = 0.20, 100000.0                      # a 10% trim
        _step(clock, venue, DAY if trigger == 'clock' else 61)              # the tick's read, or any read
        bot.cycle()
        assert abs(bot.row['lever_cap'] - 1.8) < 1e-9
        assert abs(venue.coins['BTC'] - 1.5) < 1e-3, (trigger, venue.coins)
        assert abs(venue.coins['ETH'] - 30.0) < 1e-2, (trigger, venue.coins)
        for s in ('BTCUSD', 'ETHUSD'):
            assert abs(venue.positions[s][0]['size'] - 90000.0) <= 1.0, (trigger, s, venue.positions[s])
        assert abs(venue.coins['USDT'] + 80000.0) < 10.0, (trigger, venue.coins['USDT'])   # the loan repaid by the trim


# --- H2: a spot order the venue filled only in part --------------------------------

def _partial(venue, symbol, side, fill):
    """The venue fills `fill` of a spot order and cancels the rest
    (`PartiallyFilledCanceled`, a spot-only status)."""
    real = venue.place_market

    def place(mt, sym, sd, qty, *a, **k):
        if (sym, sd) == (symbol, side):
            if k.get('quote_qty') is not None:
                k['quote_qty'] = f"{float(k['quote_qty']) * fill:.2f}"
            qty = f'{float(qty) * fill:.10g}'
        return real(mt, sym, sd, qty, *a, **k)
    venue.place_market = place
    return real


def spec_H2_review_a_partly_filled_spot_buy_returns_the_unspent_quote():
    """Bybit filled 31,500 of a 45,000 ETH buy and cancelled the rest: the
    row had taken the 45,000 from its cash at placement and only ever moved
    coins at the fill, so the 13,500 left in the wallet was gone from the
    row — 76,500 against 90,000, and with `max_loss` 5,000 it flattened a
    book that had lost nothing."""
    venue, lines, clock = _venue(), [], Clock()
    venue.t_ms = int(clock.t * 1000)
    bot, _ = _bot(venue, lines, clock=clock, row={'risk': {'max_loss': 5000,
                                                           'max_loss_since': '2026-01-01T00:00:00Z'}})
    real = _partial(venue, 'ETHUSDT', 'Buy', 0.7)
    bot.cycle()
    venue.place_market = real
    _step(clock, venue)
    bot.cycle()
    assert bot.alive, [ln for ln in lines if ' kill ' in ln]
    assert abs(bot.portfolio_view['value'] - 90000.0) < 0.05, bot.portfolio_view['value']
    assert abs(bot.row['coins']['ETH'] - 10.5) < 1e-9


def spec_H2_review_a_partly_filled_spot_sell_credits_only_what_it_sold():
    """A drift sale filled in half: the row's cash had the whole sale's
    proceeds, and the wallet (holding more than the row's own) never bounded
    them back — the value read 99,000 plus the half never sold."""
    from spec_portfolio_bot import THREE, _three_coin_legs
    venue, lines, clock = _venue(), [], Clock()
    venue.marks.update({'SOLUSDT': 100.0, 'SOLUSD': 100.0})
    venue.t_ms = int(clock.t * 1000)
    bot, _ = _bot(venue, lines, clock=clock, legs=_three_coin_legs(), row=THREE)
    bot.cycle()
    for s in ('BTCUSDT', 'BTCUSD'):
        venue.marks[s] = 75000.0
    real = _partial(venue, 'BTCUSDT', 'Sell', 0.5)
    _step(clock, venue, 3600)
    n = len(venue.orders)
    bot.cycle()
    venue.place_market = real
    sold = venue.orders[n][3]
    _step(clock, venue)
    m = len(venue.orders)
    bot.cycle()
    assert abs(bot.portfolio_view['value'] - 99000.0) < 0.05, bot.portfolio_view['value']
    if len(venue.orders) == m:                                              # nothing sold again on this read
        assert abs(bot.row['cash'] - sold * 75000.0) < 0.05, (bot.row['cash'], sold * 75000.0)


def spec_H2_review_a_spot_fill_written_late_still_moves_the_cash_once():
    """The fills list can lag the order: a buy with no fill by the next read
    returns its quote, and the fill that comes later takes it again — once."""
    venue, lines, clock = _venue(), [], Clock()
    venue.t_ms = int(clock.t * 1000)
    bot, _ = _bot(venue, lines, clock=clock)
    bot.cycle()
    late = [f for f in venue.fills if f['symbol'] == 'ETHUSDT']
    venue.fills = [f for f in venue.fills if f['symbol'] != 'ETHUSDT']  # not written yet
    _step(clock, venue)
    bot.cycle()
    assert abs(bot.row['cash'] - 45000.0) < 0.05, bot.row['cash']         # unspent, as far as the row can see
    for f in late:
        f['time_ms'] = venue.t_ms + 1000
    venue.fills += late
    for _ in range(2):
        _step(clock, venue)
        bot.cycle()
        assert abs(bot.row['cash']) < 0.05, bot.row['cash']
        assert abs(bot.portfolio_view['value'] - 90000.0) < 0.05, bot.portfolio_view['value']


# --- the review of these fixes (2026-10-28) ---------------------------------------

def spec_H8_review_a_sale_of_the_hedges_settled_coin_claims_no_foreign_coin():
    """The unwind sells the row's coins with its hedge's settled coin, but
    the sale came off the spot book alone, clamped at zero, while the
    inverse book's realised coin went on being counted — so the row then
    read 5 foreign ETH in the wallet as its own, beside their parked quote,
    and the re-entry hedged 26.0086 ETH where 21.0086 were meant."""
    venue, lines, clock, bot, _ = _settling()
    venue.coins['ETH'] += 5.0                                               # not the row's
    _move(venue, 0.7)
    venue.marks['ETHUSD'] = 2100.0 * 1.02
    _step(clock, venue)
    bot.cycle()                                                             # unwound
    assert abs(venue.coins['ETH'] - 5.0) < 1e-4, venue.coins
    _step(clock, venue)
    bot.cycle()                                                             # its fills in the books
    v = bot.portfolio_view
    assert v['spot']['ETH']['coins'] < 1e-4, v['spot']['ETH']
    want = bot.row['parked']['ETH'] / 2100.0
    venue.marks['ETHUSD'] = 2100.0                                          # the basis closes: the pair re-enters
    _step(clock, venue)
    n = len(venue.orders)
    bot.cycle()
    hedge = [o for o in venue.orders[n:] if o[1] == 'ETHUSD' and o[2] == 'Sell']
    assert hedge and abs(hedge[0][3] / 2100.0 - want) < 0.01, (hedge, want)


def spec_H8_review_a_trim_past_the_spot_book_claims_no_foreign_coin():
    """`_delever` the same way: trims in a fall sell their share of the
    coins H8 counts, and after a few the share is more than the spot book
    holds — the rest is the hedge's realised coin."""
    venue, lines, clock, bot, _ = _settling()
    venue.coins['ETH'] += 5.0
    _move(venue, 0.7)
    venue.available_pct = 0.3
    for _ in range(6):                                                      # a quarter each read
        _step(clock, venue)
        bot.cycle()
    venue.available_pct = 0.9
    _step(clock, venue)
    bot.cycle()
    own = venue.coins['ETH'] - 5.0
    assert abs(bot.portfolio_view['spot']['ETH']['coins'] - own) < 1e-3, (bot.portfolio_view['spot']['ETH'], own)


def spec_H2_review_a_late_buy_fill_on_a_row_alone_in_its_wallet_loses_nothing():
    """A row alone in its wallet, `cash_reserve` 4%: the ETH fill listed one
    read late. The settle gave the quote back, the wallet's bound (D76) cut
    the cash to the wallet it had already left, and the late fill took it
    again — the cash 3,600 → 0 against a wallet of 3,600, the value 86,400
    against 90,000, for good. A margin row whose wallet stands above zero
    the same."""
    for terms in ({}, {'spot_borrow': True, 'margin': {'spot_leverage': 1.0}}):
        venue, lines, clock = _venue(), [], Clock()
        venue.coins['USDT'] = 90000.0                                           # the row's own, alone
        venue.t_ms = int(clock.t * 1000)
        bot, _ = _bot(venue, lines, clock=clock, row=dict(terms, rebalance={'cash_reserve': 0.04}))
        bot.cycle()
        late = [f for f in venue.fills if f['symbol'] == 'ETHUSDT']
        venue.fills = [f for f in venue.fills if f['symbol'] != 'ETHUSDT']
        _step(clock, venue)
        bot.cycle()
        for f in late:
            f['time_ms'] = venue.t_ms + 1000
        venue.fills += late
        for _ in range(2):
            _step(clock, venue)
            bot.cycle()
        wallet = venue.coins['USDT']
        assert abs(bot.row['cash'] - wallet) < 0.05, (terms, bot.row['cash'], wallet)
        assert abs(bot.portfolio_view['value'] - 90000.0) < 0.05, bot.portfolio_view['value']


def spec_H2_review_the_bounds_cut_takes_no_genuine_partial_fill_refund():
    """The cut was taken oldest first, so it landed on an earlier part-fill's
    real refund (tick 1's ETH buy filled 70%: 12,960 back), and the next
    day's unlisted ETH buy kept its refund — its late fill charged it again:
    the cash 662.40 → 0 against a wallet of 662.40, the value 89,337.60.
    Only a refund made on the bound's own read, for an order with no fill
    listed at all, can be a fill not yet listed; only those are cut."""
    venue, lines, clock = _venue(), [], Clock()
    venue.coins['USDT'] = 90000.0                                           # the row's own, alone
    venue.t_ms = int(clock.t * 1000)
    bot, _ = _bot(venue, lines, clock=clock, row={'rebalance': {'cash_reserve': 0.04}})
    real = _partial(venue, 'ETHUSDT', 'Buy', 0.7)
    bot.cycle()                                                             # tick 1: ETH fills 70%
    venue.place_market = real
    _step(clock, venue)
    bot.cycle()                                                             # 12,960 back: a real refund
    _step(clock, venue, DAY)
    t0 = venue.t_ms
    n = len(venue.orders)
    bot.cycle()                                                             # the next day's tick buys ETH
    assert any(o[1] == 'ETHUSDT' and o[2] == 'Buy' for o in venue.orders[n:])
    late = [f for f in venue.fills if f['symbol'] == 'ETHUSDT' and f['time_ms'] >= t0]
    venue.fills = [f for f in venue.fills if f not in late]                 # its fill listed a read late
    _step(clock, venue)
    bot.cycle()
    for f in late:
        f['time_ms'] = venue.t_ms + 1000
    venue.fills += late
    for _ in range(2):
        _step(clock, venue)
        bot.cycle()
    wallet = venue.coins['USDT']
    assert abs(bot.row['cash'] - wallet) < 0.05, (bot.row['cash'], wallet)
    assert abs(bot.portfolio_view['value'] - 90000.0) < 0.05, bot.portfolio_view['value']


def spec_H2_review_a_late_fill_reads_an_old_settled_entry_as_nothing_to_move():
    """A `spot_done` entry from before the refunds were kept is the order's
    book alone (a plain string): its late fill moves nothing, never raises."""
    venue, lines, clock = _venue(), [], Clock()
    venue.t_ms = int(clock.t * 1000)
    bot, _ = _bot(venue, lines, clock=clock)
    bot.cycle()
    late = [f for f in venue.fills if f['symbol'] == 'ETHUSDT']
    venue.fills = [f for f in venue.fills if f['symbol'] != 'ETHUSDT']
    _step(clock, venue)
    bot.cycle()
    for link in bot.row['spot_done']:
        bot.row['spot_done'][link] = 'cash'                                 # the old shape
    cash = bot.row['cash']
    for f in late:
        f['time_ms'] = venue.t_ms + 1000
    venue.fills += late
    _step(clock, venue)
    bot.cycle()
    assert abs(bot.row['cash'] - cash) < 0.05 and abs(bot.row['coins']['ETH'] - 15.0) < 1e-9
