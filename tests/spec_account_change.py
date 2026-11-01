"""D162 — the account as its assets, read by read (R25–R28), and the panel's
view of what changed (U150–U154). Display and recording only: nothing here
places, cancels or pages. Made-up figures throughout."""
import json
import tempfile
import time
from pathlib import Path

H = 3_600_000
NOW = 1_800_000_000_000            # a fixed "now", in ms


def _fleet_path(d):
    p = Path(d) / 'configs' / 'fleet.x.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"bots": []}')
    return str(p)


def _fig(wallet=None, positions=(), tier='demo', transfers=None):
    return {'tier': tier, 'equity': 1000.0, 'notional': 0.0, 'collateral': 1000.0, 'source': 'bybit',
            'available': 900.0,
            'wallet': {c: {'balance': b, 'usd': None, 'borrow': l, 'interest': 0.0}
                       for c, (b, l) in (wallet or {}).items()},
            'positions': [dict(market=m, symbol=s, side=sd, size=sz, entry=100.0, mark=101.0,
                               upnl=1.5, leverage=10.0) for m, s, sd, sz in positions],
            'transfers': transfers}


def _contract(t, **kw):
    return {'generated_ms': t, 'account': {'bybit': _fig(**kw)}}


def _fill(t, side, qty, link='', symbol='BTCUSDT', market='linear', eid=None):
    return {'time_ms': t, 'side': side, 'qty': qty, 'price': 100.0, 'fee': 0.0, 'link_id': link,
            'symbol': symbol, 'market_type': market, 'exec_id': eid or f'e{t}{side}{qty}{link}',
            'venue': 'bybit'}


# --- R25: one record per read, from the reads the readout already makes -----

def spec_R25_every_position_comes_from_the_readouts_own_position_pages():
    """No new venue call: Bybit's position pages (R19's three) and wallet
    read are the same calls as before; HL's positions come from the
    clearinghouse state already read."""
    from gridgremlin.exchange.bybit.truth import account_figures
    calls = []
    pages = {'linear': [{'symbol': 'BTCUSDT', 'side': 'Buy', 'size': '0.5', 'avgPrice': '70000',
                         'markPrice': '71000', 'unrealisedPnl': '500', 'leverage': '10',
                         'positionValue': '35000'},
                        {'symbol': 'XRPUSDT', 'side': '', 'size': '0', 'positionValue': '0'}],
             'inverse': [{'symbol': 'BTCUSD', 'side': 'Sell', 'size': '1000', 'avgPrice': '70000',
                          'markPrice': '71000', 'unrealisedPnl': '-0.0002', 'leverage': '2',
                          'positionValue': '0.014'}]}

    class C:
        def get(self, path, params, signed=False):
            calls.append(path)
            if params.get('settleCoin') == 'USDC':
                return {'list': []}
            return {'list': pages[params['category']]}

        def wallet_balance(self):
            calls.append('wallet')
            return {'list': [{'totalMarginBalance': '9000', 'coin': []}]}
    fig = account_figures(C())
    assert calls == ['/v5/position/list'] * 3 + ['wallet'], calls
    assert fig['positions'] == [
        {'market': 'linear', 'symbol': 'BTCUSDT', 'side': 'long', 'size': 0.5, 'entry': 70000.0,
         'mark': 71000.0, 'upnl': 500.0, 'leverage': 10.0},
        {'market': 'inverse', 'symbol': 'BTCUSD', 'side': 'short', 'size': 1000.0, 'entry': 70000.0,
         'mark': 71000.0, 'upnl': -0.0002, 'leverage': 2.0}]
    from gridgremlin.exchange.hyperliquid.truth import account_positions
    state = {'assetPositions': [{'position': {'coin': 'ETH', 'szi': '-2', 'entryPx': '3000',
                                              'positionValue': '6100', 'unrealizedPnl': '-100',
                                              'leverage': {'value': 5}}},
                                {'position': {'coin': 'BTC', 'szi': '0'}}]}
    assert account_positions(state) == [{'market': 'linear', 'symbol': 'ETH', 'side': 'short', 'size': 2.0,
                                         'entry': 3000.0, 'mark': 3050.0, 'upnl': -100.0, 'leverage': 5.0}]


