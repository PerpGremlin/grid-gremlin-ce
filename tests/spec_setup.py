# Specs for the panel's setup form (§11): the quick setup, the advanced
# form that reaches every config key, and the bot in plain words.
import glob
import json
import os

from gridgremlin.apply import check_link_fits, make_botid, widest_rung
from gridgremlin.config import (GRID_KEYS, MARTINGALE_KEYS, SLIDE_KEYS,
                                STOP_KEYS, validate_config)
from gridgremlin.main import BYBIT_LINK_LIMIT
from panel.setup import (CAUTION, PRESETS, advanced_page, bot_from_form,
                         config_paths, fields, form_from_bot, quick_bot,
                         quick_page, sentence)

CONFIGS = os.path.join(os.path.dirname(__file__), '..', 'configs')


def _shipped_rows():
    for path in sorted(glob.glob(os.path.join(CONFIGS, 'fleet*.json'))):
        for row in json.load(open(path))['bots']:
            yield row


# --- the advanced form reaches every key the file accepts --------------------

def spec_U1_the_advanced_form_reaches_every_config_key():
    """The owner: "every configurable part of creating a bot accessible
    through the UI". A key config.py learns and the form does not fails
    here — never again a 'file-only for now'."""
    # from_base_pct is the martingale's: a grid has no base order (X10)
    grid = (set(GRID_KEYS) | {f'stop.{k}' for k in STOP_KEYS
                              if k != 'from_base_pct'}
            | {f'slide.{k}' for k in SLIDE_KEYS})
    assert grid - config_paths('grid') == set()
    # rungs_beyond follows a sliding window; a martingale has none (X8)
    mart = (set(MARTINGALE_KEYS)
            | {f'stop.{k}' for k in STOP_KEYS if k != 'rungs_beyond'})
    assert mart - config_paths('martingale') == set()


def spec_U1_every_field_has_plain_words_and_a_unique_name():
    for strategy in ('grid', 'martingale'):
        names = [f[0] for f in fields(strategy)]
        assert len(names) == len(set(names))
        for name, path, kind, label, help_ in fields(strategy):
            assert label and help_ and '_' not in label, (name, label)
        page = advanced_page(strategy, {}, ['a.json'])
        for name in names:
            assert f'name="{name}"' in page, name


def spec_U2_every_shipped_row_survives_the_form_unchanged():
    """Row -> form values -> row: the engine must see the same bot. This is
    'copy a bot', and it is the proof the form loses nothing."""
    n = 0
    for row in _shipped_rows():
        venue = row.get('venue', 'bybit')
        back = bot_from_form(form_from_bot(row), venue)
        assert validate_config(back) == validate_config(dict(row)), (
            row['symbol'], row['side'])
        n += 1
    assert n >= 15


def spec_U2_a_blank_is_left_out_and_a_percent_is_a_percent():
    bot = bot_from_form({'strategy': 'martingale', 'symbol': 'solusdt',
                         'side': 'long', 'capital': '1,000',
                         'deviation_pct': '1.5', 'leverage': '',
                         'take_profit_tranches': '1:50, 2:50',
                         'repeat': '1', 'stop_level': '50'}, 'bybit')
    assert bot == {'strategy': 'martingale',             # no venue: default
                   'symbol': 'SOLUSDT', 'side': 'long', 'capital': 1000,
                   'deviation_pct': 0.015, 'repeat': True,
                   'take_profit_tranches': [
                       {'at_avg_pct': 0.01, 'share': 0.5},
                       {'at_avg_pct': 0.02, 'share': 0.5}]}
    # a block's fields count only when the block is switched on
    on = bot_from_form({'symbol': 'BTCUSDT', 'side': 'long', 'stop_on': '1',
                        'stop_watch': 'mark_price', 'stop_level': '50'},
                       'bybit')
    assert on['stop'] == {'watch': 'mark_price', 'level': 50.0}


def spec_U2_a_field_that_does_not_parse_is_named_in_plain_words():
    try:
        bot_from_form({'symbol': 'BTCUSDT', 'side': 'long',
                       'capital': 'lots'}, 'bybit')
    except ValueError as e:
        assert 'Investment' in str(e) and 'lots' in str(e)
    else:
        raise AssertionError('accepted a capital of "lots"')


# --- the quick setup ----------------------------------------------------------

def _quick(preset, caution, venue='bybit', symbol='BTCUSDT', stop=False):
    form = {'preset': preset, 'caution': caution, 'symbol': symbol,
            'capital': '1000'}
    if stop:
        form['stop_on'] = '1'
    return quick_bot(form, venue, 84905.14)


def spec_U3_every_preset_at_every_caution_is_a_row_the_engine_accepts():
    for venue, symbol in (('bybit', 'BTCUSDT'), ('hyperliquid', 'BTC'),
                          ('hyperliquid', 'DOGE')):
        for preset in PRESETS:
            for caution in CAUTION:
                for stop in (False, True):
                    if preset == 'reversal' and venue == 'hyperliquid':
                        try:                        # D54: one-way venue
                            _quick(preset, caution, venue, symbol, stop)
                        except ValueError as e:
                            assert 'one position per coin' in str(e)
                            continue
                        raise AssertionError('a reversal pair on HL')
                    bot = _quick(preset, caution, venue, symbol, stop)
                    cfg = validate_config(dict(bot))
                    hl = venue == 'hyperliquid'      # I3, as the build does
                    check_link_fits(
                        make_botid(cfg['market_type'], symbol, cfg['side']),
                        widest_rung(cfg), 16 if hl else BYBIT_LINK_LIMIT,
                        gen_chars=4 if hl else 10)
                    assert bool(cfg.get('stop')) is stop


def spec_U3_the_quick_grid_is_built_around_todays_price():
    bot = _quick('sideways', 'balanced', stop=True)
    assert bot['lower'] < 84905.14 < bot['upper']
    assert abs(bot['upper'] / 84905.14 - 1.10) < 0.001
    assert bot['stop']['level'] < bot['lower']         # a long's stop: below
    assert 'slide' not in bot
    up = _quick('rising', 'careful', stop=True)
    assert up['slide']['direction'] == 'favourable' and up['seed'] is True
    assert up['stop'] == {'watch': 'mark_price', 'rungs_beyond': 3}   # X8
    down = _quick('falling', 'bold')
    assert down['side'] == 'short' and 'seed' not in down
    assert 'stop' not in down                          # opt-in (D32)


def spec_U3_the_quick_dca_fits_the_money_and_stops_past_its_last_order():
    for caution in CAUTION:
        bot = _quick('dca_long', caution, stop=True)
        cfg = validate_config(dict(bot))               # M2 would refuse
        assert cfg['ladder_total_notional'] <= 1000 * bot['leverage']
        assert cfg['ladder_total_notional'] > 0.9 * 1000 * bot['leverage']
        depth = sum(cfg['deviation_pct'] * cfg['deviation_step_multiplier']
                    ** i for i in range(cfg['max_averaging_orders']))
        assert bot['stop']['level'] < 84905.14 * (1 - depth)
    short = _quick('dca_short', 'balanced', stop=True)
    assert short['side'] == 'short' and short['stop']['level'] > 84905.14


def spec_U3_a_missing_answer_is_asked_for_in_plain_words():
    for form, frag in (({'preset': 'sideways', 'capital': '5'}, 'which coin'),
                       ({'preset': 'sideways', 'symbol': 'BTCUSDT'},
                        'how much')):
        try:
            quick_bot(form, 'bybit', 100.0)
        except ValueError as e:
            assert frag in str(e)
        else:
            raise AssertionError(f'accepted {form}')


# --- the sentence -------------------------------------------------------------

def spec_U4_the_sentence_says_what_the_bot_will_do():
    cfg = validate_config(_quick('sideways', 'balanced'))
    s = sentence(cfg, 84905.14)
    for frag in ('31 grids', '76,415', '93,396', 'buys about',
                 'one grid higher', 'investment is 1,000', '5x leverage',
                 'no stop loss', 'is inside the range'):
        assert frag in s, (frag, s)
    cfg = validate_config(_quick('falling', 'careful', stop=True))
    s = sentence(cfg, 84905.14)
    for frag in ('sells about', 'follows it down', '3 grids beyond',
                 'stops for good'):
        assert frag in s, (frag, s)
    cfg = validate_config(_quick('dca_long', 'balanced'))
    s = sentence(cfg)
    for frag in ('buys BTCUSDT in steps', 'up to 5 more orders',
                 '1.00% move', 'starts again', 'no stop loss'):
        assert frag in s, (frag, s)


def spec_U4_the_sentence_warns_when_following_buys_beyond_the_money():
    row = next(r for r in _shipped_rows()
               if (r.get('slide') or {}).get('direction') == 'both')
    s = sentence(validate_config(dict(row)), 1.0)
    assert 'up or down' in s and 'MORE than its investment' in s
    assert 'is OUTSIDE the range' in s


def spec_U4_every_shipped_row_has_a_sentence():
    for row in _shipped_rows():
        assert sentence(validate_config(dict(row)), 100.0).endswith('.')


def spec_D54_the_reversal_preset_is_two_halves_split_at_a_static_mid():
    """Owner 2026-10-05, taking the framing: two legs split at a mid on a
    venue that holds both sides, the mid static (the slide is the human-
    shaped follower), the flipping single-position shape parked."""
    from panel.setup import _sig
    mark = 84905.14
    long = quick_bot({'preset': 'reversal', 'caution': 'balanced',
                      'symbol': 'BTCUSDT', 'capital': '1000',
                      'stop_on': '1'}, 'bybit', mark)
    assert long['side'] == 'long' and long['upper'] == _sig(mark)
    assert abs(long['lower'] / mark - 0.90) < 0.001
    assert long['capital'] == 500 and long['rungs'] == 16      # half each
    assert 'slide' not in long and 'seed' not in long           # static mid
    assert long['stop']['level'] < long['lower']          # a level: static
    assert 'the long half, below the mid' in long['_note']
    short = quick_bot({'preset': 'reversal', 'caution': 'balanced',
                       'symbol': 'BTCUSDT', 'capital': '1000',
                       'leg': 'short', 'mid': f"{long['upper']:.10g}"},
                      'bybit', mark * 1.02)                 # price moved on
    assert short['side'] == 'short' and short['lower'] == long['upper']
    assert abs(short['upper'] / long['upper'] - 1.10) < 0.001
    assert short['capital'] == long['capital'] and 'stop' not in short
    for leg in (long, short):
        validate_config(dict(leg))
    skewed = quick_bot({'preset': 'reversal', 'caution': 'balanced',
                        'symbol': 'BTCUSDT', 'capital': '1000',
                        'mid': '90000'}, 'bybit', mark)    # the owner's mid
    assert skewed['upper'] == 90000 and skewed['lower'] < mark < skewed['upper']
    try:
        quick_bot({'preset': 'reversal', 'caution': 'bold', 'symbol': 'BTC',
                   'capital': '100'}, 'hyperliquid', mark)
    except ValueError as e:
        assert 'one position per coin' in str(e)
    else:
        raise AssertionError('Hyperliquid took a reversal pair')


def spec_D57_the_gate_judges_the_merged_row_and_never_skips_a_bad_one():
    """At the panel's gates a row naming a profile is judged merged; and a
    bad row, which the ENGINE sets aside under D52, is a refusal at the
    gate — never a quiet skip."""
    from panel.create import validate_whole
    wd = {'tag': 't', 'snapshot': 's', 'state': 'st', 'staleness_seconds': 9,
          'mm_rate_max': 0.5, 'equity_min': 10, 're_alert_seconds': 9,
          'assumes_sole_actor': True}
    from gridgremlin.adapters import LinearAdapter
    ad = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001,
                        'min_qty': 0.001, 'price_tick': 0.1,
                        'min_notional': 5.0})
    good = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
            'capital': 1000, 'lower': 80000, 'upper': 90000, 'rungs': 11,
            'risk_profile': 'careful'}
    fleet = {'risk_profiles': {'careful': {'leverage': 2}}, 'bots': [good]}
    assert validate_whole(fleet, wd, lambda c: ad) is None
    bad = dict(fleet, bots=[good, dict(good, side='shrot')])
    why = validate_whole(bad, wd, lambda c: ad)
    assert why and 'bots[1]' in why


