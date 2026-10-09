# The local durable facts E3 permits (tombstones X7, slide state G22) and
# the watchdog's memory (F1) are small JSON files. Two rules for all of
# them (audit 2026-10-05): a write is ATOMIC and durable — temp file in the
# same directory, fsync, rename, fsync the directory — so a crash leaves
# the old file or the new one, never half of either; and a file with more
# than one writer (the engine's stop and the panel's revive share the
# tombstones) is changed only under one lock, re-read inside it, so
# neither writer can undo the other.
import contextlib
import fcntl
import json
import os
import tempfile
from pathlib import Path

# One file PER FLEET (2026-10-08): two fleets on one box shared
# logs/slide_state.json, each holding its own copy since its build, and the
# last writer won — the HL fleet's slide wrote back a copy taken before the
# demo's BTC, SOL and XRP windows moved, and those offsets were gone. The
# demo and carry fleets also share botids (both run a BTCUSDT pair), so a
# shared file could never be right even with a re-read. The portfolio
# state had the same flaw the same day: the second subaccount's fleet
# loaded the first's book at its start and wrote it back stale every cycle,
# and the first's writes dropped the second's row. The fleet's own key
# still wins; the fleet-wide file refuses the build, naming the split.
STATE_KINDS = ('tombstones', 'slide_state', 'portfolio_state', 'trades')


class LegacyStateError(Exception):
    pass


def logs_dir(fleet_path):
    """logs/ beside the fleet's home: configs/x.json -> configs/../logs;
    a fleet file anywhere else keeps logs as its sibling. Anchored to the
    file so every launcher agrees, whatever directory it ran from."""
    parent = Path(fleet_path).resolve().parent
    root = parent.parent if parent.name == 'configs' else parent
    return root / 'logs'


def fleet_tag(fleet_path):
    """The fleet's name from its file: fleet.demo.json -> demo,
    fleet.hl.testnet.json -> hl.testnet; any other name keeps its stem."""
    stem = Path(fleet_path).name
    if stem.endswith('.json'):
        stem = stem[:-5]
    if stem.startswith('fleet.') and len(stem) > len('fleet.'):
        stem = stem[len('fleet.'):]
    return stem


def state_path(fleet_path, fleet_raw, kind):
    """Where a fleet's local durable fact lives — its own key
    (`tombstones`, `slide_state`, `portfolio_state`), else logs/<kind>-<fleet>.json beside its
    home — the one answer for the engine, close, flatten and the panel."""
    if kind not in STATE_KINDS:
        raise ValueError(kind)
    if (fleet_raw or {}).get(kind):
        return Path(fleet_raw[kind])
    return logs_dir(fleet_path) / f'{kind}-{fleet_tag(fleet_path)}.json'


def refuse_legacy_state(fleet_path, fleet_raw):
    """At build: a fleet-wide logs/tombstones.json, logs/slide_state.json or
    logs/portfolio_state.json beside a fleet that does not name it is the
    old shared file — refuse,
    naming the split, rather than start every window at home and every
    stopped bot alive."""
    for kind in STATE_KINDS:
        if (fleet_raw or {}).get(kind):
            continue
        old = logs_dir(fleet_path) / f'{kind}.json'
        if old.exists():
            raise LegacyStateError(
                f'{old}: the fleet-wide {kind} file of every fleet on this '
                f'box — split it first: python3 ops/split_local_state.py '
                f'configs/fleet.*.json --commit (one file per fleet, the old '
                f'one kept under logs/archive/); refusing to build with it beside '
                f'{state_path(fleet_path, fleet_raw, kind).name}')


def write_json(path, obj, indent=1):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=f'.{p.name}.')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(json.dumps(obj, indent=indent))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(p))
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise
    dfd = os.open(str(p.parent), os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


@contextlib.contextmanager
def locked(path):
    """An exclusive advisory lock beside the file, held for the block."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(f'{p}.lock', 'a') as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
