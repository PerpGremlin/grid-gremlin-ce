"""F35–F38 (D155): the daily box hygiene check — strays, leaks, the box's
memory, and where each is said. /proc and the cgroup tree are fixtures."""
import json
import tempfile
from pathlib import Path

from gridgremlin import hygiene as hy

ROOT = Path(__file__).resolve().parents[1]
MIB = 1 << 20
DAY = 86400
SESSION = '/user.slice/user-1000.slice/session-5.scope'
PANEL = '/user.slice/user-1000.slice/user@1000.service/app.slice/gg-panel.service'


def _box(procs, total_kb=2_000_000, avail_kb=1_000_000, memory=None):
    """A fake /proc and cgroup tree: procs = [(pid, ppid, comm, cgroup, kthread)],
    a sixth field the command line when it is not `comm -c loop`."""
    d = Path(tempfile.mkdtemp())
    proc, cg = d / 'proc', d / 'cgroup'
    for pid, ppid, comm, path, kthread, *cmd in procs:
        p = proc / str(pid)
        p.mkdir(parents=True)
        flags = hy.PF_KTHREAD if kthread else 4194304
        p.joinpath('stat').write_text(f'{pid} ({comm}) S {ppid} {pid} {pid} 0 -1 {flags} 0 0')
        p.joinpath('cgroup').write_text(f'0::{path}\n')
        line = cmd[0] if cmd else comm + ' -c loop'
        p.joinpath('cmdline').write_bytes(b'' if kthread else line.encode().replace(b' ', b'\0'))
    proc.joinpath('meminfo').write_text(f'MemTotal: {total_kb} kB\nMemFree: 1 kB\n'
                                        f'MemAvailable: {avail_kb} kB\n')
    for path, n in (memory or {}).items():
        (cg / path.lstrip('/')).mkdir(parents=True, exist_ok=True)
        (cg / path.lstrip('/') / 'memory.current').write_text(f'{n}\n')
    return str(proc), str(cg)


BOX = [(1, 0, 'systemd', '/init.scope', False),
       (2, 0, 'kthreadd', '/', True),
       (40, 2, 'kworker/0:1', '/', True),
       (900, 1, 'systemd', '/user.slice/user-1000.slice/user@1000.service/init.scope', False),
       (901, 900, 'python3', PANEL, False),
       (950, 1, 'sshd', '/system.slice/ssh.service', False),
       (1200, 1, 'python3', SESSION, False),                     # reparented loop from a login
       (1300, 1, 'sleep', '/user.slice/user-1000.slice/user@1000.service/app.slice/run-x.scope', False),
       (7000, 1, 'python3', '/user.slice/user-1000.slice/user@1000.service/app.slice/'
                            'grid-gremlin3-hygiene.service', False)]


def spec_F35_a_session_scope_process_is_a_stray_a_service_process_is_known():
    proc, _ = _box(BOX)
    s = hy.strays(hy.read_procs(proc), me=7000)
    assert [(x['pid'], x['unit']) for x in s] == [(1200, 'session-5.scope'), (1300, 'run-x.scope')]
    assert s[0]['cmd'] == 'python3 -c loop'
    # kernel threads, pid 1, each user's manager, a service, the check itself: none listed
    assert not {1, 2, 40, 900, 901, 950, 7000} & {x['pid'] for x in s}
    assert hy.is_known('gg-panel.service') and hy.is_known('init.scope')
    assert not hy.is_known('session-5.scope') and not hy.is_known(None)
    assert hy.unit_of(PANEL)[0] == 'gg-panel.service' and hy.unit_of('/user.slice') == (None, None)


def spec_F35_sabotage_were_any_unit_known_the_session_loop_would_pass_unseen():
    proc, _ = _box(BOX)
    procs = hy.read_procs(proc)
    real = hy.is_known
    try:
        hy.is_known = lambda unit: bool(unit)           # the guard loosened
        assert [x['pid'] for x in hy.strays(procs, me=7000)] == []
    finally:
        hy.is_known = real
    assert [x['pid'] for x in hy.strays(procs, me=7000)] == [1200, 1300]


def spec_F35_run_by_hand_the_check_leaves_out_its_own_login_chain():
    proc, _ = _box(BOX + [(5000, 1, 'bash', SESSION, False), (5001, 5000, 'python3', SESSION, False)])
    pids = [x['pid'] for x in hy.strays(hy.read_procs(proc), me=5001)]
    assert 5000 not in pids and 5001 not in pids and 1200 in pids


