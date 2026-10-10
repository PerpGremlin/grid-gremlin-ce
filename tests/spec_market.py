"""K — the market readings (D67): read, kept, said; never acted on."""
import json
import tempfile
import urllib.request
from pathlib import Path

from gridgremlin import market as mk


def _candles(closes, wick=0.005):
    return [{'t': i, 'o': c, 'h': c * (1 + wick), 'l': c * (1 - wick), 'c': c}
            for i, c in enumerate(closes)]


def _trend(n=60, step=0.01):
    c, out = 100.0, []
    for _ in range(n):
        out.append(c)
        c *= 1 + step
    return out


def _zigzag(n=60, amp=0.01):
    return [100.0 * (1 + amp * (1 if i % 2 else -1)) for i in range(n)]


def spec_K1_adx_reads_a_trend_high_and_a_zigzag_low():
    a_up, p_up, m_up = mk.adx(_candles(_trend()))
    assert a_up > 40 and p_up > m_up, (a_up, p_up, m_up)
    a_dn, p_dn, m_dn = mk.adx(_candles(list(reversed(_trend()))))
    assert a_dn > 40 and m_dn > p_dn
    a_zz, _, _ = mk.adx(_candles(_zigzag()))
    assert a_zz < 20, a_zz
    assert mk.adx(_candles(_trend(20))) == (None, None, None)   # short of data
    assert mk.regime(a_up, p_up, m_up) == 'trending up'
    assert mk.regime(a_dn, p_dn, m_dn) == 'trending down'
    assert mk.regime(a_zz, 1, 2) == 'ranging'
    assert mk.regime(25.0, 1, 2) == 'leaning down'
    assert mk.regime(None, None, None) is None


def spec_K1_atr_is_a_percent_of_the_last_close():
    flat = [{'t': i, 'o': 100, 'h': 101, 'l': 99, 'c': 100} for i in range(30)]
    assert abs(mk.atr_pct(flat) - 2.0) < 1e-9
    assert mk.atr_pct(flat[:5]) is None


def spec_K2_crowding_and_thinness_are_words_from_numbers():
    assert mk.crowding(74, 0.010) == 'crowded long'
    assert mk.crowding(74, 0.002) == 'leaning long'
    assert mk.crowding(25, -0.012) == 'crowded short'
    assert mk.crowding(55, 0.05) == 'balanced'
    assert mk.crowding(None, 0.05) is None
    # HYPE on the testnet, 2026-10-06: ~150 resting within 1%, ~2.5k a day,
    # against a grid of 750 — thin by both measures
    assert mk.thin(150.0, 2500.0, 750.0) is True
    assert mk.thin(60_000.0, 2_300_000.0, 7500.0) is False    # 8x the ladder: fine
    assert mk.thin(3_000_000.0, 5e9, 4_000_000.0) is True      # under one ladder
    assert mk.thin(16_000_000.0, 3e9, 10_000.0) is False
    assert mk.thin(None, None, 1.0) is None
    assert mk.thin(9_000.0, 1e9, 0.0) is True                 # under the floor


def spec_K3_depth_is_quote_within_the_band_and_inverse_sizes_are_dollars():
    bids = [(99.5, 10.0), (99.0, 10.0), (98.0, 100.0)]          # 98 is outside 1%
    asks = [(100.5, 10.0), (101.5, 100.0)]
    assert abs(mk.depth_within(bids, asks, 100.0) - (995 + 990 + 1005)) < 1e-9
    assert mk.depth_within(bids, asks, None) is None
    canned = _bybit_canned()
    inv = mk.read_bybit(lambda u: canned(u), 'inverse', 'BTCUSD', committed=100.0)
    # the book sizes are $1 contracts: 1,000 contracts at 100 is 1,000 of quote
    assert abs(inv['depth_1pct'] - 2000.0) < 1e-9, inv['depth_1pct']
    assert inv['volume_24h'] == 5_000_000.0                   # volume24h, not turnover


