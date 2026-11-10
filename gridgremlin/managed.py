# Managed trades (SPEC L9–L13, D164): a perpetual position no bot covers,
# adopted by the owner and managed from the panel — a take profit and a
# stop set on the venue, a close of part or all.
#
#   python3 -m gridgremlin.managed <fleet.json> exits <venue:market:SYMBOL:side> [--tp P] [--sl P]
#   python3 -m gridgremlin.managed <fleet.json> close <venue:market:SYMBOL:side> [--qty Q]
#
# Adopting is a record only (`adopt`, the panel's): it places no order and
# sets no exit. Every write below re-reads the venue first and acts only on
# the UNCOVERED part of the side's position — the position minus what the
# bots on that side hold (`uncovered`). By I2 a bot owns its side's whole
# position (its holding is the venue's, read every cycle), so on a side any
# bot of the account runs nothing is uncovered and nothing is sent; the
# part is a whole side no bot runs. Perpetuals only (linear and inverse).
# The orders carry no bot's link (I1): no bot counts, amends or cancels them.
# Prints one JSON object; a refusal is {"refused": "..."}.
#
# D181: the command is Demo and Testnet only, as D164 had it. Where the
# account's fleet runs, the panel writes a REQUEST into the trade's record
# (`ask`) and the running fleet carries it out (`ManagedWatch`) with its own
# clients — no second signer beside it (X15b), and on Mainnet the only way:
# the fleet's start typed both halves (D25). The answer is written back
# into the record for the panel to read.
import json
import re
import sys
import time
from pathlib import Path

from common.files import write_json
from common.fmt import utc_stamp
from .durable import fleet_tag, locked, logs_dir

EPS = 1e-9
ENTRY_RTOL = 1e-6           # the readout's entry and the venue's, one field read twice
KEY_RE = re.compile(r'(bybit|hyperliquid):(linear|inverse):([A-Za-z0-9-]{1,40}):(long|short)')


class ManagedError(Exception):
    pass


def managed_path(fleet_path):
    """Beside the fleet's other logs: logs/managed-<fleet>.json."""
    return logs_dir(fleet_path) / f'managed-{fleet_tag(fleet_path)}.json'


def answers_path(fleet_path):
    """D181: the running fleet's answers to the panel's requests, one per
    trade, beside the records: logs/managed-answers-<fleet>.json."""
    return logs_dir(fleet_path) / f'managed-answers-{fleet_tag(fleet_path)}.json'


def key_of(venue, market, symbol, side):
    return f'{venue}:{market}:{symbol}:{side}'


def parse_key(key):
    """(venue, market, symbol, side) from a key, or a refusal: the argv the
    panel builds carries only a key of this shape, never a flag (P6)."""
    m = KEY_RE.fullmatch(str(key or ''))
    if not m:
        raise ManagedError(f'{key or "nothing"}: a managed trade is named venue:market:SYMBOL:side, '
                           'a perpetual (linear or inverse) — spot is not managed (D164)')
    return m.groups()


def uncovered(size, shares):
    """THE guard (L10): the part of a side's position no bot covers — the
    position less what each bot on that side holds, never below nothing.
    A share that cannot be known leaves nothing uncovered."""
    if any(s is None for s in shares):
        return 0.0
    return max(0.0, abs(size) - sum(abs(s) for s in shares))


def bot_shares(run, venue, market, symbol, side, size):
    """What the bots on a side hold: by I2 a bot owns its side's whole
    position (its holding is read from the venue every cycle), so each side
    a bot runs — a grid, DCA or trade row, or a Portfolio Bot's leg — is
    held whole by it; a side no bot runs, by none."""
    return [abs(size)] if (venue, market, symbol, side) in run else []


def load(path):
    try:
        got = json.loads(Path(path).read_text() or '{}')
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise ManagedError(f'{path}: unreadable ({e}) — fix or move it, deliberately') from e
    if not isinstance(got, dict) or any(not isinstance(v, dict) for v in got.values()):
        raise ManagedError(f'{path}: malformed — a map of managed trades')
    return got


