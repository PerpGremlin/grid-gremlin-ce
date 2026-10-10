"""J1/J3 (D80/D81): the agent's limits, its intents and its one door."""
import inspect
import json
import tempfile
from pathlib import Path

from gridgremlin.agent import (check_intent, day_loss, intents_since, read_state, submit,
                               validate_agent)
from gridgremlin.agent_door import VERBS, handle
from gridgremlin.config import ConfigError, validate_fleet

LIMITS = {'markets': ['BTCUSDT', 'ETHUSDT'], 'max_notional': 1000, 'max_gross': 1500, 'max_leverage': 5,
          'max_loss_day': 100, 'max_intents_hour': 3, 'min_stop_pct': 0.003, 'max_stop_pct': 0.03,
          'session_utc': [0, 24]}
GOOD = {'market': 'btcusdt', 'side': 'long', 'size_quote': 100, 'leverage': 5, 'stop_pct': 0.01,
        'tp_pct': 0.015, 'reason': 'held the 4h low with a volume spike', 'confidence': 0.6}
CLEAR = {'open': [], 'intents_last_hour': 0, 'day_loss': 0.0, 'tombstoned': set()}
NOON = 20_000 * 86_400 + 12 * 3600


def _refused(fn, *a):
    try:
        fn(*a)
    except ConfigError as e:
        return str(e)
    raise AssertionError(f'{a} was accepted')


def spec_J3_the_owners_limits_are_all_stated_paper_is_the_default():
    lim = validate_agent(dict(LIMITS))
    assert lim['paper'] is True and lim['markets'] == ['BTCUSDT', 'ETHUSDT']
    assert validate_agent(dict(LIMITS, paper=False))['paper'] is False
    for k in ('markets', 'max_notional', 'max_gross', 'max_leverage', 'max_loss_day', 'max_intents_hour',
              'min_stop_pct', 'max_stop_pct'):
        assert _refused(validate_agent, {x: v for x, v in LIMITS.items() if x != k}), k
    assert 'above' in _refused(validate_agent, dict(LIMITS, min_stop_pct=0.05))
    assert 'no trade could ever open' in _refused(validate_agent, dict(LIMITS, max_gross=500))
    assert 'session_utc' in _refused(validate_agent, dict(LIMITS, session_utc=[20, 8]))
    assert _refused(validate_agent, dict(LIMITS, withdraw=True))            # unknown keys refused
    f = validate_fleet({'account': 'agent', 'agent': dict(LIMITS)})          # an agent fleet may start botless
    assert f['bots'] == [] and f['agent']['max_leverage'] == 5
    assert 'non-empty' in _refused(validate_fleet, {'bots': []})            # any other fleet may not


def spec_J3_every_limit_refuses_by_name_sabotage():
    lim = validate_agent(dict(LIMITS))
    row = check_intent(dict(GOOD), lim, CLEAR, NOON)
    assert row['symbol'] == 'BTCUSDT' and row['capital'] == 100 and row['leverage'] == 5
    assert row['stop'] == {'watch': 'mark_price', 'from_base_pct': 0.01} and row['by'] == 'agent'
    from gridgremlin.trades import validate_trade
    validate_trade(dict(row))                                               # D81's validator takes it
    cases = {
        'not one the agent may trade': dict(GOOD, market='SOLUSDT'),
        'long or short': dict(GOOD, side='up'),
        "above the agent's 5": dict(GOOD, leverage=10),
        'a trade': dict(GOOD, size_quote=300),                               # 1500 notional
        'a stop is required': {k: v for k, v in GOOD.items() if k != 'stop_pct'},
        'outside the agent': dict(GOOD, stop_pct=0.001),
        'tp_pct': {k: v for k, v in GOOD.items() if k != 'tp_pct'},
        'market or maker': dict(GOOD, entry='limit'),
    }
    for words, intent in cases.items():
        assert words in _refused(check_intent, intent, lim, CLEAR, NOON), words
    assert 'gross' in _refused(check_intent, dict(GOOD), lim, dict(CLEAR, open=[{'notional': 1200}]), NOON)
    assert 'intents this hour' in _refused(check_intent, dict(GOOD), lim, dict(CLEAR, intents_last_hour=3), NOON)
    assert 'stood down until 00:00 UTC' in _refused(check_intent, dict(GOOD), lim, dict(CLEAR, day_loss=100), NOON)
    night = validate_agent(dict(LIMITS, session_utc=[13, 21]))
    assert 'outside the agent\'s session' in _refused(check_intent, dict(GOOD), night, CLEAR, NOON)
    assert _refused(check_intent, dict(GOOD, withdraw='all'), lim, CLEAR, NOON)   # unknown keys refused
    maker = check_intent(dict(GOOD, entry='maker', trail_pct=0.004, trail_from_pct=0.01), lim, CLEAR, NOON)
    assert maker['start_order_type'] == 'maker' and maker['trailing_activation_pct'] == 0.01
    assert len(check_intent(dict(GOOD, reason='x' * 900), lim, CLEAR, NOON)['reason']) == 500


