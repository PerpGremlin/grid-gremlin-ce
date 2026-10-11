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


def spec_K11_the_how_it_decided_page_redoes_each_hour_from_the_reading():
    """The owner (2026-10-11): the calm-or-wild working, live, as a panel
    page. The reading carries its model (the transition table, each state's
    drift and spread); the page redoes every hour of the last two days in
    the filter's three steps — carry the belief forward, read each state's
    bell curve at the move, Bayes' rule — and lands on the model's own
    figure. A reading with no model, or one regime, says so."""
    from gridgremlin.market import read_hmm
    from panel.markets import decide_steps, decided_page, tile
    fetch, _, t_end = _hourly_feed(24 * 200, wild_tail=10)
    h = read_hmm(fetch, 'BTC', {}, t_end / 1000 + 60)
    assert {'A', 'mu', 'var'} <= set(h) and h['var'][0] < h['var'][1]        # state 1 is the wild one
    # the steps, against the filter itself on a model that switches often
    # (a feed that never switches hides a wrong row of the table)
    import math
    import random
    from gridgremlin.hmm import forward, sample
    A, mu, var = [[0.9, 0.1], [0.3, 0.7]], [0.0002, -0.0005], [0.003 ** 2, 0.012 ** 2]
    obs, _ = sample([0.75, 0.25], A, mu, var, 300, random.Random(5))
    alphas, _ = forward(obs, [0.75, 0.25], A, mu, var)
    closes = [100.0]
    for x in obs:
        closes.append(closes[-1] * math.exp(x))
    known = {'A': A, 'mu': mu, 'var': var, 'closes_48h': closes[-48:],
             'p_wild_48h': [a[1] for a in alphas[-48:]]}
    steps = decide_steps(known)
    assert len(steps) == 47 and steps[-1]['ago_h'] == 0
    for s in steps:                                                         # the page lands where the filter did
        assert abs(s['after'] - s['model']) < 1e-6, s
    assert any(s['after'] > 0.5 for s in steps) and any(s['after'] < 0.5 for s in steps)
    assert decide_steps(h)[-1]['after'] > 0.9                               # the live reading's wild tail
    row = {'t': t_end / 1000, 'markets': {'bybit:linear:BTCUSDT': {'symbol': 'BTCUSDT', 'committed': 1.0}},
           'hmm': {'BTC': h}}
    page = decided_page(row, 'BTC', now=t_end / 1000 + 120)
    assert '<h1>how it decided — BTC</h1>' in page
    assert 'carry the belief forward' in page and "Bayes' rule" in page and 'read the move' in page
    assert page.count('<tr><td>') >= 47 + 6                                # the model's table and every hour
    assert "The model's own figure:" in page
    old = {k: v for k, v in h.items() if k not in ('A', 'mu', 'var')}       # a reading from before K11
    assert decide_steps(old) == [] and 'appears from the next hourly reading' in decided_page(
        dict(row, hmm={'BTC': old}), 'BTC')
    assert 'one regime.' in decided_page(dict(row, hmm={'BTC': {'two_states': False, 'sd_day': [0.02],
                                                               'bic_gain': 3.0, 'fit_hours': 4320}}), 'BTC')
    assert 'href="/calm-wild?coin=BTC"' in tile('BTC', {'price': 1.0}, h)   # the tile leads to it


