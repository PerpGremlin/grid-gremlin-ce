# Specs for SPEC F18 (D61) — reading commands over Telegram: owner-only,
# read-only, answered from what the box already keeps.

import inspect
import json
import tempfile
import time
from pathlib import Path

from gridgremlin import phone
from gridgremlin.phone import accepted, answer, chunks, poll_once

OWNER = 4242
CONTRACT = {
    'bots': {'linBTCUSDTl': {'realized': 10.0, 'fees': 1.0,
                             'unreal_at_mark': -2.0, 'position': 0.5,
                             'avg_cost': 60000.0, 'mark': 59000.0},
             'linADAUSDTl': {'realized': 1.0, 'fees': 0.5,
                             'unreal_at_mark': 0.0, 'position': 0.0,
                             'avg_cost': 0.0, 'mark': 0.27}},
    'since_first': {'linBTCUSDTl': {'realized': 100.0, 'fees': 5.0,
                                    'unreal_at_mark': -2.0, 'whole': True,
                                    'behind': None, 'fills': 9},
                    'linADAUSDTl': {'fills': 4, 'whole': False,
                                    'behind': None}},
    'ranges': {'linBTCUSDTl': {'lower': 50000.0, 'upper': 70000.0}},
    'terms': {'linADAUSDTl': {'strategy': 'martingale'},
              'linBTCUSDTl': {'strategy': 'grid'}}}


class FakeBox(phone.Box):
    def __init__(self):
        super().__init__(['configs/fleet.demo.json'])
        self.readouts = 0

    def readout(self, fp):
        self.readouts += 1
        return CONTRACT

    def snapshot(self, fp):
        return {'t': time.time() - 20, 'equity': 5000.0, 'mm_rate': 0.05,
                'bots': {'linBTCUSDTl': {'alive': True, 'orders': {
                    'resting': {'buys': 3, 'sells': 2},
                    'waiting': {'buys': 1, 'sells': 0}}},
                         'linADAUSDTl': {'alive': False}}}

    def watchdog(self, fp):
        return ({'equity_min': 4000.0, 'mm_rate_max': 0.5,
                 'equity_drawdown_max': 0.3}, {'_peak': 6000.0, 'mmr': 1})

    def log_lines(self, fp):
        return ['[ship] fill linBTCUSDTl: position 1 -> 2',
                '[ship] warn linBTCUSDTl: tp: refused',
                'cycle 3 linBTCUSDTl: {}',
                '[ship] kill linADAUSDTl: stood down',
                '[ship] exit linBTCUSDTl: position 2 -> 1']

    def digest(self):
        return 'the digest'


def _u(uid, sender, text):
    return {'update_id': uid, 'message': {'from': {'id': sender},
                                          'text': text}}


def spec_F18_only_the_owner_and_only_commands():
    assert accepted(_u(1, OWNER, '/pnl'), OWNER) == ('/pnl', 'command')
    assert accepted(_u(1, 999, '/pnl'), OWNER)[0] is None       # a stranger
    assert accepted(_u(1, OWNER, 'hello'), OWNER)[0] is None    # not a command
    assert accepted(_u(1, OWNER, '/pnl'), 0)[0] is None         # fail closed


