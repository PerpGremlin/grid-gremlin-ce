# The slide state (SPEC G22): the SECOND narrow local durable fact E3
# permits, beside tombstones. The exchange cannot express "this bot's window
# is k rungs from home" — resting orders reveal it only while they rest.
# Persisted BEFORE the orders move (a crash mid-slide resumes at the new
# window, whose orders may already rest); missing means home, which is safe
# (orders outside home are cancelled and re-planned: a lost ratchet, never
# lost money); unreadable fails CLOSED like a tombstone file.
import json
from pathlib import Path

from .durable import locked, write_json


class SlideStateError(Exception):
    pass


def _read(path):
    try:
        rows = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise SlideStateError(
            f'{path}: unreadable ({e}) — fix or delete it, deliberately; '
            'refusing to build rather than guess every window') from e
    if not isinstance(rows, dict) or any(
            not isinstance(v, int) or isinstance(v, bool)
            for v in rows.values()):
        raise SlideStateError(f'{path}: malformed — offsets must be integers')
    return rows


class SlideState:
    def __init__(self, path):
        self.path = Path(path)
        self._rows = _read(self.path)

    def get(self, botid):
        return int(self._rows.get(botid, 0))

    def set(self, botid, offset):
        """Durable before returning — the caller moves orders only after this.
        Under the file's lock and re-read inside it, as the tombstones are
        (X7b): rows held since the build would write back over another
        writer's — the 2026-10-08 clobber, one file for two fleets."""
        with locked(self.path):
            try:
                rows = _read(self.path)
            except SlideStateError:
                rows = dict(self._rows)     # sliding beats bookkeeping (G22)
            rows[botid] = int(offset)
            write_json(self.path, rows)
        self._rows = rows
