"""One vocabulary for the primitives (C10, audit 2026-10-09): the float
parser, the UTC stamp, the number words. Each exists here once; a second
definition anywhere fails the suite."""
import time


def float_or(x, default=None):
    """A float, or `default` when the value is not one (None, '', text)."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


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


def pct(v, nd=2, sign=True):
    """+1.23% — or a dash for nothing."""
    if v is None:
        return '—'
    return f'{v:+.{nd}f}%' if sign else f'{v:.{nd}f}%'
