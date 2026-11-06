"""D65: the pinned live copy moves only by promotion — merged code, a day on
play money, or a hotfix with its reason written down."""
import importlib.util
import json
import os
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    'promote', HERE.parent / 'ops' / 'promote.py')
promote = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(promote)

DAY = 24 * 3600
T0 = 1_800_000_000                                  # a fixed clock


def _git(repo, *args, when=None):
    env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t',
               GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@t')
    if when is not None:
        env['GIT_COMMITTER_DATE'] = env['GIT_AUTHOR_DATE'] = f'{when} +0000'
    subprocess.run(['git', '-C', str(repo), *args], check=True,
                   capture_output=True, env=env)


def _world():
    """origin (bare), the main checkout, and the live worktree at commit A."""
    d = Path(tempfile.mkdtemp())
    origin, work, main, live = d / 'origin.git', d / 'work', d / 'main', d / 'main-live'
    _git(d, 'init', '-q', '--bare', '-b', 'main', str(origin))
    _git(d, 'init', '-q', '-b', 'main', str(work))
    _git(work, 'remote', 'add', 'origin', str(origin))
    (work / 'f').write_text('a')
    _git(work, 'add', 'f')
    _git(work, 'commit', '-qm', 'A', when=T0)
    _git(work, 'push', '-q', 'origin', 'main')
    _git(d, 'clone', '-q', str(origin), str(main), when=T0)
    _git(main, 'worktree', 'add', '-q', '--detach', str(live), 'HEAD')

    def ship(msg, at):
        """A merged change, then deployed to the main checkout at `at`."""
        (work / 'f').write_text(msg)
        _git(work, 'commit', '-qam', msg, when=at)
        _git(work, 'push', '-q', 'origin', 'main')
        _git(main, 'pull', '-q', 'origin', 'main', when=at)
        return subprocess.run(['git', '-C', str(main), 'rev-parse', 'HEAD'],
                              capture_output=True, text=True).stdout.strip()
    return main, live, work, ship


def _ran(main, sha, since, until, dirty=False, tiers=None):
    """A play-money fleet's snapshot rows: a run started from `sha` at
    `since`, a row an hour until `until` (F19b)."""
    (main / 'configs').mkdir(exist_ok=True)
    (main / 'logs').mkdir(exist_ok=True)
    (main / 'configs' / 'wd.demo.json').write_text(json.dumps({'snapshot': 'logs/demo.snap.jsonl'}))
    (main / 'configs' / 'fleet.demo.json').write_text(json.dumps({'watchdog': 'configs/wd.demo.json',
                                                                  'bots': []}))
    code = dict({'sha': sha, 'since': since}, **({'dirty': True} if dirty else {}))
    t = since
    with open(main / 'logs' / 'demo.snap.jsonl', 'a') as f:
        while True:
            t = min(t, until)
            f.write(json.dumps({'t': t, 'code': code, 'equity': 1.0, 'mm_rate': 0.0,
                                **({'tiers': tiers} if tiers else {}), 'bots': {}}) + '\n')
            if t >= until:
                break
            t += 3600


def _head(repo):
    return subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD'],
                          capture_output=True, text=True).stdout.strip()