def current(record, position):
    """Is this record the position's own: the same side, held, and its entry
    the one adopted (an add moves the entry; a close of part does not). A
    record of a position since closed never manages the next one."""
    if not record or not position or abs(position.get('size') or 0.0) <= EPS:
        return False
    a, b = record.get('entry'), position.get('entry')
    if not a or not b:
        return False
    return abs(a - b) <= ENTRY_RTOL * max(abs(a), abs(b))


def adopt(path, venue, position, run, by='owner'):
    """L9: the position becomes a managed trade — a record of what was
    adopted (size, entry, when, by whom) and no exits. Places no order:
    it takes no client. Refused where a bot runs the side (nothing there is
    uncovered) and for spot."""
    market, symbol, side = position['market'], position['symbol'], position['side']
    if market not in ('linear', 'inverse'):
        raise ManagedError(f'{symbol}: a {market} holding is not managed — perpetual '
                           'futures only for now (D164)')
    size = abs(position.get('size') or 0.0)
    free = uncovered(size, bot_shares(run, venue, market, symbol, side, size))
    if free <= EPS:
        raise ManagedError(f'{symbol} {side}: a bot of this account runs this side — by I2 its '
                           'whole position there is the bot\'s, so nothing is uncovered to manage')
    key = key_of(venue, market, symbol, side)
    with locked(path):
        got = load(path)
        if current(got.get(key), position):
            raise ManagedError(f'{symbol} {side}: already managed — set its exits on its page')
        # an earlier adoption's exits may still rest on the venue (the entry
        # moved with an add): kept, so the next set cancels them first
        kept = list((got.get(key) or {}).get('orders') or [])
        got[key] = {'adopted': utc_stamp(), 'by': str(by), 'size': free,
                    'entry': position.get('entry'), 'tp': None, 'sl': None, 'orders': kept}
        write_json(path, got)
    return key, got[key]


def drop(path, key):
    with locked(path):
        got = load(path)
        if got.pop(key, None) is not None:
            write_json(path, got)


def check_exits(side, mark, tp, sl):
    """A take profit beyond the mark on the trade's side, a stop behind it;
    None is no such exit. Refusals in words, before anything is sent."""
    long = side == 'long'
    for name, px, beyond in (('take profit', tp, True), ('stop', sl, False)):
        if px is None:
            continue
        if not px > 0:
            raise ManagedError(f'the {name} is a price above nothing')
        if not mark:
            raise ManagedError(f'the mark is not read, so the {name} cannot be checked; nothing was sent')
        ahead = px > mark if long else px < mark
        if ahead != beyond:
            where = ('above' if long == beyond else 'below')
            raise ManagedError(f'a {side}\'s {name} sits {where} the mark ({mark:.10g}); '
                               f'{px:.10g} is not')


def _held(client, adapter, market, symbol, side):
    entry = 'Buy' if side == 'long' else 'Sell'
    truth = client.read_symbol_truth(market, symbol)
    pos = truth['positions'].get(adapter.position_idx(entry, False) or 0) or {}
    if pos.get('side') and pos['side'] != entry:
        return 0.0, truth['mark'], None                 # the other side's: not this trade
    return abs(pos.get('size') or 0.0), truth['mark'], pos.get('avg_entry')


def _refuse_mainnet(client, allow_mainnet=False):
    """D164: the command is Demo and Testnet only — refused flatly on
    Mainnet, where no switch of the fleet file or flag of its own opens it.
    D181: a running fleet whose start passed both halves (D25) carries out
    a request with its own clients, and says so here."""
    if allow_mainnet and getattr(client, 'env', None) == 'mainnet':
        return
    if getattr(client, 'env', 'mainnet') not in ('demo', 'testnet'):
        raise ManagedError('a managed trade is Demo or Testnet only (D164) — this key reaches '
                           f'{getattr(client, "env", "an unknown network")}; nothing was sent')


def _ours(client, market, symbol, idx):
    book = getattr(client, 'stop_orders', None)
    if book is None:
        return set()
    return {o['orderId'] for o in book(market, symbol)
            if int(o.get('positionIdx') or 0) == idx
            and ('TakeProfit' in (o.get('stopOrderType') or '')
                 or 'StopLoss' in (o.get('stopOrderType') or ''))}


