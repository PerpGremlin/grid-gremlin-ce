"""H5 (D78): two accounts on one box — a fleet names its account, the
process reads that account's keys, Hyperliquid's sub-account rides every
signed action as its vault, and the lock knows the account."""
import json
import os
import tempfile
from pathlib import Path

from gridgremlin.config import ConfigError, validate_fleet
from gridgremlin.exchange.env import select_account

ROW = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long', 'capital': 1000,
       'leverage': 5, 'lower': 80000, 'upper': 90000, 'rungs': 11}
WD = {'tag': 't', 'snapshot': 's', 'state': 'st', 'staleness_seconds': 9, 'mm_rate_max': 0.5,
      'equity_min': 10, 're_alert_seconds': 9, 'assumes_sole_actor': True}


def _env(**kv):
    saved = {k: os.environ.get(k) for k in kv}
    for k, v in kv.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    return saved


def _restore(saved):
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def spec_H5_the_process_reads_the_named_accounts_keys_under_the_standard_names():
    saved = _env(BYBIT_API_KEY='main-k', BYBIT_API_SECRET='main-s', BYBIT_DEMO='true',
                 BYBIT_CARRY_API_KEY='carry-k', BYBIT_CARRY_API_SECRET='carry-s', BYBIT_CARRY_DEMO='true',
                 HL_ACCOUNT_ADDRESS='0xmaster', HL_CARRY_SUBACCOUNT='0xsub', HL_SUBACCOUNT=None,
                 BYBIT_LIVE_API_KEY='live-k', BYBIT_LIVE_API_SECRET='live-s')
    try:
        import gridgremlin.exchange.env as envmod
        envmod._defaults = None                      # this process's first sight is here
        assert select_account('default') == {} and os.environ['BYBIT_API_KEY'] == 'main-k'
        picked = select_account('carry')
        assert os.environ['BYBIT_API_KEY'] == 'carry-k' and os.environ['BYBIT_API_SECRET'] == 'carry-s'
        assert os.environ['BYBIT_DEMO'] == 'true'
        assert os.environ['HL_ACCOUNT_ADDRESS'] == '0xsub' == os.environ['HL_SUBACCOUNT']
        assert set(picked) == {'BYBIT_API_KEY', 'BYBIT_API_SECRET', 'BYBIT_DEMO', 'HL_ACCOUNT_ADDRESS', 'HL_SUBACCOUNT'}
        # an account that says neither demo nor testnet is real money: the flags clear, D25 decides
        select_account('live')
        assert os.environ['BYBIT_API_KEY'] == 'live-k' and os.environ['BYBIT_DEMO'] == '' and os.environ['BYBIT_TESTNET'] == ''
        # a process that reads several fleets: 'default' after 'carry' is the main keys again
        assert select_account('default') == {}
        assert os.environ['BYBIT_API_KEY'] == 'main-k' and os.environ['HL_ACCOUNT_ADDRESS'] == '0xmaster'
        assert 'HL_SUBACCOUNT' not in os.environ
        select_account('carry')
        try:
            select_account('ghost')
        except PermissionError as e:
            assert "account 'ghost': no keys" in str(e) and 'BYBIT_GHOST_API_KEY' in str(e)
        else:
            raise AssertionError('an account with no keys was accepted')
    finally:
        _restore(saved)
        os.environ.pop('BYBIT_TESTNET', None)
        envmod._defaults = None


def spec_H5_a_fleet_names_one_account_and_a_rows_account_must_be_it():
    assert validate_fleet({'bots': [ROW]})['account'] == 'default'
    assert validate_fleet({'bots': [ROW], 'account': 'carry'})['account'] == 'carry'
    for bad in ('Carry', 'my account', '', 12):
        try:
            validate_fleet({'bots': [ROW], 'account': bad})
        except ConfigError as e:
            assert "'account'" in str(e)
        else:
            raise AssertionError(f'{bad!r} accepted')
    pfo = {'strategy': 'portfolio', 'name': 'c', 'capital': 1000, 'account': 'carry',
           'assets': [{'coin': 'BTC', 'weight': 0.5}, {'coin': 'ETH', 'weight': 0.5}]}
    assert validate_fleet({'bots': [pfo], 'account': 'carry'})['bots'][0]['account'] == 'carry'
    bare = {k: v for k, v in pfo.items() if k != 'account'}
    assert validate_fleet({'bots': [bare], 'account': 'carry'})['bots'][0]['account'] == 'carry'   # inherited
    try:
        validate_fleet({'bots': [pfo]})                       # the fleet is 'default'
    except ConfigError as e:
        assert "names account 'carry' but the fleet trades 'default'" in str(e)
    else:
        raise AssertionError('a row on another account was accepted')


