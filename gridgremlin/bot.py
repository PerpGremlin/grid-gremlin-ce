# The loop with its guards (SPEC E2, E3, W1, B3-B7, T2).
import time

from .apply import diff, make_botid, make_link, pair_amends, rung_of
from .config import CANDLE_SECONDS, hosts_position_stop
from .exchange.errors import VenueError
from .ladder import (SEED_RUNG, anchor_from_rung, fee_floor_for, grid_rungs,
                     guard_band, lot, min_gap, plan_grid, plan_martingale,
                     sellable_base, slide_is_adverse, slide_offset, split,
                     stop_level_for)
from .window import window

FLAT_CONFIRMATIONS = 3  # E9: consecutive flat reads before standing down
RUNGS_LAG_CYCLES = 20       # G26: cycles the exit side waits for the fill list
DEFER_ESCALATE_CYCLES = 60  # G15: withheld-exit cycles before the operator
                            # is told the cost is not reconstructable
FLAP_LIMIT = 3          # B5: strikes before a (rung, side) cools
FLAP_COOLDOWN = 60.0
BACKOFF_BASE = 30.0     # B7: margin backoff, doubling to the ceiling
BACKOFF_CEILING = 300.0
HISTORY_WINDOW_DAYS = 30    # M12/M13: the venue-practical fills lookback
VENUE_STOP = 'the venue-held stop'    # X12: how a round ended (M14)
STOP_RUNG = 99    # X11: the link rung of a stop that ends the ROUND — no
                  # safety order has it (the schedule tops out at 50), and
                  # the link check already sizes a martingale for two digits.
                  # The closing fill carries it, so the venue remembers that
                  # the round ended by its stop (the cooldown reads it)


