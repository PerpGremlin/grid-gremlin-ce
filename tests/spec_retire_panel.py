"""D145: retire from the panel — pause, stand down keeping the position, stand
down closing everything, and the row's removal inside it — through the
running fleet's own bot."""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from gridgremlin.bot import Bot
from gridgremlin.config import ConfigError
from gridgremlin.events import Notifier
from gridgremlin.retire import RetireWatch, drop, load_requests, request
from gridgremlin.tombstones import Tombstones


def _refused(fn, *a, **k):
    try:
        fn(*a, **k)
    except ConfigError as e:
        return str(e)
    raise AssertionError(f'{a} was accepted')


def spec_X15e_a_retire_request_is_one_of_three_steps_and_a_stand_down_stands():
    path = Path(tempfile.mkdtemp()) / 'logs' / 'retire-x.json'
    assert load_requests(path) == {}
    assert 'one of pause, hold, close' in _refused(request, path, 'b', 'stop', 'owner')
    assert 'remove goes with a stand-down' in _refused(request, path, 'b', 'pause', 'owner', remove=True)
    p = request(path, 'b', 'pause', 'owner')
    assert p['action'] == 'pause' and p['t'].endswith('Z') and p['remove'] is False
    assert request(path, 'b', 'hold', 'owner', remove=True)['action'] == 'hold'   # a pause may escalate
    assert request(path, 'b', 'close', 'owner')['action'] == 'hold'               # a stand-down stands
    assert drop(path, 'b', only_pause=True) is False                              # resume lifts a pause only
    request(path, 'c', 'pause', 'owner')
    assert drop(path, 'c', only_pause=True) is True and 'c' not in load_requests(path)
    assert drop(path, 'b') is True and load_requests(path) == {}


def spec_X15e_the_fleet_hands_each_request_to_its_bot_once_restart_included():
    path = Path(tempfile.mkdtemp()) / 'retire-x.json'

    class B:
        botid, alive, paused, retire_request = 'linBTCUSDTl', True, None, None

    class Portfolio:
        botid, alive = 'porBASKET', True              # no retire_request: never handed one
    bot, lines = B(), []
    w = RetireWatch(path, [bot, Portfolio()], Notifier(sink=lines.append))
    request(path, bot.botid, 'pause', 'owner')
    os.utime(path, (5, 6))
    w.poll()
    assert bot.paused['by'] == 'owner' and sum('paused by owner' in ln for ln in lines) == 1
    os.utime(path, (7, 8))
    w.poll()
    assert sum('paused by' in ln for ln in lines) == 1                       # once
    drop(path, bot.botid, only_pause=True)
    os.utime(path, (9, 10))
    w.poll()
    assert bot.paused is None and any('resumed' in ln for ln in lines)
    request(path, bot.botid, 'close', 'owner')
    os.utime(path, (11, 12))
    w.poll()
    assert bot.retire_request['action'] == 'close'
    assert any('closing its position at market' in ln for ln in lines)
    fresh = B()                                                              # a restart: it stands
    RetireWatch(path, [fresh], Notifier(sink=lines.append))
    assert fresh.retire_request['action'] == 'close'


def _grid(lines, tombs=None):
    from spec_loop import ADAPTER, FakeVenue, _cfg
    venue = FakeVenue()
    bot = Bot(_cfg(), ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1, tombstones=tombs)
    bot.cycle()
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': '0.05', 'avgPrice': '59000',
                      'leverage': '10', 'unrealisedPnl': '0'}
    bot._basis_cache = None
    bot.cycle()
    return venue, bot


def spec_X15e_a_paused_bot_adds_nothing_and_its_exits_keep_working():
    """Sabotage: a bot that ignores `paused` keeps its buys resting."""
    venue, bot = _grid([])
    assert any(o['side'] == 'Buy' for o in venue.orders)
    sells = [o['order_id'] for o in venue.orders if o['side'] == 'Sell']
    bot.paused = {'t': 'now', 'by': 'owner'}
    bot.cycle()
    assert not any(o['side'] == 'Buy' for o in venue.orders)
    assert [o['order_id'] for o in venue.orders if o['side'] == 'Sell'] == sells and bot.alive
    bot.paused = None
    bot.cycle()
    assert any(o['side'] == 'Buy' for o in venue.orders)
    from spec_round import ADAPTER, FakeVenue, _cfg
    mv = FakeVenue()
    mg = Bot(_cfg(), ADAPTER, mv, Notifier(sink=lambda ln: None), gen_seed=1)
    mg.paused = {'t': 'now', 'by': 'owner'}
    assert mg.cycle() == {'round': 'paused'} and mv.position is None


