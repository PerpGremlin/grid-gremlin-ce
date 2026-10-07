# Specs for SPEC A6's exam and the V contract across BOTH venues. The rule:
# if any strategy file needed touching for the second venue, the seam failed.

from pathlib import Path

from gridgremlin.adapters import LinearAdapter
from gridgremlin.exchange.truth import validate_truth, validate_wallet
from gridgremlin.exchange.hyperliquid.adapters import HLPerpAdapter
from gridgremlin.exchange.hyperliquid import truth as hl
from gridgremlin.exchange.bybit import truth as bb

HL_SPEC = hl.parse_instrument({'name': 'SOL', 'szDecimals': 2,
                               'maxLeverage': 50})


# --- A6: the seam exam -------------------------------------------------------

def spec_A6_no_strategy_file_knows_the_second_venue_exists():
    # config.py is exempt: the VENUES enum is the declaration surface — the
    # one place a venue NAME belongs. Strategy and maths must never know.
    for name in ('ladder.py', 'bot.py', 'apply.py', 'window.py',
                 'adapters.py', 'backtest.py', 'events.py'):
        src = Path(f'gridgremlin/{name}').read_text()
        assert 'hyperliquid' not in src.lower(), f'{name} leaked the venue'


def spec_A6_hl_inherits_the_linear_maths_unchanged():
    # not similar code — the SAME functions (M1's rule applied to venues)
    assert HLPerpAdapter.qty_from_notional is LinearAdapter.qty_from_notional
    assert HLPerpAdapter.realised_pnl is LinearAdapter.realised_pnl
    assert HLPerpAdapter.pnl_to_usd is LinearAdapter.pnl_to_usd
    a = HLPerpAdapter(HL_SPEC)
    assert a.one_way_mode and a.position_idx('Buy', False) == 0


def spec_A6_hl_rounding_is_sig_figs_capped_by_decimals():
    a = HLPerpAdapter(HL_SPEC)                     # szDecimals 2 -> 4 places
    assert a.round_price(1867.2534) == 1867.3      # 5 sig figs bind
    assert a.round_price(73.12345) == 73.123       # 5 sig figs again
    assert a.round_price(64000.7) == 64001.0       # quantum never coarser than 1
    tiny = HLPerpAdapter(hl.parse_instrument({'name': 'X', 'szDecimals': 0}))
    assert tiny.round_price(0.1234567) == 0.12346  # 5 sig inside 6 places
    assert a.fmt_price(1867.2534) == '1867.3'      # plain string, no junk


def spec_A6_hl_min_notional_is_the_ten_dollar_floor():
    a = HLPerpAdapter(HL_SPEC)
    assert not a.meets_minimum(0.01, 900.0)        # $9: below the floor
    assert a.meets_minimum(0.02, 900.0)


# --- the V contract, both venues through one validator -----------------------

class FakeHL:
    def meta_and_ctxs(self):
        return ({'universe': [{'name': 'SOL', 'szDecimals': 2}]},
                [{'markPx': '73.5', 'funding': '0.0000125'}])

    def l2_book(self, coin):
        return {'levels': [[{'px': '73.49', 'sz': '10'}],
                           [{'px': '73.51', 'sz': '10'}]]}

    def clearinghouse_state(self):
        return {'marginSummary': {'accountValue': '5000',
                                  'totalMarginUsed': '250'},
                'crossMaintenanceMarginUsed': '25', 'withdrawable': '4000',
                'assetPositions': [{'position': {
                    'coin': 'SOL', 'szi': '1.3', 'entryPx': '73.7',
                    'leverage': {'value': 5}, 'unrealizedPnl': '-0.3'}}]}

    def user_abstraction(self):
        return 'disabled'

    def open_orders(self, coin=None):
        from gridgremlin.exchange.hyperliquid.signing import link_to_cloid
        return [{'coin': 'SOL', 'oid': 77, 'side': 'B', 'limitPx': '73.0',
                 'sz': '1.0', 'origSz': '1.3', 'reduceOnly': False,
                 'isTrigger': False, 'timestamp': 1700000000000,
                 'cloid': link_to_cloid('linSOLl-3-ab12')},
                {'coin': 'SOL', 'oid': 78, 'side': 'A', 'limitPx': '80.0',
                 'sz': '1', 'origSz': '1', 'isTrigger': True}]       # V5: out


