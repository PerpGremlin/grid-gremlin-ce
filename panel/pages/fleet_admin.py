"""A bot's edit page and the tombstones (X7b). Moved out of routes.py whole (D91 step 3): a mixin
the Handler inherits."""
from gridgremlin.apply import row_botid
from ..html_bits import qarg
from pathlib import Path
import html
import json
import time
import urllib.parse


class FleetAdminPages:
    def _tombs_path(self, fi=0):
        """One fleet's tombstone file (one per fleet since 2026-10-08)."""
        from gridgremlin.tombstones import path_for
        f = self.fleets[min(fi, len(self.fleets) - 1)]
        try:
            raw = json.loads(Path(f).read_text())
        except (OSError, ValueError):
            raw = {}
        return path_for(f, raw)

    def _tombs_all(self):
        """Every fleet's tombstones: [(fleet index, label, path, rows)]."""
        out = []
        for fi, lb in enumerate(self.labels):
            tp = self._tombs_path(fi)
            try:
                rows = json.loads(tp.read_text() or '{}') if tp.exists() else {}
            except (OSError, ValueError):
                rows = {}
            out.append((fi, lb, tp, rows))
        return out

    def _edit_page(self):
        q = dict(urllib.parse.parse_qsl(self.path.split('?', 1)[1]))
        body = self._edit_body(int(q.get('fleet') or 0), q.get('bot', ''), q.get('mode'))
        if body is None:
            return self._deny(404, f'{html.escape(q.get("bot", ""))}: not in this fleet')
        return self._page(body + '<p><a href="/">&larr; fleet</a></p>')

    def _edit_body(self, fi, botid, mode=None):
        """A bot's edit door — its own page, or the front page's right half
        (U78c): the same form, posting where it always did. None: no such
        bot in the fleet."""
        fleet_raw = json.loads(Path(self.fleets[fi]).read_text())
        bot = next((b for b in fleet_raw.get('bots', [])
                    if row_botid(b) == botid), None)
        if bot is None:
            return None
        if bot.get('strategy') == 'portfolio' and mode != 'remove':
            from panel.carry_setup import carry_page, form_from_row
            from panel.lever import lever_form                      # D143
            try:                                                    # U111: the carry form, filled
                form = carry_page(form_from_row(bot), self._fleet_labels(), fi, edit=botid)
            except ValueError as e:
                form = f'<p class="dim">its coins, hedges, clock and risk: the fleet file, by hand — {html.escape(str(e))}.</p>'
            return (lever_form(fi, botid, bot) + form
                    + f'<p class="dim"><a href="/edit?fleet={fi}&amp;bot={qarg(botid)}&amp;mode=remove">remove</a> '
                    'is here.</p>')
        if mode == 'remove':
            return (f'<h1>remove {html.escape(botid)}</h1><p class="dim">the bot and its '
                    'watchdog line leave together; the remaining fleet must '
                    'still validate (F1). The running fleet is untouched until '
                    'restarted (§11).</p>' + self._still_held(fi, botid) +    # U97
                    f'<form method="post" action="/create">'
                    f'<input type="hidden" name="gg" value="1">'
                    f'<input type="hidden" name="mode" value="remove">'
                    f'<input type="hidden" name="fleet" value="{fi}">'
                    f'<input type="hidden" name="orig" value="{html.escape(botid)}">'
                    f'<button>run the gates</button></form>')
        from panel.setup import advanced_page, form_from_bot
        w = json.loads(Path(fleet_raw['watchdog']).read_text())
        wmax = (w.get('positions', {}).get(botid) or {}).get('max', '')
        vals = dict(form_from_bot(bot), ceiling=wmax)
        return advanced_page(bot.get('strategy', 'grid'), vals, self._fleet_labels(), fi, edit=botid)

    def _fleet_rows(self, fi):
        """The botids a fleet file holds now."""
        try:
            raw = json.loads(Path(self.fleets[min(fi, len(self.fleets) - 1)]).read_text())
        except (OSError, ValueError):
            return set()
        return {row_botid(b) for b in raw.get('bots') or []
                if isinstance(b, dict) and (b.get('symbol') or b.get('name'))}

    def _orphans(self, fi, tombs):
        """D149: a fleet's tombstones whose bot is no longer in its file —
        nothing they stop runs; they only block a new bot of the same coin,
        side and kind."""
        rows = self._fleet_rows(fi)
        return sorted(b for b in tombs if b not in rows)

    def _clear_orphans_act(self, form):
        """D149 (the owner, 2026-10-22: "that needs to be something we can do
        from the dash"): one fleet's leftover tombstones out at once, the
        fleet file's name typed. A tombstone whose bot is still in the file
        is a stand-down and keeps its own revive."""
        from gridgremlin.tombstones import remove
        from ..html_bits import refusal_box
        from panel.chart import _f
        if not self.units and not self.supervise:
            return self._deny(404, 'control is not armed on this panel')
        fi = int(_f(form.get('fleet')) or 0)
        name = Path(self.fleets[min(fi, len(self.fleets) - 1)]).name
        if form.get('confirm', '').strip() != name:
            return self._page(refusal_box('not cleared', f'type the fleet file name exactly: {name}'))
        tp = self._tombs_path(fi)
        try:
            tombs = json.loads(tp.read_text() or '{}') if tp.exists() else {}
        except (OSError, ValueError):
            tombs = {}
        gone = [b for b in self._orphans(fi, tombs) if remove(tp, b) is not None]
        from gridgremlin.kept_fills import cut
        cut(self.fleets[min(fi, len(self.fleets) - 1)], gone, time.time() * 1000)    # R18c
        return self._page(f'<h1>{html.escape(name)}: {len(gone)} tombstone'
                          f'{"" if len(gone) == 1 else "s"} cleared</h1>'
                          + (f'<p>{html.escape(", ".join(gone))}</p>' if gone else
                             '<p class="dim">none whose bot had left the fleet</p>')
                          + '<p><a href="/control">control</a> · <a href="/">fleet</a></p>')

    def _tombs_html(self):
        clears = ''.join(
            f"<form method='post' action='/clear-tombstones' style='margin:.3em 0'>"
            f"<input type='hidden' name='gg' value='1'><input type='hidden' name='fleet' value='{fi}'>"
            f"{html.escape(str(lb))}: {len(orph)} left from bots no longer in the fleet — type "
            f"<b>{html.escape(Path(self.fleets[fi]).name)}</b> "
            f"<input name='confirm' size='18'> <button>clear them</button></form>"
            for fi, lb, _tp, tombs in self._tombs_all()
            for orph in [self._orphans(fi, tombs)] if orph)
        trows = ''.join(
            f"<tr><td class='dim'>{html.escape(str(lb))}</td><td>{html.escape(b)}</td>"
            f"<td class='dim'>{html.escape(str(v.get('reason')))}"
            + (" · <i>no longer in the fleet</i>" if b not in self._fleet_rows(fi) else '')
            + "</td>"
            f"<td><form method='post' action='/revive' style='margin:0'>"
            f"<input type='hidden' name='gg' value='1'>"
            f"<input type='hidden' name='fleet' value='{fi}'>"
            f"<input name='confirm' size='14' placeholder='{html.escape(b, quote=True)}'>"
            f"<button>revive</button></form></td></tr>"
            for fi, lb, _tp, tombs in self._tombs_all()
            for b, v in tombs.items()) or \
            '<tr><td class="dim" colspan="4">no tombstones</td></tr>'
        return ('<h1>tombstones <span class="dim">— revival is deliberate, '
                'with the evidence (X7)</span></h1>'
                '<p class="dim">to revive a stopped bot, type its name in '
                'the box on its own row and press revive (capitals do not '
                'matter). One file per fleet; the row says whose.</p>'
                '<div class="fsec"><table><tr><th>fleet</th><th>bot</th><th>reason</th><th></th></tr>'
                + trows + '</table></div>' + clears +
                '<p class="dim">a revival takes effect at the next fleet '
                'start — the file is the truth; the process reads it at '
                'build.</p>')
