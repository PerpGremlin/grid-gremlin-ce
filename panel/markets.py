"""U67: the markets half of the fleet page — one tile per coin the fleets
trade, from the newest market reading (D67, K10): what a trader wants
beside the bots. Display only, from the readings file; no venue is read
here and nothing here decides anything."""
import html
import time

from .render import _num_cls


def _pick(markets, coin):
    """A coin's representative market: Bybit's linear USDT perpetual first."""
    order = (f'bybit:linear:{coin}USDT', f'bybit:linear:{coin}PERP', f'bybit:inverse:{coin}USD',
             f'bybit:spot:{coin}USDT', f'hyperliquid:linear:{coin}')
    for k in order:
        if k in markets:
            return markets[k]
    return None


def coins_of(row):
    """The coins read, the most capital committed first."""
    seen = {}
    for m in (row.get('markets') or {}).values():
        sym = m.get('symbol') or ''
        coin = sym
        for q in ('USDT', 'PERP', 'USDC', 'USD'):
            if sym.endswith(q) and len(sym) > len(q):
                coin = sym[:-len(q)]
                break
        seen[coin] = seen.get(coin, 0.0) + float(m.get('committed') or 0.0)
    return [c for c, _ in sorted(seen.items(), key=lambda kv: -kv[1])]


def mini_chart(closes, p_wild, width=220, height=38):
    """The last 48 hours: the price line over the wild hours' shading."""
    pts = [float(c) for c in closes or []]
    if len(pts) < 2:
        return ''
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1.0
    step = width / (len(pts) - 1)
    bands = ''.join(
        f'<rect x="{max(0.0, i * step - step / 2):.1f}" y="0" width="{step:.1f}" height="{height}" '
        f'fill="var(--wild)" fill-opacity="{0.55 * p:.2f}"/>'
        for i, p in enumerate(p_wild or []) if p > 0.05)
    line = ' '.join(f'{i * step:.1f},{height - 3 - (v - lo) / span * (height - 6):.1f}'
                    for i, v in enumerate(pts))
    return (f'<svg class="mini" viewBox="0 0 {width} {height}" width="100%" height="{height}" '
            f'preserveAspectRatio="none" role="img" aria-label="the last 48 hours">{bands}'
            f'<polyline points="{line}" fill="none" stroke="var(--fg)" stroke-width="1.4" '
            f'vector-effect="non-scaling-stroke"/></svg>')


def calm_wild(h):
    """The hidden model's word for the coin, with how sure and how long."""
    if not h:
        return '<div class="dim">calm or wild: not read yet</div>'
    if h.get('unread'):
        return f'<div class="dim">calm or wild: unread ({html.escape(str(h["unread"]))[:80]})</div>'
    if not h.get('two_states'):
        return ('<div><b>one regime</b> <span class="dim">· no distinct wild state in 180 days '
                f'(±{h["sd_day"][0]:.1%}/day)</span></div>')
    wild = h['state'] == 'wild'
    typical = (h.get('typical_spell_h') or [None, None])[1 if wild else 0]
    p = h['p_wild']
    gauge = (f'<span class="gauge" title="P(wild) {p:.0%}"><i style="width:{max(2.0, p * 100):.0f}%"></i></span>')
    return (f'<div class="cw"><b class="{"wild" if wild else "calm"}">{"wild" if wild else "calm"}</b> '
            f'{gauge} <span class="num">{p:.0%}</span> <span class="dim">wild · {h["spell_h"]} h in'
            + (f', typical {typical:.0f} h' if typical else '') + '</span></div>'
            f'<div class="dim">calm ±{h["sd_day"][0]:.1%}/day · wild ±{h["sd_day"][1]:.1%}/day</div>')


