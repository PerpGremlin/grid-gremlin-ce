# What if the price moves (§11, U9): one straight move from today's price,
# and what the bot would then hold, what that is worth, and the margin in
# use.
#
# The SERVER answers: the orders are the engine's own plan at the mark
# (plan_grid, martingale_schedule) and the money is the adapter's own
# (realised_pnl), so the answer cannot disagree with the engine. The
# page's script only reads the slider and asks. Public data only, no key.
#
# What it is not: a forecast or a backtest. A straight move has no bounces,
# so a grid earns nothing on the way; the rehearsal answers that question.
import html

from gridgremlin.ladder import slide_offset, stop_level_for

STEPS = (-0.30, -0.20, -0.10, -0.05, 0.05, 0.10, 0.20, 0.30)
SLIDER_MAX = 50                    # percent either way


def entries(cfg, adapter, mark):
    """The bot's opening orders at this mark, nearest first: [(price, qty)].
    A grid: the entry side of the engine's plan from flat. A DCA bot: its
    first order at the mark, then each add-on."""
    if cfg['strategy'] == 'martingale':
        from panel.create import martingale_preview
        rows, _ = martingale_preview(cfg, mark)
        return [(r['price'], adapter.qty_from_notional(r['notional'],
                                                       r['price']))
                for r in rows]
    from panel.create import dry_ladder
    got = [(o['price'], o['qty']) for o in dry_ladder(cfg, adapter, mark)
           if not o['reduce_only']]
    return sorted(got, key=lambda e: abs(e[0] - mark))


def _stop(cfg, mark):
    stop = cfg.get('stop') or {}
    if stop.get('watch') != 'mark_price':
        return None
    if stop.get('from_base_pct') is not None:   # X10: the first order is
        sign = -1.0 if cfg['side'] == 'long' else 1.0     # at the mark
        return mark * (1.0 + sign * stop['from_base_pct'])
    return (stop_level_for(cfg) if cfg['strategy'] == 'grid'
            else stop.get('level'))


def _targets(cfg):
    """[(fraction above the average, share of the position)]."""
    tr = cfg.get('take_profit_tranches')
    if tr:
        return [(t['at_avg_pct'], t['share']) for t in tr]
    return [(cfg['take_profit_avg_pct'], 1.0)]


def whatif(cfg, adapter, ladder, mark, move):
    """One straight move of `move` (a fraction, signed) from `mark`.
    `ladder` is entries(). Returns the facts; words() says them. With a
    loss limit (X14) the move ends where the loss first reaches it: found
    by bisection on the same function, so it holds for every market type."""
    out = _whatif(cfg, adapter, ladder, mark, move)
    limit = cfg.get('max_loss')
    if not limit or -out['pnl'] < limit:
        return out                  # no limit, or a stop ended it sooner
    lo, hi = 0.0, move
    for _ in range(50):
        mid = (lo + hi) / 2.0
        if -_whatif(cfg, adapter, ladder, mark, mid)['pnl'] >= limit:
            hi = mid
        else:
            lo = mid
    at = _whatif(cfg, adapter, ladder, mark, hi)
    out.update(filled=at['filled'], held=0.0, avg=None, cost=0.0, value=0.0,
               margin=0.0, pnl=-limit, stopped_at=None,
               loss_limit_at=mark * (1.0 + hi), follows=None)
    return out


def _whatif(cfg, adapter, ladder, mark, move):
    long = cfg['side'] == 'long'
    sign = 1.0 if long else -1.0
    price = mark * (1.0 + move)
    adverse = (price < mark) if long else (price > mark)
    out = {'move': move, 'price': price, 'orders': len(ladder), 'filled': 0,
           'held': 0.0, 'avg': None, 'cost': 0.0, 'value': 0.0, 'pnl': 0.0,
           'margin': 0.0, 'stopped_at': None, 'took_profit_at': None,
           'loss_limit_at': None,
           'follows': None, 'outside': False}
    stop = _stop(cfg, mark)
    end = price
    if stop is not None and adverse and (price <= stop if long
                                         else price >= stop):
        end, out['stopped_at'] = stop, stop

    def crossed(p):
        if p == mark:                       # a DCA bot's first order
            return cfg['strategy'] == 'martingale'
        if not adverse:
            return False
        return (end <= p < mark) if long else (mark < p <= end)
    fills = [(p, q) for p, q in ladder if crossed(p)]
    out['filled'] = len(fills)
    lev = float(cfg.get('leverage') or 1.0)
    pnl = 0.0
    if cfg['strategy'] == 'martingale' and not adverse and fills:
        # the favourable way: only the first order is in; each target the
        # price reaches sells its share at that target
        p0, q0 = fills[0]
        left = 1.0
        for pct, share in _targets(cfg):
            target = p0 * (1.0 + sign * pct)
            if (price >= target) if long else (price <= target):
                pnl += sign * adapter.pnl_to_usd(
                    adapter.realised_pnl(p0, target, q0 * share), target)
                left -= share
                out['took_profit_at'] = target
        fills = [(p0, q0 * left)] if left > 1e-12 else []
    left_open = (out['stopped_at'] is not None and (cfg.get('stop') or {})
                 .get('action') == 'leave_position')
    if left_open:
        end = price            # X13: the bot stops; the position rides on
    for p, q in fills:
        pnl += sign * adapter.pnl_to_usd(adapter.realised_pnl(p, end, q),
                                         end)
    if (out['stopped_at'] is None or left_open) and fills:
        inverse = cfg['market_type'] == 'inverse'
        held = sum(q for _, q in fills)
        cost = sum(q if inverse else p * q for p, q in fills)
        out['held'] = held
        out['cost'] = cost
        out['avg'] = (held / sum(q / p for p, q in fills) if inverse
                      else cost / held)
        out['value'] = cost + sign * pnl
        out['margin'] = cost / lev
    out['pnl'] = pnl
    if cfg['strategy'] == 'grid':
        if cfg.get('slide') and slide_offset(cfg, 0, price) != 0:
            out['follows'] = 'up' if price > mark else 'down'
        out['outside'] = not (cfg['lower'] <= price <= cfg['upper'])
    return out


