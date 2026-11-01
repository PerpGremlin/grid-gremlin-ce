# Specs for D159: a refusal takes the eye and the focus, and a typed
# confirmation is a pop-up. Every page with a typed gate renders the dialog
# and keeps the inline box for a page without script; the dialog shows
# to_type's words and matches what confirmed() takes, Mainnet the code only.
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from spec_start_stop import RISING, _Systemctl, _call, _mainnet, _proposal, _served  # noqa: E402

DIALOG = re.compile(r'<dialog class="ggconfirm" data-accept="([^"]*)"( data-multi="1")?>'
                    r'<p class="what">(.*?)</p><p>To go ahead, type (.*?):</p>(.*?)</dialog>', re.S)


def forms(page):
    """Every form holding a typed gate, as (its dialog's accept list, multi,
    what, words, the rest of the dialog, the form's whole text)."""
    out = []
    for f in re.findall(r'(?s)<form\b.*?</form>', page):
        if 'name="confirm"' not in f and "name='confirm'" not in f:
            continue
        if re.search(r'<input type="hidden" name="confirm"', f):
            continue                          # resume: a button, nothing typed
        m = DIALOG.search(f)
        out.append((json.loads(html.unescape(m.group(1))) if m else None,
                    bool(m and m.group(2)), m and m.group(3), m and m.group(4),
                    m and m.group(5), f))
    return out


def unstamped(page):
    """A served page's scripts without this answer's nonce (P6b)."""
    return re.sub(r'<script nonce="[^"]+">', '<script>', page)


def problems(page, label):
    """What a confirm page lacks: a form whose typed gate has no pop-up, or
    no inline box for the page without script, or an answer put in the box
    as a placeholder."""
    found = forms(page)
    bad = [] if found else [f'{label}: no typed gate on the page']
    for acc, _multi, what, words, _rest, f in found:
        if acc is None:
            bad.append(f'{label}: a typed gate with no pop-up')
            continue
        typed = re.search(r'(?s)<span class="typed">(.*?)</span>(?=<dialog)', f)
        if not typed or not re.search(r'name=["\']confirm["\']', typed.group(1)):
            bad.append(f'{label}: no inline box beside the pop-up')
        if re.search(r'name=["\']confirm["\'][^>]*placeholder', f):
            bad.append(f'{label}: an answer as the box\'s placeholder')
        if not what or not words or not acc:
            bad.append(f'{label}: a pop-up that says nothing')
    return bad


def _gates(base, d):
    """Every page with a typed gate, on the served Demo fleet: {label: page}."""
    import panel.routes as ps
    from gridgremlin.tombstones import Tombstones, path_for
    pages = {'create': _call(base, '/setup', RISING)}
    pages['carry'] = _call(base, '/setup-carry', {
        'fleet': '0', 'name': 'basket', 'capital': '1000', 'assets': 'BTC 50, SOL 50',
        'hedge_ratio': '100', 'hedge_product': 'inverse'})
    from spec_lever import PFO
    fleet = json.loads((d / 'f.json').read_text())
    (d / 'f.json').write_text(json.dumps(dict(fleet, bots=fleet['bots'] + [PFO])))
    pages['leverage'] = _call(base, '/lever', {'fleet': '0', 'orig': 'pfocarry', 'spot': '3',
                                               'perp_BTC': '4', 'perp_SOL': '2', 'perp_ETH': ''})
    (d / 'f.json').write_text(json.dumps(fleet))
    pages['remove (never started)'] = _call(base, '/retire?fleet=0&bot=linETHUSDTl')
    (d / 's').write_text(json.dumps({'t': 0, 'bots': {'linETHUSDTl': {'position': 0.5}}}) + '\n')
    pages['stop'] = _call(base, '/retire?fleet=0&bot=linETHUSDTl')
    saved = ps.Handler._run_close
    ps.Handler._run_close = lambda self, fi, botid, dry, expect=None: {
        'botid': botid, 'side': 'long', 'symbol': 'ETHUSDT', 'held': 0.5,
        'avg_entry': 2500.0, 'mark': 2600.0}
    try:
        pages['close'] = _call(base, '/close?fleet=0&bot=linETHUSDTl')
    finally:
        ps.Handler._run_close = saved
    assert 'queued' in _call(base, '/trade', {'action': 'open', 'go': '1', 'fleet': '0', 'side': 'short',
                                              'symbol': 'SOLUSDT', 'capital': '100', 'tp': '1'})
    pages['close trade'] = _call(base, '/close?fleet=0&bot=linSOLUSDTs')
    tp = path_for(str(d / 'f.json'), json.loads((d / 'f.json').read_text()))
    Tombstones(str(tp)).add('linSOLUSDTs', 'took profit')
    Tombstones(str(tp)).add('linGONEUSDTl', 'left the account')
    pages['trade clear'] = _call(base, '/trade')
    saved = ps.Handler._run_retire_all
    ps.Handler._run_retire_all = lambda self, fi, dry, sell, clear: {'rows': [], 'flat': True}
    try:
        pages['retire all'] = _call(base, '/retire-all', {'fleet': '0'})
    finally:
        ps.Handler._run_retire_all = saved
    with _Systemctl('inactive'):
        pages['control (unit, revive, clear tombstones)'] = _call(base, '/control')
    return pages


