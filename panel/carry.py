"""U148: the Portfolio Bot's rehearsal — the year of the basket the form
describes, worked on the venue's public record before anything is saved.
It was the carry calculator (U69, `/carry`); the owner (2026-11-01): "a
function inside of the creation, so users can see that, like the grid
rehearsal". Each hedge (and outright short) is paid its perpetual's
funding; the loan pays its interest; the fees come off. One function
computes it (`rehearsal`); the form, its live box, its review and the old
`/carry` address all reach it. Display only: nothing here decides or
saves anything, and no venue is read here — the caller hands the rates in.
"""
import html
import json
import re

from common.fmt import float_or

from .html_bits import _num_cls

FEES_PCT = 0.35          # of the stack a year: in and out, and the daily rebalances
LTV_WARN = 0.70          # past this the venue's collateral haircut and the short's margin are close
SENSITIVITY = (0.0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.15)


def rehearsal(cfg, rate, borrow, windows=None, fees_pct=FEES_PCT):
    """The year of a validated portfolio row, in USDT. `rate(market_type,
    symbol, days)`: the yearly funding a short on that market was paid over
    the last `days`, or None (unread); `borrow`: the USDT loan's yearly
    rate, or None. Funding is each short leg's committed USDT times its
    market's rate; the loan is the spot stack past the row's own money;
    fees are `fees_pct` of the spot stack and the outright shorts. A
    window with a leg unread, or a loan with no rate, has no net."""
    from gridgremlin.portfolio import leg_markets
    from panel.carry_setup import WINDOW_DAYS
    windows = tuple(windows or WINDOW_DAYS)
    spot = short = outright = 0.0
    legs = []
    for kind, coin, mt, sym, put in leg_markets(cfg):
        if kind == 'spot':
            spot += put
            continue
        short += put
        outright += put if kind == 'short' else 0.0
        legs.append({'kind': kind, 'coin': coin, 'market_type': mt, 'symbol': sym, 'put': put,
                     'apr': {d: rate(mt, sym, d) for d in windows}})
    own = float(cfg['capital'])
    loan = max(0.0, spot - own)
    interest = 0.0 if loan == 0 else None if borrow is None else loan * borrow
    fees = (spot + outright) * fees_pct / 100

    def year(funding):
        net = None if funding is None or interest is None else funding - interest - fees
        return {'funding': funding, 'net': net,
                'on_own': None if net is None or own <= 0 else net / own}
    years = {}
    for d in windows:
        aprs = [lg['apr'][d] for lg in legs]
        years[d] = year(None if any(a is None for a in aprs)
                        else sum(lg['put'] * a for lg, a in zip(legs, aprs)))
    return {'legs': legs, 'spot': spot, 'short': short, 'outright': outright, 'own': own, 'loan': loan,
            'borrow': borrow, 'interest': interest, 'fees': fees, 'fees_pct': fees_pct,
            'lever': spot / own if own > 0 else None, 'years': years,
            'breakeven': (None if interest is None or short <= 0 else (interest + fees) / short),
            'sensitivity': [(r, year(short * r)) for r in SENSITIVITY]}


def old_query(q):
    """U149: what the old calculator's address (`/carry?coin=&stack=&loan=
    &leg=`) said, as the Portfolio Bot form's values: one coin at the whole
    basket, hedged in full on the perpetual it named, the stack's own part
    as the investment and the rest as spot leverage (1 to 10x). What it
    cannot say is dropped; the windows are the form's own (7 and 30 days)."""
    q = q or {}
    vals = {}
    coin = str(q.get('coin') or '').strip().upper()
    if re.fullmatch(r'[A-Z0-9]{1,15}', coin):
        vals.update(assets=f'{coin} 100', max_weight='100', hedge_ratio='100')
    leg = {'inverse': 'inverse', 'linear': 'usdt'}.get(str(q.get('leg') or ''))
    if leg:
        vals['hedge_product'] = leg
    stack = float_or(q.get('stack'))
    loan = float_or(q.get('loan')) or 0.0
    if stack is not None and stack == stack and 0 < stack < 1e12:
        loan = min(max(0.0, loan if loan == loan else 0.0), stack)
        own, lev = stack - loan, None
        if own > 0:
            lev = stack / own
        if lev is not None and lev <= 10:
            vals['capital'] = f'{own:.2f}'.rstrip('0').rstrip('.')
            if lev > 1:
                vals['spot_leverage'] = f'{lev:.6g}'
    return vals


def _pct(v, digits=2):
    return '<span class="dim">—</span>' if v is None else \
        f'<span class="{_num_cls(v)}">{v * 100:+.{digits}f}%</span>'


def _money(v):
    return '<span class="dim">—</span>' if v is None else f'<span class="{_num_cls(v)}">{v:+,.0f}</span>'


PLACEHOLDER = ('<p class="dim">Type the coins and the investment: the year this basket '
               'would have been paid shows here — the funding on each hedge, the loan\'s '
               'interest, the fees — from the venue\'s public record. Nothing is saved.</p>')


