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


from panel.routes import form_token
FT = form_token('tok123')        # P6b: the forms' token for this launch

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
    from panel.position_view import position_page
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
        assert '<svg' in html and 'circle' in html      # the range strip
        assert 'watchdog swept 41s ago' in html
        # U56: the numbers are the position's own page, behind the same cookie
        req = urllib.request.Request(f'{base}/position?fleet=0&bot=spoADAUSDTl',
                                     headers={'Cookie': 'gg=tok123'})
        html = op.open(req).read().decode()
        assert 'as the exchange shows it' in html and '<td>0.207</td>' in html and '910.57' in html
        # settlement: 910.57 * 0.2017 * (1 - 0.0025) = 183.20
        assert '183.2' in html, 'stop-now estimate missing or wrong'
        assert '9% of 9,700' in html          # 910.57 / 9700 utilization
        req = urllib.request.Request(f'{base}/data',
                                     headers={'Cookie': 'gg=tok123'})
        data = json.loads(op.open(req).read())
        assert data == {'demo': dict(CONTRACT, equity=None)}    # labelled by fleet, unmangled; U63 adds the line
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
        req = urllib.request.Request(f'{base}/rehearse', data=f'gg={FT}'.encode(),
                                     method='POST')
        try:
            urllib.request.urlopen(req)
            assert False, 'unauthed POST accepted'
        except urllib.error.HTTPError as e:
            assert e.code == 401
        req = urllib.request.Request(
            f'{base}/rehearse', data=f'gg={FT}'.encode(), method='POST',
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
    """§12: a panel launched without --unit has NO control surface — its
    page says control is off and offers nothing to press (the bug hunt,
    2026-10-11: a bare 404 behind a link on every page), and the action
    is refused; with it, an unmatched typed confirmation does nothing."""
    srv, base = _serve(CONTRACT)
    try:
        req = urllib.request.Request(f'{base}/control',
                                     headers={'Cookie': 'gg=tok123'})
        page = urllib.request.urlopen(req).read().decode()
        assert 'is off on this' in page and '--units' in page
        assert '<form' not in page.split('</nav>')[-1] and '<button' not in page.split('</nav>')[-1].replace('class="quiet theme"', '')
        req = urllib.request.Request(
            f'{base}/unit', data=f'gg={FT}&action=stop&confirm=wrong'.encode(),
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
    assert path_for(d / 'configs' / 'f.json', {}) == d / 'logs' / 'tombstones-f.json'
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
    assert 'spoADAUSDTl' in frozen and 'HOLDING' in frozen
    assert 'http-equiv="refresh"' in live
    assert 'http-equiv="refresh"' not in frozen
    assert '/?show=control' in live and 'show=control' not in frozen and '/control' not in frozen
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
    for link in ("/?fleet=0&amp;bot=spoADAUSDTl&amp;show=edit'>edit",     # U78c: in the half
                 '/setup?fleet=0&amp;copy=spoADAUSDTl', 'mode=remove'):
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
    assert '.hero{display:grid;grid-template-columns:repeat(7,max-content)' in CSS   # squared; the 7th is U63's line
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
    for href in ('/table', '/?show=control', '/?show=setup', '/?show=rehearse', '/export', '/key'):   # U78d: the half
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
    assert 'nav.side{position:sticky;top:var(--hero)' in CSS and '@media(max-width:60em){.page{display:block}' in CSS
    assert "root.style.setProperty('--hero',hero.offsetHeight+'px')" in cards   # U86: one measure, both columns
    assert '--gap:1em;--gap-s:.5em' in CSS and '.cards{display:grid;gap:var(--gap)' in CSS


def spec_U86_the_sites_look_each_part_boxed_and_the_right_half_never_slides():
    """The owner (2026-10-14): take the site's look — its colours, thicker
    borders and boxes, "more bordering so things look a lot more defined" —
    and the right column must not "scroll down with the rest of the page…
    it moves down a little, then stops". Each exchange sits in its own box;
    cards, money boxes, the strip, the side panel and the right half share
    one thick edge; the right half's pin is the strip's measured height plus
    the gap under it — exactly where it starts — so it never moves."""
    from panel.server import CSS, render
    page = render([('demo', CONTRACT), ('hl', CONTRACT)])
    assert page.count('<section class="fbox"><h1 id="fleet') == 2
    assert page.count('</details></section>') == 2
    assert ':root{--bg:#0b0f0c;--fg:#d7e4da;--dim:#7c8c80;--line:#1c2620;--edge:#2c3d31;' in CSS
    assert '--pos:#36d17a;--neg:#e5534b;--accent:#36d17a;' in CSS and '--bw:2px}' in CSS
    for rule in ('section.fbox{border:var(--bw) solid var(--edge)', '.card{border:var(--bw) solid var(--edge)',
                 '.pnl{border:var(--bw) solid var(--edge)', '.eqbox{border:var(--bw) solid var(--edge)',
                 'border-bottom:var(--bw) solid var(--edge)}', 'border-right:var(--bw) solid var(--edge)}',
                 'border:var(--bw) solid var(--edge);border-radius:8px}'):
        assert rule in CSS, rule
    assert '.pane{position:sticky;top:calc(var(--hero) + var(--gap));' in CSS
    assert 'max-height:calc(100vh - var(--hero) - 2*var(--gap))' in CSS
    assert "root.style.setProperty('--hero',hero.offsetHeight+'px')" in page
    assert 'top:3.2em' not in CSS and '1px solid var(--line)}' not in CSS.split('.card{', 1)[1].split('}', 1)[0]


def spec_U87_the_polish_pass_quiet_heading_line_and_buttons_without_stray_dots():
    """The owner (2026-10-14): "now do the polish pass". The heading is the
    exchange's name; how fresh it is goes on a quiet line under it. A card's
    buttons wrap as a row with no separator dots (a "·" stranded at the
    start of the second line before). The side menu is a box like the right
    half; section labels are small spaced capitals."""
    from panel.server import CSS, render
    page = render([('demo', CONTRACT)])
    h1 = page.split('<h1 id="fleet0">', 1)[1].split('</h1>', 1)[0]
    assert '<span class="meta"><span class="dim">watchdog' in h1 and 'refreshes every' in h1.split('class="meta"', 1)[1]
    foots = [f.split('</div>', 1)[0] for f in page.split('class="dim foot">')[1:]]
    assert foots and all('·' not in f and '>edit</a> <a' in f for f in foots)
    assert 'h1 .meta{display:block;font-size:.78em;font-weight:normal' in CSS
    assert '.card .foot>span:last-child{display:flex;flex-wrap:wrap;gap:.25em}' in CSS
    assert 'nav.side{border:var(--bw) solid var(--edge);border-radius:8px' in CSS
    assert 'nav.side h3,.pane h3{text-transform:uppercase' in CSS and '.pane h3{border-top:1px solid var(--edge)' in CSS


def spec_U88_every_form_on_one_grid_and_each_part_of_a_page_boxed():
    """The owner (2026-10-14): on the advanced form "align all the
    descriptions on one side of the page, still in line with their
    function… the value boxes also arent aligned in nearly all pages", and
    border sections as the site does. Each section of a form was its own
    table, sized to its own words; now every three-cell form row puts its
    label, value box and description on one grid of fixed columns, the
    boxes one width, and each section (and each account on the results
    page) sits in a box. The trade form, which kept box and description in
    one cell, is three cells like the rest, its unit beside its box."""
    import re
    from panel.server import CSS
    from panel.setup import advanced_page, quick_page
    from panel.trade_page import trade_form
    from panel.results import results_page
    assert ':is(form,.fakeform) td:first-child:nth-last-child(3),:is(form,.fakeform) td:first-child:nth-last-child(2){width:17em}' in CSS
    assert ':is(form,.fakeform) td:nth-child(2):nth-last-child(2){width:15em}' in CSS
    assert '.fin{width:100%;max-width:none;box-sizing:border-box}' in CSS
    assert ':is(form,.fakeform) td,:is(form,.fakeform) th{text-align:left}' in CSS
    assert ':is(form,.fakeform)>details,.fsec{border:var(--bw) solid var(--edge);border-radius:8px' in CSS
    for strategy in ('grid', 'martingale'):
        page = advanced_page(strategy, {}, ['demo', 'hl'], 0)
        assert page.count('<div class="fsec">') == 1 and '<form' in page
        for row in re.findall(r'<tr>(.*?)</tr>', page, re.S):
            assert row.count('<td') == 3, row[:80]                 # one grid: label, box, words
    quick = quick_page(['demo'], 0)
    assert quick.count('<div class="fsec">') == 2
    trade = trade_form(['demo'])
    rows = re.findall(r'<tr>(.*?)</tr>', trade, re.S)
    assert len(rows) == 10 and all(r.count('<td') == 3 and '<span class="u">' in r for r in rows)
    assert '<i class="un">%</i>' in trade and '<i class="un">x</i>' in trade
    res = results_page([('demo', {'since_first': {}}), ('hl', {'since_first': {}})])
    assert res.count('<div class="fsec"><h2>') == 2


def spec_U89_cleaner_cards_one_frame_the_state_on_the_right_no_dots():
    """The owner (2026-10-14): "lets do the cleaner cards". A card's top line
    holds the side and name left and the state right, ruled off; the money
    is a quiet panel inside the card, never a second coloured frame (the
    card's side edge already says long or short); the footer is ruled off,
    and no link in it, close trade and clear included, starts with a dot."""
    from panel.server import CSS
    from panel import card as cardmod
    assert '.card>div:first-child>.st{margin-left:auto}' in CSS
    assert '.card .pnl,.card .pnl.pos,.card .pnl.neg{border:0;' in CSS
    assert '.card .foot{border-top:1px solid var(--edge)' in CSS
    import inspect
    src = inspect.getsource(cardmod)
    assert 'links += (f" · <a' not in src and 'links += " · <a' not in src


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
                          'covers a move of <b>-9.00%</b>, then 96,000.00 committed at an '
                          'average of -4.12%</summary>')
    assert '<tr><td>base</td><td>+0.00%</td><td>1,500.00</td><td>1,500.00</td><td>+0.00%</td><td>+1.00%</td></tr>' in box
    assert '<tr><td>6</td><td>-9.00%</td><td>48,000.00</td><td>96,000.00</td><td>-4.12%</td><td>+6.52%</td></tr>' in box
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
    assert 'margin IM 0.013488 BTC · MM 0.001214 BTC' in _everything(inv)
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
    from panel.nav import VIEWS, grouped
    from panel.render import render
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
    assert '<details class="fold"' in live             # U58: a card folds its lower half…
    assert '<details' not in live.split('<details class="fold"')[0].split('class="cards"')[-1]   # …and nothing above it
    assert 'http-equiv="refresh"' in live and KEEP_JS in live
    assert KEEP_JS in render([('demo', CONTRACT)], table=True)
    assert '<script' not in render([('demo', CONTRACT)], static='then')
    for word in ("details[data-k]", "'toggle'", 'scrollTo', 'gg-light'):
        assert word in KEEP_JS, word
    for word in ('http://', 'https://', 'eval(', 'Math.', 'localStorage', 'cookie'):
        assert word not in KEEP_JS, word
    # U61: the one fetch the script makes is of this same page, nothing
    # else — the refresh, or a pick on it (U78: same origin, same path)
    assert KEEP_JS.count('fetch(') == 1 and 'swap(location.href)' in KEEP_JS
    assert 'if(u.origin!==location.origin||u.pathname!==location.pathname)return;' in KEEP_JS


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
    page = _everything(c)
    assert '<div class="neg">waiting: bots holding 8 >= 8 — opens nothing until it clears' in page
    c['bots']['spoADAUSDTl']['position'] = 910.57
    c['watchdog']['belief']['bots']['spoADAUSDTl']['capped'] = 'notional 55,000 >= 50,000'
    page = _everything(c)
    assert '<div class="neg">capped: notional 55,000 >= 50,000 — adds nothing, exits run' in page
    assert 'waiting:' not in _everything(CONTRACT) and 'capped:' not in _everything(CONTRACT)


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
    page = _everything(c)
    assert ("<div class=\"dim\">wallet 2,040 ADA · this bot's book 910.57 · 1,129.43 not this "
            "bot's — the inverse books' P&amp;L and fees since 2026-10-08 account for 1,100; "
            '29.43 unexplained (funding not counted)') in page
    c['terms']['spoADAUSDTl']['spot'].update(explained=100.0, unexplained=1029.43)
    assert '<div class="neg">wallet 2,040 ADA' in _everything(c)      # mostly unexplained: red
    c['terms']['spoADAUSDTl']['spot'] = {'wallet': 2040.0, 'book': 910.57, 'outside': 1129.43,
                                         'explained': None, 'unexplained': None}
    page = _everything(c)
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
    html = _everything(c)
    assert 'loss limit: down 12.40 of 50 USDT (25% used)' in html
    c['watchdog']['belief']['bots']['spoADAUSDTl']['loss']['result'] = -40.0
    assert '<div class="neg">loss limit: down 40.00 of 50 USDT (80% used)' \
        in _everything(c)
    c['watchdog']['belief']['bots']['spoADAUSDTl']['loss']['result'] = 7.0
    assert 'loss limit: down 0.00 of 50 USDT (0% used)' in _everything(c)
    assert 'loss limit' not in _everything(CONTRACT)


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
    assert '<th colspan="16" class="grp">shorts</th>' in table
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
    assert '<label>investment <input' in blank and '<label>grids <input' in blank      # U78d: labelled fields
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
            data=f'gg={FT}&symbol=ADAUSDT'.encode() + b'&side=long&lower=0.2&upper=0.3'
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
    assert '<div class="card long slim"><div><span class="side long">LONG</span>' \
        in cards
    assert '<div class="card short slim"><div><span class="side short">SHORT' \
        in cards
    table = render([('demo', _dead())], table=True)
    assert '<td><span class="side short">SHORT</span> linAVAXUSDTs' in table
    assert '.side.long{background:var(--pos)}' in CSS
    assert '.card.short{border-left:5px solid var(--neg)}' in CSS
    assert 'button{background:var(--accent)' in CSS    # buttons stand out;
    assert 'button.quiet{' in CSS and 'class="quiet theme"' in cards   # the
                                                       # theme toggle stays small


def spec_X15_a_dead_bots_card_offers_the_close_and_says_DEAD():
    from panel.server import render
    for c in (_dead(True), _dead(False)):          # fills in the window or
        page = render([('demo', c)])               # not: dead is said either way
        assert 'class="neg st st-dead"' in page and '>DEAD</span>' in page
        assert "href='/close?fleet=0&amp;bot=linAVAXUSDTs'>close position" in page
    assert '/close?fleet=0&amp;bot=spoADAUSDTl' not in render([('demo', _dead())])
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
    from pathlib import Path                       # P6: the close names a bot of this fleet
    Path(srv.RequestHandlerClass.fleets[0]).write_text(json.dumps(
        {'bots': [{'market_type': 'linear', 'symbol': 'AVAXUSDT', 'side': 'short'}]}))

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
        Handler._run_close = lambda self, fi, botid, dry, expect=None: (
            ran.append((botid, dry)) or
            {'botid': botid, 'side': 'short', 'symbol': 'AVAXUSDT',
             'held': 53.8, 'avg_entry': 11.125, 'mark': 11.124,
             **({} if dry else {'closed': 53.8, 'left': 0.0})})
        code, page = call('/close?fleet=0&bot=linAVAXUSDTs')
        assert code == 200 and 'position of <b>53.8</b> AVAXUSDT' in page
        assert 'can only reduce the position' in page
        assert 'class="danger">close at market' in page
        assert ran == [('linAVAXUSDTs', True)]         # looked, sold nothing
        code, page = call('/close', f'gg={FT}'.encode() + b'&fleet=0&bot=linAVAXUSDTs'
                                    b'&confirm=yes')
        assert 'not closed' in page and len(ran) == 1  # a click is no decision
        code, page = call('/close', f'gg={FT}'.encode() + b'&fleet=0&bot=linAVAXUSDTs'
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
    page = _everything(c)
    assert ('investment 3,000 USDT · up to 3,000 USDT in the market') in page
    assert 'x</b>' not in page                        # 1x is not said
    c['terms']['spoADAUSDTl'] = {'capital': 2000.0, 'leverage': 10.0,
                                 'notional': 20000.0}
    page = _everything(c)
    assert 'investment 2,000 USDT at <b>10x</b> · up to 20,000 USDT in the market' \
        in page
    assert 'investment' not in _everything(CONTRACT)   # no terms: none
    c['terms']['spoADAUSDTl'] = {'capital': 40000.0, 'leverage': 50.0,
                                 'notional': 2000000.0}
    assert 'investment 40,000 USDT at <b>50x</b> · up to 2,000,000 USDT in the market' \
        in _everything(c)                      # never 2e+06


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
    page = _everything(c)
    assert 'margin IM 1,842.50 USDT · MM 92.10 USDT · at 10x on the exchange' in page
    B.margin_view = {'im': 300.0, 'mm': None, 'leverage': None}   # HL's shape
    row = snapshot_row([B()], {'equity': 1.0, 'mm_rate': 0.0}, 0)
    c['watchdog']['belief']['bots']['spoADAUSDTl'] = row['bots']['spoADAUSDTl']
    assert '>margin IM 300.00 USDT</div>' in _everything(c)
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
    assert 'data-size="coin"' in page and '<h3>size in</h3>' in page
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

        labels = ('demo', 'hl')

        def _tombs_path(self, fi=0):
            from pathlib import Path
            return Path('/nonexistent/tombstones.json')

        def _tombs_all(self):
            return [(0, 'demo', self._tombs_path(), {})]

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
    page = _everything(c)
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
    page = _everything(c)
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
    import panel.card as cd                      # and the pieces it was split into
    import panel.table as tb                     # (the 2026-10-11 review)
    import panel.strip_view as st
    for mod in (dg, ph, sv, cd, tb, st):
        src = inspect.getsource(mod)
        assert "['realized'] - v['fees'] +" not in src, mod.__name__
        assert 'card_total(' in src or 'kept_total' in src, mod.__name__   # kept_total sums through it


def spec_D63_a_capped_card_says_where_its_fills_start():
    # pins: R22
    from panel.server import render
    c = json.loads(json.dumps(CONTRACT))
    c['generated_ms'] = 30 * 86400000
    b = c['bots']['spoADAUSDTl']
    b.update(counted_from='cap', counted_since_ms=0,
             first_ms=c['generated_ms'] - int(4.4 * 86400000))
    page = _everything(c)
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
    page = _everything(c)
    assert '<div class="neg">liquidates at 0.195 · 3.3% away' in page, page[-3000:]
    B.margin_view['liq'] = 0.1500                   # far: said, not red
    c['watchdog']['belief']['bots']['spoADAUSDTl'] = snapshot_row(
        [B()], {'equity': 1.0, 'mm_rate': 0.0}, 0)['bots']['spoADAUSDTl']
    assert '<div class="dim">liquidates at 0.15 · 25.6% away' in _everything(c)
    B.margin_view['liq'] = None                     # cross, no price stated
    c['watchdog']['belief']['bots']['spoADAUSDTl'] = snapshot_row(
        [B()], {'equity': 1.0, 'mm_rate': 0.0}, 0)['bots']['spoADAUSDTl']
    assert 'liquidates at' not in _everything(c)
    B.margin_view['liq'] = 0.2100                   # a long's mark already below it (audit 2026-10-16)
    c['watchdog']['belief']['bots']['spoADAUSDTl'] = snapshot_row(
        [B()], {'equity': 1.0, 'mm_rate': 0.0}, 0)['bots']['spoADAUSDTl']
    page = _everything(c)
    assert 'mark is past the liquidation price 0.21' in page and '% away' not in page.split('past the liquidation')[1][:80]


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
    for f in sorted(root.rglob("*.py")):              # panel/pages/ too (the review)
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


def spec_U68_a_card_is_slim_and_its_numbers_page_is_live():
    """The owner (2026-10-11): "far too much for a card … looks like pionex
    at first", the rest on the numbers page, live, for every position type;
    the bots and the markets side by side on a laptop's window. A card
    keeps the side, the name, the state, the money with its return on the
    investment, the run rate, the range — and only what needs the owner
    now (capped, near liquidation, the loss limit half used, a thin book).
    The numbers page refreshes in place."""
    import copy
    from panel.css import CSS
    from panel.card import card, portfolio_card
    from panel.position_view import position_page
    c = copy.deepcopy(CONTRACT)
    c['terms'] = {'spoADAUSDTl': {'capital': 1000.0, 'leverage': 1.0, 'market_type': 'spot', 'strategy': 'grid'}}
    belief = c['watchdog']['belief']['bots']
    belief['spoADAUSDTl'] = {'alive': True, 'position': 910.57}
    b = c['bots']['spoADAUSDTl']
    slim = card(0, 'spoADAUSDTl', b, c, belief)
    assert '<div class="card long slim">' in slim and 'HOLDING' in slim
    assert '<span class="big' in slim and '% </span>' not in slim and 'on 1,000</span>' in slim  # the return on the investment
    assert '<div class="rng">' in slim and "numbers</a>" in slim                  # the range, the door to the rest
    for gone in ('investment 1,000', 'margin IM', '<div class="numbers">', 'stop-now', 'grid on spot'):
        assert gone not in slim, gone
    full = card(0, 'spoADAUSDTl', b, c, belief, full=True)
    assert 'investment 1,000' in full and '<div class="numbers">' in full and 'grid on spot' in full
    # what needs the owner now stays on the slim card, red
    belief['spoADAUSDTl'] = dict(belief['spoADAUSDTl'], margin={'im': 1.0, 'mm': 0.5, 'leverage': 5.0, 'liq': 0.195},
                                 loss={'limit': 50.0, 'result': -30.0})
    slim = card(0, 'spoADAUSDTl', b, c, belief)
    assert '<div class="neg">liquidates at 0.195 · 3.3% away</div>' in slim
    assert '<div class="neg">loss limit 60% used (30.00 of 50)</div>' in slim
    belief['spoADAUSDTl']['margin']['liq'] = 0.10                                  # far: the page's, not the card's
    belief['spoADAUSDTl']['loss']['result'] = -5.0
    slim = card(0, 'spoADAUSDTl', b, c, belief)
    assert 'liquidates' not in slim and 'loss limit' not in slim
    # the portfolio's card is slim too: its assets and facts are the page's
    from spec_portfolio_view import CONTRACT as PC
    pb = PC['watchdog']['belief']['bots']
    pslim = portfolio_card(0, 'pfocarry', PC, pb)
    assert '<div class="card pfo slim">' in pslim and 'since its anchor' in pslim
    assert '<table>' not in pslim and 'stack <b>' not in pslim
    assert '<table>' in portfolio_card(0, 'pfocarry', PC, pb, full=True)
    # the numbers page is live: the page's script swaps it in place
    page = position_page(0, 'demo', 'spoADAUSDTl', c, belief)
    assert page.startswith('<meta name="gg-refresh" content="')
    # the split holds down to a laptop's window
    assert '@media (max-width:860px){.split{display:block}' in CSS and 'max-width:1100px){.split' not in CSS


def spec_U69_the_carry_page_works_the_year_on_the_newest_reading():
    """The owner (2026-10-11): "say i held 100k of BTC with an 85K USDT debt
    … shorted 100k of BTCUSD (inverse) … what would that look like over an
    entire year?" — live, as a page: the funding on the stack, the interest
    on the loan, the fees; the net on the owner's own money; the funding
    that breaks even; the year at other funding rates; every coin read. A
    loan past 70% of the stack is said, red. No reading: said."""
    from panel.carry import carry_page, year_of
    y = year_of(100_000, 85_000, 0.057, 0.0393)
    assert round(y['funding']) == 5700 and round(y['interest']) == 3340 and round(y['fees']) == 350
    assert round(y['net']) == 2010 and abs(y['on_own'] - 2010.5 / 15_000) < 1e-3
    assert abs(y['breakeven'] - (3340.5 + 350) / 100_000) < 1e-6 and abs(y['lever'] - 100 / 15) < 1e-9
    row = {'t': 1000.0, 'carry': {'borrow_apr': {'USDT': 0.0393, 'BTC': 0.0042},
           'funding': {'BTC': {'inverse': {'last': 0.02, 'every_h': 8, 'd7': 0.06, 'd30': 0.056, 'd90': 0.057},
                               'linear': {'last': -0.005, 'every_h': 8, 'd7': 0.027, 'd30': 0.042, 'd90': 0.044}},
                       'DOT': {'linear': {'unread': 'HTTPError'}}}}}
    page = carry_page(row, {}, now=1060.0)
    assert '<h1>carry</h1>' in page and 'value="100000"' in page and 'value="85000"' in page   # the owner's example
    assert '+2,010' in page and '+13.4%' in page and '6.7× on the spread' in page
    assert '3.69% a year' in page                                                             # breaks even
    assert '85% of the stack is borrowed' in page and '<p class="neg">' in page
    assert page.count('<tr><td>') >= 6 + 7 + 2 and 'unread' in page
    calm = carry_page(row, {'loan': '50000', 'leg': 'linear', 'window': 'd30'}, now=1060.0)
    assert 'of the stack is borrowed' not in calm and '+4.20% a year on 100,000' in calm
    assert 'no carry reading yet' in carry_page(None) and 'no carry reading yet' in carry_page({'t': 1.0})
    big = carry_page(row, {'loan': '999999999'}, now=1060.0)                                  # a loan past the stack: capped
    assert 'value="100000" inputmode' in big and big.count('value="100000"') == 2


def spec_U58_a_cards_lower_half_folds_and_the_side_panel_folds_every_card_at_once():
    """The owner (2026-10-09): fold what sits under the bar, with one switch
    for every card. U68 (2026-10-11) made the fleet page's cards slim, so
    the fold lives on the position's page and the cards' switch is gone;
    the accounts' switch (U59) stays. A click is remembered either way; an
    export shows the fold open."""
    import copy
    from panel.position_view import position_page
    from panel.server import render
    from panel.reference import KEEP_JS
    c = copy.deepcopy(CONTRACT)
    html = render([('demo', c)])
    assert '<details class="fold"' not in html                                   # slim: nothing to fold
    assert 'data-cls="fold"' not in html and 'data-cls="acct">folded</a>' in html  # U59's switch stays
    belief = c['watchdog']['belief']['bots']
    bot = next(b for b, v in c['bots'].items() if v is not None and c['ranges'].get(b))
    page = position_page(0, 'demo', bot, c, belief)
    assert f'<details class="fold" data-k="0:{bot}:fold" open><summary>details</summary>' in page
    i = page.index(f'data-k="0:{bot}:fold"')
    assert page.rindex('<div class="card ', 0, i) < page.index('<div class="rng">', page.rindex('<div class="card ', 0, i)) < i
    assert "open[d.dataset.k]=d.open?1:0" in KEEP_JS and "window.ggFold=function(k,c)" in KEEP_JS
    assert "S.setItem('gg-fold:'+c,k)" in KEEP_JS


def spec_U59_an_account_folds_to_its_heading_and_box_and_the_side_panel_folds_every_account():
    """The owner (2026-10-09): each account collapsible into a smaller
    form, individually and all at once. The heading and the exchange's
    box stay; the cards fold behind "N bots"; the side panel's accounts
    switch sets them all, apart from the cards switch."""
    import copy
    from panel.server import render
    c = copy.deepcopy(CONTRACT)
    html = render([('demo', c), ('hl', c)])
    for i in (0, 1):
        assert f'<details class="acct" data-k="acct:{i}" open><summary>{len(c["bots"])} bots</summary><div class="cards">' in html
        h1 = html.index(f'<h1 id="fleet{i}">')
        box = html.index('<span class="dim">this exchange</span>', h1)
        assert h1 < box < html.index(f'data-k="acct:{i}"', h1)      # heading, box, then the fold
    assert '<a href="#" data-fold="folded" data-cls="acct">folded</a>' in html
    assert '<a href="#" data-fold="open" data-cls="acct">full</a>' in html
    assert 'data-cls="fold">folded</a>' not in html                   # U68: the cards' switch is gone
    # one link beside each account's count folds or opens that account's cards alone
    for i in (0, 1):
        assert f'bots <a href="#" data-foldin="{i}" class="tier">fold cards</a>' in html
    from panel.server import KEEP_JS
    assert 'details.acct[data-k="acct:\'+i+\'"] details.fold' in KEEP_JS and 'window.ggFoldIn=function(i)' in KEEP_JS
    assert "a.textContent=all?'fold cards':'open cards'" in KEEP_JS
    assert 'data-cls="acct"' not in render([('demo', c)], table=True)   # the table folds nothing
    out = render([('demo', c)], static='then')
    assert 'data-k="acct:0" open>' in out and 'ggFold' not in out


def spec_U61_the_live_page_refreshes_in_place_and_never_reloads_whole():
    """The owner (2026-10-09): the refresh flickers the whole screen every
    few seconds. The live page carries no reload now; its script fetches
    this same URL and swaps the strip and the cards in place, re-wiring
    what folds; without script the old whole-page refresh stands; an
    export refreshes nothing."""
    from panel.html_bits import REFRESH_S
    from panel.server import KEEP_JS, render
    live = render([('demo', CONTRACT)])
    assert f'<meta name="gg-refresh" content="{REFRESH_S}">' in live
    assert live.count('http-equiv="refresh"') == 1
    assert f'<noscript><meta http-equiv="refresh" content="{REFRESH_S}"></noscript>' in live
    assert "fetch(url,{credentials:'same-origin',cache:'no-store'})" in KEEP_JS
    assert "swap(location.href).catch(function(){});},every*1000);" in KEEP_JS
    # U78c: a form open in the right half is never swapped out from under the typing
    # (U82: …while it is being typed in — an untouched one refreshes)
    assert "setInterval(function(){if(busy||dirty())return;" in KEEP_JS
    # …and a form's own script arriving in the half runs (a swapped-in script never would)
    assert "document.querySelectorAll('main .pane script').forEach(" in KEEP_JS and "s.text=old.text;old.replaceWith(s)" in KEEP_JS
    assert "['.hero','main']" in KEEP_JS and 'innerHTML=b.innerHTML' in KEEP_JS
    assert "wire(document.querySelector('main')" in KEEP_JS          # the swapped cards fold as before
    table = render([('demo', CONTRACT)], table=True)
    assert 'name="gg-refresh"' in table and table.count('http-equiv="refresh"') == 1
    out = render([('demo', CONTRACT)], static='then')
    assert 'gg-refresh' not in out and 'http-equiv="refresh"' not in out and '<script' not in out


def spec_U62_the_table_and_the_exchange_view_scroll_sideways_and_the_strip_stacks_on_a_phone():
    """Seen in screenshots (2026-10-09): the table's fixed layout cut every
    number to "6…" at desktop width; the exchange's view of a position
    ran off the page; the strip clipped its totals on a phone. The table
    and the exchange view sit in a sideways-scrolling box with nothing
    truncated; on a narrow screen the strip stacks one account per row."""
    from panel.css import CSS
    from panel.position_view import exchange_table
    from panel.server import render
    t = render([('demo', CONTRACT)], table=True)
    assert '<div class="scroll"><table class="fleet">' in t and '</table></div>' in t
    assert 'table-layout:fixed' not in CSS and 'text-overflow:ellipsis' not in CSS
    assert '.scroll{overflow-x:auto' in CSS and 'table.fleet td,table.fleet th{white-space:nowrap}' in CSS
    x = exchange_table('linDOGEs', None, {'linDOGEs': {'alive': True, 'position': 730.0, 'margin': {}}},
                       {'quote': 'USDT', 'margin_coin': 'USDT'})
    assert x.startswith('<div class="scroll"><table class="xch">') and x.endswith('</table></div>')
    narrow = CSS[CSS.index('@media(max-width:40em)'):]
    assert '.hero{' in narrow and 'display:block' in narrow and '.hero .fleet{display:block' in narrow


def spec_U63_the_strip_carries_a_sparkline_and_the_box_the_days_and_the_weeks_line():
    """The owner (2026-10-09), after the comparison: every other dashboard
    leads with a line over time. From the fleet's own snapshots: a
    sparkline in the strip, a 24 h and a 7 d chart under the account's
    box with the low, the high and the change; nothing drawn without
    two points; an export carries the same lines; one series, no legend."""
    import copy
    import time
    from panel.drawings import equity_svg
    from panel.server import render
    now = time.time()
    c = copy.deepcopy(CONTRACT)
    c['equity'] = {'24h': [[now - 3600 + i * 300, 1000.0 + i] for i in range(12)],
                   '7d': [[now - 6 * 86400 + i * 1800, 900.0 + i] for i in range(200)]}
    html = render([('demo', c)])
    assert '<span class="spark" title="equity, 24 h"><svg class="eq"' in html
    assert 'equity, 24 h</div><div class="eqbox">' in html and 'equity, 7 d</div><div class="eqbox">' in html
    assert '<span>low 1,000.00</span><span>high 1,011.00</span><b class="pos">+11.00 (+1.1%)</b>' in html
    assert html.count('<polyline') == 3 and '<legend' not in html and 'stroke-width="2"' in html
    assert '<title>' in html                                        # the box's native tooltip
    out = render([('demo', c)], static='then')
    assert out.count('<polyline') == 3 and '<script' not in out
    assert equity_svg([[1, 2]]) == '' and equity_svg(None) == ''
    assert 'equity line: no history yet' in render([('demo', CONTRACT)])
    assert 'class="spark"' not in render([('demo', CONTRACT)])
    down = equity_svg([[0, 10.0], [60, 5.0]], 400, 60, labels=True)
    assert '<b class="neg">-5.00 (-50.0%)</b>' in down and 'fill="var(--neg)"' in down


def spec_U64b_grid_profit_is_the_matched_trips_and_the_run_starts_at_the_first_fill():
    """The second audit, 2026-10-13: a long grid holding lots bought on the
    way down realises at an average above its exits, so average-cost
    realised read -2,031/day where its trips made +3,817/day. Grid profit
    is the matched trips' (R12) after fees; no matched trip, realised. A
    bot 38 minutes old in a 24 h window read "running 1.0 d". Sabotage:
    realised in place of the trips flips the sign below."""
    from panel.card import run_rate
    gen = 10 * 86_400_000
    c = {'generated_ms': gen, 'window_hours': 24}
    b = {'fills': 10, 'realized': -300.0, 'gap_realized': 500.0, 'gap_trips': 4, 'fees': 100.0,
         'counted_from': 'flat', 'counted_since_ms': gen - 4 * 86_400_000}
    assert '+100.00</b>/day' in run_rate(b, c, 1000.0)                  # (500 - 100) / 4 d
    assert '-100.00</b>/day' in run_rate(dict(b, gap_trips=0), c, 1000.0)   # no trip: realised
    young = {'fills': 2, 'realized': 0.0, 'fees': 1.0, 'counted_from': None,
             'first_ms': gen - 38 * 60_000}
    assert 'running 38 h' not in run_rate(young, c) and 'running 1 h' in run_rate(young, c)


def spec_U64_a_card_says_how_long_it_has_run_and_its_grid_profit_per_day_and_a_year():
    """The comparison (2026-10-09): every grid product states run time and
    an APR. Bybit's way: grid profit (realised after fees) / investment /
    days x 365, under a day counted as one. In the figure's own span —
    since last flat, since the first fill in the cap, or the window."""
    import copy
    from panel.card import run_rate
    gen = 10 * 86_400_000
    b = {'fills': 10, 'realized': 120.0, 'fees': 20.0, 'counted_from': 'flat',
         'counted_since_ms': gen - 4 * 86_400_000}
    c = {'generated_ms': gen, 'window_hours': 24}
    line = run_rate(b, c, capital=1000.0)
    assert 'running 4.0 d' in line and '+25.00</b>/day' in line and '+912.5%' in line   # 100/1000/4*365
    short = dict(b, counted_since_ms=gen - 6 * 3_600_000)
    assert 'running 6 h' in run_rate(short, c, 1000.0) and '+100.00</b>/day' in run_rate(short, c, 1000.0)   # a day at least
    cap = dict(b, counted_from='cap', first_ms=gen - 2 * 86_400_000)
    assert 'running 2.0 d' in run_rate(cap, c)  and 'APR' not in run_rate(cap, c)          # no investment, no rate
    win = dict(b, counted_from=None)
    assert 'running 1.0 d' in run_rate(win, c, 1000.0)
    assert run_rate(dict(b, fills=0), c, 1000.0) == '' and run_rate(b, {}, 1000.0) == ''
    assert 'class="neg">-' in run_rate(dict(b, realized=-500.0), c, 1000.0)
    from panel.server import render
    live = copy.deepcopy(CONTRACT)
    live['generated_ms'] = gen                       # the fixture's clock reads zero: no span, no line
    assert '<div class="rate">running 6 h · grid profit' in render([('demo', live)])   # the fixture's 6 h window
    assert '<div class="rate">' not in render([('demo', copy.deepcopy(CONTRACT))])


def spec_U75_the_bug_hunts_findings_stay_fixed():
    """The bug hunt (2026-10-11, the panel run on the example configs, 103
    pages): a fleet with no known network shifted every later cell of the
    top strip one place left; the table said RESTING where the card said
    NOT STARTED; "depth ±1%" was read from a book that ends far inside 1%;
    the run-rate line printed −0.00 and called a DCA's profit "grid"; the
    public edition's example expiry calendar named private infrastructure."""
    import copy
    import json as _json
    from pathlib import Path as _P
    from gridgremlin import expiry as ex
    from ggdata.market import depth_reach_pct
    from panel.card import run_rate
    from panel.strip_view import tier_badge
    from panel.server import render
    assert tier_badge({}) == '<span></span>'                                   # an unknown network still fills its cell
    c = copy.deepcopy(CONTRACT)
    c['bots']['linXRPUSDTl'] = None                                            # configured, never started
    c['watchdog']['belief']['bots'].pop('linXRPUSDTl', None)
    row = render([('demo', c)], table=True).split('linXRPUSDTl')[1].split('</tr>')[0]
    assert 'NOT STARTED' in row and 'RESTING' not in row
    bids = [(99.9, 1), (99.8, 1)]
    asks = [(100.1, 1), (100.25, 1)]
    assert abs(depth_reach_pct(bids, asks, 100.0) - 0.2) < 1e-9               # the nearer edge of the book served
    b = {'realized': -0.001, 'fees': 0.0, 'fills': 3, 'counted_from': 'cap', 'first_ms': 8.64e7}
    line = run_rate(b, {'generated_ms': 5 * 8.64e7}, 1000.0, trade=True)
    assert '-0.00' not in line and '+0.00' in line and 'grid' not in line
    root = _P(__file__).resolve().parents[1]                          # the public tree's configs ARE the examples
    shipped = (root / 'configs' / 'examples' / 'expiry.json' if (root / 'configs' / 'examples').is_dir()
               else root / 'configs' / 'expiry.json')
    text = shipped.read_text().lower()
    for private in ('agent door', 'authorized keys', 'carry', 'tilt', 'subaccount 1', 'the box'):
        assert private not in text, private
    assert ex.load_calendar(shipped) and all(e['expires'] is None for e in _json.loads(shipped.read_text()))


def spec_U76_the_bug_hunts_nits_stay_fixed():
    """The rest of the bug hunt (2026-10-11): a readout that crashed killed
    the fleet page; a perpetual's edit page showed spot-only rows; the form
    named accounts by their files; a DCA ladder mixed "45" with "67.5";
    two same-venue lines shared one solid swatch; and query links carried a
    bare '&'."""
    import copy
    import re
    import subprocess
    import tempfile
    from pathlib import Path as _P
    from panel.server import Handler, render
    from panel.setup import SPOT_ONLY, advanced_page
    from panel.card import ladder_box
    # a readout that printed nothing: the last good one stays; with none, the section says so
    fleet = _P(tempfile.mkdtemp()) / 'fleet.x.json'
    fleet.write_text('{"bots": [{"symbol": "BTCUSDT"}]}')
    saved_run = subprocess.run
    subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 1, '', 'Traceback…\nKeyError: boom\n')
    try:
        h = Handler.__new__(Handler)
        h.hours = 6.0
        Handler._cache.pop(str(fleet), None)
        got = h._read_contract(str(fleet))
        assert got['bots'] == {} and got['unavailable'] == 'KeyError: boom'
        good = copy.deepcopy(CONTRACT)
        Handler._cache[str(fleet)] = (0.0, good)
        assert h._read_contract(str(fleet)) is good                       # the last good one stays
    finally:
        subprocess.run = saved_run
        Handler._cache.pop(str(fleet), None)
    page = render([('demo', got)])
    assert 'readout unavailable' in page and 'KeyError: boom' in page
    # a perpetual's edit page has no spot rows; a spot bot's keeps them
    perp = advanced_page('grid', {'symbol': 'BTCUSDT', 'market_type': 'linear', 'side': 'long'}, ['bybit demo'], edit='linBTCUSDTl')
    spot = advanced_page('grid', {'symbol': 'BTCUSDT', 'market_type': 'spot', 'side': 'long'}, ['bybit demo'], edit='spoBTCUSDTl')
    for key in SPOT_ONLY:
        assert f'name="{key}"' not in perp, key
    assert 'name="holding"' in spot and 'name="spot_borrow"' in spot
    assert '<b>bybit demo</b>' in perp                                   # the account's name, not its file
    # the form's accounts are the dash's names (U55), by index
    h = Handler.__new__(Handler)
    h.fleets, h.labels = ('configs/fleet.demo.json', 'configs/fleet.x.json'), ('bybit demo', '')
    assert h._fleet_labels() == ['bybit demo', 'fleet.x.json']
    # one number format down the ladder, right-aligned
    rows = [{'step': i, 'fill_pct': -0.01 * i, 'notional': n, 'committed': c, 'avg_pct': 0.0, 'to_tp_pct': 0.01}
            for i, (n, c) in enumerate([(30, 30), (45, 75), (67.5, 142.5), (101.25, 243.75)])]
    box = ladder_box(0, 'b', {'ladder': rows, 'quote': 'USDT'})
    assert '<td>45.00</td>' in box and '<td>67.50</td>' in box and 'class="ladder"' in box
    assert ladder_box(0, 'b', {'ladder': [dict(rows[0], notional=0.0015, committed=0.0015)]}).count('0.0015') >= 2
    # no query link carries a bare '&'
    pages = render([('demo', copy.deepcopy(CONTRACT))]) + render([('demo', copy.deepcopy(CONTRACT))], table=True)
    bare = re.findall(r"href=[\"']/[a-z-]+\?[^\"']*&(?!amp;)", pages)
    assert not bare, bare[:3]


def spec_P4_a_name_is_never_markup():
    """A bot id, a symbol or a fleet's label with markup in it is drawn as
    text on every page and encoded in every link (review 2026-10-11)."""
    import copy
    from panel.server import render
    bad = 'lin<i>X</i>USDTl'
    c = copy.deepcopy(CONTRACT)
    c['bots'][bad] = dict(c['bots'].pop('spoADAUSDTl'), side='long')
    c['ranges'] = {bad: c['ranges'].pop('spoADAUSDTl')}
    c['watchdog']['ceilings'][bad] = 9700.0
    for page in (_everything(c), render([('<s>demo', c)]),
                 render([('<s>demo', c)], table=True),
                 render([('<s>demo', c)], view='market'),
                 render([('<s>demo', c)], table=True, view='market')):
        assert '<i>X</i>' not in page and '<s>demo' not in page
        assert '&lt;i&gt;X&lt;/i&gt;' in page
    assert 'bot=lin%3Ci%3EX%3C%2Fi%3EUSDTl' in _everything(c)


def spec_P5_the_door_reads_exactly_the_cookie_and_the_fleet_it_is_given():
    """The cookie by name, in constant time; a fleet parameter that names no
    fleet is refused at the door (review 2026-10-11)."""
    srv, base = _serve(CONTRACT)

    def code(path, cookie='gg=tok123', data=None):
        req = urllib.request.Request(base + path, data=data,
                                     headers={'Cookie': cookie})
        try:
            return urllib.request.urlopen(req).status
        except urllib.error.HTTPError as e:
            return e.code
    try:
        assert code('/') == 200
        for cookie in ('gg=tok1234', 'xgg=tok123', 'gg=tok12', ''):
            assert code('/', cookie) == 401, cookie
        assert code('/', 'a=1; gg=tok123') == 200
        assert code('/position?fleet=0&bot=spoADAUSDTl') == 200
        for f in ('abc', '-1', '1', '0x0', '1e0'):
            assert code(f'/position?fleet={f}&bot=spoADAUSDTl') == 400, f
            assert code('/close', data=f'gg={FT}&fleet={f}'.encode()) == 400, f
    finally:
        srv.shutdown()


def spec_U75b_no_figure_prints_minus_zero():
    """The second audit, 2026-10-13: the card's headline, the money cells,
    the phone and the digest each printed "-0.00" for -0.001. One helper
    rounds first. Sabotage: f'{v:+,.2f}' prints -0.00 again."""
    from common.fmt import signed
    from gridgremlin.digest import _m as dm
    from gridgremlin.phone import _m as pm
    from panel.html_bits import money
    assert signed(-0.001) == '+0.00' and signed(-0.006) == '-0.01' and signed(2.5) == '+2.50'
    assert dm(-0.001) == pm(-0.001) == '+0.00'
    assert money(-0.001) == '<td>0.00</td>'


def spec_P6_every_answer_carries_the_security_headers():
    """The 2026-10-13 audit, part 4: no answer of the panel's — a page, a
    refusal, a denial — may be framed by another site, sniffed into another
    type or kept by a cache. One helper adds the four to every response."""
    import urllib.parse
    from spec_setup import _served_fleet
    base, d, close = _served_fleet()
    want = {'X-Frame-Options': 'DENY',
            'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store'}

    def heads(path, data=None, cookie=True):
        body = (None if data is None else
                urllib.parse.urlencode(dict(data, gg=form_token('tok'))).encode())
        req = urllib.request.Request(base + path, data=body,
                                     headers={'Cookie': 'gg=tok'} if cookie else {})
        try:
            r = urllib.request.urlopen(req)
            return r.status, r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.headers
    try:
        answers = (heads('/setup'), heads('/setup?adv=grid'),                # pages
                   heads('/setup', cookie=False),                            # a denial
                   heads('/trade', {'action': 'clear', 'fleet': '0',         # a refusal
                                    'confirm': 'nope'}))
        assert answers[2][0] == 401
        for code, h in answers:
            for k, v in want.items():
                assert h.get(k) == v, (code, k, h.get(k))
            csp = h.get('Content-Security-Policy') or ''
            assert "frame-ancestors 'none'" in csp and "script-src 'nonce-" in csp, (code, csp)
    finally:
        close()


def spec_P6_the_close_runs_only_for_a_bot_of_the_fleet():
    """The close spawns the engine's own command with the bot's id in its
    argv: a posted id that is not a bot of this account (one starting '--'
    above all) is refused before anything is spawned."""
    from panel.server import Handler
    from spec_setup import _call, _served_fleet
    base, d, close = _served_fleet()
    saved_units, saved_run = Handler.units, Handler._run_close
    ran = []

    def fake(self, fi, botid, dry, expect=None):
        ran.append((botid, dry))
        return {'botid': botid, 'side': 'long', 'symbol': 'ETHUSDT', 'held': 0.25,
                'avg_entry': 2500.0, 'mark': 2600.0, 'closed': 0.25, 'left': 0.0}
    Handler.units, Handler._run_close = ('some.service',), fake
    try:
        for bad in ('--allow-mainnet', '--dry', 'linXRPUSDTl'):
            page = _call(base, '/close?fleet=0&bot=' + bad)
            assert 'class="refusal"' in page and 'not a bot of this account' in page, bad
            page = _call(base, '/close', {'fleet': '0', 'bot': bad, 'confirm': bad})
            assert 'class="refusal"' in page and 'not a bot of this account' in page, bad
        assert ran == []                                   # nothing was spawned
        assert 'close at market' in _call(base, '/close?fleet=0&bot=linETHUSDTl')
        assert 'closed 0.25' in _call(base, '/close', {'fleet': '0', 'bot': 'linETHUSDTl',
                                                       'confirm': 'linETHUSDTl'})
        assert ran == [('linETHUSDTl', True), ('linETHUSDTl', False)]
    finally:
        Handler.units, Handler._run_close = saved_units, saved_run
        close()


def spec_P7_names_from_the_files_are_drawn_as_text():
    """A fleet name, a tombstone's id, a money or margin coin reach the page
    as text, never markup; and a refusal is escaped once (refusal_box
    escapes), not twice into a visible '&amp;#x27;'."""
    import copy
    from panel.card import holding_html
    from panel.forms import unit_refusal
    from panel.position_view import exchange_table
    from panel.server import Handler
    from panel.strip_view import venue_money
    from spec_setup import _call, _served_fleet
    q, h = '<b>Q</b>', 'linx<svg/onload=alert(3)>l'
    live = unit_refusal('<b>q</b>', ('gg.service',), {}, {q: '<i>u</i>'})
    tomb = unit_refusal(h, ('<s>gg</s>',), {h: {}}, {})
    other = unit_refusal('nope', ('<s>gg</s>',), {}, {})
    for out in (live, tomb, other):
        assert '<svg/onload' not in out and '<b>Q' not in out and '<i>' not in out and '<s>' not in out, out
    assert '&lt;b&gt;Q&lt;/b&gt;' in live and '&lt;svg/onload=alert(3)&gt;' in tomb
    c = copy.deepcopy(CONTRACT)
    coin = 'U<svg/onload=alert(3)>'
    c['terms'] = {'spoADAUSDTl': {'quote': coin, 'margin_coin': coin, 'capital': 100.0}}
    c['watchdog']['belief']['bots']['spoADAUSDTl'] = {
        'alive': True, 'position': 910.57, 'margin': {'im': 1.0, 'mm': 0.5, 'leverage': 2}}
    c['bots']['spoADAUSDTl']['settle'] = {'coin': coin, 'realized': 1.0, 'fees': 0.1,
                                          'unreal': 0.0, 'funding': None}
    page = _everything(c) + exchange_table('spoADAUSDTl', c['bots']['spoADAUSDTl'],
                                           c['watchdog']['belief']['bots'], c['terms']['spoADAUSDTl'])
    page += holding_html(1.0, 2.0, 2.0, 'linBTCUSDTl', quote=coin) + venue_money(c)
    assert '<svg/onload' not in page and '&lt;svg/onload=alert(3)&gt;' in page
    assert '&amp;lt;' not in page                          # and once, not twice
    # a refusal's apostrophe reaches the page escaped once
    base, d, close = _served_fleet()
    saved_units, saved_run = Handler.units, Handler._run_close
    Handler.units = ('some.service',)
    Handler._run_close = lambda self, fi, botid, dry, expect=None: {'refused': "the bot's gone"}
    try:
        trade = _call(base, '/trade', {'action': 'clear', 'fleet': '0', 'confirm': 'linXRPUSDTl'})
        assert 'account&#x27;s file' in trade and '&amp;#x27;' not in trade
        shut = _call(base, '/close', {'fleet': '0', 'bot': 'linETHUSDTl', 'confirm': 'linETHUSDTl'})
        assert 'the bot&#x27;s gone' in shut and '&amp;#x27;' not in shut
    finally:
        Handler.units, Handler._run_close = saved_units, saved_run
        close()


def spec_L6b_a_running_trade_is_never_cleared():
    """Clear is for a trade that has ended (L6). A trade still running is
    refused with its row and the close-trade path kept: cleared, nothing
    would own its position after the next restart (audit 2026-10-16)."""
    from spec_setup import _call, _served_fleet
    from gridgremlin.trade import build_row
    from gridgremlin.trades import add_trade, fleet_rows, trade_status, trades_path
    from gridgremlin.tombstones import Tombstones, path_for
    base, d, close = _served_fleet()
    try:
        f = str(d / 'f.json')
        raw = json.loads(open(f).read())
        _fl, rows = fleet_rows(f)
        tp = trades_path(f, raw)
        bid = add_trade(tp, rows, build_row('long', 'SOLUSDT', {'capital': '100', 'tp': '1', 'stop': '1'}))
        assert trade_status(tp, bid, Tombstones(str(path_for(f, raw)))) == 'live'
        page = _call(base, '/trade', {'action': 'clear', 'fleet': '0', 'confirm': bid})
        assert 'still running' in page and 'cleared</h1>' not in page, page[-600:]
        assert trade_status(tp, bid, Tombstones(str(path_for(f, raw)))) == 'live'   # the row stays
    finally:
        close()


def spec_U82_a_late_refresh_never_replaces_what_was_just_opened():
    """The live page's swap: an answer arriving after a newer swap began is
    dropped (a counter, newest wins), the timer waits while a swap is in
    flight, and it skips while a form in the right half is focused or
    differs from its defaults — an untouched form refreshes. The suite has
    no browser: the script's own words are pinned."""
    from panel.reference import KEEP_JS as js
    assert 'var seq=0,busy=0;' in js and 'var my=++seq;busy++;' in js
    assert js.index('if(my!==seq)return null;') < js.index('innerHTML=b.innerHTML')
    assert '.then(function(v){busy--;return v;},function(e){busy--;throw e;});' in js
    assert 'setInterval(function(){if(busy||dirty())return;' in js
    for word in ("a.closest('.pane form')", 'e.checked!==e.defaultChecked',
                 'o.defaultSelected', 'e.value!==e.defaultValue'):
        assert word in js, word
    # a dropped answer is neither drawn nor a reason to load the page whole
    assert 'else if(ok===false)location.href=u.href;' in js


def spec_U90_a_grid_card_splits_its_total_into_grid_profit_and_trend():
    """The owner (2026-10-14): a grid "could be thousands of dollars in
    profit, but simultaneously look underwater" — the exchanges split it.
    A grid card says its grid profit (the matched trips after fees) and its
    trend (the rest), which sum to the total exactly, and the price at which
    the total is nothing; a bot without a matched trip keeps realised and
    open. Sabotage: a split that drops the fees no longer sums."""
    import copy
    from panel.card import grid_split
    from panel.server import render
    b = dict(CONTRACT['bots']['spoADAUSDTl'], gap_realized=30.0, gap_trips=12)
    total = 5.04 - 2.07 - 4.83
    out = grid_split(b, total)
    grid, trend = 30.0 - 2.07, total - (30.0 - 2.07)
    assert f'{grid:+,.2f}' in out and f'{trend:+,.2f}' in out
    even = 0.2017 - total / 910.57
    assert 'back to even at' in out and f'{even:,.6g}' in out
    assert abs(910.57 * (even - 0.2017) + total) < 1e-9         # at that price the total is nothing
    short = dict(b, position=-910.57, unreal_at_mark=4.83)
    assert 'in profit while below' in grid_split(short, 5.04 - 2.07 + 4.83)
    assert grid_split(dict(b, inverse=True), total).count('<span>') == 2   # no price for an inverse book
    assert grid_split(CONTRACT['bots']['spoADAUSDTl'], total) == ''      # no matched trip
    c = copy.deepcopy(CONTRACT)
    c['bots']['spoADAUSDTl'].update(gap_realized=30.0, gap_trips=12)
    card = render([('demo', c)]).split('class="card ')[1]
    assert '<div class="split"><span>grid profit</span>' in card


def spec_U93_the_audit_of_2026_10_16_the_panels_smaller_numbers():
    """An inverse bot with no book in the window still counts $1 contracts;
    an unpriced book's realised is unknown, never +0.00; a trade's `by` and
    `opened` are text; flat equity over ten days is not "under ten days";
    the panel carries a phone viewport and the showcase leaves it to the site."""
    import time
    from panel.card import kind_line
    from panel.drawings import equity_boxes
    from panel.position_view import exchange_table
    from panel.render import VIEWPORT
    from panel.server import render
    bl = {'invETHUSDl': {'alive': True, 'position': 5000.0}}
    t = {'market_type': 'inverse', 'symbol': 'ETHUSD', 'quote': 'USD', 'margin_coin': 'ETH'}
    page = exchange_table('invETHUSDl', None, bl, t)
    assert '5,000 USD' in page and '5,000 ETH' not in page
    page = exchange_table('invETHUSDl', {'position': 5000.0, 'mark': 2000.0, 'inverse': True,
                                         'realized': None, 'fees': 0.1}, bl, t)
    assert '+0.00' not in page.split('realised')[0] + page.split('</tr><tr>')[1].split('</td>')[-4]
    line = kind_line({'trade': True, 'tp_pct': 0.01, 'opened': '2026-10-16T10:00', 'by': '<b>x</b>',
                      'market_type': 'linear', 'leverage': 1})
    assert '<b>x</b>' not in line and '&lt;b&gt;x&lt;/b&gt;' in line
    now = time.time()
    flat = {'equity': {'30d': [[now - 20 * 86400 + i * 86400, 100.0] for i in range(21)], 'sharpe': {'30d': None}}}
    assert 'no day-to-day movement' in equity_boxes(flat) and 'under ten days' not in equity_boxes(flat)
    html = render([('demo', CONTRACT)])
    assert VIEWPORT in html and VIEWPORT not in render([('demo', CONTRACT)], static='then')


def spec_U94_the_engines_figures_say_their_age_when_old():
    """The card's state, cap, margin, liquidation and loss limit are the
    engine's last snapshot; past ten minutes the card and the strip say how
    old, and a fresh snapshot claims nothing (the audit, 2026-10-16)."""
    import copy
    from panel.server import render
    old = copy.deepcopy(CONTRACT)
    old['watchdog']['belief']['age_s'] = 25 * 60
    old['watchdog']['belief']['bots']['spoADAUSDTl'] = {'alive': True, 'position': 910.57}
    page = render([('demo', old)])
    hero = page.split('<div class="hero">')[1].split('</div></div>')[0]
    assert 'engine read 25 min ago' in hero
    said = "the engine's state, margin and limits are from 25 min ago"
    assert said in page                                    # the slim card
    assert _everything(old).count(said) >= 3               # both bots' own pages too
    gone = copy.deepcopy(old)
    del gone['watchdog']['belief']['bots']['spoADAUSDTl']
    assert said not in render([('demo', gone)])            # not in the snapshot: no claim
    old['watchdog']['belief']['age_s'] = 5 * 3600
    assert 'engine read 5 h ago' in render([('demo', old)])
    page = render([('demo', CONTRACT)])
    assert 'engine read' not in page and 'margin and limits are from' not in page


def spec_U95_an_unpriced_open_position_is_named_never_a_silent_0():
    """A bot holding with its mark unread counts its open part as nothing:
    its card says so and drops the ROI; the exchange box and the strip name
    how many such books its total leaves out; the box's parts show the
    portfolio rows it adds (the audit, 2026-10-16)."""
    import copy
    from panel.server import render
    c = copy.deepcopy(CONTRACT)
    c['terms'] = {'spoADAUSDTl': {'capital': 1000.0, 'quote': 'USDT'}}
    page = render([('demo', c)])
    assert 'not priced' not in page and 'unpriced' not in page and '%</span>' in page
    c['bots']['spoADAUSDTl'].update(unreal_at_mark=None, mark=None)
    page = render([('demo', c)])
    assert 'an open position not priced' in page and '%</span> <span class="dim">on 1,000' not in page
    assert '1 bot holding a position not priced' in page
    assert '+ 1 unpriced' in page.split('<div class="hero">')[1].split('</div></div>')[0]
    c = copy.deepcopy(CONTRACT)
    c['watchdog']['belief']['bots']['spoBTCUSDTl'] = {'alive': True, 'portfolio': {'total': 12.5}}
    assert 'portfolio rows <b class="pos">+12.50</b>' in render([('demo', c)])


def spec_U96_the_table_and_the_card_agree_on_state_and_window():
    """A stopped bot holding reads DEAD in the table as on its card, and a
    slid grid's window is the same slid window in both (the audit,
    2026-10-16: the table said HOLDING and judged the home range)."""
    import copy
    from panel.server import render
    c = copy.deepcopy(CONTRACT)
    c['watchdog']['belief']['bots']['spoADAUSDTl'] = {'alive': False, 'position': 910.57, 'offset': 2}
    table = render([('demo', c)], table=True)
    row = table.split('spoADAUSDTl')[1].split('</tr>')[0]
    assert '>DEAD<' in row and 'HOLDING' not in row
    assert 'window slid +2 rungs from home' in row
    gap = (0.23 - 0.155) / 15
    lo = 0.155 + 2 * gap
    assert f"{(0.2017 - lo) / 0.2017 * 100:.1f}%" in row
    assert 'DEAD' in render([('demo', c)]).split('spoADAUSDTl')[1]


def spec_P6b_only_the_panels_own_scripts_run_and_its_forms_carry_a_secret():
    """The audit, 2026-10-16: the policy names a nonce made for each answer,
    every script on the page carries it, and nothing runs inline beside
    them (no handler, no javascript: link); the forms' hidden token comes
    from the launch's secret — the old constant 1, or another launch's
    token, is refused before anything is read."""
    import re
    import urllib.error
    import urllib.parse
    from spec_setup import _served_fleet
    base, d, close = _served_fleet()

    def get(path):
        r = urllib.request.urlopen(urllib.request.Request(base + path, headers={'Cookie': 'gg=tok'}))
        return r.headers['Content-Security-Policy'], r.read().decode()

    def post(gg):
        data = urllib.parse.urlencode({'gg': gg, 'action': 'clear', 'fleet': '0', 'confirm': 'nope'}).encode()
        try:
            return urllib.request.urlopen(urllib.request.Request(
                base + '/trade', data=data, headers={'Cookie': 'gg=tok'})).status
        except urllib.error.HTTPError as e:
            return e.code
    try:
        seen = set()
        for path in ('/', '/setup', '/trade', '/rehearse', '/control', '/table'):
            csp, page = get(path)
            n = re.search(r"'nonce-([^']+)'", csp).group(1)
            seen.add(n)
            tags = re.findall(r'<script\b[^>]*>', page)
            assert tags and all(t == f'<script nonce="{n}">' for t in tags), (path, tags[:2])
            assert 'javascript:' not in page and not re.search(r'\son[a-z]+=', page), path
            forms = re.findall(r'name="gg" value="([^"]*)"', page)
            assert all(v == form_token('tok') for v in forms), path
        assert len(seen) == 6                                  # a new nonce each answer
        assert post('1') == 403 and post(form_token('other')) == 403
        assert post(form_token('tok')) != 403
    finally:
        close()


def spec_P7b_unit_names_on_the_control_page_are_text():
    """The audit, 2026-10-16: a unit name from the launch is drawn escaped
    on the control page, as every other name from a file (P7)."""
    from panel.server import Handler
    from spec_setup import _call, _served_fleet
    base, d, close = _served_fleet()
    saved = Handler.units
    try:
        Handler.units = ('<i>x</i>.service',)
        page = _call(base, '/control')
        assert '<i>x</i>' not in page and '&lt;i&gt;x&lt;/i&gt;.service' in page
    finally:
        Handler.units = saved
        close()


def spec_U97_removing_a_bot_says_what_it_still_holds():
    """The audit, 2026-10-16: removing a row closes nothing — the remove
    page and its review say what the bot holds by the engine's last
    snapshot, and that it stays open with no bot to manage it; a flat bot's
    pages say nothing of it."""
    import json as _json
    import urllib.parse
    from spec_setup import _call, _served_fleet
    base, d, close = _served_fleet()
    try:
        botid = 'linETHUSDTl'
        door = f'/edit?fleet=0&bot={botid}&mode=remove'
        assert 'still holds a position' not in _call(base, door)
        (d / 's').write_text(_json.dumps({'t': 0, 'bots': {botid: {'position': 0.25}}}) + '\n')
        page = _call(base, door)             # the door; the review shows the same box
        assert 'it still holds a position</b> — 0.25' in page and 'does not close it' in page
    finally:
        close()


def spec_P8_the_door_takes_localhost_refuses_with_a_way_back_and_keeps_the_key_out_of_logs():
    """The audit, 2026-10-16: `localhost` is the same panel as 127.0.0.1 (an
    Origin must still match the Host it came to); a refusal is a page with
    the way back; a service's start line names the token file instead of
    printing the key; the launcher reopens a running panel signed in, and
    never with a key others can read."""
    import os
    import tempfile
    import urllib.error
    from pathlib import Path as _P
    from panel.launch import TOKEN_FILE, saved_key
    from panel.server import start_line
    from spec_setup import _served_fleet
    base, d, close = _served_fleet()
    port = base.rsplit(':', 1)[1]

    def get(host, path='/', data=None, origin=None):
        h = {'Cookie': 'gg=tok', 'Host': f'{host}:{port}'}
        if origin:
            h['Origin'] = origin
        try:
            r = urllib.request.urlopen(urllib.request.Request(base + path, data=data, headers=h))
            return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()
    try:
        assert get('localhost')[0] == 200 and get('127.0.0.1')[0] == 200
        code, page = get('evil.example')
        assert code == 403 and 'wrong Host' in page and 'back to your bots' in page
        body = f'gg={form_token("tok")}&action=clear&fleet=0&confirm=x'.encode()
        assert get('localhost', '/trade', body, origin=f'http://127.0.0.1:{port}')[0] == 403
        assert get('localhost', '/trade', body, origin=f'http://localhost:{port}')[0] == 200
        code, page = get('127.0.0.1', '/?t=nope')
        assert code == 403 and '<a href="/">back to your bots</a>' in page
    finally:
        close()
    assert start_line('127.0.0.1:41900', 'k3y', '/x/.panel-token', tty=False) == (
        'panel: http://127.0.0.1:41900/ — the key is in its token file (.panel-token); open /?t=<key> once')
    assert 'k3y' in start_line('127.0.0.1:41900', 'k3y', '/x/.panel-token', tty=True)
    assert 'k3y' in start_line('127.0.0.1:41900', 'k3y', None, tty=False)      # a one-off key lives nowhere else
    root = _P(tempfile.mkdtemp())
    assert saved_key(root) == ''
    (root / TOKEN_FILE).write_text('k3y\n')
    os.chmod(root / TOKEN_FILE, 0o600)
    assert saved_key(root) == '?t=k3y'
    os.chmod(root / TOKEN_FILE, 0o644)
    assert saved_key(root) == ''


def spec_U98_the_exchange_box_says_its_window():
    """The audit, 2026-10-16: the exchange box says its figure is each
    bot's own window, not the equity line's (a reader took the gap for a bug)."""
    from panel.server import render
    assert 'not the same window as the equity line below' in render([('demo', CONTRACT)])
