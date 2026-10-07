"""The panel, phase View — a localhost window onto the readout's contract.

Security floor (docs/archive/DASHBOARD.md §5): binds 127.0.0.1 on a random port;
a per-launch token is exchanged for a cookie on first load; the exact Host
is allowlisted (defeats DNS rebinding); no CORS headers exist; keys do not
exist here — this process holds no secrets and can write nothing.

    python3 -m panel.server <fleet.json> [--hours N]

Data is the engine's own contract (report --json). One shape, every
renderer: this page can never disagree with the terminal readout.
"""
import http.server
import os
from pathlib import Path
import urllib.parse
import html

from gridgremlin.report import card_total, money_units
import json
import re
import secrets
import subprocess
import sys
import time

REFRESH_S = 15          # the readout hits venue APIs: poll gently
CACHE_TTL_S = 30.0       # the readout reads the venues; 10 s fed the rate limit
WATCHDOG_OFF_S = 3600   # no sweep for an hour: it is off, not late (D39)

CSS = """:root{--bg:#14161a;--fg:#d6dae0;--dim:#7a828c;--line:#262a30;
--pos:#5dbb7c;--neg:#d4756b;--accent:#8ab4d8;--accent-soft:#8ab4d82e;
--gap:1em;--gap-s:.5em}
:root.light{--bg:#f5f4f0;--fg:#232629;--dim:#6f6a60;--line:#ddd8d0;
--pos:#2e7d4f;--neg:#b04a40;--accent:#3a6ea5;--accent-soft:#3a6ea524}
body{background:var(--bg);color:var(--fg);font:14px/1.5 monospace;margin:2em}
table.fleet{table-layout:fixed;width:100%}td{overflow:hidden;text-overflow:ellipsis}
table{border-collapse:collapse}td,th{padding:.35em .8em;
text-align:right;border-bottom:1px solid var(--line)}
th{color:var(--dim);font-weight:normal}td:first-child,th:first-child
{text-align:left}.pos{color:var(--pos)}.neg{color:var(--neg)}
.dim{color:var(--dim)}h1{font-size:1.1em;color:var(--accent);margin:var(--gap) 0 var(--gap-s)}
p{margin:var(--gap-s) 0}
input.derived{color:var(--dim);font-style:italic}
.refusal{border:2px solid var(--neg);color:var(--neg);padding:.7em 1em;
margin:0 0 1em;max-width:62em;font-size:1.1em}
.refusal a{color:var(--accent)}
a{color:var(--accent)}
a[href]{display:inline-block;padding:.2em .7em;margin:.15em .2em;background:var(--accent-soft);border:1px solid var(--accent);border-radius:4px;color:var(--fg);text-decoration:none;line-height:1.5}a[href]:hover,a.pick{background:var(--accent);color:var(--bg)}b.on{display:inline-block;padding:.2em .7em;margin:.15em .2em;background:var(--accent);border:1px solid var(--accent);border-radius:4px;color:var(--bg)}a[href*='mode=remove'],a[href^='/close']{border-color:var(--neg)}
.grp{grid-column:1/-1;color:var(--dim);text-align:left;padding-top:.6em;
border-bottom:1px solid var(--line)}
button{background:var(--accent);color:var(--bg);border:0;border-radius:4px;
padding:.45em 1.1em;margin:var(--gap-s) var(--gap-s) var(--gap-s) 0;font:inherit;font-weight:bold;
cursor:pointer}button:hover{filter:brightness(1.15)}
button.quiet{background:var(--accent-soft);border:1px solid var(--accent);color:var(--fg)}
button.theme{margin:var(--gap) 0 0}
details td.wide{text-align:left;white-space:normal;width:auto;padding-top:.4em}
.st{cursor:help;border-bottom:1px dotted var(--dim)}.st-holding{color:var(--accent)}
.st-dead{color:var(--neg)}.st-not-started{color:var(--pos)}.st-resting,.st-flat{color:var(--dim)}
.bar{height:.6em;background:var(--line);border-radius:.3em;max-width:40em;margin:.4em 0}
.bar div{height:100%;background:var(--accent);border-radius:.3em;transition:width .3s}
button.danger{background:var(--neg)}
.side{display:inline-block;font-size:.8em;font-weight:bold;
padding:.05em .55em;border-radius:3px;color:var(--bg);margin-right:.5em;
vertical-align:middle}.side.long{background:var(--pos)}
.side.short{background:var(--neg)}
.card.long{border-left:4px solid var(--pos)}
.card.short{border-left:4px solid var(--neg)}
.cards{display:grid;gap:var(--gap);
grid-template-columns:repeat(auto-fill,minmax(21em,1fr))}
.card{border:1px solid var(--line);border-radius:6px;padding:.8em 1em}
.card>div{margin:var(--gap-s) 0}.big{font-size:1.5em}
.pnl{border:1px solid var(--line);border-radius:5px;padding:.45em .75em;
background:color-mix(in srgb,var(--line) 40%,transparent);margin:var(--gap-s) 0}
.pnl.pos{border-color:var(--pos)}.pnl.neg{border-color:var(--neg)}
.tier{font-size:.55em;padding:.1em .45em;border-radius:3px;text-decoration:none;
vertical-align:middle;border:1px solid var(--line)}
.hero{position:sticky;top:0;z-index:5;background:var(--bg);margin:-2em -2em var(--gap);
padding:.45em 2em;border-bottom:1px solid var(--line)}
.hero{display:grid;grid-template-columns:repeat(6,max-content);gap:0 var(--gap);
align-items:baseline}.hero .fleet{display:contents}.hero .num{text-align:right}
.hero .tier{font-size:.75em}.hero .big{font-size:1.15em}
.page{display:grid;grid-template-columns:14em minmax(0,1fr);gap:0 calc(var(--gap)*1.5)}
nav.side{position:sticky;top:0;align-self:start;max-height:100vh;overflow:auto;
padding-right:var(--gap-s);border-right:1px solid var(--line)}
nav.side h3{font-size:1em;font-weight:normal;color:var(--dim);margin:var(--gap) 0 var(--gap-s)}
nav.side h3:first-child{margin-top:var(--gap-s)}
nav.side a[href],nav.side b.on,nav.side a{display:block;margin:.15em var(--gap-s) .15em 0}
@media(max-width:60em){.page{display:block}nav.side{position:static;max-height:none;
border-right:0;border-bottom:1px solid var(--line);margin-bottom:var(--gap);padding:0 0 var(--gap-s)}
nav.side h3{display:inline-block;margin:var(--gap-s) var(--gap-s) var(--gap-s) 0}
nav.side h3::after{content:':'}nav.side a[href],nav.side b.on,nav.side a{display:inline-block}
nav.side button.theme{margin:var(--gap-s) 0 0}}
@media(max-width:40em){body{margin:1em}.hero{margin:-1em -1em var(--gap);padding:.4em 1em;
grid-template-columns:repeat(3,max-content)}}
.tier-test{color:var(--dim)}.tier-main{color:#fff;background:var(--neg);
border-color:var(--neg);font-weight:700}
.pnl .parts{color:var(--dim);font-size:.92em}.pnl .parts b{font-weight:normal}
h1+.pnl{max-width:40em;font-size:1.05em}
.lev-filled{display:none}.lev-on .lev-filled{display:block}.lev-on .lev-now{display:none}
.rng{display:flex;align-items:center;gap:.6em}.rng svg{flex:1}
.card table{width:100%}.card td{padding:.1em .4em}
.say{max-width:62em;font-size:1.1em;border-left:3px solid var(--accent);
padding:.2em 1em}details{margin:.6em 0}summary{cursor:pointer;
color:var(--accent)}details td{text-align:left}details td:first-child
{width:22em}input,select{background:var(--bg);color:var(--fg);
border:1px solid var(--line);font:inherit;padding:.15em .3em}
.only-coin .u-value,.only-coin .u-cost,.only-coin .u-sep,.only-value .u-coin,.only-value .u-cost,.only-value .u-sep,.only-cost .u-coin,.only-cost .u-value,.only-cost .u-sep{display:none}"""


def money(v, cls=True):
    if v is None:
        return '<td class="dim">—</td>'
    c = ' class="pos"' if (cls and v > 0) else (' class="neg"'
                                               if cls and v < 0 else '')
    return f'<td{c}>{v:,.2f}</td>'


def strip(rng, mark, width='120'):
    """The range as a picture: bar, rung ticks, mark dot. Inline SVG,
    server-side, no scripts — a glance instead of arithmetic."""
    if not rng or not mark:
        return ''
    lo, hi = rng['lower'], rng['upper']
    span = hi - lo or 1.0
    x = max(0.0, min(1.0, (mark - lo) / span)) * 100
    ticks = ''.join(
        f'<line x1="{lo_x:.1f}" y1="3" x2="{lo_x:.1f}" y2="9" '
        'stroke="var(--line)"/>'
        for i in range(rng.get('rungs') or 0)
        for lo_x in [i / max(1, (rng['rungs'] - 1)) * 100])
    return (f'<svg width="{width}" height="12" viewBox="0 0 100 12" '
            f'preserveAspectRatio="none"><rect x="0" y="4" width="100" '
            f'height="4" fill="var(--line)"/>{ticks}'
            f'<circle cx="{x:.1f}" cy="6" r="3" fill="var(--accent)"/></svg>')


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


def sweep_note(contract):
    wd = contract.get('watchdog') or {}
    ago = wd.get('swept_s_ago')
    if ago is None:
        return '<span class="dim">watchdog OFF</span>'
    if ago > WATCHDOG_OFF_S:
        return '<span class="dim">watchdog OFF</span>'
    if ago > 900:              # it should sweep every 5 minutes: it is late
        return (f'<span class="neg">watchdog late: swept {ago / 60:.0f} '
                'min ago</span>')
    return f'<span class="dim">watchdog swept {ago}s ago</span>'



def rehearse_form(values=None):
    """The rehearsal's form, holding what was typed (U13): a result or a
    refusal comes back above the same numbers, never a blank form."""
    import html as _html
    v = dict({'symbol': 'ADAUSDT', 'side': 'long', 'lower': '', 'upper': '',
              'rungs': '16', 'capital': '1500', 'days': '7'},
             **{k: str(x) for k, x in (values or {}).items()})

    def box(name, size):
        return (f'<input name="{name}" size="{size}" '
                f'value="{_html.escape(v[name], quote=True)}">')
    sides = ''.join(f'<option{" selected" if o == v["side"] else ""}>{o}'
                    '</option>' for o in ('long', 'short'))
    return (
        '<h1>rehearse a grid <span class="dim">— a draft, validated by\n'
        'the engine, replayed over real candles. nothing is created.</span>'
        '</h1>\n<form method="post" action="/rehearse">\n'
        '<table><tr><th>coin</th><th>direction</th><th>lowest price</th>'
        '<th>highest price</th><th>grids</th><th>investment</th>'
        '<th>days</th><th></th></tr>\n'
        f'<tr><td>{box("symbol", 9)}</td>'
        f'<td><select name="side">{sides}</select></td>'
        f'<td>{box("lower", 8)}</td><td>{box("upper", 8)}</td>'
        f'<td>{box("rungs", 4)}</td><td>{box("capital", 7)}</td>'
        f'<td>{box("days", 4)}</td>'
        '<td><button>rehearse</button> <button name="optimize" value="1" '
        'class="quiet" title="replays your range with 5 to 77 grids over the '
        'last two weeks and shows which did best, and whether that holds up '
        '(T9) — about six minutes while the fleets run; press once" onclick="setTimeout(function(b){b.disabled=1;'
        'b.textContent=\'sweeping, about six minutes\u2026\'},0,this)">'
        'compare grid counts</button></td></tr></table>\n'
        '<input type="hidden" name="gg" value="1"></form>\n'
        '<p class="dim">any USDT or USDC perpetual Bybit lists, typed as '
        'Bybit names it (BTCUSDT, SUIUSDT). This quick form is for a plain '
        'grid; to rehearse a buy-the-dips bot, or a grid with every '
        'setting, set the bot up and press "rehearse" on its summary '
        'page. A rehearsal is not '
        'a promise —\nsame candles are never same fills. The replay plans '
        'against a synthetic\n1bp spread so guard-band drops happen as '
        'they would live (§9).</p>\n'
        '<p><a href="javascript:history.back()">&larr; back</a> · '
        '<a href="/">back to your bots</a></p>')


FORM = rehearse_form()


def curve_svg(points, width=600, height=80):
    """The rehearsal's equity path as inline SVG — server-side, styleable,
    no scripts, no pan/zoom (§4: that is where the rot lives). The zero
    line is drawn so a curve below it LOOKS below it."""
    if not points or len(points) < 2:
        return ''
    lo, hi = min(points + [0.0]), max(points + [0.0])
    span = (hi - lo) or 1.0
    def y(v):
        return height - (v - lo) / span * (height - 8) - 4
    step = width / (len(points) - 1)
    path = ' '.join(f'{i * step:.1f},{y(v):.1f}'
                    for i, v in enumerate(points))
    return (f'<svg width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" preserveAspectRatio="none">'
            f'<line x1="0" y1="{y(0.0):.1f}" x2="{width}" '
            f'y2="{y(0.0):.1f}" stroke="var(--line)"/>'
            f'<polyline points="{path}" fill="none" '
            f'stroke="var(--accent)" stroke-width="1.5"/></svg>')


def rehearse_bot_form(bot_json, days='7'):
    """T7/U14: rehearse the bot exactly as configured — every setting the
    form knows rides along in the row itself."""
    import html as _html
    return ('<form method="post" action="/rehearse">'
            '<input type="hidden" name="gg" value="1">'
            '<input type="hidden" name="bot_json" value="'
            + _html.escape(bot_json, quote=True) + '">'
            'rehearse this bot over the last <input name="days" size="4" '
            f'value="{_html.escape(str(days), quote=True)}"> days of real '
            'prices <button>rehearse</button> <button name="optimize" '
            'value="1" class="quiet" title="replays your range with 5 to 77 '
            'grids over the last two weeks and shows which did best, and '
            'whether that holds up (T9) — about six minutes while the fleets run; press once" onclick="setTimeout('
            'function(b){b.disabled=1;b.textContent=\'sweeping, about six '
            'minutes\u2026\'},0,this)">compare grid counts</button>'
            '</form>')


