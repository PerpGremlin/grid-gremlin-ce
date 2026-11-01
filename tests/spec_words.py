# Specs for the panel's words (D157, the retail pass's first part): the
# state a bot is in, its money line and its choices in the words Bybit and
# Pionex use; no spec or decision code in what a page shows; the key page a
# glossary; and the audit's small contradictions fixed to what the code does.
import copy
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# a spec, decision or section code: D157, U46, X15, §11 — never on a page
CODE = re.compile(r'(?<![A-Za-z0-9_/.\-])([A-Z]\d{1,3}[a-z]?)(?![A-Za-z0-9_])|§\s?\d+')


def visible(page):
    """What a reader sees: no script, style or comment, no tag or attribute
    (a hover's title keeps its code), but a box's placeholder; an engine
    refusal is said verbatim (P3) and is left out."""
    page = re.sub(r'(?is)<(script|style)\b.*?</\1>', ' ', page)
    page = re.sub(r'(?s)<!--.*?-->', ' ', page)
    page = re.sub(r'(?s)<div class="refusal"[^>]*>.*?</div>', ' ', page)
    held = ' '.join(re.findall(r'placeholder="([^"]*)"', page))
    return html.unescape(re.sub(r'<[^>]+>', ' ', page) + ' ' + held)


def codes_in(page):
    return [m.group(0) for m in CODE.finditer(visible(page))]


def _contract():
    from spec_panel import CONTRACT
    c = copy.deepcopy(CONTRACT)
    c['terms'] = {'spoADAUSDTl': {'capital': 1000, 'leverage': 2.0, 'quote': 'USDT',
                                  'market_type': 'spot', 'strategy': 'grid'}}
    c['bots']['spoADAUSDTl'].update(gap_trips=3, gap_realized=6.0, counted_from='flat',
                                     counted_since_ms=8 * 86_400_000, first_ms=8 * 86_400_000)
    c['generated_ms'] = 10 * 86_400_000
    return c


# --- U114: the state words -------------------------------------------------

def spec_U114_a_bots_state_is_said_in_a_persons_words():
    """DEAD, RESTING, FLAT, HOLDING and NOT STARTED were the engine's own
    words on every card, the table and the strip ("1 dead" for a bot that
    met its own take-profit count). Each state now reads as the platforms
    say it, its meaning on hover; the engine's key stays the CSS class."""
    from panel.card import card, state_tag
    from panel.reference import STATE_LABEL, STATE_WORDS
    from panel.server import render
    from panel.strip_view import hero_strip
    assert set(STATE_LABEL) == set(STATE_WORDS)
    assert STATE_LABEL['DEAD'] == 'Stopped (by its rule)'
    assert STATE_LABEL['RESTING'] == STATE_LABEL['FLAT'] == 'Running · no position'
    assert STATE_LABEL['HOLDING'] == 'Running · in position'
    assert STATE_LABEL['NOT STARTED'] == 'Waiting to start'
    for key, words in STATE_LABEL.items():
        tag = state_tag(key, 'dim')
        assert f'>{html.escape(words)}</span>' in tag and f'st-{key.lower().replace(" ", "-")}' in tag
        assert f'>{key}<' not in tag
    c = _contract()
    page = render([('demo', c)]) + render([('demo', c)], table=True)
    for raw in ('>DEAD<', '>RESTING<', '>FLAT<', '>HOLDING<', '>NOT STARTED<'):
        assert raw not in page, raw
    assert 'Running · in position' in page
    c['watchdog']['belief']['bots']['linDOGEs']['alive'] = False
    assert 'Stopped (by its rule)' in card(0, 'linDOGEs', None, c, c['watchdog']['belief']['bots'])
    strip = hero_strip([('demo', c)])
    assert '1 stopped</b>' in strip and 'dead' not in strip


# --- U115: the money line ----------------------------------------------------

