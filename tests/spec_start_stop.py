# Specs for D157's third part: start and stop. A new bot starts from the page
# it was written on, with one click that says what else restarts; a typed
# confirmation on Demo or Testnet takes the bot's plain name, and Mainnet's
# stays as it was; stop is a choice (close the position or leave it open);
# a new trade is reviewed in one line before it opens; control speaks of
# accounts, its unit names a detail.
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

RISING = {'how': 'quick', 'then': 'gates', 'fleet': '0', 'preset': 'rising',
          'caution': 'balanced', 'symbol': 'btcusdt', 'capital': '1000'}
UNIT = 'gg-f'          # the served fleet is f.json: its tag, f, is in this unit's name


def _served(units=(UNIT,)):
    import spec_setup
    from panel.server import Handler
    base, d, close = spec_setup._served_fleet()
    saved = Handler.units

    def done():
        Handler.units = saved
        close()
    Handler.units = units
    return base, d, done


def _call(base, path, data=None):
    import spec_setup
    return spec_setup._call(base, path, data)


def _proposal(page):
    return html.unescape(re.search(r'name="proposal" value="([^"]*)"', page).group(1))


def _mainnet(d):
    fleet = json.loads((d / 'f.json').read_text())
    (d / 'f.json').write_text(json.dumps(dict(fleet, allow_mainnet=True)))


class _Systemctl:
    """subprocess.run, faked for systemctl: the unit answers `state`, and
    every call is kept."""

    def __init__(self, state='active'):
        import subprocess
        self.state, self.calls, self.real = state, [], subprocess.run

    def __enter__(self):
        import subprocess

        def run(args, **k):
            if args[:2] != ['systemctl', '--user']:
                return self.real(args, **k)
            self.calls.append(list(args))
            out = self.state + '\n' if args[2] == 'is-active' else ''
            return subprocess.CompletedProcess(args, 0, out, '')
        subprocess.run = run
        return self

    def __exit__(self, *exc):
        import subprocess
        subprocess.run = self.real

    def acts(self):
        return [c for c in self.calls if c[2] != 'is-active']


# --- U125: the plain name, typed ----------------------------------------------

def spec_U125_one_function_spells_the_plain_name_the_card_and_the_box_use():
    """D161: "BTCUSDT Futures Grid" is read from the bot's own fields, by
    one function: the card's name is the same words, and a confirm box
    takes them with the side ("BTCUSDT Futures Grid long") or the short
    form ("BTCUSDT grid long"), any capitals or spacing, for that bot only
    — on Demo or Testnet."""
    from panel.card import _plain_name
    from panel.html_bits import confirmed, full_name, plain_name, row_of_botid, short_name, to_type
    grid = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long', 'strategy': 'grid'}
    assert plain_name(grid) == 'BTCUSDT Futures Grid'
    assert full_name(grid) == 'BTCUSDT Futures Grid long' and short_name(grid) == 'BTCUSDT grid long'
    assert plain_name(dict(grid, strategy='martingale', side='short')) == 'BTCUSDT Futures DCA'
    assert plain_name(dict(grid, market_type='inverse', symbol='BTCUSD')) == 'BTCUSD Inverse Futures Grid'
    assert plain_name(dict(grid, strategy='martingale', trade=True)) == 'BTCUSDT Perpetual Futures Trade'
    assert plain_name(dict(grid, market_type='spot', symbol='ETHUSDT', strategy='martingale')) == 'ETHUSDT Spot DCA'
    assert plain_name(dict(grid, market_type='spot', symbol='ETHUSDT', strategy='martingale',
                           spot_borrow=True)) == 'ETHUSDT Margined Spot DCA'
    assert plain_name({'strategy': 'portfolio', 'name': 'carry'}) == 'carry Portfolio Bot'
    assert full_name({'strategy': 'portfolio', 'name': 'carry'}) == 'carry Portfolio Bot'
    assert plain_name({'symbol': 'BTCUSDT'}) is None
    for botid, kind, trade in (('linBTCUSDTl', 'grid', False), ('spoADAUSDTl', 'grid', False),
                               ('invBTCUSDs', 'martingale', False), ('linSOLUSDTs', 'martingale', True)):
        contract = {'ranges': {botid: {}} if kind == 'grid' else {},
                    'terms': {botid: {'trade': trade}}}
        assert _plain_name(botid, contract, None) == plain_name(row_of_botid(botid, kind, trade))
    assert confirmed('linBTCUSDTl', 'linBTCUSDTl')                      # the code, as always
    assert confirmed('  btcusdt   FUTURES grid  LONG ', 'linBTCUSDTl', grid)
    assert confirmed('BTCUSDT grid long', 'linBTCUSDTl', grid)          # the short form
    assert not confirmed('BTCUSDT Futures Grid', 'linBTCUSDTl', grid)   # the side is part of it
    assert not confirmed('BTCUSDT grid short', 'linBTCUSDTl', grid)
    assert not confirmed('BTCUSDT long grid', 'linBTCUSDTl', grid)      # the old spelling is gone
    assert not confirmed('BTCUSDT Futures Grid long', 'linBTCUSDTs', grid)   # another bot's words
    assert not confirmed('BTCUSDT Futures Grid long', 'linBTCUSDTl')    # no row: the code only
    assert not confirmed('BTCUSDT Futures Grid long', 'linBTCUSDTl', grid, mainnet=True)
    assert not confirmed('BTCUSDT grid long', 'linBTCUSDTl', grid, mainnet=True)
    assert confirmed('linBTCUSDTl', 'linBTCUSDTl', grid, mainnet=True)
    assert '<code>BTCUSDT Futures Grid long</code>' in to_type('linBTCUSDTl', grid)
    assert 'BTCUSDT Futures Grid' not in to_type('linBTCUSDTl', grid, mainnet=True)


