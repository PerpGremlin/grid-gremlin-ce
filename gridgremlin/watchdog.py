# The watchdog (SPEC F1-F6). Pure evaluate/decide; the CLI pages before it
# persists, so a failed page re-pages.
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from .config import ConfigError, _flag, _num, _reject_unknown
from .exchange.env import load_env

WATCHDOG_KEYS = ('tag', 'snapshot', 'state', 'staleness_seconds', 'mm_rate_max',
                 'equity_min', 'equity_drawdown_max', 're_alert_seconds',
                 'positions', 'assumes_sole_actor', 'disk_used_max')


def validate_watchdog(cfg, where='watchdog'):
    """v2 shipped no validator for these; v3 refuses like everything else."""
    _reject_unknown(cfg, WATCHDOG_KEYS, where)
    out = {k: v for k, v in cfg.items() if not k.startswith('_')}
    for key in ('tag', 'snapshot', 'state'):
        if not isinstance(out.get(key), str) or not out.get(key):
            raise ConfigError(f"{where}: '{key}' is required")
    out['staleness_seconds'] = _num(out, 'staleness_seconds', where,
                                    least=0.0, least_open=True, required=True)
    out['mm_rate_max'] = _num(out, 'mm_rate_max', where, least=0.0,
                              least_open=True, most=1.0, required=True)
    out['equity_min'] = _num(out, 'equity_min', where, least=1.0, required=True)
    out['equity_drawdown_max'] = _num(out, 'equity_drawdown_max', where,
                                      least=0.0, least_open=True, most=1.0)
    out['re_alert_seconds'] = _num(out, 're_alert_seconds', where, least=0.0,
                                   least_open=True, required=True)
    # F25: every box has a disk, and a full one stops the log and the fleet
    # with it — the alarm is on by default, at 85% of the snapshot's volume
    out['disk_used_max'] = _num(out, 'disk_used_max', where, least=0.0,
                                least_open=True, most=1.0) or 0.85
    if 'assumes_sole_actor' not in cfg:
        raise ConfigError(f"{where}: 'assumes_sole_actor' is required — every "
                          'threshold assumes something about who else trades '
                          'this account; say it (F6)')
    out['assumes_sole_actor'] = _flag(out, 'assumes_sole_actor')
    # D32: per-bot bounds are opt-in — the account guards above are the
    # watch every bot is under; a bound is for the bot you choose to pin
    positions = out.setdefault('positions', {})
    if not isinstance(positions, dict):
        raise ConfigError(f"{where}: 'positions' maps a botid to "
                          '{min, max} — leave it out to bound no bot (D32)')
    for botid, lim in positions.items():
        if not isinstance(lim, dict) or 'min' not in lim or 'max' not in lim:
            raise ConfigError(f'{where}: positions.{botid} needs min and max')
        extra = set(lim) - {'min', 'max', 'ceiling_loose'}
        if extra:
            raise ConfigError(f'{where}: positions.{botid} has unknown '
                              f'keys {sorted(extra)}')
    return out


def peak_equity(prev, equity):
    """Monotone high-water. None is unknown, never a zero — v2's falsy
    sentinel silently disabled the drawdown check (exchange study M30)."""
    if equity is None:
        return prev
    if prev is None:
        return equity
    return max(prev, equity)


def evaluate(cfg, row, now, peak, recent=(), disk_used=None):
    """Pure: one snapshot row -> {stable_key: human_text}. F13: `recent` is
    the rows of the last `staleness_seconds` before `row`; an unknown
    equity is a breach only when EVERY one of them is unknown too — one
    rate-limited wallet read (E9) writes one null row, and the HL watchdog
    paged "could not read equity" and "recovered" five minutes apart on
    it (2026-10-05, four times a day at the two-second pace). The equity
    floor and drawdown are then judged on the newest KNOWN figure."""
    breaches = {}
    if disk_used is not None and disk_used >= cfg.get('disk_used_max', 0.85):
        # F25: the volume the snapshot lives on; a full disk ends the log
        # and the fleet's own state writes with it
        breaches['disk'] = (f"disk {disk_used:.0%} used >= "
                            f"{cfg.get('disk_used_max', 0.85):.0%} — logs and "
                            'state stop writing when it fills')
    if row is None:
        breaches['nosnap'] = 'no readable snapshot row'
        return breaches
    age = now - row['t']
    if age > cfg['staleness_seconds']:
        breaches['stale'] = f'snapshot is {age:.0f}s old'
    if row.get('mm_rate') is not None and row['mm_rate'] > cfg['mm_rate_max']:
        breaches['mmr'] = f"mm_rate {row['mm_rate']:.4f} > {cfg['mm_rate_max']}"
    window = [r for r in recent if r.get('t', 0) >= row['t'] - cfg['staleness_seconds']]
    equity = row['equity']
    if equity is None:
        known = [r['equity'] for r in window if r.get('equity') is not None]
        if known:
            equity = known[-1]                 # the blip's neighbour knows
        else:
            breaches['equity_unknown'] = (
                'the fleet could not read equity'
                + (f' for {cfg["staleness_seconds"]:.0f}s' if window else ''))
    if equity is not None and equity < cfg['equity_min']:
        breaches['equity'] = f"equity {equity:.0f} < {cfg['equity_min']:.0f}"
    dd_max = cfg.get('equity_drawdown_max')
    if dd_max and peak and equity is not None:
        dd = (peak - equity) / peak
        if dd > dd_max:
            breaches['drawdown'] = f'{dd:.1%} below the peak'
    for botid, lim in cfg['positions'].items():
        bot = row['bots'].get(botid)
        if bot is None:
            breaches[f'missing:{botid}'] = 'absent from the snapshot entirely'
            continue
        if not bot.get('alive', True) or bot.get('position') is None:
            continue          # F9: dead = visible (F4), not bounded; its own
                              # stand-down paged; the account guards still run
        size = abs(bot['position'])
        if not lim['min'] <= size <= lim['max']:
            breaches[f'pos:{botid}'] = (f"position {size:.10g} outside "
                                        f"[{lim['min']:.10g}, {lim['max']:.10g}]")
    return breaches


