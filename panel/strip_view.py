"""The strip pinned to the top (U50) and the exchange figures it shows: network badges, leverage, MMR, the totals. Out of render.py (D91 step 3)."""
from gridgremlin.report import contract_tiers, card_total
from .card import not_whole, since_first_total, snapshot_age, unpriced
from .drawings import equity_svg
from .html_bits import _num_cls, esc, units_of


def exchange_leverage(contract):
    """R19: the account's leverage, the owner's measure, in the exchange box."""
    from gridgremlin.report import leverage_lines
    return ''.join(f'<div class="parts lev-now">{now}</div>'
                   f'<div class="parts lev-filled">{filled}</div>'
                   for now, filled in leverage_lines(contract).values())


MMR_WARN = 0.5             # the account's MMR from which its line is red


def exchange_mmr(contract):
    """U66: the account's MMR as the exchange states it — maintenance margin
    over equity, the gauge Bybit liquidates at 100% — from the fleet's
    latest snapshot, in every account's box; red from MMR_WARN, its age said
    when the snapshot is old, nothing claimed when there is none. (The
    owner, 2026-10-11: "account MMR should be displayed for every account".)"""
    belief = ((contract.get('watchdog') or {}).get('belief') or {})
    rate = belief.get('mm_rate')
    if rate is None:
        return ''
    stale = snapshot_age(contract)
    old = f' · as of {stale}' if stale else ''
    cls = 'neg' if rate >= MMR_WARN else 'dim'
    return (f'<div class="parts mmr">account MMR <b class="{cls}">{rate:.1%}</b>'
            f' <span class="dim">· the exchange liquidates at 100%{old}</span></div>')


FREE_WARN = 0.2            # the share of equity free to trade under which its line is red


def free_share(belief):
    """U100: (free to trade, its share of equity) from a snapshot's belief;
    None when either is unknown."""
    free, eq = belief.get('available'), belief.get('equity')
    if free is None or not eq:
        return None
    return free, free / eq


def exchange_free(contract):
    """U100: what the exchange says is free to open more with — Bybit's
    available balance, Hyperliquid's withdrawable — and its share of the
    equity, from the fleet's latest snapshot; red under FREE_WARN, its age
    said when old, nothing claimed without one. (The owner, 2026-10-19:
    "the users cannot see what they have left before they burn through
    their immediate margin".)"""
    got = free_share((contract.get('watchdog') or {}).get('belief') or {})
    if got is None:
        return ''
    free, share = got
    stale = snapshot_age(contract)
    old = f' · as of {stale}' if stale else ''
    cls = 'neg' if share < FREE_WARN else 'dim'
    return (f'<div class="parts free">free to trade <b class="{cls}">{free:,.2f}</b> '
            f'{venue_money(contract)} <b class="{cls}">({share:.0%} of equity)</b>'
            f' <span class="dim">· what the exchange lets you open more with{old}</span></div>')


READOUT_STALE_S = 600      # U138: a readout older than this is "not read"


DUST_USD = 1.0      # U138b: a coin worth less than this, owing nothing, is folded


def _balances(wallet):
    """U138b: each coin's balance and what the BALANCE is worth — Bybit's
    usdValue is the coin's equity (balance + the open P&L of the perps
    settled in it), so the balance's worth is the balance at the price that
    equity implies; the open P&L is said apart, per coin. Coins worth under
    DUST_USD that owe nothing fold into one count."""
    shown, dust, opl = [], 0, []
    for c, w in sorted(wallet.items()):
        b, u, upl = w.get('balance') or 0.0, w.get('usd'), w.get('upl') or 0.0
        worth = None
        if u is not None:
            eq = b + upl
            worth = b * (u / eq) if eq else (u if not upl else None)
        if upl:
            opl.append(f'{esc(c)} {upl:+,.2f}')
        if (worth is not None and abs(worth) < DUST_USD and not upl
                and not (w.get('borrow') or 0.0) and b >= 0):
            dust += 1
            continue
        shown.append(f'{esc(c)} {b:,.8g}' + (f' (≈ {worth:,.2f} USDT)' if worth is not None else ''))
    text = ' · '.join(shown) or 'empty'
    if dust:
        text += f' · + {dust} coin{"s" if dust > 1 else ""} under {DUST_USD:g} USDT'
    return text, ' · '.join(opl)