def _funding_feed(t_end=1_800_000_000_000, days=100, rate=0.0001, every_h=8, no_inverse=('DOT',)):
    """A fake Bybit: funding settlements every `every_h` hours at `rate`
    (the last 10 days at twice it), newest first in pages of 200; margin
    borrow rates; no inverse market for the coins in `no_inverse`."""
    from urllib.parse import parse_qs, urlparse
    calls = []
    def fetch(url):
        calls.append(url)
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if 'spot-margin-trade' in u.path:
            return {'result': {'vipCoinList': [{'list': [
                {'currency': 'USDT', 'hourlyBorrowRate': '0.0000044425670000'},
                {'currency': 'BTC', 'hourlyBorrowRate': '0.00000048'},
                {'currency': 'PEPE', 'hourlyBorrowRate': '0.00001'}]}]}}
        if q['category'] == 'inverse' and q['symbol'][:-3] in no_inverse:
            return {'retCode': 10001, 'retMsg': 'symbol invalid', 'result': {}}
        step = every_h * 3_600_000
        ts = [t for t in range(t_end - days * 86_400_000, t_end + 1, step) if t <= int(q['endTime'])]
        page = list(reversed(ts))[:int(q['limit'])]
        return {'retCode': 0, 'result': {'list': [
            {'symbol': q['symbol'], 'fundingRate': str(rate * (2 if t > t_end - 10 * 86_400_000 else 1)),
             'fundingRateTimestamp': str(t)} for t in page]}}
    return fetch, calls, t_end


def spec_K12_the_reading_says_what_a_short_was_paid_and_what_a_loan_costs():
    """The owner (2026-10-11), on the carry trade: the reading carries both
    sides — each coin's margin borrow rate (one call, every coin, a year)
    and what its perpetuals paid a short over the last settlement, 7, 30
    and 90 days (linear and inverse; a coin with no inverse has none), as a
    yearly rate whatever the settlement interval. The history is kept and
    refetched only as it settles."""
    from gridgremlin.market import CARRY_REFRESH_S, read_carry
    fetch, calls, t_end = _funding_feed()
    now = t_end / 1000 + 60
    cache = {}
    c = read_carry(fetch, ['BTC', 'DOT'], cache, now)
    assert abs(c['borrow_apr']['USDT'] - 0.0389169) < 1e-6 and 'PEPE' not in c['borrow_apr']
    btc = c['funding']['BTC']['linear']
    assert abs(btc['d90'] - (80 * 3 * 0.0001 + 10 * 3 * 0.0002) / 90 * 365) < 1e-9          # 270 settlements, paged
    assert abs(btc['d7'] - 0.0002 * 3 * 365) < 0.01 and abs(btc['last'] - 0.0002 * 3 * 365) < 1e-9
    assert btc['every_h'] == 8 and set(c['funding']['DOT']) == {'linear'}               # no inverse: none
    assert len(cache['linear:BTCUSDT']['h']) == 270 and cache['inverse:DOTUSD']['h'] == []
    n = len(calls)
    read_carry(fetch, ['BTC', 'DOT'], cache, now + 3600)                                # kept: one call
    assert len(calls) == n + 1
    read_carry(fetch, ['BTC', 'DOT'], cache, now + CARRY_REFRESH_S)                     # settled: refetched
    assert len(calls) > n + 2
    f4, _, _ = _funding_feed(every_h=4)                                                 # 4-hourly: the same year
    c4 = read_carry(f4, ['BTC'], {}, now)['funding']['BTC']['linear']
    assert c4['every_h'] == 4 and abs(c4['last'] - 0.0002 * 6 * 365) < 1e-9
    assert abs(c4['d7'] - 2 * btc['d7']) < 0.02                                         # twice the settlements, twice the pay
    short, _, _ = _funding_feed(days=20)                                                # too short for 90 days: none
    assert read_carry(short, ['BTC'], {}, now)['funding']['BTC']['linear']['d90'] is None


