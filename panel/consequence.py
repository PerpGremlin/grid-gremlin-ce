# What a setup means in numbers (D157, the create flow): the figures Bybit,
# Pionex and 3Commas put under their inputs — profit per grid level after
# fees, the size of each order, the least money the setup works with
# against what is free, and an estimated liquidation price.
#
# Every figure is the engine's own, never a second formula beside it:
#   - the orders are the engine's plan (plan_grid, martingale_schedule) and
#     its lattice (grid_rungs, lot); the money is the adapter's
#     (realised_pnl, notional) and a fee is charged as the backtest charges
#     it (notional x the rehearsal's maker rate per leg);
#   - the least money is the engine's own judges asked again (validate_config,
#     check_placeable, ladder_fits), bisected over the investment;
#   - a grid's liquidation is the backtest's `alone_liquidation` (T10), the
#     very figure the rehearsal prints, over one steady move against the
#     bot; a DCA bot's, which the backtest cannot replay, is the what-if's
#     straight move (the engine's schedule, the adapter's money) held to the
#     backtest's own maintenance rate.
# Display only: nothing here caps, refuses or changes a row (D29).
import copy
import html
import math

from gridgremlin.backtest import MM_RATE, backtest
from gridgremlin.config import ConfigError, check_placeable, validate_config
from gridgremlin.fees import BYBIT_MAKER, BYBIT_SPOT_TAKER
from gridgremlin.ladder import grid_rungs, ladder_fits, lot

PATH_STEP = 0.005            # each bar of the steady move: 0.5% further
PATH_LOW = 0.001             # a long's move ends at 0.1% of today's price
PATH_HIGH = 20.0             # a short's at twenty times it
PATH_BAR_MS = 3_600_000      # an hour a bar: a steady fall, not a crash


def fee_rate(cfg):
    """The rehearsal's maker rate on a perpetual; spot pays its own."""
    return BYBIT_SPOT_TAKER if cfg.get('market_type') == 'spot' else BYBIT_MAKER


def steady_move(mark, long, step=PATH_STEP):
    """One move against the bot, from today's price, a bar per `step`:
    a long's down to PATH_LOW of it, a short's up to PATH_HIGH times."""
    bars, p, t = [], mark, 0
    while True:
        q = p * (1.0 - step) if long else p * (1.0 + step)
        if q < mark * PATH_LOW or q > mark * PATH_HIGH:
            return bars
        bars.append({'t': t, 'o': p, 'h': max(p, q), 'l': min(p, q), 'c': q})
        p, t = q, t + PATH_BAR_MS


def trip(adapter, p_in, p_out, qty, sign, fee):
    """One entry and its exit, as the backtest books them: the adapter's
    realised P&L (R12's matched trip) less each leg's notional x fee."""
    gain = sign * adapter.pnl_to_usd(adapter.realised_pnl(p_in, p_out, qty), p_out)
    fees = (adapter.notional(qty, p_in) + adapter.notional(qty, p_out)) * fee
    return gain - fees, adapter.notional(qty, p_in)


def per_level(cfg, adapter, mark):
    """A grid's profit per level after fees: each gap of the home lattice
    sold one level on at the engine's lot (G4) -> (lowest %, highest %,
    lowest money, highest money), or None when the lot rounds to nothing."""
    q = lot(cfg, adapter, mark)
    if q <= 0:
        return None
    long = cfg['side'] == 'long'
    sign = 1.0 if long else -1.0
    prices = grid_rungs(cfg, adapter)
    fee = fee_rate(cfg)
    got = []
    for i in range(len(prices) - 1):
        p_in, p_out = (prices[i], prices[i + 1]) if long else (prices[i + 1], prices[i])
        net, size = trip(adapter, p_in, p_out, q, sign, fee)
        got.append((net / size if size else 0.0, net))
    if not got:
        return None
    pcts, money = [g[0] for g in got], [g[1] for g in got]
    return min(pcts), max(pcts), min(money), max(money)


def least_capital(row, adapter, mark):
    """The smallest investment the engine accepts for this row, every other
    setting as typed: its own validators asked again (C5's placeable rung,
    M2's ladder, D89's coin ladder at today's price), bisected. Rounded UP
    to three figures, then asked once more. None when no investment would
    do (something else is refused)."""
    def ok(c):
        try:                       # a deep copy: the row's blocks stay its own
            cfg = validate_config(dict(copy.deepcopy(row), capital=c))
            if cfg['strategy'] == 'grid':
                check_placeable(cfg, adapter)
            elif not ladder_fits(cfg, mark):
                return False
            return True
        except (ConfigError, ValueError, TypeError, KeyError, ZeroDivisionError):
            return False
    hi = max(float(row.get('capital') or 1.0), 1.0)
    while not ok(hi):
        hi *= 2.0
        if hi > 1e13:
            return None
    lo = 0.0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if mid <= lo or mid >= hi:
            break
        lo, hi = (lo, mid) if ok(mid) else (mid, hi)
    k = 10.0 ** (math.floor(math.log10(hi)) - 2)
    up = math.ceil(hi / k - 1e-9) * k
    return float(f'{up:.10g}') if ok(float(f'{up:.10g}')) else hi


