# Specs for SPEC F32 — the market data still arriving: the data server's
# public status, read by one watchdog, one page when it goes stale.

import json

NOW = 1_800_000_000.0
FRESH = {'t': NOW - 60, 'newest': {k: NOW - 200 for k in ('book', 'oi', 'funding', 'flow', 'ratio')} | {'liq': NOW - 9000},
         'coins': 33}


def spec_F32_stale_data_is_one_page_and_says_why():
    """Fresh is no breach (liquidations are shown, never paged: a quiet
    market is real); the site's own writer stopped, a kind falling
    behind, a kind missing, an unreadable status — each one key,
    `data_stale`, naming why, so a stopped server is one page."""
    from gridgremlin.freshness import freshness_breaches
    assert freshness_breaches(FRESH, NOW, 900) == {}
    writer = freshness_breaches(dict(FRESH, t=NOW - 1800), NOW, 900)
    assert list(writer) == ['data_stale'] and '30 min ago' in writer['data_stale']
    late = dict(FRESH, newest=dict(FRESH['newest'], book=NOW - 1500, ratio=None))
    got = freshness_breaches(late, NOW, 900)['data_stale']
    assert 'book 25 min' in got and 'ratio none' in got and 'oi' not in got
    assert 'could not be read' in freshness_breaches(None, NOW, 900)['data_stale']
    assert 'no time' in freshness_breaches({'newest': {}}, NOW, 900)['data_stale']


def spec_F32_one_dropped_request_is_not_a_page():
    """The status is fetched twice before it counts as unread; a body that
    is not an object is unread."""
    from gridgremlin.freshness import fetch_status
    calls = []

    def flaky(url):
        calls.append(url)
        if len(calls) == 1:
            raise OSError('reset')
        return json.dumps(FRESH)
    assert fetch_status('u', get=flaky, sleep=lambda s: None) == FRESH and len(calls) == 2
    assert fetch_status('u', get=lambda u: '[1]', sleep=lambda s: None) is None


def spec_F32_one_watchdog_reads_it_and_only_where_the_box_names_the_address():
    """The setting is one watchdog's (the calendar's, demo) and validated
    (at least a minute); with DATA_STATUS_URL unset the check is off and
    says so; set, a stale status pages through the watchdog's own
    transitions — new, reminded, recovered."""
    import os
    import tempfile
    from pathlib import Path
    from gridgremlin import freshness, watchdog
    from gridgremlin.config import ConfigError
    root = Path(__file__).resolve().parents[1]
    for cfgdir in ('configs/examples', 'configs'):
        p = root / cfgdir / 'watchdog.demo.json'
        if p.exists():
            assert watchdog.validate_watchdog(json.loads(p.read_text()))['data_stale_seconds'] == 900
            break
    base = {'tag': 't', 'snapshot': 's', 'state': 'st', 'staleness_seconds': 9, 'mm_rate_max': 0.5,
            'equity_min': 10, 're_alert_seconds': 9, 'assumes_sole_actor': True}
    try:
        watchdog.validate_watchdog(dict(base, data_stale_seconds=5))
        raise AssertionError('a 5 s staleness was accepted')
    except ConfigError:
        pass
    pages, state = watchdog.decide({}, freshness.freshness_breaches(None, NOW, 900), NOW, 3600)
    assert pages[0].startswith('data_stale: ') and 'data_stale' in state
    pages, _ = watchdog.decide(state, freshness.freshness_breaches(FRESH, NOW, 900), NOW + 300, 3600)
    assert pages == ['recovered: data_stale']
    # wired: the run reads the status only where the address is named
    with tempfile.TemporaryDirectory() as d:
        import time as _t
        snap = Path(d) / 'snap.jsonl'
        snap.write_text(json.dumps({'t': _t.time(), 'equity': 1000.0, 'mm_rate': 0.1, 'bots': {}}) + '\n')
        wd = Path(d) / 'wd.json'
        wd.write_text(json.dumps(dict(base, snapshot=str(snap), state=str(Path(d) / 'st.json'), positions={},
                                      staleness_seconds=1e9, data_stale_seconds=900)))
        seen, sent = [], []
        real = (freshness.fetch_status, watchdog.send_telegram, watchdog.ping_deadman, watchdog.load_env)
        watchdog.load_env = lambda: None                                      # never this machine's .env
        freshness.fetch_status = lambda url: seen.append(url)            # returns None: unread
        watchdog.send_telegram = sent.append
        watchdog.ping_deadman = lambda url: None
        old = os.environ.pop('DATA_STATUS_URL', None)
        try:
            watchdog.main([str(wd)])
            assert seen == [] and not any('data_stale' in s for s in sent)      # off without the address
            os.environ['DATA_STATUS_URL'] = 'https://status.example/status.json'
            watchdog.main([str(wd)])
            assert seen == ['https://status.example/status.json']
            assert any('data_stale' in s for s in sent)
        finally:
            freshness.fetch_status, watchdog.send_telegram, watchdog.ping_deadman, watchdog.load_env = real
            os.environ.pop('DATA_STATUS_URL', None)
            if old is not None:
                os.environ['DATA_STATUS_URL'] = old
