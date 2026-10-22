# Retire a bot for good (SPEC X15c, D92).
#   python3 -m gridgremlin.retire <fleet.json> <botid> [--dry]
#
# Taking a bot out of a fleet file leaves its orders resting and its
# position open — the next start no longer owns them. Retiring does the
# three steps in order, with the fleet stopped: the tombstone first (X7: it
# can never revive by a restart in between), every order it owns cancelled
# (I1: by its link prefix, nothing else), then what it holds closed by
# close's own reduce-only market order (X15). Then the row leaves the file
# by a PR, as any config change.
#
# Narrow like close: never mainnet, not spot, never beside its running
# fleet (the running bot would place its orders back). --dry says what it
# would do and does nothing. Prints one JSON object; a refusal is
# {"refused": "..."}.
import json
import sys
from pathlib import Path

from .apply import make_botid, rung_of
from .close import close_position
from .config import ConfigError, market_rows, validate_fleet
from common.env import load_env
from .exchange.errors import VenueError


def retire_bot(cfg, client, adapter, tombs, reason, dry=False):
    """The whole act, venue-neutral and testable: the JSON-able answer."""
    botid = make_botid(cfg['market_type'], cfg['symbol'], cfg['side'])
    if cfg['market_type'] == 'spot':
        return {'refused': f'{botid}: a spot holding is the coins in the '
                           'wallet — retire it by hand on the exchange'}
    truth = client.read_symbol_truth(cfg['market_type'], cfg['symbol'])
    owned = [o for o in truth['orders'] if rung_of(o['link_id'], botid) is not None]
    if dry:
        held = close_position(cfg, client, adapter, True, dry=True)
        return {'botid': botid, 'dry': True, 'orders': len(owned),
                'held': held.get('held', 0.0), 'tombstoned': tombs.has(botid)}
    if not tombs.has(botid):
        tombs.add(botid, reason)                      # X7: first, before any write
    cancelled, failed = 0, []
    for o in owned:
        try:
            client.cancel_order(cfg['market_type'], cfg['symbol'], o['order_id'])
            cancelled += 1
        except VenueError as e:
            failed.append(f"{o['link_id']}: {e}")
    closed = close_position(cfg, client, adapter, True)
    after = client.read_symbol_truth(cfg['market_type'], cfg['symbol'])  # X4: re-read
    left = [o['link_id'] for o in after['orders'] if rung_of(o['link_id'], botid) is not None]
    out = {'botid': botid, 'tombstoned': True, 'cancelled': cancelled,
           'orders_left': left, 'closed': closed.get('closed', 0.0),
           'held_left': closed.get('left', 0.0)}
    if failed:
        out['cancel_failed'] = failed
    return out


# --- D145: retiring from the panel, through the running fleet ----------------
# The panel writes a request into logs/retire-<fleet>.json; the running
# fleet's RetireWatch hands it to the bot, which acts on its next cycle under
# its own links — the same road as a trade's close (L7). Three steps:
#   pause  no new exposure; exits and the stop keep working; resume undoes it
#   hold   stand down: its orders cancelled, the position kept, unprotected
#   close  stand down: its orders cancelled, its whole position closed at market
# A request made while the fleet is stopped is acted on at its next start.
ACTIONS = ('pause', 'hold', 'close')


def requests_path(fleet_path):
    """Where a fleet's retire requests live: logs/retire-<fleet>.json."""
    from .durable import fleet_tag, logs_dir
    return logs_dir(fleet_path) / f'retire-{fleet_tag(fleet_path)}.json'


def load_requests(path):
    """{botid: {action, t, by, reason, remove}}; none when there is no file."""
    try:
        got = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {}
    return got if isinstance(got, dict) else {}


def request(path, botid, action, by, reason='', remove=False):
    """Ask the fleet to retire one bot. A pause may become a stand-down; a
    stand-down stands (the first wins, as L7's). Returns the request in force."""
    from common.files import write_json
    from common.fmt import utc_stamp
    from .durable import locked
    if action not in ACTIONS:
        raise ConfigError(f'{action!r}: retire is one of {", ".join(ACTIONS)}')
    if remove and action == 'pause':
        raise ConfigError('a paused bot stays in the fleet — remove goes with a stand-down')
    with locked(path):
        reqs = load_requests(path)
        was = reqs.get(botid)
        if was and was.get('action') != 'pause':
            return was
        reqs[botid] = {'action': action, 't': utc_stamp(), 'by': str(by),
                       'reason': str(reason or '')[:200], 'remove': bool(remove)}
        write_json(path, reqs)
        return reqs[botid]


