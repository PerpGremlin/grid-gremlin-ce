"""Control (§12): the control page, starting and stopping units, closing what a stopped bot left open (X15). Moved out of routes.py whole (D91 step 3): a mixin
the Handler inherits."""
from ..forms import unit_for_fleet, unit_refusal, waiting_for_restart
from ..html_bits import named, refusal_box
from panel.chart import _f
from pathlib import Path
import html
import json
import re
import subprocess
import sys
import urllib.parse


class ControlPages:
    def _control_page(self):
        if not self.units and not self.supervise:
            # the side panel links here on every page: say what control is
            # and that it is off, never a bare 404 (the bug hunt, 2026-10-11)
            return self._page('<h1>control</h1><p>Starting and stopping the fleets from here is off on this '
                              'panel. It is armed by starting the panel with <code>--units</code> (the units it '
                              'may restart) or <code>--supervise</code> (on a laptop) — §12, §13.</p>'
                              '<p><a href="/">&larr; fleet</a></p>')
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
        b = _html.escape(botid)
        if self._live_trade(fi, botid):
            # L7: a running trade is closed by its own bot, never from
            # outside — the panel writes the request, the fleet acts on it
            return self._page(
                f'<h1>close trade {b}</h1>'
                '<p class="say">The fleet closes this trade at market within a '
                'cycle: one reduce-only market order for what it holds, sent by '
                'the trade itself, which then stands down. It cannot be undone.</p>'
                '<form method="post" action="/close">'
                '<input type="hidden" name="gg" value="1">'
                f'<input type="hidden" name="fleet" value="{fi}">'
                f'<input type="hidden" name="bot" value="{b}">'
                f'type the trade\'s name to close it: <input name="confirm" '
                f'size="18" placeholder="{b}"> '
                '<button class="danger">close at market</button></form>')
        got = self._run_close(fi, botid, dry=True)
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
        fi = int(_f(form.get('fleet')) or 0)
        path = self._live_trade(fi, botid)
        if path:                                                    # L7
            from gridgremlin.trades import TradeError, request_close
            try:
                req = request_close(path, botid, 'owner', 'close trade on the panel')
            except (TradeError, OSError) as e:
                return self._page(refusal_box('not closed', _html.escape(str(e))))
            type(self)._cache.pop(self.fleets[min(fi, len(self.fleets) - 1)], None)
            return self._page(
                f'<h1>{_html.escape(botid)}: close requested</h1>'
                f'<p class="say">Requested by {_html.escape(req["by"])} at '
                f'{_html.escape(req["t"])}. The fleet closes it at market within a '
                'cycle and the trade stands down; its card then offers <b>clear</b>.</p>'
                '<p><a href="/">back to your bots</a></p>')
        got = self._run_close(fi, botid, dry=False)
        if 'refused' in got:
            return self._page(refusal_box('not closed', got['refused']))
        left = got.get('left') or 0.0
        return self._page(
            f'<h1>{_html.escape(botid)}: closed {got["closed"]:.10g}</h1>'
            + (f'<p class="neg">{left:.10g} is STILL OPEN — the market order '
               'did not fill in full; look at the exchange.</p>' if left > 0
               else '<p>the exchange now shows no position on this bot\'s '
                    'side of this market.</p>'))

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
            tombs = {}
            for _fi, _lb, _tp, rows in self._tombs_all():
                tombs.update(rows)
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
        tp = self._tombs_path(int(_f(form.get('fleet')) or 0))
        try:
            tombs = json.loads(tp.read_text() or '{}') if tp.exists() else {}
        except (OSError, ValueError):
            tombs = {}
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
