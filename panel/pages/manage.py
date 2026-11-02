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
        holds it (fresh), its record, and its uncovered part. Refuses Mainnet,
        a stale readout, a position the account does not hold."""
        from gridgremlin.managed import (ManagedError, account_run, bot_shares, load, managed_path,
                                         parse_key, uncovered)
        from panel.strip_view import READOUT_STALE_S
        f = self.fleets[min(max(fi, 0), len(self.fleets) - 1)]
        venue, market, symbol, side = parse_key(key)
        if self._mainnet(f, venue):
            raise ManagedError('a managed trade is Demo or Testnet only (D164): this account may '
                               'reach Mainnet, where nothing here acts')
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

    def _manage_form(self, fi, key, action, row, botid, what, button, inner, danger=False):
        return ('<form method="post" action="/manage"><input type="hidden" name="gg" value="1">'
                f'<input type="hidden" name="fleet" value="{fi}">'
                f'<input type="hidden" name="key" value="{esc(key)}">'
                f'<input type="hidden" name="action" value="{action}">{inner}'
                + typed_inline(f'type {to_type(botid, row)} to confirm: '
                               '<input name="confirm" size="22" autocomplete="off"> ')
                + confirm_dialog(what, to_type(botid, row), accepts(botid, row), button, danger=danger)
                + f'<button{" class=\"danger\"" if danger else ""}>{esc(button)}</button></form>')

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
            return self._page(
                head + '<p class="say">Adopting places no order and sets no exit: the trade is '
                'yours to manage from here, its take profit and stop unset until you set them. '
                'Only the part no bot covers is ever managed.</p>'
                + self._manage_form(fi, key, 'adopt', row, botid,
                                    f'Manage {symbol} {side} on {acct} as a trade. No order is placed.',
                                    'manage it', '')
                + '<p><a href="/">back, change nothing</a></p>')
        armed = bool(self.units or self.supervise)
        exits = self._manage_form(
            fi, key, 'exits', row, botid,
            f'Set the take profit and stop of {symbol} {side} on {acct}, for the '
            f'{free:.10g} no bot covers. A box left empty sets no such exit; any set before is replaced.',
            'set exits',
            f'<p>take profit <input name="tp" size="12" value="{esc(_blank(rec.get("tp")))}"> '
            f'stop <input name="sl" size="12" value="{esc(_blank(rec.get("sl")))}"> '
            '<span class="dim">prices; on the exchange as a take profit and a stop sized to the '
            'uncovered part, triggered at the mark</span></p>')
        close = self._manage_form(
            fi, key, 'close', row, botid,
            f'Close part or all of {symbol} {side} on {acct} at market: one reduce-only order, '
            f'never more than the {free:.10g} no bot covers. It cannot be undone.',
            'close at market',
            f'<p>size <input name="qty" size="12" placeholder="{free:.10g}"> '
            '<span class="dim">empty closes all of the uncovered part</span></p>', danger=True)
        return self._page(
            head + f'<p class="say">managed since {esc(rec.get("adopted") or "—")} · take profit '
            f'<b>{_q(rec.get("tp"))}</b> · stop <b>{_q(rec.get("sl"))}</b></p>'
            + (exits + close if armed else
               '<p class="dim">control is not armed on this panel (--units or --supervise): '
               'setting exits and closing reach the exchange and need it.</p>')
            + '<p><a href="/">back to your bots</a></p>')

    def _manage_post(self, form):
        """D164: adopt (a record only), set the exits, or close part or all —
        each typed through the pop-up, each refused on Mainnet."""
        from gridgremlin.apply import make_botid
        from gridgremlin.managed import ManagedError, adopt, managed_path
        fi, key, act = int(_f(form.get('fleet')) or 0), form.get('key', ''), form.get('action', '')
        if act not in ('adopt', 'exits', 'close'):
            return self._deny(403, 'unknown action')
        try:
            f, (venue, market, symbol, side), pos, rec, run, free = self._managed_ctx(fi, key)
            row, botid = trade_row(market, symbol, side), make_botid(market, symbol, side)
            if not confirmed(form.get('confirm'), botid, row):
                raise ManagedError(f'type {row["symbol"]} Perpetual Futures Trade {side}, or its code '
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
            if act == 'exits':
                tp, sl = _price(form.get('tp')), _price(form.get('sl'))
                got = self._run_managed(fi, 'exits', key, tp=tp, sl=sl)
            else:
                qty = _price(form.get('qty'))
                if qty is not None and qty > free * (1 + 1e-9):              # L12: said here first
                    raise ManagedError(f'{qty:.10g} is more than the {free:.10g} no bot covers — '
                                       'a trade closes only its own part')
                got = self._run_managed(fi, 'close', key, qty=qty)
        except ManagedError as e:
            return self._page(refusal_box('not done', e))
        if 'refused' in got:
            return self._page(refusal_box('not done', got['refused']))
        type(self)._cache.pop(f, None)
        if act == 'exits':
            return self._page(f'<h1>{esc(symbol)} {esc(side)}: exits set</h1><p class="say">take '
                              f'profit {got.get("tp") or "none"} · stop {got.get("sl") or "none"}, for '
                              f'{got.get("sized"):.10g} — the part no bot covers.</p>'
                              '<p><a href="/">back to your bots</a></p>')
        left = got.get('left') or 0.0
        return self._page(f'<h1>{esc(symbol)} {esc(side)}: closed {got.get("closed", 0.0):.10g}</h1>'
                          + (f'<p class="say">{left:.10g} is still open.</p>' if left > 0 else
                             '<p class="say">the exchange shows no position on this side now.</p>')
                          + '<p><a href="/">back to your bots</a></p>')


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
