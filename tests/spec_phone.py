# Specs for SPEC F16 (D60) — the phone carries what needs the owner now. Everything
# still prints; the routing below is the phone's alone.

import inspect
import re

from gridgremlin.events import (PERSIST_COUNT, PERSIST_REPEAT, PERSIST_WINDOW,
                                TelegramNotifier, VenueNotifier)


def _n(t=None):
    sent, lines, clock = [], [], t if t is not None else [0.0]
    n = TelegramNotifier('tok', 'chat', transport=sent.append,
                         clock=lambda: clock[0], sink=lines.append)
    n.startup = False
    return n, sent, lines, clock


def _phone(sent):
    return '\n'.join(sent)


def spec_F16_trading_churn_stays_in_the_log():
    n, sent, lines, _ = _n()
    for kind, text in (('fill', 'position 1 -> 2'), ('exit', 'position 2 -> 1'),
                       ('tp', '2 tranche TP(s) resting'), ('start', 'round 3'),
                       ('repeat', 'round 3 re-anchors'), ('seed', 'Buy 1'),
                       ('slide', 'window +1 -> +2')):
        n.event(kind, 'botA', text)
    n.close()
    assert sent == []                                # nothing on the phone
    assert len(lines) == 7 and all(l.startswith('[ship]') for l in lines)


def spec_F16_emergencies_and_the_fleet_reach_the_phone():
    n, sent, _, clock = _n()
    for kind in ('kill', 'margin', 'backoff', 'fleet'):
        n.event(kind, 'botA', f'{kind} happened')
        clock[0] += 4.0
    n.close()
    for kind in ('kill', 'margin', 'backoff', 'fleet'):
        assert f'{kind} happened' in _phone(sent), kind


def spec_F16_an_urgent_event_reaches_the_phone_a_plain_one_does_not():
    n, sent, _, clock = _n()
    n.event('warn', 'botA', 'amend: rejected')                 # once: the log's
    n.event('warn', 'botA', 'tp: refused', urgent=True)
    clock[0] += 4.0
    n.event('exit', 'botA', 'trailing stop crossed — closed', urgent=True)
    n.close()
    phone = _phone(sent)
    assert 'tp: refused' in phone and 'trailing stop crossed' in phone
    assert 'amend: rejected' not in phone
    sent2 = []
    v = VenueNotifier(TelegramNotifier('t', 'c', transport=sent2.append,
                                       clock=lambda: 0.0,
                                       sink=lambda l: None), '🟧')
    v._inner.startup = False
    v.event('warn', 'botB', 'server stop: refused', urgent=True)
    v._inner.close()
    assert sent2 and '🟧 warn botB: server stop: refused' in sent2[0]


def spec_F16_the_fleet_start_reaches_the_phone_whole():
    sent = []
    n = TelegramNotifier('tok', 'chat', transport=sent.append,
                         clock=lambda: 0.0, sink=lambda l: None)
    assert n.startup                                 # until the fleet is built
    n.event('warn', 'BTCUSDT', 'slide at 25x: a full-ladder trend bet')
    n.close()
    assert 'slide at 25x' in _phone(sent)


def spec_F16_a_repeating_warning_reaches_the_phone_once_as_persisting():
    """The SUI exit refused 286 times on 2026-10-05 with no exit resting —
    a warning nobody marked urgent, that kept coming. Its numbers change;
    its shape does not."""
    n, sent, _, clock = _n()
    for i in range(PERSIST_COUNT - 1):
        n.event('warn', 'linSUIl', f'tp: minimum value of $10. asset={i}')
        clock[0] += 30.0
    n.close()
    assert sent == []                                # not yet
    n.event('warn', 'linSUIl', 'tp: minimum value of $10. asset=99')
    n.close()
    assert len(sent) == 1 and 'persisting (5x in 2 min)' in sent[0]
    for _ in range(20):                              # it lasts: quiet...
        clock[0] += 30.0
        n.event('warn', 'linSUIl', 'tp: minimum value of $10. asset=1')
    n.close()
    assert len(sent) == 1
    clock[0] += PERSIST_REPEAT                       # ...until the hour
    for _ in range(PERSIST_COUNT):
        n.event('warn', 'linSUIl', 'tp: minimum value of $10. asset=1')
    n.close()
    assert len(sent) == 2
    n.event('warn', 'other', 'tp: minimum value of $10. asset=1')
    n.close()
    assert len(sent) == 2                            # per bot, not global
    m, sent3, _, clock3 = _n()
    for _ in range(PERSIST_COUNT):                   # spread past the window
        m.event('warn', 'b', 'G26 lag')
        clock3[0] += PERSIST_WINDOW / (PERSIST_COUNT - 1) + 1
    m.close()
    assert sent3 == []


def spec_F16_the_fault_that_can_cost_money_is_marked_where_it_is_raised():
    """A call site is the one place that knows what its warning means.
    These are the ones that need the owner now or can cost money; a
    refactor that drops the mark silences them, so the source is read."""
    from gridgremlin import bot, reload
    src = inspect.getsource(bot) + inspect.getsource(reload)
    calls = re.findall(r"\.event\((.*?)\)\s*\n", src, re.S)
    def marked(needle):
        hit = [c for c in calls if needle in c]
        assert hit, needle
        return all('urgent=True' in c for c in hit)
    for needle in ("f'tp: {e}'", "f'server stop: {e}'", "f'breakeven stop: {e}'",
                   "f'flatten: {e}'", "f'trailing: {e}'", 'WRONG side',
                   'nothing harvestable', 'no reconstructable cost',
                   'tombstone write FAILED', 'REFUSED by the venue',
                   'consumed the capital', "'exit', self.botid, said"):
        assert marked(needle), needle


def spec_F16_an_urgent_line_that_recurs_is_said_then_held():
    """Urgent is not a licence to flood: the refused SUI exit came every
    cycle. Said the first time, then at most every URGENT_REPEAT, saying
    how often it came."""
    from gridgremlin.events import URGENT_REPEAT
    n, sent, _, clock = _n()
    n.event('warn', 'linSUIl', 'tp: minimum value of $10. asset=1', urgent=True)
    n.close()
    assert len(sent) == 1 and sent[0].endswith('asset=1')
    for _ in range(100):
        clock[0] += 2.0
        n.event('warn', 'linSUIl', 'tp: minimum value of $10. asset=2',
                urgent=True)
    n.close()
    assert len(sent) == 1                            # held
    clock[0] += URGENT_REPEAT
    n.event('warn', 'linSUIl', 'tp: minimum value of $10. asset=3', urgent=True)
    n.close()
    assert len(sent) == 2 and sent[1].startswith('warn linSUIl: still (101x')
    n.event('warn', 'linDOTl', 'tp: minimum value of $10. asset=3', urgent=True)
    n.close()
    assert len(sent) == 3                            # another bot: its own
    n.event('kill', 'linSUIl', 'stood down')
    n.event('kill', 'linSUIl', 'stood down')
    n.close()
    assert _phone(sent).count('stood down') == 2     # a kill is never held
