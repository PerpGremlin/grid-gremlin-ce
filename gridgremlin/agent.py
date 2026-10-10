# The agent's limits and its intents (SPEC J3, D80/D81). An agent fleet's
# file carries an `agent` block the model can never change — only the
# owner's merged main does — and every intent the model sends is checked
# against it here before it becomes a trade (D81's trades file, through the
# same validator as the owner's), or, in paper mode, is only checked and
# logged. Every intent is logged with its verdict, reason and confidence:
# the record the experiment is scored from (J5). Pure but for the reads of
# the fleet's own files.
import json
import time
from pathlib import Path

from .config import ConfigError, _flag, _num, _refuse, _reject_unknown

AGENT_KEYS = ('markets', 'max_notional', 'max_gross', 'max_leverage', 'max_loss_day',
              'max_intents_hour', 'min_stop_pct', 'max_stop_pct', 'session_utc', 'paper')
INTENT_KEYS = ('market', 'side', 'size_quote', 'leverage', 'entry', 'stop_pct', 'tp_pct',
               'trail_pct', 'trail_from_pct', 'reason', 'confidence')


def validate_agent(block, where='fleet.agent'):
    """The owner's limits for the agent, all required but `paper` (default on)
    and `session_utc` (default all day). Refuses the shapeless like every
    config: a limit the owner meant to set must never silently be absent."""
    if not isinstance(block, dict):
        _refuse(f'{where}: an object of the agent\'s limits')
    _reject_unknown(block, AGENT_KEYS, where)
    out = dict(block)
    mk = block.get('markets')
    if not isinstance(mk, list) or not mk or not all(isinstance(m, str) and m for m in mk):
        _refuse(f"{where}: 'markets' lists the perps the agent may trade, like ['BTCUSDT']")
    out['markets'] = [m.upper() for m in mk]
    for key, least in (('max_notional', 0.0), ('max_gross', 0.0), ('max_loss_day', 0.0)):
        out[key] = _num(block, key, where, least=least, least_open=True, required=True)
    out['max_leverage'] = _num(block, 'max_leverage', where, least=1.0, most=125.0, required=True)
    out['max_intents_hour'] = _num(block, 'max_intents_hour', where, least=1, integer=True, required=True)
    out['min_stop_pct'] = _num(block, 'min_stop_pct', where, least=0.0, least_open=True, most=1.0, required=True)
    out['max_stop_pct'] = _num(block, 'max_stop_pct', where, least=0.0, least_open=True, most=1.0, required=True)
    if out['min_stop_pct'] > out['max_stop_pct']:
        _refuse(f"{where}: 'min_stop_pct' is above 'max_stop_pct'")
    if out['max_gross'] < out['max_notional']:
        _refuse(f"{where}: 'max_gross' below 'max_notional' — no trade could ever open")
    s = block.get('session_utc', [0, 24])
    if (not isinstance(s, list) or len(s) != 2 or not all(isinstance(h, (int, float)) for h in s)
            or not 0 <= s[0] < s[1] <= 24):
        _refuse(f"{where}: 'session_utc' is [start, end] hours UTC, start before end, like [0, 24]")
    out['session_utc'] = [float(s[0]), float(s[1])]
    out['paper'] = True if 'paper' not in block else _flag(block, 'paper')
    return out


