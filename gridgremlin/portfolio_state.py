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


class PortfolioState:
    def __init__(self, path):
        self.path = Path(path)
        try:
            self._rows = json.loads(self.path.read_text())
        except FileNotFoundError:
            self._rows = {}
        except (OSError, ValueError) as e:
            raise PortfolioStateError(
                f'{path}: unreadable ({e}) — fix or delete it, deliberately; '
                'refusing to build rather than guess every book') from e
        if not isinstance(self._rows, dict) or any(
                not isinstance(v, dict) for v in self._rows.values()):
            raise PortfolioStateError(f'{path}: malformed — one object per row')

    def get(self, botid):
        return dict(self._rows.get(botid) or {})

    def set(self, botid, row):
        """Durable before returning — the next cycle reads what this one knew."""
        self._rows[botid] = dict(row)
        with locked(self.path):
            write_json(self.path, self._rows)
