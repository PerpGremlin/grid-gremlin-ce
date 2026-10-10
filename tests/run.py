# The spec runner. stdlib only, no framework.
#
# A spec file is tests/spec_*.py; a spec is a zero-argument function in it whose
# name starts with 'spec_'. Function names carry the SPEC id they pin
# (e.g. spec_G7_entry_never_rearms_while_lot_unexited), which is how docs/SPEC.md's
# `test:` column and the suite stay one vocabulary (T1, T5).
#
# Usage:  python3 tests/run.py            # every spec file
#         python3 tests/run.py spec_foo   # one file
# Exit code 0 iff every spec passed. A spec fails by raising; AssertionError or
# otherwise — an error IS a failure, never a skip.

import importlib.util
import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # make `gridgremlin` importable

LOOPBACK = ('localhost', '127.0.0.1', '::1', '')


def _no_network():
    """T6: a spec never reaches the network. Name resolution for anything but
    loopback is refused — the panel's specs serve on 127.0.0.1 — so the
    workstation runs the suite as GitHub's runners do (Bybit answers them
    403): a spec that fetched a live price passed here and failed there
    (spec_J1, 2026-10-10). Code that tolerates a dead network still runs."""
    import socket
    real = socket.getaddrinfo

    def guarded(host, *a, **k):
        h = host.decode() if isinstance(host, bytes) else (host or '')
        if h not in LOOPBACK:
            raise OSError(f'specs never reach the network (T6): {h}')
        return real(host, *a, **k)
    socket.getaddrinfo = guarded


_no_network()


def _load(path):
    module_spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def main(argv):
    if argv:
        files = [HERE / (name if name.endswith('.py') else name + '.py') for name in argv]
        missing = [str(f) for f in files if not f.exists()]
        if missing:
            print('no such spec file: ' + ', '.join(missing))
            return 2
    else:
        files = sorted(HERE.glob('spec_*.py'))

    ran = failed = 0
    start = time.monotonic()
    for path in files:
        try:
            module = _load(path)
        except Exception:
            print(f'FAIL {path.name} (import)')
            traceback.print_exc()
            failed += 1
            ran += 1
            continue
        specs = [name for name in sorted(dir(module))
                 if name.startswith('spec_') and callable(getattr(module, name))]
        for name in specs:
            ran += 1
            try:
                getattr(module, name)()
            except Exception:
                failed += 1
                print(f'FAIL {path.name}::{name}')
                traceback.print_exc()

    elapsed = time.monotonic() - start
    print(f'{ran} specs, {failed} failed ({elapsed:.2f}s)')
    return 1 if failed else 0


def contained(run):
    """Every temp file a spec makes lands in one directory of this run's,
    removed when the run ends — however it ends. The specs make theirs with
    mkdtemp/mkstemp and leave them; one run left 61 entries in /tmp, and the
    workstation had collected ~5,300 (2026-10-07). TMPDIR carries it into
    the subprocesses some specs start."""
    tmp = tempfile.mkdtemp(prefix='gg-specs-')
    was_env, was_dir = os.environ.get('TMPDIR'), tempfile.tempdir
    os.environ['TMPDIR'] = tmp
    tempfile.tempdir = tmp
    try:
        return run()
    finally:
        tempfile.tempdir = was_dir
        if was_env is None:
            os.environ.pop('TMPDIR', None)
        else:
            os.environ['TMPDIR'] = was_env
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(contained(lambda: main(sys.argv[1:])))