def spec_U115_the_cards_money_reads_as_the_platforms_and_the_caveat_hovers():
    """Bybit's and Pionex's words: Total P&L · ROI, then grid profit and
    floating P&L ("trend" and "open" before), then runtime and APR. The
    account box's forty-word caveat is the hover of its Total P&L, not a
    line of text. Only labels change: every figure is the one before."""
    from panel.card import card, grid_split, pnl_parts, run_rate
    from panel.render import ACCOUNT_PNL_NOTE, cards_section
    c = _contract()
    belief = c['watchdog']['belief']['bots']
    slim = card(0, 'spoADAUSDTl', c['bots']['spoADAUSDTl'], c, belief)
    text = visible(slim)
    for word in ('Total P&L', 'ROI', 'Grid profit', 'Floating P&L', 'Runtime', 'APR'):
        assert word in text, word
    assert 'trend' not in text and ' open ' not in text
    assert text.index('Total P&L') < text.index('ROI') < text.index('Grid profit') < text.index('Runtime')
    assert 'Floating P&amp;L</span> <b class="neg">-4.83</b>' in pnl_parts(2.97, -4.83, 0.0)
    b = c['bots']['spoADAUSDTl']
    split = grid_split(b, 1.0)
    assert '+3.93' in split and '-2.93' in split                 # the same figures: 6.00 − 2.07, the rest
    assert 'Runtime 2.0 d' in run_rate(b, c, 1000.0)
    box = cards_section(0, 'demo', c)
    assert f'title="{ACCOUNT_PNL_NOTE}">Total P&amp;L</span>' in box
    assert 'not the same window as the equity line' not in visible(box)
    assert 'this exchange' not in box


# --- U116: the choices -------------------------------------------------------

def _selects(page):
    """{name: (values offered, the value a browser would send)}."""
    out = {}
    for name, body in re.findall(r'<select name="([^"]+)">(.*?)</select>', page, re.S):
        vals, sent = [], None
        for attrs, text in re.findall(r'<option([^>]*)>(.*?)</option>', body, re.S):
            m = re.search(r'value="([^"]*)"', attrs)
            vals.append(html.unescape(m.group(1) if m else text))
            if re.search(r'\bselected\b', attrs):
                sent = vals[-1]
        out[name] = (vals, vals[0] if sent is None and vals else sent)   # none selected: the first
    return out


def spec_U116_a_choice_shows_words_and_sends_the_files_own_value():
    """mark_price, stop_bot, leave_position, linear, favourable, rung,
    quote, maker, percent: the advanced form showed the file's values. Each
    labelled choice now shows words and sends the same value as before, so
    a row, its form and the file round-trip unchanged (U2, U19)."""
    from panel.carry_setup import CHOICE_WORDS
    from panel.setup import (ALWAYS_STATED, CHOICE_LABELS, SCHEMAS, advanced_page, bot_from_form,
                             form_from_bot)
    from gridgremlin.config import validate_config
    from spec_setup import _shipped_rows
    for strategy, schema in SCHEMAS.items():
        page = advanced_page(strategy, {}, ['f.json'])
        sel = _selects(page)
        for name, _p, kind, *_ in (r for rows in schema.values() for r in rows):
            if not kind.startswith('choice:'):
                continue
            offered = [v for v in sel[name][0] if v]
            assert set(offered) <= set(kind[7:].split('|')), (name, offered)   # values, never words
        for name, words in CHOICE_LABELS.items():
            for value, label in words.items():
                if f'<select name="{name}">' in page and label != value and f'value="{value}"' in page:
                    assert f'>{html.escape(label)}</option>' in page
    assert '>linear<' not in advanced_page('grid', {}, ['f.json'])
    assert set(CHOICE_WORDS['hedge_product']) == {'inverse', 'usdt', 'usdc'}
    # every shipped row: the form a browser would post back is the row again
    n = 0
    for row in _shipped_rows():
        strategy = row.get('strategy', 'grid')
        form = form_from_bot(row)
        page = advanced_page(strategy, form, ['f.json'])
        choices = {r[0] for rows in SCHEMAS[strategy].values() for r in rows if r[2].startswith('choice:')}
        for name, (vals, sent) in _selects(page).items():
            if name in choices and str(form.get(name) or ''):
                assert sent == str(form[name]), (row['symbol'], name, sent, form[name])
            elif name in choices and name not in ALWAYS_STATED:
                assert sent == '', (row['symbol'], name, sent)        # left out: the engine's default
        back = bot_from_form(dict(form), row.get('venue', 'bybit'))
        assert validate_config(back) == validate_config(dict(row))
        n += 1
    assert n >= 15


# --- U117: no codes on a page -------------------------------------------------

