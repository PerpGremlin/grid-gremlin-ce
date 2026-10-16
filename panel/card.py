"""A bot's card (U68 slim, U56 full) and a portfolio's (H6), with the lines a card is made of. Out of render.py (D91 step 3)."""
from common.fmt import signed
from gridgremlin.report import card_total
from .reference import STATE_WORDS
from .drawings import strip
from .html_bits import _day, _num_cls, coin_of, esc, money, pick_link, qarg, units_of


def run_rate(b, contract, capital=None, trade=False):
    """U64: what every grid product states — how long the bot has run in
    the figure's own span, its grid profit per day, and that as a yearly
    rate on its investment. Bybit's way: grid profit / investment / days x
    365, a run under a day counted as one day. Grid profit is the matched
    trips' (R12's gap figure: each exit against its own lot) after fees —
    the second audit, 2026-10-13: average-cost realised read -2,031/day on
    a long grid whose trips made +3,817/day; a bot with no matched trip (a
    DCA, a trade) keeps realised. The run starts at the later of the span's
    start and the first fill (a bot 38 minutes old read "1.0 d"). Returns
    the line, or '' without fills or a span."""
    gen = contract.get('generated_ms')
    how = b.get('counted_from')
    start = (b.get('counted_since_ms') if how == 'flat' else
             b.get('first_ms') if how == 'cap' else
             gen - contract.get('window_hours', 24) * 3.6e6 if gen else None)
    if not gen or not start or not b.get('fills'):
        return ''
    if b.get('first_ms'):
        start = max(start, b['first_ms'])
    days = max(1.0, (gen - start) / 8.64e7)
    shown = (gen - start) / 8.64e7
    gross = b['gap_realized'] if b.get('gap_trips') and b.get('gap_realized') is not None else b['realized']
    net = gross - b['fees']
    per_day = net / days
    if abs(per_day) < 0.005:                 # never "−0.00" (the bug hunt, 2026-10-11)
        per_day = 0.0
    run = f'{shown:.1f} d' if shown >= 1 else f'{shown * 24:.0f} h'
    word = '' if trade else 'grid '          # a trade (D81) or a DCA has no grid
    line = (f'running {run} · {word}profit <b class="{_num_cls(per_day)}">{per_day:+,.2f}</b>/day')
    if capital:
        apr = net / capital / days * 365 * 100
        apr = 0.0 if abs(apr) < 0.05 else apr
        line += f' · {word}APR <b class="{_num_cls(apr)}">{apr:+,.1f}%</b>'
    return f'<div class="rate">{line}</div>'


def settle(b, floor):
    """Stop now and you receive: the number every user reaches for and
    nobody ships. Position sold at mark, less the venue-shaped fee —
    an estimate and labelled as one."""
    if abs(b['position']) < 1e-12 or not b['mark']:
        return '<span class="dim">flat</span>'
    if b.get('inverse'):            # A4: a contract is one dollar
        quote = abs(b['position']) * (1.0 - (floor or 0.0))
    else:
        quote = abs(b['position']) * b['mark'] * (1.0 - (floor or 0.0))
    return f'~{quote:,.2f} quote'


def ladder_box(idx, botid, terms, open_=False):
    """U52 (the 3Commas summary box, owner: "what am I actually risking
    with this row"): a DCA card folds a table of its ladder — each step's
    fill, size, total committed, average entry and the bounce take-profit
    then needs — and says, in one line, the drop the ladder covers. From
    the contract's terms; percentages, so true before a round and after."""
    rows = (terms or {}).get('ladder')
    if not rows:
        return ''
    def pct(v):
        return '—' if v is None else f'{v * 100:+.2f}%'
    def amount(v):
        # U76: one format down a column — two decimals, or significant
        # figures for an amount under one (a coin-sized ladder, D89)
        return f'{v:,.2f}' if abs(v) >= 1 else f'{v:.6g}'
    last = rows[-1]
    body = ''.join(
        f'<tr><td>{"base" if r["step"] == 0 else r["step"]}</td>'
        f'<td>{pct(r["fill_pct"])}</td><td>{amount(r["notional"])}</td>'
        f'<td>{amount(r["committed"])}</td><td>{pct(r["avg_pct"])}</td>'
        f'<td>{pct(r["to_tp_pct"])}</td></tr>' for r in rows)
    return (f'<details{" open" if open_ else ""} data-k="{idx}:{esc(botid)}:ladder"><summary>the ladder: '
            f'covers a move of <b>{pct(last["fill_pct"])}</b>, then '
            f'{amount(last["committed"])} committed at an average of '
            f'{pct(last["avg_pct"])}</summary><table class="ladder"><tr><th>step</th>'
            '<th>fills at</th><th>size</th><th>committed</th><th>average</th>'
            f'<th>to take-profit</th></tr>{body}</table>'
            '<div class="dim">from the base price; size and committed in '
            f'{esc((terms or {}).get("quote") or "quote")}</div></details>')


