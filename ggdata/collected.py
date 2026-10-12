"""What the data server collects, read for the panel's coin pages (D95).

The collectors live in their own private repository (datagremlin); its
docs/SPEC.md holds the data folder's format — the contract this reader
keeps to. The trading server's copy arrives by collect-pull (D93), read
only: `logs/collect/<COIN>/<kind>-YYYY-MM-DD.jsonl`, one JSON object a line,
`t` in seconds (books) or `ts` in milliseconds (liquidations)."""
import json
import time
from pathlib import Path

DIR = 'logs/collect'


def day_of(t):
    return time.strftime('%Y-%m-%d', time.gmtime(t))


def read_days(coin, kind, since, root=None):
    """A coin's rows of `kind` ('book', 'liq', …) from `since` (epoch
    seconds), oldest first; a line that is not JSON is skipped."""
    root = Path(root or DIR) / coin
    out = []
    for f in sorted(root.glob(f'{kind}-*.jsonl')):
        if f.stem.split('-', 1)[1] < day_of(since):
            continue
        for line in f.read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            t = r.get('t') or r.get('ts', 0) / 1000
            if t >= since:
                out.append(r)
    return out
