"""F39–F41 (D-number: owner to assign, the lead proposes D156): the daily
drift check — the kept ledger beside the venue's own record. Fakes only:
the venue is a fixed history behind the clients' read seams."""
import inspect
import json
import tempfile
from pathlib import Path

from gridgremlin import pnl_drift as pd
from gridgremlin.exchange.hyperliquid.signing import link_to_cloid

DAY = 86_400_000
NOW = 40 * DAY
T0 = NOW - 3 * DAY
HOUR = 3_600_000
GRID = {'lower': 90.0, 'upper': 110.0, 'rungs': 21, 'spacing_type': 'linear'}   # rung j at 90 + j


def _cfg(side='long', sym='BTCUSDT', mt='linear', venue='bybit', **kw):
    return dict(GRID, venue=venue, market_type=mt, symbol=sym, side=side, **kw)


def _bot(cfg):
    from gridgremlin.report import make_botid
    return make_botid(cfg['market_type'], cfg['symbol'], cfg['side'])


def _ladder(cfg):
    """U113's case on a real book: bought down four rungs, sold one up —
    (time, side, rung, price, qty, fee) — or a short's mirror."""
    long = cfg['side'] == 'long'
    e, x, step = ('buy', 'sell', -1) if long else ('sell', 'buy', 1)
    rows = [(T0 + i * HOUR, e, 10 + step * i, 100.0 + step * i, 1.0, 0.01) for i in range(4)]
    rows.append((T0 + 4 * HOUR, x, 10 + step * 2, 100.0 + step * 2, 1.0, 0.02))
    return rows


def _ledger_fill(cfg, i, t, side, rung, price, qty, fee):
    b = _bot(cfg)
    return {'venue': 'hyperliquid' if cfg['venue'] == 'hyperliquid' else 'bybit',
            'market_type': cfg['market_type'], 'symbol': cfg['symbol'], 'exec_id': f'{b}x{i}',
            'time_ms': t, 'side': side, 'price': price, 'qty': qty, 'fee': fee,
            'link_id': f'{b}-{rung}-a{i}', 'venue_closed': False, 'venue_kind': ''}


def _book(cfgs, rows_of=_ladder):
    """(kept ledger, venue executions) agreeing, for these bots."""
    from gridgremlin.report import kept_venue_key
    fills = []
    for cfg in cfgs:
        fills += [_ledger_fill(cfg, i, *r) for i, r in enumerate(rows_of(cfg))]
    fills.sort(key=lambda f: f['time_ms'])
    kept = {'fills': fills, 'collected': {kept_venue_key(c['venue'], c['market_type'], c['symbol']): NOW
                                          for c in cfgs},
            'anchors': {_bot(c): {'kind': 'clean', 'time_ms': T0 - DAY} for c in cfgs}}
    return kept, [dict(f) for f in fills]


def _closed(fills, cfg):
    """The venue's closed P&L rows for a bot's exits — the average-cost
    gross less the open and close fees it nets, as Bybit states it."""
    from gridgremlin.report import apply_fill, new_book
    book, rows = new_book(), []
    entry = 'buy' if cfg['side'] == 'long' else 'sell'
    inverse = cfg['market_type'] == 'inverse'
    for f in fills:
        if f['symbol'] != cfg['symbol'] or (not f['link_id'].startswith(_bot(cfg) + '-')):
            continue
        before, avg = book['realized'], book['avg_cost']
        apply_fill(book, f['side'], f['price'], f['qty'], f['fee'], inverse=inverse)
        if f['side'] != entry:
            gross = book['realized'] - before
            rows.append({'orderId': f.get('order_id', f['exec_id']), 'createdTime': str(f['time_ms']),
                         'side': 'Buy' if f['side'] == 'buy' else 'Sell',
                         'closedSize': str(f['qty']), 'closedPnl': str(gross - 0.01 - f['fee']),
                         'openFee': '0.01', 'closeFee': str(f['fee']),
                         'cumEntryValue': repr(f['qty'] / avg if inverse else f['qty'] * avg),
                         'cumExitValue': repr(f['qty'] / f['price'] if inverse else f['qty'] * f['price']),
                         'avgEntryPrice': str(avg)})
    return rows


