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
     'each coin\'s share of the basket, like BTC 50, ETH 50 (or BTC 1, ETH 1: '
     'the same); the panel scales them to the whole basket, spot leverage '
     'included. A minus is an outright short of that share', True),
    ('hedge_ratio', ('hedge', 'ratio'), 'pct', 'Hedged',
     'percent of each coin held short on its perpetual: 100 = market '
     'neutral (the carry), 0 = no hedge. Blank = 100', False),
    ('hedge_product', ('hedge', 'product'), 'choice:inverse|usdt|usdc',
     'Hedge on', 'inverse = BTCUSD, margined in the coin (the default); '
     'usdt = BTCUSDT; usdc = BTCPERP', False),
    ('hedge_each', ('hedge', '*'), 'products', 'Hedge some coins on',
     'a coin on another perpetual than the one above, like SOL usdt, SUI '
     'usdc — the funding table below the form compares them. Blank = every '
     'coin on the one above', False),
    ('perp_leverage', ('perp_leverage',), 'num', 'Perp leverage',
     'set on every hedge at each start; blank = whatever the venue holds', False),
)
ADVANCED = (
    ('spot_borrow', ('spot_borrow',), 'flag', 'Borrow on spot',
     'lets the basket borrow USDT on spot (spot leverage turns it on)', False),
    ('spot_leverage', ('margin', 'spot_leverage'), 'num', 'Spot leverage',
     'the spot stack on a loan, 1 to 10x: 5 buys five times the investment '
     'in coins. Blank = none', False),
    ('borrow_apr_max', ('margin', 'borrow_apr_max'), 'pct', 'Most borrow rate',
     'yearly percent; above it the loan is cut back to 1x. Blank = 8', False),
    ('trigger', ('rebalance', 'trigger'), 'choice:clock|drift|either', 'Rebalance when',
     'clock = every so many hours, moving only what has drifted past the '
     'drift (the default); drift = whenever a weight or hedge drifts past it, '
     'checked at every read; either = both', False),
    ('every_hours', ('rebalance', 'every_hours'), 'num', 'Rebalance every (h)',
     'the clock, for clock or either. Blank = 24', False),
    ('drift_pct', ('rebalance', 'drift_pct'), 'pct', 'Drift',
     'percent a weight or hedge may drift before it is traded back. Blank = 5', False),
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
     'percent of the basket. Blank = 50', False),
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
    """[(coin, share as Decimal)] — shares in any units; row_from_form
    scales them to the stack (U108b: BTC 0.5, ETH 0.5 was read as 1 %)."""
    out = []
    for part in [p for p in str(text).replace(';', ',').split(',') if p.strip()]:
        bits = part.split()
        if len(bits) != 2:
            raise ValueError(f'Coins and weights: "{part.strip()}" is not a coin and '
                             'a percent, like BTC 50')
        out.append((bits[0].upper(), _dec(bits[1].rstrip('%'), bits[0])))
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
        elif kind == 'products':
            v = _products(raw)
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
    # U108b: the shares fill the stack — the investment times the spot
    # leverage — whatever units they were typed in; the most in one coin
    # is a share of the basket, scaled the same way
    lev = Decimal(str((row.get('margin') or {}).get('spot_leverage', 1)))
    if 'margin' in row:
        row['spot_borrow'] = True                    # a loan needs the right (D24)
    shares = row.get('assets') or []
    total = sum(abs(sh) for _, sh in shares)
    if not total:
        raise ValueError('Coins and weights: the shares add up to nothing')
    row['assets'] = [{'coin': c, 'weight': float(sh / total * lev)} for c, sh in shares]
    if lev != 1:
        mw = (row.get('risk') or {}).get('max_weight', 0.5)
        row.setdefault('risk', {})['max_weight'] = float(Decimal(str(mw)) * lev)
    if 'regime' in row:
        row['regime'].setdefault('source', 'structure')
    each = (row.get('hedge') or {}).pop('*', None)
    if 'hedge' in row:
        row['hedge'].setdefault('product', 'inverse')
        row['hedge'].setdefault('ratio', 1.0)
    if each:
        # a coin on another perp: the hedge is written per coin, every long
        # named with the one ratio (a coin left out would read 100 %)
        longs = [a['coin'] for a in row['assets'] if a['weight'] > 0]
        stray = sorted(set(each) - set(longs))
        if stray:
            raise ValueError(f"Hedge some coins on: {', '.join(stray)} is not a coin the basket holds")
        h = row.get('hedge') or {'product': 'inverse', 'ratio': 1.0}
        row['hedge'] = {c: {'product': each.get(c, h['product']), 'ratio': h['ratio']} for c in longs}
    return {k: row[k] for k in _ORDER if k in row}


