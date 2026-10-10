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


def tile(coin, m, h):
    price = m.get('price')
    ch = m.get('change_24h_pct')
    f8 = m.get('funding_8h_pct')
    rows = [
        f'<div class="mhead"><b>{html.escape(coin)}</b>'
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