def spec_U130_every_typed_gate_renders_its_pop_up_and_its_inline_box():
    """Create, carry, leverage, remove, stop, close, close trade, a trade's
    clear, retire all, control's unit actions, revive and the leftover
    tombstones: each form's typed gate is a dialog, with the inline box kept
    for a page without script and no answer standing in it as a
    placeholder. The script that opens it rides on every page."""
    from panel.reference import CONFIRM_JS, KEEP_JS
    base, d, close = _served()
    try:
        pages = _gates(base, d)
    finally:
        close()
    bad = [p for label, page in pages.items() for p in problems(page, label)]
    assert bad == [], bad
    control = forms(pages['control (unit, revive, clear tombstones)'])
    assert len(control) == 4 and control[0][1]                 # the unit form, several names (U43)
    assert all(CONFIRM_JS in unstamped(page) for page in pages.values()) and CONFIRM_JS in KEEP_JS
    # the inline box is hidden only once the script can open a dialog
    from panel.css import CSS
    assert '.gg-dlg .typed{display:none}' in CSS and "R.classList.add('gg-dlg')" in CONFIRM_JS
    assert 'if(can)R.classList.add' in CONFIRM_JS
    # sabotage: a page that dropped its pop-up, or put the answer back as a placeholder
    page = pages['create']
    assert problems(DIALOG.sub('', page), 'x') and problems(
        page.replace('name="confirm" size="22"', 'name="confirm" placeholder="BTCUSDT long grid"'), 'x')


def spec_U131_the_pop_up_shows_to_types_words_and_says_what_happens():
    """The dialog's words are to_type's, the same as the inline box's; its
    one line says what will happen, on which account."""
    from panel.html_bits import to_type
    base, d, close = _served()
    try:
        page = _call(base, '/setup', RISING)
        row = json.loads(_proposal(page))['bot']
        carry = _call(base, '/setup-carry', {
            'fleet': '0', 'name': 'basket', 'capital': '1000', 'assets': 'BTC 50, SOL 50',
            'hedge_ratio': '100', 'hedge_product': 'inverse'})
    finally:
        close()
    (acc, _m, what, words, _r, f), = forms(page)
    assert words == to_type('linBTCUSDTl', row) and words in f.split('<dialog')[0]
    assert html.unescape(what) == 'Create the bot BTCUSDT long grid on demo.'
    assert acc == ['linbtcusdtl', 'btcusdt long grid']
    (acc, _m, what, words, _r, _f), = forms(carry)
    assert html.unescape(what) == 'Create the carry bot basket on demo.'
    assert '<code>basket</code>' in words and acc == ['pfobasket', 'basket portfolio', 'basket']


