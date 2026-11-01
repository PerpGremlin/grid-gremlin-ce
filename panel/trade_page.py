"""The owner's door onto trades on the panel (SPEC L6, D81): one form for a
single long or short with its exit, the trades open in each fleet, and the
clear of a finished one. Every number meets the bot validator, through the
same `gridgremlin.trades` the command line and the agent's door use."""
import html


def trade_form(labels, msg='', typed=None, mainnet=False):
    """The form, refilled with what was typed when a trade is refused.
    `mainnet`: an account here may reach Mainnet, where the investment is
    typed twice (D64); off it the second box is not shown (D157)."""
    t = typed or {}

    def v(k, d=''):
        return html.escape(str(t.get(k, d)), quote=True)
    fleets = ''.join(f'<option value="{i}"{" selected" if str(i) == str(t.get("fleet", "")) else ""}>'
                     f'{html.escape(lb)}</option>' for i, lb in enumerate(labels))
    side = t.get('side', 'long')
    # U88: three columns like the setup forms — the label, the value box with
    # its unit beside it, the description — in a box of their own
    def row(label, box, say='', unit=''):
        return (f'<tr><td>{label}</td><td><span class="u">{box}<i class="un">{unit}</i></span></td>'
                f'<td class="dim">{say}</td></tr>')
    return (f'<h1>new trade <span class="dim">— one long or short with its exit</span></h1>{msg}'
            '<form method="post" action="/trade"><input type="hidden" name="gg" value="1">'
            '<input type="hidden" name="action" value="open"><div class="fsec"><table>'
            + row('account', f'<select name="fleet">{fleets}</select>', 'the account the trade joins')
            + row('side', '<select name="side">'
                  f'<option{" selected" if side == "long" else ""}>long</option>'
                  f'<option{" selected" if side == "short" else ""}>short</option></select>')
            + row('market', f'<input name="symbol" value="{v("symbol", "BTCUSDT")}" size="14">', 'a perp like BTCUSDT')
            + row('investment', f'<input name="capital" value="{v("capital")}" size="10">',
                  'the margin, in the quote coin')
            + (row('investment, again', f'<input name="retype_capital" value="" size="10">',
                   'on Mainnet only: type it a second time') if mainnet else '')
            + row('leverage', f'<input name="leverage" value="{v("leverage", "1")}" size="6">', unit='x')
            + row('take profit', f'<input name="tp" value="{v("tp")}" size="6">',
                  'beyond the entry — required: a trade is never without its exit', unit='%')
            + row('stop', f'<input name="stop" value="{v("stop")}" size="6">',
                  'against the entry, watched at the mark each cycle — blank for none', unit='%')
            + row('trailing', f'<input name="trail" value="{v("trail")}" size="6">% from '
                  f'<input name="trail_from" value="{v("trail_from")}" size="6">',
                  'optional: follows the price once it is that far in profit', unit='%')
            + row('entry', '<label><input type="checkbox" name="maker" value="1"'
                  f'{" checked" if t.get("maker") else ""}> as a maker order</label>', 'unticked: at market')
            + '</table></div><button>review the trade</button></form>'
            '<p class="dim">It is reviewed in one line first; once opened, its account places '
            'it within a cycle, and its card appears with the next readout. A market and side another bot of the account holds is refused — the '
            'exchange keeps one position per side of a market per account.</p>')