def check_intent(intent, limits, state, now_s):
    """Pure: the intent against the limits and the agent's state now —
    {'open': [{botid, notional}], 'intents_last_hour': n, 'day_loss': x,
    'tombstoned': set}. Returns the trade row for D81's validator, or raises
    ConfigError naming the limit. Never reads, never writes."""
    if not isinstance(intent, dict):
        raise ConfigError('an intent is one JSON object')
    _reject_unknown(intent, INTENT_KEYS, 'intent')
    market = str(intent.get('market') or '').upper()
    if market not in limits['markets']:
        raise ConfigError(f"intent: {market or 'no market'} is not one the agent may trade "
                          f"({', '.join(limits['markets'])})")
    side = intent.get('side')
    if side not in ('long', 'short'):
        raise ConfigError("intent: 'side' is long or short")
    size = _num(intent, 'size_quote', 'intent', least=0.0, least_open=True, required=True)
    lev = _num(intent, 'leverage', 'intent', least=1.0) or 1.0
    if lev > limits['max_leverage']:
        raise ConfigError(f"intent: leverage {lev:g} is above the agent's {limits['max_leverage']:g}")
    notional = size * lev
    if notional > limits['max_notional'] + 1e-9:
        raise ConfigError(f"intent: {notional:g} notional is above the agent's {limits['max_notional']:g} a trade")
    gross = sum(t['notional'] for t in state['open'])
    if gross + notional > limits['max_gross'] + 1e-9:
        raise ConfigError(f"intent: {gross + notional:g} gross is above the agent's {limits['max_gross']:g}")
    stop = _num(intent, 'stop_pct', 'intent', least=0.0, least_open=True, most=1.0)
    if stop is None:
        raise ConfigError('intent: a stop is required — the agent never trades without one')
    if not limits['min_stop_pct'] <= stop <= limits['max_stop_pct']:
        raise ConfigError(f"intent: a stop {stop:.4%} away is outside the agent's "
                          f"{limits['min_stop_pct']:.4%}–{limits['max_stop_pct']:.4%}")
    tp = _num(intent, 'tp_pct', 'intent', least=0.0, least_open=True, most=1.0, required=True)
    if state['intents_last_hour'] >= limits['max_intents_hour']:
        raise ConfigError(f"intent: {state['intents_last_hour']} intents this hour — the agent's "
                          f"limit is {limits['max_intents_hour']}")
    if state['day_loss'] >= limits['max_loss_day']:
        raise ConfigError(f"intent: today's loss {state['day_loss']:g} has reached the agent's "
                          f"{limits['max_loss_day']:g} — stood down until 00:00 UTC")
    hour = (now_s % 86_400) / 3600.0
    a, b = limits['session_utc']
    if not a <= hour < b:
        raise ConfigError(f'intent: {hour:.2f} UTC is outside the agent\'s session {a:g}–{b:g}')
    entry = intent.get('entry', 'market')
    if entry not in ('market', 'maker'):
        raise ConfigError("intent: 'entry' is market or maker")
    row = {'symbol': market, 'side': side, 'capital': size, 'leverage': lev,
           'take_profit_avg_pct': tp, 'stop': {'watch': 'mark_price', 'from_base_pct': stop},
           'by': 'agent', 'reason': str(intent.get('reason') or '')[:500]}
    if intent.get('confidence') is not None:
        row['confidence'] = _num(intent, 'confidence', 'intent', least=0.0, most=1.0)
    if entry == 'maker':
        row['start_order_type'] = 'maker'
    if intent.get('trail_pct') is not None:
        row['trailing_stop_pct'] = _num(intent, 'trail_pct', 'intent', least=0.0, least_open=True, most=1.0)
        if intent.get('trail_from_pct') is not None:
            row['trailing_activation_pct'] = _num(intent, 'trail_from_pct', 'intent', least=0.0,
                                                  least_open=True, most=1.0)
    return row


# --- the agent's state, read from the fleet's own files -------------------------

def intents_log_path(fleet_path):
    from .durable import fleet_tag, logs_dir
    return logs_dir(fleet_path) / f'agent-intents-{fleet_tag(fleet_path)}.jsonl'


