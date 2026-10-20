# The backtester (SPEC T3). The REAL plan_grid replayed over bars — no second
# engine to drift. Its money is the adapter's (A4): fees and funding on the
# adapter's notional, the basis by its average, P&L realised and marked in
# its settle coin and stated in USD — so an inverse row rehearses in its
# own maths rather than being refused (2026-10-08). Fills require trade-through, never touch; funding is
# modelled; the plan is computed at each bar's open, so only pre-existing
# inventory can exit within the bar (conservative by construction). Entries
# are OPTIMISTIC on coarse bars: every rung the bar trades through fills,
# where the live bot rests only the window (W1) and a fast move skips rungs
# — replay on bars no coarser than the move you are asking about (T6).
# T10: funding is the market's own settlements when given. Margin is the
# ACCOUNT's (cross), which one row's replay cannot know — and D34 buys an
# adverse slide's lots from free balance, beyond capital — so the replay
# trades as decided and only SAYS when the row, standing alone on its
# capital, would first have met the maintenance margin at a bar's worst
# price (`alone_liquidation`): a risk line, never a refusal or a stop.
# T11 (the owner: "cant we just use MMR that the exchange shows?"): given the
# account as it is now ({equity, mm}), each bar's worst price projects the
# account's MMR — (its maintenance margin + the row's) over (its equity +
# the row's P&L) — the cross-margin gauge Bybit liquidates at 100%: the
# peak, and the first bar it would have reached 100%.
# T6b: an exit placed at one bar's open and still unfilled RESTS into the
# next, as on the venue: B4 exempts it from the quote guard and W3 keeps it
# outside the window. Re-checking the guard every bar without that moved
# nearly every exit on 1-second bars (the rungs study, 2026-10-15).
# T15: the row's stop and loss limit end the replay as they end the bot (X1,
# X8, X9, X12, X13, X14), judged on the candles' prices — a mark stop on
# trade prices, said so. A touch fires inside its bar at the level (the open
# when it gapped past): that bar's entries fill down to it and its exits wait,
# the order inside a bar being unknown. A cool-down is judged on closes, in
# whole bars (ceil(confirm_seconds / bar), as G21), and the emergency level
# overrides it. The loss limit and an account_equity stop (with the account
# given) fire at the price that reaches them, after the bar's fills. A
# flatten pays the taker fee and keeps the floor core (X6); leave_position
# keeps everything, marked to the end. Nothing rests after either.
import math

from .config import CANDLE_SECONDS
from .ladder import plan_grid, slide_offset, stop_level_for
from .window import window
from .fees import BYBIT_MAKER, BYBIT_TAKER

MM_RATE = 0.005            # Bybit's base maintenance tier, linear and inverse