def account_lines(contract, now=None):
    """U138, the one renderer: each account's wallet as its readout states
    it — the coins and stables with their USDT value, the floating debt
    per coin (the venue's borrowed amount, or a balance below zero, and the
    interest accrued when the read carries it), and the available balance
    to trade (the venue's own figure). "not read" for each line the readout
    lacks, and for all of them when the readout is missing or stale. The
    account box, the create, carry and leverage forms all show this."""
    import time as _t
    now = _t.time() if now is None else now
    gen = (contract or {}).get('generated_ms')
    fresh = bool(contract) and gen is not None and now - gen / 1000.0 <= READOUT_STALE_S
    figs = (contract or {}).get('account') or {}
    out = []
    for venue in sorted(figs) or ['the account']:
        fig = figs.get(venue) if fresh else None
        name = esc(TIER_NAMES.get((venue, (fig or {}).get('tier')), venue))
        wallet = (fig or {}).get('wallet')
        if wallet is None:
            bal = debt = 'not read'
            opl = ''
        else:
            bal, opl = _balances(wallet)
            owed = [(c, max(w.get('borrow') or 0.0, -(w.get('balance') or 0.0), 0.0), w.get('interest') or 0.0)
                    for c, w in sorted(wallet.items())]
            debt = ' · '.join(f'{esc(c)} {d:,.8g}' + (f' (+ {i:,.8g} interest)' if i else '')
                              for c, d, i in owed if d > 0) or 'none'
        avail = (fig or {}).get('available')
        avail = 'not read' if avail is None else f'{avail:,.2f} USDT'
        out.append(f'<div class="parts acctlines"><b>{name}</b> '
                   f'<div>balances: <span class="dim">{bal}</span></div>'
                   + (f'<div>open P&amp;L on its perps: <span class="dim">{opl}</span></div>' if opl else '') +
                   f'<div>floating debt: <span class="dim">{debt}</span></div>'
                   f'<div>available to trade: <b>{avail}</b></div></div>')
    return ''.join(out)


SINCE_WORDS = (('1h', '1 h'), ('24h', '24 h'), ('7d', '7 d'))


def _q(x):
    return '—' if x is None else f'{x:,.8g}'


def _dq(x):
    return '—' if x is None else ('0' if abs(x) < 1e-12 else f'{x:+,.8g}')


def _at(ms):
    import time as _t
    return _t.strftime('%d %b %H:%M UTC', _t.gmtime(ms / 1000.0))


def position_words(p, trade=False):
    """D162: a position as the platforms say a trade (D161): "BTCUSDT
    Perpetual Futures Trade · SHORT"; without `trade`, the market alone."""
    from .html_bits import market_words
    said = f"{p['symbol']} {market_words({'market_type': p['market']}, trade=True)}"
    return esc(f"{said}{' Trade' if trade else ''} · {p['side'].upper()}")


