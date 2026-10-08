"""D78 — the portfolio row running: H2 the legs as identities on books of
the row's own fills, H3 placed on the clock, H4 the portfolio's risk.
A fake venue that fills every market order at its mark."""
import json
import tempfile
from pathlib import Path

from gridgremlin.adapters import InverseAdapter, LinearAdapter, SpotAdapter
from gridgremlin.config import ConfigError, validate_config
from gridgremlin.events import Notifier
from gridgremlin.portfolio_bot import PortfolioBot
from gridgremlin.portfolio_state import PortfolioState
from gridgremlin.tombstones import Tombstones

DAY = 86_400
ROW = {'strategy': 'portfolio', 'name': 'carry', 'capital': 90000,
       'assets': [{'coin': 'BTC', 'weight': 0.5}, {'coin': 'ETH', 'weight': 0.5}],
       'hedge': {'product': 'inverse', 'ratio': 1.0},
       'rebalance': {'cash_reserve': 0}}          # hand numbers: no fee reserve (pinned in its own spec)
SPOT = {'BTC': SpotAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.000001, 'price_tick': 0.1, 'min_qty': 0.00001, 'min_notional': 1}),
        'ETH': SpotAdapter({'symbol': 'ETHUSDT', 'qty_step': 0.00001, 'price_tick': 0.01, 'min_qty': 0.0001, 'min_notional': 1})}
INV = {'BTC': InverseAdapter({'symbol': 'BTCUSD', 'qty_step': 1, 'price_tick': 0.1, 'min_qty': 1, 'settle_coin': 'BTC'}),
       'ETH': InverseAdapter({'symbol': 'ETHUSD', 'qty_step': 1, 'price_tick': 0.01, 'min_qty': 1, 'settle_coin': 'ETH'})}
LIN = {'ETH': LinearAdapter({'symbol': 'ETHUSDT', 'qty_step': 0.01, 'price_tick': 0.01, 'min_qty': 0.01, 'settle_coin': 'USDT'})}


class FakeCarryVenue:
    """Spot wallet, perp positions, fills and funding; a market order fills
    at the mark at once and lands in the fills and the wallet."""
    env = 'demo'

    def __init__(self, marks, usdt=200000.0):
        self.marks = dict(marks)                        # symbol -> price
        self.coins = {'USDT': usdt}
        self.positions = {}                             # symbol -> {idx: {...}}
        self.fills, self.funding, self.orders = [], [], []
        self.t_ms = 0
        self.available_pct = 0.9
        self.n = 0

    im = None

    def read_wallet(self):
        eq = sum(q * self.marks.get(f'{c}USDT', 1.0) for c, q in self.coins.items())
        return {'equity': eq, 'available': eq * self.available_pct, 'mm_rate': 0.01, 'im': self.im,
                'coins': {c: {'wallet_balance': q} for c, q in self.coins.items()}}

    def read_symbol_truth(self, mt, symbol, funding_interval=480.0):
        pos = {}
        if mt == 'spot':
            base = symbol[:-4]
            q = self.coins.get(base, 0.0)
            if q > 0:
                pos = {0: {'side': 'Buy', 'size': q, 'avg_entry': None}}
        else:
            pos = {i: dict(p) for i, p in (self.positions.get(symbol) or {}).items()}
        return {'mark': self.marks[symbol], 'positions': pos, 'orders': []}

    def place_market(self, mt, symbol, side, qty, position_idx=0, reduce_only=False,
                     link_id=None, borrow=False, quote_qty=None):
        self.n += 1
        q, px = float(qty), self.marks[symbol]
        if quote_qty is not None:                       # H2: a cash buy says the quote
            assert mt == 'spot' and side == 'Buy'
            self.quote_buys = getattr(self, 'quote_buys', 0) + 1
            q = float(quote_qty) / px
        self.orders.append((mt, symbol, side, q, position_idx, reduce_only, link_id))
        if mt == 'spot':
            base = symbol[:-4]
            if side == 'Buy':
                self.coins['USDT'] -= q * px
                self.coins[base] = self.coins.get(base, 0.0) + q
            else:
                assert self.coins.get(base, 0.0) + 1e-9 >= q, f'selling {q} {base} it does not hold'
                self.coins[base] -= q
                self.coins['USDT'] += q * px
        else:
            book = self.positions.setdefault(symbol, {})
            p = book.get(position_idx) or {'side': 'Sell', 'size': 0.0, 'avg_entry': None}
            if side == 'Sell':
                tot = p['size'] + q
                p['avg_entry'] = ((p['avg_entry'] or px) * p['size'] + px * q) / tot
                p['size'] = tot
            else:
                assert reduce_only and p['size'] + 1e-9 >= q, f'buying back {q} of {p["size"]}'
                p['size'] -= q
            if p['size'] <= 1e-12:
                book.pop(position_idx, None)
            else:
                book[position_idx] = p
        self.fills.append({'exec_id': f'e{self.n}', 'time_ms': self.t_ms, 'symbol': symbol,
                           'market_type': mt, 'side': side.lower(), 'price': px, 'qty': q,
                           'fee': 0.0, 'link_id': link_id or ''})
        return {'orderId': str(self.n)}

    def fills_history(self, mt, symbol, since_ms, now_ms):
        return [f for f in self.fills if f['symbol'] == symbol and since_ms <= f['time_ms'] <= now_ms]

    def funding_history(self, mt, symbol, since_ms, now_ms):
        return [f for f in self.funding if f['symbol'] == symbol and since_ms < f['time_ms'] <= now_ms]

    def pay_funding(self, symbol, amount):
        self.funding.append({'time_ms': self.t_ms, 'symbol': symbol, 'side': 'sell', 'amount': amount})


def _legs(hedge='inverse'):
    legs = {'spot': {c: {'market_type': 'spot', 'symbol': f'{c}USDT', 'adapter': SPOT[c]} for c in SPOT},
            'hedge': {}, 'short': {}}
    for c in SPOT:
        if hedge == 'inverse':
            legs['hedge'][c] = {'market_type': 'inverse', 'symbol': f'{c}USD', 'adapter': INV[c]}
    return legs


def _bot(venue, lines, row=None, legs=None, tmp=None, clock=None):
    tmp = tmp or Path(tempfile.mkdtemp())
    state = PortfolioState(tmp / 'portfolio_state.json')
    tombs = Tombstones(tmp / 'tombstones.json')
    cfg = validate_config(dict(ROW, **(row or {})))
    bot = PortfolioBot(cfg, legs or _legs(), venue, Notifier(sink=lines.append), state,
                       tombstones=tombs, clock=clock)
    return bot, tmp


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def _venue():
    return FakeCarryVenue({'BTCUSDT': 60000.0, 'BTCUSD': 60000.0, 'ETHUSDT': 3000.0, 'ETHUSD': 3000.0})


