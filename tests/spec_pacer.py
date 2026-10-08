"""E11 — the write pacer: a floor between writes, and the venue's own
refill moment honoured."""
from gridgremlin.exchange.pacer import Pacer


class _Clock:
    def __init__(self):
        self.t = 100.0
        self.slept = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(round(s, 4))
        self.t += s


def spec_E11_writes_are_spread_by_a_floor_not_burst():
    c = _Clock()
    p = Pacer(min_gap=0.12, clock=c, sleep=c.sleep)
    for _ in range(30):
        p.wait()                                   # thirty orders at a fleet's start
    assert c.slept == [0.12] * 29                   # the first goes at once, the rest 120 ms apart
    assert abs(p.waited - 29 * 0.12) < 1e-9 and abs(c.t - 100.0 - 29 * 0.12) < 1e-9
    c.t += 10.0
    p.wait()
    assert len(c.slept) == 29                       # a write after a pause waits for nothing


def spec_E11_a_spent_budget_holds_the_next_write_until_the_venue_refills_and_no_longer():
    c = _Clock()
    p = Pacer(min_gap=0.0, clock=c, sleep=c.sleep)
    assert p.learn({'X-Bapi-Limit-Status': '3', 'X-Bapi-Limit': '10',
                    'X-Bapi-Limit-Reset-Timestamp': '1700000001000'}) == 3
    p.wait(venue_now_ms=1700000000000)
    assert c.slept == []                            # budget left: no hold
    assert p.learn({'X-Bapi-Limit-Status': '0', 'X-Bapi-Limit-Reset-Timestamp': '1700000000800'}) == 0
    p.wait(venue_now_ms=1700000000500)
    assert c.slept == [0.3]                         # held until the refill moment, 300 ms away
    p.wait(venue_now_ms=1700000000900)
    assert c.slept == [0.3]                         # the hold was spent once; nothing more
    p.learn({'X-Bapi-Limit-Status': '0', 'X-Bapi-Limit-Reset-Timestamp': '1700000099000'})
    p.wait(venue_now_ms=1700000000000)
    assert c.slept == [0.3, 5.0]                    # a refill far off is capped: five seconds, never a minute
    assert p.learn({}) is None and p.learn({'X-Bapi-Limit-Status': 'x'}) is None   # no headers: no hold


def spec_E11_the_write_client_paces_every_post_and_never_a_read():
    """The pacer is the write client's own, built at its first post."""
    import json
    from gridgremlin.exchange.bybit.client import Client, WriteClient
    src = open(WriteClient.post.__code__.co_filename).read()
    post = src[src.index('    def post(self, path, body):'):src.index('    def set_trading_stop')]
    assert 'pacer.wait(' in post and 'pacer.learn(resp.headers)' in post
    get = src[src.index('    def get(self, path'):src.index('    def post(self, path, body):')]
    assert 'pacer' not in get                        # reads ride E10's kept connection, unpaced
