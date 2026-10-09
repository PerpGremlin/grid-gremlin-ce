"""The panel's HTTP side: auth, routing, the readout cache, the rehearsal job
runner, the create/edit/close/control flows (P1, P2, §12)."""
import http.server
import os
from pathlib import Path
import urllib.parse
import html
from gridgremlin.report import card_total, money_units
import json
import re
import secrets
import subprocess
import sys
import time
from panel.chart import _f

from .css import CSS
from .reference import KEY, TRADING
from .render import contract_tiers, named, refusal_box, render, tidy
from .forms import BACK, FORM, next_step_html, other_half_html, other_side_html, rehearse_bot_form, unit_for_fleet, unit_refusal, verdict, waiting_for_restart
from gridgremlin.apply import row_botid

CACHE_TTL_S = 30.0       # the readout reads the venues; 10 s fed the rate limit


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = 'gg-panel'
    token = ''
    fleets = ()            # venue sections: one per fleet file
    units = ()             # §12: control is opt-in per launch (--units)
    supervise = False      # §13: systemd's laptop twin (--supervise)
    labels = ()
    host_ok = ''
    fleet = ''
    hours = 24.0
    _cache = {}

    def log_message(self, *a):
        pass

    _locks = {}               # U47: one readout per fleet at a time

    def _mainnet(self, fleet_p, venue):
        """D64: is this fleet's venue on Mainnet — by the network its
        running fleet (else the readout) connected to. Unknown is not
        Mainnet: the check asks more of a real-money edit, it never blocks
        a play-money one it cannot place. It reads the readout already held
        (the page being edited from drew it) and never starts one."""
        try:
            _, data = Handler._cache.get(str(fleet_p), (0.0, None))
            return bool(data) and contract_tiers(data).get(venue) == 'mainnet'
        except Exception:                                   # noqa: BLE001
            return False

    def _contract(self, fleet):
        """U47: one readout per fleet at a time. Fresh is served as it is;
        stale is served at once while ONE background refresh runs (the page
        says its age); with nothing yet, the first asker reads and the rest
        wait for that same read. Each asker started its own before, and on
        a slow venue they piled up — 18 demo readouts at once, 350 timeouts
        in an hour, the page and the rehearsal hung (2026-10-06)."""
        import threading
        t, data = Handler._cache.get(fleet, (0.0, None))
        if data is not None and time.time() - t < CACHE_TTL_S:
            return data
        lock = Handler._locks.setdefault(fleet, threading.Lock())
        if data is not None:
            if lock.acquire(blocking=False):
                def refresh():
                    try:
                        self._read_contract(fleet)
                    except Exception as e:                   # noqa: BLE001
                        print(f'panel: readout {fleet}: {e}', flush=True)
                    finally:
                        lock.release()
                threading.Thread(target=refresh, daemon=True).start()
            return data                       # stale, its age on the page
        with lock:
            t, data = Handler._cache.get(fleet, (0.0, None))
            if data is not None:              # the read we waited for
                return data
            return self._read_contract(fleet)

    def _read_contract(self, fleet):
        raw = json.loads(Path(fleet).read_text()) if Path(fleet).exists() \
            else {}
        if not raw.get('bots'):
            # a just-initialised world: nothing to report on yet, and the
            # engine's own report would (rightly) refuse an empty fleet
            return {'window_hours': self.hours,
                    'generated_ms': int(time.time() * 1000),
                    'bots': {}, 'unowned': {}}
        out = subprocess.run(
            [sys.executable, '-m', 'gridgremlin.report', fleet,
             '--hours', str(self.hours), '--json'],
            capture_output=True, text=True, timeout=120)
        data = json.loads(out.stdout)
        Handler._cache[fleet] = (time.time(), data)
        return data

    _series = {}                       # U63: per snapshot file, the tail already read

    def _labelled(self):
        return [(lb, self._with_equity(f, self._contract(f)))
                for lb, f in zip(self.labels, self.fleets)]

    def _with_equity(self, fleet, contract):
        """U63: the account's equity over the last day and week, from the
        fleet's own snapshot file, beside the readout it was made for."""
        from gridgremlin.equity_series import equity_windows, snapshot_path
        snap = snapshot_path(fleet)
        try:
            eq = equity_windows(snap, time.time(), Handler._series.setdefault(snap, {})) if snap else None
        except (OSError, ValueError):
            eq = None
        return dict(contract, equity=eq)

    def _authed(self):
        return f'gg={self.token}' in (self.headers.get('Cookie') or '')

    def _deny(self, code, why):
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(why.encode())

    def do_GET(self):
        if self.headers.get('Host', '') != self.host_ok:
            return self._deny(403, 'wrong Host')       # rebinding defence
        if self.path.startswith('/?t='):
            if secrets.compare_digest(self.path[4:], self.token):
                self.send_response(303)
                self.send_header('Set-Cookie',
                                 f'gg={self.token}; HttpOnly; SameSite=Strict')
                self.send_header('Location', '/')
                self.end_headers()
                return
            return self._deny(403, 'bad token')
        if not self._authed():
            return self._deny(401, 'open the tokened URL from the terminal')
        missing = [f for f in self.fleets if not Path(f).exists()]
        if missing and self.path.split('?')[0] == '/':
            f0 = missing[0]
            return self._page(
                f'<h1>first run — {f0} does not exist yet</h1>'
                '<p class="dim">init writes a minimal valid fleet + '
                'watchdog pair; then the create flow takes over. The '
                'engine will refuse to start until the first bot exists — '
                'nothing trades unwatched, and nothing trades empty.</p>'
                f'<form method="post" action="/init">'
                f'<input type="hidden" name="gg" value="1">'
                f'<input type="hidden" name="path" value="{f0}">'
                '<table><tr><th>name (tag)</th><th>equity floor</th>'
                '<th>max margin rate</th></tr><tr>'
                '<td><input name="tag" value="mine" size="10"></td>'
                '<td><input name="equity_min" size="8" '
                'placeholder="e.g. 500"></td>'
                '<td><input name="mm_rate_max" value="0.5" size="5"></td>'
                '</tr></table><button>write the pair</button></form>'
                '<p class="dim">equity floor: the watchdog pages if account '
                'equity falls below this. Margin rate 0.5 = alarm at 50% '
                'of maintenance margin.</p>')
        if self.path == '/key':
            return self._page(KEY)
        if self.path == '/trading':
            return self._page(TRADING)
        if self.path == '/control':
            return self._control_page()
        if self.path == '/export':
            import email.utils
            stamp = email.utils.formatdate(usegmt=True)
            body = render(self._labelled(), static=stamp)
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Disposition',
                             'attachment; filename="grid-gremlin-'
                             + time.strftime('%Y%m%d-%H%M%S') + '.html"')
            self.end_headers()
            self.wfile.write(tidy(body).encode())
            return
        if self.path == '/trade':
            return self._page(self._trade_html())             # L6 (D81)
        if self.path.startswith('/close?'):
            return self._close_page()
        if self.path.startswith('/position?'):
            return self._position_page()
        if self.path.startswith('/edit?'):
            return self._edit_page()
        if self.path == '/create' or self.path.split('?')[0] == '/setup':
            return self._setup_page()
        if self.path.startswith('/rehearse?job='):
            return self._rehearse_job_page(self.path.split('job=', 1)[1][:16])
        if self.path == '/rehearse':
            from panel.render import PAGE_END
            from panel.reference import KEEP_JS
            body = (f'<!doctype html><meta charset="utf-8">'
                    f'<title>rehearse</title><style>{CSS}</style>{BACK}{FORM}{PAGE_END}{KEEP_JS}')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(tidy(body).encode())
            return
        base, _, query = self.path.partition('?')
        view = dict(urllib.parse.parse_qsl(query)).get('view', 'all')
        body = (json.dumps({lb: c for lb, c in self._labelled()})
                if self.path == '/data' else
                render(self._labelled(), table=base == '/table', view=view))
        self.send_response(200)
        self.send_header('Content-Type',
                         'application/json' if self.path == '/data'
                         else 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(tidy(body).encode())


    def do_POST(self):
        if self.headers.get('Host', '') != self.host_ok:
            return self._deny(403, 'wrong Host')
        if not self._authed():
            return self._deny(401, 'open the tokened URL from the terminal')
        origin = self.headers.get('Origin', '')
        if origin and origin != f'http://{self.host_ok}':
            return self._deny(403, 'wrong Origin')     # cross-site write
        try:                                     # a negative length read
            n = int(self.headers.get('Content-Length') or 0)   # to EOF and
        except ValueError:                                     # hung (audit
            n = 0                                              # 2026-10-05)
        raw = self.rfile.read(max(0, min(n, 16384))).decode(errors='replace')
        form = dict(urllib.parse.parse_qsl(raw))
        if form.pop('gg', None) != '1':
            return self._deny(403, 'missing form token')
        if self.path in ('/create', '/apply'):
            return self._create_flow(form, apply=self.path == '/apply')
        if self.path == '/setup':
            return self._setup_post(form)
        if self.path == '/chart':
            return self._chart_post(form)
        if self.path == '/whatif':
            return self._whatif_post(form)
        if self.path in ('/unit', '/revive'):
            return self._control_act(form, self.path)
        if self.path == '/close':
            return self._close_act(form)
        if self.path == '/trade':
            return self._trade_post(form)
        if self.path == '/init':
            from panel.create import init_pair
            try:
                # only a fleet file this panel was started on: init wrote
                # wherever the form named (audit 2026-10-05)
                want = Path(form.get('path', '')).resolve()
                if want not in {Path(f).resolve() for f in self.fleets}:
                    raise ValueError('init writes only the fleet file this '
                                     'panel was started on')
                wp = init_pair(str(want), form.get('tag', 'mine'),
                               _f(form.get('equity_min')),
                               _f(form.get('mm_rate_max')) or 0.5)
            except Exception as e:                          # noqa: BLE001
                return self._page(f'<h1 class="neg">init refused</h1>'
                                  f'<p class="neg">{html.escape(str(e))}</p>')
            return self._page(f'<h1>written</h1><p>fleet + watcher pair '
                              f'created ({wp.name} beside it). '
                              '<a href="/create">create your first bot '
                              '&rarr;</a></p>')
        if self.path != '/rehearse':
            return self._deny(404, 'no such action')
        bot_json = form.get('bot_json')
        if bot_json:                   # U14: the bot exactly as configured
            try:
                draft = json.loads(bot_json)
            except ValueError:
                draft = {}
            draft = {k: v for k, v in draft.items() if not k.startswith('_')}
        else:
            draft = {'market_type': 'linear', 'venue': 'bybit',
                     'symbol': form.get('symbol', '').upper(),
                     'side': form.get('side', 'long'),
                     'capital': _f(form.get('capital')),
                     'lower': _f(form.get('lower')),
                     'upper': _f(form.get('upper')),
                     'rungs': int(_f(form.get('rungs')) or 0)}
        days = _f(form.get('days'))
        if not days or days <= 0:
            result = {'refused': '"days": how many days of history to '
                                 'replay? Type a number, like 7'}
        elif days > 90:
            result = {'refused': '"days": 90 at most — a longer replay '
                                 'takes minutes of candles to fetch'}
        else:
            # U23/T9: compare grid counts always reads 14 days and splits them —
            # about six minutes of replays on the box beside the fleets, shown live (U26);
            # the days box is the rehearsal's. The terminal has no limit.
            # U26: the rehearsal is a JOB — the page answers at once and
            # refreshes itself with the engine's own progress words until
            # the verdict is in (a spinner that spins whether or not
            # anything happens would have lied for five minutes, 10-04)
            job = self._start_rehearsal(form, draft, bot_json, days)
            if job is None:
                result = {'refused': f'{self.JOBS_MAX} rehearsals are already '
                                     'running on this one-core box — wait for '
                                     'one to finish, then press again'}
                self._send_html(self._rehearse_html(form, draft, bot_json,
                                                    result))
                return
            self.send_response(303)
            self.send_header('Location', f'/rehearse?job={job}')
            self.end_headers()
            return
        self._send_html(self._rehearse_html(form, draft, bot_json, result))

    _jobs = {}                       # job id -> dict (class-wide, in memory)
    JOBS_MAX = 2                     # rehearsals at once (audit 2026-10-05)
    JOB_KEEP = 900.0                 # a finished verdict stays 15 minutes
    LEAVE_SECONDS = 12.0             # U29: three missed refreshes = gone

    def _rehearse_html(self, form, draft, bot_json, result):
        return (f'<!doctype html><meta charset="utf-8"><title>rehearse'
                f'</title><style>{CSS}</style>'
                + BACK + verdict(draft, result, typed={
                    k: form[k] for k in ('symbol', 'side', 'lower', 'upper',
                                         'rungs', 'capital', 'days')
                    if k in form}, bot_json=bot_json,
                    days=form.get('days', '7')))

    def _send_html(self, body):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(tidy(body).encode())

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
                           'bot_json': bot_json, 'days': days,
                           'optimize': form.get('optimize') == '1',
                           'progress': 'starting', 'frac': 0.0,
                           'seen': now, 'cancelled': False,
                           'done': False, 'result': None}
        threading.Thread(target=self._rehearsal_runner,
                         args=(self._jobs[job],), daemon=True).start()
        return job

    @staticmethod
    def _rehearsal_runner(job):
        """Runs the engine's CLI as a subprocess under the fleets' priority
        (U23), reads its progress words from stderr as they come, keeps
        the verdict. Specs swap this function for a fake."""
        # `nice` as the command, not preexec_fn: preexec_fn is unsafe in a
        # threaded server (audit 2026-10-05)
        args = (['nice', '-n', '10', sys.executable, '-m',
                 'gridgremlin.backtest_cli', '--draft', '--days',
                 f"{job['days']:g}"]
                + (['--windows'] if job['optimize'] else []))   # T9
        try:
            proc = subprocess.Popen(args, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)
            proc.stdin.write(json.dumps(job['draft']))
            proc.stdin.close()
            import threading
            threading.Thread(target=Handler._leave_watch,
                             args=(job, proc), daemon=True).start()
            # stdout drains beside stderr: reading it only after stderr
            # closed could deadlock on a verdict over 64 KB
            got = []
            reader = threading.Thread(target=lambda: got.append(
                proc.stdout.read()), daemon=True)
            reader.start()
            last = 'no reason given'
            for line in proc.stderr:                     # progress, live
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    p = msg.get('progress')
                except (ValueError, AttributeError):
                    msg, p = {}, None
                if p:
                    job['progress'] = p
                    if msg.get('frac') is not None:
                        job['frac'] = float(msg['frac'])
                else:
                    last = line
            try:
                reader.join(timeout=300)
                out = got[0] if got else ''
                proc.wait(timeout=300)
            except subprocess.TimeoutExpired:
                proc.kill()
                job['result'] = {'refused': 'the rehearsal took longer than '
                                            'five minutes — try fewer days'}
                return
            if job.get('cancelled'):
                job['result'] = {'refused': 'stopped — you left the page for '
                                            'more than ten seconds, so the '
                                            'run was ended; run it again when '
                                            'you can stay'}
                return
            try:
                job['result'] = (json.loads(out) if out.strip() else
                                 {'refused': f'the rehearsal stopped: {last}'})
            except ValueError:
                job['result'] = {'refused': 'the rehearsal answered '
                                            'something unreadable — try again'}
        except OSError as e:
            job['result'] = {'refused': f'the rehearsal could not start: {e}'}
        finally:
            job['done'] = True

    @staticmethod
    def _leave_watch(job, proc, clock=time.time, sleep=time.sleep):
        """U29 (owner: "when the page does go back, it kills the function"):
        the page's refreshes are its heartbeat; three missed ones and the
        subprocess is ended. Returns True when it ended the run."""
        while proc.poll() is None:
            if clock() - job['seen'] > Handler.LEAVE_SECONDS:
                job['cancelled'] = True
                try:
                    proc.kill()
                except OSError:
                    pass
                return True
            sleep(2.0)
        return False

    def _rehearse_job_page(self, job_id):
        job = self._jobs.get(job_id)
        if job is None:
            return self._send_html(
                f'<!doctype html><meta charset="utf-8"><title>rehearse'
                f'</title><style>{CSS}</style>{BACK}'
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
            f'<title>working</title><style>{CSS}</style>{BACK}'
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


    def _page(self, body):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        from panel.render import PAGE_END
        from panel.reference import KEEP_JS
        self.wfile.write(tidy(f'<!doctype html><meta charset="utf-8">'
                              f'<title>grid-gremlin</title><style>{CSS}</style>'
                              + BACK + body + PAGE_END + KEEP_JS).encode())

    def _create_flow(self, form, apply=False):
        from panel.create import (atomic_write, dry_ladder, dump_config,
                                  merge_proposal, public_adapter,
                                  public_mark, unified_diff, validate_whole)
        fi = int(_f(form.get('fleet')) or 0)
        fleet_p = Path(self.fleets[min(fi, len(self.fleets) - 1)])
        fleet_raw = json.loads(fleet_p.read_text())
        wd_p = Path(fleet_raw['watchdog'])
        wd_raw = json.loads(wd_p.read_text())
        mode = form.get('mode', 'create')
        if apply:
            proposal = json.loads(form.get('proposal', '{}'))
            mode = proposal.get('mode', 'create')
        elif mode == 'remove':
            proposal = {'mode': 'remove', 'orig': form.get('orig', '')}
        elif form.get('bot_json'):                # §11: the setup form's row
            proposal = {'mode': mode, 'orig': form.get('orig', ''),
                        'bot': json.loads(form['bot_json']),
                        'watchdog': {'max': _f(form.get('ceiling'))}}
            if form.get('pair'):                         # D54: the other half
                proposal['pair'] = json.loads(form['pair'])
        else:
            return self._refused(form, 'refused', 'nothing to create — '
                                 'start from "set up a bot"')
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
                    q0 = adapter.round_qty(vbot['base_order_size'] / m0)
                    if q0 <= 0 or not adapter.meets_minimum(q0, m0):
                        raise _CE(
                            f"the first order ({vbot['base_order_size']:g}) "
                            "is smaller than this market's minimum order "
                            f"({adapter.min_notional:g}, or "
                            f"{adapter.min_qty:g} coins) — raise the "
                            'investment, use fewer add-on orders, or raise the '
                            'leverage')
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
            return self._page(
                f'<h1>{botid}: written</h1><p>bot and watcher landed '
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
            ladder_html = (f'<p class="dim">the ladder at mark '
                           f'{mark:,.6g} (dry-run — nothing placed)</p>'
                           f'<table><tr><th>side</th><th>price</th>'
                           f'<th>qty</th></tr>{lrows}</table>')
        diffs = (unified_diff(fleet_p.read_text(), new_fleet, fleet_p.name)
                 + unified_diff(wd_p.read_text(), new_wd, wd_p.name))
        pj = html.escape(json.dumps(proposal), quote=True)
        say = ''
        if proposal.get('pair'):                           # D54
            say = ('<p class="dim">the long half of a reversal grid, below '
                   f"the mid {float(proposal['pair']['mid']):,.6g}; the "
                   'short half above it follows once this one is written '
                   '(D54).</p>')
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
                Handler._adapters[self._market_key(vbot)] = (time.time(),
                                                             adapter)
                picture += whatif_section(
                    vbot, adapter, mark, json.dumps(proposal['bot']), fi)
            except Exception as e:                          # noqa: BLE001
                picture += (f'<p class="dim">no what-if: '
                            f'{_html.escape(str(e))}</p>')
            say += (f'<h1 class="dim">in plain words</h1><p class="say">'
                    f'{_html.escape(sentence(vbot, mark))}</p>' + picture)
        if mode in ('create', 'edit'):
            say += ('<form method="post" action="/setup">'
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
        verb = {'create': 'create this bot', 'edit': 'apply the change',
                'remove': 'remove this bot'}[mode]
        # U17: the apply box sits right under the summary; the file diff
        # and the dry-run orders fold away for whoever wants them
        return self._page(
            f'<h1>{botid} — {mode}: gates passed</h1>' + say +
            f'<form method="post" action="/apply" class="apply">'
            f'<input type="hidden" name="gg" value="1">'
            f'<input type="hidden" name="fleet" value="{fi}">'
            f'<input type="hidden" name="proposal" value="{pj}">'
            f'<b>To {verb}</b>, type its name <code>{botid}</code> here: '
            f'<input name="confirm" size="16" placeholder="{botid}"> '
            + ''.join(f'<br><b class="neg">Mainnet:</b> type the new {k} '
                      f'(<code>{n:g}</code>) again: <input name="retype_{k}" '
                      'size="12">' for k, _, n in jumps)
            + f'<button>{verb}</button></form>'
            '<p class="dim">this writes the fleet file. A running fleet '
            'takes changed terms within seconds; a new bot, a removed one '
            'or a changed range waits for a restart (F12).</p>'
            '<details><summary>the change to the file</summary>'
            f'<pre class="dim">{html.escape(diffs)}</pre></details>'
            '<details><summary>the orders it would place</summary>'
            + ladder_html + '</details>')


    def _fleet_labels(self):
        return [Path(f).name for f in self.fleets]

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
        """A fleet file trades one venue: its first row says which."""
        try:
            bots = json.loads(Path(self.fleets[fi]).read_text()).get('bots')
        except (OSError, ValueError):
            bots = None
        return (bots[0].get('venue', 'bybit') if bots else 'bybit')

    def _refused(self, form, title, why):
        """A refusal returns to the form it came from, values intact."""
        fi = int(_f(form.get('fleet')) or 0)
        extra = ''
        if 'already in this fleet' in str(why):
            # the commonest refusal, said as what to do next (U11)
            botid = str(why).split(':', 1)[0]
            extra = ('<br>You already have a bot for this coin and '
                     'direction in this account, and there can be only '
                     f'one. <a href="/edit?fleet={fi}&bot={botid}">Open '
                     'that bot to change it</a>, or pick another coin or '
                     'the other direction below.')
        note = refusal_box(title, why, extra)
        if form.get('bot_json'):
            from panel.setup import advanced_page, form_from_bot
            bot = json.loads(form['bot_json'])
            vals = dict(form_from_bot(bot), ceiling=form.get('ceiling', ''))
            return self._page(advanced_page(
                bot.get('strategy', 'grid'), vals, self._fleet_labels(),
                fi, alert=note, edit=form.get('orig') or None))
        return self._page(note + '<p><a href="/setup">set up a bot</a> · '
                          '<a href="/">fleet</a></p>')

    def _setup_page(self):
        from panel.setup import advanced_page, form_from_bot, quick_page
        q = (dict(urllib.parse.parse_qsl(self.path.split('?', 1)[1]))
             if '?' in self.path else {})
        fi = min(int(_f(q.get('fleet')) or 0), len(self.fleets) - 1)
        labels = self._fleet_labels()
        if q.get('copy'):
            from gridgremlin.apply import make_botid as _mb
            bots = json.loads(Path(self.fleets[fi]).read_text()).get(
                'bots', [])
            src = next((b for b in bots if _mb(
                b['market_type'], b['symbol'], b['side']) == q['copy']),
                None)
            if src is None:
                return self._deny(404, f"{q['copy']}: not in this fleet")
            vals = form_from_bot(src)
            vals['symbol'] = ''        # one bot per market and side (I2)
            return self._page(advanced_page(
                src.get('strategy', 'grid'), vals, labels, fi,
                note=f'<p class="dim">copied from {q["copy"]}: every '
                     'setting is carried over — choose the coin, and '
                     'check the prices, which belong to the old one.</p>'))
        if q.get('adv') in ('grid', 'martingale'):
            return self._page(advanced_page(q['adv'], {}, labels, fi,
                                            symbols=self._symbols(fi)))
        return self._page(quick_page(labels, fi, symbols=self._symbols(fi)))

    _bars = {}                       # (venue, market, symbol) -> (t, bars)

    def _bars_for(self, cfg):
        """Public candles, kept five minutes: a drag redraws, it does not
        refetch a month of history."""
        from panel.create import public_bars
        key = (cfg.get('venue'), cfg.get('market_type'), cfg.get('symbol'))
        hit = Handler._bars.get(key)
        if hit and time.time() - hit[0] < 300:
            return hit[1]
        bars = public_bars(cfg)
        Handler._bars[key] = (time.time(), bars)
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

    _adapters = {}                   # (venue, market, symbol) -> (t, adapter)

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
            hit = Handler._adapters.get(key)
            if not hit or time.time() - hit[0] >= 300:
                hit = Handler._adapters[key] = (time.time(),
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
        self.wfile.write(tidy(body).encode())

    def _setup_post(self, form):
        from panel.create import public_mark
        from panel.setup import (advanced_page, bot_from_form,
                                 form_from_bot, quick_bot)
        fi = min(int(_f(form.get('fleet')) or 0), len(self.fleets) - 1)
        venue = self._fleet_venue(fi)
        labels = self._fleet_labels()
        how = form.get('how')
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
                from panel.setup import resolve_size
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
        fi = int(q.get('fleet') or 0)
        botid = q.get('bot', '')
        fleet_raw = json.loads(Path(self.fleets[fi]).read_text())
        bot = next((b for b in fleet_raw.get('bots', [])
                    if row_botid(b) == botid), None)
        if bot is None:
            return self._deny(404, f'{botid}: not in this fleet')
        if bot.get('strategy') == 'portfolio' and q.get('mode') != 'remove':
            return self._page(
                f'<h1>{botid}</h1><p class="dim">a portfolio row (D78) is edited in '
                'the fleet file by hand — its assets, hedges, clock and risk are the '
                'row\'s own terms; the setup form knows one market at a time. '
                f'<a href="/edit?fleet={fi}&bot={botid}&mode=remove">remove</a> is '
                'here.</p><p><a href="/">&larr; fleet</a></p>')
        if q.get('mode') == 'remove':
            return self._page(
                f'<h1>remove {botid}</h1><p class="dim">the bot and its '
                'watchdog line leave together; the remaining fleet must '
                'still validate (F1). The running fleet is untouched until '
                'restarted (§11).</p>'
                f'<form method="post" action="/create">'
                f'<input type="hidden" name="gg" value="1">'
                f'<input type="hidden" name="mode" value="remove">'
                f'<input type="hidden" name="fleet" value="{fi}">'
                f'<input type="hidden" name="orig" value="{botid}">'
                f'<button>run the gates</button></form>'
                f'<p><a href="/">&larr; fleet</a></p>')
        from panel.setup import advanced_page, form_from_bot
        w = json.loads(Path(fleet_raw['watchdog']).read_text())
        wmax = (w.get('positions', {}).get(botid) or {}).get('max', '')
        vals = dict(form_from_bot(bot), ceiling=wmax)
        return self._page(advanced_page(
            bot.get('strategy', 'grid'), vals, self._fleet_labels(), fi,
            edit=botid))

    def _control_page(self):
        if not self.units and not self.supervise:
            return self._deny(404, 'control is not armed on this panel '
                                   '(--units or --supervise) — §12/§13')
        if self.supervise:
            from panel import supervise as sup
            rows = []
            for f in self.fleets:
                st, pid = sup.status(f)
                cls = 'pos' if st == 'running' else 'neg'
                rows.append(f'<p>engine <b>{Path(f).name}</b>: '
                            f'<span class="{cls}">{st}'
                            + (f' (pid {pid})' if pid else '')
                            + '</span></p>')
            names = ', '.join(Path(f).name for f in self.fleets)
            return self._page(f"""<h1>control <span class="dim">— processes
and files, never the venue (§13, supervised)</span></h1>
{''.join(rows)}
<form method="post" action="/unit">
<input type="hidden" name="gg" value="1">
<select name="action"><option>start</option><option>stop</option>
<option>restart</option></select>
type the fleet file name to confirm ({names}):
<input name="confirm" size="22"><button>do it</button></form>
<p class="dim">the engine is a DETACHED child: closing the panel does
nothing to it. stop PARKS, never flattens (E3). no auto-restart, ever
(§6).</p>
{self._tombs_html()}<p><a href="/">&larr; fleet</a></p>""")
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
                parts = ([f'new: {", ".join(new)}'] if new else []) + \
                        ([f'removed: {", ".join(gone)}'] if gone else [])
                if parts:
                    waits = (' <span class="dim">— waiting for a restart: '
                             + '; '.join(parts) + '</span>')
            rows.append(f'<p>unit <b>{u}</b>: <span class="{cls}">{state}'
                        f'</span>{waits}</p>')
        return self._page(f"""<h1>control <span class="dim">— processes and
files, never the venue (§12)</span></h1>
{''.join(rows)}
<form method="post" action="/unit">
<input type="hidden" name="gg" value="1">
<select name="action"><option>restart</option><option>stop</option>
<option>start</option></select>
type a unit name to confirm — or several, separated by spaces or commas:
<input name="confirm" size="44">
<button>do it</button></form>
<p class="dim">one exception to "never the venue": a STOPPED bot's card
offers <b>close position</b>, which asks the engine to close what that bot
left open (X15).</p>
<p class="dim">stop PARKS, never flattens: positions and their
venue-resting orders survive a stopped engine (E3) — but stops go
unevaluated and nothing replenishes until start. restart enacts any
written config (§11).</p>
{self._tombs_html()}<p><a href="/">&larr; fleet</a></p>""")

    def _run_close(self, fi, botid, dry):
        """X15: the engine's own close command, as a subprocess — the keys
        are its, never this process's (the readout's arrangement)."""
        fleet = self.fleets[min(fi, len(self.fleets) - 1)]
        try:
            out = subprocess.run(
                [sys.executable, '-m', 'gridgremlin.close', fleet, botid]
                + (['--dry'] if dry else []),
                capture_output=True, text=True, timeout=60)
            last = (out.stderr.strip().splitlines() or ['no reason given'])[-1]
            return (json.loads(out.stdout) if out.stdout.strip()
                    else {'refused': f'the close command stopped: {last}'})
        except subprocess.TimeoutExpired:
            return {'refused': 'the exchange did not answer within a minute '
                               '— look at it directly before trying again'}
        except ValueError:
            return {'refused': 'the close command answered something '
                               'unreadable — look at the exchange directly'}

    def _position_page(self):
        """U56: one position, one page."""
        from panel.render import position_page
        q = dict(urllib.parse.parse_qsl(self.path.split('?', 1)[1]))
        fi = min(int(_f(q.get('fleet')) or 0), len(self.fleets) - 1)
        botid = q.get('bot', '')
        contract = self._contract(self.fleets[fi])
        belief = ((contract.get('watchdog') or {}).get('belief') or {}).get('bots', {})
        if botid not in (contract.get('bots') or {}) and botid not in belief:
            return self._deny(404, f'{botid}: not in this fleet')
        # U65: the price from the fleet's own snapshots, the fills from the kept ledger
        from gridgremlin.durable import fleet_tag, logs_dir
        from gridgremlin.equity_series import bot_fills, price_windows, snapshot_path
        snap = snapshot_path(self.fleets[fi])
        now = time.time()
        try:
            prices = price_windows(snap, botid, now, Handler._series.setdefault(snap, {})) if snap else None
        except (OSError, ValueError):
            prices = None
        fills = bot_fills(logs_dir(self.fleets[fi]) / 'fills' / f'{fleet_tag(self.fleets[fi])}.json',
                          botid, int((now - 7 * 86400) * 1000))
        return self._page(position_page(fi, self.labels[fi], botid, contract, belief, prices, fills))

    def _trades_of(self, fi):
        """One fleet's trades file and validated rows, for the trade page."""
        from gridgremlin.trades import fleet_rows, trades_path
        f = self.fleets[min(fi, len(self.fleets) - 1)]
        fleet, rows = fleet_rows(f)
        return f, fleet, rows, trades_path(f, json.loads(Path(f).read_text()))

    def _trade_html(self, msg='', typed=None):
        """L6: the form, then every fleet's open trades."""
        from gridgremlin.trades import TradeError, _botid, load_trades
        from panel.trade_page import open_trades_html, trade_form
        listed = []
        for fi, lb in enumerate(self.labels):
            try:
                _f0, _fl, _rows, path = self._trades_of(fi)
                trades, _ = load_trades(path)
            except (TradeError, OSError, ValueError, KeyError):
                trades = []
            listed.append((fi, lb, [(_botid(t), t) for t in trades]))
        return trade_form(self.labels, msg, typed) + open_trades_html(listed)

    def _trade_post(self, form):
        """L6: open a trade through the bot validator, or clear an ended one."""
        from gridgremlin.config import ConfigError
        from gridgremlin.trade import build_row
        from gridgremlin.trades import TradeError, add_trade, clear_trade
        fi = int(_f(form.get('fleet')) or 0)
        try:
            f, _fleet, rows, path = self._trades_of(fi)
            if form.get('action') == 'clear':
                botid = form.get('confirm', '').strip()
                from gridgremlin.tombstones import path_for
                gone = clear_trade(path, botid, path_for(f, json.loads(Path(f).read_text())))
                if gone is None:
                    raise TradeError(f'{botid or "nothing"}: not a trade in this account\'s file — '
                                     'type its name exactly')
                return self._page(f'<h1>{html.escape(botid)}: cleared</h1>'
                                  '<p><a href="/trade">trades</a></p>')
            opts = {k: form[k] for k in ('capital', 'tp', 'leverage', 'stop', 'trail') if form.get(k, '').strip()}
            if form.get('trail_from', '').strip():
                opts['trail-from'] = form['trail_from']
            if form.get('maker'):
                opts['maker'] = True
            botid = add_trade(path, rows, build_row(form.get('side', ''), form.get('symbol', ''), opts))
        except (ConfigError, TradeError, ValueError, OSError) as e:
            return self._page(self._trade_html(refusal_box('trade refused', html.escape(str(e))), form))
        Handler._cache.pop(self.fleets[min(fi, len(self.fleets) - 1)], None)   # the next readout shows it
        return self._page(f'<h1>{html.escape(botid)}: queued</h1><p class="say">The fleet '
                          f'{html.escape(self.labels[min(fi, len(self.labels) - 1)])} opens it within a '
                          'cycle; its card appears with the next readout.</p>'
                          '<p><a href="/">back to your bots</a> <a href="/trade">trades</a></p>')

    def _close_page(self):
        import html as _html
        if not self.units and not self.supervise:
            return self._deny(404, 'control is not armed on this panel '
                                   '(--units or --supervise) — §12/§13')
        q = dict(urllib.parse.parse_qsl(self.path.split('?', 1)[1]))
        fi, botid = int(_f(q.get('fleet')) or 0), q.get('bot', '')
        got = self._run_close(fi, botid, dry=True)
        b = _html.escape(botid)
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
            f'type the bot\'s name to close it: <input name="confirm" '
            f'size="18" placeholder="{b}"> '
            '<button class="danger">close at market</button></form>')

    def _close_act(self, form):
        import html as _html
        if not self.units and not self.supervise:
            return self._deny(404, 'control is not armed on this panel')
        botid = form.get('bot', '')
        if not botid or not named(form.get('confirm'), botid):
            return self._page(refusal_box(
                'not closed', f'the typed name must be exactly {botid} — '
                              'a click is not a decision'))
        got = self._run_close(int(_f(form.get('fleet')) or 0), botid,
                              dry=False)
        if 'refused' in got:
            return self._page(refusal_box('not closed', got['refused']))
        left = got.get('left') or 0.0
        return self._page(
            f'<h1>{_html.escape(botid)}: closed {got["closed"]:.10g}</h1>'
            + (f'<p class="neg">{left:.10g} is STILL OPEN — the market order '
               'did not fill in full; look at the exchange.</p>' if left > 0
               else '<p>the exchange now shows no position on this bot\'s '
                    'side of this market.</p>'))

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
                '<table><tr><th>fleet</th><th>bot</th><th>reason</th><th></th></tr>'
                + trows + '</table>'
                '<p class="dim">a revival takes effect at the next fleet '
                'start — the file is the truth; the process reads it at '
                'build.</p>')

    def _control_act(self, form, path):
        if not self.units and not self.supervise:
            return self._deny(404, 'control is not armed on this panel')
        if path == '/unit' and self.supervise:
            from panel import supervise as sup
            byname = {Path(f).name: f for f in self.fleets}
            fleet = byname.get(form.get('confirm', ''))
            if fleet is None:
                return self._page('<h1 class="neg">not done</h1><p>type '
                                  'the fleet file name exactly (§13). '
                                  '<a href="/control">back</a></p>')
            act = form.get('action', '')
            if act not in ('start', 'stop', 'restart'):
                return self._deny(403, 'unknown action')
            notes = []
            if act in ('stop', 'restart'):
                notes.append(sup.stop(fleet))
            if act in ('start', 'restart'):
                notes.append(sup.start(fleet))
            return self._page(f'<h1>{Path(fleet).name}: {act}</h1><p>'
                              + '<br>'.join(notes)
                              + '</p><p><a href="/control">control</a> · '
                                '<a href="/">fleet</a></p>')
        if path == '/unit':
            # U43 (owner 2026-10-05: "can i restart both fleets at the same
            # time from the panel by typing both lines?"): several names,
            # each the decision; ALL must be units or nothing is done
            typed = [u for u in re.split(r'[\s,]+', form.get('confirm', ''))
                     if u]
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
                return self._page(f'<h1>{html.escape(unit)}: {act}</h1>'
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
                    f'<h1 class="neg">{unit}: not started</h1><p>it is '
                    'already running, and <b>start</b> does nothing to a '
                    'running unit. To load a new or removed bot, or a '
                    'changed range, grid count or ladder, choose '
                    '<b>restart</b> and type the name again. '
                    '<a href="/control">back</a></p>')
            r = subprocess.run(['systemctl', '--user', act, unit],
                               capture_output=True, text=True, timeout=60)
            note = html.escape(r.stderr.strip() or f'{act}: done')
            return self._page(f'<h1>{unit}: {act}</h1><p>{note}</p>'
                              '<p><a href="/control">control</a> · '
                              '<a href="/">fleet</a></p>')
        # /revive — under the engine's own lock (X7, audit 2026-10-05)
        from gridgremlin.tombstones import remove as tomb_remove
        tp = self._tombs_path(int(_f(form.get('fleet')) or 0))
        try:
            tombs = json.loads(tp.read_text() or '{}') if tp.exists() else {}
        except (OSError, ValueError):
            tombs = {}
        botid = next((t for t in tombs if named(form.get('confirm'), t)),
                     form.get('confirm', ''))
        gone = tomb_remove(tp, botid) if botid in tombs else None
        if gone is None:
            return self._page('<h1 class="neg">not revived</h1><p>type the '
                              'botid exactly as the tombstone names it. '
                              '<a href="/control">back</a></p>')
        return self._page(f'<h1>{html.escape(botid)}: tombstone removed</h1>'
                          f'<p class="dim">was: {html.escape(str(gone.get("reason")))}</p>'
                          '<p>takes effect at the next fleet start (X7) — '
                          'restart from <a href="/control">control</a> when '
                          'ready.</p>')
