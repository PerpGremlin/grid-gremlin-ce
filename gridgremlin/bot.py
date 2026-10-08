# The loop with its guards (SPEC E2, E3, W1, B3-B7, T2). One bot, four files
# (audit 2026-10-09): this one holds the construction, the grid cycle and its
# churn guards; bot_stops.py the stops, bot_basis.py the book, bot_round.py
# the martingale round. Mixins — every attribute is Bot's and is reset in
# __init__ (S6); nothing is private to a file.
import time

from .apply import diff, make_botid, make_link, pair_amends, rung_of
from .config import CANDLE_SECONDS, hosts_position_stop
from .exchange.errors import VenueError
from .ladder import (SEED_RUNG, anchor_from_rung, fee_floor_for, grid_rungs,
                     guard_band, lot, min_gap, plan_grid, plan_martingale,
                     sellable_base, slide_is_adverse, slide_offset, split,
                     stop_level_for)
from .window import window
from .bot_constants import (FLAT_CONFIRMATIONS, RUNGS_LAG_CYCLES, DEFER_ESCALATE_CYCLES, FLAP_LIMIT, FLAP_COOLDOWN, BACKOFF_BASE, BACKOFF_CEILING, HISTORY_WINDOW_DAYS, VENUE_STOP, STOP_RUNG)  # noqa: F401  (re-exported: the specs read them here)
from .bot_basis import BasisMixin
from .bot_round import RoundMixin
from .bot_stops import StopsMixin


class Bot(StopsMixin, BasisMixin, RoundMixin):
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
                and (cfg.get('assumed_avg_entry') is None
                     or cfg.get('holding_since_ms'))):
            # D58 — unless the row ADOPTS the wallet's coins: a stated
            # assumed_avg_entry declares them this bot's (V6); a stated
            # holding (D76) is the book's start and wins over adoption
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
