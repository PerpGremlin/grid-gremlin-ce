"""The panel's security floor, pinned live: real server, real requests."""
import json
import threading
import urllib.request
import urllib.error


def _serve(contract):
    import http.server
    from panel.server import Handler

    class H(Handler):
        def _contract(self, fleet):
            return contract
    H.token = 'tok123'
    import tempfile as _tf
    from pathlib import Path as _P
    _fp = _P(_tf.mkdtemp()) / 'f.json'
    _fp.write_text('{"bots": [{"x": 1}]}')     # exists and non-empty:
    H.fleets = (str(_fp),)                      # the init guard stands down
    H.labels = ('demo',)
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
    H.host_ok = f'127.0.0.1:{srv.server_port}'
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f'http://{H.host_ok}'


CONTRACT = {'window_hours': 6.0, 'generated_ms': 0, 'unowned': {},
            
            'ranges': {'spoADAUSDTl': {'lower': 0.155, 'upper': 0.23,
                                       'rungs': 16}},
            'fee_floors': {'spoADAUSDTl': 0.0025},
            'watchdog': {'ceilings': {'spoADAUSDTl': 9700.0,
                                      'linDOGEs': 8000.0},
                         'swept_s_ago': 41,
                         'belief': {'age_s': 3, 'bots': {
                             'linDOGEs': {'alive': True,
                                          'position': 730.0}}}},
            'bots': {'spoADAUSDTl': {
                'fills': 3, 'realized': 5.04, 'fees': 2.07, 'bought': 910.0,
                'sold': 0.0, 'position': 910.57, 'avg_cost': 0.207,
                'unreal_at_mark': -4.83, 'truncated': False, 'mark': 0.2017,
                'side': 'long', 'strategy': 'grid', 'inverse': False}}}



def _everything(c):
    """U56: the fleet page and every position's page — the numbers moved to
    the latter; a spec that pins a number reads both."""
    from panel.render import position_page
    from panel.server import render
    belief = ((c.get('watchdog') or {}).get('belief') or {}).get('bots', {})
    return render([('demo', c)]) + ''.join(position_page(0, 'demo', b, c, belief)
                                           for b in sorted(set(c['bots']) | set(belief)))

def spec_P1_no_cookie_no_page_and_wrong_host_is_refused():
    srv, base = _serve(CONTRACT)
    try:
        try:
            urllib.request.urlopen(f'{base}/')
            assert False, 'served without auth'
        except urllib.error.HTTPError as e:
            assert e.code == 401
        req = urllib.request.Request(f'{base}/?t=tok123',
                                     headers={'Host': 'evil.example'})
        try:
            urllib.request.urlopen(req)
            assert False, 'rebinding not refused'
        except urllib.error.HTTPError as e:
            assert e.code == 403
    finally:
        srv.shutdown()


def spec_P2_the_token_becomes_a_cookie_and_the_page_renders_the_contract():
    srv, base = _serve(CONTRACT)
    try:
        op = urllib.request.build_opener()   # no redirect cookie jar needed:
        try:
            op.open(f'{base}/?t=tok123')     # 303 w/ Set-Cookie then / -> 401
        except urllib.error.HTTPError:
            pass
        req = urllib.request.Request(f'{base}/',
                                     headers={'Cookie': 'gg=tok123'})
        html = op.open(req).read().decode()
        assert 'spoADAUSDTl' in html and 'HOLDING' in html
        assert '910.57' in html
        assert '<svg' in html and 'circle' in html      # the range strip
        assert 'watchdog swept 41s ago' in html
        # U56: the numbers are the position's own page, behind the same cookie
        req = urllib.request.Request(f'{base}/position?fleet=0&bot=spoADAUSDTl',
                                     headers={'Cookie': 'gg=tok123'})
        html = op.open(req).read().decode()
        assert 'as the exchange shows it' in html and '<td>0.207</td>' in html
        # settlement: 910.57 * 0.2017 * (1 - 0.0025) = 183.20
        assert '183.2' in html, 'stop-now estimate missing or wrong'
        assert '9% of 9,700' in html          # 910.57 / 9700 utilization
        req = urllib.request.Request(f'{base}/data',
                                     headers={'Cookie': 'gg=tok123'})
        data = json.loads(op.open(req).read())
        assert data == {'demo': CONTRACT}    # labelled by fleet, unmangled
    finally:
        srv.shutdown()


def spec_P3_rehearse_speaks_the_engines_refusal_verbatim():
    """One validator, three doors: a bad draft posted through the panel
    must come back with the engine's own refusal text — never a second
    validator's paraphrase. And a POST without auth or with a foreign
    Origin is refused before any work happens."""
    from gridgremlin.backtest_cli import run_draft
    import json as _json
    out = run_draft(_json.dumps(
        {'market_type': 'linear', 'venue': 'bybit', 'symbol': 'ADAUSDT',
         'side': 'long', 'capital': 1500, 'lower': 0.23, 'upper': 0.155,
         'rungs': 16}), 7, 60, 0.0002)
    assert 'refused' in out
    assert 'lower' in out['refused'] or 'upper' in out['refused']

    srv, base = _serve(CONTRACT)
    try:
        req = urllib.request.Request(f'{base}/rehearse', data=b'gg=1',
                                     method='POST')
        try:
            urllib.request.urlopen(req)
            assert False, 'unauthed POST accepted'
        except urllib.error.HTTPError as e:
            assert e.code == 401
        req = urllib.request.Request(
            f'{base}/rehearse', data=b'gg=1', method='POST',
            headers={'Cookie': 'gg=tok123',
                     'Origin': 'http://evil.example'})
        try:
            urllib.request.urlopen(req)
            assert False, 'cross-origin POST accepted'
        except urllib.error.HTTPError as e:
            assert e.code == 403
    finally:
        srv.shutdown()


def spec_T3_the_rehearsal_reports_the_hold_benchmark():
    """§9: every verdict carries what the same capital did just holding —
    the number every user asks for and nobody ships."""
    from gridgremlin.adapters import SpotAdapter
    from gridgremlin.backtest_cli import rehearse
    from gridgremlin.config import validate_grid
    draft = validate_grid({'market_type': 'spot', 'symbol': 'ADAUSDT',
                           'side': 'long', 'capital': 1000,
                           'lower': 0.15, 'upper': 0.25, 'rungs': 11,
                           'stop': {'watch': 'mark_price', 'level': 0.14}})
    a = SpotAdapter({'symbol': 'ADAUSDT', 'qty_step': 0.01, 'min_qty': 1.0,
                     'price_tick': 0.0001, 'min_notional': 1.0})
    bars = [{'o': 0.20, 'h': 0.21, 'l': 0.19, 'c': 0.20},
            {'o': 0.20, 'h': 0.22, 'l': 0.20, 'c': 0.22}]
    out = rehearse(draft, bars, a)
    assert abs(out['hold_benchmark'] - 100.0) < 1e-9   # 1000 * (0.22/0.20-1)
    assert out['bars'] == 2


def _fake_adapter():
    from gridgremlin.adapters import LinearAdapter
    return LinearAdapter({'symbol': 'ADAUSDT', 'qty_step': 1.0,
                          'min_qty': 1.0, 'price_tick': 0.0001,
                          'min_notional': 1.0})


_FLEET = {'bots': [], 'watchdog': 'wd.json'}
_WD = {'tag': 't', 'snapshot': 's', 'state': 'st',
       'staleness_seconds': 600, 'mm_rate_max': 0.5,
       'equity_min': 100, 're_alert_seconds': 900,
       'assumes_sole_actor': True,
       'positions': {}}
_BOT = {'market_type': 'linear', 'venue': 'bybit', 'symbol': 'ADAUSDT',
        'side': 'long', 'capital': 1500, 'lower': 0.155, 'upper': 0.23,
        'rungs': 16, 'stop': {'watch': 'mark_price', 'level': 0.148}}


def spec_D32_the_panel_writes_a_limit_only_when_one_is_asked():
    from panel.create import edit_proposal, merge_proposal, validate_whole
    adapter = _fake_adapter()
    botid, fleet, wd = merge_proposal(
        _FLEET, _WD, {'bot': dict(_BOT), 'watchdog': {'max': None}})
    assert botid not in wd['positions']            # blank = no limit
    assert validate_whole(fleet, wd, lambda c: adapter) is None
    _, _, wd2 = edit_proposal(fleet, wd, botid, dict(_BOT), 5000.0)
    assert wd2['positions'][botid] == {'min': 0, 'max': 5000.0}
    _, _, wd3 = edit_proposal(fleet, wd2, botid, dict(_BOT), None)
    assert botid not in wd3['positions']           # blanked = lifted


def spec_C5_the_gate_refuses_a_row_that_cannot_place_one_order():
    """The engine sets an unplaceable row aside dead (D52); the panel
    refuses it before it is written, naming the bot (2026-10-06: a HYPE
    row of 47 dust rungs was saved and took the HL fleet down)."""
    from panel.create import merge_proposal, validate_whole
    from gridgremlin.adapters import LinearAdapter
    strict = LinearAdapter({'symbol': 'ADAUSDT', 'qty_step': 1.0,
                            'min_qty': 1.0, 'price_tick': 0.0001,
                            'min_notional': 10.0})
    dust = dict(_BOT, capital=150, rungs=47)       # ~3.2 a rung, minimum 10
    _, fleet, wd = merge_proposal(_FLEET, _WD, {'bot': dust})
    why = validate_whole(fleet, wd, lambda c: strict)
    assert why and 'cannot place a single order' in why, why
    assert 'linADAUSDTl' in why
    _, fleet, wd = merge_proposal(_FLEET, _WD, {'bot': dict(_BOT)})
    assert validate_whole(fleet, wd, lambda c: strict) is None


def spec_V16_the_gate_refuses_leverage_past_the_coins_maximum():
    from panel.create import merge_proposal, validate_whole
    from gridgremlin.exchange.hyperliquid.adapters import HLPerpAdapter
    from gridgremlin.exchange.hyperliquid.truth import parse_instrument
    sol = HLPerpAdapter(parse_instrument({'name': 'SOL', 'szDecimals': 2,
                                          'maxLeverage': 10}))
    row = {'venue': 'hyperliquid', 'market_type': 'linear', 'symbol': 'SOL',
           'side': 'long', 'capital': 150, 'lower': 112.5, 'upper': 127.2,
           'rungs': 15}
    _, fleet, wd = merge_proposal(_FLEET, _WD, {'bot': dict(row, leverage=15)})
    why = validate_whole(fleet, wd, lambda c: sol)
    assert why and 'maximum of 10x' in why and 'linSOLl' in why, why
    _, fleet, wd = merge_proposal(_FLEET, _WD, {'bot': dict(row, leverage=10)})
    assert validate_whole(fleet, wd, lambda c: sol) is None