def rehearsal_html(form, read_many, now_ms, reading):
    """The rehearsal of the form as it stands, drawn: the year at 7 and 30
    days, the funding that breaks even, the year at other funding rates,
    then each coin's three perpetuals side by side (the hedge chosen in
    bold). `read_many([(market_type, symbol)])` -> {that: settlements or
    None}; `reading`: the engine's newest market reading (the USDT borrow
    rate), or None. A form the engine would refuse says why, in its words."""
    from gridgremlin.config import ConfigError
    from gridgremlin.portfolio import validate_portfolio
    from panel.carry_setup import (PRODUCT_WORDS, WINDOW_DAYS, _assets, funding_apr,
                                   funding_html, row_from_form)
    if not str(form.get('assets') or '').strip() or not str(form.get('capital') or '').strip():
        return PLACEHOLDER
    try:
        coins = [c for c, _ in _assets(form.get('assets'))]
        row = row_from_form(dict(form, name=str(form.get('name') or '').strip() or 'rehearse'))
        cfg = validate_portfolio(json.loads(json.dumps(row)), 'the basket')
    except (ValueError, ConfigError) as e:
        return f'<p class="dim">not yet: {html.escape(str(e))}</p>'
    wanted = [(mt, sym.format(c=c)) for c in coins for _, mt, sym in PRODUCT_WORDS]
    got = read_many(wanted)

    def rate(mt, sym, days):
        s = got.get((mt, sym))
        return None if s is None else funding_apr(s, now_ms, days)
    carry = (reading or {}).get('carry') or {}
    borrow = (carry.get('borrow_apr') or {}).get('USDT')
    r = rehearsal(cfg, rate, borrow)
    cols = ''.join(f'<th>{d} days</th>' for d in WINDOW_DAYS)

    def line(words, cells, bold=False):
        b0, b1 = ('<b>', '</b>') if bold else ('', '')
        return f'<tr><td>{b0}{words}{b1}</td>' + ''.join(f'<td class="num">{b0}{c}{b1}</td>' for c in cells) + '</tr>'
    rows = ''.join(
        line(f'{html.escape(lg["coin"])} short on {html.escape(lg["symbol"])}, {lg["put"]:,.0f} '
             f'<span class="dim">({"/".join(_pct(lg["apr"][d]) for d in WINDOW_DAYS)} a year)</span>',
             [_money(None if lg['apr'][d] is None else lg['put'] * lg['apr'][d]) for d in WINDOW_DAYS])
        for lg in r['legs'])
    age = ('' if not reading or reading.get('t') is None
           else f', read {max(0, int((now_ms / 1000 - reading["t"]) / 60))} min ago')
    if r['loan'] == 0:
        loan_words = 'no loan'
    elif borrow is None:
        loan_words = f'interest on the loan ({r["loan"]:,.0f}; the USDT borrow rate is not read)'
    else:
        loan_words = f'interest on the loan ({borrow * 100:.2f}% a year on {r["loan"]:,.0f}{age})'
    neg = None if r['interest'] is None else -r['interest']
    rows += line(loan_words, [_money(neg)] * len(WINDOW_DAYS))
    rows += line(f'fees (about {r["fees_pct"]:g}% of {r["spot"] + r["outright"]:,.0f} a year)',
                 [_money(-r['fees'])] * len(WINDOW_DAYS))
    rows += line('net', [_money(r['years'][d]['net']) for d in WINDOW_DAYS], bold=True)
    rows += line(f'on your own {r["own"]:,.0f}' + (f' ({r["lever"]:.1f}× on the spread)' if r['lever'] and r['loan'] else ''),
                 [_pct(r['years'][d]['on_own'], 1) for d in WINDOW_DAYS], bold=True)
    notes = ''
    ltv = r['loan'] / r['spot'] if r['spot'] else 0.0
    if ltv > LTV_WARN:
        notes += (f'<p class="neg">{ltv:.0%} of the stack is borrowed. The venue counts the coin at a '
                  'discount as collateral and the short needs margin of its own: this is close to where '
                  'a move forces a sale. The price cancels in the trade, not in the margin.</p>')
    cap = (cfg.get('margin') or {}).get('borrow_apr_max')
    if r['loan'] and borrow is not None and cap and borrow > cap:
        notes += (f'<p class="neg">The loan costs {borrow * 100:.2f}% a year, above this bot\'s most '
                  f'borrow rate ({cap * 100:.2f}%): while it stays there the engine stands the leverage '
                  'down to 1× (H4). The year above is at the leverage typed.</p>')
    if not r['legs']:
        notes += '<p class="dim">Not hedged: no short is paid funding; the coins carry the price.</p>'
    even = ('' if r['breakeven'] is None else
            f'<p class="dim">Funding that breaks even: {r["breakeven"] * 100:.2f}% a year on the shorts.</p>')
    sens = ('' if not r['legs'] else
            '<table class="cwtab"><tr><th>if funding were, a year</th><th>net</th><th>on your own</th></tr>'
            + ''.join(f'<tr><td>{x * 100:.0f}%</td><td class="num">{_money(y["net"])}</td>'
                      f'<td class="num">{_pct(y["on_own"], 1)}</td></tr>' for x, y in r['sensitivity'])
            + '</table>')
    chosen = {lg['coin']: lg['symbol'] for lg in r['legs']}
    return ('<table class="cwtab"><tr><th>a year at the rate paid over</th>' + cols + '</tr>'
            + rows + '</table>' + notes + even + sens
            + funding_html(coins, lambda mt, sym: got.get((mt, sym)), now_ms, chosen=chosen)
            + '<p class="dim">The past windows are what was paid, not a forecast: funding has run from '
              'below zero to past 10% a year, and the borrow rate rises when everyone borrows. '
              'Nothing is saved; the bot is written only from its review.</p>')