def _venues_feed(t_end=1_800_000_000_000, hours=600, okx_missing=('XAUT',), okx_no_spot=('XAU',), fail=()):
    """A fake Bybit, Binance and OKX answering every K13 endpoint: a flat
    price of 100 (index 99.9), retail 60% long, top traders 45%, OI 1,000
    coins, buys 10 over sells 8 an hour; OKX knows gold as XAU and has no
    gold spot; any URL containing a word in `fail` raises."""
    from urllib.parse import parse_qs, urlparse
    calls = []
    def fetch(url):
        calls.append(url)
        if any(f in url for f in fail):
            raise OSError('down')
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        lim = int(q.get('limit', 100))
        ts = [t_end - i * 3_600_000 for i in range(min(lim, hours))]           # newest first
        e8 = [t_end - i * 8 * 3_600_000 for i in range(min(lim, 200))]           # settlements, newest first
        if 'bybit' in u.netloc and 'funding/history' in u.path:
            if q['category'] == 'inverse' and q['symbol'] == 'XAUTUSD':
                return {'retCode': 10001, 'retMsg': 'params error: Symbol Invalid', 'result': {}}
            return {'retCode': 0, 'result': {'list': [{'fundingRate': '0.0001', 'fundingRateTimestamp': str(t)} for t in e8]}}
        if 'binance' in u.netloc and u.path.endswith('/fundingRate'):
            return [{'fundingTime': t + 3, 'fundingRate': '0.00005'} for t in reversed(e8)]     # stamped past the hour
        if 'okx' in u.netloc and 'funding-rate-history' in u.path:
            return {'code': '0', 'data': [{'fundingTime': str(t), 'fundingRate': '-0.00002', 'realizedRate': '-0.00002'}
                                          for t in [t_end - i * 3_600_000 for i in range(100)]]}   # hourly
        if 'bybit' in u.netloc:
            if u.path.endswith('/kline'):
                return {'result': {'list': [[str(t), '100', '100', '100', '100', '1', '1'] for t in ts]}}
            if 'index-price' in u.path:
                return {'result': {'list': [[str(t), '99.9', '99.9', '99.9', '99.9'] for t in ts]}}
            if 'account-ratio' in u.path:
                return {'result': {'list': [{'buyRatio': '0.6', 'sellRatio': '0.4', 'timestamp': str(t)} for t in ts]}}
            if 'open-interest' in u.path:
                return {'result': {'list': [{'openInterest': '1000', 'timestamp': str(t)} for t in ts]}}
            if 'orderbook' in u.path:
                return {'result': {'b': [['99.95', '10'], ['99.0', '5'], ['90', '100']],
                                   'a': [['100.05', '5'], ['100.9', '5'], ['110', '100']]}}
        if 'binance' in u.netloc:
            if u.path.endswith('/depth'):
                return {'bids': [['99.95', '10']], 'asks': [['100.05', '10']]}
            if u.path.endswith('/klines'):
                return [[t, '100', '100', '100', '100', '18', 0, '1800', 0, '10', '1000', '0'] for t in ts]
            ep = u.path.rsplit('/', 1)[1]
            row = {'globalLongShortAccountRatio': {'longAccount': '0.6'}, 'topLongShortAccountRatio': {'longAccount': '0.45'},
                   'topLongShortPositionRatio': {'longAccount': '0.45'}, 'openInterestHist': {'sumOpenInterestValue': '100000'},
                   'takerlongshortRatio': {'buyVol': '10', 'sellVol': '8'}}[ep]
            return [dict(row, timestamp=t) for t in reversed(ts)]
        if 'okx' in u.netloc:
            coin = q.get('ccy') or q.get('instId', '').split('-')[0]
            if coin in okx_missing or (coin in okx_no_spot and q.get('instType') == 'SPOT'):
                return {'code': '51012', 'msg': 'Token does not exist', 'data': []}
            if 'taker-volume' in u.path:
                return {'code': '0', 'data': [[str(t), '8', '10'] for t in ts[:72]]}
            if 'open-interest-volume' in u.path:
                return {'code': '0', 'data': [[str(t), '50000', '1'] for t in ts]}
            if 'top-trader' in u.path:
                return {'code': '0', 'data': [[str(t), str(0.45 / 0.55)] for t in ts[:100]]}
            return {'code': '0', 'data': [[str(t), '1.5'] for t in ts]}
        raise AssertionError(url)
    return fetch, calls, t_end


