"""F26/F27 (D74): what the box keeps, and the workstation's copy of it."""
import gzip
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def spec_F26_an_archived_log_older_than_a_day_is_compressed_in_place():
    """One archived log held 2.3 GB uncompressed, 80% of the disk
    (2026-10-08). Kept — compressed; a fresh one and anything not a log
    are left alone; the .gz replaces the original only once whole."""
    from gridgremlin.retention import compress_archive
    d = Path(tempfile.mkdtemp())
    old = d / 'fleet-demo.2026-09-25.log'
    old.write_text('line\n' * 1000)
    os.utime(old, (time.time() - 200000, time.time() - 200000))
    fresh = d / 'fleet-hl.2026-10-08.log'
    fresh.write_text('new\n')
    other = d / 'tombstones.2026-10-02.json'
    other.write_text('{}')
    os.utime(other, (time.time() - 200000, time.time() - 200000))
    done = compress_archive(str(d))
    assert done == [str(d / 'fleet-demo.2026-09-25.log.gz')]
    assert not old.exists() and fresh.exists() and other.exists()
    assert gzip.open(d / 'fleet-demo.2026-09-25.log.gz').read() == b'line\n' * 1000
    assert compress_archive(str(d)) == []                       # nothing twice
    assert compress_archive(str(d / 'missing')) == []           # no dir: nothing
    assert not list(d.glob('*.part'))


def spec_F27_the_backup_pulls_dated_hard_linked_copies_and_prunes():
    """The box's logs, configs and keys file, pulled nightly to the
    workstation: dated, hard-linked against the previous copy, the newest
    KEEP kept, settings from one file and never from the script."""
    if not shutil.which('rsync'):
        raise AssertionError('rsync is needed to run the backup spec')
    d = Path(tempfile.mkdtemp())
    src = d / 'box'
    (src / 'logs').mkdir(parents=True)
    (src / 'configs').mkdir()
    (src / 'logs' / 'fleet-demo.log').write_text('a' * 5000)
    (src / 'configs' / 'fleet.demo.json').write_text('{}')
    (src / '.env').write_text('K=v\n')
    os.chmod(src / '.env', 0o600)
    dest = d / 'backups'
    env = d / 'gg-backup.env'
    env.write_text(f'REMOTE={src}\nDEST={dest}\nKEEP=2\n')
    script = ROOT / 'ops' / 'workstation' / 'backup.sh'

    def run(date):
        r = subprocess.run(['sh', str(script)], capture_output=True, text=True,
                           env={**os.environ, 'GG_BACKUP_ENV': str(env), 'GG_DATE': date})
        assert r.returncode == 0, r.stderr
        return r.stdout
    run('2026-10-01')
    assert (dest / '2026-10-01' / 'logs' / 'fleet-demo.log').read_text() == 'a' * 5000
    assert (dest / '2026-10-01' / '.env').stat().st_mode & 0o777 == 0o600
    assert os.readlink(dest / 'latest') == '2026-10-01'
    run('2026-10-02')
    a = (dest / '2026-10-01' / 'logs' / 'fleet-demo.log').stat()
    b = (dest / '2026-10-02' / 'logs' / 'fleet-demo.log').stat()
    assert a.st_ino == b.st_ino                                  # unchanged: one copy
    (src / 'logs' / 'fleet-demo.log').write_text('b' * 5000)
    os.utime(src / 'logs' / 'fleet-demo.log', (time.time() + 5, time.time() + 5))   # a later write
    out = run('2026-10-03')
    assert (dest / '2026-10-03' / 'logs' / 'fleet-demo.log').read_text() == 'b' * 5000
    assert (dest / '2026-10-02' / 'logs' / 'fleet-demo.log').read_text() == 'a' * 5000
    assert not (dest / '2026-10-01').exists() and '2 kept' in out      # KEEP=2
    assert os.readlink(dest / 'latest') == '2026-10-03'
    assert oct(dest.stat().st_mode & 0o777) == '0o700'
    r = subprocess.run(['sh', str(script)], capture_output=True, text=True,
                       env={**os.environ, 'GG_BACKUP_ENV': str(d / 'none')})
    assert r.returncode == 2 and 'no settings' in r.stderr


