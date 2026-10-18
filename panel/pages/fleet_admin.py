"""A bot's edit page and the tombstones (X7b). Moved out of routes.py whole (D91 step 3): a mixin
the Handler inherits."""
from gridgremlin.apply import row_botid
from ..html_bits import qarg
from pathlib import Path
import html
import json
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
            from panel.lever import lever_form                      # D143
            return (lever_form(fi, botid, bot)
                    + '<p class="dim">its coins, hedges, clock and risk: the fleet file, by hand (D78). '
                    f'<a href="/edit?fleet={fi}&amp;bot={qarg(botid)}&amp;mode=remove">remove</a> is '
                    'here.</p>')
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

    def _tombs_html(self):
        trows = ''.join(
            f"<tr><td class='dim'>{html.escape(str(lb))}</td><td>{html.escape(b)}</td>"
            f"<td class='dim'>{html.escape(str(v.get('reason')))}</td>"
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
                + trows + '</table></div>'
                '<p class="dim">a revival takes effect at the next fleet '
                'start — the file is the truth; the process reads it at '
                'build.</p>')