def verdict(draft, out, typed=None, bot_json=None, days='7'):
    import html as _html
    form = (rehearse_bot_form(bot_json, days) if bot_json
            else rehearse_form(typed))
    if 'refused' in out:
        return (f'{form}<h1 class="neg">the engine refuses this draft</h1>'
                + refusal_box('not rehearsed', out['refused']))
    if 'windows' in out:                                # T9: two windows
        return form + windows_html(draft, out)
    if 'rows' in out and 'best' in out:                 # T8: the sweep
        return form + sweep_html(draft, out)
    dca = out.get('strategy') == 'martingale'
    rows = ''.join(
        f'<tr><td>{k}</td>{money(v)}</tr>' for k, v in
        [('profit from closed rounds' if dca else 'grid profit',
          out['grid_profit']), ('fees', -out['fees']),
         ('net', out['net']), ('total (incl. open)', out['total']),
         ('hold benchmark', out['hold_benchmark']),
         ('max drawdown', -out['max_drawdown'])])
    curve = curve_svg(out.get('equity_curve') or [])
    holding = (f"<tr><td>ends holding</td><td>{out['held']:.10g}"
               + (f" @ {out['basis']:,.6g}" if out.get('basis') else '')
               + '</td></tr>')
    if dca:
        deepest = int(draft.get('max_averaging_orders') or 0)
        ended = (_html.escape(out['ended']) if out.get('ended') else
                 'still running at the end of the window')
        head = (f"{draft.get('symbol')} {draft.get('side')} DCA — "
                f"{out['bars']} candles of {out.get('bar_minutes', 5)} min")
        detail = (
            f"<tr><td>rounds completed</td><td>{out['rounds']}</td></tr>"
            f"<tr><td>add-on orders filled</td><td>{out['so_fills']}</td></tr>"
            f"<tr><td>deepest add-on reached</td><td>{out['max_depth']} of "
            f"{deepest}</td></tr>"
            f"<tr><td>stops fired</td><td>{out['stops']}</td></tr>"
            f"<tr><td>rounds closed by the hold limit</td>"
            f"<td>{out['max_hold_closes']}</td></tr>" + holding +
            f'<tr><td>how it ended</td><td style="text-align:left;'
            f'white-space:normal">{ended}</td></tr>')
        foot = ("the real bot, replayed against these candles. Each candle "
                "is walked open, worst extreme, best extreme, close, so a "
                "stop comes before a target; resting orders fill when the "
                "price trades through them; anything timed in seconds is "
                "judged at quarter-candle steps. Window shown, never "
                "annualised.")
    else:
        head = (f"{draft.get('symbol')} {draft.get('side')} "
                f"{draft.get('lower')}–{draft.get('upper')} x "
                f"{draft.get('rungs')} — {out['bars']} bars")
        detail = (f"<tr><td>trips / entry fills</td>"
                  f"<td>{out['trips']} / {out['entry_fills']}</td></tr>"
                  + holding)
        foot = ('window shown, never annualised. beat the hold benchmark '
                'or hold.')
    note = (f"from a rehearsal over {days} days: net {out['net']:+,.2f}, "
            f"hold benchmark {out['hold_benchmark']:+,.2f}, "
            f"max drawdown {out['max_drawdown']:,.2f}")
    return (f'{form}<h1>{head}</h1>'
            + (f'<p>{curve}</p>' if curve else '')
            + f'<table>{rows}{detail}</table>'
            f"<p class='dim'>{foot}</p>"
            + '<p>' + setup_button(draft, note) + ' <span class="dim">opens '
            'the advanced form with this draft; every gate still follows'
            '</span></p>')


def waiting_for_restart(fleet_path):
    """U34: the rows a running fleet has not loaded — in the file but not in
    the engine's last snapshot (new), or in the snapshot but gone from the
    file (removed). Both wait for the unit's restart. (ids, ids); nothing
    when the snapshot cannot be read."""
    from gridgremlin.apply import make_botid
    try:
        fleet = json.loads(Path(fleet_path).read_text())
        wd = json.loads(Path(fleet['watchdog']).read_text())
        snap_path = Path(fleet_path).parent.parent / wd['snapshot']
        last = Path(snap_path).read_text().strip().splitlines()[-1]
        running = set(json.loads(last).get('bots') or {})
    except (OSError, ValueError, KeyError, IndexError):
        return [], []
    in_file = [make_botid(b['market_type'], b['symbol'], b['side'])
               for b in fleet.get('bots', [])]
    return ([b for b in in_file if b not in running],
            sorted(running - set(in_file)))


def unit_for_fleet(fleet_path, units):
    """U31: the unit that runs a fleet file, by the tag they share
    (fleet.demo.json -> grid-gremlin3-demo); None when no unit matches."""
    name = Path(fleet_path).name
    tags = [t for t in name.replace('.json', '').split('.')
            if t not in ('fleet', 'json')]
    for u in units:
        if any(t and t in u for t in tags):
            return u
    return None


def other_half_html(pair):
    """D54: after the long half is written, the short half is one button —
    the same three answers, the same mid, its own gates and its own typed
    name. Nothing is made until that is done."""
    if not pair:
        return ''
    import html as _html
    hidden = ''.join(
        f'<input type="hidden" name="{k}" value="{_html.escape(str(v), quote=True)}">'
        for k, v in pair.items())
    return ('<p class="say"><b>This is half of a reversal grid.</b> The '
            f"short half, above the mid {float(pair['mid']):,.6g}, is its "
            'own bot with its own gates and its own name to type:</p>'
            '<form method="post" action="/setup">'
            '<input type="hidden" name="gg" value="1">'
            '<input type="hidden" name="how" value="quick">'
            '<input type="hidden" name="then" value="gates">'
            + hidden +
            '<button>now the short half &rarr;</button></form>')


def other_side_html(bot, fi):
    """U42: after any grid is written on a venue that holds both sides of a
    market, one button offers its mirror on the other side — the same
    width, rungs, money and leverage past its edge — through its own gates
    and its own name. The pair is a reversal grid meeting at that edge."""
    if (bot.get('strategy', 'grid') != 'grid' or bot.get('venue') == 'hyperliquid'
            or bot.get('market_type') != 'linear'
            or not all(k in bot for k in ('lower', 'upper', 'rungs'))):
        return ''
    import html as _html
    long = bot.get('side', 'long') == 'long'
    edge = bot['upper'] if long else bot['lower']
    return ('<p class="say"><b>The other side.</b> A '
            f"{'short' if long else 'long'} grid of the same width, rungs, "
            f"money and leverage {'above' if long else 'below'} {edge:,.6g} "
            'would make this a reversal pair meeting there (D54). Its own '
            'gates, its own name:</p>'
            '<form method="post" action="/setup">'
            '<input type="hidden" name="gg" value="1">'
            '<input type="hidden" name="how" value="mirror">'
            f'<input type="hidden" name="fleet" value="{fi}">'
            '<input type="hidden" name="bot_json" value="'
            + _html.escape(json.dumps(bot), quote=True) + '">'
            '<button class="quiet">make the other side &rarr;</button></form>')


def next_step_html(mode, unit, units):
    """U31 (owner, after applying a bot: "it doesnt appear as if anything
    has happened, or any direction as to where to go?"): the written page
    says what starts now and what waits, and names the step."""
    if mode == 'edit':
        return ('<p><b>Next:</b> changed terms — leverage, investment, '
                'stops, limits, take profit, trailing, repeat — are applied '
                'by the running fleet within seconds (F12; the log says what '
                'it applied). A changed range, grid count or ladder size '
                'waits for the fleet\'s next restart.</p>')
    what = ('the bot leaves the fleet' if mode == 'remove'
            else 'this bot starts')
    if unit:
        how = (f'on <a href="/control">control</a>, choose <b>restart</b>, '
               f'type <b>{unit}</b> and press do it — or restart that unit '
               'from the terminal')
    elif units:
        how = ('on <a href="/control">control</a>, restart the unit that '
               'runs this fleet (' + ', '.join(units) + ')')
    else:
        how = ('restart the fleet process that runs this file (this panel '
               'has no control over units)')
    return (f'<p><b>Next:</b> {what} at the fleet\'s next restart, and not '
            f'before. To restart now: {how}. A restart parks the fleet for '
            'a few seconds — positions and venue-resting orders survive '
            'it — and the new row is probed at start; a row the venue '
            'refuses keeps the whole fleet down until it is fixed.</p>')


def setup_button(draft, note, rungs=None, label='set up this bot &rarr;',
                 quiet=True):
    """U30: a verdict hands its exact draft to the advanced form — the
    panel's own reopen door — with the verdict's words as the note on top.
    Opens the form; a human still walks every gate."""
    from panel.setup import form_from_bot
    import html as _h
    row = {k: v for k, v in (draft or {}).items()
           if not k.startswith('_') and k not in ('rung_weights', 'seed')}
    if rungs is not None:
        row['rungs'] = rungs
        row.pop('rung_sizing', None)        # weights were set aside (T8)
    vals = form_from_bot(row)
    return ('<form method="post" action="/setup" style="display:inline">'
            '<input type="hidden" name="gg" value="1">'
            '<input type="hidden" name="how" value="reopen">'
            '<input type="hidden" name="values" value="'
            + _h.escape(json.dumps(vals), quote=True) + '">'
            '<input type="hidden" name="note" value="'
            + _h.escape(note, quote=True) + '">'
            f'<button{" class=quiet" if quiet else ""}>{label}</button></form>')


def windows_html(draft, out):
    """T9: the sweep read on two windows, the older week's choice tested on
    the newer, and how much of the window the price spent in the range.
    The table is the answer; the sentences say what it means."""
    w14, w7 = out['windows']['14d'], out['windows']['7d']
    head = (f"{draft.get('symbol')} {draft.get('side')} "
            f"{draft.get('lower')}–{draft.get('upper')} — grid counts compared "
            f"over 14 days and the last 7")
    if w14['best'] is None or w7['best'] is None:
        return (f'<h1>{head}</h1>' + refusal_box(
            'no step to name', 'every candidate gap sits inside the '
            'round-trip fee or under the venue\'s minimum for this range — '
            'widen the range or use fewer grids'))
    v7, v14 = out['visited']['7d'], out['visited']['14d']
    oos = out['oos']
    r14 = {r['rungs']: r for r in w14['rows']}
    r7 = {r['rungs']: r for r in w7['rows']}
    lo, hi = w14['plateau']
    rows = ''
    for n in sorted(set(r14) | set(r7)):
        a, b = r14.get(n), r7.get(n)
        if a and 'skipped' in a:
            rows += (f"<tr><td>{n}</td><td>{a['gap_pct']:.2f}%</td>"
                     f"<td class='dim' colspan='4'>{a['skipped']}</td></tr>")
            continue
        gap = (a or b)['gap_pct']
        mark = (' <b>&larr; 14d</b>' if n == w14['best'] else '') + \
               (' <b>&larr; 7d</b>' if n == w7['best'] else '')
        cls = ' class="pos"' if lo <= n <= hi else ''
        share = ('—' if not a or a.get('fee_share') is None
                 else f"{a['fee_share'] * 100:.0f}%")
        rows += (f"<tr{cls}><td>{n}{mark}</td><td>{gap:.2f}%</td>"
                 + (money(b['net']) if b and 'net' in b else
                    '<td class="dim">—</td>')
                 + (money(a['net']) if a and 'net' in a else
                    '<td class="dim">—</td>')
                 + f"<td>{share}</td>"
                 + (money(-a['max_drawdown'], cls=False) if a and 'net' in a
                    else '<td class="dim">—</td>')
                 + '<td>' + setup_button(
                     draft, _row_note(n, a, w14, oos), rungs=n,
                     label=f'set up with {n} grids &rarr;') + '</td></tr>')
    have = out.get('draft_rungs')
    if oos['holds'] is None:
        oos_s = ''
    else:
        verdict_s = ('the choice <b>holds up</b> out of sample.'
                     if oos['holds'] else
                     'the sweep is <b>fitting noise</b> here; hold any choice '
                     'loosely.')
        oos_s = (f"Chosen on the older week alone, <b>{oos['fit_rungs']} "
                 f"grids</b> netted {oos['fit_net_newer']:+,.2f} on the newer "
                 f"week against that week's own best of "
                 f"{oos['newer_best_net']:+,.2f} at {oos['newer_best']} — "
                 + verdict_s)
    visited = (f"The price closed inside your range on {v7:.0f}% of the last "
               f"7 days' candles and {v14:.0f}% of the 14 — "
               + ('a grid earns only where the price goes.'
                  if min(v7, v14) < 60 else
                  'the range was where the price was.'))
    return (f'<h1>{head}</h1>'
            f"<p>Over 14 days <b>{w14['best']} grids</b> made the most "
            f"(net {r14[w14['best']]['net']:+,.2f}; any of <b>{lo}–{hi}</b> "
            f"within 5%); over the last 7, <b>{w7['best']}</b> "
            f"(net {r7[w7['best']]['net']:+,.2f})"
            + (f"; the row has {have}" if have else '') + '. '
            'Nothing is applied here — type the number you choose into the '
            'form above.</p>'
            + (f'<p>{oos_s}</p>' if oos_s else '')
            + f'<p>{visited}</p>'
            + (f"<p class='dim'>every grid was sized equally for the sweep; "
               f"set aside: {', '.join(out['dropped'])}.</p>"
               if out.get('dropped') else '')
            + '<table><tr><th>grids</th><th>gap</th><th>net 7d</th>'
              '<th>net 14d</th><th>fees share</th><th>max drawdown</th>'
              '<th></th></tr>'
            + rows + '</table>'
            "<p class='dim'>score = grid profit − fees, the range exactly as "
            'you set it, the engine\'s own planner, fills on trade-through '
            'through 5-minute candles. Rows in the 14-day plateau are '
            'coloured. Two windows and an out-of-sample test are how a '
            'number earns trust; a sweep is still not a promise. A row\'s '
            'button opens the advanced form with that count and this '
            'page\'s verdict as its note; every gate still follows.</p>')


def _row_note(n, a, w14, oos):
    """U30: the words that travel with a chosen count."""
    lo, hi = w14['plateau']
    where = ('the 14-day best' if n == w14['best'] else
             'inside the 14-day plateau' if lo <= n <= hi else
             'outside the 14-day plateau')
    verdict_s = ('' if oos.get('holds') is None else
                 '; the older week\'s choice holds up out of sample'
                 if oos['holds'] else
                 '; the sweep was fitting noise — hold this loosely')
    net = f", net {a['net']:+,.2f} over 14 days" if a and 'net' in a else ''
    return (f'from a comparison of grid counts over 14 days: {n} grids, '
            f'{where}{net}{verdict_s}')