def spec_F28_the_runbook_names_every_unit_timer_and_command_that_exists():
    """D75: one page the owner can read in a minute, held to the box by
    the suite — what the templates render, what the phone answers, the
    tools — or it has drifted."""
    import re
    page = (ROOT / 'docs' / 'RUNBOOK.md').read_text()
    units = set()
    for t in (ROOT / 'ops' / 'systemd').glob('*.template'):
        name = t.name.replace('.template', '')
        if name.startswith('fleet-failed') or name.startswith('watchdog-failed'):
            continue                           # the alarms are named by their pages
        if name == 'panel.service':
            units.add('gg-panel')
        elif name.startswith('fleet.'):
            units.add('grid-gremlin3-demo'); units.add('grid-gremlin3-hl')
        elif name.startswith('fleet-live'):
            units.add('fleet-live.service')            # D98: named by its template
        elif name.startswith('watchdog.timer'):
            units.add('grid-gremlin3-<fleet>-watchdog.timer')
        elif name.endswith('.timer'):
            units.add('grid-gremlin3-' + name.replace('.timer', '') + '.timer')
        elif name.endswith('.service') and not name.startswith('watchdog.'):
            units.add('grid-gremlin3-' + name.replace('.service', ''))
    for u in sorted(units):
        short = u.replace('grid-gremlin3-', '-') if u.startswith('grid-gremlin3-') else u
        assert u in page or short in page, f'runbook does not name {u}'
    cmds = set(re.findall(r'^def cmd_([a-z_]+)', (ROOT / 'gridgremlin' / 'phone.py').read_text(), re.M))
    for c in cmds:
        assert f'/{c}' in page, f'runbook does not name /{c}'
    for tool in ('gridgremlin.close', 'ops/promote.py', 'gg-panel', 'dead-man', 'backups/gg/latest',
                 'systemctl --user stop grid-gremlin3-demo grid-gremlin3-hl', '/remote-control'):
        assert tool in page, tool
    assert len(page.splitlines()) < 140                       # one page, not a manual


def spec_G22_the_split_gives_each_fleet_its_own_state_from_the_old_file_and_its_snapshot():
    """ops/split_local_state.py, once per box (2026-10-08): the old shared
    files are dealt out by botid, a window offset comes from the fleet's
    latest snapshot when it has one (the clobbered file lost it; the
    running fleet's belief did not), the same botid in two fleets lands in
    both, rows already in a per-fleet file stay, leftovers are named and
    kept only in the archive copy, a running fleet refuses the commit."""
    import importlib.util
    import json
    spec = importlib.util.spec_from_file_location(
        'split_local_state', ROOT / 'ops' / 'split_local_state.py')
    split = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(split)
    d = Path(tempfile.mkdtemp())
    (d / 'configs').mkdir()
    (d / 'logs').mkdir()
    btc = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long'}
    demo = d / 'configs' / 'fleet.demo.json'
    carry = d / 'configs' / 'fleet.carry.json'
    demo.write_text(json.dumps({'watchdog': 'configs/watchdog.demo.json',
                                'bots': [btc, dict(btc, symbol='SOLUSDT')]}))
    carry.write_text(json.dumps({'bots': [btc, {'strategy': 'portfolio', 'name': 'carry'}]}))
    (d / 'configs' / 'watchdog.demo.json').write_text(json.dumps({'snapshot': 'logs/snapshots-demo.jsonl'}))
    (d / 'logs' / 'snapshots-demo.jsonl').write_text(
        json.dumps({'bots': {'linBTCUSDTl': {'offset': -28}, 'linSOLUSDTl': {'offset': -14}}}) + '\n'
        + '{broken\n')
    (d / 'logs' / 'slide_state.json').write_text(json.dumps({'linBTCUSDTl': -3, 'linETHs': -24}))
    (d / 'logs' / 'tombstones.json').write_text(json.dumps(
        {'linBTCUSDTl': {'reason': 'stop'}, 'pfocarry': {'reason': 'loss'}, 'linOLDl': {'reason': 'gone'}}))
    (d / 'logs' / 'tombstones-carry.json').write_text(json.dumps({'linBTCUSDTs': {'reason': 'kept'}}))
    (d / 'logs' / 'portfolio_state.json').write_text(json.dumps(
        {'pfocarry': {'cash': 1.0}, 'pfogone': {'cash': 9.0}}))
    (d / 'logs' / 'portfolio_state-carry.json').write_text(json.dumps({'pfocarry': {'cash': 2.0}}))
    p = split.plan([demo, carry])
    assert p['fleets']['carry']['portfolio_state']['rows'] == {'pfocarry': {'cash': 2.0}}   # the per-fleet row wins
    assert p['fleets']['demo']['portfolio_state']['rows'] == {}
    assert p['orphans']['portfolio_state'] == {'pfogone': {'cash': 9.0}}
    assert p['fleets']['demo']['slide_state']['rows'] == {'linBTCUSDTl': -28, 'linSOLUSDTl': -14}
    assert p['fleets']['carry']['slide_state']['rows'] == {'linBTCUSDTl': -3}
    assert p['fleets']['demo']['tombstones']['rows'] == {'linBTCUSDTl': {'reason': 'stop'}}
    assert p['fleets']['carry']['tombstones']['rows'] == {
        'linBTCUSDTl': {'reason': 'stop'}, 'pfocarry': {'reason': 'loss'},
        'linBTCUSDTs': {'reason': 'kept'}}
    assert p['orphans']['tombstones'] == {'linOLDl': {'reason': 'gone'}}
    assert p['orphans']['slide_state'] == {'linETHs': -24}
    try:
        split.commit([demo, carry], p, running=lambda f: f.endswith('fleet.carry.json'))
    except split.Refused as e:
        assert 'running' in str(e)
    else:
        raise AssertionError('committed under a running fleet')
    assert (d / 'logs' / 'slide_state.json').exists()           # nothing moved
    moved = split.commit([demo, carry], p, running=lambda f: False)
    assert json.loads((d / 'logs' / 'slide_state-demo.json').read_text()) == {
        'linBTCUSDTl': -28, 'linSOLUSDTl': -14}
    assert json.loads((d / 'logs' / 'tombstones-carry.json').read_text())['linBTCUSDTs'] == {'reason': 'kept'}
    assert not (d / 'logs' / 'slide_state.json').exists()
    assert json.loads((d / 'logs' / 'archive' / 'slide_state.pre-split.json').read_text())['linETHs'] == -24
    assert [str(m[1].name) for m in moved] == ['tombstones.pre-split.json', 'slide_state.pre-split.json',
                                               'portfolio_state.pre-split.json']
    try:
        split.plan([demo, d / 'elsewhere' / 'fleet.x.json'])
    except split.Refused as e:
        assert 'logs/' in str(e)
    else:
        raise AssertionError('two logs directories were split as one')


