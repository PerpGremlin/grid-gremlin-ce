# Reading commands over Telegram (SPEC F18, D61). The owner asks from the
# phone; the box answers from what it already keeps — the snapshot, the
# readout, the kept ledger, the digest, the logs. Read-only by construction:
# no venue write client is imported here, and nothing it runs writes either.
# Owner-only and fail-closed: no TELEGRAM_OWNER_ID, no answers. It is the
# channel's ONE consumer of getUpdates — it keeps the relay's offset file,
# and the relay (agentic phase) must not run beside it.
#   python3 -m gridgremlin.phone <fleet.json> ...        (systemd service)
#   python3 -m gridgremlin.phone <fleet.json> ... --ask "/pnl"   (local)
import json
import os
import sys
import time
from pathlib import Path

from .durable import write_json
from .report import card_total
from .exchange.env import load_env

STATE = Path('logs/relay.state.json')   # the channel's offset, shared on
                                        # purpose: one consumer, one place
LIMIT = 3900                            # Telegram refuses > 4096
READOUT_TTL = 60.0                      # a readout serves a minute of asks
WARM_EVERY = 60.0                       # the service keeps one warm: /pnl
                                        # answers at once, its age said
                                        # (owner, 2026-10-06: 20 s was long)
LOG_TAIL = 20_000_000                   # bytes of each log read: demo's cycle
                                        # lines fill 600 KB in minutes; its
                                        # [ship] events need about a day


def accepted(update, owner_id):
    """Pure: (text or None, reason). Owner-only, commands only."""
    msg = update.get('message') or {}
    if not owner_id:
        return None, 'TELEGRAM_OWNER_ID unset — refusing everything'
    if (msg.get('from') or {}).get('id') != owner_id:
        return None, 'not the owner'
    text = (msg.get('text') or '').strip()
    if not text.startswith('/'):
        return None, 'not a command'
    return text, 'command'


def chunks(text, limit=LIMIT):
    """Telegram's cap, split on line ends."""
    out, cur = [], ''
    for line in text.splitlines():
        while len(line) > limit:
            out.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) + 1 > limit:
            out.append(cur)
            cur = ''
        cur += ('\n' if cur else '') + line
    if cur:
        out.append(cur)
    return out or ['(empty)']


def _m(v):
    return '—' if v is None else f'{v:+,.2f}'


def _n(v):
    if v is None:
        return '—'
    return f'{v:,.0f}' if abs(v) >= 1000 else f'{v:,.6g}'


class Box:
    """What the commands read. Every source is a method, so specs stand a
    fake box in; the real one reads files and runs the readout."""

    def __init__(self, fleets):
        self.fleets = list(fleets)
        self._readouts = {}
        self.warm = False            # True: a background loop keeps them fresh

    def tag(self, fp):
        return Path(fp).stem.replace('fleet.', '', 1)

    def readout(self, fp):
        """The newest readout: while warm, whatever the loop last read (its
        age is said in the answer); otherwise one serves READOUT_TTL."""
        hit = self._readouts.get(fp)
        if hit and (self.warm or time.time() - hit[0] < READOUT_TTL):
            return hit[1]
        return self.refresh(fp)

    def refresh(self, fp):
        from .archive import run_readout
        contract = run_readout(fp)
        self._readouts[fp] = (time.time(), contract)
        return contract

    def keep_warm(self, every=WARM_EVERY, rounds=None):
        """The service's background loop: every fleet's readout, refreshed;
        a failed read keeps the last one (its age keeps growing, and says so)."""
        n = 0
        while rounds is None or n < rounds:
            for fp in self.fleets:
                try:
                    self.refresh(fp)
                except Exception as e:                   # noqa: BLE001
                    print(f'phone: readout {fp}: {e}', file=sys.stderr,
                          flush=True)
            n += 1
            if rounds is None or n < rounds:
                time.sleep(every)

    def snapshot(self, fp):
        from .archive import last_snapshot
        return last_snapshot(fp) or {}

    def watchdog(self, fp):
        """The fleet's watchdog thresholds and remembered peak."""
        try:
            fleet = json.loads(Path(fp).read_text())
            wd = json.loads(Path(fleet['watchdog']).read_text())
            state = {}
            if wd.get('state') and Path(wd['state']).exists():
                state = json.loads(Path(wd['state']).read_text())
            return wd, state
        except (OSError, ValueError, KeyError, TypeError):
            return {}, {}

    def digest(self):
        from .digest import build
        text, _ = build(self.fleets)          # dry: the place never moves
        return text

    def log_lines(self, fp):
        """The [ship] events in the newest LOG_TAIL bytes of the fleet's log."""
        from .digest import log_path
        try:
            with open(log_path(fp), 'rb') as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - LOG_TAIL))
                return [l.decode(errors='replace').rstrip('\n') for l in f
                        if l.startswith(b'[ship]')]
        except OSError:
            return []


