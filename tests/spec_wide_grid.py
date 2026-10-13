# Specs for the grid at wide, slow terms (the audit before real money,
# 2026-10-13): W1b the window fits the gap, G27 the step's effect said.


def _adapter(step, minimum):
    from gridgremlin.adapters import LinearAdapter
    return LinearAdapter({'symbol': 'X', 'qty_step': step, 'min_qty': minimum, 'price_tick': 0.01,
                          'min_notional': 5.0, 'settle_coin': 'USDT'})


def _row(**kw):
    from gridgremlin.config import validate_fleet
    row = dict({'market_type': 'linear', 'symbol': 'ETHUSDT', 'side': 'long', 'capital': 1000,
                'leverage': 2, 'lower': 2100, 'upper': 2900, 'rungs': 8}, **kw)
    return validate_fleet({'bots': [row]})['bots'][0]


def spec_W1b_a_wide_grids_window_reaches_its_exits():
    """A lot's exit sits one gap above its buy; a 5% window on a 4.7% grid
    left a bought lot's exit off the venue. Unstated, a wide grid's window
    is two gaps (a narrow grid keeps 5%); stated narrower than one gap, the
    row is refused by name; stated wide enough, it stands."""
    from gridgremlin.config import ConfigError, rung_gap
    c = _row()
    gap = rung_gap(c)
    assert 0.04 < gap < 0.05 and abs(c['place_within_pct'] - round(2 * gap, 4)) < 1e-9
    assert _row(lower=2400, upper=2600, rungs=41)['place_within_pct'] == 0.05
    assert _row(place_within_pct=0.12)['place_within_pct'] == 0.12
    try:
        _row(place_within_pct=0.03)
        raise AssertionError('a window narrower than a gap was accepted')
    except ConfigError as e:
        assert 'narrower than one rung gap' in str(e) and 'W1b' in str(e)


def spec_G27_the_venues_step_is_said_when_it_bends_the_ladder():
    """On BTC's 0.001 step a 1,000 USDT grid of 12 rungs floors every rung
    to the minimum (the ladder well short of capital x leverage) and 10
    rungs mix 0.001 and 0.002 (a tilt nobody chose): said. ETH's 0.01 step
    keeps the same grid even: nothing said."""
    from gridgremlin.ladder import rounding_note
    btc = _row(symbol='BTCUSDT', lower=90000, upper=130000, rungs=12)
    note = rounding_note(btc, _adapter(0.001, 0.001))
    assert note and 'uneven' in note and 'G27' in note
    assert rounding_note(_row(), _adapter(0.01, 0.01)) is None


def spec_F1b_a_fleet_refuses_to_start_unless_its_watchdog_reads_its_snapshots():
    """A watchdog copied from another fleet would read that fleet's file and
    vouch for it; the start refuses, naming both, before any write. The
    same file, or no snapshot at all, passes."""
    import json
    import tempfile
    from pathlib import Path
    from gridgremlin.config import ConfigError
    from gridgremlin.main import check_snapshot_watched
    with tempfile.TemporaryDirectory() as d:
        wd = Path(d) / 'wd.json'
        wd.write_text(json.dumps({'snapshot': str(Path(d) / 'snap-a.jsonl')}))
        fleet = Path(d) / 'fleet.json'
        fleet.write_text(json.dumps({'watchdog': str(wd), 'bots': []}))
        check_snapshot_watched(fleet, str(Path(d) / 'snap-a.jsonl'))
        check_snapshot_watched(fleet, None)
        try:
            check_snapshot_watched(fleet, str(Path(d) / 'snap-b.jsonl'))
            raise AssertionError('a fleet watched through another file was started')
        except ConfigError as e:
            assert 'snap-b' in str(e) and 'snap-a' in str(e) and 'F1b' in str(e)
