"""The martingale round (SPEC M1-M26, D23, D38, D69, D71): the base order and its
chase, the targets and tranches, the breakeven ladder, the trail, the remainder
close, the round's end. A mixin of Bot; every attribute is Bot's."""
import time

from .apply import diff, make_botid, make_link, pair_amends, rung_of
from .config import CANDLE_SECONDS, hosts_position_stop
from .exchange.errors import VenueError
from .ladder import (SEED_RUNG, anchor_from_rung, fee_floor_for, grid_rungs,
                     guard_band, lot, min_gap, plan_grid, plan_martingale,
                     sellable_base, slide_is_adverse, slide_offset, split,
                     stop_level_for)
from .window import window
from .bot_constants import FLAT_CONFIRMATIONS, HISTORY_WINDOW_DAYS, STOP_RUNG, VENUE_STOP


class RoundMixin:
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

    def _round_target(self, basis):
        """M4: from average entry, recomputed as fills deepen."""
        pct = self.cfg['take_profit_avg_pct']
        raw = basis * (1.0 + pct) if self.cfg['side'] == 'long' \
            else basis * (1.0 - pct)
        return self.adapter.round_price(raw)

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
