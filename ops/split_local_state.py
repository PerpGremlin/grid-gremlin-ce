"""One local state file per fleet (G22/X7, 2026-10-08).

Until this day every fleet on the box shared logs/tombstones.json and
logs/slide_state.json, each process holding its own copy since its build,
and the last writer won: the HL fleet's slide wrote back a copy taken before
the demo's BTC, SOL and XRP windows moved, and those offsets were gone. The
demo and carry fleets also share botids (both run a BTCUSDT pair), so one
file could never be right. The engine now keeps logs/<kind>-<fleet>.json and
refuses to build beside the old shared file.

This splits the old files once, with every fleet STOPPED:

    python3 ops/split_local_state.py configs/fleet.*.json            # the plan
    python3 ops/split_local_state.py configs/fleet.*.json --commit   # do it

Each fleet gets the old file's rows for its own botids; a window offset is
taken from the fleet's latest snapshot when it has one (the running fleet's
belief outlives the clobbered file); rows already in a per-fleet file stay.
Rows that belong to no fleet given are listed and kept only in the archive
copy. The old files move to logs/archive/<name>.pre-split.json.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from gridgremlin.apply import row_botid                       # noqa: E402
from gridgremlin.durable import (STATE_KINDS, fleet_tag, logs_dir,   # noqa: E402
                                 state_path, write_json)


class Refused(Exception):
    pass


def _json(path, default):
    try:
        return json.loads(Path(path).read_text() or 'null') or default
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as e:
        raise Refused(f'{path}: unreadable ({e}) — fix or move it, deliberately')


def _botids(raw):
    out = set()
    for row in raw.get('bots') or []:
        try:
            out.add(row_botid(row))
        except (KeyError, TypeError):
            continue
    return out


def _snapshot_offsets(fleet_path, raw):
    """The fleet's latest snapshot's offsets, by the watchdog file it names."""
    wd = raw.get('watchdog')
    if not wd:
        return {}
    root = logs_dir(fleet_path).parent
    snap = (_json(root / wd, {}) or {}).get('snapshot')
    if not snap:
        return {}
    try:
        lines = (root / snap).read_text().strip().splitlines()
    except OSError:
        return {}
    for line in reversed(lines):
        try:
            s = json.loads(line)
        except ValueError:
            continue
        return {b: int(v['offset']) for b, v in (s.get('bots') or {}).items()
                if isinstance(v, dict) and v.get('offset')}
    return {}


def plan(fleet_paths):
    """Pure: what each fleet's files will hold, and what is left over."""
    fleet_paths = [Path(f) for f in fleet_paths]
    if not fleet_paths:
        raise Refused('name the fleet files: configs/fleet.*.json')
    logs = {logs_dir(f) for f in fleet_paths}
    if len(logs) != 1:
        raise Refused(f'the fleets keep different logs/ directories: {sorted(map(str, logs))}')
    logs = logs.pop()
    legacy = {k: _json(logs / f'{k}.json', {}) for k in STATE_KINDS}
    fleets, claimed = {}, {k: set() for k in STATE_KINDS}
    for f in fleet_paths:
        raw = _json(f, {})
        tag = fleet_tag(f)
        if tag in fleets:
            raise Refused(f'{f}: two fleet files named {tag}')
        ids = _botids(raw)
        snap = _snapshot_offsets(f, raw)
        out = {}
        for k in STATE_KINDS:
            rows = {b: v for b, v in legacy[k].items() if b in ids}
            if k == 'slide_state':
                rows.update({b: v for b, v in snap.items() if b in ids})
            path = state_path(f, raw, k)
            rows.update(_json(path, {}))          # what a per-fleet file already holds stays
            claimed[k] |= set(rows)
            out[k] = {'path': path, 'rows': rows}
        fleets[tag] = out
    orphans = {k: {b: v for b, v in legacy[k].items() if b not in claimed[k]}
               for k in STATE_KINDS}
    return {'logs': logs, 'legacy': legacy, 'fleets': fleets, 'orphans': orphans}


def commit(fleet_paths, p, running=None):
    """Writes every per-fleet file and moves the old ones aside. Refuses
    while any of the fleets runs — its copy would write the old file back."""
    from gridgremlin.main import fleet_running
    running = running or fleet_running
    for f in fleet_paths:
        if running(str(f)):
            raise Refused(f'{f} is running — stop every fleet first; a running '
                          'fleet writes the old file back')
    for tag, out in p['fleets'].items():
        for k in STATE_KINDS:
            write_json(out[k]['path'], out[k]['rows'])
    archive = p['logs'] / 'archive'
    archive.mkdir(parents=True, exist_ok=True)
    moved = []
    for k in STATE_KINDS:
        old = p['logs'] / f'{k}.json'
        if old.exists():
            dest = archive / f'{k}.pre-split.json'
            n = 1
            while dest.exists():
                n += 1
                dest = archive / f'{k}.pre-split.{n}.json'
            old.rename(dest)
            moved.append((old, dest))
    return moved


def main(argv):
    do = '--commit' in argv
    fleets = [a for a in argv if a != '--commit']
    try:
        p = plan(fleets)
        for tag, out in p['fleets'].items():
            for k in STATE_KINDS:
                print(f'{tag}: {out[k]["path"]} <- {len(out[k]["rows"])} row(s)'
                      + (f': {json.dumps(out[k]["rows"])}' if k == 'slide_state' else ''))
        for k in STATE_KINDS:
            if p['orphans'][k]:
                print(f'{k}: {len(p["orphans"][k])} row(s) belong to no fleet given — '
                      f'kept only in the archive copy: {sorted(p["orphans"][k])}')
        if not do:
            print('a plan; --commit writes it (with every fleet stopped)')
            return 0
        for old, dest in commit(fleets, p):
            print(f'{old} -> {dest}')
        print('done: start the fleets')
        return 0
    except Refused as e:
        print(f'refused: {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