def _fleet(paper=True):
    d = Path(tempfile.mkdtemp())
    (d / 'configs').mkdir()
    (d / 'logs').mkdir()
    f = d / 'configs' / 'fleet.agent.json'
    (d / 'configs' / 'watchdog.agent.json').write_text(json.dumps({'snapshot': 'logs/snapshots-agent.jsonl'}))
    f.write_text(json.dumps({'account': 'agent', 'agent': dict(LIMITS, paper=paper),
                             'watchdog': 'configs/watchdog.agent.json'}))
    return d, f


def spec_J3_a_live_agent_fleet_names_the_watchdog_its_day_loss_is_read_from():
    from gridgremlin.config import validate_fleet
    assert validate_fleet({'account': 'agent', 'agent': dict(LIMITS)})['agent']['paper']   # paper needs none
    _refused(validate_fleet, {'account': 'agent', 'agent': dict(LIMITS, paper=False)})
    try:
        validate_fleet({'account': 'agent', 'agent': dict(LIMITS, paper=False)})
    except ConfigError as e:
        assert "names its 'watchdog'" in str(e) and 'J3' in str(e)


def _market(path, **others):
    """A fake Bybit kline endpoint over 1m candles {t_ms: (o, h, l, c)} —
    BTCUSDT's, and any other symbol's by name: what the paper book reads
    instead of the network."""
    from urllib.parse import parse_qs, urlparse
    tapes = {'BTCUSDT': path, **others}

    def fetch(url):
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        lo, hi = int(q['start']), int(q['end'])
        path = tapes[q['symbol']]
        rows = [[str(t), str(o), str(h), str(l), str(c), '1', '1']
                for t, (o, h, l, c) in sorted(path.items(), reverse=True) if lo <= t <= hi]
        return {'result': {'list': rows}}
    return fetch


def _flat_market(price=60000.0, t0=NOON * 1000 - 600_000, n=2000):
    return _market({t0 + i * 60_000: (price, price, price, price) for i in range(n)})


def spec_J3_paper_logs_and_sends_nothing_live_queues_a_trade_every_intent_is_logged():
    d, f = _fleet(paper=True)
    v, text = submit(f, dict(GOOD), NOON, _flat_market())
    assert v == 'paper' and 'nothing sent' in text and not (d / 'logs' / 'trades-agent.json').exists()
    v, text = submit(f, dict(GOOD, market='SOLUSDT'), NOON + 1, _flat_market())
    assert v == 'refused' and 'SOLUSDT' in text
    log = intents_since(d / 'logs' / 'agent-intents-agent.jsonl', 0)
    assert [e['verdict'] for e in log] == ['paper', 'refused'] and log[0]['intent']['reason'].startswith('held')
    d, f = _fleet(paper=False)
    v, text = submit(f, dict(GOOD), NOON)
    assert v == 'queued' and text.startswith('linBTCUSDTl: queued')
    rows = json.loads((d / 'logs' / 'trades-agent.json').read_text())
    assert rows[0]['by'] == 'agent' and rows[0]['confidence'] == 0.6 and rows[0]['symbol'] == 'BTCUSDT'
    st = read_state(f, NOON + 5)
    assert st['open'][0]['botid'] == 'linBTCUSDTl' and st['open'][0]['notional'] == 500
    assert st['intents_last_hour'] == 1
    v, text = submit(f, dict(GOOD), NOON + 6)                               # the same market and side again
    assert v == 'refused' and 'already in the file' in text
    (d / 'logs' / 'tombstones-agent.json').write_text(json.dumps({'linBTCUSDTl': {'reason': 'tp'}}))
    assert read_state(f, NOON + 7)['open'] == []                           # an ended trade frees the gross


