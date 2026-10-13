"""The panel's HTTP side: auth, routing, the readout cache, the rehearsal job
runner, the create/edit/close/control flows (P1, P2, §12)."""
import http.cookies
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
from gridgremlin.report import contract_tiers
from .html_bits import named, refusal_box, tidy
from .render import render
from .forms import BACK, FORM, next_step_html, other_half_html, other_side_html, rehearse_bot_form, unit_for_fleet, unit_refusal, verdict, waiting_for_restart
from gridgremlin.apply import row_botid
from .pages.rehearse import RehearsePages
from .pages.create_flow import CreateFlowPages
from .pages.fleet_admin import FleetAdminPages
from .pages.control import ControlPages
from .pages.position import PositionPages
from .pages.trade import TradePages

CACHE_TTL_S = 30.0       # the readout reads the venues; 10 s fed the rate limit


class Handler(RehearsePages, CreateFlowPages, FleetAdminPages, ControlPages, PositionPages, TradePages, http.server.BaseHTTPRequestHandler):
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
        """D64: is this fleet's venue on Mainnet. The fleet file's own
        real-money switch decides first (U79, read by the engine's helper —
        the panel never names it, D65): a fleet that may reach real
        money is treated as real money even before any readout is held — a
        restart, a direct post or a failed readout no longer lets a jump
        through unasked. Without it, the network its running fleet (else the
        readout) connected to; a fleet without the switch cannot run on
        Mainnet at all (D25). Never starts a readout."""
        from gridgremlin.config import may_reach_mainnet
        try:
            if may_reach_mainnet(json.loads(Path(fleet_p).read_text())):
                return True
        except (OSError, ValueError):
            return True                                     # unreadable: ask more, never less
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
        if not raw.get('bots') and not raw.get('agent'):
            # a just-initialised world: nothing to report on yet, and the
            # engine's own report would (rightly) refuse an empty fleet —
            # an agent's fleet has no bots by design and is read (J5)
            return {'window_hours': self.hours,
                    'generated_ms': int(time.time() * 1000),
                    'bots': {}, 'unowned': {}}
        from gridgremlin.archive import shared_readout
        shared = shared_readout(fleet, self.hours)        # U47b: the phone's, when fresh
        if shared is not None:
            Handler._cache[fleet] = (time.time(), shared)
            return shared
        from gridgremlin.durable import fleet_home
        out = subprocess.run(                              # U80: from the fleet's own copy
            [sys.executable, '-m', 'gridgremlin.report', str(Path(fleet).resolve()),
             '--hours', str(self.hours), '--json'],
            capture_output=True, text=True, timeout=120, cwd=str(fleet_home(fleet)))
        try:
            data = json.loads(out.stdout)
        except ValueError:
            # U76: the readout crashed or printed nothing. The last good
            # one stays (its age is on the page); with none, the section
            # says so with the readout's last line, and the next ask after
            # the TTL tries again — the request never dies on it.
            why = ((out.stderr or '').strip().splitlines() or
                   [f'exit {out.returncode}, nothing printed'])[-1][:300]
            print(f'panel: readout {fleet} unavailable: {why}', flush=True)
            _, held = Handler._cache.get(fleet, (0.0, None))
            if held is not None and not held.get('unavailable'):
                return held
            data = {'window_hours': self.hours,
                    'generated_ms': int(time.time() * 1000),
                    'bots': {}, 'unowned': {}, 'unavailable': why}
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
        # the cookie read by name and compared in constant time: a substring
        # test matched any cookie ending in the token, and short-circuited
        # (the 2026-10-11 review)
        jar = http.cookies.SimpleCookie()
        try:
            jar.load(self.headers.get('Cookie') or '')
        except http.cookies.CookieError:
            return False
        got = jar.get('gg')
        return bool(self.token) and got is not None and secrets.compare_digest(
            got.value.encode(), self.token.encode())

    def _fleet_ok(self, raw):
        """A `fleet` parameter names one of this panel's fleets: absent is the
        first; anything else — a word, a negative, past the end — is refused
        at the door, never read as some other fleet or a crash (the
        2026-10-11 review)."""
        if raw is None or raw == '':
            return True
        return raw.isdigit() and int(raw) < len(self.fleets)

    _drift = (0.0, '')

    @classmethod
    def _drift_notice(cls, now=None, read=None):
        """F31 (D94): the config files edited here and not in git yet, as the
        front page's one line — git asked at most once a minute."""
        now = time.time() if now is None else now
        if now - cls._drift[0] >= 60:
            from gridgremlin.drift import edited_here, notice
            rows = (read or edited_here)(Path(__file__).resolve().parents[1])
            cls._drift = (now, notice(rows))
        return cls._drift[1]

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
        if not self._fleet_ok(dict(urllib.parse.parse_qsl(
                self.path.split('?', 1)[1] if '?' in self.path else '')).get('fleet')):
            return self._deny(400, 'no such fleet')
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
            from panel.nav import PAGE_END
            from panel.reference import KEEP_JS
            body = (f'<!doctype html><meta charset="utf-8">'
                    f'<title>rehearse</title><style>{CSS}</style>{BACK}{FORM}{PAGE_END}{KEEP_JS}')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(tidy(body).encode())
            return
        if self.path.split('?')[0] == '/carry':                      # U69
            from ggdata.market import latest
            from panel.reference import KEEP_JS
            from .carry import carry_page
            from .nav import PAGE_END, side_nav
            q = dict(urllib.parse.parse_qsl(self.path.partition('?')[2]))
            body = (f'<!doctype html><meta charset="utf-8"><title>carry</title><style>{CSS}</style>'
                    f'{side_nav()}<main>{carry_page(latest(), q)}</main>{PAGE_END}{KEEP_JS}')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(tidy(body).encode())
            return
        if self.path == '/results':                                   # R24
            from panel.reference import KEEP_JS
            from .nav import PAGE_END, side_nav
            from .results import results_page
            body = (f'<!doctype html><meta charset="utf-8"><title>results</title><style>{CSS}</style>'
                    f'{side_nav()}{results_page(self._labelled())}{PAGE_END}{KEEP_JS}')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(tidy(body).encode())
            return
        base, _, query = self.path.partition('?')
        q = dict(urllib.parse.parse_qsl(query))
        view = q.get('view', 'all')
        labelled = self._labelled()
        pane = None
        if self.path != '/data' and base != '/table':
            pane = (self._pick_pane(labelled, q) if q.get('bot')
                    else self._page_pane(labelled, q) if q.get('show') else None)
        body = (json.dumps({lb: c for lb, c in labelled})
                if self.path == '/data' else
                render(labelled, table=base == '/table', view=view, pane=pane,
                       notice=self._drift_notice()))
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
        if not self._fleet_ok(form.get('fleet')):
            return self._deny(400, 'no such fleet')
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


    def _send_html(self, body):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(tidy(body).encode())


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
                + (['--windows'] if job['optimize'] else [])    # T9
                + (['--account', json.dumps(job['account'])] if job.get('account') else []))   # T11
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


    def _page(self, body):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        from panel.nav import PAGE_END
        from panel.reference import KEEP_JS
        self.wfile.write(tidy(f'<!doctype html><meta charset="utf-8">'
                              f'<title>grid-gremlin</title><style>{CSS}</style>'
                              + BACK + body + PAGE_END + KEEP_JS).encode())


    _bars = {}                       # (venue, market, symbol) -> (t, bars)


    _adapters = {}                   # (venue, market, symbol) -> (t, adapter)


