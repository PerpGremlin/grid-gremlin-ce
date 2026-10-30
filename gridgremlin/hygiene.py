# The box hygiene check (SPEC F35–F38, D155). Once a day on each box: every
# process outside a known service (a stray: left in an ssh session, a
# reparented loop), each service's memory kept day by day (a leak is steady
# growth), and the box's own memory. It reports and never kills: the report
# is a file, the digest says what is off, and the phone hears only a box near
# its memory limit (D60).
#   python3 -m gridgremlin.hygiene run --box <name>     # read, record, report
#   python3 -m gridgremlin.hygiene page <report.json> ...   # a near-full box pages
#   python3 -m gridgremlin.hygiene show                 # what the digest would say
import json
import os
import re
import sys
import time
from pathlib import Path

from common.files import write_json

ROOT = Path('logs/hygiene')
# Every threshold, in one place (the RUNBOOK and DECISIONS say them).
LIMITS = {
    'leak_days': 7,          # a service's last 7 daily readings are the window,
    'leak_rises': 5,         # rising on at least 5 of its 6 steps,
    'leak_growth': 0.25,     # up a quarter or more from the first to the last,
    'leak_floor_mib': 32,    # and by 32 MiB at least: a small service's noise is no leak
    'mem_low': 0.20,         # MemAvailable under a fifth of MemTotal: said in the digest
    'mem_page': 0.10,        # under a tenth: the phone (F37)
    'page_fresh_s': 7200,    # only a report this new pages; an old one is the digest's
    'stale_s': 36 * 3600,    # a report older than this is said as old
    'keep_days': 30,         # the history kept
}
PF_KTHREAD = 0x00200000
BOX = re.compile(r'^[a-z][a-z0-9-]{0,15}$')
MIB = 1 << 20


def cgroup_path(text):
    """The unified hierarchy's path from /proc/<pid>/cgroup ('0::/…'); on a
    hybrid box, systemd's own named hierarchy."""
    named = ''
    for line in text.splitlines():
        if line.startswith('0::'):
            return line[3:]
        if ':name=systemd:' in line:
            named = line.split(':name=systemd:', 1)[1]
    return named


def unit_of(path):
    """The innermost systemd unit a cgroup path sits in, and the path up to
    it: user@1000.service/app.slice/x.service is x.service; a process loose
    under a slice has none."""
    parts = [p for p in path.split('/') if p]
    for i in range(len(parts) - 1, -1, -1):
        if parts[i].endswith(('.service', '.scope')):
            return parts[i], '/' + '/'.join(parts[:i + 1])
    return None, None


def is_known(unit):
    """F35: a service is known; so is init.scope (pid 1, and each user's
    own service manager). A session scope, any other scope, and no unit at
    all are strays."""
    return bool(unit) and (unit.endswith('.service') or unit == 'init.scope')


# An ssh login's own processes (the daemon's per-session child: `sshd`, or
# `sshd-session` from OpenSSH 9.8) are plumbing, not a job someone left: a
# standing `ssh -N` tunnel is one every night. Matched by name alone, never
# by the scope they share with the session's real jobs.
SSH_PLUMBING = ('sshd', 'sshd-session')


def is_plumbing(p):
    """A session's ssh daemon process — not a stray (the owner, 2026-10-30)."""
    return p['comm'] in SSH_PLUMBING


def _starts_the_check(p):
    """A `systemctl … start …hygiene…` typed in a login: it started this
    run through its unit, so it and its chain are the run's own."""
    return p['comm'] == 'systemctl' and 'hygiene' in p['cmd']


def read_procs(proc='/proc'):
    """Every process the reader may see: pid, parent, name, command line,
    cgroup path, whether it is a kernel thread. A process that ended
    mid-read, or that /proc hides, is skipped."""
    out = []
    for d in Path(proc).iterdir():
        if not d.name.isdigit():
            continue
        try:
            stat = (d / 'stat').read_text()
            cg = (d / 'cgroup').read_text()
        except OSError:
            continue
        try:
            cmd = (d / 'cmdline').read_bytes()
        except OSError:
            cmd = b''
        lp, rp = stat.find('('), stat.rfind(')')
        rest = stat[rp + 2:].split()
        try:
            pid, ppid, flags = int(d.name), int(rest[1]), int(rest[6])
        except (IndexError, ValueError):
            continue                                    # a stat line we cannot read
        out.append({'pid': pid, 'ppid': ppid, 'comm': stat[lp + 1:rp],
                    'cmd': cmd.replace(b'\0', b' ').decode(errors='replace').strip()[:80],
                    'cgroup': cgroup_path(cg),
                    'kthread': bool(flags & PF_KTHREAD) or 2 in (pid, ppid)})
    return out