def spec_H2_the_first_tick_buys_the_stack_from_capital_and_hedges_it_then_nothing_until_the_clock():
    venue, lines, clock = _venue(), [], Clock()
    venue.t_ms = int(clock.t * 1000)
    bot, tmp = _bot(venue, lines, clock=clock)
    out = bot.cycle()
    assert out == {'placed': 4, 'tick': True}
    spot = [(o[1], o[2], o[3]) for o in venue.orders if o[0] == 'spot']
    assert spot == [('BTCUSDT', 'Buy', 0.75), ('ETHUSDT', 'Buy', 15.0)]       # 45,000 each
    hedges = [(o[1], o[2], o[3], o[5]) for o in venue.orders if o[0] == 'inverse']
    assert hedges == [('BTCUSD', 'Sell', 45000.0, False), ('ETHUSD', 'Sell', 45000.0, False)]
    assert all(o[6].startswith('pfocarry-') for o in venue.orders)         # every order is the row's
    assert venue.quote_buys == 2                                             # the spot buys said the quote
    # the next minute: the fills are booked, nothing more is wanted
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    assert bot.cycle() is None
    assert abs(bot.row['coins']['BTC'] - 0.75) < 1e-9 and abs(bot.row['coins']['ETH'] - 15.0) < 1e-9
    assert bot.row['cash'] == 0.0 and bot.row['last_tick_ms'] == 1_000_000_000
    assert abs(bot.portfolio_view['stack_value'] - 90000.0) < 1e-6
    assert bot.portfolio_view['assets'][0]['hedged'] == 0.75 and abs(bot._last_pos - 90000.0) < 1e-6
    # within the read cadence the venue is not even asked
    before = len(venue.fills); clock.t += 10
    assert bot.cycle() is None and len(venue.fills) == before
    # a day on, the book sits at its weights: a tick with nothing to do
    clock.t += DAY; venue.t_ms = int(clock.t * 1000)
    assert bot.cycle() == {'placed': 0, 'tick': True} or bot.cycle() is None
    assert len(venue.orders) == 4
    # the state survived: a new process continues from the same book
    again, _ = _bot(venue, lines, tmp=tmp, clock=clock)
    assert again.row['coins'] == bot.row['coins'] and again.row['anchor_value'] == 90000.0
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    again.cycle()
    assert len(venue.orders) == 4                                            # no second stack bought


def spec_H3_inverse_funding_joins_the_book_as_coins_and_the_hedge_grows_over_them_at_the_tick():
    venue, lines, clock = _venue(), [], Clock()
    venue.t_ms = int(clock.t * 1000)
    bot, _ = _bot(venue, lines, clock=clock)
    bot.cycle()
    clock.t += 8 * 3600; venue.t_ms = int(clock.t * 1000)
    venue.pay_funding('BTCUSD', 0.05)                                        # inverse: paid in the coin —
    venue.pay_funding('ETHUSD', 1.0)                                         # 6.7% of each leg, in one go
    venue.coins['BTC'] += 0.05; venue.coins['ETH'] += 1.0                    # the wallet shows it
    bot.cycle()
    assert bot.row['cash'] == 0.0 and bot.row['funding_total'] == 6000.0     # coins in the book; the carry line in quote
    assert abs(bot.row['coins']['BTC'] - 0.8) < 1e-9 and abs(bot.row['coins']['ETH'] - 16.0) < 1e-9
    assert len(venue.orders) == 4                                            # not a tick yet
    clock.t += DAY; venue.t_ms = int(clock.t * 1000)
    bot.cycle()
    assert [o for o in venue.orders[4:] if o[0] == 'spot'] == []            # nothing to buy: the coins are here
    hedge = [(o[1], o[2], o[3]) for o in venue.orders[4:] if o[0] == 'inverse']
    assert hedge == [('BTCUSD', 'Sell', 3000.0), ('ETHUSD', 'Sell', 3000.0)]  # the hedge grows over them: 6.7% > 5%
    assert bot.portfolio_view['carry']['total'] == 6000.0


def spec_H4_the_loss_limit_flattens_every_leg_together_and_tombstones():
    venue, lines, clock = _venue(), [], Clock()
    venue.t_ms = int(clock.t * 1000)
    bot, tmp = _bot(venue, lines, row={'risk': {'max_loss': 1000, 'max_loss_since': '2026-01-01T00:00:00Z'}},
                    clock=clock)
    bot.cycle()
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    bot.cycle()
    assert bot._loss_now is not None and abs(bot._loss_now) < 1e-6           # hedged: flat to price
    # the hedge is lifted by an outside hand, then the market falls: a real loss
    venue.positions['BTCUSD'] = {}
    venue.marks['BTCUSDT'] = venue.marks['BTCUSD'] = 57000.0                 # −2,250 on 0.75 BTC
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    out = bot.cycle()
    assert out == {'flattened': True} and not bot.alive
    tail = venue.orders[4:]
    assert [(o[0], o[1], o[2]) for o in tail] == [('inverse', 'ETHUSD', 'Buy'), ('spot', 'BTCUSDT', 'Sell'),
                                                  ('spot', 'ETHUSDT', 'Sell')]
    assert tail[0][5] is True                                                # reduce-only
    assert venue.coins.get('BTC', 0.0) < 1e-9 and venue.coins.get('ETH', 0.0) < 1e-9
    assert venue.positions.get('ETHUSD') in (None, {})
    assert Tombstones(tmp / 'tombstones.json').has('pfocarry')
    kill = next(ln for ln in lines if ' kill ' in ln)
    assert 'every leg flattened together' in kill and 'loss 2,250.00 >= max_loss 1,000.00' in kill
    assert bot.cycle() is None                                               # dead stays dead


def spec_H4_a_leg_that_refuses_does_not_stop_the_others_and_is_named():
    venue, lines, clock = _venue(), [], Clock()
    venue.t_ms = int(clock.t * 1000)
    bot, _ = _bot(venue, lines, row={'risk': {'max_loss': 1000, 'max_loss_since': '2026-01-01T00:00:00Z'}},
                  clock=clock)
    bot.cycle()
    venue.positions['BTCUSD'] = {}
    venue.marks['BTCUSDT'] = venue.marks['BTCUSD'] = 57000.0
    real = venue.place_market
    from gridgremlin.exchange.errors import VenueError

    def flaky(mt, symbol, *a, **k):
        if symbol == 'ETHUSD':
            raise VenueError('ETHUSD: venue says no', kind='other')
        return real(mt, symbol, *a, **k)
    venue.place_market = flaky
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    bot.cycle()
    assert not bot.alive and venue.coins.get('BTC', 0.0) < 1e-9             # the stack still went
    kill = next(ln for ln in lines if ' kill ' in ln)
    assert 'NOT closed: hedge ETH: ETHUSD: venue says no' in kill


def spec_H4_the_margin_floor_cuts_every_leg_by_a_quarter_spot_and_hedge_together_and_says_so_once():
    venue, lines, clock = _venue(), [], Clock()
    venue.t_ms = int(clock.t * 1000)
    bot, _ = _bot(venue, lines, clock=clock)
    bot.cycle()
    venue.available_pct = 0.3                                                # under the 40% floor
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    bot.cycle()
    cuts = [(o[1], o[2], o[3], o[5]) for o in venue.orders[4:]]
    assert cuts == [('BTCUSDT', 'Sell', 0.1875, False), ('ETHUSDT', 'Sell', 3.75, False),
                    ('BTCUSD', 'Buy', 11250.0, True), ('ETHUSD', 'Buy', 11250.0, True)]   # a quarter of each leg, together
    assert bot.row['delevered'] == 1
    assert sum('under the floor' in ln for ln in lines) == 1
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    bot.cycle()                                                              # still under: cut again, quietly
    assert bot.row['delevered'] == 2 and sum('under the floor' in ln for ln in lines) == 1


