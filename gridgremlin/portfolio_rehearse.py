"""H7 (D78): the portfolio row's rehearsal is its own planner run over
history — hourly closes and funding per coin, the row's own gate and
plan, the research's fees — one engine, no second model. The research
harnesses (`ops/research/basket_carry.py`) measured the idea; this
reproduces their numbers with the engine's code, and the panel's figures
are the same function.

  python3 -m gridgremlin.portfolio_rehearse <fleet.json> --name <row> [--years 2]
"""
import sys

from .fees import BYBIT_MAKER, BYBIT_SPOT_TAKER
from .portfolio import plan_portfolio

H = 3_600_000
SPOT_FEE, PERP_FEE = BYBIT_SPOT_TAKER, BYBIT_MAKER   # the research's: taker spot, maker perp
HAIRCUT = 0.10                              # spot collateral haircut on the margin test


class _Leg:
    """One short leg. Linear: coins, P&L in quote. Inverse: $1 contracts,
    P&L in the coin — a fixed hedge in contracts covers fewer coins as
    the price rises and more as it falls (the shape)."""

    def __init__(self, inverse):
        self.inverse, self.qty, self.entry, self.real = inverse, 0.0, 0.0, 0.0

    def coins(self, p):
        return self.qty / p if self.inverse else self.qty

    def unreal(self, p):
        if self.qty <= 0:
            return 0.0
        if self.inverse:
            return self.qty * (1 / p - 1 / self.entry) * p
        return (self.entry - p) * self.qty

    def funding(self, rate, p):
        return rate * (self.qty if self.inverse else self.qty * p)

    def trade(self, side, coins, p):
        """'sell' adds, 'buy' reduces; returns quote notional traded."""
        delta = coins * p if self.inverse else coins
        if side == 'buy':
            closed = min(self.qty, delta)
            self.real += (closed * (1 / p - 1 / self.entry) * p if self.inverse
                          else (self.entry - p) * closed)
            self.qty -= closed
            if self.qty <= 1e-12:
                self.qty, self.entry = 0.0, 0.0
        else:
            self.entry = ((self.entry * self.qty + p * delta) / (self.qty + delta)
                          if self.qty + delta else 0.0)
            self.qty += delta
        return coins * p                           # quote notional traded