class Bybit:
    """The read seams the collector uses, over a fixed history; anything
    else is refused (the no-writes spec reads `calls`)."""
    READS = {'executions_page', 'closed_pnl_page'}

    def __init__(self, fills, closed, fail=None):
        self.fills, self.closed, self.fail, self.calls = fills, closed, fail, []

    def __getattr__(self, name):            # any other method: recorded, answered with nothing
        if name.startswith('_'):
            raise AttributeError(name)
        return lambda *a, **k: self.calls.append(name)

    def executions_page(self, category, symbol, start_ms, end_ms, cursor=None, exec_type=None):
        self.calls.append('executions_page')
        if self.fail:
            raise RuntimeError(self.fail)
        rows = [{'execId': f['exec_id'], 'execType': 'Trade', 'execTime': str(f['time_ms']),
                 'symbol': f['symbol'], 'side': 'Buy' if f['side'] == 'buy' else 'Sell',
                 'execPrice': str(f['price']), 'execQty': str(f['qty']), 'execFee': str(f['fee']),
                 'orderLinkId': f['link_id'], 'closedSize': '0', 'createType': 'CreateByUser',
                 'orderId': f.get('order_id', f['exec_id'])}
                for f in self.fills if f['symbol'] == symbol and f['market_type'] == category
                and start_ms <= f['time_ms'] <= end_ms]
        return {'list': rows, 'nextPageCursor': ''}

    def closed_pnl_page(self, category, symbol, start_ms, end_ms, cursor=None):
        self.calls.append('closed_pnl_page')
        return {'list': [r for r in self.closed if start_ms <= int(r['createdTime']) <= end_ms],
                'nextPageCursor': ''}


def _run(cfgs, kept, client, **kw):
    fleet = {'bots': cfgs}
    return pd.check_fleet(fleet, kept, NOW, {'bybit': client}, **kw)


def _agreeing(cfgs=None):
    cfgs = cfgs or [_cfg()]
    kept, venue = _book(cfgs)
    closed = [r for c in cfgs for r in _closed(venue, c)]
    return cfgs, kept, venue, closed


def _said(report):
    return pd.problems(report, NOW / 1000)


# --- F39: fills ---------------------------------------------------------------

def spec_F39_an_agreeing_book_is_silent():
    cfgs, kept, venue, closed = _agreeing()
    r = _run(cfgs, kept, Bybit(venue, closed))
    assert _said(r) == [], _said(r)
    e = r['bots'][_bot(cfgs[0])]
    assert e['missing'] == e['extra'] == e['changed'] == []
    assert e['realised'] and not e['realised']['off'] and abs(e['realised']['ours'] + 0.5) < 1e-9
    assert e['identity'] and not e['identity']['off']
    with tempfile.TemporaryDirectory() as d:
        Path(d, 'demo.json').write_text(json.dumps(r))
        assert pd.digest_lines(d, NOW / 1000) == []                      # the digest says nothing


def spec_F39_a_fill_dropped_from_the_ledger_is_named_by_id():
    cfgs, kept, venue, closed = _agreeing()
    lost = kept['fills'].pop(1)
    said = _said(_run(cfgs, kept, Bybit(venue, closed)))
    assert any('1 fill missing from the ledger' in s and lost['exec_id'] in s for s in said), said
    with tempfile.TemporaryDirectory() as d:
        Path(d, 'demo.json').write_text(json.dumps(_run(cfgs, kept, Bybit(venue, closed))))
        line = pd.digest_lines(d, NOW / 1000)
        assert len(line) == 1 and line[0].startswith('📏 drift · demo: linBTCUSDTl 1 fill missing')


def spec_F39_a_ledger_fill_the_venue_does_not_list_is_named():
    cfgs, kept, venue, closed = _agreeing()
    venue = [f for f in venue if f['exec_id'] != kept['fills'][0]['exec_id']]
    said = _said(_run(cfgs, kept, Bybit(venue, closed)))
    assert any('in the ledger the venue does not list (linBTCUSDTlx0)' in s for s in said), said


def spec_F39_a_fill_the_venue_restated_is_named():
    cfgs, kept, venue, closed = _agreeing()
    venue[2] = dict(venue[2], fee=0.5)
    said = _said(_run(cfgs, kept, Bybit(venue, closed)))
    assert any("differ from the venue's (linBTCUSDTlx2)" in s for s in said), said