def spec_H4_the_basis_stop_unwinds_one_pair_and_leaves_the_rest_then_re_enters():
    venue, lines, clock = _venue(), [], Clock()
    venue.t_ms = int(clock.t * 1000)
    bot, _ = _bot(venue, lines, clock=clock)
    bot.cycle()
    venue.marks['ETHUSD'] = 3060.0                                           # 2% over spot
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    bot.cycle()
    tail = [(o[0], o[1], o[2], o[3]) for o in venue.orders[4:]]
    assert tail == [('inverse', 'ETHUSD', 'Buy', 45000.0), ('spot', 'ETHUSDT', 'Sell', 15.0)]
    assert 'ETH' in bot.row['unwound'] and bot.row['parked'] == {'ETH': 45000.0}
    assert venue.coins['BTC'] == 0.75 and venue.positions['BTCUSD'][0]['size'] == 45000.0   # BTC untouched
    assert any('basis 2.00% past the stop 1.00%' in ln for ln in lines)
    # the next tick, still wide: BTC alone is the book; the parked cash is not spent
    clock.t += DAY; venue.t_ms = int(clock.t * 1000)
    bot.cycle()
    assert len(venue.orders) == 6 and bot.portfolio_view['parked'] == 45000.0
    # the basis closes: ETH re-enters from its parked cash at the next tick
    venue.marks['ETHUSD'] = 3000.0
    clock.t += DAY; venue.t_ms = int(clock.t * 1000)
    bot.cycle()
    back = [(o[0], o[1], o[2], o[3]) for o in venue.orders[6:]]
    assert ('spot', 'ETHUSDT', 'Buy', 15.0) in back and ('inverse', 'ETHUSD', 'Sell', 45000.0) in back
    assert bot.row['unwound'] == {} and bot.row['parked'] == {}


def spec_H2_the_row_in_the_fleet_resolves_its_legs_as_identities_and_a_collision_is_refused():
    from gridgremlin.apply import check_fleet_unique
    from gridgremlin.main import build_portfolio, portfolio_legs

    class Catalogue:
        """instruments-info for the three products, in the venue's shape."""
        def __init__(self):
            self.hedge_mode = []

        def instruments_info(self, mt, symbol):
            coin = symbol.replace('USDT', '').replace('PERP', '').replace('USD', '')
            return {'symbol': symbol, 'status': 'Trading', 'baseCoin': coin,
                    'settleCoin': {'spot': 'USDT', 'linear': 'USDT', 'inverse': coin}[mt],
                    'priceFilter': {'tickSize': '0.1'},
                    'lotSizeFilter': ({'basePrecision': '0.000001', 'minOrderQty': '0.00001', 'minOrderAmt': '1'}
                                      if mt == 'spot' else {'qtyStep': '1', 'minOrderQty': '1'})}

        def ensure_hedge_mode(self, mt, symbol):
            self.hedge_mode.append(symbol)

        def ensure_collateral(self, coin):
            pass
    cat = Catalogue()
    cfg = validate_config(dict(ROW, assets=[{'coin': 'BTC', 'weight': 0.5}, {'coin': 'ETH', 'weight': 0.3},
                                            {'coin': 'SOL', 'weight': -0.2}],
                               hedge={'BTC': {'product': 'inverse'}, 'ETH': {'product': 'usdt'},
                                      'SOL': {'product': 'usdc'}}))
    legs = portfolio_legs(cfg, cat)
    assert set(legs['spot']) == {'BTC', 'ETH'} and legs['hedge']['BTC']['symbol'] == 'BTCUSD'
    assert legs['hedge']['ETH']['symbol'] == 'ETHUSDT' and legs['short']['SOL']['symbol'] == 'SOLPERP'
    tmp = Path(tempfile.mkdtemp())
    bot, idents = build_portfolio(cfg, cat, Notifier(sink=[].append),
                                  PortfolioState(tmp / 'p.json'), Tombstones(tmp / 't.json'))
    assert bot.botid == 'pfocarry' and cat.hedge_mode == ['ETHUSDT', 'SOLPERP']
    assert [i for _, i in idents] == [('spot', 'BTCUSDT', 0), ('spot', 'ETHUSDT', 0), ('inverse', 'BTCUSD', 0),
                                      ('linear', 'ETHUSDT', 2), ('linear', 'SOLPERP', 2)]
    try:
        check_fleet_unique(idents + [('invBTCUSDs', ('inverse', 'BTCUSD', 0))])
    except ConfigError as e:
        assert 'invBTCUSDs and pfocarry both own' in str(e)
    else:
        raise AssertionError('a grid on the row\'s hedge market was accepted')
    try:
        validate_config(dict(ROW, venue='hyperliquid'))
    except ConfigError as e:
        assert 'step 5, not built' in str(e)
    else:
        raise AssertionError('the HL leg was accepted')


def spec_H3_a_regime_is_believed_only_after_it_has_held():
    venue, lines, clock = _venue(), [], Clock()
    venue.t_ms = int(clock.t * 1000)
    words = {'BTC': 'trending up', 'ETH': 'ranging'}
    tmp = Path(tempfile.mkdtemp())
    state = PortfolioState(tmp / 'p.json')
    cfg = validate_config(dict(ROW, regime={'tilt': 0.3, 'hold_hours': 24}))
    bot = PortfolioBot(cfg, _legs(), venue, Notifier(sink=lines.append), state, clock=clock,
                       regime_reader=lambda coin: words[coin])
    bot.cycle()                                                  # first sight: the reading is the belief
    assert bot.row['regime_seen']['BTC'][2] == 'up' and bot.row['regime_seen']['ETH'][2] == 'range'
    hedges = {o[1]: o[3] for o in venue.orders if o[0] == 'inverse'}
    assert hedges == {'BTCUSD': 31500.0, 'ETHUSD': 45000.0}      # BTC leaned to 0.7
    words['BTC'] = 'trending down'                               # a flip is a candidate, not a belief
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    bot.cycle()
    assert bot.row['regime_seen']['BTC'][0] == 'down' and bot.row['regime_seen']['BTC'][2] == 'up'
    clock.t += DAY; venue.t_ms = int(clock.t * 1000)             # 24h later it has held: believed
    bot.cycle()
    assert bot.row['regime_seen']['BTC'][2] == 'down'
    sells = [o for o in venue.orders[4:] if o[1] == 'BTCUSD' and o[2] == 'Sell']
    assert sells and abs(sum(o[3] for o in sells) - 27000.0) < 1e-6   # 0.7 → 1.3 of 0.75 BTC
    from gridgremlin.portfolio import regime_word
    assert regime_word('leaning up') == 'range' and regime_word(None) == 'range'