def spec_U42_a_written_grid_offers_its_mirror_on_the_other_side():
    """Owner 2026-10-04 made a BTCPERP long through the advanced door and
    lost the preset's hand-off. Any written grid now offers its mirror:
    the same width, rungs, money and leverage past its edge."""
    from panel.setup import mirror_leg
    long = {'market_type': 'linear', 'symbol': 'BTCPERP', 'side': 'long',
            'capital': 15000, 'leverage': 10, 'lower': 70000, 'upper': 90000,
            'rungs': 21, 'slide': {'direction': 'both', 'trigger_rungs': 2,
                                   'max_rungs': 9, 'confirm_seconds': 900,
                                   'ref_position': 0.5},
            'stop': {'watch': 'mark_price', 'level': 68000}, 'seed': True,
            '_note': 'mine'}
    m = mirror_leg(long)
    assert m['side'] == 'short' and m['lower'] == 90000
    assert abs(m['upper'] / 90000 - 90000 / 70000) < 2e-3     # same ratio, rounded
    assert m['capital'] == 15000 and m['leverage'] == 10 and m['rungs'] == 21
    assert 'slide' not in m and 'seed' not in m
    assert m['stop']['level'] > m['upper']                  # past its edge
    assert 'the other side of linBTCPERPl, mirrored at 90000' in m['_note']
    back = mirror_leg(m)                                    # and back again
    assert back['side'] == 'long' and back['upper'] == 90000
    assert abs(back['lower'] - 70000) < 10.0            # five significant figures
    fixed = mirror_leg(dict(long, spacing_type='fixed'))
    assert fixed['upper'] == 110000                         # same width
    try:
        mirror_leg({'strategy': 'martingale', 'symbol': 'X'})
    except ValueError as e:
        assert 'only a grid' in str(e)
    else:
        raise AssertionError('a DCA row has no other side')
    # through the served panel: a plain quick grid, written, offers it
    import html
    import re
    base, d, close = _served_fleet()
    try:
        page = _call(base, '/setup', {
            'how': 'quick', 'then': 'gates', 'fleet': '0',
            'preset': 'sideways', 'caution': 'balanced', 'symbol': 'btcusdt',
            'capital': '1000'})
        proposal = html.unescape(
            re.search(r'name="proposal" value="([^"]*)"', page).group(1))
        done = _call(base, '/apply', {'fleet': '0', 'proposal': proposal,
                                      'confirm': 'linBTCUSDTl'})
        assert 'make the other side' in done
        bot_json = html.unescape(re.search(
            r'name="bot_json" value="([^"]*)"', done).group(1))
        page2 = _call(base, '/setup', {'how': 'mirror', 'fleet': '0',
                                       'bot_json': bot_json})
        assert 'linBTCUSDTs — create: gates passed' in page2
        proposal2 = html.unescape(
            re.search(r'name="proposal" value="([^"]*)"', page2).group(1))
        done2 = _call(base, '/apply', {'fleet': '0', 'proposal': proposal2,
                                       'confirm': 'linBTCUSDTs'})
        assert 'linBTCUSDTs: written' in done2
        rows = json.loads((d / 'f.json').read_text())['bots']
        l = next(b for b in rows if b['symbol'] == 'BTCUSDT' and b['side'] == 'long')
        s = next(b for b in rows if b['symbol'] == 'BTCUSDT' and b['side'] == 'short')
        assert s['lower'] == l['upper'] and s['rungs'] == l['rungs']
        assert s['capital'] == l['capital']
    finally:
        close()


def spec_U5_the_quick_page_offers_every_preset_and_the_advanced_door():
    page = quick_page(['fleet.demo.json', 'fleet.hl.testnet.json'])
    for key in PRESETS:
        assert f'value="{key}"' in page
    assert '/setup?adv=grid' in page and '/setup?adv=martingale' in page
    assert 'fleet.hl.testnet.json' in page
    assert 'name="stop_on" value="1">' in page         # off unless ticked
    assert 'name="mid"' in page and 'reversal only' in page   # D54: a skew
    assert 'USDC on a PERP market and on Hyperliquid' in page  # U41: the coin


# --- through the real server: quick setup -> summary -> apply ----------------

def _bars(n=60, start=80000.0, step=100.0):
    """A plain rising month: close climbs, each bar spans +-200."""
    return [{'t': i * 14_400_000, 'o': start + step * i,
             'h': start + step * i + 200, 'l': start + step * i - 200,
             'c': start + step * i} for i in range(n)]


def _served_fleet():
    """A real panel over a temp fleet + watchdog pair, public data faked."""
    import http.server
    import tempfile
    import threading
    from pathlib import Path
    import panel.create as pc
    from gridgremlin.adapters import LinearAdapter
    from panel.server import Handler
    d = Path(tempfile.mkdtemp())
    wd = {'tag': 't', 'snapshot': 's', 'state': 'st', 'staleness_seconds': 9,
          'mm_rate_max': 0.5, 'equity_min': 10, 're_alert_seconds': 9,
          'assumes_sole_actor': True}
    (d / 'wd.json').write_text(json.dumps(wd))
    seed_row = dict(next(r for r in _shipped_rows()
                         if r['symbol'] == 'ETHUSDT' and r['side'] == 'long'))
    (d / 'f.json').write_text(json.dumps(
        {'watchdog': str(d / 'wd.json'), 'bots': [seed_row]}))
    saved = pc.public_mark, pc.public_adapter, pc.public_bars
    pc.public_mark = lambda cfg: 84905.14
    pc.public_bars = lambda cfg, **kw: _bars()
    pc.public_adapter = lambda cfg: LinearAdapter(
        {'symbol': cfg['symbol'], 'qty_step': 0.001, 'min_qty': 0.001,
         'price_tick': 0.1, 'min_notional': 5.0, 'settle_coin': 'USDT'})

    class H(Handler):
        pass
    H.token, H.fleets, H.labels = 'tok', (str(d / 'f.json'),), ('demo',)
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
    H.host_ok = f'127.0.0.1:{srv.server_port}'
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def close():
        srv.shutdown()
        pc.public_mark, pc.public_adapter, pc.public_bars = saved
        H._bars.clear()
        H._adapters.clear()
    return f'http://{H.host_ok}', d, close


def _call(base, path, data=None):
    import urllib.parse
    import urllib.request
    body = urllib.parse.urlencode(dict(data, gg='1')).encode() \
        if data is not None else None
    req = urllib.request.Request(base + path, data=body,
                                 headers={'Cookie': 'gg=tok'})
    return urllib.request.urlopen(req).read().decode()


def spec_P1_the_panel_holds_its_boundary_behind_the_token():
    """Audit 2026-10-05, phase 2: what the token already guards is still
    held tight — operator text is escaped wherever it is drawn, /init
    writes only the panel's own fleet file, a negative length is no read,
    and rehearsals are capped on the one-core box."""
    import socket
    from gridgremlin.tombstones import path_for
    base, d, close = _served_fleet()
    try:
        from panel.server import Handler
        tp = path_for(d / 'f.json', {})
        tp.parent.mkdir(parents=True, exist_ok=True)
        tp.write_text(json.dumps({'<b>x</b>': {'reason': '<script>1</script>'}}))

        class Me:
            def _tombs_path(self):
                return tp
        page = Handler._tombs_html(Me())
        assert '<script>1</script>' not in page and '&lt;script&gt;' in page
        assert '<b>x</b>' not in page
        outside = d / 'elsewhere' / 'f.json'
        page = _call(base, '/init', {'path': str(outside), 'tag': 't',
                                     'equity_min': '10'})
        assert 'init refused' in page and 'started on' in page
        assert not outside.parent.exists()
        host = base.split('//')[1]
        h, p = host.split(':')
        s = socket.create_connection((h, int(p)), timeout=5)
        s.sendall(f'POST /setup HTTP/1.1\r\nHost: {host}\r\nCookie: gg=tok'
                  '\r\nConnection: close\r\nContent-Length: -1\r\n\r\n'
                  .encode())
        s.settimeout(10)
        answer = b''
        while True:                             # read it all: closing early
            chunk = s.recv(4096)                # broke the server's write
            if not chunk:
                break
            answer += chunk
        s.close()
        assert answer.startswith(b'HTTP/1.')    # an answer, not a hang
        assert b' 403 ' in answer.split(b'\r\n', 1)[0]   # no form, no act
    finally:
        close()
    from panel.server import Handler
    saved, Handler._jobs = Handler._jobs, {}
    try:
        Handler._jobs = {str(i): {'done': False, 't0': 0} for i in range(2)}
        assert Handler._start_rehearsal(Handler, {}, {}, '{}', 7) is None
    finally:
        Handler._jobs = saved


def spec_P2_the_keys_stay_the_owners():
    """Audit 2026-10-05: .env's 0600 was a stated rule, never checked; the
    Telegram token rode curl's argv in the alert units, visible to `ps`."""
    import os
    import tempfile
    from pathlib import Path
    from gridgremlin.exchange.env import load_env
    d = Path(tempfile.mkdtemp())
    env = d / '.env'
    env.write_text('GG_SPEC_P2=1\n')
    os.chmod(env, 0o644)
    try:
        load_env(env)
    except PermissionError as e:
        assert 'chmod 600' in str(e)
    else:
        raise AssertionError('a public .env was loaded')
    os.chmod(env, 0o600)
    load_env(env)
    assert os.environ.pop('GG_SPEC_P2') == '1'
    ops = Path(__file__).resolve().parents[1] / 'ops'
    for name in ('fleet-failed.service.template',
                 'watchdog-failed.service.template'):
        text = (ops / 'systemd' / name).read_text()
        assert '${TELEGRAM_BOT_TOKEN}' not in text.replace('$${', '')
        assert '-K -' in text
    tri = (ops / 'retired' / 'triage.sh').read_text()
    assert 'bot${TELEGRAM_BOT_TOKEN}' not in tri and '-K -' in tri


def spec_U6_quick_setup_to_a_written_bot_through_the_four_gates():
    import html
    import re
    base, d, close = _served_fleet()
    try:
        assert 'set up a bot' in _call(base, '/setup')
        assert 'set up a bot' in _call(base, '/create')    # the old door
        page = _call(base, '/setup', {
            'how': 'quick', 'then': 'gates', 'fleet': '0',
            'preset': 'rising', 'caution': 'balanced', 'symbol': 'btcusdt',
            'capital': '1000'})
        assert 'linBTCUSDTl — create: gates passed' in page
        assert 'in plain words' in page and 'follows it up' in page
        assert 'change something' in page
        before = (d / 'f.json').read_text()
        proposal = html.unescape(
            re.search(r'name="proposal" value="([^"]*)"', page).group(1))
        wrong = _call(base, '/apply', {'fleet': '0', 'proposal': proposal,
                                       'confirm': 'yes'})
        assert 'not applied' in wrong and 'capitals do not matter' in wrong
        assert (d / 'f.json').read_text() == before      # a click is not it
        done = _call(base, '/apply', {'fleet': '0', 'proposal': proposal,
                                      'confirm': ' LINbtcusdtL '})   # U18:
        # the name is the decision, its capitals and stray spaces are not
        assert 'linBTCUSDTl: written' in done
        fleet = json.loads((d / 'f.json').read_text())
        row = fleet['bots'][-1]
        assert row['symbol'] == 'BTCUSDT' and row['slide'] and row['seed']
        validate_config(dict(row))
        assert 'positions' not in json.loads((d / 'wd.json').read_text()) \
            or 'linBTCUSDTl' not in json.loads(
                (d / 'wd.json').read_text())['positions']     # D32: opt-in
    finally:
        close()


def spec_D54_the_written_page_hands_over_to_the_short_half():
    """The quick path twice: the long half through its gates and name,
    then one button on the written page carries the same answers and the
    same mid to the short half's gates and name. Two rows meet at the mid."""
    import html
    import re
    base, d, close = _served_fleet()
    try:
        page = _call(base, '/setup', {
            'how': 'quick', 'then': 'gates', 'fleet': '0',
            'preset': 'reversal', 'caution': 'balanced',
            'symbol': 'btcusdt', 'capital': '1000'})
        assert 'linBTCUSDTl — create: gates passed' in page
        assert 'the long half of a reversal grid, below the mid' in page
        proposal = html.unescape(
            re.search(r'name="proposal" value="([^"]*)"', page).group(1))
        done = _call(base, '/apply', {'fleet': '0', 'proposal': proposal,
                                      'confirm': 'linBTCUSDTl'})
        assert 'linBTCUSDTl: written' in done
        assert 'now the short half' in done
        hidden = dict(re.findall(
            r'name="([a-z_]+)" value="([^"]*)"',
            done[done.index('This is half'):done.index('now the short half')]))
        assert hidden['leg'] == 'short' and hidden['preset'] == 'reversal'
        page2 = _call(base, '/setup', dict(hidden, how='quick', then='gates'))
        assert 'linBTCUSDTs — create: gates passed' in page2
        assert 'the long half of a reversal grid' not in page2
        proposal2 = html.unescape(
            re.search(r'name="proposal" value="([^"]*)"', page2).group(1))
        done2 = _call(base, '/apply', {'fleet': '0', 'proposal': proposal2,
                                       'confirm': 'linBTCUSDTs'})
        assert 'linBTCUSDTs: written' in done2
        assert 'now the short half' not in done2            # the pair is done
        rows = json.loads((d / 'f.json').read_text())['bots']
        long = next(b for b in rows if b['symbol'] == 'BTCUSDT'
                    and b['side'] == 'long')
        short = next(b for b in rows if b['symbol'] == 'BTCUSDT'
                     and b['side'] == 'short')
        assert long['upper'] == short['lower'] == float(hidden['mid'])
        assert long['capital'] == short['capital']
        for b in (long, short):
            validate_config(dict(b))
            assert 'slide' not in b
    finally:
        close()


