"""The portfolio row running (D78): H2 the legs as identities on books of
the row's own fills, H3's plan placed on the clock, H4 the portfolio's
risk. One cycle, at most once a minute: read the venue, settle the book
from the row's own fills and the funding its shorts received, value the
row against its anchor, judge the risk, and — on the tick — plan and
place. Orders are market orders at the tick (the research's fees): the
engine's post-only law (G13) is the grid's, whose orders rest; a
rebalance once a day is a taker act by design.
"""
import time

from .exchange.errors import VenueError
from .portfolio import plan_portfolio, regime_word

READ_EVERY_S = 60.0          # the risk rules want a read a minute; the plan is daily
OVERLAP_MS = 10 * 60 * 1000  # fills are re-read this far back and deduped by id
DELEVER_STEP = 0.25          # the most the floor cuts in one read
DELEVER_LEAST = 0.03         # the least worth cutting
FLOOR_BUFFER = 0.05          # the floor is restored to this much above itself
RELAX_STEP = 0.05            # the ratchet eases back toward the file's leverage by this per tick
LEG_CODES = {'spot': 's', 'hedge': 'h', 'short': 'x'}


def _unreal(mt, size, avg, mark):
    """A short leg's open P&L in quote: linear (avg − mark) × size; inverse
    $1 contracts realise in the coin — stated at mark (A4)."""
    if not size or not avg or not mark:
        return 0.0
    if mt == 'inverse':
        return size * (1.0 / mark - 1.0 / avg) * mark
    return (avg - mark) * size


def _apply(book, side, price, qty, fee, inverse):
    """A short leg's own average-cost book: a sell opens or adds, a buy
    reduces and realises. Linear: realised and fees in quote. Inverse: $1
    contracts, realised and fees in the coin (the venue charges an inverse
    fee in the coin — H8), and the average entry is the contracts-weighted
    HARMONIC mean: the arithmetic mean overstates the short's P&L whenever
    contracts are added at a new price (the return-split audit, 2026-10-09)."""
    pos, avg = book['position'], book['avg']
    if side == 'sell':
        total = pos + qty
        if inverse:
            if not pos or not avg:
                book['avg'] = price
            elif total and price:
                book['avg'] = total / (pos / avg + qty / price)
        else:
            book['avg'] = (avg * pos + price * qty) / total if total else 0.0
        book['position'] = total
    else:
        closed = min(pos, qty)
        if closed > 0 and avg:
            book['realized'] += (closed * (1.0 / price - 1.0 / avg) if inverse
                                 else (avg - price) * closed)
        book['position'] = max(pos - closed, 0.0)
        if book['position'] <= 1e-12:
            book['position'], book['avg'] = 0.0, 0.0
    book['fees'] += fee


class RegimeReader:
    """H3: the D67 reading for a coin's spot market, re-read only when the
    readings file has changed. Answers the reading's own word, or None."""

    def __init__(self, path=None):
        from .market import STORE
        from pathlib import Path
        self.path = Path(path or STORE)
        self._mtime, self._row = None, None

    def __call__(self, coin):
        try:
            m = self.path.stat().st_mtime
        except OSError:
            return None
        if m != self._mtime:
            from .market import latest
            self._mtime, self._row = m, latest(self.path)
        markets = (self._row or {}).get('markets') or {}
        for key in (f'bybit:spot:{coin}USDT', f'bybit:linear:{coin}USDT', f'bybit:inverse:{coin}USD'):
            if key in markets:
                return markets[key].get('regime')
        return None