def _products(text):
    """{coin: product} from "SOL usdt, SUI usdc"."""
    out = {}
    for part in [p for p in str(text).replace(';', ',').split(',') if p.strip()]:
        bits = part.split()
        if len(bits) != 2 or bits[1].lower() not in ('inverse', 'usdt', 'usdc'):
            raise ValueError(f'Hedge some coins on: "{part.strip()}" is not a coin and '
                             'inverse, usdt or usdc, like SOL usdt')
        out[bits[0].upper()] = bits[1].lower()
    return out


def form_from_row(row):
    """The form's values for a row (edit, copy, a refused form kept)."""
    hedge = row.get('hedge') or {}
    each = {}
    if any(k not in ('product', 'ratio') for k in hedge):
        # per coin: one ratio for all, the products the form can say
        ratios = {float((h or {}).get('ratio', 1.0)) for h in hedge.values()}
        if len(ratios) != 1:
            raise ValueError('the hedge ratio differs by coin — edit it in the fleet file')
        prods = [(c, (h or {}).get('product', 'inverse')) for c, h in hedge.items()]
        common = max(sorted({p for _, p in prods}), key=lambda p: sum(q == p for _, q in prods))
        each = {c: p for c, p in prods if p != common}
        row = dict(row, hedge={'product': common, 'ratio': ratios.pop()})
    if row.get('spot_quote', 'USDT') != 'USDT' or row.get('account') or row.get('venue', 'bybit') != 'bybit':
        raise ValueError('a basket on another quote, account or venue is edited in the fleet file')
    lev = Decimal(str((row.get('margin') or {}).get('spot_leverage', 1)))
    vals = {'hedge_each': ', '.join(f'{c} {p}' for c, p in each.items())} if each else {}
    for n, path, kind, _, _, _ in FIELDS:
        if kind == 'products':
            continue
        v = row.get(path[0])
        if len(path) == 2:
            v = v.get(path[1]) if isinstance(v, dict) else None
        if v is None:
            continue
        if kind == 'assets':
            vals[n] = ', '.join(f"{a['coin']} {_pct(Decimal(str(a['weight'])) / lev)}" for a in v)
        elif n == 'max_weight':
            vals[n] = _pct(Decimal(str(v)) / lev)
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
    d = (Decimal(str(x)) * 100).quantize(Decimal('1e-8')).normalize()
    return format(d, 'f')


def sentence(cfg):
    """A validated row in plain words."""
    longs = [a for a in cfg['assets'] if a['weight'] > 0]
    shorts = [a for a in cfg['assets'] if a['weight'] < 0]
    lev = (cfg.get('margin') or {}).get('spot_leverage', 1.0)
    held = ', '.join(f"{a['coin']} {a['weight'] / lev:.0%}" for a in longs)
    hedges = sorted({(h['ratio'], h['product']) for h in cfg['hedges'].values()})
    by = {}
    for c, h in cfg['hedges'].items():
        by.setdefault((h['ratio'], h['product']), []).append(c)
    hedge = ('not hedged' if all(r == 0 for r, _ in hedges) else
             'each held short on its perpetual at ' +
             ', '.join(f'{r:.0%} ({p}' + (f": {', '.join(by[(r, p)])}" if len(hedges) > 1 else '') + ')'
                       for r, p in hedges))
    reb = cfg['rebalance']
    when = {'drift': f"Rebalances whenever a weight or hedge drifts {reb['drift_pct']:.0%}, "
                     'checked at every read.',
            'either': f"Rebalances every {reb['every_hours']:g} h, and between whenever a "
                      f"weight or hedge drifts {reb['drift_pct']:.0%}."}.get(
        reb.get('trigger', 'clock'),
        f"Rebalances every {reb['every_hours']:g} h, trading back what has drifted "
        f"{reb['drift_pct']:.0%}.")
    out = (f"Buys {held} on spot with {cfg['capital']:g} USDT"
           + (f' at {lev:g}x on a loan' if lev > 1 else '') + f', {hedge}. ' + when)
    if shorts:
        out += ' Outright short: ' + ', '.join(f"{a['coin']} {-a['weight']:.0%}" for a in shorts) + '.'
    if cfg.get('regime'):
        out += (f" The hedge leans {cfg['regime']['tilt']:.0%} with the market "
                f"reading once it has held {cfg['regime']['hold_hours']:g} h.")
    if cfg['risk'].get('max_loss'):
        out += f" Closes everything if down {cfg['risk']['max_loss']:g} USDT."
    return out


def _input(n, kind, value, fixed=False):
    v = html.escape(str(value or ''), quote=True)
    if fixed:
        return f'<input name="{n}" size="12" value="{v}" readonly>'
    if kind == 'flag':
        return f'<input type="checkbox" name="{n}" value="1"{" checked" if value else ""}>'
    if kind.startswith('choice:'):
        opts = ''.join(f'<option{" selected" if o == value else ""}>{o}</option>'
                       for o in [''] + kind[7:].split('|'))
        return f'<select name="{n}">{opts}</select>'
    size = 34 if kind in ('assets', 'products') else 22 if n == 'max_loss_since' else 12
    return f'<input name="{n}" size="{size}" value="{v}">'