def sweep_html(draft, out):
    """T8 (D50): the whole table is the answer; the best is named, the
    plateau says how much the choice matters; nothing is applied."""
    head = (f"{draft.get('symbol')} {draft.get('side')} "
            f"{draft.get('lower')}–{draft.get('upper')} — grid counts compared "
            f"over {out['bars']} candles of {out.get('bar_minutes', 5)} min")
    if out['best'] is None:
        return (f'<h1>{head}</h1>' + refusal_box(
            'no step to name', 'every candidate gap sits inside the '
            'round-trip fee for this range — widen the range or use fewer '
            'grids'))
    lo, hi = out['plateau']
    best = next(r for r in out['rows'] if r['rungs'] == out['best'])
    rows = ''
    for r in out['rows']:
        if 'skipped' in r:
            rows += (f"<tr><td>{r['rungs']}</td><td>{r['gap_pct']:.2f}%</td>"
                     f"<td class='dim' colspan='4'>{r['skipped']}</td></tr>")
            continue
        share = ('—' if r['fee_share'] is None
                 else f"{r['fee_share'] * 100:.0f}%")
        mark = ' <b>&larr; best</b>' if r['rungs'] == out['best'] else ''
        cls = ' class="pos"' if lo <= r['rungs'] <= hi else ''
        rows += (f"<tr{cls}><td>{r['rungs']}{mark}</td>"
                 f"<td>{r['gap_pct']:.2f}%</td>{money(r['net'])}"
                 f"<td>{r['trips']}</td><td>{share}</td>"
                 f"{money(-r['max_drawdown'], cls=False)}</tr>")
    have = out.get('draft_rungs')
    return (f'<h1>{head}</h1>'
            f"<p><b>{out['best']} grids</b> (gap {best['gap_pct']:.2f}%) "
            f"made the most over this window, net {best['net']:+,.2f}. "
            f"Any of <b>{lo}–{hi}</b> lands within 5% of it"
            + (f"; the row has {have}" if have else '') + '. '
            'Nothing is applied here — type the number you choose into the '
            'form above.</p>'
            + (f"<p class='dim'>every grid was sized equally for the sweep; "
               f"set aside: {', '.join(out['dropped'])}.</p>"
               if out.get('dropped') else '')
            + '<table><tr><th>grids</th><th>gap</th><th>net</th><th>trips'
            '</th><th>fees share</th><th>max drawdown</th></tr>'
            + rows + '</table>'
            "<p class='dim'>score = grid profit − fees over this window, "
            'the range exactly as you set it, the engine\'s own planner, '
            'fills on trade-through through 5-minute candles. Rows in the '
            'plateau are coloured. Window shown, never annualised; a '
            'sweep is not a promise — same candles are never same fills.'
            '</p>')


COLS = ('<colgroup><col style="width:10%"><col style="width:5%">'
        '<col style="width:4%"><col style="width:7%"><col style="width:5%">'
        '<col style="width:6%">'                            # D63: funding
        '<col style="width:10%"><col style="width:7%"><col style="width:7%">'
        '<col style="width:6%"><col style="width:6%"><col style="width:8%">'
        '<col style="width:7%"><col style="width:8%"><col style="width:8%">'
        '<col style="width:6%"></colgroup>')


def ladder_box(idx, botid, terms):
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
        return f'{v:,.0f}' if abs(v) >= 1000 else f'{v:,.6g}'
    last = rows[-1]
    body = ''.join(
        f'<tr><td>{"base" if r["step"] == 0 else r["step"]}</td>'
        f'<td>{pct(r["fill_pct"])}</td><td>{amount(r["notional"])}</td>'
        f'<td>{amount(r["committed"])}</td><td>{pct(r["avg_pct"])}</td>'
        f'<td>{pct(r["to_tp_pct"])}</td></tr>' for r in rows)
    return (f'<details data-k="{idx}:{botid}:ladder"><summary>the ladder: '
            f'covers a move of <b>{pct(last["fill_pct"])}</b>, then '
            f'{amount(last["committed"])} committed at an average of '
            f'{pct(last["avg_pct"])}</summary><table><tr><th>step</th>'
            '<th>fills at</th><th>size</th><th>committed</th><th>average</th>'
            f'<th>to take-profit</th></tr>{body}</table>'
            '<div class="dim">from the base price; size and committed in '
            f'{(terms or {}).get("quote") or "quote"}</div></details>')


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
    return (f"{botid[3:-1]} {side} "
            f"{'grid' if kind == 'grid' else 'DCA'}{market}")


def _side_tag(botid):
    """U15: long or short at a glance — a coloured tag, the same on the
    card and in the table."""
    side = 'short' if botid.endswith('s') else 'long'
    return f'<span class="side {side}">{side.upper()}</span> '


STATE_WORDS = {
    'NOT STARTED': 'in the fleet file but not yet running — it starts at '
                   'the fleet\'s next restart',
    'RESTING': 'running, holding nothing; its orders rest or wait for the '
               'price to come within reach (see "orders" on the card)',
    'HOLDING': 'running with a position; its exits rest or wait for the '
               'price to come within reach',
    'FLAT': 'running, holding nothing now, and it traded in this window',
    'DEAD': 'stood down — a stop, a limit or a round count ended it; its '
            'reason is on the control page, and revival is deliberate',
}


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


def tidy(page):
    """U46: links are buttons now — the " · " that separated them as text
    only crowds the row. Dropped wherever it stands between two of them."""
    import re
    return re.sub(r'(</a>|<b class="on">[^<]*</b>)\s*(?:·|&middot;)\s*'
                  r'(?=<a\b|<b class="on">)', r'\1 ', page)


def _num_cls(v):
    return 'pos' if v > 0 else 'neg' if v < 0 else 'dim'


def card(idx, botid, b, contract, belief):
    """One bot, one card: its state in a word, what it made, where the
    price sits in its range. Everything the table row said is still here —
    the rest folds under 'the numbers'."""
    rng = (contract.get('ranges') or {}).get(botid)
    ceil = ((contract.get('watchdog') or {}).get('ceilings') or {}).get(botid)
    money_coin, margin_coin = units_of(botid, (contract.get('terms') or {}).get(botid))   # U53
    links = (f"<a href='/edit?fleet={idx}&bot={botid}'>edit</a> · "
             f"<a href='/setup?fleet={idx}&copy={botid}'>copy</a> · "
             f"<a href='/edit?fleet={idx}&bot={botid}&mode=remove'>remove"
             '</a>')
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
        mark, more, note = None, '', ''
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
                    f"{coin_total:+.6f} {st['coin']}</span>")
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
        head = (f'<div class="pnl {_num_cls(total)}">'
                f'<span class="big {_num_cls(total)}">{total:+,.2f}</span> '
                f'{money_coin}{coin} <span class="dim">after fees, {span}</span>'
                f'<div class="parts">'
                f'{pnl_parts(net, b["unreal_at_mark"], b.get("funding"))}'
                f'</div>{since_first_line(contract, botid)}</div>')
        held = holding_html(pos, b['avg_cost'], mark, botid,
                            bool(b.get('inverse')), quote=money_coin)   # U44/U53
        floor = (contract.get('fee_floors') or {}).get(botid)
        unreal = b['unreal_at_mark']
        limit = (f'{abs(pos) / ceil * 100:.0f}% of {ceil:,.4g}' if ceil
                 else 'no limit')
        more = (
            f'<details data-k="{idx}:{botid}"><summary>the numbers'
            '</summary><table>'
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
            + '</table></details>')
    more += ladder_box(idx, botid, (contract.get('terms') or {}).get(botid))   # U52
    capped = (belief.get(botid) or {}).get('capped')
    if capped:
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
        held += (f'</div><div class="{"neg" if away < 5 else "dim"}">'
                 f"liquidates at {mv['liq']:,.6g} · {away:.1f}% away")
    mkt = (contract.get('market') or {}).get(botid)
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
        coin = terms.get('coin') or coin_of(botid)
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
                 f'<div class="dim">price {mark:,.6g} — {place}</div>')
    elif rng:
        where = (f"<div class=\"dim\">range {rng['lower']:,.6g} to "
                 f"{rng['upper']:,.6g}</div>")
    loss = (belief.get(botid) or {}).get('loss')
    if loss and loss.get('limit'):
        # X14: the engine's own count, from its last snapshot
        down = max(0.0, -loss['result'])
        used = down / loss['limit']
        held += (f'</div><div class="{"neg" if used >= 0.75 else "dim"}">'
                 f"loss limit: down {down:,.2f} of {loss['limit']:,.6g} "
                 f'{money_coin} ({used:.0%} used)')
    cls = 'neg' if state == 'DEAD' else 'dim'
    side = 'short' if botid.endswith('s') else 'long'
    flat = (abs(pos) <= 1e-12 if b is not None else
            (belief.get(botid) or {}).get('position') == 0)   # unknown ≠ flat
    if state == 'DEAD' and not botid.startswith('spo') and not flat:
        # X15: what a stopped bot left open can be closed from here — and
        # only then: a bot known to have stood down flat has nothing to
        # close (HL AVAX after its last round, 2026-10-06: the door led to
        # "nothing"); a holding the panel cannot see is still offered —
        # the close page asks the exchange itself
        links += (f" · <a href='/close?fleet={idx}&bot={botid}'>close "
                  'position</a>')
    return (f'<div class="card {side}"><div>'
            f'<span class="side {side}">{side.upper()}</span> <b>'
            f'{_plain_name(botid, contract, b)}</b>{note} '
            f'{state_tag(state, cls)}</div>'
            f'<div>{head}</div>{where}<div class="dim">{held}</div>{more}'
            f'<div class="dim">{botid} · {links}</div></div>')


VIEWS = (('all', 'as listed'), ('side', 'longs / shorts'),
         ('pairs', 'pairs'))


def grouped(contract, view='all'):
    """U12: the venue's bots arranged for reading — [(heading, [(botid,
    b)])]. 'all' is the fleet file's own order under no heading; 'side'
    is the longs, then the shorts; 'pairs' puts a market's long beside its
    short (a pair is one market held both ways), then the rest. An
    arrangement only: every bot appears exactly once in every view."""
    items = list(contract['bots'].items())
    if view == 'side':
        groups = [('longs', [x for x in items if not x[0].endswith('s')]),
                  ('shorts', [x for x in items if x[0].endswith('s')])]
    elif view == 'pairs':
        ids = {botid for botid, _ in items}
        both = {botid[:-1] for botid in ids
                if botid[:-1] + 'l' in ids and botid[:-1] + 's' in ids}
        first = {}
        for n, (botid, _) in enumerate(items):
            first.setdefault(botid[:-1], n)
        paired = sorted((x for x in items if x[0][:-1] in both),
                        key=lambda x: (first[x[0][:-1]], x[0][-1]))
        groups = [('pairs — one market, long and short', paired),
                  ('on their own', [x for x in items
                                    if x[0][:-1] not in both])]
    else:
        return [('', items)]
    return [(title, rows) for title, rows in groups if rows]


def pnl_parts(net, unreal, funding=0.0):
    """U45: what a total is made of — banked after fees, funding paid or
    received (D63, its own line; — when it could not be read), and still
    open."""
    def part(v):
        return ('—' if v is None else
                f'<b class="{_num_cls(v)}">{v:+,.2f}</b>')
    return (f'realised after fees {part(net)} · funding {part(funding)} · '
            f'open {part(unreal)}')


def _day(ms):
    return time.strftime('%Y-%m-%d', time.gmtime(ms / 1000))


def since_first_total(sf):
    """R18: a kept book's whole result, or None when it cannot be whole
    (the ledger behind the window, or an unknown mark on an open book)."""
    if (not sf or sf.get('behind') is not None or not sf.get('whole', True)
            or sf.get('realized') is None):
        return None
    if sf['unreal_at_mark'] is None and abs(sf.get('position') or 0) > 1e-12:
        return None
    return card_total(sf)                                       # D63


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
             f'<b class="{_num_cls(total)}">{total:+,.2f}</b>')
    op = sf.get('opened')
    since = (f'fresh from {_day(op["time_ms"])} (opened holding '
             f'{op["qty"]:,.10g} at {op["price"]:,.6g})' if op
             else f'since {_day(sf["first_ms"])}')
    return (f'<div class="parts">kept history, {since}'
            f' {shown}{star} · {rounds}</div>')


def exchange_leverage(contract):
    """R19: the account's leverage, the owner's measure, in the exchange box."""
    from gridgremlin.report import leverage_lines
    return ''.join(f'<div class="parts lev-now">{now}</div>'
                   f'<div class="parts lev-filled">{filled}</div>'
                   for now, filled in leverage_lines(contract).values())


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


def contract_tiers(contract):
    """D65: each venue's network — first as the running fleet connected to
    it (its snapshot), else as the readout's own client did."""
    belief = ((contract.get('watchdog') or {}).get('belief') or {})
    tiers = dict(belief.get('tiers') or {})
    for venue, fig in (contract.get('account') or {}).items():
        if venue not in tiers and fig and fig.get('tier'):
            tiers[venue] = fig['tier']
    return tiers


def tier_badge(contract):
    """D65: the exchange's own name for the network, on every fleet's
    heading; Mainnet in red. A link to what the networks mean."""
    out = []
    for venue, env in sorted(contract_tiers(contract).items()):
        name = TIER_NAMES.get((venue, env), env)
        cls = 'tier-main' if env == 'mainnet' else 'tier-test'
        out.append(f'<a class="tier {cls}" href="/trading" title="what this '
                   f'means">{name}</a>')
    return ' '.join(out)


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
        total = sum(card_total(b) for b in live)
        belief = ((c.get('watchdog') or {}).get('belief') or {}).get('bots', {})
        dead = sum(1 for bl in belief.values() if bl.get('alive') is False)
        levs = [a['now'] for a in account_leverage(c).values()]
        lev = ('leverage —' if not levs or any(v is None for v in levs) else
               'leverage ' + ' · '.join(f'{v:.2f}x' for v in levs))
        # six cells per fleet in one grid, so every column lines up whatever
        # the words' lengths (the owner: "so it looks squared")
        lines.append(
            f'<div class="fleet"><a href="#fleet{idx}">{label}</a>{tier_badge(c)}'
            f'<span class="big num {_num_cls(total)}">{total:+,.2f} '
            f'<span class="dim">{venue_money(c)}</span></span>'
            f'<span class="dim num">{len(c["bots"])} bots</span>'
            + (f'<b class="neg num">{dead} dead</b>' if dead else '<span></span>')
            + f'<span class="dim">{lev}</span></div>')
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


def cards_section(idx, label, contract, view='all'):
    age = max(0, int(time.time() - contract['generated_ms'] / 1000))
    belief = ((contract.get('watchdog') or {}).get('belief')
              or {}).get('bots', {})
    live = [b for b in contract['bots'].values() if b is not None]
    net = sum(b['realized'] - b['fees'] for b in live)
    funded = [b.get('funding') for b in live]                     # D63
    funding = (None if any(f is None for f in funded)
               else sum(funded))
    opened = [b['unreal_at_mark'] for b in live
              if b['unreal_at_mark'] is not None]
    total = sum(card_total(b) for b in live)
    cards = '</div><div class="cards">'.join(
        (f'<div class="grp">{title}</div>' if title else '')
        + ''.join(card(idx, botid, b, contract, belief)
                  for botid, b in rows)
        for title, rows in grouped(contract, view))
    # U45: the exchange's money in a box of its own, under its name
    return (f"<h1 id=\"fleet{idx}\">{label} {tier_badge(contract)} — {len(contract['bots'])} bots "
            f'{sweep_note(contract)} <span class="dim">(read {age}s ago; '
            f'refreshes every {REFRESH_S}s)</span></h1>'
            f'<div class="pnl {_num_cls(total)}"><span class="dim">this '
            'exchange</span> <span class="big '
            f'{_num_cls(total)}">{total:+,.2f}</span> {venue_money(contract)} '
            '<span class="dim">after fees, each bot counted as its card says</span>'
            f'<div class="parts">'
            f'{pnl_parts(net, sum(opened) if opened else None, funding)}'
            f'</div>{exchange_since_first(contract)}{exchange_leverage(contract)}</div>'
            f'<div class="cards">{cards}</div>')


