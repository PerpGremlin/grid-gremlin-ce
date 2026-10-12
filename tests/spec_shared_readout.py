# Specs for SPEC U47b — one readout, read once: the phone keeps every
# fleet's readout warm and shares it; the panel reads that one while fresh.

import json
import tempfile
import time
from pathlib import Path


def _fleet(d):
    (Path(d) / 'configs').mkdir()
    fp = Path(d) / 'configs' / 'fleet.demo.json'
    fp.write_text('{"bots": [{"x": 1}]}')
    return str(fp)


def spec_U47b_a_shared_readout_serves_while_fresh_and_over_the_same_window():
    """Written whole beside the fleet's logs; read back only when its
    window matches and it is no older than the phone's round allows; a stale one, another
    window, an unavailable one or none at all is None — the reader then
    runs its own."""
    from gridgremlin.archive import SHARED_MAX_AGE_S, share_readout, shared_path, shared_readout
    with tempfile.TemporaryDirectory() as d:
        fp = _fleet(d)
        now = time.time()
        assert shared_readout(fp, 24.0, now=now) is None                       # none yet
        c = {'window_hours': 24.0, 'generated_ms': int(now * 1000), 'bots': {}}
        share_readout(fp, c)
        assert shared_path(fp) == Path(d) / 'logs' / 'readouts' / 'demo.json'
        assert shared_readout(fp, 24.0, now=now + 5) == c
        assert shared_readout(fp, 24.0, now=now + SHARED_MAX_AGE_S + 1) is None   # stale
        assert shared_readout(fp, 6.0, now=now) is None                        # another window
        share_readout(fp, dict(c, unavailable='venue down'))
        assert shared_readout(fp, 24.0, now=now) is None
        assert not [p for p in shared_path(fp).parent.iterdir() if p.name != 'demo.json']   # no temp left


def spec_U47b_the_phone_shares_what_it_reads_and_the_panel_uses_it():
    """The phone's refresh writes the readout it read; the panel's readout
    of that fleet is the shared one while fresh — no readout process of
    its own — and runs its own when the shared one is stale."""
    from gridgremlin import archive
    from gridgremlin.phone import Box
    from panel import routes
    with tempfile.TemporaryDirectory() as d:
        fp = _fleet(d)
        c = {'window_hours': 24.0, 'generated_ms': int(time.time() * 1000), 'bots': {}, 'unowned': {}}
        real = archive.run_readout
        archive.run_readout = lambda f, hours=24.0: c
        try:
            Box([fp]).refresh(fp)
        finally:
            archive.run_readout = real
        assert json.loads(archive.shared_path(fp).read_text()) == c
        ran = []
        real_run = routes.subprocess.run

        def fake_run(*a, **k):
            ran.append(a)
            raise AssertionError('the panel ran its own readout')
        routes.subprocess.run = fake_run
        h = routes.Handler.__new__(routes.Handler)
        h.hours = 24.0
        try:
            routes.Handler._cache.pop(fp, None)
            assert h._read_contract(fp) == c and not ran
            archive.share_readout(fp, dict(c, generated_ms=int((time.time() - 600) * 1000)))
            routes.Handler._cache.pop(fp, None)
            try:
                h._read_contract(fp)
            except AssertionError:
                pass
            assert ran                                                        # stale: its own
        finally:
            routes.subprocess.run = real_run
            routes.Handler._cache.pop(fp, None)
