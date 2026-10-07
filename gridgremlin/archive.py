# The daily results archive (SPEC R17). The readout answers "now" and the
# venue's fill history fades past the windows we read, so a soak's results
# were nowhere unless someone looked that day. Once a day this writes, per
# fleet, the readout's whole contract (every bot's money counted from its
# last flat point, its trips and rounds, the window's activity) beside the
# newest snapshot row (equity, margin rate, what each bot holds) to
# logs/daily/<fleet>/<UTC date>.json — the record a results chapter cites.
# Read-only toward the venues, like the readout it runs (R4).
import json
import subprocess
import sys
import time
from pathlib import Path

from .durable import write_json


def run_readout(fleet_path, hours=24.0):
    """The readout as the panel runs it: its own process, its JSON."""
    out = subprocess.run([sys.executable, '-m', 'gridgremlin.report',
                          str(fleet_path), '--hours', f'{hours:g}', '--json'],
                         capture_output=True, text=True, timeout=300)
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f'readout failed: {out.stderr.strip()[-300:]}')
    return json.loads(out.stdout)


def last_snapshot(fleet_path):
    """The newest row of the fleet's snapshot file, named by its watchdog
    config (the one place the path is stated); None when absent."""
    try:
        fleet = json.loads(Path(fleet_path).read_text())
        wd = json.loads(Path(fleet['watchdog']).read_text())
        lines = Path(wd['snapshot']).read_text().strip().splitlines()
        return json.loads(lines[-1]) if lines else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def archive(fleet_path, out_dir='logs/daily', now=None, readout=run_readout,
            snapshot=last_snapshot):
    now = time.time() if now is None else now
    day = time.strftime('%Y-%m-%d', time.gmtime(now))
    tag = Path(fleet_path).stem.replace('fleet.', '', 1)
    record = {'date': day, 'written_utc': time.strftime(
                  '%Y-%m-%dT%H:%M:%SZ', time.gmtime(now)),
              'fleet': Path(fleet_path).name,
              'snapshot': snapshot(fleet_path),
              'readout': readout(fleet_path)}
    path = Path(out_dir) / tag / f'{day}.json'
    write_json(path, record)       # the day's last run is the day's record
    return path


def main(argv):
    if not argv:
        print('usage: python3 -m gridgremlin.archive <fleet.json> ... '
              '[--out logs/daily]')
        return 2
    out = 'logs/daily'
    if '--out' in argv:
        i = argv.index('--out')
        out = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    failed = 0
    for fleet in argv:
        try:
            print(f'archived {archive(fleet, out)}')
        except Exception as e:                       # noqa: BLE001
            failed += 1                    # one fleet's trouble never costs
            print(f'[warn] {fleet}: {e}', file=sys.stderr)   # the others
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