def spec_U6_a_refusal_returns_to_the_form_with_the_values_kept():
    base, d, close = _served_fleet()
    try:
        page = _call(base, '/setup', {
            'how': 'advanced', 'strategy': 'grid', 'fleet': '0',
            'symbol': 'BTCUSDT', 'side': 'long', 'capital': '1000',
            'market_type': 'linear', 'lower': '90000', 'upper': '80000',
            'rungs': '21'})
        assert 'advanced setup: grid' in page          # back on the form
        assert 'class="refusal"' in page               # the engine's words,
        assert 'nothing was saved' in page             # boxed, and FIRST
        assert page.index('class="refusal"') < page.index('advanced setup')
        assert 'value="90000"' in page                 # nothing retyped
        again = _call(base, '/setup', {
            'how': 'advanced', 'strategy': 'grid', 'fleet': '0',
            'symbol': 'ETHUSDT', 'side': 'long', 'capital': '1000',
            'market_type': 'linear', 'lower': '2000', 'upper': '3000',
            'rungs': '21'})
        assert 'already in this fleet' in again        # one bot per market
        assert 'You already have a bot for this coin' in again
        assert '/edit?fleet=0&bot=linETHUSDTl' in again    # the way forward
        typo = _call(base, '/setup', {
            'how': 'advanced', 'strategy': 'grid', 'fleet': '0',
            'symbol': 'BTCUSDT', 'capital': 'lots'})
        assert 'Investment' in typo and 'not yet' in typo
    finally:
        close()


def spec_U6_copy_carries_every_setting_but_the_coin():
    base, d, close = _served_fleet()
    try:
        page = _call(base, '/setup?fleet=0&copy=linETHUSDTl')
        assert 'copied from linETHUSDTl' in page
        assert 'name="symbol" value=""' in page
        assert 'name="slide_on" value="1" checked' in page
        assert 'name="rungs" value="41"' in page
    finally:
        close()


def spec_I3_the_panel_gate_refuses_a_link_the_build_would_refuse():
    """2026-10-02: a row passed the validator and crash-looped the HL unit
    on a 17-character link. Gate 1 now runs the build's own check."""
    from panel.create import validate_whole
    row = {'venue': 'hyperliquid', 'market_type': 'linear', 'symbol': 'DOGE',
           'side': 'short', 'capital': 150, 'leverage': 5, 'lower': 0.08,
           'upper': 0.1, 'rungs': 15, 'max_position_base': 'unbounded',
           'slide': {'trigger_rungs': 2, 'max_rungs': 400,
                     'confirm_seconds': 900, 'direction': 'both'},
           'stop': {'watch': 'mark_price', 'rungs_beyond': 3}}
    wd = {'tag': 't', 'snapshot': 's', 'state': 'st', 'staleness_seconds': 9,
          'mm_rate_max': 0.5, 'equity_min': 10, 're_alert_seconds': 9,
          'assumes_sole_actor': True}
    from gridgremlin.adapters import LinearAdapter
    adapter = LinearAdapter({'symbol': 'DOGE', 'qty_step': 1.0,
                             'min_qty': 1.0, 'price_tick': 0.00001,
                             'min_notional': 10.0})
    why = validate_whole({'watchdog': 'w', 'bots': [row]}, wd,
                         lambda cfg: adapter)
    assert why and 'order link' in why
    row['slide']['max_rungs'] = 8
    assert validate_whole({'watchdog': 'w', 'bots': [row]}, wd,
                          lambda cfg: adapter) is None


def spec_U5_the_setup_form_holds_no_key_and_asks_for_none():
    """§11's floor: a compromised panel steals nothing."""
    import inspect
    import panel.setup as ps
    src = inspect.getsource(ps)
    for word in ('os.environ', 'load_env', 'API_KEY', 'SECRET',
                 'exchange.bybit.client', 'signing'):
        assert word not in src, word
    pages = quick_page(['f.json']) + ''.join(
        advanced_page(s, {}, ['f.json']) for s in ('grid', 'martingale'))
    for word in ('api key', 'secret', 'password', 'type="password"'):
        assert word not in pages.lower(), word


def spec_U7_edit_opens_every_setting_of_the_bot_with_its_identity_fixed():
    """The owner: "the advanced setting feature where the user can edit all
    the parametres of the bot". The old edit form moved four knobs."""
    base, d, close = _served_fleet()
    try:
        page = _call(base, '/edit?fleet=0&bot=linETHUSDTl')
        assert 'edit linETHUSDTl' in page
        for name in ('capital', 'rungs', 'slide_max', 'stop_level',
                     'place_within_pct', 'max_position_base'):
            assert f'name="{name}"' in page, name      # all of it, not four
        assert 'name="rungs" value="41"' in page       # filled in
        assert 'name="slide_on" value="1" checked' in page
        # identity is shown, not editable (I2)
        assert '<b>ETHUSDT</b><input type="hidden" name="symbol"' in page
        assert '<select name="side"' not in page
        assert 'name="mode" value="edit"' in page
    finally:
        close()


def spec_U7_an_edit_changes_what_was_changed_and_keeps_the_rest():
    import html
    import re
    base, d, close = _served_fleet()
    try:
        fleet = json.loads((d / 'f.json').read_text())
        fleet['bots'][0]['_note'] = 'mine'            # the operator's own
        (d / 'f.json').write_text(json.dumps(fleet))
        before = dict(fleet['bots'][0])
        form = dict(form_from_bot(before), how='advanced', strategy='grid',
                    fleet='0', mode='edit', orig='linETHUSDTl')
        form['capital'] = '3000'                      # one number changed
        form.pop('slide_on')                          # and following off
        form['max_position_base'] = ''                # so the cap returns
        page = _call(base, '/setup', form)
        assert 'linETHUSDTl — edit: gates passed' in page
        assert 'investment is 3,000' in page
        assert 'follows it' not in page               # the sentence agrees
        assert 'change something' in page
        proposal = html.unescape(
            re.search(r'name="proposal" value="([^"]*)"', page).group(1))
        done = _call(base, '/apply', {'fleet': '0', 'proposal': proposal,
                                      'confirm': 'linETHUSDTl'})
        assert 'linETHUSDTl: written' in done
        after = json.loads((d / 'f.json').read_text())['bots'][0]
        assert after['capital'] == 3000.0 and 'slide' not in after
        assert after['_note'] == 'mine'               # rode along
        for key in ('symbol', 'side', 'lower', 'upper', 'rungs',
                    'leverage'):
            assert after[key] == before[key], key     # untouched
    finally:
        close()


def spec_U7_an_edit_cannot_change_what_the_bot_is():
    base, d, close = _served_fleet()
    try:
        row = json.loads((d / 'f.json').read_text())['bots'][0]
        form = dict(form_from_bot(row), how='advanced', strategy='grid',
                    fleet='0', mode='edit', orig='linETHUSDTl',
                    symbol='BTCUSDT')                 # a forged identity
        page = _call(base, '/setup', form)
        assert 'cannot change identity' in page
        assert 'edit linETHUSDTl' in page             # back on the edit form
        gone = _call(base, '/create', {'fleet': '0', 'symbol': 'BTCUSDT'})
        assert 'nothing to create' in gone            # the old forms retired
    finally:
        close()


def spec_U2_a_choice_left_at_default_stays_out_of_the_file():
    page = advanced_page('grid', {}, ['f.json'])
    assert ('<select name="exit_floor"><option value="" selected>rung'
            '</option><option>basis</option></select>') in page    # U46
    assert '<select name="side"><option' in page
    assert '<select name="side"><option value=""' not in page
    bot = bot_from_form({'symbol': 'BTCUSDT', 'side': 'long',
                         'market_type': 'linear', 'exit_floor': '',
                         'spacing_type': '', 'rung_sizing': ''}, 'bybit')
    assert set(bot) == {'symbol', 'side', 'market_type'}


def spec_U5_the_hl_lookup_names_testnet_and_needs_no_environment():
    """Found on the box 2026-10-02: the panel process has no env file by
    design, so an env-guessed client resolved to mainnet and D25 refused
    every Hyperliquid setup."""
    import os
    import gridgremlin.exchange.hyperliquid.client as hc
    import panel.create as pc
    seen = {}

    class Fake:
        def __init__(self, env=None, **kw):
            seen['env'], seen['kw'] = env, kw

        def meta_and_ctxs(self):
            return ({'universe': [{'name': 'BTC', 'szDecimals': 5}]},
                    [{'markPx': '85000.0'}])
    saved, env = hc.InfoClient, os.environ.pop('HL_TESTNET', None)
    hc.InfoClient = Fake
    try:
        cfg = {'venue': 'hyperliquid', 'market_type': 'linear',
               'symbol': 'BTC'}
        assert pc.public_mark(cfg) == 85000.0
        assert seen == {'env': 'testnet', 'kw': {}}     # no mainnet flag
        assert type(pc.public_adapter(cfg)).__name__ == 'HLPerpAdapter'
        try:
            pc.public_mark(dict(cfg, symbol='NOPE'))
        except pc.ConfigError as e:
            assert 'lists no such market' in str(e)
        else:
            raise AssertionError('an unlisted coin was priced')
    finally:
        hc.InfoClient = saved
        if env is not None:
            os.environ['HL_TESTNET'] = env


def spec_U6_a_first_order_below_the_venue_minimum_is_refused_at_the_form():
    """Seen live: 100 of money, careful, on Hyperliquid made a first order
    of 9 against a minimum of 10. The validator cannot know (it has no
    price); the engine would only say so once running."""
    base, d, close = _served_fleet()
    try:
        page = _call(base, '/setup', {
            'how': 'quick', 'then': 'gates', 'fleet': '0',
            'preset': 'dca_long', 'caution': 'careful', 'symbol': 'SOLUSDT',
            'capital': '40'})
        assert 'minimum order' in page and 'raise the investment' in page
        assert 'advanced setup' in page and 'value="40"' in page
        ok = _call(base, '/setup', {
            'how': 'quick', 'then': 'gates', 'fleet': '0',
            'preset': 'dca_long', 'caution': 'careful', 'symbol': 'SOLUSDT',
            'capital': '4000'})
        assert 'gates passed' in ok
    finally:
        close()


# --- the bot drawn on its price ----------------------------------------------

def _grid_cfg(**over):
    row = {'venue': 'bybit', 'market_type': 'linear', 'symbol': 'BTCUSDT',
           'side': 'long', 'capital': 1000, 'leverage': 5, 'lower': 80000,
           'upper': 90000, 'rungs': 11, 'spacing_type': 'fixed'}
    row.update(over)
    return validate_config(row)


def spec_U8_the_chart_draws_the_engines_own_levels():
    """Every line comes from the engine's maths — lattice_price,
    stop_level_for, martingale_schedule — so the picture cannot disagree
    with the plan."""
    from gridgremlin.ladder import lattice_price, stop_level_for
    from panel.chart import levels
    cfg = _grid_cfg(stop={'watch': 'mark_price', 'rungs_beyond': 3},
                    max_position_base='unbounded',
                    slide={'trigger_rungs': 2, 'max_rungs': 50,
                           'confirm_seconds': 900, 'direction': 'both'})
    got = levels(cfg, 85000.0)
    kinds = [k for _, k, _ in got]
    assert kinds.count('rung') == 9                  # the 9 inside the edges
    assert (80000.0, 'edge-lower', 'lowest') in got
    assert (90000.0, 'edge-upper', 'highest') in got
    assert (stop_level_for(cfg), 'stop', 'stop loss') in got      # 77000
    trig = sorted(p for p, k, _ in got if k == 'trigger')
    assert trig == [lattice_price(cfg, -2), lattice_price(cfg, 12)]
    one_way = levels(_grid_cfg(slide={'trigger_rungs': 2, 'max_rungs': 50,
                                      'confirm_seconds': 900}), 85000.0)
    assert [lb for _, k, lb in one_way if k == 'trigger'] == [
        'follows up']                                # a long: favourable


def spec_U8_a_dca_bot_is_drawn_as_its_orders_and_its_target():
    from panel.chart import levels
    cfg = validate_config(_quick('dca_long', 'balanced', stop=True))
    got = levels(cfg, 100.0)
    orders = [p for p, k, _ in got if k == 'order']
    assert orders[0] == 100.0 and len(orders) == 6   # base + 5 add-ons
    assert orders == sorted(orders, reverse=True)    # a long adds lower
    assert abs(orders[1] - 99.0) < 1e-9              # first add-on at -1%
    assert [round(p, 6) for p, k, _ in got if k == 'target'] == [101.0]
    assert any(k == 'stop' for _, k, _ in got)
    short = levels(validate_config(_quick('dca_short', 'bold')), 100.0)
    assert [p for p, k, _ in short if k == 'order'][1] > 100.0


