# Specs for SPEC R18 — the kept ledger: every fill of a fleet, once, kept
# past what the exchanges still answer, and the readout's "since first trade".

import json
import tempfile
from pathlib import Path

from gridgremlin.kept_fills import (HL_CAP, OVERLAP_MS, collect, hl_history,
                                    keep, load, merge)
from gridgremlin.report import first_flat_ms, kept_books

DAY = 86_400_000
NOW = 200 * DAY

FLEET = {'bots': [{'venue': 'bybit', 'market_type': 'linear',
                   'symbol': 'BTCUSDT', 'side': 'long'},
                  {'venue': 'hyperliquid', 'market_type': 'linear',
                   'symbol': 'SUI', 'side': 'long'}]}


def _kf(t, eid, venue='bybit', symbol='BTCUSDT', side='buy', price=100.0,
        qty=1.0, fee=0.0, link=''):
    return {'venue': venue, 'market_type': 'linear', 'symbol': symbol,
            'exec_id': eid, 'time_ms': t, 'side': side, 'price': price,
            'qty': qty, 'fee': fee, 'link_id': link}


class Bybit:
    """executions_page over a fixed history, honouring the window."""
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def executions_page(self, category, symbol, start_ms, end_ms, cursor=None):
        self.calls.append((symbol, start_ms, end_ms))
        return {'list': [r for r in self.rows if r['symbol'] == symbol
                         and start_ms <= int(r['execTime']) <= end_ms],
                'nextPageCursor': None}


def _bx(t, eid, symbol='BTCUSDT', side='Buy', price='100'):
    return {'execId': eid, 'execType': 'Trade', 'execTime': str(t),
            'symbol': symbol, 'side': side, 'execPrice': price,
            'execQty': '1', 'execFee': '0', 'orderLinkId': ''}


class HL:
    """userFillsByTime that, like the venue, answers at most HL_CAP fills —
    the NEWEST in the window, so a capped answer hides the older ones."""
    address = '0xabc'

    def __init__(self, n, base=NOW - DAY):
        self.rows = [{'coin': 'SUI', 'tid': i, 'time': base + i, 'side': 'B',
                      'px': '1', 'sz': '1', 'fee': '0', 'cloid': None}
                     for i in range(n)]
        self.calls = 0

    def user_fills_by_time(self, start_ms, end_ms=None):
        self.calls += 1
        got = [r for r in self.rows if r['time'] >= start_ms
               and (end_ms is None or r['time'] <= end_ms)]
        return got[-HL_CAP:]


def spec_R18_one_fill_once_the_newer_read_wins():
    a = _kf(5, 'x', price=100.0)
    relabelled = dict(a, price=101.0)
    out = merge([a, _kf(3, 'y')], [relabelled, _kf(9, 'z')])
    assert [f['exec_id'] for f in out] == ['y', 'x', 'z']   # time-ordered
    assert out[1]['price'] == 101.0                         # newer read wins
    other = _kf(5, 'x', venue='hyperliquid', symbol='SUI')
    assert len(merge(out, [other])) == 4      # an id is a venue's, not global


def spec_R18_a_capped_hl_answer_is_split_until_every_part_fits():
    hl = HL(2 * HL_CAP + 7)
    got = hl_history(hl, 0, NOW)
    assert len({r['tid'] for r in got}) == 2 * HL_CAP + 7   # nothing hidden
    assert hl.calls > 1


def spec_R18_backfill_first_then_onward_from_where_collection_reached():
    bx = Bybit([_bx(NOW - 100 * DAY, 'old'), _bx(NOW - 10 * DAY, 'a')])
    empty = {'version': 1, 'collected': {}, 'fills': []}
    kept, errors = collect(FLEET, empty, NOW, bybit=bx, hl=HL(3),
                           backfill_days=90)
    assert not errors
    ids = {f['exec_id'] for f in kept['fills']}
    assert 'a' in ids and 'old' not in ids                  # 90 days back
    assert kept['collected'] == {'bybit:linear:BTCUSDT': NOW,
                                 'hyperliquid': NOW}
    assert {f['venue'] for f in kept['fills']} == {'bybit', 'hyperliquid'}
    bx.calls.clear()
    later = NOW + DAY
    bx.rows.append(_bx(later - 5, 'b'))
    kept, _ = collect(FLEET, kept, later, bybit=bx, hl=HL(3))
    assert bx.calls[0][1] == NOW - OVERLAP_MS               # onward, overlapped
    assert sorted(f['exec_id'] for f in kept['fills']
                  if f['venue'] == 'bybit') == ['a', 'b']   # nothing twice


