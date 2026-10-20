"""The table view (U12): one row per bot. Out of render.py (D91 step 3)."""
from gridgremlin.report import card_total
import time
from .card import _side_tag, settle, slid_range
from .drawings import strip
from .fleet_bits import sweep_note
from .html_bits import REFRESH_S, esc, money, qarg
from .nav import grouped
from .strip_view import tier_badge


COLS = ('<colgroup><col style="width:10%"><col style="width:5%">'
        '<col style="width:4%"><col style="width:7%"><col style="width:5%">'
        '<col style="width:6%">'                            # D63: funding
        '<col style="width:10%"><col style="width:7%"><col style="width:7%">'
        '<col style="width:6%"><col style="width:6%"><col style="width:8%">'
        '<col style="width:7%"><col style="width:8%"><col style="width:8%">'
        '<col style="width:6%"></colgroup>')


def section(idx, label, contract, view='all'):
    age = max(0, int(time.time() - contract['generated_ms'] / 1000))
    rows = []
    belief = ((contract.get('watchdog') or {}).get('belief')
              or {}).get('bots', {})
    ordered = []
    for title, members in grouped(contract, view):
        if title:
            ordered.append((None, title))
        ordered += members
    for botid, b in ordered:
        if botid is None:                      # U12: a group's heading row
            rows.append(f'<tr><th colspan="16" class="grp">{esc(b)}</th></tr>')
            continue
        if b is not None and b.get('realized') is None:
            b = None                     # an inverse book with no mark (the second audit)
        if b is None:
            # no fills in the window — the engine's own belief fills in,
            # and says so (the snapshot is the bot's belief, not the venue)
            bl = belief.get(botid, {})
            alive = bl.get('alive')
            pos = bl.get('position') or 0.0
            state = ('DEAD' if alive is False else
                     'HOLDING' if abs(pos) > 1e-12 else
                     'NOT STARTED' if botid not in belief else 'RESTING')   # as the card says (U34)
            cls = 'neg' if state == 'DEAD' else 'dim'
            wd0 = contract.get('watchdog') or {}
            ceil0 = (wd0.get('ceilings') or {}).get(botid)
            watch0 = (f'<td class="dim">{abs(pos) / ceil0 * 100:.0f}% of '
                      f'{ceil0:,.4g}</td>' if ceil0
                      else '<td class="dim">no limit</td>')
            rows.append(
                f'<tr><td>{_side_tag(botid)}{esc(botid)}</td>'
                f'<td class="{cls}">{state}</td>'
                f'<td class="dim">0</td><td class="dim">no fills</td>'
                f'<td class="dim">—</td><td class="dim">—</td>'   # D63
                f'<td class="dim">'
                + (f'{pos:.10g} (belief)' if abs(pos) > 1e-12 else '—')
                + '</td><td class="dim">—</td><td class="dim">—</td>'
                  '<td class="dim">—</td><td class="dim">—</td>'
                  '<td class="dim">—</td><td class="dim">—</td>'
                  '<td class="dim">—</td>'
                + watch0
                + f"<td class='dim'><a href='/edit?fleet={idx}&amp;bot={qarg(botid)}'>"
                  f"edit</a> <a href='/edit?fleet={idx}&amp;bot={qarg(botid)}"
                  f"&amp;mode=remove'>remove</a> "
                  f"<a href='/setup?fleet={idx}&amp;copy={qarg(botid)}'>copy</a>"
                  "</td></tr>")
            continue
        state = ('DEAD' if (belief.get(botid) or {}).get('alive') is False   # U96: as the card
                 else 'HOLDING' if abs(b['position']) > 1e-12 else 'FLAT')
        openat = (f"{b['position']:.10g} @ {b['avg_cost']:.6g}"
                  if abs(b['position']) > 1e-12 else '—')
        total = card_total(b)                                   # D63
        note = ' *' if b['truncated'] else ''
        rng, slid = slid_range(contract.get('ranges', {}).get(botid), belief.get(botid))   # U96
        floor = contract.get('fee_floors', {}).get(botid)
        wd = contract.get('watchdog') or {}
        ceil = (wd.get('ceilings') or {}).get(botid)
        if ceil:
            used = abs(b['position']) / ceil * 100
            wcls = ' class="neg"' if used >= 100 else ''
            watch = f'<td{wcls}>{used:.0f}% of {ceil:,.4g}</td>'
        else:
            watch = '<td class="dim">no limit</td>'
        edge = ''
        if rng and b['mark']:
            edge = (f"<td>{strip(rng, b['mark'])}</td>"
                    f"<td class='dim'>{(b['mark'] - rng['lower']) / b['mark'] * 100:.1f}%"
                    f" / {(rng['upper'] - b['mark']) / b['mark'] * 100:.1f}%{slid}</td>")
        else:
            edge = '<td class="dim">—</td><td class="dim">—</td>'
        rows.append(
            f'<tr><td>{_side_tag(botid)}{esc(botid)}{note}</td>'
            f'<td class="{"neg" if state == "DEAD" else "dim"}">{state}</td>'
            f"<td>{b['fills']}</td>{money(b['realized'])}"
            f"{money(b['fees'], cls=False)}{money(b.get('funding'))}"
            f"<td>{openat}</td>"
            f"{money(b['unreal_at_mark'])}{money(total)}"
            f"<td>{b['bought']:,.4g}</td><td>{b['sold']:,.4g}</td>"
            f"{edge}<td>{settle(b, floor)}</td>{watch}"
            f"<td class='dim'><a href='/edit?fleet={idx}&amp;bot={qarg(botid)}'>edit"
            f"</a> <a href='/retire?fleet={idx}&amp;bot={qarg(botid)}'>"
            f"retire</a> <a href='/setup?fleet={idx}&amp;copy={qarg(botid)}'>copy</a>"
            "</td></tr>")
    return f"""
<h1 id="fleet{idx}">{esc(label)} {tier_badge(contract)} — last {contract['window_hours']:g}h {sweep_note(contract)}
<span class="dim">(read {age}s ago; refreshes every {REFRESH_S}s)</span></h1>
<div class="scroll"><table class="fleet">{COLS}
<tr><th>bot</th><th>state</th><th>fills</th><th>realized</th>
<th>fees</th><th>funding</th><th>open@avg</th><th>unreal</th><th>total</th>
<th>bought</th><th>sold</th><th>range</th><th>edge lo/hi</th>
<th>stop-now est.</th><th>watcher</th><th></th></tr>
{''.join(rows)}</table></div>
"""
