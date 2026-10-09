"""SPEC V18: Hyperliquid signing and writes, stdlib-vendored (docs/HYPERLIQUID.md §6.1).

The crypto pipeline (keccak / msgpack / RFC6979-secp256k1 / EIP-712) is pinned
BIT-FOR-BIT against the official hyperliquid-python-sdk's production test
vectors (tests/signing_test.py @ master, fetched 2026-07-27) — a wrong byte
anywhere changes r/s/v, so these vectors transitively prove every layer. The
write client is exercised against a stubbed transport: payload shape, nonce
monotonicity, cloid identity, float refusal, ambiguity discipline. One spec per
layer, every vector named in its own failure (the 2026-10-08 audit: the module
body was one spec, and one bad vector read as one failure with no id).
"""
import os

from gridgremlin.exchange.hyperliquid.client import HLError
from gridgremlin.exchange.hyperliquid.exchange import ExchangeClient
from gridgremlin.exchange.hyperliquid.signing import (action_hash, cloid_to_link, keccak256,
                                                      link_to_cloid, msgpack_pack, priv_to_address,
                                                      sign_l1_action)

KEY = '0x0123456789012345678901234567890123456789012345678901234567890123'
WALLET = '0x14791697260e4c9a71f18484c9f997b308e59325'

cases = [
    (127, '7f'), (128, 'cc80'), (255, 'ccff'), (256, 'cd0100'),
    (65535, 'cdffff'), (65536, 'ce00010000'), (2 ** 32, 'cf0000000100000000'),
    (-1, 'ff'), (-32, 'e0'), (-33, 'd0df'),
    (True, 'c3'), (False, 'c2'), (None, 'c0'),
    ('Alo', 'a3416c6f'), ('x' * 32, 'd920' + '78' * 32),
    ([1, 'a'], '9201a161'), ({'a': 1}, '81a16101'),
]


VECTORS = [
    ('dummy action', {'type': 'dummy', 'num': 100000000000}, None,
     ('0x53749d5b30552aeb2fca34b530185976545bb22d0b3ce6f62e31be961a59298',
      '0x755c40ba9bf05223521753995abb2f73ab3229be8ec921f350cb447e384d8ed8', 27),
     ('0x542af61ef1f429707e3c76c5293c80d01f74ef853e34b76efffcb57e574f9510',
      '0x17b8b32f086e8cdede991f1e2c529f5dd5297cbe8128500e00cbaf766204a613', 28)),
    ('Gtc order', {'type': 'order', 'orders': [
        {'a': 1, 'b': True, 'p': '100', 's': '100', 'r': False,
         't': {'limit': {'tif': 'Gtc'}}}], 'grouping': 'na'}, None,
     ('0xd65369825a9df5d80099e513cce430311d7d26ddf477f5b3a33d2806b100d78e',
      '0x2b54116ff64054968aa237c20ca9ff68000f977c93289157748a3162b6ea940e', 28),
     ('0x82b2ba28e76b3d761093aaded1b1cdad4960b3af30212b343fb2e6cdfa4e3d54',
      '0x6b53878fc99d26047f4d7e8c90eb98955a109f44209163f52d8dc4278cbbd9f5', 27)),
    ('order + cloid', {'type': 'order', 'orders': [
        {'a': 1, 'b': True, 'p': '100', 's': '100', 'r': False,
         't': {'limit': {'tif': 'Gtc'}}, 'c': '0x00000000000000000000000000000001'}],
        'grouping': 'na'}, None,
     ('0x41ae18e8239a56cacbc5dad94d45d0b747e5da11ad564077fcac71277a946e3',
      '0x3c61f667e747404fe7eea8f90ab0e76cc12ce60270438b2058324681a00116da', 27),
     ('0xeba0664bed2676fc4e5a743bf89e5c7501aa6d870bdb9446e122c9466c5cd16d',
      '0x7f3e74825c9114bc59086f1eebea2928c190fdfbfde144827cb02b85bbe90988', 28)),
    ('vault variant', {'type': 'dummy', 'num': 100000000000},
     '0x1719884eb866cb12b2287399b15f7db5e7d775ea',
     ('0x3c548db75e479f8012acf3000ca3a6b05606bc2ec0c29c50c515066a326239',
      '0x4d402be7396ce74fbba3795769cda45aec00dc3125a984f2a9f23177b190da2c', 28),
     ('0xe281d2fb5c6e25ca01601f878e4d69c965bb598b88fac58e475dd1f5e56c362b',
      '0x7ddad27e9a238d045c035bc606349d075d5c5cd00a6cd1da23ab5c39d4ef0f60', 27)),
    ('trigger (nested maps)', {'type': 'order', 'orders': [
        {'a': 1, 'b': True, 'p': '100', 's': '100', 'r': False,
         't': {'trigger': {'isMarket': True, 'triggerPx': '103', 'tpsl': 'sl'}}}],
        'grouping': 'na'}, None,
     ('0x98343f2b5ae8e26bb2587daad3863bc70d8792b09af1841b6fdd530a2065a3f9',
      '0x6b5bb6bb0633b710aa22b721dd9dee6d083646a5f8e581a20b545be6c1feb405', 27),
     ('0x971c554d917c44e0e1b6cc45d8f9404f32172a9d3b3566262347d0302896a2e4',
      '0x206257b104788f80450f8e786c329daa589aa0b32ba96948201ae556d5637eac', 28)),
]