TUNNEL = '/user.slice/user-1000.slice/session-7.scope'     # a standing `ssh -N` login
TYPED = '/user.slice/user-1000.slice/session-9.scope'      # an interactive ssh run


def spec_F35_an_ssh_logins_daemon_processes_are_plumbing_not_strays():
    # the owner, 2026-10-30: the workstation's panel tunnel showed as two
    # strays every night — `sshd: user [priv]` and `sshd: user@notty`
    tunnel = [(6000, 950, 'sshd', TUNNEL, False, 'sshd: user [priv]'),
              (6001, 6000, 'sshd', TUNNEL, False, 'sshd: user@notty'),
              (6010, 950, 'sshd-session', TUNNEL, False, 'sshd-session: user [priv]')]
    proc, _ = _box(BOX + tunnel)
    assert [x['pid'] for x in hy.strays(hy.read_procs(proc), me=7000)] == [1200, 1300]


def spec_F35_a_job_left_in_an_ssh_session_still_counts():
    # the same tunnel's session, with real jobs in it: a loop under its
    # shell and a background python3 reparented to pid 1
    procs = BOX + [(6000, 950, 'sshd', TUNNEL, False), (6001, 6000, 'sshd', TUNNEL, False),
                   (6100, 6001, 'bash', TUNNEL, False, 'bash -c while true; do sleep 60; done'),
                   (6200, 1, 'python3', TUNNEL, False, 'python3 study.py')]
    proc, _ = _box(procs)
    pids = [x['pid'] for x in hy.strays(hy.read_procs(proc), me=7000)]
    assert pids == [1200, 1300, 6100, 6200]


def spec_F35_the_runs_own_chain_is_never_a_stray():
    # by hand through its unit: the login's shell and the systemctl that
    # started the service are the run's own; a job the same shell left is not
    typed = [(8000, 950, 'sshd', TYPED, False), (8001, 8000, 'bash', TYPED, False),
             (8002, 8001, 'systemctl', TYPED, False,
              'systemctl --user start grid-gremlin3-hygiene.service'),
             (8003, 8001, 'python3', TYPED, False, 'python3 left.py')]
    proc, _ = _box(BOX + typed)
    pids = [x['pid'] for x in hy.strays(hy.read_procs(proc), me=7000)]
    assert pids == [1200, 1300, 8003]
    # a systemctl that starts something else is no part of the run
    other = [t if t[0] != 8002 else t[:5] + ('systemctl --user start other.service',)
             for t in typed]
    proc, _ = _box(BOX + other)
    assert [x['pid'] for x in hy.strays(hy.read_procs(proc), me=7000)] == [1200, 1300, 8001, 8002, 8003]


def spec_F35_sabotage_were_the_whole_session_plumbing_its_jobs_would_pass_unseen():
    procs = BOX + [(6000, 950, 'sshd', TUNNEL, False),
                   (6200, 1, 'python3', TUNNEL, False, 'python3 study.py')]
    got = hy.read_procs(_box(procs)[0])
    real = hy.is_plumbing
    try:
        hy.is_plumbing = lambda p: p['cgroup'].endswith('.scope')     # widened to the scope
        assert [x['pid'] for x in hy.strays(got, me=7000)] == []
    finally:
        hy.is_plumbing = real
    assert [x['pid'] for x in hy.strays(got, me=7000)] == [1200, 1300, 6200]


def spec_F36_each_service_memory_is_read_from_its_cgroup():
    proc, cg = _box(BOX, memory={PANEL: 150 * MIB, '/system.slice/ssh.service': 5 * MIB})
    mem = hy.service_memory(hy.read_procs(proc), cg)
    assert mem == {PANEL: 150 * MIB, '/system.slice/ssh.service': 5 * MIB}   # unreadable left out
    assert hy._name(PANEL) == 'gg-panel.service (user 1000)'
    assert hy._name('/system.slice/ssh.service') == 'ssh.service'


def _history(series, path=PANEL):
    h = {}
    for i, v in enumerate(series):
        h = hy.record(h, f'2026-10-{i + 1:02d}', {path: int(v * MIB)})
    return h


def spec_F36_steady_growth_is_a_leak():
    leak = hy.growing(_history([100, 110, 118, 125, 131, 140, 150]))
    assert len(leak) == 1 and leak[0]['service'] == PANEL and leak[0]['days'] == 7
    assert leak[0]['first'] == 100 * MIB and leak[0]['last'] == 150 * MIB
    one_dip = hy.growing(_history([100, 110, 105, 120, 130, 140, 150]))   # 5 of 6 rises
    assert len(one_dip) == 1


