"""D67: market readings — display only, said never guessed (SPEC K).

What a grid or DCA operator wants to know about each market the fleets are
on, read hourly from public endpoints and kept in logs/market.jsonl beside
the day's readout, so a reading can later be set against the bots' own
results. Nothing here acts: no bot reads this, no key is used.

  python3 -m gridgremlin.market configs/a.json [configs/b.json]   # read, keep
  python3 -m gridgremlin.market configs/a.json --send             # and page it
  python3 -m gridgremlin.market configs/a.json --dry              # print only
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

from .config import market_rows, validate_fleet
from .exchange.truth import _f

ADX_PERIOD = 14
RANGING_BELOW, TRENDING_FROM = 20.0, 30.0        # ADX: Wilder's own bands
THIN_DEPTH_X, THIN_VOLUME_X = 1.0, 10.0          # of what the fleet puts there
THIN_DEPTH_FLOOR, THIN_VOLUME_FLOOR = 10_000.0, 100_000.0   # quote, however small the fleet
CROWDED_PCT, CROWDED_FUNDING_8H = 60.0, 0.01     # % of accounts, %/8h
STORE = 'logs/market.jsonl'
HMM_STORE = 'logs/market-hmm.json'   # K10: each coin's daily fit, reused hourly
HMM_FIT_DAYS, HMM_FILTER_HOURS, HMM_REFIT_S = 180, 500, 86_400
HMM_MIN_BIC_GAIN = 10.0              # two states must beat one bell curve by this (strong evidence)
TG_CAP = 3500
FEAR_GREED_URL = 'https://api.alternative.me/fng/?limit=30'
SESSIONS = ((0, 'Asia'), (8, 'Europe'), (16, 'US'))


# --- transport ---------------------------------------------------------------

def fetch_json(url, timeout=15):
    req = (url if isinstance(url, urllib.request.Request)
           else urllib.request.Request(url, headers={'User-Agent': 'grid-gremlin'}))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _read(fetch, url, pick):
    """One reading: its value, or the error said in its place."""
    try:
        return pick(fetch(url)), None
    except Exception as e:                                   # noqa: BLE001
        return None, f'{type(e).__name__}: {str(e)[:80]}'


# --- the maths, pure ---------------------------------------------------------

def adx(candles, period=ADX_PERIOD):
    """Wilder's ADX with its +DI/-DI, on candles oldest first ({h,l,c}).
    -> (adx, plus_di, minus_di) or (None, None, None) short of data."""
    if len(candles) < 2 * period + 1:
        return None, None, None
    tr, pdm, mdm = [], [], []
    for a, b in zip(candles, candles[1:]):
        up, down = b['h'] - a['h'], a['l'] - b['l']
        tr.append(max(b['h'] - b['l'], abs(b['h'] - a['c']), abs(b['l'] - a['c'])))
        pdm.append(up if up > down and up > 0 else 0.0)
        mdm.append(down if down > up and down > 0 else 0.0)
    s_tr, s_p, s_m = sum(tr[:period]), sum(pdm[:period]), sum(mdm[:period])
    dx = []
    for i in range(period, len(tr)):
        s_tr += tr[i] - s_tr / period
        s_p += pdm[i] - s_p / period
        s_m += mdm[i] - s_m / period
        p_di = 100.0 * s_p / s_tr if s_tr else 0.0
        m_di = 100.0 * s_m / s_tr if s_tr else 0.0
        dx.append(100.0 * abs(p_di - m_di) / (p_di + m_di) if p_di + m_di else 0.0)
    a = sum(dx[:period]) / period
    for x in dx[period:]:
        a = (a * (period - 1) + x) / period
    return a, p_di, m_di


def atr_pct(candles, period=ADX_PERIOD):
    """Average true range as a percent of the last close."""
    if len(candles) < period + 1:
        return None
    tr = [max(b['h'] - b['l'], abs(b['h'] - a['c']), abs(b['l'] - a['c']))
          for a, b in zip(candles, candles[1:])]
    close = candles[-1]['c']
    return 100.0 * sum(tr[-period:]) / period / close if close else None


def regime(adx_v, plus_di, minus_di):
    if adx_v is None:
        return None
    if adx_v < RANGING_BELOW:
        return 'ranging'
    way = 'up' if (plus_di or 0) >= (minus_di or 0) else 'down'
    return f"{'trending' if adx_v >= TRENDING_FROM else 'leaning'} {way}"


def crowding(long_pct, funding_8h_pct):
    """How one-sided the market's accounts and its funding are."""
    if long_pct is None:
        return None
    if long_pct >= CROWDED_PCT:
        return ('crowded long' if (funding_8h_pct or 0) >= CROWDED_FUNDING_8H
                else 'leaning long')
    if 100.0 - long_pct >= CROWDED_PCT:
        return ('crowded short' if (funding_8h_pct or 0) <= -CROWDED_FUNDING_8H
                else 'leaning short')
    return 'balanced'


