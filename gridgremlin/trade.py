"""The owner's door onto trades (SPEC L, D81): open one, list them, clear a
finished one. A trade joins the running fleet within a cycle (L1).

  python3 -m gridgremlin.trade <fleet.json> open long|short SYMBOL --capital Q
        --tp PCT [--leverage X] [--stop PCT] [--trail PCT --trail-from PCT]
        [--maker]
  python3 -m gridgremlin.trade <fleet.json> list
  python3 -m gridgremlin.trade <fleet.json> clear <botid>

Percentages are of the entry: --tp 1.5 closes 1.5% beyond it, --stop 2 stands
the trade down 2% against it. Every number is checked by the bot validator,
the same one every bot meets.
"""
import json
import sys
from pathlib import Path

from .config import ConfigError
from .trades import TradeError, add_trade, clear_trade, fleet_rows, load_trades, trades_path


def _pct(v, name):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ConfigError(f'--{name} is a percent, like 1.5') from None
    return x / 100.0


def build_row(side, symbol, opts):
    """The trade row from the command's words — pure, so a spec reads it."""
    if side not in ('long', 'short'):
        raise ConfigError('the side is long or short')
    if 'capital' not in opts or 'tp' not in opts:
        raise ConfigError('--capital and --tp are required: a trade is never without its size or its exit')
    row = {'symbol': symbol.upper(), 'side': side, 'capital': float(opts['capital']),
           'take_profit_avg_pct': _pct(opts['tp'], 'tp')}
    if 'leverage' in opts:
        row['leverage'] = float(opts['leverage'])
    if 'stop' in opts:
        # watched by the engine at its mark each cycle: a venue-side stop sits
        # at one fixed level and cannot also be a share of the entry (X10)
        row['stop'] = {'watch': 'mark_price', 'from_base_pct': _pct(opts['stop'], 'stop')}
    if 'trail' in opts:
        row['trailing_stop_pct'] = _pct(opts['trail'], 'trail')
        if 'trail-from' in opts:
            row['trailing_activation_pct'] = _pct(opts['trail-from'], 'trail-from')
    if opts.get('maker'):
        row['start_order_type'] = 'maker'
    return row


def _opts(words):
    flags = ('maker',)
    out, i = {}, 0
    while i < len(words):
        w = words[i]
        if not w.startswith('--'):
            raise ConfigError(f'unexpected {w!r}')
        k = w[2:]
        if k in flags:
            out[k] = True
            i += 1
        else:
            if i + 1 >= len(words):
                raise ConfigError(f'--{k} needs a value')
            out[k] = words[i + 1]
            i += 2
    return out


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    fleet_path, verb = argv[0], argv[1]
    try:
        fleet, rows = fleet_rows(fleet_path)
        raw = json.loads(Path(fleet_path).read_text())
        path = trades_path(fleet_path, raw)
        if verb == 'open' and len(argv) >= 4:
            row = build_row(argv[2], argv[3], _opts(argv[4:]))
            botid = add_trade(path, rows, row)
            print(f'{botid}: queued in {path} — the running fleet opens it within a cycle')
            return 0
        if verb == 'list':
            trades, refused = load_trades(path)
            for t in trades:
                rec = t.get('_record', {})
                print(f"{t['symbol']} {t['side']} {t['capital']:g} at {t['leverage']:g}x · tp "
                      f"{(t.get('take_profit_avg_pct') or 0) * 100:g}% · stop "
                      f"{((t.get('stop') or {}).get('from_base_pct') or 0) * 100:g}% · opened "
                      f"{rec.get('opened', '?')} by {rec.get('by', '?')}")
            for i, why in refused:
                print(f'trade {i} refused: {why}')
            if not trades and not refused:
                print('no trades')
            return 0
        if verb == 'clear' and len(argv) == 3:
            from .tombstones import path_for
            gone = clear_trade(path, argv[2], path_for(fleet_path, raw))
            print(f'{argv[2]}: cleared' if gone else f'{argv[2]}: not in the trades file')
            return 0 if gone else 1
        print(__doc__)
        return 2
    except (ConfigError, TradeError) as e:
        print(f'refused: {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
