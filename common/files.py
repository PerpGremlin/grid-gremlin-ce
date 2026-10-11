"""A JSON file written atomically and durably: a temp file in the same
directory, fsync, rename, fsync the directory — a crash leaves the old file
or the new one, never half of either (the 2026-10-05 audit)."""
import contextlib
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