def backtest(cfg, adapter, bars, fee_rate=BYBIT_MAKER, funding_rate_hourly=0.0,
             bar_hours=1.0, spread_bps=1.0, funding=None, mm_rate=MM_RATE,
             account=None, entries=None, stop_fee=BYBIT_TAKER):
    events = sorted(funding or [], key=lambda e: e['t'])      # before `funding` is the sum
    long = cfg['side'] == 'long'
    sign = 1.0 if long else -1.0
    step = adapter.qty_step
    held_steps = 0            # inventory in integer qty-steps: float
    held, basis = 0.0, None   # subtract-then-floor loses a whole step
    lots = []                 # G23: the rung each held lot came from
    rung_mode = cfg.get('exit_floor', 'rung') == 'rung'
    lot_step = -1 if long else 1       # an exit at j closes the lot at j+step
    realized = fees = funding = 0.0
    trips = entry_fills = 0
    peak = max_drawdown = 0.0
    equity_curve = []
    offset, slides = 0, 0      # G17/G18: the window over the lattice
    max_held = 0.0             # the deepest inventory the run carried
    # G21 in whole bars: the trigger must still hold at the open of
    # ceil(confirm_seconds / bar) FURTHER bars — a one-bar spike never slides
    s = cfg.get('slide') or {}
    confirm_bars = math.ceil((s.get('confirm_seconds') or 0.0)
                             / (bar_hours * 3600.0))
    beyond = 0
    # T10: the risk line — futures only (spot holds its coins outright)
    margined = adapter.market_type != 'spot'
    capital = float(cfg.get('capital') or 0.0)
    alone = None
    acct = account if margined and account and account.get('equity') else None
    mmr_peak, mmr_cross = None, None
    ev = 0
    bar_ms = bar_hours * 3_600_000

    def unreal_at(price):
        return (sign * adapter.pnl_to_usd(adapter.realised_pnl(basis, price, held), price)
                if basis and held else 0.0)

    def equity_at(price):
        return capital + realized - fees - funding_paid() + unreal_at(price)

    def funding_paid():
        return funding_total[0]
    funding_total = [0.0]

    # T15: the stop, the loss limit, and what of them this replay can judge
    stop = cfg.get('stop') or {}
    watch = stop.get('watch')
    max_loss = cfg.get('max_loss')
    floor_steps = int(round((cfg.get('min_position_base') or 0.0) / step))
    not_modelled = []
    if watch == 'position_sl':
        not_modelled.append('the stop-loss you keep on the venue (position_sl)')
        watch = None
    elif watch == 'account_equity' and not acct:
        not_modelled.append('the account_equity stop (the account was not given)')
        watch = None
    confirm = stop.get('confirm_seconds')
    candle = stop.get('confirm_candle')
    need = math.ceil(confirm / (bar_hours * 3600.0)) if confirm else 0
    closes_beyond = 0
    stopped = None
    dead = False              # X1/X13: fired — nothing is placed after it

    def crossed(price, level):
        return price <= level if long else price >= level

    def reaching(fn, lo, hi):
        """The price between the open `lo` and the bar's worst `hi` where
        fn first goes <= 0 (the open itself when it already has)."""
        if fn(lo) <= 0:
            return lo
        for _ in range(60):
            mid = (lo + hi) / 2.0
            lo, hi = (mid, hi) if fn(mid) > 0 else (lo, mid)
        return hi

    def at_candle_close(bar, n_bar):
        width = CANDLE_SECONDS[candle] * 1000
        if bar_ms >= width:
            return True
        if bar.get('t') is not None:
            return (bar['t'] + bar_ms) % width == 0
        return (n_bar + 1) % round(width / bar_ms) == 0

    paused_bars = 0
    resting = frozenset()      # T6b: exit rungs left resting by the last bar
    for n_bar, bar in enumerate(bars):
        fired = None
        if not dead:
            # T14: a research gate — `entries(i, bar)` False pauses new entries for
            # the bar (exits keep working, as D56's cap); asked at the bar's open
            allow = entries is None or entries(n_bar, bar)
            paused_bars += 0 if allow else 1
            new = slide_offset(cfg, offset, bar['o'])
            if new == offset:
                beyond = 0
            else:
                beyond += 1
                if beyond > confirm_bars:
                    offset, slides, beyond = new, slides + 1, 0
            # T15: a touch fires inside the bar (no cool-down, or the
            # emergency level past one); X8: the level after the slide
            level = stop_level_for(cfg, offset) if watch == 'mark_price' else None
            touch = None
            if level is not None:
                worst = bar['l'] if long else bar['h']
                e = stop.get('emergency_pct')
                hard = None if e is None else level * (1.0 - e if long else 1.0 + e)
                for lvl, said, armed in ((level, f'mark_price {level:.10g}',
                                          not (confirm or candle)),
                                         (hard, f'emergency level {hard:.10g}'
                                          if hard else '', hard is not None)):
                    if armed and touch is None and crossed(worst, lvl):
                        touch = ((bar['o'] if crossed(bar['o'], lvl) else lvl),
                                 said, False)
            # the firing bar is cut at the stop: entries fill down to it,
            # exits wait (which came first inside the bar is unknown)
            fb = (bar if touch is None else
                  dict(bar, h=bar['o'], l=touch[0]) if long else
                  dict(bar, l=bar['o'], h=touch[0]))
            # a synthetic spread around the open feeds B3/B4: without bid/ask
            # the guard-band drops never happened and near-quote rungs filled
            # that live would skip — optimistic (audit 2026-08-07 LOW)
            half = bar['o'] * spread_bps / 20_000.0
            desired = plan_grid(cfg, adapter, bar['o'], held, basis,
                                bar['o'] - half, bar['o'] + half, resting, offset=offset,
                                held_rungs=(list(lots) if rung_mode else None))
            # T6/W1: only what the live bot would have RESTING can fill; W3: an
            # exit already resting outside the window stays
            exit_side = 'Sell' if long else 'Buy'
            inside = {id(o) for o in window(desired, bar['o'],
                                            cfg.get('place_within_pct', 0.05))}
            desired = [o for o in desired if id(o) in inside
                       or (o['side'] == exit_side and o['rung'] in resting)]
            filled = set()
            for o in desired:
                if o['side'] == ('Buy' if long else 'Sell'):        # entries
                    through = fb['l'] < o['price'] if long else fb['h'] > o['price']
                    if through and not allow:
                        continue                                     # T14: paused
                    if through:
                        basis = adapter.average_entry(basis, held, o['price'], o['qty'])
                        held_steps += int(round(o['qty'] / step))
                        held = held_steps * step
                        fees += adapter.notional(o['qty'], o['price']) * fee_rate
                        entry_fills += 1
                        lots.append(o['rung'])
                else:                                               # exits
                    through = fb['h'] > o['price'] if long else fb['l'] < o['price']
                    if through and held > 0:
                        qty_steps = min(int(round(o['qty'] / step)), held_steps)
                        qty = qty_steps * step
                        realized += adapter.pnl_to_usd(
                            adapter.realised_pnl(basis, o['price'], qty), o['price']) * sign
                        held_steps -= qty_steps
                        held = held_steps * step
                        fees += adapter.notional(qty, o['price']) * fee_rate
                        trips += 1
                        filled.add(o['rung'])
                        if lots:                       # G23: the lot this exit closed
                            want = o['rung'] + lot_step
                            lots.remove(want if want in lots
                                        else (min(lots) if long else max(lots)))
            resting = frozenset(o['rung'] for o in desired
                                if o['side'] == exit_side and o['rung'] not in filled)
            fired = touch
            if fired is None:                 # T15: the price that reaches them
                worst = bar['l'] if long else bar['h']
                found = []
                if max_loss:                                 # X14: always X1
                    def short_of_limit(p):
                        return realized - fees + unreal_at(p) + max_loss
                    if short_of_limit(worst) <= 0:
                        found.append((reaching(short_of_limit, bar['o'], worst),
                                      f'max_loss {max_loss:.10g}', True))
                if watch == 'account_equity':
                    def over_level(p):
                        return (acct['equity'] + realized - fees - funding_paid()
                                + unreal_at(p) - stop['level'])
                    if over_level(worst) <= 0:
                        found.append((reaching(over_level, bar['o'], worst),
                                      f"account_equity {stop['level']:.10g}", False))
                if found:                        # the one the price met first
                    fired = max(found) if long else min(found)
            if fired is None and level is not None and (confirm or candle):
                if candle:                                   # X12: at its close
                    if at_candle_close(bar, n_bar) and crossed(bar['c'], level):
                        fired = (bar['c'], f'mark_price {level:.10g}, at the '
                                           f'{candle} close', False)
                else:                                        # X9: held, in bars
                    closes_beyond = closes_beyond + 1 if crossed(bar['c'], level) else 0
                    if closes_beyond >= need:
                        fired = (bar['c'], f'mark_price {level:.10g}, held '
                                           f'{confirm:.0f}s', False)
            if fired is not None:
                price, reason, force = fired
                leave = not force and stop.get('action') == 'leave_position'
                if not leave and held_steps > floor_steps:   # X1, X6: the core stays
                    qty_steps = held_steps - floor_steps
                    qty = qty_steps * step
                    realized += adapter.pnl_to_usd(
                        adapter.realised_pnl(basis, price, qty), price) * sign
                    fees += adapter.notional(qty, price) * stop_fee
                    held_steps -= qty_steps
                    held = held_steps * step
                dead, resting = True, frozenset()
                stopped = {'t': bar.get('t'), 'price': price, 'reason': reason,
                           'action': 'leave_position' if leave else 'flatten',
                           'held_after': held}
        if held_steps == 0:
            held, basis, lots, resting = 0.0, None, [], frozenset()
        max_held = max(max_held, held)
        if events:                                   # T10: the market's settlements
            t0 = bar.get('t')
            while ev < len(events) and t0 is not None and events[ev]['t'] <= t0 + bar_ms:
                if events[ev]['t'] > t0 and held:
                    funding_total[0] += (sign * adapter.notional(held, bar['c'])
                                         * events[ev]['rate'])
                ev += 1
        elif held and funding_rate_hourly:
            funding_total[0] += sign * adapter.notional(held, bar['c']) * funding_rate_hourly * bar_hours
        funding = funding_total[0]
        if alone is None and margined and capital > 0 and held and basis:   # T10
            worst = bar['l'] if long else bar['h']
            def short_of(p):
                return equity_at(p) - adapter.notional(held, p) * mm_rate
            if short_of(worst) <= 0:
                lo, hi = bar['o'], worst
                if short_of(lo) <= 0:
                    price = lo                           # it opened beyond: a gap
                else:
                    for _ in range(60):
                        mid = (lo + hi) / 2.0
                        lo, hi = (mid, hi) if short_of(mid) > 0 else (lo, mid)
                    price = hi
                alone = {'t': bar.get('t'), 'price': price, 'held': held}
        if acct:                                     # T11: the account's MMR, projected
            worst = bar['l'] if long else bar['h']
            eq = acct['equity'] + realized - fees - funding_paid() + unreal_at(worst)
            mm = (acct.get('mm') or 0.0) + (adapter.notional(held, worst) * mm_rate if held else 0.0)
            mmr = mm / eq if eq > 0 else float('inf')
            mmr_peak = mmr if mmr_peak is None else max(mmr_peak, mmr)
            if mmr_cross is None and mmr >= 1.0:
                mmr_cross = {'t': bar.get('t'), 'price': worst}
        unreal = unreal_at(bar['c'])
        equity = realized - fees - funding + unreal
        equity_curve.append(equity)
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)

    return {'alone_liquidation': alone, 'paused_bars': paused_bars,
            'stopped': stopped, 'stop_not_modelled': not_modelled,
            'account_mmr': (None if not acct else
                            {'start': (acct.get('mm') or 0.0) / acct['equity'],
                             'peak': mmr_peak, 'reaches_100': mmr_cross,
                             'label': acct.get('label')}),
            'funding_modelled': bool(events) or bool(funding_rate_hourly),'grid_profit': realized, 'fees': fees, 'funding': funding,
            'net': realized - fees - funding,
            'total': equity_curve[-1] if equity_curve else 0.0,
            'trips': trips, 'entry_fills': entry_fills,
            'held': held, 'basis': basis,
            'max_drawdown': max_drawdown, 'equity_curve': equity_curve,
            'slides': slides, 'offset': offset, 'max_held': max_held}
