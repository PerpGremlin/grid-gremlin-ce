"""The panel's reference text: the key page, the networks page, the state words,
and the small script that keeps what the reader opened (V12)."""
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


STATE_WORDS = {
    'NOT STARTED': 'in the fleet file but not yet running — it starts at '
                   'the fleet\'s next restart',
    'RESTING': 'running, holding nothing; its orders rest or wait for the '
               'price to come within reach (see "orders" on the card)',
    'HOLDING': 'running with a position; its exits rest or wait for the '
               'price to come within reach',
    'FLAT': 'running, holding nothing now, and it traded in this window',
    'DEAD': 'stood down — a stop, a limit or a round count ended it; its '
            'reason is on the control page, and revival is deliberate',
}


TRADING = """<h1>demo, testnet and mainnet</h1>
<p>Every fleet's heading names the network its exchange connection is on, in
the exchange's own words: Bybit's <b>Demo Trading</b> and <b>Testnet</b>, and
Hyperliquid's <b>Testnet</b>, use play money; <b class="neg">Mainnet</b> is
real money and is shown in red everywhere it appears. The name comes from
what the running fleet actually connected to, not from a file's say-so.</p>
<h2>What this panel will not do</h2>
<p>It cannot move a fleet from play money to real money, or back. Which
network a fleet uses is set outside the panel, in the box's own files, and
real money needs two separate, deliberate switches to agree before a fleet
will start; either one alone is refused. This page does not describe how to
set them.</p>
<h2>What real money asks for first</h2>
<ul>
<li>A long soak on play money: every bot past its minimum days and trades,
no new engine fault for a week, every alarm path seen to work.</li>
<li>Exchange keys made for this alone: trading only, never withdrawal or
transfer, locked to the box's address, on an account set aside for it.</li>
<li>Changes reach real money only after they have run on play money — a
separate, pinned copy of the code that moves when its owner says so.</li>
<li>On a Mainnet fleet, raising a bot's capital or leverage by more than
double asks for the new number twice.</li>
</ul>
<p class="dim">Trading carries risk of loss, more so with leverage. Nothing
here is advice.</p>"""


KEY = """<h1>key — what every word on this page means</h1>
<table><tr><th>term</th><th></th></tr>
<tr><td>realized</td><td class="dim">profit from MATCHED buys and sells,
in quote currency (USDT). Money already made or lost; it never moves
again.</td></tr>
<tr><td>fees</td><td class="dim">what the venue charged for every fill
in the window — already excluded from nothing: total = realized − fees
+ funding + unreal.</td></tr>
<tr><td>USDT · USDC · USD · BTC …</td><td class="dim">every money figure
names its coin (U53): a linear or spot bot's money is its settle coin
(Bybit USDT or USDC, Hyperliquid USDC); an inverse bot's capital, notional,
loss and P&amp;L are dollars ($1 contracts) and its margin is the coin
itself. An exchange's total joins the coins its bots use.</td></tr>
<tr><td>wallet · this bot's book · not this bot's</td><td class="dim">a spot
bot with a stated holding (D76): the coin's whole wallet balance, what this
bot's book says it owns (the stated holding plus its own fills since), and
the difference — coins that are not its. Where the kept ledger can say,
how much of that the inverse bots on the same coin realised there, and what
is left unexplained; red when more than half is unexplained (an outside
hand, or a ledger behind). Funding settles in the coin too and is not
counted.</td></tr>
<tr><td>the ladder</td><td class="dim">a DCA card's own sum (U52): for
each step, where it fills from the base price, its size, what is then
committed, the average entry, and how far the price must come back from
that fill for the whole position to reach take-profit. The summary line
is the drop (a short: the rise) the ladder covers before it runs out.
Percentages of the base price, so it holds before a round and during one.</td></tr>
<tr><td>funding</td><td class="dim">what the bot's position paid (−) or
received (+) in funding over the same window, from the exchange's own
record (D63). A perp holds it; spot has none. — when it could not be
read.</td></tr>
<tr><td>open@avg</td><td class="dim">what the bot HOLDS right now, at
its average cost. This inventory is not profit and not loss yet.</td></tr>
<tr><td>unreal</td><td class="dim">the open remainder marked to the
current price. Moves every second; becomes real only when sold.</td></tr>
<tr><td>total</td><td class="dim">realized − fees + funding + unreal. The
honest sum — the number other dashboards inflate by leaving parts
out.</td></tr>
<tr><td>bought / sold</td><td class="dim">base quantity each way in the
window — how much churn produced the numbers to the left.</td></tr>
<tr><td>range</td><td class="dim">the grid's territory: bar = range,
ticks = rungs, dot = current price.</td></tr>
<tr><td>edge lo/hi</td><td class="dim">distance from price to each end
of the range, as % of price. Small number = near that edge.</td></tr>
<tr><td>stop-now est.</td><td class="dim">roughly what you would receive
if you flattened this bot right now — position at price, minus the
venue fee. An estimate, never a promise.</td></tr>
<tr><td>watcher</td><td class="dim">how much of this bot's watchdog
ceiling its position uses, when you gave it one. The watchdog is the
independent alarm that pages if a position outgrows that limit.</td></tr>
<tr><td>NOT STARTED / RESTING / HOLDING / FLAT</td><td class="dim">not
started = in the fleet file, waits for the fleet's restart; resting =
running, holding nothing; holding = has a position; flat = no position,
traded in this window. Hover any state word for its meaning. A bot rests
only the orders within a few percent of the price (5% unless set) and
places the rest as the price comes near — so a wide grid shows one or two
orders and a position, which is correct; the card's "orders" line says
what rests and what waits.</td></tr>
<tr><td>DEAD</td><td class="dim">the bot stood down and wrote a
tombstone. Its reason is on the control page; revival is deliberate.
</td></tr>
<tr><td>no limit</td><td class="dim">this bot has no position limit of
its own. The account guards (margin, equity floor, drawdown, a stale
fleet) still cover it; a limit is an opt-in.</td></tr>
<tr><td>(belief)</td><td class="dim">a number from the engine's own
snapshot rather than venue records — what the bot believes, seconds
old, honest about its source.</td></tr>
<tr><td>* (star)</td><td class="dim">this bot's numbers come from a
window that opened mid-round: partial by construction. Widen the window
for the whole story.</td></tr>
<tr><td>ZERO-SPREAD (R9)</td><td class="dim">exits that closed inside
the fee of their own cost — churn that pays the venue and nobody else.
Should be zero.</td></tr>
<tr><td>trips / per-trip</td><td class="dim">a trip is an exit that
closed a lot; per-trip is what each exit earned against its own rung (R12),
not the book's average &mdash; a grid that bought cheaper lots on the way
down shows a falling average, and realized against it is not what the trip
earned. The grid's heartbeat.</td></tr>
<tr><td>rounds / SO fills / max depth</td><td class="dim">martingale:
completed rounds; safety orders filled this window; the deepest rung
reached. Depth near max SOs = the schedule nearly exhausted.</td></tr>
<tr><td>hold benchmark</td><td class="dim">what the same capital would
have done just holding over the same window. Beat it or hold.</td></tr>
</table><p><a href="/">&larr; fleet</a></p>"""


