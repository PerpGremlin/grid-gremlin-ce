"""U190: where a running bot's own orders and stop are now, for its price chart.

One small file beside the fleet's snapshots, replaced at each snapshot. Not a
field of the snapshot line: that file is read whole at every readout and already
runs to 100 MB, and a grid's prices would add about two thirds to each line
(measured 2026-11-03: 1.8 KB a line, a line every 76 s, on a six-bot fleet)."""
import json
import os
import time
from pathlib import Path

MAX_ORDERS = 60            # the nearest to the price; a row may have thousands
STALE_S = 900.0            # older than this the fleet is not writing: draw nothing


def levels_view(desired, live_keys, ref, exit_side, stop=None):
    """The plan as the chart wants it: [price, 'Buy'|'Sell', is an exit, rests on
    the venue now], nearest the price first, with how many the cap left out."""
    orders = sorted(desired, key=lambda o: abs(o['price'] - ref) if ref else 0.0)
    return {'orders': [[o['price'], o['side'], o['side'] == exit_side,
                        (o['rung'], o['side']) in live_keys] for o in orders[:MAX_ORDERS]],
            'more': max(0, len(orders) - MAX_ORDERS),
            'stop': stop}


def path_for(snapshot):
    return Path(snapshot).with_suffix('.levels.json')


def write(snapshot, bots, now):
    """Each live bot's view, whole or not at all (replaced, never appended)."""
    rows = {b.botid: b.levels_view for b in bots
            if b.alive and getattr(b, 'levels_view', None)}
    path = path_for(snapshot)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps({'t': now, 'bots': rows}))
    os.replace(tmp, path)


def read(snapshot, now=None):
    """{botid: view} while the file is fresh, else {}: a fleet that stopped
    writing has no levels to show, and a chart never draws an old plan as live."""
    try:
        row = json.loads(path_for(snapshot).read_text())
        age = (time.time() if now is None else now) - float(row['t'])
        return row['bots'] if age <= STALE_S else {}
    except (OSError, ValueError, KeyError, TypeError):
        return {}