def kind_line(terms):
    """U36 (owner: "a lay person may just see a dca bot and not understand
    the mathematics of leverage and martingale-style mechanics"): what kind
    of thing this bot is, in one line — the market, the leverage, and for a
    DCA whether its add-ons grow — with a hover on the one word that needs
    one. None when the contract does not say."""
    if not terms or not terms.get('market_type'):
        return None
    mt = terms['market_type']
    market = {'linear': 'futures, USDT/USDC-margined',
              'inverse': 'futures, coin-margined (inverse)',
              'spot': 'spot'}.get(mt, mt)
    if mt == 'spot' and terms.get('spot_borrow'):
        market = 'spot on margin (borrowed)'
    lev = terms.get('leverage') or 1.0
    lev_s = (f'{lev:g}x leverage' if lev != 1 else
             ('no leverage' if mt == 'spot' else '1x, no leverage'))
    if terms.get('trade'):                                          # L6 (D81)
        parts = [f"take profit +{terms['tp_pct'] * 100:g}%" if terms.get('tp_pct') else 'take profit in tranches']
        if terms.get('stop_pct'):
            parts.append(f"stop −{terms['stop_pct'] * 100:g}% at the mark")
        if terms.get('trail_pct'):
            parts.append(f"trailing {terms['trail_pct'] * 100:g}%")
        who = (f" · opened {terms['opened'][:16].replace('T', ' ')} by {terms.get('by', '?')}"
               if terms.get('opened') else '')
        return f'trade on {market} · {lev_s} · ' + ' · '.join(parts) + who
    if terms.get('strategy') == 'martingale':
        k, n = terms.get('multiplier') or 1.0, terms.get('add_ons')
        grows = (f'<span class="st" title="each add-on order is {k:g}× the '
                 'one before, so the average entry chases the price — and '
                 'the position grows fast on the way down; the loss limit '
                 'and the stop are what bound it">martingale-style</span>: '
                 f'each add-on {k:g}× the last' if k and k != 1 else
                 'equal add-ons')
        return (f'DCA on {market} · {lev_s} · {grows}'
                + (f', up to {n}' if n else ''))
    return f'grid on {market} · {lev_s}'


def _plain_name(botid, contract, b):
    """'BTCUSDT long grid' from the botid and the contract — the name a
    person says; the botid stays on the card for the confirm box."""
    side = (b or {}).get('side') or ('short' if botid.endswith('s')
                                     else 'long')
    kind = (b or {}).get('strategy') or (
        'grid' if botid in (contract.get('ranges') or {}) else 'martingale')
    market = {'inv': ' inverse', 'spo': ' spot'}.get(botid[:3], '')
    if ((contract.get('terms') or {}).get(botid) or {}).get('trade'):
        return f"{botid[3:-1]} {side} trade{market}"                # L6
    return (f"{botid[3:-1]} {side} "
            f"{'grid' if kind == 'grid' else 'DCA'}{market}")


def _side_tag(botid):
    """U15: long or short at a glance — a coloured tag, the same on the
    card and in the table."""
    side = 'short' if botid.endswith('s') else 'long'
    return f'<span class="side {side}">{side.upper()}</span> '


def state_tag(state, cls=''):
    """U35: the state word with its meaning on hover and its own colour."""
    import html as _h
    slug = state.lower().replace(' ', '-')
    return (f'<span class="{cls} st st-{slug}" title="'
            f'{_h.escape(STATE_WORDS.get(state, ""), quote=True)}">'
            f'{state}</span>')


def orders_line(ov):
    """U35: what rests and what waits, in words, from the engine's own
    snapshot (V15). None when the engine has not said."""
    if not ov:
        return None
    r, w = ov.get('resting') or {}, ov.get('waiting') or {}
    pct = (ov.get('within_pct') or 0.0) * 100

    def n(k, word):
        v = (k or {}).get(word + 's', 0)
        return f'{v} {word}{"" if v == 1 else "s"}'
    rest = ', '.join(x for x in (n(r, 'buy') if r.get('buys') else '',
                                 n(r, 'sell') if r.get('sells') else '') if x)
    wait = ', '.join(x for x in (n(w, 'buy') if w.get('buys') else '',
                                 n(w, 'sell') if w.get('sells') else '') if x)
    out = f'resting: {rest}' if rest else 'nothing resting'
    if wait:
        near = w.get('nearest')
        out += (f' · waiting: {wait} — placed when the price comes within '
                f'{pct:g}% of them'
                + (f' (the nearest at {near:,.6g})' if near else ''))
    return out


