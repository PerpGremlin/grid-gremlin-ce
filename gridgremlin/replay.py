# The martingale's rehearsal (SPEC T7). No second engine: the REAL Bot runs,
# cycle by cycle, against a venue made of candles. Everything the bot does —
# the base order, the safety ladder, the take profit, every stop and limit —
# is the live code; only the exchange is pretend.
#
# What the pretend exchange assumes, said once:
# - a bar is walked open -> the adverse extreme -> the other extreme -> close
#   (a long sees the low first): when a bar could have hit a stop and a
#   target both, the stop comes first;
# - a resting limit fills at its own price when the walk trades THROUGH it
#   (T3), at the maker fee; market orders and the venue's own TP/SL fill at
#   the walk's price or their trigger, at the taker fee;
# - the fill list never lags and nothing is ever refused for margin.
# Anything timed in seconds is judged at quarter-bar steps, so a timeout
# shorter than that is only as fine as the candles are.
from .apply import rung_of
from .bot import Bot
from .events import Notifier
from .exchange.errors import VenueError
from .report import apply_fill, new_book

CYCLES_PER_STEP = 4      # the bot needs a few cycles to finish a sequence
                         # (close -> account -> cleanup -> re-enter)
UNREHEARSABLE = ()       # (key, why) for anything the venue cannot model


def refuse_replay(cfg):
    """Why this row cannot be rehearsed, or None."""
    for key, why in UNREHEARSABLE:
        if cfg.get(key) is not None:
            return f"'{key}': {why} — rehearse without it"
    if (cfg.get('stop') or {}).get('watch') == 'position_sl':
        return ("a position_sl stop is one you place on the exchange "
                'yourself — there is nothing here to rehearse it against')
    return None