def spec_U8_an_unfinished_form_still_draws_and_offers_a_range():
    from panel.chart import form_levels
    lines, fill = form_levels({'venue': 'bybit', 'symbol': 'BTCUSDT'},
                              84905.14)
    assert fill == {'lower': 76415.0, 'upper': 93396.0}   # +-10% of price
    assert [k for _, k, _ in lines] == ['edge-lower', 'edge-upper']
    lines, fill = form_levels({'venue': 'bybit', 'symbol': 'BTCUSDT',
                               'lower': 80000.0}, 84905.14)
    assert fill == {} and lines == [(80000.0, 'edge-lower', 'lowest')]
    assert form_levels({'strategy': 'martingale', 'symbol': 'X'},
                       1.0) == ([], {})


def spec_U8_the_picture_puts_every_line_where_its_price_is():
    import re
    from panel.chart import BOTTOM, H, TOP, chart_svg, levels
    cfg = _grid_cfg()
    svg = chart_svg(_bars(), levels(cfg, 85900.0), 85900.0, drag=True)
    ymin, ymax = (float(re.search(f'data-{k}="([^"]+)"', svg).group(1))
                  for k in ('ymin', 'ymax'))
    assert ymin < 79800 and ymax > 90000             # bars AND lines fit

    def y_of(field):
        return float(re.search(
            rf'data-field="{field}"[^>]*translate\(0,([0-9.]+)\)',
            svg).group(1))

    def price_at(y):                                 # the script's own maths
        return ymax - (y - TOP) / (H - TOP - BOTTOM) * (ymax - ymin)
    assert abs(price_at(y_of('lower')) - 80000) < 10     # 0.1px rounding
    assert abs(price_at(y_of('upper')) - 90000) < 10
    assert y_of('upper') < y_of('lower')             # higher price, higher up
    assert svg.count('class="drag"') == 2            # only the two edges
    assert '85,900 now' in svg and '80,000 lowest' in svg
    still = chart_svg(_bars(), levels(cfg, 85900.0), 85900.0)
    assert 'class="drag"' not in still               # the summary: no handles
    assert 'no price history' in chart_svg([], [], None)


def spec_U8_the_form_carries_the_chart_and_the_server_redraws_it():
    base, d, close = _served_fleet()
    try:
        page = _call(base, '/setup?adv=grid')
        assert '<div id="chart">' in page and "fetch('/chart'" in page
        assert page.index('<div id="chart">') < page.index('</form>')
        empty = _call(base, '/chart', {'fleet': '0', 'strategy': 'grid'})
        assert 'once a coin is typed' in empty
        first = _call(base, '/chart', {'fleet': '0', 'strategy': 'grid',
                                       'symbol': 'btcusdt'})
        assert '<svg' in first and 'data-fill-lower="77310"' in first
        assert first.count('class="drag"') == 2      # a range is offered
        full = _call(base, '/chart', {
            'fleet': '0', 'strategy': 'grid', 'symbol': 'BTCUSDT',
            'side': 'long', 'market_type': 'linear', 'capital': '1000',
            'lower': '80000', 'upper': '90000', 'rungs': '11',
            'stop_on': '1', 'stop_watch': 'mark_price',
            'stop_level': '78000'})
        assert 'data-fill-lower' not in full         # the user's own range
        assert '78,000 stop loss' in full and 'now</text>' in full
        dca = _call(base, '/chart', {
            'fleet': '0', 'strategy': 'martingale', 'symbol': 'SOLUSDT',
            'side': 'long', 'market_type': 'linear', 'capital': '4000',
            'leverage': '2', 'base_order_size': '300',
            'safety_order_size': '300', 'order_size_multiplier': '1.5',
            'deviation_pct': '1', 'max_averaging_orders': '5',
            'take_profit_avg_pct': '1'})
        assert 'first order' in dca and 'take profit' in dca
        assert 'class="drag"' not in dca             # derived, not dragged
        bad = _call(base, '/chart', {'fleet': '0', 'strategy': 'grid',
                                     'symbol': 'BTCUSDT', 'capital': 'x'})
        assert 'no chart yet' in bad and 'Investment' in bad
    finally:
        close()


def spec_U8_the_summary_page_shows_the_bot_on_its_price():
    base, d, close = _served_fleet()
    try:
        page = _call(base, '/setup', {
            'how': 'quick', 'then': 'gates', 'fleet': '0',
            'preset': 'sideways', 'caution': 'balanced',
            'symbol': 'BTCUSDT', 'capital': '1000'})
        assert 'gates passed' in page and '<svg viewBox' in page
        assert 'lowest</text>' in page and 'class="drag"' not in page
        assert page.index('in plain words') < page.index('<svg viewBox')
    finally:
        close()


def spec_U5_the_chart_holds_no_key_and_its_script_computes_no_level():
    import inspect
    import panel.chart as ch
    src = inspect.getsource(ch)
    for word in ('os.environ', 'load_env', 'API_KEY', 'SECRET', 'signing'):
        assert word not in src, word
    js = ch.CHART_JS
    for word in ('rungs', 'spacing', 'Math.pow', 'leverage', 'eval(',
                 'http://', 'https://'):
        assert word not in js, word                  # drag and redraw only


def spec_U8_labels_of_close_lines_are_stacked_not_overprinted():
    """Seen in the first real picture: a stop 3 levels below the range and
    the follow-down trigger printed on top of the 'lowest' label."""
    import re
    from panel.chart import H, LABEL_GAP, chart_svg, levels
    cfg = _grid_cfg(lower=85000, upper=86000, rungs=41,
                    stop={'watch': 'mark_price', 'rungs_beyond': 3},
                    max_position_base='unbounded',
                    slide={'trigger_rungs': 2, 'max_rungs': 50,
                           'confirm_seconds': 900, 'direction': 'both'})
    svg = chart_svg(_bars(), levels(cfg, 85900.0), 85900.0)
    spots = sorted(
        float(ty) + float(dy) for ty, dy in re.findall(
            r'translate\(0,([0-9.]+)\)">(?:(?!</g>).)*?<text x="\d+" '
            r'y="([-0-9.]+)"', svg))
    assert len(spots) == 6            # lowest, highest, 2 triggers, stop, now
    gaps = [b - a for a, b in zip(spots, spots[1:])]
    assert min(gaps) >= LABEL_GAP - 0.2, gaps
    assert spots[-1] <= H


_SPEC = {'symbol': 'BTCUSDT', 'qty_step': 0.001, 'min_qty': 0.001,
         'price_tick': 0.1, 'min_notional': 5.0, 'settle_coin': 'USDT'}
_DCA = {'venue': 'bybit', 'market_type': 'linear', 'symbol': 'SOLUSDT',
        'side': 'long', 'strategy': 'martingale', 'capital': 4000,
        'leverage': 2, 'base_order_size': 300, 'safety_order_size': 300,
        'order_size_multiplier': 1.5, 'deviation_pct': 0.01,
        'max_averaging_orders': 5, 'take_profit_avg_pct': 0.01,
        'repeat': True}


def spec_U9_a_straight_move_fills_the_engines_own_orders():
    """The what-if's orders ARE the engine's plan at the mark, and its
    money is the adapter's: a fall of 3% from 84,905 passes the 84,000 and
    83,000 rungs of an 80-90k grid and no other."""
    from gridgremlin.adapters import LinearAdapter
    from panel.create import dry_ladder
    from panel.whatif import entries, whatif
    cfg, ad, mark = _grid_cfg(), LinearAdapter(_SPEC), 84905.14
    ladder = entries(cfg, ad, mark)
    assert sorted(ladder) == sorted(
        (o['price'], o['qty']) for o in dry_ladder(cfg, ad, mark))
    r = whatif(cfg, ad, ladder, mark, -0.03)
    assert (r['filled'], r['orders']) == (2, 5)
    assert abs(r['held'] - 0.010) < 1e-12 and abs(r['avg'] - 83500) < 1e-6
    assert abs(r['margin'] - 835.0 / 5) < 1e-9          # cost / leverage
    assert abs(r['pnl'] - (mark * 0.97 - 83500) * 0.010) < 1e-6
    assert abs(r['value'] - mark * 0.97 * 0.010) < 1e-6
    up = whatif(cfg, ad, ladder, mark, 0.03)             # away from the buys
    assert up['held'] == 0 and up['pnl'] == 0 and not up['outside']
    assert whatif(cfg, ad, ladder, mark, 0.10)['outside']


def spec_U9_a_short_is_the_mirror():
    from gridgremlin.adapters import LinearAdapter
    from panel.whatif import entries, whatif
    cfg, ad, mark = _grid_cfg(side='short'), LinearAdapter(_SPEC), 84905.14
    ladder = entries(cfg, ad, mark)
    assert whatif(cfg, ad, ladder, mark, -0.03)['held'] == 0
    r = whatif(cfg, ad, ladder, mark, 0.03)              # 85k, 86k, 87k
    assert r['filled'] == 3 and abs(r['avg'] - 86000) < 1e-6
    assert abs(r['pnl'] - (86000 - mark * 1.03) * 0.015) < 1e-6 > r['pnl']


def spec_U9_a_stop_on_the_way_ends_the_move_there():
    """The move does not run past a price stop: the loss is the loss AT
    the stop, and nothing is held after it."""
    from gridgremlin.adapters import LinearAdapter
    from panel.whatif import entries, whatif, words
    cfg = _grid_cfg(stop={'watch': 'mark_price', 'level': 78000})
    ad, mark = LinearAdapter(_SPEC), 84905.14
    ladder = entries(cfg, ad, mark)
    r = whatif(cfg, ad, ladder, mark, -0.10)             # to 76,415
    assert r['stopped_at'] == 78000 and r['held'] == 0 and r['margin'] == 0
    assert abs(r['pnl'] - (78000 - 82000) * 0.025) < 1e-6   # -100
    assert 'stop loss fires at 78,000' in words(cfg, r)
    assert whatif(cfg, ad, ladder, mark, -0.05)['stopped_at'] is None
    slid = _grid_cfg(stop={'watch': 'mark_price', 'rungs_beyond': 3},
                     slide={'trigger_rungs': 2, 'max_rungs': 50,
                            'confirm_seconds': 900})
    r = whatif(slid, ad, entries(slid, ad, mark), mark, -0.10)
    assert r['stopped_at'] == 77000                      # X8's level
    r = whatif(slid, ad, entries(slid, ad, mark), mark, 0.10)
    assert r['follows'] == 'up' and 'follows the price up' in words(slid, r)


def spec_U9_a_dca_bot_adds_on_the_way_and_takes_profit_the_other_way():
    from gridgremlin.adapters import LinearAdapter
    from panel.whatif import entries, whatif, words
    cfg, ad = validate_config(dict(_DCA)), LinearAdapter(_SPEC)
    ladder = entries(cfg, ad, 100.0)
    assert len(ladder) == 6 and ladder[0][0] == 100.0    # first at the mark
    r = whatif(cfg, ad, ladder, 100.0, -0.03)   # 99, 98, 96.5 added; 94 not
    assert r['filled'] == 4
    assert abs(r['cost'] - (300 + 300 + 450 + 675)) < 1e-6
    assert abs(r['margin'] - r['cost'] / 2) < 1e-9
    deep = whatif(cfg, ad, ladder, 100.0, -0.30)
    assert deep['filled'] == 6 and deep['pnl'] < r['pnl'] < 0
    flat = whatif(cfg, ad, ladder, 100.0, 0.005)         # short of target
    assert flat['filled'] == 1 and flat['took_profit_at'] is None
    won = whatif(cfg, ad, ladder, 100.0, 0.03)
    assert abs(won['took_profit_at'] - 101.0) < 1e-9 and won['held'] == 0
    assert abs(won['pnl'] - 3.0) < 1e-9                  # 300 x 1%
    assert 'starts again' in words(cfg, won)
    steps = validate_config(dict(
        {k: v for k, v in _DCA.items() if k != 'take_profit_avg_pct'},
        take_profit_tranches=[{'at_avg_pct': 0.01, 'share': 0.5},
                              {'at_avg_pct': 0.02, 'share': 0.5}]))
    half = whatif(steps, ad, entries(steps, ad, 100.0), 100.0, 0.015)
    assert abs(half['held'] - 1.5) < 1e-9                # half still held
    assert abs(half['pnl'] - (1.5 + 1.5 * 1.5)) < 1e-9   # sold + open


