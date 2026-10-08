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
--gap:1em;--gap-s:.5em}
:root.light{--bg:#f5f4f0;--fg:#232629;--dim:#6f6a60;--line:#ddd8d0;
--pos:#2e7d4f;--neg:#b04a40;--accent:#3a6ea5;--accent-soft:#3a6ea524}
body{background:var(--bg);color:var(--fg);font:14px/1.5 monospace;margin:2em}
table.fleet{table-layout:fixed;width:100%}td{overflow:hidden;text-overflow:ellipsis}
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
.card{border:1px solid var(--line);border-radius:6px;padding:.8em 1em}
.card>div{margin:var(--gap-s) 0}.big{font-size:1.5em}
.pnl{border:1px solid var(--line);border-radius:5px;padding:.45em .75em;
background:color-mix(in srgb,var(--line) 40%,transparent);margin:var(--gap-s) 0}
.pnl.pos{border-color:var(--pos)}.pnl.neg{border-color:var(--neg)}
.tier{font-size:.55em;padding:.1em .45em;border-radius:3px;text-decoration:none;
vertical-align:middle;border:1px solid var(--line)}
.hero{position:sticky;top:0;z-index:5;background:var(--bg);margin:-2em -2em var(--gap);
padding:.45em 2em;border-bottom:1px solid var(--line)}
.hero{display:grid;grid-template-columns:repeat(6,max-content);gap:0 var(--gap);
align-items:baseline}.hero .fleet{display:contents}.hero .num{text-align:right}
.hero .tier{font-size:.75em}.hero .big{font-size:1.15em}
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
grid-template-columns:repeat(3,max-content)}}
.tier-test{color:var(--dim)}.tier-main{color:#fff;background:var(--neg);
border-color:var(--neg);font-weight:700}
.pnl .parts{color:var(--dim);font-size:.92em}.pnl .parts b{font-weight:normal}
h1+.pnl{max-width:40em;font-size:1.05em}
.lev-filled{display:none}.lev-on .lev-filled{display:block}.lev-on .lev-now{display:none}
.rng{display:flex;align-items:center;gap:.6em}.rng svg{flex:1}
.card table{width:100%}.card.pfo{grid-column:1/-1;overflow-wrap:anywhere}.card td{padding:.1em .4em}
.say{max-width:62em;font-size:1.1em;border-left:3px solid var(--accent);
padding:.2em 1em}details{margin:.6em 0}summary{cursor:pointer;
color:var(--accent)}details td{text-align:left}details td:first-child
{width:22em}input,select{background:var(--bg);color:var(--fg);
border:1px solid var(--line);font:inherit;padding:.15em .3em}
.only-coin .u-value,.only-coin .u-cost,.only-coin .u-sep,.only-value .u-coin,.only-value .u-cost,.only-value .u-sep,.only-cost .u-coin,.only-cost .u-value,.only-cost .u-sep{display:none}"""