def strays(procs, me=None):
    """F35: every process outside a known service. Kernel threads are not
    processes of ours; the check itself and its ancestors are left out (run
    by hand, that chain is the owner's own login), and so is a `systemctl`
    that started its unit, with that systemctl's own ancestors; an ssh
    login's daemon processes are plumbing (`is_plumbing`). Anything else in
    a session — a loop, a job sent to the background — is a stray."""
    me = os.getpid() if me is None else me
    parent = {p['pid']: p['ppid'] for p in procs}
    mine = set()
    for start in [me] + [p['pid'] for p in procs if _starts_the_check(p)]:
        at = start
        while at and at not in mine:
            mine.add(at)
            at = parent.get(at)
    out = []
    for p in procs:
        if p['kthread'] or p['pid'] in mine or is_plumbing(p):
            continue
        unit, _ = unit_of(p['cgroup'])
        if not is_known(unit):
            out.append({'pid': p['pid'], 'comm': p['comm'], 'cmd': p['cmd'],
                        'unit': unit or p['cgroup'] or 'no unit'})
    return sorted(out, key=lambda s: s['pid'])


def service_memory(procs, cgroup_root='/sys/fs/cgroup'):
    """F36: each service that holds a process, by its cgroup path, and its
    memory.current in bytes (a cgroup v1 box has none: left out)."""
    out = {}
    for p in procs:
        unit, path = unit_of(p['cgroup'])
        if not (unit and unit.endswith('.service')) or path in out:
            continue
        try:
            out[path] = int((Path(cgroup_root + path) / 'memory.current').read_text())
        except (OSError, ValueError):
            continue
    return out


def meminfo(proc='/proc'):
    """F37: MemTotal and MemAvailable, in bytes."""
    got = {}
    for line in (Path(proc) / 'meminfo').read_text().splitlines():
        k, _, v = line.partition(':')
        if k in ('MemTotal', 'MemAvailable'):
            got[k] = int(v.split()[0]) * 1024
    return {'total': got['MemTotal'], 'available': got['MemAvailable']}


def record(history, day, readings, keep=LIMITS['keep_days']):
    """The day's readings into the history (a second run the same day
    replaces the first); the oldest days beyond `keep` are dropped."""
    days = dict(history.get('days') or {})
    days[day] = readings
    return {'days': {d: days[d] for d in sorted(days)[-keep:]}}


def growing(history, limits=LIMITS):
    """F36: the services whose memory grew steadily — over their last
    `leak_days` readings, rising on at least `leak_rises` steps and up by
    `leak_growth` and `leak_floor_mib` from the first to the last. A
    service with fewer readings is not judged yet; one restarted inside the
    window falls and rises again, and is not a leak until it climbs again."""
    days = history.get('days') or {}
    if not days:
        return []
    out = []
    for path in sorted(days[max(days)]):
        series = [days[d][path] for d in sorted(days) if path in days[d]][-limits['leak_days']:]
        if len(series) < limits['leak_days'] or series[0] <= 0:
            continue
        rises = sum(b > a for a, b in zip(series, series[1:]))
        grew = series[-1] - series[0]
        if (rises >= limits['leak_rises'] and grew / series[0] >= limits['leak_growth']
                and grew >= limits['leak_floor_mib'] * MIB):
            out.append({'service': path, 'first': series[0], 'last': series[-1],
                        'days': len(series)})
    return out


def check(box, now, history, proc='/proc', cgroup_root='/sys/fs/cgroup', me=None,
          limits=LIMITS):
    """One run: the report and the history it leaves."""
    procs = read_procs(proc)
    mem = service_memory(procs, cgroup_root)
    history = record(history, time.strftime('%Y-%m-%d', time.gmtime(now)), mem,
                     limits['keep_days'])
    return {'box': box, 't': now, 'mem': meminfo(proc), 'strays': strays(procs, me),
            'leaks': growing(history, limits), 'services': len(mem), 'seen': len(procs),
            # hidepid: without pid 1 the reader sees its own user's processes only
            'whole': any(p['pid'] == 1 for p in procs)}, history


def _name(path):
    """A service as the owner knows it: its unit, and its user when it is
    one of a user's own (user@1000.service/…)."""
    parts = path.strip('/').split('/')
    user = next((p[5:-8] for p in parts if p.startswith('user@') and p.endswith('.service')
                 and p != parts[-1]), None)
    return parts[-1] + (f' (user {user})' if user else '')