def card(idx, botid, b, contract, belief, full=False):
    """One bot, one card: its state in a word, what it made, where the
    price sits in its range. Everything the table row said is still here;
    the numbers live on the position's own page (U56), where `full` lays
    them open below the exchange's view of the position."""
    if ((contract.get('terms') or {}).get(botid) or {}).get('strategy') == 'portfolio':
        return portfolio_card(idx, botid, contract, belief, full=full)       # D78/H6
    rng = (contract.get('ranges') or {}).get(botid)
    ceil = ((contract.get('watchdog') or {}).get('ceilings') or {}).get(botid)
    quote_raw, margin_raw = units_of(botid, (contract.get('terms') or {}).get(botid))   # U53
    money_coin, margin_coin = esc(quote_raw), esc(margin_raw)     # P7: names from the file are text
    links = (('' if full else f"<a data-pick href='/?fleet={idx}&amp;bot={qarg(botid)}&amp;show=numbers'>numbers</a>")
             + ('' if ((contract.get('terms') or {}).get(botid) or {}).get('trade') else
                (' ' if not full else '') + f"<a data-pick href='/?fleet={idx}&amp;bot={qarg(botid)}&amp;show=edit'>edit</a> "
                f"<a href='/setup?fleet={idx}&amp;copy={qarg(botid)}'>copy</a> "
                f"<a href='/edit?fleet={idx}&amp;bot={qarg(botid)}&amp;mode=remove'>remove"
                '</a>'))
    # L8: a trade is not a fleet row — edit, copy and remove answered "not in
    # this fleet" (the owner, 2026-10-11, on tilt's ended BTC trade); a trade
    # ends by its own exit, close trade, or clear
    if b is not None and b.get('realized') is None:
        b = None             # an inverse book with no mark has no dollars (the second
                             # audit, 2026-10-13): shown as the engine's belief, never a crash
    if b is None:
        # no fills in the window — the engine's own belief fills in, and
        # says so (the snapshot is the bot's belief, not the venue)
        bl = belief.get(botid, {})
        pos = bl.get('position') or 0.0
        state = ('DEAD' if bl.get('alive') is False else
                 'HOLDING' if abs(pos) > 1e-12 else
                 'NOT STARTED' if botid not in belief else 'RESTING')  # U34
        head = ('<span class="big dim">waits for the fleet\'s restart</span>'
                if botid not in belief else
                '<span class="big dim">no fills</span>'
                + (f' <span class="dim">— {orders_line(bl.get("orders"))}'
                   '</span>' if bl.get('orders') else ''))          # U35
        kept = since_first_line(contract, botid)                  # R18
        if kept:
            head += f'<div class="pnl">{kept}</div>'
        held = (f'holding {pos:.10g} (belief)' if abs(pos) > 1e-12
                else 'holding nothing')
        _quiet_held = held                        # U68: the slim card says it too
        mark = (contract.get('marks') or {}).get(botid)             # U57: a quiet bot has a price too
        more, note = '', ''
        limit = (f'{abs(pos) / ceil * 100:.0f}% of {ceil:,.4g}' if ceil
                 else 'no limit')
    else:
        pos, mark = b['position'], b['mark']
        state = ('DEAD' if (belief.get(botid) or {}).get('alive') is False
                 else 'HOLDING' if abs(pos) > 1e-12 else 'FLAT')
        total = card_total(b)                                   # D63
        note = ' *' if b['truncated'] else ''
        coin = ''
        if b.get('settle'):            # R11: an inverse bot says both, as
            st = b['settle']           # the exchange does
            coin_total = (st['realized'] - st['fees']
                          + (st.get('funding') or 0.0)
                          + (st['unreal'] or 0.0))
            coin = (f' <span class="{_num_cls(coin_total)}">'
                    f"{coin_total:+.6f} {esc(st['coin'])}</span>")
        if b.get('counted_from') == 'flat':                   # R14
            days = (contract['generated_ms'] - b['counted_since_ms']) / 8.64e7
            span = (f'since it was last flat, {days:.1f} d'
                    if days >= 1 else f'since it was last flat, {days * 24:.0f} h')
        elif b.get('counted_from') == 'cap':
            # the cap is how far back it LOOKED; the figure is the fills it
            # found — say where they start when that is later (2026-10-06:
            # a "last 30 d" card counted 4.4 days)
            first = b.get('first_ms')
            days = ((contract['generated_ms'] - first) / 8.64e7
                    if first else None)
            span = ('never flat in 30 d; its fills start '
                    + (f'{days:.1f} d ago' if days is not None and days < 29
                       else '30 d ago')
                    + (' *' if b['truncated'] else ''))
        else:
            span = f"last {contract['window_hours']:g}h"
        # U45: the money in its own box — the total, then what it is made of
        net = b['realized'] - b['fees']
        cap = ((contract.get('terms') or {}).get(botid) or {}).get('capital')
        roi = (f' <span class="{_num_cls(total)}">{total / cap * 100:+.2f}%</span>'
               f' <span class="dim">on {cap:,.0f}</span>' if cap else '')
        # U68: the card's money at a glance, as the bot pages of the big
        # venues show it; every other line is the numbers page's
        slim_head = (f'<div class="pnl {_num_cls(total)}">'
                     f'<span class="big {_num_cls(total)}">{signed(total)}</span> {money_coin}{coin}{roi}'
                     f' <span class="dim">· {span}</span>'                 # D63: what the figure covers
                     + (grid_split(b, total) or f'<div class="parts">{pnl_parts(net, b["unreal_at_mark"], b.get("funding"))}</div>')
                     + f'{run_rate(b, contract, cap, bool(((contract.get("terms") or {}).get(botid) or {}).get("trade")) or ((contract.get("terms") or {}).get(botid) or {}).get("strategy") == "martingale")}'
                     '</div>')
        head = (f'<div class="pnl {_num_cls(total)}">'
                f'<span class="big {_num_cls(total)}">{signed(total)}</span> '
                f'{money_coin}{coin} <span class="dim">after fees, {span}</span>'
                f'{grid_split(b, total)}<div class="parts">'
                f'{pnl_parts(net, b["unreal_at_mark"], b.get("funding"))}'
                f'</div>{run_rate(b, contract, ((contract.get("terms") or {}).get(botid) or {}).get("capital"), bool(((contract.get("terms") or {}).get(botid) or {}).get("trade")) or ((contract.get("terms") or {}).get(botid) or {}).get("strategy") == "martingale")}'
                f'{since_first_line(contract, botid)}</div>')
        held = holding_html(pos, b['avg_cost'], mark, botid,
                            bool(b.get('inverse')), quote=quote_raw)    # U44/U53
        floor = (contract.get('fee_floors') or {}).get(botid)
        unreal = b['unreal_at_mark']
        limit = (f'{abs(pos) / ceil * 100:.0f}% of {ceil:,.4g}' if ceil
                 else 'no limit')
        more = (
            '<div class="numbers"><h3>the numbers</h3><table>'
            f"<tr><td>fills</td><td>{b['fills']}</td></tr>"
            + (f"<tr><td>per trip after fees ({b['gap_trips'] or b['trips']}"
               f" trips; {b['per_trip']:+,.2f} before)</td>"
               f"{money(b.get('per_trip_net'))}</tr>"
               if b.get('per_trip') is not None else '')            # R12
            + f"<tr><td>realized</td>{money(b['realized'])}</tr>"
            f"<tr><td>fees</td>{money(b['fees'], cls=False)}</tr>"
            f"<tr><td>funding</td>{money(b.get('funding'))}</tr>"   # D63
            f'<tr><td>unreal</td>{money(unreal)}</tr>'
            f"<tr><td>bought</td><td>{b['bought']:,.4g}</td></tr>"
            f"<tr><td>sold</td><td>{b['sold']:,.4g}</td></tr>"
            + (f"<tr><td colspan='2' class='wide'><b>orders</b> — "
               f"{orders_line((belief.get(botid) or {}).get('orders'))}"
               '</td></tr>'
               if (belief.get(botid) or {}).get('orders') else '')  # U35/U37
            + f'<tr><td>stop-now est.</td><td>{settle(b, floor)}</td></tr>'
            f'<tr><td>watcher</td><td>{limit}</td></tr>'
            + (f"<tr><td>in the coin itself</td><td>realized "
               f"{b['settle']['realized']:+.6f}, fees "
               f"{b['settle']['fees']:.6f}, funding "
               + ('—' if b['settle'].get('funding') is None else
                  f"{b['settle']['funding']:+.6f}") + ', unreal '
               + ('—' if b['settle']['unreal'] is None else
                  f"{b['settle']['unreal']:+.6f}") + '</td></tr>'
               if b.get('settle') else '')
            + '</table></div>')
    more += ladder_box(idx, botid, (contract.get('terms') or {}).get(botid), open_=True)   # U52
    if not full:
        more = ''                                 # U56: the numbers are the page's
    alerts = []                                   # U68: what a slim card still says
    capped = (belief.get(botid) or {}).get('capped')
    if capped:
        alerts.append(f'capped: {capped} — adds nothing, exits run' if pos else
                      f'waiting: {capped} — opens nothing until it clears')
        # D56/D70: the account's cap holds this bot back — a flat one
        # opens nothing, a holding one adds nothing
        held += ('</div><div class="neg">'
                 + (f'capped: {capped} — adds nothing, exits run' if pos else
                    f'waiting: {capped} — opens nothing until it clears'))
    mv = (belief.get(botid) or {}).get('margin')
    if mv and mv.get('liq') and mark:
        # V17: where the exchange says this position is liquidated, and how
        # far the mark is from it (2026-10-06: HYPE, isolated, went with no
        # line on its card saying how close it stood)
        away = abs(mark - mv['liq']) / mark * 100
        if away < 10:
            alerts.append(f"liquidates at {mv['liq']:,.6g} · {away:.1f}% away")
        held += (f'</div><div class="{"neg" if away < 5 else "dim"}">'
                 f"liquidates at {mv['liq']:,.6g} · {away:.1f}% away")
    mkt = (contract.get('market') or {}).get(botid)
    if mkt and mkt.get('thin'):
        alerts.append(f"market {mkt.get('line') or ''} · THIN for this fleet")
    if mkt and mkt.get('line'):
        # D67: the market's regime beside the bot that trades it; red when
        # the book is thin for this fleet
        age = mkt.get('age_s') or 0
        held += (f'</div><div class="{"neg" if mkt.get("thin") else "dim"}">'
                 f"market {mkt['line']}"
                 + (' · THIN for this fleet' if mkt.get('thin') else '')
                 + (f' · read {age // 3600} h ago' if age >= 7200 else ''))
    if mv and (mv.get('im') is not None or mv.get('mm') is not None):
        # V14: the exchange's own margin on this position, from the
        # engine's last snapshot
        parts = []
        # U53: two decimals for a dollar coin; a margin held in the coin
        # itself is small (MM 0.0012 BTC read as 0.00) — six figures
        fmt = ',.2f' if margin_coin in ('USDT', 'USDC', 'USD') else ',.6g'
        if mv.get('im') is not None:
            parts.append(f"IM {mv['im']:{fmt}} {margin_coin}")
        if mv.get('mm') is not None:
            parts.append(f"MM {mv['mm']:{fmt}} {margin_coin}")
        if mv.get('leverage'):
            parts.append(f"at {mv['leverage']:g}x on the exchange")
        held += '</div><div class="dim">margin ' + ' · '.join(parts)
    terms = (contract.get('terms') or {}).get(botid)
    kind = kind_line(terms)
    if kind:
        held = f'{kind}</div><div class="dim">' + held       # U36, first,
                                     # its own line ("leverageholding", U46)
    if terms and terms.get('capital'):
        lev = terms.get('leverage') or 1.0
        def amount(v):                 # 46,600 and 3,495,000, never 3.5e+06
            return f'{v:,.0f}' if abs(v) >= 1000 else f'{v:,.6g}'
        held += (f'</div><div class="dim">investment {amount(terms["capital"])} {money_coin}'
                 + (f' at <b>{lev:g}x</b>' if lev != 1 else '')
                 + (f' · up to {amount(terms["notional"])} {money_coin} in the market'
                    if terms.get('notional') else ''))
    rec = (terms or {}).get('spot')
    if rec:
        # D76: the shared wallet against this bot's book — what is not
        # this bot's, how much the inverse books on the coin account for,
        # and what is left that nothing explains
        coin = esc(terms.get('coin') or coin_of(botid))
        def c(v):
            return '—' if v is None else f'{v:,.6g}'
        line = (f"wallet {c(rec['wallet'])} {coin} · this bot's book {c(rec['book'])}"
                f" · {c(rec['outside'])} not this bot's")
        if rec.get('explained') is not None:
            line += (f" — the inverse books' P&amp;L and fees since "
                     f"{terms.get('holding_since', '')[:10]} account for "
                     f"{c(rec['explained'])}; {c(rec['unexplained'])} unexplained"
                     ' (funding not counted)')
        bad = rec.get('unexplained') is not None and abs(rec['unexplained']) > abs(rec['outside']) * 0.5 + 1e-9
        held += f'</div><div class="{"neg" if bad else "dim"}">{line}'
    where = ''
    slid = ''
    if rng and (belief.get(botid) or {}).get('offset') and rng.get('rungs', 0) > 1:
        # U57: the window as it has slid (G17): the home lattice's gap times
        # the offset, so the card judges the price against the window the
        # bot trades, not the home it started from
        gap = (rng['upper'] - rng['lower']) / (rng['rungs'] - 1)
        off = belief[botid]['offset']
        rng = dict(rng, lower=rng['lower'] + off * gap, upper=rng['upper'] + off * gap)
        slid = f' · window slid {off:+d} rungs from home'
    if rng and mark:
        lo, hi = rng['lower'], rng['upper']
        if lo <= mark <= hi:
            place = (f'{(mark - lo) / mark * 100:.1f}% above the bottom, '
                     f'{(hi - mark) / mark * 100:.1f}% below the top')
        else:
            place = ('<span class="neg">price is OUTSIDE the range ('
                     + ('above' if mark > hi else 'below') + ')</span>')
        where = (f'<div class="rng"><span class="dim">{lo:,.6g}</span>'
                 f'{strip(rng, mark, "100%")}'
                 f'<span class="dim">{hi:,.6g}</span></div>'
                 f'<div class="dim">price {mark:,.6g} — {place}{slid}</div>')
    elif rng:
        where = (f"<div class=\"dim\">range {rng['lower']:,.6g} to "
                 f"{rng['upper']:,.6g}</div>")
    loss = (belief.get(botid) or {}).get('loss')
    if loss and loss.get('limit'):
        # X14: the engine's own count, from its last snapshot
        down = max(0.0, -loss['result'])
        used = down / loss['limit']
        if used >= 0.5:
            alerts.append(f"loss limit {used:.0%} used ({down:,.2f} of {loss['limit']:,.6g})")
        held += (f'</div><div class="{"neg" if used >= 0.75 else "dim"}">'
                 f"loss limit: down {down:,.2f} of {loss['limit']:,.6g} "
                 f'{money_coin} ({used:.0%} used)')
    cls = 'neg' if state == 'DEAD' else 'dim'
    side = 'short' if botid.endswith('s') else 'long'
    flat = (abs(pos) <= 1e-12 if b is not None else
            (belief.get(botid) or {}).get('position') == 0)   # unknown ≠ flat
    is_trade = bool(((contract.get('terms') or {}).get(botid) or {}).get('trade'))
    if is_trade and state != 'DEAD' and not flat and not botid.startswith('spo'):
        # L6: a live trade can be ended early from its card — the close page
        # asks for its name and sends one reduce-only market order
        links += (f" <a href='/close?fleet={idx}&amp;bot={qarg(botid)}'>close trade</a>")
    elif is_trade and state == 'DEAD':
        links += " <a href='/trade'>clear</a>"
    if state == 'DEAD' and not botid.startswith('spo') and not flat and not (
            is_trade and not abs((belief.get(botid) or {}).get('position') or 0.0) > 1e-12):
        # L8: a stopped trade ended by its own exit or stop — offer the close
        # only when its holding is known to be open, and clear otherwise
        # X15: what a stopped bot left open can be closed from here — and
        # only then: a bot known to have stood down flat has nothing to
        # close (HL AVAX after its last round, 2026-10-06: the door led to
        # "nothing"); a holding the panel cannot see is still offered —
        # the close page asks the exchange itself
        links += (f" <a href='/close?fleet={idx}&amp;bot={qarg(botid)}'>close "
                  'position</a>')
    if not full:
        # U68 (the owner: "far too much for a card … looks like pionex at
        # first", the rest on the numbers page, live): the side, the name,
        # the state; the money; the range; only what needs the owner now
        warn = ''.join(f'<div class="neg">{a}</div>' for a in alerts)
        return (f'<div class="card {side} slim"><div>'
                f'<span class="side {side}">{side.upper()}</span> <b>'
                f'{pick_link(idx, botid, esc(_plain_name(botid, contract, b)))}</b>{note} '
                f'{state_tag(state, cls)}</div>'
                f'<div>{slim_head if b is not None else head}</div>'
                + ('' if b is not None else f'<div class="dim">{_quiet_held}</div>')
                + f'{where}{warn}'
                f'<div class="dim foot"><span>{esc(botid)}</span><span>{links}</span></div></div>')
    # U58: the lines under the bar fold behind one word, so a card can be
    # small; the click is remembered per card, and the side panel folds or
    # opens every card at once (the owner, 2026-10-09: "toggle all so it
    # can be bigger and smaller"). The numbers stay the page's (U56).
    return (f'<div class="card {side}"><div>'
            f'<span class="side {side}">{side.upper()}</span> <b>'
            f'{esc(_plain_name(botid, contract, b))}</b>{note} '
            f'{state_tag(state, cls)}</div>'
            f'<div>{head}</div>{where}{fold(idx, botid, f'<div class="dim">{held}</div>')}{more}'
            f'<div class="dim foot"><span>{esc(botid)}</span><span>{links}</span></div></div>')