class Bot:
    # E3/S6: the reset-on-restart list, complete and asserted by spec —
    # _last_pos (fill baseline, re-seeded first cycle), _gen (restart-unique),
    # _held_ref (re-anchors), _placed_last/_flap/_cooldown (churn guards),
    # _backoff*/_exit_links_last/_uncovered_warned/_anomaly_warned (latches),
    # _slide_since (G21's confirmation clock), _entry_since/_quoted_at (D37's
    # entry clocks — restarted at first sight of the resting base, so a
    # restart delays an expiry or a requote, never brings one early),
    # _stop_since/_candle_seen (X9/X12's cool-down clocks, the same way: a
    # restart delays the stop by at most one cool-down), _stop_base (X10:
    # re-read from the venue's fills), _loss_cache/_loss_now (X14: the same), _trail_said/_trail_best/
    # _trail_basis (M21: the trail starts again from the mark a new process
    # finds, so a restart can only loosen it by what the price gave back),
    # _round_hwm_basis (M22: the average the round's gauge belongs to),
    # _round_hwm_held (M25: the holding it last saw; a shrink asks the fills),
    # _folded (D71: the slivers folded this round, said once).
    # Everything else the bot knows
    # comes from the venue each cycle — except the two stated durable local
    # facts: `tombs` (X7) and `offset`, the slide window (G22).

    def __init__(self, cfg, adapter, client, notifier, gen_seed, clock=None,
                 tombstones=None, slide_state=None):
        self.cfg = cfg
        self.adapter = adapter
        self.client = client
        from .config import VENUE_ICONS
        from .events import VenueNotifier
        self.notify = VenueNotifier(
            notifier, VENUE_ICONS.get(cfg.get('venue'), ''))
        self.botid = make_botid(cfg['market_type'], cfg['symbol'], cfg['side'])
        self._gen = gen_seed
        self._now = clock or time.time
        self._last_pos = None
        self._placed_last = set()      # (rung, side) placed on the prior cycle
        self._flap = {}                # B5: (rung, side) -> strike count
        self._cooldown = {}            # B6: (rung, side) -> (until, cause)
        self._backoff = 0.0            # B7
        self._backoff_until = 0.0
        self._backoff_emitted = 0.0
        self._entry_side = 'Buy' if cfg['side'] == 'long' else 'Sell'
        self._exit_side = 'Sell' if cfg['side'] == 'long' else 'Buy'
        self._held_ref = None          # B2
        self.slide = slide_state       # G22: the second durable local fact
        self.offset = 0                # G17: the window, restored below
        self._slide_since = None       # G21: the confirmation clock (E3-reset)
        if slide_state is not None and cfg.get('slide'):
            want = slide_state.get(self.botid)
            m = cfg['slide']['max_rungs']
            if cfg['slide'].get('direction') == 'both':      # D34
                self.offset = max(-m, min(want, m))
            else:
                self.offset = (min(max(want, 0), m) if cfg['side'] == 'long'
                               else max(min(want, 0), -m))  # G19 on restart
            if self.offset != want:
                self.notify.event('warn', self.botid,
                                  f'persisted window offset {want:+d} is '
                                  'outside this config\'s clamp or side — '
                                  f'resuming at {self.offset:+d} (G19/G22)')
        self._min_gap = (min_gap(grid_rungs(cfg, adapter, self.offset))
                         if cfg['strategy'] == 'grid' else 0.0)   # M8: no lattice
        self.alive = True
        self._spot_seen = None         # D58: (wallet, own net) last cycle
        self._spot_lag = 0             # D58: cycles the fill list lagged
        self.capped = None             # D56: the account cap's reason, set
                                       # by the fleet each cycle; None = free
        self.notional_now = 0.0        # D56: |held| at mark, in quote
        self.margin_view = None        # V14: the venue's margin on the
                                       # position, read each cycle (public,
                                       # derived — not E3 state)
        self._exit_links_last = set()  # S7: the ownership discriminator
        self._uncovered_warned = False
        self._anomaly_warned = False
        self._anchor = None            # M: the round's base price
        self._borrow = bool(cfg.get('spot_borrow'))    # D24
        self.tombs = tombstones        # X7: the prevents-restart half of D1
        self._round = 0
        self._scale = None             # M12: reinvest factor, venue-derived
        self._cool_until = None        # M13: venue-anchored, recomputed on need
        self._unplaceable_warned = False
        self._history_capped_warned = False
        self._flat_streak = 0          # E9: confirmations of 'flat'
        self._round_hwm = None         # M10: best mark seen this round
        self._round_hwm_basis = None   # M22: ...for THIS average
        self._round_hwm_held = None    # M25: ...and the holding it last saw
        self._folded = ()              # D71: the slivers folded, said once
        self._be_level = None          # D38: the breakeven stop, round-scoped
        self._basis_cache = None       # G15: (held, basis) from fills
        self._rungs_cache = None       # G23: (held, [rung per lot]) from fills
        self._rungs_seen = None        # G26: (|held|, fill ids, newest ms) of
        self._rungs_lag = 0            # the last derivation; cycles it lagged
        self._close_streak = 0         # M14: cycles waiting for the venue's
                                       # account of a closing fill
        self._defer_cycles = 0         # G15: cycles exits were withheld
        self._entry_since = None       # D37: when this round's maker base
        self._quoted_at = None         # first rested / was last quoted
        self._stop_since = None        # X9: when the stop level was crossed
        self._candle_seen = None       # X12: the last candle boundary seen
        self._loss_cache = None        # X14: (when, held, realised net)
        self._loss_now = None          # X14: the result last judged
        self._trail_said = None        # M21: the trail level last announced
        self._trail_best = None        # M21: best mark since this average
        self._trail_basis = None       # M21: the average the trail is for
        self._round_t0 = None          # M19: the round's first fill, from
                                       # the venue; round-scoped
        self._round_rungs = set()      # M24: safety rungs filled this round
        self._round_rungs_at = None    # ...read at this holding
        self._stop_base = None         # X10: the round's base price, from
                                       # the venue when the anchor is gone

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

    def _round_started(self, held):
        """M19: when this round's first order filled, from the venue: walk
        the fills newest first, unwinding what is held back to flat. Only a
        walk that REACHES flat is an answer. The fill list lags the
        position by seconds: with this round's own base fill not yet
        listed, the walk lands on the LAST round's first fill, and the new
        round was closed the moment it opened (live, 2026-10-02). Short of
        flat the answer is None — asked again next cycle — and so it is
        when the venue cannot be read."""
        if self._round_t0 is not None:
            return self._round_t0
        try:
            fills = self._round_fills()
        except (VenueError, OSError):
            return None
        entry, exit_ = self._entry_side.lower(), self._exit_side.lower()
        pos, t0 = abs(held), None
        for f in sorted(fills, key=lambda f: f['time_ms'], reverse=True):
            if pos <= self.adapter.qty_step * 0.5:
                break
            side = str(f.get('side', '')).lower()
            if side == entry:
                pos -= abs(f['qty'])
                t0 = f['time_ms']
            elif side == exit_:
                pos += abs(f['qty'])
        if t0 is not None and pos <= self.adapter.qty_step * 0.5:
            self._round_t0 = t0 / 1000.0
        return self._round_t0

    def _rungs_filled_this_round(self, held):
        """M24: which safety rungs have filled since this round began, by
        link identity from the venue's fills. Only a tranche round asks —
        there a partial exit shrinks the holding below the ladder's
        cumulative prefix and M1's suppression would re-place a rung that
        already filled, taking the round past `max_averaging_orders` and
        the capital M2 approved (replay 2026-10-04: SO1 filled twice in
        one round). Read once per change of holding; a round's fills only
        accumulate, so the set is a union. Short of an answer (the fill
        list lagging the position, or unreadable) the set is what it was."""
        if not self.cfg.get('take_profit_tranches'):
            return frozenset()
        if self._round_rungs_at == held:
            return frozenset(self._round_rungs)
        t0 = self._round_started(held)
        if t0 is None:
            return frozenset(self._round_rungs)
        try:
            fills = self._round_fills()
        except (VenueError, OSError):
            return frozenset(self._round_rungs)
        entry = self._entry_side.lower()
        for f in fills:
            r = rung_of(f.get('link_id'), self.botid)
            if (r and f['time_ms'] >= t0 * 1000.0
                    and str(f.get('side', '')).lower() == entry):
                self._round_rungs.add(r)
        self._round_rungs_at = held
        return frozenset(self._round_rungs)

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

    def _close_round(self, truth, held, rung, result, what, said):
        """Close what the round holds at market under our own link, so M14
        reads it as our exit and M5 decides what follows. The round's
        resting exits are cancelled first (E2)."""
        cfg, adapter = self.cfg, self.adapter
        idx = adapter.position_idx(self._entry_side, False) or 0
        stale = [o['order_id'] for o in truth['orders']
                 if o['reduce_only'] and o['side'] == self._exit_side
                 and rung_of(o['link_id'], self.botid) is not None]
        if self._hosts_tp():
            # I1: only the round's own conditionals — its hosted TPs, and
            # the breakeven ladder's stop where that is on. A conditional
            # someone else placed on the symbol is never ours to cancel.
            kinds = ('TakeProfit', 'StopLoss') if cfg.get(
                'breakeven_ladder') else ('TakeProfit',)
            stale += [o['orderId'] for o in self.client.stop_orders(
                cfg['market_type'], cfg['symbol'])
                if int(o.get('positionIdx') or 0) == idx
                and any(k in (o.get('stopOrderType') or '') for k in kinds)]
        for oid in stale:
            try:
                self.client.cancel_order(cfg['market_type'], cfg['symbol'],
                                         oid)
            except VenueError as e:
                if e.kind != 'gone':
                    raise
        self._last_pos = held          # the latch: this round was open (M5)
        self._stop_since = None
        self._gen += 1
        try:
            self.client.place_market(
                cfg['market_type'], cfg['symbol'], self._exit_side,
                adapter.fmt_qty(abs(held)),
                adapter.position_idx(self._exit_side, True) or 0,
                reduce_only=True, link_id=self._make_link(rung),
                borrow=self._borrow)
        except (VenueError, OSError) as e:          # E6: may have landed
            self.notify.event('warn', self.botid,
                              f'{what} ambiguous ({e}) — the next read '
                              'reconciles (E6)')
            return {'round': result}
        self.notify.event('exit', self.botid, said, urgent=True)
        return {'round': result}

    def _cooldown_after(self, fills):
        """M13/D33: the pause the last close asks for — the stop's own
        cooldown when the newest fill carries STOP_RUNG, else the TP's."""
        scd = self.cfg.get('stop_cooldown_seconds') or 0.0
        if scd and fills:
            last = max(fills, key=lambda f: f['time_ms'])
            if (rung_of(last.get('link_id'), self.botid) == STOP_RUNG
                    or (last.get('venue_closed') and 'stoploss' in str(
                        last.get('venue_kind') or '').lower())):
                return scd, 'the stop'
        return self.cfg.get('repeat_cooldown_seconds') or 0.0, 'the TP fill'

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

    def _round_target(self, basis):
        """M4: from average entry, recomputed as fills deepen."""
        pct = self.cfg['take_profit_avg_pct']
        raw = basis * (1.0 + pct) if self.cfg['side'] == 'long' \
            else basis * (1.0 - pct)
        return self.adapter.round_price(raw)

    def _own_fills(self, days=HISTORY_WINDOW_DAYS):
        """M12/M13: this bot's venue fills over the last HISTORY_WINDOW_DAYS,
        link-attributed — the exchange is the state, so scale and cooldown
        survive restarts. Bounded: an epoch-0 pull was ~3,000 requests (the
        audit's H1); 30 days is five. G23's walk asks for a short window
        first."""
        hist = getattr(self.client, 'fills_history', None)
        if hist is None:
            return []
        now_ms = int(self._now() * 1000)
        since_ms = now_ms - days * 86_400_000
        fills = hist(self.cfg['market_type'], self.cfg['symbol'], since_ms,
                     now_ms)
        if len(fills) >= 2000 and not self._history_capped_warned:
            self._history_capped_warned = True
            self.notify.event('warn', self.botid,
                              'fill history hit the venue cap — reinvest/'
                              'cooldown are reading a truncated window')
        return [f for f in fills
                if rung_of(f['link_id'], self.botid) is not None]

    def _derive_basis(self, held):
        """G15: a venue that reports no average entry (spot: the position IS
        a wallet balance) leaves the exit floor with nothing to clear, so
        exits may rest at the very price the inventory was bought at — the
        grid churns at zero spread and pays fees both ways (measured live
        2026-08-06: 17 LTC round trips, every buy and sell at one price).
        The venue still knows: its own fill history reconstructs the cost."""
        if not held or self.adapter.reports_avg_entry:
            return None
        cached = self._basis_cache
        if cached and abs(cached[0] - held) < 1e-12:
            return cached[1]
        try:
            fills = self._own_fills()
        except (VenueError, OSError):
            # a degraded read may serve the cache — but only for the SAME
            # holding; a cached basis for a different quantity is a guess
            return (cached[1] if cached
                    and abs(cached[0] - held) < 1e-12 else None)
        # Walk NEWEST first until the fills cover the holding. Two live
        # failures forbid the obvious all-history average: the fill list
        # lags the wallet by seconds, so right after a buy the average
        # prices YESTERDAY'S inventory (an exit rested at the freshly
        # bought rung 6s later); and residue accumulates in a running
        # book, drifting the average off the true cost of what is
        # actually held. Coverage is the honesty test: if the venue's
        # account cannot explain the holding, there is no basis — refuse.
        entry = self._entry_side.lower()
        want = abs(held)
        # tolerance covers the base-coin fee shave (~0.1%/fill) plus one
        # rounding step — NEVER min_qty, which for small holdings let a
        # 17%-coverage sliver price the whole position (audit 2026-08-07)
        slack = want * 0.02 + self.adapter.qty_step
        remaining, cost, deficit = want, 0.0, 0.0
        for f in sorted(fills, key=lambda f: f['time_ms'], reverse=True):
            qty = abs(f['qty'])
            if str(f.get('side', '')).lower() != entry:
                deficit += qty              # sold: consumes older buys
                continue
            usable = qty - min(deficit, qty)
            deficit -= min(deficit, qty)
            take = min(usable, remaining)
            cost += take * f['price']
            remaining -= take
            if remaining <= slack:
                break
        if remaining > slack:
            return None                     # account incomplete: never guess
        covered = want - remaining
        basis = cost / covered if covered > 0 else None
        if basis:
            self._basis_cache = (held, basis)     # never cache a refusal
            self.notify.event('net', self.botid,
                              f'basis {basis:.10g} reconstructed from the '
                              'newest venue fills covering the holding (G15)')
        return basis

    def _held_rungs(self, held):
        """G23 (D35): WHICH rungs the held lots came from — the venue's own
        fills, newest first, every link carrying its absolute rung (G17).
        Netting is LIFO like G15's cost walk: a sell consumes the newest
        buys, which under bottom-up exits is exactly the lot that exit
        closed. Exact pairing by identity, no local state, re-derived on
        every change of the holding and on every restart (E3). When the
        account cannot cover the holding (adoption, a lagging fill list)
        the answer is None and the plan falls back to the block the
        average pins — never a guess dressed as a fact. The seed's fill
        carries SEED_RUNG, a rung no lattice has: it sets no floor and
        suppresses nothing (S3: seeded lots came from nowhere below)."""
        if not held:
            return None
        cached = self._rungs_cache
        if cached and abs(cached[0] - held) < 1e-12:
            self._rungs_lag = 0
            return cached[1]
        entry = self._entry_side.lower()
        want = abs(held)
        slack = want * 0.02 + self.adapter.qty_step
        for days in (2, HISTORY_WINDOW_DAYS):     # the newest cover almost always
            try:
                fills = self._own_fills(days)
            except (VenueError, OSError):
                return None
            if days == 2 and self._fills_lag(fills, want, entry):
                # G26: the position moved and the fill list has not caught
                # up. Covering the holding from it now names the wrong lots
                # (an exit that just filled is missing, so its lot still
                # looks held; an entry is missing, so its rung looks
                # empty). The caller places and cancels nothing this cycle.
                self._rungs_lag += 1
                if self._rungs_lag < RUNGS_LAG_CYCLES:
                    return cached[1] if cached else None
                if self._rungs_lag == RUNGS_LAG_CYCLES:
                    self.notify.event(
                        'warn', self.botid,
                        'our fills do not account for the change in the '
                        f'position after {RUNGS_LAG_CYCLES} cycles — an '
                        'outside hand or a venue close; pairing exits from '
                        'the fills there are (G26)')
            remaining, deficit, lots = want, 0.0, []
            for f in sorted(fills, key=lambda f: f['time_ms'], reverse=True):
                qty = abs(f['qty'])
                if str(f.get('side', '')).lower() != entry:
                    deficit += qty
                    continue
                usable = qty - min(deficit, qty)
                deficit -= min(deficit, qty)
                take = min(usable, remaining)
                if take > 0:
                    lots.append(rung_of(f['link_id'], self.botid))
                    remaining -= take
                if remaining <= slack:
                    break
            if remaining <= slack:
                rungs = sorted(r for r in lots if r != SEED_RUNG)
                self._rungs_cache = (held, rungs)
                self._rungs_seen = (
                    want, frozenset(self._fill_id(f) for f in fills),
                    max((f['time_ms'] for f in fills), default=0))
                self._rungs_lag = 0       # this account is the new baseline
                return rungs
        return None

    @staticmethod
    def _fill_id(f):
        return f.get('exec_id') or (f['time_ms'], f.get('side'), f['price'],
                                    f['qty'])

    def _fills_lag(self, fills, want, entry):
        """G26: since the last derivation that added up, the fills that are
        NEW must net to the change in the holding. A fill the venue has not
        listed yet shows as a change nothing explains."""
        seen = self._rungs_seen
        if seen is None:
            return False                  # first sight (a restart): no claim
        was, ids, newest = seen
        net = 0.0
        for f in fills:
            if f['time_ms'] < newest - 60_000 or self._fill_id(f) in ids:
                continue
            qty = abs(f['qty'])
            net += qty if str(f.get('side', '')).lower() == entry else -qty
        change = want - was
        return abs(net - change) > abs(change) * 0.02 + self.adapter.qty_step

    def _how_round_ended(self):
        """M14: read the venue's own account of the closing fill — our exit
        (link or hosted TP), a liquidation, or an outside hand. None means
        the venue could not tell us, and silence is never evidence."""
        try:
            fills = self._own_fills_all()
        except (VenueError, OSError):
            return None
        if fills is None:
            return 'unknowable'   # no fills surface at all: judge nothing
        # Find the fill that ACCOUNTS FOR OUR CLOSE — never merely the
        # newest fill on the symbol. Two live misattributions forbid that
        # (2026-08-06): the fill list lags the position, so 3s after a
        # hosted TP the close was not yet visible; and on a hedged symbol
        # the newest fill belonged to the OTHER side's bot. A fill is our
        # close only if it is on our exit side, recent, and either carries
        # our link or was created by the venue itself.
        fills = sorted(fills, key=lambda f: f['time_ms'], reverse=True)
        entry_side = self._entry_side.lower()
        # the closing fill must be newer than the round's own newest entry
        # — that is what separates THIS round's close from the last one's
        # (a fixed recency window broke on any cooldown longer than it)
        anchor = max((f['time_ms'] for f in fills
                      if str(f.get('side', '')).lower() == entry_side
                      and rung_of(f['link_id'], self.botid) is not None),
                     default=0)
        exit_side = self._exit_side.lower()
        for f in fills:
            if f['time_ms'] < anchor:
                break
            if str(f.get('side', '')).lower() != exit_side:
                continue
            ours = rung_of(f['link_id'], self.botid) is not None
            if not ours and f.get('link_id'):
                continue                  # another bot's fill on our symbol
            kind = str(f.get('venue_kind') or '').lower()
            if 'liquidation' in kind or 'adl' in kind:
                return 'liquidation'
            if (not ours and f.get('venue_closed') and 'stoploss' in kind
                    and self._hosts_own_stop()):
                return VENUE_STOP        # X12: our stop, fired by the venue
            if ours or f.get('venue_closed'):
                return 'exit'
            # an unlinked, user-created reduce: an outside hand — but only
            # when the round is bracketed by a visible entry. With no linked
            # entry in the window (a round older than the lookback) the fill
            # cannot be placed inside or outside the round: judge nothing.
            return 'an outside close' if anchor > 0 else None
        return None                       # no account YET — not evidence

    def _venue_stop_closed_this_round(self):
        """M22: the venue's account of a stop-loss close AFTER this round's
        base order (the newest rung-0 entry fill) — or None. Silence is
        not evidence (M14): an unreadable or absent history judges
        nothing."""
        try:
            fills = self._own_fills_all()
        except (VenueError, OSError):
            return None
        if not fills:
            return None
        entry_side, exit_side = self._entry_side.lower(), self._exit_side.lower()
        base = max((f['time_ms'] for f in fills
                    if str(f.get('side', '')).lower() == entry_side
                    and rung_of(f.get('link_id'), self.botid) == 0),
                   default=None)
        if base is None:
            return None
        for f in sorted(fills, key=lambda f: f['time_ms']):
            if f['time_ms'] < base:
                continue
            if (str(f.get('side', '')).lower() == exit_side
                    and f.get('venue_closed') and not f.get('link_id')
                    and 'stoploss' in str(f.get('venue_kind') or '').lower()):
                return f
        return None

    def _end_round_after_venue_stop(self, truth, held, idx, stop_fill):
        """M22: the round ended on the venue; close the stray at market
        under our own link (M14 reads an exit), cancel what still rests."""
        cfg, adapter = self.cfg, self.adapter
        stale = [o['order_id'] for o in truth['orders']
                 if rung_of(o['link_id'], self.botid) is not None]
        stale += [o['orderId'] for o in self.client.stop_orders(
            cfg['market_type'], cfg['symbol'])
            if int(o.get('positionIdx') or 0) == idx]
        for oid in stale:
            try:
                self.client.cancel_order(cfg['market_type'], cfg['symbol'],
                                         oid)
            except VenueError as e:
                if e.kind != 'gone':
                    raise
        self._last_pos = held
        self._gen += 1
        try:
            self.client.place_market(
                cfg['market_type'], cfg['symbol'], self._exit_side,
                adapter.fmt_qty(abs(held)),
                adapter.position_idx(self._exit_side, True) or 0,
                reduce_only=True, link_id=self._make_link(0),
                borrow=self._borrow)
        except (VenueError, OSError) as e:          # E6: may have landed
            self.notify.event('warn', self.botid,
                              f'stray close ambiguous ({e}) — the next read '
                              'reconciles (E6)')
            return {'round': 'venue_stop'}
        self.notify.event('exit', self.botid,
                          f"the venue fired this round's stop at "
                          f"{float(stop_fill['price']):.10g} and a safety "
                          f'order filled after it — closed the stray '
                          f'{abs(held):.10g} at market; the round ends, the '
                          'bot does not (M22/D38)', urgent=True)
        return {'round': 'venue_stop'}

    def _hosts_tp(self):
        """D21/D59: does the venue hold this bot's round exit as a position
        TP? A venue without the capability does not, and neither does spot
        on any venue — its exits rest as plain sells."""
        return (getattr(self.client, 'hosts_position_tp', True)
                and self.cfg['market_type'] != 'spot')

    def _hosts_own_stop(self):
        """Does this row keep a stop of its own on the venue (X3's
        server-side stop, or X12's emergency level)?"""
        stop = self.cfg.get('stop') or {}
        return bool(stop.get('server_side')
                    or (stop.get('emergency_pct') is not None
                        and hosts_position_stop(self.cfg)))

    def _own_fills_all(self):
        """Every recent fill on OUR symbol — including ones with no link
        (a liquidation carries none), which _own_fills deliberately drops."""
        hist = getattr(self.client, 'fills_history', None)
        if hist is None:
            return None       # the venue offers no account — unknowable
        now_ms = int(self._now() * 1000)
        return hist(self.cfg['market_type'], self.cfg['symbol'],
                    now_ms - 2 * 86_400_000, now_ms)

    def _round_fills(self):
        """M12/M13/R8: this bot's round history INCLUDING venue-created
        closes. A hosted TP or a liquidation carries no link — the link
        filter alone hid every close from reinvest sizing (a profitable
        bot's factor drifted DOWN on entry fees; a liquidation's loss was
        invisible — audit 2026-08-07 H1). On a hedged symbol the exit
        SIDE disambiguates whose close an unlinked fill is."""
        linked = self._own_fills()
        all_fills = self._own_fills_all()
        if not all_fills:
            return linked
        exit_side = self._exit_side.lower()
        seen = {f['time_ms'] for f in linked}
        for f in all_fills:
            if (f['time_ms'] not in seen
                    and not f.get('link_id')
                    and str(f.get('side', '')).lower() == exit_side
                    and (f.get('venue_closed') or f.get('venue_kind'))):
                linked = linked + [f]
        return sorted(linked, key=lambda f: f['time_ms'])

    def _reinvest_scale(self, fills):
        """M12: 1 + lifetime realized-net / capital, floored at 0, CAPPED at
        1.2 — the watchdog ceiling sits at cap x1.2 (F2), so auto-compound
        never outgrows its watcher; beyond +20% the owner raises capital in
        config, ceiling reviewed together (D26)."""
        from .report import apply_fill, new_book
        book = new_book()
        inverse = self.cfg['market_type'] == 'inverse'
        for f in sorted(fills, key=lambda f: f['time_ms']):
            apply_fill(book, f['side'], f['price'], f['qty'], f['fee'],
                       inverse=inverse)
        from .report import window_truncated
        if window_truncated(book, self.cfg['side']):
            # R7's honesty applied here: the window opened mid-round, so the
            # ledger holds a phantom. Scaling on it is worse than not scaling.
            self.notify.event('warn', self.botid,
                              'reinvest: the fill window opened mid-round — '
                              'holding sizes at 1.0 this round (M12)')
            return 1.0
        net = book['realized'] - book['fees']
        if inverse:
            net = self.adapter.pnl_to_usd(net, fills[-1]['price']) if fills \
                else 0.0
        return min(max(0.0, 1.0 + net / self.cfg['capital']), 1.2)

    def _round_targets(self, basis, held, mark=None):
        """M4/D23: targets from average entry; tranches share ONE position.
        A tranche the mark has already PASSED is done (filled, or owed at
        better-than-target) — it is filtered out and the remaining shares
        renormalise over what is still held, so a filled tranche is never
        re-placed below mark (the venue refuses those, correctly). An empty
        return means every target is met: the caller closes the remainder."""
        tranches = self.cfg.get('take_profit_tranches')
        if not tranches:
            return [(self._round_target(basis), abs(held))]
        adapter, long = self.adapter, self.cfg['side'] == 'long'
        sign = 1.0 if long else -1.0
        priced = [(adapter.round_price(basis * (1.0 + sign * t['at_avg_pct'])),
                   t['share']) for t in tranches]
        if mark is not None:
            # M10: "passed" must be MONOTONE within a round — measured
            # against the best mark the round has seen, not the current one.
            # Without this a fired tranche resurrects the moment price dips
            # back below it, and the conditional book churns every wobble.
            hwm = self._round_hwm
            # M22: the gauge belongs to ONE average. A safety fill lowers
            # the average and every target with it; measured against the
            # round's old high those new targets read as already passed, a
            # tranche "fired" that never did, and the breakeven ladder (D38)
            # armed above the mark and closed the round at a loss (replay,
            # 2026-10-03). A fill that moves the average starts the gauge
            # again from the mark it finds — as M21's trail does.
            if (hwm is not None and self._round_hwm_basis is not None
                    and abs(basis - self._round_hwm_basis)
                    > 1e-9 * abs(basis)):
                hwm = None
            self._round_hwm_basis = basis
            if hwm is None and self._last_pos is None and held:
                hwm = self._seed_round_hwm(held)      # D38: across a restart
            gauge = mark if hwm is None else (max(hwm, mark) if long
                                              else min(hwm, mark))
            # M25: a resting exit fills on a TRADE, and the mark can lag
            # it — HL's markPx sat under a filled TP1 for 286 cycles, so t1
            # read as unfired, the remainder re-split into two halves and
            # the half under the venue's minimum was refused every cycle
            # with no exit resting at all (live, 2026-10-05). When the
            # holding shrinks the round's own exit fills are prices it
            # reached: fold them in. A fill list still lagging the
            # position answers nothing yet — ask again next cycle.
            seen = self._round_hwm_held
            if (seen is not None and held
                    and abs(held) < abs(seen) - self.adapter.qty_step * 0.5):
                best = self._seed_round_hwm(held)
                if best is not None:
                    gauge = max(gauge, best) if long else min(gauge, best)
                    self._round_hwm_held = abs(held)
            else:
                self._round_hwm_held = abs(held)
            self._round_hwm = gauge
            # M10 retires a tranche only when the mark actually CLEARED
            # it. The guard band is a PLACEMENT deferral, applied where the
            # order is written (_maintain_partial_tps) — folding it in here
            # retired near-missed tranches unfilled and armed the trail
            # with zero profit taken, M11's bug reborn (audit 2026-08-07).
            priced = [(p, sh) for p, sh in priced
                      if (p > gauge if long else p < gauge)]
        if not priced:
            return []
        total = sum(sh for _, sh in priced)
        # M23: shares round DOWN to the lot step, so two halves of 0.017
        # are 0.008 and 0.008 and 0.001 is left with no exit of its own —
        # on a venue whose lot is bigger than the dust the round could
        # never end. The last tranche takes what the others leave — to the
        # NEAREST lot: the rest of an on-grid holding is on the grid, and
        # float subtraction puts it a hair under (3.19 - 1.59 floored to
        # 1.59 left 0.01 with no exit, replay 2026-10-04)
        out, used = [], 0.0
        for i, (p, sh) in enumerate(priced):
            if i == len(priced) - 1:
                q = adapter.nearest_qty(max(abs(held) - used, 0.0))
            else:
                q = adapter.round_qty(abs(held) * sh / total)
                used += q
            out.append((p, q))
        return self._fold_slivers(out)

    def _fold_slivers(self, targets):
        """D71: a tranche under the venue's minimum folds into its
        neighbour — the next target out, else the one before — instead of
        being asked for and refused every cycle (HL, 2026-10-05: the half
        under the minimum was refused 286 times with no exit resting). The
        holding is still covered whole; a lone tranche is left as it is,
        there being nowhere to fold it. Said once per change."""
        adapter = self.adapter
        out = [list(t) for t in targets]
        folded = []
        i = 0
        while len(out) > 1 and i < len(out):
            p, q = out[i]
            if q > 0 and adapter.meets_minimum(q, p):
                i += 1
                continue
            j = i + 1 if i + 1 < len(out) else i - 1
            out[j][1] = adapter.nearest_qty(out[j][1] + q)
            folded.append((p, q, out[j][0]))
            out.pop(i)
            if j < i:
                i = j                      # the one before may now be last
        key = tuple((p, q) for p, q, _ in folded)
        if key != self._folded:
            self._folded = key
            if folded:
                self.notify.event('tp', self.botid, '; '.join(
                    f'tranche at {p:.10g} ({q:.10g}) folded into the one at '
                    f'{to:.10g}: under the venue\'s minimum (D71)'
                    for p, q, to in folded))
        return [tuple(t) for t in out]

    def _seed_round_hwm(self, held):
        """D38/M10 across a restart: the round's best mark lived in memory,
        so a restart after a tranche filled and price fell back re-placed
        that tranche and forgot the breakeven step. The venue still knows —
        the round's own exit fills are the marks it reached. Walk NEWEST
        first, unwinding the holding back to flat (the round's start); the
        best exit price on the way is a floor under the best mark."""
        try:
            fills = self._round_fills()
        except (VenueError, OSError):
            return None                   # unreadable: today's mark, as before
        long = self.cfg['side'] == 'long'
        entry, exit_ = self._entry_side.lower(), self._exit_side.lower()
        pos, best = abs(held), None
        for f in sorted(fills, key=lambda f: f['time_ms'], reverse=True):
            if pos <= self.adapter.qty_step:
                break                     # unwound to flat: the round began
            side = str(f.get('side', '')).lower()
            if side == entry:
                pos -= abs(f['qty'])
            elif side == exit_:
                pos += abs(f['qty'])
                p = f['price']
                best = p if best is None else (max(best, p) if long
                                               else min(best, p))
        return best

    def _breakeven_level(self, basis, fired):
        """D38, 3Commas' ladder: TP1 filled -> average entry plus the fee
        floor (G6's constant: a breakeven that pays the round trip); TP n
        filled -> TP n-1's price. None before the first tranche fills."""
        if fired < 1 or basis is None:
            return None
        sign = 1.0 if self.cfg['side'] == 'long' else -1.0
        first = self.cfg.get('breakeven_offset_pct')       # D55: the owner's
        if first is None:                                  # choice, else G6's
            first = fee_floor_for(self.cfg['market_type'])  # fee-covering one
        pct = (first if fired == 1 else
               self.cfg['take_profit_tranches'][fired - 2]['at_avg_pct'])
        return self.adapter.round_price(basis * (1.0 + sign * pct))

    def _maintain_breakeven(self, truth, basis, held, idx, hosted, fired,
                            reason=None):
        """D38: the stop steps up the tranche ladder and only ever
        tightens. Venue first — Bybit's partial stop-loss, sized to what is
        still held, survives this process; on a venue that cannot host it
        the engine watches the mark itself. A fired stop ends the ROUND,
        never the bot: it is an exit, and M5 decides what follows."""
        cfg, adapter = self.cfg, self.adapter
        long = cfg['side'] == 'long'
        want = self._breakeven_level(basis, fired)
        have = self._be_level
        book = []
        if hosted:
            book = [o for o in self.client.stop_orders(cfg['market_type'],
                                                       cfg['symbol'])
                    if 'StopLoss' in (o.get('stopOrderType') or '')
                    and int(o.get('positionIdx') or 0) == idx]
            for o in book:     # a restart adopts the venue's step: the stop
                lv = float(o.get('triggerPrice') or 0)   # never loosens
                if lv > 0 and (have is None or (lv > have if long
                                                else lv < have)):
                    have = lv
        if have is not None and (want is None
                                 or (have >= want if long else have <= want)):
            want = have
        if want is None:
            return None
        if want != self._be_level:
            self.notify.event('tp', self.botid,
                              f'breakeven stop steps to {want:.10g} '
                              + (reason or f'after {fired} tranche(s) filled '
                                           '(D38)'))
        self._be_level = want
        lv_s, qty_s = adapter.fmt_price(want), adapter.fmt_qty(abs(held))
        resting = [o for o in book
                   if adapter.fmt_price(float(o.get('triggerPrice') or 0))
                   == lv_s]
        mark = truth['mark']
        through = mark is not None and (mark <= want if long else mark >= want)
        if through:
            # the round is ENDING: the latch must know it held, or a restart
            # that fires at once reads the flat as never-opened (M5/M14)
            self._last_pos = held
            if resting:
                return {'round': 'breakeven'}     # the venue's to fire
            return self._fire_breakeven(truth, held, idx, hosted, want, book)
        if not hosted:
            return None                   # bot-side: the mark is watched above
        if (len(book) == 1 and resting
                and adapter.fmt_qty(float(book[0].get('qty') or 0)) == qty_s):
            return None                   # level AND size agree
        for o in book:        # partial mode STACKS: clear before the new set
            try:
                self.client.cancel_order(cfg['market_type'], cfg['symbol'],
                                         o['orderId'])
            except VenueError as e:
                if e.kind != 'gone':
                    raise
        try:
            self.client.set_trading_stop(cfg['market_type'], cfg['symbol'],
                                         idx, stop_loss=lv_s, sl_size=qty_s)
            self.notify.event('tp', self.botid,
                              f'breakeven stop resting venue-side at '
                              f'{want:.10g} for {qty_s} — survives this '
                              'process (D38)')
        except VenueError as e:
            if e.kind != 'flat':                 # the round just closed
                self.notify.event('warn', self.botid, f'breakeven stop: {e}', urgent=True)
        return None

    def _fire_breakeven(self, truth, held, idx, hosted, level, book):
        """D38 bot-side: the mark crossed the step. The round's resting
        exits are cancelled first (E2), then what is still held closes at
        market under our own link — M14 reads it as our exit."""
        cfg, adapter = self.cfg, self.adapter
        stale = [o['order_id'] for o in truth['orders']
                 if o['reduce_only'] and o['side'] == self._exit_side
                 and rung_of(o['link_id'], self.botid) == 0]
        if hosted:
            stale += [o['orderId'] for o in self.client.stop_orders(
                cfg['market_type'], cfg['symbol'])
                if int(o.get('positionIdx') or 0) == idx
                and 'TakeProfit' in (o.get('stopOrderType') or '')]
            stale += [o['orderId'] for o in book]
        for oid in stale:
            try:
                self.client.cancel_order(cfg['market_type'], cfg['symbol'],
                                         oid)
            except VenueError as e:
                if e.kind != 'gone':
                    raise
        self._gen += 1
        try:
            self.client.place_market(
                cfg['market_type'], cfg['symbol'], self._exit_side,
                adapter.fmt_qty(abs(held)),
                adapter.position_idx(self._exit_side, True) or 0,
                reduce_only=True, link_id=self._make_link(0),
                borrow=self._borrow)
        except (VenueError, OSError) as e:          # E6: may have landed
            self.notify.event('warn', self.botid,
                              f'breakeven close ambiguous ({e}) — the next '
                              'read reconciles (E6)')
            return {'round': 'breakeven'}
        self.notify.event('tp', self.botid,
                          f'breakeven stop {level:.10g} crossed — closed the '
                          f'remaining {abs(held):.10g} at market; the round '
                          'ends, the bot does not (D38)', urgent=True)
        return {'round': 'breakeven'}

    def _exits_cover(self, truth, held, idx, hosted):
        """M3: is the position already covered by exits resting on the
        venue? Hosted venues answer from the conditional book, others from
        our own rung-0 reduce-only orders."""
        want = abs(held)
        if want <= 0:
            return want, 0.0
        if hosted:
            book = getattr(self.client, 'stop_orders', None)
            if book is None:
                return bool(truth['positions'].get(idx, {}).get('take_profit'))
            resting = sum(
                float(o.get('qty') or 0)
                for o in book(self.cfg['market_type'], self.cfg['symbol'])
                if 'TakeProfit' in (o.get('stopOrderType') or '')
                and int(o.get('positionIdx') or 0) == idx)
            # ...and our own resting exit: the remainder close below is a
            # plain reduce-only limit, not a conditional. Left uncounted it
            # was placed again every cycle (found by the rehearsal,
            # 2026-10-03: a tranche fills, then a safety order does)
            resting += sum(o['qty'] for o in truth['orders']
                           if o['reduce_only'] and o['side'] == self._exit_side
                           and rung_of(o['link_id'], self.botid) == 0)
        else:
            resting = sum(o['qty'] for o in truth['orders']
                          if o['reduce_only'] and o['side'] == self._exit_side
                          and rung_of(o['link_id'], self.botid) == 0)
        # the venue rounds our shares, so a step of slack is expected —
        # returns (want, resting) so the remainder close can place ONLY
        # the uncovered part (audit 2026-08-07 MED: it stacked abs(held)
        # on top of partial exits and the refusals were silently eaten)
        return want, resting

    def _close_remainder_at_best(self, uncovered, basis):
        """M3 for a blown-through tranche round: every target already met —
        close what remains UNCOVERED, marketable at the DEEPEST target
        (fills at target or better). Partially-resting exits keep their
        queue; only the gap is placed."""
        cfg, adapter = self.cfg, self.adapter
        long = cfg['side'] == 'long'
        sign = 1.0 if long else -1.0
        prices = [adapter.round_price(basis * (1.0 + sign * t['at_avg_pct']))
                  for t in cfg['take_profit_tranches']]
        best = max(prices) if long else min(prices)
        self._gen += 1
        self.client.place_order(
            cfg['market_type'], cfg['symbol'], self._exit_side,
            adapter.fmt_qty(uncovered), adapter.fmt_price(best),
            self._make_link(0),
            adapter.position_idx(self._exit_side, True) or 0,
            reduce_only=True, post_only=False, borrow=self._borrow)
        self.notify.event('tp', self.botid,
                          f'every tranche target met — closing the remainder '
                          f'at {best:.10g} or better')

    def _maintain_partial_tps(self, truth, targets, idx):
        """D23 hosted: tranche TPs live on the venue's conditional book —
        level-triggered, re-anchored whenever the average moves."""
        cfg, adapter = self.cfg, self.adapter
        long = cfg['side'] == 'long'
        mark, guard = truth['mark'], guard_band(truth['bid'], truth['ask'])

        def clear(p):     # B3 for the hosted TP: too close to mark right
            return (mark is None       # now -> defer the WRITE, not the round
                    or (p > mark + guard if long else p < mark - guard))
        want = {(adapter.fmt_price(p), adapter.fmt_qty(q))
                for p, q in targets if q > 0}
        have = {}
        for o in self.client.stop_orders(cfg['market_type'], cfg['symbol']):
            if int(o.get('positionIdx') or 0) != idx:
                continue                  # not ours to touch (I1's spirit, H3)
            if 'TakeProfit' in (o.get('stopOrderType') or ''):
                key = (adapter.fmt_price(float(o.get('triggerPrice') or 0)),
                       adapter.fmt_qty(float(o.get('qty') or 0)))
                have[key] = o
        for key, o in have.items():
            if key not in want:
                try:
                    self.client.cancel_order(cfg['market_type'], cfg['symbol'],
                                             o['orderId'])
                except VenueError as e:
                    if e.kind != 'gone':
                        raise
        placed, refused = 0, None
        for p, q in targets:
            key = (adapter.fmt_price(p), adapter.fmt_qty(q))
            if q <= 0 or key in have or not clear(p):
                continue
            try:
                self.client.set_trading_stop(
                    cfg['market_type'], cfg['symbol'], idx,
                    take_profit=adapter.fmt_price(p),
                    tp_size=adapter.fmt_qty(q))
            except VenueError as e:
                # D71: one refused tranche must not leave the others
                # unwritten this cycle — write the rest, then say it
                if e.kind == 'flat':
                    raise
                refused = refused or e
                continue
            placed += 1
        if placed:
            self.notify.event('tp', self.botid,
                              f'{placed} tranche TP(s) resting venue-side')
        if refused:
            raise refused

    def _maintain_resting_exits(self, truth, targets):
        """D23 on the hostless venue: the tranche ladder IS several D21
        exits — rung 0, reduce-only, diff-shielded, adopted by identity."""
        cfg, adapter = self.cfg, self.adapter
        want = {(adapter.fmt_price(p), adapter.fmt_qty(q))
                for p, q in targets if q > 0}
        have = {}
        for o in truth['orders']:
            if (o['reduce_only'] and o['side'] == self._exit_side
                    and rung_of(o['link_id'], self.botid) == 0):
                have[(adapter.fmt_price(o['price']),
                      adapter.fmt_qty(o['qty']))] = o
        for key, o in have.items():
            if key not in want:
                try:
                    self.client.cancel_order(cfg['market_type'], cfg['symbol'],
                                             o['order_id'])
                except VenueError as e:
                    if e.kind != 'gone':
                        raise
        placed, refused = 0, None
        for p, q in targets:
            key = (adapter.fmt_price(p), adapter.fmt_qty(q))
            if q <= 0 or key in have:
                continue
            self._gen += 1
            try:
                self.client.place_order(
                    cfg['market_type'], cfg['symbol'], self._exit_side,
                    adapter.fmt_qty(q), adapter.fmt_price(p),
                    self._make_link(0),
                    adapter.position_idx(self._exit_side, True) or 0,
                    reduce_only=True, post_only=False, borrow=self._borrow)
            except VenueError as e:
                # D71: one refused exit must not leave the others unwritten
                # this cycle — write the rest, then say it
                if e.kind == 'flat':
                    raise
                refused = refused or e
                continue
            placed += 1
        if placed:
            self.notify.event('tp', self.botid,
                              f'{placed} tranche exit(s) resting')
        if refused:
            raise refused

    def _maintain_trailing(self, truth, basis, held, idx, armed=True):
        """D23: trailing rides the venue or does not exist. Set once per
        round; the venue moves it from there. M11: with tranches, it arms
        only AFTER the first target fills — a trail tighter than the first
        tranche closes the round before it can ever take profit (measured
        live 2026-08-06: 30 rounds averaging a small loss)."""
        pct = self.cfg.get('trailing_stop_pct')
        if not pct or not held or basis is None or not armed:
            return None
        long = self.cfg['side'] == 'long'
        act = self.cfg.get('trailing_activation_pct')
        active = (None if act is None else self.adapter.round_price(
            basis * (1.0 + act if long else 1.0 - act)))
        dist = self.adapter.round_price(basis * pct)
        if not self._hosts_tp():
            return self._trail_bot_side(truth, basis, held, dist,
                                        active)                  # M21
        if truth['positions'].get(idx, {}).get('trailing_stop'):
            return None
        try:
            extra = ({} if active is None else
                     {'active_price': self.adapter.fmt_price(active)})
            self.client.set_trading_stop(
                self.cfg['market_type'], self.cfg['symbol'], idx,
                trailing_stop=self.adapter.fmt_price(dist), **extra)
            self.notify.event('tp', self.botid,
                              f'trailing stop riding the venue, {dist:.10g} '
                              'behind'
                              + ('' if active is None else
                                 f', armed from {active:.10g}'))
        except VenueError as e:
            self.notify.event('warn', self.botid, f'trailing: {e}', urgent=True)
        return None

    def _trail_bot_side(self, truth, basis, held, dist, active):
        """M21 (D31): where the venue hosts no trailing stop the engine
        carries one — a fixed distance behind the best mark since it was
        armed. "No activation, no stop": with an activation price nothing
        trails until the mark has reached it. The trail belongs to ONE
        average: when a fill moves the average the trail starts again from
        the mark it finds, because a best price from before the position
        was averaged down sits above the new activation and would close
        the round at once, at a loss (found in rehearsal, 2026-10-03). The
        best mark is never remembered across a restart (E3): a new process
        trails from the mark it finds, or, with tranches, from the round's
        best exit fill. A plain stop is judged first each cycle, so it
        wins a tie. Firing closes the round at market: an exit, and M5
        decides."""
        long = self.cfg['side'] == 'long'
        mark = truth['mark']
        if self._trail_basis != basis:              # a new average: start over
            seed = None
            if (self._trail_basis is None and self._last_pos is None
                    and self.cfg.get('take_profit_tranches')):
                seed = self._seed_round_hwm(held)   # across a restart
            self._trail_basis, self._trail_best = basis, seed
            self._trail_said = None
        best = self._trail_best
        best = mark if best is None else (max(best, mark) if long
                                          else min(best, mark))
        self._trail_best = best
        if active is not None and (best < active if long else best > active):
            return None                             # no activation, no stop
        level = best - dist if long else best + dist
        if self._trail_said != level:
            first = self._trail_said is None
            self._trail_said = level
            if first:
                self.notify.event('tp', self.botid,
                                  f'trailing stop armed bot-side: {dist:.10g} '
                                  f'behind the best price, now {level:.10g} '
                                  '(M21)')
        if (mark > level) if long else (mark < level):
            return None
        return self._close_round(
            truth, held, 0, 'trailing', 'trailing close',
            f'trailing stop {level:.10g} crossed ({dist:.10g} behind the '
            f'best price {best:.10g}) — closed {abs(held):.10g} at market; '
            'the round ends (M21)')

    def _martingale_round(self, truth, held, basis):
        """M3/M5/M6. Returns a dict to end the cycle early, None to continue
        to the ladder plan."""
        cfg, adapter = self.cfg, self.adapter
        idx = adapter.position_idx(self._entry_side, False) or 0
        if held == 0:
            # D37: a resting maker base is a round STARTING, not the
            # leftovers of one that finished — a restart mid-entry with
            # repeat off read it as 'complete' and killed the bot
            base = self._base_order(truth)
            completed = ((self._last_pos and abs(self._last_pos) > 0)
                         or (self._last_pos is None and any(
                             rung_of(o['link_id'], self.botid) is not None
                             and o is not base for o in truth['orders'])))
            if completed and self._last_pos:
                # M14: a round that ended by LIQUIDATION or by the operator's
                # own hand is not a completed round — re-entering there walks
                # straight back into what just killed it. Ask the venue how
                # the position actually closed.
                how = self._how_round_ended()
                if how is None:
                    # the fill list lags the position by seconds — the
                    # account of the close usually arrives on the next read
                    self._close_streak += 1
                    if self._close_streak < FLAT_CONFIRMATIONS:
                        self.notify.event(
                            'warn', self.botid,
                            'round ended, but the venue has no account of '
                            'the closing fill yet — confirming '
                            f'({self._close_streak}/{FLAT_CONFIRMATIONS}) '
                            'before judging (M14/E9)')
                        return {'confirming_close': self._close_streak}
                    if self._close_streak == FLAT_CONFIRMATIONS:
                        self.notify.event(
                            'warn', self.botid,
                            'round ended and the venue STILL has no account '
                            'of the closing fill — holding this round open, '
                            'not judging; a kill on silence cancels real '
                            'orders on a maybe (M14/E9, audit 2026-08-07)', urgent=True)
                    return {'round': 'unaccounted'}
                self._close_streak = 0
                if how == VENUE_STOP and (cfg['stop'].get('action')
                                          == 'end_round'):
                    how = 'exit'      # X11: this stop ends rounds, not bots
                if how not in ('exit', 'unknowable'):
                    self._kill(truth, f'round ended by {how}, not by our exit '
                                      '— standing down (M14/D1)')
                    return {'round': how}
            if completed:
                if not cfg['repeat']:
                    self._kill(truth, 'round complete (TP hit), repeat off')
                    return {'round': 'complete'}
                done = self._max_rounds_reached(truth)       # D41
                if done:
                    return done
                self._round += 1
                self._anchor = None
                self._round_hwm = None          # M10: round-scoped
                self._round_hwm_basis = None    # M22: and its average
                self._round_hwm_held = None     # M25: and its holding
                self._be_level = None           # D38: so is the ladder
                self._folded = ()               # D71: and the folds
                self._stop_since = self._stop_base = None    # X9/X10 too
                self._round_t0 = None                        # and M19
                self._round_rungs = set()                    # and M24
                self._round_rungs_at = None
                self._trail_said = None                      # and M21:
                self._trail_best = self._trail_basis = None  # round-scoped
                self.notify.event('repeat', self.botid,
                                  f'round {self._round + 1} re-anchors at '
                                  'market (M5: from flat only)')
                # ONE venue read answers both cooldown and reinvest (H1),
                # then the completion latch clears so none of this re-runs
                # on the next flat cycle (H4a)
                if (cfg.get('repeat_cooldown_seconds') or cfg.get('reinvest')
                        or cfg.get('stop_cooldown_seconds')):
                    fills = self._round_fills()   # H1: closes carry no link
                    cd, after = self._cooldown_after(fills)
                    if cd and fills:
                        self._cool_until = (max(f['time_ms'] for f in fills)
                                            / 1000.0 + cd)
                        if self._now() < self._cool_until:
                            self.notify.event(
                                'repeat', self.botid,
                                f'cooling {cd:.0f}s from {after} '
                                '(M13, venue-anchored)')
                    elif not cd:
                        self._cool_until = None
                    if cfg.get('reinvest'):
                        scale = self._reinvest_scale(fills)
                        if self._scale != scale:
                            self._scale = scale
                            if abs(scale - 1.0) > 1e-9:
                                self.notify.event(
                                    'repeat', self.botid,
                                    f'reinvest: sizes x{scale:.4g} (M12, '
                                    f'last {HISTORY_WINDOW_DAYS}d of venue '
                                    'fills)')
                self._last_pos = 0.0             # the completion latch (H4a)
                # E2 across rounds (H4b): the closed round's safety ladder is
                # cancelled BEFORE any new base fires — this cycle cleans,
                # the next one opens
                stale = [o for o in truth['orders']
                         if rung_of(o['link_id'], self.botid) is not None]
                if stale:
                    for o in stale:
                        try:
                            self.client.cancel_order(cfg['market_type'],
                                                     cfg['symbol'],
                                                     o['order_id'])
                        except VenueError as e:
                            if e.kind != 'gone':
                                raise
                    return {'round': 'cleanup'}
            if ((cfg.get('repeat_cooldown_seconds')
                 or cfg.get('stop_cooldown_seconds'))
                    and self._cool_until is None and self._last_pos is None):
                # restart during a cooldown: re-derive the anchor from the
                # venue once — a first-ever start has no fills and skips this
                fills = self._round_fills()   # H1: closes carry no link
                cd, _ = self._cooldown_after(fills)
                self._cool_until = ((max(f['time_ms'] for f in fills)
                                     / 1000.0 + cd) if fills else 0.0)
            if self._cool_until and self._now() < self._cool_until:
                return {'round': 'cooling'}
            if cfg.get('reinvest') and self._scale is None:
                self._scale = self._reinvest_scale(self._round_fills())
            # M12: 0.0 is a REAL factor (capital fully lost), not "unset" —
            # truthiness here re-entered at full size after a total loss.
            scale = (self._scale if (cfg.get('reinvest')
                                     and self._scale is not None) else 1.0)
            if cfg.get('reinvest') and scale <= 0.0:
                if not self._unplaceable_warned:
                    self._unplaceable_warned = True
                    self.notify.event(
                        'warn', self.botid,
                        'reinvest: realised losses have consumed the capital '
                        '— refusing to open another round (M12)', urgent=True)
                return {'round': 'capital_exhausted'}
            if self._last_pos is None:
                # M14 across a restart (audit 2026-08-07 H2): a liquidation
                # while the process was down left no tombstone — the fill
                # history is the only witness. Ask before re-entering.
                if self._how_round_ended() == 'liquidation':
                    self._kill(truth,
                               'last round ended by liquidation while this '
                               'process was down — standing down (M14/D1)')
                    return {'round': 'liquidation'}
            if base is not None:
                return self._chase_base(truth, base, idx)
            if self._last_pos is None:
                # D41 across a restart: the count is the venue's, so a
                # process that came back flat asks before it opens
                done = self._max_rounds_reached(truth)
                if done:
                    return done
            if self._entry_expired(truth):
                return {'round': 'expired'}
            if self.capped:                       # D56: the account is full;
                return {'round': 'capped'}        # the next round waits
            qty = adapter.round_qty(cfg['base_order_size'] * scale
                                    / truth['mark'])
            if qty <= 0 or not adapter.meets_minimum(qty, truth['mark']):
                if not self._unplaceable_warned:         # once, not once/sec
                    self._unplaceable_warned = True
                    self.notify.event('warn', self.botid,
                                      'base order below minimum', urgent=True)
                return {'round': 'unplaceable'}
            self._unplaceable_warned = False
            if cfg['start_order_type'] == 'maker':
                return self._quote_base(truth, qty, idx)
            self._gen += 1
            try:
                self.client.place_market(cfg['market_type'], cfg['symbol'],
                                         self._entry_side,
                                         adapter.fmt_qty(qty), idx,
                                         link_id=self._make_link(0),
                                         borrow=self._borrow)
            except (VenueError, OSError) as e:      # E6: may have landed
                self._anchor = truth['mark']
                self._last_pos = 0.0
                self.notify.event('warn', self.botid,
                                  f'base order ambiguous ({e}) — assuming '
                                  'placed; the next read reconciles (E6)')
                return {'round': 'ambiguous'}
            self._anchor = truth['mark']
            self.notify.event('start', self.botid,
                              f'round {self._round + 1}: base '
                              f'{self._entry_side} {qty:.10g} at market')
            self._last_pos = 0.0
            return {'round_started': self._round + 1}

        # holding: the round is never without a venue-resting exit
        # (M3/D21/D23 — tranches are the same law, split into shares)
        hosted = self._hosts_tp()
        if hosted and self._be_level is not None:
            # M22: the venue's own stop fires in price order — a breakeven
            # stop above a resting safety order closes the position, then
            # the safety fills a moment later, and the position is never
            # flat for M5 to see. The venue's fills are the evidence: a
            # stop-loss close after this round's base order means the
            # round ENDED there; what is held now is a stray that no exit
            # covers. Close it, cancel the rest, and let M5 decide.
            stray = self._venue_stop_closed_this_round()
            if stray:
                return self._end_round_after_venue_stop(truth, held, idx,
                                                        stray)
        act = cfg.get('breakeven_activation_pct')
        if act is not None and basis is not None and held:
            # D69, v2's activation: the stop arms once the round is this far
            # in profit, whatever the take-profit's shape, at the ladder's
            # first step (D55's offset, else G6's floor); armed, it only
            # tightens — the latch is _be_level, or the venue's own row
            is_long = cfg['side'] == 'long'
            mark = truth['mark']
            armed = self._be_level is not None or (
                mark is not None and (mark >= basis * (1.0 + act) if is_long
                                      else mark <= basis * (1.0 - act)))
            if armed:
                try:
                    out = self._maintain_breakeven(
                        truth, basis, held, idx, hosted, 1,
                        reason=f'— the round is {act:.2%} in profit (D69)')
                except VenueError as e:
                    out = None
                    if e.kind != 'flat':         # the round just closed
                        self.notify.event('warn', self.botid,
                                          f'breakeven stop: {e}', urgent=True)
                if out:
                    return out
        if self.cfg.get('take_profit_tranches'):
            targets = self._round_targets(basis, held, truth['mark'])
            # M11: a tranche has fired iff fewer targets remain than configured
            fired = len(targets) < len(self.cfg['take_profit_tranches'])
            trailed = self._maintain_trailing(truth, basis, held, idx,
                                              armed=fired)
            if trailed:
                return trailed                       # M21: the round ends
            if cfg.get('breakeven_ladder') and targets:
                try:
                    out = self._maintain_breakeven(
                        truth, basis, held, idx, hosted,
                        len(self.cfg['take_profit_tranches']) - len(targets))
                except VenueError as e:
                    out = None
                    if e.kind != 'flat':         # the round just closed
                        self.notify.event('warn', self.botid,
                                          f'breakeven stop: {e}', urgent=True)
                if out:
                    return out
            try:
                if not targets:
                    # M3 asks for a venue-resting exit, not for a NEW one.
                    # Once the high-water has passed every tranche, the
                    # exits placed earlier are still resting and will fill —
                    # adding another reduce-only order on top is refused for
                    # capacity (110017) and warns every cycle forever.
                    want, resting = self._exits_cover(truth, held, idx,
                                                      hosted)
                    slack = max(self.adapter.qty_step, want * 1e-6)
                    if resting < want - slack:
                        self._close_remainder_at_best(
                            self.adapter.round_qty(want - resting), basis)
                        self._last_pos = held      # seen: say a fill once
                        return {'round': 'closing'}
                    return None
                if hosted:
                    self._maintain_partial_tps(truth, targets, idx)
                else:
                    self._maintain_resting_exits(truth, targets)
            except VenueError as e:
                if e.kind == 'ro_capacity':
                    # the venue already holds what we asked for — quiet,
                    # but ONCE per episode it is worth a line: a partially
                    # covered position retrying forever was invisible
                    # (audit 2026-08-07 MED)
                    if not self._uncovered_warned:
                        self._uncovered_warned = True
                        self.notify.event('warn', self.botid,
                                          f'tp refused for capacity — '
                                          f'checking coverage next cycle '
                                          f'({e})')
                elif e.kind != 'flat':           # the round just closed
                    self.notify.event('warn', self.botid, f'tp: {e}', urgent=True)
            return None
        trailed = self._maintain_trailing(truth, basis, held, idx)
        if trailed:
            return trailed                           # M21: the round ends
        targets = self._round_targets(basis, held)
        target = targets[0][0]
        tp_order = None
        if hosted:
            venue_tp = truth['positions'].get(idx, {}).get('take_profit')
        else:
            tp_order = next(
                (o for o in truth['orders']
                 if o['reduce_only'] and o['side'] == self._exit_side
                 and rung_of(o['link_id'], self.botid) == 0), None)
            venue_tp = tp_order['price'] if tp_order else None
        through = (truth['mark'] >= target if cfg['side'] == 'long'
                   else truth['mark'] <= target)
        if venue_tp is None and through:
            self._gen += 1
            link = self._make_link(0)
            self.client.place_order(
                cfg['market_type'], cfg['symbol'], self._exit_side,
                adapter.fmt_qty(abs(held)), adapter.fmt_price(target), link,
                adapter.position_idx(self._exit_side, True) or 0,
                reduce_only=True, post_only=False,     # marketable: target or better
                borrow=self._borrow)
            self.notify.event('tp', self.botid,
                              f'target {target:.10g} already met — closing the '
                              'round at target or better')
            return {'round': 'closing'}
        grew = self._last_pos is not None and abs(held) > abs(self._last_pos)
        if venue_tp is None or grew:
            try:
                if hosted:
                    self.client.set_trading_stop(
                        cfg['market_type'], cfg['symbol'], idx,
                        take_profit=adapter.fmt_price(target))
                else:                        # D21: the venue-resting exit
                    if tp_order is not None:
                        try:
                            self.client.cancel_order(cfg['market_type'],
                                                     cfg['symbol'],
                                                     tp_order['order_id'])
                        except VenueError as e:
                            if e.kind != 'gone':
                                raise
                    self._gen += 1
                    self.client.place_order(
                        cfg['market_type'], cfg['symbol'], self._exit_side,
                        adapter.fmt_qty(abs(held)), adapter.fmt_price(target),
                        self._make_link(0),
                        adapter.position_idx(self._exit_side, True) or 0,
                        reduce_only=True, post_only=False, borrow=self._borrow)
                if venue_tp is None:
                    self.notify.event('tp', self.botid,
                                      f'round TP resting: {target:.10g}')
            except VenueError as e:
                if e.kind != 'flat':             # the round just closed
                    self.notify.event('warn', self.botid, f'tp: {e}', urgent=True)
        return None

    def _base_order(self, truth):
        """D37: the maker base rests as the entry side's rung 0 — safety
        orders start at rung 1, and the round exit (D21) is reduce-only."""
        if self.cfg.get('start_order_type') != 'maker':
            return None
        return next((o for o in truth['orders']
                     if o['side'] == self._entry_side and not o['reduce_only']
                     and rung_of(o['link_id'], self.botid) == 0), None)

    def _near_side(self, truth):
        """D37: the best bid for a long, the best ask for a short — the
        price a post-only entry can rest at without crossing."""
        return self.adapter.round_price(
            truth['bid'] if self.cfg['side'] == 'long' else truth['ask'])

    def _entry_expired(self, truth):
        """D37: a base that never fills stands the bot down — Altrady's
        entry expiration, ledger item (n). Flat only: a partial fill is a
        round, and a round ends by its exit or its stop (D1)."""
        ex = self.cfg.get('start_order_expire_seconds')
        if not ex or self._entry_since is None:
            return False
        if self._now() - self._entry_since < ex:
            return False
        self._kill(truth, f'base order unfilled after {ex:g}s — the entry '
                          'expired (D37)')
        return True

    def _quote_base(self, truth, qty, idx):
        """D37: the base rests post-only at the near side of the book, so
        it fills as maker. A post-only refusal (the book moved into it) is
        retried next cycle."""
        cfg, adapter, now = self.cfg, self.adapter, self._now()
        price = self._near_side(truth)
        self._gen += 1
        try:
            self.client.place_order(cfg['market_type'], cfg['symbol'],
                                    self._entry_side, adapter.fmt_qty(qty),
                                    adapter.fmt_price(price),
                                    self._make_link(0), idx,
                                    reduce_only=False, post_only=True,
                                    borrow=self._borrow)
        except VenueError as e:
            if e.kind != 'post_only_reject':
                self.notify.event('warn', self.botid, f'base order: {e}')
            return {'round': 'entering'}
        self._anchor, self._quoted_at = price, now
        self._last_pos = 0.0
        if self._entry_since is not None:    # vanished without a fill
            self.notify.event('placed', self.botid,
                              f'base re-rested: {self._entry_side} '
                              f'{qty:.10g} at {price:.10g} (D37)')
            return {'round': 'requoted'}
        self._entry_since = now
        self.notify.event('start', self.botid,
                          f'round {self._round + 1}: base '
                          f'{self._entry_side} {qty:.10g} resting at '
                          f'{price:.10g}, maker (D37)')
        return {'round_started': self._round + 1}

    def _chase_base(self, truth, base, idx, held=0.0):
        """D37: a resting base keeps its queue place while it is the best
        price; once it has rested `start_order_requote_seconds` and the book
        has moved away, it is cancelled and re-rested at the new near side
        for what is still unfilled. The cancel is confirmed before the new
        order (E2) — 'gone' means it filled or vanished, and the next read
        says which."""
        cfg, adapter, now = self.cfg, self.adapter, self._now()
        if self._entry_since is None:    # a restart: the clocks start at
            self._entry_since = now      # first sight of the resting base
        if self._quoted_at is None:
            self._quoted_at = now
        if self._anchor is None:         # M15: the venue holds the anchor
            self._anchor = base['price']
        if not held:
            self._last_pos = 0.0         # a round is opening (M14 asked once)
            if self._entry_expired(truth):
                return {'round': 'expired'}
        price = self._near_side(truth)
        if (now - self._quoted_at < cfg['start_order_requote_seconds']
                or base['price'] == price):
            return {'round': 'entering'}
        try:
            self.client.cancel_order(cfg['market_type'], cfg['symbol'],
                                     base['order_id'])
        except VenueError as e:
            if e.kind != 'gone':
                self.notify.event('warn', self.botid, f'base requote: {e}')
            return {'round': 'entering'}
        left = adapter.round_qty(base['qty'] - (base['cum_exec_qty'] or 0.0))
        if left <= 0 or not adapter.meets_minimum(left, price):
            return {'round': 'entering'}  # the remainder is dust: base done
        self._gen += 1
        try:
            self.client.place_order(cfg['market_type'], cfg['symbol'],
                                    self._entry_side, adapter.fmt_qty(left),
                                    adapter.fmt_price(price),
                                    self._make_link(0), idx,
                                    reduce_only=False, post_only=True,
                                    borrow=self._borrow)
        except VenueError as e:
            if e.kind != 'post_only_reject':
                self.notify.event('warn', self.botid, f'base requote: {e}')
            return {'round': 'entering'}  # flat: re-quoted whole next cycle
        self._anchor, self._quoted_at = price, now
        self.notify.event('placed', self.botid,
                          f'base re-quoted: {self._entry_side} {left:.10g} '
                          f'at {price:.10g} (D37)')
        return {'round': 'requoted'}

    def _maybe_seed(self, truth, held, ref):
        """D9/S2/S3: first cycle, flat, no owned orders resting — market-buy
        one lot per exit-side rung. Observable as done from the venue alone."""
        if not self.cfg.get('seed') or held != 0 or self._last_pos is not None:
            return False
        if self.capped:                                 # D56: no new exposure
            return False
        if any(rung_of(o['link_id'], self.botid) is not None
               for o in truth['orders']):
            return False
        rungs = grid_rungs(self.cfg, self.adapter, self.offset)
        exit_rungs = split(self.cfg['side'], rungs, ref)['exits']
        qty = self.adapter.round_qty(
            lot(self.cfg, self.adapter, ref) * len(exit_rungs))
        if qty <= 0 or not self.adapter.meets_minimum(qty, ref):
            return False
        idx = self.adapter.position_idx(self._entry_side, False) or 0
        self._gen += 1
        try:
            self.client.place_market(self.cfg['market_type'],
                                     self.cfg['symbol'], self._entry_side,
                                     self.adapter.fmt_qty(qty), idx,
                                     link_id=self._make_link(SEED_RUNG),
                                     borrow=self._borrow)
        except (VenueError, OSError) as e:
            # E6: the write may have landed. Treating it as done is the SAFE
            # direction here — a re-fired seed doubles the ladder, while a
            # lost seed is visible as an uncovered position next cycle.
            self.notify.event('warn', self.botid,
                              f'seed ambiguous ({e}) — assuming placed; the '
                              'next truth read reconciles (E6)')
            return True
        self.notify.event('seed', self.botid,
                          f'{self._entry_side} {qty:.10g} at market for '
                          f'{len(exit_rungs)} exit rungs')
        return True

    def _make_link(self, rung):
        mk = getattr(self.client, 'make_link', None)
        return mk(self.botid, rung, self._gen) if mk \
            else make_link(self.botid, rung, self._gen)

    def _maybe_slide(self, ref, now):
        """G18/G21/G22: the ratchet — confirmed, then durable, then moved.
        The trigger must hold on every cycle for `confirm_seconds`; a ref
        back inside resets the clock (one wick slid an ETH window for good
        in the control replay). The offset is written BEFORE any order
        moves; the planner reads self.offset from here on, so this same
        cycle cancels what left the window and places what entered it —
        the overlap keeps its identity (G17)."""
        cfg = self.cfg
        if not cfg.get('slide') or cfg['strategy'] != 'grid':
            return
        new = slide_offset(cfg, self.offset, ref)
        if new == self.offset:
            self._slide_since = None
            return
        confirm = cfg['slide']['confirm_seconds']
        if self._slide_since is None:
            self._slide_since = now
            if confirm > 0:
                self.notify.event('slide', self.botid,
                                  f'ref {ref:.10g} sits past the trigger — '
                                  f'confirming for {confirm:.0f}s before the '
                                  'window moves (G21)')
        if now - self._slide_since < confirm:
            return
        if self.slide is not None:
            try:
                self.slide.set(self.botid, new)
            except OSError as e:
                self.notify.event('warn', self.botid,
                                  f'slide state write FAILED ({e}) — sliding '
                                  'anyway; a restart resumes at home (G22)', urgent=True)
        old, self.offset, self._slide_since = self.offset, new, None
        rungs = grid_rungs(cfg, self.adapter, new)
        self._min_gap = min_gap(rungs)
        stop = cfg.get('stop') or {}
        tail = ''
        if stop.get('rungs_beyond') is not None:
            tail = f'; stop follows to {stop_level_for(cfg, new):.10g}'
        if slide_is_adverse(cfg, old, new):
            # D34: the new far rungs are NEW lots, bought from the account's
            # free balance beyond the ladder's capital — said at the move
            tail += ('; ADVERSE slide (D34): the new rungs buy beyond '
                     'capital from free balance')
        self.notify.event('slide', self.botid,
                          f'window {old:+d} -> {new:+d} rungs from home: '
                          f'{rungs[0]:.10g}..{rungs[-1]:.10g}{tail}')

    def _sticky(self, ref):
        """B2: the split ref moves only past the band, then snaps to current.
        Zero band is identical to unset."""
        frac = self.cfg.get('split_hysteresis_rungs') or 0.0
        if frac <= 0:
            return ref
        if (self._held_ref is None
                or abs(ref - self._held_ref) > self._min_gap * frac):
            self._held_ref = ref
        return self._held_ref

    def _spot_own_holding(self, wallet_size):
        """D58: a spot bot owns only its own coins. The wallet's balance of
        the coin is shared — an inverse bot settles its profit there, dust
        rests there, the operator may hold some — so the bot holds the
        SMALLER of its own fills (entries less exits, by link, I1) and the
        wallet: coins above its own are not its; coins missing from the
        wallet are gone whoever took them, and D1 judges that as ever. The
        one gap is our BUY filled and not yet listed — the wallet rose,
        our fills did not — and a rise of half our smallest lot that the
        listed fills do not explain (a settlement is a thousandth of a lot)
        means nothing is placed or cancelled until it is listed (G26's
        lesson: a filled order neither resting nor listed is re-bought).
        Past RUNGS_LAG_CYCLES the rise is said once as coins from an outside
        hand, which are not ours. Returns (held, lagging)."""
        try:
            fills = self._own_fills()
        except (VenueError, OSError):
            prev = self._spot_seen
            return (min(wallet_size, prev[1]) if prev else wallet_size), True
        entry = self._entry_side.lower()
        own = 0.0
        for f in fills:
            q = abs(f['qty'])
            own += q if str(f.get('side', '')).lower() == entry else -q
        own = max(own, 0.0)
        step = max(self.adapter.min_qty, self.adapter.qty_step)
        half_lot = max(step, 0.5 * min(
            (o['qty'] for o in (getattr(self, '_last_desired', None) or [])),
            default=step))
        held = min(wallet_size, own)
        if held < self.adapter.min_qty:
            held = 0.0                       # fee shavings are not a holding
        prev = self._spot_seen
        self._spot_seen = (wallet_size, own)
        if prev is None:
            return held, False
        rose = (wallet_size - prev[0]) - (own - prev[1])
        if rose >= half_lot:
            self._spot_lag += 1
            if self._spot_lag < RUNGS_LAG_CYCLES:
                self._spot_seen = prev       # judge against the same base
                return held, True
            self.notify.event('warn', self.botid,
                              f'the wallet gained {rose:.10g} that our own '
                              f'fills do not explain after {RUNGS_LAG_CYCLES} '
                              'cycles — coins from an outside hand, not this '
                              "bot's; trading on from its own (D58)", urgent=True)
        self._spot_lag = 0
        return held, False

    def _held(self, truth):
        idx = self.adapter.position_idx(self._entry_side, False) or 0
        pos = truth['positions'].get(idx)
        if pos and pos['side'] and pos['side'] != self._entry_side:
            return None, None              # S4: a position we cannot explain
        return (pos['size'] if pos else 0.0), (pos['avg_entry'] if pos else None)

    def _would_cross(self, order, bid, ask):
        """B3/G13: one band, imported — nothing rests near the opposite quote."""
        if bid is None or ask is None:
            return False
        guard = guard_band(bid, ask)
        if order['side'] == 'Buy':
            return order['price'] >= ask - guard
        return order['price'] <= bid + guard

    def _cooling(self, key, now):
        entry = self._cooldown.get(key)
        if not entry:
            return False
        if now >= entry[0]:
            del self._cooldown[key]
            return False
        return True

    def _do_backoff(self, now):
        if now > self._backoff_until + BACKOFF_CEILING:
            self._backoff = 0.0            # quiet spell: the schedule restarts
        self._backoff = min(max(BACKOFF_BASE, self._backoff * 2.0),
                            BACKOFF_CEILING)
        self._backoff_until = now + self._backoff
        if self._backoff > self._backoff_emitted:
            self._backoff_emitted = self._backoff
            self.notify.event('backoff', self.botid,
                              f'margin: growth halted {self._backoff:.0f}s')

    def _account_flaps(self, resting_keys, pos_stable, now):
        """B5: placed-but-not-resting while the position held still is a book
        race; a rung whose position moved is trading and is never cooled."""
        for key in self._placed_last:
            if key in resting_keys or not pos_stable:
                self._flap.pop(key, None)
                continue
            strikes = self._flap.get(key, 0) + 1
            self._flap[key] = strikes
            if strikes >= FLAP_LIMIT:
                self._cooldown[key] = (now + FLAP_COOLDOWN, 'flap')   # B6
                self._flap.pop(key)
                self.notify.event('backoff', self.botid,
                                  f'rung {key[0]} {key[1]} flapping: '
                                  f'cooling {FLAP_COOLDOWN:.0f}s')

    def cycle(self, equity=None):
        if not self.alive:
            return None
        cfg, adapter, now = self.cfg, self.adapter, self._now()
        truth = self.client.read_symbol_truth(
            cfg['market_type'], cfg['symbol'],
            cfg.get('funding_interval_minutes', 480.0))
        if cfg['market_type'] == 'spot' and cfg['strategy'] == 'martingale':
            # D59: spot has no reduce-only — our sells ARE the round's
            # exits; say so in the shape every exit path reads
            for o in truth['orders']:
                if (o['side'] == self._exit_side
                        and rung_of(o['link_id'], self.botid) is not None):
                    o['reduce_only'] = True
        held, basis = self._held(truth)
        spot_lag = False
        if (cfg['market_type'] == 'spot' and held is not None
                and cfg.get('assumed_avg_entry') is None):
            # D58 — unless the row ADOPTS the wallet's coins: a stated
            # assumed_avg_entry declares them this bot's (V6)
            held, spot_lag = self._spot_own_holding(held)
        mark = truth.get('mark') or 0.0
        q = abs(held or 0.0)                 # D56: what this bot carries
        self.notional_now = (q if adapter.market_type == 'inverse'
                             else q * mark)
        # V14: what the venue says the position costs — carried for the
        # snapshot and the card, never used to decide anything
        pv = truth['positions'].get(
            adapter.position_idx(self._entry_side, False) or 0) or {}
        self.margin_view = ({'im': pv.get('position_im'),
                             'mm': pv.get('position_mm'),
                             'leverage': pv.get('leverage'),
                             # V17: the venue's own liquidation price
                             'liq': pv.get('liq_price')}
                            if pv.get('size') else None)
        if held is None:                           # S4: halt and alert
            if not self._anomaly_warned:
                self._anomaly_warned = True
                self.notify.event('warn', self.botid,
                                  'position on our index has the WRONG side — '
                                  'halting this bot until an operator looks', urgent=True)
            return {'anomaly': True}
        if basis is None:              # a venue-reported basis overrules the
            # G15: the config's stated cost first (V6, from v2), then the
            # venue's own fill history — never nothing, or the exit floor is
            # inert and a spot grid exits at the very rung it bought (36
            # zero-spread round trips live before this call was WIRED; the
            # function existed unwired — B8's failure mode in G15's coat).
            basis = cfg.get('assumed_avg_entry') or self._derive_basis(held)
        # G15: holding with no reconstructable cost — the wallet moved
        # before the fill list did (it lags by seconds). An exit priced
        # blind is how zero-spread churn happens; withhold exits and let
        # the account arrive. Escalate only if it never does.
        defer_exits = (basis is None and bool(held)
                       and not self.adapter.reports_avg_entry)

        reason = self._stop_confirmed(                  # X1: before everything
            self._stop_hit(truth, equity), now, truth)
        if reason:
            if (cfg['stop'].get('action') == 'end_round' and held
                    and abs(held) > 0):
                return self._end_round_stop(truth, held, reason)   # X11
            self._execute_stop(truth, held, reason)
            return None
        if cfg.get('max_loss'):                                    # X14
            reason = self._max_loss_hit(truth, held, basis, now)
            if reason:
                self._execute_stop(truth, held, reason, flatten=True)
                return None
        if (cfg['strategy'] == 'martingale' and held and abs(held) > 0
                and cfg.get('max_hold_seconds')):
            done = self._max_hold_reached(truth, held, now)        # M19
            if done:
                return done
        self._maintain_server_stop(truth, held)

        pos_stable = self._last_pos is not None and held == self._last_pos

        if spot_lag:
            # D58: our own market fill is in flight — the wallet has the
            # coins, the fill list not yet. Seen as flat, a DCA bot would
            # open its round AGAIN and a grid would seed again (live
            # 2026-10-05: the spot DCA's base bought twice). Nothing moves
            # until the fill is listed; stops above have already been judged.
            return {'lagging': 'own fill in flight (D58)'}

        if self._maybe_seed(truth, held, truth['split_ref']):
            self._last_pos = 0.0                   # the fill lands next cycle
            return {'seeded': True}

        if self._last_pos is not None and held != self._last_pos:
            grew = abs(held) > abs(self._last_pos)
            self.notify.event('fill' if grew else 'exit', self.botid,
                              f'position {self._last_pos:.10g} -> {held:.10g}')

        if cfg['strategy'] == 'martingale':
            early = self._martingale_round(truth, held, basis)
            if early is not None:
                return early
            base = self._base_order(truth)
            if base is not None:     # D37: a partial base fill holds its TP
                self._last_pos = held          # (M3) and the safety ladder
                return self._chase_base(       # waits for the rest
                    truth, base,
                    self.adapter.position_idx(self._entry_side, False) or 0,
                    held)
            self._entry_since = self._quoted_at = None    # the base is done
        elif (self._last_pos and abs(self._last_pos) > 0 and held == 0):
            links_now = {o['link_id'] for o in truth['orders']}
            if self._exit_links_last - links_now:
                # fast path: one of our exit links vanished — but a link
                # vanishes the same way when WE cancelled it in the last
                # replace, and an outside flatten hiding behind that
                # coincidence re-entered as a benign trip (audit
                # 2026-08-07 MED). One fills question closes the blind
                # side; None (lag) passes as a trip — the next flat
                # without vanished links gets the full confirm path.
                how = self._how_round_ended()
                if how in ('liquidation', 'an outside close', VENUE_STOP):
                    self._kill(truth, f'position closed by {how} (D1)')
                    return None
            if not (self._exit_links_last - links_now):      # no exit of ours
                # E9: a venue that answers an EMPTY position list (under load,
                # or on an account-type mismatch) is indistinguishable from
                # flat — and this path is irreversible. Confirm across
                # consecutive reads before killing.
                self._flat_streak += 1
                if self._flat_streak < FLAT_CONFIRMATIONS:
                    self.notify.event(
                        'warn', self.botid,
                        f'position reads flat but our exits still rest — '
                        f'confirming ({self._flat_streak}/'
                        f'{FLAT_CONFIRMATIONS}) before standing down (E9)')
                    return {'confirming_flat': self._flat_streak}
                # M14's law, extended to grids: absence of a link proves
                # nothing — a link vanishes the same way whether it FILLED
                # or we CANCELLED it in the last replace. Ask the venue how
                # the position actually closed before doing anything
                # irreversible (live 2026-08-06: a bot's own exit fill read
                # as an outside hand; tombstoned mid-session, healthy).
                how = self._how_round_ended()
                if how == 'exit':
                    self._flat_streak = 0          # our exit filled: a trip
                elif how is None and self._flat_streak < 2 * FLAT_CONFIRMATIONS:
                    # the fill list lags the wallet by seconds — keep asking
                    self.notify.event(
                        'warn', self.botid,
                        'flat, but the venue has no account of the closing '
                        f'fill yet — waiting ({self._flat_streak}/'
                        f'{2 * FLAT_CONFIRMATIONS}) (E9/M14)')
                    return {'confirming_flat': self._flat_streak}
                else:
                    if how in (None, 'unknowable'):
                        how = ('an unaccounted hand — the venue '
                               + ('gave no account of the closing fill'
                                  if how is None else
                                  'offers no fill history'))
                    self._kill(truth, f'position closed by {how} (D1)')
                    return None
        if held:
            self._flat_streak = 0
            self._close_streak = 0
        else:
            self._basis_cache = None   # a cached cost describes a holding
            self._rungs_cache = None
            self._rungs_lag = 0        # G26: the baseline stays — the fills
                                       # since it still net to the change
                                       # that no longer exists (H2 2026-08-07)

        ref = self._sticky(truth['split_ref'])     # W2: the one anchor
        self._maybe_slide(ref, now)                # G18/G21/G22
        bid, ask = truth['bid'], truth['ask']
        resting_exits = {rung_of(o['link_id'], self.botid)
                         for o in truth['orders']
                         if o['side'] == self._exit_side
                         and rung_of(o['link_id'], self.botid) is not None}
        orders_view = truth['orders']
        if cfg['strategy'] == 'martingale':
            # D21: rung 0 on the exit side is the round's exit — shielded
            # from the ladder's diff. On a venue that hosts the TP it is the
            # remainder close (M3), and the diff cancelling it every cycle
            # was the other half of the same churn
            orders_view = [o for o in orders_view
                           if not (o['reduce_only']
                                   and o['side'] == self._exit_side
                                   and rung_of(o['link_id'], self.botid) == 0)]
        lagging = False
        if cfg['strategy'] == 'martingale':
            if cfg.get('reinvest') and self._scale is None:
                self._scale = self._reinvest_scale(self._round_fills())
            if self._anchor is None:
                # M15: a restart mid-round must NOT re-anchor on the average
                # entry — that deepens every remaining rung and un-suppresses
                # rungs that already filled, pushing the position past the
                # capital the validator approved. The venue still holds the
                # answer: any resting safety order inverts to the anchor.
                for o in truth['orders']:
                    r = rung_of(o['link_id'], self.botid)
                    if r and not o['reduce_only']:
                        found = anchor_from_rung(cfg, o['price'], r)
                        if found:
                            self._anchor = adapter.round_price(found)
                            self.notify.event(
                                'repeat', self.botid,
                                f'round anchor recovered from the venue: '
                                f'{self._anchor:.10g} (M15)')
                            break
            if (self._anchor is None and held
                    and abs(held) > 0):
                # M15's worst case: the deepest round — every safety
                # filled, nothing resting to invert, and the fallback
                # anchor (average entry) is the exact re-anchoring M15
                # forbids: it deepens rungs past validated capital. Hold
                # what we hold, keep the exits alive, place no new
                # safeties (audit 2026-08-07 MED).
                if not self._unplaceable_warned:
                    self._unplaceable_warned = True
                    self.notify.event(
                        'warn', self.botid,
                        'restarted in the deepest round: no resting '
                        'safety to recover the anchor from — placing no '
                        'new safeties; exits maintained (M15)')
                desired = []
            else:
                desired = plan_martingale(
                    cfg, adapter, self._anchor or basis or ref,
                    ref, held,
                    scale=(self._scale
                           if cfg.get('reinvest')
                           and self._scale is not None
                           else 1.0),
                    filled_rungs=self._rungs_filled_this_round(held))
        else:
            held_rungs = (self._held_rungs(held)
                          if cfg.get('exit_floor', 'rung') == 'rung' else None)
            lagging = 0 < self._rungs_lag < RUNGS_LAG_CYCLES      # G26
            desired = plan_grid(cfg, adapter, ref, held, basis, bid, ask,
                                resting_exits, offset=self.offset,
                                held_rungs=held_rungs)
        if self.capped:
            # D56: the account is at its cap — no order that ADDS exposure
            # rests; exits keep working, so the cap is reached and left by
            # the bots' own selling, never by a forced close
            desired = [d for d in desired
                       if d['side'] == self._exit_side or d.get('reduce_only')]
        if defer_exits:
            # freeze the exit side: place nothing new (the plan priced them
            # off a basis we do not have) and cancel nothing resting (they
            # were priced off a basis we DID have — tearing them down on
            # every fills-lag window cost queue position and left the
            # holding uncovered, audit 2026-08-07 H5)
            desired = [d for d in desired if d['side'] != self._exit_side]
            self._defer_cycles += 1
            if self._defer_cycles == DEFER_ESCALATE_CYCLES:
                self.notify.event(
                    'warn', self.botid,
                    'holding with no reconstructable cost — no venue fills '
                    'cover the holding and no assumed_avg_entry is set; '
                    'exits withheld (G15). State assumed_avg_entry to trade '
                    'this inventory.', urgent=True)
        else:
            self._defer_cycles = 0
        live = window(desired, ref, cfg['place_within_pct'])          # W1
        # V15: the snapshot says what rests and what waits for the price to
        # come within the window — a wide grid rests one order and looks
        # broken to anyone who does not know W1 (owner, 2026-10-04)
        live_keys = {(o['rung'], o['side']) for o in live}
        waiting = [o for o in desired if (o['rung'], o['side']) not in live_keys]
        self.orders_view = {
            'within_pct': cfg['place_within_pct'],
            'resting': {'buys': sum(o['side'] == 'Buy' for o in live),
                        'sells': sum(o['side'] == 'Sell' for o in live)},
            'waiting': {'buys': sum(o['side'] == 'Buy' for o in waiting),
                        'sells': sum(o['side'] == 'Sell' for o in waiting),
                        'nearest': (min((o['price'] for o in waiting),
                                        key=lambda p: abs(p - ref))
                                    if waiting and ref else None)}}
        self._last_desired = [d for d in desired
                              if d['side'] == self._entry_side] or desired
        if spot_lag:
            lagging = True                   # D58: our fill is in flight
        to_cancel, _ = diff(desired, orders_view, self.botid)         # full
        if defer_exits:
            to_cancel = [o for o in to_cancel
                         if o['side'] != self._exit_side]
        _, to_create = diff(live, orders_view, self.botid)            # windowed
        if lagging:
            # G26: the plan above was drawn from an account that does not
            # add up — WHICH lots are held is unknown on both sides (a
            # missing exit fill re-places that exit; a missing entry fill
            # re-buys that rung). Nothing is placed, nothing cancelled,
            # until the fills account for the position: seconds, usually.
            to_cancel, to_create = [], []
        amends, cancels, creates = pair_amends(to_cancel, to_create, self.botid)

        for order, want in amends:
            try:
                self.client.amend_order(cfg['market_type'], cfg['symbol'],
                                        order['order_id'],
                                        adapter.fmt_qty(want['qty']))
                self.notify.event('amend', self.botid,
                                  f"{want['side']}@{want['price']:.10g} "
                                  f"qty -> {want['qty']:.10g}")
            except VenueError as e:
                if e.kind not in ('gone', 'not_modified'):
                    self.notify.event('warn', self.botid, f'amend: {e}')

        uncancelled = set()
        for order in cancels:                       # E2: cancels before creates
            try:
                self.client.cancel_order(cfg['market_type'], cfg['symbol'],
                                         order['order_id'])
                self.notify.event('cancel', self.botid,
                                  f"{order['side']}@{order['price']:.10g}")
            except VenueError as e:
                if e.kind != 'gone':
                    # E2 is a CONDITION, not a sequence: the old order still
                    # rests, so its replacement must not join it — that is
                    # how two full-size sells shared one wallet (audit
                    # 2026-08-07 H3). The rung retries whole next cycle.
                    uncancelled.add((rung_of(order['link_id'], self.botid),
                                     order['side']))
                    self.notify.event('warn', self.botid, f'cancel: {e}')

        placed_now, placed_exit_links, skipped = set(), set(), 0
        if now < self._backoff_until:               # B7: growth only is halted
            creates, skipped = [], len(creates)
        for want in creates:
            key = (want['rung'], want['side'])
            if key in uncancelled:
                skipped += 1
                continue
            if self._cooling(key, now) or self._would_cross(want, bid, ask):
                self.notify.event('skip', self.botid,
                                  f"{want['side']}@{want['price']:.10g}")
                skipped += 1
                continue
            self._gen += 1
            link = self._make_link(want['rung'])
            idx = adapter.position_idx(want['side'], want['reduce_only']) or 0
            try:
                self.client.place_order(
                    cfg['market_type'], cfg['symbol'], want['side'],
                    adapter.fmt_qty(want['qty']), adapter.fmt_price(want['price']),
                    link, idx, want['reduce_only'], borrow=self._borrow)
                placed_now.add(key)
                if want['side'] == self._exit_side:
                    placed_exit_links.add(link)
                self.notify.event('placed', self.botid,
                                  f"{want['side']}@{want['price']:.10g} "
                                  f"x {want['qty']:.10g}")
            except VenueError as e:
                if e.kind == 'margin':   # account-level: B7's backoff, never
                    self.notify.event('margin', self.botid, str(e))
                    self._do_backoff(now)              # a rung-flap matter
                    break
                # rung-level failure: an ATTEMPT — placed-but-not-resting
                # strikes the flap next cycle (B5), so a rung that fails
                # repeatedly COOLS instead of warning once per cycle (the
                # 170037 incident: ~1500 warns before the switch was found)
                placed_now.add(key)
                if e.kind not in ('ro_capacity', 'post_only_reject'):
                    self.notify.event('warn', self.botid, f'place: {e}')

        sellable = held and abs(held) > 0 and cfg['strategy'] == 'grid'
        has_exits = any(o['side'] == self._exit_side for o in desired)
        if sellable and not has_exits and not defer_exits:   # S5: warned once
            # two causes, two names (the old text asserted one cause it
            # never verified): a sub-minimum partial-fill sliver is routine
            # and self-resolves in seconds — log-only; a basis beyond the
            # range is the operator's to resolve — page once.
            sliver = not self.adapter.meets_minimum(
                abs(held), truth['mark'] or 0.0)
            if sliver:
                self.notify.event('net', self.botid,
                                  f'holding {abs(held):.10g} — below the '
                                  'venue minimum, unharvestable until the '
                                  'fill completes (S5)')
            elif not self._uncovered_warned:
                self._uncovered_warned = True
                self.notify.event('warn', self.botid,
                                  'holding, but nothing harvestable — basis '
                                  'beyond the range; position left to you', urgent=True)
        else:
            self._uncovered_warned = False

        resting_keys = {(rung_of(o['link_id'], self.botid), o['side'])
                        for o in truth['orders']}
        self._account_flaps(resting_keys, pos_stable, now)
        self._placed_last = placed_now
        self._exit_links_last = placed_exit_links | {
            o['link_id'] for o in truth['orders']
            if o['side'] == self._exit_side
            and rung_of(o['link_id'], self.botid) is not None}
        self._last_pos = held
        return {'desired': len(desired), 'live': len(live),
                'amends': len(amends), 'cancels': len(cancels),
                'creates': len(placed_now), 'skips': skipped}