def spec_F1_the_create_flow_judges_the_merged_fleet_not_the_bot_alone():
    """§11 gate 1: an unwatchable addition is refused by the engine's own
    coverage check, in the engine's own words — and a well-watched one
    passes. Bot and watcher land together or not at all."""
    from panel.create import merge_proposal, validate_whole
    from gridgremlin.config import validate_grid
    from gridgremlin.ladder import grid_rungs, position_cap
    adapter = _fake_adapter()
    vbot = validate_grid(dict(_BOT))    # the same normalisation the flow does
    cap = position_cap(vbot, adapter, grid_rungs(vbot, adapter))
    # ceiling inside the band: the merged fleet validates
    botid, fleet, wd = merge_proposal(
        _FLEET, _WD, {'bot': dict(_BOT), 'watchdog': {'max': cap * 1.2}})
    assert botid == 'linADAUSDTl'
    assert validate_whole(fleet, wd, lambda c: adapter) is None
    assert wd['positions']['linADAUSDTl']['max'] == cap * 1.2
    # ceiling beyond 1.5x cap: refused, engine's words (F2)
    _, fleet2, wd2 = merge_proposal(
        _FLEET, _WD, {'bot': dict(_BOT), 'watchdog': {'max': cap * 3.0}})
    why = validate_whole(fleet2, wd2, lambda c: adapter)
    assert why and 'ceiling' in why
    # duplicate identity: refused before validation
    try:
        merge_proposal(fleet, wd, {'bot': dict(_BOT),
                                   'watchdog': {'max': cap}})
        assert False, 'identity reused'
    except Exception as e:
        assert 'already in this fleet' in str(e)


def spec_X8_atomic_write_replaces_whole_and_keeps_the_bak():
    """§11: 'safe' means an atomic rename with a kept .bak — the OctoBot
    safe_dump lesson. The old content survives beside the new."""
    import tempfile
    from pathlib import Path as _P
    from panel.create import atomic_write
    d = _P(tempfile.mkdtemp())
    p = d / 'fleet.json'
    p.write_text('{"old": true}')
    atomic_write(p, '{"new": true}')
    assert p.read_text() == '{"new": true}'
    assert (d / 'fleet.json.bak').read_text() == '{"old": true}'
    assert not list(d.glob('fleet.json?*[!k]'))       # no temp litter


def spec_C1_control_is_opt_in_and_typed():
    """§12: a panel launched without --unit has NO control surface; with
    it, an unmatched typed confirmation does nothing."""
    srv, base = _serve(CONTRACT)
    try:
        req = urllib.request.Request(f'{base}/control',
                                     headers={'Cookie': 'gg=tok123'})
        try:
            urllib.request.urlopen(req)
            assert False, 'control served unarmed'
        except urllib.error.HTTPError as e:
            assert e.code == 404
        req = urllib.request.Request(
            f'{base}/unit', data=b'gg=1&action=stop&confirm=wrong',
            method='POST', headers={'Cookie': 'gg=tok123'})
        try:
            urllib.request.urlopen(req)
            assert False
        except urllib.error.HTTPError as e:
            assert e.code == 404       # unarmed: refused before the confirm
    finally:
        srv.shutdown()


def spec_X7_revive_removes_exactly_the_typed_entry_atomically():
    # pins: X7b (two writers, one lock)
    """The revive path is the delete-the-entry-deliberately workflow: the
    typed botid goes, everything else stays."""
    import tempfile
    from pathlib import Path as _P
    from gridgremlin.tombstones import remove
    d = _P(tempfile.mkdtemp())
    tp = d / 'tombstones.json'
    tp.write_text(json.dumps({'a': {'reason': 'x'}, 'b': {'reason': 'y'}}))
    assert remove(tp, 'a') == {'reason': 'x'}
    assert json.loads(tp.read_text()) == {'b': {'reason': 'y'}}
    assert remove(tp, 'zzz') is None                      # not there: no write


def spec_X7_two_writers_cannot_undo_each_other():
    """Audit 2026-10-05: the engine rewrote the tombstones from rows held
    since the build, so a revive done in the panel was undone by the next
    stop — or the panel's write lost the stop's row and a stopped bot
    revived at the next restart. Both now re-read under one lock."""
    import tempfile
    from pathlib import Path as _P
    from gridgremlin.tombstones import Tombstones, remove, path_for
    d = _P(tempfile.mkdtemp())
    tp = d / 'tombstones.json'
    tp.write_text(json.dumps({'A': {'reason': 'old'}}))
    engine = Tombstones(tp)                     # the fleet built, A dead
    assert remove(tp, 'A') == {'reason': 'old'}  # the operator revives A
    engine.add('B', 'stop fired')                # then B's stop fires
    rows = json.loads(tp.read_text())
    assert 'A' not in rows and 'B' in rows       # the revive stands
    # the lock is real: a second holder waits for the first
    import threading
    import time as _t
    from gridgremlin.durable import locked
    order = []

    def second():
        with locked(tp):
            order.append('second')
    with locked(tp):
        t = threading.Thread(target=second)
        t.start()
        _t.sleep(0.2)
        order.append('first')
    t.join(2)
    assert order == ['first', 'second']
    # one answer for where a fleet's tombstones live
    assert path_for(d / 'configs' / 'f.json', {}) == d / 'logs' / 'tombstones.json'
    assert path_for(d / 'x.json', {'tombstones': '/t/z.json'}) == _P('/t/z.json')


def spec_V7_a_quiet_bot_is_shown_not_omitted():
    """No fills in the window must never mean no row: the page renders the
    engine's belief (labelled as belief) — HOLDING, RESTING, or DEAD.
    Live 2026-08-08: three HL bots vanished from the panel for being
    quiet, and quiet is exactly when you want to see them."""
    c = json.loads(json.dumps(CONTRACT))
    c['bots']['linDOGEs'] = None                  # configured, no fills
    render = __import__('panel.server', fromlist=['render']).render
    for face in (False, True):                    # the cards and the table
        html = render([('hl', c)], table=face)
        assert 'linDOGEs' in html
        assert 'HOLDING' in html and '730 (belief)' in html
        assert 'no fills' in html
    # every row carries the full column count — a short row shears the
    # table and lands cells under the wrong headers (live 2026-08-08)
    for row in html.split('<tr>')[1:]:
        cells = row.split('</tr>')[0]
        n = cells.count('<td') or cells.count('<th')
        assert n == 16, f'{n} cells in row: {cells[:90]}'   # D63: funding


def spec_F1_edit_and_remove_move_bot_and_watcher_together():
    """An edit keeps identity or is refused; a removal takes the watchdog
    line with it and the remaining fleet still validates (F1) — the same
    one-act rule as creation, in reverse."""
    from panel.create import (edit_proposal, merge_proposal,
                              remove_proposal, validate_whole)
    from gridgremlin.config import validate_grid
    from gridgremlin.ladder import grid_rungs, position_cap
    adapter = _fake_adapter()
    vbot = validate_grid(dict(_BOT))
    cap = position_cap(vbot, adapter, grid_rungs(vbot, adapter))
    botid, fleet, wd = merge_proposal(
        _FLEET, _WD, {'bot': dict(_BOT), 'watchdog': {'max': cap * 1.2}})
    # edit: new capital, watcher moves with it, fleet revalidates
    newbot = dict(_BOT, capital=2000)
    vnew = validate_grid(dict(newbot))
    ncap = position_cap(vnew, adapter, grid_rungs(vnew, adapter))
    _, f2, w2 = edit_proposal(fleet, wd, botid, newbot, ncap * 1.2)
    assert validate_whole(f2, w2, lambda c: adapter) is None
    assert f2['bots'][0]['capital'] == 2000
    # edit refusing an identity change
    try:
        edit_proposal(fleet, wd, botid, dict(_BOT, side='short'), cap)
        assert False
    except Exception as e:
        assert 'cannot change identity' in str(e)
    # remove: both lines go; the empty fleet still validates coverage
    _, f3, w3 = remove_proposal(fleet, wd, botid)
    assert f3['bots'] == [] and botid not in w3['positions']
    assert 'not in this fleet' in str(
        _catch(lambda: remove_proposal(f3, w3, botid)))


def _catch(fn):
    try:
        fn()
        return ''
    except Exception as e:
        return str(e)


def spec_V8_the_export_is_the_same_renderer_frozen():
    """§4: one renderer, two artefacts. The export carries the same rows,
    drops the refresh and every action link, and stamps its provenance —
    a snapshot must say it is one."""
    from panel.server import render
    live = render([('demo', CONTRACT)])
    frozen = render([('demo', CONTRACT)], static='Fri, 08 Aug 2026')
    assert 'spoADAUSDTl' in frozen and '910.57' in frozen
    assert 'http-equiv="refresh"' in live
    assert 'http-equiv="refresh"' not in frozen
    assert '/control' in live and '/control' not in frozen
    assert 'exported Fri, 08 Aug 2026' in frozen
    assert 'snapshot, not a live view' in frozen


def spec_T3_the_verdict_draws_the_equity_path_with_a_zero_line():
    """The curve is inline SVG with the zero line drawn — a rehearsal that
    spent the window underwater must LOOK underwater."""
    from panel.server import verdict
    out = {'grid_profit': 5.0, 'fees': 1.0, 'net': 4.0, 'total': 4.0,
           'hold_benchmark': 2.0, 'max_drawdown': 3.0, 'trips': 2,
           'entry_fills': 4, 'held': 0.0, 'basis': None, 'bars': 3,
           'equity_curve': [0.0, -2.0, 4.0]}
    html = verdict({'symbol': 'X', 'side': 'long', 'lower': 1, 'upper': 2,
                    'rungs': 3}, out)
    assert '<polyline' in html and '<line' in html
    from panel.server import curve_svg
    assert curve_svg([]) == '' and curve_svg([1.0]) == ''


def spec_M2_the_preview_does_the_compounding_and_names_full_depth():
    """§8: the deviation ladder as numbers — every 3Commas thread's
    hand-arithmetic, machine-done. Pinned by hand: base 800 + safeties
    800x1.5^i, deviations 0.8% stepping x1.5, short side (prices ABOVE
    the anchor)."""
    from panel.create import martingale_preview
    from gridgremlin.config import validate_martingale
    raw = {'strategy': 'martingale', 'market_type': 'linear',
           'symbol': 'SOLUSDT', 'side': 'short', 'capital': 5000,
           'leverage': 10, 'base_order_size': 800, 'safety_order_size': 800,
           'order_size_multiplier': 1.5, 'deviation_pct': 0.008,
           'deviation_step_multiplier': 1.5, 'max_averaging_orders': 4,
           'take_profit_avg_pct': 0.012, 'repeat': True}
    cfg = validate_martingale(dict(raw))
    rows, full = martingale_preview(cfg, 100.0)
    assert len(rows) == 5                       # base + 4 safeties
    assert rows[0]['price'] == 100.0 and rows[0]['notional'] == 800
    assert abs(rows[1]['price'] - 100.8) < 1e-9         # +0.8%
    assert abs(rows[2]['price'] - 102.0) < 1e-9         # +0.8% + 1.2%
    assert rows[2]['notional'] == 1200                  # 800 x 1.5
    assert abs(rows[-1]['cum_notional'] - (800 + 800 + 1200 + 1800 + 2700)) < 1e-9
    assert abs(full - sum(r['qty'] for r in rows)) < 1e-12
    # and a martingale proposal passes the whole-fleet gate with a ceiling
    from panel.create import merge_proposal, validate_whole
    # merge the RAW row, as the flow does — the validator's derived keys
    # (ladder_notional) never belong in a fleet file
    botid, fleet, wd = merge_proposal(
        _FLEET, _WD, {'bot': raw, 'watchdog': {'max': full * 1.2}})
    assert botid == 'linSOLUSDTs'
    assert validate_whole(fleet, wd, lambda c: _fake_adapter()) is None