def spec_H6_the_tilt_line_is_the_shorts_excess_over_neutral_marked_each_read():
    venue, lines, clock = _venue(), [], Clock()
    venue.t_ms = int(clock.t * 1000)
    words = {'BTC': 'trending up', 'ETH': 'trending up'}
    tmp = Path(tempfile.mkdtemp())
    cfg = validate_config(dict(ROW, regime={'tilt': 0.5, 'hold_hours': 1}))
    bot = PortfolioBot(cfg, _legs(), venue, Notifier(sink=lines.append), PortfolioState(tmp / 'p.json'),
                       clock=clock, regime_reader=lambda coin: words[coin])
    bot.cycle()                                                  # hedges at 0.5 of the stack
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    bot.cycle()                                                  # last_px set
    venue.marks['BTCUSDT'] = venue.marks['BTCUSD'] = 66000.0     # +10%: the lean is short 0.375 BTC less
    venue.marks['ETHUSDT'] = venue.marks['ETHUSD'] = 3300.0
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    bot.cycle()
    v = bot.portfolio_view
    # neutral would hold 0.75 BTC short; it holds ~0.341 (inverse: 22,500 / 66,000) → the lean
    # made (0.75 − 0.341) × 6,000 ≈ 2,455 on BTC and (15 − 6.82) × 300 ≈ 2,455 on ETH
    assert 4800 < v['tilt'] < 5000, v['tilt']
    assert abs(v['total'] - (v['carry']['total'] + v['tilt'] + v['basis'])) < 1e-6   # the three sum to the total
    assert v['total'] > 4000                                     # half-hedged into a 10% rise


def spec_H3_a_refused_leg_is_asked_again_at_the_next_read_not_the_next_day():
    """The carry fleet's first minute (2026-10-10): the stack bought, both
    inverse hedges refused (collateral off) — and the tick was stamped, so
    the row would have run a day long and naked."""
    venue, lines, clock = _venue(), [], Clock()
    venue.t_ms = int(clock.t * 1000)
    bot, _ = _bot(venue, lines, clock=clock)
    real = venue.place_market
    from gridgremlin.exchange.errors import VenueError
    gate = {'on': False}

    def collateral_off(mt, symbol, *a, **k):
        if mt == 'inverse' and not gate['on']:
            raise VenueError('retCode 110101: requires enabling the settlement asset as collateral', kind='other')
        return real(mt, symbol, *a, **k)
    venue.place_market = collateral_off
    bot.cycle()
    assert [o[0] for o in venue.orders] == ['spot', 'spot'] and bot.row['last_tick_ms'] is None
    assert sum('asked again at the next read' in ln for ln in lines) == 2
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    bot.cycle()                                                  # still refused, quietly
    assert len(venue.orders) == 2 and sum('asked again' in ln for ln in lines) == 2
    gate['on'] = True
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    bot.cycle()                                                  # the switch is on: hedged within the minute
    assert [(o[0], o[2]) for o in venue.orders[2:]] == [('inverse', 'Sell'), ('inverse', 'Sell')]
    assert bot.row['last_tick_ms'] == int(clock.t * 1000)
    assert len([o for o in venue.orders if o[0] == 'spot']) == 2       # the stack was not bought twice


def spec_H2_the_build_switches_each_inverse_legs_coin_on_as_collateral_and_the_snapshot_reads_the_rows_limit():
    from gridgremlin.main import build_portfolio, loss_limit, snapshot_row

    class Catalogue:
        def __init__(self):
            self.collateral, self.hedge_mode = [], []

        def instruments_info(self, mt, symbol):
            coin = symbol.replace('USDT', '').replace('USD', '')
            return {'symbol': symbol, 'status': 'Trading', 'baseCoin': coin,
                    'settleCoin': {'spot': 'USDT', 'linear': 'USDT', 'inverse': coin}[mt],
                    'priceFilter': {'tickSize': '0.1'},
                    'lotSizeFilter': ({'basePrecision': '0.000001', 'minOrderQty': '0.00001', 'minOrderAmt': '1'}
                                      if mt == 'spot' else {'qtyStep': '1', 'minOrderQty': '1'})}

        def ensure_collateral(self, coin):
            self.collateral.append(coin)

        def ensure_hedge_mode(self, mt, symbol):
            self.hedge_mode.append(symbol)
    cat = Catalogue()
    tmp = Path(tempfile.mkdtemp())
    cfg = validate_config(dict(ROW, risk={'max_loss': 500, 'max_loss_since': '2026-10-10T00:00:00Z'}))
    bot, _ = build_portfolio(cfg, cat, Notifier(sink=[].append), PortfolioState(tmp / 'p.json'),
                             Tombstones(tmp / 't.json'))
    assert cat.collateral == ['BTC', 'ETH'] and cat.hedge_mode == []
    assert loss_limit(cfg) == 500.0 and loss_limit({'max_loss': 7.0}) == 7.0
    bot._loss_now = 12.5
    row = snapshot_row([bot], {'equity': 1.0, 'mm_rate': 0.0}, 0.0)
    assert row['bots']['pfocarry']['loss'] == {'limit': 500.0, 'result': 12.5}


def spec_H2_new_terms_on_a_restart_are_cash_to_spend_and_a_leg_to_add_planned_at_once():
    """The owner, 2026-10-10: 'utilise some of the stablecoins to open a
    solana spot position, with its own hedge … as much of the account as
    possible' — a raised capital and a third coin on an edited fleet file,
    picked up at the restart, not a day later."""
    venue, lines, clock = _venue(), [], Clock()
    venue.marks['SOLUSDT'] = venue.marks['SOLUSD'] = 150.0
    venue.t_ms = int(clock.t * 1000)
    bot, tmp = _bot(venue, lines, clock=clock)
    bot.cycle()                                                  # 2 coins, 90k: at weights, hedged
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    bot.cycle()
    assert bot.row['last_tick_ms'] is not None and len(venue.orders) == 4
    # the file edited: SOL as a third, capital up to 135k; the fleet restarts
    sol_spot = SpotAdapter({'symbol': 'SOLUSDT', 'qty_step': 0.001, 'price_tick': 0.01, 'min_qty': 0.01, 'min_notional': 1})
    sol_inv = InverseAdapter({'symbol': 'SOLUSD', 'qty_step': 1, 'price_tick': 0.01, 'min_qty': 1, 'settle_coin': 'SOL'})
    legs = _legs()
    legs['spot']['SOL'] = {'market_type': 'spot', 'symbol': 'SOLUSDT', 'adapter': sol_spot}
    legs['hedge']['SOL'] = {'market_type': 'inverse', 'symbol': 'SOLUSD', 'adapter': sol_inv}
    clock.t += 120; venue.t_ms = int(clock.t * 1000)
    again, _ = _bot(venue, lines, tmp=tmp, legs=legs, clock=clock,
                    row={'capital': 135000, 'assets': [{'coin': 'BTC', 'weight': 1 / 3}, {'coin': 'ETH', 'weight': 1 / 3},
                                                       {'coin': 'SOL', 'weight': 1 / 3}]})
    out = again.cycle()
    assert out and out['tick']
    assert any('capital raised by 45,000.00' in ln for ln in lines) and any('assets or weights changed' in ln for ln in lines)
    new = [(o[0], o[1], o[2], o[3]) for o in venue.orders[4:]]
    # the 45,000 goes where the book is short: all of it into SOL (its deficit is exactly 45,000)
    assert new[0] == ('spot', 'SOLUSDT', 'Buy', 300.0) and ('spot', 'BTCUSDT', 'Buy') not in [n[:3] for n in new]
    assert ('inverse', 'SOLUSD', 'Sell', 45000.0) in new                 # its own hedge
    assert len([n for n in new if n[1] in ('BTCUSD', 'ETHUSD')]) == 0   # the others sat at ratio: untouched
    assert again.row['cash'] == 0.0 and again.row['terms_seen']['capital'] == 135000.0
    # a lowered capital is said and nothing is sold
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    lower, _ = _bot(venue, lines, tmp=tmp, legs=legs, clock=clock,
                    row={'capital': 100000, 'assets': [{'coin': 'BTC', 'weight': 1 / 3}, {'coin': 'ETH', 'weight': 1 / 3},
                                                       {'coin': 'SOL', 'weight': 1 / 3}]})
    n = len(venue.orders)
    lower.cycle()
    assert any('capital lowered by 35,000.00' in ln for ln in lines) and len(venue.orders) == n