def spec_J3_todays_loss_is_the_agents_account_since_midnight_utc():
    d = Path(tempfile.mkdtemp())
    p = d / 'snapshots-agent.jsonl'
    day = 20_000 * 86_400
    rows = [(day - 600, 999.0), (day + 60, 1000.0), (day + 3600, 950.0), (day + 7200, 930.0)]
    p.write_text(''.join(json.dumps({'t': t, 'equity': e, 'bots': {}}) + '\n' for t, e in rows))
    assert day_loss(str(p), day + 7300) == 70.0
    p.write_text(''.join(json.dumps({'t': t, 'equity': e + i * 50, 'bots': {}}) + '\n'
                         for i, (t, e) in enumerate(rows)))
    assert day_loss(str(p), day + 7300) == 0.0                              # a profitable day: no loss
    assert day_loss(None, day) == 0.0 and day_loss(str(d / 'none.jsonl'), day) == 0.0


def spec_J1_the_door_has_two_verbs_and_the_owner_names_the_fleet():
    """The verb list is the door's whole surface: a spec holds it, so a third
    verb (a config edit, a unit, a close) cannot creep in unreviewed. The
    fleet comes from the owner's key line (argv), never from the agent."""
    assert VERBS == ('read', 'intent')
    d, f = _fleet(paper=True)
    code, text = handle(str(f), 'rm -rf /', NOON)
    assert code == 2 and 'the door knows read, intent' in text
    code, text = handle(str(f), '', NOON)
    assert code == 2
    code, text = handle(str(f), 'read', NOON, _flat_market())
    got = json.loads(text)
    assert code == 0 and got['paper'] is True and got['intents_left_this_hour'] == 3 and got['open'] == []
    code, text = handle(str(f), 'intent ' + json.dumps(GOOD), NOON, _flat_market())
    assert code == 0 and json.loads(text)['verdict'] == 'paper'      # a fake market: specs never fetch (T12)
    code, text = handle(str(f), 'intent {not json', NOON)
    assert code == 1 and 'not JSON' in text
    plain = Path(tempfile.mkdtemp()) / 'fleet.json'
    plain.write_text(json.dumps({'bots': [{'market_type': 'linear', 'symbol': 'ETHUSDT', 'side': 'long',
                                           'capital': 100.0, 'leverage': 5, 'upper': 3000.0, 'lower': 2000.0,
                                           'rungs': 11}]}))
    assert 'no agent block' in handle(str(plain), 'read', NOON)[1]
    from gridgremlin import agent_door
    src = inspect.getsource(agent_door.main)
    assert "os.environ.get('SSH_ORIGINAL_COMMAND'" in src and 'argv[0]' in src


def spec_J3_an_agent_fleet_opens_its_venue_client_with_the_mainnet_gate():
    from gridgremlin import main as m
    src = inspect.getsource(m.build_fleet)
    i = src.index("if fleet.get('agent') and 'bybit' not in clients")
    assert 'refuse_mainnet(' in src[i:i + 500]


# --- J6.1: the paper book -----------------------------------------------------------

T0 = 999_999_960_000                             # on a minute boundary

def _pos(side='long', entry=100.0, stop=0.01, tp=0.02, trail=None, arm=None):
    from gridgremlin.agent_paper import open_position
    row = {'symbol': 'BTCUSDT', 'side': side, 'capital': 100.0, 'leverage': 5.0,
           'take_profit_avg_pct': tp, 'stop': {'watch': 'mark_price', 'from_base_pct': stop}}
    if trail:
        row['trailing_stop_pct'] = trail
        if arm:
            row['trailing_activation_pct'] = arm
    return open_position(row, entry, T0 + 30_000, "p1")             # mid-minute