def _age(contract):
    """How old a readout's figures are, said in the answer."""
    ms = contract.get('generated_ms')
    if not ms:
        return ''
    s = max(0, time.time() - ms / 1000)
    return f' (read {s:.0f}s ago)' if s < 120 else f' (read {s / 60:.0f} min ago)'


def _bots(box):
    """[(fleet, botid)] across the box, in fleet order."""
    out = []
    for fp in box.fleets:
        snap = box.snapshot(fp)
        out += [(fp, b) for b in (snap.get('bots') or {})]
    return out


def _pick(box, word):
    """A bot named in part, case-blind: 'btc' -> every BTC bot; an exact
    botid wins outright."""
    word = (word or '').lower()
    every = _bots(box)
    exact = [x for x in every if x[1].lower() == word]
    return exact or [x for x in every if word in x[1].lower()]


def cmd_help(box, args):
    return '\n'.join([
        '🧌 read-only — nothing here changes anything',
        '/status — fleets, bots alive, snapshot age, equity',
        '/pnl [bot] — P&L now and kept history, per exchange or one bot',
        '/today — the day so far (the digest, unsent)',
        '/positions — every holding: size, average, price, open P&L',
        '/orders [bot] — resting and waiting orders',
        '/grids — where the price sits in each grid',
        '/rounds — every DCA bot: holding, average, open P&L',
        '/risk — equity, margin rate, drawdown against the watchdog',
        '/alerts [n] — the newest warnings and stand-downs',
        '/log <bot> [n] — a bot\'s newest events',
        '/market [n] — the newest market readings (D67); n for a later part',
        'a bot can be named in part: /pnl btc'])


def cmd_status(box, args):
    out = []
    now = time.time()
    for fp in box.fleets:
        snap = box.snapshot(fp)
        bots = snap.get('bots') or {}
        dead = [b for b, v in bots.items() if v.get('alive') is False]
        age = now - snap['t'] if snap.get('t') else None
        line = f'{box.tag(fp)}: '
        if age is None or age > 600:
            line += '⚠️ no fresh snapshot — is the fleet running?'
        else:
            line += f'{len(bots) - len(dead)}/{len(bots)} alive · ' \
                    f'snapshot {age:.0f}s old'
            if snap.get('equity') is not None:
                line += f" · equity {snap['equity']:,.0f}"
        if dead:
            line += '\n  stood down: ' + ', '.join(dead)
        out.append(line)
    return '\n'.join(out)


def cmd_pnl(box, args):
    picked = _pick(box, args[0]) if args else None
    out = []
    for fp in box.fleets:
        if picked is not None and not any(p[0] == fp for p in picked):
            continue
        c = box.readout(fp)
        bots, sf = c.get('bots') or {}, c.get('since_first') or {}
        names = [p[1] for p in picked if p[0] == fp] if picked else list(bots)
        now_t, kept_t, out_n, rows = 0.0, 0.0, 0, []
        for b in names:
            v, k = bots.get(b), sf.get(b)
            t = (card_total(v)                                  # D63
                 if v and v.get('realized') is not None else None)
            kt = (card_total(k)
                  if k and k.get('whole', True) and k.get('behind') is None
                  and k.get('realized') is not None else None)
            now_t += t or 0.0
            if kt is None and k:
                out_n += 1
            kept_t += kt or 0.0
            rows.append(f'  {b}: now {_m(t)} · kept {_m(kt)}')
        out.append(f'{box.tag(fp)}: now {_m(now_t)} · kept {_m(kept_t)}'
                   + (f' ({out_n} not whole)' if out_n else '') + _age(c))
        if picked:
            out += rows
    if picked is not None and not picked:
        return f'no bot matches "{args[0]}" — /status lists them'
    return '\n'.join(out) + '\n(now = since each bot was last flat; ' \
                            'kept = its whole kept history)'


def cmd_positions(box, args):
    out = []
    for fp in box.fleets:
        c = box.readout(fp)
        rows = []
        for b, v in (c.get('bots') or {}).items():
            if not v or abs(v.get('position') or 0.0) < 1e-12:
                continue
            rows.append(f"  {b}: {_n(abs(v['position']))} @ "
                        f"{_n(v.get('avg_cost'))} · price {_n(v.get('mark'))}"
                        f" · open {_m(v.get('unreal_at_mark'))}")
        out.append(f'{box.tag(fp)}{_age(c)}:' + ('\n' + '\n'.join(rows) if rows
                                                 else ' nothing held'))
    return '\n'.join(out)


