# Close what a STOPPED bot left open (SPEC X15, D48).
#   python3 -m gridgremlin.close <fleet.json> <botid> [--dry]
#
# A bot that stood down holding a position — `leave_position` (X13), or a
# flatten the venue only partly filled — leaves a chore: someone has to
# close it by hand on the exchange. This is that hand, in the engine, so
# the keys stay where they are: the panel runs this as a subprocess, the
# way it runs the readout, and still holds none itself.
#
# Deliberately narrow:
# - only a TOMBSTONED bot. A live bot manages its own position; closing it
#   from outside is exactly the outside hand S7 stands a bot down for.
# - one reduce-only market order for what the venue says is held on that
#   bot's side of that market — it cannot open or flip anything.
# - never mainnet: the double gate (D25) is asked with the run half shut,
#   and this command has no flag that opens it.
# - not spot: a spot "position" is the wallet's coins, the operator's own
#   stack included.
# Prints one JSON object; a refusal is {"refused": "..."}.
import json
import sys
from pathlib import Path

from .adapters import adapter_for
from .apply import make_botid
from .config import ConfigError, validate_fleet
from .exchange.env import load_env
from .exchange.errors import VenueError


def close_position(cfg, client, adapter, tombstoned, dry=False):
    """The whole act, venue-neutral and testable: returns the JSON-able
    answer. `tombstoned` is whether X7 holds a tombstone for this bot."""
    botid = make_botid(cfg['market_type'], cfg['symbol'], cfg['side'])
    if cfg['market_type'] == 'spot':
        return {'refused': f'{botid}: a spot holding is the coins in the '
                           'wallet, your own included — sell them on the '
                           'exchange; this closes futures positions only'}
    if not tombstoned:
        return {'refused': f'{botid} has not stood down — a running bot '
                           'manages its own position, and closing it from '
                           'outside is the outside hand it stands down for '
                           '(S7). This closes what a STOPPED bot left open'}
    entry = 'Buy' if cfg['side'] == 'long' else 'Sell'
    exit_ = 'Sell' if cfg['side'] == 'long' else 'Buy'
    idx = adapter.position_idx(entry, False) or 0

    def held():
        truth = client.read_symbol_truth(cfg['market_type'], cfg['symbol'])
        pos = truth['positions'].get(idx) or {}
        if pos.get('side') and pos['side'] != entry:
            return 0.0, truth['mark'], None       # the other side's: not ours
        return pos.get('size') or 0.0, truth['mark'], pos.get('avg_entry')

    size, mark, avg = held()
    out = {'botid': botid, 'side': cfg['side'], 'symbol': cfg['symbol'],
           'held': size, 'avg_entry': avg, 'mark': mark}
    if size <= 0:
        return dict(out, closed=0.0, left=0.0, note='nothing to close')
    if dry:
        return out
    client.place_market(cfg['market_type'], cfg['symbol'], exit_,
                        adapter.fmt_qty(size),
                        adapter.position_idx(exit_, True) or 0,
                        reduce_only=True)
    left, mark, _ = held()                 # X4: re-read, never assume
    return dict(out, closed=size - left, left=left, mark=mark)


def main(argv):
    dry = '--dry' in argv
    argv = [a for a in argv if a != '--dry']
    if len(argv) != 2:
        print('usage: python3 -m gridgremlin.close <fleet.json> <botid> '
              '[--dry]')
        return 2
    fleet_path, botid = argv
    try:
        load_env()
        fleet = validate_fleet(json.loads(Path(fleet_path).read_text()))
        cfg = next((b for b in fleet['bots'] if make_botid(
            b['market_type'], b['symbol'], b['side']) == botid), None)
        if cfg is None:
            raise ConfigError(f'{botid}: not in this fleet')
        from .main import _logs_dir, refuse_mainnet
        from .tombstones import Tombstones
        tombs = Tombstones(fleet.get('tombstones')
                           or str(_logs_dir(fleet_path) / 'tombstones.json'))
        if cfg['venue'] == 'hyperliquid':
            from .exchange.hyperliquid.adapters import HLPerpAdapter
            from .exchange.hyperliquid.truth import parse_instrument as hl_pi
            from .exchange.hyperliquid.venue import HLVenueClient
            client = HLVenueClient(allow_mainnet=False)
            refuse_mainnet(client, False, False)
            adapter = HLPerpAdapter(hl_pi(client._entry(cfg['symbol'])[1]))
        else:
            from .exchange.bybit.client import WriteClient
            from .exchange.bybit.truth import parse_instrument
            client = WriteClient()
            refuse_mainnet(client, False, False)
            adapter = adapter_for(cfg['market_type'], parse_instrument(
                cfg['market_type'], client.instruments_info(
                    cfg['market_type'], cfg['symbol'])))
        out = close_position(cfg, client, adapter, tombs.has(botid), dry=dry)
    except Exception as e:                                   # noqa: BLE001
        out = {'refused': f'{type(e).__name__}: {e}'}
    print(json.dumps(out))
    return 1 if 'refused' in out else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