def spec_F39_the_newest_hour_is_the_collectors_to_finish():
    """A fill the venue lists inside the hour before the ledger's mark is
    not yet missing: the collector re-reads an hour back (R18)."""
    cfgs, kept, venue, closed = _agreeing()
    late = dict(venue[-1], exec_id='late', time_ms=NOW - HOUR // 2, link_id='linBTCUSDTl-10-late')
    r = _run(cfgs, kept, Bybit(venue + [late], closed))
    assert r['bots'][_bot(cfgs[0])]['missing'] == []


def spec_F39_a_failed_venue_read_is_said_never_agreement():
    cfgs, kept, venue, closed = _agreeing()
    r = _run(cfgs, kept, Bybit(venue, closed, fail='timed out'))
    said = _said(r)
    assert said and "couldn't read bybit linear BTCUSDT: timed out" in said[0], said
    assert _bot(cfgs[0]) not in r['bots']                                 # nothing judged, nothing clean
    with tempfile.TemporaryDirectory() as d:
        Path(d, 'demo.json').write_text(json.dumps(r))
        assert "couldn't read bybit" in pd.digest_lines(d, NOW / 1000)[0]


def spec_F39_an_old_report_is_said():
    """The check runs minutes before the digest; a report hours old means
    it did not run, and the digest says so rather than its old silence."""
    cfgs, kept, venue, closed = _agreeing()
    r = _run(cfgs, kept, Bybit(venue, closed))
    assert pd.problems(r, NOW / 1000 + 5 * 3600) == ['report 5 h old — did the check run?']


def spec_F39_a_hedge_pair_shares_its_market_and_each_fill_is_named_by_its_link():
    """I2 lets a long and a short share a market on one account; each fill
    is its bot's by link (R1), and each bot's realised is the venue's
    closing rows on its own exit side."""
    cfgs = [_cfg('long'), _cfg('short')]
    cfgs, kept, venue, closed = _agreeing(cfgs)
    assert _said(_run(cfgs, kept, Bybit(venue, closed))) == []
    lost = next(f for f in kept['fills'] if f['link_id'].startswith('linBTCUSDTs-'))
    kept['fills'].remove(lost)
    said = _said(_run(cfgs, kept, Bybit(venue, closed)))
    assert any(s.startswith('linBTCUSDTs 1 fill missing') and lost['exec_id'] in s for s in said), said
    assert not any(s.startswith('linBTCUSDTl') for s in said)


def spec_F39_two_fleets_on_one_market_are_noted():
    a = {'account': 'default', 'bots': [_cfg()]}
    b = {'account': 'default', 'bots': [_cfg('short')]}
    c = {'account': 'carry', 'bots': [_cfg()]}
    got = pd._shared([('demo', a), ('slow', b), ('carry', c)])
    assert got['demo'] == {('bybit', 'linear', 'BTCUSDT'): ['slow']} and got['carry'] == {}


# --- F40: realised ------------------------------------------------------------

def spec_F40_realised_off_past_the_tolerance_is_reported_within_it_is_not():
    cfgs, kept, venue, closed = _agreeing()
    near = [dict(r, cumExitValue=repr(float(r['cumExitValue']) + 0.005)) for r in closed]
    assert _said(_run(cfgs, kept, Bybit(venue, near))) == []             # rounding: inside
    far = [dict(r, cumExitValue=repr(float(r['cumExitValue']) + 0.4)) for r in closed]
    said = _said(_run(cfgs, kept, Bybit(venue, far)))
    assert said == ['linBTCUSDTl realised -0.50 vs venue -0.10'], said
    r = _run(cfgs, kept, Bybit(venue, closed))['bots'][_bot(cfgs[0])]['realised']
    assert abs(r['tol'] - (0.01 + 1e-4 * 98.0)) < 1e-12                   # a cent + 1 bp of 98 closed


def spec_F40_an_inverse_book_is_compared_in_its_coin():
    cfg = _cfg(sym='BTCUSD', mt='inverse')
    cfgs, kept, venue, closed = _agreeing([cfg])
    r = _run(cfgs, kept, Bybit(venue, closed))
    e = r['bots'][_bot(cfg)]
    assert _said(r) == [] and e['unit'] == 'BTC'
    avg = 4 / sum(1 / p for p in (100.0, 99.0, 98.0, 97.0))                 # the harmonic entry (R2)
    assert abs(e['realised']['ours'] - (1 / avg - 1 / 98.0)) < 1e-15 and e['realised']['ours'] < 0
    far = [dict(x, cumEntryValue=repr(float(x['cumEntryValue']) + 0.01)) for x in closed]
    said = _said(_run(cfgs, kept, Bybit(venue, far)))
    assert len(said) == 1 and 'BTC vs venue' in said[0], said


def spec_F40_a_fill_no_bot_owns_leaves_realised_uncompared_and_says_why():
    """A hand's trade moves the venue's position and no book of ours: the
    two figures cannot agree, so they are not compared — said in show."""
    cfgs, kept, venue, closed = _agreeing()
    hand = dict(kept['fills'][0], exec_id='hand', link_id='', side='buy', time_ms=T0 + 30 * 60_000)
    kept['fills'].append(hand)
    venue.append(dict(hand))
    e = _run(cfgs, kept, Bybit(venue, [dict(r, closedPnl='9') for r in closed]))['bots'][_bot(cfgs[0])]
    assert e['realised'] is None and 'belong to no bot' in e['realised_note']


def spec_F40_a_fresh_anchor_is_compared_from_its_first_flat():
    """A fresh record opens at the holding's price, not the venue's entry
    (R18): never compared before it is flat again, then from there."""
    cfg = _cfg()
    cfgs, kept, venue, closed = _agreeing([cfg])
    kept['anchors'] = {_bot(cfg): {'kind': 'fresh', 'time_ms': T0 - HOUR, 'qty': 2.0, 'price': 95.0}}
    e = _run(cfgs, kept, Bybit(venue, closed))['bots'][_bot(cfg)]
    assert e['realised'] is None and 'fresh anchor' in e['realised_note']
    assert e['identity'] is None and 'fresh anchor' in e['identity_note']


def spec_F40_bybit_closed_pnl_is_read_in_7_day_windows_every_cursor_followed():
    from gridgremlin.exchange.bybit.truth import read_closed_pnl
    seen = []

    class Paged:
        def closed_pnl_page(self, category, symbol, start_ms, end_ms, cursor=None):
            seen.append((start_ms, end_ms, cursor))
            assert end_ms - start_ms <= 7 * DAY
            if cursor is None:
                return {'list': [{'orderId': 'a', 'createdTime': str(start_ms + 1), 'side': 'Sell',
                                  'closedSize': '1', 'closedPnl': '1.0', 'openFee': '0.1',
                                  'closeFee': '0.2', 'cumEntryValue': '98.7', 'cumExitValue': '100'}], 'nextPageCursor': 'p2'}
            return {'list': [{'orderId': 'b', 'createdTime': str(start_ms + 2), 'side': 'Buy',
                              'closedSize': '1', 'closedPnl': '-1.0', 'openFee': '0',
                              'closeFee': '0', 'cumEntryValue': '49', 'cumExitValue': '50'}], 'nextPageCursor': ''}
    rows = read_closed_pnl(Paged(), 'linear', 'BTCUSDT', 0, 10 * DAY)
    assert [(s, e) for s, e, c in seen if c is None] == [(0, 7 * DAY), (7 * DAY, 10 * DAY)]
    assert len(rows) == 4 and abs(rows[0]['gross'] - 1.3) < 1e-12 and rows[0]['side'] == 'sell'
    assert abs(rows[0]['stated'] - 1.3) < 1e-12                            # closedPnl + both fees
    assert abs(rows[1]['gross'] + 1.0) < 1e-12 and rows[1]['side'] == 'buy'  # a short: entry − exit
    inv = read_closed_pnl(Paged(), 'inverse', 'BTCUSD', 0, DAY)               # values in the coin
    assert abs(inv[0]['gross'] + 1.3) < 1e-12 and abs(inv[1]['gross'] - 1.0) < 1e-12


def spec_F40_gross_is_the_rows_own_values_whatever_closedpnl_holds():
    """The venue's closedPnl may carry what the trade did not (funding, a
    fee taken another way): the gross is the row's values, and what
    closedPnl holds besides is the residue `show` prints."""
    cfgs, kept, venue, closed = _agreeing()
    odd = [dict(r, closedPnl=str(float(r['closedPnl']) - 3.0)) for r in closed]   # funding inside
    r = _run(cfgs, kept, Bybit(venue, odd))
    assert _said(r) == []
    e = r['bots'][_bot(cfgs[0])]['realised']
    assert abs(e['residue'] + 3.0) < 1e-9
    assert any('fees/funding residue): -3.00000000' in line for line in pd.details(r))


# --- F41: the U113 identity on the real book -------------------------------------

def spec_F41_the_identity_holds_on_an_agreeing_book_long_and_short():
    for side in ('long', 'short'):
        cfgs, kept, venue, closed = _agreeing([_cfg(side)])
        i = _run(cfgs, kept, Bybit(venue, closed))['bots'][_bot(cfgs[0])]['identity']
        assert not i['off'] and abs(i['gap']) < 1e-9, (side, i)
        assert abs(i['gross'] - 1.0) < 1e-9 and abs(i['realised'] + 0.5) < 1e-9
        assert abs(i['shift'] - 1.5) < 1e-9 and i['lots_qty'] == 3.0 == i['position']


def spec_F41_an_entry_lost_before_the_window_is_said_by_the_walk():
    """The exit's entry fell out of the ledger before the look-back, so
    check 1 cannot see it. While other lots are held the exit consumes the
    newest of them (G23, 2026-10-31) — here the rung-8 lot, its own rung:
    a same-rung exit, counted in `show`, not a failure. When the lost
    entries leave nothing held, the exit closes no lot — said."""
    cfgs, kept, venue, closed = _agreeing()
    b = _bot(cfgs[0])
    kept['anchors'][b]['time_ms'] = NOW - 11 * DAY                       # the record began earlier
    for f in venue:
        if f['link_id'].startswith(b + '-7-'):
            f['time_ms'] = NOW - 10 * DAY                                # the entry, before the look-back
    kept['fills'] = [f for f in kept['fills'] if not f['link_id'].startswith(b + '-7-')]
    r = _run(cfgs, kept, Bybit(venue, closed))
    i = r['bots'][b]['identity']
    assert r['bots'][b]['missing'] == [] and i['no_lot'] == 0 and i['same_rung'] == 1, i
    assert not i['off'] and i['first_off'] is None
    assert any('same-rung exits (R9, a trip of ~0): 1' in line for line in pd.details(r))
    # every entry lost: the whole inventory is empty when the exit comes
    cfgs, kept, venue, closed = _agreeing()
    kept['anchors'][b]['time_ms'] = NOW - 11 * DAY
    for f in venue:
        if f['side'] == 'buy':
            f['time_ms'] = NOW - 10 * DAY
    kept['fills'] = [f for f in kept['fills'] if f['side'] != 'buy']
    r = _run(cfgs, kept, Bybit(venue, closed))
    assert r['bots'][b]['identity']['no_lot'] == 1, r['bots'][b]
    said = _said(r)
    assert any('1 exit close no lot the record holds' in s for s in said), said


def spec_F41_a_tampered_book_is_reported():
    """Sabotage: were the book's average-cost walk wrong — its realised
    moved by a cent — the identity no longer closes and says by how much."""
    import gridgremlin.fill_list as fl
    cfgs, kept, venue, closed = _agreeing()
    real = fl.fill_list

    def tampered(*a, **k):
        got = real(*a, **k)
        return dict(got, realized=got['realized'] + 0.01)
    fl.fill_list = tampered
    try:
        i = _run(cfgs, kept, Bybit(venue, closed))['bots'][_bot(cfgs[0])]['identity']
    finally:
        fl.fill_list = real
    assert i['off'] and abs(i['gap'] + 0.01) < 1e-9
    assert 'the open lots say +1.50' in pd.problems({'t': NOW / 1000, 'bots': {'b': {'identity': i}}},
                                                    NOW / 1000)[0]


def spec_F41_a_dca_is_checked_for_fills_and_realised_not_the_identity():
    cfg = {'venue': 'bybit', 'market_type': 'linear', 'symbol': 'ETHUSDT', 'side': 'long',
           'strategy': 'martingale'}
    cfgs, kept, venue, closed = _agreeing([cfg])
    e = _run(cfgs, kept, Bybit(venue, closed))['bots'][_bot(cfg)]
    assert e['kind'] == 'dca' and e['identity'] is None and e['realised'] is not None
    assert _said(_run(cfgs, kept, Bybit(venue, closed))) == []


# --- Hyperliquid ------------------------------------------------------------------

class HL:
    address = '0x' + 'ab' * 20

    def __init__(self, raw):
        self.raw, self.calls = raw, []

    def user_fills_by_time(self, start_ms, end_ms=None):
        self.calls.append('user_fills_by_time')
        return [f for f in self.raw if start_ms <= f['time'] <= (end_ms or 1 << 62)]


def spec_F39_hyperliquid_fills_and_closed_pnl_agree_and_a_drop_is_named():
    cfg = _cfg(sym='BTC', venue='hyperliquid')
    kept, venue = _book([cfg])
    gross = {f['exec_id']: g for f, g in zip(venue, [0, 0, 0, 0, -0.5])}
    raw = [{'coin': 'BTC', 'tid': f['exec_id'], 'time': f['time_ms'], 'side': 'B' if f['side'] == 'buy' else 'A',
            'px': str(f['price']), 'sz': str(f['qty']), 'fee': str(f['fee']),
            'cloid': link_to_cloid(f['link_id']), 'closedPnl': str(gross[f['exec_id']])} for f in venue]
    fleet = {'bots': [cfg]}
    r = pd.check_fleet(fleet, kept, NOW, {'hl': HL(raw)})
    assert pd.problems(r, NOW / 1000) == [], pd.problems(r, NOW / 1000)
    kept['fills'].pop(0)
    said = pd.problems(pd.check_fleet(fleet, kept, NOW, {'hl': HL(raw)}), NOW / 1000)
    assert any(f'missing from the ledger ({_bot(cfg)}x0)' in s for s in said), said


# --- portfolio rows ---------------------------------------------------------------

def spec_F39_a_portfolio_rows_fill_it_never_settled_is_named():
    from gridgremlin.portfolio import validate_portfolio
    row = validate_portfolio({'strategy': 'portfolio', 'name': 'carry', 'venue': 'bybit', 'capital': 1000,
                              'assets': [{'coin': 'SOL', 'weight': 0.5}, {'coin': 'ETH', 'weight': 0.5}],
                              'hedge': {'ratio': 1.0, 'product': 'usdt'}})
    fills = [{'venue': 'bybit', 'market_type': 'linear', 'symbol': 'SOLUSDT', 'exec_id': f'h{i}',
              'time_ms': T0 + i * HOUR, 'side': 'sell', 'price': 100.0, 'qty': 1.0, 'fee': 0.01,
              'link_id': f'pfocarry-h{i}'} for i in range(3)]
    state = {'pfocarry': {'since_ms': T0 - 200 * DAY, 'fills_to_ms': NOW, 'seen': ['h0', 'h2'], 'books': {}}}
    r = pd.check_fleet({'bots': [row]}, {'fills': []}, NOW, {'bybit': Bybit(fills, [])},
                       portfolio_rows=state)
    said = pd.problems(r, NOW / 1000)
    assert said == ['pfocarry 1 fill missing from the ledger (h1)'], said
    assert 'portfolio_rebuild' in r['bots']['pfocarry']['realised_note']


# --- read-only by construction --------------------------------------------------

WRITES = ('WriteClient', 'place_order', 'place_market', 'cancel_order', 'amend_order',
          'set_trading_stop', 'set_leverage', 'set_risk_limit', 'ensure_hedge_mode',
          'ensure_collateral', 'exchange_action', '_post(', '.post(', 'ExchangeClient')


def writes_in(src):
    return [w for w in WRITES if w in src]


def spec_F39_nothing_here_can_reach_a_venue_write():
    """The check holds only read clients: no write method's name is in its
    source, and run against a venue that records every call it reads and
    nothing else."""
    assert writes_in(inspect.getsource(pd)) == []
    cfgs, kept, venue, closed = _agreeing([_cfg('long'), _cfg('short')])
    client = Bybit(venue, closed)
    _run(cfgs, kept, client)
    assert client.calls and set(client.calls) <= Bybit.READS


def spec_F39_sabotage_a_write_in_the_check_is_caught():
    """The guard bites both ways: a write call added to the module's source
    is named by the scan, and a write the check made at run time is in the
    venue's record of calls, which the spec above holds to reads."""
    src = inspect.getsource(pd).replace('def owner_name(', "def _x(c):\n    c.cancel_order('linear', 'X', 1)\n\n\ndef owner_name(")
    assert writes_in(src) == ['cancel_order']
    cfgs, kept, venue, closed = _agreeing()
    client = Bybit(venue, closed)
    real = pd.venue_fills

    def writing(clients, *a):
        clients['bybit'].place_order('linear', 'BTCUSDT', 'Buy', 1, 1, 'x')
        return real(clients, *a)
    pd.venue_fills = writing
    try:
        _run(cfgs, kept, client)
    finally:
        pd.venue_fills = real
    assert 'place_order' in client.calls and not set(client.calls) <= Bybit.READS


# --- the run and the digest -------------------------------------------------------

def spec_F39_a_fleet_that_cannot_be_checked_is_written_as_unread():
    with tempfile.TemporaryDirectory() as d:
        bad = Path(d, 'fleet.gone.json')
        bad.write_text('{not json')
        (path, report), = pd.run([str(bad)], root=d, now_ms=NOW)
        assert path.name == 'gone.json' and report['unread']
        said = pd.problems(json.loads(path.read_text()), NOW / 1000)
        assert said[0].startswith("couldn't read the fleet")


def spec_F39_the_digest_carries_the_drift_lines_and_only_when_off():
    from gridgremlin.digest import build
    cfgs, kept, venue, closed = _agreeing()
    with tempfile.TemporaryDirectory() as d:
        Path(d, 'demo.json').write_text(json.dumps(_run(cfgs, kept, Bybit(venue, closed))))
        text, _ = build([d + '/fleet.demo.json'], now=NOW / 1000, drift_root=d, hygiene_root=d + '/none')
        assert '📏' not in text
        kept['fills'].pop(0)
        Path(d, 'demo.json').write_text(json.dumps(_run(cfgs, kept, Bybit(venue, closed))))
        text, _ = build([d + '/fleet.demo.json'], now=NOW / 1000, drift_root=d, hygiene_root=d + '/none')
        assert '📏 drift · demo: linBTCUSDTl 1 fill missing from the ledger (linBTCUSDTlx0)' in text


def spec_F39_the_digest_unit_runs_the_check_before_the_digest_and_never_fails_for_it():
    unit = (Path(__file__).resolve().parents[1] / 'ops' / 'systemd' / 'digest.service.template').read_text()
    pre = [l for l in unit.splitlines() if l.startswith('ExecStartPre=')]
    assert pre[0].endswith('gridgremlin.kept_fills configs/{{FLEET_CONFIG}} {{MORE_FLEET_CONFIGS}}')
    assert pre[1].startswith('ExecStartPre=-/usr/bin/timeout 600 /usr/bin/python3 -m gridgremlin.pnl_drift run ')


# --- the review of 2026-10-31: what a mutation survived ---------------------------

def _mark(kept, at):
    from gridgremlin.report import kept_venue_key
    k = kept_venue_key('bybit', 'linear', 'BTCUSDT')
    if at is None:
        kept['collected'].pop(k, None)
    else:
        kept['collected'][k] = at


def spec_F39_a_ledger_behind_by_days_says_so_though_its_window_agrees():
    """The collector stopped after the ladder: the window is shorter, and
    whatever the venue listed since is unjudged — said, never clean."""
    cfgs, kept, venue, closed = _agreeing()
    _mark(kept, T0 + 5 * HOUR)
    late = dict(venue[-1], exec_id='lost', time_ms=NOW - DAY, link_id='linBTCUSDTl-10-z')
    said = _said(_run(cfgs, kept, Bybit(venue + [late], closed)))
    assert said == ['ledger collected linear BTCUSDT only to 1970-02-07 05:00 UTC'], said


def spec_F39_a_ledger_behind_the_whole_window_still_says_its_bots():
    cfgs, kept, venue, closed = _agreeing()
    _mark(kept, NOW - 8 * DAY)
    r = _run(cfgs, kept, Bybit(venue, closed))
    assert _said(r) == ['ledger collected linear BTCUSDT only to 1970-02-02 00:00 UTC'], _said(r)
    assert 'stops before the window' in r['bots'][_bot(cfgs[0])]['note']


def spec_F39_a_market_the_ledger_never_collected_is_said():
    cfgs, kept, venue, closed = _agreeing()
    _mark(kept, None)
    assert _said(_run(cfgs, kept, Bybit(venue, closed))) == ['ledger has never collected linear BTCUSDT']


def spec_F39_a_ledger_an_hour_behind_is_not_behind():
    cfgs, kept, venue, closed = _agreeing()
    _mark(kept, NOW - HOUR)
    assert _said(_run(cfgs, kept, Bybit(venue, closed))) == []


def spec_F40_a_closed_pnl_read_that_fails_is_said_as_unread():
    cfgs, kept, venue, closed = _agreeing()

    class NoClosed(Bybit):
        def closed_pnl_page(self, *a, **k):
            raise RuntimeError('boom')
    r = _run(cfgs, kept, NoClosed(venue, closed))
    assert _said(r) == ["couldn't read bybit linear BTCUSDT closed P&L: boom"], _said(r)
    assert r['bots'][_bot(cfgs[0])]['realised'] is None


def spec_F40_the_closed_pnl_page_cap_is_said_as_unread():
    import gridgremlin.exchange.bybit.truth as truth
    cfgs, kept, venue, closed = _agreeing()

    class Endless(Bybit):
        def closed_pnl_page(self, *a, **k):
            return {'list': [], 'nextPageCursor': 'more'}
    real, truth.MAX_ORDER_PAGES = truth.MAX_ORDER_PAGES, 3
    try:
        said = _said(_run(cfgs, kept, Endless(venue, closed)))
    finally:
        truth.MAX_ORDER_PAGES = real
    assert said == ["couldn't read bybit linear BTCUSDT closed P&L: BTCUSDT: closed P&L beyond 3 pages"], said


def spec_F40_an_order_across_the_window_is_left_out_of_both_sides():
    """A resting exit filled in part inside the window and in part after
    it: the venue's row is the whole order, ours the part — neither is
    compared, every day it rests, and the rest still agrees."""
    cfgs, kept, venue, closed = _agreeing()
    b = _bot(cfgs[0])
    part = dict(_ledger_fill(cfgs[0], 9, T0 + 6 * HOUR, 'sell', 9, 99.0, 0.5, 0.01), order_id='rest')
    kept['fills'].append(part)
    venue.append(dict(part))
    row = {'orderId': 'rest', 'createdTime': str(T0 + 6 * HOUR), 'side': 'Sell', 'closedSize': '1.0',
           'closedPnl': '5', 'openFee': '0', 'closeFee': '0', 'cumEntryValue': '90', 'cumExitValue': '99'}
    r = _run(cfgs, kept, Bybit(venue, closed + [row]))
    e = r['bots'][b]['realised']
    assert _said(r) == [] and e['straddling'] == 1 and abs(e['ours'] + 0.5) < 1e-9, e
    row = dict(row, closedSize='0.5')                       # whole inside: compared, and off
    assert _said(_run(cfgs, kept, Bybit(venue, closed + [row])))


def spec_F40_a_fresh_anchor_flat_mid_window_is_compared_from_that_flat():
    """The opening balance's own close realises against the price recording
    began, the venue's against its entry: from the next fill on they agree."""
    cfg = _cfg()
    b = _bot(cfg)

    def rows(_):
        return [(T0, 'sell', 11, 96.0, 1.0, 0.01), (T0 + HOUR, 'buy', 10, 100.0, 1.0, 0.01),
                (T0 + 2 * HOUR, 'buy', 9, 99.0, 1.0, 0.01), (T0 + 3 * HOUR, 'sell', 10, 100.0, 1.0, 0.01)]
    kept, venue = _book([cfg], rows)
    kept['anchors'] = {b: {'kind': 'fresh', 'time_ms': T0 - HOUR, 'qty': 1.0, 'price': 95.0}}
    closed = [{'orderId': f'{b}x{i}', 'createdTime': str(t), 'side': 'Sell', 'closedSize': '1',
               'closedPnl': '0', 'openFee': '0', 'closeFee': '0', 'cumEntryValue': repr(entry),
               'cumExitValue': repr(px)}
              for i, t, entry, px in ((0, T0, 90.0, 96.0), (3, T0 + 3 * HOUR, 99.5, 100.0))]
    e = _run([cfg], kept, Bybit(venue, closed))['bots'][b]['realised']
    assert e['from_ms'] == T0 + 1 and not e['off'] and abs(e['ours'] - 0.5) < 1e-9, e


def spec_F41_lots_that_do_not_add_up_to_the_book_are_said():
    cfgs, kept, venue, closed = _agreeing()
    real = pd.open_lots
    pd.open_lots = lambda *a: dict(real(*a), lots=real(*a)['lots'][1:])   # a lot the walk lost
    try:
        said = _said(_run(cfgs, kept, Bybit(venue, closed)))
    finally:
        pd.open_lots = real
    assert said == ['linBTCUSDTl open lots hold 2, the book 3'], said


def spec_F41_one_bots_failure_is_its_own_not_the_fleets():
    cfgs, kept, venue, closed = _agreeing([_cfg('long'), _cfg('short')])
    real = pd.check_identity

    def flaky(kept_, fleet, b, cfg, record):
        if b == 'linBTCUSDTs':
            raise ValueError('odd')
        return real(kept_, fleet, b, cfg, record)
    pd.check_identity = flaky
    try:
        r = _run(cfgs, kept, Bybit(venue, closed))
    finally:
        pd.check_identity = real
    assert r['unread'] == [] and r['bots']['linBTCUSDTl']['identity'] is not None
    assert _said(r) == ['linBTCUSDTs its identity could not be worked (ValueError: odd)'], _said(r)


def _carry_row():
    from gridgremlin.portfolio import validate_portfolio
    return validate_portfolio({'strategy': 'portfolio', 'name': 'carry', 'venue': 'bybit', 'capital': 1000,
                               'assets': [{'coin': 'SOL', 'weight': 0.5}, {'coin': 'ETH', 'weight': 0.5}],
                               'hedge': {'ratio': 1.0, 'product': 'usdt'}})


def spec_F39_a_portfolio_legs_failed_read_is_said():
    state = {'pfocarry': {'since_ms': T0 - 200 * DAY, 'fills_to_ms': NOW, 'seen': [], 'books': {}}}
    r = pd.check_fleet({'bots': [_carry_row()]}, {'fills': []}, NOW, {'bybit': Bybit([], [], fail='down')},
                       portfolio_rows=state)
    said = pd.problems(r, NOW / 1000)
    assert "couldn't read bybit linear SOLUSDT: down" in said and len(said) == 4, said


def spec_F39_a_full_seen_list_judges_only_what_it_still_remembers():
    """A busy row keeps its newest 400 ids: a fill older than the oldest
    of them it still holds is forgotten, not missing; a newer one is."""
    fills = [{'venue': 'bybit', 'market_type': 'linear', 'symbol': 'SOLUSDT', 'exec_id': f'h{i}',
              'time_ms': T0 + i * 60_000, 'side': 'sell', 'price': 100.0, 'qty': 1.0, 'fee': 0.01,
              'link_id': f'pfocarry-h{i}'} for i in range(450)]
    seen = [f'h{i}' for i in range(110, 450) if i != 300] + [f'other{i}' for i in range(61)]   # other legs' ids too
    state = {'pfocarry': {'since_ms': T0 - 200 * DAY, 'fills_to_ms': NOW, 'seen': seen, 'books': {}}}
    r = pd.check_fleet({'bots': [_carry_row()]}, {'fills': []}, NOW, {'bybit': Bybit(fills, [])},
                       portfolio_rows=state)
    assert r['bots']['pfocarry']['missing'] == ['h300'], r['bots']['pfocarry']['missing']


def spec_F39_the_check_holds_read_clients_only():
    """`_clients` builds the read classes alone, and neither class carries
    a write: the HL write transport lives on the exchange client."""
    import gridgremlin.exchange.bybit.client as bc
    import gridgremlin.exchange.hyperliquid.client as hc
    made = []

    class R:
        def __init__(self, *a, **k):
            made.append(type(self).__name__)
    real = bc.Client, hc.InfoClient
    bc.Client, hc.InfoClient = type('Client', (R,), {}), type('InfoClient', (R,), {})
    try:
        pd._clients({'bots': [_cfg(), _cfg(sym='BTC', venue='hyperliquid')]})
    finally:
        bc.Client, hc.InfoClient = real
    assert sorted(made) == ['Client', 'InfoClient']
    for cls in real:
        for name in ('post', '_post', '_post_action', 'place_order', 'place_market', 'cancel_order',
                     'amend_order', 'set_trading_stop', 'set_leverage', 'set_risk_limit',
                     'ensure_hedge_mode', 'ensure_collateral', 'exchange_action'):
            assert not hasattr(cls, name), (cls.__name__, name)


def spec_F39_one_unreadable_report_never_costs_the_others():
    with tempfile.TemporaryDirectory() as d:
        Path(d, 'bad.json').write_text(json.dumps({'t': NOW / 1000, 'bots': {'b': 'str'}}))
        Path(d, 'good.json').write_text(json.dumps({'t': NOW / 1000, 'bots': {}, 'unread': ['x']}))
        lines = pd.digest_lines(d, NOW / 1000)
        assert len(lines) == 2 and lines[0].startswith('📏 drift · bad: unreadable — ')
        assert lines[1] == "📏 drift · good: couldn't read x"


def spec_F39_a_fleet_the_digest_no_longer_names_is_left_alone():
    with tempfile.TemporaryDirectory() as d:
        Path(d, 'old.json').write_text(json.dumps({'t': NOW / 1000 - 30 * 86400, 'bots': {}}))
        assert pd.digest_lines(d, NOW / 1000, tags={'demo'}) == []
        assert pd.digest_lines(d, NOW / 1000)                                   # show still sees it