def spec_V1_hl_truth_passes_the_shared_schema():
    t = hl.read_symbol_truth(FakeHL(), 'SOL')
    validate_truth(t)                              # the SAME validator
    assert t['split_ref'] == 73.5
    assert t['market_type'] == 'linear'            # no third category word (M10)


def spec_V2_hl_funding_is_hourly_at_the_source():
    t = hl.read_symbol_truth(FakeHL(), 'SOL')
    assert t['funding_rate_hourly'] == 0.0000125   # identity, unit in the name


def spec_V5_hl_trigger_orders_are_excluded():
    t = hl.read_symbol_truth(FakeHL(), 'SOL')
    assert [o['order_id'] for o in t['orders']] == ['77']
    o = t['orders'][0]
    assert o['qty'] == 1.3                         # origSz, not the remainder
    assert abs(o['cum_exec_qty'] - 0.3) < 1e-12    # derived
    assert o['link_id'] == 'linSOLl-3-ab12'        # the cloid DECODES back —
    # without this the diff cannot see its own orders and re-places them every
    # cycle: the live testnet duplicate incident, 2026-08-04, pinned


def spec_V1_hl_positions_are_one_shape_with_every_key():
    t = hl.read_symbol_truth(FakeHL(), 'SOL')
    p = t['positions'][0]
    assert p['stop_loss'] is None and p['take_profit'] is None
    assert p['side'] == 'Buy' and p['size'] == 1.3
    # documented consequence: watch: position_sl is inert on HL — honestly


def spec_V1_hl_wallet_passes_the_shared_schema_with_computed_rates():
    w = hl.read_wallet(FakeHL())
    validate_wallet(w)
    assert w['mm_rate'] == 25.0 / 5000.0           # computed, never venue-sent
    assert w['im_rate'] == 250.0 / 5000.0


def spec_V1_hl_unified_mode_sums_without_double_counting():
    # v2's live measurement: perp margin mirrors as a spot hold — the honest
    # sum is perp accountValue + (spot total - hold)
    class Unified(FakeHL):
        def user_abstraction(self):
            return 'unifiedAccount'

        def clearinghouse_state(self):
            st = dict(FakeHL.clearinghouse_state(self))
            st['marginSummary'] = {'accountValue': '33.47',
                                   'totalMarginUsed': '33.47'}
            return st

        def spot_clearinghouse_state(self):
            return {'balances': [{'coin': 'USDC', 'total': '999.0',
                                  'hold': '33.47'}]}
    w = hl.read_wallet(Unified())
    assert abs(w['equity'] - (33.47 + (999.0 - 33.47))) < 1e-9   # = 999
    assert w['coins']['USDC']['perp'] == 33.47
    assert w['coins']['USDC']['spot'] == 999.0


def spec_V4_the_contract_is_one_module_for_both_venues():
    from gridgremlin.exchange import truth as shared
    assert bb.validate_truth is shared.validate_truth
    assert hl.validate_truth is shared.validate_truth


def spec_F7_hl_mainnet_is_double_safetied():
    # D25 (2026-08-05) ends the testnet-only phase: mainnet is CONSTRUCTIBLE
    # but only through the explicit armed path — a bare env flag still refuses.
    from gridgremlin.exchange.errors import VenueError
    from gridgremlin.exchange.hyperliquid.client import InfoClient
    try:
        InfoClient(env='mainnet')
    except VenueError as e:
        assert 'double-safetied' in str(e)
    else:
        raise AssertionError('HL mainnet client armed itself')
    armed = InfoClient(env='mainnet', allow_mainnet=True)
    assert armed.base == 'https://api.hyperliquid.xyz'
    assert InfoClient(env='testnet').base.startswith('https://api.hyperliquid-t')


# --- C7 at the universe seam: a removed coin refuses BY NAME -----------------
# HL removed XRP from its testnet universe mid-soak; the build crashed as a
# bare StopIteration. The refusal must name the coin.

