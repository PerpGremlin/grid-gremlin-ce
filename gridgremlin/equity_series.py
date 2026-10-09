# The account's equity over time (SPEC U63), read from the fleet's own
# snapshot file — the per-minute row the engine already writes (F4), never
# rotated (F26) — so the panel can draw a line without a second source or a
# single venue read. The file is read from its tail, once cold and then only
# what was appended, so a 40 MB history costs the page a few kilobytes a
# refresh. A row the engine could not price (equity null, E9) is skipped.
import json
import os
from pathlib import Path

DAY = 86_400.0
CHUNK = 1 << 20                      # 1 MB: a day of the busiest fleet
WINDOWS = (('24h', DAY, 300.0),       # name, span, bucket seconds
           ('7d', 7 * DAY, 1800.0))


def snapshot_path(fleet_path):
    """The fleet's snapshot file, by the watchdog config its file names —
    both resolved from the fleet's home, never the working directory."""
    fleet_path = Path(fleet_path)
    parent = fleet_path.resolve().parent
    root = parent.parent if parent.name == 'configs' else parent
    try:
        raw = json.loads(fleet_path.read_text())
        wd = raw.get('watchdog')
        if not wd:
            return None
        snap = json.loads((root / wd).read_text()).get('snapshot')
    except (OSError, ValueError, AttributeError):
        return None
    return str(root / snap) if snap else None


def _parse(buf):
    out = []
    for line in buf.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue                                  # a torn or partial line
        t, e = row.get('t'), row.get('equity')
        if not isinstance(t, (int, float)):
            continue
        marks = {b: v['mark'] for b, v in (row.get('bots') or {}).items()
                 if isinstance(v, dict) and isinstance(v.get('mark'), (int, float))}
        if isinstance(e, (int, float)) or marks:
            out.append((float(t), float(e) if isinstance(e, (int, float)) else None, marks))
    return out


def read_tail(path, since, cache=None):
    """The rows with t >= since, as [(t, equity)]. `cache` is a dict the
    caller keeps per path — {'size', 'points'} — so a second call reads
    only what the engine appended since; a file that shrank (never, by
    F26; a hand) starts cold again. Missing file: no points."""
    cache = cache if cache is not None else {}
    try:
        size = os.path.getsize(path)
    except OSError:
        cache.clear()
        return []
    points = cache.get('points') or []
    read_from = cache.get('size')
    if read_from is None or read_from > size or not points:
        # cold: back from the end a chunk at a time until a whole line is
        # older than `since`, or the file begins
        with open(path, 'rb') as f:
            end, buf = size, b''
            while end > 0:
                start = max(0, end - CHUNK)
                f.seek(start)
                buf = f.read(end - start) + buf
                end = start
                head = buf.split(b'\n', 1)
                if start == 0 or len(head) < 2:
                    continue
                first = _parse(head[1][:4096].split(b'\n', 1)[0].decode('utf-8', 'replace'))
                if first and first[0][0] < since:
                    break
        points = _parse(buf.decode('utf-8', 'replace'))
    elif read_from < size:
        with open(path, 'rb') as f:
            f.seek(read_from)
            tail = f.read(size - read_from)
        # the incremental read starts mid-line only if the last read ended
        # mid-write; a torn first line is skipped by the parser as any other
        points = points + _parse(tail.decode('utf-8', 'replace'))
    points = [p for p in points if p[0] >= since]
    cache['size'], cache['points'] = size, points
    return points


def downsample(points, bucket_s):
    """One point per bucket — the last seen — so a day at one a minute
    draws as 288 points, a week at one a minute as 336. Points are
    (t, value) pairs."""
    out, last_bucket = [], None
    for t, e in points:
        b = int(t // bucket_s)
        if b == last_bucket:
            out[-1] = (t, e)
        else:
            out.append((t, e))
            last_bucket = b
    return out


def windows(points, now):
    """{'24h': [[t, e], …], '7d': [[t, e], …]} — the equity of each row
    that has one, from one sorted series."""
    out = {}
    eq = [(p[0], p[1]) for p in points if p[1] is not None]
    for name, span, bucket in WINDOWS:
        out[name] = [[t, e] for t, e in downsample([p for p in eq if p[0] >= now - span], bucket)]
    return out


def mark_windows(points, botid, now):
    """U65: the same two windows of one bot's price, from the rows that
    carry its mark; None when no row does."""
    ms = [(p[0], p[2][botid]) for p in points if len(p) > 2 and botid in p[2]]
    if not ms:
        return None
    return {name: [[t, m] for t, m in downsample([q for q in ms if q[0] >= now - span], bucket)]
            for name, span, bucket in WINDOWS}


def equity_windows(path, now, cache=None):
    """The panel's one call: the two windows for a snapshot file."""
    if not path:
        return None
    pts = read_tail(path, now - 7 * DAY, cache)
    w = windows(pts, now) if pts else None
    return w if w and (w['24h'] or w['7d']) else None


def price_windows(path, botid, now, cache=None):
    """U65: one bot's price over a day and a week, from the same tail."""
    if not path:
        return None
    return mark_windows(read_tail(path, now - 7 * DAY, cache), botid, now)


def bot_fills(ledger_path, botid, since_ms):
    """U65: the bot's own fills from the kept ledger (R18), as
    [(time_s, price, side)], since `since_ms` — ours by the link's prefix
    (I1)."""
    try:
        kept = json.loads(Path(ledger_path).read_text())
    except (OSError, ValueError):
        return []
    out = []
    for f in kept.get('fills') or []:
        if (f.get('link_id') or '').startswith(botid + '-') and (f.get('time_ms') or 0) >= since_ms:
            out.append((f['time_ms'] / 1000.0, float(f['price']), f.get('side')))
    return out
