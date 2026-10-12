# Is the market data still arriving? (SPEC F32). The data server publishes
# a small public status file — when its pages were last written and the
# newest row of each kind — and one fleet's watchdog reads it over HTTPS
# and pages when it goes stale. No key passes between the two servers; the
# trading server needs none of this to trade. The address lives only in
# the box's .env (DATA_STATUS_URL): without it the check is off.
import json
import time
import urllib.request

PAGED = ('book', 'oi', 'funding', 'flow', 'ratio')   # every five minutes, always
# liquidations are shown, never paged: a quiet market is a real answer


def fetch_status(url, get=None, tries=2, pause=5.0, sleep=time.sleep):
    """The status file as a dict, or None — a second try after a pause, so
    one dropped request is not a page."""
    get = get or _get
    for i in range(tries):
        try:
            got = json.loads(get(url))
            if isinstance(got, dict):
                return got
        except (OSError, ValueError):
            pass
        if i + 1 < tries:
            sleep(pause)
    return None


def _get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'grid-gremlin', 'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode()


def freshness_breaches(status, now, max_age_s):
    """What the watchdog adds to its breaches (F32): one key at most, so a
    stopped server is one page, not six. Unread status, a status the site
    stopped writing, and kinds whose newest row is too old each say why."""
    if status is None:
        return {'data_stale': 'the data status could not be read — the site or the data server may be down'}
    t = status.get('t')
    if not isinstance(t, (int, float)):
        return {'data_stale': 'the data status has no time — its shape changed'}
    if now - t > max_age_s:
        return {'data_stale': f'the site last wrote its data status {_mins(now - t)} ago — '
                              'its page writer or the data server has stopped'}
    newest = status.get('newest') or {}
    late = [f'{k} {_mins(now - newest[k])}' if isinstance(newest.get(k), (int, float)) else f'{k} none'
            for k in PAGED
            if not isinstance(newest.get(k), (int, float)) or now - newest[k] > max_age_s]
    if late:
        return {'data_stale': 'collecting has stopped or fallen behind — newest: ' + ', '.join(late)}
    return {}


def _mins(s):
    return f'{int(s // 60)} min' if s < 7200 else f'{s / 3600:.1f} h'
