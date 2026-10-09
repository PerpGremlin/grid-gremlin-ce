# Tombstones (SPEC X7): the ONE narrow local durable fact E3 permits.
# The exchange cannot express "this bot's stop fired" — a flat position is
# indistinguishable from a fresh start — so D1's prevents-restart clause
# needs a file. Persisted BEFORE the flatten (a crash mid-stop still refuses
# revival); removal is a deliberate operator act, never automatic.
import json
import time
from pathlib import Path

from .durable import locked, write_json


class TombstoneError(Exception):
    pass


def _read(path):
    try:
        rows = json.loads(Path(path).read_text() or '{}')
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        # fail CLOSED: a corrupt/unreadable tombstone file must never
        # silently revive stop-fired bots (the audit's M3)
        raise TombstoneError(
            f'{path}: unreadable ({e}) — fix or delete it, deliberately; '
            'refusing to build rather than revive stopped bots') from e
    if not isinstance(rows, dict):
        raise TombstoneError(f'{path}: malformed — an object of botid rows')
    return rows


class Tombstones:
    def __init__(self, path):
        self.path = Path(path)
        self._rows = _read(self.path)

    def has(self, botid):
        return botid in self._rows

    def reason(self, botid):
        return (self._rows.get(botid) or {}).get('reason', '')

    def add(self, botid, reason):
        """Durable before returning — the caller flattens only after this.
        Under the file's lock and re-read inside it: the panel's revive is
        the other writer, and rewriting from rows held since the build
        undid a revive, or lost a stop's row to one (audit 2026-10-05)."""
        row = {'reason': reason, 't': int(time.time())}
        with locked(self.path):
            try:
                rows = _read(self.path)
            except TombstoneError:
                rows = dict(self._rows)    # stopping beats bookkeeping (X7)
            rows[botid] = row
            write_json(self.path, rows)
        self._rows = rows


def remove(path, botid):
    """The operator's revive (X7): the one row out, under the same lock,
    atomically. Returns the removed row, or None when it was not there."""
    with locked(path):
        rows = _read(path)
        gone = rows.pop(botid, None)
        if gone is not None:
            write_json(path, rows)
    return gone


def path_for(fleet_path, fleet_raw):
    """Where a fleet's tombstones live — the fleet's own key, else
    logs/tombstones-<fleet>.json beside its home — the one answer for
    engine, close and panel (durable.state_path)."""
    from .durable import state_path
    return state_path(fleet_path, fleet_raw, 'tombstones')