def section(idx, label, contract, view='all'):
    age = max(0, int(time.time() - contract['generated_ms'] / 1000))
    rows = []
    belief = ((contract.get('watchdog') or {}).get('belief')
              or {}).get('bots', {})
    ordered = []
    for title, members in grouped(contract, view):
        if title:
            ordered.append((None, title))
        ordered += members
    for botid, b in ordered:
        if botid is None:                      # U12: a group's heading row
            rows.append(f'<tr><th colspan="15" class="grp">{b}</th></tr>')
            continue
        if b is None:
            # no fills in the window — the engine's own belief fills in,
            # and says so (the snapshot is the bot's belief, not the venue)
            bl = belief.get(botid, {})
            alive = bl.get('alive')
            pos = bl.get('position') or 0.0
            state = ('DEAD' if alive is False else
                     'HOLDING' if abs(pos) > 1e-12 else 'RESTING')
            cls = 'neg' if state == 'DEAD' else 'dim'
            wd0 = contract.get('watchdog') or {}
            ceil0 = (wd0.get('ceilings') or {}).get(botid)
            watch0 = (f'<td class="dim">{abs(pos) / ceil0 * 100:.0f}% of '
                      f'{ceil0:,.4g}</td>' if ceil0
                      else '<td class="dim">no limit</td>')
            rows.append(
                f'<tr><td>{_side_tag(botid)}{botid}</td>'
                f'<td class="{cls}">{state}</td>'
                f'<td class="dim">0</td><td class="dim">no fills</td>'
                f'<td class="dim">—</td><td class="dim">—</td>'   # D63
                f'<td class="dim">'
                + (f'{pos:.10g} (belief)' if abs(pos) > 1e-12 else '—')
                + '</td><td class="dim">—</td><td class="dim">—</td>'
                  '<td class="dim">—</td><td class="dim">—</td>'
                  '<td class="dim">—</td><td class="dim">—</td>'
                  '<td class="dim">—</td>'
                + watch0
                + f"<td class='dim'><a href='/edit?fleet={idx}&bot={botid}'>"
                  f"edit</a> <a href='/edit?fleet={idx}&bot={botid}"
                  f"&mode=remove'>remove</a> "
                  f"<a href='/setup?fleet={idx}&copy={botid}'>copy</a>"
                  "</td></tr>")
            continue
        state = ('HOLDING' if abs(b['position']) > 1e-12 else 'FLAT')
        openat = (f"{b['position']:.10g} @ {b['avg_cost']:.6g}"
                  if abs(b['position']) > 1e-12 else '—')
        total = card_total(b)                                   # D63
        note = ' *' if b['truncated'] else ''
        rng = contract.get('ranges', {}).get(botid)
        floor = contract.get('fee_floors', {}).get(botid)
        wd = contract.get('watchdog') or {}
        ceil = (wd.get('ceilings') or {}).get(botid)
        if ceil:
            used = abs(b['position']) / ceil * 100
            wcls = ' class="neg"' if used >= 100 else ''
            watch = f'<td{wcls}>{used:.0f}% of {ceil:,.4g}</td>'
        else:
            watch = '<td class="dim">no limit</td>'
        edge = ''
        if rng and b['mark']:
            edge = (f"<td>{strip(rng, b['mark'])}</td>"
                    f"<td class='dim'>{(b['mark'] - rng['lower']) / b['mark'] * 100:.1f}%"
                    f" / {(rng['upper'] - b['mark']) / b['mark'] * 100:.1f}%</td>")
        else:
            edge = '<td class="dim">—</td><td class="dim">—</td>'
        rows.append(
            f'<tr><td>{_side_tag(botid)}{botid}{note}</td>'
            f'<td class="dim">{state}</td>'
            f"<td>{b['fills']}</td>{money(b['realized'])}"
            f"{money(b['fees'], cls=False)}{money(b.get('funding'))}"
            f"<td>{openat}</td>"
            f"{money(b['unreal_at_mark'])}{money(total)}"
            f"<td>{b['bought']:,.4g}</td><td>{b['sold']:,.4g}</td>"
            f"{edge}<td>{settle(b, floor)}</td>{watch}"
            f"<td class='dim'><a href='/edit?fleet={idx}&bot={botid}'>edit"
            f"</a> <a href='/edit?fleet={idx}&bot={botid}&mode=remove'>"
            f"remove</a> <a href='/setup?fleet={idx}&copy={botid}'>copy</a>"
            "</td></tr>")
    return f"""
<h1 id="fleet{idx}">{label} {tier_badge(contract)} — last {contract['window_hours']:g}h {sweep_note(contract)}
<span class="dim">(read {age}s ago; refreshes every {REFRESH_S}s)</span></h1>
<table class="fleet">{COLS}
<tr><th>bot</th><th>state</th><th>fills</th><th>realized</th>
<th>fees</th><th>funding</th><th>open@avg</th><th>unreal</th><th>total</th>
<th>bought</th><th>sold</th><th>range</th><th>edge lo/hi</th>
<th>stop-now est.</th><th>watcher</th><th></th></tr>
{''.join(rows)}</table>
"""


TRADING = """<h1>demo, testnet and mainnet</h1>
<p>Every fleet's heading names the network its exchange connection is on, in
the exchange's own words: Bybit's <b>Demo Trading</b> and <b>Testnet</b>, and
Hyperliquid's <b>Testnet</b>, use play money; <b class="neg">Mainnet</b> is
real money and is shown in red everywhere it appears. The name comes from
what the running fleet actually connected to, not from a file's say-so.</p>
<h2>What this panel will not do</h2>
<p>It cannot move a fleet from play money to real money, or back. Which
network a fleet uses is set outside the panel, in the box's own files, and
real money needs two separate, deliberate switches to agree before a fleet
will start; either one alone is refused. This page does not describe how to
set them.</p>
<h2>What real money asks for first</h2>
<ul>
<li>A long soak on play money: every bot past its minimum days and trades,
no new engine fault for a week, every alarm path seen to work.</li>
<li>Exchange keys made for this alone: trading only, never withdrawal or
transfer, locked to the box's address, on an account set aside for it.</li>
<li>Changes reach real money only after they have run on play money — a
separate, pinned copy of the code that moves when its owner says so.</li>
<li>On a Mainnet fleet, raising a bot's capital or leverage by more than
double asks for the new number twice.</li>
</ul>
<p class="dim">Trading carries risk of loss, more so with leverage. Nothing
here is advice.</p>"""


KEY = """<h1>key — what every word on this page means</h1>
<table><tr><th>term</th><th></th></tr>
<tr><td>realized</td><td class="dim">profit from MATCHED buys and sells,
in quote currency (USDT). Money already made or lost; it never moves
again.</td></tr>
<tr><td>fees</td><td class="dim">what the venue charged for every fill
in the window — already excluded from nothing: total = realized − fees
+ funding + unreal.</td></tr>
<tr><td>USDT · USDC · USD · BTC …</td><td class="dim">every money figure
names its coin (U53): a linear or spot bot's money is its settle coin
(Bybit USDT or USDC, Hyperliquid USDC); an inverse bot's capital, notional,
loss and P&amp;L are dollars ($1 contracts) and its margin is the coin
itself. An exchange's total joins the coins its bots use.</td></tr>
<tr><td>wallet · this bot's book · not this bot's</td><td class="dim">a spot
bot with a stated holding (D76): the coin's whole wallet balance, what this
bot's book says it owns (the stated holding plus its own fills since), and
the difference — coins that are not its. Where the kept ledger can say,
how much of that the inverse bots on the same coin realised there, and what
is left unexplained; red when more than half is unexplained (an outside
hand, or a ledger behind). Funding settles in the coin too and is not
counted.</td></tr>
<tr><td>the ladder</td><td class="dim">a DCA card's own sum (U52): for
each step, where it fills from the base price, its size, what is then
committed, the average entry, and how far the price must come back from
that fill for the whole position to reach take-profit. The summary line
is the drop (a short: the rise) the ladder covers before it runs out.
Percentages of the base price, so it holds before a round and during one.</td></tr>
<tr><td>funding</td><td class="dim">what the bot's position paid (−) or
received (+) in funding over the same window, from the exchange's own
record (D63). A perp holds it; spot has none. — when it could not be
read.</td></tr>
<tr><td>open@avg</td><td class="dim">what the bot HOLDS right now, at
its average cost. This inventory is not profit and not loss yet.</td></tr>
<tr><td>unreal</td><td class="dim">the open remainder marked to the
current price. Moves every second; becomes real only when sold.</td></tr>
<tr><td>total</td><td class="dim">realized − fees + funding + unreal. The
honest sum — the number other dashboards inflate by leaving parts
out.</td></tr>
<tr><td>bought / sold</td><td class="dim">base quantity each way in the
window — how much churn produced the numbers to the left.</td></tr>
<tr><td>range</td><td class="dim">the grid's territory: bar = range,
ticks = rungs, dot = current price.</td></tr>
<tr><td>edge lo/hi</td><td class="dim">distance from price to each end
of the range, as % of price. Small number = near that edge.</td></tr>
<tr><td>stop-now est.</td><td class="dim">roughly what you would receive
if you flattened this bot right now — position at price, minus the
venue fee. An estimate, never a promise.</td></tr>
<tr><td>watcher</td><td class="dim">how much of this bot's watchdog
ceiling its position uses, when you gave it one. The watchdog is the
independent alarm that pages if a position outgrows that limit.</td></tr>
<tr><td>NOT STARTED / RESTING / HOLDING / FLAT</td><td class="dim">not
started = in the fleet file, waits for the fleet's restart; resting =
running, holding nothing; holding = has a position; flat = no position,
traded in this window. Hover any state word for its meaning. A bot rests
only the orders within a few percent of the price (5% unless set) and
places the rest as the price comes near — so a wide grid shows one or two
orders and a position, which is correct; the card's "orders" line says
what rests and what waits.</td></tr>
<tr><td>DEAD</td><td class="dim">the bot stood down and wrote a
tombstone. Its reason is on the control page; revival is deliberate.
</td></tr>
<tr><td>no limit</td><td class="dim">this bot has no position limit of
its own. The account guards (margin, equity floor, drawdown, a stale
fleet) still cover it; a limit is an opt-in.</td></tr>
<tr><td>(belief)</td><td class="dim">a number from the engine's own
snapshot rather than venue records — what the bot believes, seconds
old, honest about its source.</td></tr>
<tr><td>* (star)</td><td class="dim">this bot's numbers come from a
window that opened mid-round: partial by construction. Widen the window
for the whole story.</td></tr>
<tr><td>ZERO-SPREAD (R9)</td><td class="dim">exits that closed inside
the fee of their own cost — churn that pays the venue and nobody else.
Should be zero.</td></tr>
<tr><td>trips / per-trip</td><td class="dim">a trip is an exit that
closed a lot; per-trip is what each exit earned against its own rung (R12),
not the book's average &mdash; a grid that bought cheaper lots on the way
down shows a falling average, and realized against it is not what the trip
earned. The grid's heartbeat.</td></tr>
<tr><td>rounds / SO fills / max depth</td><td class="dim">martingale:
completed rounds; safety orders filled this window; the deepest rung
reached. Depth near max SOs = the schedule nearly exhausted.</td></tr>
<tr><td>hold benchmark</td><td class="dim">what the same capital would
have done just holding over the same window. Beat it or hold.</td></tr>
</table><p><a href="/">&larr; fleet</a></p>"""


# U11: every page off the main one starts with the way back to it. U21
# (owner 2026-10-03): and one step back — a result page's "back" should
# return to the page it came from, not only to the start.
BACK = ('<p><a href="javascript:history.back()">&larr; back</a> · '
        '<a href="/">back to your bots</a> <span class="dim">'
        '— leaving a form saves nothing</span></p>')




def unit_refusal(typed, units, tombs, fleet_bots=None):
    """§12: the typed name is the decision. When it is not a unit, say
    which box it belongs to — a stopped bot's name goes beside its
    tombstone (U20; the owner typed a bot's name into the unit box,
    2026-10-03); a live bot's name is pointed at the unit that runs its
    fleet (U34). `fleet_bots` maps botid -> unit. None when the name is a
    unit."""
    if typed in units:
        return None
    live = next(((b, u) for b, u in (fleet_bots or {}).items()
                 if named(typed, b)), None)
    if live:
        b, u = live
        return (f'<b>{b}</b> is a bot, not a unit. Bots start and stop with '
                'their fleet: to load a new or removed bot, choose '
                f'<b>restart</b> and type <b>{u or "the unit that runs its fleet"}'
                '</b>.')
    bot = next((t for t in tombs if named(typed, t)), None)
    if bot:
        return (f'<b>{bot}</b> is a stopped bot, not a unit. To revive it, '
                'type its name in the small box beside its tombstone '
                '(further down this page) and press <b>revive</b>; the unit '
                'box above is for ' + ', '.join(units) + '.')
    return ('type one of the armed unit names exactly (' + ', '.join(units)
            + ') — a click is not a decision (§12).')


def named(typed, botid):
    """U18: the typed name is the decision; its capitals are not. A bot's
    name is one spelling, so the comparison ignores case and stray space."""
    return bool(botid) and (typed or '').strip().lower() == botid.lower()


def refusal_box(title, why, extra=''):
    """U11: a refusal is the first thing on the page, boxed, in plain
    words: what happened (nothing was saved), the engine's reason, and
    what to do about it."""
    import html as _html
    return (f'<div class="refusal"><b>{_html.escape(title)}</b> — nothing '
            f'was saved.<br>{_html.escape(str(why))}{extra}</div>')


def coin_of(botid):
    """The coin a bot's position is counted in, from its id: linBTCUSDTl ->
    BTC, linBTCPERPl -> BTC, invBTCUSDl -> BTC, linSOLl (Hyperliquid) ->
    SOL."""
    core = botid[3:-1] if len(botid) > 4 else botid
    for quote in ('USDT', 'USDC', 'PERP', 'USD'):
        if core.endswith(quote) and len(core) > len(quote):
            return core[:-len(quote)]
    return core


def units_of(botid, terms):
    """U53: (money coin, margin coin) for a card — from the contract's
    terms; a contract without them answers from the bot's own name."""
    if terms and terms.get('quote'):
        return terms['quote'], terms.get('margin_coin') or terms['quote']
    mt = {'lin': 'linear', 'inv': 'inverse', 'spo': 'spot'}.get(botid[:3], 'linear')
    u = money_units(None, mt, botid[3:-1])
    return u['quote'], u['margin_coin']


