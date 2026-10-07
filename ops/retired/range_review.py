#!/usr/bin/env python3
"""range_review.py — D10's closing note: routine "is this range still sane" as
an ops health-check, NOT engine code. Trail was deleted (D10) because range
edits through the normal diff give trailing when wanted — this is the layer
that notices when such an edit is worth considering, and it NEVER acts.

Shape: a deterministic collector reads each grid's bounds from the fleet
files and the current mark from PUBLIC venue endpoints (stdlib only, no keys,
no gridgremlin import — a broken engine cannot take the review down with it),
then hands the fact sheet to the same read-only Claude cage as triage for a
judgment. No CLI or token → the fact sheet itself is paged. Martingales are
skipped: they have no range (D13).

Run:  python3 ops/range_review.py configs/fleet.demo.json configs/fleet.hl.testnet.json
      RANGE_DRY=1 ...          (print instead of paging)
"""
import json
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SETTINGS = REPO / 'ops' / 'triage-settings.json'
TG_LIMIT = 3800
CLAUDE_TIMEOUT = 300
BYBIT_HOST = 'https://api-demo.bybit.com'    # v3's Bybit phase is demo-only
HL_HOST = 'https://api.hyperliquid-testnet.xyz'  # and HL is testnet-only (F5)


def read_env(path):
    out = {}
    try:
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            out[k.strip()] = re.split(r'\s+#', v.strip(), maxsplit=1)[0].strip()
    except OSError:
        pass
    return out


def bybit_mark(category, symbol):
    url = (f'{BYBIT_HOST}/v5/market/tickers?'
           + urllib.parse.urlencode({'category': category, 'symbol': symbol}))
    with urllib.request.urlopen(url, timeout=15) as r:
        row = json.load(r)['result']['list'][0]
    return float(row.get('markPrice') or row.get('lastPrice'))