def carry_page(values, fleets, chosen=0, alert='', edit=None):
    """The form: what the basket needs first, every other setting folded.
    `edit`: the running bot's id — its fleet and name fixed (U111)."""
    from panel.setup import fleet_select
    edit = edit or values.get('edit') or None

    def rows(fs):
        return ''.join(
            f'<tr><td>{html.escape(lb)}{" *" if req else ""}</td>'
            f'<td>{_input(n, kind, values.get(n), fixed=bool(edit) and n == "name")}</td>'
            f'<td class="dim">{html.escape(hp)}</td></tr>'
            for n, _, kind, lb, hp, req in fs)
    adv_open = any(str(values.get(n) or '').strip() for n, *_ in ADVANCED)
    title = (f'<h1>edit {html.escape(edit)} <span class="dim">— its coins, hedges, clock and '
             'risk. A coin is not taken out here, nor a held coin moved to another perpetual: '
             'its coins and short would be left with nothing managing them. The running bot '
             'takes the change at its fleet\'s restart.</span></h1>' if edit else
             '<h1>set up a carry bot <span class="dim">— coins on spot, each held '
             'short on its perpetual, the funding collected (D78). Bybit only. '
             'Nothing is saved until you have read the summary and typed the '
             'bot\'s name.</span></h1>')
    where = (f'<input type="hidden" name="fleet" value="{chosen}">'
             f'<input type="hidden" name="edit" value="{html.escape(edit, quote=True)}">' if edit else
             f'<tr><td>Account *</td><td>{fleet_select(fleets, chosen)}</td>'
             '<td class="dim">which fleet the bot joins; it trades that account\'s '
             'spot and perps, so no other bot there may use its coins\' markets</td></tr>')
    return (
        alert + title +
        '<form method="post" action="/setup-carry">'
        '<input type="hidden" name="gg" value="1">' + (where if edit else '') +
        '<div class="fsec"><h1 class="dim">What the bot needs</h1><table>'
        + ('' if edit else where)
        + rows(ESSENTIAL) + '</table></div>'
        f'<details class="adv"{" open" if adv_open else ""}><summary>Advanced</summary>'
        '<div class="fsec"><table>' + rows(ADVANCED) + '</table></div></details>'
        '<button>Next: review the bot &rarr;</button></form>'
        '<p class="dim">* needed. A blank takes the engine\'s default.</p>')


PRODUCT_WORDS = (('inverse', 'inverse', '{c}USD'), ('usdt', 'linear', '{c}USDT'), ('usdc', 'linear', '{c}PERP'))
WINDOW_DAYS = (7, 30)


def funding_apr(rates, now_ms, days):
    """The yearly funding a short is paid over the last `days`, from the
    market's own settlements [(time_ms, rate)] — summed, so a market that
    settles hourly and one that settles 8-hourly compare alike. None when
    the window holds nothing."""
    got = [r for t, r in rates if t > now_ms - days * 86_400_000]
    return sum(got) * 365.0 / days if got else None


def funding_html(coins, read, now_ms):
    """U111: each coin's perpetuals side by side — what a short on each was
    paid a year, over 7 and 30 days, from the venue's public record —
    beside the choice of where to hedge. `read(market_type, symbol)` gives
    the settlements, or None when the market cannot be read (no such
    market, the venue down): a dash, never a guess."""
    if not coins:
        return ''
    head = ('<tr><th rowspan="2">coin</th>'
            + ''.join(f'<th colspan="{len(WINDOW_DAYS)}">{p}</th>' for p, _, _ in PRODUCT_WORDS)
            + '</tr><tr>' + ''.join(f'<th>{d} d</th>' for _ in PRODUCT_WORDS for d in WINDOW_DAYS) + '</tr>')
    body = []
    for c in coins:
        cells = []
        for _, mt, sym in PRODUCT_WORDS:
            rates = read(mt, sym.format(c=c))
            for d in WINDOW_DAYS:
                v = None if rates is None else funding_apr(rates, now_ms, d)
                cells.append('<td class="dim">—</td>' if v is None else
                             f'<td class="{"pos" if v > 0 else "neg" if v < 0 else ""}">{v * 100:+.2f}%</td>')
        body.append(f'<tr><td>{html.escape(c)}</td>{"".join(cells)}</tr>')
    return ('<div class="fsec"><h1 class="dim">Funding a short was paid, a year</h1>'
            f'<table class="fund">{head}{"".join(body)}</table>'
            '<p class="dim">inverse = COINUSD, margined in the coin; usdt = COINUSDT; usdc = '
            'COINPERP. From Bybit\'s public record of each market\'s settlements, summed over '
            'the window and scaled to a year: the past, not a promise. A dash: no such market, '
            'or it could not be read.</p></div>')
