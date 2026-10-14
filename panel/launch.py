"""U92: one thing to start — `./grid-gremlin` from the repo root, or a
double-click on it. It runs the doctor (its report only: the panel itself
offers init and set-up when keys or fleets are missing), starts the panel
on a fixed port with a saved key, and opens the browser on it; the address
stays the same between starts, so it can be bookmarked. A second start
while the panel runs only opens the browser. `--desktop` adds it to the
desktop's application menu. Linux first (the owner, 2026-10-15).

    ./grid-gremlin [configs/<fleet>.json] [--port P] [--desktop]
"""
import os
import socket
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = 41960
TOKEN_FILE = '.panel-token'
DEFAULT_FLEETS = ('configs/fleet.demo.json', 'configs/mine.json')


def fleet_arg(argv, root=ROOT):
    """The fleet named, else the demo example, else a new one the panel
    will offer to set up."""
    named = [a for a in argv if a.endswith('.json')]
    if named:
        return named[0]
    for f in DEFAULT_FLEETS:
        if (Path(root) / f).exists():
            return f
    return DEFAULT_FLEETS[-1]


def port_arg(argv):
    return int(argv[argv.index('--port') + 1]) if '--port' in argv else PORT


def in_use(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', port)) == 0


def panel_command(fleet, port, root=ROOT):
    return [sys.executable, '-m', 'panel.server', fleet, '--supervise',
            '--port', str(port), '--token-file', str(Path(root) / TOKEN_FILE), '--open']


def desktop_entry(root=ROOT):
    """A menu entry: it runs in a terminal window, so the panel's lines
    show, and closing that window stops the panel (said in the comment)."""
    return ('[Desktop Entry]\nType=Application\nName=grid-gremlin\n'
            'Comment=grid-gremlin: the panel (close its window to stop it)\n'
            f'Exec="{Path(root) / "grid-gremlin"}"\nPath={Path(root)}\n'
            'Terminal=true\nCategories=Office;Finance;\n')


def main(argv, root=ROOT, opener=webbrowser.open, run=subprocess.call, doctor=None):
    root = Path(root)
    if '--desktop' in argv:
        apps = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share') / 'applications'
        apps.mkdir(parents=True, exist_ok=True)
        (apps / 'grid-gremlin.desktop').write_text(desktop_entry(root))
        print(f'added to the menu: {apps / "grid-gremlin.desktop"}', flush=True)
        return 0
    port = port_arg(argv)
    if in_use(port):
        url = f'http://127.0.0.1:{port}/'
        print(f'grid-gremlin is already running: opening {url}', flush=True)
        opener(url)
        return 0
    if doctor is None:
        from gridgremlin.doctor import run as doctor      # from the repo root: the script starts there
    try:
        text, ok = doctor()
        print(text, flush=True)
        if not ok:
            print('(the panel opens anyway: it can set up what is missing)', flush=True)
    except Exception as e:                       # the doctor must never stop the start
        print(f'doctor: could not run ({type(e).__name__}: {e})', flush=True)
    fleet = fleet_arg(argv, root)
    print(f'starting the panel on {fleet} — bookmark http://127.0.0.1:{port}/ ; '
          'close this window, or press Ctrl+C, to stop it', flush=True)
    return run(panel_command(fleet, port, root), cwd=str(root))


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