def liquidation(cfg, adapter, mark):
    """The estimated liquidation price of a VALIDATED row standing alone on
    its own investment, every level filled on one steady move against it
    -> {'price', 'held', 'move'} or {'price': None, 'why'}. A stop or loss
    limit that closes it first is said instead; spot has none."""
    long = cfg['side'] == 'long'
    if cfg.get('market_type') == 'spot':
        return {'price': None, 'why': 'spot holds its coins outright: no liquidation'}
    if cfg.get('strategy', 'grid') == 'grid':
        r = backtest(cfg, adapter, steady_move(mark, long), fee_rate=fee_rate(cfg),
                     mm_rate=MM_RATE)
        alone = r.get('alone_liquidation')
        if alone:
            return {'price': alone['price'], 'held': alone['held'],
                    'move': alone['price'] / mark - 1.0}
        s = r.get('stopped')
        if s and s.get('action') == 'flatten':
            what = ('loss limit' if s['reason'].startswith('max_loss') else
                    'account-value stop' if s['reason'].startswith('account_equity') else
                    'stop loss')
            return {'price': None, 'why': f"its {what} closes it at "
                                          f"{_p(s['price'])} first"}
        return {'price': None, 'why': _never(mark, long)}
    return _dca_liquidation(cfg, adapter, mark)


def _never(mark, long):
    far = mark * (PATH_LOW if long else PATH_HIGH)
    return (f"its own investment carries every level all the way "
            f"{'down' if long else 'up'} to {_p(far)}")


def _dca_liquidation(cfg, adapter, mark):
    from panel.whatif import entries, whatif
    long = cfg['side'] == 'long'
    ladder = entries(cfg, adapter, mark)
    way = -1.0 if long else 1.0
    end = (1.0 - PATH_LOW) if long else (PATH_HIGH - 1.0)

    def short_of(move):
        """(maintenance left over, the what-if's facts) — None for the
        first when a stop or the loss limit has closed it."""
        r = whatif(cfg, adapter, ladder, mark, move)
        if r['loss_limit_at'] is not None:
            return None, r
        if r['stopped_at'] is not None and not r['held']:
            return None, r
        mm = adapter.notional(r['held'], r['price']) * MM_RATE if r['held'] else 0.0
        return cfg['capital'] + r['pnl'] - mm, r
    prev, n = 0.0, 1
    while True:
        move = way * min(n * PATH_STEP if long else (1.0 + PATH_STEP) ** n - 1.0, end)
        left, r = short_of(move)
        if left is None:
            at = r['loss_limit_at'] if r['loss_limit_at'] is not None else r['stopped_at']
            what = 'loss limit' if r['loss_limit_at'] is not None else 'stop loss'
            return {'price': None, 'why': f'its {what} closes it at {_p(at)} first'}
        if left <= 0:
            lo, hi = prev, move
            for _ in range(60):
                mid = (lo + hi) / 2.0
                got, _ = short_of(mid)
                lo, hi = (mid, hi) if got is not None and got > 0 else (lo, mid)
            _, r = short_of(hi)
            return {'price': mark * (1.0 + hi), 'held': r['held'], 'move': hi}
        if abs(move) >= end:
            return {'price': None, 'why': _never(mark, long)}
        prev, n = move, n + 1


def _p(v):
    """A price as a person reads it."""
    a = abs(v)
    if a >= 1000:
        return f'{v:,.0f}'
    if a >= 1:
        return f'{v:,.4g}' if a < 100 else f'{v:,.2f}'.rstrip('0').rstrip('.')
    return f'{v:.4g}'


def _m(v):
    """Money as a person reads it: whole above a thousand, cents below."""
    a = abs(v)
    if a >= 1000:
        return f'{v:,.0f}'
    if a >= 1:
        return f'{v:,.2f}'.rstrip('0').rstrip('.')
    if a >= 0.01 or a == 0:
        return f'{v:,.2f}'
    return f'{v:.2g}'