def _c(i, o, h, l, c):
    return {"t": T0 + i * 60_000, 'o': o, 'h': h, 'l': l, 'c': c}


def spec_J6_paper_the_candles_after_entry_decide_stop_gap_take_profit_and_trail():
    from gridgremlin.agent_paper import walk
    p = _pos()                                   # long at 100, stop 99, take profit 102
    assert abs(p['stop'] - 99.0) < 1e-9 and abs(p['tp'] - 102.0) < 1e-9
    # the entry's own minute never judges it: it began before the fill
    assert walk(p, [_c(0, 100, 105, 90, 100)]) is None
    assert walk(p, [_c(1, 100, 100.5, 99.5, 100), _c(2, 100, 100.2, 98.9, 99)]) == \
        {'how': 'stop', 'price': 99.0, 't': _c(2, 0, 0, 0, 0)['t']}
    assert walk(p, [_c(1, 97, 98, 96, 97)])['price'] == 97               # a gap fills at the open
    assert walk(p, [_c(1, 100, 102.5, 99.5, 102)])['how'] == 'take_profit'
    assert walk(p, [_c(1, 100, 103, 98, 100)])['how'] == 'stop'          # both in one candle: the worse
    s = _pos(side='short')                       # short at 100, stop 101, take profit 98
    assert walk(s, [_c(1, 100, 101.2, 99.8, 101)])['how'] == 'stop'
    assert walk(s, [_c(1, 100, 100.4, 97.9, 98)])['how'] == 'take_profit'
    # a 1% trail armed after +0.5%: up to 101.5, then back through 100.485
    t = _pos(tp=0.05, trail=0.01, arm=0.005)
    hit = walk(t, [_c(1, 100, 101.5, 100, 101.4), _c(2, 101.4, 101.4, 100.3, 100.4)])
    assert hit['how'] == 'stop' and abs(hit['price'] - 101.5 * 0.99) < 1e-9


def spec_J6_paper_fees_both_sides_and_a_close_at_the_last_price():
    from gridgremlin.agent_paper import close_now, settle
    from gridgremlin.fees import BYBIT_MAKER, BYBIT_TAKER
    p = _pos()                                   # 500 notional, 5 coins at 100
    won = settle(p, [_c(1, 100, 102.5, 99.5, 102)], 102, 0)['closed']
    assert abs(won['pnl'] - (5 * 2 - 500 * BYBIT_TAKER - 5 * 102 * BYBIT_MAKER)) < 1e-9
    lost = settle(p, [_c(1, 100, 100, 98, 98.5)], 98.5, 0)['closed']
    assert abs(lost['pnl'] - (-5 - 500 * BYBIT_TAKER - 5 * 99 * BYBIT_TAKER)) < 1e-9
    open_ = settle(p, [_c(1, 100, 101, 99.5, 101)], 101, 0)
    assert open_['closed'] is None and open_['open_pnl'] > 0
    shut = close_now(p, [_c(1, 100, 101, 99.5, 101)], 101, 5)['closed']
    assert shut['how'] == 'close' and shut['price'] == 101 and shut['t'] == 5
    # a close after the candles already stopped it keeps the stop
    assert close_now(p, [_c(1, 100, 100, 98, 98.5)], 98.5, 5)['closed']['how'] == 'stop'


