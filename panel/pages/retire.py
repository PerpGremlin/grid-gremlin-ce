"""Retire (D145): one page per bot with every way to wind it down — pause,
stand down keeping the position, stand down closing everything — and its
removal from the fleet inside it. The panel holds no keys: it writes the
request, and the running fleet's bot acts on it under its own links (the
road a trade's close takes, L7). A mixin the Handler inherits."""
from ..html_bits import accepts, confirm_dialog, typed_inline, confirmed, full_name, refusal_box, to_type, typed_name
from panel.chart import _f
from pathlib import Path
import html
import json
import time
import urllib.parse

# D157: stop is a choice, as on the platforms — close the position or leave
# it open — and pause, the gentlest, after them: (value, label, what it does).
# The values are the engine's own retire steps (D145); none is picked for you.
STEPS = (
    ('close', 'stop and close the position',
     'cancels every order it owns, closes its whole position with one market order '
     'that can only reduce it, and stops it for good. It cannot be undone.'),
    ('hold', 'stop and leave the position open',
     'cancels every order it owns and stops it for good; the position stays open '
     'on the exchange with nothing managing it, and <b>close position</b> on its '
     'card closes it when you choose.'),
    ('pause', 'pause instead',
     'opens and adds nothing; its exits, take profit and stop keep working, and '
     'its position and orders stay. <b>resume</b> undoes it.'),
)
CHOICES = ('close', 'hold', 'pause')
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
        said = html.escape(full_name(row) or botid)
        top = (f'<h1>stop {said} <span class="dim">{b}</span></h1><p class="say">'
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
                + typed_inline(f'type {to_type(botid, row, real)} to take it off the account: '
                               '<input name="confirm" size="22" autocomplete="off"> ')
                + confirm_dialog(                                   # D159: the pop-up
                    f'Take the bot {full_name(row) or botid} off {self._account(min(fi, len(self.fleets) - 1))}: '
                    'its row and watchdog line leave the files.',
                    to_type(botid, row, real), accepts(botid, row, real), 'remove', danger=True)
                + '<button class="danger">remove</button></form>'
                '<p class="dim">the bot and its watchdog line leave the account\'s files together; a '
                'backup is kept beside each.</p>')
        if req and req.get('action') in ('hold', 'close'):
            return self._page(
                top + f'<p>Stop asked by {html.escape(str(req["by"]))} at {html.escape(str(req["t"]))}: '
                + html.escape(dict((s[0], s[1]) for s in STEPS)[req['action']])
                + '. The running bot acts within a cycle (on a stopped account, when it next starts); '
                '<a href="">reload</a> to see it stood down'
                + (' and remove its row' if req.get('remove') else '') + '.</p>')
        paused = req and req.get('action') == 'pause'
        steps = ''.join(
            f'<p><label><input type="radio" name="do" value="{v}"'
            + (' disabled' if v == 'pause' and paused else '')
            + f'> <b>{label}</b></label> — {what}</p>' for v, label, what in STEPS)
        return self._page(
            top
            + (f'<p class="neg">paused since {html.escape(str(req["t"]))} by {html.escape(str(req["by"]))}.</p>'
               '<form method="post" action="/retire">' + hidden
               + '<input type="hidden" name="do" value="resume">'
               f'<input type="hidden" name="confirm" value="{b}">'
               '<button>resume</button></form>' if paused else '')
            + '<form method="post" action="/retire">' + hidden
            + '<p class="say"><b>Close the position, or leave it open?</b></p>' + steps
            + '<p><label><input type="checkbox" name="remove" value="1"> and <b>remove</b> it from the '
            'account once it has stopped</label> <span class="dim">(not with pause)</span></p>'
            + typed_inline(
                f'type {to_type(botid, row, real)}: <input name="confirm" size="22" autocomplete="off"> '
                + ('<br><span class="neg">real money</span> — to close everything, type the size a second '
                   'time: <input name="size" size="14" placeholder="the size above"> ' if real and held else ''))
            + confirm_dialog(                                       # D159: the pop-up
                f'Stop the bot {full_name(row) or botid} on {self._account(min(fi, len(self.fleets) - 1))}, '
                'as chosen above.', to_type(botid, row, real), accepts(botid, row, real), 'stop it',
                [('size', f'<b>real money</b>, to close everything: type the size (<code>{held:.10g}</code>) '
                  'a second time', None)] if real and held else [], danger=True)
            + '<button class="danger">stop it</button></form>')

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
        real = self._mainnet(f, row.get('venue', 'bybit'))
        if not confirmed(form.get('confirm'), botid, row, mainnet=real):       # D157
            said = None if real else typed_name(row)
            return self._page(refusal_box('not retired', 'the typed name must be exactly '
                                          + (f'{said} or {botid}' if said else botid)
                                          + ' — a click is not a decision'))
        if do not in CHOICES + ('resume', 'remove'):
            return self._page(refusal_box('not stopped', 'choose one: close the position, '
                                                         'leave it open, or pause'))
        b = html.escape(botid)
        back = f'<p><a href="/retire?fleet={fi}&amp;bot={b}">back to its stop page</a> · <a href="/">your bots</a></p>'
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
            return self._page(f'<h1>{b}: paused</h1><p>The running bot pauses within a cycle: '
                              'it opens and adds nothing, and its exits and stop keep working. '
                              'Its stop page offers <b>resume</b>.</p>' + back)
        if req.get('remove'):
            # the bot acts within a cycle; wait for it, then take the row out
            end = time.time() + WAIT_S
            while time.time() < end:
                if self._retire_state(fi, botid)[1]:
                    return self._retire_remove(fi, botid, back)
                time.sleep(0.5)
        return self._page(f'<h1>{b}: stop asked</h1><p>The running bot '
                          + ('cancels its orders and closes its whole position at market'
                             if do == 'close' else 'cancels its orders and leaves its position open')
                          + ' within a cycle, and stops for good (on a stopped account, when it '
                          'next starts).'
                          + (' It has not stopped yet; its stop page offers the removal once '
                             'it has.' if req.get('remove') else '') + '</p>' + back)

    def _retire_remove(self, fi, botid, back):
        """The row and its watchdog line out of the files — only for a bot
        that has stood down or never started, so nothing it owns is left
        running unmanaged; everything kept under its name goes with it (X16:
        nothing is left to revive, and a new bot on that coin and side
        starts clean)."""
        from panel.create import atomic_write, dump_config, public_adapter, remove_proposal, validate_whole
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
        from gridgremlin.forget import forget_bot
        forget_bot(f, fleet_raw, botid)              # X16: a new bot on this coin starts clean
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