def _refused(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except promote.Refused as e:
        return str(e)
    raise AssertionError('not refused')


def spec_D65_a_day_on_play_money_then_it_moves_and_is_logged():
    main, live, _, ship = _world()
    b = ship('B', T0 + 100)
    before = _head(live)
    _ran(main, b, T0 + 200, T0 + 200 + 3600)
    why = _refused(promote.promote, main, live, b, now=T0 + 200 + 3600)
    assert '1.0 h of the 24 h' in why and _head(live) == before, why
    _ran(main, b, T0 + 200, T0 + 200 + DAY)
    target, current, changes = promote.promote(main, live, b,
                                               now=T0 + 200 + DAY + 1)
    assert target == b and _head(live) == b and current == before
    assert 'B' in changes
    log = (live / 'logs' / 'promotions.log').read_text()
    assert f'{before[:7]} -> {b[:7]} promoted' in log and '24.0 h' in log


def spec_D65_a_hotfix_moves_today_with_its_reason():
    main, live, _, ship = _world()
    c = ship('C', T0 + 500)
    assert 'reason' in _refused(promote.promote, main, live, c, hotfix='  ',
                                now=T0 + 600)
    promote.promote(main, live, c, hotfix='stop never fires', now=T0 + 600)
    assert _head(live) == c
    assert 'HOTFIX: stop never fires' in (
        live / 'logs' / 'promotions.log').read_text()


def spec_D65_only_merged_code_reaches_the_live_copy():
    main, live, _, ship = _world()
    ship('D', T0 + 100)
    _git(main, 'commit', '-q', '--allow-empty', '-m', 'local only', when=T0 + 200)
    why = _refused(promote.promote, main, live, 'HEAD', hotfix='urgent',
                   now=T0 + DAY * 3)
    assert 'not on the merged main' in why


def spec_D65_a_version_play_money_never_ran_waits_or_is_a_hotfix():
    main, live, work, _ = _world()
    (work / 'f').write_text('E')
    _git(work, 'commit', '-qam', 'E', when=T0 + 100)
    _git(work, 'push', '-q', 'origin', 'main')
    _git(main, 'fetch', '-q', 'origin')               # fetched, never deployed
    why = _refused(promote.promote, main, live, 'origin/main', now=T0 + DAY * 5)
    assert 'never run on a play-money fleet' in why and 'deployed' not in why, why


def spec_D65_status_says_what_waits_and_for_how_long():
    main, live, _, ship = _world()
    f = ship('F', T0 + 100)
    out = promote.status(main, live, now=T0 + 100 + 7200)
    assert 'waiting' in out and 'deployed 2.0 h, no fleet run on it yet' in out, out
    _ran(main, f, T0 + 200, T0 + 200 + 7200)
    out = promote.status(main, live, now=T0 + 200 + 7200)
    assert 'run on play money 2.0 h' in out, out


def spec_F19b_a_deploy_no_fleet_restarted_on_has_not_run():
    """The fifth audit (2026-11-05): the 24 h was the main checkout's
    reflog — when a deploy pulled it — while the fleets, never restarted,
    went on running the old code. It is now what the fleets ran: each
    snapshot row names the version its run started from."""
    main, live, _, ship = _world()
    a = _head(main)
    g = ship('G', T0 + 100)
    _ran(main, a, T0, T0 + 5 * DAY)                    # the fleet ran the old code all along
    why = _refused(promote.promote, main, live, g, now=T0 + 5 * DAY)
    assert 'never run on a play-money fleet (deployed 120.0 h ago, no fleet restarted on it)' in why, why
    _ran(main, g, T0 + 5 * DAY, T0 + 6 * DAY, dirty=True)    # code edited in place: not this version
    _ran(main, g, T0 + 6 * DAY, T0 + 7 * DAY, tiers={'bybit': 'mainnet'})   # not play money
    assert 'never run' in _refused(promote.promote, main, live, g, now=T0 + 7 * DAY)
    _ran(main, g, T0 + 7 * DAY, T0 + 8 * DAY)
    assert promote.promote(main, live, g, now=T0 + 8 * DAY)[0] == g
    log = (live / 'logs' / 'promotions.log').read_text()
    assert 'ran on play money: 24.0 h' in log


def spec_F19b_a_merge_that_changes_no_code_counts_its_trees_run():
    main, live, work, ship = _world()
    h = ship('H', T0 + 100)
    _ran(main, h, T0 + 200, T0 + 200 + DAY)
    _git(work, 'commit', '-q', '--allow-empty', '-m', 'docs', when=T0 + 300)
    _git(work, 'push', '-q', 'origin', 'main')
    _git(main, 'pull', '-q', 'origin', 'main', when=T0 + 300)
    assert promote.promote(main, live, _head(main), now=T0 + 200 + DAY)[0] == _head(main)


def spec_F19b_the_fleet_writes_the_version_it_started_from():
    import inspect
    from gridgremlin import main as m
    class Git:
        def __init__(self, out, code=0):
            self.stdout, self.returncode = out, code
    said = iter([Git('a' * 40 + '\n'), Git('')])
    got = m.code_version(5.0, run=lambda *a, **k: next(said))
    assert got == {'sha': 'a' * 40, 'since': 5.0}, got
    said = iter([Git('a' * 40), Git(' M gridgremlin/bot.py\n')])
    assert m.code_version(5.0, run=lambda *a, **k: next(said))['dirty'] is True
    row = m.snapshot_row([], {'equity': 1.0, 'mm_rate': 0.0}, 9.0, code=got)
    assert promote.ROW_T.match(json.dumps(row)), json.dumps(row)[:80]        # the head promote reads
    assert 'code' not in m.snapshot_row([], {'equity': 1.0, 'mm_rate': 0.0}, 9.0)

    assert m.code_version(5.0, run=lambda *a, **k: Git('', 128)) is None     # no git: unknown
    src = inspect.getsource(m.run)
    assert 'code = code_version(time.time())' in src and "for v, c in clients.items()}, code)" in src


def spec_F19b_sabotage_the_reflog_age_again_is_caught():
    """Sabotage: the age back to the reflog's — the deploy-only spec goes red."""
    real = promote.ran_for

    def reflog(main, target, ran=None):
        seen = promote.first_seen(main, target)
        return None if seen is None else T0 + 5 * DAY - seen
    promote.ran_for = reflog
    try:
        spec_F19b_a_deploy_no_fleet_restarted_on_has_not_run()
    except AssertionError:
        return
    finally:
        promote.ran_for = real
    raise AssertionError('the sabotage was not caught')
