# The portfolio row's state (D78, SPEC H2): the third narrow local durable
# fact beside tombstones (X7) and the slide state (G22). The exchange
# cannot say which coins in a shared wallet are this row's, when its clock
# last ticked, what funding it has received and not yet spent, or the
# value it is judged against — the row keeps that, written atomically
# under the file's lock after every cycle that changed it. Missing means
# a row never seen: it starts from its capital. Unreadable fails CLOSED.
import json
from pathlib import Path

from .durable import locked, write_json


class PortfolioStateError(Exception):
    pass


def _read(path):
    try:
        rows = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise PortfolioStateError(
            f'{path}: unreadable ({e}) — fix or delete it, deliberately; '
            'refusing to build rather than guess every book') from e
    if not isinstance(rows, dict) or any(not isinstance(v, dict) for v in rows.values()):
        raise PortfolioStateError(f'{path}: malformed — one object per row')
    return rows


class PortfolioState:
    """One file per fleet (X7b's rule) and every write re-read under the
    lock: two fleets on one file each wrote back the other's row as it was
    at their own start (2026-10-09, the second subaccount's first hour)."""

    def __init__(self, path):
        self.path = Path(path)
        self._rows = _read(self.path)

    def get(self, botid):
        return dict(self._rows.get(botid) or {})

    def _change(self, fn):
        with locked(self.path):
            try:
                rows = _read(self.path)
            except PortfolioStateError:
                rows = dict(self._rows)        # the book beats bookkeeping
            fn(rows)
            write_json(self.path, rows)
        self._rows = rows

    def forget(self, botid):
        """The row's book removed, durably: the next start is a first sight."""
        self._change(lambda rows: rows.pop(botid, None))

    def set(self, botid, row):
        """Durable before returning — the next cycle reads what this one knew."""
        self._change(lambda rows: rows.__setitem__(botid, dict(row)))