def spec_F36_flat_noisy_restarted_young_or_small_is_not():
    assert hy.growing(_history([100, 101, 99, 100, 102, 100, 101])) == []      # flat noise
    assert hy.growing(_history([100, 140, 180, 60, 80, 100, 130])) == []       # restarted
    assert hy.growing(_history([100, 120, 140, 160, 180, 200])) == []          # 6 days: not yet
    assert hy.growing(_history([10, 12, 14, 16, 18, 20, 22])) == []            # +12 MiB: under the floor
    assert hy.growing(_history([400, 405, 410, 415, 420, 425, 430])) == []     # +7.5%: under a quarter
    assert hy.growing({}) == []


def spec_F36_sabotage_with_the_thresholds_off_flat_noise_would_be_a_leak():
    off = dict(hy.LIMITS, leak_rises=0, leak_growth=0.0, leak_floor_mib=0)
    assert len(hy.growing(_history([100, 101, 99, 100, 102, 100, 101]), off)) == 1


def spec_F36_the_history_keeps_its_days_and_one_reading_a_day():
    h = {}
    for i in range(40):
        h = hy.record(h, f'2026-09-{i:02d}', {PANEL: i})
    assert len(h['days']) == hy.LIMITS['keep_days'] and min(h['days']) == '2026-09-10'
    h = hy.record(h, '2026-09-39', {PANEL: 999})
    assert len(h['days']) == 30 and h['days']['2026-09-39'] == {PANEL: 999}


def _report(avail_share, t=1000.0, box='trading', strays=(), leaks=()):
    total = 2000 * MIB
    return {'box': box, 't': t, 'mem': {'total': total, 'available': int(total * avail_share)},
            'strays': list(strays), 'leaks': list(leaks), 'services': 9, 'seen': 99, 'whole': True}


def spec_F37_a_box_under_a_tenth_of_its_memory_pages_and_nothing_else_does():
    assert hy.meminfo(_box(BOX, 2_000_000, 150_000)[0]) == {'total': 2_000_000 * 1024,
                                                            'available': 150_000 * 1024}
    text = hy.page_text(_report(0.099), 1000.0)
    assert text.startswith('box memory · trading: 10% available') and 'near its limit' in text
    assert hy.page_text(_report(0.10), 1000.0) is None                 # at the line: no page
    stray = [{'pid': 1, 'comm': 'x', 'cmd': 'x', 'unit': 'session-1.scope'}]
    assert hy.page_text(_report(0.5, strays=stray), 1000.0) is None    # a stray is the digest's
    assert hy.page_text(_report(0.05, t=0.0), 3 * 3600.0) is None      # an old report never pages


def spec_F37_sabotage_with_the_page_line_at_nothing_a_full_box_is_silent():
    assert hy.page_text(_report(0.05), 1000.0, dict(hy.LIMITS, mem_page=0.0)) is None
    assert hy.page_text(_report(0.05), 1000.0) is not None


def spec_F37_the_page_command_sends_once_for_the_boxes_near_their_limit():
    d = Path(tempfile.mkdtemp())
    import time
    now = time.time()
    (d / 'trading.json').write_text(json.dumps(_report(0.5, t=now)))
    (d / 'data.json').write_text(json.dumps(_report(0.04, t=now, box='data')))
    sent = []
    assert hy.main(['page', str(d / 'trading.json'), str(d / 'data.json'),
                    str(d / 'missing.json')], send=sent.append) == 0
    assert len(sent) == 1 and 'box memory · data: 4% available' in sent[0] and 'trading' not in sent[0]
    sent.clear()
    (d / 'data.json').write_text(json.dumps(_report(0.5, t=now, box='data')))
    hy.main(['page', str(d / 'trading.json'), str(d / 'data.json')], send=sent.append)
    assert sent == []