def fold(idx, botid, inner, word='details'):
    """U58: a card's lower half behind a summary word — open by default,
    remembered per card by the page's script, folded or opened for every
    card by the side panel's switch. An export (no script) shows it open."""
    return (f'<details class="fold" data-k="{idx}:{esc(botid)}:fold" open>'
            f'<summary>{word}</summary>{inner}</details>')


def pnl_parts(net, unreal, funding=0.0):
    """U45: what a total is made of — banked after fees, funding paid or
    received (D63, its own line; — when it could not be read), and still
    open."""
    def part(v):
        return ('—' if v is None else
                f'<b class="{_num_cls(v)}">{v:+,.2f}</b>')
    return (f'realised after fees {part(net)} · funding {part(funding)} · '
            f'open {part(unreal)}')


def grid_split(b, total):
    """U90 (the owner, 2026-10-14: a grid "could be thousands of dollars in
    profit, but simultaneously look underwater"): the total as Bybit and
    Pionex split it — grid profit, the matched trips (R12) after fees, and
    trend, the rest (the held coins at the mark, what a slide realised,
    funding), the two summing to the total exactly — and the price at which
    the total would be nothing, before the closing fee. A linear book only
    (an inverse book's dollars move with 1/price); '' for a bot without a
    matched trip (a DCA or a trade keeps realised and open)."""
    if total is None or not b.get('gap_trips') or b.get('gap_realized') is None:
        return ''
    grid = b['gap_realized'] - b['fees']
    trend = total - grid
    rows = [('grid profit', f'<b class="{_num_cls(grid)}">{grid:+,.2f}</b>'),
            ('trend', f'<b class="{_num_cls(trend)}">{trend:+,.2f}</b>')]
    pos, mark = b.get('position') or 0.0, b.get('mark')
    if abs(pos) > 1e-12 and mark and not b.get('inverse'):
        even = mark - total / pos
        if even > 0:
            rows.append(('back to even at' if total < 0 else
                         f'in profit while {"above" if pos > 0 else "below"}', f'<b>{even:,.6g}</b>'))
    return ('<div class="split">' + ''.join(f'<span>{k}</span><span class="num">{v}</span>' for k, v in rows)
            + '</div>')