def spec_U125_every_typed_gate_on_demo_takes_the_plain_name():
    """Create, stop, close, revive, clear a trade, and control's account
    name: on Demo each takes the plain name the page shows."""
    from gridgremlin.tombstones import Tombstones, path_for
    base, d, close = _served()
    try:
        page = _call(base, '/setup', RISING)
        assert '<code>BTCUSDT Futures Grid long</code>' in page and 'placeholder="BTCUSDT Futures Grid long"' not in page   # D159
        assert '&quot;btcusdt futures grid long&quot;' in page                     # the pop-up takes it
        with _Systemctl('inactive'):
            done = _call(base, '/apply', {'fleet': '0', 'proposal': _proposal(page),
                                          'confirm': 'btcusdt grid long'})
        assert 'linBTCUSDTl: written' in done
        stop = _call(base, '/retire?fleet=0&bot=linETHUSDTl')
        assert '<code>ETHUSDT Futures Grid long</code>' in stop
        (d / 's').write_text(json.dumps({'t': 0, 'bots': {'linETHUSDTl': {'position': 0.5}}}) + '\n')
        assert 'linETHUSDTl: paused' in _call(base, '/retire', {
            'fleet': '0', 'bot': 'linETHUSDTl', 'do': 'pause', 'confirm': 'ETHUSDT Futures Grid long'})
        tp = path_for(str(d / 'f.json'), json.loads((d / 'f.json').read_text()))
        Tombstones(str(tp)).add('linETHUSDTl', 'its stop')
        with _Systemctl('inactive'):
            control = _call(base, '/control')
        assert "type <code>ETHUSDT Futures Grid long</code>" in control and "placeholder='ETHUSDT" not in control
        assert 'tombstone removed' in _call(base, '/revive', {'fleet': '0', 'confirm': 'ethusdt grid long'})
        ok = _call(base, '/trade', {'action': 'open', 'go': '1', 'fleet': '0', 'side': 'short',
                                    'symbol': 'SOLUSDT', 'capital': '100', 'tp': '1'})
        assert 'linSOLUSDTs: queued' in ok
        Tombstones(str(tp)).add('linSOLUSDTs', 'took profit')
        trades = _call(base, '/trade')
        assert "type <code>SOLUSDT Perpetual Futures Trade short</code>" in trades and "placeholder='SOLUSDT" not in trades
        assert 'linSOLUSDTs: cleared' in _call(base, '/trade', {'action': 'clear', 'fleet': '0',
                                                                 'confirm': 'SOLUSDT trade short'})
    finally:
        close()


