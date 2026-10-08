"""The panel's form pages: rehearsal, set-up buttons, verdicts, the way back."""
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
from panel.chart import _f

from .render import money, named, refusal_box, setup_button, sweep_html, windows_html

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
