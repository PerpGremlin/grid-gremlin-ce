"""Small HTML pieces every page uses: a money cell, a number's colour, the tidy pass, a name, a refusal box, a bot's coin and units, the refresh constants. Out of render.py (D91 step 3)."""
from gridgremlin.report import money_units
import html
import re
import time
import urllib.parse


def esc(v):
    """A name into a page as text or an attribute: a bot id, a symbol, a
    fleet's label never becomes markup (the 2026-10-11 review)."""
    return html.escape(str(v))


def qarg(v):
    """A name into a link's query: every reserved character encoded, which
    also leaves nothing an attribute could break on."""
    return urllib.parse.quote(str(v), safe='')


def pick_link(idx, botid, text):
    """D96/U78: a bot's name on its card, opening the bot in the front
    page's right half; the pick lives in the address."""
    return (f'<a class="bname" data-pick href="/?fleet={idx}&amp;bot={qarg(botid)}">'
            f'{text}</a>')


REFRESH_S = 15          # the readout hits venue APIs: poll gently


WATCHDOG_OFF_S = 3600   # no sweep for an hour: it is off, not late (D39)


def money(v, cls=True):
    if v is None:
        return '<td class="dim">—</td>'
    v = 0.0 if abs(v) < 0.005 else v                     # never "-0.00" (the second audit)
    c = ' class="pos"' if (cls and v > 0) else (' class="neg"'
                                               if cls and v < 0 else '')
    return f'<td{c}>{v:,.2f}</td>'


def tidy(page):
    """U46: links are buttons now — the " · " that separated them as text
    only crowds the row. Dropped wherever it stands between two of them."""
    import re
    return re.sub(r'(</a>|<b class="on">[^<]*</b>)\s*(?:·|&middot;)\s*'
                  r'(?=<a\b|<b class="on">)', r'\1 ', page)


def _num_cls(v):
    return 'pos' if v > 0 else 'neg' if v < 0 else 'dim'


def _day(ms):
    return time.strftime('%Y-%m-%d', time.gmtime(ms / 1000))


def named(typed, botid):
    """U18: the typed name is the decision; its capitals are not. A bot's
    name is one spelling, so the comparison ignores case and stray space."""
    return bool(botid) and (typed or '').strip().lower() == botid.lower()


MARKET_WORD = {'inverse': ' inverse', 'spot': ' spot'}


def plain_name(row):
    """D157: a bot's plain name, from its own fields — "BTCUSDT long grid",
    "BTCUSD long DCA inverse", "SOLUSDT short trade", "carry portfolio".
    The one spelling: the card says it, and a confirm box on Demo or Testnet
    takes it as well as the bot's code. None when the row says too little."""
    if not isinstance(row, dict):
        return None
    if row.get('strategy') == 'portfolio':
        return f"{row.get('name')} portfolio" if row.get('name') else None
    side, symbol = row.get('side'), row.get('symbol')
    if side not in ('long', 'short') or not symbol:
        return None
    kind = ('trade' if row.get('trade') else
            'DCA' if row.get('strategy') == 'martingale' else 'grid')
    market = MARKET_WORD.get(row.get('market_type') or 'linear', '')
    return f"{str(symbol).replace('-', '')} {side} {kind}{market}"


def row_of_botid(botid, strategy=None, trade=False):
    """The fields plain_name reads, from a bot's code alone (I1): what the
    card has when no fleet row is at hand."""
    mt = {'inv': 'inverse', 'spo': 'spot'}.get(botid[:3], 'linear')
    if botid.startswith('pfo'):
        return {'strategy': 'portfolio', 'name': botid[3:]}
    return {'market_type': mt, 'symbol': botid[3:-1],
            'side': 'short' if botid.endswith('s') else 'long',
            'strategy': strategy or 'grid', 'trade': trade}


def _squash(text):
    return ' '.join(str(text or '').lower().split())


def confirmed(typed, botid, row=None, mainnet=False):
    """D157 (the owner's answer): a typed confirmation takes the bot's code,
    as always (U18), and on Demo or Testnet its plain name too — derived
    from the row, which must be this bot's. Mainnet takes the code only,
    exactly as before: its typing is unchanged."""
    if named(typed, botid):
        return True
    if mainnet or not row:
        return False
    from gridgremlin.apply import row_botid
    try:
        if row_botid(row) != botid:
            return False
    except (KeyError, TypeError):
        return False
    said = plain_name(row)
    if said and _squash(typed) == _squash(said):
        return True
    # a carry bot's own name, as typed on its form ("basket" for pfobasket):
    # the word its maker chose is the one they type back
    return (row.get('strategy') == 'portfolio' and bool(row.get('name'))
            and _squash(typed) == _squash(row.get('name')))


def typed_name(row):
    """The words a confirm box shows to type off Mainnet: a carry bot's own
    name as its form took it, any other bot's plain name."""
    if isinstance(row, dict) and row.get('strategy') == 'portfolio' and row.get('name'):
        return str(row['name'])
    return plain_name(row)


def to_type(botid, row=None, mainnet=False):
    """D157: the words a confirm box asks for, shown on the page: the plain
    name with the code as the other spelling, or on Mainnet the code."""
    said = None if mainnet else typed_name(row)
    if not said:
        return f'its code <code>{esc(botid)}</code>'
    return f'its name <code>{esc(said)}</code> <span class="dim">(or its code {esc(botid)})</span>'