def spec_K13_each_coins_market_data_is_kept_a_month_from_the_big_venues():
    """The owner (2026-10-11): positioning of retail and the top traders
    across the big venues, open interest, basis, the book, spot net flows —
    each coin's series from Bybit, Binance and OKX, merged into a file and
    kept 30 days, refetched only for the last two days once fresh; each
    source fails alone and is named; OKX's own name for gold."""
    import tempfile
    from gridgremlin import marketdata as md
    fetch, calls, t_end = _venues_feed()
    now = t_end / 1000 + 60
    root = tempfile.mkdtemp()
    said = md.update(fetch, ['BTC', 'XAUT'], now, root=root, pause=lambda s: None)
    btc = md.load('BTC', root)
    lt = said['BTC']['latest']
    assert lt['price'] == 100.0 and abs(lt['basis.bybit'] - (100 / 99.9 - 1) * 100) < 1e-9
    assert lt['retail.bybit'] == 0.6 and lt['retail.binance'] == 0.6 and abs(lt['retail.okx'] - 0.6) < 1e-12
    assert lt['top.binance_positions'] == 0.45 and abs(lt['top.okx_positions'] - 0.45) < 1e-12
    assert lt['oi.bybit'] == 1000 * 100 and lt['oi.binance'] == 100000 and lt['oi.okx'] == 50000
    assert lt['taker.binance'] == 2 * 100 and lt['taker.okx'] == 2                          # coins × price; USD
    assert lt['spot.binance'] == 2 * 1000 - 1800 and lt['spot.okx'] == 2 * 100              # USD; coins × price
    assert abs(lt['spread.bybit'] - 0.1 / 100 * 1e4) < 1e-9
    assert abs(lt['depth.bybit'] - (99.95 * 10 + 99.0 * 5 + 100.05 * 5 + 100.9 * 5)) < 1e-6  # 90 and 110 are past 1%
    assert said['BTC']['unread'] == {}
    # funding as a yearly rate at each market's own interval: 8-hourly, Binance a few ms past, OKX hourly
    assert abs(lt['funding.bybit'] - 0.0001 * 3 * 365) < 1e-12 and abs(lt['funding.bybit_inverse'] - 0.1095) < 1e-12
    assert abs(lt['funding.binance'] - 0.00005 * 3 * 365) < 1e-12 and abs(lt['funding.okx'] + 0.00002 * 24 * 365) < 1e-12
    assert all(int(t) % 60_000 == 0 for t in btc['funding.binance'])                    # landed on the minute
    assert len(btc['price']) == 600 and len(btc['top.okx_positions']) == 100
    # OKX's gold is XAU, and it has no gold spot market: only that one is unread
    assert set(said['XAUT']['unread']) == {'spot.okx', 'funding.bybit_inverse'} and 'retail.okx' in said['XAUT']['latest']
    assert any('ccy=XAU&' in c for c in calls) and not any('ccy=XAUT' in c for c in calls)
    # fresh: the next hour asks for two days only
    calls.clear()
    md.update(fetch, ['BTC'], now + 3600, root=root, pause=lambda s: None)
    assert all('limit=' not in c or 'limit=48' in c or 'orderbook' in c or 'depth' in c for c in calls), calls
    # kept a month: points past 30 days are trimmed
    later = md.merge(btc, {'price': {t_end + 31 * 86_400_000: 101.0}}, t_end / 1000 + 31 * 86400)
    assert min(int(t) for t in later['price']) >= t_end + 86_400_000 and str(t_end + 31 * 86_400_000) in later['price']
    # one venue down: its sources are named, the rest are read
    down, _, _ = _venues_feed(fail=('binance.com',))
    d = md.update(down, ['BTC'], now, root=tempfile.mkdtemp(), pause=lambda s: None)['BTC']
    assert {n for n in d['unread']} == {'retail.binance', 'top.binance_accounts', 'top.binance_positions',
                                        'oi.binance', 'taker.binance', 'spot.binance', 'funding.binance',
                                        'spread.binance', 'depth.binance', 'imbalance.binance'}
    assert 'retail.okx' in d['latest'] and 'price' in d['latest']
    # the day's summary: OI summed over the venues, its change, the day's flow
    day = said['BTC']['day']
    assert day['oi'] == 100000 + 100000 + 50000 and abs(day['oi_24h_pct']) < 1e-9
    assert day['taker_24h'] == 24 * 200 + 24 * 2 and day['spot_24h'] == 24 * 200 + 24 * 200


