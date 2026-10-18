"""D143: a portfolio row's leverage from the panel — the spot's (its weights
and its loan) and the perps' (its hedges and outright shorts). Pure: the
form, the new row from the old and two numbers, and the change said in
words. The route writes the file; the engine applies it live (F12)."""
import html
import json

from gridgremlin.config import SPOT_LEVERAGE_MOST
from gridgremlin.portfolio import PERP_LEVERAGE_MOST, validate_portfolio

BORROW_APR_MAX = 0.08        # the gate's own default (H1), written out when a loan first appears


def spot_of(row):
    """The stack's leverage as the file states it: 1 without a margin block."""
    return float((row.get('margin') or {}).get('spot_leverage', 1.0))


def perps_of(row):
    """The row's perps by coin, in its assets' order, and the leverage the
    file gives each ({coin: x}; absent, the venue's own) — as the gate
    reads them."""
    cfg = validate_portfolio(json.loads(json.dumps(row)))
    coins = [a['coin'] for a in cfg['assets']
             if (a['weight'] > 0 and cfg['hedges'].get(a['coin'], {}).get('ratio', 0) > 0) or a['weight'] < 0]
    return coins, cfg.get('perp_leverage') or {}


def lever_row(row, spot, perp):
    """The row with its stack at `spot`× and its perps at `perp`, {coin: x}
    (a coin left out: the file's setting for it as it is). The weights keep their shares and signs
    and sum to `spot`, as H1 has them; the per-asset cap follows them when
    they outgrow it; a loan's block appears when the stack first borrows
    and stays (at 1×) once there. Refuses in words (ValueError)."""
    if not (isinstance(spot, (int, float)) and 1.0 <= spot <= SPOT_LEVERAGE_MOST):
        raise ValueError(f'spot leverage: a number from 1 to {SPOT_LEVERAGE_MOST:g}')
    perp = perp or {}
    coins, had = perps_of(row)
    for c, x in perp.items():
        if c not in coins:
            raise ValueError(f'{c}: no hedge or short in this row')
        if not (isinstance(x, (int, float)) and 1.0 <= x <= PERP_LEVERAGE_MOST):
            raise ValueError(f'futures leverage for {c}: a number from 1 to {PERP_LEVERAGE_MOST:g}, or blank')
    new = {k: (dict(v) if isinstance(v, dict) else v) for k, v in row.items()}
    assets = [dict(a) for a in row.get('assets') or []]
    total = sum(abs(float(a['weight'])) for a in assets)
    if not total:
        raise ValueError('the row has no weights to scale')
    f = spot / total
    for a in assets:
        a['weight'] = round(float(a['weight']) * f, 6)
    last = assets[-1]
    rest = sum(abs(a['weight']) for a in assets[:-1])
    last['weight'] = round((spot - rest) * (1 if last['weight'] > 0 else -1), 6)
    new['assets'] = assets
    risk = dict(row.get('risk') or {})
    cap = risk.get('max_weight', 0.5)
    biggest = max(abs(a['weight']) for a in assets)
    if biggest > cap + 1e-9:
        risk['max_weight'] = round(min(cap * f if cap * f >= biggest else biggest, 10.0), 6)
        new['risk'] = risk
    if spot > 1.0 or row.get('margin'):
        new['spot_borrow'] = True
        new['margin'] = dict(row.get('margin') or {'borrow_apr_max': BORROW_APR_MAX}, spot_leverage=spot)
    if perp:
        new['perp_leverage'] = {c: perp.get(c, had.get(c)) for c in coins
                                if perp.get(c, had.get(c)) is not None}
    return new


def said(old, new):
    """The change in plain words, one line each."""
    out = []
    a, b = spot_of(old), spot_of(new)
    if a != b:
        out.append(f'Spot: from {a:g}× to {b:g}×. The coins held move to {b:g} times the '
                   'row\'s own money at the next read (within a minute), bought with '
                   + ('a bigger loan' if b > a else 'less of the loan, the sales repaying it')
                   + '; each hedge follows its coin.')
        if not old.get('margin') and new.get('margin'):
            out.append(f'This row has not borrowed before: it may now, at up to '
                       f'{new["margin"]["borrow_apr_max"]:.0%} a year before its leverage stands down (H4).')
    coins, pa = perps_of(old)
    _, pb = perps_of(new)
    moved = [c for c in coins if pa.get(c) != pb.get(c)]
    if moved:
        out.append('Futures: ' + '; '.join(
            f"{c} from {('%g×' % pa[c]) if c in pa else 'what the exchange holds'} to {pb[c]:g}×"
            for c in moved) + '. Set on the exchange first, each coin checked against what '
            'the exchange allows at its size; if one is refused, those already changed are put '
            'back. On a cross-margin account this moves the margin each position sets aside, '
            'not when the account is liquidated; the account\'s own margin decides that.')
    rb = (new.get('risk') or {}).get('max_weight')
    if rb != (old.get('risk') or {}).get('max_weight'):
        out.append(f'The cap on one coin follows the weights: {rb:g} of the row\'s money.')
    return out


def lever_form(fi, botid, row, gg='1'):
    """The boxes, as the file has them now, posting to the review: one for
    the spot, one for each coin's perp."""
    e = html.escape
    coins, had = perps_of(row)
    boxes = ''.join(
        f'<label>{e(c)} <input name="perp_{e(c)}" size="5" '
        f'value="{"" if c not in had else f"{had[c]:g}"}"></label> ' for c in coins)
    return (f'<h1>{e(botid)} <span class="dim">— leverage</span></h1>'
            '<p class="say">The rest of a portfolio row (its coins, hedges, clock and risk) '
            'is set in its fleet file; its leverage is set here and applied while it runs.</p>'
            f'<form method="post" action="/lever">'
            f'<input type="hidden" name="gg" value="{e(gg)}">'
            f'<input type="hidden" name="fleet" value="{int(fi)}">'
            f'<input type="hidden" name="orig" value="{e(botid, quote=True)}">'
            '<div class="fsec"><label>spot leverage <input name="spot" size="6" '
            f'value="{spot_of(row):g}"></label> '
            f'<span class="dim">one for every coin: 1 = no loan; up to {SPOT_LEVERAGE_MOST:g}. '
            'The coins held, as a multiple of the row\'s own money.</span></div>'
            + (f'<div class="fsec">futures leverage, each coin: {boxes}'
               '<span class="dim">blank leaves that coin as it is (the exchange\'s own '
               'setting when the file names none). The most each allows at its size '
               'is checked before anything is sent.</span></div>' if coins else '')
            + '<button>review the change</button></form>')
