"""Research (2026-10-08): the basket — several coins at target weights, each
with its own hedge, rebalanced on one clock. The owner: "a portfolio of
assets … with the ability to run short hedges, which can also be
rebalanced." Does a basket beat the best single-asset book on drawdown
with similar return? Reuses rebalance_carry's regime, leg and fetchers.

  python3 ops/research/basket_carry.py [--years 2] [--coins BTC,ETH,SOL] [--funding hl]

--funding hl: the hedges are Hyperliquid's USDC perps (linear legs) paid
Hyperliquid's own hourly funding, summed to the 8h clock — the shape the
HL leg of the portfolio row will trade (the testnet refuses a sub-account
until more volume has traded there, so the rehearsal stands in meanwhile).
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ops.research.fib_backtest import fetch                                 # noqa: E402
from ops.research.funding_carry import fetch as fetch_funding               # noqa: E402
from ops.research.funding_spread import fetch_hl                            # noqa: E402
from ops.research.rebalance_carry import (H, HAIRCUT, PERP_FEE, SPOT_FEE,    # noqa: E402
                                          Leg, Regime, run as run_single)


def hl_8h(rows):
    """Hyperliquid pays hourly; the basket's clock is 8h — sum each bucket."""
    out = {}
    for x in rows:
        b = x['t'] // (8 * H)
        out[b] = out.get(b, 0.0) + x['rate']
    return [{'t': b * 8 * H, 'rate': r} for b, r in sorted(out.items())]