def decide_steps(h):
    """K11: each of the last two days' hours redone from the reading's own
    model — the three steps the filter takes — so the page shows its
    working. Hour j moves from close j-1 to close j; its prior comes from
    the model's figure after hour j-1. Returns one dict per hour, oldest
    first; [] when the reading carries no model."""
    import math
    A, mu, var = h.get('A'), h.get('mu'), h.get('var')
    closes, pw = h.get('closes_48h') or [], h.get('p_wild_48h') or []
    if not (A and mu and var) or len(closes) < 2 or len(pw) != len(closes):
        return []
    def pdf(x, m, v):
        return math.exp(-(x - m) ** 2 / (2 * v)) / math.sqrt(2 * math.pi * v)
    out = []
    for j in range(1, len(closes)):
        if closes[j - 1] <= 0 or closes[j] <= 0:
            continue
        r = math.log(closes[j] / closes[j - 1])
        before = pw[j - 1]
        prior = before * A[1][1] + (1 - before) * A[0][1]        # step 1: carry the belief forward
        lc, lw = pdf(r, mu[0], var[0]), pdf(r, mu[1], var[1])    # step 2: each state's bell curve at the move
        tot = prior * lw + (1 - prior) * lc
        post = prior * lw / tot if tot > 0 else prior            # step 3: Bayes' rule
        out.append({'ago_h': len(closes) - 1 - j, 'close': closes[j], 'move': r, 'before': before,
                    'prior': prior, 'like_calm': lc, 'like_wild': lw, 'after': post, 'model': pw[j]})
    return out


