"""D143: a portfolio row's leverage from the panel — the spot's (its weights
and its loan) and the perps' (its hedges and outright shorts). Pure: the
form, the new row from the old and two numbers, and the change said in
words. The route writes the file; the engine applies it live (F12)."""
import html

from gridgremlin.config import SPOT_LEVERAGE_MOST
from gridgremlin.portfolio import PERP_LEVERAGE_MOST

BORROW_APR_MAX = 0.08        # the gate's own default (H1), written out when a loan first appears


def spot_of(row):
    """The stack's leverage as the file states it: 1 without a margin block."""
    return float((row.get('margin') or {}).get('spot_leverage', 1.0))


def lever_row(row, spot, perp):
    """The row with its stack at `spot`× and its perps at `perp`× (None: the
    file's perp setting as it is). The weights keep their shares and signs
    and sum to `spot`, as H1 has them; the per-asset cap follows them when
    they outgrow it; a loan's block appears when the stack first borrows
    and stays (at 1×) once there. Refuses in words (ValueError)."""
    if not (isinstance(spot, (int, float)) and 1.0 <= spot <= SPOT_LEVERAGE_MOST):
        raise ValueError(f'spot leverage: a number from 1 to {SPOT_LEVERAGE_MOST:g}')
    if perp is not None and not (isinstance(perp, (int, float)) and 1.0 <= perp <= PERP_LEVERAGE_MOST):
        raise ValueError(f'futures leverage: a number from 1 to {PERP_LEVERAGE_MOST:g}, or blank')
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
    if perp is not None:
        new['perp_leverage'] = perp
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
    pa, pb = old.get('perp_leverage'), new.get('perp_leverage')
    if pa != pb:
        out.append(f"Futures: from {('%g×' % pa) if pa else 'what the exchange holds'} to {pb:g}×, "
                   'set on the exchange for every hedge and short at once. On a cross-margin '
                   'account this moves the margin each position sets aside, not when the '
                   'account is liquidated; the account\'s own margin decides that.')
    rb = (new.get('risk') or {}).get('max_weight')
    if rb != (old.get('risk') or {}).get('max_weight'):
        out.append(f'The cap on one coin follows the weights: {rb:g} of the row\'s money.')
    return out


def lever_form(fi, botid, row, gg='1'):
    """The two boxes, as the file has them now, posting to the review."""
    e = html.escape
    perp = row.get('perp_leverage')
    return (f'<h1>{e(botid)} <span class="dim">— leverage</span></h1>'
            '<p class="say">The rest of a portfolio row (its coins, hedges, clock and risk) '
            'is set in its fleet file; its leverage is set here and applied while it runs.</p>'
            f'<form method="post" action="/lever">'
            f'<input type="hidden" name="gg" value="{e(gg)}">'
            f'<input type="hidden" name="fleet" value="{int(fi)}">'
            f'<input type="hidden" name="orig" value="{e(botid, quote=True)}">'
            '<div class="fsec"><label>spot leverage <input name="spot" size="6" '
            f'value="{spot_of(row):g}"></label> '
            f'<span class="dim">1 = no loan; up to {SPOT_LEVERAGE_MOST:g}. The coins held, '
            'as a multiple of the row\'s own money.</span></div>'
            '<div class="fsec"><label>futures leverage <input name="perp" size="6" '
            f'value="{"" if perp is None else f"{perp:g}"}"></label> '
            '<span class="dim">for every hedge and short; blank leaves it as it is'
            + ('' if perp is not None else ' (the exchange\'s own setting today)')
            + '. The exchange\'s ceiling is on the card.</span></div>'
            '<button>review the change</button></form>')