def spec_K4_funding_is_said_per_8h_whatever_the_venue_charges_by():
    assert abs(mk.funding_per_8h_pct(0.0001, 8.0) - 0.01) < 1e-12
    assert abs(mk.funding_per_8h_pct(0.0001, 4.0) - 0.02) < 1e-12     # Bybit 4 h coins
    assert abs(mk.funding_per_8h_pct(0.0000125, 1.0) - 0.01) < 1e-12  # HL, hourly
    assert mk.funding_per_8h_pct(None, 8.0) is None
    assert mk.base_of('BTCUSDT') == 'BTC' and mk.base_of('BTCPERP') == 'BTC'
    assert mk.base_of('ETHUSD') == 'ETH' and mk.base_of('SOL') == 'SOL'


def _bybit_canned(fail=()):
    closes = _zigzag(60)
    def fetch(url):
        if isinstance(url, urllib.request.Request):
            body = json.loads(url.data.decode())
            kind = body['type']
            if kind == 'metaAndAssetCtxs':
                return [{'universe': [{'name': 'BTC'}]},
                        [{'markPx': '100', 'dayNtlVlm': '2300000', 'openInterest': '52',
                          'funding': '0.0000125', 'oraclePx': '99', 'prevDayPx': '102'}]]
            if kind == 'l2Book':
                return {'levels': [[{'px': '99.5', 'sz': '3'}], [{'px': '100.5', 'sz': '3'}]]}
            if kind == 'candleSnapshot':
                return [{'t': i, 'o': c, 'h': c * 1.005, 'l': c * 0.995, 'c': c}
                        for i, c in enumerate(closes)]
            raise AssertionError(kind)
        for part in fail:
            if part in url:
                raise OSError('venue down')
        if '/market/tickers' in url:
            return {'result': {'list': [{'lastPrice': '100', 'price24hPcnt': '-0.017',
                                         'turnover24h': '52400000', 'volume24h': '5000000',
                                         'openInterest': '1400', 'fundingRate': '0.0001',
                                         'fundingIntervalHour': '4'}]}}
        if '/market/open-interest' in url:
            return {'result': {'list': [{'openInterest': '1400'}] + [{'openInterest': '1000'}] * 24}}
        if '/market/account-ratio' in url:
            return {'result': {'list': [{'buyRatio': '0.74', 'sellRatio': '0.26'}]}}
        if '/market/orderbook' in url:
            return {'result': {'b': [['99.5', '1000'], ['97', '9999']],
                               'a': [['100.5', '1000'], ['103', '9999']]}}
        if '/market/kline' in url:
            return {'result': {'list': [[str(i), c, c * 1.005, c * 0.995, c, '1', '1']
                                        for i, c in reversed(list(enumerate(closes)))]}}
        if 'announcements' in url:
            return {'result': {'list': [
                {'title': 'ByPick Season 1: Free picks', 'type': {'title': 'Latest Campaigns'}, 'publishTime': 1},
                {'title': 'Bybit to Delist 2 Token(s) on Oct 8', 'type': {'title': 'Delistings'}, 'publishTime': 2},
                {'title': 'Adjustments to BTCUSDT leverage tiers', 'type': {'title': 'Latest News'}, 'publishTime': 3}]}}
        if 'alternative.me' in url:
            return {'data': [{'value': str(v), 'value_classification': 'Greed'}
                             for v in [71] + [60] * 29]}
        if 'binance' in url:
            return {'lastFundingRate': '-0.00005'}
        if 'okx' in url:
            return {'data': [{'fundingRate': '0.00002'}]}
        if 'bitget' in url:
            return {'data': [{'fundingRate': '0.0001'}]}
        raise AssertionError(url)
    return fetch


def _fleets(d):
    f = d / 'fleet.json'
    f.write_text(json.dumps({'bots': [
        {'venue': 'bybit', 'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
         'capital': 1000, 'leverage': 10, 'lower': 70000, 'upper': 90000, 'rungs': 20},
        {'venue': 'hyperliquid', 'market_type': 'linear', 'symbol': 'BTC', 'side': 'long',
         'capital': 300, 'leverage': 25, 'lower': 70000, 'upper': 90000, 'rungs': 21}]}))
    return [str(f)]


