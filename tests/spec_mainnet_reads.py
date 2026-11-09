# Specs for D177: a real-money fleet's readers reach mainnet on the fleet
# file's own switch — the live panel said "no fills" over a bot that had
# filled twice, its report refused by D25's launch half (owner, 2026-11-10).

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _private():
    """D177 is the private edition's; the public one refuses mainnet flatly
    (F21) — set here, never left to whichever spec file ran before."""
    from gridgremlin import edition
    found, edition.PUBLIC = edition.PUBLIC, False
    return found


def _restore(found):
    from gridgremlin import edition
    from gridgremlin.exchange.hyperliquid import client as hl
    hl.permit_mainnet_reads({})
    edition.PUBLIC = found


def _refused(make):
    from gridgremlin.exchange.hyperliquid.client import VenueError
    try:
        make()
    except VenueError as e:
        return str(e)
    return None


def spec_D177_a_real_money_fleets_switch_opens_mainnet_reads_and_only_its_own():
    """Unpermitted, a mainnet read is refused naming the file's switch; a
    fleet whose file says JSON true opens it; the next fleet read without
    it closes it again (never left over from the last fleet); a string
    'true' is not the switch (D25b)."""
    from gridgremlin.exchange.hyperliquid import client as hl
    found = _private()
    try:
        hl.permit_mainnet_reads({})
        said = _refused(lambda: hl.InfoClient(env='mainnet', address='0xabc'))
        assert said and '"allow_mainnet": true' in said and 'reading it' in said
        assert hl.permit_mainnet_reads({'allow_mainnet': True}) is True
        c = hl.InfoClient(env='mainnet', address='0xabc')
        assert c.env == 'mainnet' and c.base.startswith('https://api.hyperliquid.xyz')
        hl.permit_mainnet_reads({'allow_mainnet': False})
        assert _refused(lambda: hl.InfoClient(env='mainnet', address='0xabc'))
        hl.permit_mainnet_reads({'allow_mainnet': 'true'})
        assert _refused(lambda: hl.InfoClient(env='mainnet', address='0xabc'))
        hl.permit_mainnet_reads({'allow_mainnet': True})
        assert hl.InfoClient(env='testnet').env == 'testnet'      # paper unchanged
    finally:
        _restore(found)


def spec_D177_trading_never_takes_a_readers_permit():
    """With reads open, the trading client stays D25's: refused unless its
    caller states both halves. Sabotage: ExchangeClient passing its
    allow_mainnet through as given (False → None) lets the permit arm it."""
    from gridgremlin.exchange.hyperliquid import client as hl
    from gridgremlin.exchange.hyperliquid.exchange import ExchangeClient
    from gridgremlin.exchange.hyperliquid.venue import HLVenueClient
    key = '0x' + '11' * 32
    found = _private()
    try:
        hl.permit_mainnet_reads({'allow_mainnet': True})
        for cls in (ExchangeClient, HLVenueClient):
            said = _refused(lambda: cls(env='mainnet', private_key=key))
            assert said and '--allow-mainnet' in said, cls
            said = _refused(lambda: cls(env='mainnet', private_key=key, allow_mainnet=None))
            assert said, cls
        assert ExchangeClient(env='mainnet', private_key=key, allow_mainnet=True).env == 'mainnet'
    finally:
        _restore(found)


def spec_D177_each_reader_permits_from_its_fleet_before_any_client():
    """The report (what the panel shows), the kept ledger and the drift
    check set the permit from the fleet they read, before any HL client;
    the fleet engine never sets it."""
    def src(name):
        return (ROOT / 'gridgremlin' / name).read_text()
    rep = src('report.py')
    body = rep[rep.index('\ndef main('):]
    assert body.index('permit_mainnet_reads(fleet)') < body.index('_hl_pull(')
    kept = src('kept_fills.py')
    assert kept.index('permit_mainnet_reads(fleet)') < kept.index("clients['hl'] = InfoClient()")
    drift = src('pnl_drift.py')
    assert drift.index('permit_mainnet_reads(fleet)') < drift.index("out['hl'] = InfoClient()")
    assert 'permit_mainnet_reads' not in src('main.py')
    assert 'permit_mainnet_reads' not in src('bot.py')
