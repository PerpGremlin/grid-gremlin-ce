# The agent's working program (SPEC J2, D80): the arithmetic of technical
# analysis done in code, so a model — or the owner by hand — only judges.
# Read-only, public endpoints, no keys: candles at several timeframes with
# their indicators, the session's VWAP and the day's range, and the market's
# state (funding, open interest, crowding, depth, the D67 regime). One dense,
# plain-text block per market, the same every call.
#
#   python3 -m gridgremlin.agent_tools BTCUSDT [ETHUSDT ...] [--tf 5m,15m,1h,4h]
import sys
import time

from .market import SESSIONS, adx, atr_pct, fetch_json, read_bybit, regime

BASE = 'https://api.bybit.com/v5'
INTERVALS = {'1m': '1', '5m': '5', '15m': '15', '1h': '60', '4h': '240', '1d': 'D'}
DEFAULT_TFS = ('5m', '15m', '1h', '4h')
BARS = 300                         # EMA200's history; a whole UTC day of 5m bars
EMAS = (9, 21, 50, 200)


# --- the maths, pure ---------------------------------------------------------

def ema(values, n):
    """The exponential moving average's last value, seeded by the first n's
    simple mean; None short of n values."""
    if len(values) < n:
        return None
    k = 2.0 / (n + 1)
    e = sum(values[:n]) / n
    for v in values[n:]:
        e = v * k + e * (1 - k)
    return e


def rsi(closes, n=14):
    """Wilder's RSI; None short of n + 1 closes; 100 when nothing fell."""
    if len(closes) < n + 1:
        return None
    gains = [max(b - a, 0.0) for a, b in zip(closes, closes[1:])]
    losses = [max(a - b, 0.0) for a, b in zip(closes, closes[1:])]
    g, l = sum(gains[:n]) / n, sum(losses[:n]) / n
    for gi, li in zip(gains[n:], losses[n:]):
        g = (g * (n - 1) + gi) / n
        l = (l * (n - 1) + li) / n
    return 100.0 if l == 0 else 100.0 - 100.0 / (1 + g / l)


def bb_width_pct(closes, n=20, k=2.0):
    """Bollinger band width (upper − lower) as a percent of the middle."""
    if len(closes) < n:
        return None
    w = closes[-n:]
    m = sum(w) / n
    sd = (sum((x - m) ** 2 for x in w) / n) ** 0.5
    return 100.0 * 2 * k * sd / m if m else None


def swings(candles, k=3, last=3):
    """Pivot highs and lows: a bar whose high (low) beats the k bars either
    side. -> (highs, lows), the most recent `last` of each, newest first."""
    hi, lo = [], []
    for i in range(k, len(candles) - k):
        win = candles[i - k:i + k + 1]
        hs, ls = [c['h'] for c in win], [c['l'] for c in win]
        if candles[i]['h'] == max(hs) and max(hs) > min(hs):      # a dead-flat window is no pivot
            hi.append(candles[i]['h'])
        if candles[i]['l'] == min(ls) and min(ls) < max(ls):
            lo.append(candles[i]['l'])
    def distinct(xs):                       # a flat top is one level, not three
        out = []
        for x in xs:
            if not out or x != out[-1]:
                out.append(x)
        return out[:last]
    return distinct(hi[::-1]), distinct(lo[::-1])


def session_start_ms(now_ms):
    """The current trading session's opening, UTC (Asia 00, Europe 08, US 16)."""
    day = now_ms - now_ms % 86_400_000
    hour = (now_ms - day) // 3_600_000
    start = max(h for h, _ in SESSIONS if h <= hour)
    return day + start * 3_600_000


def session_name(now_ms):
    hour = (now_ms % 86_400_000) // 3_600_000
    return max((h, n) for h, n in SESSIONS if h <= hour)[1]


def vwap(candles, since_ms):
    """Volume-weighted average of the typical price from `since_ms`; None
    without volume."""
    num = den = 0.0
    for c in candles:
        if c['t'] >= since_ms and c.get('v'):
            num += (c['h'] + c['l'] + c['c']) / 3 * c['v']
            den += c['v']
    return num / den if den else None


def day_range(candles, now_ms):
    """The UTC day's high and low so far."""
    day = now_ms - now_ms % 86_400_000
    today = [c for c in candles if c['t'] >= day]
    if not today:
        return None, None
    return max(c['h'] for c in today), min(c['l'] for c in today)


def tf_reading(candles):
    """One timeframe's figures, from candles oldest first ({t,o,h,l,c,v})."""
    closes = [c['c'] for c in candles]
    emas = {n: ema(closes, n) for n in EMAS}
    a, p, m = adx(candles)
    hi, lo = swings(candles)
    last = closes[-1] if closes else None
    above = [n for n, e in emas.items() if e is not None and last is not None and last > e]
    return {'last': last, 'emas': emas, 'above': above,
            'rsi': rsi(closes), 'atr_pct': atr_pct(candles), 'bb_pct': bb_width_pct(closes),
            'adx': a, 'regime': regime(a, p, m), 'swing_hi': hi, 'swing_lo': lo}


