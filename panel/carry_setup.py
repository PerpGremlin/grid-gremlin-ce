"""U108: the carry bot's setup form — the portfolio row (D78) from the
panel. The owner (2026-10-23): "can we make it so we can create the carry
bots as well?" It was a fleet-file edit only. Pure: form values in, a row
out, and back (a row survives the form unchanged, as U2 for a grid);
percentages travel as Decimal text, so 33.34 % is 0.3334 exactly.
"""
import html
from decimal import Decimal, InvalidOperation

# (form name, the row's path, kind, label, help, required)
ESSENTIAL = (
    ('name', ('name',), 'text', 'Name',
     'yours, one to twelve lower-case letters or digits, like basket. The '
     'panel adds pfo (portfolio) in front: basket becomes pfobasket, the '
     'name you type to save it and see on its card', True),
    ('capital', ('capital',), 'num', 'Investment',
     'the money the basket is built from, in USDT', True),
    ('assets', ('assets',), 'assets', 'Coins and weights',
     'percent of the investment each, like BTC 50, ETH 50 — they add up to '
     '100 (with spot leverage, to the leverage times 100); a minus is an '
     'outright short of that share', True),
    ('hedge_ratio', ('hedge', 'ratio'), 'pct', 'Hedged',
     'percent of each coin held short on its perpetual: 100 = market '
     'neutral (the carry), 0 = no hedge. Blank = 100', False),
    ('hedge_product', ('hedge', 'product'), 'choice:inverse|usdt|usdc',
     'Hedge on', 'inverse = BTCUSD, margined in the coin (the default); '
     'usdt = BTCUSDT; usdc = BTCPERP', False),
    ('perp_leverage', ('perp_leverage',), 'num', 'Perp leverage',
     'set on every hedge at each start; blank = whatever the venue holds', False),
)
ADVANCED = (
    ('spot_borrow', ('spot_borrow',), 'flag', 'Borrow on spot',
     'lets the basket borrow USDT on spot (needed for spot leverage)', False),
    ('spot_leverage', ('margin', 'spot_leverage'), 'num', 'Spot leverage',
     'the spot stack on a loan, 1 to 3x; needs borrow on spot. Blank = none', False),
    ('borrow_apr_max', ('margin', 'borrow_apr_max'), 'pct', 'Most borrow rate',
     'yearly percent; above it the loan is cut back to 1x. Blank = 8', False),
    ('every_hours', ('rebalance', 'every_hours'), 'num', 'Rebalance every (h)',
     'blank = 24', False),
    ('drift_pct', ('rebalance', 'drift_pct'), 'pct', 'Rebalance at drift',
     'percent a weight may drift before the clock acts on it. Blank = 5', False),
    ('min_notional', ('rebalance', 'min_notional'), 'num', 'Smallest trade',
     'in USDT: a rebalance smaller than this is left. Blank = 0', False),
    ('cash_reserve', ('rebalance', 'cash_reserve'), 'pct', 'Cash kept for fees',
     'percent of each buy. Blank = 0.3', False),
    ('regime_tilt', ('regime', 'tilt'), 'pct', 'Regime tilt',
     'percent the hedge leans with the market reading (the tilt fleet ran '
     '30). Blank = no tilt', False),
    ('regime_hold_hours', ('regime', 'hold_hours'), 'num', 'Tilt believed after (h)',
     'a reading must hold this long before the hedge leans; with a tilt, '
     'required', False),
    ('stand_down_below', ('funding_rule', 'stand_down_below'), 'pct',
     'Stand the hedge down below',
     'yearly funding percent; under it the hedge stands down. Blank = 0, '
     '-100 = never', False),
    ('trailing_days', ('funding_rule', 'trailing_days'), 'num',
     'Funding judged over (days)', 'blank = 7', False),
    ('margin_floor_pct', ('risk', 'margin_floor_pct'), 'pct', 'Margin floor',
     'percent of free margin; under it the shorts shrink together. Blank = 40', False),
    ('basis_stop_pct', ('risk', 'basis_stop_pct'), 'pct', 'Basis stop',
     'percent gap between a coin\'s perp and spot that flattens that coin. '
     'Blank = 1', False),
    ('max_weight', ('risk', 'max_weight'), 'pct', 'Most in one coin',
     'percent of the stack. Blank = 50', False),
    ('max_loss', ('risk', 'max_loss'), 'num', 'Most it may lose',
     'in USDT, counted from the moment below; then the basket closes. Blank '
     '= no limit', False),
    ('max_loss_since', ('risk', 'max_loss_since'), 'text', 'Counted from',
     'a UTC time like 2026-10-23T00:00:00Z; goes with the loss limit', False),
)
FIELDS = ESSENTIAL + ADVANCED
_ORDER = ('strategy', 'name', 'venue', 'capital', 'assets', 'hedge', 'rebalance',
          'regime', 'funding_rule', 'risk', 'spot_quote', 'spot_borrow', 'margin',
          'perp_leverage')