def refusal_box(title, why, extra=''):
    """U11: a refusal is the first thing on the page, boxed, in plain
    words: what happened (nothing was saved), the engine's reason, and
    what to do about it."""
    import html as _html
    # D159: it takes the reader's eye and focus on load (CONFIRM_JS)
    return (f'<div class="refusal" tabindex="-1" role="alert"><b>{_html.escape(title)}</b> — nothing '
            f'was saved.<br>{_html.escape(str(why))}{extra}</div>')


def accepts(botid, row=None, mainnet=False):
    """D159: the spellings confirmed() takes, as the page's pop-up matches
    them — lower case, spaces squashed: the code always; off Mainnet the
    plain name (and a carry bot's own name) of a row that is this bot's.
    Mainnet: the code only. The server's confirmed() stays the authority."""
    out = [_squash(botid)]
    if not mainnet and isinstance(row, dict):
        from gridgremlin.apply import row_botid
        try:
            mine = row_botid(row) == botid
        except (KeyError, TypeError):
            mine = False
        if mine:
            out += [_squash(s) for s in (
                plain_name(row),
                row.get('name') if row.get('strategy') == 'portfolio' else None) if s]
    return list(dict.fromkeys(out))


def typed_inline(inner):
    """D159: the inline typed box (the page without script): the pop-up's
    script hides it once it can open the dialog instead."""
    return f'<span class="typed">{inner}</span>'


def confirm_dialog(what, words, accept, button, retypes=(), multi=False, danger=False):
    """D159: the typed confirmation as a pop-up, inside its form. `what` is
    the one plain line of what happens, `words` the words to type (to_type's
    HTML), `accept` the spellings it takes (accepts()), `retypes` Mainnet's
    second typing as (field, label HTML, the number or None). Its confirm
    stays disabled until the typing matches; on press the typed words go
    into the form's own confirm field and the form is sent. Escape or
    cancel sends nothing. Without script it never opens: the inline box
    stays (typed_inline)."""
    import json
    again = ''.join(
        f'<label class="again">{label} <input data-into="{esc(name)}" size="14" '
        f'autocomplete="off"' + (f' data-want="{want!r}"' if want is not None else '') + '></label>'
        for name, label, want in retypes)
    return (f'<dialog class="ggconfirm" data-accept="{esc(json.dumps(accept))}"'
            + (' data-multi="1"' if multi else '') + '>'
            f'<p class="what">{esc(what)}</p>'
            f'<p>To go ahead, type {words}:</p>'
            '<input class="gg-typed" autofocus autocomplete="off" spellcheck="false" '
            'aria-label="the words to type">' + again +
            '<p class="dlgbtn"><button type="button" class="quiet" data-cancel>cancel</button> '
            f'<button type="button" data-go disabled{" class=\"danger\"" if danger else ""}>'
            f'{esc(button)}</button></p></dialog>')


def coin_of(botid):
    """The coin a bot's position is counted in, from its id: linBTCUSDTl ->
    BTC, linBTCPERPl -> BTC, invBTCUSDl -> BTC, linSOLl (Hyperliquid) ->
    SOL."""
    from common.symbols import coin_of as _coin       # D91: one of each
    return _coin(botid[3:-1] if len(botid) > 4 else botid)


def units_of(botid, terms):
    """U53: (money coin, margin coin) for a card — from the contract's
    terms; a contract without them answers from the bot's own name."""
    if terms and terms.get('quote'):
        return terms['quote'], terms.get('margin_coin') or terms['quote']
    mt = {'lin': 'linear', 'inv': 'inverse', 'spo': 'spot'}.get(botid[:3], 'linear')
    u = money_units(None, mt, botid[3:-1])
    return u['quote'], u['margin_coin']


CODE_RE = re.compile(r' ?\((?:[A-Z]\d{1,3}[a-z]?|§\d+)\)')


def uncoded(text):
    """D157: an engine warning shown as advice (not a refusal, which stays
    verbatim) loses its spec code: the code is ours, not the reader's."""
    return CODE_RE.sub('', str(text))


def decode_botid(botid, quote=None):
    """D157: a bot's code read out — linBTCUSDTl is "USDT perpetual ·
    BTCUSDT · long" (I1: the market type's first three letters, the market,
    the side's initial); a portfolio's pfo<name> is "portfolio · <name>".
    The code stays the word a confirm box asks for; this says what it is."""
    head, mid = botid[:3], botid[3:-1]
    if head == 'pfo':
        return f'portfolio · {botid[3:]}'
    side = {'l': 'long', 's': 'short'}.get(botid[-1:], '?')
    if head == 'inv':
        market = 'coin-margined perpetual'
    elif head == 'spo':
        market = 'spot'
    else:
        coin = quote or units_of(botid, None)[0]
        market = f"{coin if coin in ('USDT', 'USDC') else 'USDT/USDC'} perpetual"
    return f'{market} · {mid} · {side}'


def bot_code(botid, quote=None):
    """D157: the card footer's bot code, decoded beside it."""
    return (f'<span class="code" title="this bot\'s code: the name a confirm box asks you '
            f'to type">{esc(botid)} <span class="dim">= {esc(decode_botid(botid, quote))}</span></span>')