def spec_H3_cash_buys_spot_toward_the_weights_deficits_first():
    from gridgremlin.portfolio import plan_portfolio
    cfg = validate_config(dict(ROW))
    px = {'BTC': 60000.0, 'ETH': 3000.0}
    # off the weights: BTC 45,000, ETH 15,000, 30,000 cash → the stack is 90,000, each wants 45,000:
    # ETH's shortfall is 30,000 — every coin of cash goes to ETH, none to BTC
    plan = plan_portfolio(cfg, {'coins': {'BTC': 0.75, 'ETH': 5.0}, 'hedged': {}, 'cash': 30000.0}, px, DAY * 1000, None)
    buys = [(o['leg'][1], round(o['coins'] * px[o['leg'][1]])) for o in plan['orders'] if o['why'] == 'cash buys spot']
    assert buys == [('ETH', 30000)]
    # at the weights the rule is pro rata, as before
    plan = plan_portfolio(cfg, {'coins': {'BTC': 0.75, 'ETH': 15.0}, 'hedged': {}, 'cash': 6000.0}, px, DAY * 1000, None)
    buys = [(o['leg'][1], round(o['coins'] * px[o['leg'][1]])) for o in plan['orders'] if o['why'] == 'cash buys spot']
    assert buys == [('BTC', 3000), ('ETH', 3000)]
    # more cash than the shortfalls: the shortfall first, the rest pro rata
    plan = plan_portfolio(cfg, {'coins': {'BTC': 0.75, 'ETH': 5.0}, 'hedged': {}, 'cash': 50000.0}, px, DAY * 1000, None)
    buys = {o['leg'][1]: round(o['coins'] * px[o['leg'][1]]) for o in plan['orders'] if o['why'] == 'cash buys spot'}
    assert buys == {'BTC': 10000, 'ETH': 40000}                           # 110,000 stack: 55,000 each


def spec_H2_a_stated_holding_joins_the_book_and_is_hedged_and_rebalanced():
    """The subaccount came with coins of its own (a demo gift of 1 BTC and
    1 ETH): a 'holding' on an asset says they are the row's — adopted at
    first sight, bounded by the wallet, hedged and rebalanced like the rest."""
    venue, lines, clock = _venue(), [], Clock()
    venue.coins['BTC'] = 1.0                                     # the wallet already holds 1 BTC
    venue.t_ms = int(clock.t * 1000)
    bot, tmp = _bot(venue, lines, clock=clock,
                    row={'capital': 30000, 'assets': [{'coin': 'BTC', 'weight': 0.5, 'holding': 1.0},
                                                      {'coin': 'ETH', 'weight': 0.5}]})
    bot.cycle()
    assert any('BTC: 1 coins adopted' in ln for ln in lines)
    # the stack is 60,000 of BTC + 30,000 cash = 90,000: 45,000 each → the cash buys ETH (its shortfall
    # is 45,000), then BTC sells 0.25 to its weight and ETH buys the rest of its share from that sale,
    # and both hedges go on at ratio 1
    orders = [(o[0], o[1], o[2], o[3]) for o in venue.orders]
    assert ('spot', 'ETHUSDT', 'Buy', 10.0) in orders and ('spot', 'BTCUSDT', 'Sell', 0.25) in orders
    assert ('spot', 'ETHUSDT', 'Buy', 5.0) in orders
    assert ('inverse', 'BTCUSD', 'Sell', 45000.0) in orders and ('inverse', 'ETHUSD', 'Sell', 45000.0) in orders
    assert ('spot', 'BTCUSDT', 'Buy') not in [o[:3] for o in orders]
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    bot.cycle()
    assert abs(bot.row['coins']['BTC'] - 0.75) < 1e-9 and abs(bot.row['coins']['ETH'] - 15.0) < 1e-9
    # a holding stated beyond the wallet is bounded by it (D76): the book says 2, the wallet holds 0.75
    venue.t_ms = int(clock.t * 1000)
    more, _ = _bot(venue, lines, tmp=tmp, clock=clock,
                   row={'capital': 30000, 'assets': [{'coin': 'BTC', 'weight': 0.5, 'holding': 2.0},
                                                     {'coin': 'ETH', 'weight': 0.5}]})
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    more.cycle()
    assert abs(more.row['coins']['BTC'] - 1.75) < 1e-9                 # the book: 0.75 + 1 more adopted
    assert abs(more.portfolio_view['stack']['BTC']['coins'] - 0.75) < 1e-9   # the stack: what the wallet holds
    from gridgremlin.config import ConfigError
    try:
        validate_config(dict(ROW, assets=[{'coin': 'BTC', 'weight': 0.5}, {'coin': 'ETH', 'weight': -0.5, 'holding': 1}]))
    except ConfigError as e:
        assert 'an outright short holds none' in str(e)
    else:
        raise AssertionError('a holding on a short was accepted')


def spec_H2_an_inverse_legs_funding_lands_in_the_book_as_coins_a_linear_legs_as_cash():
    """Caught before the carry fleet's first settlement (2026-10-10): an
    inverse short is paid its funding in the coin — the wallet's BTC grows,
    no quote arrives — and the row was about to spend cash it did not have."""
    venue, lines, clock = _venue(), [], Clock()
    venue.marks['ETHUSDT'] = 3000.0
    venue.t_ms = int(clock.t * 1000)
    legs = _legs()
    legs['hedge']['ETH'] = {'market_type': 'linear', 'symbol': 'ETHUSDT', 'adapter': LIN['ETH']}   # ETH: a USDT hedge
    bot, _ = _bot(venue, lines, legs=legs, row={'hedge': {'BTC': {'product': 'inverse'}, 'ETH': {'product': 'usdt'}}},
                  clock=clock)
    bot.cycle()
    clock.t += 8 * 3600; venue.t_ms = int(clock.t * 1000)
    venue.pay_funding('BTCUSD', 0.01)                             # 0.01 BTC, as the venue pays it
    venue.pay_funding('ETHUSDT', 300.0)                           # 300 USDT
    venue.coins['BTC'] += 0.01                                    # the wallet shows it
    bot.cycle()
    assert abs(bot.row['coins']['BTC'] - 0.76) < 1e-9             # the coins joined the book
    assert bot.row['cash'] == 300.0                               # only the linear leg's is cash
    assert abs(bot.row['funding_total'] - 900.0) < 1e-6           # 0.01 × 60,000 + 300, the carry line in quote
    assert bot.portfolio_view['carry']['total'] == bot.row['funding_total']
    clock.t += DAY; venue.t_ms = int(clock.t * 1000)
    bot.cycle()
    # at the tick the BTC hedge grows over the funding coins; the 300 buys spot toward the weights
    assert any(o[1] == 'BTCUSD' and o[2] == 'Sell' for o in venue.orders[4:]) or bot.row['last_tick_ms']