def decide(state, breaches, now, re_alert_seconds):
    """Pure transitions: page new keys, remind persisting ones on the
    interval, announce recoveries. Returns (pages, new_state)."""
    pages, new_state = [], {}
    for key, text in breaches.items():
        last = state.get(key)
        if last is None:
            pages.append(f'{key}: {text}')
            new_state[key] = now
        elif now - last >= re_alert_seconds:
            pages.append(f'still breached — {key}: {text}')
            new_state[key] = now
        else:
            new_state[key] = last
    for key in state:
        if key not in breaches:
            pages.append(f'recovered: {key}')
    return pages, new_state


def send_telegram(text):
    """Direct page — the watchdog is its own process; a send failure RAISES so
    state is never persisted over an undelivered page (it re-pages next tick,
    and the unit's OnFailure alarm fires)."""
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat = os.environ.get('TELEGRAM_CHAT_ID')
    if not (token and chat):
        print('WATCHDOG HAS NO TELEGRAM CREDENTIALS — this page reached '
              'NOBODY (journal only)', flush=True)
        return
    from .tg import payload, redact                   # F20: heading in bold
    data = urllib.parse.urlencode(payload(chat, text)).encode()
    try:
        urllib.request.urlopen(
            f'https://api.telegram.org/bot{token}/sendMessage', data,
            timeout=20).read()
    except OSError as e:                              # P3: never the token
        raise OSError(redact(f'telegram: {e} {getattr(e, "url", "") or ""}',
                             token)) from None


def disk_used(path):
    """F25: the used fraction of the volume `path` lives on; None when the
    path does not exist yet (a fleet that has not written)."""
    import shutil
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        u = shutil.disk_usage(p)
    except OSError:
        return None
    return (u.total - u.free) / u.total if u.total else None


def ping_deadman(url, get=None):
    """F24: the dead-man's switch — one GET to an outside uptime check at
    the end of every completed watchdog run, so a box that dies, or a
    watchdog that stops running, is noticed by something NOT on the box.
    Never raises: a failed ping is one printed line, never a failed run."""
    if not url:
        return None
    try:
        (get or urllib.request.urlopen)(url, timeout=10).read()
        return True
    except Exception as e:                                   # noqa: BLE001
        print(f'deadman ping failed: {type(e).__name__}: {e}', flush=True)
        return False


def main(argv):
    load_env()
    cfg = validate_watchdog(json.loads(Path(argv[0]).read_text()))
    now = time.time()
    row, recent = None, []
    snap = Path(cfg['snapshot'])
    if snap.exists():
        lines = snap.read_text().strip().splitlines()
        if lines:
            try:
                row = json.loads(lines[-1])
            except ValueError:
                row = None
            for ln in lines[-40:-1]:           # F13: the blip's neighbours
                try:
                    recent.append(json.loads(ln))
                except ValueError:
                    continue
    statep = Path(cfg['state'])
    healed = None
    try:
        state = json.loads(statep.read_text()) if statep.exists() else {}
        if not isinstance(state, dict):
            raise ValueError('not an object')
    except (OSError, ValueError) as e:
        # a torn state file must not leave the fleet unwatched until a
        # hand repairs it (audit 2026-10-05): start the memory again and
        # say so — the cost is one re-page per standing breach and a
        # drawdown peak that restarts at today's equity
        state, healed = {}, f'state file unreadable ({e}) — started again'
    peak = peak_equity(state.get('_peak'), row['equity'] if row else None)
    breaches = evaluate(cfg, row, now, peak, recent,
                        disk_used=disk_used(snap))
    if healed:
        print(f"[{cfg['tag']}] {healed}", flush=True)
        send_telegram(f"[{cfg['tag']}] {healed}")
    pages, new_alerts = decide(state.get('_alerts', {}), breaches, now,
                               cfg['re_alert_seconds'])
    for page in pages:                       # page BEFORE persisting: a failed
        print(f"[{cfg['tag']}] {page}", flush=True)   # page re-pages next tick
    if pages:
        send_telegram(f"[{cfg['tag']}] " + '\n'.join(pages))
    from .durable import write_json
    write_json(statep, {'_peak': peak, '_alerts': new_alerts}, indent=None)
    print(f"[{cfg['tag']}] {'BREACHED' if breaches else 'ok'} "
          f'({len(breaches)} breach(es))', flush=True)
    ping_deadman(os.environ.get('DEADMAN_URL'))     # F24: the run completed
    return 1 if breaches else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
