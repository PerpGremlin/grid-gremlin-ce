# The reconcile step of a cycle (the 2026-10-08 audit): the plan's diff
# against what rests, made real — amends first, then cancels, then creates
# (E2: a create never joins an order its cancel failed to remove), with the
# churn guards (B5 cooling, B6/B7 backoff) and the cross check. Split from
# `cycle` as it was; the cycle decides WHAT, this does it.
from .apply import pair_amends, rung_of
from .exchange.errors import VenueError


class ReconcileMixin:

    def _reconcile(self, to_cancel, to_create, bid, ask, now):
        """Amend, cancel, create — in that order — and return (amends,
        cancels, placed (rung, side) keys, placed exit links, skipped)."""
        cfg, adapter = self.cfg, self.adapter
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
        return amends, cancels, placed_now, placed_exit_links, skipped
