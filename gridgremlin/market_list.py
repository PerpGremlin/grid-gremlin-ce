"""D91: the markets the fleets are on, as the list the data layer reads —
and the hourly reading of them (K1). ggdata never reads a fleet; this is
the engine's side of that line.

  python3 -m gridgremlin.market_list configs/a.json [configs/b.json]   # read, keep
  python3 -m gridgremlin.market_list configs/a.json --send             # and page it
  python3 -m gridgremlin.market_list configs/a.json --dry              # print only
"""
import json
import sys
from pathlib import Path

from .config import market_rows, validate_fleet


def markets_of(fleet_paths):
    """Every (venue, market_type, symbol) a fleet trades, once, with what
    the fleets put on it in quote: {key: committed}."""
    out = {}
    for fp in fleet_paths:
        fleet = validate_fleet(json.loads(Path(fp).read_text()))
        from .trades import with_trades
        fleet = with_trades(fp, fleet)                # L5: a trade's market is read too
        for cfg in market_rows(fleet):
            key = (cfg['venue'], cfg['market_type'], cfg['symbol'])
            put = cfg.get('ladder_total_notional') or cfg.get('ladder_notional') or 0.0
            out[key] = out.get(key, 0.0) + float(put)
        for cfg in fleet['bots']:                        # D78: the row's legs
            if cfg.get('strategy') != 'portfolio':
                continue
            from .portfolio import leg_markets
            for _, _, mt, sym, put in leg_markets(cfg):
                key = (cfg['venue'], mt, sym)
                out[key] = out.get(key, 0.0) + float(put)
    return out


def main(argv):
    paths = [a for a in argv if not a.startswith('--')]
    if not paths:
        print('usage: python3 -m gridgremlin.market_list <fleet.json> ... [--send] [--dry]')
        return 2
    from ggdata.market import run
    return run(markets_of(paths), send='--send' in argv, dry='--dry' in argv)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