def thin(depth_quote, volume_quote, committed=0.0):
    """A market that cannot absorb what the fleet puts on it: less resting
    within 1% of the mark than the fleet's whole ladder there, or less
    traded in a day than ten ladders — with floors for a tiny fleet (HYPE
    on the testnet, 2026-10-06: a grid about half the whole market)."""
    if depth_quote is None and volume_quote is None:
        return None
    need_depth = max(THIN_DEPTH_FLOOR, THIN_DEPTH_X * (committed or 0.0))
    need_vol = max(THIN_VOLUME_FLOOR, THIN_VOLUME_X * (committed or 0.0))
    return bool((depth_quote is not None and depth_quote < need_depth)
                or (volume_quote is not None and volume_quote < need_vol))


def depth_within(bids, asks, mark, pct=0.01):
    """Quote resting within pct of the mark, both sides, from [(px, sz)]."""
    if not mark:
        return None
    lo, hi = mark * (1 - pct), mark * (1 + pct)
    return (sum(p * s for p, s in bids if p >= lo)
            + sum(p * s for p, s in asks if p <= hi))


def funding_per_8h_pct(rate, interval_hours):
    if rate is None or not interval_hours:
        return None
    return 100.0 * rate * 8.0 / interval_hours


def base_of(symbol):
    s = str(symbol)
    for suffix in ('USDT', 'USDC', 'PERP', 'USD'):
        if s.endswith(suffix) and len(s) > len(suffix):
            return s[:-len(suffix)]
    return s


# --- the venues, public endpoints only ---------------------------------------

def _candles_bybit(rows):
    return [{'t': int(r[0]), 'o': float(r[1]), 'h': float(r[2]),
             'l': float(r[3]), 'c': float(r[4])} for r in reversed(rows)]


def read_bybit(fetch, category, symbol, committed=0.0):
    base = 'https://api.bybit.com/v5'
    out, errors = {'venue': 'bybit', 'market_type': category, 'symbol': symbol,
                   'committed': committed}, {}
    inverse = category == 'inverse'      # A4: sizes are $1 contracts, the
    t, err = _read(fetch, f'{base}/market/tickers?category={category}&symbol={symbol}',
                   lambda d: d['result']['list'][0])   # coin is what turns over
    if t is not None:
        out.update(price=_f(t.get('lastPrice')),
                   change_24h_pct=(_f(t.get('price24hPcnt'), 0.0) or 0.0) * 100.0,
                   volume_24h=_f(t.get('volume24h' if inverse else 'turnover24h')),
                   oi=_f(t.get('openInterest')),
                   funding_8h_pct=funding_per_8h_pct(
                       _f(t.get('fundingRate')), _f(t.get('fundingIntervalHour'))))
    else:
        errors['ticker'] = err
    if category != 'spot':
        hist, err = _read(fetch, f'{base}/market/open-interest?category={category}'
                          f'&symbol={symbol}&intervalTime=1h&limit=25',
                          lambda d: d['result']['list'])
        if hist and len(hist) >= 2:
            now_, then = _f(hist[0]['openInterest']), _f(hist[-1]['openInterest'])
            out['oi_change_24h_pct'] = ((now_ - then) / then * 100.0
                                        if then else None)
        elif err:
            errors['oi'] = err
        ratio, err = _read(fetch, f'{base}/market/account-ratio?category={category}'
                           f'&symbol={symbol}&period=1h&limit=1',
                           lambda d: d['result']['list'][0])
        if ratio is not None:
            out['long_pct'] = _f(ratio['buyRatio'], 0.0) * 100.0
        else:
            errors['ratio'] = err
    book, err = _read(fetch, f'{base}/market/orderbook?category={category}'
                      f'&symbol={symbol}&limit=200', lambda d: d['result'])
    if book is not None:
        q = (lambda p, s: (float(p), float(s) / float(p))) if inverse \
            else (lambda p, s: (float(p), float(s)))
        out['depth_1pct'] = depth_within([q(p, s) for p, s in book['b']],
                                         [q(p, s) for p, s in book['a']],
                                         out.get('price'))
    else:
        errors['book'] = err
    k, err = _read(fetch, f'{base}/market/kline?category={category}&symbol={symbol}'
                   f'&interval=240&limit=60', lambda d: _candles_bybit(d['result']['list']))
    if k is not None:
        _add_candle_maths(out, k)
    else:
        errors['candles'] = err
    return _finish(out, errors)