def spec_X15e_standing_down_keeping_the_position_cancels_and_sells_nothing():
    lines = []
    tombs = Tombstones(str(Path(tempfile.mkdtemp()) / 't.json'))
    venue, bot = _grid(lines, tombs)
    bot.retire_request = {'action': 'hold', 'by': 'owner', 'reason': 'retire on the panel'}
    assert bot.cycle() is None
    assert not bot.alive and venue.orders == [] and float(venue.position['size']) == 0.05
    assert tombs.has(bot.botid) and not getattr(venue, 'market_links', [])
    kill = next(ln for ln in lines if ' kill ' in ln)
    assert 'retired by owner' in kill and 'LEFT OPEN as its retirement asked (D145)' in kill


def spec_X15e_standing_down_closing_everything_sells_the_whole_position():
    lines = []
    tombs = Tombstones(str(Path(tempfile.mkdtemp()) / 't.json'))
    venue, bot = _grid(lines, tombs)
    bot.retire_request = {'action': 'close', 'by': 'owner', 'reason': 'retire on the panel'}
    assert bot.cycle() is None
    assert not bot.alive and venue.orders == [] and venue.position is None
    assert tombs.has(bot.botid) and 'flattened 0.05 at market' in next(ln for ln in lines if ' kill ' in ln)


def spec_X15e_closing_everything_takes_the_floor_core_a_stop_keeps():
    """X6 keeps a floor core through a stop; retire's close takes it too,
    and its hold sells nothing. Sabotage: drop `whole` and 0.014 stays."""
    from spec_stops import _bot, _holding
    from spec_loop import FakeVenue
    for action, left in (('close', None), ('hold', 0.035)):
        venue, lines = FakeVenue(mark=61000.0), []
        _holding(venue, size='0.035')                      # 2 floored + 3 grid lots
        bot = _bot(venue, lines, min_position_base=0.014)
        bot.retire_request = {'action': action, 'by': 'owner', 'reason': ''}
        bot.cycle()
        assert not bot.alive
        if left is None:
            assert venue.position is None, action
        else:
            assert abs(float(venue.position['size']) - left) < 1e-9, action


def spec_X15e_the_card_offers_retire_and_the_retire_page_holds_every_step():
    from spec_setup import _call, _served_fleet
    from panel.server import Handler
    base, d, close = _served_fleet()
    saved = Handler.units
    try:
        Handler.units = ('some.service',)
        page = _call(base, '/retire?fleet=0&bot=linETHUSDTl')
        assert 'retire linETHUSDTl' in page and 'has not started' in page
        assert 'value="remove"' in page                              # never started: removable
        (d / 's').write_text(json.dumps({'t': 0, 'bots': {'linETHUSDTl': {'position': 0.5}}}) + '\n')
        page = _call(base, '/retire?fleet=0&bot=linETHUSDTl')
        for step in ('value="pause"', 'value="hold"', 'value="close"', 'name="remove"'):
            assert step in page
        assert 'It holds <b>0.5</b>' in page
        assert 'not retired' in _call(base, '/retire', {'fleet': '0', 'bot': 'linETHUSDTl',
                                                        'do': 'pause', 'confirm': 'yes'})
        assert 'still running' in _call(base, '/retire', {'fleet': '0', 'bot': 'linETHUSDTl',
                                                          'do': 'remove', 'confirm': 'linETHUSDTl'})
        assert 'linETHUSDTl: paused' in _call(base, '/retire', {'fleet': '0', 'bot': 'linETHUSDTl',
                                                                 'do': 'pause', 'confirm': 'linETHUSDTl'})
        reqs = json.loads((d / 'logs' / 'retire-f.json').read_text())
        assert reqs['linETHUSDTl']['action'] == 'pause' and reqs['linETHUSDTl']['by'] == 'owner'
        assert '>resume</button>' in _call(base, '/retire?fleet=0&bot=linETHUSDTl')
        assert 'resumed' in _call(base, '/retire', {'fleet': '0', 'bot': 'linETHUSDTl',
                                                    'do': 'resume', 'confirm': 'linETHUSDTl'})
        assert json.loads((d / 'logs' / 'retire-f.json').read_text()) == {}
        assert 'not a bot of this fleet' in _call(base, '/retire?fleet=0&bot=linXRPUSDTl')
    finally:
        Handler.units = saved
        close()