def spec_R18_a_venue_that_cannot_be_read_keeps_its_mark():
    class Down(Bybit):
        def executions_page(self, *a, **kw):
            raise OSError('reset')
    start = {'version': 1, 'collected': {'bybit:linear:BTCUSDT': 7},
             'fills': [_kf(5, 'k', venue='bybit', symbol='ETHUSDT')]}
    kept, errors = collect(FLEET, start, NOW, bybit=Down([]), hl=HL(1))
    assert errors and kept['collected']['bybit:linear:BTCUSDT'] == 7
    assert kept['collected']['hyperliquid'] == NOW          # one costs not all
    assert any(f['exec_id'] == 'k' for f in kept['fills'])  # never dropped


def spec_R18_a_market_taken_out_of_the_fleet_is_still_collected():
    bx = Bybit([_bx(NOW - DAY, 'e', symbol='ETHUSDT')])
    start = {'version': 1, 'collected': {}, 'fills': [
        _kf(NOW - 2 * DAY, 'k', symbol='ETHUSDT')]}
    kept, _ = collect(FLEET, start, NOW, bybit=bx, hl=None)
    assert 'bybit:linear:ETHUSDT' in kept['collected']
    assert {'k', 'e'} <= {f['exec_id'] for f in kept['fills']}


def spec_R18_a_ledger_that_will_not_parse_is_refused_not_restarted():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / 'demo.json'
        p.write_text('{"fills": [')
        try:
            load(p)
        except RuntimeError as e:
            assert 'move it aside' in str(e)
        else:
            raise AssertionError('a torn ledger was read as empty')
        assert p.read_text() == '{"fills": ['                # untouched


def spec_R18_keep_writes_the_fleet_ledger_and_adds_only_the_new():
    with tempfile.TemporaryDirectory() as d:
        fleet = Path(d) / 'fleet.demo.json'
        fleet.write_text(json.dumps({'bots': [{
            'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
            'capital': 1000, 'leverage': 5, 'lower': 90, 'upper': 110,
            'rungs': 5}], 'watchdog': 'x'}))
        bx = Bybit([_bx(NOW - DAY, 'a')])
        quiet = lambda fleet, clients: ({}, lambda cfg: None)   # no network
        path, added, errors = keep(str(fleet), root=d, now_ms=NOW,
                                   clients={'bybit': bx},
                                   held_and_marks=quiet)
        assert path.name == 'demo.json' and added == 1 and not errors
        _, added, _ = keep(str(fleet), root=d, now_ms=NOW + 1000,
                           clients={'bybit': bx}, held_and_marks=quiet)
        assert added == 0                                   # read again: once


def _sf_args(root, since_ms):
    key_of = {'linBTCUSDTl': ('linear', 'BTCUSDT')}
    return dict(venue_of={('linear', 'BTCUSDT'): 'bybit'}, key_of=key_of,
                since_ms=since_ms, inverse_ids=set(),
                entry_sides={'linBTCUSDTl': 'buy'},
                closers={('linear', 'BTCUSDT', 'sell'): 'linBTCUSDTl'},
                grids={}, rounders=set(), held={'linBTCUSDTl': 0.0},
                root=root)


def spec_R18_since_first_trade_is_the_kept_history_plus_the_fresh():
    """Two round trips kept from weeks ago, one fresh in the window: the
    card's window says one, since first trade says all three — and a fill
    in both is counted once."""
    link = 'linBTCUSDTl-1-a'
    old = [_kf(DAY, 'o1', link=link), _kf(DAY + 1, 'o2', side='sell',
                                           price=110.0, link=link),
           _kf(2 * DAY, 'o3', link=link), _kf(2 * DAY + 1, 'o4', side='sell',
                                              price=110.0, link=link)]
    fresh = [dict(f, venue=None) for f in
             (_kf(NOW - 10, 'n1', link=link),
              _kf(NOW - 5, 'n2', side='sell', price=110.0, link=link))]
    with tempfile.TemporaryDirectory() as d:
        Path(d, 'demo.json').write_text(json.dumps({
            'version': 1, 'collected': {'bybit:linear:BTCUSDT': NOW - 7},
            'fills': old + [_kf(NOW - 10, 'n1', link=link)]}))
        books, behind = kept_books('fleet.demo.json', fresh,
                                   **_sf_args(d, NOW - DAY))
        b = books['linBTCUSDTl']
        assert b['trips'] == 3 and abs(b['realized'] - 30.0) < 1e-9
        assert b['first_ms'] == DAY and behind['linBTCUSDTl'] is None
        # collected only up to before the window: a hole — said, not summed
        _, behind = kept_books('fleet.demo.json', fresh,
                               **_sf_args(d, NOW - 3))
        assert behind['linBTCUSDTl'] == NOW - 7
        assert kept_books('fleet.demo.json', fresh,
                          **_sf_args(str(Path(d) / 'none'), 0)) is None


