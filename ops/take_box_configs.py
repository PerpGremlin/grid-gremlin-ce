"""D94: bring the panel's edits on the box home — run on the workstation.

  python3 ops/take_box_configs.py <ssh host> <checkout on the box>

Reads, never writes, the box: the config files its checkout has changed,
added or deleted (git's own view there), copied into this tree's configs/.
Then review, run the suite (U19 round-trips every row) and open the PR as
for any config change; once merged, the deploy lets them through (staged as
already in git). Refuses when this tree's configs/ has edits of its own.
"""
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from gridgremlin.drift import edited_here  # noqa: E402


def take(host, box_root, local_root, ssh):
    """`ssh(host, command)` -> (exit code, stdout). Returns [(status, path)] taken."""
    if edited_here(local_root):
        raise SystemExit('take: this tree has config edits of its own — commit or drop them first')
    q = shlex.quote(box_root)
    code, out = ssh(host, f'git -C {q} status --porcelain=v1 --untracked-files=all -- configs')
    if code != 0:
        raise SystemExit(f'take: could not read the box ({host})')
    rows = [(ln[:2].strip(), ln[3:].strip().strip('"')) for ln in out.splitlines() if len(ln) > 3]
    for status, path in rows:
        if not path.startswith('configs/') or '..' in path:
            raise SystemExit(f'take: refusing a path outside configs/: {path}')
        dest = Path(local_root) / path
        if status == 'D':
            if dest.exists():
                dest.unlink()
            continue
        code, text = ssh(host, f'cat {shlex.quote(box_root + "/" + path)}')
        if code != 0:
            raise SystemExit(f'take: could not read {path}')
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text)
    return rows


def _ssh(host, command):
    r = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ClearAllForwardings=yes', host, command],
                       capture_output=True, text=True)
    return r.returncode, r.stdout


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[2].strip())
        return 2
    rows = take(argv[0], argv[1], HERE, _ssh)
    if not rows:
        print('take: the box has no config edits — nothing to take')
        return 0
    for status, path in rows:
        print(f'  {status:>2} {path}')
    print(f'take: {len(rows)} taken into configs/ — review with git diff, run the suite, open the PR')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
