"""The owner's door onto trades on the panel (SPEC L6, D81): one form for a
single long or short with its exit, the trades open in each fleet, and the
clear of a finished one. Every number meets the bot validator, through the
same `gridgremlin.trades` the command line and the agent's door use."""
import html


def trade_form(labels, msg='', typed=None):
    """The form, refilled with what was typed when a trade is refused."""
    t = typed or {}

    def v(k, d=''):
        return html.escape(str(t.get(k, d)), quote=True)
    fleets = ''.join(f'<option value="{i}"{" selected" if str(i) == str(t.get("fleet", "")) else ""}>'
                     f'{html.escape(lb)}</option>' for i, lb in enumerate(labels))
    side = t.get('side', 'long')
    return (f'<h1>new trade <span class="dim">— one long or short with its exit (D81)</span></h1>{msg}'
            '<form method="post" action="/trade"><input type="hidden" name="gg" value="1">'
            '<input type="hidden" name="action" value="open"><table>'
            f'<tr><td>account</td><td><select name="fleet">{fleets}</select></td></tr>'
            '<tr><td>side</td><td><select name="side">'
            f'<option{" selected" if side == "long" else ""}>long</option>'
            f'<option{" selected" if side == "short" else ""}>short</option></select></td></tr>'
            f'<tr><td>market</td><td><input name="symbol" value="{v("symbol", "BTCUSDT")}" size="14"> '
            '<span class="dim">a perp like BTCUSDT</span></td></tr>'
            f'<tr><td>investment</td><td><input name="capital" value="{v("capital")}" size="10"> '
            '<span class="dim">the margin, in the quote coin</span></td></tr>'
            f'<tr><td>leverage</td><td><input name="leverage" value="{v("leverage", "1")}" size="6">x</td></tr>'
            f'<tr><td>take profit</td><td><input name="tp" value="{v("tp")}" size="6">% '
            '<span class="dim">beyond the entry — required: a trade is never without its exit</span></td></tr>'
            f'<tr><td>stop</td><td><input name="stop" value="{v("stop")}" size="6">% '
            '<span class="dim">against the entry, watched at the mark each cycle — blank for none</span></td></tr>'
            f'<tr><td>trailing</td><td><input name="trail" value="{v("trail")}" size="6">% '
            f'from <input name="trail_from" value="{v("trail_from")}" size="6">% '
            '<span class="dim">optional: follows the price once it is that far in profit</span></td></tr>'
            '<tr><td>entry</td><td><label><input type="checkbox" name="maker" value="1"'
            f'{" checked" if t.get("maker") else ""}> as a maker order</label> '
            '<span class="dim">unticked: at market</span></td></tr>'
            '</table><button>open the trade</button></form>'
            '<p class="dim">The fleet opens it within a cycle; its card appears with the next '
            'readout. A market and side another bot of the account holds is refused — the '
            'exchange keeps one position per side of a market per account.</p>')


def open_trades_html(rows_by_fleet):
    """[(fleet index, label, [(botid, trade cfg)])] as one table with a clear
    box per row — clearing is for a trade that has ended."""
    rows = ''.join(
        f"<tr><td class='dim'>{html.escape(lb)}</td><td>{html.escape(b)}</td>"
        f"<td>{html.escape(t['side'])} {html.escape(t['symbol'])} {t['capital']:g} at {t['leverage']:g}x</td>"
        f"<td class='dim'>tp {(t.get('take_profit_avg_pct') or 0) * 100:g}% · stop "
        f"{((t.get('stop') or {}).get('from_base_pct') or 0) * 100:g}% · "
        f"{html.escape(str((t.get('_record') or {}).get('opened', '?')))} by "
        f"{html.escape(str((t.get('_record') or {}).get('by', '?')))}</td>"
        f"<td><form method='post' action='/trade' style='margin:0'><input type='hidden' name='gg' value='1'>"
        f"<input type='hidden' name='action' value='clear'><input type='hidden' name='fleet' value='{fi}'>"
        f"<input name='confirm' size='14' placeholder='{html.escape(b, quote=True)}'>"
        f"<button class='quiet'>clear</button></form></td></tr>"
        for fi, lb, trades in rows_by_fleet for b, t in trades)
    return ('<h1>trades in the files</h1><p class="dim">a trade ends itself at its take profit or '
            'stop; <b>close position</b> on its card ends it early. Clear one that has ended, by '
            'typing its name, to open another on that market and side.</p>'
            '<table><tr><th>account</th><th>trade</th><th>terms</th><th>exit · opened</th><th></th></tr>'
            + (rows or '<tr><td class="dim" colspan="5">no trades</td></tr>') + '</table>')
