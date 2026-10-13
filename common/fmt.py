"""One vocabulary for the primitives (C10, audit 2026-10-08): the float
parser, the UTC stamp, the number words. Each exists here once; a second
definition anywhere fails the suite."""
import math
import time


def float_or(x, default=None):
    """A float, or `default` when the value is not one (None, '', text, and
    since the audit of 2026-10-13 nan and inf: "nan" passed D64's and D97's
    second typing — every comparison with it is false)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def utc_stamp(now=None):
    """The moment as the files write it: 2026-10-08T13:10:00Z."""
    return time.strftime('%Y-%m-%dT%H:%M:%SZ',
                         time.gmtime(time.time() if now is None else now))


def num(v, nd=2):
    """1,234.50 — or a dash for nothing."""
    return '—' if v is None else f'{v:,.{nd}f}'


def big(v):
    """Whole figures: 46,600 and 3,495k — the readout's leverage words."""
    return '—' if v is None else (f'{v / 1000:,.0f}k' if v >= 10_000
                                  else f'{v:,.0f}')


def big_si(v):
    """2.5B, 51.9M, 10.0k — the market readings' depth and turnover."""
    if v is None:
        return '—'
    for unit, div in (('B', 1e9), ('M', 1e6), ('k', 1e3)):
        if abs(v) >= div:
            return f'{v / div:,.1f}{unit}'
    return f'{v:,.0f}'


def usd_compact(v):
    """15.65B, 47.8M, 845k, 500 — the pages' dollar figures (D91: one of each;
    the copies wrote "0k" for 500, or "15650.0M" with no billions)."""
    if v is None:
        return '—'
    a = abs(v)
    return (f'{v / 1e9:,.2f}B' if a >= 1e9 else f'{v / 1e6:,.1f}M' if a >= 1e6
            else f'{v / 1e3:,.0f}k' if a >= 1e3 else f'{v:,.0f}')


def pct(v, nd=2, sign=True):
    """+1.23% — or a dash for nothing."""
    if v is None:
        return '—'
    return f'{v:+.{nd}f}%' if sign else f'{v:.{nd}f}%'


def signed(v, places=2):
    """A money figure with its sign, never "-0.00": a value that rounds to
    zero is +0 (the second audit, 2026-10-13 — the card, the phone and the
    digest each printed "-0.00" for -0.001)."""
    if abs(v) < 0.5 * 10 ** -places:
        v = 0.0
    return f'{v:+,.{places}f}'