def since_first_total(sf):
    """R18: a kept book's whole result, or None when it cannot be whole
    (the ledger behind the window, or an unknown mark on an open book)."""
    from gridgremlin.report import kept_total
    return kept_total(sf)                                       # D63, one rule


def since_first_line(contract, botid):
    """R18: the line under a card's money — since the bot first traded,
    from the kept ledger. Nothing when no ledger is kept; a ledger behind
    the readout's window says so and shows no number."""
    if 'since_first' not in contract:
        return ''
    sf = contract['since_first'].get(botid)
    if not sf or not sf.get('fills'):
        return '<div class="parts">kept history: nothing kept yet</div>'
    if sf.get('behind') is not None:
        when = (f"kept to {_day(sf['behind'])}" if sf['behind']
                else 'not collected yet')
        return ('<div class="parts">kept history: the ledger is behind '
                f'— {when}</div>')
    if not sf.get('whole', True):
        return ('<div class="parts">kept history: no clean start yet — it '
                'held through the whole record, so nothing is summed</div>')
    total = since_first_total(sf)
    rounds = (f"{sf['rounds']} rounds" if sf.get('strategy') == 'martingale'
              else f"{sf['trips']} trips")
    star = ' *' if sf.get('truncated') else ''
    shown = ('—' if total is None else
             f'<b class="{_num_cls(total)}">{signed(total)}</b>')
    op = sf.get('opened')
    since = (f'fresh from {_day(op["time_ms"])} (opened holding '
             f'{op["qty"]:,.10g} at {op["price"]:,.6g})' if op
             else f'since {_day(sf["first_ms"])}')
    return (f'<div class="parts">kept history, {since}'
            f' {shown}{star} · {rounds}</div>')