def spec_K5_collect_keeps_every_reading_and_says_the_unread_part():
    d = Path(tempfile.mkdtemp())
    row = mk.collect(_fleets(d), fetch=_bybit_canned(fail=('account-ratio',)), now=1_800_000_000)
    b = row['markets']['bybit:linear:BTCUSDT']
    assert b['unread'] == {'ratio': 'OSError: venue down'} and b.get('long_pct') is None
    assert b['price'] == 100.0 and abs(b['funding_8h_pct'] - 0.02) < 1e-12   # 4 h coin
    assert abs(b['oi_change_24h_pct'] - 40.0) < 1e-9 and b['regime'] == 'ranging'
    assert b['committed'] == 10_000.0 and b['thin'] is False   # 200k resting vs 10k
    assert abs(b['depth_1pct'] - 200_000.0) < 1e-9
    h = row['markets']['hyperliquid:linear:BTC']
    assert abs(h['funding_8h_pct'] - 0.01) < 1e-12 and h['committed'] == 7500.0
    assert h['thin'] is True                                   # 600 resting: under the floor
    assert abs(h['change_24h_pct'] - (100 / 102 - 1) * 100) < 1e-9
    assert row['fear_greed']['score'] == 71 and row['fear_greed']['avg_30d'] == 60
    x = row['cross']['BTC']
    assert x['divergence'] is True and abs(x['binance'] + 0.005) < 1e-12
    titles = [a['title'] for a in row['announcements']]
    assert titles == ['Bybit to Delist 2 Token(s) on Oct 8', 'Adjustments to BTCUSDT leverage tiers']
    store = d / 'market.jsonl'
    mk.append(row, store)
    mk.append(dict(row, t=1_800_003_600), store)
    assert mk.latest(store)['t'] == 1_800_003_600
    assert mk.latest(d / 'none.jsonl') is None


def spec_K6_the_report_fits_telegram_and_says_each_coin_once():
    d = Path(tempfile.mkdtemp())
    row = mk.collect(_fleets(d), fetch=_bybit_canned(), now=1_800_000_000)
    msgs = mk.report(row, now=1_800_000_000)
    text = '\n'.join(msgs)
    assert text.count('📈 BTC') == 1 and 'ranging · ADX' in text
    assert 'Bybit 100' in text and 'HL 100' in text and 'THIN' in text
    assert 'crowded long 74/26' in text and '= 0× yours' in text
    assert 'elsewhere /8h: binance -0.005%' in text and '⚠️ disagree' in text
    assert '• Bybit to Delist' in text and 'ByPick' not in text
    assert text.endswith('readings only — nothing acts on them (D67)')
    wide = dict(row, markets={f'bybit:linear:{i}USDT': dict(row['markets']['bybit:linear:BTCUSDT'], symbol=f'C{i}USDT')
                              for i in range(40)})
    many = mk.report(wide, now=1_800_000_000)
    assert len(many) > 1 and all(len(m) <= mk.TG_CAP for m in many)
    stale = mk.report(row, now=1_800_000_000 + 7200)
    assert 'read 2.0 h ago' in stale[0]
    assert mk.session_name(1_800_000_000 + 0 * 3600) in ('Asia', 'Europe', 'US')


def spec_K7_the_readings_module_is_read_only_and_keyless():
    src = (Path(__file__).resolve().parents[1] / 'gridgremlin' / 'market.py').read_text()
    for word in ('api_key', 'api_secret', 'X-BAPI-SIGN', 'private_key', 'WriteClient',
                 'ExchangeClient', '/exchange', 'order/create', 'sign_l1'):
        assert word not in src, word
    assert 'from .bot' not in src and 'from .main' not in src


def spec_K8_the_phone_answers_market_from_the_kept_readings():
    from gridgremlin import phone
    d = Path(tempfile.mkdtemp())
    row = mk.collect(_fleets(d), fetch=_bybit_canned(), now=1_800_000_000)
    store, saved = d / 'market.jsonl', mk.STORE
    mk.STORE = str(store)
    try:
        assert 'no market readings yet' in phone.answer(object(), '/market')
        mk.append(row, store)
        said = phone.answer(object(), '/market')
        assert '📈 BTC' in said and 'readings only' in said
        assert '/market [n] —' in phone.cmd_help(None, [])
    finally:
        mk.STORE = saved