def spec_C7_a_coin_missing_from_the_universe_refuses_by_name():
    from gridgremlin.exchange.errors import VenueError
    from gridgremlin.exchange.hyperliquid.venue import HLVenueClient
    c = HLVenueClient.__new__(HLVenueClient)
    c._universe = {'BTC': (0, {'name': 'BTC'})}
    try:
        c._entry('XRP')
    except VenueError as e:
        assert 'XRP' in str(e)
    else:
        raise AssertionError('a missing coin did not refuse')


# --- I6: an amended order keeps its link ---------------------------------------
# Live 2026-10-04: the HL SOL grid's exit at the top rung part-filled, the
# engine amended the rest in place, and HL's modify made a NEW order from
# the body it was given — a body without the cloid. The remainder filled
# unlinked; the D1 rule read an unlinked reduce as an outside hand and
# killed the bot, flat at the top of its range.

def spec_I6_an_amended_order_keeps_its_link():
    from gridgremlin.exchange.hyperliquid.venue import HLVenueClient
    from gridgremlin.exchange.hyperliquid.signing import link_to_cloid
    c = HLVenueClient.__new__(HLVenueClient)
    c._universe = {'SOL': (5, {'name': 'SOL', 'szDecimals': 2,
                               'maxLeverage': 20})}
    link = 'linSOLl-14-d6hj'
    c.open_orders = lambda coin=None: [
        {'coin': 'SOL', 'oid': 61818973947, 'cloid': link_to_cloid(link),
         'side': 'A', 'limitPx': '127.2', 'sz': '0.19', 'origSz': '0.39',
         'reduceOnly': True, 'orderType': 'Limit', 'timestamp': 0}]
    posted = []
    c._post_action = lambda action: (posted.append(action) or {
        'statuses': [{'resting': {'oid': 61818994438}}]})
    c.amend_order('linear', 'SOL', 61818973947, '0.19')
    body = posted[-1]['modifies'][0]
    assert posted[-1]['type'] == 'batchModify' and body['oid'] == 61818973947
    assert body['order']['c'] == link_to_cloid(link)        # the link rides
    assert body['order']['s'] == '0.19' and body['order']['r'] is True
    # sabotage: the body without 'c' is what killed the bot
    from gridgremlin.exchange.hyperliquid.truth import read_fills
    unlinked = {'coin': 'SOL', 'tid': 1, 'time': 1, 'side': 'A', 'px': '127.2',
                'sz': '0.14', 'fee': '0', 'oid': 61818994438, 'dir': 'Close Long',
                'cloid': None, 'closedPnl': '0'}
    rows = read_fills([unlinked], {'SOL'}, '0x' + 'ab' * 20)
    assert rows and not rows[0]['link_id']           # no link = outside hand


# --- the watch's finding: 429s climb a patient ladder, not a single retry ----

def spec_E7_hl_info_reads_ride_out_a_429_burst():
    import urllib.error
    from gridgremlin.exchange.hyperliquid.client import InfoClient
    calls = {'n': 0}
    slept = []
    c = InfoClient(env='testnet')
    real_sleep = __import__('time').sleep

    class Wire:                       # E10: the reads ride KeepAlive
        def request(self, method, url, headers, body=None):
            calls['n'] += 1
            if calls['n'] <= 2:
                raise urllib.error.HTTPError(url, 429, 'Too Many', {}, None)
            return {}, b'{"ok": 1}'
    c._wire = Wire()
    __import__('time').sleep = slept.append
    try:
        out = c._http({'type': 'meta'})
    finally:
        __import__('time').sleep = real_sleep
    assert out == {'ok': 1} and calls['n'] == 3
    assert slept == [2.0, 4.0]                   # the ladder, not one retry


# --- R10: HL's liquidation stamp names WHO was liquidated ------------------
# The real shape, pulled from the venue for the two fills that killed the
# 48-day run's ETH and BTC grids (JOURNAL 2026-09-25): our resting exit, our
# cloid, `crossed` false — and someone else's address in the stamp.

OURS = '0xAbCdEf0000000000000000000000000000001234'      # checksum-cased