def spec_U125_controls_account_name_starts_its_unit_off_mainnet():
    import panel.routes as ps
    base, d, close = _served()
    try:
        with _Systemctl('inactive') as sc:
            page = _call(base, '/unit', {'action': 'start', 'confirm': ' Demo '})
            assert 'not done' not in page and sc.acts() == [['systemctl', '--user', 'start', UNIT]]
        _mainnet(d)
        ps.Handler._cache.clear()
        with _Systemctl('inactive') as sc:
            assert 'not done' in _call(base, '/unit', {'action': 'start', 'confirm': 'demo'})
            assert sc.acts() == []
            _call(base, '/unit', {'action': 'start', 'confirm': UNIT})          # its unit, typed
            assert sc.acts() == [['systemctl', '--user', 'start', UNIT]]
    finally:
        close()


def spec_U194_a_mainnet_account_asks_for_the_name_it_takes():
    """The live panel's control said "type the account's name to confirm
    (Hyperliquid MAINNET)", which D157 refuses on Mainnet: no restart could
    be typed (owner 2026-11-10: "it wont let me restart the live fleet").
    Now it names the unit, and the account's name typed says so; nothing
    runs until the unit is typed. Sabotage: the old prompt is caught by its
    words, the pop-up by the name it shows."""
    import panel.routes as ps
    from spec_words import visible
    base, d, close = _served()
    try:
        _mainnet(d)
        ps.Handler._cache.clear()
        with _Systemctl('active') as sc:
            page = _call(base, '/control')
            shown = ' '.join(visible(page.split('</nav>')[-1]).split())
            assert f'type to confirm: {UNIT}' in shown and 'confirm (demo)' not in shown
            assert f'its name ({UNIT})' in shown and 'name (demo)' not in shown
            got = _call(base, '/unit', {'action': 'restart', 'confirm': 'demo'})
            assert 'not done' in got and f'type its unit name, <b>{UNIT}</b>' in got and sc.acts() == []
            _call(base, '/unit', {'action': 'restart', 'confirm': UNIT})
            assert sc.acts() == [['systemctl', '--user', 'restart', UNIT]]
    finally:
        close()


def _mainnet_takes_the_plain_name(base, d):
    """The gates of a Mainnet fleet that took the plain name where only the
    code was taken before: create, stop, close and revive. [] when none."""
    import panel.routes as ps
    from gridgremlin.tombstones import Tombstones, path_for
    took = []
    _mainnet(d)
    ps.Handler._cache.clear()
    page = _call(base, '/setup', RISING)
    proposal = _proposal(page)
    retype = re.search(r'name="(retype_\w+)"', page)
    with _Systemctl('inactive'):
        got = _call(base, '/apply', dict({'fleet': '0', 'proposal': proposal, 'confirm': 'BTCUSDT Futures Grid long'},
                                         **({retype.group(1): '1000'} if retype else {})))
        if 'not applied' not in got or 'linBTCUSDTl' in json.dumps(json.loads((d / 'f.json').read_text())):
            took.append('create')
        (d / 's').write_text(json.dumps({'t': 0, 'bots': {'linETHUSDTl': {'position': 0.5}}}) + '\n')
        got = _call(base, '/retire', {'fleet': '0', 'bot': 'linETHUSDTl', 'do': 'pause',
                                      'confirm': 'ETHUSDT Futures Grid long'})
        if 'not retired' not in got:
            took.append('stop')
        calls = []
        saved = ps.Handler._run_close
        ps.Handler._run_close = lambda self, fi, botid, dry, expect=None: calls.append(dry) or {
            'held': 0.5, 'closed': 0.5, 'left': 0.0}
        try:
            got = _call(base, '/close', {'fleet': '0', 'bot': 'linETHUSDTl', 'confirm': 'ETHUSDT Futures Grid long',
                                         'size': '0.5'})
        finally:
            ps.Handler._run_close = saved
        if calls or 'not closed' not in got:
            took.append('close')
        tp = path_for(str(d / 'f.json'), json.loads((d / 'f.json').read_text()))
        Tombstones(str(tp)).add('linETHUSDTl', 'its stop')
        got = _call(base, '/revive', {'fleet': '0', 'confirm': 'ETHUSDT Futures Grid long'})
        if 'not revived' not in got:
            took.append('revive')
    return took


def spec_U125_mainnet_still_takes_the_code_only():
    """Mainnet's typing is unchanged: the plain name is refused where only
    the code was taken, and the code still passes the name gate (the
    second typing of size or capital follows, as before)."""
    base, d, close = _served()
    try:
        assert _mainnet_takes_the_plain_name(base, d) == []
        page = _call(base, '/retire?fleet=0&bot=linETHUSDTl')
        assert '<code>linETHUSDTl</code>' in page and 'ETHUSDT Futures Grid long</code>' not in page
        got = _call(base, '/retire', {'fleet': '0', 'bot': 'linETHUSDTl', 'do': 'pause',
                                      'confirm': 'linETHUSDTl'})
        assert 'paused' in got
    finally:
        close()