def spec_H2_the_spot_quote_names_the_legs_and_a_buys_fee_is_shaved_from_the_coins():
    from gridgremlin.portfolio import leg_markets
    cfg = validate_config(dict(ROW, spot_quote='USDC'))
    assert [(k, s) for k, _, _, s, _ in leg_markets(cfg)] == [('spot', 'BTCUSDC'), ('hedge', 'BTCUSD'),
                                                               ('spot', 'ETHUSDC'), ('hedge', 'ETHUSD')]
    assert validate_config(dict(ROW))['spot_quote'] == 'USDT'
    try:
        validate_config(dict(ROW, spot_quote='EUR'))
    except ConfigError as e:
        assert "'spot_quote'" in str(e)
    else:
        raise AssertionError('EUR accepted')
    venue, lines, clock = _venue(), [], Clock()
    venue.t_ms = int(clock.t * 1000)
    real = venue.place_market

    def with_fee(mt, symbol, side, qty, *a, **k):
        r = real(mt, symbol, side, qty, *a, **k)
        if mt == 'spot' and side == 'Buy':
            f = venue.fills[-1]
            f['fee'] = 0.001 * f['qty'] * f['price']               # 0.1%, stated in quote (M2)
            venue.coins[symbol[:-4]] -= 0.001 * f['qty']           # taken from the coins received
        return r
    venue.place_market = with_fee
    bot, _ = _bot(venue, lines, clock=clock)
    bot.cycle()
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    bot.cycle()
    assert abs(bot.row['coins']['BTC'] - 0.75 * 0.999) < 1e-9 and abs(venue.coins['BTC'] - 0.75 * 0.999) < 1e-9


def spec_H2_a_row_born_before_terms_were_kept_gets_a_baseline_and_a_new_quote_is_a_new_pot():
    """The carry fleet's state on the box predates terms_seen: at the restart
    on the three-coin USDC file it must adopt, re-pot and plan — not record
    the new terms as seen and sit."""
    venue, lines, clock = _venue(), [], Clock()
    venue.marks['SOLUSDC'] = venue.marks['SOLUSD'] = 150.0
    venue.marks['BTCUSDC'], venue.marks['ETHUSDC'] = 60000.0, 3000.0
    venue.coins['BTC'], venue.coins['ETH'], venue.coins['USDC'] = 1.0, 1.0, 50000.0
    venue.t_ms = int(clock.t * 1000)
    bot, tmp = _bot(venue, lines, row={'capital': 40000, 'assets': [{'coin': 'BTC', 'weight': 0.5}, {'coin': 'ETH', 'weight': 0.5}]},
                    clock=clock)
    bot.cycle()                                                  # 40k USDT in: 0.333 BTC, 6.67 ETH, hedged
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    bot.cycle()
    del bot.row['terms_seen']                                    # the state as the first engine left it
    bot.state.set(bot.botid, bot.row)
    # the file edited: three coins in USDC, the sub's BTC and ETH adopted
    legs = {'spot': {c: {'market_type': 'spot', 'symbol': f'{c}USDC', 'adapter': ad} for c, ad in
                     (('BTC', SPOT['BTC']), ('ETH', SPOT['ETH']),
                      ('SOL', SpotAdapter({'symbol': 'SOLUSDC', 'qty_step': 0.0001, 'price_tick': 0.01, 'min_qty': 0.0001, 'min_notional': 5})))},
            'hedge': {'BTC': {'market_type': 'inverse', 'symbol': 'BTCUSD', 'adapter': INV['BTC']},
                      'ETH': {'market_type': 'inverse', 'symbol': 'ETHUSD', 'adapter': INV['ETH']},
                      'SOL': {'market_type': 'inverse', 'symbol': 'SOLUSD',
                              'adapter': InverseAdapter({'symbol': 'SOLUSD', 'qty_step': 1, 'price_tick': 0.01, 'min_qty': 1, 'settle_coin': 'SOL'})}},
            'short': {}}
    clock.t += 120; venue.t_ms = int(clock.t * 1000)
    again, _ = _bot(venue, lines, tmp=tmp, legs=legs, clock=clock,
                    row={'capital': 50000, 'spot_quote': 'USDC',
                         'assets': [{'coin': 'BTC', 'weight': 0.3334, 'holding': 1.0}, {'coin': 'ETH', 'weight': 0.3333, 'holding': 1.0},
                                    {'coin': 'SOL', 'weight': 0.3333}]})
    out = again.cycle()
    assert out and out['tick']
    assert any('baseline capital 40,000.00 USDT' in ln for ln in lines)
    assert any('spot quote USDT → USDC: cash is the capital, 50,000.00 USDC' in ln for ln in lines)
    assert any('BTC: 1 coins adopted' in ln for ln in lines) and any('ETH: 1 coins adopted' in ln for ln in lines)
    new = [(o[0], o[1], o[2]) for o in venue.orders[4:]]
    # the book: 1.333 BTC (80k) + 7.67 ETH (23k) + 50k USDC = 153k, 51k each: the cash fills SOL's
    # shortfall first, BTC sells down, ETH buys up, every hedge resized to ratio one
    assert ('spot', 'SOLUSDC', 'Buy') in new and ('spot', 'BTCUSDC', 'Sell') in new and ('spot', 'ETHUSDC', 'Buy') in new
    assert ('inverse', 'SOLUSD', 'Sell') in new and ('inverse', 'BTCUSD', 'Sell') in new and ('inverse', 'ETHUSD', 'Sell') in new
    assert ('spot', 'BTCUSDC', 'Buy') not in new
    assert again.row['cash'] == 0.0 and again.row['terms_seen']['spot_quote'] == 'USDC'
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    again.cycle()                                                # the fills book: the stack sits at thirds
    v = again.portfolio_view
    assert all(abs(a['actual'] - 1 / 3) < 0.02 for a in v['assets']), v['assets']
    assert all(abs(a['hedged'] / v['stack'][a['coin']]['coins'] - 1.0) < 0.01 for a in v['assets'])


