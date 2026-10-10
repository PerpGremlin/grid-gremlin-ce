"""The panel's stylesheet (U46, U50, U51): one string, the page's whole look."""
import http.server
import os
from pathlib import Path
import urllib.parse
import html
from gridgremlin.report import card_total, money_units
import json
import re
import secrets
import subprocess
import sys
import time
from panel.chart import _f


CSS = """:root{--bg:#14161a;--fg:#d6dae0;--dim:#7a828c;--line:#262a30;
--pos:#5dbb7c;--neg:#d4756b;--accent:#8ab4d8;--accent-soft:#8ab4d82e;
--calm:#5fb3c2;--wild:#e59a4c;
--gap:1em;--gap-s:.5em}
:root.light{--bg:#f5f4f0;--fg:#232629;--dim:#6f6a60;--line:#ddd8d0;
--pos:#2e7d4f;--neg:#b04a40;--accent:#3a6ea5;--accent-soft:#3a6ea524;
--calm:#2f7d8c;--wild:#c26a12}
body{background:var(--bg);color:var(--fg);font:14px/1.5 monospace;margin:2em}
.scroll{overflow-x:auto;max-width:100%}table.fleet{width:100%}table.fleet td,table.fleet th{white-space:nowrap}
table{border-collapse:collapse}td,th{padding:.35em .8em;
text-align:right;border-bottom:1px solid var(--line)}
th{color:var(--dim);font-weight:normal}td:first-child,th:first-child
{text-align:left}.pos{color:var(--pos)}.neg{color:var(--neg)}
.dim{color:var(--dim)}h1{font-size:1.1em;color:var(--accent);margin:var(--gap) 0 var(--gap-s)}
p{margin:var(--gap-s) 0}
input.derived{color:var(--dim);font-style:italic}
.refusal{border:2px solid var(--neg);color:var(--neg);padding:.7em 1em;
margin:0 0 1em;max-width:62em;font-size:1.1em}
.refusal a{color:var(--accent)}
a{color:var(--accent)}
a[href]{display:inline-block;padding:.2em .7em;margin:.15em .2em;background:var(--accent-soft);border:1px solid var(--accent);border-radius:4px;color:var(--fg);text-decoration:none;line-height:1.5}a[href]:hover,a.pick{background:var(--accent);color:var(--bg)}b.on{display:inline-block;padding:.2em .7em;margin:.15em .2em;background:var(--accent);border:1px solid var(--accent);border-radius:4px;color:var(--bg)}a[href*='mode=remove'],a[href^='/close']{border-color:var(--neg)}
.grp{grid-column:1/-1;color:var(--dim);text-align:left;padding-top:.6em;
border-bottom:1px solid var(--line)}
button{background:var(--accent);color:var(--bg);border:0;border-radius:4px;
padding:.45em 1.1em;margin:var(--gap-s) var(--gap-s) var(--gap-s) 0;font:inherit;font-weight:bold;
cursor:pointer}button:hover{filter:brightness(1.15)}
button.quiet{background:var(--accent-soft);border:1px solid var(--accent);color:var(--fg)}
button.theme{margin:var(--gap) 0 0}
details td.wide{text-align:left;white-space:normal;width:auto;padding-top:.4em}
.st{cursor:help;border-bottom:1px dotted var(--dim)}.st-holding{color:var(--accent)}
.st-dead{color:var(--neg)}.st-not-started{color:var(--pos)}.st-resting,.st-flat{color:var(--dim)}
.bar{height:.6em;background:var(--line);border-radius:.3em;max-width:40em;margin:.4em 0}
.bar div{height:100%;background:var(--accent);border-radius:.3em;transition:width .3s}
button.danger{background:var(--neg)}
.side{display:inline-block;font-size:.8em;font-weight:bold;
padding:.05em .55em;border-radius:3px;color:var(--bg);margin-right:.5em;
vertical-align:middle}.side.long{background:var(--pos)}
.side.short{background:var(--neg)}.side.pfo{background:var(--accent)}
.card.long{border-left:4px solid var(--pos)}
.card.short{border-left:4px solid var(--neg)}
.cards{display:grid;gap:var(--gap);
grid-template-columns:repeat(auto-fill,minmax(21em,1fr))}
.card{border:1px solid var(--line);border-radius:6px;padding:.8em 1em;display:flex;flex-direction:column}
.cards.one{grid-template-columns:minmax(0,1fr);max-width:calc(63em + 2*var(--gap))}
.numbers h3,.xch+h3{margin:.5em 0 .2em}table.xch{width:100%;max-width:calc(63em + 2*var(--gap));font-size:.95em}table.xch th{text-align:left;color:var(--dim);font-weight:normal;padding:.1em .5em}table.xch td{padding:.1em .5em;white-space:nowrap}
.card .foot{margin-top:auto;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.3em var(--gap-s)}
.card>div{margin:var(--gap-s) 0}.big{font-size:1.5em}
.pnl{border:1px solid var(--line);border-radius:5px;padding:.45em .75em;
background:color-mix(in srgb,var(--line) 40%,transparent);margin:var(--gap-s) 0}
.pnl.pos{border-color:var(--pos)}.pnl.neg{border-color:var(--neg)}
.tier{font-size:.55em;padding:.1em .45em;border-radius:3px;text-decoration:none;
vertical-align:middle;border:1px solid var(--line)}
.hero{position:sticky;top:0;z-index:5;background:var(--bg);margin:-2em -2em var(--gap);
padding:.45em 2em;border-bottom:1px solid var(--line)}
.hero{display:grid;grid-template-columns:repeat(7,max-content);gap:0 var(--gap);
align-items:baseline}.hero .fleet{display:contents}.hero .num{text-align:right}
.hero .tier{font-size:.75em}.hero .big{font-size:1.15em}.hero .spark svg{vertical-align:middle}
.eqrow{display:grid;grid-template-columns:repeat(auto-fit,minmax(18em,1fr));gap:var(--gap-s) var(--gap);max-width:calc(63em + 2*var(--gap));margin:var(--gap-s) 0}
.eqbox{border:1px solid var(--line);border-radius:5px;padding:.35em .6em}.eqlab{display:flex;gap:var(--gap-s);justify-content:space-between;font-size:.9em}
svg.eq{display:block}svg.px{display:block;max-width:calc(63em + 2*var(--gap));overflow:visible}
svg.px .ax{font-size:11px;fill:var(--dim)}svg.px .ax.neg{fill:var(--neg)}
.pkey{font-size:.9em;margin:.2em 0 var(--gap-s)}.pkey span{display:inline-block;vertical-align:middle;margin:0 .35em 0 .6em}
.k-line{width:1.2em;height:2px;background:var(--accent)}.k-buy,.k-sell{width:.6em;height:.6em;border-radius:50%}
.k-buy{background:var(--pos)}.k-sell{background:var(--neg)}.pnl .rate{color:var(--dim);font-size:.92em}.pnl .rate b{font-weight:normal}
.page{display:grid;grid-template-columns:14em minmax(0,1fr);gap:0 calc(var(--gap)*1.5)}
nav.side{position:sticky;top:0;align-self:start;max-height:100vh;overflow:auto;
padding-right:var(--gap-s);border-right:1px solid var(--line)}
nav.side h3{font-size:1em;font-weight:normal;color:var(--dim);margin:var(--gap) 0 var(--gap-s)}
nav.side h3:first-child{margin-top:var(--gap-s)}
nav.side a[href],nav.side b.on,nav.side a{display:block;margin:.15em var(--gap-s) .15em 0}
@media(max-width:60em){.page{display:block}nav.side{position:static;max-height:none;
border-right:0;border-bottom:1px solid var(--line);margin-bottom:var(--gap);padding:0 0 var(--gap-s)}
nav.side h3{display:inline-block;margin:var(--gap-s) var(--gap-s) var(--gap-s) 0}
nav.side h3::after{content:':'}nav.side a[href],nav.side b.on,nav.side a{display:inline-block}
nav.side button.theme{margin:var(--gap-s) 0 0}}
@media(max-width:40em){body{margin:1em}.hero{margin:-1em -1em var(--gap);padding:.4em 1em;
display:block}.hero .fleet{display:block;padding:.15em 0;border-bottom:1px solid var(--line)}
.hero .fleet>*{display:inline-block;margin-right:.6em;text-align:left}.hero .fleet>span:empty{display:none}}
.tier-test{color:var(--dim)}.tier-main{color:#fff;background:var(--neg);
border-color:var(--neg);font-weight:700}
.pnl .parts{color:var(--dim);font-size:.92em}.pnl .parts b{font-weight:normal}
h1+.pnl{max-width:40em;font-size:1.05em}
.lev-filled{display:none}.lev-on .lev-filled{display:block}.lev-on .lev-now{display:none}
.rng{display:flex;align-items:center;gap:.6em}.rng svg{flex:1}
.card table{width:100%}.card.pfo{grid-column:1/-1;justify-self:start;width:100%;max-width:calc(63em + 2*var(--gap));overflow-wrap:anywhere}
.card.pfo .two{display:grid;grid-template-columns:1fr 1fr;gap:var(--gap-s) var(--gap);align-items:start}.card.pfo .two>div{min-width:0}.card.pfo .pnl{max-width:none}.card td{padding:.1em .4em}
nav.side span.dim{display:block;margin:var(--gap-s) 0 0;font-size:.9em}
details.acct{margin:0}details.acct>summary{color:var(--dim);margin:0 0 var(--gap-s)}
.card details.fold{margin:.2em 0}.card details.fold>summary{color:var(--dim);font-size:.9em}
.card details.fold>summary:hover{color:var(--accent)}
.card details.fold td,.card details.fold th{text-align:right;white-space:nowrap;padding:.1em .4em}
.card details.fold td:first-child,.card details.fold th:first-child{text-align:left;width:auto}
.say{max-width:62em;font-size:1.1em;border-left:3px solid var(--accent);
padding:.2em 1em}details{margin:.6em 0}summary{cursor:pointer;
color:var(--accent)}details td{text-align:left}details td:first-child
{width:22em}input,select{background:var(--bg);color:var(--fg);
border:1px solid var(--line);font:inherit;padding:.15em .3em}
.only-coin .u-value,.only-coin .u-cost,.only-coin .u-sep,.only-value .u-coin,.only-value .u-cost,.only-value .u-sep,.only-cost .u-coin,.only-cost .u-value,.only-cost .u-sep{display:none}
/* U67: the fleet page in two halves — the bots, and the markets beside them */
.split{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:0 calc(var(--gap)*1.5);align-items:start}
.split>.bots{min-width:0}
.markets{position:sticky;top:3.2em;align-self:start;max-height:calc(100vh - 4em);overflow:auto;min-width:0;
padding-left:calc(var(--gap)*1.5);border-left:1px solid var(--line)}
.markets h2{font-size:1.1em;margin:0 0 var(--gap-s)}
.mtiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(19em,1fr));gap:var(--gap);margin-top:var(--gap)}
.mtile{border:1px solid var(--line);border-radius:6px;padding:.6em .8em;display:grid;gap:.25em;font-size:.92em;min-width:0}
.mtile .mhead{font-size:1.1em}.mtile a.plain{display:inline;padding:0;margin:0;background:none;border:0;border-bottom:1px dotted var(--accent);border-radius:0;color:var(--fg)}.mtile a.plain:hover{background:none;color:var(--accent)}.cwtab td,.cwtab th{padding:.2em .7em;text-align:right;white-space:nowrap}.cwtab td:first-child,.cwtab th:first-child{text-align:left}.cwsteps{display:grid;gap:.8em;max-width:62em}.carryform{display:flex;flex-wrap:wrap;gap:.6em 1.2em;align-items:end;margin:.8em 0}.carryform label{display:grid;gap:.2em}.cwsteps code{font-size:.95em}
.mtile svg.mini{display:block;margin:.15em 0}
.calm{color:var(--calm)}.wild{color:var(--wild)}
.gauge{display:inline-block;width:5em;height:.5em;background:var(--line);border-radius:3px;vertical-align:middle;overflow:hidden}
.gauge i{display:block;height:100%;background:var(--wild)}
@media (max-width:860px){.split{display:block}.markets{position:static;max-height:none;overflow:visible;
padding-left:0;border-left:0;border-top:1px solid var(--line);margin-top:calc(var(--gap)*1.5);padding-top:var(--gap)}}
"""
