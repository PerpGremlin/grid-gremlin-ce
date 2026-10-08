"""The bot's stops (SPEC X1-X15, D47): the rules that end a round or the bot —
mark, equity and venue-held stops, the loss limit, the round and hold limits,
the flatten. A mixin of Bot; every attribute is Bot's."""
import time

from .apply import diff, make_botid, make_link, pair_amends, rung_of
from .config import CANDLE_SECONDS, hosts_position_stop
from .exchange.errors import VenueError
from .ladder import (SEED_RUNG, anchor_from_rung, fee_floor_for, grid_rungs,
                     guard_band, lot, min_gap, plan_grid, plan_martingale,
                     sellable_base, slide_is_adverse, slide_offset, split,
                     stop_level_for)
from .window import window
from .bot_constants import STOP_RUNG


class StopsMixin:
    def _kill(self, truth, reason):
        """D1/S7: cancel every owned order, stand down, never restart. X4:
        the event states what still rests. X7: tombstone FIRST."""
        if self.tombs:
            try:
                self.tombs.add(self.botid, reason)
            except OSError as e:
                self.notify.event('warn', self.botid,
                                  f'tombstone write FAILED ({e}) — killing '
                                  'anyway; this bot may revive on restart', urgent=True)
        n = 0
        for o in truth['orders']:
            if rung_of(o['link_id'], self.botid) is not None:
                try:
                    self.client.cancel_order(self.cfg['market_type'],
                                             self.cfg['symbol'], o['order_id'])
                    n += 1
                except VenueError:
                    pass
        self.alive = False
        self.notify.event('kill', self.botid,
                          f'{reason} — cancelled {n} owned orders; nothing '
                          'owned rests; position flat')

    def _stop_hit(self, truth, equity):
        """X2: the rule names what it watches. Absence is never a breach."""
        stop = self.cfg.get('stop')
        mark = truth['mark']
        if not stop or mark is None:
            return None
        watch, long = stop['watch'], self.cfg['side'] == 'long'
        if watch == 'mark_price':
            level, said = self._mark_stop_level(truth)
            if level is None:
                return None
            hit = mark <= level if long else mark >= level
            return said if hit else None
        if watch == 'account_equity':
            if equity is not None and equity <= stop['level']:
                return f"account_equity {stop['level']:.10g}"
            return None
        idx = self.adapter.position_idx(self._entry_side, False) or 0
        sl = truth['positions'].get(idx, {}).get('stop_loss')
        if not sl:
            return None
        hit = mark <= sl if long else mark >= sl
        return f'position_sl {sl:.10g} (yours, on the venue)' if hit else None

    def _mark_stop_level(self, truth):
        """The `mark_price` stop's level right now and how to say it:
        X10's percent from the round's base, X8's rungs beyond the window,
        or the absolute level. (None, None) when there is no level — a
        flat martingale has no base, and absence is never a breach."""
        stop = self.cfg['stop']
        long = self.cfg['side'] == 'long'
        if stop.get('from_base_pct') is not None:
            base = self._round_base(truth)
            if base is None:
                return None, None
            pct = stop['from_base_pct']
            level = base * (1.0 - pct if long else 1.0 + pct)
            return level, (f'mark_price {level:.10g} ({pct:.4%} from the '
                           f'base order at {base:.10g})')
        level = stop_level_for(self.cfg, self.offset)   # X8: follows the
        if stop.get('rungs_beyond') is not None:        # window
            return level, (f"mark_price {level:.10g} ({stop['rungs_beyond']}"
                           f' rungs beyond the window at {self.offset:+d})')
        return level, f'mark_price {level:.10g}'

    def _emergency_level(self, truth):
        """X12: the stop that overrides the cool-down — `emergency_pct`
        further out than the stop's own level, so it follows a slide and
        a round's base exactly as the stop does."""
        stop = self.cfg.get('stop') or {}
        e = stop.get('emergency_pct')
        if e is None:
            return None
        level, _ = self._mark_stop_level(truth)
        if level is None:
            return None
        return level * (1.0 - e if self.cfg['side'] == 'long' else 1.0 + e)

    def _round_base(self, truth):
        """X10: the price of this round's base order. The anchor while the
        process remembers it; after a restart, the venue's own account —
        the newest rung-0 entry fill. None while flat, or when the venue
        cannot say."""
        idx = self.adapter.position_idx(self._entry_side, False) or 0
        if not (truth['positions'].get(idx) or {}).get('size'):
            return None
        if self._anchor is not None:
            return self._anchor
        if self._stop_base is None:
            try:
                fills = self._own_fills()
            except (VenueError, OSError):
                return None
            entry = self._entry_side.lower()
            base = [f for f in fills
                    if str(f.get('side', '')).lower() == entry
                    and rung_of(f['link_id'], self.botid) == 0]
            if base:
                self._stop_base = max(base,
                                      key=lambda f: f['time_ms'])['price']
        return self._stop_base

    def _stop_confirmed(self, reason, now, truth):
        """The stop's cool-down (D33). X9, "Time" (3Commas' SL timeout):
        the level must stay crossed for `confirm_seconds`; a recovery
        resets the clock. X12, "Candle close" (Altrady's): only the mark
        at a `confirm_candle` boundary is compared, so a wick inside the
        candle never fires it — and the emergency level overrides either.
        Both clocks live in memory, so a restart delays the stop by at
        most one cool-down and never brings it early."""
        stop = self.cfg.get('stop') or {}
        confirm, candle = stop.get('confirm_seconds'), stop.get(
            'confirm_candle')
        if not (confirm or candle):
            return reason
        at_close = False
        if candle:
            boundary = int(now // CANDLE_SECONDS[candle])
            at_close = (self._candle_seen is not None
                        and boundary > self._candle_seen)
            self._candle_seen = boundary
        if reason:
            hard = self._emergency_level(truth)
            mark = truth['mark']
            if hard is not None and (mark <= hard
                                     if self.cfg['side'] == 'long'
                                     else mark >= hard):
                return (f'{reason}; emergency level {hard:.10g} crossed, '
                        'the cool-down is overridden')
        if candle:
            if not reason:
                self._stop_since = None
                return None
            if at_close:
                return f'{reason}, at the {candle} close'
            if self._stop_since is None:
                self._stop_since = now
                self.notify.event('warn', self.botid,
                                  f'stop level crossed ({reason}) — waiting '
                                  f'for the {candle} candle to close past '
                                  'it (X12)', urgent=True)
            return None
        if not reason:
            if self._stop_since is not None:
                self._stop_since = None
                self.notify.event('warn', self.botid,
                                  'the price recovered past the stop level '
                                  'before the timeout — the stop stands by '
                                  '(X9)', urgent=True)
            return None
        if self._stop_since is None:
            self._stop_since = now
            self.notify.event('warn', self.botid,
                              f'stop level crossed ({reason}) — it must hold '
                              f'{confirm:.0f}s before the stop fires (X9)', urgent=True)
        if now - self._stop_since < confirm:
            return None
        return f'{reason}, held {confirm:.0f}s'

    def _end_round_stop(self, truth, held, reason):
        """X11 (D42, 3Commas' "close deal"): the stop ends the ROUND, not
        the bot — closed under STOP_RUNG, so the venue remembers it."""
        return self._close_round(
            truth, held, STOP_RUNG, 'stopped', 'stop close',
            f'stop fired ({reason}): closed {abs(held):.10g} at market; '
            'the round ends, the bot does not (X11)')

    def _max_hold_reached(self, truth, held, now):
        """M19 (D44, 3Commas' maximum hold period): a round still open
        `max_hold_seconds` after its first fill closes at market, profit
        or loss. It ends the round; M5 decides what follows."""
        limit = self.cfg.get('max_hold_seconds')
        if not limit:
            return None
        t0 = self._round_started(held)
        if t0 is None or now - t0 < limit:
            return None
        return self._close_round(
            truth, held, 0, 'max_hold', 'max-hold close',
            f'max hold reached: the round has been open {(now - t0) / 3600:.2f}h '
            f'(limit {limit / 3600:.2f}h) — closed {abs(held):.10g} at '
            'market; the round ends (M19)')

    def _rounds_opened(self):
        """D41: rounds opened since `max_rounds_since`, counted from the
        venue's fills — a base-order fill opens a round, and the next one
        only counts after an exit came between (a re-quoted maker base is
        one round, not two). None when the venue cannot be read."""
        try:
            fills = self._round_fills()
        except (VenueError, OSError):
            return None
        since = self.cfg['max_rounds_since_ms']
        entry, exit_ = self._entry_side.lower(), self._exit_side.lower()
        n, open_ = 0, False
        for f in sorted(fills, key=lambda f: f['time_ms']):
            if f['time_ms'] < since:
                continue
            side = str(f.get('side', '')).lower()
            if side == exit_:
                open_ = False
            elif (side == entry and not open_
                  and rung_of(f.get('link_id'), self.botid) == 0):
                n, open_ = n + 1, True
        return n

    def _max_rounds_reached(self, truth):
        """D41 (3Commas' maximum trade iterations): after `max_rounds`
        rounds have OPENED and the last has finished, the bot stands down.
        Asked only from flat, before another round could open."""
        want = self.cfg.get('max_rounds')
        if not want:
            return None
        opened = self._rounds_opened()
        if opened is None:
            self.notify.event('warn', self.botid,
                              'max_rounds: the venue gave no fills to count '
                              'from — opening nothing until it does (D41)')
            return {'round': 'uncounted'}
        if opened < want:
            return None
        self._kill(truth, f'max_rounds reached: {opened} of {want} rounds '
                          f"opened since {self.cfg['max_rounds_since']} — "
                          'standing down (D41)')
        return {'round': 'max_rounds'}

    def _flatten_scope(self, held):
        """X6 (D2): grid inventory only — the floor core survives. A
        martingale has no floor; its scope is the whole position."""
        if self.cfg['strategy'] == 'martingale':
            return abs(held)
        return sellable_base(self.cfg, self.adapter, held)

    def _bot_result(self, truth, held, basis, now):
        """X14: what this bot has made or lost since `max_loss_since`, in
        quote money: (realised net of fees, open). Realised is walked from
        the venue's fills, average cost, one side: an exit closes what the
        walk has seen bought, and an exit of a holding older than the
        moment realises nothing here — what was lost before the moment is
        not this limit's. Open is what is held now against the venue's
        average, the older part included, so the count errs toward firing
        early. The fills are re-read when the holding changes and once a
        minute; None when the venue has never answered."""
        cache = self._loss_cache
        if cache is None or cache[1] != held or now - cache[0] >= 60.0:
            try:
                fills = self._round_fills()
            except (VenueError, OSError):
                fills = None
            if fills is not None:
                since = self.cfg['max_loss_since_ms']
                ad, sign = self.adapter, (1.0 if self.cfg['side'] == 'long'
                                          else -1.0)
                inverse = self.cfg['market_type'] == 'inverse'
                entry = self._entry_side.lower()
                qty = weight = net = 0.0     # weight: sum(q*p), or sum(q/p)
                for f in sorted(fills, key=lambda f: f['time_ms']):
                    if f['time_ms'] < since:
                        continue
                    q, p = abs(f['qty']), f['price']
                    net -= ad.pnl_to_usd(f.get('fee') or 0.0, p)
                    if str(f.get('side', '')).lower() == entry:
                        qty += q
                        weight += q / p if inverse else q * p
                        continue
                    closed = min(q, qty)
                    if closed <= 0:
                        continue
                    avg = qty / weight if inverse else weight / qty
                    net += sign * ad.pnl_to_usd(
                        ad.realised_pnl(avg, p, closed), p)
                    weight *= (qty - closed) / qty
                    qty -= closed
                # the fill list lags the position by seconds: a re-read
                # forced by a change of holding is asked again five seconds
                # later, so a fill that was not listed yet is not missed
                # for a whole minute
                changed = cache is not None and cache[1] != held
                cache = self._loss_cache = (now - 55.0 if changed else now,
                                            held, net)
        if cache is None:
            return None
        open_ = 0.0
        if held and basis and truth['mark']:
            sign = 1.0 if self.cfg['side'] == 'long' else -1.0
            open_ = sign * self.adapter.pnl_to_usd(
                self.adapter.realised_pnl(basis, truth['mark'], abs(held)),
                truth['mark'])
        return cache[2], open_

    def _max_loss_hit(self, truth, held, basis, now):
        """X14 (D47): the bot's own loss, realised and open together, has
        reached `max_loss`. Unknown is never a breach."""
        limit = self.cfg.get('max_loss')
        if not limit:
            return None
        got = self._bot_result(truth, held, basis, now)
        if got is None:
            return None
        realised, open_ = got
        self._loss_now = realised + open_      # the snapshot shows it (F4)
        if -(realised + open_) < limit:
            return None
        return (f'max_loss {limit:.10g} reached: this bot is down '
                f'{-(realised + open_):.10g} since '
                f"{self.cfg['max_loss_since']} (realised {realised:+.10g} "
                f'after fees, open {open_:+.10g})')

    def _execute_stop(self, truth, held, reason, flatten=False):
        """X1 (D1): flatten, cancel, kill, never restart. X4: the event
        states what still rests. X5: owned orders only, from paginated truth."""
        cfg, adapter = self.cfg, self.adapter
        if self.tombs:                 # X7: durable BEFORE the flatten — a
            try:                       # crash mid-stop stays dead
                self.tombs.add(self.botid, reason)
            except OSError as e:       # a broken disk must never block the
                self.notify.event('warn', self.botid,   # flatten itself (M3)
                                  f'tombstone write FAILED ({e}) — stopping '
                                  'anyway; this bot may revive on restart', urgent=True)
        leave = (not flatten and (cfg.get('stop') or {}).get('action')
                 == 'leave_position')          # X14 always closes
        qty = 0.0 if leave else self._flatten_scope(held)   # X13: by choice
        if qty > 0:
            self._gen += 1
            try:
                self.client.place_market(
                    cfg['market_type'], cfg['symbol'], self._exit_side,
                    adapter.fmt_qty(qty),
                    adapter.position_idx(self._exit_side, True) or 0,
                    reduce_only=True, link_id=self._make_link(0),
                    borrow=self._borrow)
            except (VenueError, OSError) as e:      # raw OSError too (M2)
                self.notify.event('warn', self.botid, f'flatten: {e}', urgent=True)
        floor = abs(held) - qty
        try:                           # X4 honestly: re-read, never assume the
            after = self.client.read_symbol_truth(     # flatten fully filled
                cfg['market_type'], cfg['symbol'],
                cfg.get('funding_interval_minutes', 480.0))
            idx_now = adapter.position_idx(self._entry_side, False) or 0
            left = (after['positions'].get(idx_now) or {}).get('size', 0.0)
        except Exception:                                    # noqa: BLE001
            left = None
        if leave:
            residue = (f'position {abs(held):.10g} LEFT OPEN by this row\'s '
                       'own choice (leave_position, X13) — UNPROTECTED and '
                       'yours to manage; anything the venue holds on the '
                       'position itself still rests' if held else
                       'position flat')
        elif left is None:
            residue = f'flatten SUBMITTED for {qty:.10g}; venue unreadable to confirm'
        elif left > floor + 1e-12:
            residue = (f'position {left:.10g} STILL OPEN (flatten partial?) — '
                       'look at the venue')
        elif floor > 1e-12:
            residue = f'floor core {floor:.10g} REMAINS, unprotected'
        else:
            residue = 'position flat'
        n = 0
        for o in truth['orders']:
            if rung_of(o['link_id'], self.botid) is not None:
                try:
                    self.client.cancel_order(cfg['market_type'], cfg['symbol'],
                                             o['order_id'])
                    n += 1
                except VenueError:
                    pass
        self.alive = False
        self.notify.event('kill', self.botid,
                          f'stop fired ({reason}): '
                          + ('nothing sold; ' if leave else
                             f'flattened {qty:.10g} at market; ')
                          + f'cancelled {n} owned orders; nothing owned '
                          f'rests; {residue}')

    def _maintain_server_stop(self, truth, held):
        """X3: the venue holds the stop, sized to the grid's inventory —
        level-triggered every cycle, so growth re-sizes it."""
        stop = self.cfg.get('stop')
        if not (stop and held and abs(held) > 0):
            return
        emergency = None
        if not stop.get('server_side'):
            # X12: with a cool-down the venue holds the EMERGENCY level, not
            # the stop's own — where the venue can hold one at all
            if not hosts_position_stop(self.cfg):
                return
            emergency = self._emergency_level(truth)
            if emergency is None:
                return
        qty = self._flatten_scope(held)
        if qty <= 0:
            return
        idx = self.adapter.position_idx(self._entry_side, False) or 0
        venue_sl = truth['positions'].get(idx, {}).get('stop_loss')
        want = self.adapter.round_price(      # X8: re-derived every cycle, so
            emergency if emergency is not None       # a slide re-sets it
            else stop_level_for(self.cfg, self.offset))
        partial = self._flatten_scope(held) < abs(held)
        if venue_sl is not None and abs(venue_sl - want) < 1e-9:
            if not partial:
                return                            # the venue already agrees
            # partial mode: the level agreeing says nothing about the SIZE —
            # the audit's H2: growth must re-size the venue's conditional.
            # Partial-mode set_trading_stop STACKS a new conditional per
            # call, so stale ones are cancelled before the new set.
            book = getattr(self.client, 'stop_orders', None)
            if book is not None:
                mine = [o for o in book(self.cfg['market_type'],
                                        self.cfg['symbol'])
                        if 'StopLoss' in (o.get('stopOrderType') or '')
                        and int(o.get('positionIdx') or 0) == idx]
                have = sum(float(o.get('qty') or 0) for o in mine)
                if abs(have - qty) <= max(qty * 0.001, 1e-12):
                    return                        # level AND size agree
                for o in mine:
                    try:
                        self.client.cancel_order(self.cfg['market_type'],
                                                 self.cfg['symbol'],
                                                 o['orderId'])
                    except VenueError as e:
                        if e.kind != 'gone':
                            raise
        try:
            self.client.set_trading_stop(
                self.cfg['market_type'], self.cfg['symbol'], idx,
                stop_loss=self.adapter.fmt_price(want),
                sl_size=self.adapter.fmt_qty(qty) if partial else None)
            self.notify.event('tp', self.botid,
                              ('emergency stop' if emergency is not None
                               else 'server-side stop')
                              + f' resting at {want:.10g} '
                              f'for {qty:.10g} — survives this process')
        except VenueError as e:
            self.notify.event('warn', self.botid, f'server stop: {e}', urgent=True)
