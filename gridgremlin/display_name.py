# A Hyperliquid account's display name, shown on HL's leaderboard (D182).
#   python3 -m gridgremlin.display_name <fleet.json> NAME [--env PATH]
#                                       [--allow-mainnet]
#
# One signed `setDisplayName` action, sent by the fleet's own signer for the
# fleet's own account. NAME is at most 20 characters; '' removes the name.
# - Mainnet only with both of D25's halves: the fleet file's switch and
#   `--allow-mainnet` typed on this command.
# - Refused while the fleet runs: on Hyperliquid one process signs for a
#   wallet at a time (X15b). Stop the fleet, run this, start it.
# - `--env` reads that copy's keys file (the real-money copy is pinned, so
#   this runs from the main copy with the live copy's .env).
# Prints one JSON object; a refusal is {"refused": "..."}.
import json
import sys
from pathlib import Path

from common.env import load_env
from .config import ConfigError, validate_fleet

MAX_LEN = 20                       # HL's own limit


def check_name(name):
    """The name HL accepts, or a refusal in words."""
    if not isinstance(name, str):
        raise ConfigError('the display name is text')
    if len(name) > MAX_LEN:
        raise ConfigError(f'{name!r} is {len(name)} characters; Hyperliquid '
                          f'takes at most {MAX_LEN}')
    if name != name.strip():
        raise ConfigError(f'{name!r} starts or ends with a space')
    return name


def set_display_name(client, name):
    """Send the action; the venue's answer, or HLError raised by the client."""
    client._post_action({'type': 'setDisplayName',
                         'displayName': check_name(name)})
    return {'account': client.address, 'network': client.env,
            'display_name': name or None}


def main(argv):
    armed = '--allow-mainnet' in argv
    argv = [a for a in argv if a != '--allow-mainnet']
    env_path = None
    if '--env' in argv:
        i = argv.index('--env')
        env_path = argv[i + 1] if i + 1 < len(argv) else ''
        del argv[i:i + 2]
    if len(argv) != 2 or env_path == '':
        print('usage: python3 -m gridgremlin.display_name <fleet.json> NAME '
              "[--env PATH] [--allow-mainnet]   (NAME '' removes it)")
        return 2
    fleet_path, name = argv
    try:
        check_name(name)
        if env_path and not Path(env_path).exists():
            raise ConfigError(f'{env_path}: no such keys file')
        load_env(env_path)
        fleet = validate_fleet(json.loads(Path(fleet_path).read_text()))
        if not any(b.get('venue') == 'hyperliquid' for b in fleet['bots']):
            raise ConfigError('this fleet has no Hyperliquid bot; the name is '
                              "a Hyperliquid account's")
        from .exchange.env import select_account
        select_account(fleet['account'])              # H5
        from .main import fleet_running, refuse_mainnet
        if fleet_running(fleet_path, {b.get('venue', 'bybit') for b in fleet['bots']},
                         fleet['account']):
            raise ConfigError('the fleet is running on this file — on '
                              'Hyperliquid one process signs for the wallet '
                              'at a time; stop the fleet, run this, start it '
                              '(X15b)')
        from types import SimpleNamespace
        from .exchange.hyperliquid.client import detect_env
        from .exchange.hyperliquid.exchange import ExchangeClient
        fleet_allows = fleet.get('allow_mainnet') is True
        # D25, both halves, said in words before any client is built
        refuse_mainnet(SimpleNamespace(env=detect_env()), fleet_allows, armed)
        client = ExchangeClient(allow_mainnet=fleet_allows and armed)
        out = set_display_name(client, name)
    except Exception as e:                                   # noqa: BLE001
        out = {'refused': f'{type(e).__name__}: {e}'}
    print(json.dumps(out))
    return 1 if 'refused' in out else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
