"""One position's page (U56): the exchange's view first, then the price, then the full card. Out of render.py (D91 step 3)."""
from .card import _plain_name, card
from .drawings import price_boxes
from .html_bits import REFRESH_S, coin_of, units_of


def exchange_table(botid, b, belief, terms):
    """U56 (the owner: "reads the data directly shown from the position
    when viewed in the Bybit dashboard"): the position as the exchange's
    own panel lays it out — symbol, side, size, value, entry, mark,
    liquidation, margin, leverage, open and closed P&L — from the readout's
    book and the engine's snapshot of the venue's margin (V14/V17)."""
    bl = belief.get(botid) or {}
    mv = bl.get('margin') or {}
    money_coin, margin_coin = units_of(botid, terms)
    pos = (b or {}).get('position') if b else bl.get('position')
    mark = (b or {}).get('mark')
    side = 'short' if botid.endswith('s') else 'long'
    symbol = (terms or {}).get('symbol') or botid[3:-1]

    def n(v, f=',.6g'):
        return '—' if v is None else f'{v:{f}}'
    inverse = bool((b or {}).get('inverse'))
    qty = None if pos is None else abs(pos)
    value = None if qty is None or not mark else (qty if inverse else qty * mark)
    fmt = ',.2f' if margin_coin in ('USDT', 'USDC', 'USD') else ',.6g'
    rows = [('symbol', symbol), ('side', side.upper()),
            ('size', f"{n(qty)} {'USD' if inverse else coin_of(botid)}"),
            ('value', f'{n(value, ",.2f")} {money_coin}'),
            ('entry price', n((b or {}).get('avg_cost') or None)),
            ('mark price', n(mark)),
            ('liq. price', n(mv.get('liq'))),
            ('initial margin', f"{n(mv.get('im'), fmt)} {margin_coin}" if mv.get('im') is not None else '—'),
            ('maint. margin', f"{n(mv.get('mm'), fmt)} {margin_coin}" if mv.get('mm') is not None else '—'),
            ('leverage', f"{mv['leverage']:g}×" if mv.get('leverage') else '—'),
            ('unrealised P&amp;L', f"{n((b or {}).get('unreal_at_mark'), '+,.2f')} {money_coin}"),
            ('realised, after fees', f"{n(((b or {}).get('realized') or 0) - ((b or {}).get('fees') or 0), '+,.2f')} {money_coin}"
                                      if b else '—'),
            ('funding', f"{n((b or {}).get('funding'), '+,.2f')} {money_coin}" if b else '—')]
    return ('<div class="scroll"><table class="xch"><tr>' + ''.join(f'<th>{k}</th>' for k, _ in rows) + '</tr><tr>'
            + ''.join(f'<td>{v}</td>' for _, v in rows) + '</tr></table></div>')


def position_page(idx, label, botid, contract, belief, prices=None, fills=()):
    """U56: one position, one page — the exchange's view first, then the
    price with its levels and fills (U65), then the card with every number
    laid open."""
    terms = (contract.get('terms') or {}).get(botid)
    b = (contract.get('bots') or {}).get(botid)
    xch = ('' if (terms or {}).get('strategy') == 'portfolio'
           else f'<h3>as the exchange shows it</h3>{exchange_table(botid, b, belief, terms)}')
    if (terms or {}).get('strategy') != 'portfolio':
        rng = (contract.get('ranges') or {}).get(botid)
        off = (belief.get(botid) or {}).get('offset')
        if rng and off and rng.get('rungs', 0) > 1:
            gap = (rng['upper'] - rng['lower']) / (rng['rungs'] - 1)
            rng = dict(rng, lower=rng['lower'] + off * gap, upper=rng['upper'] + off * gap)
        liq = ((belief.get(botid) or {}).get('margin') or {}).get('liq')
        xch += price_boxes(prices, rng, liq, fills)
    return (f'<meta name="gg-refresh" content="{REFRESH_S}">'      # U68: live, in place
            f'<h1>{label} · {_plain_name(botid, contract, b) if (terms or {}).get("strategy") != "portfolio" else botid[3:] + " portfolio"}</h1>'
            f'{xch}<div class="cards one">{card(idx, botid, b, contract, belief, full=True)}</div>'
            '<p><a href="/">&larr; fleet</a></p>')