def hl_marks():
    req = urllib.request.Request(HL_HOST + '/info',
                                 data=json.dumps({'type': 'metaAndAssetCtxs'}).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as r:
        meta, ctxs = json.load(r)
    return {e['name']: float(c['markPx'])
            for e, c in zip(meta['universe'], ctxs) if c.get('markPx')}


def slide_offsets(fleet_path, fleet):
    """G22: the engine's persisted window offsets, read-only. Missing or
    unreadable means home for every bot — the engine itself refuses to
    build on an unreadable file; the review only reports."""
    path = fleet.get('slide_state')
    if not path:
        parent = Path(fleet_path).resolve().parent
        root = parent.parent if parent.name == 'configs' else parent
        path = root / 'logs' / 'slide_state.json'
    try:
        rows = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return rows if isinstance(rows, dict) else {}


def dead_bots(fleet_path):
    """F9: the bots the fleet's newest snapshot row says are dead. The
    snapshot sits beside the slide state: logs/snapshots-<tag>.jsonl, the
    tag being the fleet file's name between `fleet.` and `.json` with dots
    as dashes (fleet.hl.testnet.json -> snapshots-hl-testnet.jsonl).
    Unreadable means nobody is known dead — the review only reports."""
    fp = Path(fleet_path).resolve()
    tag = re.sub(r'^fleet\.', '', fp.name[:-len('.json')]).replace('.', '-')
    root = fp.parent.parent if fp.parent.name == 'configs' else fp.parent
    path = root / 'logs' / f'snapshots-{tag}.jsonl'
    try:
        with open(path, 'rb') as f:              # the tail only: the file
            f.seek(0, 2)                         # grows a row a minute
            f.seek(max(0, f.tell() - 65536))
            last = f.read().decode('utf-8', 'replace').strip().splitlines()[-1]
        row = json.loads(last)
    except (OSError, ValueError, IndexError):
        return set()
    bots = row.get('bots') if isinstance(row, dict) else None
    if not isinstance(bots, dict):
        return set()
    return {b for b, v in bots.items()
            if isinstance(v, dict) and v.get('alive') is False}


def review_row(cfg, mark, offset=0):
    """PURE. One grid's facts -> one line. `offset` is the slide window's
    distance from home in rungs (G17); the bounds shown are the window's."""
    botid = (f"{cfg['market_type'][:3]}{cfg['symbol']}{cfg['side'][0]}"
             .replace('-', ''))
    lo, hi, rungs = cfg['lower'], cfg['upper'], cfg['rungs']
    tag = ''
    if offset:
        if cfg.get('spacing_type', 'percent') == 'percent':
            ratio = (hi / lo) ** (1.0 / max(rungs - 1, 1))
            lo, hi = lo * ratio ** offset, hi * ratio ** offset
        else:
            step = (hi - lo) / max(rungs - 1, 1)
            lo, hi = lo + step * offset, hi + step * offset
        tag = f'  (slid {offset:+d} rungs from home)'
    width = hi - lo
    rung = width / max(rungs - 1, 1)
    if mark is None:
        return f'{botid:<14} {lo:g}..{hi:g}  mark UNKNOWN (venue unreadable){tag}'
    if mark < lo:
        return (f'{botid:<14} {lo:g}..{hi:g}  mark {mark:g}  '
                f'IDLE BELOW range by {(lo - mark) / rung:.1f} rungs{tag}')
    if mark > hi:
        return (f'{botid:<14} {lo:g}..{hi:g}  mark {mark:g}  '
                f'IDLE ABOVE range by {(mark - hi) / rung:.1f} rungs{tag}')
    pos = (mark - lo) / width
    edge = min(mark - lo, hi - mark)
    return (f'{botid:<14} {lo:g}..{hi:g}  mark {mark:g}  {pos:.0%} up-range, '
            f'{edge / rung:.1f} rungs to the nearer edge{tag}')


def collect(fleet_paths):
    lines, skipped = [], 0
    hl = None
    for path in fleet_paths:
        fleet = json.loads(Path(path).read_text())
        offsets = slide_offsets(path, fleet)
        dead = dead_bots(path)
        for cfg in fleet.get('bots', []):
            if cfg.get('strategy') == 'martingale':
                skipped += 1                      # no range to review (D13)
                continue
            botid = (f"{cfg['market_type'][:3]}{cfg['symbol']}{cfg['side'][0]}"
                     .replace('-', ''))
            if botid in dead:
                lines.append(f'{botid:<14} DEAD (stood down) — not reviewed')
                continue                          # F9
            mark = None
            try:
                if cfg.get('venue') == 'hyperliquid':
                    hl = hl_marks() if hl is None else hl
                    mark = hl.get(cfg['symbol'])
                else:
                    mark = bybit_mark(cfg.get('market_type', 'linear'),
                                      cfg['symbol'])
            except Exception:                                    # noqa: BLE001
                pass                              # UNKNOWN is a fact too
            offset = offsets.get(botid, 0)
            lines.append(review_row(cfg, mark,
                                    offset if isinstance(offset, int) else 0))
    if skipped:
        lines.append(f'({skipped} martingale(s) skipped — no range, D13)')
    return '\n'.join(lines)


AUTH_FAILED = re.compile(r'failed to authenticate|oauth', re.I)


def judge(env, facts):
    """(verdict, reason): a verdict, or None and WHY there is none. F10:
    the judgement is an extra on top of the facts, never a substitute —
    for 30 days of the 48-day run the CLI printed 'Failed to authenticate:
    OAuth session expired' on stdout, exit 0, and that one line was paged
    AS the review while the fact sheet was dropped."""
    claude = env.get('CLAUDE_BIN') or shutil.which('claude')
    if not claude:
        return None, 'no claude CLI on the box'
    if not env.get('CLAUDE_CODE_OAUTH_TOKEN'):
        return None, 'no CLAUDE_CODE_OAUTH_TOKEN in .env'
    prompt = (
        'You are the daily range review for grid-gremlin v3 (test-fund soak, '
        'two fleets). Today\'s facts, computed from live marks:\n---\n'
        f'{facts}\n---\n\n'
        'You may read configs, docs/SOAK.md, and logs for context. Judge each '
        'grid: KEEP (mark comfortably inside), WATCH (near an edge or drifting '
        'one way), or REVIEW BOUNDS (idle outside, or the range no longer fits '
        'how the symbol trades). A grid idling outside its range is by design '
        '(G11) — flag it, do not call it broken. You cannot change anything: '
        'a bounds edit is a workstation task through the normal config diff '
        '(D10) — say what edit you would propose and why. One line per grid, '
        'then at most three sentences overall. Phone-sized, no preamble.')
    try:
        r = subprocess.run([claude, '-p', prompt, '--settings', str(SETTINGS)],
                           capture_output=True, text=True,
                           timeout=CLAUDE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, f'claude timed out after {CLAUDE_TIMEOUT}s'
    except OSError as e:
        return None, f'claude could not start: {e}'
    return verdict_or_reason(r.returncode, r.stdout, r.stderr)


def verdict_or_reason(rc, stdout, stderr):
    """PURE half of judge (F10)."""
    out = (stdout or '').strip()
    first = (out or (stderr or '').strip()).splitlines()[:1]
    first = first[0][:160] if first else ''
    if rc != 0:
        return None, f'claude exit {rc}: {first}' if first else f'claude exit {rc}'
    if not out:
        return None, 'claude answered nothing'
    if AUTH_FAILED.search(first) and len(out.splitlines()) <= 2:
        return None, f'claude not authenticated — re-mint the token: {first}'
    return out, ''


def compose(facts, verdict, reason):
    """PURE (F10): facts ALWAYS; the verdict above them when there is one,
    the reason there is none when there is not."""
    if verdict:
        return f'{verdict}\n\n--- facts ---\n{facts}'
    return f'(no judgement: {reason})\n\n{facts}'


def page(env, text):
    if not (env.get('TELEGRAM_BOT_TOKEN') and env.get('TELEGRAM_CHAT_ID')):
        print('range-review: no telegram credentials')
        print(text)
        return
    data = urllib.parse.urlencode({'chat_id': env['TELEGRAM_CHAT_ID'],
                                   'text': text[:TG_LIMIT]}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/sendMessage",
        data=data)
    urllib.request.urlopen(req, timeout=20).read()


def main(argv):
    sys.exit('range_review.py: retired 2026-10-06 — the box-side Claude stays off until the agentic phase rebuilds it in an OS-level sandbox (ops/retired/README.md)')   # RETIRED: refuses to run
    import os
    fleets = [a for a in argv if not a.startswith('-')]
    if not fleets:
        print('usage: range_review.py <fleet.json> [...]')
        return 2
    env = read_env(REPO / '.env')
    facts = collect(fleets)
    verdict, reason = judge(env, facts)
    text = f'🧌 [vps · range review]\n\n{compose(facts, verdict, reason)}'
    if os.environ.get('RANGE_DRY'):
        print(f'--- facts ---\n{facts}\n--- page ---\n{text}')
        return 0
    log = REPO / 'logs' / 'range-review.log'          # the record of record:
    log.parent.mkdir(parents=True, exist_ok=True)     # "what did he say" must
    with open(log, 'a') as f:                         # never need reproducing
        import time as _t
        f.write(f'{_t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime())}\n{text}\n\n')
    page(env, text)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
