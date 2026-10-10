"""The bot's book (SPEC R2, G15, M12-M15, M24, D58): what the venue's fills say
it holds and at what cost — the fills it owns, the basis, the rungs held, how a
round ended, the spot wallet's attribution. A mixin of Bot; every attribute is Bot's."""
import time

from .apply import diff, make_botid, make_link, pair_amends, rung_of
from .config import CANDLE_SECONDS, hosts_position_stop
from .exchange.errors import VenueError
from .ladder import (SEED_RUNG, anchor_from_rung, fee_floor_for, grid_rungs,
                     guard_band, lot, min_gap, plan_grid, plan_martingale,
                     sellable_base, slide_is_adverse, slide_offset, split,
                     stop_level_for)
from .window import window
from .bot_constants import HISTORY_WINDOW_DAYS, RUNGS_LAG_CYCLES, VENUE_STOP


class BasisMixin:
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

    def _own_fills(self, days=HISTORY_WINDOW_DAYS, since_ms=None):
        """M12/M13: this bot's venue fills over the last HISTORY_WINDOW_DAYS,
        link-attributed — the exchange is the state, so scale and cooldown
        survive restarts. Bounded: an epoch-0 pull was ~3,000 requests (the
        audit's H1); 30 days is five. G23's walk asks for a short window
        first."""
        hist = getattr(self.client, 'fills_history', None)
        if hist is None:
            return []
        now_ms = int(self._now() * 1000)
        if since_ms is None:
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
        escalated = False
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
                escalated = True
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
                if self._rungs_lag and not escalated:
                    # G26, measured: how long the venue's fill list lagged
                    # the position — the log's, for the loose end's count
                    self.notify.event('net', self.botid,
                                      f'fill list caught up after {self._rungs_lag} '
                                      'cycle(s) (G26)')
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
        # D76: a stated holding is the book's start — the coins this bot
        # owned at `holding_since`, plus its own fills from that moment;
        # without one, the thirty-day walk of its fills (D58)
        anchor = self.cfg.get('holding_since_ms')
        try:
            fills = (self._own_fills(since_ms=anchor) if anchor
                     else self._own_fills())
        except (VenueError, OSError):
            prev = self._spot_seen
            return (min(wallet_size, prev[1]) if prev else wallet_size), True
        entry = self._entry_side.lower()
        own = float(self.cfg.get('holding') or 0.0) if anchor else 0.0
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
