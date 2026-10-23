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


CSS = """/* U86: the site's look (terminalgremlin) — its green on near-black, and
every part in a box with a thick edge (--edge) */
:root{--bg:#0b0f0c;--fg:#d7e4da;--dim:#7c8c80;--line:#1c2620;--edge:#2c3d31;
--pos:#36d17a;--neg:#e5534b;--accent:#36d17a;--accent-soft:#36d17a26;
--calm:#5fb3c2;--wild:#e59a4c;--s3:#b48ef0;
--gap:1em;--gap-s:.5em;--hero:3.2em;--bw:2px}
:root.light{--bg:#f3f5f1;--fg:#1d2620;--dim:#5f6d63;--line:#d5ddd6;--edge:#a9b8ac;
--pos:#1f8a4c;--neg:#c0392b;--accent:#1f8a4c;--accent-soft:#1f8a4c24;
--calm:#2f7d8c;--wild:#c26a12;--s3:#7a4fc4}
html{background:var(--bg)}
body{background:var(--bg);color:var(--fg);font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;margin:2em}
section.fbox{border:var(--bw) solid var(--edge);border-radius:8px;padding:0 1em .6em;margin:0 0 calc(var(--gap)*1.5)}
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
a[href]{display:inline-block;padding:.2em .7em;margin:.15em .2em;background:var(--accent-soft);border:1px solid var(--accent);border-radius:4px;color:var(--fg);text-decoration:none;line-height:1.5}a[href]:hover,a.pick{background:var(--accent);color:var(--bg)}b.on{display:inline-block;padding:.2em .7em;margin:.15em .2em;background:var(--accent);border:1px solid var(--accent);border-radius:4px;color:var(--bg)}a[href*='mode=remove'],a[href^='/retire'],a[href^='/close']{border-color:var(--neg)}
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
.card.long{border-left:5px solid var(--pos)}
.card.short{border-left:5px solid var(--neg)}
.cards{display:grid;gap:var(--gap);
grid-template-columns:repeat(auto-fill,minmax(21em,1fr))}
.card{border:var(--bw) solid var(--edge);border-radius:8px;padding:.65em .8em;display:flex;flex-direction:column}
.cards.one{grid-template-columns:minmax(0,1fr);max-width:calc(63em + 2*var(--gap))}
.numbers h3,.xch+h3{margin:.5em 0 .2em}table.xch{width:100%;max-width:calc(63em + 2*var(--gap));font-size:.95em}table.xch th{text-align:left;color:var(--dim);font-weight:normal;padding:.1em .5em}table.xch td{padding:.1em .5em;white-space:nowrap}
.card .foot{margin-top:auto;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.3em var(--gap-s)}
.card>div{margin:var(--gap-s) 0}.big{font-size:1.5em}
.pnl{border:var(--bw) solid var(--edge);border-radius:6px;padding:.45em .75em;
background:color-mix(in srgb,var(--line) 40%,transparent);margin:var(--gap-s) 0}
.pnl.pos{border-color:var(--pos)}.pnl.neg{border-color:var(--neg)}
.tier{font-size:.55em;padding:.1em .45em;border-radius:3px;text-decoration:none;
vertical-align:middle;border:1px solid var(--edge)}
.hero{position:sticky;top:0;z-index:5;background:var(--bg);margin:-2em -2em var(--gap);
padding:.45em 2em;border-bottom:var(--bw) solid var(--edge)}
.hero{display:grid;grid-template-columns:repeat(7,max-content);gap:0 var(--gap);
align-items:baseline}.hero .fleet{display:contents}.hero .num{text-align:right}
.hero .tier{font-size:.75em}.hero .big{font-size:1.15em}.hero .spark svg{vertical-align:middle}
.eqrow{display:grid;grid-template-columns:repeat(auto-fit,minmax(18em,1fr));gap:var(--gap-s) var(--gap);max-width:calc(63em + 2*var(--gap));margin:var(--gap-s) 0}
.eqsw{display:block;max-width:36em}.eqsw>.eqwin{display:none}.eqsw>input:nth-of-type(1):checked~.eqwin:nth-of-type(1){display:block}.eqsw>input:nth-of-type(2):checked~.eqwin:nth-of-type(2){display:block}.eqsw>input:nth-of-type(3):checked~.eqwin:nth-of-type(3){display:block}.eqsw>input:nth-of-type(4):checked~.eqwin:nth-of-type(4){display:block}.eqnext{cursor:pointer}.eqgo{float:right;color:var(--accent)}.eqnext:hover .eqgo{text-decoration:underline}
.eqnote{max-width:63em;font-size:.88em;margin:0 0 var(--gap-s)}
.eqbox{border:var(--bw) solid var(--edge);border-radius:6px;padding:.35em .6em}.eqlab{display:flex;gap:var(--gap-s);justify-content:space-between;font-size:.9em}
svg.eq{display:block}svg.px{display:block;max-width:calc(63em + 2*var(--gap));overflow:visible}
svg.px .ax{font-size:11px;fill:var(--dim)}svg.px .ax.neg{fill:var(--neg)}
.pkey{font-size:.9em;margin:.2em 0 var(--gap-s)}.pkey span{display:inline-block;vertical-align:middle;margin:0 .35em 0 .6em}
.k-line{width:1.2em;height:2px;background:var(--accent)}.k-buy,.k-sell{width:.6em;height:.6em;border-radius:50%}
.k-buy{background:var(--pos)}.k-sell{background:var(--neg)}.pnl .rate{color:var(--dim);font-size:.92em}.pnl .rate b{font-weight:normal}
.page{display:grid;grid-template-columns:14em minmax(0,1fr);gap:0 calc(var(--gap)*1.5)}
nav.side{position:sticky;top:var(--hero);align-self:start;max-height:calc(100vh - var(--hero));overflow:auto;
padding-right:var(--gap-s);border-right:var(--bw) solid var(--edge)}
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
.pnl .split{display:grid;grid-template-columns:auto auto;justify-content:start;column-gap:1.2em;color:var(--dim);font-size:.92em;margin:.2em 0}.pnl .split b{font-weight:normal}.pnl .split .num{text-align:right}.pnl .split span:nth-child(5)+span b{color:var(--fg)}
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
{width:22em}details td.dim{min-width:18em}table.ladder td:not(:first-child),table.ladder th:not(:first-child){text-align:right;font-variant-numeric:tabular-nums}details select{max-width:18em}input,select{background:var(--bg);color:var(--fg);
border:1px solid var(--edge);border-radius:3px;font:inherit;padding:.15em .3em}
.only-coin .u-value,.only-coin .u-cost,.only-coin .u-sep,.only-value .u-coin,.only-value .u-cost,.only-value .u-sep,.only-cost .u-coin,.only-cost .u-value,.only-cost .u-sep{display:none}
/* U67: the fleet page in two halves — the bots, and the markets beside them */
.split{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:0 calc(var(--gap)*1.5);align-items:start}
.split>.bots{min-width:0}
/* U86: pinned where it starts — its top is the strip's height plus the gap
under it, so it never slides as the left half scrolls */
.pane{position:sticky;top:calc(var(--hero) + var(--gap));align-self:start;max-height:calc(100vh - var(--hero) - 2*var(--gap));overflow:auto;overscroll-behavior:contain;min-width:0;
padding:.2em 1em .8em;border:var(--bw) solid var(--edge);border-radius:8px}
.pane h2{font-size:1.1em;margin:0 0 var(--gap-s)}
.pane a.plain{font-size:.8em;font-weight:normal;margin-left:.6em}
.ptabs{display:flex;flex-wrap:wrap;gap:.2em;margin:.4em 0 .8em}
a.bname{display:inline;padding:0;margin:0;background:none;border:0;border-bottom:1px dotted var(--accent);border-radius:0;color:inherit;line-height:inherit}a.bname:hover{background:none;color:var(--accent)}
table.fills{border-collapse:collapse;font-size:.9em;width:100%}
table.fills td,table.fills th{padding:.15em .5em;text-align:right;white-space:nowrap;border-bottom:1px solid var(--line)}
table.fills td:nth-child(-n+3),table.fills th:nth-child(-n+3){text-align:left}
table.fills td:nth-child(3){white-space:normal}
.pane{container-type:inline-size}.pane table.fills:not(.trades){font-size:clamp(.68rem,2.05cqi,.9em)}
.pane table.fund{font-size:clamp(.68rem,2.05cqi,.9em)}.pane table.fund :is(td,th){padding:.15em .35em;white-space:nowrap;text-align:right}
.pane table.fund th[colspan]{text-align:center}.pane table.fund td:first-child{min-width:0;text-align:left}
table.fills:is(.trades,.bot) td{vertical-align:top}.pane table.fills:is(.trades,.bot) :is(td,th){padding:.15em .3em}table.fills.bot td:nth-child(2){white-space:nowrap}table.fills.bot td:nth-child(3){text-align:right}table.fills.bot th:nth-child(3){text-align:right}table.fills.trades td:nth-child(2){white-space:normal}table.fills.trades td:nth-child(3){white-space:nowrap}
.pane table:not(.fills) td,.pane table:not(.fills) th{white-space:normal;overflow-wrap:break-word}.pane table:not(.fills) td:first-child{min-width:7em}.pane form input,.pane form select{max-width:16em;box-sizing:border-box}.pane details td:first-child{width:auto}.pane details td.dim{min-width:0}
.cwtab td,.cwtab th{padding:.2em .7em;text-align:right;white-space:nowrap}.cwtab td:first-child,.cwtab th:first-child{text-align:left}.carryform{display:flex;flex-wrap:wrap;gap:.6em 1.2em;align-items:end;margin:.8em 0}.carryform label{display:grid;gap:.2em}
.pane h3{font-size:.95em;margin:1.2em 0 .4em;color:var(--accent)}
/* U85: the overview — the book by coin as two half-bars from a middle line */
table.ov{border-collapse:collapse;font-size:.9em;width:100%}table.ov td,table.ov th{padding:.15em .5em;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
table.ov td:first-child,table.ov th:first-child{text-align:left}.pane table.ov td:first-child{min-width:3em}
table.ov td.xcell{width:40%}.xbar{display:flex;height:.7em}.xh{flex:1;display:flex}.xleft{justify-content:flex-end;border-right:2px solid var(--line)}
.xbar i{display:block;height:100%}.xbar .xs{background:var(--neg);border-radius:3px 0 0 3px}.xbar .xl{background:var(--pos);border-radius:0 3px 3px 0}
table.moods td{text-align:left;white-space:normal}
ul.watch{margin:.3em 0;padding-left:1.2em}ul.watch li{margin:.2em 0;color:var(--neg)}
.calm{color:var(--calm)}.wild{color:var(--wild)}
.gauge{display:inline-block;width:5em;height:.5em;background:var(--line);border-radius:3px;vertical-align:middle;overflow:hidden}
.gauge i{display:block;height:100%;background:var(--wild)}
/* U87: the polish pass — the heading's quiet line, the card's buttons in a
row of their own, the side menu boxed like the right half, small spaced
section labels, the right half's sections ruled, and the small things
(a card's edge lit on hover, numbers in columns, scrollbars, selection, focus) */
h1 .meta{display:block;font-size:.78em;font-weight:normal;margin-top:.15em}
.card .foot>span:last-child{display:flex;flex-wrap:wrap;gap:.25em}.card .foot a[href]{margin:0}
.card:hover{border-color:var(--accent)}.card.long:hover{border-left-color:var(--pos)}.card.short:hover{border-left-color:var(--neg)}
nav.side{border:var(--bw) solid var(--edge);border-radius:8px;padding:.2em .8em .8em}
nav.side h3,.pane h3{text-transform:uppercase;letter-spacing:.08em;font-size:.75em}
.pane h3{border-top:1px solid var(--edge);padding-top:.8em;margin-top:1em}
.pane h2{border-bottom:var(--bw) solid var(--edge);padding:.5em 0;margin-bottom:.6em}
body{font-variant-numeric:tabular-nums}
*{scrollbar-width:thin;scrollbar-color:var(--edge) transparent}
::selection{background:var(--accent);color:var(--bg)}
a[href]:focus-visible,button:focus-visible,summary:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
/* U88: every form's rows on one grid — the label, the value box and its
description start at the same place in every section (each section was its
own table, sized to its own words); the value boxes one width; a form's
sections each a box of their own, as the site boxes each part */
:is(form,.fakeform) table{width:100%;max-width:72em}:is(form,.fakeform) td,:is(form,.fakeform) th{text-align:left}
:is(form,.fakeform) td:first-child:nth-last-child(3),:is(form,.fakeform) td:first-child:nth-last-child(2){width:17em}
:is(form,.fakeform) td:nth-child(2):nth-last-child(2){width:15em}
:is(form,.fakeform) td:nth-child(2):nth-last-child(2) input:not([type=checkbox]):not([type=radio]),
:is(form,.fakeform) td:nth-child(2):nth-last-child(2) select,.fakeform td:nth-child(2):nth-last-child(2) .fin{width:100%;max-width:none;box-sizing:border-box}
:is(form,.fakeform) td:last-child:nth-child(3){white-space:normal;min-width:0}
.pane :is(form,.fakeform) td:first-child:nth-last-child(3){width:9em}.pane :is(form,.fakeform) td:nth-child(2):nth-last-child(2){width:10em}
:is(form,.fakeform)>details,.fsec{border:var(--bw) solid var(--edge);border-radius:8px;padding:.35em 1em .6em;margin:.8em 0;max-width:72em}
:is(form,.fakeform)>details>summary{font-weight:bold;padding:.15em 0}:is(form,.fakeform)>details[open]>summary{border-bottom:1px solid var(--edge);margin-bottom:.4em;padding-bottom:.4em}
:is(form,.fakeform)>details>table,.fsec>table{max-width:none}
:is(form,.fakeform) td .u{display:flex;align-items:center;gap:.35em}:is(form,.fakeform) td .u input:not([type=checkbox]){flex:1;min-width:0;width:auto}
:is(form,.fakeform) td .u label{display:flex;align-items:center;gap:.35em}.fsec>table{width:100%}
.carryform{border:var(--bw) solid var(--edge);border-radius:8px;padding:.7em 1em;max-width:72em;box-sizing:border-box}
.carryform input:not([type=checkbox]),.carryform select{width:9em;height:2em;box-sizing:border-box}
.carryform button{margin:0}
:is(form,.fakeform) td .u i.un{font-style:normal;width:1.2ch;flex:none}
.fsec.go{border-color:var(--accent)}input[type=range],input[type=checkbox],input[type=radio]{accent-color:var(--accent)}.fsec>h1:first-child{margin-top:.4em}
.fsec>h2{font-size:1.1em;margin:.3em 0 .5em;padding-bottom:.4em;border-bottom:1px solid var(--edge)}
/* U89: cleaner cards — the name and side on the left, the state on the
right, ruled off; the money a quiet panel (the card's own edge already says
long or short; a second coloured frame fought it), its sign in the number;
the footer ruled off, its buttons a size smaller */
.card>div:first-child{display:flex;flex-wrap:wrap;align-items:baseline;gap:.2em .5em;
padding-bottom:.55em;border-bottom:1px solid var(--edge);margin-top:0}
.card>div:first-child>.st{margin-left:auto}.card>div:first-child .side{margin-right:0}
.card .pnl,.card .pnl.pos,.card .pnl.neg{border:0;border-radius:6px;background:color-mix(in srgb,var(--edge) 38%,transparent)}
.card .foot{border-top:1px solid var(--edge);padding-top:.55em;margin-bottom:0}
.card .foot a[href]{padding:.1em .6em;font-size:.92em}
.card span.big.dim{font-size:1.1em}
/* D105: the published read-only page — the note on top, and the panel's
links that lead nowhere there drawn as buttons that cannot be pressed */
.pubnote{margin:-2em -2em 2em;padding:.5em 2em;background:color-mix(in srgb,var(--accent) 14%,var(--bg));
border-bottom:var(--bw) solid var(--accent);font-size:.92em;white-space:normal;overflow-wrap:anywhere}.pubnote a[href]{padding:0 .4em;margin:0}
a.off{display:inline-block;padding:.2em .7em;margin:.15em .2em;border:1px dashed var(--edge);border-radius:4px;
color:var(--dim);cursor:not-allowed;line-height:1.5}nav.side a.off{display:block;margin:.15em var(--gap-s) .15em 0}
@media(max-width:60em){nav.side a.off{display:inline-block}}@media(max-width:40em){.pubnote{margin:-1em -1em 1em;padding:.5em 1em}}
.pub nav.side,.pub .pane{position:static;max-height:none;overflow:visible}
.rsel{position:absolute;opacity:0;pointer-events:none;width:0;height:0;margin:0}
.rhsbox>aside{display:none}.pub .rhsbox>aside{position:sticky;top:var(--hero-pub,9em);max-height:calc(100vh - var(--hero-pub,9em) - 1em);overflow:auto}
label.lab{display:inline-block;padding:.2em .7em;margin:.15em .2em;background:var(--accent-soft);border:1px solid var(--accent);
border-radius:4px;color:var(--fg);cursor:pointer;line-height:1.5}label.lab:hover{background:var(--accent);color:var(--bg)}
nav.side label.lab{display:block;margin:.15em var(--gap-s) .15em 0}label.lab.bname{display:inline;padding:0;margin:0;background:none;
border:0;border-bottom:1px dotted var(--accent);border-radius:0;color:inherit}label.lab.plain{font-size:.8em;margin-left:.6em}
.card .foot label.lab{padding:.1em .6em;font-size:.92em;margin:0}
.fin{display:inline-block;min-width:8em;min-height:1.5em;vertical-align:middle;box-sizing:border-box;padding:.15em .4em;border:1px solid var(--edge);border-radius:3px;background:var(--bg)}
button[disabled]{opacity:.55;cursor:not-allowed}
a.off.bname{display:inline;border:0;padding:0;margin:0;color:inherit;cursor:default;border-bottom:1px dotted var(--edge);border-radius:0}
@media (max-width:860px){.split{display:block}.pane{position:static;max-height:none;overflow:visible;
margin-top:calc(var(--gap)*1.5)}}
"""
