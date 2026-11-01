"""Control (§12): the control page, starting and stopping units, closing what a stopped bot left open (X15). Moved out of routes.py whole (D91 step 3): a mixin
the Handler inherits."""
from ..forms import unit_for_fleet, unit_refusal, waiting_for_restart
from ..html_bits import (_squash, accepts, confirm_dialog, confirmed, esc, plain_name, refusal_box,
                         to_type, typed_inline)
from gridgremlin.apply import row_botid
from panel.chart import _f
from pathlib import Path
import html
import json
import subprocess
import sys
import urllib.parse


class ControlPages:
    def _control_page(self):
        if not self.units and not self.supervise:
            # the side panel links here on every page: say what control is
            # and that it is off, never a bare 404 (the bug hunt, 2026-10-11)
            return self._page('<h1>control</h1><p>Starting and stopping your bots from here is off on this '
                              'panel: a bot starts when its account\'s engine is started or restarted on the '
                              'computer that runs it. <span class="dim">Control is armed by starting the panel '
                              'with <code>--units</code> (the engines it may restart) or '
                              '<code>--supervise</code> (on a laptop).</span></p>'
                              '<p><a href="/">&larr; your bots</a></p>')
        if self.supervise:
            from panel import supervise as sup
            rows = []
            for fi, f in enumerate(self.fleets):
                st, pid = sup.status(f)
                cls = 'pos' if st == 'running' else 'neg'
                rows.append(f'<p><b>{html.escape(self._account(fi))}</b>: '
                            f'<span class="{cls}">{st}'
                            + (f' (pid {pid})' if pid else '')
                            + f'</span> <span class="dim">file {html.escape(Path(f).name)}</span></p>')
            names = ', '.join(self._account(fi) for fi in range(len(self.fleets)))
            return self._page(f"""<h1>control <span class="dim">— start and stop each
account's bots, on this computer; never the exchange</span></h1>
<div class="fsec">{''.join(rows)}
<form method="post" action="/unit">
<input type="hidden" name="gg" value="1">
<select name="action"><option value="start">start</option><option value="stop">stop —
its bots park, positions stay open</option>
<option value="restart">restart — loads new and removed bots</option></select>
{typed_inline(f"type the account's name to confirm ({html.escape(names)}) — its file name works too: "
              '<input name="confirm" size="22" autocomplete="off">')}{self._unit_dialog(names, supervise=True)}<button>do it</button></form></div>
<p class="dim">the engine runs on its own: closing the panel does
nothing to it. Stop parks the bots and never closes a position. Nothing
restarts by itself.</p>
{self._tombs_html()}<p><a href="/">&larr; your bots</a></p>""")
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
            word = 'running' if state == 'active' else 'stopped'
            rows.append(f'<p>{name}: <span class="{cls}" title="{html.escape(state, quote=True)}">'
                        f'{word}</span>{waits}</p>')
        names = ', '.join(self._account(fi) for fi in range(len(self.fleets)))
        return self._page(f"""<h1>control <span class="dim">— start and stop each
account's bots, on this computer; never the exchange</span></h1>
<div class="fsec">{''.join(rows)}
<form method="post" action="/unit">
<input type="hidden" name="gg" value="1">
<select name="action"><option value="restart">restart — loads new and removed bots</option>
<option value="stop">stop — its bots park, positions stay open</option>
<option value="start">start</option></select>
{typed_inline(f"type the account's name to confirm ({html.escape(names)}) — or its unit name; several go "
              "separated by commas. An account that may reach Mainnet takes its unit name only: "
              '<input name="confirm" size="44" autocomplete="off">')}{self._unit_dialog(names)}
<button>do it</button></form></div>
<p class="dim">one exception to "never the exchange": a bot's card offers
<b>stop</b>, which asks the running bot to close its position or leave it
open; a stopped bot's card offers <b>close position</b>.</p>
{self._retire_all_form()}
<p class="dim">stopping an account parks its bots and never closes a
position: positions and the orders resting on the exchange stay, but
stops go unwatched and nothing is replaced until it starts again. A
restart loads every written change.</p>
{self._tombs_html()}<p><a href="/">&larr; your bots</a></p>""")

    def _account(self, fi):
        """D157: an account's name as the cards say it; its file's name
        without labels."""
        if len(self.labels) == len(self.fleets) and self.labels[fi]:
            return str(self.labels[fi])
        return Path(self.fleets[fi]).name

    def _unit_dialog(self, names, supervise=False):
        """D159: control's pop-up — what it takes is what _control_act
        takes: an account's name where _account_typed reads one, else its
        unit name (several, separated by commas, U43), or on a laptop its
        file name."""
        named = [self._account(fi) for fi in range(len(self.fleets))
                 if self._account_typed(self._account(fi)) == fi]
        other = [Path(f).name for f in self.fleets] if supervise else list(self.units)
        return confirm_dialog(
            "Start, stop or restart the account's engine, as chosen above.",
            f'the account\'s name <span class="dim">({esc(names)}) — or its '
            + ('file name' if supervise else 'unit name; several go separated by commas')
            + '</span>', list(dict.fromkeys(_squash(n) for n in named + other)), 'do it',
            multi=not supervise)

    def _real(self, fleet):
        """D157: may this fleet reach Mainnet, by either venue's reading —
        where a shortcut is never taken."""
        return any(self._mainnet(fleet, v) for v in ('bybit', 'hyperliquid'))

    def _account_typed(self, typed):
        """D157: the fleet index an account's name names — only one account
        of that name, and never one that may reach Mainnet, which keeps its
        file or unit name typed. None otherwise."""
        want = ' '.join(str(typed or '').lower().split())
        hits = [fi for fi in range(len(self.fleets))
                if want and ' '.join(self._account(fi).lower().split()) == want]
        if len(hits) != 1 or self._real(self.fleets[hits[0]]):
            return None
        return hits[0]

    def _account_words(self, fi):
        """D159: what to type to act on one account's file (retire all, the
        leftover tombstones): its name, or its file name where the name is
        not taken (Mainnet, or two of a name)."""
        fi = min(fi, len(self.fleets) - 1)
        name = Path(self.fleets[fi]).name
        if self._account_typed(self._account(fi)) == fi:
            return (f'<b>{html.escape(self._account(fi))}</b> '
                    f'<span class="dim">(or {html.escape(name)})</span>')
        return f'<b>{html.escape(name)}</b>'

    def _account_accepts(self, fi):
        """D159: the spellings those pages take, for the pop-up: the file
        name, and the account's name where _account_typed reads it."""
        fi = min(fi, len(self.fleets) - 1)
        out = [_squash(Path(self.fleets[fi]).name)]
        if self._account_typed(self._account(fi)) == fi:
            out.append(_squash(self._account(fi)))
        return out

    def _units_typed(self, typed):
        """D157: the unit names a typed confirmation means — a part between
        commas that is an account's name stands for its unit, the rest is
        split on spaces as before (U43)."""
        out = []
        for part in str(typed or '').split(','):
            fi = self._account_typed(part)
            unit = unit_for_fleet(self.fleets[fi], self.units) if fi is not None else None
            out += [unit] if unit else [u for u in part.split() if u]
        return out

    def _retire_all_form(self):
        """D149: retire a whole stopped fleet, and clear it to nothing — a
        dry run first; the act on its own page, with the fleet file's name
        typed."""
        labels = self.labels if len(self.labels) == len(self.fleets) else [None] * len(self.fleets)
        opts = ''.join(f'<option value="{i}">{html.escape(str(lb) + " — " if lb else "")}'
                       f'{html.escape(Path(f).name)}</option>'
                       for i, (f, lb) in enumerate(zip(self.fleets, labels)))
        return (f'<h2>retire all <span class="dim">— every bot of one account, stopped first</span></h2>'
                f'<form method="post" action="/retire-all"><input type="hidden" name="gg" value="1">'
                f'<select name="fleet">{opts}</select> '
                '<label><input type="checkbox" name="sell" value="1"> and sell every coin for USDT</label> '
                '<label><input type="checkbox" name="clear" value="1"> and take every bot off the account</label> '
                '<button>dry run</button></form>'
                '<p class="dim">every bot retired as one is: its orders cancelled, its position '
                'closed, a portfolio row flattened leg by leg; then the exchange read back. '
                'Taking every bot off removes each bot, its watchdog line and its tombstone from '
                'the account\'s file, so its cards leave the page; an account with no bots will '
                'not start until a bot is added. The dry run sends nothing.</p>')

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
        # D157: the account's name as the cards say it does too, off Mainnet
        if go and form.get('confirm', '').strip() != name and self._account_typed(
                form.get('confirm')) != min(fi, len(self.fleets) - 1):
            return self._page(refusal_box('not done', f'type the account\'s name or its file name '
                                          f'exactly: {name} — a click is not a decision'))
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
        words = self._account_words(fi)
        again = ('' if go else
                 f'<form method="post" action="/retire-all"><input type="hidden" name="gg" value="1">'
                 f'<input type="hidden" name="fleet" value="{fi}"><input type="hidden" name="go" value="1">'
                 + ('<input type="hidden" name="sell" value="1">' if sell else '')
                 + ('<input type="hidden" name="clear" value="1">' if clear else '')
                 + typed_inline('type ' + words + ' to do it: <input name="confirm" size="24" autocomplete="off"> ')
                 + confirm_dialog(                               # D159: the pop-up
                     f'Retire every bot of {self._account(min(fi, len(self.fleets) - 1))}'
                     + (', sell its coins' if sell else '') + (', and clear it to no bots' if clear else '')
                     + '.', words, self._account_accepts(fi), 'retire all', danger=True)
                 + '<button>retire all</button></form>')
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

    def _row_of(self, fi, botid):
        """D157: the row a bot's plain name is read from — its fleet row,
        or its trade (validated, so it says it is one); None when neither
        holds it, and then only its code is taken."""
        from gridgremlin.trades import TradeError, _botid, load_trades, trades_path
        f = self.fleets[min(fi, len(self.fleets) - 1)]
        try:
            raw = json.loads(Path(f).read_text())
            row = next((b for b in raw.get('bots') or []
                        if isinstance(b, dict) and (b.get('symbol') or b.get('name'))
                        and row_botid(b) == botid), None)
            if row is None:
                row = next((t for t in load_trades(trades_path(f, raw))[0] if _botid(t) == botid), None)
        except (TradeError, OSError, ValueError, KeyError, TypeError, AttributeError):
            return None
        return row

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
                                   '(--units or --supervise)')
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
            row = self._row_of(fi, botid)
            said = (None if real else plain_name(row)) or botid
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
                + typed_inline(
                    f'type {to_type(botid, row, real)} to close it: <input name="confirm" '
                    'size="18" autocomplete="off"> '
                    + (f'<br><span class="neg">real money</span> — it holds <b>{held:.10g}</b> '
                       '(the engine\'s last snapshot); type the size a second time: '
                       '<input name="size" size="14" placeholder="the size above"> '
                       if real else ''))                                # X15d
                + confirm_dialog(                                       # D159: the pop-up
                    f'Close the trade {said} at market on {self._account(min(fi, len(self.fleets) - 1))}.',
                    to_type(botid, row, real), accepts(botid, row, real), 'close at market',
                    [('size', f'<b>real money</b>: type the size it holds (<code>{held:.10g}</code>) '
                      'a second time', held)] if real else [], danger=True)
                + '<button class="danger">close at market</button></form>')
        real = self._mainnet(self.fleets[min(fi, len(self.fleets) - 1)], 'bybit')
        row = self._row_of(fi, botid)
        said = (None if real else plain_name(row)) or botid
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
            + typed_inline(
                f'type {to_type(botid, row, real)} to close it: <input name="confirm" '
                'size="18" autocomplete="off"> '
                + ('<br><span class="neg">real money</span> — type the size a second time: '
                   '<input name="size" size="14" placeholder="the size above"> '
                   if real else ''))
            + confirm_dialog(                                           # D159: the pop-up
                f'Close the {got["side"]} position of {got["held"]:.10g} {got["symbol"]} that '
                f'{said} left open, at market, on {self._account(min(fi, len(self.fleets) - 1))}.',
                to_type(botid, row, real), accepts(botid, row, real), 'close at market',
                [('size', f'<b>real money</b>: type the size (<code>{got["held"]:.10g}</code>) '
                  'a second time', got['held'])] if real else [], danger=True)
            + '<button class="danger">close at market</button></form>')

    def _close_act(self, form):
        import html as _html
        if not self.units and not self.supervise:
            return self._deny(404, 'control is not armed on this panel')
        botid = form.get('bot', '')
        fi = int(_f(form.get('fleet')) or 0)
        real = self._mainnet(self.fleets[min(fi, len(self.fleets) - 1)], 'bybit')
        row = self._row_of(fi, botid)
        if not botid or not confirmed(form.get('confirm'), botid, row, mainnet=real):
            said = None if real else plain_name(row)
            return self._page(refusal_box(
                'not closed', f'the typed name must be exactly '
                              + (f'{said} or {botid}' if said else botid)
                              + ' — a click is not a decision'))
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
            fi = self._account_typed(form.get('confirm'))              # D157
            if fleet is None and fi is not None:
                fleet = self.fleets[fi]
            if fleet is None:
                return self._page('<h1 class="neg">not done</h1><p>type '
                                  'the account\'s name or its file name exactly. '
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
            # D157: an account's name stands for its unit, off Mainnet
            typed = self._units_typed(form.get('confirm', ''))
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
        rfi = int(_f(form.get('fleet')) or 0)
        real = self._real(self.fleets[min(rfi, len(self.fleets) - 1)])
        botid = next((t for t in tombs if confirmed(form.get('confirm'), t,   # D157
                                                    self._row_of(rfi, t), mainnet=real)),
                     form.get('confirm', ''))
        gone = tomb_remove(tp, botid) if botid in tombs else None
        if gone is None:
            return self._page('<h1 class="neg">not revived</h1><p>type the '
                              'bot\'s name or its code exactly as its row shows it. '
                              '<a href="/control">back</a></p>')
        return self._page(f'<h1>{html.escape(botid)}: tombstone removed</h1>'
                          f'<p class="dim">was: {html.escape(str(gone.get("reason")))}</p>'
                          '<p>takes effect when its account\'s engine next starts — '
                          'restart it from <a href="/control">control</a> when '
                          'ready.</p>')

    # --- D157: "start it now" ---------------------------------------------------

    def _engine(self, fi):
        """D157: what runs an account's bots on this panel, and whether it is
        running: ('unit', name, running) under systemd, ('file', fleet,
        running) under the laptop supervisor, None when nothing here does.
        The engine is one process per account: it starts and restarts whole."""
        f = self.fleets[min(fi, len(self.fleets) - 1)]
        if self.supervise:
            from panel import supervise as sup
            return 'file', f, sup.status(f)[0] == 'running'
        unit = unit_for_fleet(f, self.units) if self.units else None
        if not unit or unit not in self.units:
            return None
        state = subprocess.run(['systemctl', '--user', 'is-active', unit],
                               capture_output=True, text=True).stdout.strip()
        return 'unit', unit, state == 'active'

    def _start_html(self, fi, botid):
        """D157 (the owner's answer: a button, and nothing starts without
        the click): the written page's "start it now" — the same engine
        start control makes, its unit known, so nothing is typed. It says
        plainly that the account's other bots restart with it. Not on an
        account that may reach Mainnet (its unit name stays typed on
        control), and not when control is off: '' and the page says how."""
        if not self.units and not self.supervise:
            return ''
        f = self.fleets[min(fi, len(self.fleets) - 1)]
        if self._real(f):
            return ('<p><b class="neg">Mainnet:</b> no one-click start. On '
                    '<a href="/control">control</a>, choose <b>restart</b> and type the '
                    'engine\'s unit name; the engine\'s own real-money gate still applies.</p>')
        eng = self._engine(fi)
        if eng is None:
            return ''
        kind, name, running = eng
        acct = html.escape(self._account(min(fi, len(self.fleets) - 1)))
        n = len(self._fleet_rows(fi) - {botid})
        others = f'{n} other bot' + ('' if n == 1 else 's')
        if running and n:
            what = (f'Starting it <b>restarts the engine that runs {acct}</b>, so its {others} '
                    + ('restarts' if n == 1 else 'restart') + ' with it: each is parked for a few '
                    'seconds, and positions and the orders resting on the exchange stay.')
        elif running:
            what = f'Starting it restarts the engine that runs {acct}; no other bot runs there.'
        else:
            what = (f'The engine that runs {acct} is stopped: starting it <b>starts every bot '
                    f'in it</b> — this one' + (f' and its {others}.' if n else '.'))
        detail = f'unit {name}' if kind == 'unit' else f'file {Path(name).name}'
        return ('<div class="fsec go"><form method="post" action="/start">'
                '<input type="hidden" name="gg" value="1">'
                f'<input type="hidden" name="fleet" value="{min(fi, len(self.fleets) - 1)}">'
                f'<input type="hidden" name="bot" value="{html.escape(botid, quote=True)}">'
                '<button>start it now</button></form>'
                f'<p class="say">{what} The new bot is checked as it starts: one the exchange '
                'refuses is set aside (its card says stopped) and the rest run. '
                f'<span class="dim">({html.escape(detail)})</span></p></div>')

    def _start_act(self, form):
        """D157: the button's post. Only a bot in this account's file, never
        on an account that may reach Mainnet, through the engine control
        would start or restart — the engine's own checks at its start are
        all still ahead of it."""
        if not self.units and not self.supervise:
            return self._deny(404, 'control is not armed on this panel')
        fi = min(int(_f(form.get('fleet')) or 0), len(self.fleets) - 1)
        f, botid = self.fleets[fi], form.get('bot', '')
        if not botid or botid not in self._fleet_rows(fi):
            return self._page(refusal_box('not started', f'{botid or "nothing"}: not a bot of this account'))
        if self._real(f):
            return self._page(refusal_box(
                'not started', 'this account may reach Mainnet: its engine is restarted on '
                               'control, with its unit name typed — never one click'))
        eng = self._engine(fi)
        if eng is None:
            return self._page(refusal_box(
                'not started', 'no engine this panel controls runs this account — start or '
                               'restart it on the computer that runs it'))
        kind, name, running = eng
        said = html.escape(plain_name(self._row_of(fi, botid)) or botid)
        back = '<p><a href="/">back to your bots</a> · <a href="/control">control</a></p>'
        if running and self._retire_state(fi, botid)[2] is not None:
            return self._page(f'<h1>{said}: already running</h1><p>its account\'s engine has '
                              'loaded it; nothing was restarted.</p>' + back)
        act = 'restart' if running else 'start'
        if kind == 'unit':
            r = subprocess.run(['systemctl', '--user', act, name],
                               capture_output=True, text=True, timeout=60)
            note = r.stderr.strip() or f'{act}: done'
        else:
            from panel import supervise as sup
            note = '; '.join(([sup.stop(name)] if running else []) + [sup.start(name)])
        type(self)._cache.pop(f, None)
        acct = html.escape(self._account(fi))
        return self._page(
            f'<h1>{said}: starting</h1><p class="say">The engine that runs {acct} was '
            + ('restarted: every bot in it restarted with it.' if running else
               'started: every bot in it started with it.')
            + ' Its card says it is running after the next readout; a bot the exchange '
            'refuses at start is set aside and its card says stopped.</p>'
            f'<p class="dim">{html.escape(note)}</p>' + back)
