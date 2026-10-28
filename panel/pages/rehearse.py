"""The rehearsal pages (§9): the form's answer, a job's page, the account a draft rehearses against. Moved out of routes.py whole (D91 step 3): a mixin
the Handler inherits."""
from ..css import CSS
from ..reference import THEME_JS
from ..forms import BACK, verdict
from ..html_bits import refusal_box
from pathlib import Path
import json
import secrets
import time


class RehearsePages:
    def _rehearse_html(self, form, draft, bot_json, result):
        return (f'<!doctype html><meta charset="utf-8"><title>rehearse'
                f'</title><style>{CSS}</style>{THEME_JS}'
                + BACK + verdict(draft, result, typed={
                    k: form[k] for k in ('symbol', 'side', 'lower', 'upper',
                                         'rungs', 'capital', 'days')
                    if k in form}, bot_json=bot_json,
                    days=form.get('days', '7')))

    def _account_for(self, draft):
        """T11: the account a new bot of this venue would land on — the
        first fleet on that venue trading the default account, else the
        first on that venue — as its latest snapshot states it: {equity,
        mm, label}. None when no snapshot says (the verdict then says so)."""
        from gridgremlin.equity_series import snapshot_path
        venue = (draft or {}).get('venue') or 'bybit'
        picks = []
        for f, lb in zip(self.fleets, self.labels):
            try:
                raw = json.loads(Path(f).read_text())
            except (OSError, ValueError):
                continue
            venues = {r.get('venue') or 'bybit' for r in raw.get('bots') or []
                      if r.get('strategy') != 'portfolio'}
            if venue in venues:
                picks.append((raw.get('account') not in (None, 'default'), f, lb))
        for _, f, lb in sorted(picks, key=lambda p: p[0]):
            snap = snapshot_path(f)
            try:
                with open(snap, 'rb') as fh:
                    fh.seek(0, 2)
                    fh.seek(max(0, fh.tell() - 65536))
                    last = fh.read().decode(errors='replace').strip().splitlines()[-1]
                row = json.loads(last)
            except (OSError, ValueError, IndexError, TypeError):
                continue
            eq, rate = row.get('equity'), row.get('mm_rate')
            if eq and rate is not None:
                return {'equity': float(eq), 'mm': float(eq) * float(rate), 'label': lb}
        return None

    def _start_rehearsal(self, form, draft, bot_json, days):
        import threading
        now = time.time()
        for k, j in list(self._jobs.items()):            # sweep the old
            if j.get('done') and now - j['t0'] > self.JOB_KEEP:
                self._jobs.pop(k, None)
        live = sum(1 for j in self._jobs.values() if not j.get('done'))
        if live >= self.JOBS_MAX:              # one core: a queue of replays
            return None                        # starves the fleets (U23)
        job = secrets.token_hex(4)
        self._jobs[job] = {'t0': now, 'form': dict(form), 'draft': draft,
                           'account': self._account_for(draft),
                           'bot_json': bot_json, 'days': days,
                           'optimize': form.get('optimize') == '1',
                           'progress': 'starting', 'frac': 0.0,
                           'seen': now, 'cancelled': False,
                           'done': False, 'result': None}
        threading.Thread(target=self._rehearsal_runner,
                         args=(self._jobs[job],), daemon=True).start()
        return job

    def _rehearse_job_page(self, job_id):
        job = self._jobs.get(job_id)
        if job is None:
            return self._send_html(
                f'<!doctype html><meta charset="utf-8"><title>rehearse'
                f'</title><style>{CSS}</style>{THEME_JS}{BACK}'
                + refusal_box('no such rehearsal', 'it finished more than '
                              'fifteen minutes ago, or the panel was '
                              'restarted — run it again'))
        if job['done']:
            return self._send_html(self._rehearse_html(
                job['form'], job['draft'], job['bot_json'], job['result']))
        import html as _h
        job['seen'] = time.time()                     # U29: the heartbeat
        elapsed = int(time.time() - job['t0'])
        what = 'compare grid counts' if job['optimize'] else 'rehearsal'
        pct = max(0, min(100, int(round((job.get('frac') or 0.0) * 100))))
        return self._send_html(
            f'<!doctype html><meta charset="utf-8">'
            '<meta http-equiv="refresh" content="3">'
            f'<title>working</title><style>{CSS}</style>{THEME_JS}{BACK}'
            f'<h1>{what}: working <span class="dim">· {elapsed}s</span></h1>'
            f'<div class="bar" title="{pct}%"><div style="width:{pct}%">'
            '</div></div>'
            f"<p>{_h.escape(str(job['progress']))} "
            f'<span class="dim">— {pct}%</span></p>'
            '<p class="dim">this page refreshes itself every three seconds '
            'with the engine\'s own words, and the verdict appears here in '
            'their place. <b>Leaving this page stops the run</b>: if it has '
            'not been seen for ten seconds the engine is told to stop, and '
            'you start again when you can stay. Another tab is fine; it is '
            'this page that must stay open.</p>')