def rehearse(cfg, bars1h, funding, regimes=None, start_cash=None):
    """`bars1h`: {coin: [{'t', 'c'}]} on one grid; `funding`: {coin: rows
    {'t', 'rate'}} per 8h for the coin's short; `regimes`: {coin: f(t_ms)
    -> 'up'|'down'|'range'} or None. Returns {'equity' (× start),
    'maxDD', 'funding', 'fees', 'rebalances', 'path'}; None when the
    margin test fails (a short the stack cannot carry)."""
    coins = [a['coin'] for a in cfg['assets']]
    n = len(bars1h[coins[0]])
    assert all(len(bars1h[c]) == n for c in coins), 'one grid'
    fund = {c: {x['t'] // (8 * H): x['rate'] for x in funding.get(c, [])} for c in coins}
    inverse = {c: (cfg['hedges'].get(c) or {}).get('product', cfg['short_products'].get(c)) == 'inverse'
               for c in coins}
    legs = {c: _Leg(inverse[c]) for c in coins}
    hedged = {c: [] for c in coins}
    start = float(start_cash or cfg['capital'])
    held = {c: 0.0 for c in coins}
    cash, fees, paid, rebalances, seen = start, 0.0, 0.0, 0, set()
    apr = (cfg.get('margin') or {}).get('borrow_apr_max', 0.0)      # the row borrows at its cap
    last_tick, path = None, []
    for i in range(n):
        t = bars1h[coins[0]][i]['t'] + H
        px = {c: float(bars1h[c][i]['c']) for c in coins}
        bucket = t // (8 * H)
        if bucket not in seen:
            seen.add(bucket)
            for c in coins:
                got = legs[c].funding(fund[c].get(bucket, 0.0), px[c])
                cash += got
                paid += got
        book = {'coins': dict(held), 'cash': cash,
                'hedged': {c: legs[c].coins(px[c]) for c in coins if (cfg['hedges'].get(c) or {}).get('ratio', 0) > 0},
                'shorts': {c: legs[c].coins(px[c]) for c in coins if c in cfg['short_products']}}
        reg = {c: regimes[c](t) for c in coins} if regimes else None
        plan = plan_portfolio(cfg, book, px, t, last_tick, regimes=reg)
        if plan['tick']:
            last_tick = t
            moved = False
            for o in plan['orders']:
                kind, c = o['leg']
                q, p = o['coins'], px[c]
                if kind == 'spot':
                    held[c] += q if o['side'] == 'buy' else -q
                    cash += (-q * p) if o['side'] == 'buy' else q * p
                    fees += q * p * SPOT_FEE                   # the fee, counted once
                else:
                    traded = legs[c].trade('sell' if o['side'] == 'sell' else 'buy', q, p)
                    fees += traded * PERP_FEE
                moved = True
            rebalances += moved
        if cash < 0:
            fees += -cash * apr / 8760.0                 # the loan's hour of interest
        value = sum(held[c] * px[c] for c in coins)
        perp = sum(l.real + l.unreal(px[c]) for c, l in legs.items())
        equity = value + cash + perp - fees
        notional = sum(l.coins(px[c]) * px[c] for c, l in legs.items())
        path.append(equity)
        if notional > (value * (1 - HAIRCUT) + cash + perp) * 10 or equity <= 0:
            return None
    peak, dd = path[0], 0.0
    for e in path:
        peak = max(peak, e)
        dd = max(dd, 1 - e / peak)
    return {'equity': path[-1] / start, 'maxDD': dd, 'funding': paid / start,
            'fees': fees / start, 'rebalances': rebalances, 'path': path}


def main(argv):
    import json
    import time
    from pathlib import Path
    from .config import validate_fleet
    years = int(argv[argv.index('--years') + 1]) if '--years' in argv else 2
    name = argv[argv.index('--name') + 1] if '--name' in argv else None
    paths = [a for a in argv if a.endswith('.json')]
    if not paths:
        print(__doc__)
        return 2
    fleet = validate_fleet(json.loads(Path(paths[0]).read_text()))
    rows = [c for c in fleet['bots'] if c.get('strategy') == 'portfolio'
            and (name is None or c['name'] == name)]
    if not rows:
        print('no portfolio row' + (f" named {name}" if name else '') + ' in that fleet')
        return 2
    cfg = rows[0]
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from ops.research.fib_backtest import fetch                      # the research's fetchers
    from ops.research.funding_carry import fetch as fetch_funding
    from ops.research.funding_spread import fetch_hl
    from ops.research.basket_carry import hl_8h
    end = int(time.time() * 1000) // 86_400_000 * 86_400_000
    start = end - (365 * years + 40) * 86_400_000
    coins = [a['coin'] for a in cfg['assets']]
    bars = {c: fetch(f'{c}USDT', 60, start, end) for c in coins}
    common = set.intersection(*(set(b['t'] for b in bars[c]) for c in coins))
    bars = {c: [b for b in bars[c] if b['t'] in common] for c in coins}
    funding = {}
    for c in coins:
        product = (cfg['hedges'].get(c) or {}).get('product') or cfg['short_products'].get(c)
        if cfg['venue'] == 'hyperliquid':
            funding[c] = hl_8h(fetch_hl(c, start, end))
        elif product == 'inverse':
            funding[c] = fetch_funding('inverse', f'{c}USD', start, end)
        else:
            funding[c] = fetch_funding('linear', f'{c}USDT', start, end)
    r = rehearse(cfg, bars, funding)
    if r is None:
        print('could not be held (margin)')
        return 1
    a, z = bars[coins[0]][0]['t'], bars[coins[0]][-1]['t']
    print(f"{cfg['botid']} {'/'.join(coins)} {time.strftime('%Y-%m-%d', time.gmtime(a / 1000))} → "
          f"{time.strftime('%Y-%m-%d', time.gmtime(z / 1000))}: equity x{r['equity']:.3f}  "
          f"maxDD {r['maxDD']:.1%}  funding {r['funding']:+.2%}  fees {r['fees']:.2%}  "
          f"rebalances {r['rebalances']}")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
