"""U108: a carry bot (the portfolio row, D78) set up from the panel — its
form, its review and its write, beside the grid and DCA flow and through
the same gates: the engine's own loaders over the merged fleet, no market
shared with another bot of the fleet (the build's I2 collision, said at
the form), the change as a diff, the bot in plain words, its name typed.
"""
import html
import json
from pathlib import Path

from common.fmt import float_or as _f
from panel.html_bits import named, refusal_box


def stranded(was, now):
    """U111: an edit that would leave a running bot's coins or shorts with
    nothing managing them is refused in words — a coin taken out, a long
    turned short or back, an outright short's perpetual changed (the old
    short would stay open on the old market). A hedged coin moved to
    another perpetual is the engine's to carry over (H17): allowed, and
    what will happen is returned in words, one line a coin."""
    sign = {a['coin']: a['weight'] > 0 for a in now['assets']}
    for a in was['assets']:
        c = a['coin']
        if c not in sign:
            raise ValueError(f'{c} is taken out: its coins and short would be left unmanaged — '
                             'flatten the bot first, or set up a new one')
        if sign[c] != (a['weight'] > 0):
            raise ValueError(f'{c} turns from {"long" if a["weight"] > 0 else "short"} to the other '
                             'side: flatten the bot first, or set up a new one')
    said = []
    for kind in ('hedges', 'short_products'):
        for c, h in (was.get(kind) or {}).items():
            if isinstance(h, dict) and not h.get('ratio'):
                continue                             # no hedge held: nothing left behind
            p0 = h['product'] if isinstance(h, dict) else h
            n = (now.get(kind) or {}).get(c)
            p1 = n['product'] if isinstance(n, dict) else n
            if p1 is None or p1 == p0:
                continue
            if kind == 'hedges' and n.get('ratio'):
                said.append(f"{c}'s hedge moves from {p0} to {p1} on the next read: the new short "
                            'opens, then the old one closes, a slice of at most '
                            f"{now['rebalance']['move_slice']:,.0f} USDT a read (H17)")
                continue
            raise ValueError(f'{c} moves from its {p0} perpetual to {p1}: the {p0} short would '
                             'stay open with nothing managing it — flatten the bot first, or '
                             'set up a new one')
    return said


FUNDING_TTL_S = 1800        # a market's funding record, kept this long by the panel


def public_funding(market_type, symbol, days=30, now_ms=None):
    """U111: a market's settlements over `days` from Bybit's PUBLIC record
    (the panel holds no keys), [(time_ms, rate)]; None when it cannot be
    read. Kept FUNDING_TTL_S per market: the form re-renders often."""
    import time
    import urllib.parse
    import urllib.request
    from gridgremlin.exchange.bybit.klines import PUBLIC_HOST
    key = (market_type, symbol)
    got = _FUNDING.get(key)
    if got and time.time() - got[0] < FUNDING_TTL_S:
        return got[1]
    now_ms = now_ms or int(time.time() * 1000)
    since, end, out = now_ms - days * 86_400_000, now_ms, []
    try:
        while end > since:
            q = urllib.parse.urlencode({'category': market_type, 'symbol': symbol,
                                        'startTime': since, 'endTime': end, 'limit': 200})
            with urllib.request.urlopen(f'{PUBLIC_HOST}/v5/market/funding/history?{q}', timeout=8) as r:
                d = json.load(r)
            if d.get('retCode') not in (0, None):
                raise ValueError(d.get('retMsg'))
            rows = (d.get('result') or {}).get('list') or []
            out += [(int(x['fundingRateTimestamp']), float(x['fundingRate'])) for x in rows]
            if len(rows) < 200:
                break
            end = min(int(x['fundingRateTimestamp']) for x in rows) - 1
        rates = sorted(set(out)) or None
    except Exception:                                 # noqa: BLE001 — unread, said as a dash
        rates = None
    _FUNDING[key] = (time.time(), rates)
    return rates


_FUNDING = {}