def spec_F1_init_writes_a_valid_pair_and_only_into_the_empty_world():
    """First run: a minimal fleet + watchdog pair the create flow can
    merge into — watchdog validated by the engine's own loader before
    anything touches disk; existing files are never overwritten."""
    import tempfile
    from pathlib import Path as _P
    from panel.create import init_pair
    from gridgremlin.watchdog import validate_watchdog
    d = _P(tempfile.mkdtemp())
    wp = init_pair(d / 'fleet.mine.json', 'mine', equity_min=500.0)
    fleet = json.loads((d / 'fleet.mine.json').read_text())
    wd = json.loads(wp.read_text())
    assert fleet == {'bots': [], 'watchdog': str(wp)}
    # the loaders refuse EMPTY worlds (correctly, for running) — so the
    # pair must validate the moment one bot joins it, which is the gate
    # that actually matters
    from panel.create import merge_proposal, validate_whole
    from gridgremlin.config import validate_grid
    _, f2, w2 = merge_proposal(fleet, wd, {'bot': dict(_BOT),
                                           'watchdog': {'max': 9604.0}})
    assert validate_whole(f2, w2, lambda c: _fake_adapter()) is None
    assert wd['assumes_sole_actor'] is True and wd['equity_min'] == 500.0
    try:
        init_pair(d / 'fleet.mine.json', 'mine', 500.0)
        assert False, 'overwrote an existing world'
    except Exception as e:
        assert 'already exists' in str(e)


def spec_V9_the_key_defines_every_word_the_page_uses():
    """A dashboard that needs a translator failed the thesis: the key
    defines each column, state, and symbol the page can show."""
    from panel.server import KEY
    for term in ('realized', 'unreal', 'stop-now', 'watcher', 'DEAD',
                 'no limit', '(belief)', 'ZERO-SPREAD', 'hold benchmark',
                 'trips', 'max depth', '* (star)'):
        assert term in KEY, f'key missing: {term}'


def spec_F3_the_supervisor_detaches_stops_and_never_mistakes_a_stale_pid():
    """§13 with a real process: start detaches (the child outlives any
    parent shell), status reads pid-liveness, stop is SIGTERM, and a
    dead pid is reported as stale — never as a running engine."""
    import os
    import subprocess as sp
    import sys as _sys
    import tempfile
    import time as _t
    from pathlib import Path as _P
    from panel import supervise as sup
    d = _P(tempfile.mkdtemp())
    (d / 'configs').mkdir()
    (d / 'logs').mkdir()
    fleet = d / 'configs' / 'fleet.t.json'
    fleet.write_text('{}')
    assert sup.status(fleet) == ('stopped', None)
    # a stand-in child (the real engine would refuse the empty fleet —
    # correctly; the supervisor's contract is process handling)
    proc = sp.Popen([_sys.executable, '-c', 'import time; time.sleep(60)',
                     'gridgremlin', str(fleet)],       # the engine's own words
                    start_new_session=True)
    sup._pid_path(fleet).write_text(str(proc.pid))
    for _ in range(40):                 # a cold start reads /proc before the
        st, pid = sup.status(fleet)     # child's argv is in place: the one
        if st == 'running':             # intermittent failure of 10-05
            break
        _t.sleep(0.05)
    assert st == 'running' and pid == proc.pid
    # a RECYCLED pid — alive, but not our engine — is stale, and stop never
    # signals it (audit 2026-10-05: SIGTERM went to whoever owned the pid)
    other = sp.Popen([_sys.executable, '-c', 'import time; time.sleep(60)'],
                     start_new_session=True)
    sup._pid_path(fleet).write_text(str(other.pid))
    assert sup.status(fleet) == ('stale pid file', None)
    assert 'not running' in sup.stop(fleet)
    for _ in range(5):                          # give a wrong signal time
        _t.sleep(0.1)                           # to land, on a slow box too
        assert other.poll() is None, 'a stranger was signalled'
    other.kill()
    sup._pid_path(fleet).write_text(str(proc.pid))
    assert 'already running' in sup.start(fleet)     # no double spawn
    note = sup.stop(fleet)
    assert 'parked, not flattened' in note
    for _ in range(50):
        if proc.poll() is not None:
            break
        _t.sleep(0.1)
    assert proc.poll() is not None, 'SIGTERM did not land'
    assert sup.status(fleet) == ('stopped', None)
    import inspect
    assert "'-m', 'gridgremlin', str(fleet)" in inspect.getsource(sup.start)
    # a stale pid (dead process) is named, never believed
    sup._pid_path(fleet).write_text(str(proc.pid))
    st, _ = sup.status(fleet)
    assert st == 'stale pid file'
    assert 'not running' in sup.stop(fleet)


def spec_V10_a_card_says_the_bot_in_a_glance_and_keeps_every_number():
    """The owner's panel was a 14-column table of jargon. A card leads with
    the bot's plain name, its state in a word, what it made after fees and
    where the price sits in its range; every number the row carried is
    still there, folded."""
    from panel.server import render
    html = _everything(CONTRACT)
    assert 'class="cards"' in html and '<table class="fleet">' not in html
    assert 'ADAUSDT long grid spot' in html          # the name a person says
    assert 'spoADAUSDTl' in html                     # the botid, for confirms
    assert '-1.86</span>' in html                    # 5.04 - 2.07 - 4.83
    assert 'after fees, last 6h' in html
    assert 'above the bottom' in html and 'below the top' in html
    for word in ('fills', 'realized', 'fees', 'unreal', 'bought', 'sold',
                 'stop-now est.', 'watcher'):
        assert f'<td>{word}</td>' in html, word      # nothing was dropped
    for link in ("/edit?fleet=0&bot=spoADAUSDTl'>edit",
                 '/setup?fleet=0&copy=spoADAUSDTl', 'mode=remove'):
        assert link in html
    assert '1 bots' in html and 'href="/table"' in html
    table = render([('demo', CONTRACT)], table=True)
    assert '<table class="fleet">' in table and 'href="/">cards' in table


def spec_U45_the_money_sits_in_its_own_box_per_bot_and_per_exchange():
    """The owner looked for the P&L and could not find it: a card's total
    was one line among many, the exchange's a figure inside its heading.
    Each now has a box of its own, the total first, then what it is made
    of — banked after fees, and still open."""
    import copy
    from panel.server import render
    html = render([('demo', CONTRACT)])
    card = html.split('class="card ')[1]
    assert '<div class="pnl neg">' in card           # 5.04 - 2.07 - 4.83
    assert 'realised after fees <b class="pos">+2.97</b>' in card
    assert 'open <b class="neg">-4.83</b>' in card
    head = html.split('class="cards"')[0]
    assert 'this exchange</span> <span class="big neg">-1.86</span>' in head
    c = copy.deepcopy(CONTRACT)                      # two bots: summed
    c['bots']['spoXRPUSDTl'] = dict(c['bots']['spoADAUSDTl'], realized=10.0,
                                    fees=1.0, unreal_at_mark=None,
                                    position=0.0)
    head = render([('demo', c)]).split('class="cards"')[0]
    assert '<span class="big pos">+7.14</span>' in head    # -1.86 + 9
    assert 'realised after fees <b class="pos">+11.97</b>' in head
    assert 'open <b class="neg">-4.83</b>' in head         # flat adds nothing


def spec_U50_the_exchange_boxes_ride_in_a_strip_pinned_to_the_top():
    """The owner, ten cards down the page: the exchange boxes "get lost
    while scrolling". A strip pinned to the top carries each fleet's name,
    network, total after fees, bots and dead count, leverage now — the same
    numbers as the box, from the same contract — and jumps to the box."""
    import copy
    from panel.server import CSS, render
    c2 = copy.deepcopy(CONTRACT)
    c2['bots']['spoADAUSDTl']['realized'] = 20.0
    c2['watchdog']['belief']['bots']['linDOGEs']['alive'] = False
    c2['account'] = {'bybit': {'equity': 1000.0, 'notional': 2780.0, 'collateral': 1000.0}}
    html = render([('demo', CONTRACT), ('hl', c2)])
    strip, rest = html.split('</div><div class="page">', 1)
    strip = strip.split('<div class="hero">', 1)[1]
    assert strip.count('<div class="fleet">') == 2 and strip.index('>demo<') < strip.index('>hl<')
    demo, hl = strip.split('<div class="fleet">')[1:]
    assert 'href="#fleet0"' in demo and '<span class="big num neg">-1.86 <span class="dim">USDT</span></span>' in demo
    assert '>1 bots</span><span></span><span class="dim">leverage —</span>' in demo
    assert 'href="#fleet1"' in hl and '<span class="big num pos">+13.10 <span class="dim">USDT</span></span>' in hl
    assert '<b class="neg num">1 dead</b><span class="dim">leverage 2.78x</span>' in hl
    assert '.hero{display:grid;grid-template-columns:repeat(6,max-content)' in CSS   # squared
    assert '.hero .fleet{display:contents}' in CSS
    assert 'this exchange</span> <span class="big pos">+13.10</span>' in rest   # the box agrees
    assert '<h1 id="fleet0">' in rest and '<h1 id="fleet1">' in rest
    assert '.hero{position:sticky;top:0' in CSS
    assert '<h1 id="fleet0">' in render([('demo', CONTRACT)], table=True)      # the table too
    static = render([('demo', CONTRACT)], static='2026-10-07')
    assert static.index('class="hero"') < static.index('<h1 id="fleet0">')