# --- reading the venue (public) ----------------------------------------------

def candles(symbol, tf, category='linear', fetch=fetch_json, bars=BARS):
    """Bybit's public candles, oldest first, with volume."""
    d = fetch(f'{BASE}/market/kline?category={category}&symbol={symbol}'
              f'&interval={INTERVALS[tf]}&limit={bars}')
    rows = d['result']['list']
    return [{'t': int(r[0]), 'o': float(r[1]), 'h': float(r[2]), 'l': float(r[3]),
             'c': float(r[4]), 'v': float(r[5])} for r in reversed(rows)]


# --- the block -----------------------------------------------------------------

def _p(v):
    if v is None:
        return '—'
    return f'{v:,.2f}' if abs(v) >= 100 else f'{v:,.4f}' if abs(v) >= 1 else f'{v:.6g}'


def _q(v):
    """A quote amount, compact: 21.1M, 845k."""
    if v is None:
        return '—'
    return f'{v / 1e6:,.1f}M' if v >= 1e6 else f'{v / 1e3:,.0f}k' if v >= 1e3 else f'{v:,.0f}'


def _n(v, f='.1f'):
    return '—' if v is None else format(v, f)


def block(symbol, tfs=DEFAULT_TFS, category='linear', fetch=fetch_json, now_ms=None):
    """The whole reading of one market as plain text. A timeframe or a
    market figure that cannot be read is said in its place, never guessed."""
    now_ms = now_ms or int(time.time() * 1000)
    lines = [f'== {symbol} ({category}) · {time.strftime("%Y-%m-%d %H:%M", time.gmtime(now_ms / 1000))} UTC'
             f' · {session_name(now_ms)} session']
    m = read_bybit(fetch, category, symbol)
    lines.append(f"price {_p(m.get('price'))} · 24h {_n(m.get('change_24h_pct'), '+.2f')}% · "
                 f"funding {_n(m.get('funding_8h_pct'), '+.4f')}%/8h · "
                 f"OI 24h {_n(m.get('oi_change_24h_pct'), '+.1f')}% · "
                 f"accounts long {_n(m.get('long_pct'), '.0f')}% · "
                 f"depth ±1% {_q(m.get('depth_1pct'))}"
                 + (f" · unread: {', '.join(sorted(m['unread']))}" if m.get('unread') else ''))
    five = None
    for tf in tfs:
        try:
            cs = candles(symbol, tf, category, fetch)
        except Exception as e:                                   # noqa: BLE001
            lines.append(f'{tf:>3}: unread ({type(e).__name__})')
            continue
        if tf in ('1m', '5m') and five is None:
            five = cs
        r = tf_reading(cs)
        e = r['emas']
        lines.append(
            f"{tf:>3}: EMA9/21/50/200 {' / '.join(_p(e[n]) for n in EMAS)} "
            f"(above {len(r['above'])} of {sum(1 for v in e.values() if v is not None)}) · "
            f"RSI {_n(r['rsi'], '.0f')} · ATR {_n(r['atr_pct'], '.2f')}% · BB width {_n(r['bb_pct'], '.2f')}% · "
            f"ADX {_n(r['adx'], '.0f')} {r['regime'] or ''} · "
            f"swing hi {' '.join(_p(x) for x in r['swing_hi']) or '—'} · "
            f"lo {' '.join(_p(x) for x in r['swing_lo']) or '—'}")
    if five:
        start = session_start_ms(now_ms)
        hi, lo = day_range(five, now_ms)
        lines.append(f"session VWAP {_p(vwap(five, start))} (since {time.strftime('%H:%M', time.gmtime(start / 1000))} UTC)"
                     f" · day high {_p(hi)} · low {_p(lo)}")
    return '\n'.join(lines)


def main(argv):
    tfs = DEFAULT_TFS
    if '--tf' in argv:
        i = argv.index('--tf')
        tfs = tuple(argv[i + 1].split(','))
        argv = argv[:i] + argv[i + 2:]
        bad = [t for t in tfs if t not in INTERVALS]
        if bad:
            print(f'unknown timeframe {bad}; one of {", ".join(INTERVALS)}')
            return 2
    symbols = [a.upper() for a in argv if not a.startswith('-')]
    if not symbols:
        print('usage: python3 -m gridgremlin.agent_tools BTCUSDT [ETHUSDT ...] [--tf 5m,15m,1h,4h]')
        return 2
    print('\n\n'.join(block(s, tfs) for s in symbols))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