# --- F31: the panel's edits beside git (D94) ---------------------------------

def _git_pair():
    """An 'origin' with one config, a 'box' clone of it; git run quietly."""
    import subprocess
    d = Path(tempfile.mkdtemp())
    env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t',
           'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'}

    def g(where, *args):
        r = subprocess.run(['git', '-C', str(where), *args], capture_output=True, text=True, env=env)
        assert r.returncode == 0, r.stderr
        return r.stdout
    (d / 'origin' / 'configs').mkdir(parents=True)
    g(d / 'origin', 'init', '-q', '-b', 'main')
    (d / 'origin' / 'configs' / 'fleet.a.json').write_text('{"v": 1}\n')
    (d / 'origin' / 'configs' / 'fleet.b.json').write_text('{"v": 1}\n')
    (d / 'origin' / 'code.py').write_text('x = 1\n')
    g(d / 'origin', 'add', '.')
    g(d / 'origin', 'commit', '-q', '-m', 'one')
    subprocess.run(['git', 'clone', '-q', str(d / 'origin'), str(d / 'box')], check=True, env=env)
    return d, g


def spec_F31_the_deploy_lets_through_what_git_already_has_and_refuses_the_rest():
    """The panel's edit on the box, taken into the repository: the deploy
    stages it (identical) and fast-forwards — the file never goes back to
    the old terms on the way. An edit that differs from what arrives refuses
    the whole deploy and changes nothing. An edit nothing arrives for stays,
    named. --dry acts on nothing."""
    import importlib.util
    import subprocess
    spec = importlib.util.spec_from_file_location('deploy', ROOT / 'ops' / 'deploy.py')
    dep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dep)
    d, g = _git_pair()
    box, origin = d / 'box', d / 'origin'
    (box / 'configs' / 'fleet.a.json').write_text('{"v": 2}\n')          # the panel's edit
    (box / 'configs' / 'fleet.b.json').write_text('{"v": 9}\n')          # another, not taken
    (origin / 'configs' / 'fleet.a.json').write_text('{"v": 2}\n')       # taken home, merged
    (origin / 'code.py').write_text('x = 2\n')
    g(origin, 'commit', '-qam', 'take the box and a code change')
    out = []
    head = g(box, 'rev-parse', 'HEAD')
    assert dep.deploy(box, subprocess.run, dry=True, log=out.append) == 0
    assert g(box, 'rev-parse', 'HEAD') == head and 'would stage' in out[-1]
    assert dep.deploy(box, subprocess.run, log=out.append) == 0
    assert (box / 'code.py').read_text() == 'x = 2\n'                       # deployed
    assert (box / 'configs' / 'fleet.a.json').read_text() == '{"v": 2}\n'
    assert 'fleet.a.json' in out[-1] and 'still edited here' in out[-1] and 'fleet.b.json' in out[-1]
    assert g(box, 'status', '--porcelain', '--', 'configs/fleet.a.json') == ''   # git agrees now
    # an edit that differs from what arrives: refused, nothing changed
    (origin / 'configs' / 'fleet.b.json').write_text('{"v": 3}\n')
    g(origin, 'commit', '-qam', 'a repo-side change')
    head = g(box, 'rev-parse', 'HEAD')
    assert dep.deploy(box, subprocess.run, log=out.append) == 1
    assert 'REFUSED' in out[-1] and 'fleet.b.json' in out[-1]
    assert g(box, 'rev-parse', 'HEAD') == head
    assert (box / 'configs' / 'fleet.b.json').read_text() == '{"v": 9}\n'   # the box's edit untouched
    # a new fleet file made on the box, the same one arriving: let through
    (box / 'configs' / 'fleet.c.json').write_text('{"v": 1}\n')
    (box / 'configs' / 'fleet.b.json').write_text('{"v": 3}\n')            # taken home meanwhile
    (origin / 'configs' / 'fleet.c.json').write_text('{"v": 1}\n')
    g(origin, 'add', '.')
    g(origin, 'commit', '-qm', 'the new fleet')
    assert dep.deploy(box, subprocess.run, log=out.append) == 0, out[-1]
    assert g(box, 'status', '--porcelain') == ''