def spec_H2_cash_is_bounded_by_the_wallet_and_sells_go_before_buys_in_a_tick():
    """The carry fleet's second restart (2026-10-10): the cash step's SOL buy
    refused by a hair, the weight step bought it from the BTC sale — and the
    row kept believing in cash the wallet no longer held."""
    venue, lines, clock = _venue(), [], Clock()
    venue.coins['BTC'] = 1.0
    venue.t_ms = int(clock.t * 1000)
    bot, _ = _bot(venue, lines, clock=clock,
                  row={'capital': 30000, 'rebalance': {'min_notional': 20, 'cash_reserve': 0},
                       'assets': [{'coin': 'BTC', 'weight': 0.5, 'holding': 1.0}, {'coin': 'ETH', 'weight': 0.5}]})
    bot.cycle()
    kinds = [(o[0], o[2]) for o in venue.orders]
    assert kinds.index(('spot', 'Sell')) < kinds.index(('spot', 'Buy'))        # the BTC sale pays the ETH buys
    assert kinds[-2:] == [('inverse', 'Sell'), ('inverse', 'Sell')]
    # the book believes in cash the wallet does not hold: bounded, said once, and the tick completes
    bot.row['cash'] = 31000.0
    bot.state.set(bot.botid, bot.row)
    venue.coins['USDT'] = 12.5
    clock.t += DAY; venue.t_ms = int(clock.t * 1000)
    n = len(venue.orders)
    bot.cycle()
    assert bot.row['cash'] == 12.5 and any("beyond the wallet's 12.50 USDT — bounded" in ln for ln in lines)
    assert len(venue.orders) == n and bot.row['last_tick_ms'] == int(clock.t * 1000)   # nothing phantom asked; the tick stamped


def spec_H1_a_levered_row_buys_on_the_venues_loan_and_carries_it_as_negative_cash():
    venue, lines, clock = _venue(), [], Clock()
    venue.coins['USDT'] = 100000.0
    venue.t_ms = int(clock.t * 1000)
    borrowed = []
    real = venue.place_market

    def lending(mt, symbol, side, qty, *a, **k):
        if mt == 'spot' and side == 'Buy':
            borrowed.append(k.get('borrow'))
        return real(mt, symbol, side, qty, *a, **k)
    venue.place_market = lending
    bot, tmp = _bot(venue, lines, clock=clock,
                    row={'capital': 100000, 'spot_borrow': True, 'margin': {'spot_leverage': 1.5},
                         'assets': [{'coin': 'BTC', 'weight': 0.75}, {'coin': 'ETH', 'weight': 0.75}],
                         'risk': {'max_weight': 0.75}})
    bot.cycle()
    assert borrowed and all(borrowed)                                      # every buy says: lend me the rest
    assert abs(venue.coins['USDT'] + 50000.0) < 1.0                        # the venue lent 50,000
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    bot.cycle()
    v = bot.portfolio_view
    assert abs(bot.row['cash'] + 50000.0) < 1.0 and abs(v['borrowed'] - 50000.0) < 1.0
    assert abs(v['leverage'] - 1.5) < 0.01 and abs(v['value'] - 100000.0) < 1.0  # equity: the coins less the loan
    assert abs(bot._last_pos - 150000.0) < 1.0                             # the stack is 1.5× the equity
    # the venue charges interest: the loan grows, the row's equity shrinks by exactly that
    venue.coins['USDT'] -= 10.0
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    bot.cycle()
    assert abs(bot.portfolio_view['value'] - 99990.0) < 1.0
    # a leverage change on the file is planned at the next read, not the next tick
    flat, _ = _bot(venue, lines, tmp=tmp, clock=clock,
                   row={'capital': 100000, 'assets': [{'coin': 'BTC', 'weight': 0.5}, {'coin': 'ETH', 'weight': 0.5}]})
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    n = len(venue.orders)
    flat.cycle()
    assert any("leverage 1.5× → 1×" in ln for ln in lines) and len(venue.orders) > n
    sells = [o for o in venue.orders[n:] if o[0] == 'spot' and o[2] == 'Sell']
    assert sells and abs(sum(o[3] * venue.marks[o[1]] for o in sells) - 50000.0) < 100.0   # the loan repaid


def spec_H4_contributions_move_the_anchor_so_the_total_counts_only_what_the_book_made():
    """The carry card read +135k 'since its anchor' after a night of
    adoptions and capital raises: money that joins the book is not profit."""
    venue, lines, clock = _venue(), [], Clock()
    venue.coins['BTC'] = 1.0
    venue.t_ms = int(clock.t * 1000)
    bot, tmp = _bot(venue, lines, clock=clock,
                    row={'capital': 30000, 'assets': [{'coin': 'BTC', 'weight': 0.5, 'holding': 1.0},
                                                      {'coin': 'ETH', 'weight': 0.5}]})
    bot.cycle()
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    bot.cycle()
    v = bot.portfolio_view
    assert abs(v['value'] - 90000.0) < 1e-6 and abs(v['total']) < 1e-6         # 60k adopted + 30k cash: nothing made
    # a capital raise and a bigger holding: the anchor moves with them, the total stays what the book made
    venue.coins['BTC'] += 0.5
    venue.coins['USDT'] += 20000.0
    more, _ = _bot(venue, lines, tmp=tmp, clock=clock,
                   row={'capital': 50000, 'assets': [{'coin': 'BTC', 'weight': 0.5, 'holding': 1.5},
                                                     {'coin': 'ETH', 'weight': 0.5}]})
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    more.cycle()
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    more.cycle()
    v = more.portfolio_view
    assert abs(v['contributed'] - 50000.0) < 1e-6                              # 0.5 BTC at 60,000 + 20,000
    assert abs(v['value'] - 140000.0) < 1.0 and abs(v['total']) < 1.0
    # a row from before contributions were counted re-anchors once, and says so
    del more.row['contributed']
    more.row['anchor_value'] = 40000.0
    more.state.set(more.botid, more.row)
    old, _ = _bot(venue, lines, tmp=tmp, clock=clock,
                  row={'capital': 50000, 'assets': [{'coin': 'BTC', 'weight': 0.5, 'holding': 1.5},
                                                    {'coin': 'ETH', 'weight': 0.5}]})
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    old.cycle()
    assert any('anchor re-set at 1' in ln and 'the loss limit counts from now' in ln for ln in lines)
    assert abs(old.portfolio_view['total']) < 1.0


def spec_H4_the_floors_cut_is_fitted_to_the_shortfall_not_a_flat_quarter():
    """3× on the carry sub read free margin 44%; one more turn sits under the
    25% floor on purpose. A flat quarter a minute would churn 130k of
    orders; the cut is what restores the floor plus a buffer."""
    cut = PortfolioBot.cut_for_floor
    # free margin 20% of a 185k equity, 95k of initial margin in use, floor 25%:
    # the shortfall to 30% is 18.5k, freed in proportion to what is sold → 19.5% of the book
    assert abs(cut(0.20 * 185000, 185000, 95000, 0.25) - 18500 / 95000) < 1e-9
    assert cut(0.05 * 185000, 185000, 95000, 0.25) == 0.25               # deep under: the most one read cuts
    assert cut(0.29 * 185000, 185000, 95000, 0.25) == 0.03               # a hair under: the least worth placing
    assert cut(1000.0, 10000.0, None, 0.25) == 0.25                      # no IM stated: the flat step
    venue, lines, clock = _venue(), [], Clock()
    venue.t_ms = int(clock.t * 1000)
    bot, _ = _bot(venue, lines, clock=clock, row={'risk': {'margin_floor_pct': 0.25}})
    bot.cycle()
    venue.available_pct, venue.im = 0.20, 100000.0                       # 200k equity: shortfall to 30% is 20k over 100k IM = 20%
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    bot.cycle()
    cuts = [(o[1], o[2], round(o[3], 6)) for o in venue.orders[4:]]
    assert cuts == [('BTCUSDT', 'Sell', 0.15), ('ETHUSDT', 'Sell', 3.0), ('BTCUSD', 'Buy', 9000.0), ('ETHUSD', 'Buy', 9000.0)]
    assert any('every leg cut by 20%' in ln for ln in lines)