def portfolio_card(idx, botid, contract, belief, full=False):
    """H6: the portfolio's card — the stack's value and coins, one line per
    asset (weight target → actual, hedge ratio target → actual, coins
    hedged, the regime word when the tilt is on), and three money lines
    that never mix: carry, tilt, basis & shape."""
    import html as _h
    terms = (contract.get('terms') or {}).get(botid) or {}
    bl = belief.get(botid) or {}
    v = bl.get('portfolio') or {}
    q = esc(terms.get('quote') or 'USDT')
    links = (('' if full else f"<a data-pick href='/?fleet={idx}&amp;bot={qarg(botid)}&amp;show=numbers'>numbers</a> ")
             + f"<a data-pick href='/?fleet={idx}&amp;bot={qarg(botid)}&amp;show=edit'>edit</a> "
             f"<a href='/edit?fleet={idx}&amp;bot={qarg(botid)}&amp;mode=remove'>remove</a>")
    state = ('DEAD' if bl.get('alive') is False else 'NOT STARTED' if botid not in belief
             else 'HOLDING' if (v.get('stack_value') or 0) > 0 else 'RESTING')
    name = f"{botid[3:]} portfolio"
    kind = (f"{len(terms.get('assets') or [])} assets · hedged on "
            + ', '.join(sorted({h['product'] for h in (terms.get('hedges') or {}).values()}) or ['nothing'])
            + f" · rebalanced every {(terms.get('rebalance') or {}).get('every_hours', 24):g} h"
            + (f" · tilt {terms['regime']['tilt']:.0%} with the regime" if terms.get('regime') else ' · neutral'))
    # the owner (2026-10-11): a borrowing row on a shared account says so,
    # and what its siblings' cash came to — kept out of its own
    shares = (f" · shares margin with {v['siblings']} bot{'s' if v['siblings'] != 1 else ''}"
              f" (their cash {v.get('others_cash') or 0.0:+,.2f} {q}, not this row's)"
              if v.get('siblings') else '')
    facts = ''
    if not v:
        head = ('<span class="big dim">waits for the fleet\'s restart</span>' if botid not in belief
                else '<span class="big dim">not yet valued</span>')
        body = ''
    else:
        total = v.get('total') or 0.0
        carry, tilt, basis = v.get('carry', {}).get('total') or 0.0, v.get('tilt') or 0.0, v.get('basis') or 0.0
        head = (f'<div class="pnl {_num_cls(total)}"><span class="big {_num_cls(total)}">{signed(total)}</span> {q} '
                f'<span class="dim">since its anchor, after fees</span><div class="parts">'
                f'carry <b class="{_num_cls(carry)}">{carry:+,.2f}</b> · '
                f'tilt <b class="{_num_cls(tilt)}">{tilt:+,.2f}</b> · '
                f'basis &amp; shape <b class="{_num_cls(basis)}">{basis:+,.2f}</b>'
                + (f' · interest <b class="neg">−{v["interest"]:,.2f}</b>' if v.get('interest') else '')
                + '</div></div>')
        rows = ''
        # the owner (2026-10-16): each coin's leverage, spot and hedge, from 1×
        # (none) up to what the venue allows — the spot's is the row's loan
        spot_lev = max(v.get('leverage') or 1.0, 1.0) if v.get('borrowed') else 1.0
        legs = {(g.get('kind'), g.get('coin')): g for g in v.get('legs') or []}

        def lev_cell(coin, w):
            spot = f"spot {spot_lev:.2f}× <span class='dim'>of {v.get('spot_leverage_most') or 1.0:g}×</span>" if w > 0 else ''
            g = legs.get(('hedge' if w > 0 else 'short', coin)) or {}
            perp = (f"{'hedge' if w > 0 else 'short'} {g['leverage']:g}×"
                    + (f" <span class='dim'>of {g['max_leverage']:g}×</span>" if g.get('max_leverage') else '')
                    if g.get('leverage') else '')
            return ' · '.join(x for x in (spot, perp) if x) or '—'
        for a in v.get('assets') or []:
            w, act = a.get('weight') or 0.0, a.get('actual') or 0.0
            hedged, coins = a.get('hedged') or 0.0, (v.get('stack') or {}).get(a['coin'], {}).get('coins') or 0.0
            ratio_act = (hedged / coins) if coins else 0.0
            note = ('unwound (basis)' if a.get('unwound') else
                    f"regime {a['regime']}" if a.get('regime') else '')
            rows += (f"<tr><td>{a['coin']}</td>"
                     + (f"<td>{w:.0%} → {act:.0%}</td>" if w > 0 else f"<td>short {abs(w):.0%}</td>")
                     + (f"<td>{a.get('ratio') or 0:g} → {ratio_act:.2f}</td><td>{hedged:,.6g}</td>"
                        if w > 0 else f"<td>—</td><td>{a.get('short') or 0.0:,.6g}</td>")
                     + f"<td>{coins:,.6g}</td><td>{lev_cell(a['coin'], w)}</td>"
                     + f"<td class='dim'>{_h.escape(note)}</td></tr>")
        nxt = v.get('next_tick_ms')
        due = ''
        if nxt:
            left = (nxt - contract['generated_ms']) / 3.6e6
            due = f"next tick in {left:.1f} h" if left > 0 else 'tick due'
        facts = (f"<div class=\"dim\">stack <b>{v.get('stack_value') or 0:,.2f}</b> {q}"
                f" · cash {v.get('cash') or 0:,.2f}"
                + (f" · parked {v['parked']:,.2f}" if v.get('parked') else '')
                + (f" · borrowed <b>{v['borrowed']:,.2f}</b> ({v['leverage']:.2f}× the equity"
                   + (f", {v['borrow_apr']:.2%}/yr" if v.get('borrow_apr') is not None else '')
                   + (f", interest paid {v['interest']:,.2f}" if v.get('interest') else '') + ')'
                   if v.get('borrowed') and v.get('leverage') else '')
                + (f" · shorts cut {v['delevered']}×" if v.get('delevered') else '')
                + (f" · {due}" if due else '') + '</div>')
        body = (f'<table><tr><th>asset</th><th>weight</th><th>hedge ratio</th>'
                f'<th>coins hedged</th><th>coins held</th><th>leverage</th><th></th></tr>{rows}</table>'
                + (holdings_table(v, q, contract['generated_ms']) if full else '')
                + (('<div class="numbers"><h3>the numbers</h3><table>'
                f"<tr><td>value</td>{money(v.get('value'), cls=False)}</tr>"
                f"<tr><td>anchor</td>{money(v.get('anchor'), cls=False)}</tr>"
                f"<tr><td>shorts, open</td>{money(v.get('unreal'))}</tr>"
                f"<tr><td>shorts, realised after fees</td>{money(v.get('realised'))}</tr>"
                f"<tr><td>funding, trailing window</td>{money((v.get('carry') or {}).get('trailing'))}</tr>"
                + (f"<tr><td>loss limit</td><td>{bl['loss']['result']:,.2f} of {bl['loss']['limit']:,.2f}</td></tr>"
                   if bl.get('loss') else '')
                + '</table></div>') if full else ''))
    cls = 'neg' if state == 'DEAD' else 'dim'
    # H6: the portfolio's card spans the cards' row — six columns of assets
    # and three money lines ran past a 21em card's border (the owner, 2026-10-08)
    # U55: three cards wide, not the page; the money and the facts side by
    # side, the assets below, the footer aligned with every other card's
    if not full:                                  # U68: the slim card
        lev = (f'<div class="dim">{v["leverage"]:.2f}× the equity'
               + (f' · borrowed {v["borrowed"]:,.0f}' if v.get('borrowed') else '') + '</div>'
               if v and v.get('leverage') else '')
        return (f'<div class="card pfo slim"><div><span class="side pfo">PORTFOLIO</span> <b>{esc(name)}</b> '
                f'{state_tag(state, cls)}</div><div class="dim">{kind}{shares}</div><div>{head}</div>{lev}'
                f'<div class="dim foot"><span>{esc(botid)}</span><span>{links}</span></div></div>')
    return (f'<div class="card pfo"><div><span class="side pfo">PORTFOLIO</span> <b>{esc(name)}</b> '
            f'{state_tag(state, cls)}</div><div class="dim">{kind}{shares}</div>'
            f'<div class="two"><div>{head}</div><div>{facts}</div></div>'
            + (fold(idx, botid, body, word='assets') if body else '')          # U58
            + f'<div class="dim foot"><span>{esc(botid)}</span><span>{links}</span></div></div>')


