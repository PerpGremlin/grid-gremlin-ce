"""The portfolio row (D78, SPEC family H): several coins on spot at target
weights, each hedged by its own perpetual short at its own ratio, the
funding collected, weights and hedges rebalanced on one clock, the risk
the portfolio's. This module is the gate (H1) and the plan (H3), both
pure: no I/O, no clock of their own, no venue. docs/PORTFOLIO.md is the
design; SPEC.md holds what is built.
"""
import re

from .config import (ConfigError, _enum, _flag, _fraction, _num,
                     _reject_unknown, _refuse, _utc_ms)

PORTFOLIO_KEYS = ('strategy', 'name', 'venue', 'account', 'capital', 'assets',
                  'hedge', 'rebalance', 'regime', 'funding_rule', 'risk',
                  'margin', 'spot_borrow', 'spot_quote')
PRODUCTS = ('usdt', 'usdc', 'inverse')
H = 3_600_000
CASH_RESERVE = 0.003         # of the cash a tick spends, kept for the buys' fees (three refusals by a hair, 2026-10-08)


def validate_portfolio(row, where='row'):
    """H1: the row — its assets and weights, its hedges, its clock, its
    optional regime tilt, its funding rule, its risk, its margin; every
    refusal names the key and the rule (C7)."""
    _reject_unknown(row, PORTFOLIO_KEYS, where)
    cfg = {k: v for k, v in row.items() if not k.startswith('_')}
    cfg['strategy'] = 'portfolio'
    name = cfg.get('name')
    if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9]{1,12}', name):
        _refuse(f"{where}: 'name' is required — one to twelve lower-case letters "
                "or digits; it is the row's id (pfo<name>) on every surface")
    cfg['botid'] = f'pfo{name}'
    cfg['venue'] = _enum(cfg, 'venue', where, ('bybit', 'hyperliquid'), default='bybit')
    account = cfg.get('account')                    # None: the fleet's (H5)
    if account is not None and (not isinstance(account, str)
                                or not re.fullmatch(r'[a-z0-9]{1,12}', account)):
        _refuse(f"{where}: 'account' names the keys the row trades with — "
                "'default', or a name whose keys .env carries (H5)")
    cfg['account'] = account
    cfg['capital'] = _num(cfg, 'capital', where, least=0.0, least_open=True, required=True)
    cfg['spot_borrow'] = _flag(cfg, 'spot_borrow')
    cfg['spot_quote'] = _enum(cfg, 'spot_quote', where, ('USDT', 'USDC'), default='USDT')   # the stack's cash

    # --- the assets and their weights ---------------------------------------
    assets = cfg.get('assets')
    if not isinstance(assets, list) or not assets:
        _refuse(f"{where}: 'assets' is a list of {{coin, weight}} — at least one")
    seen, out = set(), []
    for i, a in enumerate(assets):
        w = f'{where}.assets[{i}]'
        if not isinstance(a, dict):
            _refuse(f'{w}: an object {{coin, weight}}')
        _reject_unknown(a, ('coin', 'weight', 'holding'), w)
        coin = a.get('coin')
        if not isinstance(coin, str) or not re.fullmatch(r'[A-Z0-9]{2,12}', coin):
            _refuse(f"{w}: 'coin' is the base coin's ticker, like BTC")
        if coin in seen:
            _refuse(f"{where}: {coin} is named twice in 'assets' — one asset, one weight")
        seen.add(coin)
        weight = _num(a, 'weight', w, required=True)
        if weight == 0:
            _refuse(f"{w}: a weight of zero is no asset — leave it out")
        holding = _num(a, 'holding', w, least=0.0) or 0.0     # coins adopted into the book (H2)
        if holding and weight < 0:
            _refuse(f"{w}: a 'holding' is coins on spot — an outright short holds none")
        out.append({'coin': coin, 'weight': float(weight), 'holding': float(holding)})
    cfg['assets'] = out

    # --- margin on the stack (opt-in; D24's spot_borrow is the right) --------
    lev = 1.0
    margin = cfg.get('margin')
    if margin is not None:
        w = f'{where}.margin'
        if not isinstance(margin, dict):
            _refuse(f'{w}: an object {{spot_leverage, borrow_apr_max}}')
        _reject_unknown(margin, ('spot_leverage', 'borrow_apr_max'), w)
        if not cfg['spot_borrow']:
            _refuse(f"{w}: margin on the stack borrows quote — it needs 'spot_borrow': true (D24)")
        lev = _num(margin, 'spot_leverage', w, least=1.0, most=10.0, required=True)
        margin['spot_leverage'] = lev
        margin['borrow_apr_max'] = _fraction(margin, 'borrow_apr_max', w) or 0.08
        cfg['margin'] = margin

    # --- the weights must fill the stack exactly ------------------------------
    total = sum(abs(a['weight']) for a in out)
    if abs(total - lev) > 1e-6:
        _refuse(f"{where}: the weights' sizes sum to {total:.4g}, not {lev:g} — "
                "every weight is a share of the stack (a negative weight is an "
                "outright short of that share); with 'margin' they sum to spot_leverage")

    # --- the risk ---------------------------------------------------------------
    risk = cfg.get('risk') or {}
    w = f'{where}.risk'
    if not isinstance(risk, dict):
        _refuse(f'{w}: an object')
    _reject_unknown(risk, ('max_loss', 'max_loss_since', 'margin_floor_pct',
                           'basis_stop_pct', 'max_weight'), w)
    ml = _num(risk, 'max_loss', w, least=0.0, least_open=True)
    since = risk.get('max_loss_since')
    if (ml is None) != (since is None):
        _refuse(f"{w}: 'max_loss' and 'max_loss_since' travel together — the "
                "portfolio's loss is counted from a stated moment (D47's shape)")
    if ml is not None:
        risk['max_loss'] = ml
        risk['max_loss_since_ms'] = _utc_ms(since, f"{w}: 'max_loss_since'")
    risk['margin_floor_pct'] = _fraction(risk, 'margin_floor_pct', w) or 0.4
    risk['basis_stop_pct'] = _fraction(risk, 'basis_stop_pct', w) or 0.01
    risk['max_weight'] = _num(risk, 'max_weight', w, least=0.0, least_open=True, most=10.0) or 0.5
    for a in out:
        if abs(a['weight']) > risk['max_weight'] + 1e-9:
            _refuse(f"{where}: {a['coin']} at {abs(a['weight']):.2%} is above "
                    f"'max_weight' {risk['max_weight']:.0%} — no asset may carry "
                    'more of the stack than the row allows')
    cfg['risk'] = risk

    # --- the hedges ---------------------------------------------------------------
    hedge = cfg.get('hedge') or {}
    w = f'{where}.hedge'
    if not isinstance(hedge, dict):
        _refuse(f'{w}: an object — {{product, ratio}} for every asset, or {{coin: {{product, ratio}}}}')
    longs = [a['coin'] for a in out if a['weight'] > 0]
    if hedge and all(k in ('product', 'ratio') for k in hedge):
        per = {coin: dict(hedge) for coin in longs}            # one setting for all
    else:
        for coin in hedge:
            if coin not in seen:
                _refuse(f"{w}: {coin} is hedged but not in 'assets' — a hedge covers "
                        'an asset the row holds (an outright short is a negative weight)')
            if coin not in longs and 'ratio' in (hedge.get(coin) or {}):
                _refuse(f"{w}: {coin} is an outright short — it is its own hedge; "
                        "name only its 'product' here")
        per = {coin: dict(hedge.get(coin) or {}) for coin in longs}
    hedges = {}
    for coin, h in per.items():
        hw = f'{w}.{coin}'
        _reject_unknown(h, ('product', 'ratio'), hw)
        product = _enum(h, 'product', hw, PRODUCTS, default='inverse')
        ratio = _num(h, 'ratio', hw, least=0.0, most=3.0)
        hedges[coin] = {'product': product, 'ratio': 1.0 if ratio is None else float(ratio)}
    cfg['hedges'] = hedges
    cfg.pop('hedge', None)
    # H1c: an outright short is a USD-margined perp. An inverse contract is
    # margined in its own coin — the row would have to hold the coin, a long
    # the short exists not to have, and nothing here counts it
    shorts = {}
    for a in out:
        if a['weight'] < 0:
            c = a['coin']
            prod = _enum(hedge.get(c) or {}, 'product', f'{w}.{c}', PRODUCTS, default='usdt')
            if prod == 'inverse':
                _refuse(f"{w}.{c}: an outright short cannot be inverse — an inverse contract is "
                        f"margined in {c} itself, so the row would hold {c}: a long the short "
                        "exists not to have. Name 'usdt' or 'usdc' (H1c)")
            shorts[c] = prod
    cfg['short_products'] = shorts

    # --- the clock -----------------------------------------------------------------
    reb = cfg.get('rebalance') or {}
    w = f'{where}.rebalance'
    if not isinstance(reb, dict):
        _refuse(f'{w}: an object {{every_hours, drift_pct, min_notional}}')
    _reject_unknown(reb, ('every_hours', 'drift_pct', 'min_notional', 'cash_reserve'), w)
    reb['every_hours'] = _num(reb, 'every_hours', w, least=1.0) or 24.0
    reb['drift_pct'] = _fraction(reb, 'drift_pct', w) or 0.05
    reb['min_notional'] = _num(reb, 'min_notional', w, least=0.0) or 0.0
    cr = _fraction(reb, 'cash_reserve', w, zero_means_off=True, most=0.05)
    reb['cash_reserve'] = CASH_RESERVE if cr is None else cr
    cfg['rebalance'] = reb

    # --- the regime tilt (opt-in) ---------------------------------------------------
    regime = cfg.get('regime')
    if regime is not None:
        w = f'{where}.regime'
        if not isinstance(regime, dict):
            _refuse(f'{w}: an object {{tilt, hold_hours, source}}')
        _reject_unknown(regime, ('tilt', 'hold_hours', 'source'), w)
        regime['tilt'] = _fraction(regime, 'tilt', w, most=0.9)
        if regime['tilt'] is None:
            _refuse(f"{w}: 'tilt' is required — how far the hedge leans with the regime")
        hold = _num(regime, 'hold_hours', w, least=1.0)
        if hold is None:
            _refuse(f"{w}: 'hold_hours' is required — a regime change is believed "
                    'only after it has held; a tilt that flips on one reading churns')
        regime['hold_hours'] = hold
        regime['source'] = _enum(regime, 'source', w, ('structure',), default='structure')
        cfg['regime'] = regime

    # --- the funding rule (on by default) ----------------------------------------
    fr = cfg.get('funding_rule')
    w = f'{where}.funding_rule'
    if fr is None:
        fr = {}
    if not isinstance(fr, dict):
        _refuse(f'{w}: an object {{stand_down_below, trailing_days}}')
    _reject_unknown(fr, ('stand_down_below', 'trailing_days'), w)
    sdb = _num(fr, 'stand_down_below', w, least=-1.0, most=1.0)
    fr['stand_down_below'] = 0.0 if sdb is None else sdb
    fr['trailing_days'] = _num(fr, 'trailing_days', w, least=1.0) or 7.0
    cfg['funding_rule'] = fr
    if cfg['venue'] == 'hyperliquid':
        _refuse(f"{where}: the portfolio row trades Bybit — its Hyperliquid leg is "
                'the design\'s step 5, not built (D78)')
    return cfg