def spec_H5_hyperliquids_sub_account_rides_every_signed_action_as_its_vault():
    from gridgremlin.exchange.hyperliquid.exchange import ExchangeClient
    key = '0x' + '11' * 32

    class Stub(ExchangeClient):
        def __init__(self):
            super().__init__(env='testnet', private_key=key)
            self.posted = []

        def _post(self, path, body, retry_429=True):
            self.posted.append(body)
            return {'status': 'ok', 'response': {'type': 'order', 'data': {'statuses': [{'resting': {'oid': 1}}]}}}
    saved = _env(HL_SUBACCOUNT=None, HL_ACCOUNT_ADDRESS=None)
    try:
        plain = Stub()
        plain.place_order(0, 'Buy', '0.0002', '60000', order_link_id='pfoc-0-x')
        assert plain.posted[-1]['vaultAddress'] is None and plain.address == plain.wallet
        _env(HL_SUBACCOUNT='0x00000000000000000000000000000000000000ab',
             HL_ACCOUNT_ADDRESS='0x00000000000000000000000000000000000000ab')
        sub = Stub()
        sub.place_order(0, 'Buy', '0.0002', '60000', order_link_id='pfoc-0-y')
        assert sub.posted[-1]['vaultAddress'] == '0x00000000000000000000000000000000000000ab'
        assert sub.address == '0x00000000000000000000000000000000000000ab' != sub.wallet   # truth for the sub, signed by the master
    finally:
        _restore(saved)


def spec_H5_the_fleet_lock_is_named_for_the_account_too():
    from gridgremlin.main import lock_tag_for

    class C:
        def __init__(self, env):
            self.env = env
    clients = {'bybit': C('demo'), 'hyperliquid': C('testnet')}
    assert lock_tag_for(clients) == 'bybit.demo+hyperliquid.testnet'
    assert lock_tag_for(clients, 'default') == 'bybit.demo+hyperliquid.testnet'
    assert lock_tag_for(clients, 'carry') == 'bybit.demo+hyperliquid.testnet.carry'


def spec_U55_a_fleet_names_itself_for_the_dash():
    """The owner (2026-10-08): call the carry fleet 'bybit demo subaccount 1'
    on the dash. A fleet file's `label` is what the panel calls it; without
    one the venue and the file's environment word, as before."""
    import tempfile
    from pathlib import Path
    from panel.server import fleet_label
    assert validate_fleet({'bots': [ROW], 'label': 'Bybit demo subaccount 1'})['label'] == 'Bybit demo subaccount 1'
    assert validate_fleet({'bots': [ROW]})['label'] is None
    for bad in ('', '   ', 'x' * 41, 7):
        try:
            validate_fleet({'bots': [ROW], 'label': bad})
        except ConfigError as e:
            assert "'label'" in str(e)
        else:
            raise AssertionError(f'{bad!r} accepted')
    d = Path(tempfile.mkdtemp())
    (d / 'fleet.carry.json').write_text(json.dumps({'label': 'Bybit demo subaccount 1', 'bots': [ROW]}))
    (d / 'fleet.hl.testnet.json').write_text(json.dumps({'bots': [dict(ROW, venue='hyperliquid')]}))
    assert fleet_label(str(d / 'fleet.carry.json')) == 'Bybit demo subaccount 1'
    assert fleet_label(str(d / 'fleet.hl.testnet.json')) == 'hyperliquid testnet'