def spec_U132_the_pop_up_takes_what_confirmed_takes_and_mainnet_the_code_only():
    """The page's spellings (accepts) are confirmed()'s: each it lists is
    taken, and of every candidate the server takes exactly those it lists
    (squashed as the script squashes). On Mainnet the list is the code
    alone, on every gate, and the second typing is in the dialog."""
    from panel.html_bits import _squash, accepts, confirmed
    from panel.reference import CONFIRM_JS
    rows = [('linBTCUSDTl', {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long', 'strategy': 'grid'}),
            ('invBTCUSDs', {'market_type': 'inverse', 'symbol': 'BTCUSD', 'side': 'short',
                            'strategy': 'martingale'}),
            ('pfobasket', {'strategy': 'portfolio', 'name': 'basket'}),
            ('linBTCUSDTs', {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long'}),   # not its row
            ('linETHUSDTl', None)]
    tries = ['linBTCUSDTl', ' LINBTCUSDTL ', 'BTCUSDT long grid', 'btcusdt  LONG grid', 'BTCUSDT long',
             'BTCUSD short DCA inverse', 'basket', 'basket portfolio', 'pfobasket', 'invBTCUSDs',
             'linETHUSDTl', 'BTCUSDT', '']
    for botid, row in rows:
        for real in (False, True):
            acc = accepts(botid, row, real)
            if real:
                assert acc == [botid.lower()], (botid, acc)
            for t in tries:
                assert confirmed(t, botid, row, mainnet=real) == (_squash(t) in acc), (botid, real, t)
    # the script squashes as _squash does and matches against data-accept
    assert "toLowerCase().split(/\\s+/).filter(Boolean).join(' ')" in CONFIRM_JS
    assert 'acc.indexOf(sq(p))>=0' in CONFIRM_JS and 'JSON.parse(d.dataset.accept' in CONFIRM_JS
    assert "c.value=d.querySelector('input.gg-typed').value.trim()" in CONFIRM_JS
    base, d, close = _served()
    try:
        assert mainnet_leaks(*_mainnet_pages(base, d)) == []
    finally:
        close()


def _mainnet_pages(base, d):
    import panel.routes as ps
    _mainnet(d)
    ps.Handler._cache.clear()
    pages = {'create': _call(base, '/setup', RISING)}
    (d / 's').write_text(json.dumps({'t': 0, 'bots': {'linETHUSDTl': {'position': 0.5}}}) + '\n')
    pages['stop'] = _call(base, '/retire?fleet=0&bot=linETHUSDTl')
    saved = ps.Handler._run_close
    ps.Handler._run_close = lambda self, fi, botid, dry, expect=None: {
        'botid': botid, 'side': 'long', 'symbol': 'ETHUSDT', 'held': 0.5,
        'avg_entry': 2500.0, 'mark': 2600.0}
    try:
        pages['close'] = _call(base, '/close?fleet=0&bot=linETHUSDTl')
    finally:
        ps.Handler._run_close = saved
    return pages, {'create': 'linBTCUSDTl', 'stop': 'linETHUSDTl', 'close': 'linETHUSDTl'}


def mainnet_leaks(pages, botids):
    """The Mainnet pages whose pop-up would take more than the code, or
    lost the second typing a page asks for. [] when none."""
    bad = []
    for label, page in pages.items():
        for acc, _m, _what, _words, rest, f in forms(page):
            if acc != [botids[label].lower()]:
                bad.append(f'{label}: takes {acc}')
            inline = set(re.findall(r'name="(retype_\w+|size)"', f.split('<dialog')[0]))
            popped = set(re.findall(r'data-into="(retype_\w+|size)"', rest))
            if not inline or inline != popped:
                bad.append(f'{label}: the second typing {sorted(inline)} vs the pop-up {sorted(popped)}')
    return bad


def spec_U133_a_mainnet_pop_up_that_takes_the_plain_name_is_caught():
    """Sabotage: the create page's pop-up built as if off Mainnet takes
    the plain name, and the check names it; the server still refuses."""
    import panel.pages.create_flow as cf
    from panel.html_bits import accepts
    base, d, close = _served()
    saved = cf.accepts
    cf.accepts = lambda botid, row=None, mainnet=False: accepts(botid, row, False)
    try:
        pages, botids = _mainnet_pages(base, d)
        assert [p for p in mainnet_leaks(pages, botids) if p.startswith('create: takes')], 'not caught'
        assert not [p for p in mainnet_leaks(pages, botids) if not p.startswith('create')]
        retype = re.search(r'name="(retype_\w+)"', pages['create']).group(1)
        with _Systemctl('inactive'):
            got = _call(base, '/apply', {'fleet': '0', 'proposal': _proposal(pages['create']),
                                         'confirm': 'BTCUSDT long grid', retype: '1000'})
        assert 'not applied' in got                       # confirmed() stays the authority
    finally:
        cf.accepts = saved
        close()


def spec_U134_a_refusal_takes_the_eye_and_the_focus():
    """A refusal is boxed apart from everything else and focusable; the
    page's script scrolls to the first and focuses it on load; each theme
    keeps its own colours on it. Without script it is already first."""
    from panel.css import CSS
    from panel.html_bits import refusal_box
    from panel.reference import CONFIRM_JS
    box = refusal_box('not applied', 'why <b>')
    assert box.startswith('<div class="refusal" tabindex="-1" role="alert"><b>not applied</b>')
    assert 'why &lt;b&gt;' in box
    assert "document.querySelector('.refusal[tabindex]')" in CONFIRM_JS
    assert 'scrollIntoView' in CONFIRM_JS and 'focus({preventScroll:true})' in CONFIRM_JS
    assert '.refusal>b:first-child{display:block' in CSS and 'background:var(--neg);color:var(--bg)' in CSS
    assert ':root.t-win95 .refusal{' in CSS and ':root.t-win95 dialog.ggconfirm' in CSS
    base, d, close = _served()
    try:
        wrong = _call(base, '/apply', {'fleet': '0', 'proposal': _proposal(_call(base, '/setup', RISING)),
                                       'confirm': 'no'})
    finally:
        close()
    assert 'class="refusal" tabindex="-1"' in wrong and CONFIRM_JS in unstamped(wrong)
    assert focused(wrong) == 'not applied'
    # sabotage: a refusal drawn without its tabindex is not one the script focuses
    assert focused(wrong.replace(' tabindex="-1"', '')) is None


def focused(page):
    """The refusal the page's script focuses on load: the first .refusal
    with a tabindex, by its title; None when there is none."""
    m = re.search(r'<div class="refusal"[^>]*\btabindex="-1"[^>]*><b>([^<]*)</b>', page)
    return m and m.group(1)
