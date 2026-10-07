"""D65: the pinned live copy moves only by promotion — merged code, a day on
play money, or a hotfix with its reason written down."""
import importlib.util
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
    why = _refused(promote.promote, main, live, b, now=T0 + 100 + 3600)
    assert 'h of the 24 h' in why and _head(live) == before
    target, current, changes = promote.promote(main, live, b,
                                               now=T0 + 100 + DAY + 1)
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
    assert 'never run in the play-money checkout' in why


def spec_D65_status_says_what_waits_and_for_how_long():
    main, live, _, ship = _world()
    ship('F', T0 + 100)
    out = promote.status(main, live, now=T0 + 100 + 7200)
    assert 'waiting' in out and 'on play money 2.0 h' in out