def spec_R25_a_record_holds_each_coin_its_loan_and_each_position():
    from gridgremlin.account_change import snapshot_of
    rec = snapshot_of({'bybit': _fig(wallet={'USDT': (500.0, 0.0), 'BTC': (0.1, 0.02)},
                                     positions=[('linear', 'BTCUSDT', 'long', 0.5)]),
                       'hyperliquid': None})
    assert rec == {'bybit': {'tier': 'demo',
                             'wallet': {'BTC': {'balance': 0.1, 'loan': 0.02},
                                        'USDT': {'balance': 500.0, 'loan': 0.0}},
                             'positions': {'linear:BTCUSDT:long': {'size': 0.5, 'entry': 100.0,
                                                                   'mark': 101.0}}}}
    hl = snapshot_of({'hyperliquid': {'tier': 'testnet', 'positions': []}})
    assert 'wallet' not in hl['hyperliquid']                  # not given: absent, never zero


# --- R26: the last day thinned, one record a day kept long --------------------

def _run_reads(d, every_s=30, hours=30, start=NOW):
    from gridgremlin.account_change import record
    fp = _fleet_path(d)
    t = start
    end = start + int(hours * H)
    while t <= end:
        record(fp, _contract(t, wallet={'USDT': (1000.0 + (t - start) / H, 0.0)}), now_ms=t)
        t += every_s * 1000
    return fp, end


def _bound():
    from gridgremlin.account_change import RECENT_S, THIN_STEPS
    prev, n = 0, 0
    for limit, step in THIN_STEPS:
        n += (limit - prev) // step + 1
        prev = limit
    return n


def spec_R26_the_last_day_is_thinned_and_each_day_kept_once():
    from gridgremlin.account_change import days_path, load_history, recent_path
    with tempfile.TemporaryDirectory() as d:
        fp, end = _run_reads(d)
        hist = load_history(recent_path(fp))
        ts = [r['t'] for r in hist['records']]
        assert ts == sorted(ts) and ts[-1] == end                          # the newest read stays
        assert len(ts) <= _bound(), (len(ts), _bound())
        assert end - ts[0] <= 25 * H and end - ts[0] >= 24 * H             # a 24 h window has a before
        last2h = [t for t in ts if end - t <= 2 * H]
        assert len(last2h) >= 55                                          # about one per 2 min there
        days = [json.loads(x) for x in days_path(fp).read_text().splitlines()]
        spanned = sorted({time.strftime('%Y-%m-%d', time.gmtime(t / 1000))
                          for t in range(NOW, end + 1, 30_000)})
        assert [x['day'] for x in days] == spanned                         # one a day, the day's first
        assert days[0]['t'] == NOW
        assert days_path(fp).name == 'x.account-days.jsonl' and days_path(fp).parent.name == 'fills'


def spec_R26_sabotage_without_thinning_the_file_grows_with_every_read():
    import gridgremlin.account_change as ac
    saved = ac.THIN_STEPS
    ac.THIN_STEPS = ((ac.RECENT_S, 1),)                                    # the guard removed
    try:
        with tempfile.TemporaryDirectory() as d:
            fp, _ = _run_reads(d, every_s=60, hours=6)
            n = len(ac.load_history(ac.recent_path(fp))['records'])
    finally:
        ac.THIN_STEPS = saved
    assert n > _bound(), n                                                # the bound would catch it


# --- R27: the venue's money records, listed or "not read" -------------------