def spec_U9_an_inverse_market_is_counted_in_its_own_money():
    """Coin-settled contracts: the gain or loss goes through the adapter
    (A4), never price x quantity."""
    from gridgremlin.adapters import InverseAdapter
    from panel.whatif import entries, whatif
    cfg = _grid_cfg(market_type='inverse', symbol='BTCUSD')
    ad = InverseAdapter(dict(_SPEC, symbol='BTCUSD', qty_step=1, min_qty=1,
                             settle_coin='BTC'))
    mark = 84905.14
    ladder = entries(cfg, ad, mark)
    r = whatif(cfg, ad, ladder, mark, -0.03)
    end = mark * 0.97
    want = sum(ad.pnl_to_usd(ad.realised_pnl(p, end, q), end)
               for p, q in ladder if p >= end)
    assert r['filled'] == 2 and abs(r['pnl'] - want) < 1e-9 > want
    assert abs(r['cost'] - r['held']) < 1e-9             # contracts are USD


def spec_U9_the_summary_page_carries_the_slider_and_the_server_answers():
    import html as _html
    import re
    base, d, close = _served_fleet()
    try:
        page = _call(base, '/setup', {
            'how': 'quick', 'then': 'gates', 'fleet': '0',
            'preset': 'sideways', 'caution': 'balanced',
            'symbol': 'BTCUSDT', 'capital': '1000'})
        assert 'what if the price moves' in page
        assert '<input type="range" name="move"' in page
        assert "fetch('/whatif'" in page and 'Not a forecast' in page
        assert page.count('<td>-30%</td>') == 1 and '<td>+30%</td>' in page
        assert page.index('<svg viewBox') < page.index('id="whatif"') \
            < page.index('the change to the file')
        assert 'If the price falls 10%' in page          # a long opens there
        bot = _html.unescape(re.search(
            r'id="whatif".*?name="bot_json" value="([^"]*)"', page,
            re.S).group(1))
        mark = re.search(r'name="mark" value="([^"]*)"', page).group(1)
        got = _call(base, '/whatif', {'fleet': '0', 'bot_json': bot,
                                      'mark': mark, 'move': '-4'})
        assert got.startswith('<p class="say">If the price falls 4% to')
        assert 'orders filled' in got
        for bad in ({'move': '80'}, {'bot_json': '{"symbol": 1}'},
                    {'mark': 'x'}):
            got = _call(base, '/whatif', dict(
                {'fleet': '0', 'bot_json': bot, 'mark': mark, 'move': '5'},
                **bad))
            assert got.startswith('<p class="dim">no answer:'), bad
    finally:
        close()


def spec_U5_the_whatif_holds_no_key_and_its_script_computes_no_money():
    import inspect
    import panel.whatif as wi
    src = inspect.getsource(wi)
    for word in ('os.environ', 'load_env', 'API_KEY', 'SECRET', 'signing'):
        assert word not in src, word
    for word in ('rungs', 'leverage', 'Math.', 'eval(', 'http://',
                 'https://', '*', 'parseFloat'):
        assert word not in wi.WHATIF_JS, word            # ask and show only


def spec_U11_every_form_page_has_the_way_back():
    """Owner, 2026-10-02: "no way to back out of the create bot screen once
    started". Every page off the main one opens with the link home."""
    base, d, close = _served_fleet()
    try:
        pages = [_call(base, '/setup'), _call(base, '/setup?adv=grid'),
                 _call(base, '/setup?adv=martingale'),
                 _call(base, '/edit?fleet=0&bot=linETHUSDTl'),
                 _call(base, '/setup', {
                     'how': 'quick', 'then': 'gates', 'fleet': '0',
                     'preset': 'sideways', 'caution': 'balanced',
                     'symbol': 'BTCUSDT', 'capital': '1000'}),
                 _call(base, '/setup', {'how': 'quick', 'then': 'gates',
                                        'fleet': '0', 'preset': 'sideways',
                                        'symbol': 'BTCUSDT'})]
        for page in pages:
            assert '<a href="/">back to your bots</a>' in page
            assert 'history.back()' in page                       # U21
            assert page.index('back to your bots') < page.index('<h1') \
                if '<h1' in page else True
        assert 'class="refusal"' in pages[-1]          # and a quick refusal
        assert pages[-1].index('class="refusal"') < pages[-1].index(
            'set up a bot')
    finally:
        close()


_DCA_FORM = {'strategy': 'martingale', 'symbol': 'solusdt', 'side': 'long',
             'capital': '4000', 'leverage': '2', 'base_order_size': '300',
             'safety_order_size': '300', 'order_size_multiplier': '1.5',
             'deviation_pct': '1', 'max_averaging_orders': '5',
             'take_profit_avg_pct': '1', 'repeat': '1'}


def spec_D41_the_form_stamps_the_moment_and_an_edit_keeps_it():
    """3Commas counts from when the setting is switched on. The form
    stamps that moment; reopening the bot carries it, so an edit does not
    restart the count — only clearing the box does."""
    import re
    row = bot_from_form(dict(_DCA_FORM, max_rounds='5'), 'bybit')
    assert row['max_rounds'] == 5
    assert re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ',
                        row['max_rounds_since'])
    assert validate_config(dict(row, market_type='linear'))['max_rounds'] == 5
    kept = bot_from_form(dict(_DCA_FORM, max_rounds='5',
                              max_rounds_since='2026-10-02T14:30:00Z'),
                         'bybit')
    assert kept['max_rounds_since'] == '2026-10-02T14:30:00Z'
    assert form_from_bot(kept)['max_rounds_since'] == '2026-10-02T14:30:00Z'
    assert 'max_rounds_since' not in bot_from_form(dict(_DCA_FORM), 'bybit')


def spec_U4_the_sentence_says_the_stops_opt_ins_and_the_round_limit():
    row = bot_from_form(dict(
        _DCA_FORM, stop_on='1', stop_watch='mark_price', stop_from_base='20',
        stop_action='end_round', stop_confirm='30',
        stop_cooldown_seconds='3600', max_rounds='5',
        max_rounds_since='2026-10-02T14:30:00Z'), 'bybit')
    assert row['stop'] == {'watch': 'mark_price', 'from_base_pct': 0.2,
                           'action': 'end_round', 'confirm_seconds': 30.0}
    says = sentence(validate_config(dict(row, market_type='linear')))
    assert ("If the price falls 20.00% from a round's first order and "
            'stays there 30 seconds it closes that round at a loss and '
            'starts a new one after waiting 3600 seconds.') in says
    assert ('After 5 rounds, counted from 2026-10-02T14:30:00Z, it '
            'finishes the round it is in and stops for good.') in says
    plain = sentence(validate_config(dict(bot_from_form(dict(
        _DCA_FORM, stop_on='1', stop_watch='mark_price',
        stop_from_base='20'), 'bybit'), market_type='linear')))
    assert 'cancels its orders and stops for good.' in plain   # D1 default


def spec_U9_the_chart_and_the_whatif_follow_the_percent_stop():
    from gridgremlin.adapters import LinearAdapter
    from panel.chart import levels
    from panel.whatif import entries, whatif, words
    row = dict(_DCA, stop={'watch': 'mark_price', 'from_base_pct': 0.2,
                           'action': 'end_round'})
    cfg, ad = validate_config(row), LinearAdapter(_SPEC)
    assert (80.0, 'stop', 'stop loss') in levels(cfg, 100.0)
    r = whatif(cfg, ad, entries(cfg, ad, 100.0), 100.0, -0.30)
    assert r['stopped_at'] == 80.0 and r['held'] == 0
    assert words(cfg, r).endswith('and starts a new round.')


def spec_U4_the_sentence_says_leave_position_and_the_hold_limit():
    row = bot_from_form(dict(
        _DCA_FORM, stop_on='1', stop_watch='mark_price', stop_from_base='20',
        stop_action='leave_position', max_hold_seconds='7200'), 'bybit')
    cfg = validate_config(dict(row, market_type='linear'))
    says = sentence(cfg)
    assert ('it cancels its orders and stops for good, but LEAVES its '
            'position open, unprotected, for you to manage.') in says
    assert ('A round still open after 2 hours is closed at the market '
            'price, in profit or loss.') in says
    grid = advanced_page('grid', {}, ['a.json'])
    assert '<option>leave_position</option>' in grid
    assert '<option>end_round</option>' not in grid    # a grid has no round


def spec_U9_the_whatif_keeps_a_left_position_moving():
    from gridgremlin.adapters import LinearAdapter
    from panel.whatif import entries, whatif, words
    row = dict(_DCA, stop={'watch': 'mark_price', 'from_base_pct': 0.2,
                           'action': 'leave_position'})
    cfg, ad = validate_config(row), LinearAdapter(_SPEC)
    ladder = entries(cfg, ad, 100.0)
    r = whatif(cfg, ad, ladder, 100.0, -0.30)
    closed = whatif(validate_config(dict(_DCA, stop={
        'watch': 'mark_price', 'from_base_pct': 0.2})), ad, ladder, 100.0,
        -0.30)
    assert r['stopped_at'] == 80.0 and r['held'] > 0
    assert r['pnl'] < closed['pnl'] < 0            # valued at 70, not at 80
    assert 'the position stays open' in words(cfg, r)


def spec_X14_the_form_offers_the_loss_limit_on_both_kinds_and_stamps_it():
    import re
    for strategy in ('grid', 'martingale'):
        page = advanced_page(strategy, {}, ['a.json'])
        assert 'Most this bot may lose' in page and 'name="max_loss"' in page
    row = bot_from_form(dict(_DCA_FORM, max_loss='250'), 'bybit')
    assert row['max_loss'] == 250.0
    assert re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ',
                        row['max_loss_since'])
    kept = bot_from_form(dict(_DCA_FORM, max_loss='250',
                              max_loss_since='2026-10-02T14:30:00Z'), 'bybit')
    assert kept['max_loss_since'] == '2026-10-02T14:30:00Z'
    says = sentence(validate_config(dict(kept, market_type='linear')))
    assert ('If it is ever down 250 in total, counting closed and open '
            'losses since 2026-10-02T14:30:00Z, it closes its position and '
            'stops for good.') in says
    grid = sentence(_grid_cfg(max_loss=100,
                              max_loss_since='2026-10-02T14:30:00Z'))
    assert 'If it is ever down 100 in total' in grid


def spec_X14_the_quick_setup_offers_the_loss_limit_and_blank_is_none():
    assert 'name="max_loss"' in quick_page(['a.json'])
    plain = _quick('sideways', 'balanced')
    assert 'max_loss' not in plain and 'max_loss_since' not in plain
    for preset in ('sideways', 'dca_long'):
        row = quick_bot({'preset': preset, 'caution': 'balanced',
                         'symbol': 'BTCUSDT', 'capital': '1000',
                         'max_loss': '150'}, 'bybit', 84905.14)
        cfg = validate_config(row)
        assert cfg['max_loss'] == 150.0 and cfg['max_loss_since_ms'] > 0
    try:
        quick_bot({'preset': 'sideways', 'caution': 'balanced',
                   'symbol': 'BTCUSDT', 'capital': '1000',
                   'max_loss': 'a lot'}, 'bybit', 84905.14)
    except ValueError as e:
        assert 'Most this bot may lose' in str(e)
    else:
        raise AssertionError('accepted')


def spec_X14_the_whatif_ends_the_move_where_the_loss_reaches_the_limit():
    """An 80-90k grid from 84,905, limit 60. By 81,000 it holds four lots
    of 0.005 from 82,500 on average: down 30 at 81,000, 50 at 80,000 with
    the fifth lot in, and 60 at 79,600."""
    from gridgremlin.adapters import LinearAdapter
    from panel.whatif import entries, table, whatif, words
    cfg = _grid_cfg(max_loss=60, max_loss_since='2026-10-02T14:30:00Z')
    ad, mark = LinearAdapter(_SPEC), 84905.14
    ladder = entries(cfg, ad, mark)
    near = whatif(cfg, ad, ladder, mark, -0.05)        # 80,660: down ~37
    assert near['loss_limit_at'] is None and near['held'] > 0
    r = whatif(cfg, ad, ladder, mark, -0.10)
    assert abs(r['loss_limit_at'] - 79600.0) < 1.0
    assert r['held'] == 0 and r['pnl'] == -60 and r['filled'] == 5
    assert 'its loss limit of 60 is reached at 79,600' in words(cfg, r)
    assert 'loss limit at 79,600' in table(cfg, ad, ladder, mark)
    stopped = _grid_cfg(max_loss=500, max_loss_since='2026-10-02T14:30:00Z',
                        stop={'watch': 'mark_price', 'level': 78000})
    r = whatif(stopped, ad, entries(stopped, ad, mark), mark, -0.10)
    assert r['stopped_at'] == 78000 and r['loss_limit_at'] is None


