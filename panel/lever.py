"""D143: a portfolio row's leverage from the panel — the spot's (its weights
and its loan) and the perps' (its hedges and outright shorts). Pure: the
form, the new row from the old and two numbers, and the change said in
words. The route writes the file; the engine applies it live (F12)."""
import html
import json

from gridgremlin.config import SPOT_LEVERAGE_MOST
from gridgremlin.portfolio import PERP_LEVERAGE_MOST, borrowed_split, keep_stack_move, validate_portfolio

BORROW_APR_MAX = 0.08        # the gate's own default (H1), written out when a loan first appears
SNAP_FRESH_S = 600           # U135: keep the coins is offered only on a snapshot this young (the card's own)
KEEP_DRIFT = 0.05            # U135: at the write, the reviewed money may differ from the newest by this much


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


def bot_snapshot(fleet_path, botid, now=None):
    """U135: the bot's portfolio block in the engine's newest snapshot and
    the snapshot's time — (view, t) — or (None, the reason in words). The
    snapshot is the one file the engine writes each minute; the review
    reads nothing else."""
    import time
    from pathlib import Path
    from gridgremlin.equity_series import snapshot_path
    path = snapshot_path(fleet_path)
    if not path:
        return None, 'this fleet names no snapshot file'
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2)
            f.seek(max(f.tell() - 262144, 0))
            last = [ln for ln in f.read().decode('utf-8', 'replace').splitlines() if ln.strip()][-1]
        snap = json.loads(last)
    except (OSError, ValueError, IndexError):
        return None, f'its snapshot ({Path(path).name}) could not be read'
    now = time.time() if now is None else now
    age = now - float(snap.get('t') or 0)
    view = ((snap.get('bots') or {}).get(botid) or {}).get('portfolio')
    if age > SNAP_FRESH_S:
        return None, f"the engine's newest snapshot is {age / 60:,.0f} minutes old (is the fleet running?)"
    if not view:
        return None, "the engine's newest snapshot has no figures for this bot"
    return view, float(snap['t'])


def keep_numbers(view, new_row):
    """U135, pure: what keeping the coins at the new row's leverage moves,
    from the engine's own snapshot of the bot — the same function the
    engine books with (H18). {stack, before, after, moved, outside,
    outside_after}; moved > 0 frees money to the account's own. Refuses in
    words (ValueError)."""
    stack, value, out = view.get('stack_value'), view.get('value'), view.get('outside_cash')
    if out is None:
        raise ValueError("the running engine does not report the account's spare money yet "
                         '(it is older than this choice): restart the fleet on this version first')
    if not stack or stack <= 0:
        raise ValueError('the bot holds no coins, so there is nothing to keep: grow the position instead')
    if value is None:
        raise ValueError("the engine's snapshot has no value for this bot")
    long_w = sum(float(a['weight']) for a in new_row['assets'] if float(a['weight']) > 0)
    moved = keep_stack_move(value, stack, long_w)
    if moved < 0 and out + moved < -1e-6:
        raise ValueError(f"keeping the coins at {spot_of(new_row):g}× needs {-moved:,.2f} from the "
                         f"account's spare money, which holds {out:,.2f}. Pick a leverage nearer "
                         'the one it has, or grow the position instead')
    return {'stack': stack, 'before': value, 'after': value - moved, 'moved': moved,
            'outside': out, 'outside_after': out + moved}


def keep_row(new_row, numbers):
    """U135: the leveraged row, keeping the coins: `terms_move` beside the
    new capital — the bot's own money after the move — for the engine to
    book once (H18)."""
    return dict(new_row, capital=round(numbers['after'], 2), terms_move='keep_stack')