class _Bybit:
    """A key that reads its id, both transfer lists and withdrawals, and is
    refused the deposits."""
    def __init__(self, deny=('/v5/asset/deposit/query-record',)):
        self.deny, self.calls = set(deny), []

    def get(self, path, params, signed=False):
        from gridgremlin.exchange.errors import VenueError
        self.calls.append(path)
        if path in self.deny:
            raise VenueError(f'bybit {path}: retCode 10005: Permission denied for current apikey')
        if path == '/v5/user/query-api':
            return {'userID': 7}
        t = params['endTime'] - H
        if path.endswith('query-inter-transfer-list'):
            return {'list': [{'transferId': 'a', 'coin': 'USDT', 'amount': '500', 'status': 'SUCCESS',
                              'fromAccountType': 'FUND', 'toAccountType': 'UNIFIED', 'timestamp': str(t)},
                             {'transferId': 'b', 'coin': 'USDT', 'amount': '9', 'status': 'FAILED',
                              'fromAccountType': 'FUND', 'toAccountType': 'UNIFIED', 'timestamp': str(t)}]}
        if path.endswith('query-universal-transfer-list'):
            return {'list': [{'transferId': 'c', 'coin': 'USDT', 'amount': '200', 'status': 'SUCCESS',
                              'fromMemberId': '3', 'toMemberId': '7', 'fromAccountType': 'UNIFIED',
                              'toAccountType': 'UNIFIED', 'timestamp': str(t + 1)}]}
        if path.endswith('withdraw/query-record'):
            return {'rows': [{'withdrawId': 'w', 'coin': 'USDT', 'amount': '50', 'withdrawFee': '1',
                              'status': 'success', 'updateTime': str(t + 2)}]}
        return {'rows': []}


def spec_R27_money_moved_is_listed_and_a_record_the_key_cannot_read_is_named():
    from gridgremlin.exchange.bybit.truth import read_transfers
    rows, unread = read_transfers(_Bybit(), NOW - 7 * 24 * H, NOW)
    got = [(r['dir'], r['amount'], r['coin'], r['what']) for r in rows]
    assert got == [('in', 500.0, 'USDT', 'transfer within the account (Funding → Unified Trading)'),
                   ('in', 200.0, 'USDT', 'transfer from another account (Unified Trading → Unified Trading)'),
                   ('out', 50.0, 'USDT', 'withdrawal (fee 1)')], got
    assert list(unread) == ['deposits'] and 'Permission denied' in unread['deposits']
    rows, unread = read_transfers(_Bybit(deny=('/v5/user/query-api',)), NOW - H * 2, NOW)
    assert rows[1]['dir'] is None and "id unread" in rows[1]['what']   # direction never guessed
    from gridgremlin.exchange.hyperliquid.truth import read_transfers as hl_read

    class HL:
        address = '0xAbC'

        def ledger_updates(self, a, b):
            return [{'time': NOW - 1, 'hash': 'h1', 'delta': {'type': 'deposit', 'usdc': '1000'}},
                    {'time': NOW, 'hash': 'h2', 'delta': {'type': 'accountClassTransfer', 'usdc': '5',
                                                          'toPerp': True}},
                    {'time': NOW, 'hash': 'h3', 'delta': {'type': 'internalTransfer', 'usdc': '20',
                                                          'user': '0xabc', 'destination': '0xdef'}}]
    rows, unread = hl_read(HL(), NOW - H, NOW)
    assert [(r['dir'], r['amount']) for r in rows] == [('in', 1000.0), ('out', 20.0)] and not unread

    class Down(HL):
        def ledger_updates(self, a, b):
            raise OSError('unreachable')
    assert hl_read(Down(), NOW - H, NOW) == ([], {'the ledger of money moved': 'unreachable'})


