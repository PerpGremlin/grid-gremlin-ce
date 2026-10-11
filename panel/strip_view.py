"""The strip pinned to the top (U50) and the exchange figures it shows: network badges, leverage, MMR, the totals. Out of render.py (D91 step 3)."""
from gridgremlin.report import contract_tiers, card_total
from .card import since_first_total
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
    age = belief.get('age_s') or 0
    old = f' · as of {age // 60:.0f} min ago' if age > 600 else ''
    cls = 'neg' if rate >= MMR_WARN else 'dim'
    return (f'<div class="parts mmr">account MMR <b class="{cls}">{rate:.1%}</b>'
            f' <span class="dim">· the exchange liquidates at 100%{old}</span></div>')


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
    return ('<div class="parts">kept history '
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
    belief = ((contract.get('watchdog') or {}).get('belief') or {}).get('bots', {})
    return sum((bl.get('portfolio') or {}).get('total') or 0.0
               for bl in belief.values() if bl.get('alive') is not False)


def hero_strip(labelled):
    """U50 (the owner: the exchange boxes "get lost while scrolling"): a
    strip pinned to the top of the page, one row per fleet — its name and
    network, the exchange's total after fees, bots and how many are dead,
    the account's leverage now — read from the same contract as the box
    below, so the two can never disagree; the name jumps to the box."""
    from gridgremlin.report import account_leverage
    lines = []
    for idx, (label, c) in enumerate(labelled):
        live = [b for b in c['bots'].values() if b is not None]
        total = sum(card_total(b) for b in live) + portfolio_total(c)       # H6
        belief = ((c.get('watchdog') or {}).get('belief') or {}).get('bots', {})
        dead = sum(1 for bl in belief.values() if bl.get('alive') is False)
        levs = [a['now'] for a in account_leverage(c).values()]
        lev = ('leverage —' if not levs or any(v is None for v in levs) else
               'leverage ' + ' · '.join(f'{v:.2f}x' for v in levs))
        rate = ((c.get('watchdog') or {}).get('belief') or {}).get('mm_rate')
        if rate is not None:                                     # U66
            lev += (f' · MMR <b class="{"neg" if rate >= MMR_WARN else ""}">{rate:.1%}</b>')
        # six cells per fleet in one grid, so every column lines up whatever
        # the words' lengths (the owner: "so it looks squared")
        spark = equity_svg(((c.get('equity') or {}).get('24h')), 120, 18)       # U63
        lines.append(
            f'<div class="fleet"><a href="#fleet{idx}">{esc(label)}</a>{tier_badge(c)}'
            f'<span class="big num {_num_cls(total)}">{total:+,.2f} '
            f'<span class="dim">{venue_money(c)}</span></span>'
            f'<span class="dim num">{len(c["bots"])} bots</span>'
            + (f'<b class="neg num">{dead} dead</b>' if dead else '<span></span>')
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
    return '/'.join(coins) if coins else 'quote'