def numbers(cfg, adapter, mark, free=None, least=None):
    """The facts for a VALIDATED row at today's price. `least` is
    least_capital() of the raw row (the review and the form both have it);
    `free` the account's free balance from its last readout, or None."""
    long = cfg['side'] == 'long'
    lev = float(cfg.get('leverage') or 1.0)
    out = {'strategy': cfg.get('strategy', 'grid'), 'mark': mark,
           'leverage': lev, 'capital': cfg['capital'],
           'in_market': cfg.get('ladder_notional') or cfg['capital'] * lev,
           'least': least, 'free': free,
           'liquidation': liquidation(cfg, adapter, mark)}
    fee = fee_rate(cfg)
    out['fee'] = fee
    if out['strategy'] == 'grid':
        out['per_level'] = per_level(cfg, adapter, mark)
        q = lot(cfg, adapter, mark)
        out['order'] = (q, adapter.notional(q, mark))
        return out
    from panel.create import martingale_preview
    rows, _ = martingale_preview(cfg, mark)
    out['orders'] = [(r['qty'], r['notional']) for r in rows]
    out['full'] = sum(r['notional'] for r in rows)
    first = rows[0]
    tp = cfg.get('take_profit_avg_pct')
    if tp is None:
        tp = (cfg.get('take_profit_tranches') or [{}])[0].get('at_avg_pct')
    if tp is not None and first['qty'] > 0:
        sign = 1.0 if long else -1.0
        q0 = adapter.qty_from_notional(first['notional'], first['price'])
        net, size = trip(adapter, first['price'], first['price'] * (1.0 + sign * tp),
                         q0, sign, fee)
        out['first_round'] = (net / size if size else 0.0, net)
    return out


def _coins(cfg):
    return 'contracts' if cfg.get('market_type') == 'inverse' else 'coins'


def rows_html(cfg, n, money=''):
    """The facts as table rows, in the order the platforms show them."""
    e = html.escape
    unit = f' {e(money)}' if money else ''
    lev = n['leverage']
    out = [('Leverage', f"{lev:g}x — {_m(n['capital'])}{unit} trades up to "
                        f"{_m(n['in_market'])}{unit} in the market")]
    if n['strategy'] == 'grid':
        pl = n.get('per_level')
        if pl:
            lo, hi, mlo, mhi = pl
            span = (f'{lo:.2%}' if abs(hi - lo) < 5e-5 else f'{lo:.2%} – {hi:.2%}')
            mspan = (_m(mlo) if abs(mhi - mlo) < 0.005 else f'{_m(mlo)} – {_m(mhi)}')
            cls = ' class="neg"' if lo <= 0 else ''
            out.append(('Profit per grid level', f'<b{cls}>{span}</b> after fees '
                        f'(about {mspan}{unit} each time a level sells)'))
        q, notional = n['order']
        out.append(('Size per order', f'{q:.10g} {_coins(cfg)} — about {_m(notional)}{unit} '
                                      'at today\'s price' if q > 0 else
                     '<b class="neg">rounds to nothing</b> at this market\'s smallest '
                     'step: raise the investment or use fewer grids'))
    else:
        orders = n['orders']
        first, adds = orders[0], orders[1:]
        said = f'first order about {_m(first[1])}{unit}'
        if adds:
            said += (f', then {len(adds)} add-on{"s" if len(adds) != 1 else ""} '
                     f'from {_m(adds[0][1])} to {_m(adds[-1][1])}{unit}')
        out.append(('Size per order', said + f'; {_m(n["full"])}{unit} with every one filled'))
        fr = n.get('first_round')
        if fr:
            cls = ' class="neg"' if fr[0] <= 0 else ''
            out.append(('Profit per round', f'<b{cls}>{fr[0]:.2%}</b> after fees if it '
                        f'closes on the first order alone (about {_m(fr[1])}{unit})'))
    least, free = n.get('least'), n.get('free')
    if least is not None:
        said = f'{_m(least)}{unit}'
        if free is not None:
            short = n['capital'] > free
            cls = ' class="neg"' if short else ''
            said += (f' · this bot {_m(n["capital"])} · free to trade '
                     f'<b{cls}>{_m(free)}{unit}</b>'
                     + (' — more than the account has free' if short else ''))
        else:
            said += ' · free to trade: not read yet (the bots page reads it)'
        out.append(('Least investment that works', said))
    liq = n['liquidation']
    if liq.get('price') is not None:
        out.append(('Est. liquidation price',
                    f"<b class=\"neg\">{_p(liq['price'])}</b> ({liq['move']:+.1%} from "
                    f"today's {_p(n['mark'])}), with every "
                    + ('level' if n['strategy'] == 'grid' else 'add-on')
                    + ' filled on the way'))
    else:
        out.append(('Est. liquidation price', f"none on the way: {e(liq['why'])}"))
    return ''.join(f'<tr><td>{a}</td><td>{b}</td></tr>' for a, b in out)


NOTE = ('estimates at today\'s price, from the engine\'s own orders. Fees at '
        'the base maker rate. The liquidation is this bot standing alone on its '
        'own investment, as the rehearsal says it; under cross margin the '
        'account\'s free balance holds it longer, and the exchange\'s own figure '
        'is the one that counts.')


def block(cfg, n, money=''):
    """The numbers as one box: under the inputs, and on the review page."""
    return (f'<table class="numbers">{rows_html(cfg, n, money)}</table>'
            f'<p class="dim">{NOTE}</p>')
