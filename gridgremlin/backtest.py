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
import math

from .ladder import plan_grid, slide_offset
from .window import window
from .fees import BYBIT_MAKER

MM_RATE = 0.005            # Bybit's base maintenance tier, linear and inverse


def backtest(cfg, adapter, bars, fee_rate=BYBIT_MAKER, funding_rate_hourly=0.0,
             bar_hours=1.0, spread_bps=1.0, funding=None, mm_rate=MM_RATE,
             account=None):
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

    for bar in bars:
        new = slide_offset(cfg, offset, bar['o'])
        if new == offset:
            beyond = 0
        else:
            beyond += 1
            if beyond > confirm_bars:
                offset, slides, beyond = new, slides + 1, 0
        # a synthetic spread around the open feeds B3/B4: without bid/ask
        # the guard-band drops never happened and near-quote rungs filled
        # that live would skip — optimistic (audit 2026-08-07 LOW)
        half = bar['o'] * spread_bps / 20_000.0
        desired = plan_grid(cfg, adapter, bar['o'], held, basis,
                            bar['o'] - half, bar['o'] + half, offset=offset,
                            held_rungs=(list(lots) if rung_mode else None))
        # T6/W1: only what the live bot would have RESTING can fill
        desired = window(desired, bar['o'], cfg.get('place_within_pct', 0.05))
        for o in desired:
            if o['side'] == ('Buy' if long else 'Sell'):        # entries
                through = bar['l'] < o['price'] if long else bar['h'] > o['price']
                if through:
                    basis = adapter.average_entry(basis, held, o['price'], o['qty'])
                    held_steps += int(round(o['qty'] / step))
                    held = held_steps * step
                    fees += adapter.notional(o['qty'], o['price']) * fee_rate
                    entry_fills += 1
                    lots.append(o['rung'])
            else:                                               # exits
                through = bar['h'] > o['price'] if long else bar['l'] < o['price']
                if through and held > 0:
                    qty_steps = min(int(round(o['qty'] / step)), held_steps)
                    qty = qty_steps * step
                    realized += adapter.pnl_to_usd(
                        adapter.realised_pnl(basis, o['price'], qty), o['price']) * sign
                    held_steps -= qty_steps
                    held = held_steps * step
                    fees += adapter.notional(qty, o['price']) * fee_rate
                    trips += 1
                    if lots:                       # G23: the lot this exit closed
                        want = o['rung'] + lot_step
                        lots.remove(want if want in lots
                                    else (min(lots) if long else max(lots)))
        if held_steps == 0:
            held, basis, lots = 0.0, None, []
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

    return {'alone_liquidation': alone,
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