def spec_J6_paper_end_to_end_the_book_judges_closes_and_limits_by_itself():
    from gridgremlin.agent import read_state
    from gridgremlin.agent_door import handle
    d, f = _fleet(paper=True)
    t0 = NOON * 1000
    tape = {t0 - 600_000 + i * 60_000: (60000.0, 60000.0, 60000.0, 60000.0) for i in range(11)}
    eth = {t0 - 600_000 + i * 60_000: (3000.0,) * 4 for i in range(20)}
    m = _market(tape, ETHUSDT=eth)
    v, text = submit(f, dict(GOOD), NOON, m)                # long 500 at 60000: stop 59400, tp 60900
    assert v == 'paper' and 'p1' in text
    v, _ = submit(f, dict(GOOD, market='ethusdt', size_quote=200), NOON + 1, m)
    assert v == 'paper'
    # the gross counts paper positions: 500 + 1000 + 500 is above 1500
    v, text = submit(f, dict(GOOD), NOON + 2, m)
    assert v == 'refused' and 'gross' in text
    # the market falls through the stop four minutes later
    tape.update({t0 + 240_000: (60000.0, 60000.0, 59300.0, 59350.0), t0 + 300_000: (59350.0,) * 4})
    st = read_state(f, NOON + 400, True, _market(tape, ETHUSDT=eth))
    assert [p['symbol'] for p in st['open']] == ['ETHUSDT']   # the BTC one stopped; ETH stands
    code, out = handle(f, 'read', NOON + 400, _market(tape, ETHUSDT=eth))
    got = json.loads(out)
    assert code == 0 and got['paper'] and got['closed_today'][0]['how'] == 'stop'
    assert got['closed_today'][0]['price'] == 59400.0 and got['day_loss'] > 5
    # a close of a market with nothing open is refused, named
    v, text = submit(f, {'market': 'BTCUSDT', 'side': 'close'}, NOON + 401, _market(tape, ETHUSDT=eth))
    assert v == 'refused' and 'no open paper position' in text


def spec_J6_paper_close_ignores_the_hour_and_the_session_and_live_close_is_refused():
    d, f = _fleet(paper=True)
    m = _flat_market()
    assert submit(f, dict(GOOD), NOON, m)[0] == 'paper'
    for i in range(3):
        submit(f, dict(GOOD, market='SOLUSDT'), NOON + 1 + i, m)      # spend the hour's three intents
    assert submit(f, dict(GOOD, market='ethusdt'), NOON + 5, m)[0] == 'refused'
    v, text = submit(f, {'market': 'btcusdt', 'side': 'close', 'reason': 'done'}, NOON + 6, m)
    assert v == 'closed' and 'p1' in text and 'by close' in text
    log = intents_since(d / 'logs' / 'agent-intents-agent.jsonl', 0)
    assert log[-1]['verdict'] == 'closed' and log[-1]['closed'][0]['how'] == 'close'
    d, f = _fleet(paper=False)
    v, text = submit(f, {'market': 'BTCUSDT', 'side': 'close'}, NOON, m)
    assert v == 'refused' and 'no open trade' in text                     # live: nothing of its own there



# --- J5: the score ---------------------------------------------------------------------

def _closed(pnl, conf, t, how='take_profit', fees=1.0):
    return {'id': f'p{t}', 'confidence': conf, 'closed': {'how': how, 'pnl': pnl, 'fees': fees, 't': t}}


def spec_J5_the_score_is_pnl_drawdown_hit_rate_fees_and_calibration_with_no_early_verdict():
    from gridgremlin.agent_score import VERDICT_TRADES, render, score
    book = [_closed(10, 0.8, 1), _closed(-4, 0.3, 2, 'stop'), _closed(-6, 0.6, 3, 'stop'),
            _closed(8, 0.75, 4), _closed(-2, 0.4, 5, 'close'), {'id': 'open', 'closed': None}]
    s = score(book)
    assert s['closed'] == 5 and s['open'] == 1 and s['pnl'] == 6 and s['vs_flat'] == 6
    assert s['max_drawdown'] == 10                       # +10, then -4 and -6: down 10 from the peak
    assert s['hit_rate'] == 0.4 and s['avg_win'] == 9 and s['avg_loss'] == -4
    assert abs(s['fees_share'] - 5 / 35) < 1e-12         # 5 of fees over |pnl| 30 + fees 5
    assert s['by_how'] == {'close': 1, 'stop': 2, 'take_profit': 2}
    bands = {b['band']: (b['trades'], b['hit_rate']) for b in s['calibration']}
    assert bands == {'below 0.5': (2, 0.0), '0.5 to 0.7': (1, 0.0), '0.7 and above': (2, 1.0)}
    assert s['calibrated'] is True and s['verdict_in'] == VERDICT_TRADES - 5
    # confidence that does not order the outcomes is said
    worse = [_closed(5, 0.2, 1), _closed(-5, 0.9, 2, 'stop')]
    assert score(worse)['calibrated'] is False and 'does not order' in render(score(worse))
    text = render(s)
    assert 'no verdict: 195 closed trades to go' in text and '(flat: +0.00)' in text
    assert score([])['hit_rate'] is None and 'nothing yet' in render(score([]))