def set_exits(path, key, record, client, adapter, run, tp=None, sl=None, allow_mainnet=False):
    """L11: the take profit and the stop, on the venue, for the uncovered
    part only (re-read now), each sized to the uncovered part. Bybit: the
    exits set before by this trade are cancelled first (never two at once),
    then the venue's own set. Hyperliquid (L14): its trigger orders, the
    new placed BEFORE the old are cancelled — never a bare position; both
    reduce-only, so for a moment two stops can only close it once. Both
    None turns the exits off."""
    venue, market, symbol, side = parse_key(key)
    _refuse_mainnet(client, allow_mainnet)
    size, mark, avg = _held(client, adapter, market, symbol, side)
    if not current(record, {'size': size, 'entry': avg}):
        raise ManagedError(f'{symbol} {side}: the position is not the one adopted (closed, or its '
                           'entry moved with an add) — adopt it again first; nothing was sent')
    free = uncovered(size, bot_shares(run, venue, market, symbol, side, size))
    if free <= EPS:
        raise ManagedError(f'{symbol} {side}: nothing uncovered — a bot of this account runs this '
                           'side (I2); nothing was sent')
    check_exits(side, mark, tp, sl)
    qty = adapter.fmt_qty(free)
    if float(qty) <= 0:
        raise ManagedError(f'{free:.10g} rounds to nothing at the venue\'s step; nothing was sent')
    if venue == 'hyperliquid':
        placed = _hl_exits(client, adapter, symbol, side, qty, tp, sl, record.get('orders') or [])
        return _exits_kept(path, key, record, tp, sl, qty, placed, size, free, mark)
    idx = adapter.position_idx('Buy' if side == 'long' else 'Sell', False) or 0
    from .exchange.errors import VenueError
    for oid in record.get('orders') or []:
        try:
            client.cancel_order(market, symbol, oid)
        except VenueError as e:
            if e.kind != 'gone':
                raise
    before = _ours(client, market, symbol, idx)
    if tp is not None or sl is not None:
        client.set_trading_stop(
            market, symbol, idx,
            take_profit=adapter.fmt_price(tp) if tp is not None else None,
            stop_loss=adapter.fmt_price(sl) if sl is not None else None,
            tp_size=qty if tp is not None else None,
            sl_size=qty if sl is not None else None)
    placed = sorted(_ours(client, market, symbol, idx) - before)
    return _exits_kept(path, key, record, tp, sl, qty, placed, size, free, mark)


def _exits_kept(path, key, record, tp, sl, qty, placed, size, free, mark):
    with locked(path):
        got = load(path)
        rec = dict(got.get(key) or record, tp=tp, sl=sl, sized=float(qty), orders=placed,
                   exits_set=utc_stamp())
        got[key] = rec
        write_json(path, got)
    return {'key': key, 'held': size, 'uncovered': free, 'sized': float(qty), 'tp': tp, 'sl': sl,
            'mark': mark}


def _hl_exits(client, adapter, symbol, side, qty, tp, sl, old):
    """L14: Hyperliquid's exits are its trigger orders, placed first and
    the trade's old ones cancelled after: a stop is never lifted before its
    replacement rests. A placement refused part-way cancels what it placed
    and leaves the old standing (the refusal said, nothing half-done). The
    oids placed are returned for the record."""
    from .exchange.errors import VenueError
    close_side = 'Sell' if side == 'long' else 'Buy'
    placed, name = [], None
    try:
        for kind, px, name in (('sl', sl, 'stop'), ('tp', tp, 'take profit')):
            if px is not None:
                placed.append(client.place_exit('linear', symbol, close_side, qty,
                                                adapter.fmt_price(px), kind))
    except VenueError as e:
        for oid in placed:
            try:
                client.cancel_order('linear', symbol, oid)
            except VenueError:
                pass
        raise ManagedError(f'the exchange refused the {name}: {e} — the exits set before '
                           'still stand; nothing new rests') from e
    for oid in old:
        try:
            client.cancel_order('linear', symbol, oid)
        except VenueError as e:
            if e.kind != 'gone':
                raise ManagedError(f'the new exits rest, but an old one ({oid}) did not cancel: {e} — '
                                   'cancel it on the exchange') from e
    return [str(x) for x in placed]