def spec_F38_the_digest_says_a_box_only_when_something_is_off():
    d = Path(tempfile.mkdtemp())
    now = 100 * DAY
    (d / 'trading.json').write_text(json.dumps(_report(0.5, t=now - 600)))
    (d / 'trading.history.json').write_text('{"days": {}}')                # never read as a report
    assert hy.digest_lines(d, now) == []                                   # clean: nothing said
    stray = [{'pid': 1200, 'comm': 'python3', 'cmd': 'python3 -c loop', 'unit': 'session-5.scope'}]
    leak = [{'service': PANEL, 'first': 100 * MIB, 'last': 150 * MIB, 'days': 7}]
    (d / 'trading.json').write_text(json.dumps(_report(0.15, t=now - 600, strays=stray, leaks=leak)))
    (d / 'data.json').write_text(json.dumps(_report(0.5, t=now - 2 * DAY, box='data')))
    lines = hy.digest_lines(d, now)
    assert lines[0] == '🧹 box hygiene · data: report 48 h old — is its timer running?'
    assert lines[1] == ('🧹 box hygiene · trading: 1 stray process: python3 1200 (session-5.scope) · '
                        'growing: gg-panel.service (user 1000) 100 → 150 MiB over 7 days · '
                        'memory 15% available (300 of 2,000 MiB)')
    (d / 'data.json').write_text('{not json')
    assert 'data: unreadable' in hy.digest_lines(d, now)[0]


def spec_F38_the_digest_carries_the_hygiene_lines():
    import os
    from gridgremlin.digest import build
    d = Path(tempfile.mkdtemp())
    (d / 'hy').mkdir()
    import time
    now = time.time()
    stray = [{'pid': 7, 'comm': 'sleep', 'cmd': 'sleep 900', 'unit': 'session-2.scope'}]
    (d / 'hy' / 'trading.json').write_text(json.dumps(_report(0.5, t=now, strays=stray)))
    old = os.getcwd()
    os.chdir(d)
    try:
        text, _ = build([], now=now, hygiene_root=d / 'hy')
        assert '🧹 box hygiene · trading: 1 stray process: sleep 7 (session-2.scope)' in text
        (d / 'hy' / 'trading.json').write_text(json.dumps(_report(0.5, t=now)))
        text, _ = build([], now=now, hygiene_root=d / 'hy')
        assert 'box hygiene' not in text
    finally:
        os.chdir(old)


def spec_F35_a_run_writes_the_report_and_the_history_and_kills_nothing():
    proc, cg = _box(BOX, memory={PANEL: 150 * MIB})
    out = Path(tempfile.mkdtemp())
    assert hy.main(['run', '--box', 'trading', '--root', str(out), '--proc', proc, '--cgroup', cg]) == 0
    r = json.loads((out / 'trading.json').read_text())
    assert r['box'] == 'trading' and r['whole'] and r['services'] == 1
    assert {x['pid'] for x in r['strays']} == {1200, 1300}                # each process still listed
    assert list(json.loads((out / 'trading.history.json').read_text())['days'].values()) == [{PANEL: 150 * MIB}]
    assert hy.main(['run', '--box', '../x', '--root', str(out)]) == 2      # a box name is a file name
    src = (ROOT / 'gridgremlin' / 'hygiene.py').read_text()
    assert not _acts(src), _acts(src)


def _acts(src):
    """What in a source would act on a process rather than read it."""
    return [w for w in ('os.kill', 'killpg', 'signal', 'subprocess', 'pkill', 'cgroup.kill',
                        'cgroup.procs') if w in src]


def spec_F35_sabotage_the_never_kills_scan_catches_a_planted_kill():
    assert _acts('import os\nos.kill(1200, 15)\n') == ['os.kill']


def spec_F38_the_units_one_set_per_box_the_data_box_holds_no_key():
    ops = ROOT / 'ops' / 'systemd'
    trading = (ops / 'hygiene.service.template').read_text()
    data = (ops / 'hygiene-data.service.template').read_text()
    assert 'run --box trading' in trading and 'run --box data' in data
    pull = next(ln for ln in trading.splitlines() if ln.startswith('Exec') and 'rsync' in ln)
    assert pull.startswith('ExecStartPost=-') and '{{HYGIENE_SOURCE}}data.json' in pull
    assert 'BatchMode=yes' in pull and '--delete' not in pull
    assert 'hygiene page logs/hygiene/trading.json logs/hygiene/data.json' in trading
    runs = [ln for ln in data.splitlines() if ln.startswith('Exec')]
    assert runs == ['ExecStart=/usr/bin/python3 -m gridgremlin.hygiene run --box data']   # no page, no push
    assert 'EnvironmentFile' not in data                                   # no .env, no key, no phone
    for timer, at in (('hygiene.timer.template', '23:50:00'), ('hygiene-data.timer.template', '23:40:00')):
        assert f'OnCalendar=*-*-* {at}' in (ops / timer).read_text()
