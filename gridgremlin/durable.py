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
