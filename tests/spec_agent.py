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
    f.write_text(json.dumps({'account': 'agent', 'agent': dict(LIMITS, paper=paper)}))
    return d, f


def spec_J3_paper_logs_and_sends_nothing_live_queues_a_trade_every_intent_is_logged():
    d, f = _fleet(paper=True)
    v, text = submit(f, dict(GOOD), NOON)
    assert v == 'paper' and 'not sent' in text and not (d / 'logs' / 'trades-agent.json').exists()
    v, text = submit(f, dict(GOOD, market='SOLUSDT'), NOON + 1)
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
    code, text = handle(str(f), 'read', NOON)
    got = json.loads(text)
    assert code == 0 and got['paper'] is True and got['intents_left_this_hour'] == 3 and got['open'] == []
    code, text = handle(str(f), 'intent ' + json.dumps(GOOD), NOON)
    assert code == 0 and json.loads(text)['verdict'] == 'paper'
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