def spec_U51_every_link_and_switch_sits_in_one_side_panel():
    """The owner: the links across the bottom and the switches at the top
    "may be better as a side panel nav bar". One panel beside the cards,
    pinned while the page scrolls: pages, arrange, numbers (cards only),
    size in, leverage, theme. The export, having no actions, has none."""
    from panel.server import CSS, render
    cards = render([('demo', CONTRACT)])
    assert cards.count('<nav class="side">') == 1
    nav = cards.split('<nav class="side">', 1)[1].split('</nav>', 1)[0]
    for h in ('pages', 'arrange', 'size in', 'leverage'):
        assert f'<h3>{h}</h3>' in nav, h
    for href in ('/table', '/control', '/setup', '/rehearse', '/export', '/key'):
        assert f'href="{href}"' in nav, href
    assert '<b class="on">as listed</b>' in nav and 'ggAll(true)' not in nav   # U56: nothing folds
    assert 'data-size="coin"' in nav and 'data-lev="filled"' in nav
    assert nav.endswith('>theme</button>')
    assert cards.index('<nav class="side">') < cards.index('<h1 id="fleet0">')
    assert 'arrange: ' not in cards and '&rarr;</a> ·' not in cards     # gone from top and bottom
    table = render([('demo', CONTRACT)], table=True, view='side')
    tnav = table.split('<nav class="side">', 1)[1].split('</nav>', 1)[0]
    assert 'href="/?view=side"' in tnav and '<h3>numbers</h3>' not in tnav
    static = render([('demo', CONTRACT)], static='2026-10-07')
    assert '<nav' not in static and 'class="page"' not in static
    assert '.page{display:grid;grid-template-columns:14em' in CSS
    assert 'nav.side{position:sticky;top:0' in CSS and '@media(max-width:60em){.page{display:block}' in CSS
    assert "nav.style.top=hero.offsetHeight+'px'" in cards
    assert '--gap:1em;--gap-s:.5em' in CSS and '.cards{display:grid;gap:var(--gap)' in CSS


def spec_U52_a_dca_card_folds_its_ladder_and_says_the_drop_it_covers():
    """The owner: "what am I actually risking with this row" — the
    3Commas summary box on the card, from the contract's terms."""
    from panel.server import KEY, ladder_box, render
    rows = [{'step': 0, 'fill_pct': 0.0, 'notional': 1500.0, 'committed': 1500.0,
             'avg_pct': 0.0, 'to_tp_pct': 0.01},
            {'step': 1, 'fill_pct': -0.015, 'notional': 1500.0, 'committed': 3000.0,
             'avg_pct': -0.00756, 'to_tp_pct': 0.0176},
            {'step': 6, 'fill_pct': -0.09, 'notional': 48000.0, 'committed': 96000.0,
             'avg_pct': -0.0412, 'to_tp_pct': 0.0652}]
    box = ladder_box(3, 'lin1000PEPEUSDTl', {'ladder': rows})
    assert box.startswith('<details data-k="3:lin1000PEPEUSDTl:ladder"><summary>the ladder: '
                          'covers a move of <b>-9.00%</b>, then 96,000 committed at an '
                          'average of -4.12%</summary>')
    assert '<tr><td>base</td><td>+0.00%</td><td>1,500</td><td>1,500</td><td>+0.00%</td><td>+1.00%</td></tr>' in box
    assert '<tr><td>6</td><td>-9.00%</td><td>48,000</td><td>96,000</td><td>-4.12%</td><td>+6.52%</td></tr>' in box
    assert ladder_box(0, 'x', {'capital': 1}) == '' and ladder_box(0, 'x', None) == ''
    c = {'window_hours': 6.0, 'generated_ms': 0, 'unowned': {},
         'bots': {'lin1000PEPEUSDTl': dict(CONTRACT['bots']['spoADAUSDTl'], strategy='martingale')},
         'terms': {'lin1000PEPEUSDTl': {'capital': 2000, 'leverage': 50.0, 'market_type': 'linear',
                                         'strategy': 'martingale', 'multiplier': 2.0, 'add_ons': 6,
                                         'ladder': rows}},
         'watchdog': {'belief': {'age_s': 2, 'bots': {}}}}
    page = _everything(c)
    assert page.count(':ladder"><summary>the ladder:') == 1
    assert page.index('<h3>the numbers</h3>') < page.index('<summary>the ladder')
    assert '<tr><td>the ladder</td>' in KEY
    assert ':ladder"' not in render([('demo', CONTRACT)])         # a grid has none


def spec_U53_every_money_figure_names_its_coin():
    """The owner, reading PEPE's card: "investment 2,000 at 50x · up to
    96,000 in the market" — in what? Every money figure says: the settle
    coin for linear and spot, dollars and the coin for an inverse row."""
    import copy
    from gridgremlin.report import money_units
    from panel.server import render, units_of, venue_money
    assert money_units('bybit', 'linear', 'BTCUSDT') == {'quote': 'USDT', 'margin_coin': 'USDT'}
    assert money_units('bybit', 'linear', 'BTCPERP') == {'quote': 'USDC', 'margin_coin': 'USDC'}
    assert money_units('hyperliquid', 'linear', 'BTC') == {'quote': 'USDC', 'margin_coin': 'USDC'}
    assert money_units('bybit', 'inverse', 'BTCUSD') == {'quote': 'USD', 'margin_coin': 'BTC'}
    assert money_units('bybit', 'spot', 'ADAUSDT') == {'quote': 'USDT', 'margin_coin': 'USDT'}
    assert units_of('linBTCl', {'quote': 'USDC', 'margin_coin': 'USDC'}) == ('USDC', 'USDC')
    assert units_of('spoADAUSDTl', None) == ('USDT', 'USDT')      # from the name
    assert units_of('invBTCUSDl', None) == ('USD', 'BTC')
    c = copy.deepcopy(CONTRACT)
    c['terms'] = {'spoADAUSDTl': {'capital': 3000.0, 'leverage': 1.0, 'market_type': 'spot',
                                  'strategy': 'grid', 'quote': 'USDT', 'margin_coin': 'USDT'}}
    c['watchdog']['belief']['bots']['spoADAUSDTl'] = {
        'alive': True, 'position': 910.57, 'loss': {'limit': 50.0, 'result': -12.4},
        'margin': {'im': 300.0, 'mm': 15.0, 'leverage': 1.0, 'liq': None}}
    page = _everything(c)
    assert '<span class="big neg">-1.86</span> USDT <span class="dim">after fees' in page
    assert 'worth 183.662 USDT' in page and 'cost 188.488 USDT' in page
    assert 'margin IM 300.00 USDT · MM 15.00 USDT' in page
    assert 'investment 3,000 USDT' in page
    assert 'loss limit: down 12.40 of 50 USDT' in page
    assert 'this exchange</span> <span class="big neg">-1.86</span> USDT <span' in page
    assert '<span class="big num neg">-1.86 <span class="dim">USDT</span></span>' in page
    inv = copy.deepcopy(CONTRACT)                 # a margin held in the coin itself
    inv['bots']['invBTCUSDl'] = dict(inv['bots'].pop('spoADAUSDTl'), inverse=True,
                                     position=11424.0, avg_cost=84696.5, mark=85000.0)
    inv['watchdog']['belief']['bots']['invBTCUSDl'] = {
        'alive': True, 'position': 11424.0,
        'margin': {'im': 0.013488, 'mm': 0.001214, 'leverage': 10.0, 'liq': None}}
    assert 'margin IM 0.013488 BTC · MM 0.001214 BTC' in render([('demo', inv)])
    assert venue_money({'terms': {'a': {'quote': 'USDT'}, 'b': {'quote': 'USDC'}}}) == 'USDC/USDT'
    assert venue_money({'bots': {'linBTCl': None}, 'terms': {'linBTCl': {'quote': 'USDC'}}}) == 'USDC'
    assert 'size and committed in USDT' in _everything(dict(
        CONTRACT, terms={'spoADAUSDTl': {'strategy': 'martingale', 'quote': 'USDT',
                                         'ladder': [{'step': 0, 'fill_pct': 0.0, 'notional': 1.0,
                                                     'committed': 1.0, 'avg_pct': 0.0,
                                                     'to_tp_pct': 0.01}]}}))