def _window(w, venue):
    if w.get('none'):
        return f'<p class="dim">{esc(w["none"])} — the account is recorded from its first read.</p>'
    head = (f'<p class="dim">from the record at {_at(w["from_ms"])} to now'
            + (' — the record starts there, inside the window' if w.get('short') else '') + '</p>')
    bal = w.get('balances')
    if bal is None:
        why = ('Hyperliquid states no coin-by-coin wallet' if venue == 'hyperliquid'
               else 'the wallet was not read at one end')
        btab = f'<p>balances: <span class="dim">not read — {why}</span></p>'
    else:
        loans = any('loan_now' in r for r in bal)
        btab = ('<h4>balances (shown, not explained: funding, interest and fees move them without a trade)</h4>'
                '<table><tr><th>coin</th><th>before</th><th>now</th><th>change</th>'
                + ('<th>loan before</th><th>loan now</th>' if loans else '') + '</tr>'
                + ''.join(f'<tr><td>{esc(r["coin"])}</td><td>{_q(r["before"])}</td><td>{_q(r["now"])}</td>'
                          f'<td class="{_num_cls(r["change"])}">{_dq(r["change"])}</td>'
                          + (f'<td>{_q(r.get("loan_before"))}</td><td>{_q(r.get("loan_now"))}</td>'
                             if loans else '') + '</tr>' for r in bal)
                + '</table>') if bal else '<p>balances: <span class="dim">empty at both ends</span></p>'
    pos = w.get('positions')
    if pos is None:
        ptab = '<p>positions: <span class="dim">not read at one end</span></p>'
    elif not pos:
        ptab = '<p>positions: <span class="dim">no size changed</span></p>'
    else:
        rows = []
        for r in pos:
            tag = {'new': ' <b>new</b>', 'closed': ' <b>closed</b>'}.get(r['state'], '')
            why = f'<br><span class="dim">{esc(r["why"])}</span>' if r.get('why') else ''
            rows.append(f'<tr><td>{position_words(r)}{tag}{why}</td><td>{_q(r["before"])}</td>'
                        f'<td>{_q(r["now"])}</td><td>{_dq(r["change"])}</td>'
                        f'<td>{_dq(r.get("bots"))}</td><td>{_dq(r.get("rest"))}</td></tr>')
        ptab = ('<h4>positions (size)</h4><table><tr><th>position</th><th>before</th><th>now</th>'
                '<th>change</th><th>from the bots</th><th>not from a bot</th></tr>'
                + ''.join(rows) + '</table>')
    tr = w.get('transfers') or {}
    lines = [f'{_at(r["t"])} · <b>{"in" if r["dir"] == "in" else "out" if r["dir"] == "out" else "moved"}</b> '
             f'{_q(r["amount"])} {esc(r["coin"])} · {esc(r["what"])}' for r in tr.get('rows') or []]
    unread = tr.get('unread') or {}
    said = ('; '.join(f'{esc(k)} — {esc(v)}' for k, v in sorted(unread.items())))
    if tr.get('from_ms') and tr['from_ms'] > w['from_ms']:
        lines.append(f'<span class="dim">read from {_at(tr["from_ms"])} only</span>')
    if unread and not lines and set(unread) != {"this account's id"}:
        money = f'<span class="dim">not read: {said}</span>'
    else:
        money = ('<br>'.join(lines) or '<span class="dim">none recorded</span>') + (
            f'<br><span class="dim">not read: {said}</span>' if unread else '')
    return f'{head}{btab}{ptab}<h4>money in/out of the account</h4><p>{money}</p>'


