# The bot drawn on its price (§11): a month of public candles with the bot's
# own levels over it — the range and its rungs, the stop, where following
# the price would trigger; a DCA bot's orders and target.
#
# The SERVER draws: every level comes from the engine's own maths
# (lattice_price, stop_level_for, martingale_schedule), so the picture
# cannot disagree with the plan. The page's script only drags an edge and
# asks for a redraw; it computes no price but the one under the pointer.
# Public data only — no key, no private endpoint.
import html

from gridgremlin.config import ConfigError, validate_config
from gridgremlin.ladder import (lattice_price, martingale_schedule,
                                stop_level_for)

W, H = 900, 300                    # the viewBox; the page scales it
TOP, BOTTOM, RIGHT = 12, 12, 170   # plot margins; labels sit in RIGHT
LABEL_GAP = 12                     # px between stacked labels
MAX_RUNG_LINES = 60


from gridgremlin.fmt import float_or as _f  # noqa: E402  (C10: the one parser)


def levels(cfg, mark):
    """A VALIDATED config -> [(price, kind, label)]. kind is one of
    edge-lower / edge-upper (draggable on the form), rung, stop, trigger,
    order, target."""
    out = []
    long = cfg['side'] == 'long'
    if cfg['strategy'] == 'martingale':
        sign = -1.0 if long else 1.0
        sched = martingale_schedule(cfg)
        for i, (_, dev) in enumerate(sched):
            out.append((mark * (1.0 + sign * dev), 'order',
                        'first order' if i == 0 else
                        ('last add-on' if i == len(sched) - 1 else '')))
        up = 1.0 if long else -1.0
        targets = (cfg.get('take_profit_tranches')
                   or [{'at_avg_pct': cfg['take_profit_avg_pct']}])
        for t in targets:
            out.append((mark * (1.0 + up * t['at_avg_pct']), 'target',
                        'take profit'))
    else:
        n = cfg['rungs']
        every = max(1, -(-n // MAX_RUNG_LINES))
        for j in range(1, n - 1, every):
            out.append((lattice_price(cfg, j), 'rung', ''))
        out.append((cfg['lower'], 'edge-lower', 'lowest'))
        out.append((cfg['upper'], 'edge-upper', 'highest'))
        slide = cfg.get('slide')
        if slide:
            t = slide['trigger_rungs']
            both = slide.get('direction') == 'both'
            if long or both:
                out.append((lattice_price(cfg, n - 1 + t), 'trigger',
                            'follows up'))
            if not long or both:
                out.append((lattice_price(cfg, -t), 'trigger',
                            'follows down'))
    stop = cfg.get('stop') or {}
    if stop.get('watch') == 'mark_price':
        level = (stop_level_for(cfg) if cfg['strategy'] == 'grid'
                 else stop.get('level'))
        if stop.get('from_base_pct') is not None:      # X10: from the base
            level = mark * (1.0 + (-1.0 if long else 1.0)
                            * stop['from_base_pct'])
        if level is not None:
            out.append((level, 'stop', 'stop loss'))
    return out


def form_levels(row, mark):
    """The form as it stands -> (levels, fill). A row the engine accepts is
    drawn in full; an unfinished grid still shows the edges it has, and a
    grid with no range yet is offered one around today's price (`fill`:
    the values the page puts in the empty boxes)."""
    try:
        return levels(validate_config(dict(row)), mark), {}
    except ConfigError:
        pass
    if row.get('strategy') == 'martingale':
        return [], {}
    lo, hi = _f(row.get('lower')), _f(row.get('upper'))
    fill = {}
    if lo is None and hi is None and mark:
        lo, hi = float(f'{mark * 0.9:.5g}'), float(f'{mark * 1.1:.5g}')
        fill = {'lower': lo, 'upper': hi}
    out = []
    if lo is not None:
        out.append((lo, 'edge-lower', 'lowest'))
    if hi is not None:
        out.append((hi, 'edge-upper', 'highest'))
    return out, fill


def _p(v):
    return f'{v:,.6g}'


def chart_svg(bars, lines, mark=None, drag=False, fill=None):
    """Bars oldest first; lines from levels(). drag=True marks the two
    edges for the page's script and carries the y-scale it needs."""
    if not bars:
        return '<p class="dim">no price history for this market.</p>'
    prices = ([b['h'] for b in bars] + [b['l'] for b in bars]
              + [p for p, _, _ in lines] + ([mark] if mark else []))
    lo, hi = min(prices), max(prices)
    pad = (hi - lo) * 0.06 or hi * 0.01
    ymin, ymax = lo - pad, hi + pad
    plot_w, plot_h = W - RIGHT, H - TOP - BOTTOM

    def y(p):
        return TOP + (ymax - p) / (ymax - ymin) * plot_h

    def x(i):
        return i / max(1, len(bars) - 1) * plot_w

    band = (' '.join(f'{x(i):.1f},{y(b["h"]):.1f}'
                     for i, b in enumerate(bars)) + ' '
            + ' '.join(f'{x(i):.1f},{y(b["l"]):.1f}'
                       for i, b in reversed(list(enumerate(bars)))))
    close = ' '.join(f'{x(i):.1f},{y(b["c"]):.1f}'
                     for i, b in enumerate(bars))
    parts = [f'<polygon points="{band}" fill="var(--line)"/>',
             f'<polyline points="{close}" fill="none" '
             'stroke="var(--fg)" stroke-width="1.2"/>']
    style = {'rung': ('var(--dim)', '0.4', ''),
             'edge-lower': ('var(--accent)', '1.6', ''),
             'edge-upper': ('var(--accent)', '1.6', ''),
             'stop': ('var(--neg)', '1.4', ''),
             'trigger': ('var(--accent)', '1', '6 4'),
             'order': ('var(--accent)', '0.8', ''),
             'target': ('var(--pos)', '1.4', '')}
    # labels of lines that sit close together are stacked, not overprinted:
    # each keeps its line and takes the nearest free slot down the margin
    labelled = sorted([(y(p), p, 'now') for p in ([mark] if mark else [])]
                      + [(y(p), p, k) for p, k, _ in lines if k != 'rung'])
    slot, last = {}, None
    for ly, p, k in labelled:
        last = ly if last is None else max(ly, last + LABEL_GAP)
        slot[(p, k)] = last
    floor = H - 4
    for ly, p, k in reversed(labelled):       # and back up off the bottom
        if slot[(p, k)] > floor:
            slot[(p, k)] = floor
        floor = slot[(p, k)] - LABEL_GAP

    def dy(p, k):
        return 4 + slot[(p, k)] - y(p)
    for price, kind, label in lines:
        colour, width, dash = style[kind]
        dash = f' stroke-dasharray="{dash}"' if dash else ''
        text = (f'<text x="{plot_w + 6}" y="{dy(price, kind):.1f}" '
                f'fill="{colour}" font-size="11">{_p(price)}'
                + (f' {html.escape(label)}' if label else '') + '</text>'
                if kind != 'rung' else '')
        handle = ''
        if drag and kind.startswith('edge-'):
            handle = (f' class="drag" data-field="{kind[5:]}" '
                      'style="cursor:ns-resize"')
            text += (f'<rect x="0" y="-9" width="{plot_w}" height="18" '
                     'fill="transparent"/>')
        parts.append(
            f'<g{handle} transform="translate(0,{y(price):.1f})">'
            f'<line x1="0" y1="0" x2="{plot_w}" y2="0" stroke="{colour}" '
            f'stroke-width="{width}"{dash}/>{text}</g>')
    if mark:
        parts.append(
            f'<g transform="translate(0,{y(mark):.1f})"><line x1="0" y1="0" '
            f'x2="{plot_w}" y2="0" stroke="var(--fg)" stroke-width="0.6" '
            f'stroke-dasharray="2 3"/><text x="{plot_w + 6}" '
            f'y="{dy(mark, "now"):.1f}" fill="var(--fg)" font-size="11">'
            f'{_p(mark)} now</text></g>')
    data = (f' data-ymin="{ymin:.10g}" data-ymax="{ymax:.10g}" '
            f'data-top="{TOP}" data-ploth="{plot_h}" data-h="{H}"')
    for key, value in (fill or {}).items():
        data += f' data-fill-{key}="{value:.10g}"'
    return (f'<svg viewBox="0 0 {W} {H}" width="100%"{data} '
            'style="max-width:62em;touch-action:none">'
            + ''.join(parts) + '</svg>')


# The whole script: drag an edge, write its price in the box, ask the
# server to draw again. No price maths beyond the pointer's own position.
CHART_JS = """<script>(function(){
var box=document.getElementById('chart');if(!box)return;
var form=box.closest('form');
function field(n){return form.querySelector('[name="'+n+'"]');}
function sig(v){return Number(v.toPrecision(5));}
function wire(){
 var svg=box.querySelector('svg');if(!svg)return;
 var d=svg.dataset,ymin=+d.ymin,ymax=+d.ymax,top=+d.top,ph=+d.ploth,h=+d.h;
 ['lower','upper'].forEach(function(n){
  var v=d['fill'+n.charAt(0).toUpperCase()+n.slice(1)],i=field(n);
  if(v&&i&&!i.value)i.value=v;});
 svg.querySelectorAll('.drag').forEach(function(g){
  g.addEventListener('pointerdown',function(ev){
   ev.preventDefault();g.setPointerCapture(ev.pointerId);
   var txt=g.querySelector('text'),price=null;
   function move(e){
    var r=svg.getBoundingClientRect();
    var y=Math.max(top,Math.min(top+ph,(e.clientY-r.top)/r.height*h));
    price=sig(ymax-(y-top)/ph*(ymax-ymin));
    g.setAttribute('transform','translate(0,'+y.toFixed(1)+')');
    if(txt)txt.textContent=price.toLocaleString();}
   function up(){
    g.removeEventListener('pointermove',move);
    g.removeEventListener('pointerup',up);
    if(price!==null){field(g.dataset.field).value=price;redraw();}}
   g.addEventListener('pointermove',move);
   g.addEventListener('pointerup',up);});});}
function redraw(){
 fetch('/chart',{method:'POST',credentials:'same-origin',
  body:new URLSearchParams(new FormData(form))})
 .then(function(r){return r.text();})
 .then(function(t){box.innerHTML=t;wire();});}
form.addEventListener('change',redraw);redraw();})();</script>"""

CHART_BOX = ('<div id="chart"><p class="dim">the price chart draws here '
             'once a coin is typed.</p></div><p class="dim">dragging an '
             'edge only fills in its box below. Nothing changes on a '
             'running bot until you apply the summary and the fleet is '
             'restarted.</p>')