def spec_R27_the_records_are_read_every_ten_minutes_not_every_readout():
    from gridgremlin.account_change import (TRANSFER_SPAN_MS, load_history, record, recent_path,
                                            transfers_due)
    with tempfile.TemporaryDirectory() as d:
        fp = _fleet_path(d)
        assert transfers_due({}, 'bybit', NOW) == NOW - TRANSFER_SPAN_MS      # first: the lists' seven days
        tr = {'from_ms': NOW - TRANSFER_SPAN_MS, 'to_ms': NOW, 'unread': {},
              'rows': [{'id': 'tr:a', 't': NOW - H, 'dir': 'in', 'coin': 'USDT', 'amount': 5.0, 'what': 'x'}]}
        record(fp, _contract(NOW, wallet={'USDT': (1.0, 0.0)}, transfers=tr))
        hist = load_history(recent_path(fp))
        assert transfers_due(hist, 'bybit', NOW + 9 * 60_000) is None
        assert transfers_due(hist, 'bybit', NOW + 11 * 60_000) == NOW - H     # an hour back from the last
        tr2 = {'from_ms': NOW - H, 'to_ms': NOW + 11 * 60_000, 'unread': {'deposits': 'no'},
               'rows': [{'id': 'tr:b', 't': NOW + 60_000, 'dir': 'out', 'coin': 'USDT', 'amount': 1.0,
                         'what': 'y'}]}
        record(fp, _contract(NOW + 11 * 60_000, wallet={'USDT': (1.0, 0.0)}, transfers=tr2))
        kept = load_history(recent_path(fp))['transfers']['bybit']
        assert [r['id'] for r in kept['rows']] == ['tr:a', 'tr:b']
        assert kept['from_ms'] == NOW - TRANSFER_SPAN_MS and kept['unread'] == {'deposits': 'no'}


def spec_R27_sabotage_with_no_pause_every_readout_reads_the_records():
    import gridgremlin.account_change as ac
    hist = {'transfers': {'bybit': {'read_ms': NOW, 'from_ms': NOW - H, 'rows': []}}}
    saved = ac.TRANSFER_EVERY_S
    ac.TRANSFER_EVERY_S = 0                                                  # the guard removed
    try:
        assert ac.transfers_due(hist, 'bybit', NOW + 1000) is not None
    finally:
        ac.TRANSFER_EVERY_S = saved
    assert ac.transfers_due(hist, 'bybit', NOW + 1000) is None


# --- R28: a position's change, split exactly ---------------------------------

BOT = 'linBTCUSDTl'
RUN = {('bybit', 'linear', 'BTCUSDT', 'long'), ('bybit', 'linear', 'SOLUSDT', 'long'),
       ('bybit', 'inverse', 'BTCUSD', 'short')}
KEPT = {('bybit', 'linear', 'BTCUSDT', 'long'), ('bybit', 'linear', 'SOLUSDT', 'long')}


def _world():
    from gridgremlin.account_change import snapshot_of
    t0 = NOW - 2 * H
    before = {'t': t0, 'v': snapshot_of({'bybit': _fig(
        wallet={'USDT': (1000.0, 0.0), 'BTC': (0.2, 0.0)},
        positions=[('linear', 'BTCUSDT', 'long', 0.5), ('linear', 'SOLUSDT', 'long', 1.0),
                   ('inverse', 'BTCUSD', 'short', 1000.0)])})}
    now_fig = _fig(wallet={'USDT': (950.0, 100.0), 'BTC': (0.2, 0.0), 'ETH': (1.0, 0.0)},
                   positions=[('linear', 'BTCUSDT', 'long', 0.8), ('linear', 'ETHUSDT', 'short', 2.0),
                              ('inverse', 'BTCUSD', 'short', 1200.0)])
    fills = [_fill(t0 - 1, 'buy', 9.0, f'{BOT}-1-a'),             # before the window: not counted
             _fill(t0 + 10, 'buy', 0.4, f'{BOT}-1-b'),            # the bot's entry
             _fill(t0 + 20, 'sell', 0.2, f'{BOT}-2-c'),           # the bot's exit
             _fill(t0 + 30, 'buy', 0.1, ''),                      # a hand trade
             _fill(t0 + 40, 'sell', 0.7, 'linBTCUSDTs-1-d'),      # the short bot's, not the long's
             _fill(t0 + 50, 'sell', 1.0, 'linSOLUSDTl-3-e', symbol='SOLUSDT')]
    return before, now_fig, fills