# --- L7 for the agent: a live close and the day's loss, as close requests ----------------

def spec_J3_live_the_agents_close_and_its_day_loss_both_ask_the_fleet_to_close():
    from gridgremlin.agent import enforce_day_loss
    d, f = _fleet(paper=False)
    assert submit(f, dict(GOOD), NOON)[0] == 'queued'
    assert submit(f, dict(GOOD, market='ethusdt', size_quote=150), NOON + 1)[0] == 'queued'
    v, text = submit(f, {'market': 'btcusdt', 'side': 'close', 'reason': 'thesis broken'}, NOON + 2)
    assert v == 'close_requested' and 'linBTCUSDTl: close requested' in text
    rows = {r['symbol']: r for r in json.loads((d / 'logs' / 'trades-agent.json').read_text())}
    assert rows['BTCUSDT']['close']['by'] == 'agent' and rows['BTCUSDT']['close']['reason'] == 'thesis broken'
    assert 'close' not in rows['ETHUSDT']
    lim = validate_agent(dict(LIMITS, paper=False))
    snap = d / 'logs' / 'snapshots-agent.jsonl'
    day = NOON - NOON % 86_400
    snap.write_text(''.join(json.dumps({'t': t, 'equity': e, 'bots': {}}) + '\n'
                            for t, e in ((day + 60, 1000.0), (NOON, 950.0))))
    assert enforce_day_loss(f, lim, NOON + 3) == []                         # down 50 of 100: nothing
    snap.write_text(snap.read_text() + json.dumps({'t': NOON + 4, 'equity': 899.0, 'bots': {}}) + '\n')
    asked = enforce_day_loss(f, lim, NOON + 5)
    assert sorted(asked) == ['linBTCUSDTl', 'linETHUSDTl']
    rows = {r['symbol']: r for r in json.loads((d / 'logs' / 'trades-agent.json').read_text())}
    assert rows['BTCUSDT']['close']['by'] == 'agent'                        # the first request stands
    assert rows['ETHUSDT']['close']['by'] == 'engine' and 'reached its limit 100' in rows['ETHUSDT']['close']['reason']
    assert enforce_day_loss(f, validate_agent(dict(LIMITS)), NOON + 6) == []  # paper: the door's book, not here


def spec_J5_the_digest_carries_the_agents_score():
    from gridgremlin.agent_paper import book_path, save_book
    from gridgremlin.digest import agent_lines
    d, f = _fleet(paper=True)
    lim = validate_agent(dict(LIMITS))
    assert 'closed 0 · open 0' in agent_lines(f, lim)[0]
    save_book(book_path(f), [_closed(10, 0.8, 1), _closed(-4, 0.3, 2, 'stop')])
    text = agent_lines(f, lim)[0]
    assert text.startswith('agent (paper): closed 2') and 'P&L after fees +6.00' in text
    assert 'no verdict: 198 closed trades to go' in text
    assert 'paper book only' in agent_lines(f, validate_agent(dict(LIMITS, paper=False)))[0]



