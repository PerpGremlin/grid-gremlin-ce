# The agent's paper book (SPEC J6, D80 phase 1): a paper intent becomes a
# position filled at the market's last price, then judged against the
# 1-minute candles that actually traded after it — the stop, the take
# profit and the trail, walked from the entry every time it is read, so the
# book holds only what was decided and the venue's own history decides the
# rest. Nothing is sent to any venue. Fees on both sides at Bybit's base
# tier; the agent's `close` closes at the last price.
#
# Honest about what a candle cannot say: when one candle reaches both the
# stop and the take profit, the stop is taken (the worse of the two); a
# candle that opens beyond the stop fills there, not at the stop; a maker
# entry is assumed filled at the price it was sent at (optimistic — a real
# maker order can miss).
import json
import time
from pathlib import Path

from .fees import BYBIT_MAKER, BYBIT_TAKER

MINUTE = 60_000
PAGE = 1000                     # Bybit's candles a request


def book_path(fleet_path):
    from .durable import fleet_tag, logs_dir
    return logs_dir(fleet_path) / f'agent-paper-{fleet_tag(fleet_path)}.json'


def load_book(path):
    try:
        rows = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return []
    if not isinstance(rows, list):
        raise ValueError(f'{path}: the paper book is a list of positions')
    return rows


def save_book(path, rows):
    from .durable import write_json
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    write_json(path, rows)


# --- the walk, pure ---------------------------------------------------------------

def open_position(row, price, now_ms, pid):
    """A paper fill of D81's trade row at `price` now: the book's record."""
    stop = row['stop']['from_base_pct']
    long = row['side'] == 'long'
    maker = row.get('start_order_type') == 'maker'
    return {'id': pid, 'market': row['symbol'], 'side': row['side'],
            'notional': row['capital'] * row['leverage'], 'leverage': row['leverage'],
            'entry': price, 't': now_ms,
            'stop': price * (1 - stop if long else 1 + stop),
            'tp': price * (1 + row['take_profit_avg_pct'] if long else 1 - row['take_profit_avg_pct']),
            'trail_pct': row.get('trailing_stop_pct'), 'trail_from_pct': row.get('trailing_activation_pct'),
            'entry_fee': BYBIT_MAKER if maker else BYBIT_TAKER,
            'reason': row.get('reason', ''), 'confidence': row.get('confidence'),
            'closed': None}


def _pnl(pos, exit_price, exit_fee):
    coins = pos['notional'] / pos['entry']
    sign = 1.0 if pos['side'] == 'long' else -1.0
    gross = coins * (exit_price - pos['entry']) * sign
    fees = pos['notional'] * pos['entry_fee'] + coins * exit_price * exit_fee
    return gross - fees, fees


def walk(pos, candles):
    """The position judged against the 1m candles after its entry minute,
    oldest first: returns {'how', 'price', 't'} when the stop, the trail or
    the take profit closed it, or None while it stands. Pure."""
    long = pos['side'] == 'long'
    stop, tp = pos['stop'], pos['tp']
    best = pos['entry']
    trail, arm = pos.get('trail_pct'), pos.get('trail_from_pct')
    start = pos['t'] - pos['t'] % MINUTE + MINUTE
    for c in candles:
        if c['t'] < start:
            continue
        o, h, lo = c['o'], c['h'], c['l']
        # the stop as it stood when the candle opened (the trail moves after)
        if long and o <= stop or not long and o >= stop:
            return {'how': 'stop', 'price': o, 't': c['t']}            # a gap through it
        if long and lo <= stop or not long and h >= stop:
            return {'how': 'stop', 'price': stop, 't': c['t']}
        if long and h >= tp or not long and lo <= tp:
            return {'how': 'take_profit', 'price': tp, 't': c['t']}
        if trail:
            best = max(best, h) if long else min(best, lo)
            moved = (best / pos['entry'] - 1) if long else (1 - best / pos['entry'])
            if arm is None or moved >= arm:
                level = best * (1 - trail) if long else best * (1 + trail)
                stop = max(stop, level) if long else min(stop, level)
    return None


def settle(pos, candles, mark, now_ms):
    """The position as of now: closed (frozen) or open at `mark`. Pure."""
    if pos['closed']:
        return pos
    hit = walk(pos, candles)
    if hit:
        fee = BYBIT_MAKER if hit['how'] == 'take_profit' else BYBIT_TAKER
        pnl, fees = _pnl(pos, hit['price'], fee)
        return dict(pos, closed={**hit, 'pnl': pnl, 'fees': fees})
    if mark is None:
        return dict(pos, open_pnl=None)
    return dict(pos, mark=mark, open_pnl=_pnl(pos, mark, BYBIT_TAKER)[0])


def close_now(pos, candles, mark, now_ms):
    """The agent's `close`: at the last price — unless the candles already
    closed it, which stands. Pure."""
    s = settle(pos, candles, mark, now_ms)
    if s['closed']:
        return s
    pnl, fees = _pnl(pos, mark, BYBIT_TAKER)
    return dict(pos, closed={'how': 'close', 'price': mark, 't': now_ms, 'pnl': pnl, 'fees': fees})


def day_loss(book, now_ms):
    """Today's paper loss: what closed since 00:00 UTC plus what is open now,
    as a loss (0 when ahead)."""
    day = now_ms - now_ms % 86_400_000
    made = sum(p['closed']['pnl'] for p in book if p['closed'] and p['closed']['t'] >= day)
    made += sum(p.get('open_pnl') or 0.0 for p in book if not p['closed'])
    return max(0.0, -made)


# --- reading the market (public) ------------------------------------------------

def minutes(symbol, start_ms, end_ms, fetch=None):
    """Bybit's public 1m candles from start to end, oldest first, paged."""
    from .agent_tools import BASE
    from .market import fetch_json
    fetch = fetch or fetch_json
    out, cursor = {}, start_ms - start_ms % MINUTE
    while cursor <= end_ms:
        top = min(cursor + PAGE * MINUTE, end_ms)
        d = fetch(f'{BASE}/market/kline?category=linear&symbol={symbol}&interval=1'
                  f'&start={cursor}&end={top}&limit={PAGE}')
        for r in d['result']['list']:
            out[int(r[0])] = {'t': int(r[0]), 'o': float(r[1]), 'h': float(r[2]),
                              'l': float(r[3]), 'c': float(r[4])}
        cursor = top + MINUTE
    return [out[t] for t in sorted(out)]


def refresh(book, now_ms, fetch=None):
    """Every open position settled against the market up to now; a market
    that cannot be read leaves its positions as they were (never closed on
    a guess)."""
    out, cache = [], {}
    for p in book:
        if p['closed']:
            out.append(p)
            continue
        try:
            if p['market'] not in cache:
                since = min(q['t'] for q in book if q['market'] == p['market'] and not q['closed'])
                cache[p['market']] = minutes(p['market'], since, now_ms, fetch)
            cs = cache[p['market']]
        except (OSError, ValueError, KeyError):
            out.append(p)
            continue
        out.append(settle(p, cs, cs[-1]['c'] if cs else None, now_ms))
    return out


def last_price(symbol, now_ms, fetch=None):
    cs = minutes(symbol, now_ms - 3 * MINUTE, now_ms, fetch)
    if not cs:
        raise ValueError(f'{symbol}: no price in the last three minutes')
    return cs[-1]['c']


def now_ms():
    return int(time.time() * 1000)