def spec_U14_the_summary_offers_a_rehearsal_of_the_bot_as_configured():
    """One click from the summary: the whole row rides along, so a DCA bot
    and every setting of a grid are rehearsed, not a simplified draft."""
    import html as _html
    import re
    base, d, close = _served_fleet()
    try:
        page = _call(base, '/setup', dict(
            _DCA_FORM, how='advanced', fleet='0', market_type='linear',
            max_hold_seconds='7200'))
        assert 'gates passed' in page
        m = re.search(r'action="/rehearse">.*?name="bot_json" value="([^"]*)"'
                      r'.*?name="days"', page, re.S)
        row = json.loads(_html.unescape(m.group(1)))
        assert row['strategy'] == 'martingale'
        assert row['max_hold_seconds'] == 7200.0       # every setting rides
        assert 'rehearse this bot over the last' in page
        refused = _call(base, '/rehearse', {'bot_json': m.group(1),
                                            'days': '400'})
        assert '90 at most' in refused and 'class="refusal"' in refused
        assert 'rehearse this bot over the last' in refused    # form kept
        assert 'back to your bots' in refused
    finally:
        close()


def spec_U14_a_dca_rehearsal_reads_in_the_rounds_own_words():
    from gridgremlin.adapters import LinearAdapter
    from gridgremlin.backtest_cli import rehearse
    from panel.server import verdict
    cfg = validate_config(dict(_DCA, max_averaging_orders=5))
    bars = [{'t': i * 300_000, 'o': o, 'h': h, 'l': l, 'c': c}
            for i, (o, h, l, c) in enumerate(
                [(100, 100.1, 99.9, 100), (100, 100, 97.8, 98),
                 (98, 100.5, 97.9, 100.4)])]
    out = rehearse(cfg, bars, LinearAdapter(_SPEC), bar_minutes=5)
    page = verdict(cfg, out, bot_json='{}', days='3')
    for words in ('SOLUSDT long DCA — 3 candles of 5 min',
                  'profit from closed rounds', 'rounds completed',
                  'add-on orders filled', 'deepest add-on reached',
                  ' of 5</td>', 'stops fired', 'how it ended',
                  'still running at the end of the window',
                  'the real bot, replayed against these candles'):
        assert words in page, words
    assert 'grid profit' not in page and 'value="3"' in page


def spec_U17_the_apply_box_is_in_reach_and_the_file_folds_away():
    """Owner, 2026-10-03: "a lazy user wouldnt think to scroll so far".
    The apply box sits under the summary; the diff and the dry-run orders
    are folded; the buttons say they are a step."""
    base, d, close = _served_fleet()
    try:
        page = _call(base, '/setup', {
            'how': 'quick', 'then': 'gates', 'fleet': '0',
            'preset': 'sideways', 'caution': 'balanced',
            'symbol': 'BTCUSDT', 'capital': '1000'})
        assert page.index('action="/apply"') < page.index(
            '<details><summary>the change to the file</summary>')
        assert '<details><summary>the orders it would place</summary>' in page
        assert '<details open>' not in page[page.index('action="/apply"'):]
        assert '<button>create this bot</button>' in page
        assert 'To <b>' not in page and '<b>To create this bot</b>' in page
        edit = _call(base, '/edit?fleet=0&bot=linETHUSDTl')
        assert 'Next: review the bot &rarr;</button>' in edit
        quick = _call(base, '/setup')
        assert 'Next: review the bot &rarr;' in quick
        assert 'class="quiet">Open in the advanced form &rarr;</button>' \
            in quick
        assert 'show me the summary' not in quick + edit + page
    finally:
        close()


# --- U19: the panel writes the file a hand would write ------------------------

def spec_U19_the_panel_writes_the_repos_own_format():
    """The committed configs ARE the format: every shipped file comes back
    byte-identical through the panel's one writer, so a panel edit on the
    box is a plain diff against the repo and nothing else."""
    from panel.create import dump_config
    for path in sorted(glob.glob(os.path.join(CONFIGS, '*.json'))):
        text = open(path, encoding='utf-8').read()
        assert dump_config(json.loads(text)) == text, os.path.basename(path)


def spec_U19_an_edit_that_changes_nothing_writes_the_file_it_read():
    """Every shipped row, opened in the advanced form and applied untouched
    (as the panel's edit door does: form -> row, notes carried, watcher
    limit as it was), writes the same bytes. Whole numbers stay whole, the
    default venue stays unwritten, the row keeps its order."""
    from panel.create import dump_config, edit_proposal
    for path in sorted(glob.glob(os.path.join(CONFIGS, 'fleet*.json'))):
        text = open(path, encoding='utf-8').read()
        fleet = json.loads(text)
        wd_text, wd = '', {}            # the parked spot fleet names none
        if fleet.get('watchdog'):
            wd_path = os.path.join(CONFIGS, '..', fleet['watchdog'])
            wd_text = open(wd_path, encoding='utf-8').read()
            wd = json.loads(wd_text)
        venue = fleet['bots'][0].get('venue', 'bybit')
        for old in fleet['bots']:
            botid = make_botid(old['market_type'], old['symbol'], old['side'])
            bot = bot_from_form(form_from_bot(old), venue)
            bot.update({k: v for k, v in old.items() if k.startswith('_')})
            wmax = (wd.get('positions') or {}).get(botid, {}).get('max')
            _, f2, w2 = edit_proposal(fleet, wd, botid, bot, wmax)
            assert dump_config(f2) == text, (os.path.basename(path), botid)
            if wd_text:
                assert dump_config(w2) == wd_text, (os.path.basename(path),
                                                    botid)


def spec_U19_a_typed_whole_number_is_written_whole():
    form = {'strategy': 'grid', 'market_type': 'linear', 'symbol': 'solusdt',
            'side': 'long', 'capital': '3,000', 'leverage': '12',
            'lower': '112.2', 'upper': '126.8', 'rungs': '31',
            'max_position_base': '40'}
    bot = bot_from_form(form, 'bybit')
    assert bot['capital'] == 3000 and type(bot['capital']) is int
    assert bot['leverage'] == 12 and type(bot['leverage']) is int
    assert bot['lower'] == 112.2 and type(bot['lower']) is float
    assert type(bot['max_position_base']) is int
    assert 'venue' not in bot                       # the engine's default
    assert bot_from_form(dict(form, leverage='12.5'), 'bybit')['leverage'] == 12.5
    assert bot_from_form(form, 'hyperliquid')['venue'] == 'hyperliquid'


def spec_U22_every_cards_numbers_open_or_close_at_once():
    """Owner 2026-10-03: "can we have a show all button … open/close all the
    numbers". The cards page carries show all · hide all; the table and the
    export do not (nothing folds there)."""
    from panel.server import render
    live = render([], table=False)
    assert '<h3>numbers</h3><a href="javascript:ggAll(true)">show all</a>' in live
    assert 'ggAll(false)">hide all</a>' in live
    assert 'window.ggAll=function' in live            # the script defines it
    assert 'ggAll(' not in render([], table=True)     # the table folds nothing
    assert 'ggAll(' not in render([], static='2026-10-03T00:00Z')


def spec_U23_the_sweep_fits_the_box_and_says_it_is_working():
    """Owner 2026-10-04: a 90-day sweep outran the page and looked hung;
    repeated presses stacked three beside the live fleets. The sweep is 14
    replays over a fixed 14 days (T9), the subprocess runs under the fleets'
    priority, and the buttons say how long and "press once"."""
    from gridgremlin.backtest_cli import WINDOWS_DAYS
    from panel.server import FORM
    from panel.server import rehearse_bot_form
    assert WINDOWS_DAYS == 14
    assert 'about six minutes while the fleets run; press once' in FORM
    assert 'sweeping, about six minutes' in FORM
    bot_form = rehearse_bot_form('{}')
    assert 'about six minutes while the fleets run; press once' in bot_form
    import inspect
    from panel.server import Handler
    assert "'nice', '-n', '10'" in inspect.getsource(Handler._rehearsal_runner)


# --- U24: the size in the unit you think in ----------------------------------

def spec_U24_the_size_in_your_unit_becomes_collateral():
    from panel.setup import capital_from, resolve_size
    assert capital_from(1000.0, 'collateral', 5) == 1000.0
    assert capital_from(5000.0, 'notional', 5) == 1000.0
    assert abs(capital_from(2.0, 'coins', 4, mark=60000.0) - 30000.0) < 1e-9
    try:
        capital_from(2.0, 'coins', 4)                 # no price: refused
        assert False
    except ValueError as e:
        assert 'coins' in str(e) and 'price' in str(e)
    # quick setup: the preset's leverage does the arithmetic
    bot = quick_bot({'preset': 'sideways', 'caution': 'balanced',
                     'symbol': 'BTCUSDT', 'capital': '5000',
                     'size_unit': 'notional'}, 'bybit', 60000.0)
    assert bot['leverage'] == 5 and abs(bot['capital'] - 1000.0) < 1e-6
    bot = quick_bot({'preset': 'dca_long', 'caution': 'bold',
                     'symbol': 'BTCUSDT', 'capital': '0.1',
                     'size_unit': 'coins'}, 'bybit', 60000.0)
    assert bot['leverage'] == 5 and abs(bot['capital'] - 1200.0) < 1e-6
    # advanced form: the typed leverage, the price only when needed
    asked = []
    f = resolve_size({'capital': '0.5', 'size_unit': 'coins', 'leverage': '10'},
                     lambda: asked.append(1) or 50000.0)
    assert f['capital'] == '2500' and f['size_unit'] == 'collateral' and asked
    f = resolve_size({'capital': '3000', 'size_unit': 'notional',
                      'leverage': '3'}, lambda: 1 / 0)
    assert f['capital'] == '1000'
    f = resolve_size({'capital': '700', 'size_unit': 'collateral'}, lambda: 1 / 0)
    assert f['capital'] == '700'
    s = sentence(validate_config({'market_type': 'linear', 'symbol': 'BTCUSDT',
                                  'side': 'long', 'capital': 1000,
                                  'leverage': 5, 'lower': 50000,
                                  'upper': 70000, 'rungs': 11}), mark=60000.0)
    assert 'about 0.08333 coins' in s
    assert 'size_unit' in quick_page(['f.json'])
    assert 'size_unit' in advanced_page('grid', {}, ['f.json'])


# --- U25: the venue's markets as a list, typing still works -----------------

def spec_U25_the_coin_list_is_the_venues_own_and_optional():
    from panel.create import parse_symbols
    rows = [{'symbol': 'BTCUSDT', 'status': 'Trading', 'quoteCoin': 'USDT'},
            {'symbol': 'ETHPERP', 'status': 'Trading', 'quoteCoin': 'USDC'},
            {'symbol': 'OLDUSDT', 'status': 'Closed', 'quoteCoin': 'USDT'},
            {'symbol': 'BTCUSD', 'status': 'Trading', 'quoteCoin': 'USD'}]
    assert parse_symbols(rows) == ['BTCUSDT', 'ETHPERP']
    page = quick_page(['f.json'], symbols=('BTCUSDT', 'SOLUSDT'))
    assert '<datalist id="coins">' in page and 'value="SOLUSDT"' in page
    assert 'list="coins"' in page
    assert '<datalist' not in quick_page(['f.json'])           # unreachable
    adv = advanced_page('grid', {}, ['f.json'], symbols=('BTCUSDT',))
    assert '<datalist id="coins">' in adv and 'list="coins"' in adv


# --- U26: a rehearsal is a job; the page says what the engine is doing -------

def spec_U26_the_sweep_reports_each_replay_and_the_draft_door_relays_it():
    from gridgremlin.backtest_cli import sweep_rungs
    from spec_backtest import ADAPTER as SAW_ADAPTER, _saw
    said = []
    raw = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
           'capital': 1000.0, 'leverage': 10, 'upper': 70000.0,
           'lower': 50000.0, 'rungs': 21, 'spacing_type': 'fixed'}
    fracs = []
    sweep_rungs(raw, _saw(50000.0, 70000.0, 2, 10), SAW_ADAPTER,
                candidates=[5, 9, 13],
                progress=lambda t, f=None: (said.append(t), fracs.append(f)))
    assert said[0] == 'replay 1 of about 7' and len(said) >= 3
    assert all(s.startswith('replay ') for s in said)
    assert fracs[0] is not None and 0 < fracs[0] <= 1 and fracs == sorted(fracs)


def spec_U26_the_page_answers_at_once_and_refreshes_until_the_verdict():
    """Owner 2026-10-04: a five-minute sweep looked hung. The POST now
    starts a job and redirects; the job page carries a refresh tag and the
    engine's own progress words; when the job is done the same address is
    the verdict. The runner is swapped for a fake: no subprocess here."""
    import threading
    import urllib.parse
    import urllib.request
    from panel.server import Handler
    gate = threading.Event()

    def fake(job):
        job['progress'] = 'replay 3 of about 14'
        gate.wait(5)
        job['result'] = {'refused': 'fake verdict for the spec'}
        job['done'] = True
    saved = Handler._rehearsal_runner
    Handler._rehearsal_runner = staticmethod(fake)
    base, d, close = _served_fleet()
    try:
        data = urllib.parse.urlencode({'gg': '1', 'symbol': 'BTCUSDT',
                                       'side': 'long', 'lower': '80000',
                                       'upper': '90000', 'rungs': '21',
                                       'capital': '1000', 'days': '7',
                                       'optimize': '1'}).encode()

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        opener = urllib.request.build_opener(NoRedirect)
        req = urllib.request.Request(base + '/rehearse', data=data,
                                     headers={'Cookie': 'gg=tok'})
        try:
            opener.open(req)
            assert False, 'expected a redirect'
        except urllib.error.HTTPError as e:
            assert e.code == 303
            where = e.headers['Location']
        assert where.startswith('/rehearse?job=')
        page = _call(base, where)
        assert 'http-equiv="refresh"' in page and 'working' in page
        assert 'replay 3 of about 14' in page and 'compare grid counts' in page
        gate.set()
        import time as _t
        for _ in range(50):
            page = _call(base, where)
            if 'refresh' not in page:
                break
            _t.sleep(0.05)
        assert 'fake verdict for the spec' in page       # the same address
        assert 'class="refusal"' in page
        assert 'no such rehearsal' in _call(base, '/rehearse?job=nope')
    finally:
        Handler._rehearsal_runner = saved
        close()