def read_hyperliquid(fetch, coin, testnet=True, committed=0.0):
    host = 'https://api.hyperliquid-testnet.xyz' if testnet else 'https://api.hyperliquid.xyz'
    out, errors = {'venue': 'hyperliquid', 'market_type': 'linear', 'symbol': coin,
                   'committed': committed}, {}

    def post(body):
        req = urllib.request.Request(f'{host}/info', data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'})
        return fetch(req)
    try:
        meta, ctxs = post({'type': 'metaAndAssetCtxs'})
        names = [u['name'] for u in meta['universe']]
        c = ctxs[names.index(coin)]
        mark = _f(c.get('markPx'))
        out.update(price=mark, volume_24h=_f(c.get('dayNtlVlm')),
                   oi=_f(c.get('openInterest')),
                   funding_8h_pct=funding_per_8h_pct(_f(c.get('funding')), 1.0),
                   oracle=_f(c.get('oraclePx')))
        prev = _f(c.get('prevDayPx'))
        if prev and mark:
            out['change_24h_pct'] = (mark / prev - 1.0) * 100.0
    except Exception as e:                                   # noqa: BLE001
        errors['ticker'] = f'{type(e).__name__}: {str(e)[:80]}'
    try:
        bids, asks = post({'type': 'l2Book', 'coin': coin})['levels']
        out['depth_1pct'] = depth_within(
            [(float(x['px']), float(x['sz'])) for x in bids],
            [(float(x['px']), float(x['sz'])) for x in asks], out.get('price'))
    except Exception as e:                                   # noqa: BLE001
        errors['book'] = f'{type(e).__name__}: {str(e)[:80]}'
    try:
        now_ms = int(time.time() * 1000)
        rows = post({'type': 'candleSnapshot', 'req': {
            'coin': coin, 'interval': '4h',
            'startTime': now_ms - 60 * 4 * 3600 * 1000, 'endTime': now_ms}})
        _add_candle_maths(out, [{'t': int(r['t']), 'o': float(r['o']),
                                 'h': float(r['h']), 'l': float(r['l']),
                                 'c': float(r['c'])} for r in rows])
    except Exception as e:                                   # noqa: BLE001
        errors['candles'] = f'{type(e).__name__}: {str(e)[:80]}'
    return _finish(out, errors)


def _add_candle_maths(out, candles):
    a, p, m = adx(candles)
    out.update(adx_4h=a, regime=regime(a, p, m), atr_pct_4h=atr_pct(candles))


def _finish(out, errors):
    out['crowding'] = crowding(out.get('long_pct'), out.get('funding_8h_pct'))
    out['thin'] = thin(out.get('depth_1pct'), out.get('volume_24h'),
                       out.get('committed') or 0.0)
    if errors:
        out['unread'] = errors
    return out


def read_fear_greed(fetch):
    data, err = _read(fetch, FEAR_GREED_URL, lambda d: d['data'])
    if data is None:
        return {'unread': err}
    vals = [int(e['value']) for e in data]
    return {'score': vals[0], 'label': data[0].get('value_classification'),
            'avg_7d': round(sum(vals[:7]) / len(vals[:7])),
            'avg_30d': round(sum(vals) / len(vals))}


CROSS = (('binance', 'https://fapi.binance.com/fapi/v1/premiumIndex?symbol={b}USDT',
          lambda d: _f(d['lastFundingRate'])),
         ('okx', 'https://www.okx.com/api/v5/public/funding-rate?instId={b}-USDT-SWAP',
          lambda d: _f(d['data'][0]['fundingRate'])),
         ('bitget', 'https://api.bitget.com/api/v2/mix/market/current-fund-rate'
                    '?symbol={b}USDT&productType=USDT-FUTURES',
          lambda d: _f(d['data'][0]['fundingRate'])))


def read_cross(fetch, base):
    """Mainnet funding elsewhere, per 8 h — the reference a demo or testnet
    rate lacks. The three largest perp venues beside Bybit, all on 8 h."""
    out = {}
    for name, url, pick in CROSS:
        rate, err = _read(fetch, url.format(b=base), pick)
        out[name] = (funding_per_8h_pct(rate, 8.0) if rate is not None
                     else {'unread': err})
    rates = [v for v in out.values() if isinstance(v, float)]
    out['divergence'] = bool(rates) and any(r > 0 for r in rates) and any(r < 0 for r in rates)
    return out


def read_announcements(fetch, bases):
    """Bybit's own notices that name a fleet coin, or a delisting or
    maintenance of anything — campaigns and news are left out."""
    items, err = _read(fetch, 'https://api.bybit.com/v5/announcements/index'
                       '?locale=en-US&limit=20', lambda d: d['result']['list'])
    if items is None:
        return {'unread': err}
    keep = []
    for it in items:
        title = str(it.get('title', ''))
        low = title.lower()
        kind = str((it.get('type') or {}).get('title', ''))
        named = any(f' {b.lower()} ' in f' {low} ' or f'{b.lower()}usdt' in low
                    for b in bases)
        if named or any(w in low for w in ('delist', 'maintenance', 'suspend')):
            keep.append({'title': title[:120], 'kind': kind,
                         'at': int(it.get('publishTime') or 0)})
    return keep


# --- collect, keep, read back -----------------------------------------------

# --- K10: calm or wild, the hidden model's reading -------------------------------

def _hourly(fetch, symbol, hours, now_ms):
    """Bybit's public hourly candles for the last `hours`, oldest first."""
    base = 'https://api.bybit.com/v5/market/kline'
    out, end = {}, int(now_ms)
    while len(out) < hours:
        need = min(1000, hours - len(out))
        rows = fetch(f'{base}?category=linear&symbol={symbol}&interval=60&limit={need}&end={end}')['result']['list']
        if not rows:
            break
        for c in _candles_bybit(rows):
            out[c['t']] = c
        end = min(int(r[0]) for r in rows) - 1
        if len(rows) < need:
            break
    return [out[t] for t in sorted(out)]


def _log_returns(candles):
    import math
    return [math.log(b['c'] / a['c']) for a, b in zip(candles, candles[1:]) if a['c'] > 0 and b['c'] > 0]


def read_hmm(fetch, coin, cache, now):
    """K10: a two-state hidden Markov model of `coin`'s hourly returns on
    Bybit (the market-wide state, whichever venue a bot trades it on): fitted
    on the last HMM_FIT_DAYS once a day (kept in `cache`), then filtered over
    the last HMM_FILTER_HOURS — the probability the market is in its wild
    state now, from the hours up to now only, and how long the current state
    has held. Display only: no bot reads it."""
    import math
    from .hmm import _pdf, best_fit, bic, forward
    sym = f'{coin}USDT'
    now_ms = int(now * 1000)
    try:
        fit = cache.get(coin)
        if not fit or now - fit.get('fit_t', 0) >= HMM_REFIT_S:
            r = _log_returns(_hourly(fetch, sym, HMM_FIT_DAYS * 24, now_ms))
            if len(r) < 24 * 30:
                return {'unread': f'{len(r)} hours of {sym} — too few to fit'}
            pi, A, mu, var, ll2 = best_fit(r, 2, restarts=2)
            m1 = sum(r) / len(r)
            v1 = max(sum((x - m1) ** 2 for x in r) / len(r), 1e-12)
            ll1 = sum(math.log(_pdf(x, m1, v1)) for x in r)
            # BIC: is a second state worth its parameters, or one bell curve enough?
            fit = {'fit_t': now, 'A': A, 'mu': mu, 'var': var, 'n': len(r),
                   'bic_gain': bic(ll1, 1, len(r)) - bic(ll2, 2, len(r))}
            cache[coin] = fit
        recent = _hourly(fetch, sym, HMM_FILTER_HOURS, now_ms)
        r = _log_returns(recent)
        if len(r) < 48:
            return {'unread': f'{len(r)} recent hours of {sym}'}
    except (OSError, ValueError, KeyError, IndexError, TypeError) as e:
        return {'unread': f'{type(e).__name__}: {e}'}
    A, mu, var = fit['A'], fit['mu'], fit['var']
    a01, a10 = A[0][1], A[1][0]
    pi = [a10 / (a01 + a10), a01 / (a01 + a10)] if a01 + a10 else [0.5, 0.5]   # the long-run shares
    alphas, _ = forward(r, pi, A, mu, var)
    p = alphas[-1][1]
    wild = p > 0.5
    spell = 0
    for a in reversed(alphas):
        if (a[1] > 0.5) != wild:
            break
        spell += 1
    sd = [math.sqrt(v * 24) for v in var]
    two = (fit.get('bic_gain') or 0.0) > HMM_MIN_BIC_GAIN
    if not two:                     # one bell curve explains it: no wild state to name
        return {'two_states': False, 'state': 'one regime', 'sd_day': [math.sqrt(sum(
            (x - sum(r) / len(r)) ** 2 for x in r) / len(r) * 24)], 'bic_gain': fit.get('bic_gain'),
                'fit_age_h': (now - fit['fit_t']) / 3600.0, 'fit_hours': fit['n']}
    return {'two_states': True, 'bic_gain': fit['bic_gain'],
            'p_wild': p, 'state': 'wild' if wild else 'calm', 'spell_h': spell,
            'sd_day': sd,
            # how far apart the states are: near 1, "wild" is only less calm
            # (a market with no wild spells still fits two states)
            'separation': sd[1] / sd[0] if sd[0] else None,
            'stay': [A[0][0], A[1][1]],
            'typical_spell_h': [1.0 / (1.0 - A[k][k]) if A[k][k] < 1 else None for k in (0, 1)],
            'fit_age_h': (now - fit['fit_t']) / 3600.0, 'fit_hours': fit['n'],
            # the last two days, for the panel's mini chart: closes and P(wild)
            'closes_48h': [round(c['c'], 8) for c in recent[-48:]],
            'p_wild_48h': [round(a[1], 3) for a in alphas[-48:]]}


def load_hmm(path=None):
    try:
        return json.loads(Path(path or HMM_STORE).read_text())
    except (OSError, ValueError):
        return {}


def save_hmm(cache, path=None):
    from .durable import write_json
    p = Path(path or HMM_STORE)
    p.parent.mkdir(exist_ok=True)
    write_json(p, cache)


def markets_of(fleet_paths):
    """Every (venue, market_type, symbol) a fleet trades, once, with what
    the fleets put on it in quote: {key: committed}."""
    out = {}
    for fp in fleet_paths:
        fleet = validate_fleet(json.loads(Path(fp).read_text()))
        from .trades import with_trades
        fleet = with_trades(fp, fleet)                # L5: a trade's market is read too
        for cfg in market_rows(fleet):
            key = (cfg['venue'], cfg['market_type'], cfg['symbol'])
            put = cfg.get('ladder_total_notional') or cfg.get('ladder_notional') or 0.0
            out[key] = out.get(key, 0.0) + float(put)
        for cfg in fleet['bots']:                        # D78: the row's legs
            if cfg.get('strategy') != 'portfolio':
                continue
            from .portfolio import leg_markets
            for _, _, mt, sym, put in leg_markets(cfg):
                key = (cfg['venue'], mt, sym)
                out[key] = out.get(key, 0.0) + float(put)
    return out


def collect(fleet_paths, fetch=fetch_json, now=None, hl_testnet=True, hmm_cache=None):
    now = time.time() if now is None else now
    row = {'t': now, 'markets': {}, 'cross': {}}
    bases = []
    for (venue, mt, symbol), put in markets_of(fleet_paths).items():
        key = f'{venue}:{mt}:{symbol}'
        row['markets'][key] = (read_hyperliquid(fetch, symbol, hl_testnet, put)
                               if venue == 'hyperliquid'
                               else read_bybit(fetch, mt, symbol, put))
        b = base_of(symbol)
        if b not in bases:
            bases.append(b)
    for b in bases:
        row['cross'][b] = read_cross(fetch, b)
    if hmm_cache is not None:                                   # K10
        row['hmm'] = {b: read_hmm(fetch, b, hmm_cache, now) for b in bases}
    row['fear_greed'] = read_fear_greed(fetch)
    row['announcements'] = read_announcements(fetch, bases)
    return row


def append(row, path=None):
    p = Path(path or STORE)
    p.parent.mkdir(exist_ok=True)
    with open(p, 'a') as f:
        f.write(json.dumps(row) + '\n')


def latest(path=None):
    """The newest reading — read from the file's END (the panel asks every
    refresh; the file grows a line an hour and is never read whole)."""
    p = Path(path or STORE)
    if not p.exists():
        return None
    with open(p, 'rb') as f:
        f.seek(0, 2)
        size = f.tell()
        back = 65536
        while True:
            f.seek(max(0, size - back))
            lines = [ln for ln in f.read().split(b'\n') if ln.strip()]
            if size - back <= 0 or len(lines) >= 2:
                break                        # the last line is whole once another precedes it
            back *= 4
    return json.loads(lines[-1]) if lines else None


# --- words -------------------------------------------------------------------

from .fmt import pct as _pct  # noqa: E402  (C10)


from .fmt import big_si as _big  # noqa: E402  (C10)


def _px(v):
    if v is None:
        return '—'
    return f'{v:,.6g}' if v < 1000 else f'{v:,.0f}'


def ta_line(m):
    """The regime words a coin shares across its markets (one set of candles)."""
    parts = []
    if m.get('regime'):
        parts.append(f"{m['regime']} · ADX {m['adx_4h']:.0f}")
    if m.get('atr_pct_4h') is not None:
        parts.append(f"ATR {_pct(m['atr_pct_4h'], 1, sign=False)}/4h")
    if m.get('crowding'):
        parts.append(f"{m['crowding']} {m['long_pct']:.0f}/{100 - m['long_pct']:.0f}")
    return ' · '.join(parts)


def market_line(m):
    """One market's own numbers in a line: what a card and the phone share."""
    parts = []
    if m.get('funding_8h_pct') is not None:
        parts.append(f"fund {_pct(m['funding_8h_pct'], 3)}/8h")
    if m.get('oi') is not None:
        oi = f"OI {_big(m['oi'])}"
        if m.get('oi_change_24h_pct') is not None:
            oi += f" ({_pct(m['oi_change_24h_pct'], 1)})"
        parts.append(oi)
    if m.get('depth_1pct') is not None:
        d = f"depth {_big(m['depth_1pct'])}"
        if m.get('committed'):
            d += f" = {m['depth_1pct'] / m['committed']:.0f}× yours"
        parts.append(d)
    if m.get('thin'):
        parts.append('THIN')
    if m.get('unread'):
        parts.append('unread: ' + ', '.join(sorted(m['unread'])))
    return ' · '.join(parts) or 'nothing read'


def session_name(t):
    hour = time.gmtime(t).tm_hour
    name = 'US'
    for h, n in SESSIONS:
        if hour >= h:
            name = n
    return name


VENUE_WORD = {'bybit': 'Bybit', 'hyperliquid': 'HL'}


def report(row, now=None):
    """The Telegram text, in messages under the cap: sentiment, every coin
    with its regime once and each of its markets, funding elsewhere, the
    notices that matter. Display only, and says so."""
    now = time.time() if now is None else now
    t = row['t']
    perth = time.strftime('%H:%M', time.gmtime(t + 8 * 3600))
    utc = time.strftime('%H:%M', time.gmtime(t))
    age = now - t
    head = f'📊 market — {session_name(t)} · {perth} Perth ({utc} UTC)'
    if age > 900:
        head += f' · read {age / 3600:.1f} h ago'
    blocks = [[head]]
    fg = row.get('fear_greed') or {}
    if fg.get('score') is not None:
        blocks[0].append(f"🌡️ fear & greed {fg['score']} ({fg['label']}) · 7d {fg['avg_7d']} · 30d {fg['avg_30d']}")
    elif fg.get('unread'):
        blocks[0].append(f"🌡️ fear & greed unread ({fg['unread']})")
    by_base = {}
    for key, m in row['markets'].items():
        by_base.setdefault(base_of(m['symbol']), []).append((key, m))
    for base, markets in by_base.items():
        lead = next((m for _, m in markets if m.get('regime')), markets[0][1])
        block = [f'📈 {base} · {ta_line(lead) or "no candles read"}']
        for key, m in markets:
            venue, mt, _ = key.split(':', 2)
            where = VENUE_WORD.get(venue, venue) + ('' if mt == 'linear' else f' {mt}')
            unit = ' ' + base if mt == 'inverse' else ''
            block.append(f"{where} {_px(m.get('price'))} ({_pct(m.get('change_24h_pct'), 1)}) "
                         f"vol {_big(m.get('volume_24h'))}{unit} · {market_line(m)}")
        x = row.get('cross', {}).get(base)
        if x:
            said = ', '.join(f"{n} {_pct(x[n], 3)}" for n, _, _ in CROSS
                             if isinstance(x.get(n), float))
            if said:
                block.append(f'elsewhere /8h: {said}'
                             + (' ⚠️ disagree' if x.get('divergence') else ''))
        blocks.append(block)
    ann = row.get('announcements')
    if isinstance(ann, list) and ann:
        blocks.append(['📣 Bybit notices'] + [f"• {a['title']}" for a in ann[:5]])
    blocks[-1].append('\nreadings only — nothing acts on them (D67)')
    messages, cur = [], ''
    for block in blocks:
        text = '\n'.join(block)
        if cur and len(cur) + 2 + len(text) > TG_CAP:
            messages.append(cur)
            cur = text
        else:
            cur = f'{cur}\n\n{text}' if cur else text
    messages.append(cur)
    return messages


def _age_words(age_s):
    return f'{age_s / 3600:.1f} h ago' if age_s >= 3600 else f'{int(age_s // 60)} min ago'


def for_bots(row, key_of, venue_of, now=None):
    """D67: the newest reading set beside each bot — the words its card says.
    key_of: botid -> (market_type, symbol); venue_of: (market_type, symbol)
    -> venue. A bot whose market was not read has no entry."""
    if not row:
        return {}
    now = time.time() if now is None else now
    out = {}
    for botid, (mt, sym) in key_of.items():
        m = (row.get('markets') or {}).get(f'{venue_of.get((mt, sym))}:{mt}:{sym}')
        if m:
            out[botid] = {'line': ta_line(m), 'thin': m.get('thin'),
                          'regime': m.get('regime'),
                          'age_s': int(max(0, now - row['t']))}
    return out


def digest_block(row, now=None):
    """D67 in the digest: sentiment and each coin's regime in a line, with
    the venues where its book is thin for the fleet."""
    if not row:
        return ['market: no readings yet']
    now = time.time() if now is None else now
    fg = row.get('fear_greed') or {}
    head = f"market (read {_age_words(now - row['t'])}): "
    head += (f"fear & greed {fg['score']} ({fg['label']})" if fg.get('score') is not None
             else 'fear & greed unread')
    lines = [head]
    by_base = {}
    for key, m in (row.get('markets') or {}).items():
        by_base.setdefault(base_of(m['symbol']), []).append((key, m))
    for base, markets in by_base.items():
        lead = next((m for _, m in markets if m.get('regime')), markets[0][1])
        words = ta_line(lead) or 'no candles read'
        thin_at = [VENUE_WORD.get(k.split(':')[0], k.split(':')[0])
                   for k, m in markets if m.get('thin')]
        if thin_at:
            words += ' · thin on ' + ', '.join(sorted(set(thin_at)))
        lines.append(f'{base}: {words}')
    return lines


def main(argv):
    dry, send = '--dry' in argv, '--send' in argv
    paths = [a for a in argv if not a.startswith('--')]
    if not paths:
        print('usage: python3 -m gridgremlin.market <fleet.json> ... [--send] [--dry]')
        return 2
    from .exchange.env import load_env
    load_env()
    import os
    hmm_cache = load_hmm()
    row = collect(paths, hl_testnet=os.environ.get('HL_TESTNET', '').lower() == 'true',
                  hmm_cache=hmm_cache)
    if not dry:
        save_hmm(hmm_cache)
    texts = report(row)
    if dry:
        print(json.dumps(row)[:400] + '…')
        print('\n\n---- next message ----\n\n'.join(texts))
        return 0
    append(row)
    unread = sum(1 for m in row['markets'].values() if m.get('unread'))
    print(f"market: {len(row['markets'])} markets read, {unread} with a part unread",
          flush=True)
    if send:
        from .watchdog import send_telegram
        for text in texts:
            send_telegram(text)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