def spec_P1_the_entry_point_resolves_every_name_it_uses():
    """2026-10-08: the panel split left main() without Path, and the box's
    panel died at start — the one function no spec runs. Its free names
    are resolved against the module statically, so the façade can never
    lose an import again."""
    import ast
    import builtins
    import inspect
    import panel.server as srv
    tree = ast.parse(inspect.getsource(srv))
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    loads = {n.id for n in ast.walk(main) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    stores = {n.id for n in ast.walk(main) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    stores |= {a.arg for a in main.args.args}
    stores |= {n.name for n in ast.walk(main) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    stores |= {(a.asname or a.name).split('.')[0] for n in ast.walk(main)
               if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
    missing = sorted(n for n in loads - stores if not hasattr(srv, n) and not hasattr(builtins, n))
    assert not missing, f'panel.server.main uses names the module lacks: {missing}'


def spec_U54_the_bots_can_be_arranged_by_strategy_or_by_coin():
    """The owner: "separate every strategy type on the dash … more options
    to organise". Two more arrangements: one heading per kind of bot, and
    one per coin across its products. Every bot once in each."""
    from panel.render import VIEWS, grouped, render
    c = {'window_hours': 6.0, 'generated_ms': 0, 'unowned': {},
         'bots': {'linBTCUSDTl': dict(CONTRACT['bots']['spoADAUSDTl'], strategy='grid'),
                  'spoBTCUSDTl': dict(CONTRACT['bots']['spoADAUSDTl'], strategy='grid'),
                  'invBTCUSDl': dict(CONTRACT['bots']['spoADAUSDTl'], strategy='grid', inverse=True),
                  'lin1000PEPEUSDTl': dict(CONTRACT['bots']['spoADAUSDTl'], strategy='martingale'),
                  'linETHUSDTs': None},
         'terms': {'linETHUSDTs': {'strategy': 'martingale'}},
         'watchdog': {'belief': {'age_s': 2, 'bots': {'linETHUSDTs': {'alive': True, 'position': 0.0}}}}}
    assert [k for k, _ in VIEWS] == ['all', 'side', 'pairs', 'strategy', 'market']
    strat = grouped(c, 'strategy')
    assert [t for t, _ in strat] == ['grids', 'DCA']
    assert [b for b, _ in strat[0][1]] == ['linBTCUSDTl', 'spoBTCUSDTl', 'invBTCUSDl']
    assert [b for b, _ in strat[1][1]] == ['lin1000PEPEUSDTl', 'linETHUSDTs']      # a quiet bot by its terms
    market = grouped(c, 'market')
    assert [t for t, _ in market] == ['BTC — inverse, perp, spot', '1000PEPE — perp', 'ETH — perp']
    assert [b for b, _ in market[0][1]] == ['linBTCUSDTl', 'spoBTCUSDTl', 'invBTCUSDl']
    for view in ('strategy', 'market'):
        assert sorted(b for _, rows in grouped(c, view) for b, _ in rows) == sorted(c['bots'])
    page = render([('demo', c)], view='strategy')
    assert '<div class="grp">grids</div>' in page and '<b class="on">by strategy</b>' in page
    assert 'href="/?view=market"' in page and 'href="/table?view=strategy"' in page


def spec_V10_a_card_says_when_the_price_has_left_the_range():
    from panel.server import render
    c = json.loads(json.dumps(CONTRACT))
    c['bots']['spoADAUSDTl']['mark'] = 0.25          # above 0.23
    html = render([('demo', c)])
    assert 'price is OUTSIDE the range (above)' in html
    c['bots']['spoADAUSDTl']['mark'] = 0.15
    assert 'OUTSIDE the range (below)' in render([('demo', c)])


def spec_V10_the_table_is_still_served():
    srv, base = _serve(CONTRACT)
    try:
        req = urllib.request.Request(f'{base}/table',
                                     headers={'Cookie': 'gg=tok123'})
        page = urllib.request.urlopen(req).read().decode()
        assert '<table class="fleet">' in page
        req = urllib.request.Request(f'{base}/',
                                     headers={'Cookie': 'gg=tok123'})
        assert 'class="cards"' in urllib.request.urlopen(req).read().decode()
    finally:
        srv.shutdown()


def spec_V11_a_watchdog_that_is_off_says_OFF_not_a_number():
    """The owner, with the watchdog deliberately off (D39): "clear the
    numbers and simply have it say N/A or OFF". An hour without a sweep is
    off; late within the hour is still an alarm."""
    from panel.server import sweep_note
    assert sweep_note({'watchdog': {'swept_s_ago': 41}}) == (
        '<span class="dim">watchdog swept 41s ago</span>')
    late = sweep_note({'watchdog': {'swept_s_ago': 1500}})
    assert 'class="neg"' in late and 'late: swept 25 min ago' in late
    for off in ({'watchdog': {'swept_s_ago': 602233}},
                {'watchdog': {'swept_s_ago': None}}, {}):
        assert sweep_note(off) == '<span class="dim">watchdog OFF</span>'


def spec_U10_a_refresh_does_not_shut_what_the_reader_opened():
    """Owner, 2026-10-02: every refresh collapsed the boxes. Each box is
    named so one script can reopen it; the script carries no number and
    the export carries no script."""
    from panel.server import KEEP_JS, render
    live = _everything(CONTRACT)
    assert '<details' not in live                      # U56: a card folds nothing
    assert 'http-equiv="refresh"' in live and KEEP_JS in live
    assert KEEP_JS in render([('demo', CONTRACT)], table=True)
    assert '<script' not in render([('demo', CONTRACT)], static='then')
    for word in ("details[data-k]", "'toggle'", 'scrollTo', 'gg-light'):
        assert word in KEEP_JS, word
    for word in ('fetch(', 'http://', 'https://', 'eval(', 'Math.',
                 'localStorage', 'cookie'):
        assert word not in KEEP_JS, word


def spec_D70_a_capped_bot_says_so_on_its_card():
    """The cap's reason rides the engine's snapshot (D56/D70); a flat bot
    says it waits, a holding one that it adds nothing."""
    import copy
    from gridgremlin.main import snapshot_row
    from panel.server import render

    class B:
        botid, alive, _last_pos, offset = 'spoADAUSDTl', True, 0.0, 0
        cfg = {}
        capped = 'bots holding 8 >= 8'
    row = snapshot_row([B()], {'equity': 1.0, 'mm_rate': 0.0}, 0)
    assert row['bots']['spoADAUSDTl']['capped'] == 'bots holding 8 >= 8'

    class Free(B):
        capped = None
    assert 'capped' not in snapshot_row([Free()], {'equity': 1.0, 'mm_rate': 0.0}, 0)['bots']['spoADAUSDTl']
    c = copy.deepcopy(CONTRACT)
    c['bots']['spoADAUSDTl']['position'] = 0.0
    c['watchdog']['belief']['bots']['spoADAUSDTl'] = {'alive': True, 'position': 0.0,
                                                      'capped': 'bots holding 8 >= 8'}
    page = render([('demo', c)])
    assert '<div class="neg">waiting: bots holding 8 >= 8 — opens nothing until it clears' in page
    c['bots']['spoADAUSDTl']['position'] = 910.57
    c['watchdog']['belief']['bots']['spoADAUSDTl']['capped'] = 'notional 55,000 >= 50,000'
    page = render([('demo', c)])
    assert '<div class="neg">capped: notional 55,000 >= 50,000 — adds nothing, exits run' in page
    assert 'waiting:' not in render([('demo', CONTRACT)]) and 'capped:' not in render([('demo', CONTRACT)])


def spec_D76_a_spot_card_says_wallet_book_and_what_is_not_its():
    import copy
    from panel.server import KEY, render
    c = copy.deepcopy(CONTRACT)
    c['terms'] = {'spoADAUSDTl': {'capital': 1500, 'leverage': 2.0, 'market_type': 'spot',
                                  'strategy': 'grid', 'quote': 'USDT', 'margin_coin': 'USDT',
                                  'holding': 300.0, 'holding_since': '2026-10-08T13:10:00Z',
                                  'coin': 'ADA',
                                  'spot': {'wallet': 2040.0, 'book': 910.57, 'outside': 1129.43,
                                           'explained': 1100.0, 'unexplained': 29.43}}}
    page = render([('demo', c)])
    assert ("<div class=\"dim\">wallet 2,040 ADA · this bot's book 910.57 · 1,129.43 not this "
            "bot's — the inverse books' P&amp;L and fees since 2026-10-08 account for 1,100; "
            '29.43 unexplained (funding not counted)') in page
    c['terms']['spoADAUSDTl']['spot'].update(explained=100.0, unexplained=1029.43)
    assert '<div class="neg">wallet 2,040 ADA' in render([('demo', c)])      # mostly unexplained: red
    c['terms']['spoADAUSDTl']['spot'] = {'wallet': 2040.0, 'book': 910.57, 'outside': 1129.43,
                                         'explained': None, 'unexplained': None}
    page = render([('demo', c)])
    assert "1,129.43 not this bot's</div>" in page and 'account for' not in page   # no ledger: no claim
    assert "<tr><td>wallet · this bot's book · not this bot's</td>" in KEY


def spec_X14_the_card_shows_how_much_of_the_loss_limit_is_used():
    """The engine's own count rides its snapshot; the card says it, red
    from three quarters."""
    import copy
    from gridgremlin.main import snapshot_row
    from panel.server import render

    class B:
        botid, alive, _last_pos, offset = 'spoADAUSDTl', True, 5.0, 0
        cfg = {'max_loss': 50.0}
        _loss_now = -12.4
    row = snapshot_row([B()], {'equity': 1.0, 'mm_rate': 0.0}, 0)
    assert row['bots']['spoADAUSDTl']['loss'] == {'limit': 50.0,
                                                  'result': -12.4}

    class NoLimit(B):
        _loss_now = None
    assert 'loss' not in snapshot_row(
        [NoLimit()], {'equity': 1.0, 'mm_rate': 0.0}, 0)['bots'][
        'spoADAUSDTl']
    c = copy.deepcopy(CONTRACT)
    c.setdefault('watchdog', {}).setdefault('belief', {}).setdefault(
        'bots', {})['spoADAUSDTl'] = row['bots']['spoADAUSDTl']
    html = render([('demo', c)])
    assert 'loss limit: down 12.40 of 50 USDT (25% used)' in html
    c['watchdog']['belief']['bots']['spoADAUSDTl']['loss']['result'] = -40.0
    assert '<div class="neg">loss limit: down 40.00 of 50 USDT (80% used)' \
        in render([('demo', c)])
    c['watchdog']['belief']['bots']['spoADAUSDTl']['loss']['result'] = 7.0
    assert 'loss limit: down 0.00 of 50 USDT (0% used)' in render([('demo', c)])
    assert 'loss limit' not in render([('demo', CONTRACT)])


def _many():
    import copy
    c = copy.deepcopy(CONTRACT)
    for botid in ('linBTCUSDTl', 'linSOLUSDTs', 'linETHUSDTl',
                  'linBTCUSDTs', 'invBTCUSDl'):
        c['bots'][botid] = None                    # quiet bots: belief cards
    return c


def spec_U12_the_bots_can_be_arranged_by_side_or_by_pairs():
    """Owner, 2026-10-02: "sort the cards/table into long/short/pairs
    positions by venue". An arrangement only — every bot once, per venue."""
    from panel.server import grouped, render
    c = _many()
    listed = [b for b in c['bots']]
    assert grouped(c) == [('', list(c['bots'].items()))]
    side = grouped(c, 'side')
    assert [t for t, _ in side] == ['longs', 'shorts']
    assert [b for b, _ in side[0][1]] == ['spoADAUSDTl', 'linBTCUSDTl',
                                          'linETHUSDTl', 'invBTCUSDl']
    assert [b for b, _ in side[1][1]] == ['linSOLUSDTs', 'linBTCUSDTs']
    pairs = grouped(c, 'pairs')
    assert [b for b, _ in pairs[0][1]] == ['linBTCUSDTl', 'linBTCUSDTs']
    assert 'invBTCUSDl' in [b for b, _ in pairs[1][1]]     # another market
    for view in ('all', 'side', 'pairs', 'strategy', 'market'):
        got = [b for _, rows in grouped(c, view) for b, _ in rows]
        assert sorted(got) == sorted(listed), view         # each bot once
    c2 = _many()
    del c2['bots']['linBTCUSDTs']                          # no pair at all:
    assert [t for t, _ in grouped(c2, 'pairs')] == ['on their own']
    cards = render([('demo', c)], view='pairs')
    assert '<div class="grp">pairs — one market, long and short</div>' \
        in cards
    assert cards.index('BTCUSDT long') < cards.index('BTCUSDT short') \
        < cards.index('on their own')
    assert '<b class="on">pairs</b>' in cards and 'href="/?view=side"' in cards
    assert 'href="/table?view=pairs"' in cards             # the choice rides
    table = render([('demo', c)], table=True, view='side')
    assert '<th colspan="15" class="grp">shorts</th>' in table
    assert 'href="/table?view=pairs"' in table and 'href="/?view=side"' \
        in table
    assert 'class="grp"' not in render([('demo', c)])      # as listed
    assert 'arrange:' not in render([('demo', c)], static='then')
    assert '<b class="on">as listed</b>' in render([('demo', c)], view='nonsense')


def spec_U13_the_rehearsal_keeps_what_was_typed():
    """Owner, 2026-10-02: "when clicking rehearse it refreshes all the
    details typed into the boxes". A result and a refusal both come back
    above the same numbers."""
    from panel.server import rehearse_form, verdict
    typed = {'symbol': 'suiusdt', 'side': 'short', 'lower': '1.05',
             'upper': '1.30', 'rungs': '21', 'capital': '800', 'days': '14'}
    for page in (verdict({}, {'refused': 'no'}, typed=typed),
                 rehearse_form(typed)):
        for name, value in typed.items():
            if name != 'side':
                assert f'name="{name}" size=' in page
                assert f'value="{value}"' in page, name
        assert '<option selected>short</option>' in page
    blank = rehearse_form()
    assert 'value="ADAUSDT"' in blank and '<option selected>long' in blank
    assert '<th>investment</th>' in blank and '<th>grids</th>' in blank
    hostile = rehearse_form({'symbol': '"><script>x</script>'})
    assert '<script>x' not in hostile                  # typed text is text


def spec_U13_a_rehearsal_that_cannot_run_says_why_on_the_page():
    """Owner, 2026-10-02: "where can i view the panel journal to see why
    the rehearsal process died?" Nowhere — the page pointed at a journal
    the reason never reached. A market the venue does not list and an
    empty days box are refusals in words, on the page."""
    import json as _json
    import gridgremlin.exchange.bybit.klines as kl
    from gridgremlin.backtest_cli import run_draft
    draft = _json.dumps({'market_type': 'linear', 'venue': 'bybit',
                         'symbol': 'BTC', 'side': 'long', 'capital': 1500,
                         'lower': 100000, 'upper': 130000, 'rungs': 16})
    saved = kl.fetch_instrument
    try:
        kl.fetch_instrument = lambda c, s: [][0]          # an empty list
        out = run_draft(draft, 7, 60, 0.0002)
        assert out == {'refused': 'BTC: Bybit lists no such linear market '
                                  '— its markets are named like BTCUSDT'}

        def unreachable(c, s):
            raise OSError('timed out')
        kl.fetch_instrument = unreachable
        assert "could not reach Bybit's public data (timed out)" in \
            run_draft(draft, 7, 60, 0.0002)['refused']
    finally:
        kl.fetch_instrument = saved
    srv, base = _serve(CONTRACT)
    try:
        req = urllib.request.Request(
            f'{base}/rehearse', method='POST',
            data=b'gg=1&symbol=ADAUSDT&side=long&lower=0.2&upper=0.3'
                 b'&rungs=16&capital=1500&days=',
            headers={'Cookie': 'gg=tok123'})
        page = urllib.request.urlopen(req).read().decode()
        assert 'how many days of history' in page
        assert 'class="refusal"' in page and 'nothing was saved' in page
        assert 'value="0.2"' in page                   # and the form is kept
        assert 'see the panel journal' not in page
    finally:
        srv.shutdown()


def _dead(contract_bot=True):
    import copy
    c = copy.deepcopy(CONTRACT)
    c['bots']['linAVAXUSDTs'] = (dict(c['bots']['spoADAUSDTl'], side='short')
                                 if contract_bot else None)
    c.setdefault('watchdog', {}).setdefault('belief', {}).setdefault(
        'bots', {})['linAVAXUSDTs'] = {'alive': False, 'position': None}
    return c


def spec_U15_long_and_short_read_at_a_glance():
    """Owner, 2026-10-03: the word was there, nothing made it stand out.
    A coloured tag and a coloured edge on the card; the tag in the table."""
    from panel.server import CSS, render
    cards = render([('demo', _dead())])
    assert '<div class="card long"><div><span class="side long">LONG</span>' \
        in cards
    assert '<div class="card short"><div><span class="side short">SHORT' \
        in cards
    table = render([('demo', _dead())], table=True)
    assert '<td><span class="side short">SHORT</span> linAVAXUSDTs' in table
    assert '.side.long{background:var(--pos)}' in CSS
    assert '.card.short{border-left:4px solid var(--neg)}' in CSS
    assert 'button{background:var(--accent)' in CSS    # buttons stand out;
    assert 'button.quiet{' in CSS and 'class="quiet theme"' in cards   # the
                                                       # theme toggle stays small


def spec_X15_a_dead_bots_card_offers_the_close_and_says_DEAD():
    from panel.server import render
    for c in (_dead(True), _dead(False)):          # fills in the window or
        page = render([('demo', c)])               # not: dead is said either way
        assert 'class="neg st st-dead"' in page and '>DEAD</span>' in page
        assert "href='/close?fleet=0&bot=linAVAXUSDTs'>close position" in page
    assert '/close?fleet=0&bot=spoADAUSDTl' not in render([('demo', _dead())])
    flat = _dead(True)                             # stood down flat, as HL
    flat['bots']['linAVAXUSDTs']['position'] = 0.0  # AVAX did after its last
    page = render([('demo', flat)])                # round (2026-10-06)
    assert '>DEAD</span>' in page and '/close?fleet=0&bot=linAVAXUSDTs' not in page
    seen = _dead(False)                            # no fills in the window,
    seen['watchdog']['belief']['bots']['linAVAXUSDTs']['position'] = 0.0
    assert '/close?fleet=0&bot=linAVAXUSDTs' not in render([('demo', seen)])


def spec_X15_the_close_is_armed_typed_and_run_by_the_engine():
    from panel.server import Handler
    srv, base = _serve(_dead())

    def call(path, data=None):
        req = urllib.request.Request(
            base + path, data=data, headers={'Cookie': 'gg=tok123'})
        try:
            return 200, urllib.request.urlopen(req).read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()
    saved = Handler._run_close, Handler.units
    ran = []
    try:
        assert call('/close?fleet=0&bot=linAVAXUSDTs')[0] == 404   # not armed
        Handler.units = ('some.service',)
        Handler._run_close = lambda self, fi, botid, dry: (
            ran.append((botid, dry)) or
            {'botid': botid, 'side': 'short', 'symbol': 'AVAXUSDT',
             'held': 53.8, 'avg_entry': 11.125, 'mark': 11.124,
             **({} if dry else {'closed': 53.8, 'left': 0.0})})
        code, page = call('/close?fleet=0&bot=linAVAXUSDTs')
        assert code == 200 and 'position of <b>53.8</b> AVAXUSDT' in page
        assert 'can only reduce the position' in page
        assert 'class="danger">close at market' in page
        assert ran == [('linAVAXUSDTs', True)]         # looked, sold nothing
        code, page = call('/close', b'gg=1&fleet=0&bot=linAVAXUSDTs'
                                    b'&confirm=yes')
        assert 'not closed' in page and len(ran) == 1  # a click is no decision
        code, page = call('/close', b'gg=1&fleet=0&bot=linAVAXUSDTs'
                                    b'&confirm=LINAVAXUSDTS')      # U18
        assert 'closed 53.8' in page and ran[-1] == ('linAVAXUSDTs', False)
    finally:
        Handler._run_close, Handler.units = saved
        srv.shutdown()


def spec_R11_the_inverse_card_shows_dollars_and_the_coin():
    import copy
    from panel.server import render, settle
    c = copy.deepcopy(CONTRACT)
    c['bots']['invBTCUSDl'] = dict(
        c['bots']['spoADAUSDTl'], inverse=True, position=7616.0,
        avg_cost=85157.2, mark=84578.1, realized=-21.98, fees=9.4,
        unreal_at_mark=-51.2,
        settle={'coin': 'BTC', 'realized': -0.00026, 'fees': 0.000111,
                'unreal': -0.000605})
    page = _everything(c)
    assert '-82.58</span>' in page                  # -21.98 - 9.4 - 51.2
    assert '-0.000976 BTC</span> <span class="dim">after fees' in page
    assert ('in the coin itself</td><td>realized -0.000260, fees 0.000111, '
            'funding —, unreal -0.000605') in page       # D63: unread
    assert settle(c['bots']['invBTCUSDl'], 0.001) == '~7,608.38 quote'
    c['bots']['invETHUSDl'] = dict(c['bots']['invBTCUSDl'],
                                   settle=dict(c['bots']['invBTCUSDl']['settle'],
                                               coin='ETH'))
    assert '-0.000976 ETH</span>' in _everything(c)   # any coin


def spec_U16_a_card_states_its_investment_and_leverage():
    """Owner, 2026-10-03: "the leverage for positions isnt displayed on the
    cards". Investment, leverage and the most in the market, from the
    row's own numbers."""
    import copy
    from panel.server import render
    c = copy.deepcopy(CONTRACT)
    c['terms'] = {'spoADAUSDTl': {'capital': 3000.0, 'leverage': 1.0,
                                  'notional': 3000.0}}
    page = render([('demo', c)])
    assert ('investment 3,000 USDT · up to 3,000 USDT in the market') in page
    assert 'x</b>' not in page                        # 1x is not said
    c['terms']['spoADAUSDTl'] = {'capital': 2000.0, 'leverage': 10.0,
                                 'notional': 20000.0}
    page = render([('demo', c)])
    assert 'investment 2,000 USDT at <b>10x</b> · up to 20,000 USDT in the market' \
        in page
    assert 'investment' not in render([('demo', CONTRACT)])   # no terms: none
    c['terms']['spoADAUSDTl'] = {'capital': 46600.0, 'leverage': 75.0,
                                 'notional': 3495000.0}
    assert 'investment 46,600 USDT at <b>75x</b> · up to 3,495,000 USDT in the market' \
        in render([('demo', c)])                      # never 3.5e+06


def spec_V14_a_card_shows_the_exchanges_margin_on_the_position():
    """Owner, 2026-10-03: "MM and IM". The engine reads the venue's own
    initial and maintenance margin each cycle, the snapshot carries them,
    the card says them."""
    import copy
    from gridgremlin.main import snapshot_row
    from panel.server import render

    class B:
        botid, alive, _last_pos, offset = 'spoADAUSDTl', True, 5.0, 0
        cfg = {}
        margin_view = {'im': 1842.5, 'mm': 92.1, 'leverage': 10.0}
    row = snapshot_row([B()], {'equity': 1.0, 'mm_rate': 0.0}, 0)
    assert row['bots']['spoADAUSDTl']['margin'] == B.margin_view
    c = copy.deepcopy(CONTRACT)
    c.setdefault('watchdog', {}).setdefault('belief', {}).setdefault(
        'bots', {})['spoADAUSDTl'] = row['bots']['spoADAUSDTl']
    page = render([('demo', c)])
    assert 'margin IM 1,842.50 USDT · MM 92.10 USDT · at 10x on the exchange' in page
    B.margin_view = {'im': 300.0, 'mm': None, 'leverage': None}   # HL's shape
    row = snapshot_row([B()], {'equity': 1.0, 'mm_rate': 0.0}, 0)
    c['watchdog']['belief']['bots']['spoADAUSDTl'] = row['bots']['spoADAUSDTl']
    assert '>margin IM 300.00 USDT</div>' in render([('demo', c)])
    B.margin_view = None                                          # flat
    assert 'margin' not in snapshot_row([B()], {'equity': 1.0,
                                                'mm_rate': 0.0}, 0)['bots'][
        'spoADAUSDTl']


def spec_U44_a_holding_is_said_in_coins_value_and_cost():
    """Owner 2026-10-05: "fixed coin sizing should be a toggle so users can
    see the value, cost, asset. bybit lets you choose these as user
    preferences." Every card says all three; the page's switch shows one."""
    from panel.server import holding_html, coin_of, render, CSS
    assert coin_of('linBTCUSDTl') == 'BTC' and coin_of('linBTCPERPl') == 'BTC'
    assert coin_of('invETHUSDl') == 'ETH' and coin_of('linSOLl') == 'SOL'
    assert coin_of('linFARTCOINUSDTl') == 'FARTCOIN'
    h = holding_html(2.0, 80000.0, 85000.0, 'linBTCUSDTl')
    assert '2 BTC' in h and 'worth 170,000 USDT' in h and 'cost 160,000 USDT' in h
    s = holding_html(-1.5, 2700.0, 2800.0, 'linETHUSDTs')
    assert '-1.5 ETH' in s and 'worth 4,200 USDT' in s
    inv = holding_html(8000.0, 80000.0, 100000.0, 'invBTCUSDl', inverse=True)
    assert '0.08 BTC' in inv and 'worth 8,000 USD' in inv and '(0.1 BTC)' in inv
    assert holding_html(0.0, 0.0, 1.0, 'linBTCUSDTl') == 'holding nothing'
    page = render([])
    assert "ggSize('coin')" in page and '<h3>size in</h3>' in page
    assert '.only-coin .u-value' in CSS


def spec_U43_several_units_restart_together_or_none_does():
    """Owner 2026-10-05: "can i restart both fleets at the same time from
    the panel by typing both lines?" Several names, spaces or commas; every
    one must be a unit, or nothing is done; one systemctl call carries them."""
    import panel.routes as ps
    calls = []

    class R:
        stdout, stderr, returncode = 'active\n', '', 0
    saved = ps.subprocess.run
    ps.subprocess.run = lambda args, **k: (calls.append(args), R())[1]

    class Me:
        units = ('grid-gremlin3-demo', 'grid-gremlin3-hl')
        supervise = False
        pages = []

        def _tombs_path(self):
            from pathlib import Path
            return Path('/nonexistent/tombstones.json')

        def _fleet_bots(self):
            return {}

        def _page(self, body):
            self.pages.append(body)

        def _deny(self, code, why):
            self.pages.append(f'{code} {why}')
    try:
        me = Me()
        ps.Handler._control_act(me, {'confirm': 'grid-gremlin3-demo, grid-gremlin3-hl',
                                     'action': 'restart'}, '/unit')
        assert calls == [['systemctl', '--user', 'restart',
                          'grid-gremlin3-demo', 'grid-gremlin3-hl']]
        assert 'restart' in me.pages[-1] and 'not done' not in me.pages[-1]
        calls.clear()
        ps.Handler._control_act(me, {'confirm': 'grid-gremlin3-demo nope',
                                     'action': 'restart'}, '/unit')
        assert calls == [] and 'not done' in me.pages[-1]      # all or none
        ps.Handler._control_act(me, {'confirm': '', 'action': 'restart'}, '/unit')
        assert calls == [] and 'not done' in me.pages[-1]
    finally:
        ps.subprocess.run = saved


def spec_U20_a_bots_name_in_the_unit_box_is_pointed_to_its_tombstone():
    """Owner 2026-10-03: typed a stopped bot's name into the unit box and
    read 'type one of the armed unit names exactly'. The two boxes look
    alike; the refusal now says which box the name belongs to."""
    from panel.server import unit_refusal
    units, tombs = ['grid-gremlin3-hl'], {'linAVAXl': {'reason': 'x'}}
    assert unit_refusal('grid-gremlin3-hl', units, tombs) is None
    why = unit_refusal('linavaxl', units, tombs)          # capitals: U18
    assert 'linAVAXl' in why and 'revive' in why and 'beside' in why
    why = unit_refusal('nothing', units, tombs)
    assert 'grid-gremlin3-hl' in why and 'click is not a decision' in why


# --- V15 / U35: what rests, what waits, and what the state words mean ---------

def spec_V15_the_snapshot_says_what_rests_and_what_waits():
    from gridgremlin.main import snapshot_row

    class B:
        botid, alive, _last_pos, offset = 'linFARTCOINUSDTl', True, 50322.0, 0
        cfg = {}
        orders_view = {'within_pct': 0.05, 'resting': {'buys': 1, 'sells': 0},
                       'waiting': {'buys': 0, 'sells': 3, 'nearest': 0.2054}}
    row = snapshot_row([B()], {'equity': 1.0, 'mm_rate': 0.0}, 0)
    assert row['bots']['linFARTCOINUSDTl']['orders']['waiting']['sells'] == 3

    class Dead(B):
        alive = False
    assert 'orders' not in snapshot_row([Dead()], {'equity': 1.0,
                                                  'mm_rate': 0.0}, 0)['bots'][
        'linFARTCOINUSDTl']


def spec_U35_the_card_says_what_rests_and_the_state_words_explain_themselves():
    from panel.server import orders_line, state_tag, render, STATE_WORDS
    ov = {'within_pct': 0.05, 'resting': {'buys': 1, 'sells': 0},
          'waiting': {'buys': 0, 'sells': 3, 'nearest': 0.2054}}
    line = orders_line(ov)
    assert line.startswith('resting: 1 buy')
    assert 'waiting: 3 sells' in line and 'within 5% of them' in line
    assert 'nearest at 0.2054' in line
    assert orders_line({'within_pct': 0.05, 'resting': {'buys': 0, 'sells': 0},
                        'waiting': {'buys': 0, 'sells': 0}}) == 'nothing resting'
    assert orders_line(None) is None
    for word in STATE_WORDS:
        tag = state_tag(word, 'dim')
        assert 'title="' in tag and f'st-{word.lower().replace(" ", "-")}' in tag
    c = {'window_hours': 6.0, 'generated_ms': 0, 'unowned': {},
         'bots': {'linFARTCOINUSDTl': None},
         'watchdog': {'belief': {'age_s': 2, 'bots': {
             'linFARTCOINUSDTl': {'alive': True, 'position': 50322.0,
                                  'orders': ov}}}}}
    page = render([('demo', c)])
    assert 'resting: 1 buy' in page and 'within 5% of them' in page
    assert 'st st-holding' in page
    from panel.server import KEY
    assert 'Hover any state word' in KEY                  # the key page


# --- U36: every card says what kind of thing the bot is -----------------------

def spec_U36_a_card_names_the_market_the_leverage_and_the_growing_add_ons():
    from panel.server import kind_line, render
    dca = {'capital': 1500, 'leverage': 3.0, 'market_type': 'linear',
           'strategy': 'martingale', 'multiplier': 1.5, 'add_ons': 2}
    line = kind_line(dca)
    assert line.startswith('DCA on futures, USDT/USDC-margined · 3x leverage')
    assert 'martingale-style' in line and 'each add-on 1.5× the last, up to 2' in line
    assert 'title="each add-on order is 1.5×' in line
    flat = kind_line(dict(dca, multiplier=1.0))
    assert 'equal add-ons' in flat and 'martingale' not in flat
    grid = kind_line({'capital': 2000, 'leverage': 10.0, 'market_type': 'inverse',
                      'strategy': 'grid'})
    assert grid == 'grid on futures, coin-margined (inverse) · 10x leverage'
    assert kind_line({'market_type': 'spot', 'strategy': 'grid', 'leverage': 1.0}) \
        == 'grid on spot · no leverage'
    assert kind_line({'market_type': 'spot', 'strategy': 'grid', 'leverage': 1.0,
                      'spot_borrow': True}).startswith('grid on spot on margin')
    assert kind_line(None) is None and kind_line({'capital': 1}) is None
    c = {'window_hours': 6.0, 'generated_ms': 0, 'unowned': {},
         'bots': {'linSOLUSDTs': None},
         'terms': {'linSOLUSDTs': dict(dca, capital=5000, leverage=10.0)},
         'watchdog': {'belief': {'age_s': 2, 'bots': {
             'linSOLUSDTs': {'alive': True, 'position': 0.0}}}}}
    page = render([('demo', c)])
    assert 'DCA on futures, USDT/USDC-margined · 10x leverage · ' in page
    assert page.index('DCA on futures') < page.index('investment 5,000')


def spec_U37_the_orders_sentence_spans_the_card():
    """Owner 2026-10-04: the sentence sat in the value column, two thirds
    across. It spans both columns now, its label inline."""
    from panel.server import render, CSS
    ov = {'within_pct': 0.05, 'resting': {'buys': 1, 'sells': 0},
          'waiting': {'buys': 0, 'sells': 3, 'nearest': 0.2}}
    c = {'window_hours': 6.0, 'generated_ms': 0, 'unowned': {},
         'bots': {'linXUSDTl': {'fills': 1, 'realized': 0.0, 'fees': 0.0,
                                'unreal_at_mark': 0.0, 'bought': 1.0,
                                'sold': 0.0, 'position': 1.0, 'avg_cost': 1.0,
                                'mark': 1.0, 'truncated': False, 'trips': 0,
                                'per_trip': None, 'strategy': 'grid',
                                'side': 'long', 'same_rung': 0,
                                'entry_fills': 1, 'gap_trips': 0}},
         'watchdog': {'belief': {'age_s': 2, 'bots': {
             'linXUSDTl': {'alive': True, 'position': 1.0, 'orders': ov}}}}}
    page = _everything(c)
    assert "<td colspan='2' class='wide'><b>orders</b> — resting: 1 buy" in page
    assert 'details td.wide{text-align:left;white-space:normal;width:auto' in CSS


def spec_U46_every_link_is_a_button_and_no_words_run_together():
    """Owner 2026-10-06: "leverageheld as one word on all cards … make all
    clickable links buttons." The kind line ran into the holding on one
    line; links read as text between dots."""
    import re
    import copy
    from panel.server import CSS, render, tidy
    c = copy.deepcopy(CONTRACT)
    c['terms'] = {'spoADAUSDTl': {'capital': 1000, 'leverage': 75.0,
                                  'market_type': 'linear', 'strategy': 'grid'}}
    page = render([('demo', c)])
    assert '75x leverage' in page                    # the kind line is there
    text = re.sub(r'<[^>]+>', '', re.sub(r'</div>|<br>', '\n', page))
    assert not re.search(r'leverage(holding|held)', text)
    assert 'a[href]{display:inline-block' in CSS and 'b.on{' in CSS
    assert tidy('<a href="/a">a</a> · <a href="/b">b</a>') == \
        '<a href="/a">a</a> <a href="/b">b</a>'
    assert tidy('<b class="on">all</b> · <a href="/x">x</a>') == \
        '<b class="on">all</b> <a href="/x">x</a>'
    assert tidy('fees <b>+1</b> · open <b>-2</b>') == \
        'fees <b>+1</b> · open <b>-2</b>'               # prose keeps its dots


def spec_U47_one_readout_per_fleet_at_a_time():
    """Each page request whose cache had expired started its own readout;
    on a slow venue they piled up — 18 demo readouts at once, 350 timeouts
    in an hour, the page and a rehearsal hung (2026-10-06). One runs; stale
    is served at once meanwhile; with nothing yet, the rest wait for it."""
    import json as _json
    import tempfile
    import threading
    import time as _time
    from pathlib import Path
    import panel.routes as srv
    running, peak, calls = [0], [0], [0]
    gate = threading.Event()

    class Out:
        stdout = _json.dumps(CONTRACT)

    def slow_run(*a, **kw):
        calls[0] += 1
        running[0] += 1
        peak[0] = max(peak[0], running[0])
        gate.wait(5)
        running[0] -= 1
        return Out()
    with tempfile.TemporaryDirectory() as d:
        fleet = str(Path(d) / 'fleet.demo.json')
        Path(fleet).write_text(_json.dumps({'bots': [{'symbol': 'X'}]}))

        class Me:
            hours = 24.0
        me = Me()
        me._read_contract = lambda f: srv.Handler._read_contract(me, f)
        saved_run, saved_cache = srv.subprocess.run, dict(srv.Handler._cache)
        srv.subprocess.run = slow_run
        try:
            srv.Handler._cache.pop(fleet, None)
            got = []
            ts = [threading.Thread(target=lambda: got.append(
                srv.Handler._contract(me, fleet))) for _ in range(6)]
            for t in ts:
                t.start()
            _time.sleep(0.2)
            gate.set()
            for t in ts:
                t.join(5)
            assert calls[0] == 1 and peak[0] == 1         # one read, all six
            assert len(got) == 6                          # answered by it
            gate.clear()
            srv.Handler._cache[fleet] = (_time.time() - 3600, {'stale': 1})
            t0 = _time.time()
            for _ in range(5):                            # stale: at once,
                assert srv.Handler._contract(me, fleet) == {'stale': 1}
            assert _time.time() - t0 < 1.0                # nobody waits
            _time.sleep(0.2)
            assert peak[0] == 1 and calls[0] == 2         # one refresh only
            gate.set()
        finally:
            srv.subprocess.run = saved_run
            srv.Handler._cache.clear()
            srv.Handler._cache.update(saved_cache)


# --- D63: funding is its own line ---------------------------------------------

def spec_D63_a_cards_total_carries_funding_and_names_it():
    from panel.server import render
    c = json.loads(json.dumps(CONTRACT))
    b = c['bots']['spoADAUSDTl']
    b['funding'] = -3.10                            # paid
    page = _everything(c)
    # 5.04 - 2.07 - 3.10 - 4.83 = -4.96, on the card and in the box
    assert page.count('-4.96</span>') >= 2, 'total left funding out'
    assert 'funding <b class="neg">-3.10</b>' in page
    assert "<tr><td>funding</td>" in page and '-3.10' in page
    table = render([('demo', c)], table=True)
    assert '<th>funding</th>' in table and '-4.96' in table


def spec_D63_unread_funding_says_so_and_is_not_a_zero():
    from panel.server import render
    c = json.loads(json.dumps(CONTRACT))
    c['bots']['spoADAUSDTl']['funding'] = None
    page = render([('demo', c)])
    assert 'funding —' in page
    assert '-1.86</span>' in page                  # 5.04 - 2.07 - 4.83


def spec_D63_every_renderer_sums_through_one_total():
    import inspect
    import gridgremlin.digest as dg
    import gridgremlin.phone as ph
    import panel.render as sv                    # the renderer, since the split
    for mod in (dg, ph, sv):
        src = inspect.getsource(mod)
        assert "['realized'] - v['fees'] +" not in src, mod.__name__
        assert 'card_total(' in src, mod.__name__


def spec_D63_a_capped_card_says_where_its_fills_start():
    # pins: R22
    from panel.server import render
    c = json.loads(json.dumps(CONTRACT))
    c['generated_ms'] = 30 * 86400000
    b = c['bots']['spoADAUSDTl']
    b.update(counted_from='cap', counted_since_ms=0,
             first_ms=c['generated_ms'] - int(4.4 * 86400000))
    page = render([('demo', c)])
    assert 'never flat in 30 d; its fills start 4.4 d ago' in page
    assert 'last 30 d, never flat in it' not in page


def spec_V17_a_card_says_where_the_exchange_liquidates_it():
    """2026-10-06: HYPE, isolated at 10x, was liquidated with nothing on its
    card saying how near it stood. The venue's own liquidation price rides
    the margin view into the snapshot; the card says it and the distance
    from the mark, red inside 5%."""
    import copy
    from gridgremlin.main import snapshot_row
    from panel.server import render

    class B:
        botid, alive, _last_pos, offset = 'spoADAUSDTl', True, 5.0, 0
        cfg = {}
        margin_view = {'im': 7.29, 'mm': None, 'leverage': 10.0, 'liq': 0.1950}
    row = snapshot_row([B()], {'equity': 1.0, 'mm_rate': 0.0}, 0)
    assert row['bots']['spoADAUSDTl']['margin']['liq'] == 0.1950
    c = copy.deepcopy(CONTRACT)                     # the card's mark: 0.2017
    c.setdefault('watchdog', {}).setdefault('belief', {}).setdefault(
        'bots', {})['spoADAUSDTl'] = row['bots']['spoADAUSDTl']
    page = render([('demo', c)])
    assert '<div class="neg">liquidates at 0.195 · 3.3% away' in page, page[-3000:]
    B.margin_view['liq'] = 0.1500                   # far: said, not red
    c['watchdog']['belief']['bots']['spoADAUSDTl'] = snapshot_row(
        [B()], {'equity': 1.0, 'mm_rate': 0.0}, 0)['bots']['spoADAUSDTl']
    assert '<div class="dim">liquidates at 0.15 · 25.6% away' in render([('demo', c)])
    B.margin_view['liq'] = None                     # cross, no price stated
    c['watchdog']['belief']['bots']['spoADAUSDTl'] = snapshot_row(
        [B()], {'equity': 1.0, 'mm_rate': 0.0}, 0)['bots']['spoADAUSDTl']
    assert 'liquidates at' not in render([('demo', c)])


def spec_V17_the_bot_keeps_the_venues_liquidation_price():
    import inspect
    from gridgremlin.bot import Bot
    src = inspect.getsource(Bot)
    assert "'liq': pv.get('liq_price')" in src


# --- D65: the network is shown, never set, from the panel ---------------------

def spec_D65_the_panel_can_never_set_the_network():
    """Owner 2026-10-07: the demo/mainnet switch is configured from the files
    alone. No panel source names the switches; a row carrying one is refused
    at the gate like any unknown key."""
    from pathlib import Path
    from panel.create import merge_proposal, validate_whole
    root = Path(__file__).resolve().parents[1] / 'panel'
    for f in sorted(root.glob('*.py')):
        src = f.read_text()
        for word in ('allow_mainnet', 'allow-mainnet', 'BYBIT_DEMO',
                     'BYBIT_TESTNET', 'HL_TESTNET', "'.env'", '".env"'):
            assert word not in src, f'{f.name} names {word}'
    _, fleet, wd = merge_proposal(_FLEET, _WD,
                                  {'bot': dict(_BOT, allow_mainnet=True)})
    why = validate_whole(fleet, wd, lambda c: _fake_adapter())
    assert why and 'allow_mainnet' in why, why


def spec_D65_the_snapshot_carries_the_network_the_fleet_connected_to():
    import inspect
    import gridgremlin.main as m

    class B:
        botid, alive, _last_pos, offset = 'linBTCl', True, 0.0, 0
        cfg = {}
        margin_view = None
    row = m.snapshot_row([B()], {'equity': 1.0, 'mm_rate': 0.0}, 0,
                         {'hyperliquid': 'testnet'})
    assert row['tiers'] == {'hyperliquid': 'testnet'}
    assert 'tiers' not in m.snapshot_row([B()], {'equity': 1.0,
                                                 'mm_rate': 0.0}, 0)
    assert "{v: c.env for v, c in clients.items()}" in inspect.getsource(m.run)


def spec_D65_every_heading_names_its_network_in_the_exchanges_words():
    import copy
    from panel.server import render, TIER_NAMES
    c = copy.deepcopy(CONTRACT)
    c['watchdog']['belief'] = {'tiers': {'bybit': 'demo'}, 'bots': {}}
    page = render([('demo', c)])
    assert 'class="tier tier-test" href="/trading"' in page and '>Demo Trading<' in page
    table = render([('demo', c)], table=True)
    assert '>Demo Trading<' in table
    c['watchdog']['belief'] = {'bots': {}}                 # no snapshot yet:
    c['account'] = {'hyperliquid': {'notional': 0.0, 'equity': 1.0,  # the
                                    'collateral': 1.0, 'tier': 'mainnet'}}  # readout's own
    page = render([('hl', c)])
    assert 'class="tier tier-main"' in page and '>Mainnet<' in page
    assert TIER_NAMES[('bybit', 'testnet')] == 'Testnet'


def spec_D65_the_trading_page_explains_and_does_not_arm():
    from panel.server import TRADING
    for word in ('allow_mainnet', 'allow-mainnet', 'BYBIT_', 'HL_TESTNET',
                 '.env'):
        assert word not in TRADING, word
    assert 'Mainnet' in TRADING and 'Demo Trading' in TRADING
    srv, base = _serve(CONTRACT)
    try:
        r = urllib.request.urlopen(urllib.request.Request(
            f'{base}/trading', headers={'Cookie': 'gg=tok123'}))
        assert 'demo, testnet and mainnet' in r.read().decode()
    finally:
        srv.shutdown()


def spec_U57_the_card_judges_the_price_against_the_slid_window_and_a_quiet_bot_shows_its_price():
    """The owner's review (2026-10-08): 'a few bots appear to be out of
    range'. Two of them had slid 27 rungs and were inside their window;
    the card judged against the home range. Two quiet spot bots showed no
    price at all: the readout carried a mark only on a book."""
    import copy
    from panel.server import render
    c = copy.deepcopy(CONTRACT)
    # the ADA grid: home 0.155-0.23 over 16 rungs (gap 0.005); slid -10 rungs the
    # window is 0.105-0.18, and a mark of 0.17 is inside it, not below home
    c['watchdog']['belief']['bots']['spoADAUSDTl'] = {'alive': True, 'position': 910.57, 'offset': -10}
    c['bots']['spoADAUSDTl']['mark'] = 0.17
    html = render([('demo', c)])
    assert 'OUTSIDE' not in html and 'window slid -10 rungs from home' in html
    assert 'above the bottom' in html and 'below the top' in html
    # a quiet bot (no fills in the window) with a mark from the readout: placed, not blank
    q = copy.deepcopy(CONTRACT)
    q['bots']['spoADAUSDTl'] = None
    q['watchdog']['belief']['bots']['spoADAUSDTl'] = {'alive': True, 'position': 910.57}
    q['marks'] = {'spoADAUSDTl': 0.2017}
    html = render([('demo', q)])
    assert 'no fills' in html and 'price 0.2017 —' in html and 'above the bottom' in html