def decided_page(row, coin, now=None):
    """K11: how the hidden model decided calm or wild for one coin — the
    fitted model, the last hour worked through in three steps with the real
    numbers, then every hour of the last two days redone beside the model's
    own figure. Display only, from the newest reading."""
    import math
    now = time.time() if now is None else now
    coins = coins_of(row or {})
    nav = ' · '.join(f'<b class="on">{html.escape(c)}</b>' if c == coin else f'<a href="/calm-wild?coin={html.escape(c)}">{html.escape(c)}</a>'
                     for c in coins)
    head = f'<h1>how it decided — {html.escape(coin)}</h1><p>{nav}</p>'
    h = ((row or {}).get('hmm') or {}).get(coin)
    if not h:
        return head + '<p class="dim">no reading for this coin yet</p>'
    if h.get('unread'):
        return head + f'<p class="dim">unread: {html.escape(str(h["unread"]))}</p>'
    if not h.get('two_states'):
        return head + (f'<p><b>one regime.</b> Over {h.get("fit_hours", 0) / 24:.0f} days a single bell curve '
                       f'(±{h["sd_day"][0]:.1%} a day) explains this coin\'s hourly moves as well as two states do '
                       f'once the extra numbers are paid for (BIC gain {h.get("bic_gain") or 0:,.1f}, needs more than 10). '
                       'With no distinct wild state there is nothing to decide between.</p>')
    steps = decide_steps(h)
    if not steps:
        return head + '<p class="dim">this reading carries no model to show — the working appears from the next hourly reading</p>'
    A, mu, var = h['A'], h['mu'], h['var']
    sdh = [math.sqrt(v) for v in var]
    age = max(0, int((now - row['t']) / 60))
    model = (f'<h2>the model <span class="dim">fitted {h["fit_age_h"]:.0f} h ago on {h["fit_hours"] / 24:.0f} days of hourly moves · '
             f'reading {age} min old</span></h2>'
             '<table class="cwtab"><tr><th></th><th>calm</th><th>wild</th></tr>'
             f'<tr><td>a typical hour moves</td><td>±{sdh[0]:.3%}</td><td>±{sdh[1]:.3%}</td></tr>'
             f'<tr><td>a typical day moves</td><td>±{h["sd_day"][0]:.2%}</td><td>±{h["sd_day"][1]:.2%}</td></tr>'
             f'<tr><td>drift an hour</td><td>{mu[0]:+.4%}</td><td>{mu[1]:+.4%}</td></tr>'
             f'<tr><td>stays the next hour</td><td>{A[0][0]:.1%}</td><td>{A[1][1]:.1%}</td></tr>'
             f'<tr><td>switches the next hour</td><td>{A[0][1]:.1%}</td><td>{A[1][0]:.1%}</td></tr>'
             f'<tr><td>a spell lasts, typically</td><td>{1 / (1 - A[0][0]):.0f} h</td><td>{1 / (1 - A[1][1]):.0f} h</td></tr>'
             '</table>'
             f'<p class="dim">Two states beat one bell curve by {h.get("bic_gain") or 0:,.0f} on BIC (more than 10 is strong). '
             f'Wild moves {h.get("separation") or 0:.1f}× as much as calm.</p>')
    s = steps[-1]
    w = s['prior'] * s['like_wild']
    c = (1 - s['prior']) * s['like_calm']
    last = ('<h2>the last hour, worked through</h2><ol class="cwsteps">'
            f'<li><b>carry the belief forward.</b> After the hour before, the model was {s["before"]:.1%} sure it was wild. '
            f'Wild stays wild {A[1][1]:.1%} of the time; calm turns wild {A[0][1]:.1%}. So before looking at this hour:<br>'
            f'<code>{s["before"]:.3f} × {A[1][1]:.3f} + {1 - s["before"]:.3f} × {A[0][1]:.3f} = <b>{s["prior"]:.3f}</b></code> chance of wild.</li>'
            f'<li><b>read the move.</b> The price went {s["move"]:+.3%} this hour. How likely is a move that size in each state? '
            f'Each state\'s bell curve, read at the move:<br><code>calm (±{sdh[0]:.3%}): {s["like_calm"]:,.2f}</code> · '
            f'<code>wild (±{sdh[1]:.3%}): {s["like_wild"]:,.2f}</code><br>'
            + ('The move suits calm better' if s['like_calm'] > s['like_wild'] else 'The move suits wild better')
            + f' — {max(s["like_calm"], s["like_wild"]) / max(min(s["like_calm"], s["like_wild"]), 1e-300):,.1f}× as likely. '
            '<span class="dim">These are heights of the curves, not chances: only how they compare matters.</span></li>'
            f'<li><b>combine them (Bayes\' rule).</b> Each side\'s prior times its likelihood, then divide by the total:<br>'
            f'<code>wild {s["prior"]:.3f} × {s["like_wild"]:,.2f} = {w:,.2f}</code> · '
            f'<code>calm {1 - s["prior"]:.3f} × {s["like_calm"]:,.2f} = {c:,.2f}</code><br>'
            f'<code>{w:,.2f} ÷ ({w:,.2f} + {c:,.2f}) = <b>{s["after"]:.1%}</b></code> wild — '
            f'<b class="{"wild" if s["after"] > 0.5 else "calm"}">{"wild" if s["after"] > 0.5 else "calm"}</b>. '
            f'<span class="dim">The model\'s own figure: {s["model"]:.1%}.</span></li></ol>')
    rows = ''.join(
        f'<tr><td>{"now" if x["ago_h"] == 0 else str(x["ago_h"]) + " h ago"}</td><td class="num">{x["close"]:,.6g}</td>'
        f'<td class="num {_num_cls(x["move"])}">{x["move"]:+.3%}</td><td class="num">{x["prior"]:.1%}</td>'
        f'<td class="num">{x["like_calm"]:,.1f}</td><td class="num">{x["like_wild"]:,.1f}</td>'
        f'<td class="num"><b class="{"wild" if x["after"] > 0.5 else "calm"}">{x["after"]:.1%}</b></td>'
        f'<td class="num dim">{x["model"]:.1%}</td></tr>'
        for x in reversed(steps))
    table = ('<h2>the last two days, hour by hour <span class="dim">newest first</span></h2>'
             f'{mini_chart(h.get("closes_48h"), h.get("p_wild_48h"), height=60)}'
             '<div class="scroll"><table class="cwtab"><tr><th>hour</th><th>close</th><th>move</th><th>wild before (step 1)</th>'
             '<th>calm fits (step 2)</th><th>wild fits</th><th>wild after (step 3)</th><th>model\'s figure</th></tr>'
             f'{rows}</table></div>'
             '<p class="dim">"redone here" and "the model\'s figure" agree to rounding: the page repeats the model\'s '
             'arithmetic from the reading, it does not trust it. A wild after above 50% names the hour wild. Display only — '
             'no bot reads this.</p>')
    return head + model + last + table


