"""D68: the doctor — what is missing, in plain words, and what is next.

  python3 -m gridgremlin.doctor [--specs]

Checks Python, the edition, .env and its keys, each exchange with a
read-only call, which network each is on, Telegram, the fleet files; then
says the next step. Nothing it does writes anywhere or places anything.
"""
import glob
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

OK, BAD, SKIP = '✓', '✗', '·'


def check_python():
    v = sys.version_info
    if v >= (3, 12):
        return OK, f'Python {v.major}.{v.minor}'
    return BAD, f'Python {v.major}.{v.minor} — 3.12 or newer is needed'


def check_edition():
    from .edition import PUBLIC
    return OK, ('community edition: demo and testnet only, real money refused (D68)'
                if PUBLIC else 'private edition')


def check_env(path='.env'):
    p = Path(path)
    if not p.exists():
        return BAD, ('.env not found — create it in the repo root with your '
                     'demo/testnet keys (README §1), then chmod 600 .env'), {}
    if p.stat().st_mode & 0o077:
        return BAD, '.env is readable by others — run: chmod 600 .env', {}
    env = {}
    for line in p.read_text().splitlines():
        if line.strip() and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return OK, '.env present, mode 600', env


def check_bybit(env, probe=None):
    if not env.get('BYBIT_API_KEY') or not env.get('BYBIT_API_SECRET'):
        return SKIP, 'Bybit: no BYBIT_API_KEY/BYBIT_API_SECRET — skipped'
    net = ('Demo Trading' if env.get('BYBIT_DEMO', '').lower() == 'true'
           else 'Testnet' if env.get('BYBIT_TESTNET', '').lower() == 'true'
           else 'Mainnet')
    from .edition import real_money_refused
    if net == 'Mainnet' and real_money_refused():
        return BAD, ('Bybit: neither BYBIT_DEMO=true nor BYBIT_TESTNET=true — '
                     'that means real money, which this edition refuses; set '
                     'BYBIT_DEMO=true')
    try:
        (probe or _bybit_probe)(env)
    except Exception as e:                                   # noqa: BLE001
        return BAD, f'Bybit {net}: the key does not answer — {type(e).__name__}: {str(e)[:120]}'
    return OK, f'Bybit {net}: key answers a read-only wallet call'


def _bybit_probe(env):
    os.environ.update({k: v for k, v in env.items() if k.startswith('BYBIT_')})
    from .exchange.bybit.client import Client
    Client().wallet_balance()


def check_hyperliquid(env, probe=None):
    if not env.get('HL_ACCOUNT_ADDRESS'):
        return SKIP, 'Hyperliquid: no HL_ACCOUNT_ADDRESS — skipped'
    net = 'Testnet' if env.get('HL_TESTNET', '').lower() == 'true' else 'Mainnet'
    from .edition import real_money_refused
    if net == 'Mainnet' and real_money_refused():
        return BAD, ('Hyperliquid: HL_TESTNET is not true — that means real '
                     'money, which this edition refuses; set HL_TESTNET=true')
    try:
        (probe or _hl_probe)(env)
    except Exception as e:                                   # noqa: BLE001
        return BAD, f'Hyperliquid {net}: the account does not answer — {type(e).__name__}: {str(e)[:120]}'
    key = 'with a private key to trade' if env.get('HL_PRIVATE_KEY') else \
        'read-only (no HL_PRIVATE_KEY: it can watch, not trade)'
    return OK, f'Hyperliquid {net}: account answers, {key}'


def _hl_probe(env):
    os.environ.update({k: v for k, v in env.items() if k.startswith('HL_')})
    from .exchange.hyperliquid.client import InfoClient
    InfoClient().clearinghouse_state()


def check_telegram(env, probe=None):
    if not env.get('TELEGRAM_BOT_TOKEN') or not env.get('TELEGRAM_CHAT_ID'):
        return SKIP, ('Telegram: not set — optional; pages and the phone need '
                      'TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID and TELEGRAM_OWNER_ID')
    try:
        name = (probe or _tg_probe)(env)
    except Exception as e:                                   # noqa: BLE001
        return BAD, f'Telegram: the bot token does not answer — {type(e).__name__}: {str(e)[:120]}'
    owner = '' if env.get('TELEGRAM_OWNER_ID') else ' (no TELEGRAM_OWNER_ID: the phone will not answer commands)'
    return OK, f'Telegram: bot @{name} answers{owner}'


def _tg_probe(env):
    import urllib.request
    url = f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/getMe"
    d = json.loads(urllib.request.urlopen(url, timeout=15).read())
    return d['result']['username']


def check_fleets(root='configs'):
    from .config import validate_fleet
    files = sorted(glob.glob(os.path.join(root, 'fleet*.json')))
    if not files:
        return SKIP, (f'no fleet file in {root}/ — next: start the panel on a '
                      'name that does not exist yet and press init, or copy '
                      f'one from {root}/examples/')
    said = []
    for f in files:
        try:
            v = validate_fleet(json.loads(Path(f).read_text()))
            bad = f', {len(v["refused"])} row(s) set aside' if v['refused'] else ''
            said.append(f'{Path(f).name}: {len(v["bots"])} bot(s){bad}')
        except Exception as e:                               # noqa: BLE001
            return BAD, f'{Path(f).name} refused: {str(e)[:160]}'
    return OK, 'fleets: ' + '; '.join(said)


def check_specs(run=None):
    r = (run or _run_specs)()
    return (OK, f'specs: {r}') if '0 failed' in r else (BAD, f'specs: {r}')


def _run_specs():
    out = subprocess.run([sys.executable, 'tests/run.py'], capture_output=True,
                         text=True, timeout=600).stdout
    return out.strip().splitlines()[-1] if out.strip() else 'no output'


def next_step(results, env):
    if any(s == BAD for s, _ in results):
        return 'next: fix the ✗ lines above, then run the doctor again'
    if not glob.glob('configs/fleet*.json'):
        return ('next: python3 -m panel.server configs/mine.json --supervise — '
                'the panel offers init, then "set up a bot"')
    return ('next: python3 -m panel.server configs/<your fleet>.json --supervise '
            '— the control page starts the engine; or python3 -m gridgremlin '
            'configs/<your fleet>.json in a second terminal')


def run(argv=(), probes=None, env_path='.env', fleet_root='configs'):
    probes = probes or {}
    results = [check_python(), check_edition()]
    s, text, env = check_env(env_path)
    results.append((s, text))
    results.append(check_bybit(env, probes.get('bybit')))
    results.append(check_hyperliquid(env, probes.get('hl')))
    results.append(check_telegram(env, probes.get('tg')))
    results.append(check_fleets(fleet_root))
    if '--specs' in argv:
        results.append(check_specs(probes.get('specs')))
    else:
        results.append((SKIP, 'specs: not run — add --specs (about half a minute)'))
    lines = [f'{s} {t}' for s, t in results] + ['', next_step(results, env)]
    return '\n'.join(lines), all(s != BAD for s, _ in results)


def main(argv):
    text, ok = run(argv)
    print(text)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
