# What the checkout holds that git has not got (SPEC F31, D94).
#
# The panel writes fleet files on the box by design (create, edit, remove);
# git never sees those writes until they are taken into the repository. The
# panel names them on its front page, the deploy (ops/deploy.py) lets
# through the ones git already agrees with and refuses the rest, and
# ops/take_box_configs.py brings them home as a PR.
import html
import subprocess


def git(root, *args, run=subprocess.run):
    """One git call in `root`: (exit code, stdout)."""
    r = run(['git', '-C', str(root), *args], capture_output=True, text=True)
    return r.returncode, r.stdout


def edited_here(root, paths=('configs',), run=subprocess.run):
    """[(status, path)] — tracked files changed or deleted and new files not
    ignored, under `paths` (all of the checkout when `paths` is empty).
    `status` is git's two-letter porcelain code ('M', 'D', '??' …, stripped).
    An unreadable checkout answers [] — the panel says nothing rather than
    something wrong."""
    code, out = git(root, 'status', '--porcelain=v1', '--untracked-files=all', '--', *paths, run=run)
    if code != 0:
        return []
    rows = []
    for line in out.splitlines():
        if len(line) > 3:
            rows.append((line[:2].strip(), line[3:].strip().strip('"')))
    return rows


def notice(rows):
    """The panel's one line about them, or '' when there are none."""
    if not rows:
        return ''
    names = ', '.join(html.escape(p.split('/')[-1]) for _, p in rows[:6]) + (' …' if len(rows) > 6 else '')
    return (f'{len(rows)} config file{"s" if len(rows) != 1 else ""} edited here and not in git yet '
            f'({names}). Take them into the repository before the next config change there: '
            f'<code>python3 ops/take_box_configs.py</code> on the workstation (D94).')