def keep_said(numbers, quote='USDT', t=None):
    """U135: the review's figures, before the typed name: the stack, the
    bot's money, the money moved and which way, the account's spare after."""
    import time
    n, e = numbers, html.escape
    way = ("from the bot to the account's spare money" if n['moved'] >= 0
           else "from the account's spare money into the bot")
    when = (f"the engine's snapshot of {time.strftime('%H:%M:%S UTC', time.gmtime(t))}"
            if t else "the engine's newest snapshot")
    rows = [('Stack (the coins, at the price)', n['stack'], n['stack']),
            ("The bot's own money", n['before'], n['after']),
            ("The account's spare money", n['outside'], n['outside_after'])]
    return ('<div class="fsec"><table><tr><th></th><th>now</th><th>after</th></tr>'
            + ''.join(f'<tr><td>{e(k)}</td><td>{a:,.2f} {e(quote)}</td><td>{b:,.2f} {e(quote)}</td></tr>'
                      for k, a, b in rows)
            + f'</table><p class="say">Money moved: <b>{abs(n["moved"]):,.2f} {e(quote)}</b> {way}. '
            'It is booked as money taken out of (or put into) the bot, never as a profit or a loss. '
            "Nothing is bought or sold, and nothing moves on the exchange, so the account's free "
            'margin and the margin floor read as they did.</p>'
            f'<p class="dim">From {when}. The engine books its own read at the next minute, '
            'so the figures move a little with the price.</p></div>')


def grow_said(view, new_row, quote='USDT'):
    """U135: growing, the stack before and after at the bot's money now
    (the snapshot's), when a fresh one is there; nothing moves."""
    e = html.escape
    long_w = sum(float(a['weight']) for a in new_row['assets'] if float(a['weight']) > 0)
    stack, value = view.get('stack_value') or 0.0, view.get('value') or 0.0
    return (f'<p class="say">Stack (the coins, at the price): {stack:,.2f} {e(quote)} now, about '
            f'{long_w * value:,.2f} {e(quote)} after; the bot\'s own money stays {value:,.2f} {e(quote)}.</p>')


def account_html(view, quote='USDT'):
    """U136: the account as the venue holds it, from the engine's last
    wallet read: each spot coin and stablecoin, the part the bot treats as
    its own, and the account's own beside it (H13's `outside_cash`). Coins
    above the bot's own get a line: the bot leaves them alone and the venue
    counts them toward the account's margin (D76). Empty for an engine
    that does not report the wallet."""
    if 'wallet_coins' not in view:
        return ''
    e = html.escape
    spot, rows, notes = view.get('spot') or {}, '', []
    for c, bal in sorted((view.get('wallet_coins') or {}).items()):
        own = (spot.get(c) or {}).get('coins') or 0.0
        rows += f'<tr><td>{e(c)}</td><td>{bal:,.8g}</td><td>{own:,.8g}</td><td>{bal - own:,.8g}</td></tr>'
        if bal - own > 1e-9:
            notes.append(f"{bal - own:,.8g} {c} in the wallet are not the bot's: it leaves them alone, "
                         "and the exchange counts them toward the account's margin.")
    out = view.get('outside_cash')
    rows += (f'<tr><td>{e(quote)}</td><td>{view.get("wallet_quote") or 0.0:,.2f}</td>'
             f'<td>{view.get("cash") or 0.0:,.2f}</td>'
             f'<td>{"—" if out is None else format(out, ",.2f")}</td></tr>')
    for c, bal in sorted((view.get('stables') or {}).items()):
        if c != quote:
            rows += f'<tr><td>{e(c)}</td><td>{bal:,.2f}</td><td>0</td><td>{bal:,.2f}</td></tr>'
            notes.append(f"{bal:,.2f} {c} in the wallet are not the bot's: it leaves them alone, "
                         "and the exchange counts them toward the account's margin.")
    return ('<div class="fsec"><h1 class="dim">the account, as the exchange holds it</h1>'
            '<table><tr><th>coin</th><th>in the wallet</th><th>the bot\'s own</th>'
            '<th>the account\'s own</th></tr>' + rows + '</table>'
            + ''.join(f'<p class="say">{e(n)}</p>' for n in notes)
            + '<p class="dim">From the engine\'s last read of the wallet. A minus is borrowed: the '
            "bot's own quote below zero is what it has borrowed.</p></div>")


