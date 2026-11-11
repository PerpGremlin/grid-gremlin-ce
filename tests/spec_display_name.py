"""SPEC V19 (D182): a Hyperliquid account's display name, set by the fleet's own
signer — one `setDisplayName` action, refused on mainnet without both of D25's
halves and refused while the fleet runs (X15b)."""
import io
import json
import os
import sys
import tempfile
from pathlib import Path

import gridgremlin.display_name as dn
from gridgremlin.config import ConfigError
from spec_signing import KEY, StubExchange

ROW = {'venue': 'hyperliquid', 'market_type': 'linear', 'symbol': 'BTC', 'side': 'long',
       'capital': 100, 'leverage': 2, 'lower': 50000, 'upper': 60000, 'rungs': 5}


def _fleet(**extra):
    """A fleet file under configs/ beside its logs/, and an empty keys file."""
    d = Path(tempfile.mkdtemp()) / 'configs'
    d.mkdir()
    (d.parent / 'logs').mkdir()
    (d / 'wd.json').write_text(json.dumps({
        'tag': 't', 'snapshot': 's', 'state': 'st', 'staleness_seconds': 9,
        'mm_rate_max': 0.5, 'equity_min': 10, 're_alert_seconds': 9, 'assumes_sole_actor': True}))
    fleet = {'watchdog': str(d / 'wd.json'), 'bots': [dict(ROW)], **extra}
    (d / 'f.json').write_text(json.dumps(fleet))
    env = d.parent / '.env'
    env.write_text('')
    env.chmod(0o600)
    return d, str(env)


def _run(argv, net):
    """main() on `net` with a key, the answer parsed; the env put back."""
    saved_env = {k: os.environ.get(k) for k in ('HL_TESTNET', 'HL_PRIVATE_KEY',
                                                 'HL_ACCOUNT_ADDRESS')}
    os.environ.update(HL_TESTNET='true' if net == 'testnet' else 'false',
                      HL_PRIVATE_KEY=KEY, HL_ACCOUNT_ADDRESS='')
    out, saved = io.StringIO(), sys.stdout
    sys.stdout = out
    try:
        code = dn.main(argv)
    finally:
        sys.stdout = saved
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return code, json.loads(out.getvalue())


def spec_V19_the_name_goes_out_as_one_set_display_name_action():
    os.environ['HL_ACCOUNT_ADDRESS'] = ''
    x = StubExchange()
    x.reply = {'status': 'ok', 'response': {'type': 'default'}}
    out = dn.set_display_name(x, 'PerpGremlin')
    path, body = x.posted[-1]
    assert path == '/exchange'
    assert body['action'] == {'type': 'setDisplayName', 'displayName': 'PerpGremlin'}
    assert body['signature']['v'] in (27, 28)
    assert out == {'account': x.address, 'network': 'testnet', 'display_name': 'PerpGremlin'}
    assert dn.set_display_name(x, '')['display_name'] is None       # '' removes it
    assert x.posted[-1][1]['action']['displayName'] == ''


def spec_V19_a_name_past_twenty_characters_is_refused_before_signing():
    os.environ['HL_ACCOUNT_ADDRESS'] = ''
    x = StubExchange()
    for bad in ('x' * 21, ' PerpGremlin', 'PerpGremlin ', 7):
        try:
            dn.set_display_name(x, bad)
        except ConfigError:
            pass
        else:
            raise AssertionError(f'{bad!r} must be refused')
    assert x.posted == [], 'nothing reaches the wire'
    dn.check_name('x' * 20)


def spec_V19_mainnet_takes_both_halves_of_d25():
    from gridgremlin.edition import real_money_refused
    if real_money_refused():                      # D68: the public edition refuses flatly
        d, env = _fleet(allow_mainnet=True)
        code, out = _run([str(d / 'f.json'), 'PerpGremlin', '--env', env, '--allow-mainnet'],
                         'mainnet')
        assert code == 1 and real_money_refused() in out['refused'], out
        return
    d, env = _fleet()
    code, out = _run([str(d / 'f.json'), 'PerpGremlin', '--env', env, '--allow-mainnet'],
                     'mainnet')
    assert code == 1 and "missing '\"allow_mainnet\": true'" in out['refused'], out   # the switch
    d, env = _fleet(allow_mainnet=True)
    code, out = _run([str(d / 'f.json'), 'PerpGremlin', '--env', env], 'mainnet')
    assert code == 1 and 'missing --allow-mainnet' in out['refused'], out   # the typing


def spec_V19_refused_while_the_fleet_runs_x15b():
    from gridgremlin.main import acquire_fleet_lock
    d, env = _fleet()
    held = acquire_fleet_lock(str(d.parent / 'logs' / 'hyperliquid.testnet.lock'))
    try:
        code, out = _run([str(d / 'f.json'), 'PerpGremlin', '--env', env], 'testnet')
    finally:
        held.close()
    assert code == 1 and 'one process signs' in out['refused'], out


def spec_V19_a_fleet_with_no_hyperliquid_bot_is_refused():
    d, env = _fleet()
    raw = json.loads((d / 'f.json').read_text())
    raw['bots'][0].update(venue='bybit', symbol='BTCUSDT')
    (d / 'f.json').write_text(json.dumps(raw))
    code, out = _run([str(d / 'f.json'), 'PerpGremlin', '--env', env], 'testnet')
    assert code == 1 and 'no Hyperliquid bot' in out['refused'], out
