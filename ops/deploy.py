"""D94: the deploy, on the box, in the checkout — git's fast-forward made
safe beside the panel's own edits.

  python3 ops/deploy.py [--dry]            # then: systemctl --user restart gg-panel

A plain `git pull --ff-only` refuses the whole deploy when any arriving file
was edited here — even when the edit is exactly what is arriving (the panel
wrote it, then it was taken into the repository). Here, for every file
edited in this checkout:

- arriving, and already the same as what arrives: staged, so the
  fast-forward passes — never reset first (a running fleet re-reads its
  config, and must not see the old terms for a moment);
- arriving, and different: the deploy is refused, nothing changed, the
  files named — take them first (ops/take_box_configs.py);
- not arriving: left as it is, and named.

Prints what it did; exit 1 on a refusal.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from gridgremlin.drift import edited_here, git  # noqa: E402

REMOTE = 'origin/main'


def _arriving(root, path, run):
    """The arriving content of `path`, or None when the arriving tree has no such file."""
    code, out = git(root, 'show', f'{REMOTE}:{path}', run=run)
    return out if code == 0 else None


def plan(root, run):
    """{'stage': [...], 'refuse': [...], 'keep': [...], 'incoming': [...]} — reads only."""
    code, out = git(root, 'diff', '--name-only', 'HEAD', REMOTE, run=run)
    if code != 0:
        raise SystemExit(f'deploy: cannot compare with {REMOTE}')
    incoming = set(out.split())
    stage, refuse, keep = [], [], []
    for status, path in edited_here(root, paths=(), run=run):
        if path not in incoming:
            keep.append(path)
            continue
        here_p = Path(root) / path
        here = here_p.read_text() if here_p.exists() else None
        (stage if here == _arriving(root, path, run) else refuse).append(path)
    return {'stage': stage, 'refuse': refuse, 'keep': keep, 'incoming': sorted(incoming)}


def deploy(root, run, dry=False, log=print):
    code, _ = git(root, 'fetch', '-q', 'origin', 'main', run=run)
    if code != 0:
        log('deploy: the fetch failed — nothing changed')
        return 1
    p = plan(root, run)
    if p['refuse']:
        log('deploy REFUSED — nothing changed. Edited here and arriving different: '
            + ', '.join(p['refuse']) + '. Take them into the repository first '
            '(python3 ops/take_box_configs.py on the workstation), merge, then deploy.')
        return 1
    _, old = git(root, 'rev-parse', '--short', 'HEAD', run=run)
    _, new = git(root, 'rev-parse', '--short', REMOTE, run=run)
    old, new = old.strip(), new.strip()
    if dry:
        log(f'deploy (dry): {old}..{new}, {len(p["incoming"])} files; would stage {p["stage"] or "none"}; '
            f'edited here, not arriving: {p["keep"] or "none"}')
        return 0
    for path in p['stage']:
        git(root, 'add', '-A', '--', path, run=run)
    code, _ = git(root, 'merge', '-q', '--ff-only', REMOTE, run=run)
    if code != 0:
        for path in p['stage']:
            git(root, 'reset', '-q', '--', path, run=run)    # as found
        log('deploy: the fast-forward failed — nothing changed (is main ahead here, or diverged?)')
        return 1
    log(f'deployed {old}..{new}: {len(p["incoming"])} files'
        + (f'; already in git, let through: {", ".join(p["stage"])}' if p['stage'] else '')
        + (f'; still edited here, not in git: {", ".join(p["keep"])}' if p['keep'] else ''))
    return 0


def main(argv):
    import subprocess
    return deploy(HERE, subprocess.run, dry='--dry' in argv)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