def spec_U125_a_confirm_that_forgets_mainnet_is_caught():
    """Sabotage: a confirm that takes the plain name on Mainnet too lets
    every gate through, and the check names them."""
    import panel.html_bits as hb
    import panel.pages.control as pc
    import panel.pages.create_flow as pcf
    import panel.pages.retire as pr
    real = hb.confirmed

    def loose(typed, botid, row=None, mainnet=False):
        return real(typed, botid, row, mainnet=False)
    mods = (pc, pcf, pr)
    for m in mods:
        m.confirmed = loose
    base, d, close = _served()
    try:
        assert set(_mainnet_takes_the_plain_name(base, d)) >= {'create', 'stop', 'close', 'revive'}
    finally:
        for m in mods:
            m.confirmed = real
        close()


# --- U126: start it now ---------------------------------------------------------

def _written(base, state):
    page = _call(base, '/setup', RISING)
    with _Systemctl(state):
        return _call(base, '/apply', {'fleet': '0', 'proposal': _proposal(page), 'confirm': 'linBTCUSDTl'})


def spec_U126_a_written_bot_starts_with_one_click_and_says_who_restarts_with_it():
    """The written page offers "start it now" for the account's engine; it
    says plainly that the account's other bots restart with it, and the
    unit is shown as a detail. The click restarts a running engine, starts
    a stopped one; nothing starts without it."""
    base, d, close = _served()
    try:
        with _Systemctl('active') as sc:
            page = _call(base, '/setup', RISING)
            done = _call(base, '/apply', {'fleet': '0', 'proposal': _proposal(page),
                                          'confirm': 'linBTCUSDTl'})
            assert sc.acts() == []                                    # written, not started
        assert 'start it now</button>' in done and 'action="/start"' in done
        assert 'does not start on its own' in done
        assert 'restarts the engine that runs demo' in done and 'its 1 other bot restarts with it' in done
        assert f'(unit {UNIT})' in done
        with _Systemctl('active') as sc:
            got = _call(base, '/start', {'fleet': '0', 'bot': 'linBTCUSDTl'})
            assert sc.acts() == [['systemctl', '--user', 'restart', UNIT]]
        assert 'BTCUSDT Futures Grid long: starting' in got and 'every bot in it restarted with it' in got
        with _Systemctl('inactive') as sc:
            _call(base, '/start', {'fleet': '0', 'bot': 'linBTCUSDTl'})
            assert sc.acts() == [['systemctl', '--user', 'start', UNIT]]
        (d / 's').write_text(json.dumps({'t': 0, 'bots': {'linBTCUSDTl': {'position': 0}}}) + '\n')
        with _Systemctl('active') as sc:
            got = _call(base, '/start', {'fleet': '0', 'bot': 'linBTCUSDTl'})
            assert 'already running' in got and sc.acts() == []          # loaded: no restart
            got = _call(base, '/start', {'fleet': '0', 'bot': 'linXRPUSDTl'})
            assert 'not started' in got and sc.acts() == []
    finally:
        close()


def spec_U126_a_stopped_engine_says_every_bot_starts():
    base, d, close = _served()
    try:
        done = _written(base, 'inactive')
        assert 'is stopped: starting it <b>starts every bot in it</b>' in done
    finally:
        close()


def _mainnet_starts_on_a_click(base, d):
    """What a click does on a Mainnet fleet: (button shown, systemctl acts)."""
    import panel.routes as ps
    _mainnet(d)
    ps.Handler._cache.clear()
    page = _call(base, '/setup', RISING)
    proposal = _proposal(page)
    retype = re.search(r'name="(retype_\w+)"', page)
    with _Systemctl('active') as sc:
        done = _call(base, '/apply', dict({'fleet': '0', 'proposal': proposal, 'confirm': 'linBTCUSDTl'},
                                          **({retype.group(1): '1000'} if retype else {})))
        assert 'linBTCUSDTl: written' in done, done[:400]
        got = _call(base, '/start', {'fleet': '0', 'bot': 'linBTCUSDTl'})
        return 'start it now</button>' in done, sc.acts(), done, got


