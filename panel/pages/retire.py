"""Retire (D145): one page per bot with every way to wind it down — pause,
stand down keeping the position, stand down closing everything — and its
removal from the fleet inside it. The panel holds no keys: it writes the
request, and the running fleet's bot acts on it under its own links (the
road a trade's close takes, L7). A mixin the Handler inherits."""
from ..html_bits import named, refusal_box
from panel.chart import _f
from pathlib import Path
import html
import json
import time
import urllib.parse

# the steps, gentlest first: (value, label, what it does)
STEPS = (
    ('pause', 'pause',
     'opens and adds nothing; its exits, take profit and stop keep working, and '
     'its position and orders stay. <b>resume</b> undoes it.'),
    ('hold', 'stand down, keep the position',
     'cancels every order it owns and stops it for good; the position stays open '
     'on the exchange with nothing managing it, and <b>close position</b> on its '
     'card closes it when you choose.'),
    ('close', 'stand down and close everything',
     'cancels every order it owns, closes its whole position with one market order '
     'that can only reduce it, and stops it for good. It cannot be undone.'),
)
WAIT_S = 15.0          # how long a stand-down with removal waits for the bot


class RetirePages:
    def _retire_bot(self, fi, botid):
        """The fleet file's row for `botid`, or the refusal in words: only a
        fleet row is retired here — a trade ends by close trade, a portfolio
        row by its own flatten."""
        from gridgremlin.apply import row_botid
        f = self.fleets[min(fi, len(self.fleets) - 1)]
        try:
            raw = json.loads(Path(f).read_text())
        except (OSError, ValueError):
            return None, 'the fleet file cannot be read'
        row = next((b for b in raw.get('bots') or []
                    if isinstance(b, dict) and row_botid(b) == botid), None)
        if row is None:
            return None, (f'{botid or "nothing"}: not a bot of this fleet file — a trade ends '
                          'by <b>close trade</b> on its card')
        if row.get('strategy') == 'portfolio':
            return None, (f'{botid}: a portfolio row winds down by its own flatten '
                          '(<code>gridgremlin.portfolio_flatten</code>), then <b>remove</b>')
        return row, None

    def _retire_state(self, fi, botid):
        """(the request in force, stood down, the engine's last word on it)."""
        from gridgremlin.retire import load_requests, requests_path
        from gridgremlin.tombstones import Tombstones, path_for
        from gridgremlin.equity_series import snapshot_path
        f = self.fleets[min(fi, len(self.fleets) - 1)]
        raw = json.loads(Path(f).read_text())
        try:
            req = load_requests(requests_path(f)).get(botid)
        except (OSError, ValueError):
            req = None
        dead = Tombstones(str(path_for(f, raw))).has(botid)
        seen = None
        try:
            last = Path(snapshot_path(f)).read_text().strip().splitlines()[-1]
            seen = (json.loads(last).get('bots') or {}).get(botid)
        except (TypeError, OSError, ValueError, IndexError, AttributeError):
            pass
        return req, dead, seen

    def _retire_page(self):
        if not self.units and not self.supervise:
            return self._deny(404, 'control is not armed on this panel (--units or --supervise)')
        q = dict(urllib.parse.parse_qsl(self.path.split('?', 1)[1]))
        fi, botid = int(_f(q.get('fleet')) or 0), q.get('bot', '')
        row, why = self._retire_bot(fi, botid)
        if row is None:
            return self._page(refusal_box('cannot retire', why))
        req, dead, seen = self._retire_state(fi, botid)
        b = html.escape(botid)
        held = self._snapshot_held(fi, botid)
        real = self._mainnet(self.fleets[min(fi, len(self.fleets) - 1)], row.get('venue', 'bybit'))
        top = (f'<h1>retire {b}</h1><p class="say">'
               + (f'It holds <b>{held:.10g}</b>, as the engine\'s last snapshot says. ' if held else
                  'The engine\'s last snapshot shows it holding nothing. ' if seen else
                  'The engine has not reported this bot — it has not started. ')
               + '</p>')
        hidden = ('<input type="hidden" name="gg" value="1">'
                  f'<input type="hidden" name="fleet" value="{fi}">'
                  f'<input type="hidden" name="bot" value="{b}">')
        if dead or not seen:
            # stood down, or never started: nothing runs, the row may leave
            said = ('<p>It has stood down' + (f' ({html.escape(str(req["action"]))}, asked by '
                                              f'{html.escape(str(req["by"]))} at {html.escape(str(req["t"]))})'
                                              if req else '') + '.</p>') if dead else ''
            if dead and held:
                said += (f'<p class="neg">its position of {held:.10g} is still open — '
                         f'<a href="/close?fleet={fi}&amp;bot={b}">close position</a> '
                         'closes it; removing the row first leaves it with no door here.</p>')
            return self._page(
                top + said + '<form method="post" action="/retire">' + hidden
                + '<input type="hidden" name="do" value="remove">'
                + f'type the bot\'s name to take its row out of the fleet: <input name="confirm" '
                f'size="18" placeholder="{b}"> <button class="danger">remove</button></form>'
                '<p class="dim">the row and its watchdog line leave the files together; a '
                'backup is kept beside each.</p>')
        if req and req.get('action') in ('hold', 'close'):
            return self._page(
                top + f'<p>Retire asked by {html.escape(str(req["by"]))} at {html.escape(str(req["t"]))}: '
                + html.escape(dict((s[0], s[1]) for s in STEPS)[req['action']])
                + '. The running fleet acts within a cycle (a stopped fleet, at its next start); '
                '<a href="">reload</a> to see it stood down'
                + (' and remove its row' if req.get('remove') else '') + '.</p>')
        paused = req and req.get('action') == 'pause'
        steps = ''.join(
            f'<p><label><input type="radio" name="do" value="{v}"'
            + (' checked' if v == ('hold' if paused else 'pause') else '')
            + (' disabled' if v == 'pause' and paused else '')
            + f'> <b>{label}</b></label> — {what}</p>' for v, label, what in STEPS)
        return self._page(
            top
            + (f'<p class="neg">paused since {html.escape(str(req["t"]))} by {html.escape(str(req["by"]))}.</p>'
               '<form method="post" action="/retire">' + hidden
               + '<input type="hidden" name="do" value="resume">'
               f'<input type="hidden" name="confirm" value="{b}">'
               '<button>resume</button></form>' if paused else '')
            + '<form method="post" action="/retire">' + hidden + steps
            + '<p><label><input type="checkbox" name="remove" value="1"> and <b>remove</b> it from the '
            'fleet once it has stood down</label> <span class="dim">(not with pause)</span></p>'
            + f'type the bot\'s name: <input name="confirm" size="18" placeholder="{b}"> '
            + ('<br><span class="neg">real money</span> — to close everything, type the size a second '
               'time: <input name="size" size="14" placeholder="the size above"> ' if real and held else '')
            + '<button class="danger">retire</button></form>')

    def _retire_act(self, form):
        if not self.units and not self.supervise:
            return self._deny(404, 'control is not armed on this panel')
        from gridgremlin.retire import drop, request, requests_path
        from gridgremlin.config import ConfigError
        botid, do = form.get('bot', ''), form.get('do', '')
        fi = int(_f(form.get('fleet')) or 0)
        f = self.fleets[min(fi, len(self.fleets) - 1)]
        row, why = self._retire_bot(fi, botid)
        if row is None:
            return self._page(refusal_box('not retired', why))
        if not named(form.get('confirm'), botid):
            return self._page(refusal_box('not retired', f'the typed name must be exactly {botid} — '
                                                         'a click is not a decision'))
        b = html.escape(botid)
        back = f'<p><a href="/retire?fleet={fi}&amp;bot={b}">back to its retire page</a> · <a href="/">your bots</a></p>'
        if do == 'resume':
            done = drop(requests_path(f), botid, only_pause=True)
            return self._page(f'<h1>{b}: ' + ('resumed' if done else 'was not paused') + '</h1>'
                              '<p>the running fleet lifts the pause within a cycle.</p>' + back)
        if do == 'remove':
            return self._retire_remove(fi, botid, back)
        held = self._snapshot_held(fi, botid)
        if do == 'close' and held and self._mainnet(f, row.get('venue', 'bybit')):
            typed = _f(str(form.get('size', '')).replace(',', ''))
            if typed is None or abs(typed - held) > 1e-9 * max(1.0, held):
                return self._page(refusal_box('not retired', 'on real money the size is typed a '
                                                             'second time, exactly as the page shows it'))
        try:
            req = request(requests_path(f), botid, do, 'owner', 'retire on the panel',
                          remove=bool(form.get('remove')))
        except (ConfigError, OSError) as e:
            return self._page(refusal_box('not retired', e))
        if req['action'] != do:
            return self._page(refusal_box('not retired', f'{botid} is already asked to '
                                                         f'{req["action"]} ({req["t"]}) — that stands'))
        if do == 'pause':
            return self._page(f'<h1>{b}: paused</h1><p>The running fleet pauses it within a cycle: '
                              'it opens and adds nothing, and its exits and stop keep working. '
                              'Its retire page offers <b>resume</b>.</p>' + back)
        if req.get('remove'):
            # the bot acts within a cycle; wait for it, then take the row out
            end = time.time() + WAIT_S
            while time.time() < end:
                if self._retire_state(fi, botid)[1]:
                    return self._retire_remove(fi, botid, back)
                time.sleep(0.5)
        return self._page(f'<h1>{b}: retire asked</h1><p>The running fleet '
                          + ('cancels its orders and closes its whole position at market'
                             if do == 'close' else 'cancels its orders and keeps its position')
                          + ' within a cycle, and the bot stands down for good (a stopped fleet '
                          'does it at its next start).'
                          + (' It has not stood down yet; its retire page offers the removal once '
                             'it has.' if req.get('remove') else '') + '</p>' + back)

    def _retire_remove(self, fi, botid, back):
        """The row and its watchdog line out of the files — only for a bot
        that has stood down or never started, so nothing it owns is left
        running unmanaged; its request and tombstone go with it (nothing is
        left to revive, and a new bot on that coin and side starts clean)."""
        from panel.create import atomic_write, dump_config, public_adapter, remove_proposal, validate_whole
        from gridgremlin.retire import drop, requests_path
        from gridgremlin.tombstones import path_for, remove as tomb_remove
        req, dead, seen = self._retire_state(fi, botid)
        if seen and not dead:
            return self._page(refusal_box('not removed', f'{botid} is still running — retire it first: '
                                                         'a removed row leaves its orders and position '
                                                         'on the exchange with nothing managing them'))
        f = Path(self.fleets[min(fi, len(self.fleets) - 1)])
        try:
            fleet_raw = json.loads(f.read_text())
            wd_p = Path(fleet_raw['watchdog'])
            _, fleet, wd = remove_proposal(fleet_raw, json.loads(wd_p.read_text()), botid)
            refusal = validate_whole(fleet, wd, public_adapter)
        except Exception as e:                                   # noqa: BLE001
            return self._page(refusal_box('not removed', e))
        if refusal:
            return self._page(refusal_box('the engine refuses this fleet', refusal))
        atomic_write(f, dump_config(fleet))
        atomic_write(wd_p, dump_config(wd))
        drop(requests_path(f), botid)
        if dead:
            tomb_remove(path_for(f, fleet_raw), botid)
        held = self._snapshot_held(fi, botid)
        return self._page(
            f'<h1>{html.escape(botid)}: retired and removed</h1><p>its row and watchdog line left the '
            'files (a backup is kept beside each); the fleet forgets it at its next restart.</p>'
            + (f'<p class="dim">the engine\'s last snapshot, which may be from before the close, '
               f'shows {held:.10g} held — the exchange has the last word.</p>'
               if held and (req or {}).get('action') == 'close' else
               f'<p class="neg">its position of {held:.10g} stays open on the exchange, yours to manage.</p>'
               if held else '')
            + back)
