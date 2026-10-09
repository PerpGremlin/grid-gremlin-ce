"""Research (2026-10-08): "profit by regime identification and disciplined
rebalancing" — the owner's thesis. Long spot, short the perp, lean the
hedge ratio with the trend, rebalance on a drift threshold and on a clock.

  python3 ops/research/rebalance_carry.py [--days 365] [--coins BTC,ETH]

Books compared on the same year: HODL (spot only); NEUTRAL (always 100%
hedged, the carry alone); TILT (the hedge leans with the regime read from
the daily and 4h structure, with hysteresis). Funding received by the
short buys spot — the accumulation. Bybit fees: spot 0.1%, perp maker
0.02%; spot collateral haircut 10%. Nothing here touches a venue with a
key or any running code.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from gridgremlin.fib import known_by, structure, wilder_atr, zigzag          # noqa: E402
from ops.research.fib_backtest import fetch                                 # noqa: E402
from ops.research.funding_carry import fetch as fetch_funding               # noqa: E402

SPOT_FEE, PERP_FEE, HAIRCUT = 0.001, 0.0002, 0.10
H = 3_600_000


class Regime:
    """The trend by structure on the daily and the 4h, read without
    lookahead, held for `hold_h` hours before a change is believed."""

    def __init__(self, bars_d, bars_4h, hold_h=24):
        self.tfs = []
        for bars, minutes in ((bars_d, 1440), (bars_4h, 240)):
            atr = wilder_atr(bars, 14)
            self.tfs.append((bars, minutes, zigzag(bars, atr, 3.0)))
        self.hold_h, self.said, self.since = hold_h, 'range', None

    def read(self, t_ms):
        words = []
        for bars, minutes, swings in self.tfs:
            j = max(i for i, b in enumerate(bars) if b['t'] + minutes * 60_000 <= t_ms) if bars and bars[0]['t'] + minutes * 60_000 <= t_ms else -1
            if j < 20:
                return self.said
            trend, _, _ = structure(known_by(swings, j))
            words.append(trend)
        raw = 'up' if all(w == 'up' for w in words) else 'down' if all(w == 'down' for w in words) else 'range'
        if raw != self.said:
            if self.since is None:
                self.since = t_ms
            elif t_ms - self.since >= self.hold_h * H:
                self.said, self.since = raw, None
        else:
            self.since = None
        return self.said


class Leg:
    """One short leg. Linear: qty in coins, P&L in quote. Inverse: $1
    contracts, P&L in the coin itself — so a fixed hedge in contracts
    covers fewer coins as the price rises and more as it falls."""

    def __init__(self, inverse):
        self.inverse, self.qty, self.entry, self.real = inverse, 0.0, 0.0, 0.0

    def coins_hedged(self, p):
        return self.qty / p if self.inverse else self.qty

    def unreal(self, p):
        if self.qty <= 0:
            return 0.0
        if self.inverse:
            return self.qty * (1 / p - 1 / self.entry) * p        # coin P&L, in quote at p
        return (self.entry - p) * self.qty

    def set_coins(self, want_coins, p):
        """Resize to hedge `want_coins`; returns quote notional traded."""
        target = want_coins * p if self.inverse else want_coins
        delta = target - self.qty
        if abs(delta) < 1e-12:
            return 0.0
        if delta < 0:
            closed = -delta
            self.real += (closed * (1 / p - 1 / self.entry) * p if self.inverse
                          else (self.entry - p) * closed)
            self.qty -= closed
        elif self.inverse:
            # $1 contracts average harmonically (the return-split audit, 2026-10-09)
            self.entry = (p if self.qty <= 0 else
                          (self.qty + delta) / (self.qty / self.entry + delta / p))
            self.qty += delta
        else:
            self.entry = ((self.entry * self.qty + p * delta) / (self.qty + delta)
                          if self.qty + delta > 0 else p)
            self.qty += delta
        return abs(delta) if self.inverse else abs(delta) * p

    def open_coins(self, p):
        """An inverse leg's open P&L in its coin — part of what the book owns,
        so the hedge of N contracts covers N / p of the coins (the audit)."""
        return self.qty * (1 / p - 1 / self.entry) if self.inverse and self.qty > 0 and self.entry else 0.0

    def funding(self, rate, p):
        """What the short receives at a settlement, in quote."""
        return rate * (self.qty if self.inverse else self.qty * p)


def run(bars1h, funding, regime, tilt, threshold, check_h, start_cash=10_000.0, hodl=False,
        neutral=False, hedge='usdt', funding_inv=None, spot_lev=1.0, borrow_apr=0.0):
    """Walk the hourly bars. hedge: 'usdt', 'inverse', 'split' (half each)
    or 'rotate' (whichever's trailing 7-day funding paid more, checked on
    the clock). spot_lev > 1 borrows quote at borrow_apr to buy more spot.
    Returns the book's story, or None if its margin could not be held."""
    fund_lin = {x['t'] // (8 * H): x['rate'] for x in funding}
    fund_inv = {x['t'] // (8 * H): x['rate'] for x in (funding_inv or [])}
    p0 = bars1h[0]['c']
    borrowed = start_cash * (spot_lev - 1.0)
    coins = (start_cash + borrowed) * (1 - SPOT_FEE) / p0
    cash, fees, interest = 0.0, (start_cash + borrowed) * SPOT_FEE, 0.0
    legs = {'usdt': Leg(False), 'inverse': Leg(True)}
    last_check, rebalances, paid_funding = bars1h[0]['t'], 0, 0.0
    seen_fund, eq_path, in_regime = set(), [], {'up': 0, 'range': 0, 'down': 0}
    hist_lin, hist_inv, which = [], [], ('usdt' if hedge in ('usdt', 'rotate') else hedge)
    for b in bars1h:
        t, p = b['t'] + H, b['c']
        interest += borrowed * borrow_apr / 8760.0
        bucket = t // (8 * H)
        if bucket not in seen_fund and (bucket in fund_lin or bucket in fund_inv):
            seen_fund.add(bucket)
            got = legs['usdt'].funding(fund_lin.get(bucket, 0.0), p) + legs['inverse'].funding(fund_inv.get(bucket, 0.0), p)
            cash += got
            paid_funding += got
            hist_lin.append(fund_lin.get(bucket, 0.0))
            hist_inv.append(fund_inv.get(bucket, 0.0))
        reg = 'range' if (hodl or neutral) else regime.read(t)
        in_regime[reg] += 1
        target_h = 0.0 if hodl else 1.0 if neutral else {'up': 1.0 - tilt, 'range': 1.0, 'down': 1.0 + tilt}[reg]
        spot_value = coins * p
        if t - last_check >= check_h * H:
            last_check = t
            if cash > 0:                                        # the accumulation
                coins += cash * (1 - SPOT_FEE) / p
                fees += cash * SPOT_FEE
                cash = 0.0
                spot_value = coins * p
            if hedge == 'rotate' and len(hist_lin) >= 21:
                which = 'usdt' if sum(hist_lin[-21:]) >= sum(hist_inv[-21:]) else 'inverse'
            # the coins the hedge covers include the inverse leg's own coin P&L —
            # left out, a ratio-1 book drifts net short in a rally (the audit)
            want = target_h * (coins + legs['inverse'].open_coins(p))
            if hedge == 'split':
                plan = {'usdt': want / 2, 'inverse': want / 2}
            elif hedge in ('usdt', 'inverse'):
                plan = {hedge: want, ('inverse' if hedge == 'usdt' else 'usdt'): 0.0}
            else:
                plan = {which: want, ('inverse' if which == 'usdt' else 'usdt'): 0.0}
            hedged = sum(l.coins_hedged(p) for l in legs.values())
            drift = abs(hedged - want) * p / max(spot_value, 1e-9)
            moved = sum(1 for n, l in legs.items() if abs(l.coins_hedged(p) - plan[n]) * p > 1e-6)
            if drift > threshold or (hedge in ('rotate', 'split') and moved and drift > threshold / 2):
                traded = sum(legs[n].set_coins(plan[n], p) for n in legs)
                fees += traded * PERP_FEE
                rebalances += 1
        perp = sum(l.real + l.unreal(p) for l in legs.values())
        equity = spot_value + cash + perp - fees - interest - borrowed
        eq_path.append(equity)
        notional = sum(l.coins_hedged(p) for l in legs.values()) * p
        if notional > (spot_value * (1 - HAIRCUT) + cash + perp - borrowed) * 10 or equity <= 0:
            return None
    peak, dd = eq_path[0], 0.0
    for e in eq_path:
        peak = max(peak, e)
        dd = max(dd, 1 - e / peak)
    return {'equity': eq_path[-1] / start_cash, 'coins': coins / (start_cash / p0), 'maxDD': dd,
            'funding': paid_funding / start_cash, 'fees': fees / start_cash, 'interest': interest / start_cash,
            'rebalances': rebalances, 'regime': in_regime, 'price': bars1h[-1]['c'] / p0}


def main(argv):
    years = int(argv[argv.index('--years') + 1]) if '--years' in argv else 1
    coins = argv[argv.index('--coins') + 1].split(',') if '--coins' in argv else ['BTC', 'ETH']
    end = int(time.time() * 1000) // 86_400_000 * 86_400_000
    start = end - (365 * years + 40) * 86_400_000
    for coin in coins:
        sym = f'{coin}USDT'
        bars = {m: fetch(sym, m, start, end) for m in (1440, 240, 60)}
        funding = fetch_funding('linear', sym, start, end)
        funding_inv = fetch_funding('inverse', f'{coin}USD', start, end)
        windows = [(f'Y-{years - k}', end - (k + 1) * 365 * 86_400_000, end - k * 365 * 86_400_000)
                   for k in range(years - 1, -1, -1)]
        if years > 1:
            windows.append((f'all {years}y', end - years * 365 * 86_400_000, end))
        for label, a, z in windows:
            b1h = [b for b in bars[60] if a <= b['t'] < z]
            fl = [x for x in funding if a <= x['t'] < z]
            fi = [x for x in funding_inv if a <= x['t'] < z]
            print(f"=== {coin} {label} ({time.strftime('%Y-%m-%d', time.gmtime(a / 1000))} → "
                  f"{time.strftime('%Y-%m-%d', time.gmtime(z / 1000))}): price x{b1h[-1]['c'] / b1h[0]['c']:.2f}; "
                  f"funding to a short — USDT perp {sum(x['rate'] for x in fl):+.2%}, inverse {sum(x['rate'] for x in fi):+.2%}")

            def line(name, r):
                if r is None:
                    return f'  {name:34} could not be held (margin)'
                reg = r['regime']
                tot = sum(reg.values()) or 1
                return (f"  {name:34} equity x{r['equity']:.3f}  coins x{r['coins']:.3f}  maxDD {r['maxDD']:5.1%}  "
                        f"funding {r['funding']:+.2%}  fees {r['fees']:.2%}"
                        + (f"  interest {r['interest']:.2%}" if r['interest'] else '')
                        + f"  rebal {r['rebalances']:3}  up/range/down {reg['up'] / tot:.0%}/{reg['range'] / tot:.0%}/{reg['down'] / tot:.0%}")

            def go(name, **kw):
                regime = Regime(bars[1440], bars[240], hold_h=24)
                print(line(name, run(b1h, fl, regime, kw.pop('tilt', 0.6), 0.05, 24, funding_inv=fi, **kw)), flush=True)
            go('HODL spot', hodl=True)
            go('NEUTRAL, USDT hedge', neutral=True)
            go('NEUTRAL, inverse hedge', neutral=True, hedge='inverse')
            go('TILT 0.3, USDT hedge', tilt=0.3)
            go('TILT 0.6, USDT hedge', tilt=0.6)
            go('TILT 0.6, inverse hedge', hedge='inverse')
            go('TILT 0.6, split hedge', hedge='split')
            go('TILT 0.6, rotate by funding', hedge='rotate')
            if '--margin' in argv:
                for lev in (1.5, 2.0):
                    for apr in (0.05, 0.10):
                        go(f'NEUTRAL x{lev:g} spot, borrow {apr:.0%}', neutral=True, spot_lev=lev, borrow_apr=apr)
                        go(f'TILT 0.6 x{lev:g} spot, borrow {apr:.0%}', spot_lev=lev, borrow_apr=apr)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