def spec_U71_a_coins_page_charts_its_market_data():
    """The owner (2026-10-11): an overview per asset, like Bybit's data tab
    — a chart for each kind of market data, the price behind, a day, a week
    or a month; what each says; an unread source named."""
    import tempfile
    from gridgremlin import marketdata as md
    from panel.asset import CHARTS, asset_page
    fetch, _, t_end = _venues_feed()
    now = t_end / 1000 + 60
    root = tempfile.mkdtemp()
    md.update(fetch, ['BTC'], now, root=root, pause=lambda s: None)
    page = asset_page('BTC', ['BTC', 'ETH'], '7d', now=now, root=root, unread={'oi.okx': 'HTTPError'})
    assert '<h1>BTC <span class="dim">market data</span></h1>' in page
    assert '<b class="on">7 days</b>' in page and 'href="/asset?coin=ETH&span=7d"' in page
    for heading, *_ in CHARTS:                                             # every kind, each its chart
        assert f'<h2>{heading.replace("&", "&amp;")}</h2>' in page, heading
    assert page.count('<svg class="achart"') == len(CHARTS)
    assert 'Not read this hour: OKX.' in page
    assert 'Binance, by position size <b class="">45.0%</b>' in page        # the legend's latest
    assert 'stroke="var(--dim)"' in page                                   # the price behind
    assert 'fill="var(--pos)"' in page                                     # flow as bars, buys above
    day = asset_page('BTC', ['BTC'], '24h', now=now, root=root)
    assert '<b class="on">24 hours</b>' in day
    assert 'nothing kept for this coin yet' in asset_page('ETH', ['BTC', 'ETH'], '7d', now=now, root=root)