class BarVenue:
    """The client surface the Bot drives (Bybit's shape: it hosts the
    position's take profit and stop loss), backed by one price at a time."""

    hosts_position_tp = True

    def __init__(self, adapter, side, fee_maker, fee_taker, spread_bps=1.0):
        self.adapter = adapter
        self.long = side == 'long'
        self.entry = 'Buy' if self.long else 'Sell'
        self.idx = adapter.position_idx(self.entry, False) or 0
        self.fee_maker, self.fee_taker = fee_maker, fee_taker
        self.spread_bps = spread_bps
        self.price = None
        self.now = 0.0
        self.orders = []
        self.stop_book = []
        self.steps = 0                 # the holding, in integer qty-steps
        self.avg = None
        self.tp = self.sl = None
        self.trail = self.trail_from = self.trail_best = None
        self.fills = []
        self._n = 0
        self._ms = 0

    # --- the holding ----------------------------------------------------------

    @property
    def held(self):
        return self.steps * self.adapter.qty_step

    def _steps_of(self, qty):
        return int(round(float(qty) / self.adapter.qty_step))

    def _fill(self, side, qty, price, fee_rate, link_id='', kind=''):
        n = self._steps_of(qty)
        if side != self.entry:                     # an exit never flips
            n = min(n, self.steps)
        if n <= 0:
            return 0.0
        qty = n * self.adapter.qty_step
        if side == self.entry:
            total = (self.avg or 0.0) * self.held + price * qty
            self.steps += n
            self.avg = total / self.held
        else:
            self.steps -= n
            if self.steps == 0:        # the venue's own rows go with it
                self.avg = self.tp = self.sl = None
                self.trail = self.trail_from = self.trail_best = None
                self.stop_book = []
        self._n += 1
        # one distinct, increasing stamp per fill, never in the bot's future
        # (it asks for fills "until now")
        self._ms = max(self._ms + 1, int(self.now * 1000) - 500)
        self.fills.append({
            'time_ms': self._ms,
            'side': side.lower(), 'price': price, 'qty': qty,
            'fee': qty * price * fee_rate, 'link_id': link_id or '',
            'symbol': self.adapter.symbol, 'exec_id': f'x{self._n}',
            'venue_closed': bool(kind), 'venue_kind': kind})
        return qty

    # --- the walk -------------------------------------------------------------

    def advance(self, price, now):
        """One step of the walk: the price moves from where it was to
        `price`, and everything resting on the venue that the move trades
        through fills IN THE ORDER THE PRICE REACHES IT — a breakeven stop
        above a safety order fires before that safety fills, not after."""
        prev = self.price if self.price is not None else price
        self.price, self.now = price, max(now, self.now)
        exit_side = 'Sell' if self.long else 'Buy'
        self._trail_step(prev, price, exit_side)
        while True:
            due = []                   # (distance from prev, kind, item)
            for o in self.orders:
                if (price < o['price'] if o['side'] == 'Buy'
                        else price > o['price']):
                    due.append((abs(o['price'] - prev), 'order', o))
            for row in self.stop_book:
                level = float(row['triggerPrice'])
                up = self.long == ('TakeProfit' in row['stopOrderType'])
                if (price >= level) if up else (price <= level):
                    due.append((abs(level - prev), 'row', row))
            if self.steps and self.sl is not None and (
                    price <= self.sl if self.long else price >= self.sl):
                due.append((abs(self.sl - prev), 'sl', None))
            if self.steps and self.tp is not None and (
                    price >= self.tp if self.long else price <= self.tp):
                due.append((abs(self.tp - prev), 'tp', None))
            if not due:
                return
            _, kind, item = min(due, key=lambda d: d[0])
            if kind == 'order':
                self.orders.remove(item)
                if not (item['reduce_only'] and self.steps == 0):
                    self._fill(item['side'], item['qty'], item['price'],
                               self.fee_maker, item['link_id'])
            elif kind == 'row':
                self.stop_book.remove(item)
                self._fill(exit_side, item['qty'],
                           float(item['triggerPrice']), self.fee_taker,
                           kind=item['stopOrderType'])
            elif kind == 'sl':
                level, self.sl = self.sl, None
                self._fill(exit_side, self.held, level, self.fee_taker,
                           kind='StopLoss')
            else:
                level, self.tp = self.tp, None
                self._fill(exit_side, self.held, level, self.fee_taker,
                           kind='TakeProfit')

    def _trail_step(self, prev, price, exit_side):
        """The venue's trailing stop over one monotonic step: it arms once
        the price has reached its activation (at once, with none), follows
        the best price since, and closes the position a fixed distance
        behind it."""
        if not self.steps or self.trail is None:
            return
        fav = (price >= prev) == self.long         # a move in our favour
        if self.trail_best is None:
            start = self.trail_from
            if start is not None and not (
                    (max(prev, price) >= start) if self.long
                    else (min(prev, price) <= start)):
                return                             # not armed yet
            self.trail_best = (prev if start is None else start)
        if fav:
            self.trail_best = (max(self.trail_best, price) if self.long
                               else min(self.trail_best, price))
            return
        level = (self.trail_best - self.trail if self.long
                 else self.trail_best + self.trail)
        if (price <= level) if self.long else (price >= level):
            self._fill(exit_side, self.held, level, self.fee_taker,
                       kind='TrailingStop')

    # --- reads (the Bybit truth functions call these) -------------------------

    def read_symbol_truth(self, market_type, symbol, funding_interval=480.0):
        from .exchange.bybit.truth import read_symbol_truth
        # the pretend venue is one position and its book; a spot row (D59)
        # reads it in that one shape — the wallet is a real venue's matter
        return read_symbol_truth(self, 'linear' if market_type == 'spot'
                                 else market_type, symbol, funding_interval)

    def tickers(self, category, symbol):
        half = self.price * self.spread_bps / 20_000.0
        return {'markPrice': str(self.price),
                'bid1Price': str(self.price - half),
                'ask1Price': str(self.price + half),
                'fundingRate': '0', 'nextFundingTime': '0'}

    def open_orders_page(self, category, symbol, cursor=None):
        return {'list': [
            {'orderId': o['order_id'], 'orderLinkId': o['link_id'],
             'side': o['side'], 'price': str(o['price']), 'qty': o['qty'],
             'cumExecQty': '0', 'reduceOnly': o['reduce_only'],
             'orderStatus': 'New', 'positionIdx': o['position_idx'],
             'orderType': 'Limit', 'updatedTime': '0'}
            for o in self.orders], 'nextPageCursor': None}

    def position_list(self, category, symbol):
        if not self.steps:
            return {'list': []}
        return {'list': [{
            'positionIdx': self.idx, 'side': self.entry,
            'size': self.adapter.fmt_qty(self.held),
            'avgPrice': str(self.avg), 'leverage': '1', 'unrealisedPnl': '0',
            'takeProfit': '' if self.tp is None else str(self.tp),
            'stopLoss': '' if self.sl is None else str(self.sl),
            'trailingStop': '' if self.trail is None else str(self.trail)}]}

    def stop_orders(self, category, symbol):
        return list(self.stop_book)

    def fills_history(self, market_type, symbol, since_ms, until_ms):
        return [f for f in self.fills if since_ms <= f['time_ms'] <= until_ms]

    # --- writes ---------------------------------------------------------------

    def place_order(self, category, symbol, side, qty, price, link_id,
                    position_idx=0, reduce_only=False, post_only=True,
                    borrow=False):
        price = float(price)
        crosses = price >= self.price if side == 'Buy' else price <= self.price
        if crosses and post_only:
            raise VenueError('post-only order would cross',
                             kind='post_only_reject')
        self._n += 1
        oid = f'o{self._n}'
        if crosses:                    # marketable: this price or better
            self._fill(side, qty, self.price, self.fee_taker, link_id)
            return {'orderId': oid}
        self.orders.append({'order_id': oid, 'link_id': link_id, 'side': side,
                            'price': price, 'qty': qty,
                            'reduce_only': reduce_only,
                            'position_idx': position_idx})
        return {'orderId': oid}

    def cancel_order(self, category, symbol, order_id):
        self.orders = [o for o in self.orders if o['order_id'] != order_id]
        self.stop_book = [o for o in self.stop_book
                          if o['orderId'] != order_id]

    def amend_order(self, category, symbol, order_id, qty):
        for o in self.orders:
            if o['order_id'] == order_id:
                o['qty'] = qty

    def place_market(self, category, symbol, side, qty, position_idx=0,
                     reduce_only=False, link_id=None, borrow=False):
        half = self.price * self.spread_bps / 20_000.0
        self._fill(side, qty, self.price + (half if side == 'Buy' else -half),
                   self.fee_taker, link_id)

    def set_trading_stop(self, category, symbol, position_idx,
                         take_profit=None, stop_loss=None, sl_size=None,
                         tp_size=None, trailing_stop=None, active_price=None):
        if trailing_stop is not None and self.steps:
            self.trail = float(trailing_stop)
            self.trail_from = (None if active_price is None
                               else float(active_price))
            self.trail_best = None

        def row(kind, level, size):
            self._n += 1
            self.stop_book.append({'orderId': f's{self._n}',
                                   'stopOrderType': kind,
                                   'triggerPrice': level, 'qty': size,
                                   'positionIdx': position_idx})
        if take_profit is not None and tp_size is not None:
            row('PartialTakeProfit', take_profit, tp_size)
        elif take_profit is not None and self.steps:
            self.tp = float(take_profit)
        if stop_loss is not None and sl_size is not None:
            row('PartialStopLoss', stop_loss, sl_size)
        elif stop_loss is not None and self.steps:
            self.sl = float(stop_loss)


