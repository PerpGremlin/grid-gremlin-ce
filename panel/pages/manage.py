"""D164: the trade manager — a perpetual position no bot covers, adopted and
managed: its take profit and stop, a close of part or all. A mixin the
Handler inherits; the venue writes are the engine's (gridgremlin.managed),
run as a subprocess with the fleet's own keys, as the close command is."""
from ..html_bits import accepts, confirm_dialog, confirmed, esc, refusal_box, to_type, typed_inline
from panel.chart import _f
from pathlib import Path
import json
import subprocess
import time
import urllib.parse


def trade_row(market, symbol, side):
    """The fields the plain name reads: a managed trade is named as a trade
    ("BTCUSDT Perpetual Futures Trade long") and typed so (D157/D161)."""
    return {'symbol': symbol, 'side': side, 'market_type': market, 'strategy': 'martingale',
            'trade': True}


class ManagePages:
    def _with_managed(self, fleet, contract):
        """D164: the fleet's managed trades, for the account box's links;
        the contract as it was when there are none."""
        from gridgremlin.managed import ManagedError, load, managed_path
        try:
            got = load(managed_path(fleet))
        except ManagedError:
            got = {}
        return dict(contract, managed=got) if got else contract

    def _managed_ctx(self, fi, key):
        """The trade a key names on account `fi`: its position as the readout
        holds it (fresh), its record, and its uncovered part. Refuses a
        stale readout, a position the account does not hold. D181: Mainnet
        is read here as any account; its writes go only through its running
        fleet (_manage_post)."""
        from gridgremlin.managed import (ManagedError, account_run, bot_shares, load, managed_path,
                                         parse_key, uncovered)
        from panel.strip_view import READOUT_STALE_S
        f = self.fleets[min(max(fi, 0), len(self.fleets) - 1)]
        venue, market, symbol, side = parse_key(key)
        contract = self._contract(f)
        gen = contract.get('generated_ms')
        if gen is None or time.time() - gen / 1000.0 > READOUT_STALE_S:
            raise ManagedError('the account was not read in the last few minutes — try again '
                               'after the next readout')
        pos = next((p for p in ((contract.get('account') or {}).get(venue) or {}).get('positions') or []
                    if (p.get('market'), p.get('symbol'), p.get('side')) == (market, symbol, side)
                    and abs(p.get('size') or 0.0) > 0), None)
        if pos is None:
            raise ManagedError(f'{symbol} {side}: the account holds no such position now')
        run = account_run(f)
        size = abs(pos['size'])
        free = uncovered(size, bot_shares(run, venue, market, symbol, side, size))
        rec = load(managed_path(f)).get(key)
        return f, (venue, market, symbol, side), pos, rec, run, free

    def _run_managed(self, fi, action, key, **kw):
        """The engine's own command, as a subprocess — the keys are its,
        never this process's (X15's arrangement)."""
        fleet = self.fleets[min(fi, len(self.fleets) - 1)]
        try:
            from gridgremlin.durable import fleet_env, fleet_home
            from gridgremlin.managed import command
            out = subprocess.run(command(Path(fleet).resolve(), action, key, **kw),
                                 capture_output=True, text=True, timeout=60,
                                 cwd=str(fleet_home(fleet)), env=fleet_env(fleet))
            last = (out.stderr.strip().splitlines() or ['no reason given'])[-1]
            return (json.loads(out.stdout) if out.stdout.strip()
                    else {'refused': f'the trade command stopped: {last}'})
        except subprocess.TimeoutExpired:
            return {'refused': 'the exchange did not answer within a minute — look at it '
                               'directly before trying again'}
        except ValueError:
            return {'refused': 'the trade command answered something unreadable — look at the '
                               'exchange directly'}

    def _manage_form(self, fi, key, action, row, botid, what, button, inner, danger=False, real=False):
        """D159's typed form; on Mainnet (D181, as D157/D64 have a Mainnet
        bot) the code only, and each number typed a second time in `inner`."""
        return ('<form method="post" action="/manage"><input type="hidden" name="gg" value="1">'
                f'<input type="hidden" name="fleet" value="{fi}">'
                f'<input type="hidden" name="key" value="{esc(key)}">'
                f'<input type="hidden" name="action" value="{action}">{inner}'
                + typed_inline(f'type {to_type(botid, row, mainnet=real)} to confirm: '
                               '<input name="confirm" size="22" autocomplete="off"> ')
                + confirm_dialog(what, to_type(botid, row, mainnet=real), accepts(botid, row, mainnet=real),
                                 button, danger=danger)
                + f'<button{" class=\"danger\"" if danger else ""}>{esc(button)}</button></form>')

    def _manage_route(self, f, venue):
        """D181: who carries out a write — 'fleet' where the account's
        fleet runs (its own signer; Mainnet's only way), 'command' on a
        stopped Demo or Testnet fleet, None on a stopped Mainnet one."""
        from gridgremlin.main import fleet_running
        try:
            raw = json.loads(Path(f).read_text())
            account = raw.get('account') or 'default'
        except (OSError, ValueError, AttributeError):
            account = 'default'
        if fleet_running(f, {venue}, account):
            return 'fleet'
        return None if self._mainnet(f, venue) else 'command'

    def _ask_fleet(self, f, key, action, wait_s=None, **nums):
        """L15: the request written, its answer awaited a little (the fleet
        polls each cycle); still waiting is said, never read as done."""
        from gridgremlin.managed import answer_of, ask, managed_path
        rid = ask(managed_path(f), key, action, by='panel', **nums)
        end = time.time() + (ASK_WAIT_S if wait_s is None else wait_s)
        while True:
            got = answer_of(f, key, rid)
            if got is not None:
                return got
            if time.time() >= end:
                return {'waiting': rid}
            time.sleep(0.5)

    def _manage_page(self):
        """D164 (U156): one managed trade, the market named fully."""
        from gridgremlin.apply import make_botid
        from gridgremlin.managed import ManagedError, current
        from panel.strip_view import _dq, _q, position_words
        q = dict(urllib.parse.parse_qsl(self.path.split('?', 1)[1]))
        if not self._fleet_ok(q.get('fleet')):
            return self._deny(400, 'no such fleet')
        fi, key = int(_f(q.get('fleet')) or 0), q.get('key', '')
        try:
            _f0, (venue, market, symbol, side), pos, rec, _run, free = self._managed_ctx(fi, key)
        except ManagedError as e:
            return self._page(refusal_box('not managed', e))
        row, botid = trade_row(market, symbol, side), make_botid(market, symbol, side)
        acct = self._account(min(fi, len(self.fleets) - 1))
        said = position_words(pos, trade=True)
        head = (f'<h1>{said} <span class="dim">— {esc(acct)}</span></h1>'
                f'<p class="say">size <b>{_q(abs(pos["size"]))}</b> · not covered by a bot '
                f'<b>{_q(free)}</b> · entry {_q(pos.get("entry"))} · mark {_q(pos.get("mark"))} · '
                f'P&amp;L {_dq(pos.get("upnl"))}</p>')
        if free <= 0:
            return self._page(head + refusal_box(
                'not managed', 'a bot of this account runs this side: by I2 its whole position '
                'there is the bot\'s, so nothing is uncovered'))
        if not current(rec, pos):
            from panel.strip_view import exits_words
            found = exits_words(pos.get('exits'))
            took = (f'It takes the exits already on the exchange as its own: <b>{esc(found)}</b>. '
                    'Setting a new stop or take profit later places it first, then cancels these.'
                    if found else 'Its take profit and stop stay unset until you set them.')
            return self._page(
                head + '<p class="say">Adopting places and cancels no order: the trade is '
                f'yours to manage from here. {took} '
                'Only the part no bot covers is ever managed.</p>'
                + self._manage_form(fi, key, 'adopt', row, botid,
                                    f'Manage {symbol} {side} on {acct} as a trade. No order is placed.',
                                    'manage it', '', real=self._mainnet(_f0, venue))
                + '<p><a href="/">back, change nothing</a></p>')
        armed = bool(self.units or self.supervise)
        real = self._mainnet(_f0, venue)
        route = self._manage_route(_f0, venue)
        again = (lambda name: f' again <input name="retype_{name}" size="12" autocomplete="off">'
                 if real else '')
        how = ('the fleet running this account carries it out with its own signer'
               if route == 'fleet' else 'the engine\'s command, the fleet being stopped')
        exits = self._manage_form(
            fi, key, 'exits', row, botid,
            f'Set the take profit and stop of {symbol} {side} on {acct}, for the '
            f'{free:.10g} no bot covers. A box left empty sets no such exit; any this trade set before '
            'is replaced' + (', the new placed before the old is cancelled.' if venue == 'hyperliquid' else '.'),
            'set exits',
            f'<p>take profit <input name="tp" size="12" value="{esc(_blank(rec.get("tp")))}">{again("tp")} '
            f'· stop <input name="sl" size="12" value="{esc(_blank(rec.get("sl")))}">{again("sl")} '
            '<span class="dim">prices; on the exchange as a take profit and a stop market sized to '
            'the uncovered part, reduce-only, triggered at the mark</span></p>', real=real)
        close = self._manage_form(
            fi, key, 'close', row, botid,
            f'Close part or all of {symbol} {side} on {acct} at market: one reduce-only order, '
            f'never more than the {free:.10g} no bot covers. It cannot be undone.',
            'close at market',
            f'<p>size <input name="qty" size="12" placeholder="{free:.10g}">{again("qty")} '
            + ('<span class="dim">on Mainnet the size is typed, twice</span></p>' if real else
               '<span class="dim">empty closes all of the uncovered part</span></p>'),
            danger=True, real=real)
        scale = ''
        if venue == 'hyperliquid':
            lad = rec.get('ladder') or {}
            scale = self._manage_form(
                fi, key, 'scale', row, botid,
                f'Scale out of {symbol} {side} on {acct}: reduce-only limit orders from the start to the '
                f'end price, together the {free:.10g} no bot covers. A ladder set before is replaced, '
                'the new placed before the old is cancelled. 0 orders clears it. The stop is not touched.',
                'set scale out',
                f'<p>from <input name="start" size="10" value="{esc(_blank(lad.get("start")))}">{again("start")} '
                f'to <input name="end" size="10" value="{esc(_blank(lad.get("end")))}">{again("end")} '
                f'· orders <input name="count" size="3" value="{esc(str(lad.get("count") or 5))}">{again("count")} '
                f'· size skew <input name="skew" size="4" value="{esc(_blank(lad.get("skew") or 1.0))}">{again("skew")} '
                '<span class="dim">Hyperliquid\'s Scale: 1 is even sizes, 2 makes the last order twice '
                'the first; each order rests as a reduce-only limit</span></p>', real=real)
        if not armed:
            writes = ('<p class="dim">control is not armed on this panel (--units or --supervise): '
                      'setting exits and closing reach the exchange and need it.</p>')
        elif route is None:
            writes = ('<p class="dim">this Mainnet account\'s fleet is stopped: on Mainnet only its '
                      'running fleet sets exits or closes (D181) — start it, or act on the exchange.</p>')
        else:
            writes = f'<p class="dim">a write here: {how}.</p>' + exits + scale + close
        return self._page(
            head + f'<p class="say">managed since {esc(rec.get("adopted") or "—")} · take profit '
            f'<b>{_q(rec.get("tp"))}</b> · stop <b>{_q(rec.get("sl"))}</b></p>'
            + _ladder_line(rec) + self._ask_lines(_f0, key, rec) + writes
            + '<p><a href="/">back to your bots</a></p>')

    def _ask_lines(self, f, key, rec):
        """The request waiting for the fleet, and the fleet's last answer."""
        from gridgremlin.managed import answers_path, load
        out = ''
        a = rec.get('ask')
        if a:
            out += (f'<p class="say">a request to {esc(a.get("action"))} is waiting for the fleet '
                    f'(asked {time.strftime("%H:%M:%S", time.gmtime(float(a.get("t") or 0)))} UTC)</p>')
        try:
            last = load(answers_path(f)).get(key)
        except Exception:                                   # noqa: BLE001
            last = None
        if last:
            when = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(float(last.get('t') or 0)))
            said = (f'refused: {last["refused"]}' if 'refused' in last else 'done')
            out += f'<p class="dim">the fleet\'s last answer ({esc(when)} UTC): {esc(said)}</p>'
        return out

    def _manage_post(self, form):
        """D164: adopt (a record only), set the exits, or close part or all —
        each typed through the pop-up. D181: where the fleet runs, its own
        process carries the write out (Mainnet's only way, typed as a
        Mainnet bot is); a stopped Demo or Testnet fleet, the command."""
        from gridgremlin.apply import make_botid
        from gridgremlin.managed import ManagedError, adopt, managed_path
        fi, key, act = int(_f(form.get('fleet')) or 0), form.get('key', ''), form.get('action', '')
        if act not in ('adopt', 'exits', 'close', 'scale'):
            return self._deny(403, 'unknown action')
        try:
            f, (venue, market, symbol, side), pos, rec, run, free = self._managed_ctx(fi, key)
            row, botid = trade_row(market, symbol, side), make_botid(market, symbol, side)
            real = self._mainnet(f, venue)
            if not confirmed(form.get('confirm'), botid, row, mainnet=real):
                raise ManagedError(f'type its code {botid} exactly — on Mainnet the code only (D157)' if real else
                                   f'type {row["symbol"]} Perpetual Futures Trade {side}, or its code '
                                   f'{botid}, exactly — a click is not a decision')
            if act == 'adopt':
                adopt(managed_path(f), venue, pos, run)            # L9: no order, no exit
                type(self)._cache.pop(f, None)
                return self._page(f'<h1>{esc(symbol)} {esc(side)}: managed</h1><p class="say">No '
                                  'order was placed. Set its take profit and stop on its page.</p>'
                                  f'<p><a href="/manage?fleet={fi}&amp;key={urllib.parse.quote(key)}">'
                                  'its page</a> · <a href="/">back to your bots</a></p>')
            if not self.units and not self.supervise:
                return self._deny(404, 'control is not armed on this panel')
            route = self._manage_route(f, venue)
            if route is None:
                raise ManagedError('on Mainnet only the running fleet sets exits or closes (D181), and '
                                   'this account\'s fleet is stopped — start it, or act on the exchange')
            if act == 'exits':
                nums = {'tp': _price(form.get('tp')), 'sl': _price(form.get('sl'))}
            elif act == 'scale':
                nums = {'start': _price(form.get('start')), 'end': _price(form.get('end')),
                        'count': _price(form.get('count')), 'skew': _price(form.get('skew'))}
                if nums['count'] is None or nums['count'] != int(nums['count']):
                    raise ManagedError('the number of orders is a whole number (0 clears the ladder)')
                if nums['count'] and (nums['start'] is None or nums['end'] is None):
                    raise ManagedError('a scale out needs its start and end prices')
            else:
                nums = {'qty': _price(form.get('qty'))}
                if real and nums['qty'] is None:
                    raise ManagedError('on Mainnet the size to close is typed, never left to mean all')
                if nums['qty'] is not None and nums['qty'] > free * (1 + 1e-9):   # L12: said here first
                    raise ManagedError(f'{nums["qty"]:.10g} is more than the {free:.10g} no bot covers — '
                                       'a trade closes only its own part')
            if real:
                _retyped(nums, form)                                    # D64: each number twice
            if act == 'scale':
                nums['count'] = int(nums['count'])
                nums['skew'] = nums['skew'] or 1.0
            if route == 'fleet':
                got = self._ask_fleet(f, key, act, **nums)
            else:
                got = self._run_managed(fi, act, key, **nums)
        except ManagedError as e:
            return self._page(refusal_box('not done', e))
        page = f'/manage?fleet={fi}&amp;key={urllib.parse.quote(key)}'
        if 'waiting' in got:
            return self._page(f'<h1>{esc(symbol)} {esc(side)}: asked</h1><p class="say">The fleet has '
                              'not answered yet — it carries the request out at its next cycle. Nothing '
                              'is done until its answer shows on the trade\'s page.</p>'
                              f'<p><a href="{page}">its page</a> · <a href="/">back to your bots</a></p>')
        if 'refused' in got:
            return self._page(refusal_box('not done', got['refused']))
        type(self)._cache.pop(f, None)
        if act == 'exits':
            return self._page(f'<h1>{esc(symbol)} {esc(side)}: exits set</h1><p class="say">take '
                              f'profit {got.get("tp") or "none"} · stop {got.get("sl") or "none"}, for '
                              f'{got.get("sized"):.10g} — the part no bot covers.</p>'
                              '<p><a href="/">back to your bots</a></p>')
        if act == 'scale':
            lad = got.get('ladder') or []
            return self._page(f'<h1>{esc(symbol)} {esc(side)}: scale out '
                              + ('set' if lad else 'cleared') + '</h1>'
                              + (f'<p class="say">{len(lad)} reduce-only orders: '
                                 + ' · '.join(f'{q:.10g} at {px:.10g}' for px, q in lad) + '</p>' if lad else '')
                              + '<p><a href="/">back to your bots</a></p>')
        left = got.get('left') or 0.0
        return self._page(f'<h1>{esc(symbol)} {esc(side)}: closed {got.get("closed", 0.0):.10g}</h1>'
                          + (f'<p class="say">{left:.10g} is still open.</p>' if left > 0 else
                             '<p class="say">the exchange shows no position on this side now.</p>')
                          + '<p><a href="/">back to your bots</a></p>')