def holdings_table(v, q, now_ms):
    """The carry view (the owner, 2026-10-15): everything the account holds
    for the row, each with its own result — the coins with their floating
    P&L at the average cost, every short with its open and realised P&L,
    the loan as the debt it is, and the stablecoins in the wallet that
    count as collateral."""
    import time as _t

    def n(x, f=',.6g'):
        return '—' if x is None else format(x, f)
    rows = ''
    since = []
    for c, h in sorted((v.get('spot') or {}).items()):
        rows += (f"<tr><td>{esc(c)} spot</td><td>{n(h['coins'])}</td><td>{n(h.get('avg'))}</td>"
                 f"<td>{n(h['price'])}</td><td>{n(h['value'], ',.2f')}</td>{money(h['floating'])}"
                 f"{money(h['realized'])}</tr>")
        since.append(h.get('since_ms') or 0)
    for g in v.get('legs') or []:
        what = f"{esc(g['symbol'])} {'hedge' if g['kind'] == 'hedge' else 'short'}"
        size = (f"{n(g['size'], ',.0f')} USD" if g['inverse'] else f"{n(g['size'])} {esc(g['coin'])}")
        rows += (f"<tr><td>{what}</td><td>−{size}</td><td>{n(g['avg'])}</td><td>{n(g['mark'])}</td>"
                 f"<td></td>{money(g['unreal'])}{money(g['realized'])}</tr>")
    # H9b: each coin with its hedge, the pair's result — a short of the coin
    # gains what the coins lose; the inverse contract's convexity is the rest
    for c, h in sorted((v.get('spot') or {}).items()):
        hedged = [g for g in v.get('legs') or [] if g['coin'] == c and g['kind'] == 'hedge']
        if hedged:
            rows += (f"<tr class='net'><td>{esc(c)} net, with its hedge</td><td colspan=4 class='dim'>"
                     "the coins' floating P&amp;L and the hedge's open P&amp;L together</td>"
                     f"{money(h['floating'] + sum(g['unreal'] for g in hedged))}"
                     f"{money(h['realized'] + sum(g['realized'] for g in hedged))}</tr>")
    if v.get('borrowed'):
        rows += (f"<tr><td>loan</td><td>−{v['borrowed']:,.2f} {q}</td><td colspan=3 class='dim'>"
                 + (f"{v['borrow_apr']:.2%}/yr" if v.get('borrow_apr') is not None else '')
                 + "</td>" + money(-(v.get('interest') or 0.0)) + "<td class='dim'>interest paid</td></tr>")
    for coin, bal in sorted((v.get('stables') or {}).items()):
        if bal > 0:
            rows += (f"<tr><td>{esc(coin)} cash</td><td>{bal:,.2f}</td><td colspan=3 class='dim'>"
                     "collateral, counted in full</td><td></td><td></td></tr>")
    if not rows:
        return ''
    first = min((x for x in since if x), default=0)
    rebuilt = all((v.get('spot') or {}).get(c, {}).get('rebuilt') for c in (v.get('spot') or {}))
    when = _t.strftime('%Y-%m-%d %H:%M UTC', _t.gmtime(first / 1000)) if first else ''
    note = (f"<div class='dim'>coins' cost rebuilt from the exchange's own record since {when}</div>"
            if rebuilt and first else f"<div class='dim'>coins' cost counted from "
            f"{_t.strftime('%Y-%m-%d %H:%M UTC', _t.gmtime(first / 1000))}: before that, "
            "at the price of the first read</div>" if first else '')
    return ('<h3>what the account holds</h3><table><tr><th></th><th>size</th><th>average</th>'
            '<th>price</th><th>value</th><th>open P&amp;L</th><th>realised</th></tr>'
            f'{rows}</table>{note}')