def backtest_martingale(cfg, adapter, bars, fee_maker=0.0002,
                        fee_taker=0.00055, bar_minutes=5, spread_bps=1.0):
    """T7: the real Bot over real bars. Returns the grid rehearsal's
    vocabulary plus the round's own: rounds, deepest safety order, how each
    kind of ending was reached, and why the bot stopped if it did."""
    long = cfg['side'] == 'long'
    sign = 1.0 if long else -1.0
    venue = BarVenue(adapter, cfg['side'], fee_maker, fee_taker, spread_bps)
    # T7: the pretend venue takes the ROW's venue shape — Hyperliquid hosts
    # no position TP/SL (D21), so there the engine's own trail (M21) and
    # resting exits are what rehearse, not Bybit's hosted ones
    venue.hosts_position_tp = (cfg.get('venue') != 'hyperliquid'
                               and cfg.get('market_type') != 'spot')   # D59
    lines = []
    bot = Bot(cfg, adapter, venue, Notifier(sink=lines.append), gen_seed=1,
              clock=lambda: venue.now)
    book = new_book()
    entry = venue.entry.lower()
    seen = 0
    span = bar_minutes * 60.0
    equity_curve, peak, max_drawdown, max_held = [], 0.0, 0.0, 0.0
    ran = 0
    for bar in bars:
        ran += 1
        t0 = bar['t'] / 1000.0
        walk = ((bar['o'], bar['l'], bar['h'], bar['c']) if long
                else (bar['o'], bar['h'], bar['l'], bar['c']))
        for k, price in enumerate(walk):
            venue.advance(price, t0 + span * k / 4.0)
            for _ in range(CYCLES_PER_STEP):
                if not bot.alive:
                    break
                unreal = (sign * venue.held * (price - venue.avg)
                          if venue.steps else 0.0)
                bot.cycle(equity=cfg['capital'] + book['realized']
                          - book['fees'] + unreal)
                venue.now += 1.0
        for f in venue.fills[seen:]:               # the ledger, R2's own
            apply_fill(book, f['side'], f['price'], f['qty'], f['fee'],
                       rung=rung_of(f['link_id'], bot.botid),
                       entry_side=entry)
        seen = len(venue.fills)
        max_held = max(max_held, venue.held)
        unreal = (sign * venue.held * (bar['c'] - venue.avg)
                  if venue.steps else 0.0)
        equity = book['realized'] - book['fees'] + unreal
        equity_curve.append(equity)
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        if not bot.alive and not venue.steps:
            break                      # stood down flat: nothing more moves
        # stood down HOLDING (X13): the walk goes on, so what was left open
        # is valued to the end, and the venue's own rows on it still work
    shipped = [ln for ln in lines if ln.startswith('[ship]')]
    kill = next((ln.split(': ', 1)[1] for ln in shipped
                 if ln.startswith(f'[ship] kill {bot.botid}')), None)
    return {'hosts_position_tp': venue.hosts_position_tp,
            
        'strategy': 'martingale',
        'grid_profit': book['realized'], 'fees': book['fees'],
        'funding': 0.0, 'net': book['realized'] - book['fees'],
        'total': equity_curve[-1] if equity_curve else 0.0,
        'trips': book['trips'], 'rounds': book['rounds'],
        'entry_fills': sum(1 for f in venue.fills if f['side'] == entry),
        'so_fills': book['so_fills'], 'max_depth': book['max_depth'],
        'held': venue.held, 'basis': venue.avg, 'max_held': max_held,
        'max_drawdown': max_drawdown, 'equity_curve': equity_curve,
        'stops': sum('stop fired' in ln for ln in shipped),
        'max_hold_closes': sum('max hold reached' in ln for ln in shipped),
        'ended': kill, 'bars_run': ran}