def spec_F18_every_command_answers_from_the_box():
    box = FakeBox()
    assert '/pnl' in answer(box, '/help')
    s = answer(box, '/status')
    assert '1/2 alive' in s and 'stood down: linADAUSDTl' in s
    p = answer(box, '/pnl')
    assert 'demo: now +7.50 · kept +93.00 (1 not whole)' in p
    one = answer(box, '/pnl btc')                     # named in part
    assert 'linBTCUSDTl: now +7.00 · kept +93.00' in one
    assert 'linADAUSDTl' not in one
    assert 'no bot matches "xyz"' in answer(box, '/pnl xyz')
    pos = answer(box, '/positions')
    assert 'linBTCUSDTl: 0.5 @ 60,000 · price 59,000 · open -2.00' in pos
    assert 'linADAUSDTl' not in pos                   # flat: not a holding
    assert 'resting 3 buys / 2 sells · waiting 1 / 0' in answer(box, '/orders btc')
    assert '45% up the range' in answer(box, '/grids')
    assert 'linADAUSDTl: stood down' in answer(box, '/rounds')   # dead + flat
    r = answer(box, '/risk')
    assert 'equity 5,000 (floor 4,000)' in r and '16.7% below peak' in r
    assert 'watchdog breached: mmr' in r
    a = answer(box, '/alerts')
    assert 'tp: refused' in a and 'stood down' in a and 'position 1' not in a
    lg = answer(box, '/log btc 2')
    assert lg.count('\n') == 1 and 'position 2 -> 1' in lg   # the newest 2
    assert answer(box, '/today') == 'the digest'
    assert 'unknown command /buy' in answer(box, '/buy btc')
    assert '/pnl' in answer(box, '/help@gridgremlin_bot')     # group form
    assert 'floor 4,000' in answer(box, '/risk.')             # phone punctuation
    assert 'kept +93.00' in answer(box, '/pnl! btc')


def spec_F18_a_broken_source_is_said_not_raised():
    class Broken(FakeBox):
        def readout(self, fp):
            raise RuntimeError('readout failed: venue down')
    assert 'could not read: RuntimeError' in answer(Broken(), '/pnl')


def spec_F18_long_answers_split_under_the_cap():
    text = '\n'.join(f'line {i} ' + 'x' * 80 for i in range(200))
    parts = chunks(text, 1000)
    assert all(len(p) <= 1000 for p in parts)
    assert '\n'.join(parts) == text


def spec_F18_the_offset_is_kept_before_any_answer_is_sent():
    """A crash between the two costs an unanswered question, never a loop
    of answers to one; strangers move the offset and get nothing."""
    with tempfile.TemporaryDirectory() as d:
        state = Path(d) / 'relay.state.json'
        state.write_text(json.dumps({'offset': 10}))
        seen = {}

        class TG:
            sent = []

            def updates(self, offset, wait):
                seen['offset'] = offset
                return [_u(10, OWNER, '/status'), _u(11, 999, '/pnl'),
                        _u(12, OWNER, 'hi')]

            def send(self, chat, text):
                seen['written'] = json.loads(state.read_text())['offset']
                TG.sent.append((chat, text))
        n = poll_once(TG(), FakeBox(), OWNER, 'chat', state_path=state)
        assert seen['offset'] == 10 and n == 1
        assert seen['written'] == 13                  # kept before sending
        assert len(TG.sent) == 1 and TG.sent[0][0] == 'chat'


def spec_F18_nothing_here_can_write_to_a_venue():
    src = inspect.getsource(phone)
    for forbidden in ('place_order', 'cancel_order', 'place_market',
                      'set_trading_stop', 'exchange_action', 'WriteClient',
                      'systemctl', 'subprocess'):
        assert forbidden not in src, forbidden


def spec_F18_a_warm_box_answers_at_once_and_says_how_old():
    """/pnl ran the readout on the ask — about 20 s from the phone. The
    service keeps one warm instead; the answer says its age."""
    reads = []

    class Warm(phone.Box):
        def __init__(self):
            super().__init__(['configs/fleet.demo.json'])

        def refresh(self, fp):
            reads.append(fp)
            c = dict(CONTRACT, generated_ms=(time.time() - 42) * 1000)
            self._readouts[fp] = (time.time() - 3600, c)   # an hour-old read
            return c

        def snapshot(self, fp):
            return {}
    box = Warm()
    box.keep_warm(every=0, rounds=1)
    assert reads == ['configs/fleet.demo.json']
    box.warm = True
    p = answer(box, '/pnl')
    assert reads == ['configs/fleet.demo.json']        # no read on the ask
    assert '(read 42s ago)' in p
    box.warm = False                                   # not warm: past TTL,
    answer(box, '/pnl')                                # it reads again
    assert len(reads) == 2

    class Failing(Warm):
        def refresh(self, fp):
            raise RuntimeError('venue down')
    Failing().keep_warm(every=0, rounds=1)             # said, never raised
