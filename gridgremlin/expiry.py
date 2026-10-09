# The expiry calendar (SPEC F29, D79): what runs out and when — API keys,
# tokens, demo accounts, the box's billing, a domain — in one dated list the
# watchdog reads, so "expires in 7 days" is a page and not a surprise. The
# calendar is data; nothing here renews anything.
#
#   python3 -m gridgremlin.expiry configs/expiry.json     # the calendar, dated
import datetime as _dt
import json
import sys
from pathlib import Path

from .config import ConfigError, _reject_unknown

ENTRY_KEYS = ('name', 'expires', 'note', 'where')
WARN_DAYS = 7


def _date(text, where):
    if text is None:
        return None
    try:
        return _dt.date.fromisoformat(str(text))
    except ValueError:
        raise ConfigError(f"{where}: 'expires' is a date, YYYY-MM-DD, or null when "
                          'unknown — never a guess') from None


def validate_calendar(data, where='expiry'):
    """The calendar: a list of {name, expires, note?, where?}; `expires` is
    an ISO date or null (unknown — listed, never paged). Refuses the
    shapeless and the duplicate like every config."""
    if not isinstance(data, list):
        raise ConfigError(f'{where}: a list of {{name, expires, note, where}}')
    out, seen = [], set()
    for i, e in enumerate(data):
        w = f'{where}[{i}]'
        if not isinstance(e, dict):
            raise ConfigError(f'{w}: an object {{name, expires, note, where}}')
        _reject_unknown(e, ENTRY_KEYS, w)
        name = e.get('name')
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"{w}: 'name' says what runs out")
        if name in seen:
            raise ConfigError(f'{where}: {name!r} is listed twice')
        seen.add(name)
        if 'expires' not in e:
            raise ConfigError(f"{w}: 'expires' is required — a date, or null when unknown")
        out.append({'name': name, 'expires': _date(e['expires'], w),
                    'note': str(e.get('note') or ''), 'where': str(e.get('where') or '')})
    return out


def load_calendar(path):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise ConfigError(f'{path}: unreadable ({e})') from None
    return validate_calendar(data, str(path))


def due(entries, today, warn_days=WARN_DAYS):
    """Pure: {stable key: text} for what has run out or runs out within
    `warn_days` — the watchdog's breaches, so a page comes once, a reminder
    on its interval, and 'recovered' when the date is moved on."""
    out = {}
    for e in entries:
        if e['expires'] is None:
            continue
        left = (e['expires'] - today).days
        if left < 0:
            out[f'expired:{e["name"]}'] = (f'EXPIRED {-left} day(s) ago: {e["name"]} '
                                           f'({e["expires"].isoformat()})')
        elif left <= warn_days:
            when = 'today' if left == 0 else f'in {left} day(s)'
            out[f'expires:{e["name"]}'] = (f'expires {when}: {e["name"]} '
                                           f'({e["expires"].isoformat()})')
    return out


def expiry_breaches(path, today, warn_days=WARN_DAYS):
    """What the watchdog adds to its breaches: the calendar's due entries,
    or one breach naming an unreadable calendar — a watch that cannot read
    its list says so rather than watching nothing."""
    try:
        return due(load_calendar(path), today, warn_days)
    except ConfigError as e:
        return {'expiry_unread': f'expiry calendar unread — {e}'}


def render(entries, today):
    """The calendar as a page: soonest first, the unknown last."""
    dated = sorted((e for e in entries if e['expires'] is not None), key=lambda e: e['expires'])
    lines = []
    for e in dated:
        left = (e['expires'] - today).days
        state = (f'EXPIRED {-left}d ago' if left < 0 else 'today' if left == 0
                 else f'in {left}d')
        lines.append(f"{e['expires'].isoformat()}  {state:>16}  {e['name']}"
                     + (f"  — {e['note']}" if e['note'] else '')
                     + (f"  [{e['where']}]" if e['where'] else ''))
    for e in entries:
        if e['expires'] is None:
            lines.append(f"{'unknown':>10}  {'confirm':>16}  {e['name']}"
                         + (f"  — {e['note']}" if e['note'] else '')
                         + (f"  [{e['where']}]" if e['where'] else ''))
    return '\n'.join(lines) or '(an empty calendar)'


def main(argv):
    if not argv:
        print('usage: python3 -m gridgremlin.expiry configs/expiry.json')
        return 2
    try:
        entries = load_calendar(argv[0])
    except ConfigError as e:
        print(f'refused: {e}')
        return 1
    today = _dt.datetime.now(_dt.timezone.utc).date()
    print(render(entries, today))
    return 1 if due(entries, today) else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