def close_part(path, key, record, client, adapter, run, qty=None, allow_mainnet=False):
    """L12: one reduce-only market order for part or all of the uncovered
    part (re-read now), never more: a size above it is refused, nothing
    sent. All closed, the trade's record and its exits go."""
    venue, market, symbol, side = parse_key(key)
    _refuse_mainnet(client, allow_mainnet)
    size, mark, avg = _held(client, adapter, market, symbol, side)
    if not current(record, {'size': size, 'entry': avg}):
        raise ManagedError(f'{symbol} {side}: the position is not the one adopted (closed, or its '
                           'entry moved with an add) — adopt it again first; nothing was sent')
    free = uncovered(size, bot_shares(run, venue, market, symbol, side, size))
    if free <= EPS:
        raise ManagedError(f'{symbol} {side}: nothing uncovered — a bot of this account runs this '
                           'side (I2); nothing was sent')
    want = free if qty is None else float(qty)
    if not want > 0:
        raise ManagedError('the size to close is above nothing')
    if want > free * (1 + 1e-9):
        raise ManagedError(f'{want:.10g} is more than the uncovered {free:.10g} — '
                           'a trade closes only its own part; nothing was sent')
    q = adapter.fmt_qty(want)
    if float(q) <= 0 or not adapter.meets_minimum(float(q), mark or 0.0):
        raise ManagedError(f'{want:.10g} is below the venue\'s smallest order; nothing was sent')
    exit_ = 'Sell' if side == 'long' else 'Buy'
    client.place_market(market, symbol, exit_, q, adapter.position_idx(exit_, True) or 0,
                        reduce_only=True)
    left, mark, _ = _held(client, adapter, market, symbol, side)      # X4: re-read
    if left <= EPS:
        from .exchange.errors import VenueError
        for oid in record.get('orders') or []:
            try:
                client.cancel_order(market, symbol, oid)
            except VenueError as e:
                if e.ambiguous:      # E6e: unknown fate, kept as a timeout kept it
                    raise
        drop(path, key)
    return {'key': key, 'closed': size - left, 'left': left, 'mark': mark}


def command(fleet_path, action, key, tp=None, sl=None, qty=None):
    """The argv for the panel: the keys stay with the engine (X15's way)."""
    out = [sys.executable, '-m', 'gridgremlin.managed', str(fleet_path), action, key]
    for flag, v in (('--tp', tp), ('--sl', sl), ('--qty', qty)):
        if v is not None:
            out += [flag, f'{float(v):.10g}']
    return out


ASK_ACTIONS = ('exits', 'close')
ASK_STALE_S = 600           # an ask no fleet took in ten minutes is not carried out late


def ask(path, key, action, by='owner', tp=None, sl=None, qty=None, now=None):
    """L15 (D181): a request for the running fleet — one at a time per
    trade, answered in the record (`answer`, the same id). Returns its id.
    Places nothing itself: the panel holds no key."""
    import os
    if action not in ASK_ACTIONS:
        raise ManagedError(f'{action}: a request sets exits or closes')
    now = time.time() if now is None else now
    with locked(path):
        got = load(path)
        rec = got.get(key)
        if rec is None:
            raise ManagedError(f'{key}: not a managed trade of this account — adopt it first')
        pending = rec.get('ask')
        if pending and now - float(pending.get('t') or 0) < ASK_STALE_S:
            raise ManagedError('a request for this trade is still waiting for the fleet — '
                               'read its answer on the trade\'s page first')
        rid = f'{int(now * 1000)}-{os.urandom(4).hex()}'
        rec['ask'] = {'id': rid, 'action': action, 'by': str(by), 't': now,
                      'tp': tp, 'sl': sl, 'qty': qty}
        got[key] = rec
        write_json(path, got)
    return rid