def cmd_orders(box, args):
    picked = _pick(box, args[0]) if args else _bots(box)
    if not picked:
        return f'no bot matches "{args[0]}"'
    out = []
    for fp, b in picked:
        o = ((box.snapshot(fp).get('bots') or {}).get(b) or {}).get('orders')
        if not o:
            out.append(f'{b}: no orders said')
            continue
        r, w = o.get('resting') or {}, o.get('waiting') or {}
        out.append(f"{b}: resting {r.get('buys', 0)} buys / "
                   f"{r.get('sells', 0)} sells · waiting {w.get('buys', 0)}"
                   f" / {w.get('sells', 0)}")
    return '\n'.join(out)


def cmd_grids(box, args):
    out = []
    for fp in box.fleets:
        c = box.readout(fp)
        for b, rng in (c.get('ranges') or {}).items():
            mark = (c['bots'].get(b) or {}).get('mark')
            lo, hi = rng['lower'], rng['upper']
            if mark is None:
                where = 'price unknown'
            elif mark < lo or mark > hi:
                where = '⚠️ OUTSIDE (' + ('below' if mark < lo else 'above') + ')'
            else:
                where = f'{(mark - lo) / (hi - lo):.0%} up the range'
            out.append(f'{b}: {_n(lo)}–{_n(hi)} · price {_n(mark)} · {where}')
    return '\n'.join(out) or 'no grids'


def cmd_rounds(box, args):
    out = []
    for fp in box.fleets:
        c = box.readout(fp)
        alive = box.snapshot(fp).get('bots') or {}
        for b, t in (c.get('terms') or {}).items():
            if t.get('strategy') != 'martingale':
                continue
            v = c['bots'].get(b) or {}
            held = abs(v.get('position') or 0.0)
            if (alive.get(b) or {}).get('alive') is False and not held:
                out.append(f'{b}: stood down')      # a finished bot is not
                continue                            # between rounds (AVAX, D41)
            out.append(f'{b}: ' + (f"holding {_n(held)} @ {_n(v.get('avg_cost'))}"
                                   f" · price {_n(v.get('mark'))} · open "
                                   f"{_m(v.get('unreal_at_mark'))}"
                                   if held else 'flat, between rounds'))
    return '\n'.join(out) or 'no DCA bots'


def cmd_risk(box, args):
    out = []
    for fp in box.fleets:
        snap = box.snapshot(fp)
        wd, state = box.watchdog(fp)
        eq, mm = snap.get('equity'), snap.get('mm_rate')
        line = f'{box.tag(fp)}: equity {_n(eq)}'
        try:                                         # R19: the owner's measure
            from .report import leverage_lines
            lev = [x for pair in leverage_lines(box.readout(fp)).values()
                   for x in pair]
        except Exception:                            # noqa: BLE001
            lev = None
        if wd.get('equity_min') is not None:
            line += f" (floor {_n(wd['equity_min'])})"
        if mm is not None:
            line += f' · margin rate {mm:.1%}'
            if wd.get('mm_rate_max') is not None:
                line += f" (max {wd['mm_rate_max']:.0%})"
        peak = state.get('_peak')
        if peak and eq is not None:
            line += f' · {(peak - eq) / peak:.1%} below peak'
            if wd.get('equity_drawdown_max'):
                line += f" (max {wd['equity_drawdown_max']:.0%})"
        for x in lev or ():
            line += f'\n  {x}'
        breached = [k for k in state if not k.startswith('_')]
        if breached:
            line += '\n  ⚠️ watchdog breached: ' + ', '.join(breached)
        out.append(line)
    return '\n'.join(out)


def cmd_today(box, args):
    return box.digest()


def _ship(box, keep, n):
    out = []
    for fp in box.fleets:
        lines = [l for l in box.log_lines(fp) if l.startswith('[ship]')
                 and keep(l)]
        out += [f'{box.tag(fp)} {l[7:]}' for l in lines[-n:]]
    return out


def cmd_alerts(box, args):
    n = int(args[0]) if args and args[0].isdigit() else 15
    lines = _ship(box, lambda l: l.startswith(('[ship] warn', '[ship] kill',
                                               '[ship] margin')), n)
    return '\n'.join(lines) or 'nothing said'