def _stamped(link, who, side='B', coin='ETH'):
    from gridgremlin.exchange.hyperliquid.signing import link_to_cloid
    return {'coin': coin, 'px': '1858.9', 'sz': '0.02', 'side': side,
            'time': 1786639311071, 'startPosition': '-0.05',
            'dir': 'Close Short', 'closedPnl': '1.14', 'hash': '0x1',
            'oid': 57810108, 'crossed': False, 'fee': '0.007',
            'tid': 2999250522, 'feeToken': 'USDC', 'twapId': None,
            'cloid': link_to_cloid(link) if link else None,
            'liquidation': {'liquidatedUser': who, 'markPx': '1865.6',
                            'method': 'market'}}


def spec_R10_a_counterparty_liquidation_is_an_ordinary_fill():
    # sabotage: the pre-fix rule (any stamp → a liquidation of us) fails here
    other = '0x000000000000000000000000000000000000beef'
    fills = hl.read_fills([_stamped('linETHs-9-g58h', other)], {'ETH'}, OURS)
    assert len(fills) == 1
    f = fills[0]
    assert f['venue_closed'] is False and f['venue_kind'] == ''
    assert f['link_id'] == 'linETHs-9-g58h' and f['side'] == 'buy'


def spec_R10_our_own_liquidation_is_venue_closed():
    # the venue creates it: no cloid; the address compares case-insensitively
    fills = hl.read_fills([_stamped(None, OURS.lower(), side='A')], {'ETH'},
                          OURS)
    f = fills[0]
    assert f['venue_closed'] is True and f['venue_kind'] == 'liquidation'
    assert f['link_id'] == '' and f['side'] == 'sell'


def spec_R10_a_stamp_naming_nobody_refuses():
    from gridgremlin.exchange.errors import VenueError
    bad = _stamped('linETHs-9-g58h', '')
    for stamp in ({}, {'markPx': '1'}, {'liquidatedUser': None}, 'yes'):
        bad['liquidation'] = stamp
        if not stamp:
            assert hl.read_fills([bad], {'ETH'}, OURS)[0]['venue_closed'] \
                is False                       # empty stamp = no stamp
            continue
        try:
            hl.read_fills([bad], {'ETH'}, OURS)
        except VenueError as e:
            assert 'R10' in str(e)
        else:
            raise AssertionError(f'stamp {stamp!r} was guessed at')
    try:
        hl.read_fills([_stamped('linETHs-9-g58h', OURS)], {'ETH'}, '')
    except VenueError as e:
        assert 'address' in str(e)
    else:
        raise AssertionError('no address, yet a verdict')


# --- E10: the reads ride one kept connection --------------------------------

class _Resp:
    def __init__(self, status=200, body=b'{}', close=False):
        self.status, self.reason, self.will_close = status, 'r', close
        self.headers, self._body = {'X': '1'}, body

    def read(self):
        return self._body


class _Conn:
    """A fake HTTPSConnection: `script` is what each request does in turn."""
    def __init__(self, script):
        self.script, self.sent, self.closed = script, [], False

    def request(self, method, path, body=None, headers=None):
        self.sent.append((method, path))
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        self._next = step

    def getresponse(self):
        return self._next

    def close(self):
        self.closed = True


def _wire(*scripts):
    from gridgremlin.exchange.keepalive import KeepAlive
    made = []

    def connect(host):
        made.append(_Conn(list(scripts[len(made)])))
        return made[-1]
    return KeepAlive(connect=connect), made


def spec_E10_reads_reuse_one_connection():
    w, made = _wire([_Resp(body=b'1'), _Resp(body=b'2')])
    assert w.request('GET', 'https://h/a?x=1', {})[1] == b'1'
    assert w.request('GET', 'https://h/b', {})[1] == b'2'
    assert len(made) == 1 and made[0].sent == [('GET', '/a?x=1'), ('GET', '/b')]


def spec_E10_a_stale_reused_connection_is_retried_once_fresh():
    import http.client
    w, made = _wire([_Resp(), http.client.RemoteDisconnected('idle')],
                    [_Resp(body=b'ok')])
    w.request('GET', 'https://h/a', {})
    assert w.request('GET', 'https://h/a', {})[1] == b'ok'
    assert len(made) == 2 and made[0].closed