# V12: the live page reloads whole, so what the reader opened would shut and
# the page would jump on every refresh. This script only remembers, in the
# browser tab: which boxes are open, how far down the page is, and the
# theme. No number passes through it.
KEEP_JS = """<script>(function(){
var S=sessionStorage,open={};
try{open=JSON.parse(S.getItem('gg-open')||'{}');}catch(e){}
document.querySelectorAll('details[data-k]').forEach(function(d){
 if(open[d.dataset.k])d.open=true;
 d.addEventListener('toggle',function(){
  if(d.open)open[d.dataset.k]=1;else delete open[d.dataset.k];
  S.setItem('gg-open',JSON.stringify(open));});});
var root=document.documentElement;
if(S.getItem('gg-light'))root.classList.add('light');
window.ggSize=function(k){['coin','value','cost'].forEach(function(u){
 root.classList.toggle('only-'+u,k===u);});S.setItem('gg-size',k);
 document.querySelectorAll('[data-size]').forEach(function(a){
 a.classList.toggle('pick',a.dataset.size===k);});};
ggSize(S.getItem('gg-size')||'all');
window.ggLev=function(k){root.classList.toggle('lev-on',k==='filled');
 S.setItem('gg-lev',k);document.querySelectorAll('[data-lev]').forEach(
 function(a){a.classList.toggle('pick',a.dataset.lev===k);});};
ggLev(S.getItem('gg-lev')||'now');
new MutationObserver(function(){
 if(root.classList.contains('light'))S.setItem('gg-light','1');
 else S.removeItem('gg-light');}).observe(root,{attributes:true});
window.ggAll=function(on){document.querySelectorAll('details[data-k]')
 .forEach(function(d){d.open=on;});};
var nav=document.querySelector('nav.side'),hero=document.querySelector('.hero');
function top(){if(nav&&hero)nav.style.top=hero.offsetHeight+'px';}
top();window.addEventListener('resize',top);
var y=S.getItem('gg-y:'+location.pathname);
if(y)window.scrollTo(0,Number(y));
window.addEventListener('pagehide',function(){
 S.setItem('gg-y:'+location.pathname,String(window.scrollY));});
})();</script>"""