def spec_F31_the_box_edits_come_home_and_the_panel_names_them():
    """take_box_configs reads the box's own git view of configs/ (changed,
    new, deleted), copies them into this tree, refuses a path outside
    configs/ and a tree with config edits of its own. The panel names the
    edited files in one escaped line, asking git at most once a minute."""
    import importlib.util
    import subprocess
    from gridgremlin.drift import edited_here, notice
    spec = importlib.util.spec_from_file_location('take', ROOT / 'ops' / 'take_box_configs.py')
    take = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(take)
    d, g = _git_pair()
    box = d / 'box'
    (box / 'configs' / 'fleet.a.json').write_text('{"v": 5}\n')
    (box / 'configs' / 'fleet.new.json').write_text('{"v": 1}\n')
    (box / 'configs' / 'fleet.b.json').unlink()
    rows = edited_here(box)
    assert sorted(rows) == [('??', 'configs/fleet.new.json'), ('D', 'configs/fleet.b.json'),
                            ('M', 'configs/fleet.a.json')]

    def ssh(host, command):                 # the box, read through a local shell
        r = subprocess.run(command, shell=True, capture_output=True, text=True)
        return r.returncode, r.stdout
    home = d / 'home'
    subprocess.run(['git', 'clone', '-q', str(d / 'origin'), str(home)], check=True)
    took = take.take('box', str(box), home, ssh)
    assert len(took) == 3
    assert (home / 'configs' / 'fleet.a.json').read_text() == '{"v": 5}\n'
    assert (home / 'configs' / 'fleet.new.json').exists() and not (home / 'configs' / 'fleet.b.json').exists()
    try:
        take.take('box', str(box), home, ssh)                                  # home has edits now
        raise AssertionError('took over local edits')
    except SystemExit as e:
        assert 'of its own' in str(e)
    fresh = d / 'fresh'
    subprocess.run(['git', 'clone', '-q', str(d / 'origin'), str(fresh)], check=True)
    try:
        take.take('box', str(box), fresh, lambda h, c: (0, ' M ../etc/passwd\n') if 'status' in c else (0, ''))
        raise AssertionError('took a path outside configs/')
    except SystemExit as e:
        assert 'outside configs/' in str(e)
    line = notice([('M', 'configs/fleet.<b>.json')])
    assert '1 config file edited here' in line and '&lt;b&gt;' in line and '<b>' not in line
    assert notice([]) == ''
    from panel.routes import Handler
    calls = []
    Handler._drift = (0.0, '')
    reader = lambda root: (calls.append(root), [('M', 'configs/fleet.a.json')])[1]
    assert 'fleet.a.json' in Handler._drift_notice(now=1000.0, read=reader)
    Handler._drift_notice(now=1030.0, read=reader)
    assert len(calls) == 1                                                     # once a minute
    Handler._drift = (0.0, '')


