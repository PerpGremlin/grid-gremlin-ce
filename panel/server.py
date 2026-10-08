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
from .render import (COLS, REFRESH_S, SIZE_VIEWS, TIER_NAMES, VIEWS, WATCHDOG_OFF_S, _day, _num_cls, _plain_name, _row_note, _side_tag, card, cards_section, coin_of, contract_tiers, exchange_leverage, exchange_since_first, grouped, hero_strip, holding_html, kind_line, ladder_box, money, named, nav_panel, orders_line, pnl_parts, refusal_box, render, section, settle, setup_button, since_first_line, since_first_total, state_tag, strip, sweep_html, sweep_note, tidy, tier_badge, units_of, venue_money, windows_html)  # noqa: F401
from .forms import (BACK, FORM, curve_svg, next_step_html, other_half_html, other_side_html, rehearse_bot_form, rehearse_form, unit_for_fleet, unit_refusal, verdict, waiting_for_restart)  # noqa: F401
from .routes import (CACHE_TTL_S, Handler)  # noqa: F401

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
    else:
        Handler.token = secrets.token_urlsafe(16)
    Handler.fleets = tuple(a for a in argv if a.endswith('.json'))
    def _label(f):
        stem = Path(f).stem.replace('fleet.', '')
        try:
            bots = json.loads(Path(f).read_text()).get('bots') or []
            venue = bots[0].get('venue', 'bybit') if bots else None
        except (OSError, ValueError):
            venue = None
        if not venue:
            return stem
        # venue first, plus the stem's final token — the environment word
        # (demo, testnet, mine); abbreviations like 'hl' never survive
        return f"{venue} {stem.split('.')[-1]}"
    Handler.labels = tuple(_label(f) for f in Handler.fleets)
    if not Handler.fleets:
        print('usage: python3 -m panel.server <fleet.json>... '
              '[--hours N] [--port P] [--token-file F] [--units a,b]')
        return 2
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', port), Handler)
    Handler.host_ok = f'127.0.0.1:{srv.server_port}'
    print(f'panel: http://{Handler.host_ok}/?t={Handler.token}',
          flush=True)   # journald/pipes: the URL must not sit in a buffer
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
