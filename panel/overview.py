"""U85: the front page's right half with nothing picked — the whole book
at a glance instead of an empty half. What needs the owner now, long and
short by coin across every account, each market's mood, and the latest
trades. All of it from the readouts already drawn on the left (and the
kept ledgers' tails, read by the caller): no venue call, no new state.
A bot picked by its name still opens in the half (D96, U78)."""
import time

from .card import _plain_name
from .html_bits import _num_cls, coin_of, esc, qarg

LIQ_NEAR_PCT = 10.0         # as the card's own warning (V17, U68)
LOSS_USED = 0.5             # as the card's own warning (X14, U68)
TRADES_SHOWN = 20


def _belief(contract):
    return ((contract.get('watchdog') or {}).get('belief') or {}).get('bots') or {}


def _is_portfolio(contract, botid):
    return ((contract.get('terms') or {}).get(botid) or {}).get('strategy') == 'portfolio'


def _position(b, bl):
    """The bot's holding: the window's book, else the engine's belief."""
    if b is not None and b.get('position') is not None:
        return float(b['position'])
    return float((bl or {}).get('position') or 0.0)


def _mark(contract, botid, b, bl):
    return ((b or {}).get('mark') or (contract.get('marks') or {}).get(botid)
            or (bl or {}).get('mark'))


def watch_list(labelled):
    """What a card would warn of, every account at once: a stopped bot, a
    position near its liquidation, a price outside its range, a cap holding
    a bot back, a thin book, a loss limit half used, a readout that failed.
    [(fleet index, botid or None, account, words)]."""
    out = []
    for idx, (label, c) in enumerate(labelled):
        if c.get('unavailable'):
            out.append((idx, None, label, 'the readout failed — the panel tries again'))
        belief = _belief(c)
        for botid in sorted(c.get('bots') or {}):
            b, bl = (c['bots'] or {}).get(botid), belief.get(botid) or {}
            name = botid[3:] + ' portfolio' if _is_portfolio(c, botid) else _plain_name(botid, c, b)
            said = []
            if bl.get('alive') is False:
                said.append('stopped')
            if bl.get('paused'):
                said.append('paused')                     # D145
            if bl.get('capped'):
                said.append(f"capped: {bl['capped']}")
            mark = _mark(c, botid, b, bl)
            liq = (bl.get('margin') or {}).get('liq')
            if liq and mark:
                away = abs(mark - liq) / mark * 100
                if away < LIQ_NEAR_PCT:
                    said.append(f'liquidates {away:.1f}% away')
            rng = (c.get('ranges') or {}).get(botid)
            if rng and mark and rng.get('rungs', 0) > 1:
                gap = (rng['upper'] - rng['lower']) / (rng['rungs'] - 1)
                off = bl.get('offset') or 0          # U57: the window as it has slid
                lo, hi = rng['lower'] + off * gap, rng['upper'] + off * gap
                if not lo <= mark <= hi:
                    said.append('price above its range' if mark > hi else 'price below its range')
            if ((c.get('market') or {}).get(botid) or {}).get('thin'):
                said.append('thin market')
            loss = bl.get('loss') or {}
            if loss.get('limit'):
                used = max(0.0, -loss['result']) / loss['limit']
                if used >= LOSS_USED:
                    said.append(f'loss limit {used:.0%} used')
            if said:
                out.append((idx, botid, label, f'{esc(name)}: ' + ' · '.join(said)))
    return out


def exposure(labelled):
    """Long and short by coin, in the quote's dollars at the mark, summed
    over every account's grid and DCA bots: {coin: [long, short]}, short
    negative. A portfolio row holds the coin and a matching short, so it is
    counted apart (its rows' names returned) rather than as a long. An
    inverse book is counted in its $1 contracts; an unpriced one is skipped."""
    book, hedged = {}, []
    for label, c in labelled:
        belief = _belief(c)
        for botid, b in (c.get('bots') or {}).items():
            if _is_portfolio(c, botid):
                hedged.append(label)
                continue
            bl = belief.get(botid)
            pos = _position(b, bl)
            if abs(pos) <= 1e-12:
                continue
            inverse = (b or {}).get('inverse') or botid.startswith('inv')
            mark = _mark(c, botid, b, bl)
            value = abs(pos) if inverse else (abs(pos) * mark if mark else None)
            if value is None:
                continue
            short = botid.endswith('s') or pos < 0
            row = book.setdefault(coin_of(botid), [0.0, 0.0])
            row[1 if short else 0] += -value if short else value
    return book, hedged


def _bar(long_, short, top):
    """Two half-bars from a middle line: the short to the left, the long to
    the right, each against the largest side of any coin."""
    w = (lambda v: f'{abs(v) / top * 100:.1f}%') if top else (lambda v: '0%')
    return (f'<span class="xbar"><span class="xh xleft"><i class="xs" style="width:{w(short)}"></i></span>'
            f'<span class="xh"><i class="xl" style="width:{w(long_)}"></i></span></span>')


def _money(v):
    return f'{v:+,.0f}' if abs(v) >= 1000 else f'{v:+,.2f}'