def answer_of(fleet_path, key, rid):
    """The fleet's answer to request `rid`, or None while it waits."""
    a = load(answers_path(fleet_path)).get(key) or {}
    return a if a.get('id') == rid else None


def adapter_of(client, venue, market, symbol):
    """The instrument's adapter, read from the client the fleet holds."""
    if venue == 'hyperliquid':
        return client._adapter(symbol)
    from .adapters import adapter_for
    from .exchange.bybit.truth import parse_instrument
    return adapter_for(market, parse_instrument(market, client.instruments_info(market, symbol)))


class ManagedWatch:
    """L15 (D181): inside the running fleet. Notices the managed file
    changing (one stat a cycle), carries out each waiting request with the
    fleet's own client for its venue, and writes the answer back — a
    refusal in words, never a crash of the fleet. `allow_mainnet` is the
    fleet's start's: both halves typed (D25), else Mainnet is refused here
    as in the command. A request older than ASK_STALE_S is answered
    refused, never carried out late. Each write is said (the phone's
    'fleet' line), refusals as warnings."""

    def __init__(self, fleet_path, clients, notifier, allow_mainnet=False, clock=time.time,
                 run_of=None):
        self.fleet_path, self.clients, self.notifier = fleet_path, clients, notifier
        self.allow_mainnet, self.clock = bool(allow_mainnet), clock
        self.run_of = run_of or account_run
        self.path = managed_path(fleet_path)
        self.mtime = False

    def poll(self):
        try:
            m = self.path.stat().st_mtime
        except OSError:
            m = None
        if m == self.mtime:
            return
        self.mtime = m
        if m is None:
            return
        done = load(answers_path(self.fleet_path))
        for key, rec in load(self.path).items():
            a = rec.get('ask')
            if a and (done.get(key) or {}).get('id') != a.get('id'):
                self._carry(key, rec, a)
        try:
            self.mtime = self.path.stat().st_mtime        # our own answers are not news
        except OSError:
            self.mtime = None

    def _carry(self, key, rec, a):
        now = self.clock()
        try:
            venue, market, symbol, side = parse_key(key)
            if a.get('action') not in ASK_ACTIONS:
                raise ManagedError(f'{a.get("action")}: not a request this fleet carries out')
            if now - float(a.get('t') or 0) > ASK_STALE_S:
                raise ManagedError('the request waited past ten minutes — not carried out late; '
                                   'ask again if it still stands')
            client = self.clients.get(venue)
            if client is None:
                raise ManagedError(f'this fleet does not trade {venue}')
            adapter = adapter_of(client, venue, market, symbol)
            run = self.run_of(self.fleet_path)
            if a['action'] == 'exits':
                out = set_exits(self.path, key, rec, client, adapter, run, a.get('tp'), a.get('sl'),
                                allow_mainnet=self.allow_mainnet)
                said = (f'{symbol} {side}: exits set by {a.get("by")} — take profit '
                        f'{_or_none(a.get("tp"))}, stop {_or_none(a.get("sl"))}, for {out["sized"]:.10g} (D181)')
            else:
                out = close_part(self.path, key, rec, client, adapter, run, a.get('qty'),
                                 allow_mainnet=self.allow_mainnet)
                said = (f'{symbol} {side}: closed {out["closed"]:.10g} at market by {a.get("by")}, '
                        f'{out["left"]:.10g} left (D181)')
            self.notifier.event('fleet', 'managed', said)
        except Exception as e:                               # noqa: BLE001
            out = {'refused': str(e) if isinstance(e, ManagedError) else f'{type(e).__name__}: {e}'}
            self.notifier.event('warn', 'managed', f'{key}: request not carried out — {out["refused"]} (D181)')
        ap = answers_path(self.fleet_path)
        with locked(ap):
            done = load(ap)
            done[key] = dict(out, id=a.get('id'), t=now, action=a.get('action'))
            write_json(ap, done)
        with locked(self.path):
            got = load(self.path)
            if key in got and (got[key].get('ask') or {}).get('id') == a.get('id'):
                got[key].pop('ask', None)                    # closed whole, the record went already
                write_json(self.path, got)


def _or_none(x):
    return 'none' if x is None else f'{float(x):.10g}'