def tile(coin, m, h):
    price = m.get('price')
    ch = m.get('change_24h_pct')
    f8 = m.get('funding_8h_pct')
    rows = [
        f'<div class="mhead"><b><a class="plain" href="/calm-wild?coin={html.escape(coin)}" '
        f'title="how it decided">{html.escape(coin)}</a></b>'
        + (f' <span class="num">{price:,.6g}</span>' if price else '')
        + (f' <span class="num {_num_cls(ch)}">{ch:+.2f}%</span>' if ch is not None else '')
        + ' <span class="dim">24 h</span></div>',
        mini_chart((h or {}).get('closes_48h'), (h or {}).get('p_wild_48h')),
        calm_wild(h),
    ]
    if m.get('regime'):
        rows.append(f'<div>trend <b>{html.escape(m["regime"])}</b> <span class="dim">· ADX '
                    f'{m.get("adx_4h") or 0:.0f}, 4 h</span></div>')
    if f8 is not None:
        rows.append(f'<div>funding <span class="num {_num_cls(f8)}">{f8:+.4f}%</span>/8 h '
                    f'<span class="dim">· {f8 * 3 * 365:+.1f}%/yr</span></div>')
    parts = []
    if m.get('oi_change_24h_pct') is not None:
        parts.append(f'OI {m["oi_change_24h_pct"]:+.1f}% 24 h')
    if m.get('long_pct') is not None:
        parts.append(f'{m["long_pct"]:.0f}% of accounts long' + (f' ({m["crowding"]})' if m.get('crowding') else ''))
    if m.get('depth_1pct'):
        parts.append(f'depth ±1% {m["depth_1pct"] / 1e6:,.1f}M')
    if parts:
        rows.append('<div class="dim">' + ' · '.join(html.escape(p) for p in parts) + '</div>')
    if m.get('atr_pct_4h') is not None:
        rows.append(f'<div class="dim">a 4 h candle moves ±{m["atr_pct_4h"]:.2f}% on average (ATR)</div>')
    return f'<div class="mtile">{"".join(r for r in rows if r)}</div>'


def market_column(row, now=None):
    """The markets half: a heading with the reading's age, the fear and
    greed index, then a tile per coin. A missing reading says so."""
    now = time.time() if now is None else now
    if not row:
        return ('<aside class="markets"><h2>markets</h2><p class="dim">no market reading yet — '
                'the hourly market job writes logs/market.jsonl</p></aside>')
    age = max(0, int((now - row['t']) / 60))
    fg = row.get('fear_greed') or {}
    head = (f'<h2>markets <span class="dim">read {age} min ago · hourly</span></h2>'
            '<div class="dim">calm or wild: a hidden Markov model of each coin\'s hourly moves · '
            'trend: the ADX indicator · funding: paid by longs when positive</div>'
            + (f'<div class="dim">fear &amp; greed {fg["score"]} ({html.escape(str(fg.get("label") or ""))}) '
               f'· 7-day {fg.get("avg_7d")} · 30-day {fg.get("avg_30d")}</div>'
               if fg.get('score') is not None else ''))
    markets, hmm = row.get('markets') or {}, row.get('hmm') or {}
    tiles = ''.join(tile(c, _pick(markets, c), hmm.get(c)) for c in coins_of(row) if _pick(markets, c))
    return f'<aside class="markets">{head}<div class="mtiles">{tiles}</div></aside>'