def spec_K9_the_newest_reading_sits_beside_each_bot_and_in_the_digest():
    d = Path(tempfile.mkdtemp())
    row = mk.collect(_fleets(d), fetch=_bybit_canned(), now=1_800_000_000)
    key_of = {'linBTCUSDTl': ('linear', 'BTCUSDT'), 'linBTCl': ('linear', 'BTC'),
              'linXRPUSDTs': ('linear', 'XRPUSDT')}
    venue_of = {('linear', 'BTCUSDT'): 'bybit', ('linear', 'BTC'): 'hyperliquid',
                ('linear', 'XRPUSDT'): 'bybit'}
    got = mk.for_bots(row, key_of, venue_of, now=1_800_000_000 + 600)
    assert got['linBTCUSDTl']['line'].startswith('ranging · ADX') and got['linBTCUSDTl']['thin'] is False
    assert got['linBTCl']['thin'] is True and got['linBTCl']['age_s'] == 600
    assert 'linXRPUSDTs' not in got                      # its market was not read
    assert mk.for_bots(None, key_of, venue_of) == {}
    block = mk.digest_block(row, now=1_800_000_000 + 5400)
    assert block[0] == 'market (read 1.5 h ago): fear & greed 71 (Greed)'
    assert block[1].startswith('BTC: ranging · ADX') and block[1].endswith('thin on HL')
    assert mk.digest_block(None) == ['market: no readings yet']
    from gridgremlin.digest import build
    store = d / 'market.jsonl'
    mk.append(row, store)
    text, _ = build([], now=1_800_000_000 + 60, market_store=str(store))
    assert 'market (read 1 min ago): fear & greed 71' in text and 'BTC: ranging' in text
    text, _ = build([], now=1_800_000_000, market_store=str(d / 'none.jsonl'))
    assert 'market: no readings yet' in text


def spec_K9_the_card_says_its_markets_regime_red_when_thin():
    import copy
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from spec_panel import CONTRACT, _everything
    c = copy.deepcopy(CONTRACT)
    c['market'] = {'spoADAUSDTl': {'line': 'ranging · ADX 18 · ATR 1.2%/4h',
                                   'thin': True, 'regime': 'ranging', 'age_s': 8000}}
    page = _everything(c)
    assert ('<div class="neg">market ranging · ADX 18 · ATR 1.2%/4h · THIN for this fleet'
            ' · read 2 h ago') in page
    c['market']['spoADAUSDTl'].update(thin=False, age_s=30)
    assert '<div class="dim">market ranging · ADX 18 · ATR 1.2%/4h</div>' in _everything(c)
    del c['market']
    assert 'market ranging' not in _everything(c)


def spec_K9_the_readout_contract_carries_the_market_words():
    import inspect
    from gridgremlin import report as rp
    assert "'market': _market_for(key_of, venue_of, now_ms)" in inspect.getsource(rp.main)
    d = Path(tempfile.mkdtemp())
    row = mk.collect(_fleets(d), fetch=_bybit_canned(), now=1_800_000_000)
    store, saved = d / 'market.jsonl', mk.STORE
    mk.STORE = str(store)
    try:
        mk.append(row, store)
        got = rp._market_for({'linBTCl': ('linear', 'BTC')},
                             {('linear', 'BTC'): 'hyperliquid'}, 1_800_000_000_000)
        assert got['linBTCl']['thin'] is True
        store.write_text('{not json')                 # a torn store: said, nothing
        assert rp._market_for({'linBTCl': ('linear', 'BTC')},
                              {('linear', 'BTC'): 'hyperliquid'}, 0) == {}
    finally:
        mk.STORE = saved


# --- K10: calm or wild — the hidden model's reading -------------------------------------

def spec_K10_the_hidden_model_recovers_a_known_one():
    import math
    import random
    from gridgremlin.hmm import best_fit, sample
    rng = random.Random(3)
    obs, _ = sample([0.5, 0.5], [[0.97, 0.03], [0.06, 0.94]], [0.0002, -0.0004],
                    [0.004 ** 2, 0.015 ** 2], 6000, rng)
    pi, A, mu, var, ll = best_fit(obs, 2)
    assert abs(A[0][0] - 0.97) < 0.02 and abs(A[1][1] - 0.94) < 0.03
    assert abs(math.sqrt(var[0]) - 0.004) < 0.0006 and abs(math.sqrt(var[1]) - 0.015) < 0.002
    assert var[0] < var[1]                                     # state 0 is always the calm one