def account_run(fleet_path):
    """Every (venue, market, symbol, side) a bot runs on this fleet's account:
    this fleet's rows and trades, and those of each fleet file beside it on
    the same account. A file beside it that cannot be read refuses: it
    might run the side."""
    from .config import validate_fleet
    from .report import bot_markets
    from .trades import with_trades
    me = Path(fleet_path).resolve()
    raw = json.loads(me.read_text())
    account = raw.get('account') or 'default'
    run = set()
    for p in sorted(me.parent.glob('*.json')):
        try:
            other = json.loads(p.read_text()) if p.resolve() != me else raw
        except (OSError, ValueError) as e:
            if p.name.startswith('fleet.'):
                raise ManagedError(f'{p.name}: unreadable ({e}) — it may run this side') from e
            continue
        if not isinstance(other, dict) or 'bots' not in other \
                or (other.get('account') or 'default') != account:
            continue
        try:
            run |= bot_markets(with_trades(str(p), validate_fleet(other)))[0]
        except Exception as e:                               # noqa: BLE001
            raise ManagedError(f'{p.name}: {e} — it may run this side; nothing was sent') from e
    return run


def _client(fleet_path, venue):
    from common.env import load_env
    from .exchange.env import select_account
    from .config import validate_fleet
    load_env()
    fleet = validate_fleet(json.loads(Path(fleet_path).read_text()))
    select_account(fleet['account'])                      # H5: this account's keys
    return fleet


def main(argv):
    opts, rest, i = {}, [], 0
    while i < len(argv):
        if argv[i] in ('--tp', '--sl', '--qty') and i + 1 < len(argv):
            opts[argv[i][2:]] = argv[i + 1]
            i += 2
        else:
            rest.append(argv[i])
            i += 1
    if len(rest) != 3 or rest[1] not in ('exits', 'close') or '--allow-mainnet' in argv:
        print('usage: python3 -m gridgremlin.managed <fleet.json> exits|close '
              '<venue:market:SYMBOL:side> [--tp P] [--sl P] [--qty Q] (Demo and Testnet only)')
        return 2
    fleet_path, action, key = rest
    try:
        venue, market, symbol, side = parse_key(key)
        nums = {}
        for k, v in opts.items():
            try:
                nums[k] = float(v)
            except ValueError:
                raise ManagedError(f'--{k} is a number, like 71250.5') from None
        path = managed_path(fleet_path)
        record = load(path).get(key)
        if record is None:
            raise ManagedError(f'{symbol} {side}: not a managed trade of this account — adopt it first')
        fleet = _client(fleet_path, venue)
        run = account_run(fleet_path)
        if venue == 'hyperliquid':
            from .main import fleet_running
            if fleet_running(fleet_path, {'hyperliquid'}, fleet['account']):
                raise ManagedError('the fleet is running on this file — on Hyperliquid one process '
                                   'signs for the wallet at a time; stop the fleet first (X15b)')
            from .exchange.hyperliquid.adapters import HLPerpAdapter
            from .exchange.hyperliquid.truth import parse_instrument as hl_pi
            from .exchange.hyperliquid.venue import HLVenueClient
            client = HLVenueClient(allow_mainnet=False)
            _refuse_mainnet(client)
            adapter = HLPerpAdapter(hl_pi(client._entry(symbol)[1]))
        else:
            from .adapters import adapter_for
            from .exchange.bybit.client import WriteClient
            from .exchange.bybit.truth import parse_instrument
            client = WriteClient()
            _refuse_mainnet(client)
            adapter = adapter_for(market, parse_instrument(market, client.instruments_info(market, symbol)))
        if action == 'exits':
            out = set_exits(path, key, record, client, adapter, run, nums.get('tp'), nums.get('sl'))
        else:
            out = close_part(path, key, record, client, adapter, run, nums.get('qty'))
    except Exception as e:                                   # noqa: BLE001
        out = {'refused': str(e) if isinstance(e, ManagedError) else f'{type(e).__name__}: {e}'}
    print(json.dumps(out))
    return 1 if 'refused' in out else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
