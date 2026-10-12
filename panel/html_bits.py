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
    return (f'<a class="pick" data-pick href="/?fleet={idx}&amp;bot={qarg(botid)}">'
            f'{text}</a>')


REFRESH_S = 15          # the readout hits venue APIs: poll gently


WATCHDOG_OFF_S = 3600   # no sweep for an hour: it is off, not late (D39)


def money(v, cls=True):
    if v is None:
        return '<td class="dim">—</td>'
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


def refusal_box(title, why, extra=''):
    """U11: a refusal is the first thing on the page, boxed, in plain
    words: what happened (nothing was saved), the engine's reason, and
    what to do about it."""
    import html as _html
    return (f'<div class="refusal"><b>{_html.escape(title)}</b> — nothing '
            f'was saved.<br>{_html.escape(str(why))}{extra}</div>')


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
