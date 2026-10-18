"""U92: one thing to start — the launcher, a fixed address, a key that lasts."""
import http.client
import os
import socket
import tempfile
from pathlib import Path


def spec_U92_the_launcher_starts_the_panel_on_a_fixed_address_and_opens_it():
    """The owner (2026-10-15): "do 1 2 and 3, linux for now" — the browser
    opens itself, the address stays the same (a fixed port and a saved key,
    so a bookmark works), and one file to double-click. The doctor reports
    and never stops the start; a second start while the panel runs only
    opens the browser; --desktop adds a menu entry. Sabotage: dropping the
    saved key from the command gives a new address every start."""
    from panel.launch import PORT, TOKEN_FILE, desktop_entry, fleet_arg, main, panel_command, saved_key
    root = Path(tempfile.mkdtemp())
    (root / 'configs').mkdir()
    assert fleet_arg([], root) == 'configs/mine.json'                  # nothing yet: the panel offers init
    (root / 'configs' / 'fleet.demo.json').write_text('{}')
    assert fleet_arg([], root) == 'configs/fleet.demo.json'
    assert fleet_arg(['configs/x.json'], root) == 'configs/x.json'
    cmd = panel_command('configs/x.json', PORT, root)
    assert cmd[1:4] == ['-m', 'panel.server', 'configs/x.json']
    for part in ('--supervise', '--open', str(PORT), str(root / TOKEN_FILE)):
        assert part in cmd, part
    assert cmd[cmd.index('--token-file') + 1] == str(root / TOKEN_FILE)
    ran, opened = [], []
    def broken_doctor():
        raise OSError('no network')
    with socket.socket() as s:                                       # a free port, then released
        s.bind(('127.0.0.1', 0))
        free = s.getsockname()[1]
    assert main(['--port', str(free)], root=root, opener=opened.append,
                run=lambda c, cwd: ran.append((c, cwd)) or 0, doctor=broken_doctor) == 0
    assert ran and ran[0][1] == str(root) and str(free) in ran[0][0] and not opened
    with socket.socket() as busy:                                    # already running: open it, start nothing
        busy.bind(('127.0.0.1', 0))
        busy.listen()
        port = busy.getsockname()[1]
        ran.clear()
        assert main(['--port', str(port)], root=root, opener=opened.append, run=ran.append) == 0
        assert opened == [f'http://127.0.0.1:{port}/' + saved_key(root)] and not ran   # P8
    entry = desktop_entry(root)
    assert f'Exec="{root / "grid-gremlin"}"' in entry and 'Terminal=true' in entry and 'Name=grid-gremlin' in entry
    old = os.environ.get('XDG_DATA_HOME')
    os.environ['XDG_DATA_HOME'] = str(root / 'share')
    try:
        assert main(['--desktop'], root=root) == 0
        assert (root / 'share' / 'applications' / 'grid-gremlin.desktop').read_text() == entry
    finally:
        if old is None:
            del os.environ['XDG_DATA_HOME']
        else:
            os.environ['XDG_DATA_HOME'] = old
    here = Path(__file__).resolve().parents[1] / 'grid-gremlin'
    assert here.exists() and os.access(here, os.X_OK) and 'panel.launch' in here.read_text()


def spec_U92_a_saved_key_keeps_its_cookie_so_a_bookmark_works():
    """With a saved key (--token-file) the cookie lasts 30 days, so the
    plain address works after the browser restarts; a key made for one
    launch keeps the session cookie it always had."""
    from spec_panel import CONTRACT, _serve
    from panel.server import Handler
    for keep, want in ((False, None), (True, 'Max-Age=2592000')):
        Handler.keep_cookie = keep
        srv, base = _serve(CONTRACT)
        try:
            host, port = base.split('//')[1].split(':')
            c = http.client.HTTPConnection(host, int(port))
            c.request('GET', '/?t=tok123')
            cookie = c.getresponse().getheader('Set-Cookie')
            assert cookie.startswith('gg=tok123; HttpOnly; SameSite=Strict')
            assert (want in cookie) if want else ('Max-Age' not in cookie)
        finally:
            srv.shutdown()
            Handler.keep_cookie = False
