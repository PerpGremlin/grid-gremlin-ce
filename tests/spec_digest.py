# Specs for SPEC F17 (D62) — the daily digest: the UTC day per exchange,
# what happened since the last digest, and the machinery's health.

import json
import os
import tempfile
import time
from pathlib import Path

from gridgremlin.digest import build, day_books, log_events

DAY = 86_400_000
LINK = 'linBTCUSDTl-1-a'


def _kf(t, eid, side='buy', price=100.0, qty=1.0, fee=0.0):
    return {'venue': 'bybit', 'market_type': 'linear', 'symbol': 'BTCUSDT',
            'exec_id': eid, 'time_ms': t, 'side': side, 'price': price,
            'qty': qty, 'fee': fee, 'link_id': LINK}


FLEET = {'bots': [{'venue': 'bybit', 'market_type': 'linear',
                   'symbol': 'BTCUSDT', 'side': 'long'}]}


def spec_F17_the_day_is_what_the_kept_book_made_inside_it():
    """Yesterday's trip is history; today's trip, and today's half of a
    trip opened yesterday, are the day's — against the anchored basis."""
    start = 10 * DAY
    kept = {'anchors': {'linBTCUSDTl': {'kind': 'clean', 'time_ms': 0}},
            'fills': [_kf(1, 'a'), _kf(2, 'b', 'sell', 110.0),          # +10
                      _kf(start - 5, 'c'),                              # opened
                      _kf(start + 5, 'd', 'sell', 105.0, fee=0.5),      # +5 -.5
                      _kf(start + 9, 'e'), _kf(start + 10, 'f', 'sell', 101.0)]}
    books = day_books(FLEET, kept, start, start + 100)
    a, z = books['linBTCUSDTl']
    day = (z['realized'] - z['fees']) - (a['realized'] - a['fees'])
    assert abs(day - 5.5) < 1e-9 and z['trips'] - a['trips'] == 2
    none = day_books(FLEET, dict(kept, anchors={}), start, start + 100)
    assert none == {}                                # no whole start: absent


def spec_F17_the_log_is_read_from_where_the_last_digest_stopped():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / 'fleet-demo.log'
        p.write_text('[ship] kill botA: stood down\n'
                     '[ship] exit botB: position 2 -> 1\n'
                     '[ship] exit botC: trailing stop 9 crossed — closed\n'
                     '[ship] warn botD: tp: order rejected: minimum\n'
                     '[ship] warn botE: our fills do not account (G26)\n'
                     'Traceback (most recent call last):\n')
        counts, place = log_events(p, 0)
        assert counts == {'kills': 1, 'stop/trail closes': 1,
                          'refused orders': 1, 'fill lags (G26)': 1,
                          'margin': 0, 'tracebacks': 1}
        with open(p, 'a') as f:
            f.write('[ship] margin fleet: account cap reached\n')
        counts, place2 = log_events(p, place)
        assert counts['kills'] == 0 and counts['margin'] == 1   # only the new
        p.write_text('[ship] kill botA: again\n')               # rotated
        counts, _ = log_events(p, place2)
        assert counts['kills'] == 1                             # from the start


def spec_F17_the_digest_says_each_exchange_and_its_health():
    now = 20 * DAY / 1000 + 3600
    with tempfile.TemporaryDirectory() as d:
        old = os.getcwd()
        os.chdir(d)
        try:
            Path('configs').mkdir()
            Path('logs/daily/demo').mkdir(parents=True)
            Path('logs/fills').mkdir(parents=True)
            Path('logs/snap.jsonl').write_text(json.dumps({
                't': now - 30, 'equity': 5000.0, 'mm_rate': 0.05,
                'bots': {'linBTCUSDTl': {'alive': True, 'position': 0.0}}})
                + '\n')
            Path('configs/wd.json').write_text(json.dumps({
                'snapshot': 'logs/snap.jsonl', 'state': 'logs/wd.state'}))
            Path('configs/fleet.demo.json').write_text(json.dumps({
                'watchdog': 'configs/wd.json', 'bots': [{
                    'market_type': 'linear', 'symbol': 'BTCUSDT',
                    'side': 'long', 'capital': 1000, 'leverage': 5,
                    'lower': 90, 'upper': 110, 'rungs': 5}]}))
            start = 20 * DAY
            Path('logs/fills/demo.json').write_text(json.dumps({
                'collected': {'bybit:linear:BTCUSDT': start + 1000},
                'anchors': {'linBTCUSDTl': {'kind': 'clean', 'time_ms': 0}},
                'fills': [_kf(start + 1, 'a'),
                          _kf(start + 2, 'b', 'sell', 112.0, fee=2.0)]}))
            Path('logs/daily/demo/1970-01-21.json').write_text(json.dumps({
                'readout': {'account': {'bybit': {
                                'notional': 12_500.0, 'equity': 5000.0,
                                'collateral': 5000.0}},
                            'bots': {'linBTCUSDTl': {'unreal_at_mark': 0.0,
                                                     'mark': 112.0}},
                            'since_first': {'linBTCUSDTl': {
                                'fills': 2, 'whole': True, 'behind': None,
                                'realized': 12.0, 'fees': 2.0,
                                'unreal_at_mark': 0.0}}}}))
            Path('logs/fleet-demo.log').write_text(
                '[ship] kill linBTCUSDTl: stood down\n')
            text, state = build(['configs/fleet.demo.json'], now=now)
        finally:
            os.chdir(old)
    assert 'daily digest · 1970-01-21' in text
    assert 'day +10.00 after fees, before funding (fees 2.00) · 1 trips · 0 rounds' in text
    assert 'kept history +10.00' in text and 'equity 5,000' in text
    assert ('account leverage 2.50x (all filled: 2.50x on a fall, 2.50x on '
            'a rise)') in text
    assert 'since the log began (first digest): kills 1' in text
    assert 'health: 1/1 bots alive' in text
    assert state['demo'] > 0                         # the place, to remember


def spec_F17_a_fleet_that_cannot_be_read_does_not_cost_the_others():
    with tempfile.TemporaryDirectory() as d:
        old = os.getcwd()
        os.chdir(d)
        try:
            text, state = build(['configs/fleet.missing.json'],
                                now=time.time())
        finally:
            os.chdir(old)
    assert 'unreadable' in text and state == {}