def _bad(rows):
    """The failures of a table of (name, got, want), every one named."""
    return [f'{n}: got {g!r}, want {w!r}' for n, g, w in rows if g != w]


def spec_V18_keccak256_is_ethereums_padding_not_nist_sha3():
    assert not _bad([
        ('empty', keccak256(b'').hex(), 'c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470'),
        ('abc', keccak256(b'abc').hex(), '4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45'),
        ('multi-block length', len(keccak256(b'x' * 300)), 32),
    ])


def spec_V18_msgpack_matches_the_reference_at_every_boundary_and_refuses_floats():
    assert not _bad([(repr(v), msgpack_pack(v).hex(), want) for v, want in cases])
    try:
        msgpack_pack(1.5)
    except TypeError:
        pass
    else:
        raise AssertionError('msgpack must REFUSE floats (wire numbers are strings)')


def spec_V18_signatures_match_the_official_sdk_bit_for_bit_on_both_nets():
    h = action_hash({'type': 'order', 'orders': [
        {'a': 4, 'b': True, 'p': '1670.1', 's': '0.0147', 'r': False,
         't': {'limit': {'tif': 'Ioc'}}}], 'grouping': 'na'}, None, 1677777606040)
    rows = [('phantom-agent connectionId', h.hex(),
             '0fcbeda5ae3c4950a548021552a4fea2226858c4453571bf3f24ba017eac2908'),
            ('wallet address', priv_to_address(KEY), WALLET)]
    for name, action, vault, main_want, test_want in VECTORS:
        for is_main, want in ((True, main_want), (False, test_want)):
            sig = sign_l1_action(KEY, action, vault, 0, is_main)
            rows.append((f"{name} {'mainnet' if is_main else 'testnet'}",
                         (sig['r'], sig['s'], sig['v']), want))
    assert not _bad(rows), _bad(rows)


def spec_V18_a_cloid_carries_the_link_id_verbatim_and_refuses_to_truncate():
    c = link_to_cloid('perBTCl-5')
    assert not _bad([
        ('ascii-in-hex, null-padded', c, '0x7065724254436c2d3500000000000000'),
        ('round-trips', cloid_to_link(c), 'perBTCl-5'),
        ('a foreign binary cloid', cloid_to_link('0x00000000000000000e8ab9a57c642b15'), None),
        ('empty', cloid_to_link(''), None),
        ('none', cloid_to_link(None), None),
    ])
    try:
        link_to_cloid('this-link-id-is-way-too-long')
    except ValueError:
        pass
    else:
        raise AssertionError('a link_id over 16 bytes must be refused, not truncated (rungs would alias)')


class StubExchange(ExchangeClient):
    """Capture what would go on the wire; answer like HL."""

    def __init__(self):
        super().__init__(env='testnet', private_key=KEY)
        self.posted = []
        self.reply = {'status': 'ok', 'response': {'type': 'order', 'data': {
            'statuses': [{'resting': {'oid': 77}}]}}}

    def _post(self, path, body, retry_429=True):
        self.posted.append((path, body))
        return self.reply