def spec_E10_a_fresh_failure_or_a_timeout_is_never_resent():
    import http.client
    w, made = _wire([http.client.RemoteDisconnected('x')])
    try:
        w.request('GET', 'https://h/a', {})
        raise AssertionError('a fresh connection failure was resent')
    except http.client.RemoteDisconnected:
        pass
    assert len(made) == 1
    w, made = _wire([_Resp(), TimeoutError('slow')])
    w.request('GET', 'https://h/a', {})
    try:
        w.request('GET', 'https://h/a', {})
        raise AssertionError('a timeout was resent')
    except TimeoutError:
        pass
    assert len(made) == 1 and made[0].closed


def spec_E10_an_error_status_raises_urllibs_httperror_with_its_body():
    import urllib.error
    w, made = _wire([_Resp(status=429, body=b'slow down'), _Resp(body=b'ok')])
    try:
        w.request('POST', 'https://h/info', {}, b'{}')
        raise AssertionError('a 429 was returned as data')
    except urllib.error.HTTPError as e:
        assert e.code == 429 and e.read() == b'slow down'
    assert w.request('POST', 'https://h/info', {}, b'{}')[1] == b'ok'
    assert len(made) == 1                  # an error status keeps the line


def spec_E10_a_closing_response_drops_the_connection():
    w, made = _wire([_Resp(close=True)], [_Resp()])
    w.request('GET', 'https://h/a', {})
    w.request('GET', 'https://h/a', {})
    assert len(made) == 2 and made[0].closed


def spec_E10_writes_never_ride_the_kept_connection():
    def body(path, name):
        src = Path(path).read_text()
        rest = src[src.index(f'    def {name}('):]
        end = rest.find('\n    def ', 1)
        return rest if end < 0 else rest[:end]
    for path, name in (('gridgremlin/exchange/bybit/client.py', 'post'),
                       ('gridgremlin/exchange/hyperliquid/client.py', '_post')):
        write = body(path, name)
        assert 'urlopen' in write and '_wire' not in write, (path, name)


# --- V16: the venue's own leverage limits per coin ---------------------------

def _hl(entry):
    return HLPerpAdapter(hl.parse_instrument({'szDecimals': 2, **entry}))


def spec_V16_hl_parses_the_coins_leverage_limits():
    sol = _hl({'name': 'SOL', 'maxLeverage': 10})
    assert sol.max_leverage == 10 and not sol.only_isolated
    hype = _hl({'name': 'HYPE', 'maxLeverage': 10, 'onlyIsolated': True,
                'marginMode': 'strictIsolated'})
    assert hype.only_isolated
    assert _hl({'name': 'X'}).max_leverage is None        # unpublished: no cap


def spec_V16_past_the_cap_the_build_asks_nothing_and_says_so():
    from gridgremlin.main import hl_leverage_plan
    lev, cross, note = hl_leverage_plan(
        {'symbol': 'SOL', 'leverage': 15}, _hl({'name': 'SOL', 'maxLeverage': 10}))
    assert lev is None and 'maximum of 10x' in note and 'hiccup' not in note
    assert hl_leverage_plan({'symbol': 'SOL', 'leverage': 10},
                            _hl({'name': 'SOL', 'maxLeverage': 10})) == (10, True, None)


def spec_V16_an_isolated_only_coin_is_set_isolated_and_said():
    from gridgremlin.main import hl_leverage_plan
    lev, cross, note = hl_leverage_plan(
        {'symbol': 'HYPE', 'leverage': 5},
        _hl({'name': 'HYPE', 'maxLeverage': 10, 'onlyIsolated': True}))
    assert (lev, cross) == (5, False) and 'isolated-only' in note


def spec_V16_an_answered_refusal_is_never_called_a_hiccup():
    from gridgremlin.exchange.hyperliquid.client import HLError
    from gridgremlin.main import hl_leverage_plan, leverage_refusal_note
    said = leverage_refusal_note(HLError(200, 'updateLeverage: Isolated '
                                         'position does not have sufficient '
                                         'margin available'))
    assert 'refused' in said and 'hiccup' not in said
    assert 'hiccup' in leverage_refusal_note(HLError(429, 'rate limited'))
    assert 'hiccup' in leverage_refusal_note(
        HLError(0, 'network failure after send', ambiguous=True))
    note = hl_leverage_plan({'symbol': 'SOL', 'leverage': 15},
                            _hl({'name': 'SOL', 'maxLeverage': 10}))[2]
    assert not note.startswith('SOL:')         # the event names the coin