def spec_U126_no_one_click_start_on_mainnet():
    """A fleet that may reach Mainnet keeps its typed gate: no button, a
    post refused, and no systemctl call."""
    base, d, close = _served()
    try:
        button, acts, done, got = _mainnet_starts_on_a_click(base, d)
        assert not button and acts == [] and 'no one-click start' in done
        assert 'not started' in got and 'Mainnet' in got
    finally:
        close()


def spec_U126_a_start_that_forgets_mainnet_is_caught():
    """Sabotage: a fleet read as play money starts on one click, and the
    check sees the button and the restart."""
    import panel.pages.control as pc
    saved = pc.ControlPages._real
    pc.ControlPages._real = lambda self, fleet: False
    base, d, close = _served()
    try:
        button, acts, _done, _got = _mainnet_starts_on_a_click(base, d)
        assert button and acts == [['systemctl', '--user', 'restart', UNIT]]
    finally:
        pc.ControlPages._real = saved
        close()


def spec_U126_with_control_off_no_button_and_the_page_says_how():
    base, d, close = _served(units=())
    try:
        with _Systemctl('active') as sc:
            done = _written(base, 'active')
            assert sc.acts() == []
        assert 'start it now' not in done and 'its control is off' in done
    finally:
        close()


# --- U127: stop is a choice ---------------------------------------------------------

def spec_U127_stop_asks_close_or_leave_and_picks_neither_for_you():
    """The card's stop opens a choice — close the position, or leave it
    open — the engine's own two stand-downs, with pause after them; none is
    picked, and a stop with no choice asks for one and writes nothing."""
    from panel.card import card
    import copy
    from spec_words import _contract
    c = _contract()
    belief = c['watchdog']['belief']['bots']
    assert ">stop</a>" in card(0, 'spoADAUSDTl', c['bots']['spoADAUSDTl'], copy.deepcopy(c), belief)
    base, d, close = _served()
    try:
        (d / 's').write_text(json.dumps({'t': 0, 'bots': {'linETHUSDTl': {'position': 0.5}}}) + '\n')
        page = _call(base, '/retire?fleet=0&bot=linETHUSDTl')
        assert 'Close the position, or leave it open?' in page
        assert page.index('value="close"') < page.index('value="hold"') < page.index('value="pause"')
        assert 'stop and close the position' in page and 'stop and leave the position open' in page
        assert not _picks_for_you(page)
        form = {'fleet': '0', 'bot': 'linETHUSDTl', 'confirm': 'linETHUSDTl'}
        assert 'choose one' in _call(base, '/retire', form)
        assert not (d / 'logs' / 'retire-f.json').exists()
        assert 'stop asked' in _call(base, '/retire', dict(form, do='hold'))
        assert json.loads((d / 'logs' / 'retire-f.json').read_text())['linETHUSDTl']['action'] == 'hold'
    finally:
        close()


def _picks_for_you(page):
    return bool(re.search(r'name="do" value="(close|hold|pause)"[^>]*\bchecked', page))


def spec_U127_a_stop_page_that_picks_for_you_is_caught():
    """Sabotage: a choice pre-picked, as the page once picked pause."""
    import panel.pages.retire as pr
    assert _picks_for_you('<input type="radio" name="do" value="pause" checked>')
    saved = pr.STEPS
    pr.STEPS = tuple((v, label, what) if v != 'hold' else (v + '" checked="', label, what)
                     for v, label, what in saved)
    base, d, close = _served()
    try:
        (d / 's').write_text(json.dumps({'t': 0, 'bots': {'linETHUSDTl': {'position': 0.5}}}) + '\n')
        assert _picks_for_you(_call(base, '/retire?fleet=0&bot=linETHUSDTl'))
    finally:
        pr.STEPS = saved
        close()


# --- U128: a new trade, reviewed --------------------------------------------------

TRADE = {'action': 'open', 'fleet': '0', 'side': 'long', 'symbol': 'btcusdt', 'capital': '200',
         'leverage': '3', 'tp': '2', 'stop': '1'}


def _opened_unreviewed(base, d):
    """Did the trade form's first press write a trade?"""
    trades = d / 'logs' / 'trades-f.json'
    _call(base, '/trade', TRADE)
    return trades.exists() and json.loads(trades.read_text()) != []


