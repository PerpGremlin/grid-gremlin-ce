"""Trades (D81): the form, the list, opening and clearing one. Moved out of routes.py whole (D91 step 3): a mixin
the Handler inherits."""
from ..html_bits import refusal_box
from panel.chart import _f
from pathlib import Path
import html
import json


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
        listed = []
        for fi, lb in enumerate(self.labels):
            try:
                _f0, _fl, _rows, path = self._trades_of(fi)
                trades, _ = load_trades(path)
            except (TradeError, OSError, ValueError, KeyError):
                trades = []
            listed.append((fi, lb, [(_botid(t), t) for t in trades]))
        return trade_form(self.labels, msg, typed) + open_trades_html(listed)

    def _trade_post(self, form):
        """L6: open a trade through the bot validator, or clear an ended one."""
        from gridgremlin.config import ConfigError
        from gridgremlin.trade import build_row
        from gridgremlin.trades import TradeError, add_trade, clear_trade
        fi = int(_f(form.get('fleet')) or 0)
        try:
            f, _fleet, rows, path = self._trades_of(fi)
            if form.get('action') == 'clear':
                botid = form.get('confirm', '').strip()
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
            botid = add_trade(path, rows, build_row(form.get('side', ''), form.get('symbol', ''), opts))
        except (ConfigError, TradeError, ValueError, OSError) as e:
            return self._page(self._trade_html(refusal_box('trade refused', html.escape(str(e))), form))
        type(self)._cache.pop(self.fleets[min(fi, len(self.fleets) - 1)], None)   # the next readout shows it
        return self._page(f'<h1>{html.escape(botid)}: queued</h1><p class="say">The fleet '
                          f'{html.escape(self.labels[min(fi, len(self.labels) - 1)])} opens it within a '
                          'cycle; its card appears with the next readout.</p>'
                          '<p><a href="/">back to your bots</a> <a href="/trade">trades</a></p>')