def log_intent(path, entry):
    """One JSON line per intent, appended: the experiment's record (J5)."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a') as f:
        f.write(json.dumps(entry, sort_keys=True) + '\n')


def intents_since(path, since_s):
    try:
        lines = Path(path).read_text().splitlines()
    except FileNotFoundError:
        return []
    out = []
    for ln in lines:
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if e.get('t', 0) >= since_s:
            out.append(e)
    return out


def day_loss(snapshot_path, now_s):
    """Today's loss on the agent's own account: its equity at the first
    snapshot after 00:00 UTC less its equity now (0 when it made money or
    nothing is known yet — the engine's stops still hold either way)."""
    from .equity_series import read_tail
    if not snapshot_path:
        return 0.0
    day = now_s - now_s % 86_400
    pts = [p for p in read_tail(snapshot_path, day) if p[1] is not None]
    if len(pts) < 2:
        return 0.0
    return max(0.0, pts[0][1] - pts[-1][1])


def read_state(fleet_path, now_s, paper=False, fetch=None):
    """The agent's state from the fleet's files: its open trades (rows it
    opened, not yet tombstoned), its intents in the last hour, today's loss.
    In paper (J6.1) the trades and the loss are the paper book's, settled
    against the market up to now."""
    from .equity_series import snapshot_path
    from .tombstones import Tombstones, path_for
    from .trades import _botid, load_trades, trades_path
    recent = intents_since(intents_log_path(fleet_path), now_s - 3600)
    if paper:
        from . import agent_paper as ap
        book = paper_book(fleet_path, now_s, fetch)
        open_ = [{'botid': p['id'], 'notional': p['notional'], 'symbol': p['market'], 'side': p['side'],
                  'reason': p['reason'], 'entry': p['entry'], 'mark': p.get('mark'),
                  'open_pnl': p.get('open_pnl'), 'stop': p['stop'], 'tp': p['tp']}
                 for p in book if not p['closed']]
        return {'open': open_, 'intents_last_hour': len(recent),
                'day_loss': ap.day_loss(book, int(now_s * 1000)), 'tombstoned': set(), 'book': book}
    raw = json.loads(Path(fleet_path).read_text())
    trades, _ = load_trades(trades_path(fleet_path, raw))
    dead = Tombstones(str(path_for(fleet_path, raw)))
    open_ = [{'botid': _botid(t), 'notional': t['capital'] * t['leverage'],
              'symbol': t['symbol'], 'side': t['side'],
              'reason': (t.get('_record') or {}).get('reason', '')}
             for t in trades if (t.get('_record') or {}).get('by') == 'agent' and not dead.has(_botid(t))]
    return {'open': open_, 'intents_last_hour': len(recent),
            'day_loss': day_loss(snapshot_path(fleet_path), now_s), 'tombstoned': set()}


def paper_book(fleet_path, now_s, fetch=None):
    """The paper book settled to now, and saved so a close the candles
    made is kept (J6.1)."""
    from . import agent_paper as ap
    from .durable import locked
    path = ap.book_path(fleet_path)
    with locked(path):
        book = ap.refresh(ap.load_book(path), int(now_s * 1000), fetch)
        ap.save_book(path, book)
    return book


def _paper_open(fleet_path, row, now_s, fetch):
    from . import agent_paper as ap
    from .durable import locked
    now_ms = int(now_s * 1000)
    price = ap.last_price(row['symbol'], now_ms, fetch)
    path = ap.book_path(fleet_path)
    with locked(path):
        book = ap.load_book(path)
        pos = ap.open_position(row, price, now_ms, f"p{len(book) + 1}")
        ap.save_book(path, book + [pos])
    return pos


def _close_live(fleet_path, market, reason, now_s):
    """L7: a close request for every open trade the agent holds on the
    market — the fleet's bot for each closes it at market."""
    from .trades import request_close, trades_path
    raw = json.loads(Path(fleet_path).read_text())
    mine = [t for t in read_state(fleet_path, now_s)['open'] if t['symbol'] == market]
    if not mine:
        raise ConfigError(f'close: no open trade of the agent\'s on {market}')
    path = trades_path(fleet_path, raw)
    return [(t['botid'], request_close(path, t['botid'], 'agent', reason)) for t in mine]


def enforce_day_loss(fleet_path, limits, now_s):
    """J3 in the engine: at the day's loss limit every open trade of the
    agent's is closed (a close request each, L7) — the door already refuses
    new ones until 00:00 UTC. Paper's book is the door's; nothing here.
    Returns the botids asked to close."""
    if limits['paper']:
        return []
    from .trades import request_close, trades_path
    st = read_state(fleet_path, now_s)
    if st['day_loss'] < limits['max_loss_day'] or not st['open']:
        return []
    path = trades_path(fleet_path, json.loads(Path(fleet_path).read_text()))
    why = (f"the agent's loss today {st['day_loss']:.2f} reached its limit "
           f"{limits['max_loss_day']:g} (J3)")
    return [t['botid'] for t in st['open'] if request_close(path, t['botid'], 'engine', why)]


def _close(fleet_path, intent, limits, now_s, fetch):
    """The agent's `close` of a market: in paper every paper position it
    holds there, at the last price; live, a close request for each of its
    trades there (L7). Never refused by the hour's count or the session —
    reducing is always allowed."""
    from . import agent_paper as ap
    from .durable import locked
    market = str(intent.get('market') or '').upper()
    if market not in limits['markets']:
        raise ConfigError(f"close: {market or 'no market'} is not one the agent trades")
    if not limits['paper']:
        return _close_live(fleet_path, market, str(intent.get('reason') or ''), now_s)
    now_ms = int(now_s * 1000)
    path = ap.book_path(fleet_path)
    with locked(path):
        book = ap.load_book(path)
        mine = [p for p in book if p['market'] == market and not p['closed']]
        if not mine:
            raise ConfigError(f'close: no open paper position on {market}')
        cs = ap.minutes(market, min(p['t'] for p in mine), now_ms, fetch)
        if not cs:
            raise ConfigError(f'close: {market} has no price to close at')
        out = [ap.close_now(p, cs, cs[-1]['c'], now_ms) if p in mine else p for p in book]
        ap.save_book(path, out)
    done = [p for p in out if p['id'] in {m['id'] for m in mine}]
    return done


def submit(fleet_path, intent, now_s=None, fetch=None):
    """Check one intent and act on it: paper — filled on paper at the last
    price (J6.1); live — appended to the trades file through D81's
    validator. `side: close` closes the agent's positions on that market.
    Returns (verdict, text); every intent is logged with its verdict."""
    from .config import market_rows, validate_fleet
    from .trades import TradeError, add_trade, trades_path
    now_s = now_s or time.time()
    raw = json.loads(Path(fleet_path).read_text())
    fleet = validate_fleet(raw)
    limits = fleet.get('agent')
    log = intents_log_path(fleet_path)
    record = {'t': now_s, 'intent': intent}
    if not limits:
        record.update(verdict='refused', why='this fleet has no agent block')
        log_intent(log, record)
        return 'refused', 'this fleet has no agent block — the owner has not opened it to the agent'
    try:
        if isinstance(intent, dict) and intent.get('side') == 'close':
            _reject_unknown(intent, ('market', 'side', 'reason'), 'intent')
            done = _close(fleet_path, intent, limits, now_s, fetch)
            if not limits['paper']:
                record.update(verdict='close_requested', botids=[b for b, _ in done])
                log_intent(log, record)
                return 'close_requested', '; '.join(f'{b}: close requested — the fleet closes it at market '
                                                    'within a cycle' for b, _ in done)
            record.update(verdict='closed', closed=[{'id': p['id'], **p['closed']} for p in done])
            log_intent(log, record)
            return 'closed', '; '.join(f"{p['id']} {p['side']} {p['market']} closed by {p['closed']['how']} "
                                       f"at {p['closed']['price']:.10g}: {p['closed']['pnl']:+.2f}" for p in done)
        row = check_intent(intent, limits, read_state(fleet_path, now_s, limits['paper'], fetch), now_s)
        if limits['paper']:
            from .trades import validate_trade
            validate_trade(dict(row))
            try:
                pos = _paper_open(fleet_path, row, now_s, fetch)
            except (OSError, ValueError, KeyError) as e:
                raise ConfigError(f'paper: no price to fill at ({e}) — nothing opened')
            record.update(verdict='paper', row=row, position=pos['id'], entry=pos['entry'])
            log_intent(log, record)
            return 'paper', (f"paper {pos['id']}: {row['side']} {row['symbol']} {pos['notional']:g} notional "
                             f"filled at {pos['entry']:.10g}, stop {pos['stop']:.10g}, take profit "
                             f"{pos['tp']:.10g} — judged on the market's candles, nothing sent")
        botid = add_trade(trades_path(fleet_path, raw), market_rows(fleet), row)
    except (ConfigError, TradeError) as e:
        record.update(verdict='refused', why=str(e))
        log_intent(log, record)
        return 'refused', str(e)
    record.update(verdict='queued', botid=botid, row=row)
    log_intent(log, record)
    return 'queued', f'{botid}: queued — the fleet opens it within a cycle'