def _hourly_feed(hours, wild_tail, seed=7, t_end=1_800_000_000_000):
    """A fake Bybit kline endpoint: `hours` hourly candles, calm (±0.25% an
    hour) then the last `wild_tail` wild (±2%)."""
    import random
    from urllib.parse import parse_qs, urlparse
    rng = random.Random(seed)
    c, rows = 100.0, []
    for i in range(hours):
        t = t_end - (hours - 1 - i) * 3_600_000
        c *= 1 + rng.gauss(0, 0.02 if i >= hours - wild_tail else 0.0025)
        rows.append([str(t), str(c), str(c * 1.001), str(c * 0.999), str(c), '1', '1'])
    calls = []

    def fetch(url):
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        calls.append(url)
        end, limit = int(q['end']), int(q['limit'])
        sel = [r for r in rows if int(r[0]) <= end][-limit:]
        return {'result': {'list': list(reversed(sel))}}           # newest first, as Bybit answers
    return fetch, calls, t_end


def spec_K10_the_reading_filters_hourly_from_a_daily_fit_and_says_calm_or_wild():
    from gridgremlin.market import HMM_REFIT_S, read_hmm
    fetch, calls, t_end = _hourly_feed(24 * 200, wild_tail=30)
    now = t_end / 1000 + 60
    cache = {}
    r = read_hmm(fetch, 'BTC', cache, now)
    assert r['state'] == 'wild' and r['p_wild'] > 0.9 and 20 <= r['spell_h'] <= 35
    assert r['sd_day'][0] < r['sd_day'][1] and r['fit_age_h'] < 0.1
    fitted = cache['BTC']['fit_t']
    n = len(calls)
    read_hmm(fetch, 'BTC', cache, now + 3600)                      # an hour later: the same fit
    assert cache['BTC']['fit_t'] == fitted and len(calls) == n + 1   # one page, the filter's
    read_hmm(fetch, 'BTC', cache, now + HMM_REFIT_S + 1)           # a day later: refitted
    assert cache['BTC']['fit_t'] > fitted
    assert r['separation'] > 5 and r['two_states'] and r['bic_gain'] > 10   # the states truly differ
    calm, _, t2 = _hourly_feed(24 * 200, wild_tail=0)
    flat = read_hmm(calm, 'ETH', {}, t2 / 1000)
    # no wild spell: two states are not worth their parameters, and it says so — never "wild"
    assert flat['two_states'] is False and flat['state'] == 'one regime' and 'p_wild' not in flat

    def down(url):
        raise OSError('no route')
    assert 'unread' in read_hmm(down, 'SOL', {}, now)               # never a crash, never a guess
    assert 'too few' in read_hmm(_hourly_feed(200, 0)[0], 'XRP', {}, t_end / 1000)['unread']


def spec_K10_the_newest_reading_is_read_from_the_end_of_the_file():
    import json
    import tempfile
    from pathlib import Path
    from gridgremlin.market import latest
    p = Path(tempfile.mkdtemp()) / 'market.jsonl'
    assert latest(p) is None
    big = 'x' * 30_000                                     # long lines: the tail window must grow
    p.write_text(''.join(json.dumps({'t': i, 'pad': big}) + '\n' for i in range(40)))
    assert latest(p)['t'] == 39
    p.write_text(json.dumps({'t': 1, 'pad': 'y' * 200_000}) + '\n')   # one line, longer than the window
    assert latest(p)['t'] == 1
    p.write_text(json.dumps({'t': 1}) + '\n' + json.dumps({'t': 2}) + '\n\n')
    assert latest(p)['t'] == 2


def spec_K10_the_reading_keeps_two_days_for_the_mini_chart():
    from gridgremlin.market import read_hmm
    fetch, _, t_end = _hourly_feed(24 * 200, wild_tail=10)
    r = read_hmm(fetch, 'BTC', {}, t_end / 1000 + 60)
    assert len(r['closes_48h']) == 48 and len(r['p_wild_48h']) == 48
    assert r['p_wild_48h'][-1] > 0.9 and r['p_wild_48h'][0] < 0.5          # the wild tail at the end