def drop(path, botid, only_pause=False):
    """Take a bot's request out: resume (`only_pause`), or after its row has
    left the fleet. True when one was taken out."""
    from common.files import write_json
    from .durable import locked
    with locked(path):
        reqs = load_requests(path)
        was = reqs.get(botid)
        if not was or (only_pause and was.get('action') != 'pause'):
            return False
        del reqs[botid]
        write_json(path, reqs)
        return True


class RetireWatch:
    """D145: notices the requests file changing (by mtime, one stat a cycle)
    and hands each request to its running bot — a pause set or lifted, a
    stand-down once. Read at start too, so a request made before a restart
    stands. Portfolio rows are not retired here (they have no such bot)."""

    def __init__(self, path, bots, notifier):
        self.path, self.bots, self.notifier = Path(path), bots, notifier
        self.mtime = False
        self.poll()

    def poll(self):
        try:
            m = self.path.stat().st_mtime
        except OSError:
            m = None
        if m == self.mtime:
            return
        self.mtime = m
        reqs = load_requests(self.path) if m is not None else {}
        for bot in self.bots:
            if not hasattr(bot, 'retire_request') or not bot.alive:
                continue
            r = reqs.get(bot.botid) or {}
            if r.get('action') == 'pause' and not bot.paused:
                bot.paused = r
                self.notifier.event('stop', bot.botid, f"paused by {r.get('by')}: no new exposure; "
                                                       'exits and the stop keep working (D145)')
            elif r.get('action') != 'pause' and bot.paused:
                bot.paused = None
                self.notifier.event('stop', bot.botid, 'resumed (D145)')
            if r.get('action') in ('hold', 'close') and bot.retire_request is None:
                bot.retire_request = r
                self.notifier.event('stop', bot.botid, f"retire requested by {r.get('by')}: "
                                    + ('cancelling its orders and closing its position at market'
                                       if r['action'] == 'close' else
                                       'cancelling its orders, keeping its position')
                                    + ' this cycle (D145)')


def open_venue(cfg, clients=None):
    """The row's venue client (never mainnet) and its instrument adapter.
    `clients` caches one client per venue for a caller retiring many rows."""
    from .main import refuse_mainnet
    clients = {} if clients is None else clients
    if cfg['venue'] == 'hyperliquid':
        from .exchange.hyperliquid.adapters import HLPerpAdapter
        from .exchange.hyperliquid.truth import parse_instrument as hl_pi
        from .exchange.hyperliquid.venue import HLVenueClient
        if 'hyperliquid' not in clients:
            clients['hyperliquid'] = HLVenueClient(allow_mainnet=False)
            refuse_mainnet(clients['hyperliquid'], False, False)
        client = clients['hyperliquid']
        return client, HLPerpAdapter(hl_pi(client._entry(cfg['symbol'])[1]))
    from .adapters import adapter_for
    from .exchange.bybit.client import WriteClient
    from .exchange.bybit.truth import parse_instrument
    if 'bybit' not in clients:
        clients['bybit'] = WriteClient()
        refuse_mainnet(clients['bybit'], False, False)
    client = clients['bybit']
    return client, adapter_for(cfg['market_type'], parse_instrument(
        cfg['market_type'], client.instruments_info(cfg['market_type'], cfg['symbol'])))


def main(argv):
    dry = '--dry' in argv
    argv = [a for a in argv if a != '--dry']
    if len(argv) != 2:
        print('usage: python3 -m gridgremlin.retire <fleet.json> <botid> [--dry]')
        return 2
    fleet_path, botid = argv
    try:
        load_env()
        fleet = validate_fleet(json.loads(Path(fleet_path).read_text()))
        from .exchange.env import select_account
        select_account(fleet['account'])              # H5
        cfg = next((b for b in market_rows(fleet) if make_botid(
            b['market_type'], b['symbol'], b['side']) == botid), None)
        if cfg is None:
            raise ConfigError(f'{botid}: not in this fleet')
        from .main import fleet_running, refuse_mainnet
        if fleet_running(fleet_path, {c['venue'] for c in fleet['bots']}, fleet['account']):
            raise ConfigError('the fleet is running on this file — stop it first: '
                              'the running bot would place its orders back')
        from .tombstones import Tombstones, path_for
        tombs = Tombstones(str(path_for(fleet_path, fleet)))
        client, adapter = open_venue(cfg)
        out = retire_bot(cfg, client, adapter, tombs, 'retired by the owner (D92)', dry=dry)
    except Exception as e:                                   # noqa: BLE001
        out = {'refused': f'{type(e).__name__}: {e}'}
    print(json.dumps(out))
    return 1 if 'refused' in out else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