def _dec(text, label):
    try:
        return Decimal(str(text).strip().replace(',', ''))
    except InvalidOperation:
        raise ValueError(f'{label}: {text!r} is not a number') from None


def _number(d):
    return int(d) if d == d.to_integral_value() and abs(d) < 10 ** 15 else float(d)


def _assets(text):
    out = []
    for part in [p for p in str(text).replace(';', ',').split(',') if p.strip()]:
        bits = part.split()
        if len(bits) != 2:
            raise ValueError(f'Coins and weights: "{part.strip()}" is not a coin and '
                             'a percent, like BTC 50')
        out.append({'coin': bits[0].upper(),
                    'weight': float(_dec(bits[1].rstrip('%'), bits[0]) / 100)})
    if not out:
        raise ValueError('Coins and weights: name at least one, like BTC 50, ETH 50')
    return out


def missing(form):
    """The required settings left blank, by label, all at once (U105's way)."""
    return [lb for n, _, _, lb, _, req in FIELDS if req and not str(form.get(n) or '').strip()]


def row_from_form(form):
    """The portfolio row the form describes; ValueError in words."""
    miss = missing(form)
    if miss:
        raise ValueError('still needed: ' + '; '.join(miss))
    row = {'strategy': 'portfolio', 'venue': 'bybit'}
    for n, path, kind, label, _, _ in FIELDS:
        raw = form.get(n)
        if kind == 'flag':
            if raw:
                row[path[0]] = True
            continue
        if raw is None or not str(raw).strip():
            continue
        raw = str(raw).strip()
        if kind == 'assets':
            v = _assets(raw)
        elif kind == 'pct':
            v = float(_dec(raw.rstrip('%'), label) / 100)
        elif kind == 'num':
            v = _number(_dec(raw, label))
        elif kind == 'text' and n == 'name':
            v = raw.lower()
        else:
            v = raw
        if len(path) == 1:
            row[path[0]] = v
        else:
            row.setdefault(path[0], {})[path[1]] = v
    if 'regime' in row:
        row['regime'].setdefault('source', 'structure')
    if 'hedge' in row:
        row['hedge'].setdefault('product', 'inverse')
        row['hedge'].setdefault('ratio', 1.0)
    return {k: row[k] for k in _ORDER if k in row}


def form_from_row(row):
    """The form's values for a row (edit, copy, a refused form kept)."""
    hedge = row.get('hedge') or {}
    if any(k not in ('product', 'ratio') for k in hedge):
        raise ValueError('the hedge differs by coin — edit it in the fleet file')
    if row.get('spot_quote', 'USDT') != 'USDT' or row.get('account') or row.get('venue', 'bybit') != 'bybit':
        raise ValueError('a basket on another quote, account or venue is edited in the fleet file')
    vals = {}
    for n, path, kind, _, _, _ in FIELDS:
        v = row.get(path[0])
        if len(path) == 2:
            v = v.get(path[1]) if isinstance(v, dict) else None
        if v is None:
            continue
        if kind == 'assets':
            vals[n] = ', '.join(f"{a['coin']} {_pct(a['weight'])}" for a in v)
        elif kind == 'pct':
            vals[n] = _pct(v)
        elif kind == 'flag':
            vals[n] = '1' if v else ''
        elif kind == 'num' and isinstance(v, dict):
            if len(set(v.values())) != 1:       # one number holds one leverage
                raise ValueError('perp leverage differs by coin — edit it in the fleet file')
            vals[n] = f'{next(iter(v.values())):g}'
        elif kind == 'choice:inverse|usdt|usdc' or kind.startswith('choice:'):
            vals[n] = str(v)
        else:
            vals[n] = f'{v:g}' if isinstance(v, float) else str(v)
    return vals