def _collector_feed(t_ms, liq_rows=250, mid=100.0):
    """A fake Coinbase and OKX for the collector: books around `mid` with a
    wall 2% below, OKX contracts of 0.1 coin, and `liq_rows` liquidations a
    minute apart ending at t_ms, served newest first in pages of 100."""
    from urllib.parse import parse_qs, urlparse
    calls = []
    def fetch(url):
        calls.append(url)
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if 'coinbase' in u.netloc:
            if '/XAUT-USD/' in u.path:
                raise OSError('404')
            return {'bids': [[str(mid - 0.01), '5', 1], [str(mid * 0.98), '1000', 3], [str(mid * 0.5), '9999', 1]],
                    'asks': [[str(mid + 0.01), '5', 1], [str(mid * 1.03), '200', 2]]}
        if 'instruments' in u.path:
            return {'code': '0', 'data': [{'instId': f'{c}-USDT-SWAP', 'ctVal': '0.1'} for c in ('BTC', 'XAU')]}
        if 'books-full' in u.path:
            return {'code': '0', 'data': [{'bids': [[str(mid - 0.02), '10', '0', '1']], 'asks': [[str(mid + 0.02), '10', '0', '1']]}]}
        if 'liquidation-orders' in u.path:
            after = int(q['after']) if 'after' in q else None
            ts = [t_ms - i * 60_000 for i in range(liq_rows)]
            ts = [t for t in ts if after is None or t < after][:100]
            return {'code': '0', 'data': [{'details': [
                {'ts': str(t), 'posSide': 'long' if (t // 60_000) % 2 else 'short', 'side': 'sell', 'bkPx': '99.5',
                 'sz': '2'} for t in ts]}]}
        raise AssertionError(url)
    return fetch, calls


def spec_K14_the_collector_records_the_books_and_every_liquidation():
    """D84 (granted 2026-10-11): the books and the liquidations, recorded as
    they happen. The books — Coinbase's whole spot book and OKX's deep
    perpetual one — summed into 0.1% bands of a reference price held for the
    day, within ±5% of the mid; OKX's liquidations in coins and USD (its
    contracts × their value), paged back until they meet the last run so a
    burst is not lost; seven days kept; a venue missing for a coin (gold on
    Coinbase) not asked, the rest read."""
    import tempfile
    from gridgremlin import collector as c
    c._CT.clear()
    now = 1_800_000_000.0
    fetch, calls = _collector_feed(int(now * 1000))
    root = tempfile.mkdtemp()
    said = c.run(fetch, ['BTC', 'XAUT'], now, root=root)
    row = c.read_days('BTC', 'book', now - 60, root)[-1]
    assert abs(row['mid'] - 100.0) < 1e-9 and row['ref'] == row['mid'] and row['band'] == 0.001
    wall = row['bids'][str(math_floor((0.98 - 1) / 0.001))]
    assert wall == round(98.0 * 1000)                                      # the wall 2% below, in its band
    assert all(-51 <= int(k) <= 50 for k in list(row['bids']) + list(row['asks']))   # ±5%: the 50% bid is out
    assert sum(1 for _ in row['asks']) == 2                                # near ask + the 3% one (OKX's in band 0)
    liq = c.read_days('BTC', 'liq', now - 7200, root)
    assert len(liq) == 60 and liq[-1]['coins'] == 0.2 and abs(liq[-1]['usd'] - 0.2 * 99.5) < 1e-9   # the first hour
    assert {x['side'] for x in liq} == {'long', 'short'}
    assert said['XAUT']['unread'] == {} and said['XAUT']['mid'] is not None   # gold: OKX alone, Coinbase not asked
    assert not any('/XAUT-USD/' in u for u in calls)
    # the next run, ten minutes on: ten new liquidations, none twice; the day's reference kept
    fetch2, calls2 = _collector_feed(int((now + 600) * 1000), mid=101.0)
    c.run(fetch2, ['BTC'], now + 600, root=root)
    liq = c.read_days('BTC', 'liq', now - 7200, root)
    assert len(liq) == 70 and len({x['ts'] for x in liq}) == 70
    assert c.read_days('BTC', 'book', now - 60, root)[-1]['ref'] == row['ref']
    # a burst: 250 since the last run — paged back to meet it
    c._CT.clear()
    burst, bcalls = _collector_feed(int((now + 1200) * 1000), liq_rows=400)
    import json as _j
    st = _j.loads((Path(root) / 'state.json').read_text())
    st['BTC']['liq_ms'] = int((now + 1200) * 1000) - 250 * 60_000
    (Path(root) / 'state.json').write_text(_j.dumps(st))
    c.run(burst, ['BTC'], now + 1200, root=root)
    assert sum(1 for u in bcalls if 'liquidation-orders' in u) == 3        # three pages of 100
    # seven days kept
    old = Path(root) / 'BTC' / 'book-2020-01-01.jsonl'
    old.write_text('{}\n')
    c.run(fetch, ['BTC'], now + 1800, root=root)
    assert not old.exists()


def math_floor(x):
    import math
    return math.floor(x)


def spec_U74_a_coins_page_shows_the_book_heatmap_and_its_liquidations():
    """D84's page half: the last day's book as a heatmap — time across, price
    up the side, bids and asks shaded by size, the price over it — and the
    liquidations as hourly bars, longs below the line and shorts above, with
    the largest listed. Nothing collected: said."""
    import tempfile
    from gridgremlin import collector as c
    from panel.asset import heatmap, liquidations
    c._CT.clear()
    now = 1_800_000_000.0
    root = tempfile.mkdtemp()
    for i in range(6):
        fetch, _ = _collector_feed(int((now + i * 300) * 1000), mid=100.0 + i * 0.1)
        c.run(fetch, ['BTC'], now + i * 300, root=root)
    h = heatmap('BTC', now + 1800, root)
    assert '<svg class="achart"' in h and 'fill="var(--pos)"' in h and 'fill="var(--neg)"' in h and '<polyline' in h
    assert '6 snapshots' in h and 'The largest band now: bids' in h
    lq = liquidations('BTC', now + 1800, 1, root)
    assert 'longs liquidated' in lq and 'shorts liquidated' in lq and '<td class="neg">long</td>' in lq
    assert 'nothing collected for this coin yet' in heatmap('ETH', now, root)
    assert 'no liquidations recorded' in liquidations('ETH', now, 1, root)