def account_change_lines(contract, now=None, switch=True):
    """D162 (U150–U153): what changed on the account — its coins and its
    perpetual positions, since 1 h, 24 h or 7 d (one switch naming what is
    on, D161's look) — and its positions no bot runs. The readout's own
    `account_change`; nothing when the readout is missing or stale (the
    account lines say "not read"). The live panel's only (U138's rule)."""
    import time as _t
    now = _t.time() if now is None else now
    gen = (contract or {}).get('generated_ms')
    change = (contract or {}).get('account_change')
    if not change or gen is None or now - gen / 1000.0 > READOUT_STALE_S:
        return ''
    figs = contract.get('account') or {}
    # D163: the account box carries the switch in its header row (switch=False)
    out = ['<div class="parts acctchg"><b>what changed on the account</b> '
           + ('<button type="button" class="quiet tog" data-tog="since">since: '
              + ''.join(f'<span class="s{k}">{w}</span>' for k, w in SINCE_WORDS) + '</button>'
              if switch else '')]
    for venue, got in sorted(change.items()):
        name = esc(TIER_NAMES.get((venue, (figs.get(venue) or {}).get('tier')), venue))
        out.append(f'<div><b>{name}</b>')
        for k, _ in SINCE_WORDS:
            out.append(f'<div class="chg chg-{k}">{_window((got.get("windows") or {}).get(k) or {"none": "no record"}, venue)}</div>')
        loose = got.get('not_from_a_bot') or []
        if loose:
            out.append('<h4>Account positions, not from a bot</h4><table><tr><th>position</th><th>size</th>'
                       '<th>entry</th><th>mark</th><th>P&amp;L</th><th>leverage</th></tr>'
                       + ''.join(f'<tr><td>{position_words(p, trade=True)}</td><td>{_q(p.get("size"))}</td>'
                                 f'<td>{_q(p.get("entry"))}</td><td>{_q(p.get("mark"))}</td>'
                                 f'<td class="{_num_cls(p.get("upnl") or 0.0)}">{_dq(p.get("upnl"))}</td>'
                                 f'<td>{"—" if p.get("leverage") is None else format(p["leverage"], "g") + "x"}</td></tr>'
                                 for p in loose)
                       + '</table><p class="dim">no bot manages these; the engine leaves them alone.</p>')
        out.append('</div>')
    return ''.join(out) + '</div>'


def exchange_since_first(contract):
    """R18: the exchange box's kept line — every bot's whole result summed;
    a bot whose figure cannot be whole is named as left out, never
    silently dropped from the sum."""
    if 'since_first' not in contract:
        return ''
    whole, out = 0.0, 0
    for sf in contract['since_first'].values():
        if not sf or not sf.get('fills'):
            continue
        t = since_first_total(sf)
        if t is None:
            out += 1
        else:
            whole += t
    left = f' <span class="dim">({out} bot(s) left out: not whole)</span>' \
        if out else ''
    return ('<div class="parts">all-time '
            f'<b class="{_num_cls(whole)}">{whole:+,.2f}</b>{left}</div>')


TIER_NAMES = {('bybit', 'demo'): 'Demo Trading', ('bybit', 'testnet'): 'Testnet',
              ('bybit', 'mainnet'): 'Mainnet',
              ('hyperliquid', 'testnet'): 'Testnet',
              ('hyperliquid', 'mainnet'): 'Mainnet'}


def tier_badge(contract):
    """D65: the exchange's own name for the network, on every fleet's
    heading; Mainnet in red. A link to what the networks mean."""
    out = []
    for venue, env in sorted(contract_tiers(contract).items()):
        name = TIER_NAMES.get((venue, env), env)
        cls = 'tier-main' if env == 'mainnet' else 'tier-test'
        out.append(f'<a class="tier {cls}" href="/trading" title="what this '
                   f'means">{name}</a>')
    # the strip's grid counts a cell per fleet for the badge: an unknown
    # network still fills its cell (the bug hunt, 2026-10-11: a fleet down
    # shifted every later cell one place left)
    return ' '.join(out) or '<span></span>'


def portfolio_total(contract):
    """H6: what the fleet's portfolio rows have made since their anchors,
    from their own snapshots — counted into the exchange's total like any
    card (D63). A row the engine has not valued counts nothing."""
    from gridgremlin.report import portfolio_rows_total
    belief = ((contract.get('watchdog') or {}).get('belief') or {}).get('bots', {})
    return portfolio_rows_total(belief) or 0.0


