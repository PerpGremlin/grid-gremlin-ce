"""D143: a portfolio row's leverage, reviewed and written (panel/lever.py is
the pure half): a mixin the Handler inherits."""
from gridgremlin.apply import row_botid
from ..html_bits import named, refusal_box
from pathlib import Path
import html
import json


class LeverPages:
    def _lever_post(self, form):
        """The review (the change in words and as a diff, a box for the
        row's name), then, with the name typed, the write — onto the file
        the review read, or not at all (U84). Real money is the file's, by
        hand (D64)."""
        from panel.chart import _f
        from panel.create import atomic_write, dump_config, unified_diff, validate_whole, public_adapter
        from panel.lever import lever_row, said
        fi = min(max(int(_f(form.get('fleet')) or 0), 0), len(self.fleets) - 1)
        fleet_p = Path(self.fleets[fi])
        text = fleet_p.read_text()
        raw = json.loads(text)
        botid = form.get('orig', '')
        i = next((n for n, b in enumerate(raw.get('bots', []))
                  if row_botid(b) == botid and b.get('strategy') == 'portfolio'), None)
        if i is None:
            return self._page(refusal_box('not reviewed', f'{botid}: no portfolio row of that name in this fleet'))
        if self._mainnet(fleet_p, raw['bots'][i].get('venue', 'bybit')):
            return self._page(refusal_box('not reviewed', 'this fleet may reach real money: its '
                                          'leverage is changed in the fleet file by hand (D64)'))
        spot = _f(form.get('spot'))
        perp_text = (form.get('perp') or '').strip()
        perp = _f(perp_text) if perp_text else None
        try:
            if spot is None or (perp_text and perp is None):
                raise ValueError('type the leverage as a number, like 3')
            new_row = lever_row(raw['bots'][i], spot, perp)
        except ValueError as e:
            return self._page(refusal_box('not reviewed', e))
        fleet = json.loads(text)
        fleet['bots'][i] = new_row
        wd_text = Path(raw['watchdog']).read_text()
        refusal = validate_whole(fleet, json.loads(wd_text), public_adapter)
        if refusal:
            return self._page(refusal_box('the engine refuses this fleet', refusal))
        new_text = dump_config(fleet)
        seen = self._seen(text, wd_text)
        try:
            reviewed = json.loads(form.get('seen') or 'null')
        except ValueError:
            reviewed = None
        if form.get('confirm') is not None and reviewed != seen:
            return self._page(refusal_box('not applied', 'the file changed since you reviewed it — review again'))
        if new_text == text:
            return self._page('<h1>nothing to change</h1><p class="dim">the file already says this.</p>'
                              '<p><a href="/">back to your bots</a></p>')
        if form.get('confirm') is not None:
            if not named(form.get('confirm'), botid):
                return self._page(refusal_box('not applied', f'the name typed must be {botid} '
                                              '(capitals do not matter) — a click is not a decision (§11)'))
            atomic_write(fleet_p, new_text)
            return self._page(f'<h1>{html.escape(botid)}: written</h1><p>The running fleet applies it '
                              'within a few seconds and says so on the phone; the stack moves at '
                              'its next read. A backup of the file is kept beside it.</p>'
                              '<p><a href="/">back to your bots</a></p>')
        e = html.escape
        words = ''.join(f'<p class="say">{e(w)}</p>' for w in said(raw['bots'][i], new_row))
        return self._page(
            f'<h1>{e(botid)}: the leverage change</h1>{words}'
            f'<pre>{e(unified_diff(text, new_text, fleet_p.name))}</pre>'
            '<form method="post" action="/lever"><input type="hidden" name="gg" value="1">'
            f'<input type="hidden" name="fleet" value="{fi}">'
            f'<input type="hidden" name="orig" value="{e(botid, quote=True)}">'
            f'<input type="hidden" name="spot" value="{e(form.get("spot", ""), quote=True)}">'
            f'<input type="hidden" name="perp" value="{e(perp_text, quote=True)}">'
            f'<input type="hidden" name="seen" value="{e(json.dumps(seen), quote=True)}">'
            f'<label>type <b>{e(botid)}</b> to write it <input name="confirm" size="14"></label> '
            '<button>write it</button></form><p><a href="/">back, change nothing</a></p>')
