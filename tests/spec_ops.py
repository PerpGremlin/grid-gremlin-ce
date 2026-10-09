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
