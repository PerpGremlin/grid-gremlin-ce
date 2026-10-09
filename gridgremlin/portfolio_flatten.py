"""The owner's flatten of a portfolio row (D78): every leg together in one
act — the shorts bought back, the stack sold — the loan repaid by the
sales, the venue read back after. With --reset the row's book and its
tombstone are removed so the next start is a first sight: a fresh anchor,
the capital in cash. Stop the fleet first; the row's lock is per process.

  python3 -m gridgremlin.portfolio_flatten <fleet.json> <name> [--reset]
"""
import json
import sys
from pathlib import Path


def main(argv):
    reset = '--reset' in argv
    argv = [a for a in argv if a != '--reset']
    if len(argv) != 2:
        print(__doc__.strip())
        return 2
    fleet_path, name = argv
    from .config import validate_fleet
    from .events import Notifier
    from .exchange.bybit.client import WriteClient
    from .exchange.env import load_env, select_account
    from .main import _logs_dir, build_portfolio, fleet_running
    from .portfolio_state import PortfolioState
    from .tombstones import Tombstones, path_for, remove
    load_env()
    fleet = validate_fleet(json.loads(Path(fleet_path).read_text()))
    select_account(fleet['account'])
    if fleet_running(fleet_path, {c['venue'] for c in fleet['bots']}, fleet['account']):
        print('the fleet is running on this file — stop it first (one process per account)')
        return 1
    rows = [c for c in fleet['bots'] if c.get('strategy') == 'portfolio' and c['name'] == name]
    if not rows:
        print(f'no portfolio row named {name}')
        return 2
    cfg = rows[0]
    logs = _logs_dir(fleet_path)
    state = PortfolioState(str(logs / 'portfolio_state.json'))
    tombs = Tombstones(str(path_for(fleet_path, fleet)))
    client = WriteClient()
    if client.env == 'mainnet':
        print('mainnet: not from here (D25)')
        return 1
    bot, _ = build_portfolio(cfg, client, Notifier(sink=print), state, tombs)
    after = bot.flatten_now('flattened by the owner', tombstone=not reset)
    print('after: ' + ', '.join(f'{c} {q:,.6g}' for c, q in after.items()))
    if reset:
        state.forget(bot.botid)
        remove(tombs.path, bot.botid)
        print(f'{bot.botid}: book and tombstone reset — the next start is a first sight')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