def run_basket(coins, bars1h, funding_inv, regimes, weights, tilt, threshold, check_h,
               hedge=True, rebalance_weights=True, start_cash=10_000.0, inverse=True):
    """One basket. bars1h: {coin: hourly bars on one grid}; funding_inv:
    {coin: inverse funding rows}; regimes: {coin: Regime} or None (no tilt).
    Weights rebalance on the clock past a drift of `threshold` of the
    basket; each hedge is an inverse short at h = 1 - tilt (up) / 1 (range)
    / 1 + tilt (down) of that coin's holding; funding buys spot pro rata."""
    n = len(bars1h[coins[0]])
    assert all(len(bars1h[c]) == n for c in coins)
    fund = {c: {x['t'] // (8 * H): x['rate'] for x in funding_inv[c]} for c in coins}
    p0 = {c: bars1h[c][0]['c'] for c in coins}
    coins_held = {c: start_cash * weights[c] * (1 - SPOT_FEE) / p0[c] for c in coins}
    legs = {c: Leg(inverse) for c in coins}
    cash, fees, paid = 0.0, start_cash * SPOT_FEE, 0.0
    last_check, rebalances, seen = bars1h[coins[0]][0]['t'], 0, set()
    eq_path = []
    for i in range(n):
        t = bars1h[coins[0]][i]['t'] + H
        px = {c: bars1h[c][i]['c'] for c in coins}
        bucket = t // (8 * H)
        if bucket not in seen:
            seen.add(bucket)
            for c in coins:
                got = legs[c].funding(fund[c].get(bucket, 0.0), px[c])
                cash += got
                paid += got
        value = sum(coins_held[c] * px[c] for c in coins)
        perp = sum(l.real + l.unreal(px[c]) for c, l in legs.items())
        basket = value + cash + perp - fees
        if t - last_check >= check_h * H:
            last_check = t
            if cash > 0:                                        # funding buys spot, pro rata
                for c in coins:
                    coins_held[c] += cash * weights[c] * (1 - SPOT_FEE) / px[c]
                fees += cash * SPOT_FEE
                cash = 0.0
                value = sum(coins_held[c] * px[c] for c in coins)
                basket = value + perp - fees
            moved = False
            if rebalance_weights:
                for c in coins:
                    target_v = weights[c] * value
                    delta_v = target_v - coins_held[c] * px[c]
                    if abs(delta_v) / max(basket, 1e-9) > threshold:
                        coins_held[c] += delta_v / px[c]
                        fees += abs(delta_v) * SPOT_FEE
                        moved = True
            if hedge:
                for c in coins:
                    reg = regimes[c].read(t) if regimes else 'range'
                    h = {'up': 1.0 - tilt, 'range': 1.0, 'down': 1.0 + tilt}[reg]
                    want = h * coins_held[c]
                    drift = abs(legs[c].coins_hedged(px[c]) - want) * px[c] / max(coins_held[c] * px[c], 1e-9)
                    if drift > threshold:
                        fees += legs[c].set_coins(want, px[c]) * PERP_FEE
                        moved = True
            rebalances += moved
        notional = sum(l.coins_hedged(px[c]) * px[c] for c, l in legs.items())
        equity = value + cash + perp - fees
        eq_path.append(equity)
        if notional > (value * (1 - HAIRCUT) + cash + perp) * 10 or equity <= 0:
            return None
    peak, dd = eq_path[0], 0.0
    for e in eq_path:
        peak = max(peak, e)
        dd = max(dd, 1 - e / peak)
    return {'equity': eq_path[-1] / start_cash, 'maxDD': dd, 'funding': paid / start_cash,
            'fees': fees / start_cash, 'rebalances': rebalances}


def main(argv):
    years = int(argv[argv.index('--years') + 1]) if '--years' in argv else 2
    coins = argv[argv.index('--coins') + 1].split(',') if '--coins' in argv else ['BTC', 'ETH', 'SOL']
    hl = '--funding' in argv and argv[argv.index('--funding') + 1] == 'hl'
    end = int(time.time() * 1000) // 86_400_000 * 86_400_000
    start = end - (365 * years + 40) * 86_400_000
    bars = {c: {m: fetch(f'{c}USDT', m, start, end) for m in (1440, 240, 60)} for c in coins}
    fl = {c: fetch_funding('linear', f'{c}USDT', start, end) for c in coins}
    fi = ({c: hl_8h(fetch_hl(c, start, end)) for c in coins} if hl
          else {c: fetch_funding('inverse', f'{c}USD', start, end) for c in coins})
    inv = not hl
    kind = 'HL usdc hedges, HL funding' if hl else 'inverse hedges'
    weights = {c: 1.0 / len(coins) for c in coins}
    windows = [(f'Y-{years - k}', end - (k + 1) * 365 * 86_400_000, end - k * 365 * 86_400_000)
               for k in range(years - 1, -1, -1)]
    if years > 1:
        windows.append((f'all {years}y', end - years * 365 * 86_400_000, end))
    for label, a, z in windows:
        # one hourly grid: the timestamps every coin has
        common = set.intersection(*(set(b['t'] for b in bars[c][60] if a <= b['t'] < z) for c in coins))
        b1h = {c: [b for b in bars[c][60] if b['t'] in common] for c in coins}
        f_inv = {c: [x for x in fi[c] if a <= x['t'] < z] for c in coins}
        f_lin = {c: [x for x in fl[c] if a <= x['t'] < z] for c in coins}
        print(f"=== basket {'/'.join(coins)} equal weights ({kind}), {label} "
              f"({time.strftime('%Y-%m-%d', time.gmtime(a / 1000))} → {time.strftime('%Y-%m-%d', time.gmtime(z / 1000))})")

        def line(name, r):
            if r is None:
                return f'  {name:40} could not be held (margin)'
            return (f"  {name:40} equity x{r['equity']:.3f}  maxDD {r['maxDD']:5.1%}  "
                    f"funding {r['funding']:+.2%}  fees {r['fees']:.2%}  rebal {r['rebalances']:3}")

        def regimes():
            return {c: Regime(bars[c][1440], bars[c][240], hold_h=24) for c in coins}
        print(line('HODL basket (no rebalance, no hedge)', run_basket(coins, b1h, f_inv, None, weights, 0, 1.0, 24, hedge=False, rebalance_weights=False)))
        print(line('REBALANCED basket, unhedged', run_basket(coins, b1h, f_inv, None, weights, 0, 0.05, 24, hedge=False)))
        print(line('NEUTRAL basket, hedged', run_basket(coins, b1h, f_inv, None, weights, 0, 0.05, 24, inverse=inv)))
        for tilt in (0.3, 0.6):
            print(line(f'TILT {tilt:.1f} basket, hedged', run_basket(coins, b1h, f_inv, regimes(), weights, tilt, 0.05, 24, inverse=inv)))
        if hl:
            continue                     # the singles below are the Bybit inverse comparison
        # the single-asset tilted inverse books on the same window, and their plain average
        singles = {}
        for c in coins:
            reg = Regime(bars[c][1440], bars[c][240], hold_h=24)
            r = run_single(b1h[c], f_lin[c], reg, 0.6, 0.05, 24, hedge='inverse', funding_inv=f_inv[c])
            singles[c] = r
            print(line(f'  single {c} TILT 0.6 inverse (for comparison)', r))
        ok = [r for r in singles.values() if r]
        if ok:
            print(f"  {'  average of the singles (no cross-coin rebalance)':40} equity x{sum(r['equity'] for r in ok) / len(ok):.3f}  "
                  f"maxDD (worst single) {max(r['maxDD'] for r in ok):5.1%}")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