def spec_R18_the_card_says_since_first_trade_or_why_not():
    from panel.server import since_first_line, exchange_since_first
    sf = {'fills': 6, 'realized': 30.0, 'fees': 1.5, 'unreal_at_mark': 0.0,
          'position': 0.0, 'trips': 3, 'strategy': 'grid', 'first_ms': DAY,
          'truncated': False, 'behind': None}
    c = {'since_first': {'linBTCUSDTl': sf}}
    line = since_first_line(c, 'linBTCUSDTl')
    assert 'kept history, since 1970-01-02' in line and '+28.50' in line
    assert '3 trips' in line
    assert since_first_line({}, 'linBTCUSDTl') == ''        # nothing kept
    c2 = {'since_first': {'linBTCUSDTl': dict(sf, behind=NOW - 7),
                          'linETHUSDTl': sf}}
    assert 'the ledger is behind' in since_first_line(c2, 'linBTCUSDTl')
    assert '+28.50' not in since_first_line(c2, 'linBTCUSDTl')
    whole = since_first_line({'since_first': {'linBTCUSDTl': {
        'fills': 9, 'whole': False, 'first_ms': DAY, 'behind': None}}},
        'linBTCUSDTl')
    assert 'no clean start' in whole and '+' not in whole
    box = exchange_since_first(c2)
    assert '+28.50' in box and '1 bot(s) left out' in box   # named, not hidden


def spec_R18_a_record_that_opens_mid_position_starts_at_its_first_flat():
    """The first backfill opened on 07-08 with bots already holding: their
    first fills were exits against a basis never seen, and one demo BTC
    pair read +181k and -202k. The record counts from the earliest moment
    the bot's own fills land on what the exchange holds now."""
    def f(t, side, qty):
        return {'time_ms': t, 'side': side, 'qty': qty}
    fills = [f(1, 'sell', 2.0),            # an exit of a position from before
             f(2, 'buy', 1.0), f(3, 'sell', 1.0),     # flat here, cleanly
             f(4, 'buy', 1.0), f(5, 'buy', 1.0)]      # holding 2 now
    assert first_flat_ms(fills, 'buy', 2.0) == 2      # not 1: before it, a hole
    assert first_flat_ms(fills, 'buy', 0.5) is None   # never lands: not whole
    assert first_flat_ms(fills, 'buy', None) is None  # unknown: never guessed
    assert first_flat_ms(fills[1:3], 'buy', 0.0) == 2
    link = 'linBTCUSDTl-1-a'
    rows = [_kf(DAY, 'p', side='sell', price=60000.0, qty=2.0, link=link),
            _kf(DAY + 1, 'q', price=100.0, link=link),
            _kf(DAY + 2, 'r', side='sell', price=110.0, link=link)]
    with tempfile.TemporaryDirectory() as d:
        Path(d, 'demo.json').write_text(json.dumps({
            'version': 1, 'collected': {'bybit:linear:BTCUSDT': NOW},
            'fills': rows}))
        books, _ = kept_books('fleet.demo.json', [], **_sf_args(d, NOW - DAY))
        b = books['linBTCUSDTl']
        assert b['whole'] and b['first_ms'] == DAY + 1
        assert abs(b['realized'] - 10.0) < 1e-9       # the phantom is gone


def spec_R18_no_clean_start_starts_fresh_once_at_an_opening_balance():
    """Owner, 2026-10-05: "make the program assume that it is starting fresh
    and records from when the bot starts." A bot holding through its whole
    kept record opens at what it holds, at the price then — after three runs
    in a row without a clean start (one lagging read is not a hole), stored
    once, surviving every later collection."""
    from gridgremlin.kept_fills import FRESH_AFTER_MISSES, settle_anchors
    fleet = {'bots': [{'venue': 'bybit', 'market_type': 'spot',
                       'symbol': 'BTCUSDT', 'side': 'long'}]}
    link = 'spoBTCUSDTl-1-a'
    kept = {'version': 1, 'collected': {}, 'fills': [
        dict(_kf(DAY, 'x', side='sell', qty=1.0, link=link),
             market_type='spot')]}                       # sells pre-record
    held, px = {'spoBTCUSDTl': 0.5}, (lambda cfg: 60000.0)
    out = kept
    for k in range(FRESH_AFTER_MISSES - 1):
        out = settle_anchors(fleet, out, NOW + k, held, px)
        assert out['anchors'] == {} and out['misses'] == {'spoBTCUSDTl': k + 1}
    assert FRESH_AFTER_MISSES >= 2                      # a lag is not a hole
    out = settle_anchors(fleet, out, NOW + 9, held, px)
    assert out['anchors'] == {'spoBTCUSDTl': {
        'kind': 'fresh', 'time_ms': NOW + 9, 'qty': 0.5, 'price': 60000.0}}
    again = settle_anchors(fleet, out, NOW + DAY, {'spoBTCUSDTl': 0.2},
                           lambda cfg: 1.0)
    assert again['anchors'] == out['anchors']            # once, fixed
    kept2, _ = collect({'bots': []}, out, NOW + DAY)     # survives a run
    assert kept2['anchors'] == out['anchors']
    waits = settle_anchors(fleet, dict(kept, misses={'spoBTCUSDTl': 5}),
                           NOW, held, lambda c: None)
    assert waits['anchors'] == {}                        # no price: waits
    assert settle_anchors(fleet, kept, NOW, {}, px)['misses'] == {}   # no
                                                         # figure: no count


