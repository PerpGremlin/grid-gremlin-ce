"""Setting up and editing a bot (U19): the setup page, the review with its chart, what-if and fit, the create and apply flow. Moved out of routes.py whole (D91 step 3): a mixin
the Handler inherits."""
from ..forms import next_step_html, other_half_html, other_side_html, rehearse_bot_form, unit_for_fleet
from ..html_bits import named, qarg, refusal_box, tidy
from gridgremlin.apply import row_botid
from panel.chart import _f
from pathlib import Path
import html
import json
import time
import urllib.parse


class CreateFlowPages:
    def _create_flow(self, form, apply=False):
        from panel.create import (atomic_write, dry_ladder, dump_config,
                                  merge_proposal, public_adapter,
                                  public_mark, unified_diff, validate_whole)
        fi = int(_f(form.get('fleet')) or 0)
        fleet_p = Path(self.fleets[min(fi, len(self.fleets) - 1)])
        fleet_text = fleet_p.read_text()
        fleet_raw = json.loads(fleet_text)
        wd_p = Path(fleet_raw['watchdog'])
        wd_text = wd_p.read_text()
        wd_raw = json.loads(wd_text)
        seen = self._seen(fleet_text, wd_text)
        mode = form.get('mode', 'create')
        if not (apply or mode == 'remove' or form.get('bot_json')):
            return self._refused(form, 'refused', 'nothing to create — '
                                 'start from "set up a bot"')
        try:                     # U84: a malformed post is refused in words
            proposal = self._proposal(form, apply)
        except ValueError as e:
            return self._refused(form, 'refused', e)
        mode = proposal['mode']
        if apply and proposal.get('seen') != seen:
            # U84: the reviewed change is written onto the files it was
            # reviewed against, or not at all
            return self._page(refusal_box(
                'not applied', 'the file changed since you reviewed it — '
                'review again'))
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
                    # U107: the smallest order in money at today's price —
                    # the coin minimum binds on a dear coin (0.001 BTC ≈ 82)
                    least = max(adapter.min_notional or 0.0, adapter.min_qty * m0)
                    for what, key in (('first order', 'base_order_size'),
                                      ('add-on order', 'safety_order_size')):
                        size = vbot.get(key)
                        if not size:
                            continue
                        coins = vbot.get('size_in') == 'coin'     # D89
                        q0 = adapter.round_qty(size if coins else size / m0)
                        if q0 <= 0 or not adapter.meets_minimum(q0, m0):
                            raise _CE(
                                f"the {what} ({size:g}{' coins' if coins else ''}) "
                                "is under this market's "
                                f"smallest order: about {least:.4g} at today's "
                                f"price ({adapter.min_qty:g} coins at {m0:g}) — "
                                f'raise the {what} size to at least that (it is '
                                "the order's whole value, leverage included), or "
                                'raise the investment the quick setup draws it from')
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
            if mode in ('create', 'remove'):
                # D149: a new or removed bot owns no old window — a slide
                # offset left under its name would shift the new grid
                from gridgremlin.durable import state_path
                from gridgremlin.slide_state import forget
                forget(state_path(str(fleet_p), fleet_raw, 'slide_state'), botid)
            return self._page(
                f'<h1>{html.escape(botid)}: written</h1><p>bot and watcher landed '
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
            from gridgremlin.ladder import rounding_note
            note = rounding_note(vbot, adapter)                       # G27
            ladder_html = (f'<p class="dim">the ladder at mark '
                           f'{mark:,.6g} (dry-run — nothing placed)</p>'
                           + (f'<p class="neg">{html.escape(note)}</p>' if note else '') +
                           f'<table><tr><th>side</th><th>price</th>'
                           f'<th>qty</th></tr>{lrows}</table>')
        diffs = (unified_diff(fleet_text, new_fleet, fleet_p.name)
                 + unified_diff(wd_text, new_wd, wd_p.name))
        pj = html.escape(json.dumps(dict(proposal, seen=seen)), quote=True)
        say = ''
        if proposal.get('pair'):                           # D54
            say = ('<p class="dim">the long half of a reversal grid, below '
                   f"the mid {float(proposal['pair']['mid']):,.6g}; the "
                   'short half above it follows once this one is written '
                   '(D54).</p>')
        if mode == 'remove':
            say += self._still_held(fi, botid)              # U97
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
                type(self)._adapters[self._market_key(vbot)] = (time.time(),
                                                             adapter)
                more = ('<div class="fsec">' + whatif_section(       # U88: each part boxed
                    vbot, adapter, mark, json.dumps(proposal['bot']), fi) + '</div>')
            except Exception as e:                          # noqa: BLE001
                more = (f'<p class="dim">no what-if: '
                        f'{_html.escape(str(e))}</p>')
            try:                   # U73: and how it fits the market it trades
                from ggdata.market import latest
                from panel.fit import fit_section
                more += '<div class="fsec">' + fit_section(vbot, self._bars_for(vbot), latest()) + '</div>'
            except Exception as e:                          # noqa: BLE001
                more += (f'<p class="dim">no market fit: '
                         f'{_html.escape(str(e))}</p>')
            say += (f'<div class="fsec"><h1 class="dim">in plain words</h1><p class="say">'
                    f'{_html.escape(sentence(vbot, mark))}</p>' + picture + '</div>' + more)
        if mode in ('create', 'edit'):
            say += ('<div class="fsec"><form method="post" action="/setup">'
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
            say += '</div>'
        verb = {'create': 'create this bot', 'edit': 'apply the change',
                'remove': 'remove this bot'}[mode]
        # U17: the apply box sits right under the summary; the file diff
        # and the dry-run orders fold away for whoever wants them
        return self._page(
            f'<h1>{html.escape(botid)} — {html.escape(mode)}: gates passed</h1>' + say +
            '<div class="fsec go">'                     # U88: the one action, its own box
            f'<form method="post" action="/apply" class="apply">'
            f'<input type="hidden" name="gg" value="1">'
            f'<input type="hidden" name="fleet" value="{fi}">'
            f'<input type="hidden" name="proposal" value="{pj}">'
            f'<b>To {verb}</b>, type its name <code>{html.escape(botid)}</code> here: '
            f'<input name="confirm" size="16" placeholder="{html.escape(botid)}"> '
            + ''.join(f'<br><b class="neg">Mainnet:</b> type the new {k} '
                      f'(<code>{n:g}</code>) again: <input name="retype_{k}" '
                      'size="12">' for k, _, n in jumps)
            + f'<button>{verb}</button></form>'
            '<p class="dim">this writes the fleet file. A running fleet '
            'takes changed terms within seconds; a new bot, a removed one '
            'or a changed range waits for a restart (F12).</p></div>'
            '<details><summary>the change to the file</summary>'
            f'<pre class="dim">{html.escape(diffs)}</pre></details>'
            '<details><summary>the orders it would place</summary>'
            + ladder_html + '</details>')

    @staticmethod
    def _proposal(form, apply):
        """The change a post asks for, read whole before anything else
        runs; ValueError, in words, when it is not one (U84)."""
        def obj(text, what):
            try:
                v = json.loads(text)
            except ValueError:
                raise ValueError(f'{what} is not readable — start again from '
                                 '"set up a bot"') from None
            if not isinstance(v, dict):
                raise ValueError(f'{what} is not a bot — start again from '
                                 '"set up a bot"')
            return v
        mode = form.get('mode', 'create')
        if apply:
            proposal = obj(form.get('proposal', '{}'), 'the reviewed change')
            mode = proposal.setdefault('mode', 'create')
        elif mode == 'remove':
            proposal = {'mode': 'remove', 'orig': form.get('orig', '')}
        else:                                     # §11: the setup form's row
            proposal = {'mode': mode, 'orig': form.get('orig', ''),
                        'bot': obj(form['bot_json'], 'the bot'),
                        'watchdog': {'max': _f(form.get('ceiling'))}}
            if form.get('pair'):                         # D54: the other half
                proposal['pair'] = obj(form['pair'], 'the other half')
        if mode not in ('create', 'edit', 'remove'):
            raise ValueError(f'{mode}: not a change the panel makes')
        if not isinstance(proposal.get('orig', ''), str):
            raise ValueError('the bot changed is named by its id')
        if mode != 'remove':
            if not isinstance(proposal.get('bot'), dict):
                raise ValueError('the reviewed change carries no bot — start '
                                 'again from "set up a bot"')
            if not isinstance(proposal.get('watchdog'), dict):
                proposal['watchdog'] = {'max': None}
            if not isinstance(proposal.get('pair', {}), dict):
                raise ValueError('the other half is not a bot')
        return proposal

    @staticmethod
    def _seen(*texts):
        """U84: what the review read — the fleet file's and the watchdog
        file's sha256 — so the apply writes onto those files or refuses."""
        import hashlib
        return [hashlib.sha256(t.encode()).hexdigest() for t in texts]

    def _fleet_labels(self):
        # U76: the account's name, as the dash says it (U55), not its file;
        # the form's values are the fleet's index, so only the words change
        labels = getattr(self, 'labels', None) or ()
        return [labels[i] if i < len(labels) and labels[i] else Path(f).name
                for i, f in enumerate(self.fleets)]

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
                out[row_botid(b)] = u
        return out

    def _symbols(self, fi):
        """U25: the fleet's venue's markets for the coin list; () when the
        venue cannot be read — the box is keyless and may be offline."""
        from panel.create import public_symbols
        return public_symbols(self._fleet_venue(fi))

    def _fleet_venue(self, fi):
        """A fleet file trades one venue: its first row says which, or, with
        no rows, its own 'venue' (U106: a cleared HL fleet was set up as Bybit)."""
        try:
            raw = json.loads(Path(self.fleets[fi]).read_text())
        except (OSError, ValueError):
            raw = {}
        raw = {'bots': raw} if isinstance(raw, list) else raw
        bots = raw.get('bots')
        if bots:
            return bots[0].get('venue', 'bybit')
        return raw.get('venue') or 'bybit'

    def _refused(self, form, title, why):
        """A refusal returns to the form it came from, values intact."""
        fi = int(_f(form.get('fleet')) or 0)
        extra = ''
        if 'already in this fleet' in str(why):
            # the commonest refusal, said as what to do next (U11)
            botid = str(why).split(':', 1)[0]
            extra = ('<br>You already have a bot for this coin and '
                     'direction in this account, and there can be only '
                     f'one. <a href="/edit?fleet={fi}&amp;bot={qarg(botid)}">Open '
                     'that bot to change it</a>, or pick another coin or '
                     'the other direction below.')
        note = refusal_box(title, why, extra)
        try:                                     # U84: only a bot redraws
            bot = json.loads(form.get('bot_json') or 'null')
        except ValueError:
            bot = None
        if isinstance(bot, dict):
            from panel.setup import advanced_page, form_from_bot
            try:
                vals = dict(form_from_bot(bot), ceiling=form.get('ceiling', ''))
                return self._page(advanced_page(
                    bot.get('strategy', 'grid'), vals, self._fleet_labels(),
                    fi, alert=note, edit=form.get('orig') or None))
            except Exception:                               # noqa: BLE001
                pass                       # a bot the form cannot draw (U84)
        return self._page(note + '<p><a href="/setup">set up a bot</a> · '
                          '<a href="/">fleet</a></p>')

    def _setup_page(self):
        from panel.setup import advanced_page, form_from_bot, quick_page
        q = (dict(urllib.parse.parse_qsl(self.path.split('?', 1)[1]))
             if '?' in self.path else {})
        fi = min(int(_f(q.get('fleet')) or 0), len(self.fleets) - 1)
        labels = self._fleet_labels()
        if q.get('copy'):
            bots = json.loads(Path(self.fleets[fi]).read_text()).get(
                'bots', [])
            src = next((b for b in bots if row_botid(b) == q['copy']
                        and b.get('strategy') != 'portfolio'), None)
            if src is None:
                return self._deny(404, f"{q['copy']}: not in this fleet")
            vals = form_from_bot(src)
            vals['symbol'] = ''        # one bot per market and side (I2)
            return self._page(advanced_page(
                src.get('strategy', 'grid'), vals, labels, fi,
                note=f'<p class="dim">copied from {q["copy"]}: every '
                     'setting is carried over — choose the coin, and '
                     'check the prices, which belong to the old one.</p>'))
        if q.get('adv') == 'carry':                              # U108
            return self._carry_page(fi)
        if q.get('adv') in ('grid', 'martingale'):
            return self._page(advanced_page(q['adv'], {}, labels, fi,
                                            symbols=self._symbols(fi)))
        return self._page(quick_page(labels, fi, symbols=self._symbols(fi)))

    def _bars_for(self, cfg):
        """Public candles, kept five minutes: a drag redraws, it does not
        refetch a month of history."""
        from panel.create import public_bars
        key = (cfg.get('venue'), cfg.get('market_type'), cfg.get('symbol'))
        hit = type(self)._bars.get(key)
        if hit and time.time() - hit[0] < 300:
            return hit[1]
        bars = public_bars(cfg)
        type(self)._bars[key] = (time.time(), bars)
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
            hit = type(self)._adapters.get(key)
            if not hit or time.time() - hit[0] >= 300:
                hit = type(self)._adapters[key] = (time.time(),
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
        self._out(body)

    def _setup_post(self, form):
        from panel.create import public_mark
        from panel.setup import (advanced_page, bot_from_form,
                                 form_from_bot, quick_bot)
        fi = min(int(_f(form.get('fleet')) or 0), len(self.fleets) - 1)
        venue = self._fleet_venue(fi)
        labels = self._fleet_labels()
        how = form.get('how')
        from panel.setup import SCHEMAS
        if how not in ('quick', 'reopen', 'mirror') and \
                form.get('strategy', 'grid') not in SCHEMAS:       # U84
            return self._page(refusal_box('not yet', f"{form['strategy']}: not a kind of bot "
                                          'the panel sets up — a grid or a DCA') +
                              '<p><a href="/setup">set up a bot</a></p>')
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
                from panel.setup import missing_required, resolve_size
                miss = missing_required(form.get('strategy', 'grid'), form)   # U105
                if miss:
                    raise ValueError('still needed: ' + '; '.join(miss))
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
            old = next((b for b in json.loads(
                Path(self.fleets[fi]).read_text()).get('bots', [])
                if row_botid(b) == orig),
                {})
            bot.update({k: v for k, v in old.items() if k.startswith('_')})
        return self._create_flow({'fleet': str(fi),
                                  'mode': 'edit' if orig else 'create',
                                  'orig': orig,
                                  'bot_json': json.dumps(bot),
                                  'ceiling': form.get('ceiling', ''),
                                  'pair': pair if how == 'quick' else ''})