def _change(complete=None):
    from gridgremlin.account_change import account_change, snapshot_of
    before, now_fig, fills = _world()
    return account_change([before], snapshot_of({'bybit': now_fig}), NOW, fills, RUN, KEPT, complete,
                          {}, {'bybit': now_fig['positions']})['bybit']


def spec_R28_a_position_change_is_the_bots_fills_plus_the_rest_exactly():
    got = _change()
    w = got['windows']['24h']
    assert w['from_ms'] == NOW - 2 * H and w['short']                    # the record starts inside 24 h
    pos = {r['key']: r for r in w['positions']}
    btc = pos['linear:BTCUSDT:long']
    assert abs(btc['change'] - 0.3) < 1e-9 and abs(btc['bots'] - 0.2) < 1e-9 and abs(btc['rest'] - 0.1) < 1e-9
    for r in w['positions']:
        if r['bots'] is not None:
            assert abs(r['bots'] + r['rest'] - r['change']) < 1e-12, r       # adds up exactly
    sol = pos['linear:SOLUSDT:long']
    assert sol['state'] == 'closed' and sol['bots'] == -1.0 and sol['rest'] == 0.0
    eth = pos['linear:ETHUSDT:short']
    assert eth['state'] == 'new' and eth['bots'] == 0.0 and eth['rest'] == 2.0
    inv = pos['inverse:BTCUSD:short']
    assert inv['bots'] is None and inv['rest'] is None and 'Portfolio Bot' in inv['why']
    behind = _change(complete=lambda *a: False)['windows']['24h']
    assert 'behind' in {r['key']: r for r in behind['positions']}['linear:BTCUSDT:long']['why']


def spec_R28_sabotage_a_hand_trade_counted_as_the_bots_is_caught():
    import gridgremlin.account_change as ac
    saved = ac.rung_of
    ac.rung_of = lambda link, botid: 0                                     # any fill the bot's
    try:
        btc = {r['key']: r for r in _change()['windows']['24h']['positions']}['linear:BTCUSDT:long']
    finally:
        ac.rung_of = saved
    assert abs(btc['rest'] - 0.1) > 1e-6                                  # the spec above would fail


def spec_R28_balances_and_the_list_of_positions_no_bot_runs():
    got = _change()
    bal = {r['coin']: r for r in got['windows']['24h']['balances']}
    assert bal['USDT']['before'] == 1000.0 and bal['USDT']['now'] == 950.0 and bal['USDT']['change'] == -50.0
    assert bal['USDT']['loan_before'] == 0.0 and bal['USDT']['loan_now'] == 100.0
    assert bal['ETH']['before'] == 0.0 and bal['ETH']['change'] == 1.0 and 'loan_now' not in bal['ETH']
    assert [(p['symbol'], p['side']) for p in got['not_from_a_bot']] == [('ETHUSDT', 'short')]
    assert got['windows']['1h']['from_ms'] == NOW - 2 * H and not got['windows']['1h']['short']