def spec_U128_a_new_trade_is_reviewed_in_one_line_before_it_opens():
    """"Long BTCUSDT, 200 USDT at 3x, take profit +2%, stop −1%, at
    market." — then open it, or change something with the typing kept. A
    market and side already taken is refused before the review."""
    from panel.trade_page import trade_line
    from gridgremlin.trade import build_row
    from gridgremlin.trades import validate_trade
    assert trade_line(validate_trade(build_row('long', 'BTCUSDT', {'capital': '200', 'tp': '2', 'leverage': '3',
                                                                    'stop': '1'}))) == \
        'Long BTCUSDT, 200 USDT at 3x, take profit +2%, stop −1%, at market.'
    assert trade_line(validate_trade(build_row('short', 'SOLUSDT', {'capital': '50', 'tp': '1', 'trail': '0.5',
                                                                     'trail-from': '1', 'maker': True}))) == \
        'Short SOLUSDT, 50 USDT at 1x, take profit +1%, no stop, trailing 0.5% from +1%, as a maker order.'
    base, d, close = _served()
    try:
        assert not _opened_unreviewed(base, d)
        review = _call(base, '/trade', TRADE)
        assert 'Long BTCUSDT, 200 USDT at 3x, take profit +2%, stop −1%, at market.' in html.unescape(review)
        assert 'name="go" value="1"' in review and 'open the trade</button>' in review
        back = _call(base, '/trade', dict(TRADE, action='change'))
        assert 'name="capital" value="200"' in back and 'review the trade</button>' in back
        taken = _call(base, '/trade', dict(TRADE, symbol='ETHUSDT'))
        assert 'trade refused' in taken and 'one position per side' in taken
        assert 'linBTCUSDTl: queued' in _call(base, '/trade', dict(TRADE, go='1'))
    finally:
        close()


def spec_U128_a_trade_that_opens_without_its_review_is_caught():
    """Sabotage: the first press treated as the second opens at once."""
    import panel.pages.trade as pt
    saved = pt.TradePages._trade_post
    pt.TradePages._trade_post = lambda self, form: saved(self, dict(form, go='1'))
    base, d, close = _served()
    try:
        assert _opened_unreviewed(base, d)
    finally:
        pt.TradePages._trade_post = saved
        close()


# --- U129: control's words ---------------------------------------------------------

def spec_U129_control_speaks_of_accounts_and_shows_units_as_a_detail():
    """Each line leads with the account's name and running or stopped; the
    unit is a detail beside it. "fleet" is not a word control says."""
    from spec_words import visible
    base, d, close = _served()
    try:
        with _Systemctl('active'):
            page = _call(base, '/control')
        shown = visible(page.split('</nav>')[-1])
        assert f'<b>demo</b> <span class="dim">unit {UNIT}</span>: <span class="pos" title="active">running' in page
        assert "type to confirm: demo" in ' '.join(shown.split())
        assert 'restart — loads new and removed bots' in shown
        assert not re.search(r'\bfleets?\b', shown), re.findall(r'.{30}\bfleets?\b.{30}', shown)
    finally:
        close()


def spec_U125b_a_carry_bot_takes_its_own_name_off_mainnet():
    """U125b: a carry bot's box takes the name its maker typed on the form
    ("pocket" for pfopocket) as well as "pocket Portfolio Bot" and the code,
    and shows that name to type; Mainnet still takes the code only."""
    from panel.html_bits import confirmed, to_type
    row = {'strategy': 'portfolio', 'name': 'pocket'}
    for typed in ('pocket', ' POCKET ', 'pocket Portfolio Bot', 'pfopocket'):
        assert confirmed(typed, 'pfopocket', row), typed
    for typed in ('', 'lvgdbe', 'basket', 'pfo'):
        assert not confirmed(typed, 'pfopocket', row), typed
    assert not confirmed('pocket', 'pfopocket', row, mainnet=True)
    assert confirmed('pfopocket', 'pfopocket', row, mainnet=True)
    assert not confirmed('pocket', 'pfobasket', row)     # another bot's row
    assert '<code>pocket</code>' in to_type('pfopocket', row)
    assert 'pocket' not in to_type('pfopocket', row, mainnet=True).split('<code>')[1].replace('pfopocket', '')
    grid = {'symbol': 'BTCUSDT', 'side': 'long', 'strategy': 'grid'}
    assert not confirmed('BTCUSDT', 'linBTCUSDTl', grid)  # only a carry bot's name is bare
