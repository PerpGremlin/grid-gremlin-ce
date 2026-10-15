# The paper momentum book (SPEC Q, D134): the momentum study's one fixed
# setting run forward on the market's own public prices — the 20 USDT
# perpetuals most traded over the last 30 days, ranked each Monday by their
# last 4 weeks, long the top fifth and short the bottom fifth, half the
# money each side, held a week. Nothing is sent to any venue: each week is
# formed from Binance's daily candles at Monday's open and settled from the
# next Monday's open and the week's funding, so the book is what the
# market decided, not what a fill would have been.
#
# A week once settled is frozen: a later run never rewrites it. A run that
# finds a Monday it missed forms that week from the candles known at that
# Monday and says so (`late`). Each settled week keeps every universe
# member's return and funding, so random books can be scored on the same
# weeks (the research side's pre-registered score reads them).
import calendar
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from .fees import BYBIT_TAKER as TAKER   # the study's fee: Bybit's, a little over Binance's

N = 20                      # the universe: most traded over VOLUME_DAYS
WEEKS = 4                   # the signal's lookback
FIFTH = 0.2
MIN_DAYS = 60
VOLUME_DAYS = 30
START = '2026-10-19'        # week 1, fixed before the first trade
SETTLE_AFTER = 15 * 60_000  # a Monday's candle is read 15 minutes after its open
EXCLUDE = ('USDC', 'BUSD', 'TUSD', 'FDUSD', 'USDP', 'DAI', 'USDE', 'PAXG', 'XAU', 'XAG',
           'BTCDOM', 'DEFI', 'FOOTBALL', 'BLUEBIRD', 'ALLINDEX')
D = 86_400_000
W = 7 * D
API = 'https://fapi.binance.com'


def day_ms(text):
    y, m, d = map(int, text.split('-'))
    return calendar.timegm((y, m, d, 0, 0, 0)) * 1000


def iso(ms):
    return time.strftime('%Y-%m-%d', time.gmtime(ms / 1000))


# --- the book, pure (the study's arithmetic, unchanged) ---------------------------

def excluded(symbol):
    return not symbol.endswith('USDT') or symbol[:-4] in EXCLUDE


def universe(coins, monday, n=N):
    """The top n at `monday` by the last VOLUME_DAYS days' traded value,
    among coins with MIN_DAYS of candles and a candle the day before.
    coins = {symbol: {day ms: (open, close, quote volume)}}."""
    ranked = []
    for sym, days in coins.items():
        if excluded(sym) or monday - D not in days or monday - MIN_DAYS * D not in days:
            continue
        value = sum(days[d][2] for d in range(monday - VOLUME_DAYS * D, monday, D) if d in days)
        ranked.append((value, sym))
    ranked.sort(reverse=True)
    return [s for _, s in ranked[:n]]


def signal(days, monday, weeks=WEEKS):
    """The return over the last `weeks` weeks to Sunday's close, or None."""
    a, b = days.get(monday - weeks * W - D), days.get(monday - D)
    return b[1] / a[1] - 1 if a and b else None


def week_return(days, monday):
    """Monday's open to the next Monday's open; a coin whose candles stop
    within the week closes at its last close."""
    first = days.get(monday)
    if not first:
        return None
    nxt = days.get(monday + W)
    if nxt:
        return nxt[0] / first[0] - 1
    last = max((d for d in range(monday, monday + W, D) if d in days), default=monday)
    return days[last][1] / first[0] - 1


def legs(scores):
    """Long the top fifth by score, short the bottom fifth (at least one
    each); ties broken by name."""
    ranked = sorted(scores, key=lambda s: (-scores[s], s))
    k = max(1, int(len(ranked) * FIFTH))
    return ranked[:k], ranked[-k:]


def weights(longs, shorts):
    w = {s: 0.5 / len(longs) for s in longs}
    for s in shorts:
        w[s] = w.get(s, 0.0) - 0.5 / len(shorts)
    return w


def week_pnl(w, prev, rets, funds, fee=TAKER):
    """One week: the weighted returns, less the fee on every change of
    weight and the funding paid (a long pays a positive rate).
    -> (net, fee paid, funding paid)."""
    gross = sum(x * rets[s] for s, x in w.items())
    turn = sum(abs(w.get(s, 0.0) - prev.get(s, 0.0)) for s in set(w) | set(prev))
    paid = sum(x * funds.get(s, 0.0) for s, x in w.items())
    return gross - turn * fee - paid, turn * fee, paid


