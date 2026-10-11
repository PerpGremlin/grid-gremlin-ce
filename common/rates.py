"""Funding-rate conversions (D91: one of each)."""

YEAR_MS = 365 * 86_400_000


def per_8h_pct(rate, interval_hours):
    """A settlement's rate as a percent per 8 hours, whatever the interval."""
    if rate is None or not interval_hours:
        return None
    return 100.0 * rate * 8.0 / interval_hours


def yearly_from_8h_pct(pct_8h):
    """A percent per 8 hours as a percent a year (three settlements a day)."""
    return None if pct_8h is None else pct_8h * 3 * 365


def yearly(points):
    """Funding settlements [(ms, rate)] as yearly rates (fractions): each rate
    times the settlements a year at that market's own interval (8 h, 4 h,
    1 h). The times land on the minute (Binance stamps a few ms past)."""
    pts = sorted((int(t) // 60_000 * 60_000, r) for t, r in points)
    out = []
    for i, (t, r) in enumerate(pts):
        step = (pts[i + 1][0] - t) if i + 1 < len(pts) else (t - pts[i - 1][0]) if i else 8 * 3_600_000
        out.append((t, r * (YEAR_MS / step) if step > 0 else None))
    return out
