"""Trades (D81): the form, the list, opening and clearing one. Moved out of routes.py whole (D91 step 3): a mixin
the Handler inherits."""
from ..html_bits import refusal_box
from panel.chart import _f
from pathlib import Path
import html
import json
import re


class TradePages:
    def _trades_of(self, fi):
        """One fleet's trades file and validated rows, for the trade page."""
        from gridgremlin.trades import fleet_rows, trades_path
        f = self.fleets[min(fi, len(self.fleets) - 1)]
        fleet, rows = fleet_rows(f)
        return f, fleet, rows, trades_path(f, json.loads(Path(f).read_text()))

    def _trade_html(self, msg='', typed=None):
        """L6: the form, then every fleet's open trades."""
        from gridgremlin.trades import TradeError, _botid, load_trades
        from panel.trade_page import open_trades_html, trade_form
        listed, venues = [], []
        for fi, lb in enumerate(self.labels):
            try:
                _f0, _fl, _rows, path = self._trades_of(fi)
                venues.append(_fl.get('venue'))
                trades, _ = load_trades(path, _fl.get('venue'))
            except (TradeError, OSError, ValueError, KeyError):
                trades = []
                if len(venues) <= fi:
                    venues.append(None)
            listed.append((fi, lb, [(_botid(t), t) for t in trades]))
        # D157: the second typing is asked on Mainnet only, so its box shows
        # only when an account here may reach Mainnet (the gate is unchanged)
        real = any(self._mainnet(f, v) for f in self.fleets for v in ('bybit', 'hyperliquid'))
        each = {fi for fi, f in enumerate(self.fleets)
                if any(self._mainnet(f, v) for v in ('bybit', 'hyperliquid'))}
        return trade_form(self.labels, msg, typed, mainnet=real, venues=venues) + open_trades_html(listed, each)

    def _listed(self, fi, symbol):
        """U83: a trade names a market the venue lists — letters and digits,
        and on the venue's own public list (U25) when it can be read; a
        market that does not exist was queued for the fleet to fail on."""
        from gridgremlin.apply import not_listed
        from gridgremlin.trades import TradeError
        if not re.fullmatch(r'[A-Z0-9]+', symbol):
            raise TradeError(f'{symbol or "nothing"}: a market is named in letters and '
                             'digits, like BTCUSDT')
        listed = self._symbols(fi)
        if listed and symbol not in listed:
            raise TradeError(not_listed(symbol, 'the exchange lists no such market '
                                                'for this account — pick one from the list'))

    def _hand_clash(self, fi, cfg, mainnet):
        """L6d (owner 2026-11-10, after opening ETH and SOL by hand on the
        live account): a trade on a market the account already holds by
        hand, no bot running it, is refused — it would join that position
        and take it as its own. On Hyperliquid one position per coin, so
        either side clashes; on Bybit's two-sided books the same side only.
        A bot's or trade's own position is I2's to refuse. On Mainnet an
        account whose positions are not read is refused too: ask more,
        never less."""
        from gridgremlin.apply import make_botid
        from gridgremlin.trades import TradeError
        f = self.fleets[min(fi, len(self.fleets) - 1)]
        data = self._contract(f)
        fig = ((data or {}).get('account') or {}).get(cfg['venue'])
        positions = (fig or {}).get('positions')
        if positions is None:
            if mainnet:
                raise TradeError('the account\'s positions are not read yet, so a position held by hand '
                                 'there cannot be ruled out — try again in a moment')
            return
        ours = set((data or {}).get('bots') or {}) | set((data or {}).get('terms') or {})
        one = cfg['venue'] == 'hyperliquid'
        for pos in positions:
            if pos.get('symbol') != cfg['symbol'] or pos.get('market', 'linear') != cfg['market_type']:
                continue
            if make_botid(cfg['market_type'], cfg['symbol'], pos.get('side', '')) in ours:
                continue
            if one or pos.get('side') == cfg['side']:
                raise TradeError(
                    f"{cfg['symbol']}: the account holds a {pos.get('side')} of {pos.get('size'):g} that no bot "
                    'runs (opened by hand) — '
                    + ('Hyperliquid keeps one position per coin, so ' if one else '')
                    + 'a trade here would join it and take it as its own. Close it, or set its exits '
                      'with manage on its row, first')

    def _trade_typed(self, fi, path, typed):
        """D157: the trade a clear box names — its code, or off Mainnet its
        plain name ("SOLUSDT short trade"); what was typed when neither."""
        from gridgremlin.trades import TradeError, _botid, load_trades
        from ..html_bits import confirmed
        real = any(self._mainnet(self.fleets[min(fi, len(self.fleets) - 1)], v)
                   for v in ('bybit', 'hyperliquid'))
        try:
            trades = load_trades(path)[0]
        except (TradeError, OSError, ValueError):
            trades = []
        return next((_botid(t) for t in trades if confirmed(typed, _botid(t), t, mainnet=real)),
                    (typed or '').strip())

    def _trade_post(self, form):
        """L6: open a trade through the bot validator, or clear an ended one."""
        from gridgremlin.config import ConfigError
        from gridgremlin.trade import build_row
        from gridgremlin.trades import TradeError, add_trade, clear_trade
        fi = int(_f(form.get('fleet')) or 0)
        if form.get('action') == 'change':                      # D157: back to the form, as typed
            return self._page(self._trade_html('', form))
        try:
            f, _fleet, rows, path = self._trades_of(fi)
            if form.get('action') == 'clear':
                botid = self._trade_typed(fi, path, form.get('confirm', ''))   # D157
                if botid and self._live_trade(fi, botid):       # L6b: clear is for a trade that has ended
                    raise TradeError(f'{botid}: still running — close trade first (on its card); '
                                     'clear is for a trade that has ended')
                from gridgremlin.tombstones import path_for
                gone = clear_trade(path, botid, path_for(f, json.loads(Path(f).read_text())))
                if gone is None:
                    raise TradeError(f'{botid or "nothing"}: not a trade in this account\'s file — '
                                     'type its name exactly')
                return self._page(f'<h1>{html.escape(botid)}: cleared</h1>'
                                  '<p><a href="/trade">trades</a></p>')
            opts = {k: form[k] for k in ('capital', 'tp', 'leverage', 'stop', 'trail') if form.get(k, '').strip()}
            if form.get('trail_from', '').strip():
                opts['trail-from'] = form['trail_from']
            if form.get('maker'):
                opts['maker'] = True
            row = build_row(form.get('side', ''), form.get('symbol', ''), opts)
            if _fleet.get('venue') and 'venue' not in row:           # L1b: the account's venue
                row['venue'] = _fleet['venue']
            self._listed(fi, row['symbol'])                     # U83
            if self._mainnet(f, row.get('venue', 'bybit')):              # D64: a trade is a bot (L5)
                from panel.create import retype_refusal
                cap = float(row.get('capital') or 0)
                again = retype_refusal([('capital', None, cap)], form)
                if again:
                    raise TradeError(again)
            if form.get('go') != '1':
                # D157: reviewed in one line before it opens, as a new bot is;
                # the trade validator and the one-per-side rule refuse here first
                from gridgremlin.trades import _botid, load_trades, validate_trade
                from gridgremlin.apply import make_botid
                from panel.trade_page import trade_review
                cfg = validate_trade(row)
                botid = _botid(cfg)
                if botid in {make_botid(c['market_type'], c['symbol'], c['side'])
                             for c in rows if c.get('strategy') != 'portfolio'} | \
                        {_botid(t) for t in load_trades(path, _fleet.get('venue'))[0]}:
                    raise TradeError(f'{botid}: this account already has a bot or a trade on '
                                     f'{cfg["symbol"]} {cfg["side"]} — one position per side of a '
                                     'market per account')
                self._hand_clash(fi, cfg, self._mainnet(f, cfg['venue']))      # L6d
                return self._page(trade_review(cfg, fi, self.labels[min(fi, len(self.labels) - 1)], form))
            from gridgremlin.trades import validate_trade as _vt
            self._hand_clash(fi, _vt(row, venue=_fleet.get('venue')), self._mainnet(f, row.get('venue', 'bybit')))   # L6d
            botid = add_trade(path, rows, row, _fleet.get('venue'))
        except (ConfigError, TradeError, ValueError, OSError) as e:
            return self._page(self._trade_html(refusal_box('trade refused', e), form))
        type(self)._cache.pop(self.fleets[min(fi, len(self.fleets) - 1)], None)   # the next readout shows it
        return self._page(f'<h1>{html.escape(botid)}: queued</h1><p class="say">The account '
                          f'{html.escape(self.labels[min(fi, len(self.labels) - 1)])} opens it within a '
                          'cycle; its card appears with the next readout.</p>'
                          '<p><a href="/">back to your bots</a> <a href="/trade">trades</a></p>')
