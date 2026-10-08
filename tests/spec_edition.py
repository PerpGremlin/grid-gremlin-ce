"""D68: the public edition — real money refused in code, the doctor, the
example fleets. The export's own spec is tests/spec_export.py."""
import glob
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# the private tree keeps the examples beside the real configs; the public
# tree's configs ARE the examples
EXAMPLES = (ROOT / 'configs' / 'examples') if (ROOT / 'configs' / 'examples').is_dir() \
    else ROOT / 'configs'


def _public(flag):
    from gridgremlin import edition
    edition.PUBLIC = flag


def spec_F21_the_public_edition_refuses_real_money_whatever_the_flags_say():
    from gridgremlin.config import ConfigError
    from gridgremlin.main import refuse_mainnet
    from gridgremlin.exchange.errors import VenueError
    from gridgremlin.exchange.hyperliquid.client import InfoClient

    class C:
        env = 'mainnet'
    try:
        _public(True)
        try:
            refuse_mainnet(C(), fleet_allows=True, run_allows=True)
            raise AssertionError('the public edition armed real money')
        except ConfigError as e:
            assert 'cannot reach real money' in str(e)
        try:
            InfoClient(env='mainnet', address='0x1', allow_mainnet=True)
            raise AssertionError('the public HL client reached mainnet')
        except VenueError as e:
            assert 'cannot reach real money' in str(e)
        r = subprocess.run([sys.executable, '-c',
                            'import gridgremlin.edition as e; e.PUBLIC=True\n'
                            'import gridgremlin.__main__ as m; m.main()',
                            'x.json', '--allow-mainnet'],
                           capture_output=True, text=True, cwd=ROOT)
        assert r.returncode == 2 and 'cannot reach real money' in r.stderr
    finally:
        _public(False)
    refuse_mainnet(C(), fleet_allows=True, run_allows=True)   # private: D25 holds
    try:
        refuse_mainnet(C(), fleet_allows=True, run_allows=False)
        raise AssertionError('half a safety armed real money')
    except ConfigError as e:
        assert 'double-safetied' in str(e)


def spec_F21_the_examples_build_and_show_every_mechanic_once():
    from gridgremlin.apply import check_link_fits, make_botid, widest_rung
    from gridgremlin.config import validate_fleet
    from gridgremlin.main import BYBIT_LINK_LIMIT
    from gridgremlin.watchdog import validate_watchdog
    files = sorted(glob.glob(str(EXAMPLES / 'fleet*.json')))
    assert len(files) == 3                      # Bybit demo, Hyperliquid testnet, the portfolio (D78)
    seen = set()
    for f in files:
        v = validate_fleet(json.loads(Path(f).read_text()))
        assert not v['refused'], v['refused']
        validate_watchdog(json.loads((ROOT / v['watchdog']).read_text()))
        for cfg in v['bots']:
            if cfg.get('strategy') == 'portfolio':
                assert cfg['capital'] <= 300 and not cfg.get('margin') and not cfg.get('regime')
                seen.add('portfolio')
                continue
            hl = cfg['venue'] == 'hyperliquid'
            check_link_fits(make_botid(cfg['market_type'], cfg['symbol'], cfg['side']),
                            widest_rung(cfg), 16 if hl else BYBIT_LINK_LIMIT,
                            gen_chars=4 if hl else 10)
            assert cfg.get('capital', 0) <= 300 and cfg.get('leverage', 1) <= 5
            for k in ('slide', 'max_loss', 'take_profit_tranches', 'breakeven_ladder',
                      'trailing_stop_pct', 'repeat', 'stop'):
                if cfg.get(k):
                    seen.add(k)
    assert seen >= {'slide', 'max_loss', 'take_profit_tranches', 'breakeven_ladder',
                    'trailing_stop_pct', 'repeat', 'stop', 'portfolio'}, seen


def spec_F22_the_doctor_says_what_is_missing_and_what_is_next():
    from gridgremlin import doctor
    d = Path(tempfile.mkdtemp())
    env = d / '.env'
    text, ok = doctor.run(env_path=str(env), fleet_root=str(d / 'none'))
    assert not ok and '.env not found' in text and 'fix the ✗ lines' in text
    env.write_text('BYBIT_API_KEY=k\nBYBIT_API_SECRET=s\nBYBIT_DEMO=true\n')
    os.chmod(env, 0o644)
    text, ok = doctor.run(env_path=str(env), fleet_root=str(d / 'none'))
    assert not ok and 'chmod 600' in text
    os.chmod(env, 0o600)
    probes = {'bybit': lambda e: None, 'hl': lambda e: None, 'tg': lambda e: 'bot'}
    text, ok = doctor.run(env_path=str(env), fleet_root=str(d / 'none'), probes=probes)
    assert ok and 'Bybit Demo Trading: key answers' in text
    assert 'Hyperliquid: no HL_ACCOUNT_ADDRESS — skipped' in text
    assert 'no fleet file' in text and 'press init' in text
    env.write_text('BYBIT_API_KEY=k\nBYBIT_API_SECRET=s\n')     # neither flag: real money
    try:
        _public(True)
        text, ok = doctor.run(env_path=str(env), fleet_root=str(d / 'none'), probes=probes)
        assert not ok and 'this edition refuses' in text
    finally:
        _public(False)

    def down(e):
        raise OSError('timed out')
    env.write_text('BYBIT_API_KEY=k\nBYBIT_API_SECRET=s\nBYBIT_DEMO=true\n')
    text, ok = doctor.run(env_path=str(env), fleet_root=str(d / 'none'),
                          probes={'bybit': down})
    assert not ok and 'does not answer — OSError: timed out' in text
    text, ok = doctor.run(['--specs'], env_path=str(env), fleet_root=str(EXAMPLES),
                          probes={'bybit': lambda e: None, 'specs': lambda: '7 specs, 0 failed (1.0s)'})
    assert ok and 'fleets: fleet.demo.json: 11 bot(s); fleet.hl.testnet.json: 5 bot(s)' in text
    assert 'specs: 7 specs, 0 failed' in text and text.endswith('in a second terminal')