def _m(v):
    a = abs(v)
    if a >= 1000:
        return f'{v:,.0f}'
    if a >= 1:
        return f'{v:,.2f}'.rstrip('0').rstrip('.')
    return f'{v:.4g}'


def _signed(v):
    return ('+' if v >= 0 else '-') + _m(abs(v))


def _coin(cfg):
    return 'contracts' if cfg['market_type'] == 'inverse' else 'coins'


def words(cfg, r):
    """The answer in plain words, from whatif()'s facts."""
    long = cfg['side'] == 'long'
    way = 'rises' if r['move'] > 0 else 'falls'
    s = [f"If the price {way} {abs(r['move']):.0%} to {_m(r['price'])}:"]
    grid = cfg['strategy'] == 'grid'
    if r['loss_limit_at'] is not None:
        s.append(f"its loss limit of {_m(cfg['max_loss'])} is reached at "
                 f"{_m(r['loss_limit_at'])}, with {r['filled']} of its "
                 f"{r['orders']} orders filled. It closes everything "
                 f"({-cfg['max_loss'] / cfg['capital']:+.1%} of the "
                 'investment) and stops for good.')
        return ' '.join(s)
    if r['stopped_at'] is not None and r['held']:
        s.append(f"the stop loss fires at {_m(r['stopped_at'])} and the bot "
                 'switches off, but the position stays open: '
                 f"{_m(r['held'])} {_coin(cfg)} at an average of "
                 f"{_m(r['avg'])}, {_signed(r['pnl'])} "
                 f"({r['pnl'] / cfg['capital']:+.1%} of the "
                 'investment) at this price and still moving, unprotected.')
        return ' '.join(s)
    if r['stopped_at'] is not None:
        s.append(f"the stop loss fires at {_m(r['stopped_at'])}. By then "
                 f"{r['filled']} of its {r['orders']} orders filled; "
                 f"it closes everything for about {_signed(r['pnl'])} "
                 f"({r['pnl'] / cfg['capital']:+.1%} of the "
                 'investment) and '
                 + ('starts a new round.' if (cfg.get('stop') or {}).get(
                     'action') == 'end_round' else 'stops for good.'))
        return ' '.join(s)
    if r['took_profit_at'] is not None:
        s.append(f"it takes profit at {_m(r['took_profit_at'])}, about "
                 f"{_signed(r['pnl'])}"
                 + ('.' if not r['held'] else
                    f", and still holds {_m(r['held'])} {_coin(cfg)}."))
        if cfg.get('repeat') and not r['held']:
            s.append('Then it starts again from the new price.')
        return ' '.join(s)
    if not r['held']:
        s.append('it holds nothing: the price moved away from its '
                 f"{'buy' if long else 'sell'} orders, and it started "
                 'with none filled.')
    else:
        s.append(f"{r['filled']} of its {r['orders']} "
                 f"{'buy' if long else 'sell'} orders filled. It "
                 f"{'holds' if long else 'is short'} {_m(r['held'])} "
                 f"{_coin(cfg)} at an average of {_m(r['avg'])}, worth "
                 f"{_m(r['value'])} now: {_signed(r['pnl'])} "
                 f"({r['pnl'] / cfg['capital']:+.1%} of the "
                 f"investment). {_m(r['margin'])} of margin is in use.")
    if r['follows']:
        adverse = (r['follows'] == 'down') == long
        s.append(f"The range follows the price {r['follows']}"
                 + (', and following the losing way buys more than is '
                    'counted here.' if adverse and grid else '.'))
    elif grid and r['outside']:
        s.append('The price is outside the range, so the bot waits for it '
                 'to come back.')
    if grid and r['held'] and r['filled'] == r['orders'] and not cfg.get(
            'stop'):
        s.append('Every order is in and there is no stop loss: a further '
                 'move costs the full position.')
    return ' '.join(s)