def spec_R18_a_clean_start_is_stored_so_a_lag_cannot_lose_it():
    """The demo BTC pair landed clean at 13:48 and missed at 14:20 — the
    venue's fill list lagging its position (G26). Stored when found, the
    anchor holds through the lag; no fresh start is ever opened over it."""
    from gridgremlin.kept_fills import settle_anchors
    fleet = {'bots': [{'venue': 'bybit', 'market_type': 'linear',
                       'symbol': 'BTCUSDT', 'side': 'long'}]}
    link = 'linBTCUSDTl-1-a'
    rows = [_kf(DAY, 'a', price=100.0, link=link),
            _kf(DAY + 1, 'b', side='sell', price=110.0, link=link),
            _kf(DAY + 2, 'c', price=100.0, link=link)]           # holds 1
    kept = {'version': 1, 'collected': {'bybit:linear:BTCUSDT': NOW},
            'fills': rows}
    out = settle_anchors(fleet, kept, NOW, {'linBTCUSDTl': 1.0},
                         lambda c: 100.0)
    assert out['anchors'] == {'linBTCUSDTl': {'kind': 'clean',
                                              'time_ms': DAY}}
    for k in range(3):                                   # the lag: 2.0 held,
        out = settle_anchors(fleet, out, NOW + k, {'linBTCUSDTl': 2.0},
                             lambda c: 100.0)            # one fill unlisted
    assert out['anchors']['linBTCUSDTl']['kind'] == 'clean'
    with tempfile.TemporaryDirectory() as d:
        Path(d, 'demo.json').write_text(json.dumps(out))
        args = _sf_args(d, NOW - DAY)
        args['held'] = {'linBTCUSDTl': 2.0}             # the readout lags too
        books, _ = kept_books('fleet.demo.json', [], **args)
        b = books['linBTCUSDTl']
        assert b['whole'] and b['first_ms'] == DAY
        assert abs(b['realized'] - 10.0) < 1e-9


def spec_R18_a_fresh_start_counts_on_from_its_opening_balance():
    """Opened holding 0.5 at 100, sold at 110 (+5); then a full trip from
    flat (+10). That later flat is a clean start too — it must not move the
    anchor and drop the +5 before it."""
    link = 'linBTCUSDTl-1-a'
    rows = [_kf(DAY, 'p', side='sell', qty=2.0, link=link),     # pre-record
            _kf(NOW - 50, 'q', side='sell', price=110.0, qty=0.5, link=link),
            _kf(NOW - 40, 'r', price=100.0, qty=1.0, link=link),     # a later
            _kf(NOW - 30, 's', side='sell', price=110.0, qty=1.0,    # clean
                link=link)]                                          # flat
    with tempfile.TemporaryDirectory() as d:
        Path(d, 'demo.json').write_text(json.dumps({
            'version': 1, 'collected': {'bybit:linear:BTCUSDT': NOW},
            'fills': rows, 'anchors': {'linBTCUSDTl': {
                'kind': 'fresh', 'time_ms': NOW - 100, 'qty': 0.5,
                'price': 100.0}}}))
        books, _ = kept_books('fleet.demo.json', [], **_sf_args(d, NOW - DAY))
        b = books['linBTCUSDTl']
        assert b['whole'] and b['opened']['price'] == 100.0
        assert abs(b['realized'] - 15.0) < 1e-9 and abs(b['position']) < 1e-12
        assert b['first_ms'] == NOW - 100


def spec_R18_the_card_says_where_a_fresh_record_opened():
    from panel.server import since_first_line
    sf = {'fills': 2, 'realized': 5.0, 'fees': 0.0, 'unreal_at_mark': 0.0,
          'position': 0.0, 'trips': 1, 'strategy': 'grid',
          'first_ms': DAY, 'truncated': False, 'behind': None,
          'whole': True, 'opened': {'time_ms': DAY, 'qty': 0.5,
                                    'price': 100.0}}
    line = since_first_line({'since_first': {'b': sf}}, 'b')
    assert 'fresh from 1970-01-02' in line and 'opened holding 0.5 at 100' in line
    assert '+5.00' in line