def spec_R28_the_readouts_view_counts_its_own_fresh_fills_once_and_the_portfolio_legs_as_run():
    """account_view: the kept ledger and this readout's fresh fills, one
    fill once (I4); a Portfolio Bot's hedge legs are run but not kept."""
    from gridgremlin.account_change import record, snapshot_of
    from gridgremlin.report import account_view, bot_markets
    fleet = {'bots': [{'venue': 'bybit', 'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long'},
                      {'strategy': 'portfolio', 'venue': 'bybit', 'capital': 100.0, 'spot_quote': 'USDT',
                       'assets': [{'coin': 'BTC', 'weight': 1.0}],
                       'hedges': {'BTC': {'product': 'inverse', 'ratio': 1.0}}, 'short_products': {}}]}
    run, kept = bot_markets(fleet)
    assert run == RUN - {('bybit', 'linear', 'SOLUSDT', 'long')} and kept == {('bybit', 'linear', 'BTCUSDT', 'long')}
    before, now_fig, fills = _world()
    with tempfile.TemporaryDirectory() as d:
        fp = _fleet_path(d)
        record(fp, {'generated_ms': before['t'], 'account': {'bybit': _fig(
            wallet={'USDT': (1000.0, 0.0)}, positions=[('linear', 'BTCUSDT', 'long', 0.5)])}})
        ledger = Path(d) / 'logs' / 'fills' / 'x.json'
        ledger.write_text(json.dumps({'version': 1, 'collected': {'bybit:linear:BTCUSDT': NOW - H},
                                      'fills': fills[:3]}))
        fresh = [{k: v for k, v in f.items() if k != 'venue'} for f in fills[1:4]]   # two already kept
        import os
        here = os.getcwd()
        os.chdir(d)                                       # the readout runs from the fleet's home
        try:
            hist = json.loads((Path(d) / 'logs' / 'account' / 'x.json').read_text())
            view = account_view(fp, fleet, {'bybit': now_fig}, hist, fresh, {'bybit'},
                                NOW - 24 * H, NOW)
        finally:
            os.chdir(here)
    btc = {r['key']: r for r in view['bybit']['windows']['24h']['positions']}['linear:BTCUSDT:long']
    assert abs(btc['bots'] - 0.2) < 1e-9 and abs(btc['rest'] - 0.1) < 1e-9 and 'why' not in btc
    assert snapshot_of({'bybit': now_fig})['bybit']['positions'].keys() >= {'linear:BTCUSDT:long'}


# --- U150–U154: the account view --------------------------------------------

def _panel_contract(age_s=5, change=None):
    from gridgremlin.account_change import account_change, snapshot_of
    before, now_fig, fills = _world()
    if change is None:
        tr = {'from_ms': NOW - 7 * 24 * H, 'unread': {'deposits': 'retCode 10005: Permission denied'},
              'rows': [{'id': 'tr:a', 't': NOW - H, 'dir': 'in', 'coin': 'USDT', 'amount': 500.0,
                        'what': 'transfer within the account (Funding → Unified Trading)'}]}
        change = account_change([before], snapshot_of({'bybit': now_fig}), NOW, fills, RUN, KEPT, None,
                                {'bybit': tr}, {'bybit': now_fig['positions']})
    return {'generated_ms': int((time.time() - age_s) * 1000), 'account': {'bybit': now_fig},
            'account_change': change}


def spec_U150_balances_show_before_now_and_the_change_never_explained():
    from panel.strip_view import account_change_lines
    out = account_change_lines(_panel_contract())
    assert '<td>USDT</td><td>1,000</td><td>950</td><td class="neg">-50</td><td>0</td><td>100</td>' in out, out
    assert 'shown, not explained' in out
    hl = account_change_lines({'generated_ms': int(time.time() * 1000), 'account': {'hyperliquid': {'tier': 'testnet'}},
                               'account_change': {'hyperliquid': {'windows': {'24h': {
                                   'from_ms': NOW, 'short': False, 'balances': None, 'positions': [],
                                   'transfers': {'rows': [], 'unread': {}}}}}}})
    assert 'not read — Hyperliquid states no coin-by-coin wallet' in hl