# --- U27: grids and gap show each other -----------------------------------

def spec_U27_grids_and_gap_are_one_question_shown_both_ways():
    page = advanced_page('grid', {}, ['f.json'])
    # the formulas the page runs (the Python mirrors nothing called went,
    # audit 2026-10-05): percent = the rung ratio, fixed = the step
    assert 'Math.pow(u/l,1/(r-1))-1' in page and '(u-l)/(r-1)/l*100' in page
    assert 'Math.log(u/l)/Math.log(1+g/100)+1' in page
    assert 'id="rungs_hint"' in page and 'id="spacing_pct_hint"' in page
    assert "addEventListener('input',show)" in page           # live, both ways


def spec_U38_the_other_box_fills_itself_and_is_not_submitted():
    """Owner 2026-10-04: Pionex and Bybit fill the gap when you type the
    grid count, and the other way round. The typed one governs; the other
    is written into its box, reads dim and says where it came from, and is
    dropped on submit — the engine still gets exactly one of the two (the
    config refuses both), and with no script both boxes stay free."""
    page = advanced_page('grid', {}, ['f.json'])
    assert "governs='rungs'" in page and "governs='spacing_pct'" in page
    assert "gp.value=gap.toFixed(2)" in page and "ru.value=n" in page
    assert "'\\u2190 from the '" in page                    # says its source
    assert "addEventListener('submit'" in page and "disabled=true" in page
    from panel.server import CSS
    assert 'input.derived{color:var(--dim);font-style:italic}' in CSS
    # a loaded row with the count governs; one with the gap governs the other
    assert "(ru.value&&!gp.value)?'rungs':(gp.value&&!ru.value)?'spacing_pct'" in page


def spec_T9_the_two_window_page_says_what_the_numbers_mean():
    from panel.server import windows_html
    row = lambda n, net: {'rungs': n, 'gap_pct': 1.0, 'net': net, 'total': net,
                          'trips': 3, 'fees': 0.1, 'fee_share': 0.1,
                          'max_drawdown': 2.0}
    sweep = lambda best, nets: {'best': best, 'plateau': [best, best],
                                'rows': [row(n, v) for n, v in nets.items()]}
    out = {'windows': {'14d': sweep(13, {5: 1.0, 13: 9.0, 21: 4.0}),
                       '7d': sweep(21, {5: 0.5, 13: 3.0, 21: 5.0}),
                       'older7d': sweep(13, {5: 0.5, 13: 6.0, 21: -1.0})},
           'visited': {'7d': 48.0, '14d': 71.0},
           'oos': {'fit_rungs': 13, 'newer_best': 21, 'fit_net_newer': 3.0,
                   'newer_best_net': 5.0, 'holds': False},
           'dropped': [], 'draft_rungs': 31, 'bars': 4032, 'bar_minutes': 5}
    draft = {'symbol': 'SOLUSDT', 'side': 'long', 'lower': 100, 'upper': 120}
    page = windows_html(draft, out)
    assert '<b>13 grids</b> made the most' in page and 'the row has 31' in page
    assert 'fitting noise' in page and '48%' in page and '71%' in page
    assert 'a grid earns only where the price goes' in page
    assert '<th>net 7d</th>' in page and '<th>net 14d</th>' in page
    out['oos'].update(fit_net_newer=4.8, holds=True)
    assert 'holds up' in windows_html(draft, out)


def spec_U28_the_advanced_door_on_the_quick_page_needs_nothing_filled():
    """Owner 2026-10-04: "some users may not realise that all details in the
    quick section need to be filled in order to meet the requirements of
    opening the advanced panel." They do not, now: the button opens the
    advanced form with whatever was typed carried over, blanks included."""
    base, d, close = _served_fleet()
    try:
        page = _call(base, '/setup', {'how': 'quick', 'then': 'advanced',
                                      'fleet': '0', 'preset': 'falling',
                                      'caution': 'balanced'})
        assert 'class="refusal"' not in page
        assert 'name="rungs"' in page                        # the advanced form
        assert 'with what you typed carried over' in page
        assert '<option selected>short</option>' in page     # the preset's side
        page = _call(base, '/setup', {'how': 'quick', 'then': 'advanced',
                                      'fleet': '0', 'preset': 'dca_long',
                                      'symbol': 'SOLUSDT', 'capital': ''})
        assert 'name="deviation_pct"' in page and 'value="SOLUSDT"' in page
        assert 'nothing above needs filling' in quick_page(['f.json'])
    finally:
        close()


# --- U29: leaving the page stops the run; a bar over the words -----------------

def spec_U29_leaving_the_page_stops_the_run_and_the_page_says_so():
    from panel.server import Handler, CSS

    class Proc:
        def __init__(self):
            self.killed = False
        def poll(self):
            return 1 if self.killed else None
        def kill(self):
            self.killed = True
    job = {'seen': 100.0}
    clock = {'t': 100.0}
    ended = Handler._leave_watch(job, Proc(), clock=lambda: clock['t'],
                                 sleep=lambda s: clock.__setitem__(
                                     't', clock['t'] + 5.0))
    assert ended is True and job['cancelled'] is True     # 15 s unseen
    p2, job2 = Proc(), {'seen': 100.0}
    clock['t'] = 100.0
    def sleep_and_finish(s):
        clock['t'] += 2.0
        job2['seen'] = clock['t']                          # kept refreshing
        if clock['t'] > 110:
            p2.killed = True                               # it finished
    assert Handler._leave_watch(job2, p2, clock=lambda: clock['t'],
                                sleep=sleep_and_finish) is False
    assert not job2.get('cancelled')
    # the working page: a bar from the fraction, the heartbeat, the words
    import threading
    gate = threading.Event()
    def fake(job):
        job['progress'] = 'window 7d: replay 3 of about 14'
        job['frac'] = 0.42
        gate.wait(5)
        job['result'] = {'refused': 'stopped — you left the page for more '
                                    'than ten seconds, so the run was ended; '
                                    'run it again when you can stay'}
        job['done'] = True
    saved = Handler._rehearsal_runner
    Handler._rehearsal_runner = staticmethod(fake)
    base, d, close = _served_fleet()
    try:
        import urllib.parse, urllib.request
        data = urllib.parse.urlencode({'gg': '1', 'symbol': 'BTCUSDT',
                                       'side': 'long', 'lower': '80000',
                                       'upper': '90000', 'rungs': '21',
                                       'capital': '1000', 'days': '7',
                                       'optimize': '1'}).encode()
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        req = urllib.request.Request(base + '/rehearse', data=data,
                                     headers={'Cookie': 'gg=tok'})
        try:
            urllib.request.build_opener(NoRedirect).open(req)
        except urllib.error.HTTPError as e:
            where = e.headers['Location']
        import time as _t
        page = _call(base, where)
        for _ in range(40):
            if '42%' in page:
                break
            _t.sleep(0.05); page = _call(base, where)
        assert '<div class="bar"' in page and 'width:42%' in page
        assert 'Leaving this page stops the run' in page
        job_id = where.split('job=')[1]
        assert abs(Handler._jobs[job_id]['seen'] - _t.time()) < 5   # heartbeat
        gate.set()
        for _ in range(50):
            page = _call(base, where)
            if 'refresh' not in page:
                break
            _t.sleep(0.05)
        assert 'you left the page' in page and 'class="refusal"' in page
    finally:
        Handler._rehearsal_runner = saved
        close()
    assert 'button.quiet{background:var(--accent-soft)' in CSS   # illuminated
    assert '.bar div{height:100%;background:var(--accent)' in CSS


# --- U30: a verdict hands its draft to the setup form ------------------------

def spec_U30_a_verdict_hands_its_exact_draft_to_the_advanced_form():
    import json as _json
    import html as _html
    import re
    from panel.server import setup_button, windows_html, verdict
    draft = {'market_type': 'linear', 'venue': 'bybit', 'symbol': 'FARTCOINUSDT',
             'side': 'long', 'capital': 2000, 'lower': 0.14, 'upper': 0.22,
             'rungs': 20}
    b = setup_button(draft, 'from a rehearsal: net +1.00')
    assert 'name="how" value="reopen"' in b and 'set up this bot' in b
    m = re.search(r'name="values" value="([^"]*)"', b)
    vals = _json.loads(_html.unescape(m.group(1)))
    assert vals['symbol'] == 'FARTCOINUSDT' and vals['rungs'] == '20'
    assert vals['lower'] == '0.14' and vals['capital'] == '2000'
    b17 = setup_button(dict(draft, rung_weights=[1, 2], rung_sizing='weighted'),
                       'n', rungs=17, label='set up with 17 grids &rarr;')
    v17 = _json.loads(_html.unescape(
        re.search(r'name="values" value="([^"]*)"', b17).group(1)))
    assert v17['rungs'] == '17' and 'rung_weights' not in v17   # set aside
    # the rehearsal verdict carries the button and its words
    out = {'grid_profit': 3.0, 'fees': 0.5, 'net': 2.5, 'total': 2.4,
           'hold_benchmark': 1.0, 'max_drawdown': 0.7, 'held': 0.0,
           'trips': 2, 'entry_fills': 3, 'bars': 100, 'equity_curve': []}
    page = verdict(draft, out, typed={'symbol': 'FARTCOINUSDT'})
    assert 'set up this bot' in page and 'from a rehearsal over 7 days' in page
    # every row of the comparison hands over its own count
    row = lambda n, net: {'rungs': n, 'gap_pct': 1.0, 'net': net, 'total': net,
                          'trips': 3, 'fees': 0.1, 'fee_share': 0.1,
                          'max_drawdown': 2.0}
    sweep = lambda best, nets: {'best': best, 'plateau': [best, best],
                                'rows': [row(n, v) for n, v in nets.items()]}
    w = {'windows': {'14d': sweep(13, {5: 1.0, 13: 9.0}),
                     '7d': sweep(13, {5: 0.5, 13: 3.0}),
                     'older7d': sweep(13, {5: 0.5, 13: 6.0})},
         'visited': {'7d': 90.0, '14d': 90.0},
         'oos': {'fit_rungs': 13, 'newer_best': 13, 'fit_net_newer': 3.0,
                 'newer_best_net': 3.0, 'holds': True},
         'dropped': [], 'draft_rungs': 20, 'bars': 4032, 'bar_minutes': 5}
    page = windows_html(draft, w)
    assert 'set up with 5 grids' in page and 'set up with 13 grids' in page
    assert 'the 14-day best' in page and 'holds up out of sample' in page
    # the door: the form opens prefilled, the note on top
    base, d, close = _served_fleet()
    try:
        page = _call(base, '/setup', {
            'how': 'reopen', 'fleet': '0',
            'values': _json.dumps({'symbol': 'FARTCOINUSDT', 'side': 'long',
                                   'lower': '0.14', 'upper': '0.22',
                                   'rungs': '17', 'capital': '2000'}),
            'note': 'from a comparison of grid counts over 14 days: 17 grids'})
        assert 'value="FARTCOINUSDT"' in page and 'value="17"' in page
        assert 'from a comparison of grid counts over 14 days: 17 grids' in page
        assert 'class="refusal"' not in page
    finally:
        close()


# --- U31: the written page says the next step ---------------------------------

def spec_U31_the_written_page_names_the_next_step():
    from panel.server import next_step_html, unit_for_fleet
    units = ('grid-gremlin3-demo', 'grid-gremlin3-hl')
    assert unit_for_fleet('configs/fleet.demo.json', units) == 'grid-gremlin3-demo'
    assert unit_for_fleet('/x/configs/fleet.hl.testnet.json', units) == 'grid-gremlin3-hl'
    assert unit_for_fleet('configs/fleet.demo.json', ()) is None
    created = next_step_html('create', 'grid-gremlin3-demo', units)
    assert 'this bot starts at the fleet\'s next restart' in created
    assert '<b>grid-gremlin3-demo</b>' in created and 'href="/control"' in created
    assert 'keeps the whole fleet down' in created           # the honest risk
    assert 'leaves the fleet' in next_step_html('remove', 'grid-gremlin3-demo', units)
    edited = next_step_html('edit', 'grid-gremlin3-demo', units)
    assert 'within seconds' in edited and 'waits for the fleet' in edited
    assert 'no control over units' in next_step_html('create', None, ())