def _render(text, fleet):
    """A template filled as ops/README's install fills it, for the names."""
    return text.replace('{{FLEET}}', fleet)


def _unwatched(unit_text, fleet):
    """F24e: why a rendered fleet unit could start without its watchdog
    timer — [] when its [Unit] Wants= the timer the watchdog renders to."""
    timer = f'grid-gremlin3-{fleet}-watchdog.timer'     # ops/README: watchdog.timer -> this name
    unit = unit_text.split('[Service]', 1)[0]
    wants = [w for ln in unit.splitlines() if ln.startswith('Wants=') for w in ln[6:].split()]
    return [] if timer in wants else [f'{fleet}: its unit does not want {timer}']


def spec_F24e_starting_a_fleet_starts_its_watchdog_timer():
    """The audit, 2026-11-06: a fleet ran two weeks with its watchdog timer
    inactive and nobody told. Every fleet unit, play money and real, pulls
    its own watchdog timer when it starts."""
    root = ROOT / 'ops' / 'systemd'
    timer = (root / 'watchdog.timer.template').read_text()
    assert '[Install]' in timer and 'WantedBy=timers.target' in timer   # a timer that can start
    units = [t for t in sorted(root.glob('fleet*.service.template')) if 'failed' not in t.name]
    assert root / 'fleet.service.template' in units        # the real-money one: the private tree's
    for t in units:
        for fleet in ('demo', 'hl', 'carry'):
            assert _unwatched(_render(t.read_text(), fleet), fleet) == [], t.name
    runbook = (ROOT / 'docs' / 'RUNBOOK.md').read_text()   # the edition's stands in its place (F28)
    assert "starts the fleet's watchdog timer with it" in runbook      # start and stop say it
    assert 'stops its `grid-gremlin3-<fleet>-watchdog.timer` too' in runbook


def spec_F24e_sabotage_a_fleet_unit_without_the_line_is_named():
    text = (ROOT / 'ops' / 'systemd' / 'fleet.service.template').read_text()
    cut = '\n'.join(ln for ln in text.splitlines() if 'watchdog.timer' not in ln)   # the guard removed
    assert _unwatched(_render(cut, 'demo'), 'demo') == ['demo: its unit does not want grid-gremlin3-demo-watchdog.timer']
    wrong = text.replace('grid-gremlin3-{{FLEET}}-watchdog.timer', 'grid-gremlin3-other-watchdog.timer')
    assert _unwatched(_render(wrong, 'demo'), 'demo')                   # another fleet's timer is no watch


def spec_F31b_a_real_money_fleets_files_are_never_named_nor_taken():
    """The live copy holds its fleet and watchdog files untracked, beside
    its .env (D64). Git ignores them (configs/*.live.json), so the panel
    never asks for them to be taken into the repository and the take never
    sees them; a paper file beside them still is. The notice carries no
    decision code (U117: it showed "(D94)" on the live panel, 2026-11-09).
    Sabotage: without the ignore line, the live files are named."""
    import shutil
    import subprocess
    import tempfile
    from gridgremlin.drift import edited_here, notice
    assert 'configs/*.live.json' in (ROOT / '.gitignore').read_text().splitlines()
    d = Path(tempfile.mkdtemp())
    try:
        subprocess.run(['git', 'init', '-q', str(d)], check=True)
        shutil.copy(ROOT / '.gitignore', d / '.gitignore')
        (d / 'configs').mkdir()
        for name in ('fleet.live.json', 'watchdog.live.json', 'fleet.paper.json'):
            (d / 'configs' / name).write_text('{}\n')
        assert edited_here(d) == [('??', 'configs/fleet.paper.json')]
    finally:
        shutil.rmtree(d, ignore_errors=True)
    import re
    assert not re.search(r'\b[A-Z]\d+\b', notice([('??', 'configs/fleet.paper.json')]))