def _pct(x):
    return format((Decimal(str(x)) * 100).normalize(), 'f')


def sentence(cfg):
    """A validated row in plain words."""
    longs = [a for a in cfg['assets'] if a['weight'] > 0]
    shorts = [a for a in cfg['assets'] if a['weight'] < 0]
    lev = (cfg.get('margin') or {}).get('spot_leverage', 1.0)
    held = ', '.join(f"{a['coin']} {a['weight'] / lev:.0%}" for a in longs)
    hedges = sorted({(h['ratio'], h['product']) for h in cfg['hedges'].values()})
    hedge = ('not hedged' if all(r == 0 for r, _ in hedges) else
             'each held short on its perpetual at ' +
             ', '.join(f'{r:.0%} ({p})' for r, p in hedges))
    out = (f"Buys {held} on spot with {cfg['capital']:g} USDT"
           + (f' at {lev:g}x on a loan' if lev > 1 else '') + f', {hedge}. '
           f"Rebalances every {cfg['rebalance']['every_hours']:g} h, or when a "
           f"weight drifts {cfg['rebalance']['drift_pct']:.0%}.")
    if shorts:
        out += ' Outright short: ' + ', '.join(f"{a['coin']} {-a['weight']:.0%}" for a in shorts) + '.'
    if cfg.get('regime'):
        out += (f" The hedge leans {cfg['regime']['tilt']:.0%} with the market "
                f"reading once it has held {cfg['regime']['hold_hours']:g} h.")
    if cfg['risk'].get('max_loss'):
        out += f" Closes everything if down {cfg['risk']['max_loss']:g} USDT."
    return out


def _input(n, kind, value):
    v = html.escape(str(value or ''), quote=True)
    if kind == 'flag':
        return f'<input type="checkbox" name="{n}" value="1"{" checked" if value else ""}>'
    if kind.startswith('choice:'):
        opts = ''.join(f'<option{" selected" if o == value else ""}>{o}</option>'
                       for o in [''] + kind[7:].split('|'))
        return f'<select name="{n}">{opts}</select>'
    size = 34 if kind == 'assets' else 22 if n == 'max_loss_since' else 12
    return f'<input name="{n}" size="{size}" value="{v}">'


def carry_page(values, fleets, chosen=0, alert=''):
    """The form: what the basket needs first, every other setting folded."""
    from panel.setup import fleet_select

    def rows(fs):
        return ''.join(
            f'<tr><td>{html.escape(lb)}{" *" if req else ""}</td>'
            f'<td>{_input(n, kind, values.get(n))}</td>'
            f'<td class="dim">{html.escape(hp)}</td></tr>'
            for n, _, kind, lb, hp, req in fs)
    adv_open = any(str(values.get(n) or '').strip() for n, *_ in ADVANCED)
    return (
        alert +
        '<h1>set up a carry bot <span class="dim">— coins on spot, each held '
        'short on its perpetual, the funding collected (D78). Bybit only. '
        'Nothing is saved until you have read the summary and typed the '
        'bot\'s name.</span></h1>'
        '<form method="post" action="/setup-carry">'
        '<input type="hidden" name="gg" value="1">'
        '<div class="fsec"><h1 class="dim">What the bot needs</h1><table>'
        f'<tr><td>Account *</td><td>{fleet_select(fleets, chosen)}</td>'
        '<td class="dim">which fleet the bot joins; it trades that account\'s '
        'spot and perps, so no other bot there may use its coins\' markets</td></tr>'
        + rows(ESSENTIAL) + '</table></div>'
        f'<details class="adv"{" open" if adv_open else ""}><summary>Advanced</summary>'
        '<div class="fsec"><table>' + rows(ADVANCED) + '</table></div></details>'
        '<button>Next: review the bot &rarr;</button></form>'
        '<p class="dim">* needed. A blank takes the engine\'s default.</p>')