class PortfolioBot:
    """`legs`: {'spot': {coin: {symbol, adapter}}, 'hedge': {coin:
    {market_type, symbol, adapter}}, 'short': {coin: {...}}} — resolved by
    the build from the venue's catalogue (A1), never from config."""

    def __init__(self, cfg, legs, client, notifier, state, tombstones=None,
                 clock=None, regime_reader=None):
        from .config import VENUE_ICONS
        from .events import VenueNotifier
        self.cfg, self.legs, self.client = cfg, legs, client
        self.notify = VenueNotifier(notifier, VENUE_ICONS.get(cfg.get('venue'), ''))
        self.botid = cfg['botid']
        self.state, self.tombs = state, tombstones
        self._now = clock or time.time
        self._regime = regime_reader or (lambda coin: None)
        self.alive = True
        self._last_pos = None            # the stack's value in quote (D70 reads "holding")
        self.notional_now = 0.0          # the shorts at mark (D56)
        self.capped = None
        self._loss_now = None
        self.offset = 0
        self.margin_view = None
        self.orders_view = None
        self.portfolio_view = None
        self._next_read = 0.0
        self._warned = {}
        self._seq = 0
        self.row = state.get(self.botid)

    # --- the state row ---------------------------------------------------------

    def _fresh_row(self, now_ms):
        return {'since_ms': now_ms, 'anchor_value': None, 'last_tick_ms': None,
                'cash': float(self.cfg['capital']), 'coins': {}, 'books': {},
                'fills_to_ms': now_ms, 'seen': [], 'funding_to_ms': now_ms,
                'funding': [], 'funding_total': 0.0, 'parked': {}, 'unwound': {},
                'delevered': 0, 'spent': 0.0, 'tilt_pnl': 0.0, 'last_px': {},
                'regime_seen': {}, 'terms_seen': self._terms(),
                'interest_total': 0.0, 'interest_to_ms': now_ms, 'borrow_apr': None}

    def _terms(self):
        return {'capital': float(self.cfg['capital']), 'spot_quote': self.cfg.get('spot_quote', 'USDT'),
                'leverage': float((self.cfg.get('margin') or {}).get('spot_leverage', 1.0)),
                'assets': [[a['coin'], a['weight']] for a in self.cfg['assets']],
                'holdings': {a['coin']: a.get('holding', 0.0) for a in self.cfg['assets'] if a.get('holding')}}

    def _contribute(self, quote):
        """H4: money that joins the book is not profit — a capital raise, an
        adopted holding at the day's price, a new cash pot — so it moves the
        anchor along, and the total since the anchor counts only what the
        book made."""
        self.row['contributed'] = self.row.get('contributed', 0.0) + quote

    def _adopt(self, seen_holdings, prices):
        """H2: a stated holding is coins the owner says are the row's — they
        join the book (bounded by the wallet at every read, as all coins
        are); a raised statement adopts the difference, a lowered one is
        said and not sold."""
        for coin, h in self._terms()['holdings'].items():
            before = (seen_holdings or {}).get(coin, 0.0)
            if h > before:
                self.row['coins'][coin] = self.row['coins'].get(coin, 0.0) + (h - before)
                self._contribute((h - before) * prices.get(coin, 0.0))
                self.notify.event('info', self.botid,
                                  f'{coin}: {h - before:.10g} coins adopted into the book (H2)')
            elif h < before:
                self.notify.event('warn', self.botid,
                                  f'{coin}: the stated holding fell by {before - h:.10g} — the row '
                                  'does not sell what it was told it owns; sell by hand (H2)')

    def _learn_terms(self, prices, wallet=None):
        """H2: the row's terms changed under it (a restart on an edited
        file): a raised capital is cash to spend, a lowered one is said and
        not sold down (the owner sells by hand), a changed asset list is
        said — and the next read plans at once, not at the next tick."""
        row, now = self.row, self._terms()
        seen = row.get('terms_seen')
        if seen is None:
            # a row born before terms were kept (the carry fleet's first
            # night): its baseline is what it was given — the cash it spent
            # and holds, in USDT, no holdings — so the new terms act
            seen = {'capital': float(row.get('spent', 0.0)) + float(row.get('cash', 0.0)),
                    'spot_quote': 'USDT', 'assets': now['assets'], 'holdings': {}, 'leverage': 1.0}
            self.notify.event('info', self.botid,
                              f"terms first kept: baseline capital {seen['capital']:,.2f} USDT (H2)")
        if seen == now:
            row['terms_seen'] = now
            return
        if now.get('holdings') != seen.get('holdings'):
            self._adopt(seen.get('holdings'), prices)
        if now['spot_quote'] != seen['spot_quote']:
            bal = float(((wallet or {}).get('coins') or {}).get(now['spot_quote'], {}).get('wallet_balance', 0.0))
            if self.cfg.get('margin') and bal < 0:
                # a levered row's quote changed under a loan (the owner swapped
                # the debt's coin on the venue): the new quote's balance IS the
                # loan — the row's cash, nothing contributed
                row['cash'] = bal
                self.notify.event('info', self.botid,
                                  f"spot quote {seen['spot_quote']} → {now['spot_quote']}: the loan is "
                                  f"{-bal:,.2f} {now['spot_quote']}, the row's cash (H2)")
            else:
                # a new quote is a new cash pot: the capital, in that quote;
                # what was spent in the old quote is coins already
                self._contribute(now['capital'] - max(row['cash'], 0.0))
                row['cash'] = now['capital']
                self.notify.event('info', self.botid,
                                  f"spot quote {seen['spot_quote']} → {now['spot_quote']}: cash is the capital, "
                                  f"{now['capital']:,.2f} {now['spot_quote']} (H2)")
        elif now['capital'] > seen['capital']:
            row['cash'] += now['capital'] - seen['capital']
            self._contribute(now['capital'] - seen['capital'])
            self.notify.event('info', self.botid,
                              f"capital raised by {now['capital'] - seen['capital']:,.2f} — "
                              'cash to spend at the next read (H2)')
        elif now['capital'] < seen['capital']:
            self.notify.event('warn', self.botid,
                              f"capital lowered by {seen['capital'] - now['capital']:,.2f} — the "
                              'row does not sell down on its own; sell by hand or raise it back (H2)')
        if now['assets'] != seen['assets']:
            self.notify.event('info', self.botid,
                              'assets or weights changed: ' + ', '.join(f'{c} {w:+.0%}' for c, w in now['assets'])
                              + ' — planned at the next read (H2)')
        if now['leverage'] != seen.get('leverage', 1.0):
            self.notify.event('info', self.botid,
                              f"the stack's leverage {seen.get('leverage', 1.0):g}× → {now['leverage']:g}× — "
                              'planned at the next read (H1 margin)')
        row['last_tick_ms'] = None
        row['terms_seen'] = now

    def _regime_now(self, coin, now_ms):
        """H3: the regime the plan leans on — the reading's word, believed
        only after it has held `hold_hours` (a tilt that flips on one
        reading churns); until then the last believed word stands."""
        if not self.cfg.get('regime'):
            return None
        word = regime_word(self._regime(coin))
        seen = self.row.setdefault('regime_seen', {})
        cur = seen.get(coin) or [word, now_ms, word]          # [candidate, since, believed]
        if cur[0] != word:
            cur = [word, now_ms, cur[2]]
        if now_ms - cur[1] >= self.cfg['regime']['hold_hours'] * 3_600_000:
            cur[2] = cur[0]
        seen[coin] = cur
        return cur[2]

    def _mark_tilt(self, coins, held, prices):
        """H6's tilt line: the shorts' excess over neutral (the row's ratio
        × the coins held), marked each read — extra short gains as the
        price falls, loses as it rises. No second model: the live book
        against its own neutral."""
        row = self.row
        for c in self.legs['hedge']:
            px, last = prices[c], row['last_px'].get(c)
            if last and px:
                neutral = self.cfg['hedges'][c]['ratio'] * coins.get(c, 0.0)
                row['tilt_pnl'] += (neutral - held['hedge'].get(c, 0.0)) * (px - last)
            row['last_px'][c] = px

    def _say_once(self, key, kind, text, every_s=3600.0):
        now = self._now()
        if now - self._warned.get(key, 0.0) >= every_s:
            self._warned[key] = now
            self.notify.event(kind, self.botid, text)

    # --- reads --------------------------------------------------------------------

    def _own_fills(self, mt, symbol, since_ms, now_ms):
        hist = getattr(self.client, 'fills_history', None)
        if hist is None:
            return []
        return [f for f in hist(mt, symbol, since_ms, now_ms)
                if str(f.get('link_id') or '').startswith(self.botid + '-')]

    def _funding_rows(self, mt, symbol, since_ms, now_ms):
        hist = getattr(self.client, 'funding_history', None)
        if hist is None:
            return []
        return [f for f in hist(mt, symbol, since_ms, now_ms) if f.get('side') == 'sell']

    def _settle_fills(self, now_ms):
        """The book from the row's own fills since the watermark: spot fills
        move the coins; a short leg's fills move its book. Deduped across
        the overlap by execution id."""
        row = self.row
        since = row['fills_to_ms'] - OVERLAP_MS
        seen = set(row['seen'])
        fresh = []
        for coin, leg in self.legs['spot'].items():
            for f in self._own_fills('spot', leg['symbol'], since, now_ms):
                if f['exec_id'] in seen:
                    continue
                seen.add(f['exec_id'])
                q = float(f['qty'])
                # a spot buy's fee is taken from the received coin; the fills
                # reader states it in quote (M2) — back to coins at the price
                fee_coin = (float(f.get('fee') or 0.0) / float(f['price'])
                            if f['side'] == 'buy' and f.get('price') else 0.0)
                row['coins'][coin] = max(row['coins'].get(coin, 0.0)
                                         + (q if f['side'] == 'buy' else -q) - fee_coin, 0.0)
                fresh.append(f['exec_id'])
        for kind in ('hedge', 'short'):
            for coin, leg in self.legs[kind].items():
                book = row['books'].setdefault(f'{kind}:{coin}',
                                               {'position': 0.0, 'avg': 0.0, 'realized': 0.0, 'fees': 0.0})
                for f in self._own_fills(leg['market_type'], leg['symbol'], since, now_ms):
                    if f['exec_id'] in seen:
                        continue
                    seen.add(f['exec_id'])
                    _apply(book, f['side'], float(f['price']), float(f['qty']),
                           float(f.get('fee') or 0.0), leg['market_type'] == 'inverse')
                    fresh.append(f['exec_id'])
        row['seen'] = (row['seen'] + fresh)[-400:]
        row['fills_to_ms'] = now_ms

    def _settle_funding(self, now_ms, prices):
        """What the shorts received since the watermark: a linear leg's is
        quote and joins the cash the next tick spends on spot; an inverse
        leg's is paid in the coin and lands in the wallet as coins — it
        joins the book as coins, and the hedge grows over them at the tick
        (the inverse's own compounding). The trailing window, in quote,
        feeds the funding rule; the carry line counts quote."""
        row = self.row
        got = 0.0
        for kind in ('hedge', 'short'):
            for coin, leg in self.legs[kind].items():
                inverse = leg['market_type'] == 'inverse'
                for f in self._funding_rows(leg['market_type'], leg['symbol'],
                                            row['funding_to_ms'], now_ms):
                    amt = float(f['amount'])
                    if inverse:
                        if kind == 'hedge':
                            row['coins'][coin] = max(row['coins'].get(coin, 0.0) + amt, 0.0)
                        amt = amt * prices.get(coin, 0.0)      # the carry line, in quote
                        quote = 0.0
                    else:
                        quote = amt
                    got += quote
                    row['funding_total'] += amt - quote      # the inverse part, in quote
                    row['funding'].append([int(f['time_ms']), coin, amt])
        keep = now_ms - self.cfg['funding_rule']['trailing_days'] * 86_400_000
        row['funding'] = [x for x in row['funding'] if x[0] >= keep]
        row['funding_total'] += got
        row['cash'] += got
        row['funding_to_ms'] = now_ms

    def _settle_interest(self, now_ms):
        """H4: what the loan cost since the watermark, from the venue's own
        ledger — summed into the row's figure, the latest hourly rate kept
        as a yearly one; a venue that keeps no such ledger (a fake, a
        venue without margin) leaves both as they are."""
        hist = getattr(self.client, 'borrow_history', None)
        row = self.row
        if hist is None or not self.cfg.get('margin'):
            return
        row.setdefault('interest_total', 0.0)
        row.setdefault('interest_to_ms', now_ms - 3_600_000)
        try:
            rows = hist(self.cfg.get('spot_quote', 'USDT'), row['interest_to_ms'], now_ms)
        except (VenueError, OSError):
            return
        for r in rows:
            if r['time_ms'] > row['interest_to_ms']:
                row['interest_total'] += r['cost']
                row['borrow_apr'] = r['hourly_rate'] * 8760.0
        if rows:
            row['interest_to_ms'] = max(row['interest_to_ms'], max(r['time_ms'] for r in rows))

    def _funding_yield(self, held, prices, now_ms):
        """H4: the trailing funding to the shorts as a yearly yield on what
        they cover at mark — None until the row has a day of history, or
        while it holds no short."""
        row, cfg = self.row, self.cfg
        days = min(cfg['funding_rule']['trailing_days'],
                   (now_ms - row['since_ms']) / 86_400_000)
        notional = sum(held[k].get(c, 0.0) * prices.get(c, 0.0)
                       for k in ('hedge', 'short') for c in held[k])
        if days < 1.0 or notional <= 0:
            return None
        return sum(x[2] for x in row['funding']) / notional * (365.0 / days)

    def _trailing_funding(self, now_ms):
        """H3: each hedge's market funding over the rule's window, as a yearly
        rate (trailing_yield over the sum of the market's rates) — judged on
        the market, never on the row's own payments, which stop while the
        hedge stands down. Unreadable rates judge nothing: the hedge stays."""
        from .portfolio import trailing_yield
        win = self.cfg['funding_rule']['trailing_days']
        read = getattr(self.client, 'market_funding_rates', None)
        out = {}
        if read is None:
            return out
        for c, leg in self.legs['hedge'].items():
            try:
                rates = read(leg['market_type'], leg['symbol'], now_ms - int(win * 86_400_000), now_ms)
            except (VenueError, OSError, KeyError, ValueError):
                continue
            if not rates:
                continue
            days = min(win, (now_ms - rates[0][0]) / 86_400_000 + 1.0 / 3)
            y = trailing_yield(sum(r for _, r in rates), 1.0, days)
            if y is not None:
                out[c] = y
        return out

    def _judge_borrow_rate(self, held, prices, now_ms):
        """H4: the loan is stood down — the ratchet's cap to 1×, planned at
        the next read, said once an hour — when the venue's rate is above
        the row's `borrow_apr_max`, and when the shorts' trailing funding
        yield is under that rate (H1: a loan that costs more than the carry
        it buys is a levered long with a bill); the ratchet eases back only
        once neither holds."""
        cfg, row = self.cfg, self.row
        apr, cap = row.get('borrow_apr'), (cfg.get('margin') or {}).get('borrow_apr_max')
        if apr is None or not cap:
            return
        L = cfg['margin']['spot_leverage']

        def stand_down(key, kind, text):
            if (row.get('lever_cap') or L) > 1.0:
                row['lever_cap'] = 1.0
                row['last_tick_ms'] = None           # planned at the next read
            self._say_once(key, kind, text)

        if apr > cap:
            stand_down('apr', 'warn', f'the loan costs {apr:.2%}/yr, above the row\'s cap of '
                                      f'{cap:.2%} — the leverage stands down to 1× (H4)')
            row['rate_blocks_relax'] = True
        else:
            row['rate_blocks_relax'] = False
        y = self._funding_yield(held, prices, now_ms)
        if y is not None and y < apr:
            stand_down('yield', 'margin', f'the shorts earn {y:.2%}/yr trailing, under the loan\'s '
                                          f'{apr:.2%} — the leverage stands down to 1× (H4)')
            row['yield_blocks_relax'] = True
        else:
            row['yield_blocks_relax'] = False

    def _short_size(self, truth, leg):
        idx = leg['adapter'].position_idx('Sell', False) or 0
        pos = truth['positions'].get(idx) or {}
        if pos.get('side') and pos['side'] != 'Sell':
            return 0.0, None
        return float(pos.get('size') or 0.0), pos.get('avg_entry')

    # --- writes ----------------------------------------------------------------------

    def _link(self, kind, coin):
        self._seq += 1
        return f'{self.botid}-{LEG_CODES[kind]}{coin}-{int(self._now()) % 100000}{self._seq}'

    def _place(self, kind, coin, side, coins, price, why):
        """One market order for `coins` of the leg; under the venue's minimum
        it is left, said once. Returns the coins asked for, or 0."""
        leg = self.legs[kind][coin]
        ad = leg['adapter']
        if kind == 'spot':
            # a sell floors (never more than is held); a buy and a hedge go
            # to the nearest lot — 0.7 × 0.75 × 60,000 is 31,500, not 31,499
            qty = ad.round_qty(coins) if side == 'Sell' else ad.nearest_qty(coins)
            if not ad.meets_minimum(qty, price):
                return 0.0
            if side == 'Buy':
                # in quote: the venue checks a coin-sized buy at a buffered
                # price and refuses it when it spends nearly all the cash
                quote = f'{qty * price:.2f}'
                self.client.place_market('spot', leg['symbol'], side, ad.fmt_qty(qty),
                                         link_id=self._link(kind, coin), quote_qty=quote,
                                         borrow=bool(self.cfg.get('spot_borrow')))   # D24/H1: the venue lends
                self.notify.event('order', self.botid,
                                  f"buy {coin} spot for {quote} {self.cfg.get('spot_quote', 'USDT')} "
                                  f"(~{ad.fmt_qty(qty)}; {why})")
                return qty
            self.client.place_market('spot', leg['symbol'], side, ad.fmt_qty(qty),
                                     link_id=self._link(kind, coin))
            self.notify.event('order', self.botid,
                              f"{side.lower()} {ad.fmt_qty(qty)} {coin} spot ({why})")
            return qty
        mt = leg['market_type']
        units = ad.nearest_qty(coins * price if mt == 'inverse' else coins)
        if not ad.meets_minimum(units, price):
            return 0.0
        reduce = side == 'Buy'
        self.client.place_market(mt, leg['symbol'], side, ad.fmt_qty(units),
                                 ad.position_idx(side, reduce) or 0, reduce_only=reduce,
                                 link_id=self._link(kind, coin))
        self.notify.event('order', self.botid,
                          f"{side.lower()} {ad.fmt_qty(units)} {leg['symbol']} {kind} ({why})")
        return units / price if mt == 'inverse' else units

    # --- H4: the risk is the portfolio's ------------------------------------------

    def _flatten(self, reason, coins, held, prices):
        """Every leg together in one cycle: shorts bought back, the stack
        sold, as market orders; then the tombstone (X7). A leg that refuses
        is said and the rest still go — a hedged book cut on one side is a
        directional bet taken at the worst moment."""
        left = []
        for kind in ('hedge', 'short'):
            for coin, size in held[kind].items():
                if size <= 0:
                    continue
                try:
                    self._place(kind, coin, 'Buy', size, prices[coin], f'flatten: {reason}')
                except (VenueError, OSError) as e:
                    left.append(f'{kind} {coin}: {e}')
        for coin, q in coins.items():
            if q <= 0:
                continue
            try:
                self._place('spot', coin, 'Sell', q, prices[coin], f'flatten: {reason}')
            except (VenueError, OSError) as e:
                left.append(f'spot {coin}: {e}')
        if self.tombs is not None:
            self.tombs.add(self.botid, reason)
        self.alive = False
        tail = f" — NOT closed: {'; '.join(left)}" if left else ''
        self.notify.event('kill', self.botid,
                          f'{reason} — every leg flattened together (H4){tail}', urgent=True)

    @staticmethod
    def cut_for_floor(available, equity, im, floor):
        """H4, pure: the share of the book to cut so free margin returns to
        the floor plus a buffer — the shortfall over the margin the book
        uses (freed in proportion to what is sold), between the least worth
        placing and the most one read cuts. A book held at the edge on
        purpose is cut by what it needs, not by a flat quarter a minute."""
        if not equity or not im:
            return DELEVER_STEP
        short = (floor + FLOOR_BUFFER) * equity - available
        return max(DELEVER_LEAST, min(DELEVER_STEP, short / im))

    def _delever(self, coins, held, prices, share):
        """H4: under the floor the whole book shrinks by `share` — each
        long's coins sold and its hedge bought back together, so the book
        stays neutral while the loan is repaid; an outright short bought
        back by the same share. Cutting the shorts alone would leave a
        levered long at the worst moment."""
        n = 0
        for coin, q in coins.items():
            if q > 0 and self._place('spot', coin, 'Sell', q * share, prices[coin], 'margin floor'):
                n += 1
        for kind in ('hedge', 'short'):
            for coin, size in held[kind].items():
                if size > 0 and self._place(kind, coin, 'Buy', size * share, prices[coin], 'margin floor'):
                    n += 1
        self.row['delevered'] += 1
        return n

    def _unwind(self, coin, coins, held, prices, basis):
        q = coins.get(coin, 0.0)
        if held['hedge'].get(coin, 0.0) > 0:
            self._place('hedge', coin, 'Buy', held['hedge'][coin], prices[coin], 'basis stop')
        if q > 0:
            sold = self._place('spot', coin, 'Sell', q, prices[coin], 'basis stop')
            self.row['parked'][coin] = self.row['parked'].get(coin, 0.0) + sold * prices[coin]
        self.row['unwound'][coin] = int(self._now() * 1000)
        self.notify.event('warn', self.botid,
                          f"{coin}: basis {basis:.2%} past the stop "
                          f"{self.cfg['risk']['basis_stop_pct']:.2%} — its pair unwound, "
                          'the rest held (H4)')

    def flatten_now(self, reason, tombstone=True):
        """The owner's flatten: the cycle's reads, then every leg together
        (H4's act, by hand). Returns what the venue holds after."""
        spot = {c: self.client.read_symbol_truth('spot', leg['symbol'])
                for c, leg in self.legs['spot'].items()}
        perps = {(k, c): self.client.read_symbol_truth(leg['market_type'], leg['symbol'])
                 for k in ('hedge', 'short') for c, leg in self.legs[k].items()}
        wallet = self.client.read_wallet()
        prices = {c: float(t['mark'] or 0.0) for c, t in spot.items()}
        for (k, c), t in perps.items():
            prices.setdefault(c, float(t['mark'] or 0.0))
        row = self.row or self._fresh_row(int(self._now() * 1000))
        wcoins = {c: float((wallet.get('coins') or {}).get(c, {}).get('wallet_balance', 0.0))
                  for c in self.legs['spot']}
        coins = {c: min(row['coins'].get(c, 0.0), wcoins[c]) for c in self.legs['spot']}
        held = {'hedge': {}, 'short': {}}
        for (k, c), t in perps.items():
            size, _ = self._short_size(t, self.legs[k][c])
            px = prices[c]
            held[k][c] = size / px if self.legs[k][c]['market_type'] == 'inverse' and px else size
        tombs, self.tombs = self.tombs, (self.tombs if tombstone else None)
        try:
            self._flatten(reason, coins, held, prices)
        finally:
            self.tombs = tombs
        after = self.client.read_wallet()
        return {c: float((after.get('coins') or {}).get(c, {}).get('wallet_balance', 0.0))
                for c in list(self.legs['spot']) + [self.cfg.get('spot_quote', 'USDT')]}

    # --- the cycle -------------------------------------------------------------------

    def cycle(self, equity=None):
        if not self.alive:
            return None
        now = self._now()
        if now < self._next_read:
            return None
        self._next_read = now + READ_EVERY_S
        now_ms = int(now * 1000)
        cfg, row = self.cfg, self.row
        fresh = not row
        if fresh:
            row = self.row = self._fresh_row(now_ms)
        spot = {c: self.client.read_symbol_truth('spot', leg['symbol'])
                for c, leg in self.legs['spot'].items()}
        perps = {(k, c): self.client.read_symbol_truth(leg['market_type'], leg['symbol'])
                 for k in ('hedge', 'short') for c, leg in self.legs[k].items()}
        wallet = self.client.read_wallet()
        prices = {c: float(t['mark'] or 0.0) for c, t in spot.items()}
        for (k, c), t in perps.items():
            prices.setdefault(c, float(t['mark'] or 0.0))
        if fresh:
            self._adopt({}, prices)                  # a stated holding starts the book
            row['contributed'] = 0.0                 # the anchor is the first value: nothing contributed since
        self._learn_terms(prices, wallet)
        self._settle_fills(now_ms)
        self._settle_funding(now_ms, prices)
        self._settle_interest(now_ms)
        # the book, bounded by the wallet (D76): coins above the row's own are
        # not its; coins missing are gone whoever took them
        wcoins = {c: float((wallet.get('coins') or {}).get(c, {}).get('wallet_balance', 0.0))
                  for c in self.legs['spot']}
        coins = {c: min(row['coins'].get(c, 0.0), wcoins[c]) for c in self.legs['spot']}
        # the cash the same way: the row's quote beyond what the wallet holds
        # is not there to spend (a buy refused by a hair, the weight step
        # paying from a sale instead — the carry fleet's second restart)
        quote = cfg.get('spot_quote', 'USDT')
        wq = float((wallet.get('coins') or {}).get(quote, {}).get('wallet_balance', 0.0))
        if row['cash'] > wq + 1e-9:
            if wq >= 0 or not cfg.get('margin'):
                self._say_once('cash', 'info', f"cash {row['cash']:,.2f} beyond the wallet's {wq:,.2f} {quote} "
                                               '— bounded to the wallet (D76)')
            row['cash'] = wq if cfg.get('margin') else max(wq, 0.0)
        elif cfg.get('margin') and wq < 0:
            row['cash'] = wq                 # the venue's loan, with its interest, is the row's
        held, unreal = {'hedge': {}, 'short': {}}, 0.0
        open_coin = {}                 # H8: an inverse hedge's open P&L, in its coin
        lin_open = 0.0
        for (k, c), t in perps.items():
            leg = self.legs[k][c]
            size, avg = self._short_size(t, leg)
            px = prices[c]
            inv = leg['market_type'] == 'inverse'
            held[k][c] = (size / px if inv and px else size)
            u = _unreal(leg['market_type'], size, avg, px)
            unreal += u
            if inv and k == 'hedge' and px:
                open_coin[c] = u / px
            elif not inv:
                lin_open += u
        # H8: an inverse leg realises and pays its fees in the coin, and the
        # venue settles them into the coin's wallet — so the coins the row
        # holds are its spot book PLUS its hedge's realised coin, bounded by
        # the wallet (D76); counted there once, never again as quote (the
        # audit's double count). A linear leg's realised stays quote.
        realised, inv_real = 0.0, {}
        for key, book in row['books'].items():
            kind, c = key.split(':')
            if self.legs[kind][c]['market_type'] == 'inverse':
                if kind == 'hedge':
                    inv_real[c] = inv_real.get(c, 0.0) + book['realized'] - book['fees']
                else:
                    realised += (book['realized'] - book['fees']) * prices[c]
            else:
                realised += book['realized'] - book['fees']
        coins = {c: max(min(row['coins'].get(c, 0.0) + inv_real.get(c, 0.0), wcoins[c]), 0.0)
                 for c in self.legs['spot']}
        # H8: what the planner weighs and hedges: every coin the row owns,
        # its hedge's open coin P&L included. A ratio-1 hedge of N contracts
        # covers N / mark coins exactly when the coins include that P&L —
        # left out, the book reads under-hedged after a rally and adds shorts
        # (net short), over-hedged after a fall (net long): the drift the
        # return-split audit measured (2026-10-09)
        plan_coins = {c: coins[c] + open_coin.get(c, 0.0) for c in coins}
        self._judge_borrow_rate(held, prices, now_ms)
        stack = sum(coins[c] * prices[c] for c in coins)
        self._mark_tilt(plan_coins, held, prices)
        value = stack + row['cash'] + sum(row['parked'].values()) + unreal + realised
        if row['anchor_value'] is None:
            row['anchor_value'] = value
        if 'contributed' not in row:
            # a row from before contributions were counted (the carry fleet's
            # first night, six restarts of adoptions and raises): re-anchored
            # here, once, and said — the loss counts from now
            row['anchor_value'], row['contributed'] = value, 0.0
            self.notify.event('warn', self.botid,
                              f'anchor re-set at {value:,.2f}: contributions before this build were not '
                              'counted apart from profit — the loss limit counts from now (H4)')
        basis_value = row['anchor_value'] + row['contributed']    # what the book was given
        loss = basis_value - value
        self._last_pos = stack
        self.notional_now = sum(held[k][c] * prices[c] for k in held for c in held[k])
        risk = cfg['risk']
        self._loss_now = loss if risk.get('max_loss') is not None else None
        placed = 0
        # --- H4 -----------------------------------------------------------------
        if risk.get('max_loss') is not None and loss >= risk['max_loss']:
            self._flatten(f"loss {loss:,.2f} >= max_loss {risk['max_loss']:,.2f}",
                          coins, held, prices)
            self.state.set(self.botid, row)
            return {'flattened': True}
        eq = wallet.get('equity')
        avail = wallet.get('available')
        if eq and avail is not None and avail / eq < risk['margin_floor_pct'] and self.notional_now > 0:
            share = self.cut_for_floor(avail, eq, wallet.get('im') or wallet.get('maint_margin'), risk['margin_floor_pct'])
            placed += self._delever(coins, held, prices, share)
            if cfg.get('margin'):
                # the ratchet: the row aims lower by what the floor took, so
                # the next tick does not lever back into the floor
                L = cfg['margin']['spot_leverage']
                row['lever_cap'] = (row.get('lever_cap') or L) * (1.0 - share)
            self._say_once('floor', 'margin',
                           f"free margin {avail / eq:.0%} under the floor {risk['margin_floor_pct']:.0%} "
                           f'— every leg cut by {share:.0%}, spot and its hedge together (H4)')
        for (k, c), t in perps.items():
            if k != 'hedge' or c in row['unwound']:
                continue
            pm, sm = float(t['mark'] or 0.0), prices[c]
            basis = abs(pm - sm) / sm if sm else 0.0
            if basis > risk['basis_stop_pct'] and (coins.get(c, 0.0) > 0 or held['hedge'].get(c, 0.0) > 0):
                self._unwind(c, coins, held, prices, basis)
                coins[c] = 0.0
                plan_coins[c] = 0.0
                held['hedge'][c] = 0.0
                placed += 1
        # --- H3 on the clock ----------------------------------------------------
        active = []
        for a in cfg['assets']:
            c = a['coin']
            if c in row['unwound']:
                t = perps.get(('hedge', c))
                pm = float(t['mark'] or 0.0) if t else prices[c]
                back = abs(pm - prices[c]) / prices[c] if prices[c] else 1.0
                if back < risk['basis_stop_pct'] / 2 and prices[c]:
                    # the parked cash buys its own coin back; the plan then
                    # hedges what it sees (the fill books next cycle)
                    parked = row['parked'].pop(c, 0.0)
                    del row['unwound'][c]
                    try:
                        got = self._place('spot', c, 'Buy', parked / prices[c], prices[c],
                                          f'basis back to {back:.2%}: re-entering')
                    except (VenueError, OSError) as e:
                        row['cash'] += parked          # the next tick spends it instead
                        self._say_once(f'reenter:{c}', 'warn', f'{c}: re-entry refused: {e}')
                        got = 0.0
                    coins[c] = coins.get(c, 0.0) + got
                    plan_coins[c] = plan_coins.get(c, 0.0) + got
                    row['cash'] += parked - got * prices[c]
                    placed += 1
                else:
                    continue
            active.append(a)
        plan = {'tick': False, 'orders': []}
        if active:
            all_long = sum(a['weight'] for a in cfg['assets'] if a['weight'] > 0)
            act_long = sum(a['weight'] for a in active if a['weight'] > 0)
            if act_long and act_long < all_long:
                # a parked asset's share is its parked cash; the rest keep
                # their relative shares of the stack
                scale = all_long / act_long
                active = [dict(a, weight=a['weight'] * scale) if a['weight'] > 0 else a for a in active]
            if cfg.get('margin') and row.get('lever_cap'):
                L = cfg['margin']['spot_leverage']
                due = (row['last_tick_ms'] is None
                       or now_ms - row['last_tick_ms'] >= cfg['rebalance']['every_hours'] * 3_600_000)
                if (due and row['lever_cap'] < L and eq and avail is not None
                        and not row.get('rate_blocks_relax')
                        and not row.get('yield_blocks_relax')
                        and avail / eq > risk['margin_floor_pct'] + 2 * FLOOR_BUFFER):
                    # eased back toward the file's number, a step a tick, only
                    # while free margin sits well above the floor
                    row['lever_cap'] = min(L, row['lever_cap'] * (1.0 + RELAX_STEP))
                    self.notify.event('info', self.botid,
                                      f"leverage eased to {row['lever_cap']:.2f}× of the file's {L:g}× (H4)")
                if row['lever_cap'] >= L - 1e-9:
                    row['lever_cap'] = None
                else:
                    f = row['lever_cap'] / L
                    active = [dict(a, weight=a['weight'] * f) if a['weight'] > 0 else a for a in active]
            eff = dict(cfg, assets=active)
            trailing = self._trailing_funding(now_ms)
            regimes = {c: self._regime_now(c, now_ms) for c in self.legs['hedge']}
            # H8: the planner's equity is the row's: every coin with its hedge's
            # coin P&L, and the cash with the linear legs' P&L and realised
            book = {'coins': plan_coins, 'hedged': held['hedge'], 'shorts': held['short'],
                    'cash': row['cash'] + lin_open + realised}
            plan = plan_portfolio(eff, book, prices, now_ms, row['last_tick_ms'],
                                  regimes=regimes, funding_trailing=trailing)
        if plan['tick']:
            spent, refused = 0.0, False
            # spot sells first, then spot buys, then the perps: a buy is paid
            # from the sale beside it, and the hedges follow what landed
            rank = {('spot', 'sell'): 0, ('spot', 'buy'): 1}
            for o in sorted(plan['orders'], key=lambda o: rank.get((o['leg'][0], o['side']), 2)):
                kind, c = o['leg']
                side = ('Buy' if o['side'] == 'buy' else 'Sell')
                try:
                    done = self._place(kind, c, side, o['coins'], prices[c], o['why'])
                except (VenueError, OSError) as e:
                    refused = True
                    self._say_once(f'place:{kind}:{c}', 'warn',
                                   f'{kind} {c}: {o["side"]} refused: {e} — asked again '
                                   'at the next read, not the next tick')
                    continue
                if done:
                    placed += 1
                    if kind == 'spot' and side == 'Buy':
                        spent += done * prices[c]
            row['cash'] = (row['cash'] - spent if cfg.get('margin')      # a loan stays negative
                           else max(row['cash'] - spent, 0.0))
            row['spent'] += spent
            if not refused:
                row['last_tick_ms'] = now_ms         # a refused leg keeps the tick open
        self.portfolio_view = {
            'stack': {c: {'coins': coins[c], 'value': coins[c] * prices[c]} for c in coins},
            'stack_value': stack, 'cash': row['cash'], 'parked': sum(row['parked'].values()),
            'borrowed': max(-row['cash'], 0.0),
            'leverage': (stack / (stack + row['cash'])) if stack + row['cash'] > 0 else None,
            'lever_cap': row.get('lever_cap'),
            'assets': [{'coin': a['coin'], 'weight': a['weight'],
                        'actual': (coins.get(a['coin'], 0.0) * prices[a['coin']] / stack) if stack and a['weight'] > 0 else 0.0,
                        'ratio': (cfg['hedges'].get(a['coin']) or {}).get('ratio'),
                        'hedged': held['hedge'].get(a['coin'], 0.0),
                        'short': held['short'].get(a['coin'], 0.0),
                        'regime': ((row.get('regime_seen') or {}).get(a['coin']) or [None, 0, None])[2],
                        'unwound': a['coin'] in row['unwound']} for a in cfg['assets']],
            'carry': {'total': row['funding_total'],
                      'trailing': sum(x[2] for x in row['funding'])},
            # H6: the three money lines that never mix — and the loan's cost, its own
            'total': value - basis_value,
            'tilt': row['tilt_pnl'],
            'interest': row.get('interest_total', 0.0),
            'borrow_apr': row.get('borrow_apr'),
            'basis': value - basis_value - row['funding_total'] - row['tilt_pnl'] + row.get('interest_total', 0.0),
            'unreal': unreal, 'realised': realised, 'value': value,
            'anchor': basis_value, 'contributed': row['contributed'], 'last_tick_ms': row['last_tick_ms'],
            'next_tick_ms': ((row['last_tick_ms'] or now_ms)
                             + int(cfg['rebalance']['every_hours'] * 3_600_000)),
            'delevered': row['delevered']}
        self.state.set(self.botid, row)
        return {'placed': placed, 'tick': plan['tick']} if (placed or plan['tick']) else None
