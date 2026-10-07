"""F26: retention — what the box keeps, and in what shape.

  python3 -m gridgremlin.retention [logs/archive]

Logs rotate by size (F11); snapshots are one history, never rotated
(F11), and the disk alarm (F25) watches their growth. The archive
directory holds whole logs kept by hand (the 48-day run's demo log sat
there at 2.3 GB, 80% of the disk, 2026-10-08). A log in the archive older
than a day is compressed in place — kept, never deleted — and anything
that is not a log is left alone. Run after each rotation by the logrotate
unit. Nothing here touches a file the fleet is writing.
"""
import gzip
import os
import shutil
import sys
import time
from pathlib import Path


def compress_archive(root='logs/archive', older_than_s=86400, now=None):
    """Compress every *.log under `root` not modified within `older_than_s`;
    the .gz replaces the original only once written whole. Returns the
    paths compressed."""
    now = time.time() if now is None else now
    root = Path(root)
    done = []
    if not root.is_dir():
        return done
    for p in sorted(root.glob('*.log')):
        if now - p.stat().st_mtime < older_than_s:
            continue                       # still being written, or just was
        gz = p.with_suffix(p.suffix + '.gz')
        tmp = gz.with_name(gz.name + '.part')
        with open(p, 'rb') as src, gzip.open(tmp, 'wb', compresslevel=6) as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
        os.replace(tmp, gz)
        p.unlink()
        done.append(str(gz))
    return done


def main(argv):
    root = argv[0] if argv else 'logs/archive'
    for gz in compress_archive(root):
        print(f'compressed {gz}', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