def _served_pages(units=('grid-gremlin3-demo',)):
    import spec_setup
    from gridgremlin.apply import make_botid
    from panel.server import Handler
    base, d, close = spec_setup._served_fleet()
    saved = Handler.units
    Handler.units = units
    pages = {}
    try:
        row = json.loads((d / 'f.json').read_text())['bots'][0]
        bid = make_botid(row.get('market_type', 'linear'), row['symbol'], row['side'])
        for p in ('/', '/key', '/trading', '/control', '/trade', '/setup', '/setup?adv=grid',
                  '/setup?adv=martingale', '/setup?adv=carry', '/rehearse', '/results', '/table',
                  f'/?fleet=0&bot={bid}', f'/?fleet=0&bot={bid}&show=numbers',
                  f'/?fleet=0&bot={bid}&show=edit', f'/retire?fleet=0&bot={bid}',
                  f'/edit?fleet=0&bot={bid}', f'/position?fleet=0&bot={bid}'):
            if p.startswith('/retire') and not units:
                continue                                # unarmed: 404, and no card links it
            pages[p] = spec_setup._call(base, p)
        for preset in ('sideways', 'dca_long', 'reversal'):
            pages[f'review {preset}'] = spec_setup._call(base, '/setup', {
                'how': 'quick', 'preset': preset, 'fleet': '0', 'symbol': 'BTCUSDT',
                'capital': '1000', 'caution': 'balanced', 'then': 'gates'})
        pages['refused quick'] = spec_setup._call(base, '/setup', {
            'how': 'quick', 'preset': 'dca_long', 'fleet': '0', 'symbol': 'BTCUSDT',
            'capital': '', 'caution': 'bold', 'then': 'gates'})
    finally:
        Handler.units = saved
        close()
    return pages


def spec_U117_no_spec_or_decision_code_is_shown_on_a_page():
    """(D54), (D57), (D64), (F12), (§11), (E3), (X15), U-codes on the key
    page: to a retail reader they read as error codes. They stay in the
    code's comments and in hovers; what a page shows carries none. The
    cards, the forms, the review page, control, the key, the trade page."""
    from panel.server import render
    from panel.position_view import position_page
    found = {p: codes_in(page) for p, page in _served_pages().items()}
    c = _contract()
    belief = c['watchdog']['belief']['bots']
    found['cards'] = codes_in(render([('demo', c)]) + render([('demo', c)], table=True)
                              + position_page(0, 'demo', 'spoADAUSDTl', c, belief))
    found = {p: f for p, f in found.items() if f}
    assert not found, found


def spec_U117_the_code_check_catches_what_it_says():
    """Sabotage: a code planted in a page's text is found; the same code in
    a hover, a comment or a script is not."""
    import panel.reference as ref
    assert codes_in('<p>asks for it twice (D64)</p>') == ['D64']
    assert codes_in('<p>a click is not a decision (§11)</p>') == ['§11']
    assert codes_in('<input placeholder="see U46">') == ['U46']
    assert codes_in('<span title="the rule (D64)">asks twice</span><!-- X15 -->'
                    '<script>// U110</script><style>/* U86 */</style>') == []
    assert codes_in('<div class="refusal"><b>not yet</b> — (D25)</div>') == []
    assert codes_in('BTCUSDT 1.5x +12.34 USDT') == []
    saved = ref.TRADING
    try:
        ref.TRADING = saved.replace('</h1>', ' (D25)</h1>', 1)
        import panel.routes as routes
        was = routes.TRADING
        routes.TRADING = ref.TRADING
        try:
            assert 'D25' in codes_in(_served_pages(units=())['/trading'])
        finally:
            routes.TRADING = was
    finally:
        ref.TRADING = saved


# --- U118: the key page and the bot code ---------------------------------------

def spec_U118_the_key_is_a_glossary_and_a_card_reads_its_bot_code_out():
    """The key page listed ZERO-SPREAD (R9), which no page shows, a garbled
    fees line, and U-codes; it is a glossary now, each word with what the
    other platforms call it. A card's footer reads its code out: the word a
    confirm box asks for, said as what it is."""
    from panel.html_bits import bot_code, decode_botid
    from panel.reference import KEY
    assert 'also called' in KEY and 'ZERO-SPREAD' not in KEY and 'excluded from nothing' not in KEY
    for synonym in ('unrealised P&amp;L, trend PnL', 'grid, rung', 'add-on order', 'maintenance margin rate',
                    'arbitrage profit'):
        assert synonym in KEY, synonym
    assert not CODE.search(visible(KEY))
    assert decode_botid('linBTCUSDTl') == 'USDT perpetual · BTCUSDT · long'
    assert decode_botid('linBTCPERPs') == 'USDC perpetual · BTCPERP · short'
    assert decode_botid('linSOLl', 'USDC') == 'USDC perpetual · SOL · long'
    assert decode_botid('invBTCUSDl') == 'coin-margined perpetual · BTCUSD · long'
    assert decode_botid('spoETHUSDTs') == 'spot · ETHUSDT · short'
    assert decode_botid('pfocarry') == 'portfolio · carry'
    assert 'linBTCUSDTl <span class="dim">= USDT perpetual · BTCUSDT · long</span>' in bot_code('linBTCUSDTl')
    from panel.server import render
    assert 'spoADAUSDTl <span class="dim">= spot · ADAUSDT · long</span>' in render([('demo', _contract())])