def exposure_html(labelled):
    book, hedged = exposure(labelled)
    if not book:
        rows = '<p class="dim">No grid or DCA bot holds anything.</p>'
    else:
        top = max(max(lg, -sh) for lg, sh in book.values())
        order = sorted(book.items(), key=lambda kv: -(kv[1][0] - kv[1][1]))
        rows = ('<table class="ov"><tr><th>coin</th><th>short</th><th></th><th>long</th><th>net</th></tr>'
                + ''.join(f'<tr><td>{esc(coin)}</td><td class="neg">{_money(sh) if sh else "—"}</td>'
                          f'<td class="xcell">{_bar(lg, sh, top)}</td>'
                          f'<td class="pos">{_money(lg) if lg else "—"}</td>'
                          f'<td class="{_num_cls(lg + sh)}">{_money(lg + sh)}</td></tr>'
                          for coin, (lg, sh) in order)
                + '</table>')
    note = ('<p class="dim">At the mark, in each account\'s own dollars (USDT, USDC, USD), '
            'every account together'
            + (f'. Not counted: the hedged portfolio rows ({esc(", ".join(sorted(set(hedged))))}) — '
               'each holds its coins and a matching short' if hedged else '')
            + '.</p>')
    return f'<h3>long and short, by coin</h3>{rows}{note}'


def moods_html(labelled):
    """D67: each market's reading once, however many bots trade it."""
    seen = {}
    for _, c in labelled:
        for botid, m in (c.get('market') or {}).items():
            if m and m.get('line'):
                seen.setdefault(coin_of(botid), m)
    if not seen:
        return ''
    rows = ''.join(f'<tr><td>{esc(coin)}</td><td class="{"neg" if m.get("thin") else ""}">'
                   f'{esc(m["line"])}{" · THIN" if m.get("thin") else ""}</td></tr>'
                   for coin, m in sorted(seen.items()))
    return f'<h3>the markets</h3><table class="ov moods">{rows}</table>'


def recent_trades(tails, labelled):
    """The latest fills across every account, newest first, each owned by
    its bot (its link's prefix and dash: one id that begins another never
    takes its fills); another hand's fills are not shown.
    `tails`: per fleet index, the kept ledger's last fills."""
    out = []
    for idx, fills in tails.items():
        label, c = labelled[idx]
        bots = list(c.get('bots') or {})
        for f in fills:
            link = f.get('link_id') or ''
            owner = next((b for b in bots if link.startswith(b + '-')), None)
            if owner is None or f.get('time_ms') is None:
                continue
            out.append((f['time_ms'], idx, label, owner, f))
    return sorted(out, key=lambda r: -r[0])[:TRADES_SHOWN]


def trades_html(tails, labelled):
    rows = recent_trades(tails, labelled)
    if not rows:
        return '<h3>latest trades</h3><p class="dim">No trades kept yet.</p>'
    body = []
    for t, idx, label, botid, f in rows:
        c = labelled[idx][1]
        entry = {'l': 'buy', 's': 'sell'}.get(botid[-1:]) if not _is_portfolio(c, botid) else None
        role = '' if entry is None else ('entry' if f.get('side') == entry else 'exit')
        body.append(f'<tr><td>{time.strftime("%m-%d %H:%M", time.gmtime(t / 1000))}</td>'
                    f'<td><a class="bname" data-pick href="/?fleet={idx}&amp;bot={qarg(botid)}">'
                    f'{esc(_plain_name(botid, c, (c.get("bots") or {}).get(botid)))}</a>'
                    f' <span class="dim">{esc(label)}</span></td>'
                    f'<td class="{"pos" if f.get("side") == "buy" else "neg"}">{esc(f.get("side") or "")}</td>'
                    f'<td>{role}</td><td>{float(f.get("price") or 0):,.6g}</td>'
                    f'<td>{float(f.get("qty") or 0):,.6g}</td></tr>')
    return ('<h3>latest trades</h3><table class="fills"><tr><th>UTC</th><th>bot</th>'
            '<th>side</th><th></th><th>price</th><th>qty</th></tr>' + ''.join(body) + '</table>')


def overview_pane(labelled, tails=None):
    """The half with nothing picked: one line of counts, then what needs a
    look, the book by coin, the markets, the latest trades."""
    bots = running = holding = 0
    for _, c in labelled:
        belief = _belief(c)
        for botid, b in (c.get('bots') or {}).items():
            bots += 1
            bl = belief.get(botid) or {}
            running += bl.get('alive') is not False
            holding += abs(_position(b, bl)) > 1e-12 or _is_portfolio(c, botid)
    watch = watch_list(labelled)
    look = ('<p class="pos">Nothing needs you now.</p>' if not watch else
            '<ul class="watch">' + ''.join(
                f'<li><span class="dim">{esc(label)}</span> '
                + (f'<a class="bname" data-pick href="/?fleet={idx}&amp;bot={qarg(botid)}">{words}</a>'
                   if botid else words) + '</li>'
                for idx, botid, label, words in watch) + '</ul>')
    return ('<aside class="pane"><h2>overview</h2>'
            f'<p>{len(labelled)} accounts · {bots} bots: {running} running'
            + (f', <b class="neg">{bots - running} stopped</b>' if bots - running else '')
            + f' · {holding} holding</p>'
            '<p class="dim">Pick a bot by its name: its fills and what each one made open here.</p>'
            f'<h3>needs a look</h3>{look}'
            f'{exposure_html(labelled)}{moods_html(labelled)}{trades_html(tails or {}, labelled)}'
            '</aside>')
