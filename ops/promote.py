"""D65: the pinned copy real money runs from, and the one way it moves.

Play money runs from the main checkout, which every deploy updates. Real
money runs from a second copy — a git worktree of the same repository,
detached at one exact version, with its own .env, logs/ and fleet file. It
moves only when the owner promotes a version, and only:

  - a version already on the merged main (nothing unreviewed reaches it);
  - after that version has run in the main checkout for at least a day,
    by git's own record of when the main checkout received it (its reflog);
  - or the same day as a hotfix, the reason written down.

Every promotion is appended to <live>/logs/promotions.log. This moves the
copy and restarts nothing: the live fleet takes the new version at its next
restart, which the owner runs.

  python3 ops/promote.py --status
  python3 ops/promote.py <version>
  python3 ops/promote.py <version> --hotfix "why it cannot wait"

The live copy defaults to <main checkout>-live beside it (GG_LIVE_DIR).
"""
import os
import subprocess
import sys
import time
from pathlib import Path

DAY_S = 24 * 3600


class Refused(Exception):
    pass


def git(repo, *args):
    r = subprocess.run(['git', '-C', str(repo), *args], capture_output=True,
                       text=True)
    if r.returncode:
        raise Refused(f"git {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout.strip()


def resolve(repo, ref):
    return git(repo, 'rev-parse', '--verify', f'{ref}^{{commit}}')


def contains(repo, ancestor, descendant):
    return subprocess.run(['git', '-C', str(repo), 'merge-base',
                           '--is-ancestor', ancestor, descendant],
                          capture_output=True).returncode == 0


def first_seen(main, commit):
    """When the main checkout first held `commit`: the oldest reflog entry
    of its HEAD that contains it. None when it never has."""
    lines = git(main, 'reflog', '--date=unix', '--format=%H %gd', 'HEAD')
    seen = None
    for line in lines.splitlines():                  # newest first
        sha, ref = line.split(' ', 1)
        t = int(ref[ref.index('{') + 1:ref.index('}')])
        if contains(main, commit, sha):
            seen = t                                 # keep walking back
        else:
            break
    return seen


def plan(main, live, ref, hotfix=None, min_age_s=DAY_S, now=None):
    """Pure judgement, no move: -> (target, current, age_s) or Refused."""
    now = time.time() if now is None else now
    target = resolve(main, ref)
    merged = resolve(main, 'origin/main')
    if not contains(main, target, merged):
        raise Refused(f'{ref} is not on the merged main — only reviewed, '
                      'merged code reaches real money')
    current = resolve(live, 'HEAD')
    if target == current:
        raise Refused(f'the live copy is already on {target[:7]}')
    seen = first_seen(main, target)
    age = None if seen is None else now - seen
    if hotfix is None:
        if age is None:
            raise Refused(f'{target[:7]} has never run in the play-money '
                          'checkout — deploy it there first, or promote it '
                          'as a hotfix with its reason')
        if age < min_age_s:
            raise Refused(f'{target[:7]} has run on play money for '
                          f'{age / 3600:.1f} h of the {min_age_s / 3600:g} h '
                          'asked — wait, or promote it as a hotfix with its '
                          'reason')
    elif not hotfix.strip():
        raise Refused('a hotfix needs its reason written down')
    return target, current, age


def promote(main, live, ref, hotfix=None, min_age_s=DAY_S, now=None):
    now = time.time() if now is None else now
    target, current, age = plan(main, live, ref, hotfix, min_age_s, now)
    changes = git(main, 'log', '--oneline', f'{current}..{target}')
    git(live, 'checkout', '-q', '--detach', target)
    log = Path(live) / 'logs' / 'promotions.log'
    log.parent.mkdir(exist_ok=True)
    stamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now))
    kind = f'HOTFIX: {hotfix.strip()}' if hotfix else 'promoted'
    ran = 'never' if age is None else f'{age / 3600:.1f} h'
    with open(log, 'a') as f:
        f.write(f'{stamp} {current[:7]} -> {target[:7]} {kind} '
                f'(ran on play money: {ran})\n')
    return target, current, changes


def status(main, live, now=None):
    now = time.time() if now is None else now
    current = resolve(live, 'HEAD')
    merged = resolve(main, 'origin/main')
    out = [f'live copy on {git(live, "log", "-1", "--format=%h %s")}']
    pending = git(main, 'log', '--format=%H %h %s', f'{current}..{merged}')
    if not pending:
        out.append('nothing waiting: the live copy is on the merged main')
    for line in pending.splitlines():
        sha, short, subject = line.split(' ', 2)
        seen = first_seen(main, sha)
        when = ('not yet deployed to play money' if seen is None
                else f'on play money {(now - seen) / 3600:.1f} h')
        out.append(f'  waiting {short} {subject[:60]} — {when}')
    return '\n'.join(out)


def main(argv):
    main_dir = Path(__file__).resolve().parents[1]
    live = Path(os.environ.get('GG_LIVE_DIR') or f'{main_dir}-live')
    if not (live / '.git').exists():
        print(f'no live copy at {live} — ops/README.md says how to make it')
        return 2
    try:
        if argv == ['--status']:
            print(status(main_dir, live))
            return 0
        if not argv or argv[0].startswith('-'):
            print(__doc__.strip().split('\n\n')[-2])
            return 2
        hotfix = None
        if '--hotfix' in argv:
            i = argv.index('--hotfix')
            hotfix = argv[i + 1] if len(argv) > i + 1 else ''
        git(main_dir, 'fetch', '-q', 'origin')
        target, current, changes = promote(main_dir, live, argv[0], hotfix)
    except Refused as e:
        print(f'refused: {e}')
        return 1
    print(f'live copy moved {current[:7]} -> {target[:7]}'
          + (' (HOTFIX)' if hotfix else ''))
    print(changes or '(no commits between)')
    print('the live fleet takes it at its next restart — restart it when '
          'you are watching')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