def leg_market(coin, product):
    """H2: the market a short leg trades, by product — usdt → linear
    <COIN>USDT, usdc → linear <COIN>PERP, inverse → inverse <COIN>USD."""
    if product == 'inverse':
        return 'inverse', f'{coin}USD'
    return 'linear', f'{coin}USDT' if product == 'usdt' else f'{coin}PERP'


def leg_markets(cfg):
    """Every market a validated row trades: [(kind, coin, market_type,
    symbol, committed)] — the spot stack per long, its hedge, the outright
    shorts; `committed` is the row's quote on that leg at its weights."""
    out = []
    for a in cfg['assets']:
        coin, put = a['coin'], cfg['capital'] * abs(a['weight'])
        if a['weight'] > 0:
            out.append(('spot', coin, 'spot', f"{coin}{cfg['spot_quote']}", put))
            h = cfg['hedges'].get(coin) or {}
            if h.get('ratio', 0) > 0:
                mt, sym = leg_market(coin, h['product'])
                out.append(('hedge', coin, mt, sym, put * h['ratio']))
        else:
            mt, sym = leg_market(coin, cfg['short_products'][coin])
            out.append(('short', coin, mt, sym, put))
    return out


def regime_word(reading):
    """H3: the planner's word from a D67 reading — 'trending up' → up,
    'trending down' → down, anything else (ranging, leaning, unread) →
    range. A lean is not a regime; the tilt waits for the trend."""
    if reading == 'trending up':
        return 'up'
    if reading == 'trending down':
        return 'down'
    return 'range'


