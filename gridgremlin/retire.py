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
        if cfg['venue'] == 'hyperliquid':
            from .exchange.hyperliquid.adapters import HLPerpAdapter
            from .exchange.hyperliquid.truth import parse_instrument as hl_pi
            from .exchange.hyperliquid.venue import HLVenueClient
            client = HLVenueClient(allow_mainnet=False)
            refuse_mainnet(client, False, False)
            adapter = HLPerpAdapter(hl_pi(client._entry(cfg['symbol'])[1]))
        else:
            from .adapters import adapter_for
            from .exchange.bybit.client import WriteClient
            from .exchange.bybit.truth import parse_instrument
            client = WriteClient()
            refuse_mainnet(client, False, False)
            adapter = adapter_for(cfg['market_type'], parse_instrument(
                cfg['market_type'], client.instruments_info(cfg['market_type'], cfg['symbol'])))
        out = retire_bot(cfg, client, adapter, tombs, 'retired by the owner (D92)', dry=dry)
    except Exception as e:                                   # noqa: BLE001
        out = {'refused': f'{type(e).__name__}: {e}'}
    print(json.dumps(out))
    return 1 if 'refused' in out else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