def spec_J5_the_panel_draws_the_agents_box_from_the_readout():
    from gridgremlin.agent_score import view
    from panel.render import agent_box
    lim = validate_agent(dict(LIMITS))
    book = [_closed(10, 0.8, 1), dict(_pos(), mark=101.0, open_pnl=4.5, reason='<b>held</b> the low')]
    v = view(book, lim)
    assert v['paper'] and v['score']['closed'] == 1 and len(v['open']) == 1 and v['open'][0]['mark'] == 101.0
    html_ = agent_box({'agent': v})
    assert 'agent · paper · BTCUSDT, ETHUSDT · day-loss limit 100' in html_
    assert 'closed 1 · open 1' in html_ and 'long BTCUSDT' in html_ and '+4.50' in html_
    assert '&lt;b&gt;held&lt;/b&gt;' in html_ and '<b>held</b>' not in html_       # the model's words, escaped
    assert agent_box({}) == '' and 'no open paper position' in agent_box({'agent': view([], lim)})
    assert 'unreadable' in agent_box({'agent': {'error': 'the paper book is unreadable: x'}})


def spec_J3_the_shipped_agent_fleet_is_paper_with_no_bots_and_validates():
    from gridgremlin.config import validate_fleet
    raw = json.loads((Path(__file__).resolve().parents[1] / 'configs' / 'fleet.agent.json').read_text())
    f = validate_fleet(raw)
    assert f['agent']['paper'] is True and f['bots'] == [] and f['account'] == 'agent'


def spec_J6_paper_needs_no_keys_the_readout_of_a_paper_agent_fleet_runs_without_them():
    """Phase 1 reads only public candles: the door, the book, the score and
    the panel's readout of a paper agent fleet with no rows need no venue
    keys — so paper needs no subaccount. A live one still asks for them."""
    import contextlib
    import io
    import os
    from gridgremlin import report
    from gridgremlin.agent_paper import book_path, save_book
    d, f = _fleet(paper=True)
    save_book(book_path(f), [_closed(10, 0.8, 1)])
    saved = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith('BYBIT_AGENT_')}
    try:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert report.main([str(f), '--json']) == 0
        c = json.loads(out.getvalue())
        assert c['bots'] == {} and c['agent']['score']['closed'] == 1
        f.write_text(json.dumps(dict(json.loads(f.read_text()), agent=dict(LIMITS, paper=False))))
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                report.main([str(f), '--json'])
        except PermissionError as e:
            assert 'no keys' in str(e)
        else:
            raise AssertionError('a live agent fleet read without keys')
    finally:
        os.environ.update(saved)


def spec_J5_the_panel_and_the_digest_read_a_paper_agent_fleet_with_no_bots_and_no_keys():
    """Found live 2026-10-11: the panel skipped the readout for every fleet
    with no bots (a just-initialised world), so the agent's box never came;
    the digest asked for keys the paper agent does not have."""
    import os
    import time
    from gridgremlin.agent_paper import book_path, save_book
    from gridgremlin.digest import section
    from panel.server import Handler
    d, f = _fleet(paper=True)
    save_book(book_path(f), [_closed(4, 0.7, 1)])
    saved = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith('BYBIT_AGENT_')}
    try:
        class H(Handler):
            hours = 24
        Handler._cache.pop(str(f), None)
        c = H._read_contract(H, str(f))
        assert c['agent']['score']['closed'] == 1 and c['bots'] == {}
        now = time.time()
        lines, tag, _ = section(str(f), now, now - now % 86400, archive_root=str(d / 'daily'),
                                kept_root=str(d / 'fills'), state={})
        assert lines[0].endswith('· agent') and any(ln.startswith('agent (paper): closed 1') for ln in lines)
        f.write_text(json.dumps(dict(json.loads(f.read_text()), agent=dict(LIMITS, paper=False))))
        try:
            section(str(f), now, now - now % 86400, archive_root=str(d / 'daily'),
                    kept_root=str(d / 'fills'), state={})
        except PermissionError as e:
            assert 'no keys' in str(e)                       # live: keys, as every account
        else:
            raise AssertionError('a live agent fleet was read without keys')
    finally:
        os.environ.update(saved)
        Handler._cache.pop(str(f), None)
    empty = Path(tempfile.mkdtemp()) / 'fleet.json'
    empty.write_text(json.dumps({'bots': []}))
    assert H._read_contract(H, str(empty))['bots'] == {}         # a fresh world still skips the readout