class CarryFlowPages:

    def _funding(self, form):
        """U111: the funding table for the coins the form names (none: '')."""
        import time
        from concurrent.futures import ThreadPoolExecutor
        from panel.carry_setup import PRODUCT_WORDS, _assets, funding_html
        try:
            coins = [c for c, sh in _assets(form.get('assets') or '') if sh > 0]
        except ValueError:
            return ''
        if not coins:
            return ''
        wanted = [(mt, sym.format(c=c)) for c in coins for _, mt, sym in PRODUCT_WORDS]
        with ThreadPoolExecutor(max_workers=8) as pool:
            got = dict(zip(wanted, pool.map(lambda k: public_funding(*k), wanted)))
        return funding_html(coins, lambda mt, sym: got.get((mt, sym)), int(time.time() * 1000))

    def _carry_page(self, fi, values=None, alert=''):
        from panel.carry_setup import carry_page
        values = values or {}
        return self._page(carry_page(values, self._fleet_labels(), fi, alert=alert)
                          + self._funding(values))

    def _carry_post(self, form):
        from gridgremlin.apply import row_botid
        from gridgremlin.config import ConfigError, market_rows, validate_fleet
        from gridgremlin.portfolio import leg_markets, validate_portfolio
        from panel.carry_setup import hedge_readings, row_from_form, sentence
        from panel.create import (atomic_write, dump_config, public_adapter,
                                  unified_diff, validate_whole)
        from panel.forms import next_step_html, unit_for_fleet
        fi = min(int(_f(form.get('fleet')) or 0), len(self.fleets) - 1)
        fleet_p = Path(self.fleets[fi])
        fleet_text = fleet_p.read_text()
        fleet_raw = json.loads(fleet_text)
        fleet_raw = {'bots': fleet_raw} if isinstance(fleet_raw, list) else fleet_raw
        wd_p = Path(fleet_raw['watchdog']) if fleet_raw.get('watchdog') else None
        wd_text = wd_p.read_text() if wd_p else '{}'
        seen = self._seen(fleet_text, wd_text)
        if form.get('step') == 'change':
            return self._carry_page(fi, form)
        try:
            if self._mainnet(fleet_p, 'bybit'):
                raise ValueError('a carry bot on a Mainnet fleet is written in the '
                                 'fleet file, not here (D64)')
            if self._fleet_venue(fi) != 'bybit':
                raise ValueError('a carry bot trades Bybit — this fleet trades '
                                 f'{self._fleet_venue(fi)} (D78)')
            row = row_from_form(form)
            read_as = hedge_readings(form)               # U111d: each entry as read
            cfg = validate_portfolio(json.loads(json.dumps(row)), 'the carry bot')
            moves = []
            botid = row_botid(row)
            fleet = json.loads(json.dumps(fleet_raw))
            edit = form.get('edit')
            if edit:                                 # U111: the running bot's row, replaced
                at = next((i for i, b in enumerate(fleet.get('bots') or []) if row_botid(b) == edit), None)
                if at is None or botid != edit:
                    raise ValueError(f'{edit}: not in this fleet any more — reload its edit tab')
                old = fleet['bots'][at]
                moves = stranded(validate_portfolio(json.loads(json.dumps(old)), 'its row now'), cfg)
                kept = {a['coin']: a['holding'] for a in old.get('assets') or [] if a.get('holding')}
                for a in row['assets']:
                    if a['coin'] in kept:
                        a['holding'] = kept[a['coin']]         # coins adopted stay adopted (H2)
                for k in ('account', 'spot_quote'):
                    if k in old:
                        row[k] = old[k]
                # a row's own notes (keys starting '_') are the operator's and
                # ride along, as the grid and DCA edit has them (U111b)
                row.update({k: v for k, v in old.items() if k.startswith('_')})
                fleet['bots'][at] = row
            else:
                if any(row_botid(b) == botid for b in fleet_raw.get('bots') or []):
                    raise ValueError(f'{botid}: already in this fleet — pick another name')
                fleet.setdefault('bots', []).append(row)
            vfleet = validate_fleet(json.loads(json.dumps(fleet)))
            taken = {(c['market_type'], c['symbol']): row_botid(c)
                     for c in market_rows(vfleet)}
            for b in vfleet['bots']:
                if b.get('strategy') == 'portfolio' and b['botid'] != botid:
                    for _, _, mt, sym, _ in leg_markets(b):
                        taken[(mt, sym)] = b['botid']
            for _, coin, mt, sym, _ in leg_markets(cfg):
                if (mt, sym) in taken:
                    raise ValueError(f'{sym} ({mt}) is already traded by {taken[(mt, sym)]} '
                                     'in this fleet — one bot per market; the fleet would '
                                     'refuse to start (I2)')
            wd = json.loads(wd_text)
            refusal = validate_whole(fleet, wd, public_adapter) if wd_p else None
            if refusal:
                raise ValueError(refusal)
        except (ValueError, ConfigError) as e:
            return self._carry_page(fi, form, refusal_box('not yet', e))
        new_fleet = dump_config(fleet)
        if form.get('step') == 'apply':
            if form.get('seen') != json.dumps(seen):
                return self._carry_page(fi, form, refusal_box(
                    'not applied', 'the fleet file changed since you reviewed it — review again'))
            if not named(form.get('confirm'), botid):
                return self._carry_page(fi, form, refusal_box(
                    'not applied', f'the name typed must be {botid} (capitals do not '
                    'matter) — a click is not a decision (§11)'))
            atomic_write(fleet_p, new_fleet)
            if not form.get('edit'):
                # X16: a new carry row is a first sight — an old row's book of
                # its name (anchor, loan, spent) is not its
                from gridgremlin.forget import forget_bot
                forget_bot(fleet_p, fleet_raw, botid)
            return self._page(
                f'<h1>{html.escape(botid)}: written</h1><p>the carry bot is in the '
                'fleet file; a backup is kept beside it.'
                + (' The running bot takes its new terms at the fleet\'s restart, and says '
                   'what changed (H2).' if form.get('edit') else '') + '</p>'
                + next_step_html('create', unit_for_fleet(fleet_p, self.units), self.units)
                + '<p><a href="/">back to your bots</a></p>')
        hidden = ''.join(f'<input type="hidden" name="{html.escape(k, quote=True)}" '
                         f'value="{html.escape(str(v), quote=True)}">'
                         for k, v in form.items() if k not in ('step', 'confirm', 'seen'))
        legs = ''.join(f'<tr><td>{kind}</td><td>{html.escape(sym)}</td><td>{mt}</td>'
                       f'<td>{put:,.2f}</td></tr>'
                       for kind, _, mt, sym, put in leg_markets(cfg))
        return self._page(
            f'<h1>{html.escape(botid)} — {"edit" if form.get("edit") else "create"}: gates passed</h1>'
            '<div class="fsec"><h1 class="dim">in plain words</h1>'
            f'<p class="say">{html.escape(sentence(cfg))}</p>'
            + ''.join(f'<p class="say">{html.escape(m)}</p>' for m in moves)
            + (f'<p class="say">Hedges read as: {html.escape("; ".join(read_as))}.</p>'
               if read_as else '') +
            '<table><tr><th>leg</th><th>market</th><th>kind</th><th>USDT at its weight</th></tr>'
            f'{legs}</table></div>' + self._funding(form) +
            '<div class="fsec"><form method="post" action="/setup-carry">'
            '<input type="hidden" name="gg" value="1">' + hidden +
            '<input type="hidden" name="step" value="change">'
            '<button class="quiet">change something</button></form></div>'
            '<div class="fsec go"><form method="post" action="/setup-carry" class="apply">'
            '<input type="hidden" name="gg" value="1">' + hidden +
            '<input type="hidden" name="step" value="apply">'
            f'<input type="hidden" name="seen" value="{html.escape(json.dumps(seen), quote=True)}">'
            f'<b>To {"save this change" if form.get("edit") else "create this bot"}</b>, type its name '
            f'<code>{html.escape(botid)}</code> here: '
            f'<input name="confirm" size="16" placeholder="{html.escape(botid)}"> '
            f'<button>{"save the change" if form.get("edit") else "create this bot"}</button></form>'
            '<p class="dim">this writes the fleet file. A new bot waits for the '
            'fleet\'s restart (F12); at its start it buys its spot and opens its '
            'hedges.</p></div>'
            '<details><summary>the change to the file</summary>'
            f'<pre class="dim">{html.escape(unified_diff(fleet_text, new_fleet, fleet_p.name))}</pre>'
            '</details>')
