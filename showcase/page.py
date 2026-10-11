"""The show page (D86): the bots as the private side allowed them to be
shown (logs/show/show.json, gridgremlin.show) and the public market data
(ggdata), drawn without a link into the desk, a form or a script. Pure:
data in, HTML out."""
import html
import time

from common.symbols import coin_of

MARKET_FIELDS = ('price', 'change_24h_pct', 'funding_8h_pct', 'regime', 'long_pct',
                 'oi_change_24h_pct')                 # an allowlist: never 'committed' or 'thin'
REFRESH_S = 60
CSS = """:root{--bg:#f6f7f9;--fg:#1d232b;--dim:#68727f;--line:#d9dde3;--pos:#1f8a4c;--neg:#c0392b;--accent:#2f6fb0}
@media (prefers-color-scheme:dark){:root{--bg:#121419;--fg:#e3e6ea;--dim:#8a94a1;--line:#2a2f37;--pos:#3fb871;--neg:#e5675a;--accent:#7fb2e5}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;margin:0;padding:1.2em 16px}
main{max-width:70em;margin:0 auto}h1{font-size:1.25em;color:var(--accent);margin:.2em 0}h2{font-size:1.05em;margin:1.4em 0 .3em}
.dim{color:var(--dim)}.pos{color:var(--pos)}.neg{color:var(--neg)}.wrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}td,th{padding:.3em .7em;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
td:first-child,th:first-child,td.l,th.l{text-align:left}th{color:var(--dim);font-weight:normal}
.note{border-left:3px solid var(--accent);padding:.2em .9em;max-width:60em}"""


def _e(v):
    return html.escape(str(v))


def _pct(v, places=2):
    if v is None:
        return '<span class="dim">—</span>'
    cls = 'pos' if v > 0 else 'neg' if v < 0 else ''
    return f'<span class="{cls}">{v:+.{places}f}%</span>'


def _age(seconds):
    m = max(0, int(seconds // 60))
    return f'{m} min ago' if m < 120 else f'{m // 60} h ago'


def bots_html(show, now):
    if not show or not show.get('accounts'):
        return '<p class="dim">No bots to show yet — the private side has not written its file.</p>'
    amounts = show.get('amounts')
    out = [f'<p class="dim">the bots, as of {_age(now - show["generated_ms"] / 1000)}; '
           'each return is on the bot\'s own capital, from its first trade.</p>']
    for acct in show['accounts']:
        head = (f'<h2>{_e(acct["name"])} <span class="dim">· {_e(acct["network"])}</span> '
                f'{_pct(acct.get("return_pct"))}</h2>')
        cols = ['coin', 'side', 'kind', 'market', 'state', 'return', 'days', 'trips']
        if amounts:
            cols += ['capital', 'total', 'leverage']
        rows = []
        for b in acct['bots']:
            cells = [_e(b['coin']), _e(b['side']), _e(b['kind']), _e(b['market']), _e(b['state']),
                     _pct(b.get('return_pct')), _e(b['days'] if b.get('days') is not None else '—'),
                     _e(b['trips'] if b.get('trips') is not None else '—')]
            if amounts:
                q = f' {_e(b["quote"])}' if b.get('quote') else ''
                cells += [_e(f'{b["capital"]:,.0f}') + q if b.get('capital') else '—',
                          (f'{b["total"]:+,.2f}' + q) if b.get('total') is not None else '—',
                          _e(f'{b["leverage"]:g}x') if b.get('leverage') else '—']
            rows.append('<tr>' + ''.join(f'<td{" class=l" if i < 5 else ""}>{c}</td>'
                                         for i, c in enumerate(cells)) + '</tr>')
        out.append(head + '<div class="wrap"><table><tr>'
                   + ''.join(f'<th{" class=l" if i < 5 else ""}>{c}</th>' for i, c in enumerate(cols))
                   + '</tr>' + ''.join(rows) + '</table></div>')
    return ''.join(out)


def markets_html(reading, now):
    if not reading:
        return '<p class="dim">No market reading yet.</p>'
    by_coin = {}
    for key, m in sorted((reading.get('markets') or {}).items(),     # a coin's USDT perpetual first
                         key=lambda kv: (not (kv[1].get('symbol') or '').endswith('USDT'), kv[0])):
        if key.startswith('bybit:linear:'):
            by_coin.setdefault(coin_of(m.get('symbol') or ''), {k: m.get(k) for k in MARKET_FIELDS})
    hmm = reading.get('hmm') or {}
    rows = []
    for coin, m in by_coin.items():
        h = hmm.get(coin) or {}
        word = ({'calm': 'calm', 'wild': 'wild'}.get(h.get('state')) if h.get('two_states') else None)
        price = m.get('price')
        rows.append(
            f'<tr><td>{_e(coin)}</td><td>{_e(f"{price:,.6g}") if price else "—"}</td>'
            f'<td>{_pct(m.get("change_24h_pct"))}</td><td class="l">{_e(m.get("regime") or "—")}</td>'
            f'<td class="l">{_e(word or "—")}</td><td>{_pct(m.get("funding_8h_pct"), 4)}</td>'
            f'<td>{_e(f"{m["long_pct"]:.0f}%") if m.get("long_pct") is not None else "—"}</td>'
            f'<td>{_pct(m.get("oi_change_24h_pct"), 1)}</td></tr>')
    fg = reading.get('fear_greed') or {}
    fg_line = (f' · fear &amp; greed {_e(fg["score"])} ({_e(fg.get("label", ""))})'
               if fg.get('score') is not None else '')
    return (f'<p class="dim">public market data, read {_age(now - reading["t"])}{fg_line}</p>'
            '<div class="wrap"><table><tr><th>coin</th><th>price</th><th>24h</th><th class="l">trend</th>'
            '<th class="l">calm or wild</th><th>funding /8h</th><th>accounts long</th><th>open interest 24h</th></tr>'
            + ''.join(rows) + '</table></div>')


def page(show, reading, now=None):
    now = time.time() if now is None else now
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{REFRESH_S}">
<title>grid-gremlin showcase</title><style>{CSS}</style></head><body><main>
<h1>grid-gremlin</h1>
<p class="note">A grid and DCA trading engine, built in the open. <b>Paper money</b>: every bot
here trades an exchange's demo account or a testnet. This page shows engineering, not
financial advice. Exchange names describe where a bot runs; no exchange endorses this.</p>
<h2>The bots</h2>{bots_html(show, now)}
<h2>The markets</h2>{markets_html(reading, now)}
<p class="dim">read-only; refreshes every {REFRESH_S}s.</p>
</main></body></html>"""