def _stub():
    # hermetic: the operator's real .env must not leak in — an empty value
    # beats load_env's setdefault, forcing the no-address path
    os.environ['HL_ACCOUNT_ADDRESS'] = ''
    os.environ['HL_PRIVATE_KEY'] = ''
    return StubExchange()


def spec_V18_an_order_goes_out_in_the_sdks_envelope_post_only_and_named_by_its_link():
    x = _stub()
    assert x.wallet == WALLET == x.address           # no account address: the wallet IS the account
    r = x.place_order(0, 'Buy', '0.0002', '60000', order_link_id='perBTCl-3')
    path, body = x.posted[-1]
    wire = body['action']['orders'][0]
    assert not _bad([
        ('path', path, '/exchange'),
        ('action type', body['action']['type'], 'order'),
        ('grouping', body['action']['grouping'], 'na'),
        ('envelope', set(body), {'action', 'nonce', 'signature', 'vaultAddress', 'expiresAfter'}),
        ('post-only as Alo', wire['t'], {'limit': {'tif': 'Alo'}}),
        ('the cloid is the link', wire['c'], link_to_cloid('perBTCl-3')),
        ('v', body['signature']['v'] in (27, 28), True),
        ('r', body['signature']['r'].startswith('0x'), True),
        ('resting parsed', r, {'status': 'resting', 'oid': 77}),
    ])


def spec_V18_nonces_strictly_increase_and_floats_never_reach_the_wire():
    x = _stub()
    x.place_order(0, 'Buy', '0.0002', '60000', order_link_id='perBTCl-3')
    n1 = x.posted[-1][1]['nonce']
    x.place_order(0, 'Sell', '0.0002', '70000', order_link_id='perBTCl-9')
    n2 = x.posted[-1][1]['nonce']
    assert n2 > n1, f'nonces must strictly increase even in the same ms ({n1} -> {n2})'
    try:
        x.place_order(0, 'Buy', 0.0002, '60000')
    except TypeError:
        pass
    else:
        raise AssertionError('a float qty must be REFUSED (it would hash != serialise)')


def spec_V18_cancel_amend_and_leverage_wires_and_a_gone_cancel_is_success():
    x = _stub()
    x.cancel_order(0, order_link_id='perBTCl-3')
    by_link = x.posted[-1][1]['action']
    x.cancel_order(0, order_id=77)
    by_oid = x.posted[-1][1]['action']
    x.reply = {'status': 'ok', 'response': {'type': 'cancel', 'data': {
        'statuses': [{'error': 'Order was never placed, already canceled, or filled. asset=0'}]}}}
    gone = x.cancel_order(0, order_id=78)
    x.reply = {'status': 'ok', 'response': {'type': 'order', 'data': {
        'statuses': [{'resting': {'oid': 78}}]}}}
    x.amend_order(0, 'Buy', '0.0001', '60000', order_link_id='perBTCl-3')
    amend = x.posted[-1][1]['action']
    x.update_leverage(0, 5)
    lev = x.posted[-1][1]['action']
    assert not _bad([
        ('cancel by link', (by_link['type'], by_link['cancels'][0]['cloid']),
         ('cancelByCloid', link_to_cloid('perBTCl-3'))),
        ('cancel by oid', by_oid, {'type': 'cancel', 'cancels': [{'a': 0, 'o': 77}]}),
        ('a gone cancel is idempotent success', gone['status'], 'gone'),
        ('amend by our cloid, full body', (amend['type'], amend['modifies'][0]['oid'],
                                           amend['modifies'][0]['order']['s']),
         ('batchModify', link_to_cloid('perBTCl-3'), '0.0001')),
        ('updateLeverage', lev, {'type': 'updateLeverage', 'asset': 0, 'isCross': True, 'leverage': 5}),
    ])


def spec_V18_a_clean_err_status_is_a_real_rejection_not_ambiguous():
    x = _stub()
    x.reply = {'status': 'err', 'response': 'Invalid nonce'}
    try:
        x.place_order(0, 'Buy', '0.0002', '60000')
    except HLError as e:
        assert not e.ambiguous
    else:
        raise AssertionError("status:'err' must raise")