def hero_strip(labelled, tabs=False):
    """U50 (the owner: the exchange boxes "get lost while scrolling"): a
    strip pinned to the top of the page, one row per fleet — its name and
    network, the exchange's total after fees, bots and how many are dead,
    the account's leverage now — read from the same contract as the box
    below, so the two can never disagree; the name jumps to the box —
    with account tabs (D163), to its account's tab."""
    from gridgremlin.report import account_leverage
    lines = []

    def jump(label, idx):
        if not tabs:
            return f'#fleet{idx}'
        from .render import acct_key
        return f'/?acct={acct_key(label)}" data-acct="{acct_key(label)}'
    for idx, (label, c) in enumerate(labelled):
        live = [b for b in c['bots'].values()                         # an unpriced inverse
                if b is not None and b.get('realized') is not None]    # book: no dollars yet
        total = sum(card_total(b) for b in live) + portfolio_total(c)       # H6
        gap = sum(1 for b in c['bots'].values() if unpriced(b))
        cut = sum(1 for b in c['bots'].values() if not_whole(b))           # R14c
        belief = ((c.get('watchdog') or {}).get('belief') or {}).get('bots', {})
        dead = sum(1 for bl in belief.values() if bl.get('alive') is False)
        frozen = sum(1 for bl in belief.values()                       # U146
                     if bl.get('alive') is not False and bl.get('frozen_since') is not None)
        levs = [a['now'] for a in account_leverage(c).values()]
        lev = ('leverage —' if not levs or any(v is None for v in levs) else
               'leverage ' + ' · '.join(f'{v:.2f}x' for v in levs))
        rate = ((c.get('watchdog') or {}).get('belief') or {}).get('mm_rate')
        if rate is not None:                                     # U66
            lev += (f' · MMR <b class="{"neg" if rate >= MMR_WARN else ""}">{rate:.1%}</b>')
        got = free_share((c.get('watchdog') or {}).get('belief') or {})
        if got is not None:                                      # U100
            lev += (f' · free <b class="{"neg" if got[1] < FREE_WARN else ""}">{got[1]:.0%}</b>')
        stale = snapshot_age(c)
        if stale:
            # U94: the dead count, the MMR and the free share are the engine's last snapshot's
            lev += f' · <b class="neg">engine read {stale}</b>'
        # D157: how many stopped; U146 (D158): how many are frozen — one
        # cell, so the grid's columns stay where they were
        said = ([f'<b class="neg num st" title="stopped by their own rule (a stop loss, a loss limit, a round count) or refused at start">{dead} stopped</b>'] if dead else []) \
            + ([f'<b class="neg num st" title="running, but their fills cannot be read: nothing placed or cancelled until they can (D158)">{frozen} frozen</b>'] if frozen else [])
        count_cell = (said[0] if len(said) == 1 else
                      '<span>' + ' · '.join(said) + '</span>' if said else '<span></span>')
        # six cells per fleet in one grid, so every column lines up whatever
        # the words' lengths (the owner: "so it looks squared")
        spark = equity_svg(((c.get('equity') or {}).get('24h')), 120, 18)       # U63
        lines.append(
            f'<div class="fleet"><a href="{jump(label, idx)}">{esc(label)}</a>{tier_badge(c)}'
            f'<span class="big num {_num_cls(total)}">{total:+,.2f} '
            f'<span class="dim">{venue_money(c)}</span>'
            + (f' <span class="neg">+ {gap} unpriced</span>' if gap else '')        # U95
            + (f' <span class="neg">+ {cut} not whole</span>' if cut else '')       # R14c
            + '</span>'
            f'<span class="dim num">{len(c["bots"])} bots</span>'
            + count_cell
            + f'<span class="dim">{lev}</span>'
            + (f'<span class="spark" title="equity, 24 h">{spark}</span>' if spark else '<span></span>')
            + '</div>')
    return '<div class="hero">' + ''.join(lines) + '</div>'


def venue_money(contract):
    """U53: what an exchange's total is counted in — its bots' money
    coins, joined when they differ (USDT/USDC at par is the venue's own
    convention on a unified account)."""
    terms = (contract.get('terms') or {}).values()
    coins = sorted({t['quote'] for t in terms if t and t.get('quote')})
    if not coins:
        coins = sorted({units_of(b, None)[0] for b in contract.get('bots') or {}})
    return esc('/'.join(coins)) if coins else 'quote'
