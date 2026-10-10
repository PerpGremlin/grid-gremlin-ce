"""U69: the carry page — a leveraged basis trade worked on the newest
reading (K12): hold the coin, partly bought with a USDT loan, and short the
same value of its perpetual. The price cancels; what is left is the funding
a short is paid, less the loan's interest and the fees. Display only, from
the readings file; no venue is read here and nothing here decides anything."""
import html
import time

from gridgremlin.fmt import float_or

from .render import _num_cls

WINDOWS = (('last', 'last settlement'), ('d7', '7 days'), ('d30', '30 days'), ('d90', '90 days'))
FEES_PCT = 0.35          # of the stack a year: in and out, and the daily rebalances
LTV_WARN = 0.70          # past this the venue's collateral haircut and the short's margin are close


def _f(v, default):
    """A typed amount, or the default when it is not a sane number."""
    x = float_or(v)
    return x if x is not None and x == x and abs(x) < 1e12 else default


def year_of(stack, loan, funding_apr, borrow_apr, fees_pct=FEES_PCT):
    """The year of a carry trade, in the quote coin: the funding the short is
    paid on the stack, the interest on the loan, the fees; the net, on the
    owner's own money (stack − loan), and the funding that breaks even."""
    funding = stack * funding_apr
    interest = loan * borrow_apr
    fees = stack * fees_pct / 100
    net = funding - interest - fees
    own = stack - loan
    return {'funding': funding, 'interest': interest, 'fees': fees, 'net': net, 'own': own,
            'on_own': net / own if own > 0 else None,
            'breakeven': (interest + fees) / stack if stack > 0 else None,
            'lever': stack / own if own > 0 else None}


def _pct(v, digits=2):
    return '—' if v is None else f'<span class="{_num_cls(v)}">{v * 100:+.{digits}f}%</span>'


def _money(v):
    return f'<span class="{_num_cls(v)}">{v:+,.0f}</span>'


def carry_page(row, q=None, now=None):
    """The calculator (the owner's example by default: a 100,000 stack, 85,000
    of it borrowed, BTC hedged on the inverse perpetual, the 90-day funding),
    what the year looks like at other funding rates, then every coin read."""
    q = q or {}
    now = time.time() if now is None else now
    head = '<h1>carry</h1>'
    c = (row or {}).get('carry')
    if not c:
        return head + ('<p class="dim">no carry reading yet — the hourly market job adds it '
                       '(logs/market.jsonl)</p>')
    coins = list(c.get('funding') or {})
    coin = q.get('coin') if q.get('coin') in coins else ('BTC' if 'BTC' in coins else (coins or [''])[0])
    leg = q.get('leg') if q.get('leg') in ('inverse', 'linear') else 'inverse'
    win = q.get('window') if q.get('window') in dict(WINDOWS) else 'd90'
    stack = max(0.0, _f(q.get('stack'), 100_000.0))
    loan = min(max(0.0, _f(q.get('loan'), 85_000.0)), stack)
    borrow = (c.get('borrow_apr') or {}).get('USDT')
    legs = (c.get('funding') or {}).get(coin) or {}
    if leg not in legs and legs:
        leg = 'linear' if 'linear' in legs else next(iter(legs))
    fapr = (legs.get(leg) or {}).get(win)
    age = max(0, int((now - row['t']) / 60))
    opts = ''.join(f'<option{" selected" if x == coin else ""}>{html.escape(x)}</option>' for x in coins)
    def sel(name, pairs, cur):
        return (f'<select name="{name}">' + ''.join(
            f'<option value="{k}"{" selected" if k == cur else ""}>{w}</option>' for k, w in pairs) + '</select>')
    form = ('<form method="get" action="/carry" class="carryform">'
            f'<label>coin <select name="coin">{opts}</select></label>'
            f'<label>stack <input name="stack" value="{stack:.0f}" inputmode="decimal" size="9"></label>'
            f'<label>borrowed <input name="loan" value="{loan:.0f}" inputmode="decimal" size="9"></label>'
            f'<label>short on {sel("leg", (("inverse", "the inverse perpetual"), ("linear", "the USDT perpetual")), leg)}</label>'
            f'<label>funding over {sel("window", WINDOWS, win)}</label>'
            '<button>work it out</button></form>')
    intro = (f'<p class="dim">Hold {html.escape(coin)} worth the stack, part of it bought with a USDT loan, and short '
             'the same value of its perpetual. The price cancels: the coin and the short move against each other. '
             f'What is left is the funding a short is paid, less the loan\'s interest and the fees. Reading {age} min old; '
             'Bybit\'s public rates.</p>')
    if borrow is None or fapr is None:
        missing = 'the USDT borrow rate' if borrow is None else f'{coin}\'s {leg} funding over {dict(WINDOWS)[win]}'
        return head + intro + form + f'<p class="neg">not read: {missing}</p>' + coin_table(c, loan / stack if stack else 0.0)
    y = year_of(stack, loan, fapr, borrow)
    ltv = loan / stack if stack else 0.0
    warn = (f'<p class="neg">{ltv:.0%} of the stack is borrowed. The venue counts the coin at a discount as '
            'collateral and the short needs margin of its own: this is close to where a move forces a sale. '
            'The price cancels in the trade, not in the margin.</p>' if ltv > LTV_WARN else '')
    year = ('<h2>a year at these rates</h2><table class="cwtab">'
            f'<tr><td>funding the short is paid ({dict(WINDOWS)[win]}: {fapr * 100:+.2f}% a year on {stack:,.0f})</td><td>{_money(y["funding"])}</td></tr>'
            f'<tr><td>interest on the loan ({borrow * 100:.2f}% a year on {loan:,.0f})</td><td>{_money(-y["interest"])}</td></tr>'
            f'<tr><td>fees (about {FEES_PCT:g}% of the stack a year)</td><td>{_money(-y["fees"])}</td></tr>'
            f'<tr><td><b>net</b></td><td><b>{_money(y["net"])}</b></td></tr>'
            f'<tr><td>on your own {y["own"]:,.0f} ({y["lever"] or 0:.1f}× on the spread)</td><td><b>{_pct(y["on_own"], 1)}</b></td></tr>'
            f'<tr><td>funding that breaks even</td><td>{(y["breakeven"] or 0) * 100:.2f}% a year</td></tr></table>')
    rates = (0.0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.15)
    sens = ('<h2>if funding were different</h2><table class="cwtab"><tr><th>funding a year</th><th>net</th><th>on your own</th></tr>'
            + ''.join(f'<tr><td>{r * 100:.0f}%</td><td>{_money(year_of(stack, loan, r, borrow)["net"])}</td>'
                      f'<td>{_pct(year_of(stack, loan, r, borrow)["on_own"], 1)}</td></tr>' for r in rates)
            + '</table><p class="dim">Funding is the year\'s unknown: it has run from below zero to past 10% a year; '
              'the borrow rate rises when everyone borrows, usually when funding is high too. The past windows are '
              'what was paid, not a forecast.</p>')
    return head + intro + form + warn + year + sens + coin_table(c, ltv)