def holding_html(pos, avg, mark, botid, inverse=False, quote=None):
    """U44 (owner 2026-10-05: "users can see the value, cost, asset … bybit
    lets you choose these as user preferences"): a holding said three ways
    at once — the coins, what they are worth at the mark, what they cost at
    the average — each in its own span; the page's "size in" switch shows
    one or all, remembered per browser tab. An inverse position is counted
    in dollars by the venue: its coins are dollars / price."""
    if abs(pos) <= 1e-12:
        return 'holding nothing'
    coin = coin_of(botid)
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
    q = f' {quote}' if quote else ''
    parts = [f'<span class="u-coin">{sign}{n(coins)} {coin}</span>',
             f'<span class="u-value">worth {n(value)}{q}</span>',
             f'<span class="u-cost">cost {n(cost)}{q}'
             + (f' ({n(cost_coins)} {coin})' if cost_coins else '')
             + f' @ {avg:.6g}</span>']
    return 'holding ' + '<span class="u-sep"> · </span>'.join(parts)


SIZE_VIEWS = (('all', 'all'), ('coin', 'coins'), ('value', 'value'),
              ('cost', 'cost'))


# V12: the live page reloads whole, so what the reader opened would shut and
# the page would jump on every refresh. This script only remembers, in the
# browser tab: which boxes are open, how far down the page is, and the
# theme. No number passes through it.
KEEP_JS = """<script>(function(){
var S=sessionStorage,open={};
try{open=JSON.parse(S.getItem('gg-open')||'{}');}catch(e){}
document.querySelectorAll('details[data-k]').forEach(function(d){
 if(open[d.dataset.k])d.open=true;
 d.addEventListener('toggle',function(){
  if(d.open)open[d.dataset.k]=1;else delete open[d.dataset.k];
  S.setItem('gg-open',JSON.stringify(open));});});
var root=document.documentElement;
if(S.getItem('gg-light'))root.classList.add('light');
window.ggSize=function(k){['coin','value','cost'].forEach(function(u){
 root.classList.toggle('only-'+u,k===u);});S.setItem('gg-size',k);
 document.querySelectorAll('[data-size]').forEach(function(a){
 a.classList.toggle('pick',a.dataset.size===k);});};
ggSize(S.getItem('gg-size')||'all');
window.ggLev=function(k){root.classList.toggle('lev-on',k==='filled');
 S.setItem('gg-lev',k);document.querySelectorAll('[data-lev]').forEach(
 function(a){a.classList.toggle('pick',a.dataset.lev===k);});};
ggLev(S.getItem('gg-lev')||'now');
new MutationObserver(function(){
 if(root.classList.contains('light'))S.setItem('gg-light','1');
 else S.removeItem('gg-light');}).observe(root,{attributes:true});
window.ggAll=function(on){document.querySelectorAll('details[data-k]')
 .forEach(function(d){d.open=on;});};
var nav=document.querySelector('nav.side'),hero=document.querySelector('.hero');
function top(){if(nav&&hero)nav.style.top=hero.offsetHeight+'px';}
top();window.addEventListener('resize',top);
var y=S.getItem('gg-y:'+location.pathname);
if(y)window.scrollTo(0,Number(y));
window.addEventListener('pagehide',function(){
 S.setItem('gg-y:'+location.pathname,String(window.scrollY));});
})();</script>"""


def nav_panel(table, view):
    """U51 (the owner: the links at the bottom and the switches at the top
    "may be better as a side panel"): every page link and every view
    switch in one panel beside the cards, pinned while the page scrolls —
    pages, arrange, numbers (cards only: nothing folds in the table),
    size in, leverage, theme. The live page only; the export has no
    actions to offer."""
    here = '/table' if table else '/'
    q = '' if view == 'all' else f'?view={view}'
    pages = ((f'<a href="/{q}">cards</a>' if table else
              f'<a href="/table{q}">table</a>')
             + '<a href="/control">control</a><a href="/setup">set up a bot</a>'
               '<a href="/rehearse">rehearse a grid</a><a href="/export">export '
               'snapshot</a><a href="/key">key</a>')
    arrange = ''.join(
        f'<b class="on">{words}</b>' if key == view else
        f'<a href="{here}{"" if key == "all" else "?view=" + key}">{words}</a>'
        for key, words in VIEWS)
    # U22 (owner: "show all … open/close all the numbers"): every card's
    # numbers at once; each box still remembers itself
    numbers = ('' if table else '<h3>numbers</h3><a href="javascript:ggAll(true)">'
               'show all</a><a href="javascript:ggAll(false)">hide all</a>')
    # U44: what a holding is said in, as Bybit's preference
    size = ''.join(f'<a href="javascript:ggSize(\'{k}\')" data-size="{k}">{w}</a>'
                   for k, w in SIZE_VIEWS)
    # R19: the account's leverage now, or as if every order filled
    lev = ('<a href="javascript:ggLev(\'now\')" data-lev="now">now</a>'
           '<a href="javascript:ggLev(\'filled\')" data-lev="filled">if all filled</a>')
    return (f'<nav class="side"><h3>pages</h3>{pages}<h3>arrange</h3>{arrange}'
            f'{numbers}<h3>size in</h3>{size}<h3>leverage</h3>{lev}'
            '<button class="quiet theme" onclick="document.documentElement.'
            'classList.toggle(\'light\')">theme</button></nav>')