def trailing_yield(received, notional, days):
    """H3: the funding rule's figure — what a short received over its
    trailing window as a YEARLY rate on what it covers at mark, so
    `stand_down_below` means the same thing live and rehearsed (a raw
    window sum had no defined units; the review, 2026-10-09). None short of
    a day of history or without a notional: not judged."""
    if not notional or days is None or days < 1.0:
        return None
    return received / notional * (365.0 / days)


def hedge_ratio(cfg, coin, regime=None, funding_trailing=None):
    """H3: the ratio a hedge is held at now — the row's ratio, leaned by the
    regime tilt when the row carries one (up: × (1 − tilt); down: × (1 +
    tilt)), and stood down to zero while the trailing funding to the short
    is below the funding rule's floor."""
    h = cfg['hedges'].get(coin)
    if h is None:
        return 0.0
    ratio = h['ratio']
    tilt = (cfg.get('regime') or {}).get('tilt')
    if tilt and regime == 'up':
        ratio *= (1.0 - tilt)
    elif tilt and regime == 'down':
        ratio *= (1.0 + tilt)
    floor = cfg['funding_rule']['stand_down_below']
    if funding_trailing is not None and funding_trailing < floor:
        return 0.0
    return ratio


def plan_portfolio(cfg, book, prices, now_ms, last_tick_ms, regimes=None,
                   funding_trailing=None):
    """H3: the plan at one moment, pure. `book`: {'coins': {coin: held
    spot coins}, 'hedged': {coin: coins the short covers}, 'shorts':
    {coin: coins short outright}, 'cash': quote received and unspent —
    negative when the venue has lent the row quote (margin, H1)}.
    Between ticks nothing is wanted; at a tick: (1) cash buys spot pro
    rata to the long weights; (2) a long leg past the drift is bought or
    sold to its weight; (3) an outright short past the drift is resized;
    (4) a hedge past the drift is resized to its ratio. Each want is an
    order {'leg': ('spot'|'short'|'hedge', coin), 'side', 'coins',
    'why'}; a want under min_notional is left. Returns {'tick', 'orders',
    'targets'}."""
    reb = cfg['rebalance']
    if last_tick_ms is not None and now_ms - last_tick_ms < reb['every_hours'] * H:
        return {'tick': False, 'orders': [], 'targets': {}}
    regimes, funding_trailing = regimes or {}, funding_trailing or {}
    coins = dict(book.get('coins') or {})
    hedged, shorts = dict(book.get('hedged') or {}), dict(book.get('shorts') or {})
    cash = float(book.get('cash') or 0.0)
    orders, targets = [], {}
    longs = [a for a in cfg['assets'] if a['weight'] > 0]
    outright = [a for a in cfg['assets'] if a['weight'] < 0]
    pos_total = sum(a['weight'] for a in longs)
    # the stack is the row's equity: its coins at mark plus its cash — which
    # is negative when the venue has lent the row quote for a levered stack
    # (H1's margin: the weights then sum to spot_leverage, and each target
    # is weight × equity, so the coins held are spot_leverage × equity)
    stack = sum(coins.get(a['coin'], 0.0) * prices[a['coin']] for a in longs) + cash
    big = reb['min_notional']

    def want(leg, side, qty, price, why):
        if qty <= 0 or qty * price < big:
            return
        orders.append({'leg': leg, 'side': side, 'coins': qty, 'why': why})

    if cash > 0 and pos_total > 0:                                 # (1)
        # toward the weights: each long's shortfall from its target share of
        # the stack (cash included), by shortfall — at the weights that is
        # pro rata (each shortfall is its weight's share of the cash); off
        # them, new money lands where the book is short.
        # A reserve stays for the buys' own fees: spent to the cent, the last
        # buy is refused by the fees of the ones before it. The cash spends
        # the longs' shortfalls only — an outright short's share of the
        # stack is its margin and stays cash
        cash *= (1.0 - reb['cash_reserve'])
        deficit = {a['coin']: max(a['weight'] * stack
                                  - coins.get(a['coin'], 0.0) * prices[a['coin']], 0.0)
                   for a in longs}
        total_def = sum(deficit.values())
        spent = 0.0
        for a in longs:
            c = a['coin']
            spend = (min(cash, total_def) * deficit[c] / total_def if total_def > 0 else 0.0)
            q = spend / prices[c]
            want(('spot', c), 'buy', q, prices[c], 'cash buys spot')
            coins[c] = coins.get(c, 0.0) + q
            spent += spend
        cash -= spent                      # what the shortfalls did not need stays cash
    for a in longs:                                                 # (2)
        c, p = a['coin'], prices[a['coin']]
        target_v = a['weight'] * stack                   # the weights carry the leverage
        have_v = coins.get(c, 0.0) * p
        delta_v = target_v - have_v
        targets[c] = {'weight_value': target_v}
        if abs(delta_v) / max(stack, 1e-9) > reb['drift_pct']:
            q = abs(delta_v) / p
            want(('spot', c), 'buy' if delta_v > 0 else 'sell', q, p, 'weight')
            coins[c] = coins.get(c, 0.0) + (q if delta_v > 0 else -q)
    for a in outright:                                              # (3)
        c, p = a['coin'], prices[a['coin']]
        target_q = abs(a['weight']) * stack / p
        have_q = shorts.get(c, 0.0)
        targets[c] = {'short_coins': target_q}
        if abs(target_q - have_q) * p / max(stack, 1e-9) > reb['drift_pct']:
            want(('short', c), 'sell' if target_q > have_q else 'buy', abs(target_q - have_q), p,
                 'outright short')
    for a in longs:                                                 # (4)
        c, p = a['coin'], prices[a['coin']]
        ratio = hedge_ratio(cfg, c, regimes.get(c), funding_trailing.get(c))
        want_q = ratio * coins.get(c, 0.0)
        have_q = hedged.get(c, 0.0)
        targets[c]['ratio'] = ratio
        targets[c]['hedge_coins'] = want_q
        held_v = coins.get(c, 0.0) * p
        if held_v > 0 and abs(want_q - have_q) * p / held_v > reb['drift_pct']:
            why = ('funding stood the hedge down' if ratio == 0 and cfg['hedges'][c]['ratio'] > 0
                   else 'hedge')
            want(('hedge', c), 'sell' if want_q > have_q else 'buy', abs(want_q - have_q), p, why)
    return {'tick': True, 'orders': orders, 'targets': targets}