def form(coins, monday):
    """The week's book at `monday`: the universe, the scores and the
    weights, from candles up to Monday's open alone. None when fewer than
    5 coins can be scored (the study's rule: an empty week)."""
    uni = universe(coins, monday)
    scores = {}
    for s in uni:
        x = signal(coins[s], monday)
        if x is not None and monday in coins[s]:
            scores[s] = x
    if len(scores) < 5:
        return {'monday': iso(monday), 'universe': uni, 'scores': scores, 'weights': {}}
    longs, shorts = legs(scores)
    return {'monday': iso(monday), 'universe': uni, 'scores': scores,
            'weights': weights(longs, shorts),
            'opens': {s: coins[s][monday][0] for s in scores}}


def settle(week, coins, funding, prev):
    """The formed week closed: every universe member's return and funding
    (kept for random books on the same weeks), then the book's net."""
    monday = day_ms(week['monday'])
    rets, funds = {}, {}
    for s in week['universe']:
        r = week_return(coins.get(s, {}), monday)
        seen = (week.get('last') or {}).get(s)
        if r is None and seen and s in week.get('opens', {}):
            r = seen[1] / week['opens'][s] - 1      # gone from the venue: its last close seen
        if r is not None:
            rets[s] = r
            funds[s] = sum(rate for t, rate in funding.get(s, ()) if monday < t <= monday + W)
    w = week['weights']
    if not w:
        net = fee = paid = 0.0
    else:
        net, fee, paid = week_pnl(w, prev, {s: rets.get(s, 0.0) for s in w}, funds)
    return dict(week, rets=rets, funds=funds, gross=net + fee + paid, net=net, fee=fee, funding=paid)


def growth(weeks):
    """The settled weeks compounded: 1.0 is where it started."""
    g = 1.0
    for wk in weeks:
        if 'net' in wk:
            g *= 1 + wk['net']
    return g


# --- the ledger ------------------------------------------------------------------

def ledger_path(repo):
    return Path(repo) / 'logs' / 'momentum-paper.json'


def load(path):
    try:
        book = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {'setting': setting(), 'weeks': []}
    if book.get('setting') != setting():
        raise ValueError(f'{path}: written for {book.get("setting")}, not {setting()} '
                         '— the setting is fixed (D134); a new one is a new book')
    return book


def setting():
    return {'universe': N, 'weeks': WEEKS, 'fifth': FIFTH, 'fee': TAKER, 'start': START}


def save(path, book):
    from common.files import write_json
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    write_json(path, book)


def watch(week, coins):
    """The open week's held coins' latest close, kept daily: a coin the
    venue removes before the week settles is closed at the last close seen,
    as the study closed a delisted coin."""
    last = week.setdefault('last', {})
    for s in week['weights']:
        days = coins.get(s) or {}
        if days:
            d = max(days)
            last[s] = [iso(d), days[d][1]]


def step(book, now_ms, coins_at, funding_at):
    """Bring the book up to `now_ms`, one change at a time until none is
    left: settle a formed week whose next Monday has opened; form the next
    Monday since START not yet formed (a missed one from its own candles,
    marked late); else note the open week's held coins' latest close.
    coins_at(monday, symbols) and funding_at(monday, symbols) read the
    market; symbols None means every USDT perpetual. Returns what changed."""
    said, weeks = [], book['weeks']
    for _ in range(4 * 53 * 10):      # years of catching up at most; past that is a bug, said aloud
        due = [i for i, wk in enumerate(weeks)
               if 'net' not in wk and now_ms >= day_ms(wk['monday']) + W + SETTLE_AFTER]
        if due:
            i = due[0]
            wk, m = weeks[i], day_ms(weeks[i]['monday'])
            prev = weeks[i - 1]['weights'] if i and day_ms(weeks[i - 1]['monday']) == m - W else {}
            weeks[i] = settle(wk, coins_at(m, wk['universe']), funding_at(m, wk['universe']), prev)
            said.append(f"settled {wk['monday']}: {weeks[i]['net'] * 100:+.2f}%")
            continue
        m = day_ms(START) if not weeks else day_ms(weeks[-1]['monday']) + W
        if now_ms >= m + SETTLE_AFTER:
            wk = form(coins_at(m, None), m)
            if now_ms >= m + D:
                wk['late'] = True
            weeks.append(wk)
            said.append(f"formed {wk['monday']}" + (' (late)' if wk.get('late') else ''))
            continue
        if weeks and 'net' not in weeks[-1] and weeks[-1]['weights']:
            watch(weeks[-1], coins_at(day_ms(weeks[-1]['monday']), sorted(weeks[-1]['weights'])))
        return said
    raise RuntimeError(f'the paper book did not settle down after {len(said)} changes')