# --- D63: funding, per position side ----------------------------------------

def spec_D63_bybit_funding_is_minus_the_fee_on_the_leg_it_charged():
    from gridgremlin.exchange.bybit.truth import read_funding
    rows = [  # the shape measured on demo 2026-10-06
        {'execId': 'f1', 'execType': 'Funding', 'side': 'Buy',
         'execFee': '0.01987096', 'execTime': '1791244800000',
         'symbol': 'SOLUSDT'},
        {'execId': 'f2', 'execType': 'Funding', 'side': 'Sell',
         'execFee': '-0.00849528', 'execTime': '1791244800000',
         'symbol': 'SOLUSDT'},
        {'execId': 'f1', 'execType': 'Funding', 'side': 'Buy',     # repeated
         'execFee': '0.01987096', 'execTime': '1791244800000',
         'symbol': 'SOLUSDT'},
        {'execId': 't1', 'execType': 'Trade', 'side': 'Buy',
         'execFee': '1', 'execTime': '1791244800001', 'symbol': 'SOLUSDT'}]
    asked = []

    class C:
        def executions_page(self, cat, sym, a, z, cursor=None, exec_type=None):
            asked.append(exec_type)
            return {'list': rows}
    got = read_funding(C(), 'linear', 'SOLUSDT', 0, 1000)
    assert asked == ['Funding']
    assert [(f['side'], round(f['amount'], 8)) for f in got] == \
        [('buy', -0.01987096), ('sell', 0.00849528)]


def spec_D63_bybit_funding_keeps_both_legs_of_one_settlement():
    """Measured 2026-10-06: Bybit writes one settlement as ONE execId on
    both legs of a hedge pair (distinct orderIds, distinct sides)."""
    from gridgremlin.exchange.bybit.truth import read_funding
    rows = [{'execId': 'S', 'execType': 'Funding', 'side': 'Buy',
             'execFee': '0.81574374', 'execTime': '1791273600000'},
            {'execId': 'S', 'execType': 'Funding', 'side': 'Sell',
             'execFee': '-0.03544421', 'execTime': '1791273600000'},
            {'execId': 'S', 'execType': 'Funding', 'side': 'Sell',   # a true
             'execFee': '-0.03544421', 'execTime': '1791273600000'}]  # repeat

    class C:
        def executions_page(self, *a, **k):
            return {'list': rows}
    got = read_funding(C(), 'linear', 'BTCUSDT', 0, 1000)
    assert [(f['side'], round(f['amount'], 8)) for f in got] == \
        [('buy', -0.81574374), ('sell', 0.03544421)]


def spec_D63_hl_funding_takes_its_side_from_szi_and_pages_by_time():
    from gridgremlin.exchange.hyperliquid.truth import read_funding

    def row(t, coin, usdc, szi):
        return {'time': t, 'delta': {'type': 'funding', 'coin': coin,
                                     'usdc': usdc, 'szi': szi}}
    page1 = [row(t, c, '-0.01', '1') for t in range(100, 100 + 250)
             for c in ('SOL', 'ETH')]                      # 500 rows: full
    page2 = [row(349, 'SOL', '-0.01', '1'), row(349, 'ETH', '-0.01', '1'),
             row(400, 'ETH', '0.02', '-0.5'), row(400, 'XRP', '9', '1')]
    pages = [page1, page2]
    starts = []

    class C:
        def user_funding(self, start, end=None):
            starts.append(start)
            return pages.pop(0) if pages else []
    got = read_funding(C(), {'SOL', 'ETH'}, 100)
    assert starts == [100, 349]                # resumes AT the last instant
    assert len(got) == 501                     # 500 + the one new ETH row
    last = got[-1]
    assert (last['symbol'], last['side'], last['amount']) == ('ETH', 'sell', 0.02)