def spec_U151_each_position_says_before_now_change_and_its_split():
    from panel.strip_view import account_change_lines
    out = account_change_lines(_panel_contract())
    assert ('<tr><td>BTCUSDT Perpetual Futures · LONG</td><td>0.5</td><td>0.8</td><td>+0.3</td>'
            '<td>+0.2</td><td>+0.1</td></tr>') in out, out
    assert 'SOLUSDT Perpetual Futures · LONG <b>closed</b>' in out
    assert 'ETHUSDT Perpetual Futures · SHORT <b>new</b>' in out
    assert '<th>from the bots</th><th>not from a bot</th>' in out


def spec_U152_a_position_no_bot_runs_is_listed_with_its_pnl_and_leverage_and_no_action():
    from panel.strip_view import account_change_lines
    out = account_change_lines(_panel_contract())
    i = out.index('Account positions, not from a bot')
    part = out[i:]
    assert '<td>ETHUSDT Perpetual Futures Trade · SHORT</td><td>2</td><td>100</td><td>101</td>' in part
    assert '+1.5' in part and '10x' in part
    assert '<form' not in out and 'close' not in part.lower()               # no close path for these yet


def spec_U152_money_in_and_out_is_listed_or_not_read():
    from panel.strip_view import account_change_lines
    out = account_change_lines(_panel_contract())
    assert '<b>in</b> 500 USDT · transfer within the account (Funding → Unified Trading)' in out
    assert 'not read: deposits — retCode 10005: Permission denied' in out
    none = _panel_contract()
    for w in none['account_change']['bybit']['windows'].values():
        if 'transfers' in w:
            w['transfers'] = {'rows': [], 'unread': {k: 'Permission denied' for k in
                                                     ('deposits', 'withdrawals', 'transfers within the account',
                                                      'transfers between accounts')}}
    assert 'money in/out of the account</h4><p><span class="dim">not read: deposits' in account_change_lines(none)


def spec_U153_a_contract_marked_public_draws_no_account_lines():
    """The renderer's half of U153 (the page's own is in spec_public, which
    the public edition leaves out with the page): a contract the public
    page has stripped draws neither the account lines nor the changes."""
    from panel.render import cards_section
    c = dict(_panel_contract(), bots={}, terms={})
    assert 'parts acctlines' in cards_section(0, 'x', c, scripted=True)
    page = cards_section(0, 'x', dict(c, public=True), scripted=True)
    assert 'parts acctlines' not in page and 'parts acctchg' not in page


def spec_U154_the_since_switch_steps_1h_24h_7d_and_each_window_is_drawn():
    from panel.css import CSS
    from panel.reference import NAV_JS
    from panel.strip_view import account_change_lines
    out = account_change_lines(_panel_contract())
    assert out.count('data-tog="since"') == 1
    assert ('since: <span class="s1h">1 h</span><span class="s24h">24 h</span>'
            '<span class="s7d">7 d</span>') in out
    for k in ('1h', '24h', '7d'):
        assert f'<div class="chg chg-{k}">' in out
    assert '.s1h,.s7d,.chg-1h,.chg-7d{display:none}' in CSS                   # 24 h shows by default
    assert ".since-1h .chg-1h,.since-7d .chg-7d{display:block}" in CSS
    assert "SINCE=['1h','24h','7d']" in NAV_JS
    assert "ggSince(SINCE[(SINCE.indexOf(since())+1)%SINCE.length])" in NAV_JS


def spec_U154_a_stale_readout_shows_no_change_and_the_live_panel_alone_draws_it():
    import panel.strip_view as sv
    assert sv.account_change_lines(_panel_contract(age_s=3600)) == ''
    saved = sv.READOUT_STALE_S
    sv.READOUT_STALE_S = 1e12                                                # the guard removed
    try:
        assert sv.account_change_lines(_panel_contract(age_s=3600)) != ''
    finally:
        sv.READOUT_STALE_S = saved
    from panel.render import cards_section
    c = dict(_panel_contract(), bots={}, terms={})
    assert 'acctchg' in cards_section(0, 'x', c, scripted=True)
    assert 'acctchg' not in cards_section(0, 'x', c, scripted=False)           # an export never
