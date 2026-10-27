"""Control (§12): the control page, starting and stopping units, closing what a stopped bot left open (X15). Moved out of routes.py whole (D91 step 3): a mixin
the Handler inherits."""
from ..forms import unit_for_fleet, unit_refusal, waiting_for_restart
from ..html_bits import named, refusal_box
from gridgremlin.apply import row_botid
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
<div class="fsec">{''.join(rows)}
<form method="post" action="/unit">
<input type="hidden" name="gg" value="1">
<select name="action"><option>start</option><option>stop</option>
<option>restart</option></select>
type the fleet file name to confirm ({names}):
<input name="confirm" size="22"><button>do it</button></form></div>
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
                parts = ([f'new: {html.escape(", ".join(new))}'] if new else []) + \
                        ([f'removed: {html.escape(", ".join(gone))}'] if gone else [])
                if parts:
                    waits = (' <span class="dim">— waiting for a restart: '
                             + '; '.join(parts) + '</span>')
            # the account's name as the cards show it, the unit to type
            # beside it (the owner, 2026-10-22: "make the accounts match
            # their names in the UI")
            label = (self.labels[self.fleets.index(fleet)]
                     if fleet in self.fleets and len(self.labels) == len(self.fleets) else None)
            name = (f'<b>{html.escape(str(label))}</b> <span class="dim">unit '
                    f'{html.escape(u)}</span>' if label else f'unit <b>{html.escape(u)}</b>')
            rows.append(f'<p>{name}: <span class="{cls}">{state}'
                        f'</span>{waits}</p>')
        return self._page(f"""<h1>control <span class="dim">— processes and
files, never the venue (§12)</span></h1>
<div class="fsec">{''.join(rows)}
<form method="post" action="/unit">
<input type="hidden" name="gg" value="1">
<select name="action"><option>restart</option><option>stop</option>
<option>start</option></select>
type a unit name to confirm — or several, separated by spaces or commas:
<input name="confirm" size="44">
<button>do it</button></form></div>
<p class="dim">one exception to "never the venue": a STOPPED bot's card
offers <b>close position</b>, which asks the engine to close what that bot
left open (X15).</p>
{self._retire_all_form()}
<p class="dim">stop PARKS, never flattens: positions and their
venue-resting orders survive a stopped engine (E3) — but stops go
unevaluated and nothing replenishes until start. restart enacts any
written config (§11).</p>
{self._tombs_html()}<p><a href="/">&larr; fleet</a></p>""")

    def _retire_all_form(self):
        """D149: retire a whole stopped fleet, and clear it to nothing — a
        dry run first; the act on its own page, with the fleet file's name
        typed."""
        labels = self.labels if len(self.labels) == len(self.fleets) else [None] * len(self.fleets)
        opts = ''.join(f'<option value="{i}">{html.escape(str(lb) + " — " if lb else "")}'
                       f'{html.escape(Path(f).name)}</option>'
                       for i, (f, lb) in enumerate(zip(self.fleets, labels)))
        return (f'<h2>retire all <span class="dim">— a whole fleet, stopped first (D149)</span></h2>'
                f'<form method="post" action="/retire-all"><input type="hidden" name="gg" value="1">'
                f'<select name="fleet">{opts}</select> '
                '<label><input type="checkbox" name="sell" value="1"> and sell every coin for USDT</label> '
                '<label><input type="checkbox" name="clear" value="1"> and clear the fleet to nothing</label> '
                '<button>dry run</button></form>'
                '<p class="dim">every bot retired as one is: its orders cancelled, its position '
                'closed, a portfolio row flattened leg by leg; then the exchange read back. '
                '"clear" takes every bot, its watchdog line and its tombstone out of the file, '
                'so its cards leave the page; an empty fleet will not start until a bot is '
                'added. The dry run sends nothing.</p>')

    def _run_retire_all(self, fi, dry, sell, clear):
        """D149: the engine's own retire_all, as a subprocess with the
        fleet's own keys (the close command's arrangement)."""
        fleet = self.fleets[min(fi, len(self.fleets) - 1)]
        try:
            from gridgremlin.retire_all import command
            from gridgremlin.durable import fleet_env, fleet_home
            out = subprocess.run(command(Path(fleet).resolve(), dry=dry, sell=sell, clear=clear),
                                 capture_output=True, text=True, timeout=600,
                                 cwd=str(fleet_home(fleet)), env=fleet_env(fleet))
            last = (out.stderr.strip().splitlines() or ['no reason given'])[-1]
            return (json.loads(out.stdout.strip().splitlines()[-1]) if out.stdout.strip()
                    else {'refused': f'retire all stopped: {last}'})
        except subprocess.TimeoutExpired:
            return {'refused': 'the exchange did not answer within ten minutes '
                               '— look at it directly before trying again'}
        except ValueError:
            return {'refused': 'retire all answered something unreadable '
                               '— look at the exchange directly'}

    def _retire_all_act(self, form):
        if not self.units and not self.supervise:
            return self._deny(404, 'control is not armed on this panel')
        fi = int(_f(form.get('fleet')) or 0)
        name = Path(self.fleets[min(fi, len(self.fleets) - 1)]).name
        sell, clear = form.get('sell') == '1', form.get('clear') == '1'
        go = form.get('go') == '1'
        if go and form.get('confirm', '').strip() != name:
            return self._page(refusal_box('not done', f'type the fleet file name exactly: {name} '
                                          '— a click is not a decision (§11)'))
        got = self._run_retire_all(fi, dry=not go, sell=sell, clear=clear)
        if 'refused' in got:
            return self._page(refusal_box('not done', got['refused']))
        lines = []
        for r in got.get('rows') or []:
            what = ('would retire' if not go else 'retired') + f" ({r.get('kind')})"
            bits = [f"{k} {r[k]}" for k in ('orders', 'cancelled', 'held', 'closed', 'held_left')
                    if r.get(k) not in (None, 0, 0.0, [])]
            lines.append(f'<li><b>{html.escape(str(r.get("botid")))}</b>: {what}'
                         + (f' — {html.escape(", ".join(bits))}' if bits else '') + '</li>')
        for r in got.get('sold') or []:
            lines.append('<li>' + html.escape(', '.join(f'{k} {v}' for k, v in r.items())) + '</li>')
        if got.get('cleared'):
            lines.append(f"<li>{'would clear' if not go else 'cleared'}: "
                         f"{html.escape(', '.join(got['cleared']))}</li>")
        head = (f'<h1>{html.escape(name)}: '
                + ('dry run</h1>' if not go else
                   ('flat on the exchange</h1>' if got.get('flat') else
                    '<span class="neg">NOT all flat</span></h1>')))
        left = ('' if not got.get('left') else
                '<p class="neg">still open: ' + html.escape(json.dumps(got['left'])) + '</p>')
        for key in ('not_cleared', 'not_retired'):                # D149: a clear waits for flat
            if got.get(key):
                left += (f'<p class="neg">{key.replace("_", " ")}: '
                         + html.escape(got[key] if isinstance(got[key], str) else '; '.join(got[key]))
                         + '</p>')
        again = ('' if go else
                 f'<form method="post" action="/retire-all"><input type="hidden" name="gg" value="1">'
                 f'<input type="hidden" name="fleet" value="{fi}"><input type="hidden" name="go" value="1">'
                 + ('<input type="hidden" name="sell" value="1">' if sell else '')
                 + ('<input type="hidden" name="clear" value="1">' if clear else '')
                 + f'type <b>{html.escape(name)}</b> to do it: <input name="confirm" size="24"> '
                   '<button>retire all</button></form>')
        return self._page(head + f'<ul>{"".join(lines) or "<li>nothing in this fleet</li>"}</ul>'
                          + left + again + '<p><a href="/control">control</a> · <a href="/">fleet</a></p>')

    def _run_close(self, fi, botid, dry, expect=None):
        """X15: the engine's own close command, as a subprocess — the keys
        are its, never this process's (the readout's arrangement). On a
        fleet that may reach real money the engine's own argv carries D25's
        run half (D97; the panel never names it, D65)."""
        fleet = self.fleets[min(fi, len(self.fleets) - 1)]
        try:
            from gridgremlin.close import command
            from gridgremlin.durable import fleet_env, fleet_home
            out = subprocess.run(                          # U80: from the fleet's own copy
                command(Path(fleet).resolve(), botid, dry=dry, expect=expect,
                        real_money=self._mainnet(fleet, 'bybit')),
                capture_output=True, text=True, timeout=60, cwd=str(fleet_home(fleet)),
                env=fleet_env(fleet))                      # and its own keys
            last = (out.stderr.strip().splitlines() or ['no reason given'])[-1]
            return (json.loads(out.stdout) if out.stdout.strip()
                    else {'refused': f'the close command stopped: {last}'})
        except subprocess.TimeoutExpired:
            return {'refused': 'the exchange did not answer within a minute '
                               '— look at it directly before trying again'}
        except ValueError:
            return {'refused': 'the close command answered something '
                               'unreadable — look at the exchange directly'}

    def _closable(self, fi, botid):
        """P6: is `botid` a bot of fleet `fi` — a row of its file or one of
        its trades — so the close command's argv only ever carries a name the
        engine knows, never a word starting '--'."""
        from gridgremlin.trades import TradeError, _botid, load_trades, trades_path
        f = self.fleets[min(fi, len(self.fleets) - 1)]
        try:
            raw = json.loads(Path(f).read_text())
            names = {row_botid(b) for b in raw.get('bots') or []
                     if isinstance(b, dict) and (b.get('symbol') or b.get('name'))}
            names |= {_botid(t) for t in load_trades(trades_path(f, raw))[0]}
        except (TradeError, OSError, ValueError, KeyError, TypeError, AttributeError):
            return False
        return botid in names

    def _snapshot_held(self, fi, botid):
        """X15d for a trade (L7): the size a bot or running trade holds, as
        the engine's last snapshot states it — what the close page shows and
        the second typing must match, and what a removal warns of (U97).
        None when the snapshot does not say or it holds nothing."""
        from gridgremlin.equity_series import snapshot_path
        snap = snapshot_path(self.fleets[min(fi, len(self.fleets) - 1)])
        try:
            last = Path(snap).read_text().strip().splitlines()[-1]
            pos = ((json.loads(last).get('bots') or {}).get(botid) or {}).get('position')
        except (TypeError, OSError, ValueError, IndexError, AttributeError):
            return None
        return abs(pos) if isinstance(pos, (int, float)) and abs(pos) > 1e-12 else None

    def _still_held(self, fi, botid):
        """U97: removing a row closes nothing (the audit, 2026-10-16) — the
        remove pages say what the bot still holds, when it holds anything."""
        held = self._snapshot_held(fi, botid)
        if not held:
            return ''
        return ('<div class="refusal"><b>it still holds a position</b> — '
                f'{held:.10g}, as the engine\'s last snapshot says. Removing the '
                'row does not close it: after the restart no bot manages it, and it '
                'stays open on the exchange. To close it first, stop the fleet and '
                'use <b>close position</b> on its card.</div>')

    def _close_page(self):
        import html as _html
        if not self.units and not self.supervise:
            return self._deny(404, 'control is not armed on this panel '
                                   '(--units or --supervise) — §12/§13')
        q = dict(urllib.parse.parse_qsl(self.path.split('?', 1)[1]))
        fi, botid = int(_f(q.get('fleet')) or 0), q.get('bot', '')
        b = _html.escape(botid)
        if not self._closable(fi, botid):
            return self._page(refusal_box('cannot close', f'{botid or "nothing"}: not a bot '
                                          'of this account'))
        if self._live_trade(fi, botid):
            # L7: a running trade is closed by its own bot, never from
            # outside — the panel writes the request, the fleet acts on it
            real = self._mainnet(self.fleets[min(fi, len(self.fleets) - 1)], 'bybit')
            held = self._snapshot_held(fi, botid) if real else None
            if real and held is None:
                return self._page(refusal_box('cannot close', f'{botid}: on real money the '
                                              'size is typed a second time, and the engine has '
                                              'not reported what this trade holds yet — try '
                                              'after its next snapshot'))
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
                + (f'<br><span class="neg">real money</span> — it holds <b>{held:.10g}</b> '
                   '(the engine\'s last snapshot); type the size a second time: '
                   '<input name="size" size="14" placeholder="the size above"> '
                   if real else '')                                    # X15d
                + '<button class="danger">close at market</button></form>')
        real = self._mainnet(self.fleets[min(fi, len(self.fleets) - 1)], 'bybit')
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
            + ('<br><span class="neg">real money</span> — type the size a second time: '
               '<input name="size" size="14" placeholder="the size above"> '
               if real else '')
            + '<button class="danger">close at market</button></form>')

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
        if not self._closable(fi, botid):
            return self._page(refusal_box('not closed', f'{botid}: not a bot of this account'))
        path = self._live_trade(fi, botid)
        if path:                                                    # L7
            from gridgremlin.trades import TradeError, request_close
            if self._mainnet(self.fleets[min(fi, len(self.fleets) - 1)], 'bybit'):
                held, typed = self._snapshot_held(fi, botid), _f(str(form.get('size', '')).replace(',', ''))
                if held is None or typed is None or abs(typed - held) > 1e-9 * max(1.0, held):
                    return self._page(refusal_box(                  # X15d: name and size
                        'not closed', 'on real money the size is typed a second time, '
                                      'exactly as the page shows it'))
            try:
                req = request_close(path, botid, 'owner', 'close trade on the panel')
            except (TradeError, OSError) as e:
                return self._page(refusal_box('not closed', e))
            type(self)._cache.pop(self.fleets[min(fi, len(self.fleets) - 1)], None)
            return self._page(
                f'<h1>{_html.escape(botid)}: close requested</h1>'
                f'<p class="say">Requested by {_html.escape(req["by"])} at '
                f'{_html.escape(req["t"])}. The fleet closes it at market within a '
                'cycle and the trade stands down; its card then offers <b>clear</b>.</p>'
                '<p><a href="/">back to your bots</a></p>')
        expect = None
        if self._mainnet(self.fleets[min(fi, len(self.fleets) - 1)], 'bybit'):
            expect = _f(form.get('size'))                 # D97: the second typing, real money
            if not expect:
                return self._page(refusal_box(
                    'not closed', 'on real money the size is typed a second time, '
                                  'exactly as the page shows it'))
        got = self._run_close(fi, botid, dry=False, expect=expect)
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
            return self._page(f'<h1>{html.escape(Path(fleet).name)}: {html.escape(act)}</h1><p>'
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
                return self._page(f'<h1>{html.escape(unit)}: {html.escape(act)}</h1>'
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
                    f'<h1 class="neg">{html.escape(unit)}: not started</h1><p>it is '
                    'already running, and <b>start</b> does nothing to a '
                    'running unit. To load a new or removed bot, or a '
                    'changed range, grid count or ladder, choose '
                    '<b>restart</b> and type the name again. '
                    '<a href="/control">back</a></p>')
            r = subprocess.run(['systemctl', '--user', act, unit],
                               capture_output=True, text=True, timeout=60)
            note = html.escape(r.stderr.strip() or f'{act}: done')
            return self._page(f'<h1>{html.escape(unit)}: {html.escape(act)}</h1><p>{note}</p>'
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