def holding_html(pos, avg, mark, botid, inverse=False, quote=None):
    """U44 (owner 2026-10-05: "users can see the value, cost, asset … bybit
    lets you choose these as user preferences"): a holding said three ways
    at once — the coins, what they are worth at the mark, what they cost at
    the average — each in its own span; the page's "size in" switch shows
    one or all, remembered per browser tab. An inverse position is counted
    in dollars by the venue: its coins are dollars / price."""
    if abs(pos) <= 1e-12:
        return 'holding nothing'
    coin = esc(coin_of(botid))
    if inverse:
        coins = abs(pos) / mark if mark else None
        value, cost = abs(pos), abs(pos)            # $1 contracts
        cost_coins = abs(pos) / avg if avg else None
    else:
        coins = abs(pos)
        value = abs(pos) * mark if mark else None
        cost = abs(pos) * avg if avg else None
        cost_coins = None

    def n(v):
        return '—' if v is None else (f'{v:,.0f}' if abs(v) >= 1000
                                      else f'{v:,.6g}')
    sign = '-' if pos < 0 else ''
    if quote is None:                       # U53: from the bot's own name
        quote = units_of(botid, None)[0]
    q = f' {esc(quote)}' if quote else ''
    parts = [f'<span class="u-coin">{sign}{n(coins)} {coin}</span>',
             f'<span class="u-value">worth {n(value)}{q}</span>',
             f'<span class="u-cost">cost {n(cost)}{q}'
             + (f' ({n(cost_coins)} {coin})' if cost_coins else '')
             + f' @ {avg:.6g}</span>']
    return 'holding ' + '<span class="u-sep"> · </span>'.join(parts)