ASK_WAIT_S = 20              # the fleet polls each cycle (2 s on HL): an answer is near


def _retyped(nums, form):
    """D64 on Mainnet: each number typed a second time, and an empty box
    left empty in both."""
    from gridgremlin.managed import ManagedError
    for k, v in nums.items():
        again = _price(form.get(f'retype_{k}'))
        if (v is None) != (again is None) or (v is not None and abs(v - again) > 1e-9 * max(1.0, abs(v))):
            name = {'tp': 'take profit', 'sl': 'stop', 'qty': 'size', 'start': 'start price',
                    'end': 'end price', 'count': 'number of orders', 'skew': 'size skew'}[k]
            raise ManagedError(f'{name}: type it a second time, the same — on Mainnet each number is '
                               'typed twice (D64)' + ('' if v is not None else '; left empty, leave both empty'))


def _ladder_line(rec):
    """D184: the scale out resting, said on the trade's page."""
    lad = (rec or {}).get('ladder')
    if not lad:
        return ''
    plan = ' · '.join(f'{q:.10g} at {px:.10g}' for px, q in lad.get('plan') or [])
    return (f'<p class="say">scale out: <b>{len(lad.get("orders") or [])} orders</b> from '
            f'{lad.get("start"):.10g} to {lad.get("end"):.10g}, skew {lad.get("skew"):.10g} — {esc(plan)} '
            f'<span class="dim">(set {esc(lad.get("set") or "—")})</span></p>')


def _blank(x):
    return '' if x is None else f'{x:.10g}'


def _price(v):
    """A typed number (commas allowed), None when the box is empty; a word
    is refused, never read as no exit."""
    from gridgremlin.managed import ManagedError
    s = str(v or '').replace(',', '').strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        raise ManagedError(f'{s!r} is not a number') from None