# --- U119: the audit's contradictions ---------------------------------------------

def spec_U119_retire_and_close_are_offered_only_where_control_answers():
    """The audit's fourth: a panel started without control offered retire
    on every card, and the link answered 404. Unarmed, no card or table row
    offers retire or close; armed, they are there."""
    from panel.card import card
    c = _contract()
    c['terms']['linDOGEs'] = {'trade': True, 'strategy': 'martingale'}
    belief = c['watchdog']['belief']['bots']
    armed = card(0, 'spoADAUSDTl', c['bots']['spoADAUSDTl'], c, belief) + card(0, 'linDOGEs', None, c, belief)
    assert '/retire?' in armed and '/close?' in armed
    off = dict(c, control_off=True)
    bare = card(0, 'spoADAUSDTl', c['bots']['spoADAUSDTl'], off, belief) + card(0, 'linDOGEs', None, off, belief)
    assert '/retire?' not in bare and '/close?' not in bare and '>copy</a>' in bare
    unarmed = _served_pages(units=())
    assert '/retire?' not in unarmed['/'] and '/retire?' not in unarmed['/table']
    assert '/retire?' in _served_pages()['/']


def spec_U119_the_audits_contradictions_say_what_the_code_does():
    """When an edit takes effect (F12: hot terms within seconds, the range
    at a restart), what a refused row does (D52: set aside, the rest run),
    the trade page's "close position" for the card's "close trade", the
    Mainnet second typing shown on Demo, a refused quick setup coming back
    blank, and the blank DCA door's one-round default against the quick
    preset's repeat."""
    from panel.chart import CHART_BOX
    from panel.forms import next_step_html
    from panel.setup import advanced_page, quick_page
    from panel.trade_page import open_trades_html, trade_form
    edit = advanced_page('grid', {'symbol': 'BTCUSDT', 'side': 'long', 'market_type': 'linear'},
                         ['f.json'], edit='linBTCUSDTl')
    assert 'within seconds' in edit and 'keeps the old settings until' not in edit
    assert 'until you apply the summary and the fleet is restarted' not in CHART_BOX
    created = next_step_html('create', 'u', ('u',))
    assert 'set aside' in created and 'keeps the whole fleet down' not in created
    assert '<b>close trade</b>' in open_trades_html([]) and 'close position' not in open_trades_html([])
    assert 'retype_capital' not in trade_form(['demo']) and 'retype_capital' in trade_form(['demo'], mainnet=True)
    back = quick_page(['demo'], 0, values={'preset': 'dca_long', 'symbol': 'SOLUSDT', 'capital': '250',
                                           'size_unit': 'notional', 'caution': 'bold', 'stop_on': '1',
                                           'max_loss': '40', 'mid': ''})
    assert 'value="dca_long" checked' in back and 'value="sideways" checked' not in back
    assert 'name="symbol" value="SOLUSDT"' in back and 'name="capital" value="250"' in back
    assert '<option value="notional" selected>' in back and '<option value="bold" selected>bold — ' in back
    assert 'name="stop_on" value="1" checked' in back and 'name="max_loss" value="40"' in back
    assert 'value="sideways" checked' in quick_page(['demo'], 0)          # a first visit, as before
    import spec_setup
    base, _d, close = spec_setup._served_fleet()
    try:
        refused = spec_setup._call(base, '/setup', {'how': 'quick', 'preset': 'dca_long', 'fleet': '0',
                                                    'symbol': 'SOLUSDT', 'capital': '', 'caution': 'bold',
                                                    'then': 'gates'})
        assert 'class="refusal"' in refused and 'name="symbol" value="SOLUSDT"' in refused
        assert 'value="dca_long" checked' in refused
        door = spec_setup._call(base, '/setup', {'how': 'quick', 'preset': 'dca_long', 'fleet': '0',
                                                 'symbol': '', 'capital': '', 'then': 'advanced'})
        assert 'name="repeat" value="1" checked' in door
    finally:
        close()