def coin_table(c, ltv):
    """Every coin read: what each perpetual paid a short, the coin's own
    borrow rate, and the spread over the USDT loan at this loan share."""
    borrow = c.get('borrow_apr') or {}
    usdt = borrow.get('USDT')
    rows = ''
    for coin, legs in (c.get('funding') or {}).items():
        for leg in ('inverse', 'linear'):
            v = legs.get(leg)
            if not v:
                continue
            if v.get('unread'):
                rows += f'<tr><td>{html.escape(coin)}</td><td>{leg}</td><td colspan="6" class="dim">unread</td></tr>'
                continue
            spread = (None if v.get('d90') is None or usdt is None
                      else v['d90'] - ltv * usdt - FEES_PCT / 100)
            rows += (f'<tr><td>{html.escape(coin)}</td><td>{leg}'
                     + (f' <span class="dim">every {v["every_h"]:g} h</span>' if v.get('every_h') not in (None, 8) else '')
                     + '</td>' + ''.join(f'<td class="num">{_pct(v.get(k))}</td>' for k, _ in WINDOWS)
                     + f'<td class="num">{_pct(spread)}</td></tr>')
    return ('<h2>every coin read <span class="dim">funding a short was paid, a year</span></h2>'
            f'<p class="dim">USDT borrows at {"—" if usdt is None else f"{usdt * 100:.2f}%"} a year. '
            f'Net is the 90 days less the loan at this page\'s share ({ltv:.0%}) and the fees, on the stack.</p>'
            '<div class="scroll"><table class="cwtab"><tr><th>coin</th><th>short on</th>'
            + ''.join(f'<th>{w}</th>' for _, w in WINDOWS) + '<th>net, 90 days</th></tr>'
            + rows + '</table></div>'
            + '<p class="dim">Coins\' own borrow rates (to short the coin on margin instead): '
            + ' · '.join(f'{html.escape(k)} {v * 100:.2f}%' for k, v in sorted(borrow.items()) if k not in ('USDT', 'USDC'))
            + '.</p><p class="dim">10.95% a year is 0.01% every 8 hours — the resting rate a perpetual pays when '
              'its price sits on the index, so many coins read exactly that at a settlement. Display only — no bot reads this.</p>')