def spec_X15e_a_stand_down_with_remove_takes_the_row_out_once_the_bot_has_stood_down():
    """The bot stands down (its tombstone lands); the panel then takes the
    row and its watchdog line out, and the request and tombstone with them."""
    import threading
    import time
    import panel.pages.retire as pr
    from spec_setup import _call, _served_fleet
    from panel.server import Handler
    base, d, close = _served_fleet()
    saved = Handler.units, pr.WAIT_S
    try:
        Handler.units, pr.WAIT_S = ('some.service',), 5.0
        fleet = json.loads((d / 'f.json').read_text())              # a fleet is never emptied
        fleet['bots'].append(dict(fleet['bots'][0], side='short'))
        (d / 'f.json').write_text(json.dumps(fleet))
        (d / 's').write_text(json.dumps({'t': 0, 'bots': {'linETHUSDTl': {'position': 0.5}}}) + '\n')
        tombs = d / 'logs' / 'tombstones-f.json'

        def bot_acts():                                   # the running fleet, a cycle later
            time.sleep(1.0)
            Tombstones(str(tombs)).add('linETHUSDTl', 'retired by owner (D145)')
        threading.Thread(target=bot_acts, daemon=True).start()
        done = _call(base, '/retire', {'fleet': '0', 'bot': 'linETHUSDTl', 'do': 'close',
                                       'remove': '1', 'confirm': 'linETHUSDTl'})
        assert 'retired and removed' in done
        assert [b['side'] for b in json.loads((d / 'f.json').read_text())['bots']] == ['short']
        assert 'linETHUSDTl' not in json.loads((d / 'wd.json').read_text()).get('positions', {})
        assert json.loads((d / 'logs' / 'retire-f.json').read_text()) == {}
        assert 'linETHUSDTl' not in json.loads(tombs.read_text())
    finally:
        Handler.units, pr.WAIT_S = saved
        close()


def spec_X15e_closing_everything_on_real_money_asks_the_size_twice():
    from spec_setup import _call, _served_fleet
    from panel.server import Handler
    base, d, close = _served_fleet()
    saved = Handler.units
    try:
        Handler.units = ('some.service',)
        fleet = json.loads((d / 'f.json').read_text())
        (d / 'f.json').write_text(json.dumps(dict(fleet, allow_mainnet=True)))
        (d / 's').write_text(json.dumps({'t': 0, 'bots': {'linETHUSDTl': {'position': 0.5}}}) + '\n')
        assert 'type the size a second' in _call(base, '/retire?fleet=0&bot=linETHUSDTl')
        form = {'fleet': '0', 'bot': 'linETHUSDTl', 'do': 'close', 'confirm': 'linETHUSDTl'}
        assert 'not retired' in _call(base, '/retire', dict(form, size='0.4'))
        assert not (d / 'logs' / 'retire-f.json').exists()
        assert 'retire asked' in _call(base, '/retire', dict(form, size='0.5'))
    finally:
        Handler.units = saved
        close()


def spec_U101_close_is_said_only_where_a_position_closes():
    """The owner, 2026-10-20: a "close" that only leaves a screen could be
    read as close position. A link or button whose whole label is "close"
    (or ×) appears nowhere in the panel; leaving a view says back. Every
    close that remains names what it closes."""
    import re
    root = Path(__file__).parent.parent / 'panel'
    bare = re.compile(r'>\s*(close|×|&times;)\s*</(a|button)>', re.I)
    hits = [f'{p.name}: {m.group(0)}' for p in sorted(root.rglob('*.py'))
            for m in bare.finditer(p.read_text())]
    assert hits == [], hits
    from panel.detail import page_pane
    assert 'data-pick href="/">back</a>' in page_pane('results', '')


def spec_U102_a_dca_card_says_its_safeties_and_its_exits():
    """The first-day check (2026-10-21): a full DCA round's card said
    "nothing resting" while its take-profits sat on the exchange. The
    engine now says where it keeps a round's exits and at what prices;
    the card names its own orders as safety orders and the exits beside
    them; a grid's words are unchanged. Sabotage: drop the engine's
    exits_view and the round says nothing of its exit."""
    from gridgremlin.bot import Bot
    from panel.card import orders_line
    from spec_round import ADAPTER, FakeVenue, _cfg
    venue = FakeVenue()
    bot = Bot(_cfg(), ADAPTER, venue, Notifier(sink=lambda ln: None), gen_seed=1)
    assert bot.exits_view is None
    bot.cycle()
    bot.cycle()
    assert venue.position and bot.exits_view and bot.exits_view['prices'], bot.exits_view
    assert bot.exits_view['at'] in ('position', 'conditional', 'orders')
    words = orders_line({'resting': {}, 'waiting': {}}, {'at': 'conditional', 'prices': [0.2755, 0.2782]},
                        dca=True)
    assert words == ("no safety order resting · take-profits at 0.2755 and 0.2782, "
                     "held in the exchange's conditional book")
    assert orders_line({'resting': {'buys': 2}}, {'at': 'position', 'prices': [0.09487]}, dca=True) == \
        '2 safety orders resting · take-profit at 0.09487, held on the position'
    assert orders_line({'resting': {}, 'waiting': {}}) == 'nothing resting'            # a grid: as before