# --- U32: a bot's name where a market was wanted ------------------------------

def spec_U32_a_pasted_bot_name_is_named_as_one_with_the_coin_inside():
    """Owner 2026-10-04 pasted linFARTCOINUSDTl into the coin box and read
    "LINFARTCOINUSDTL: Bybit lists no such linear market". True, useless."""
    from gridgremlin.apply import coin_in_botid, not_listed
    assert coin_in_botid('linFARTCOINUSDTl') == 'FARTCOINUSDT'
    assert coin_in_botid('LINFARTCOINUSDTL') == 'FARTCOINUSDT'
    assert coin_in_botid('invBTCUSDl') == 'BTCUSD' and coin_in_botid('linSOLs') == 'SOL'
    assert coin_in_botid('LINKUSDT') is None            # a real market, left alone
    assert coin_in_botid('BTCUSDT') is None and coin_in_botid('') is None
    why = not_listed('LINFARTCOINUSDTL', 'Bybit lists no such linear market')
    assert "looks like a bot's name" in why and 'FARTCOINUSDT, type that' in why
    assert "bot's name" not in not_listed('XYZUSDT', 'Bybit lists no such market')
    # U40: the owner typed BTCUSDC for Bybit's USDC perpetual
    why = not_listed('BTCUSDC', 'Bybit lists no such linear market')
    assert "USDC perpetual is named BTCPERP" in why and 'type that' in why
    assert 'PERP' not in not_listed('BTCUSDC', 'Hyperliquid lists no such coin')
    assert 'PERP' not in not_listed('USDC', 'Bybit lists no such market')


# --- U33: the empty box says what a blank becomes -----------------------------

def spec_U33_every_blank_says_its_default_from_the_engine_itself():
    """Owner 2026-10-04: "the default is not defined in any field." It is
    now, read from the engine by validating a minimal row — never typed."""
    from panel.setup import engine_defaults, default_words
    g = engine_defaults('grid')
    assert g['leverage'] == 1.0 and g['exit_floor'] == 'rung'
    assert g['place_within_pct'] == 0.05 and g['split_hysteresis_rungs'] == 0.0
    assert g['capital'] is None and g['rungs'] is None           # required
    assert g['slide.ref_position'] == 0.5 and g['slide.direction'] == 'favourable'
    assert 'spacing_pct' not in g                                # derived
    m = engine_defaults('martingale')
    assert m['order_size_multiplier'] == 1.0 and m['repeat'] is False
    assert m['start_order_requote_seconds'] == 40.0 and m['base_order_size'] is None
    assert default_words('num', 1.0) == 'default 1'
    assert default_words('pct', 0.05) == 'default 5%'
    assert default_words('switch', False) == 'default off'
    assert default_words('num', None) == 'required'
    page = advanced_page('grid', {}, ['f.json'])
    assert 'name="leverage" value="" size="14" placeholder="default 1"' in page
    assert 'name="place_within_pct" value="" size="14" placeholder="default 5%"' in page
    assert 'name="capital" value="" size="10" placeholder="required"' in page
    assert '(default' not in page                             # U46: named
    assert '<option value="" selected>percent</option>' in page
    assert '<option value="" selected>rung</option>' in page
    assert 'placeholder="default 0.5"' in page                   # slide ref
    dca = advanced_page('martingale', {}, ['f.json'])
    assert 'placeholder="default 40"' in dca and 'placeholder="required"' in dca


# --- U34: a new bot is not running until the restart, and the panel says so ----

def spec_U34_the_panel_tells_the_truth_about_a_bot_that_waits():
    import tempfile
    from pathlib import Path as _P
    from panel.server import (unit_refusal, waiting_for_restart, render,
                              unit_for_fleet)
    units = ('grid-gremlin3-demo', 'grid-gremlin3-hl')
    fleet_bots = {'linFARTCOINUSDTl': 'grid-gremlin3-demo'}
    why = unit_refusal('linfartcoinusdtl', units, {}, fleet_bots)
    assert 'is a bot, not a unit' in why and 'grid-gremlin3-demo' in why
    assert 'restart' in why
    # the file vs the engine's last snapshot
    d = _P(tempfile.mkdtemp()); (d / 'configs').mkdir(); (d / 'logs').mkdir()
    (d / 'configs' / 'wd.json').write_text(json.dumps(
        {'snapshot': 'logs/snap.jsonl'}))
    (d / 'configs' / 'fleet.demo.json').write_text(json.dumps({
        'watchdog': str(d / 'configs' / 'wd.json'),
        'bots': [{'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long'},
                 {'market_type': 'linear', 'symbol': 'FARTCOINUSDT',
                  'side': 'long'}]}))
    (d / 'logs' / 'snap.jsonl').write_text(json.dumps(
        {'t': 1, 'equity': 1, 'bots': {'linBTCUSDTl': {}, 'linOLDUSDTs': {}}})
        + '\n')
    new, gone = waiting_for_restart(str(d / 'configs' / 'fleet.demo.json'))
    assert new == ['linFARTCOINUSDTl'] and gone == ['linOLDUSDTs']
    assert waiting_for_restart('/nowhere/fleet.json') == ([], [])
    assert unit_for_fleet(str(d / 'configs' / 'fleet.demo.json'), units) \
        == 'grid-gremlin3-demo'
    # the card: a bot the engine does not run says so
    contract = {'window_hours': 6.0, 'generated_ms': 0, 'unowned': {},
                'bots': {'linBTCUSDTl': None, 'linFARTCOINUSDTl': None},
                'watchdog': {'belief': {'age_s': 3, 'bots': {
                    'linBTCUSDTl': {'alive': True, 'position': 0.0}}}}}
    page = render([('demo', contract)])
    assert 'NOT STARTED' in page and "waits for the fleet's restart" in page
    import re as _re
    assert len(_re.findall(r'>RESTING<', page)) == 1      # the running one's tag


def spec_U46_a_dropdown_names_its_default_and_states_what_it_has():
    """Owner 2026-10-06: "any dropdown box that has default as an option —
    remove it. just simply state the options available … whatever the
    default one is, just make that the option visible." Unstated, the
    default is shown by name and still written as nothing (U33's tidy
    file); stated, the plain options with the row's own chosen — nothing
    dropped behind the owner's back."""
    from panel.setup import _field
    sel = _field('start_order_type',
                 'choice:market|maker', 'Start', '', None, default='market')
    assert ('<option value="" selected>market</option><option>maker</option>'
            in sel) and 'default' not in sel
    stated = _field('start_order_type',
                    'choice:market|maker', 'Start', '', 'market',
                    default='market')
    assert '<option selected>market</option><option>maker</option>' in stated
    assert 'value=""' not in stated                   # never silently dropped
    candle = _field('stop_candle',
                    'choice:1m|5m|15m|30m|1h|4h', 'Candle', '', None)
    assert '<option value="" selected>none</option><option>1m</option>' in candle
    action = _field('stop_action',
                    'choice:stop_bot|leave_position', 'When', '', None)
    assert ('<option value="" selected>stop_bot</option>'
            '<option>leave_position</option>') in action


def spec_ops_no_live_unit_runs_the_retired_agent():
    """2026-10-06: the box-side Claude, retired 2026-09-28, still ran on every
    fleet failure because the fleet-down template called it and a token sat
    in .env. Retired is a property of the templates now: none may call it,
    the alert no longer promises it, and each retired entry point refuses."""
    import subprocess
    import sys
    from pathlib import Path
    ops = Path(__file__).resolve().parents[1] / 'ops'
    for t in sorted((ops / 'systemd').glob('*.template')):
        text = t.read_text()
        for gone in ('triage', 'relay.py', 'range_review', 'claude'):
            assert gone not in text.lower(), f'{t.name} still names {gone}'
    for name in ('triage.sh', 'triage-settings.json', 'relay.py',
                 'range_review.py'):
        assert not (ops / name).exists(), f'ops/{name} is live again'
    for script in ('relay.py', 'range_review.py'):
        r = subprocess.run([sys.executable, '-I', str(ops / 'retired' / script),
                            'x'], capture_output=True, text=True)
        assert r.returncode != 0 and 'retired' in r.stderr, script
    r = subprocess.run(['sh', str(ops / 'retired' / 'triage.sh'), 'demo'],
                       capture_output=True, text=True)
    assert r.returncode != 0 and 'retired' in r.stderr


def spec_the_runner_leaves_no_temp_files_however_a_run_ends():
    """2026-10-07: one suite run left 61 entries in /tmp and the workstation
    had ~5,300. Every temp file lands in the run's own directory, removed
    when the run ends — a failing run included — and the settings it
    borrowed are given back."""
    import importlib.util
    import os
    import tempfile
    from pathlib import Path
    path = Path(__file__).resolve().parent / 'run.py'
    spec = importlib.util.spec_from_file_location('gg_run', path)
    run = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run)
    before_env, before_dir = os.environ.get('TMPDIR'), tempfile.tempdir
    made = []

    def leaky():
        made.append(tempfile.mkdtemp())
        fd, name = tempfile.mkstemp()
        os.close(fd)
        made.append(name)
        raise RuntimeError('a failing run')
    try:
        run.contained(leaky)
        raise AssertionError('the failure was swallowed')
    except RuntimeError:
        pass
    assert made and all(not os.path.exists(m) for m in made), made
    assert os.environ.get('TMPDIR') == before_env
    assert tempfile.tempdir == before_dir


def spec_D64_a_mainnet_number_past_double_is_typed_twice():
    """Owner 2026-10-07: the gates pass a valid number, so only a second
    typing catches 50000 meant as 5000. On Mainnet, a new bot's capital and
    an edit raising capital or leverage past double are typed twice."""
    from panel.create import retype_refusal, size_jumps
    fleet = {'bots': [{'market_type': 'linear', 'symbol': 'BTCUSDT',
                       'side': 'long', 'capital': 1000, 'leverage': 5}]}
    row = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long'}
    edit = lambda **kw: size_jumps(fleet, 'edit', 'linBTCUSDTl', dict(row, **kw))
    assert edit(capital=1900, leverage=5) == []                  # under double
    assert edit(capital=2500, leverage=5) == [('capital', 1000.0, 2500.0)]
    assert edit(capital=1000, leverage=15) == [('leverage', 5.0, 15.0)]
    assert size_jumps(fleet, 'create', '', dict(row, capital=700)) == \
        [('capital', None, 700.0)]
    assert size_jumps(fleet, 'remove', 'linBTCUSDTl', None) == []
    jumps = [('capital', 1000.0, 25000.0)]
    assert 'a second time' in retype_refusal(jumps, {})
    assert 'a second time' in retype_refusal(jumps, {'retype_capital': '2500'})
    assert retype_refusal(jumps, {'retype_capital': '25,000'}) is None


def spec_D64_the_served_panel_asks_twice_on_mainnet_only():
    import html
    import re
    import time
    from panel.server import Handler
    base, d, close = _served_fleet()
    fleet_p = str(d / 'f.json')
    try:
        def gates():
            page = _call(base, '/setup', {
                'how': 'quick', 'then': 'gates', 'fleet': '0',
                'preset': 'sideways', 'caution': 'balanced',
                'symbol': 'btcusdt', 'capital': '1000'})
            return page, html.unescape(re.search(
                r'name="proposal" value="([^"]*)"', page).group(1))
        Handler._cache[fleet_p] = (time.time(), {           # a Mainnet fleet
            'account': {'bybit': {'notional': 0.0, 'equity': 1.0,
                                  'collateral': 1.0, 'tier': 'mainnet'}},
            'watchdog': {'belief': {'tiers': {'bybit': 'mainnet'}}}})
        page, proposal = gates()
        assert 'name="retype_capital"' in page
        refused = _call(base, '/apply', {'fleet': '0', 'proposal': proposal,
                                         'confirm': 'linBTCUSDTl'})
        assert 'not applied' in refused and 'a second time' in refused
        assert 'BTCUSDT' not in (d / 'f.json').read_text()
        done = _call(base, '/apply', {'fleet': '0', 'proposal': proposal,
                                      'confirm': 'linBTCUSDTl',
                                      'retype_capital': '1000'})
        assert 'linBTCUSDTl: written' in done
        Handler._cache[fleet_p] = (time.time(), {           # play money
            'watchdog': {'belief': {'tiers': {'bybit': 'demo'}}}})
        page = _call(base, '/setup', {
            'how': 'quick', 'then': 'gates', 'fleet': '0',
            'preset': 'sideways', 'caution': 'balanced',
            'symbol': 'solusdt', 'capital': '1000'})
        assert 'retype_' not in page
    finally:
        Handler._cache.pop(fleet_p, None)
        close()