def borrowed_html(view, cash_after=None, wallet_after=None, quote='USDT'):
    """U137: the bot's borrowed in two — from the account's spare quote,
    and the exchange's real loan — the engine's own split now and, given
    the cash and wallet after a change, after. Empty for an engine that
    does not report it."""
    if 'borrowed_spare' not in view:
        return ''
    e = html.escape
    now = (view['borrowed_spare'], view['borrowed_venue'])
    after = (borrowed_split(max(-cash_after, 0.0), wallet_after)
             if cash_after is not None and wallet_after is not None else None)
    head = '<tr><th>borrowed</th><th>now</th>' + ('<th>after</th>' if after else '') + '</tr>'
    rows = ''.join(f'<tr><td>{e(k)}</td><td>{a:,.2f} {e(quote)}</td>'
                   + (f'<td>{b:,.2f} {e(quote)}</td>' if after else '') + '</tr>'
                   for k, a, b in (("from the account's spare " + quote, now[0], (after or now)[0]),
                                   ("the exchange's real loan", now[1], (after or now)[1])))
    return ('<div class="fsec"><table>' + head + rows + '</table><p class="dim">The bot\'s borrowed is '
            'both together. The spare part is the account\'s own money the bot stands on, which the '
            'exchange lends nothing for and charges no interest on; the real loan is what the '
            'wallet is below zero (the bot\'s part of it).</p></div>')


def said(old, new):
    """The change in plain words, one line each."""
    out = []
    a, b = spot_of(old), spot_of(new)
    if a != b and new.get('terms_move') == 'keep_stack':
        out.append(f'Spot: from {a:g}× to {b:g}×, keeping the coins. The stack stays as it is; '
                   f"the bot's own money becomes the stack divided by {b:g}, and the difference "
                   + ("goes to the account's spare money" if b > a else "comes from the account's spare money")
                   + ' at the next read (within a minute).')
    elif a != b:
        out.append(f'Spot: from {a:g}× to {b:g}×. The coins held move to {b:g} times the '
                   'row\'s own money at the next read (within a minute), bought with '
                   + ('a bigger loan' if b > a else 'less of the loan, the sales repaying it')
                   + '; each hedge follows its coin.')
        if not old.get('margin') and new.get('margin'):
            out.append(f'This row has not borrowed before: it may now, at up to '
                       f'{new["margin"]["borrow_apr_max"]:.0%} a year before its leverage stands down.')
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


def lever_form(fi, botid, row, gg='1', account=''):
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
            f'value="{spot_of(row):g}"></label> ' + account +
            f'<span class="dim">one for every coin: 1 = no loan; up to {SPOT_LEVERAGE_MOST:g}. '
            'The coins held, as a multiple of the row\'s own money.</span></div>'
            + ('<div class="fsec">a new spot leverage: '
               '<label><input type="radio" name="how" value="grow" checked> <b>grow the position</b> '
               "<span class=\"dim\">the same money; the coins become the leverage × the bot's money</span></label> "
               '<label><input type="radio" name="how" value="keep"> <b>keep the coins, free up money</b> '
               "<span class=\"dim\">the stack stays; the bot's money becomes the stack ÷ the leverage, the "
               "difference moved to (or, lowering it, from) the account's spare money</span></label></div>"
               if row.get('margin') else '')
            + (f'<div class="fsec">futures leverage, each coin: {boxes}'
               '<span class="dim">blank leaves that coin as it is (the exchange\'s own '
               'setting when the file names none). The most each allows at its size '
               'is checked before anything is sent.</span></div>' if coins else '')
            + '<button>review the change</button></form>')
