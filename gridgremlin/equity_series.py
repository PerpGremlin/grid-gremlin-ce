# The account's equity over time (SPEC U63), read from the fleet's own
# snapshot file — the per-minute row the engine already writes (F4), never
# rotated (F26) — so the panel can draw a line without a second source or a
# single venue read. The file is read from its tail, once cold and then only
# what was appended, so a 40 MB history costs the page a few kilobytes a
# refresh. A row the engine could not price (equity null, E9) is skipped.
import json
import math
import os
import re
from pathlib import Path

DAY = 86_400.0
CHUNK = 1 << 20                      # 1 MB: a day of the busiest fleet
WINDOWS = (('24h', DAY, 300.0),       # name, span, bucket seconds
           ('7d', 7 * DAY, 1800.0))
EQ_WINDOWS = (('24h', DAY, 600.0),    # U91: equity keeps each bucket's low, high and
              ('7d', 7 * DAY, 3600.0))  # last, so the buckets are wider for the same weight


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
    that has one, from one sorted series; each bucket keeps its low, high
    and last (U91: the last alone hid a week's lowest point)."""
    out = {}
    eq = [(p[0], p[1]) for p in points if p[1] is not None]
    for name, span, bucket in EQ_WINDOWS:
        out[name] = [[t, e] for t, e in extremes([p for p in eq if p[0] >= now - span], bucket)]
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


# U91: the whole history, for the 30-day and all-time lines. The file is
# read once from its start, matched for the two leading fields only (the
# engine writes "t" then "equity" first), one point kept an hour; after
# that only what was appended. 55 MB costs one pass, not a parse per row.
_ROW = re.compile(rb'^\{"t": ([0-9.]+), "equity": ([-0-9.eE+]+)', re.M)
HOUR = 3600.0


def extremes(points, bucket_s):
    """Per bucket, its lowest, highest and last points in time order (one
    to three), so a thinned line keeps every dip and peak and the box's
    low and high stay true."""
    out, cur, key = [], [], None
    def flush():
        if cur:
            keep = {min(cur, key=lambda p: p[1]), max(cur, key=lambda p: p[1]), cur[-1]}
            out.extend(sorted(keep))
    for p in points:
        b = int(p[0] // bucket_s)
        if b != key:
            flush()
            cur, key = [], b
        cur.append(p)
    flush()
    return out


def history(path, cache=None):
    """[(t, equity)], each hour's lowest, highest and last, the whole
    file; `cache` ({'size', 'points', 'rest'}) makes a second call read
    only what was appended. Missing file: no points."""
    cache = cache if cache is not None else {}
    try:
        size = os.path.getsize(path)
    except OSError:
        cache.clear()
        return []
    if cache.get('size') is None or cache['size'] > size:
        cache.update(size=0, points=[], rest=b'')
    if cache['size'] < size:
        pts = cache['points']
        with open(path, 'rb') as f:
            f.seek(cache['size'])
            rest = cache['rest']
            while True:
                chunk = f.read(CHUNK * 8)
                if not chunk:
                    break
                buf = rest + chunk
                cut = buf.rfind(b'\n') + 1
                buf, rest = buf[:cut], buf[cut:]
                new = [(float(m.group(1)), float(m.group(2))) for m in _ROW.finditer(buf)]
                if new:
                    # the last hour already kept may still be filling: re-thin it with the new rows
                    h = int(new[0][0] // HOUR)
                    while pts and int(pts[-1][0] // HOUR) == h:
                        new.insert(0, pts.pop())
                    pts.extend(extremes(new, HOUR))
        cache.update(size=size, points=pts, rest=rest)
    return cache['points']


def _daily_returns(points):
    days = {}
    for t, e in points:
        days[int(t // DAY)] = e
    closes = [days[k] for k in sorted(days)]
    return [b / a - 1.0 for a, b in zip(closes, closes[1:]) if a > 0]


def sharpe(points):
    """The daily Sharpe ratio on a year's scale: each UTC day's last
    equity against the day before's, their mean over their spread, times
    the square root of 365, with no risk-free rate. None under ten daily
    returns or with no spread. Money added or taken out moves it too."""
    rets = _daily_returns(points)
    if len(rets) < 10:
        return None
    mean = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1))
    return mean / sd * math.sqrt(365) if sd > 0 else None


def trust(points, z=1.645):
    """U91b, from the researcher's Sharpe study (research/sharpe.py,
    Bailey & López de Prado 2012): how far the daily Sharpe can be told
    from luck — {'likely': the chance the true one is above zero, 'more':
    the further days needed for that chance to reach 95%, None when it
    never will (a Sharpe at or below zero)}; skew and fat tails counted.
    None under ten daily returns."""
    r = _daily_returns(points)
    n = len(r)
    if n < 10:
        return None
    m = sum(r) / n
    pv = sum((x - m) ** 2 for x in r) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in r) / (n - 1))
    if pv <= 0 or sd <= 0:
        return None
    sr = m / sd
    g3 = sum((x - m) ** 3 for x in r) / n / pv ** 1.5
    g4 = sum((x - m) ** 4 for x in r) / n / pv ** 2
    v = 1 - g3 * sr + (g4 - 1) / 4 * sr * sr
    if v <= 0:
        return None
    likely = 0.5 * (1 + math.erf(sr * math.sqrt(n - 1) / math.sqrt(v) / math.sqrt(2)))
    more = None if sr <= 0 else max(0.0, 1 + v * (z / sr) ** 2 - n)
    return {'likely': likely, 'more': more}


def long_windows(path, now, cache=None):
    """U91: {'30d': […], 'all': […], 'sharpe': {'30d': x, 'all': y}} —
    a month in three-hour steps, the whole history in about 300, each step
    its lowest, highest and last; None with no history."""
    if not path:
        return None
    pts = history(path, cache)
    if not pts:
        return None
    month = [p for p in pts if p[0] >= now - 30 * DAY]
    bucket = max(HOUR, (now - pts[0][0]) / 300.0)
    return {'30d': [[t, e] for t, e in extremes(month, 3 * HOUR)],
            'all': [[t, e] for t, e in extremes(pts, bucket)],
            'sharpe': {'30d': sharpe(month), 'all': sharpe(pts)},
            'trust': {'30d': trust(month), 'all': trust(pts)}}


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
