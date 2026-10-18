"""The panel, phase View — a localhost window onto the readout's contract.

Security floor (docs/archive/DASHBOARD.md §5): binds 127.0.0.1 on a random port;
a per-launch token is exchanged for a cookie on first load; the exact Host
is allowlisted (defeats DNS rebinding); no CORS headers exist; keys do not
exist here — this process holds no venue secret. It does write: fleet and
watchdog files (U19), tombstone revives (X7b), unit starts and stops (§12),
and a stopped bot's close — the last through the engine's own command as a
child process (X15), so the keys stay in the child.

    python3 -m panel.server <fleet.json> [--hours N]

Data is the engine's own contract (report --json). One shape, every
renderer: this page can never disagree with the terminal readout.
"""

import sys
import secrets
import json
import http.server
from pathlib import Path

from .css import (CSS)  # noqa: F401
from .reference import (KEEP_JS, KEY, STATE_WORDS, TRADING)  # noqa: F401
from .table import COLS, section
from .html_bits import REFRESH_S, WATCHDOG_OFF_S, _day, _num_cls, coin_of, money, named, refusal_box, tidy, units_of
from .nav import SIZE_VIEWS, VIEWS, grouped, nav_panel
from gridgremlin.report import contract_tiers
from .strip_view import TIER_NAMES, exchange_leverage, exchange_since_first, hero_strip, tier_badge, venue_money
from .card import _plain_name, _side_tag, card, holding_html, kind_line, ladder_box, orders_line, pnl_parts, settle, since_first_line, since_first_total, state_tag
from .fleet_bits import _row_note, setup_button, sweep_html, sweep_note, windows_html
from .render import cards_section, render
from .drawings import strip  # noqa: F401
from .forms import (BACK, FORM, curve_svg, next_step_html, other_half_html, other_side_html, rehearse_bot_form, rehearse_form, unit_for_fleet, unit_refusal, verdict, waiting_for_restart)  # noqa: F401
from .routes import (CACHE_TTL_S, Handler)  # noqa: F401
from gridgremlin.config import fleet_label

def main(argv):
    if '--hours' in argv:
        i = argv.index('--hours')
        Handler.hours = float(argv[i + 1])
        del argv[i:i + 2]
    if '--units' in argv:
        i = argv.index('--units')
        Handler.units = tuple(argv[i + 1].split(','))
        del argv[i:i + 2]
    port = 0
    if '--port' in argv:
        port = int(argv[argv.index('--port') + 1])
    if '--supervise' in argv:
        Handler.supervise = True
        argv.remove('--supervise')
    if '--token-file' in argv:
        # the persistent-session variant: token survives restarts, stored
        # like a key (0600, refuse looser — the engine's own rule)
        tf = Path(argv[argv.index('--token-file') + 1])
        if tf.exists():
            mode = tf.stat().st_mode & 0o077
            if mode:
                print(f'refusing {tf}: group/other-readable', flush=True)
                return 1
            Handler.token = tf.read_text().strip()
        else:
            Handler.token = secrets.token_urlsafe(16)
            tf.touch(mode=0o600)
            tf.write_text(Handler.token)
        Handler.keep_cookie = True      # U92: a saved key keeps its cookie, so a bookmark works
    else:
        Handler.token = secrets.token_urlsafe(16)
    Handler.fleets = tuple(a for a in argv if a.endswith('.json'))
    Handler.labels = tuple(fleet_label(f) for f in Handler.fleets)
    if not Handler.fleets:
        print('usage: python3 -m panel.server <fleet.json>... '
              '[--hours N] [--port P] [--token-file F] [--units a,b]')
        return 2
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', port), Handler)
    Handler.host_ok = f'127.0.0.1:{srv.server_port}'
    url = f'http://{Handler.host_ok}/?t={Handler.token}'
    tf = argv[argv.index('--token-file') + 1] if '--token-file' in argv else None
    print(start_line(Handler.host_ok, Handler.token, tf, sys.stdout.isatty()),
          flush=True)                    # journald/pipes: the line must not sit in a buffer
    if '--open' in argv:                 # U92: the launcher opens the browser on it
        import threading
        import webbrowser
        threading.Timer(0.5, webbrowser.open, (url,)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        return 0

def start_line(host, token, token_file, tty):
    """P8: what the panel prints as it starts. A saved key never goes to the
    system log on every start (the audit, 2026-10-16): under a service the
    line names the token file instead; a terminal, or a one-off key that
    lives nowhere else, still shows the whole address."""
    if token_file and not tty:
        return (f'panel: http://{host}/ — the key is in its token file '
                f'({Path(token_file).name}); open /?t=<key> once')
    return f'panel: http://{host}/?t={token}'


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