def spec_U104_a_stopped_or_retired_bot_is_not_drawn_from_the_last_picture():
    """The owner (2026-10-22), after the flatten: "the demo accounts are
    all still running" — the fleets were stopped and every bot retired,
    but the cards drew the engine's last snapshot (holding, orders
    resting). A bot its tombstone names reads RETIRED, one in a fleet whose
    unit is not active STOPPED; neither shows the snapshot's holding or
    orders; the fleet's heading says stopped. What it held is said as last
    seen, the exchange having the word — never "holding nothing" unless the
    last snapshot read flat. The run state comes from systemctl and the
    tombstone file; unknown leaves the card as it was. Sabotage: ignoring
    `retired` draws the old holding again; wiping the last holding says
    "holding nothing"."""
    import copy
    import json
    import subprocess
    import tempfile
    from pathlib import Path
    from panel.card import card
    from panel.render import cards_section
    from panel.routes import Handler
    c = {'window_hours': 24.0, 'generated_ms': 0, 'bots': {'linDOGEs': None}, 'unowned': {},
         'terms': {'linDOGEs': {'strategy': 'grid'}},
         'watchdog': {'belief': {'age_s': 3, 'bots': {'linDOGEs': {
             'alive': True, 'position': 730.0, 'orders': {'entry': 2, 'exit': 1}}}}}}
    belief = c['watchdog']['belief']['bots']
    live = card(0, 'linDOGEs', None, c, belief)
    assert 'holding 730 (belief)' in live and '>HOLDING<' in live
    for key, val, word in (('retired', ['linDOGEs'], 'RETIRED'), ('stopped', 'inactive', 'STOPPED')):
        html = card(0, 'linDOGEs', None, dict(c, **{key: val}), belief)
        assert f'>{word}<' in html and 'HOLDING' not in html and '(belief)' not in html, word
        # the reviewer (2026-10-27): a stop parks and never flattens, a hold
        # keeps its position — "holding nothing" claimed what nobody read
        assert 'last seen holding 730' in html and 'the exchange has the word' in html, word
        assert 'holding nothing' not in html and 'cancelled, its position closed' not in html, word
        flat = {'linDOGEs': dict(belief['linDOGEs'], position=0.0)}
        assert 'last seen holding nothing' in card(0, 'linDOGEs', None, dict(c, **{key: val}), flat)
        unseen = card(0, 'linDOGEs', None, dict(c, **{key: val}), {})
        assert 'not known here' in unseen and 'holding nothing' not in unseen, word
    assert '<span class="tier neg">stopped</span>' in cards_section(0, 'demo', dict(c, stopped='inactive'))
    assert 'stopped</span>' not in cards_section(0, 'demo', c)
    # the run state: the fleet's unit by systemctl, the rows by their tombstones
    with tempfile.TemporaryDirectory() as d:
        fleet = Path(d) / 'fleet.demo.json'
        fleet.write_text(json.dumps({'bots': [{'symbol': 'DOGE'}]}))
        from gridgremlin.tombstones import Tombstones, path_for
        Tombstones(str(path_for(str(fleet), json.loads(fleet.read_text())))).add('linDOGEs', 'test')
        h = Handler.__new__(Handler)
        real = subprocess.run
        try:
            subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 3, 'inactive\n', '')
            h.units = ('grid-gremlin3-demo',)
            out = h._with_run_state(str(fleet), copy.deepcopy(c))
            assert out['stopped'] == 'inactive' and out['retired'] == ['linDOGEs']
            subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, 'active\n', '')
            assert 'stopped' not in h._with_run_state(str(fleet), copy.deepcopy(c))
            h.units = ()
            assert 'stopped' not in h._with_run_state(str(fleet), copy.deepcopy(c))
        finally:
            subprocess.run = real
