"""One position, one page (U56), and whether a trade there is still live (L7). Moved out of routes.py whole (D91 step 3): a mixin
the Handler inherits."""
from panel.chart import _f
from pathlib import Path
import json
import time
import urllib.parse


class PositionPages:
    def _position_page(self):
        """U56: one position, one page."""
        from panel.position_view import position_page
        q = dict(urllib.parse.parse_qsl(self.path.split('?', 1)[1]))
        fi = min(int(_f(q.get('fleet')) or 0), len(self.fleets) - 1)
        botid = q.get('bot', '')
        contract = self._contract(self.fleets[fi])
        belief = ((contract.get('watchdog') or {}).get('belief') or {}).get('bots', {})
        if botid not in (contract.get('bots') or {}) and botid not in belief:
            return self._deny(404, f'{botid}: not in this fleet')
        # U65: the price from the fleet's own snapshots, the fills from the kept ledger
        from gridgremlin.durable import fleet_tag, logs_dir
        from gridgremlin.equity_series import bot_fills, price_windows, snapshot_path
        snap = snapshot_path(self.fleets[fi])
        now = time.time()
        try:
            prices = price_windows(snap, botid, now, type(self)._series.setdefault(snap, {})) if snap else None
        except (OSError, ValueError):
            prices = None
        fills = bot_fills(logs_dir(self.fleets[fi]) / 'fills' / f'{fleet_tag(self.fleets[fi])}.json',
                          botid, int((now - 7 * 86400) * 1000))
        return self._page(position_page(fi, self.labels[fi], botid, contract, belief, prices, fills))

    def _pick_pane(self, labelled, q):
        """D96/U78: the front page's right half for `?fleet=N&bot=ID` — the
        bot's fills from the kept ledger, each with what it realised; a bot
        not in that fleet, the empty half."""
        from gridgremlin.durable import fleet_tag, logs_dir
        from gridgremlin.fill_list import fill_list
        from gridgremlin.kept_fills import load
        from panel.detail import detail_pane
        fi = min(max(int(_f(q.get('fleet')) or 0), 0), len(self.fleets) - 1)
        botid = q.get('bot', '')
        label, contract = labelled[fi]
        if botid not in (contract.get('bots') or {}):
            return None
        pos = ((((contract.get('watchdog') or {}).get('belief') or {}).get('bots') or {})
               .get(botid) or {}).get('position')
        try:
            from gridgremlin.config import validate_fleet
            from gridgremlin.trades import with_trades
            fleet = with_trades(self.fleets[fi], validate_fleet(json.loads(Path(self.fleets[fi]).read_text())))  # as the readout reads it (L5)
            kept = load(logs_dir(self.fleets[fi]) / 'fills' / f'{fleet_tag(self.fleets[fi])}.json')
            listing = fill_list(kept, fleet, botid, held=None if pos is None else abs(float(pos)))
        except (OSError, ValueError, RuntimeError, KeyError):
            listing = None
        return detail_pane(fi, label, botid, contract, listing)

    def _live_trade(self, fi, botid):
        """L7: the trades file of fleet `fi` when `botid` is a trade there
        still running (not stood down), else None."""
        from gridgremlin.tombstones import Tombstones, path_for
        from gridgremlin.trades import trade_status, trades_path
        f = self.fleets[min(fi, len(self.fleets) - 1)]
        raw = json.loads(Path(f).read_text())
        path = trades_path(f, raw)
        live = trade_status(path, botid, Tombstones(str(path_for(f, raw)))) == 'live'
        return path if live else None