def cmd_market(box, args):
    """D67: the kept readings, as the session report says them — part n of
    a report too long for one message."""
    from .market import latest, report
    row = latest()
    if row is None:
        return 'no market readings yet — the hourly reading has not run'
    msgs = report(row)
    n = int(args[0]) if args and args[0].isdigit() else 1
    n = min(max(n, 1), len(msgs))
    text = msgs[n - 1]
    if len(msgs) > 1:
        text += f'\n(part {n} of {len(msgs)}' + (f' — /market {n + 1})' if n < len(msgs) else ')')
    return text


def cmd_log(box, args):
    if not args:
        return 'which bot? /log btc'
    picked = _pick(box, args[0])
    if not picked:
        return f'no bot matches "{args[0]}"'
    n = int(args[1]) if len(args) > 1 and args[1].isdigit() else 15
    names = {b for _, b in picked}
    lines = _ship(box, lambda l: any(f' {b}:' in l for b in names), n)
    return '\n'.join(lines) or 'nothing said'


COMMANDS = {'help': cmd_help, 'start': cmd_help, 'status': cmd_status,
            'pnl': cmd_pnl, 'today': cmd_today, 'positions': cmd_positions,
            'orders': cmd_orders, 'grids': cmd_grids, 'rounds': cmd_rounds,
            'risk': cmd_risk, 'alerts': cmd_alerts, 'log': cmd_log,
            'market': cmd_market}


def answer(box, text):
    """One command -> its reply. Never raises: a broken source is said."""
    parts = text[1:].split()
    # a phone keyboard adds punctuation: '/risk.' is /risk (owner, 2026-10-06)
    name = (parts[0].split('@')[0].lower().rstrip('.,!?;:') if parts else '')
    fn = COMMANDS.get(name)
    if fn is None:
        return f'unknown command /{name} — /help lists them'
    try:
        return fn(box, parts[1:])
    except Exception as e:                           # noqa: BLE001
        return f'/{name} could not read: {type(e).__name__}: {e}'


class Telegram:
    def __init__(self, token):
        self.token = token
        self.base = f'https://api.telegram.org/bot{token}'

    def _call(self, method, body, timeout):
        import urllib.request
        from .tg import redact                        # P3: never the token
        req = urllib.request.Request(
            f'{self.base}/{method}', data=json.dumps(body).encode(),
            headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except OSError as e:
            raise OSError(redact(f'telegram: {e} {getattr(e, "url", "") or ""}',
                                 self.token)) from None

    def updates(self, offset, wait=50):
        return self._call('getUpdates', {'offset': offset, 'timeout': wait,
                                         'allowed_updates': ['message']},
                          wait + 15).get('result', [])

    def send(self, chat, text):
        from .tg import payload                       # F20: heading in bold
        self._call('sendMessage', payload(chat, text), 20)


def poll_once(tg, box, owner, chat, state_path=STATE, wait=50):
    """One long poll. The offset is written BEFORE any answer is sent: a
    crash costs an unanswered question, never a question answered twice
    into a loop. Returns how many commands were answered."""
    try:
        offset = json.loads(Path(state_path).read_text()).get('offset', 0)
    except (OSError, ValueError):
        offset = 0
    got = tg.updates(offset, wait)
    if not got:
        return 0
    write_json(state_path, {'offset': max(u['update_id'] for u in got) + 1,
                            'last_run': int(time.time())})
    n = 0
    for u in got:
        text, _ = accepted(u, owner)
        if text is None:
            continue
        for part in chunks(answer(box, text)):
            tg.send(chat, part)
        n += 1
    return n


def main(argv):
    ask = None
    if '--ask' in argv:
        i = argv.index('--ask')
        ask = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    if not argv:
        print('usage: python3 -m gridgremlin.phone <fleet.json> ... '
              '[--ask "/pnl"]')
        return 2
    load_env()
    box = Box(argv)
    if ask:
        print(answer(box, ask))
        return 0
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat = os.environ.get('TELEGRAM_CHAT_ID')
    try:
        owner = int(os.environ.get('TELEGRAM_OWNER_ID') or 0)
    except ValueError:
        owner = 0
    if not (token and chat and owner):
        print('phone: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID and '
              'TELEGRAM_OWNER_ID are all required — refusing (fail closed)',
              file=sys.stderr)
        return 1
    tg = Telegram(token)
    import threading
    box.warm = True
    threading.Thread(target=box.keep_warm, daemon=True).start()
    while True:
        try:
            poll_once(tg, box, owner, chat)
        except OSError as e:
            print(f'phone: {type(e).__name__}: {e} — again in 10s',
                  file=sys.stderr, flush=True)
            time.sleep(10)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