def render(labelled, static=None, table=False, view='all'):
    """One renderer, two artefacts (§4): the live page, or — with
    static=timestamp-text — a self-contained export: no refresh, no
    actions, provenance stamped. The numbers can never diverge because
    there is only one code path to diverge from. Two faces of the same
    contract: cards (the default) and the dense table (/table)."""
    face = section if table else cards_section
    if view not in dict(VIEWS):
        view = 'all'
    body = ''.join(face(i, lb, c, view) for i, (lb, c) in enumerate(labelled))
    if static:
        head = ''
        chrome = (f'<p class="dim">exported {static} — a snapshot, '
                  'not a live view; the fleet has moved since.</p>')
    else:                                        # U51: the side panel
        head = f'<meta http-equiv="refresh" content="{REFRESH_S}">'
        body = f'<div class="page">{nav_panel(table, view)}<main>{body}</main></div>'
        chrome = KEEP_JS
    return f"""<!doctype html><meta charset="utf-8">
<title>grid-gremlin</title><style>{CSS}</style>
{head}{hero_strip(labelled)}{body}
{chrome}
<p class="dim">this page renders the engine's own readout contract — it
cannot disagree with the terminal. It holds no keys; venue writes are the
engine's alone.</p>"""


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = 'gg-panel'
    token = ''
    fleets = ()            # venue sections: one per fleet file
    units = ()             # §12: control is opt-in per launch (--units)
    supervise = False      # §13: systemd's laptop twin (--supervise)
    labels = ()
    host_ok = ''
    fleet = ''
    hours = 24.0
    _cache = {}

    def log_message(self, *a):
        pass

    _locks = {}               # U47: one readout per fleet at a time

    def _mainnet(self, fleet_p, venue):
        """D64: is this fleet's venue on Mainnet — by the network its
        running fleet (else the readout) connected to. Unknown is not
        Mainnet: the check asks more of a real-money edit, it never blocks
        a play-money one it cannot place. It reads the readout already held
        (the page being edited from drew it) and never starts one."""
        try:
            _, data = Handler._cache.get(str(fleet_p), (0.0, None))
            return bool(data) and contract_tiers(data).get(venue) == 'mainnet'
        except Exception:                                   # noqa: BLE001
            return False

    def _contract(self, fleet):
        """U47: one readout per fleet at a time. Fresh is served as it is;
        stale is served at once while ONE background refresh runs (the page
        says its age); with nothing yet, the first asker reads and the rest
        wait for that same read. Each asker started its own before, and on
        a slow venue they piled up — 18 demo readouts at once, 350 timeouts
        in an hour, the page and the rehearsal hung (2026-10-06)."""
        import threading
        t, data = Handler._cache.get(fleet, (0.0, None))
        if data is not None and time.time() - t < CACHE_TTL_S:
            return data
        lock = Handler._locks.setdefault(fleet, threading.Lock())
        if data is not None:
            if lock.acquire(blocking=False):
                def refresh():
                    try:
                        self._read_contract(fleet)
                    except Exception as e:                   # noqa: BLE001
                        print(f'panel: readout {fleet}: {e}', flush=True)
                    finally:
                        lock.release()
                threading.Thread(target=refresh, daemon=True).start()
            return data                       # stale, its age on the page
        with lock:
            t, data = Handler._cache.get(fleet, (0.0, None))
            if data is not None:              # the read we waited for
                return data
            return self._read_contract(fleet)

    def _read_contract(self, fleet):
        raw = json.loads(Path(fleet).read_text()) if Path(fleet).exists() \
            else {}
        if not raw.get('bots'):
            # a just-initialised world: nothing to report on yet, and the
            # engine's own report would (rightly) refuse an empty fleet
            return {'window_hours': self.hours,
                    'generated_ms': int(time.time() * 1000),
                    'bots': {}, 'unowned': {}}
        out = subprocess.run(
            [sys.executable, '-m', 'gridgremlin.report', fleet,
             '--hours', str(self.hours), '--json'],
            capture_output=True, text=True, timeout=120)
        data = json.loads(out.stdout)
        Handler._cache[fleet] = (time.time(), data)
        return data

    def _labelled(self):
        return [(lb, self._contract(f))
                for lb, f in zip(self.labels, self.fleets)]

    def _authed(self):
        return f'gg={self.token}' in (self.headers.get('Cookie') or '')

    def _deny(self, code, why):
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(why.encode())

    def do_GET(self):
        if self.headers.get('Host', '') != self.host_ok:
            return self._deny(403, 'wrong Host')       # rebinding defence
        if self.path.startswith('/?t='):
            if secrets.compare_digest(self.path[4:], self.token):
                self.send_response(303)
                self.send_header('Set-Cookie',
                                 f'gg={self.token}; HttpOnly; SameSite=Strict')
                self.send_header('Location', '/')
                self.end_headers()
                return
            return self._deny(403, 'bad token')
        if not self._authed():
            return self._deny(401, 'open the tokened URL from the terminal')
        missing = [f for f in self.fleets if not Path(f).exists()]
        if missing and self.path.split('?')[0] == '/':
            f0 = missing[0]
            return self._page(
                f'<h1>first run — {f0} does not exist yet</h1>'
                '<p class="dim">init writes a minimal valid fleet + '
                'watchdog pair; then the create flow takes over. The '
                'engine will refuse to start until the first bot exists — '
                'nothing trades unwatched, and nothing trades empty.</p>'
                f'<form method="post" action="/init">'
                f'<input type="hidden" name="gg" value="1">'
                f'<input type="hidden" name="path" value="{f0}">'
                '<table><tr><th>name (tag)</th><th>equity floor</th>'
                '<th>max margin rate</th></tr><tr>'
                '<td><input name="tag" value="mine" size="10"></td>'
                '<td><input name="equity_min" size="8" '
                'placeholder="e.g. 500"></td>'
                '<td><input name="mm_rate_max" value="0.5" size="5"></td>'
                '</tr></table><button>write the pair</button></form>'
                '<p class="dim">equity floor: the watchdog pages if account '
                'equity falls below this. Margin rate 0.5 = alarm at 50% '
                'of maintenance margin.</p>')
        if self.path == '/key':
            return self._page(KEY)
        if self.path == '/trading':
            return self._page(TRADING)
        if self.path == '/control':
            return self._control_page()
        if self.path == '/export':
            import email.utils
            stamp = email.utils.formatdate(usegmt=True)
            body = render(self._labelled(), static=stamp)
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Disposition',
                             'attachment; filename="grid-gremlin-'
                             + time.strftime('%Y%m%d-%H%M%S') + '.html"')
            self.end_headers()
            self.wfile.write(tidy(body).encode())
            return
        if self.path.startswith('/close?'):
            return self._close_page()
        if self.path.startswith('/edit?'):
            return self._edit_page()
        if self.path == '/create' or self.path.split('?')[0] == '/setup':
            return self._setup_page()
        if self.path.startswith('/rehearse?job='):
            return self._rehearse_job_page(self.path.split('job=', 1)[1][:16])
        if self.path == '/rehearse':
            body = (f'<!doctype html><meta charset="utf-8">'
                    f'<title>rehearse</title><style>{CSS}</style>{FORM}')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(tidy(body).encode())
            return
        base, _, query = self.path.partition('?')
        view = dict(urllib.parse.parse_qsl(query)).get('view', 'all')
        body = (json.dumps({lb: c for lb, c in self._labelled()})
                if self.path == '/data' else
                render(self._labelled(), table=base == '/table', view=view))
        self.send_response(200)
        self.send_header('Content-Type',
                         'application/json' if self.path == '/data'
                         else 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(tidy(body).encode())


    def do_POST(self):
        if self.headers.get('Host', '') != self.host_ok:
            return self._deny(403, 'wrong Host')
        if not self._authed():
            return self._deny(401, 'open the tokened URL from the terminal')
        origin = self.headers.get('Origin', '')
        if origin and origin != f'http://{self.host_ok}':
            return self._deny(403, 'wrong Origin')     # cross-site write
        try:                                     # a negative length read
            n = int(self.headers.get('Content-Length') or 0)   # to EOF and
        except ValueError:                                     # hung (audit
            n = 0                                              # 2026-10-05)
        raw = self.rfile.read(max(0, min(n, 16384))).decode(errors='replace')
        form = dict(urllib.parse.parse_qsl(raw))
        if form.pop('gg', None) != '1':
            return self._deny(403, 'missing form token')
        if self.path in ('/create', '/apply'):
            return self._create_flow(form, apply=self.path == '/apply')
        if self.path == '/setup':
            return self._setup_post(form)
        if self.path == '/chart':
            return self._chart_post(form)
        if self.path == '/whatif':
            return self._whatif_post(form)
        if self.path in ('/unit', '/revive'):
            return self._control_act(form, self.path)
        if self.path == '/close':
            return self._close_act(form)
        if self.path == '/init':
            from panel.create import init_pair
            try:
                # only a fleet file this panel was started on: init wrote
                # wherever the form named (audit 2026-10-05)
                want = Path(form.get('path', '')).resolve()
                if want not in {Path(f).resolve() for f in self.fleets}:
                    raise ValueError('init writes only the fleet file this '
                                     'panel was started on')
                wp = init_pair(str(want), form.get('tag', 'mine'),
                               _f(form.get('equity_min')),
                               _f(form.get('mm_rate_max')) or 0.5)
            except Exception as e:                          # noqa: BLE001
                return self._page(f'<h1 class="neg">init refused</h1>'
                                  f'<p class="neg">{html.escape(str(e))}</p>')
            return self._page(f'<h1>written</h1><p>fleet + watcher pair '
                              f'created ({wp.name} beside it). '
                              '<a href="/create">create your first bot '
                              '&rarr;</a></p>')
        if self.path != '/rehearse':
            return self._deny(404, 'no such action')
        bot_json = form.get('bot_json')
        if bot_json:                   # U14: the bot exactly as configured
            try:
                draft = json.loads(bot_json)
            except ValueError:
                draft = {}
            draft = {k: v for k, v in draft.items() if not k.startswith('_')}
        else:
            draft = {'market_type': 'linear', 'venue': 'bybit',
                     'symbol': form.get('symbol', '').upper(),
                     'side': form.get('side', 'long'),
                     'capital': _f(form.get('capital')),
                     'lower': _f(form.get('lower')),
                     'upper': _f(form.get('upper')),
                     'rungs': int(_f(form.get('rungs')) or 0)}
        days = _f(form.get('days'))
        if not days or days <= 0:
            result = {'refused': '"days": how many days of history to '
                                 'replay? Type a number, like 7'}
        elif days > 90:
            result = {'refused': '"days": 90 at most — a longer replay '
                                 'takes minutes of candles to fetch'}
        else:
            # U23/T9: compare grid counts always reads 14 days and splits them —
            # about six minutes of replays on the box beside the fleets, shown live (U26);
            # the days box is the rehearsal's. The terminal has no limit.
            # U26: the rehearsal is a JOB — the page answers at once and
            # refreshes itself with the engine's own progress words until
            # the verdict is in (a spinner that spins whether or not
            # anything happens would have lied for five minutes, 10-04)
            job = self._start_rehearsal(form, draft, bot_json, days)
            if job is None:
                result = {'refused': f'{self.JOBS_MAX} rehearsals are already '
                                     'running on this one-core box — wait for '
                                     'one to finish, then press again'}
                self._send_html(self._rehearse_html(form, draft, bot_json,
                                                    result))
                return
            self.send_response(303)
            self.send_header('Location', f'/rehearse?job={job}')
            self.end_headers()
            return
        self._send_html(self._rehearse_html(form, draft, bot_json, result))

    _jobs = {}                       # job id -> dict (class-wide, in memory)
    JOBS_MAX = 2                     # rehearsals at once (audit 2026-10-05)
    JOB_KEEP = 900.0                 # a finished verdict stays 15 minutes
    LEAVE_SECONDS = 12.0             # U29: three missed refreshes = gone

    def _rehearse_html(self, form, draft, bot_json, result):
        return (f'<!doctype html><meta charset="utf-8"><title>rehearse'
                f'</title><style>{CSS}</style>'
                + BACK + verdict(draft, result, typed={
                    k: form[k] for k in ('symbol', 'side', 'lower', 'upper',
                                         'rungs', 'capital', 'days')
                    if k in form}, bot_json=bot_json,
                    days=form.get('days', '7')))

    def _send_html(self, body):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(tidy(body).encode())

    def _start_rehearsal(self, form, draft, bot_json, days):
        import threading
        now = time.time()
        for k, j in list(self._jobs.items()):            # sweep the old
            if j.get('done') and now - j['t0'] > self.JOB_KEEP:
                self._jobs.pop(k, None)
        live = sum(1 for j in self._jobs.values() if not j.get('done'))
        if live >= self.JOBS_MAX:              # one core: a queue of replays
            return None                        # starves the fleets (U23)
        job = secrets.token_hex(4)
        self._jobs[job] = {'t0': now, 'form': dict(form), 'draft': draft,
                           'bot_json': bot_json, 'days': days,
                           'optimize': form.get('optimize') == '1',
                           'progress': 'starting', 'frac': 0.0,
                           'seen': now, 'cancelled': False,
                           'done': False, 'result': None}
        threading.Thread(target=self._rehearsal_runner,
                         args=(self._jobs[job],), daemon=True).start()
        return job

    @staticmethod
    def _rehearsal_runner(job):
        """Runs the engine's CLI as a subprocess under the fleets' priority
        (U23), reads its progress words from stderr as they come, keeps
        the verdict. Specs swap this function for a fake."""
        # `nice` as the command, not preexec_fn: preexec_fn is unsafe in a
        # threaded server (audit 2026-10-05)
        args = (['nice', '-n', '10', sys.executable, '-m',
                 'gridgremlin.backtest_cli', '--draft', '--days',
                 f"{job['days']:g}"]
                + (['--windows'] if job['optimize'] else []))   # T9
        try:
            proc = subprocess.Popen(args, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)
            proc.stdin.write(json.dumps(job['draft']))
            proc.stdin.close()
            import threading
            threading.Thread(target=Handler._leave_watch,
                             args=(job, proc), daemon=True).start()
            # stdout drains beside stderr: reading it only after stderr
            # closed could deadlock on a verdict over 64 KB
            got = []
            reader = threading.Thread(target=lambda: got.append(
                proc.stdout.read()), daemon=True)
            reader.start()
            last = 'no reason given'
            for line in proc.stderr:                     # progress, live
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    p = msg.get('progress')
                except (ValueError, AttributeError):
                    msg, p = {}, None
                if p:
                    job['progress'] = p
                    if msg.get('frac') is not None:
                        job['frac'] = float(msg['frac'])
                else:
                    last = line
            try:
                reader.join(timeout=300)
                out = got[0] if got else ''
                proc.wait(timeout=300)
            except subprocess.TimeoutExpired:
                proc.kill()
                job['result'] = {'refused': 'the rehearsal took longer than '
                                            'five minutes — try fewer days'}
                return
            if job.get('cancelled'):
                job['result'] = {'refused': 'stopped — you left the page for '
                                            'more than ten seconds, so the '
                                            'run was ended; run it again when '
                                            'you can stay'}
                return
            try:
                job['result'] = (json.loads(out) if out.strip() else
                                 {'refused': f'the rehearsal stopped: {last}'})
            except ValueError:
                job['result'] = {'refused': 'the rehearsal answered '
                                            'something unreadable — try again'}
        except OSError as e:
            job['result'] = {'refused': f'the rehearsal could not start: {e}'}
        finally:
            job['done'] = True

    @staticmethod
    def _leave_watch(job, proc, clock=time.time, sleep=time.sleep):
        """U29 (owner: "when the page does go back, it kills the function"):
        the page's refreshes are its heartbeat; three missed ones and the
        subprocess is ended. Returns True when it ended the run."""
        while proc.poll() is None:
            if clock() - job['seen'] > Handler.LEAVE_SECONDS:
                job['cancelled'] = True
                try:
                    proc.kill()
                except OSError:
                    pass
                return True
            sleep(2.0)
        return False

    def _rehearse_job_page(self, job_id):
        job = self._jobs.get(job_id)
        if job is None:
            return self._send_html(
                f'<!doctype html><meta charset="utf-8"><title>rehearse'
                f'</title><style>{CSS}</style>{BACK}'
                + refusal_box('no such rehearsal', 'it finished more than '
                              'fifteen minutes ago, or the panel was '
                              'restarted — run it again'))
        if job['done']:
            return self._send_html(self._rehearse_html(
                job['form'], job['draft'], job['bot_json'], job['result']))
        import html as _h
        job['seen'] = time.time()                     # U29: the heartbeat
        elapsed = int(time.time() - job['t0'])
        what = 'compare grid counts' if job['optimize'] else 'rehearsal'
        pct = max(0, min(100, int(round((job.get('frac') or 0.0) * 100))))
        return self._send_html(
            f'<!doctype html><meta charset="utf-8">'
            '<meta http-equiv="refresh" content="3">'
            f'<title>working</title><style>{CSS}</style>{BACK}'
            f'<h1>{what}: working <span class="dim">· {elapsed}s</span></h1>'
            f'<div class="bar" title="{pct}%"><div style="width:{pct}%">'
            '</div></div>'
            f"<p>{_h.escape(str(job['progress']))} "
            f'<span class="dim">— {pct}%</span></p>'
            '<p class="dim">this page refreshes itself every three seconds '
            'with the engine\'s own words, and the verdict appears here in '
            'their place. <b>Leaving this page stops the run</b>: if it has '
            'not been seen for ten seconds the engine is told to stop, and '
            'you start again when you can stay. Another tab is fine; it is '
            'this page that must stay open.</p>')


    def _page(self, body):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(tidy(f'<!doctype html><meta charset="utf-8">'
                              f'<title>create</title><style>{CSS}</style>'
                              + BACK + body).encode())

    def _create_flow(self, form, apply=False):
        from panel.create import (atomic_write, dry_ladder, dump_config,
                                  merge_proposal, public_adapter,
                                  public_mark, unified_diff, validate_whole)
        fi = int(_f(form.get('fleet')) or 0)
        fleet_p = Path(self.fleets[min(fi, len(self.fleets) - 1)])
        fleet_raw = json.loads(fleet_p.read_text())
        wd_p = Path(fleet_raw['watchdog'])
        wd_raw = json.loads(wd_p.read_text())
        mode = form.get('mode', 'create')
        if apply:
            proposal = json.loads(form.get('proposal', '{}'))
            mode = proposal.get('mode', 'create')
        elif mode == 'remove':
            proposal = {'mode': 'remove', 'orig': form.get('orig', '')}
        elif form.get('bot_json'):                # §11: the setup form's row
            proposal = {'mode': mode, 'orig': form.get('orig', ''),
                        'bot': json.loads(form['bot_json']),
                        'watchdog': {'max': _f(form.get('ceiling'))}}
            if form.get('pair'):                         # D54: the other half
                proposal['pair'] = json.loads(form['pair'])
        else:
            return self._refused(form, 'refused', 'nothing to create — '
                                 'start from "set up a bot"')
        try:
            from panel.create import edit_proposal, remove_proposal
            if mode == 'remove':
                botid, fleet, wd = remove_proposal(fleet_raw, wd_raw,
                                                   proposal['orig'])
                vbot = adapter = None
            else:
                from gridgremlin.config import (validate_grid,
                                                validate_martingale)
                from gridgremlin.config import apply_profile, validate_profiles
                is_mg = proposal['bot'].get('strategy') == 'martingale'
                merged = apply_profile(dict(proposal['bot']), validate_profiles(
                    fleet_raw.get('risk_profiles'), 'fleet'))        # D57
                vbot = (validate_martingale(merged) if is_mg
                        else validate_grid(merged))
                adapter = public_adapter(vbot)               # defaults (A1)
                if is_mg:
                    # the engine learns this only at the first cycle
                    # ("base order below minimum") — say it at the form
                    from gridgremlin.config import ConfigError as _CE
                    m0 = public_mark(vbot)
                    q0 = adapter.round_qty(vbot['base_order_size'] / m0)
                    if q0 <= 0 or not adapter.meets_minimum(q0, m0):
                        raise _CE(
                            f"the first order ({vbot['base_order_size']:g}) "
                            "is smaller than this market's minimum order "
                            f"({adapter.min_notional:g}, or "
                            f"{adapter.min_qty:g} coins) — raise the "
                            'investment, use fewer add-on orders, or raise the '
                            'leverage')
                if mode == 'edit':
                    botid, fleet, wd = edit_proposal(
                        fleet_raw, wd_raw, proposal['orig'],
                        proposal['bot'], proposal['watchdog']['max'])
                else:
                    botid, fleet, wd = merge_proposal(fleet_raw, wd_raw,
                                                      proposal)
            refusal = validate_whole(fleet, wd, lambda cfg: adapter
                                     if adapter is not None
                                     and cfg is proposal.get('bot')
                                     else public_adapter(cfg))
        except Exception as e:                              # noqa: BLE001
            return self._refused(form, 'refused', e)
        if refusal:
            return self._refused(form, 'the engine refuses this fleet',
                                 refusal)
        new_fleet = dump_config(fleet)
        new_wd = dump_config(wd)
        from panel.create import retype_refusal, size_jumps
        jumps = (size_jumps(fleet_raw, mode, proposal.get('orig'),
                            proposal.get('bot'))
                 if self._mainnet(fleet_p, (proposal.get('bot') or {})
                                  .get('venue', 'bybit')) else [])   # D64
        if apply:
            again = retype_refusal(jumps, form)
            if again:
                return self._page(refusal_box('not applied', again))
            if not named(form.get('confirm'), botid):
                return self._page(refusal_box(
                    'not applied', f'the name typed must be {botid} '
                    '(capitals do not matter) — a click is not a decision '
                    '(§11). Go back and type it in the box.'))
            atomic_write(fleet_p, new_fleet)
            atomic_write(wd_p, new_wd)
            return self._page(
                f'<h1>{botid}: written</h1><p>bot and watcher landed '
                'together in the fleet file; a backup is kept beside each '
                'file.</p>'
                + other_half_html(proposal.get('pair'))
                + (other_side_html(proposal['bot'], fi)
                   if mode == 'create' and not proposal.get('pair') else '')
                + next_step_html(mode, unit_for_fleet(fleet_p, self.units),
                                 self.units)
                + '<p><a href="/">back to your bots</a> — the new card is '
                'there, marked as waiting for the restart.</p>')
        if mode == 'remove':
            ladder_html = '<p class="dim">removal: no ladder to dry-run — '\
                          'the diff is the whole change.</p>'
        elif proposal['bot'].get('strategy') == 'martingale':
            from panel.create import martingale_preview
            mark = public_mark(vbot)
            rows_, full = martingale_preview(vbot, mark)
            lrows = ''.join(
                f"<tr><td>{'base' if r['rung'] == 0 else 'SO ' + str(r['rung'])}"
                f"</td><td>{r['price']:,.6g}</td>"
                f"<td>{r['notional']:,.6g}</td><td>{r['qty']:,.6g}</td>"
                f"<td>{r['cum_notional']:,.6g}</td>"
                f"<td>{r['cum_qty']:,.6g}</td></tr>" for r in rows_)
            ladder_html = (
                f'<p class="dim">the deviation ladder anchored at mark '
                f'{mark:,.6g} — prices move with the anchor; sizes and '
                f'depth do not</p><table><tr><th>rung</th><th>price</th>'
                f'<th>notional</th><th>qty</th><th>cum notional</th>'
                f'<th>cum qty</th></tr>{lrows}</table>'
                f'<p class="dim">full depth: {full:,.6g} base — the '
                f'ceiling watches this number.</p>')
        else:
            mark = public_mark(vbot)
            ladder = dry_ladder(vbot, adapter, mark)
            lrows = ''.join(
                f"<tr><td>{o['side']}</td><td>{o['price']:,.6g}</td>"
                f"<td>{o['qty']:,.6g}</td></tr>" for o in ladder)
            ladder_html = (f'<p class="dim">the ladder at mark '
                           f'{mark:,.6g} (dry-run — nothing placed)</p>'
                           f'<table><tr><th>side</th><th>price</th>'
                           f'<th>qty</th></tr>{lrows}</table>')
        diffs = (unified_diff(fleet_p.read_text(), new_fleet, fleet_p.name)
                 + unified_diff(wd_p.read_text(), new_wd, wd_p.name))
        pj = html.escape(json.dumps(proposal), quote=True)
        say = ''
        if proposal.get('pair'):                           # D54
            say = ('<p class="dim">the long half of a reversal grid, below '
                   f"the mid {float(proposal['pair']['mid']):,.6g}; the "
                   'short half above it follows once this one is written '
                   '(D54).</p>')
        if mode != 'remove':
            import html as _html
            from panel.setup import form_from_bot, sentence
            vals = dict(form_from_bot(proposal['bot']),
                        ceiling=form.get('ceiling', ''))
            vj = _html.escape(json.dumps(vals), quote=True)
            try:                   # the same bot, drawn on its price
                from panel.chart import chart_svg, levels
                picture = chart_svg(self._bars_for(vbot),
                                    levels(vbot, mark), mark)
            except Exception as e:                          # noqa: BLE001
                picture = (f'<p class="dim">no chart: '
                           f'{_html.escape(str(e))}</p>')
            try:                   # and what a straight move would do
                from panel.whatif import section as whatif_section
                Handler._adapters[self._market_key(vbot)] = (time.time(),
                                                             adapter)
                picture += whatif_section(
                    vbot, adapter, mark, json.dumps(proposal['bot']), fi)
            except Exception as e:                          # noqa: BLE001
                picture += (f'<p class="dim">no what-if: '
                            f'{_html.escape(str(e))}</p>')
            say += (f'<h1 class="dim">in plain words</h1><p class="say">'
                    f'{_html.escape(sentence(vbot, mark))}</p>' + picture)
        if mode in ('create', 'edit'):
            say += ('<form method="post" action="/setup">'
                    '<input type="hidden" name="gg" value="1">'
                    '<input type="hidden" name="how" value="reopen">'
                    '<input type="hidden" name="orig" value="'
                    + html.escape(proposal['orig'] if mode == 'edit'
                                  else '', quote=True) + '">'
                    f'<input type="hidden" name="fleet" value="{fi}">'
                    f'<input type="hidden" name="values" value="{vj}">'
                    '<button class="quiet">change something</button></form>')
            if proposal['bot'].get('venue', 'bybit') == 'bybit':
                # U14: the rehearsal, one click from the summary
                say += ('<p>' + rehearse_bot_form(json.dumps(proposal['bot']))
                        + '</p>')
        verb = {'create': 'create this bot', 'edit': 'apply the change',
                'remove': 'remove this bot'}[mode]
        # U17: the apply box sits right under the summary; the file diff
        # and the dry-run orders fold away for whoever wants them
        return self._page(
            f'<h1>{botid} — {mode}: gates passed</h1>' + say +
            f'<form method="post" action="/apply" class="apply">'
            f'<input type="hidden" name="gg" value="1">'
            f'<input type="hidden" name="fleet" value="{fi}">'
            f'<input type="hidden" name="proposal" value="{pj}">'
            f'<b>To {verb}</b>, type its name <code>{botid}</code> here: '
            f'<input name="confirm" size="16" placeholder="{botid}"> '
            + ''.join(f'<br><b class="neg">Mainnet:</b> type the new {k} '
                      f'(<code>{n:g}</code>) again: <input name="retype_{k}" '
                      'size="12">' for k, _, n in jumps)
            + f'<button>{verb}</button></form>'
            '<p class="dim">this writes the fleet file. A running fleet '
            'takes changed terms within seconds; a new bot, a removed one '
            'or a changed range waits for a restart (F12).</p>'
            '<details><summary>the change to the file</summary>'
            f'<pre class="dim">{html.escape(diffs)}</pre></details>'
            '<details><summary>the orders it would place</summary>'
            + ladder_html + '</details>')


    def _fleet_labels(self):
        return [Path(f).name for f in self.fleets]

    def _fleet_bots(self):
        """U34: every bot in every fleet file -> the unit that runs it."""
        from gridgremlin.apply import make_botid
        out = {}
        for f in self.fleets:
            try:
                bots = json.loads(Path(f).read_text()).get('bots', [])
            except (OSError, ValueError):
                continue
            u = unit_for_fleet(f, self.units)
            for b in bots:
                out[make_botid(b['market_type'], b['symbol'], b['side'])] = u
        return out

    def _symbols(self, fi):
        """U25: the fleet's venue's markets for the coin list; () when the
        venue cannot be read — the box is keyless and may be offline."""
        from panel.create import public_symbols
        return public_symbols(self._fleet_venue(fi))

    def _fleet_venue(self, fi):
        """A fleet file trades one venue: its first row says which."""
        try:
            bots = json.loads(Path(self.fleets[fi]).read_text()).get('bots')
        except (OSError, ValueError):
            bots = None
        return (bots[0].get('venue', 'bybit') if bots else 'bybit')

    def _refused(self, form, title, why):
        """A refusal returns to the form it came from, values intact."""
        fi = int(_f(form.get('fleet')) or 0)
        extra = ''
        if 'already in this fleet' in str(why):
            # the commonest refusal, said as what to do next (U11)
            botid = str(why).split(':', 1)[0]
            extra = ('<br>You already have a bot for this coin and '
                     'direction in this account, and there can be only '
                     f'one. <a href="/edit?fleet={fi}&bot={botid}">Open '
                     'that bot to change it</a>, or pick another coin or '
                     'the other direction below.')
        note = refusal_box(title, why, extra)
        if form.get('bot_json'):
            from panel.setup import advanced_page, form_from_bot
            bot = json.loads(form['bot_json'])
            vals = dict(form_from_bot(bot), ceiling=form.get('ceiling', ''))
            return self._page(advanced_page(
                bot.get('strategy', 'grid'), vals, self._fleet_labels(),
                fi, alert=note, edit=form.get('orig') or None))
        return self._page(note + '<p><a href="/setup">set up a bot</a> · '
                          '<a href="/">fleet</a></p>')

    def _setup_page(self):
        from panel.setup import advanced_page, form_from_bot, quick_page
        q = (dict(urllib.parse.parse_qsl(self.path.split('?', 1)[1]))
             if '?' in self.path else {})
        fi = min(int(_f(q.get('fleet')) or 0), len(self.fleets) - 1)
        labels = self._fleet_labels()
        if q.get('copy'):
            from gridgremlin.apply import make_botid as _mb
            bots = json.loads(Path(self.fleets[fi]).read_text()).get(
                'bots', [])
            src = next((b for b in bots if _mb(
                b['market_type'], b['symbol'], b['side']) == q['copy']),
                None)
            if src is None:
                return self._deny(404, f"{q['copy']}: not in this fleet")
            vals = form_from_bot(src)
            vals['symbol'] = ''        # one bot per market and side (I2)
            return self._page(advanced_page(
                src.get('strategy', 'grid'), vals, labels, fi,
                note=f'<p class="dim">copied from {q["copy"]}: every '
                     'setting is carried over — choose the coin, and '
                     'check the prices, which belong to the old one.</p>'))
        if q.get('adv') in ('grid', 'martingale'):
            return self._page(advanced_page(q['adv'], {}, labels, fi,
                                            symbols=self._symbols(fi)))
        return self._page(quick_page(labels, fi, symbols=self._symbols(fi)))

    _bars = {}                       # (venue, market, symbol) -> (t, bars)

    def _bars_for(self, cfg):
        """Public candles, kept five minutes: a drag redraws, it does not
        refetch a month of history."""
        from panel.create import public_bars
        key = (cfg.get('venue'), cfg.get('market_type'), cfg.get('symbol'))
        hit = Handler._bars.get(key)
        if hit and time.time() - hit[0] < 300:
            return hit[1]
        bars = public_bars(cfg)
        Handler._bars[key] = (time.time(), bars)
        return bars

    def _chart_post(self, form):
        """The form as it stands, drawn on its price. Returns an SVG
        fragment (or one line of plain words) for the page to swap in."""
        import html as _html
        from panel.chart import chart_svg, form_levels
        from panel.setup import bot_from_form
        fi = min(int(_f(form.get('fleet')) or 0), len(self.fleets) - 1)
        symbol = (form.get('symbol') or '').strip().upper()
        if not symbol:
            return self._fragment('<p class="dim">the price chart draws '
                                  'here once a coin is typed.</p>')
        try:
            row = bot_from_form(form, self._fleet_venue(fi))
            row.setdefault('market_type', 'linear')
            bars = self._bars_for(row)
            mark = bars[-1]['c'] if bars else None
            lines, fill = form_levels(row, mark)
            body = chart_svg(bars, lines, mark, drag=True, fill=fill)
        except Exception as e:                              # noqa: BLE001
            body = (f'<p class="dim">no chart yet: {_html.escape(str(e))}'
                    '</p>')
        return self._fragment(body)

    _adapters = {}                   # (venue, market, symbol) -> (t, adapter)

    @staticmethod
    def _market_key(cfg):
        return (cfg.get('venue'), cfg.get('market_type'), cfg.get('symbol'))

    def _whatif_post(self, form):
        """One straight move of the price, answered in plain words (U9).
        The bot is validated again here; the market's rounding rules are
        kept five minutes so the slider does not refetch them."""
        import html as _html
        import panel.create as pc
        from gridgremlin.config import validate_config
        from panel.whatif import SLIDER_MAX, answer, entries
        try:
            cfg = validate_config(json.loads(form.get('bot_json', '')))
            mark = float(form.get('mark', ''))
            move = float(form.get('move', ''))
            if not mark > 0 or abs(move) > SLIDER_MAX:
                raise ValueError('the move is outside the slider')
            key = self._market_key(cfg)
            hit = Handler._adapters.get(key)
            if not hit or time.time() - hit[0] >= 300:
                hit = Handler._adapters[key] = (time.time(),
                                                pc.public_adapter(cfg))
            body = answer(cfg, hit[1], entries(cfg, hit[1], mark), mark,
                          move / 100.0)
        except Exception as e:                              # noqa: BLE001
            body = (f'<p class="dim">no answer: {_html.escape(str(e))}'
                    '</p>')
        return self._fragment(body)

    def _fragment(self, body):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(tidy(body).encode())

    def _setup_post(self, form):
        from panel.create import public_mark
        from panel.setup import (advanced_page, bot_from_form,
                                 form_from_bot, quick_bot)
        fi = min(int(_f(form.get('fleet')) or 0), len(self.fleets) - 1)
        venue = self._fleet_venue(fi)
        labels = self._fleet_labels()
        how = form.get('how')
        try:
            if how == 'reopen':
                vals = json.loads(form.get('values', '{}'))
                import html as _h
                note = form.get('note', '').strip()
                return self._page(advanced_page(
                    vals.get('strategy', 'grid'), vals, labels, fi,
                    edit=form.get('orig') or None,
                    note=(f'<p class="dim">{_h.escape(note)}</p>' if note
                          else ''),
                    symbols=self._symbols(fi)))
            if how == 'mirror':                                 # U42
                from panel.setup import mirror_leg
                bot = mirror_leg(json.loads(form.get('bot_json', '{}')))
                pair = ''
            elif how == 'quick' and form.get('then') == 'advanced' and not (
                    (form.get('symbol') or '').strip()
                    and (form.get('capital') or '').strip()):
                # U28 (owner 2026-10-04): the advanced door asks for nothing
                # — whatever was typed rides over, the rest stays blank
                preset = form.get('preset', 'sideways')
                strategy = ('martingale' if preset.startswith('dca')
                            else 'grid')
                vals = {k: v for k, v in form.items()
                        if k in ('symbol', 'capital', 'size_unit') and v}
                vals['side'] = 'short' if preset in ('falling', 'dca_short') \
                    else 'long'
                if strategy == 'martingale':
                    vals['strategy'] = 'martingale'
                return self._page(advanced_page(
                    strategy, vals, labels, fi,
                    note='<p class="dim">the advanced form, with what you '
                         'typed carried over — fill in the rest; a blank '
                         'takes the engine\'s default.</p>',
                    symbols=self._symbols(fi)))
            elif how == 'quick':
                symbol = (form.get('symbol') or '').strip().upper()
                mark = public_mark({'venue': venue, 'market_type': 'linear',
                                    'symbol': symbol})
                bot = quick_bot(form, venue, mark)
                pair = ''
                if (form.get('preset') == 'reversal'
                        and (form.get('leg') or 'long') == 'long'):
                    # D54: the short half follows from the written page,
                    # around the SAME mid, with the same three answers
                    pair = json.dumps({
                        'leg': 'short', 'mid': f'{bot["upper"]:.10g}',
                        'preset': 'reversal', 'fleet': str(fi),
                        **{k: form.get(k, '') for k in
                           ('symbol', 'capital', 'size_unit', 'caution',
                            'stop_on', 'max_loss')}})
                if form.get('then') == 'advanced':
                    return self._page(advanced_page(
                        bot.get('strategy', 'grid'), form_from_bot(bot),
                        labels, fi,
                        note='<p class="dim">filled in from the quick '
                             'setup at today\'s price — change anything.'
                             + (' This is the long half of a reversal '
                                'grid; the short half above the mid is '
                                'its own bot, made the same way (D54).'
                                if pair else '') + '</p>'))
            else:
                from panel.setup import resolve_size
                form = resolve_size(form, lambda: public_mark({   # U24
                    'venue': venue, 'market_type': 'linear',
                    'symbol': (form.get('symbol') or '').strip().upper()}))
                bot = bot_from_form(form, venue)
        except Exception as e:                              # noqa: BLE001
            note = refusal_box('not yet', e)
            if how == 'quick':
                from panel.setup import quick_page
                return self._page(note + quick_page(labels, fi))
            return self._page(advanced_page(
                form.get('strategy', 'grid'), form, labels, fi, alert=note,
                edit=form.get('orig') or None))
        orig = form.get('orig', '') if form.get('mode') == 'edit' else ''
        if orig:
            # the form knows every key the engine reads (U1); a row's own
            # notes (keys starting '_') are the operator's and ride along
            from gridgremlin.apply import make_botid as _mb
            old = next((b for b in json.loads(
                Path(self.fleets[fi]).read_text()).get('bots', [])
                if _mb(b['market_type'], b['symbol'], b['side']) == orig),
                {})
            bot.update({k: v for k, v in old.items() if k.startswith('_')})
        return self._create_flow({'fleet': str(fi),
                                  'mode': 'edit' if orig else 'create',
                                  'orig': orig,
                                  'bot_json': json.dumps(bot),
                                  'ceiling': form.get('ceiling', ''),
                                  'pair': pair if how == 'quick' else ''})

    def _tombs_path(self):
        from gridgremlin.tombstones import path_for
        try:
            raw = json.loads(Path(self.fleets[0]).read_text())
        except (OSError, ValueError):
            raw = {}
        return path_for(self.fleets[0], raw)

    def _edit_page(self):
        q = dict(urllib.parse.parse_qsl(self.path.split('?', 1)[1]))
        fi = int(q.get('fleet') or 0)
        botid = q.get('bot', '')
        fleet_raw = json.loads(Path(self.fleets[fi]).read_text())
        from gridgremlin.apply import make_botid as _mb
        bot = next((b for b in fleet_raw.get('bots', [])
                    if _mb(b['market_type'], b['symbol'], b['side'])
                    == botid), None)
        if bot is None:
            return self._deny(404, f'{botid}: not in this fleet')
        if q.get('mode') == 'remove':
            return self._page(
                f'<h1>remove {botid}</h1><p class="dim">the bot and its '
                'watchdog line leave together; the remaining fleet must '
                'still validate (F1). The running fleet is untouched until '
                'restarted (§11).</p>'
                f'<form method="post" action="/create">'
                f'<input type="hidden" name="gg" value="1">'
                f'<input type="hidden" name="mode" value="remove">'
                f'<input type="hidden" name="fleet" value="{fi}">'
                f'<input type="hidden" name="orig" value="{botid}">'
                f'<button>run the gates</button></form>'
                f'<p><a href="/">&larr; fleet</a></p>')
        from panel.setup import advanced_page, form_from_bot
        w = json.loads(Path(fleet_raw['watchdog']).read_text())
        wmax = (w.get('positions', {}).get(botid) or {}).get('max', '')
        vals = dict(form_from_bot(bot), ceiling=wmax)
        return self._page(advanced_page(
            bot.get('strategy', 'grid'), vals, self._fleet_labels(), fi,
            edit=botid))

    def _control_page(self):
        if not self.units and not self.supervise:
            return self._deny(404, 'control is not armed on this panel '
                                   '(--units or --supervise) — §12/§13')
        if self.supervise:
            from panel import supervise as sup
            rows = []
            for f in self.fleets:
                st, pid = sup.status(f)
                cls = 'pos' if st == 'running' else 'neg'
                rows.append(f'<p>engine <b>{Path(f).name}</b>: '
                            f'<span class="{cls}">{st}'
                            + (f' (pid {pid})' if pid else '')
                            + '</span></p>')
            names = ', '.join(Path(f).name for f in self.fleets)
            return self._page(f"""<h1>control <span class="dim">— processes
and files, never the venue (§13, supervised)</span></h1>
{''.join(rows)}
<form method="post" action="/unit">
<input type="hidden" name="gg" value="1">
<select name="action"><option>start</option><option>stop</option>
<option>restart</option></select>
type the fleet file name to confirm ({names}):
<input name="confirm" size="22"><button>do it</button></form>
<p class="dim">the engine is a DETACHED child: closing the panel does
nothing to it. stop PARKS, never flattens (E3). no auto-restart, ever
(§6).</p>
{self._tombs_html()}<p><a href="/">&larr; fleet</a></p>""")
        rows = []
        for u in self.units:
            state = subprocess.run(['systemctl', '--user', 'is-active', u],
                                   capture_output=True, text=True
                                   ).stdout.strip()
            cls = 'pos' if state == 'active' else 'neg'
            waits = ''
            fleet = next((f for f in self.fleets
                          if unit_for_fleet(f, self.units) == u), None)
            if fleet:                                     # U34
                new, gone = waiting_for_restart(fleet)
                parts = ([f'new: {", ".join(new)}'] if new else []) + \
                        ([f'removed: {", ".join(gone)}'] if gone else [])
                if parts:
                    waits = (' <span class="dim">— waiting for a restart: '
                             + '; '.join(parts) + '</span>')
            rows.append(f'<p>unit <b>{u}</b>: <span class="{cls}">{state}'
                        f'</span>{waits}</p>')
        return self._page(f"""<h1>control <span class="dim">— processes and
files, never the venue (§12)</span></h1>
{''.join(rows)}
<form method="post" action="/unit">
<input type="hidden" name="gg" value="1">
<select name="action"><option>restart</option><option>stop</option>
<option>start</option></select>
type a unit name to confirm — or several, separated by spaces or commas:
<input name="confirm" size="44">
<button>do it</button></form>
<p class="dim">one exception to "never the venue": a STOPPED bot's card
offers <b>close position</b>, which asks the engine to close what that bot
left open (X15).</p>
<p class="dim">stop PARKS, never flattens: positions and their
venue-resting orders survive a stopped engine (E3) — but stops go
unevaluated and nothing replenishes until start. restart enacts any
written config (§11).</p>
{self._tombs_html()}<p><a href="/">&larr; fleet</a></p>""")

    def _run_close(self, fi, botid, dry):
        """X15: the engine's own close command, as a subprocess — the keys
        are its, never this process's (the readout's arrangement)."""
        fleet = self.fleets[min(fi, len(self.fleets) - 1)]
        try:
            out = subprocess.run(
                [sys.executable, '-m', 'gridgremlin.close', fleet, botid]
                + (['--dry'] if dry else []),
                capture_output=True, text=True, timeout=60)
            last = (out.stderr.strip().splitlines() or ['no reason given'])[-1]
            return (json.loads(out.stdout) if out.stdout.strip()
                    else {'refused': f'the close command stopped: {last}'})
        except subprocess.TimeoutExpired:
            return {'refused': 'the exchange did not answer within a minute '
                               '— look at it directly before trying again'}
        except ValueError:
            return {'refused': 'the close command answered something '
                               'unreadable — look at the exchange directly'}

    def _close_page(self):
        import html as _html
        if not self.units and not self.supervise:
            return self._deny(404, 'control is not armed on this panel '
                                   '(--units or --supervise) — §12/§13')
        q = dict(urllib.parse.parse_qsl(self.path.split('?', 1)[1]))
        fi, botid = int(_f(q.get('fleet')) or 0), q.get('bot', '')
        got = self._run_close(fi, botid, dry=True)
        b = _html.escape(botid)
        if 'refused' in got:
            return self._page(refusal_box('cannot close', got['refused']))
        if not got['held']:
            return self._page(f'<h1>{b}: nothing to close</h1><p>the '
                              'exchange shows no position on this bot\'s '
                              'side of this market.</p>')
        value = got['held'] * (got['mark'] or 0.0)
        return self._page(
            f'<h1>close what {b} left open</h1>'
            f'<p class="say">The exchange shows a <b>{got["side"]}</b> '
            f'position of <b>{got["held"]:.10g}</b> {_html.escape(got["symbol"])}'
            + (f' from an average of {got["avg_entry"]:,.6g}'
               if got.get('avg_entry') else '')
            + f', worth about {value:,.2f} at {got["mark"]:,.6g}. Closing '
            'sends one market order for exactly that size, which can only '
            'reduce the position. It cannot be undone.</p>'
            '<form method="post" action="/close">'
            '<input type="hidden" name="gg" value="1">'
            f'<input type="hidden" name="fleet" value="{fi}">'
            f'<input type="hidden" name="bot" value="{b}">'
            f'type the bot\'s name to close it: <input name="confirm" '
            f'size="18" placeholder="{b}"> '
            '<button class="danger">close at market</button></form>')

    def _close_act(self, form):
        import html as _html
        if not self.units and not self.supervise:
            return self._deny(404, 'control is not armed on this panel')
        botid = form.get('bot', '')
        if not botid or not named(form.get('confirm'), botid):
            return self._page(refusal_box(
                'not closed', f'the typed name must be exactly {botid} — '
                              'a click is not a decision'))
        got = self._run_close(int(_f(form.get('fleet')) or 0), botid,
                              dry=False)
        if 'refused' in got:
            return self._page(refusal_box('not closed', got['refused']))
        left = got.get('left') or 0.0
        return self._page(
            f'<h1>{_html.escape(botid)}: closed {got["closed"]:.10g}</h1>'
            + (f'<p class="neg">{left:.10g} is STILL OPEN — the market order '
               'did not fill in full; look at the exchange.</p>' if left > 0
               else '<p>the exchange now shows no position on this bot\'s '
                    'side of this market.</p>'))

    def _tombs_html(self):
        tombs = {}
        tp = self._tombs_path()
        if tp.exists():
            tombs = json.loads(tp.read_text() or '{}')
        trows = ''.join(
            f"<tr><td>{html.escape(b)}</td>"
            f"<td class='dim'>{html.escape(str(v.get('reason')))}</td>"
            f"<td><form method='post' action='/revive' style='margin:0'>"
            f"<input type='hidden' name='gg' value='1'>"
            f"<input name='confirm' size='14' placeholder='{html.escape(b, quote=True)}'>"
            f"<button>revive</button></form></td></tr>"
            for b, v in tombs.items()) or \
            '<tr><td class="dim" colspan="3">no tombstones</td></tr>'
        return ('<h1>tombstones <span class="dim">— revival is deliberate, '
                'with the evidence (X7)</span></h1>'
                '<p class="dim">to revive a stopped bot, type its name in '
                'the box on its own row and press revive (capitals do not '
                'matter).</p>'
                '<table><tr><th>bot</th><th>reason</th><th></th></tr>'
                + trows + '</table>'
                '<p class="dim">a revival takes effect at the next fleet '
                'start — the file is the truth; the process reads it at '
                'build.</p>')

    def _control_act(self, form, path):
        if not self.units and not self.supervise:
            return self._deny(404, 'control is not armed on this panel')
        if path == '/unit' and self.supervise:
            from panel import supervise as sup
            byname = {Path(f).name: f for f in self.fleets}
            fleet = byname.get(form.get('confirm', ''))
            if fleet is None:
                return self._page('<h1 class="neg">not done</h1><p>type '
                                  'the fleet file name exactly (§13). '
                                  '<a href="/control">back</a></p>')
            act = form.get('action', '')
            if act not in ('start', 'stop', 'restart'):
                return self._deny(403, 'unknown action')
            notes = []
            if act in ('stop', 'restart'):
                notes.append(sup.stop(fleet))
            if act in ('start', 'restart'):
                notes.append(sup.start(fleet))
            return self._page(f'<h1>{Path(fleet).name}: {act}</h1><p>'
                              + '<br>'.join(notes)
                              + '</p><p><a href="/control">control</a> · '
                                '<a href="/">fleet</a></p>')
        if path == '/unit':
            # U43 (owner 2026-10-05: "can i restart both fleets at the same
            # time from the panel by typing both lines?"): several names,
            # each the decision; ALL must be units or nothing is done
            typed = [u for u in re.split(r'[\s,]+', form.get('confirm', ''))
                     if u]
            tp = self._tombs_path()
            tombs = (json.loads(tp.read_text() or '{}') if tp.exists()
                     else {})
            for u in typed or ['']:
                why = unit_refusal(u, self.units, tombs, self._fleet_bots())
                if why:
                    return self._page(f'<h1 class="neg">not done</h1><p>{why} '
                                      '<a href="/control">back</a></p>')
            act = form.get('action', '')
            if act not in ('start', 'stop', 'restart'):
                return self._deny(403, 'unknown action')
            unit = ' '.join(dict.fromkeys(typed))
            if len(typed) > 1:
                r = subprocess.run(['systemctl', '--user', act]
                                   + list(dict.fromkeys(typed)),
                                   capture_output=True, text=True, timeout=90)
                note = html.escape(r.stderr.strip() or f'{act}: done')
                return self._page(f'<h1>{html.escape(unit)}: {act}</h1>'
                                  f'<p>{note}</p>'
                                  '<p><a href="/control">control</a> · '
                                  '<a href="/">fleet</a></p>')
            unit = typed[0]
            state = subprocess.run(['systemctl', '--user', 'is-active', unit],
                                   capture_output=True, text=True
                                   ).stdout.strip()
            if act == 'start' and state == 'active':
                # U34 (owner 2026-10-04: "start… apparently succeeds. but
                # the fartcoin bot still rests"): start does nothing to a
                # running unit, and "done" was a lie
                return self._page(
                    f'<h1 class="neg">{unit}: not started</h1><p>it is '
                    'already running, and <b>start</b> does nothing to a '
                    'running unit. To load a new or removed bot, or a '
                    'changed range, grid count or ladder, choose '
                    '<b>restart</b> and type the name again. '
                    '<a href="/control">back</a></p>')
            r = subprocess.run(['systemctl', '--user', act, unit],
                               capture_output=True, text=True, timeout=60)
            note = html.escape(r.stderr.strip() or f'{act}: done')
            return self._page(f'<h1>{unit}: {act}</h1><p>{note}</p>'
                              '<p><a href="/control">control</a> · '
                              '<a href="/">fleet</a></p>')
        # /revive — under the engine's own lock (X7, audit 2026-10-05)
        from gridgremlin.tombstones import remove as tomb_remove
        tp = self._tombs_path()
        tombs = json.loads(tp.read_text() or '{}') if tp.exists() else {}
        botid = next((t for t in tombs if named(form.get('confirm'), t)),
                     form.get('confirm', ''))
        gone = tomb_remove(tp, botid) if botid in tombs else None
        if gone is None:
            return self._page('<h1 class="neg">not revived</h1><p>type the '
                              'botid exactly as the tombstone names it. '
                              '<a href="/control">back</a></p>')
        return self._page(f'<h1>{html.escape(botid)}: tombstone removed</h1>'
                          f'<p class="dim">was: {html.escape(str(gone.get("reason")))}</p>'
                          '<p>takes effect at the next fleet start (X7) — '
                          'restart from <a href="/control">control</a> when '
                          'ready.</p>')


from panel.chart import _f  # noqa: E402  (the one float-or-None)


def main(argv):
    if '--hours' in argv:
        i = argv.index('--hours')
        Handler.hours = float(argv[i + 1])
        del argv[i:i + 2]
    if '--units' in argv:
        i = argv.index('--units')
        Handler.units = tuple(argv[i + 1].split(','))
        del argv[i:i + 2]
    port = 0
    if '--port' in argv:
        port = int(argv[argv.index('--port') + 1])
    if '--supervise' in argv:
        Handler.supervise = True
        argv.remove('--supervise')
    if '--token-file' in argv:
        # the persistent-session variant: token survives restarts, stored
        # like a key (0600, refuse looser — the engine's own rule)
        tf = Path(argv[argv.index('--token-file') + 1])
        if tf.exists():
            mode = tf.stat().st_mode & 0o077
            if mode:
                print(f'refusing {tf}: group/other-readable', flush=True)
                return 1
            Handler.token = tf.read_text().strip()
        else:
            Handler.token = secrets.token_urlsafe(16)
            tf.touch(mode=0o600)
            tf.write_text(Handler.token)
    else:
        Handler.token = secrets.token_urlsafe(16)
    Handler.fleets = tuple(a for a in argv if a.endswith('.json'))
    def _label(f):
        stem = Path(f).stem.replace('fleet.', '')
        try:
            bots = json.loads(Path(f).read_text()).get('bots') or []
            venue = bots[0].get('venue', 'bybit') if bots else None
        except (OSError, ValueError):
            venue = None
        if not venue:
            return stem
        # venue first, plus the stem's final token — the environment word
        # (demo, testnet, mine); abbreviations like 'hl' never survive
        return f"{venue} {stem.split('.')[-1]}"
    Handler.labels = tuple(_label(f) for f in Handler.fleets)
    if not Handler.fleets:
        print('usage: python3 -m panel.server <fleet.json>... '
              '[--hours N] [--port P] [--token-file F] [--units a,b]')
        return 2
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', port), Handler)
    Handler.host_ok = f'127.0.0.1:{srv.server_port}'
    print(f'panel: http://{Handler.host_ok}/?t={Handler.token}',
          flush=True)   # journald/pipes: the URL must not sit in a buffer
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