def spec_H4_after_a_trim_the_row_aims_lower_and_eases_back_only_while_free_margin_is_comfortable():
    """4× on the carry sub: the floor trimmed 11% in the first minute. Without
    a memory the next tick levers back into the floor every day."""
    venue, lines, clock = _venue(), [], Clock()
    venue.coins['USDT'] = 100000.0
    venue.t_ms = int(clock.t * 1000)
    bot, _ = _bot(venue, lines, clock=clock,
                  row={'capital': 100000, 'spot_borrow': True, 'margin': {'spot_leverage': 2.0},
                       'assets': [{'coin': 'BTC', 'weight': 1.0}, {'coin': 'ETH', 'weight': 1.0}],
                       'risk': {'max_weight': 1.0, 'margin_floor_pct': 0.25}})
    bot.cycle()                                                  # 200k of spot on 100k
    venue.available_pct, venue.im = 0.20, 100000.0               # under the floor: equity ≈ 100k → cut 10%
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    bot.cycle()
    assert abs(bot.row['lever_cap'] - 1.8) < 1e-9
    venue.available_pct = 0.31                                   # above the floor, not comfortably (needs > 35%)
    clock.t += DAY; venue.t_ms = int(clock.t * 1000)
    n = len(venue.orders)
    bot.cycle()                                                  # the tick aims at 1.8×: nothing to buy back
    assert abs(bot.row['lever_cap'] - 1.8) < 1e-9
    assert not [o for o in venue.orders[n:] if o[0] == 'spot' and o[2] == 'Buy']
    venue.available_pct = 0.40                                   # comfortable: eased 5% a tick, toward 2×
    clock.t += DAY; venue.t_ms = int(clock.t * 1000)
    bot.cycle()
    assert abs(bot.row['lever_cap'] - 1.89) < 1e-9 and any('leverage eased to 1.89×' in ln for ln in lines)
    for _ in range(3):
        clock.t += DAY; venue.t_ms = int(clock.t * 1000)
        bot.cycle()
    assert bot.row['lever_cap'] is None                         # back at the file's 2×


def spec_H2_a_levered_rows_quote_change_under_a_loan_reads_the_new_quotes_balance_as_the_loan():
    """The owner swapped the debt's coin on the venue (USDC → USDT, 2026-10-11):
    the row's new quote balance is the loan, not a fresh pot of capital —
    read as capital it would have levered a phantom 81k four times."""
    venue, lines, clock = _venue(), [], Clock()
    venue.coins['USDT'] = 100000.0
    venue.t_ms = int(clock.t * 1000)
    row = {'capital': 100000, 'spot_borrow': True, 'margin': {'spot_leverage': 2.0},
           'assets': [{'coin': 'BTC', 'weight': 1.0}, {'coin': 'ETH', 'weight': 1.0}], 'risk': {'max_weight': 1.0}}
    bot, tmp = _bot(venue, lines, clock=clock, row=row)
    bot.cycle()                                                  # 200k of spot, the venue lent 100k USDT
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    bot.cycle()
    assert abs(bot.row['cash'] + 100000.0) < 1.0
    # the owner swaps the loan's coin on the venue: USDT back to zero, USDC owed; the file says USDC
    venue.coins['USDC'] = venue.coins['USDT']
    venue.coins['USDT'] = 0.0
    venue.marks['BTCUSDC'], venue.marks['ETHUSDC'] = venue.marks['BTCUSDT'], venue.marks['ETHUSDT']
    legs = _legs()
    for c in legs['spot']:
        legs['spot'][c] = dict(legs['spot'][c], symbol=f'{c}USDC')
    clock.t += 120; venue.t_ms = int(clock.t * 1000)
    again, _ = _bot(venue, lines, tmp=tmp, legs=legs, clock=clock, row=dict(row, spot_quote='USDC'))
    n = len(venue.orders)
    again.cycle()
    assert abs(again.row['cash'] + 100000.0) < 1.0                        # the loan, in its new coin
    assert any('the loan is 99,9' in ln and "USDC, the row's cash" in ln for ln in lines)
    assert again.row['contributed'] == 0.0 and len(venue.orders) == n    # nothing contributed, nothing bought
    assert abs(again.portfolio_view['value'] - 100000.0) < 1.0           # equity unchanged by the swap


def spec_H4_the_owners_flatten_takes_every_leg_together_and_a_reset_makes_the_next_start_a_first_sight():
    """The owner (2026-10-11): 'flatten the account and erase all debt first
    … its just demo'. The loss limit's act, by hand; the sales repay the
    loan; --reset forgets the book and the tombstone."""
    venue, lines, clock = _venue(), [], Clock()
    venue.coins['USDT'] = 100000.0
    venue.t_ms = int(clock.t * 1000)
    bot, tmp = _bot(venue, lines, clock=clock,
                    row={'capital': 100000, 'spot_borrow': True, 'margin': {'spot_leverage': 2.0},
                         'assets': [{'coin': 'BTC', 'weight': 1.0}, {'coin': 'ETH', 'weight': 1.0}],
                         'risk': {'max_weight': 1.0}})
    bot.cycle()
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    bot.cycle()
    assert venue.coins['USDT'] < -99000.0                                 # the loan
    after = bot.flatten_now('flattened by the owner', tombstone=False)
    assert venue.coins['BTC'] < 1e-9 and venue.coins['ETH'] < 1e-9        # the stack sold
    assert all(not venue.positions.get(s) for s in ('BTCUSD', 'ETHUSD'))   # the shorts bought back
    assert abs(after['USDT'] - 100000.0) < 1.0                            # the sales repaid the loan
    assert not bot.alive and not bot.tombs.has('pfocarry')                # no tombstone when told so
    assert any('flattened by the owner — every leg flattened together' in ln for ln in lines)
    bot.state.forget('pfocarry')
    assert PortfolioState(tmp / 'portfolio_state.json').get('pfocarry') == {}
    fresh, _ = _bot(venue, lines, tmp=tmp, clock=clock,
                    row={'capital': 100000, 'assets': [{'coin': 'BTC', 'weight': 0.5}, {'coin': 'ETH', 'weight': 0.5}]})
    clock.t += 61; venue.t_ms = int(clock.t * 1000)
    fresh.cycle()                                                         # a first sight: the stack from capital
    assert fresh.row['anchor_value'] is not None and fresh.row['contributed'] == 0.0
    assert abs(venue.coins['BTC'] * 60000.0 - 50000.0) < 100.0