def open_trades_html(rows_by_fleet, real=()):
    """[(fleet index, label, [(botid, trade cfg)])] as one table with a clear
    box per row — clearing is for a trade that has ended. D157: the box
    shows the trade's plain name, and its code is taken too; on an account
    that may reach Mainnet (its index in `real`) only the code, as before."""
    from .html_bits import accepts, confirm_dialog, to_type, typed_name, typed_inline
    rows = ''.join(
        f"<tr><td class='dim'>{html.escape(lb)}</td><td>{html.escape(b)}</td>"
        f"<td>{html.escape(t['side'])} {html.escape(t['symbol'])} {t['capital']:g} at {t['leverage']:g}x</td>"
        f"<td class='dim'>tp {(t.get('take_profit_avg_pct') or 0) * 100:g}% · stop "
        f"{((t.get('stop') or {}).get('from_base_pct') or 0) * 100:g}% · "
        f"{html.escape(str((t.get('_record') or {}).get('opened', '?')))} by "
        f"{html.escape(str((t.get('_record') or {}).get('by', '?')))}</td>"
        f"<td><form method='post' action='/trade' style='margin:0'><input type='hidden' name='gg' value='1'>"
        f"<input type='hidden' name='action' value='clear'><input type='hidden' name='fleet' value='{fi}'>"
        + typed_inline(f"type <code>{html.escape(said)}</code> "
                       "<input name='confirm' size='18' autocomplete='off'>")
        + confirm_dialog(                                       # D159: the pop-up
            f'Clear the ended trade {said} on {lb}, so another can open on its market and side.',
            to_type(b, t, fi in real), accepts(b, t, fi in real), 'clear')
        + "<button class='quiet'>clear</button></form></td></tr>"
        for fi, lb, trades in rows_by_fleet for b, t in trades
        for said in [(None if fi in real else typed_name(t)) or b])
    return ('<h1>your trades</h1><p class="dim">a trade ends itself at its take profit or '
            'stop; <b>close trade</b> on its card ends it early. Clear one that has ended, by '
            'typing its name (or its code), to open another on that market and side.</p>'
            '<div class="fsec"><table><tr><th>account</th><th>trade</th><th>terms</th><th>exit · opened</th><th></th></tr>'
            + (rows or '<tr><td class="dim" colspan="5">no trades</td></tr>') + '</table></div>')


def trade_line(cfg):
    """D157: a trade in one line, as the new-bot review says a bot in
    plain words: "Long BTCUSDT, 100 USDT at 5x, take profit +2%, stop −1%,
    at market." From the validated row, so it says what the fleet opens."""
    from gridgremlin.report import money_units
    quote = money_units(None, cfg.get('market_type', 'linear'), cfg['symbol'])['quote']
    parts = [f"{cfg['side'].capitalize()} {cfg['symbol']}, {cfg['capital']:,.10g} {quote} "
             f"at {cfg.get('leverage') or 1:g}x",
             f"take profit +{(cfg.get('take_profit_avg_pct') or 0) * 100:g}%"]
    stop = (cfg.get('stop') or {}).get('from_base_pct')
    parts.append(f'stop −{stop * 100:g}%' if stop else 'no stop')
    if cfg.get('trailing_stop_pct'):
        parts.append(f"trailing {cfg['trailing_stop_pct'] * 100:g}%"
                     + (f" from +{cfg['trailing_activation_pct'] * 100:g}%"
                        if cfg.get('trailing_activation_pct') else ''))
    parts.append('as a maker order' if cfg.get('start_order_type') == 'maker' else 'at market')
    return ', '.join(parts[:-1]) + ', ' + parts[-1] + '.'


def trade_review(cfg, fi, label, form):
    """D157: "new trade" reviewed before it opens, as "new bot" is: the one
    line, then open it or change something. Every field typed rides along,
    the Mainnet second typing with them, and is checked again at the open."""
    keep = ('fleet', 'side', 'symbol', 'capital', 'retype_capital', 'leverage', 'tp',
            'stop', 'trail', 'trail_from', 'maker')
    hidden = ''.join(f'<input type="hidden" name="{k}" value="{html.escape(str(form[k]), quote=True)}">'
                     for k in keep if form.get(k) not in (None, ''))
    return (f'<h1>new trade <span class="dim">— review</span></h1>'
            f'<div class="fsec"><h1 class="dim">in plain words</h1><p class="say">'
            f'{html.escape(trade_line(cfg))}</p><p class="dim">on {html.escape(str(label))}; the '
            'account opens it within a cycle of the press, and it ends itself at its take profit '
            'or stop.</p>'
            '<form method="post" action="/trade"><input type="hidden" name="gg" value="1">'
            f'<input type="hidden" name="action" value="change">{hidden}'
            '<button class="quiet">change something</button></form></div>'
            '<div class="fsec go"><form method="post" action="/trade" class="apply">'
            '<input type="hidden" name="gg" value="1"><input type="hidden" name="action" value="open">'
            f'<input type="hidden" name="go" value="1">{hidden}'
            '<button>open the trade</button></form></div>')