def problems(report, now, limits=LIMITS):
    """What is off in one report, each a short phrase; none when clean."""
    out = []
    if now - report['t'] > limits['stale_s']:
        out.append(f"report {(now - report['t']) / 3600:.0f} h old — is its timer running?")
    s = report['strays']
    if s:
        named = ', '.join(f"{x['comm']} {x['pid']} ({x['unit']})" for x in s[:4])
        out.append(f'{len(s)} stray process{"es" if len(s) > 1 else ""}: {named}'
                   + (f' +{len(s) - 4} more' if len(s) > 4 else '')
                   + ('' if report.get('whole', True) else ' (sees its own user only)'))
    for g in report['leaks']:
        out.append(f"growing: {_name(g['service'])} {g['first'] / MIB:,.0f} → "
                   f"{g['last'] / MIB:,.0f} MiB over {g['days']} days")
    m = report['mem']
    if m['total'] and m['available'] / m['total'] < limits['mem_low']:
        out.append(f"memory {m['available'] / m['total']:.0%} available "
                   f"({m['available'] / MIB:,.0f} of {m['total'] / MIB:,.0f} MiB)")
    return out


def reports(root=ROOT):
    """Every box's report beside this box's own (`<box>.json`)."""
    return sorted(p for p in Path(root).glob('*.json') if not p.name.endswith('.history.json'))


def digest_lines(root=None, now=None):
    """F38: the digest's lines — one per box with something off; none when
    every report is clean, or when no box has reported at all."""
    now = time.time() if now is None else now
    out = []
    for p in reports(ROOT if root is None else root):
        try:
            r = json.loads(p.read_text())
            said = problems(r, now)
            box = r['box']
        except (OSError, ValueError, KeyError, TypeError) as e:
            said, box = [f'unreadable — {e}'], p.stem
        if said:
            out.append(f'🧹 box hygiene · {box}: ' + ' · '.join(said))
    return out


def page_text(report, now, limits=LIMITS):
    """F37: the one page — a fresh report of a box near its memory limit;
    None otherwise (a stray or a leak is the digest's, D60)."""
    m = report['mem']
    if now - report['t'] > limits['page_fresh_s'] or not m['total']:
        return None
    share = m['available'] / m['total']
    if share >= limits['mem_page']:
        return None
    return (f"box memory · {report['box']}: {share:.0%} available "
            f"({m['available'] / MIB:,.0f} of {m['total'] / MIB:,.0f} MiB) — near its limit; "
            f"python3 -m gridgremlin.hygiene show names what grew")


def _opt(argv, name, default):
    return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else default


def main(argv, send=None):
    cmd = argv[0] if argv else ''
    root = Path(_opt(argv, '--root', str(ROOT)))
    now = time.time()
    if cmd == 'run':
        box = _opt(argv, '--box', '')
        if not BOX.match(box):
            print('--box <name>: a short lower-case name, e.g. trading')
            return 2
        hist_path = root / f'{box}.history.json'
        try:
            history = json.loads(hist_path.read_text())
        except (OSError, ValueError):
            history = {}
        report, history = check(box, now, history, _opt(argv, '--proc', '/proc'),
                                _opt(argv, '--cgroup', '/sys/fs/cgroup'))
        write_json(hist_path, history)
        write_json(root / f'{box}.json', report)
        said = problems(report, now)
        print(f'{box}: ' + (' · '.join(said) if said else
                            f"clean — {report['seen']} processes, {report['services']} services"))
        return 0
    if cmd == 'page':
        texts = []
        for f in argv[1:]:
            if f.startswith('--'):
                break
            try:
                t = page_text(json.loads(Path(f).read_text()), now)
            except (OSError, ValueError, KeyError, TypeError):
                continue                    # a missing box is the digest's, never a page
            if t:
                texts.append(t)
        if texts:
            if send is None:
                from common.env import load_env
                from common.telegram import send_telegram as send
                load_env()
            send('🧌 ' + '\n'.join(texts))
        print('\n'.join(texts) or 'no box near its memory limit')
        return 0
    if cmd == 'show':
        lines = digest_lines(root, now)
        print('\n'.join(lines) if lines else 'every box clean')
        for p in reports(root):
            try:
                r = json.loads(p.read_text())
            except (OSError, ValueError):
                continue
            for s in r.get('strays', []):
                print(f"  {r['box']} stray {s['pid']} {s['unit']}: {s['cmd'] or s['comm']}")
        return 0
    print('usage: python3 -m gridgremlin.hygiene run --box <name> | page <report.json> ... | show')
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