# --- the market, read --------------------------------------------------------------

def _get(path, params, fetch=None):
    url = f'{API}{path}?{urllib.parse.urlencode(params)}' if params else f'{API}{path}'
    if fetch:
        return fetch(url)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                return json.loads(r.read())
        except OSError as err:
            if attempt == 2 or _gone(err):
                raise
            time.sleep(2 * (attempt + 1))


def perpetuals(fetch=None):
    info = _get('/fapi/v1/exchangeInfo', None, fetch)
    return sorted(s['symbol'] for s in info['symbols']
                  if s.get('contractType') == 'PERPETUAL' and s.get('quoteAsset') == 'USDT'
                  and s.get('status') == 'TRADING' and not excluded(s['symbol']))


def _gone(err):
    import urllib.error
    return isinstance(err, urllib.error.HTTPError) and err.code == 400


def candles(symbol, monday, fetch=None):
    """Daily candles from MIN_DAYS + 5 days before `monday` to the next
    Monday's: {day ms: (open, close, quote volume)}; empty for a symbol the
    venue no longer knows."""
    try:
        rows = _get('/fapi/v1/klines', {'symbol': symbol, 'interval': '1d',
                                        'startTime': monday - (MIN_DAYS + 5) * D,
                                        'endTime': monday + W, 'limit': 1000}, fetch)
    except OSError as err:
        if not _gone(err):
            raise
        return {}
    return {int(k[0]): (float(k[1]), float(k[4]), float(k[7])) for k in rows}


def funding_rates(symbol, monday, fetch=None):
    try:
        rows = _get('/fapi/v1/fundingRate', {'symbol': symbol, 'startTime': monday,
                                             'endTime': monday + W, 'limit': 1000}, fetch)
    except OSError as err:
        if not _gone(err):
            raise
        return []
    return [(int(r['fundingTime']), float(r['fundingRate'])) for r in rows]


def market(fetch=None, pause=0.05):
    def coins_at(monday, symbols):
        out = {}
        for s in symbols if symbols is not None else perpetuals(fetch):
            out[s] = candles(s, monday, fetch)
            time.sleep(pause)
        return out

    def funding_at(monday, symbols):
        return {s: funding_rates(s, monday, fetch) for s in symbols}
    return coins_at, funding_at


def report(book):
    settled = [wk for wk in book['weeks'] if 'net' in wk]
    lines = [f"paper momentum book (D134): {len(settled)} week(s) settled, "
             f"{(growth(settled) - 1) * 100:+.2f}% compounded since {START}"]
    for wk in book['weeks'][-4:]:
        longs = sorted(s for s, x in wk['weights'].items() if x > 0)
        shorts = sorted(s for s, x in wk['weights'].items() if x < 0)
        result = f"{wk['net'] * 100:+.2f}%" if 'net' in wk else 'open'
        lines.append(f"  {wk['monday']}{' (late)' if wk.get('late') else ''}: {result} "
                     f"long {', '.join(longs) or '-'} | short {', '.join(shorts) or '-'}")
    return '\n'.join(lines)


def main(argv):
    """python3 -m gridgremlin.momentum_paper [run|show]"""
    repo = Path(__file__).resolve().parent.parent
    path = ledger_path(repo)
    book = load(path)
    if argv[1:] == ['show']:
        print(report(book))
        return 0
    if argv[1:] not in ([], ['run']):
        print(main.__doc__)
        return 2
    said = step(book, int(time.time() * 1000), *market())
    if said:
        save(path, book)
    for line in said:
        print(line)
    print(report(book))
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv))