def table(cfg, adapter, ladder, mark):
    rows = []
    for move in STEPS:
        r = whatif(cfg, adapter, ladder, mark, move)
        if r['loss_limit_at'] is not None:
            state = f"loss limit at {_m(r['loss_limit_at'])}"
        elif r['stopped_at'] is not None:
            state = f"stopped at {_m(r['stopped_at'])}"
        elif r['took_profit_at'] is not None:
            state = 'took profit'
        elif r['follows']:
            state = f"follows {r['follows']}"
        else:
            state = ''
        cls = 'pos' if r['pnl'] > 0 else ('neg' if r['pnl'] < 0 else 'dim')
        rows.append(
            f"<tr><td>{move:+.0%}</td><td>{_m(r['price'])}</td>"
            f"<td>{r['filled']} of {r['orders']}</td>"
            f"<td>{_m(r['held']) if r['held'] else '-'}</td>"
            f"<td>{_m(r['value']) if r['held'] else '-'}</td>"
            f"<td>{_m(r['margin']) if r['held'] else '-'}</td>"
            f'<td class="{cls}">{_signed(r["pnl"]) if r["pnl"] else "-"}'
            f'</td><td class="dim">{state}</td></tr>')
    return ('<table><tr><th>price moves</th><th>to</th><th>orders filled'
            f'</th><th>holds ({_coin(cfg)})</th><th>worth</th>'
            '<th>margin in use</th><th>gain / loss</th><th></th></tr>'
            + ''.join(rows) + '</table>')


def answer(cfg, adapter, ladder, mark, move):
    """The fragment the slider swaps in: one move, in words."""
    return ('<p class="say">'
            + html.escape(words(cfg, whatif(cfg, adapter, ladder, mark,
                                            move))) + '</p>')


def section(cfg, adapter, mark, bot_json, fleet, move=None):
    """The whole block for the summary page: slider, answer, table. The
    slider opens 10% the losing way: the question worth asking first."""
    if move is None:
        move = -0.10 if cfg['side'] == 'long' else 0.10
    ladder = entries(cfg, adapter, mark)
    notes = ''
    if (cfg.get('stop') or {}).get('watch') not in (None, 'mark_price'):
        notes += (' Its stop loss does not watch this price, so it is not '
                  'counted.')
    if cfg.get('seed'):
        notes += ' The opening purchase is not counted.'
    bj = html.escape(bot_json, quote=True)
    return (
        '<h1 class="dim">what if the price moves</h1>'
        '<form id="whatif" method="post" action="/whatif">'
        '<input type="hidden" name="gg" value="1">'
        f'<input type="hidden" name="fleet" value="{fleet}">'
        f'<input type="hidden" name="bot_json" value="{bj}">'
        f'<input type="hidden" name="mark" value="{mark:.10g}">'
        f'<input type="range" name="move" min="-{SLIDER_MAX}" '
        f'max="{SLIDER_MAX}" step="1" value="{move * 100:.0f}" '
        'style="width:30em;max-width:100%"> '
        f'<output>{move:+.0%}</output></form>'
        f'<div id="whatif-answer">{answer(cfg, adapter, ladder, mark, move)}'
        '</div>' + table(cfg, adapter, ladder, mark) +
        '<p class="dim">one straight move from today\'s price, starting '
        'with nothing held. No bounces, so no grid profit is counted on '
        'the way; fees and funding are left out. Not a forecast.'
        + notes + '</p>' + WHATIF_JS)


# The whole script: read the slider, ask the server, show its words. The
# newest answer wins; no price or money is computed here.
WHATIF_JS = """<script>(function(){
var form=document.getElementById('whatif');if(!form)return;
var box=document.getElementById('whatif-answer');
var slider=form.querySelector('[name="move"]');
var out=form.querySelector('output'),asked=0;
slider.addEventListener('input',function(){
 var mine=++asked,v=slider.value;
 out.textContent=(v>0?'+':'')+v+'%';
 fetch('/whatif',{method:'POST',credentials:'same-origin',
  body:new URLSearchParams(new FormData(form))})
 .then(function(r){return r.text();})
 .then(function(t){if(mine===asked)box.innerHTML=t;});});
form.addEventListener('submit',function(e){e.preventDefault();});
})();</script>"""
