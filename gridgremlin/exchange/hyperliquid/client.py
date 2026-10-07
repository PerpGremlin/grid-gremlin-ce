# HL info client (reads only; writes arrive with promotion, keys stay in v2).
import json
import os
import urllib.error
import urllib.request

from ..errors import VenueError
from ..keepalive import KeepAlive

BASE_URLS = {'mainnet': 'https://api.hyperliquid.xyz',
             'testnet': 'https://api.hyperliquid-testnet.xyz'}


class HLError(VenueError):
    def __init__(self, status, msg, body=None, ambiguous=False, kind='other'):
        super().__init__(msg, kind=kind, ambiguous=ambiguous)
        self.status = status
        self.body = body or ''


def detect_env():
    if os.environ.get('HL_TESTNET', '').lower() == 'true':
        return 'testnet'
    return 'mainnet'


class InfoClient:
    def __init__(self, env=None, address=None, transport=None,
                 allow_mainnet=False):
        self.env = env or detect_env()
        from ...edition import real_money_refused
        if self.env == 'mainnet' and real_money_refused():
            raise VenueError(real_money_refused())        # D68
        if self.env == 'mainnet' and not allow_mainnet:
            raise VenueError('HL mainnet is double-safetied (D25): it needs '
                             '\'"allow_mainnet": true\' in the fleet file AND '
                             '--allow-mainnet on the launch — a bare env flag '
                             'is never enough')
        self.base = BASE_URLS[self.env]
        self.address = address or os.environ.get('HL_ACCOUNT_ADDRESS', '')
        self._transport = transport or self._http
        self._wire = None

    def _http(self, body, retry_429=True):
        # E10: /info is a read — it rides one kept connection
        if self._wire is None:
            self._wire = KeepAlive(timeout=15)
        url, data = self.base + '/info', json.dumps(body).encode()
        headers = {'Content-Type': 'application/json'}
        # the venue's public budget IS the pace (E7): a 429 sleeps up the
        # ladder and takes the cycle late; only a persistent one raises.
        # One 2s retry was not enough under 1s polling (the watch's finding:
        # an isolated 429 every ~15 cycles).
        for wait in (2.0, 4.0, 8.0) if retry_429 else ():
            try:
                return json.loads(self._wire.request('POST', url, headers,
                                                     data)[1].decode())
            except urllib.error.HTTPError as e:
                if e.code != 429:
                    raise
                import time as _t
                _t.sleep(wait)
        return json.loads(self._wire.request('POST', url, headers,
                                             data)[1].decode())

    def _user(self):
        if not self.address:
            raise VenueError('HL_ACCOUNT_ADDRESS is not set — refuse, never '
                             'guess (E8)')
        return self.address

    def meta(self):
        return self._transport({'type': 'meta'})

    def meta_and_ctxs(self):
        return self._transport({'type': 'metaAndAssetCtxs'})

    def l2_book(self, coin):
        return self._transport({'type': 'l2Book', 'coin': coin})

    def clearinghouse_state(self):
        return self._transport({'type': 'clearinghouseState',
                                'user': self._user()})

    def open_orders(self, coin=None):
        return self._transport({'type': 'frontendOpenOrders',
                                'user': self._user()})

    def user_abstraction(self):
        return self._transport({'type': 'userAbstraction',
                                'user': self._user()})

    def user_fills_by_time(self, start_ms, end_ms=None):
        """Venue caps the answer at 2000 fills — the caller must warn (R1),
        or narrow the window until it fits (R18)."""
        body = {'type': 'userFillsByTime', 'user': self._user(),
                'startTime': int(start_ms)}
        if end_ms is not None:
            body['endTime'] = int(end_ms)
        return self._transport(body)

    def user_funding(self, start_ms, end_ms=None):
        """D63: funding settlements, at most a page (500 rows) a call —
        the caller pages by time."""
        body = {'type': 'userFunding', 'user': self._user(),
                'startTime': int(start_ms)}
        if end_ms is not None:
            body['endTime'] = int(end_ms)
        return self._transport(body)

    def spot_clearinghouse_state(self):
        return self._transport({'type': 'spotClearinghouseState',
                                'user': self._user()})

    def _post(self, path, body, retry_429=True):
        """The write transport (stub point for specs)."""
        data = json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data,
                                     headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            text = e.read().decode(errors='replace')[:300]
            if e.code == 429 and retry_429:
                import time as _t
                _t.sleep(2.0)
                return self._post(path, body, retry_429=False)
            raise HLError(e.code, f'{path}: HTTP {e.code}: {text}', text,
                          kind='rate_limit' if e.code == 429 else 'other')
