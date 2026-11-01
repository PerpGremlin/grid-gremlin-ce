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
from panel.css import DEFAULT_THEME, RENAMED_THEMES, THEMES


# D157: a bot's state as the engine knows it (the keys, kept in code and in
# the CSS classes) and as a person reads it (STATE_LABEL, what the card and
# the table show, as Bybit and Pionex say Running / Stopped); STATE_WORDS is
# each state's hover
STATE_LABEL = {
    'NOT STARTED': 'Waiting to start',
    'RESTING': 'Running · no position',
    'FLAT': 'Running · no position',
    'HOLDING': 'Running · in position',
    'FROZEN': 'Frozen',
    'STOPPED': 'Stopped (engine off)',
    'RETIRED': 'Retired',
    'DEAD': 'Stopped (by its rule)',
}

STATE_WORDS = {
    'NOT STARTED': 'saved to its account but not running yet: it starts when '
                   'the account\'s engine is next started or restarted',
    'RESTING': 'running, holding nothing; its orders rest on the exchange or '
               'wait for the price to come within reach (see "orders" on the card)',
    'HOLDING': 'running with a position; its exits rest on the exchange or '
               'wait for the price to come within reach',
    'FLAT': 'running, holding nothing now; it traded in this window',
    'FROZEN': 'running, but its fills cannot be read: nothing is placed or '
              'cancelled until they can. The card names the time it began '
              'and the exchange\'s own error; the phone hears it after a '
              'minute and every 6 hours while it lasts',
    'STOPPED': 'its account\'s engine is not running: nothing is placed or '
               'watched, and the card shows the exchange\'s fills and the holding '
               'last seen, not the engine\'s last picture as if it were now',
    'RETIRED': 'retired: its orders cancelled and its position closed or kept, as '
               'its stop chose (the card says what was last seen); it never '
               'starts again unless revived on the control page',
    'DEAD': 'stopped for good by its own rule (its stop loss, its loss limit or '
            'its round count), or set aside at start because the exchange '
            'refused it; its orders are cancelled. The reason is on the '
            'control page, and starting it again is deliberate',
}


def state_label(state):
    """D157: the words a person reads for an engine state."""
    return STATE_LABEL.get(state, state)


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


# D157: a glossary — each word the panel shows, what other platforms call
# it, and what it means here. Spec and decision codes stay in this comment
# and the code, never on the page (U53, U52, U56, U57, U58, U63, U64, U65,
# U68, U59, D63, D76, D78, D81, R12 are the entries' sources).
KEY = """<h1>key — the panel's words, and what other platforms call them</h1>
<p class="dim">Hover a state word, a label or a figure on a card for its
meaning there. Where Bybit, Pionex or 3Commas use another word, it is said
under "also called".</p>
<table><tr><th>word</th><th>also called</th><th>what it means here</th></tr>
<tr><td>Total P&amp;L</td><td class="dim">total profit, PnL</td><td class="dim">realised
after fees + funding + floating P&amp;L. The honest sum, over the span the card
names beside it (since the bot was last flat, or the last few hours).</td></tr>
<tr><td>ROI</td><td class="dim">return</td><td class="dim">Total P&amp;L as a
percentage of the bot's investment.</td></tr>
<tr><td>Grid profit</td><td class="dim">arbitrage profit, matched profit</td><td class="dim">what
the completed buy-and-sell trips made, each sell against the grid level it
bought at, after fees. A grid's heartbeat.</td></tr>
<tr><td>Floating P&amp;L</td><td class="dim">unrealised P&amp;L, trend PnL, unmatched
PnL; "unreal" in the table</td><td class="dim">what the bot holds now, at the mark price,
against what it cost. It moves every second and becomes real only when sold. On a
grid's card it is the rest of the total once grid profit is taken out, so funding
and what a moved range realised sit in it too.</td></tr>
<tr><td>realised after fees</td><td class="dim">realized profit</td><td class="dim">profit
from buys and sells already matched, in the money coin, less the fees. It never
moves again.</td></tr>
<tr><td>fees</td><td class="dim">trading fees</td><td class="dim">what the exchange charged
for every fill in the span. Already taken out of every "after fees" figure: total =
realised − fees + funding + floating P&amp;L.</td></tr>
<tr><td>funding</td><td class="dim">funding fee</td><td class="dim">what the bot's
perpetual position paid (−) or received (+) in funding over the same span, from
the exchange's own record. Spot has none; — when it could not be read.</td></tr>
<tr><td>Runtime · per day · APR</td><td class="dim">running time, grid APR, total APR</td><td class="dim">how
long the bot has run in the figure's span, its grid profit (a DCA's or a trade's
realised profit) after fees per day, and that as a yearly rate on its investment,
as Bybit counts it: profit ÷ investment ÷ days × 365, a run under a day counted as
a day. A big APR on a short run is arithmetic, not a promise.</td></tr>
<tr><td>USDT · USDC · USD · BTC …</td><td class="dim">quote coin, settle coin</td><td class="dim">every
money figure names its coin: a USDT/USDC perpetual's or a spot bot's money is its
settle coin (Bybit USDT or USDC, Hyperliquid USDC); a coin-margined bot's
investment, size, loss and P&amp;L are dollars ($1 contracts) and its margin is
the coin itself. An account's total joins the coins its bots use.</td></tr>
<tr><td>BTCUSDT Futures Grid</td><td class="dim">bot name</td><td class="dim">a bot's
name: its market's symbol, the market (Futures; Inverse Futures for coin-margined;
Spot; Margined Spot when it borrows), and its kind (Grid, DCA). A single trade says
its futures type: SOLUSDT Perpetual Futures Trade. A carry bot is its own name and
Portfolio Bot. The side is the LONG or SHORT tag beside it; a confirm box takes the
name with its side ("BTCUSDT Futures Grid long"), the short form ("BTCUSDT grid
long"), or the code.</td></tr>
<tr><td>set 3x · in use 1.2x</td><td class="dim">leverage</td><td class="dim">set is
the leverage the bot is set to (a spot bot's loan multiple, 1x when it borrows
nothing); in use is its position at the mark ÷ its own money. A carry bot says its
spot's and, when hedged, its perpetuals'. Shown only: nothing caps it.</td></tr>
<tr><td>Running · in position</td><td class="dim">running</td><td class="dim">the bot
runs and holds a position; its exits rest on the exchange or wait for the price
to come near.</td></tr>
<tr><td>Running · no position</td><td class="dim">running</td><td class="dim">the bot
runs and holds nothing; its orders rest or wait. A bot rests only the orders within
a few percent of the price (5% unless set) and places the rest as the price comes
near, so a wide grid shows one or two orders, which is correct; the card's
"orders" line says what rests and what waits.</td></tr>
<tr><td>Frozen</td><td class="dim">—</td><td class="dim">the
bot runs but its fills cannot be read, so it places and cancels nothing until they
can; the card says since when and the exchange's own error. It ends by itself on the
first clean read.</td></tr>
<tr><td>Waiting to start</td><td class="dim">pending</td><td class="dim">saved to
its account but not running yet: it starts when the account's engine is next
started or restarted (on the control page).</td></tr>
<tr><td>Stopped (by its rule)</td><td class="dim">stopped, completed, terminated</td><td class="dim">the
bot stopped for good by its own rule: its stop loss, its loss limit or its round
count; or the exchange refused it at start and it was set aside, the rest of the
account running on. Its orders are cancelled. Its reason is on the control page;
starting it again is deliberate.</td></tr>
<tr><td>Stopped (engine off)</td><td class="dim">paused</td><td class="dim">the
account's engine is not running: nothing is placed or watched. Orders already on
the exchange stay there.</td></tr>
<tr><td>Retired</td><td class="dim">deleted, closed</td><td class="dim">stood down for
good by its card's <b>stop</b>: orders cancelled, its position closed or left open, as chosen.</td></tr>
<tr><td>bot code</td><td class="dim">bot ID</td><td class="dim">the short name on a
card's footer, read out beside it: <b>linBTCUSDTl</b> = USDT perpetual · BTCUSDT ·
long (<b>lin</b> a USDT/USDC perpetual, <b>inv</b> a coin-margined one, <b>spo</b>
spot; the last letter the side). A confirm box asks for it typed.</td></tr>
<tr><td>grid level</td><td class="dim">grid, rung</td><td class="dim">one price in a
grid where a buy or a sell rests. "Number of grids" counts them.</td></tr>
<tr><td>range</td><td class="dim">price range</td><td class="dim">a grid's lowest to
highest price: on the card a bar, its ticks the grid levels, the dot today's price.</td></tr>
<tr><td>range moved up / down N levels</td><td class="dim">trailing, range moved</td><td class="dim">a
grid that follows the price has moved its range by N grid levels from where it
started; the card judges the price against the range it trades now.</td></tr>
<tr><td>edge lo/hi</td><td class="dim">distance to range</td><td class="dim">in the
table: how far the price is from each end of the range, as % of the price. A small
number is near that edge.</td></tr>
<tr><td>open@avg</td><td class="dim">position, entry price</td><td class="dim">in the
table: what the bot holds right now, at its average cost.</td></tr>
<tr><td>bought / sold</td><td class="dim">filled volume</td><td class="dim">the coins
traded each way in the span.</td></tr>
<tr><td>stop-now est.</td><td class="dim">if closed now</td><td class="dim">roughly what
you would receive if you closed this bot's position right now: the position at the
price, less the exchange fee. An estimate, never a promise.</td></tr>
<tr><td>watcher · no limit</td><td class="dim">position alert</td><td class="dim">how much
of this bot's own position limit its position uses, when it has one: an independent
check that warns if a position outgrows it. "no limit" means it has none of its own;
the account checks (margin, equity floor, drawdown, a silent engine) still cover it.</td></tr>
<tr><td>(estimated)</td><td class="dim">—</td><td class="dim">a number from the
engine's own last snapshot rather than the exchange's records: seconds old, and said
so.</td></tr>
<tr><td>all-time</td><td class="dim">total since creation</td><td class="dim">a bot's
whole result since its first recorded fill, from the panel's own record of fills;
"the record is behind" when that record has not caught up yet.</td></tr>
<tr><td>safety checks</td><td class="dim">risk monitor</td><td class="dim">the
independent checks that run every few minutes beside the bots (margin, equity floor,
each bot's position limit, a silent engine) and warn when one fails. "not running"
means nothing is checking.</td></tr>
<tr><td>order book thin for this size</td><td class="dim">low liquidity</td><td class="dim">the
market's order book near the price is small beside what this account's bots trade
there; a large order would move the price.</td></tr>
<tr><td>est. liquidation price</td><td class="dim">estimated liquidation price</td><td class="dim">on
a new bot's form and review: where this bot, standing alone on its own investment,
would be liquidated if the price moved steadily against it with every level filled.
Under cross margin the account's free balance holds it longer; the exchange's own
figure is the one that counts.</td></tr>
<tr><td>least investment that works</td><td class="dim">minimum investment</td><td class="dim">the
smallest investment the engine accepts for a setup as typed: below it a grid level's
order is under the exchange's smallest, or a DCA's orders do not fit.</td></tr>
<tr><td>profit per grid level</td><td class="dim">profit/grid</td><td class="dim">what
one level earns each time it sells, after the maker fee on both legs, as a share of
that level's order.</td></tr>
<tr><td>* (star)</td><td class="dim">partial</td><td class="dim">this bot's numbers
come from a span that opened mid-round, so they are partial. Widen the span for the
whole story.</td></tr>
<tr><td>trips / per trip</td><td class="dim">arbitrage times, matched trades</td><td class="dim">a
trip is a sell that closed a buy; per trip is what each made against its own grid
level, not against the book's average. A grid that bought cheaper on the way down
shows a falling average, and profit against that average is not what the trip
earned.</td></tr>
<tr><td>rounds</td><td class="dim">deals, cycles, loops</td><td class="dim">a DCA's
completed rounds: an entry, its safety orders, and the take profit that closed it.</td></tr>
<tr><td>safety order</td><td class="dim">add-on order, DCA order, addition</td><td class="dim">a
DCA's extra buy (a short: sell) as the price moves against it, each one perhaps
larger than the last (the multiplier), so the average entry follows the price.</td></tr>
<tr><td>the ladder</td><td class="dim">summary box, max price drop covered</td><td class="dim">a
DCA card's own sum: for each step, where it fills from the base price, its size, what
is then committed, the average entry, and how far the price must come back from that
fill for the whole position to reach its take profit. The summary line is the drop (a
short: the rise) the ladder covers before it runs out. Percentages of the base price,
so it holds before a round and during one.</td></tr>
<tr><td>mark price</td><td class="dim">mark</td><td class="dim">the exchange's fair
price for a perpetual, which it uses for floating P&amp;L and liquidation.</td></tr>
<tr><td>liquidates at · % away</td><td class="dim">liquidation price, est. liq. price</td><td class="dim">where
the exchange says this position is liquidated, and how far the mark price is from
it. Red when it is close.</td></tr>
<tr><td>MMR</td><td class="dim">maintenance margin rate, risk ratio</td><td class="dim">the
account's maintenance margin as a share of its equity; the exchange liquidates at
100%.</td></tr>
<tr><td>leverage</td><td class="dim">—</td><td class="dim">position size ÷ the money
put up. The account box's "account leverage" is everything held ÷ the account's
equity; "if every order filled" is the same with every resting and waiting order
filled.</td></tr>
<tr><td>investment</td><td class="dim">total investment, margin, amount</td><td class="dim">what
the bot puts up, in the money coin; at a leverage, its position may reach investment ×
leverage.</td></tr>
<tr><td>hold benchmark</td><td class="dim">vs just holding</td><td class="dim">on a
rehearsal: what the same money would have done just holding over the same span.</td></tr>
<tr><td>wallet · this bot's book · not this bot's</td><td class="dim">—</td><td class="dim">a spot
bot with a stated holding: the coin's whole wallet balance, what this bot's book says
it owns (the stated holding plus its own fills since), and the difference, coins
that are not its. Where the kept record can say, how much of that the coin-margined
bots on the same coin realised there, and what is left unexplained; red when more
than half is unexplained (an outside hand, or a record behind). Funding settles in
the coin too and is not counted.</td></tr>
<tr><td>… trade (card)</td><td class="dim">one-off position</td><td class="dim">a single
long or short with its own exit: its take profit, its stop watched at the mark, who
opened it when. <b>close trade</b> ends it early with one reduce-only market order;
<b>clear</b>, once it has ended, frees its market and side. Opened from <b>new
bot</b>, single trade.</td></tr>
<tr><td>numbers (button)</td><td class="dim">details</td><td class="dim">the position's
own page, live: the position as the exchange shows it, then every number laid open. A
card on the front page is slim: its money, run rate and range, and only what needs
you now, in red.</td></tr>
<tr><td>details / assets (fold)</td><td class="dim">—</td><td class="dim">on the
position's page, the card's lower half (holding, kind, margin, limits; a
portfolio's assets) behind one word. Click to fold or open; it is remembered.</td></tr>
<tr><td>price, 24 h / 7 d</td><td class="dim">chart</td><td class="dim">on a position's
page: the price the engine read each minute, the range's grid levels (edges dashed),
the bot's own buys and sells as dots, liquidation in red. Hover a dot or the line for
its time.</td></tr>
<tr><td>equity, 24 h / 7 d</td><td class="dim">account value</td><td class="dim">the
account's equity as the engine's own snapshot saw it, one point a minute or so: the
low, the high and the change over the span; hover a point for its time. The small
line in the strip at the top is the same day. The engine's reading of the
exchange's wallet, not the exchange's own chart.</td></tr>
<tr><td>N bots (fold)</td><td class="dim">—</td><td class="dim">an account's cards,
behind its heading and its box. <b>accounts: full / folded</b> sets them all; <b>fold
cards / open cards</b> beside the count folds or opens this one account's cards.</td></tr>
<tr><td>PORTFOLIO · carry / tilt / basis &amp; shape</td><td class="dim">—</td><td class="dim">the
hedged portfolio bot: several coins on spot at target weights, each hedged by its own
perpetual short. <b>carry</b> is the funding its shorts received; <b>tilt</b> what
leaning the hedges with the market's regime made or cost; <b>basis &amp; shape</b>
what is left of the total since the start after those two and after the loan's
interest: the spot/perp gap and the coin-margined contract's shape. <b>interest</b>
is what the exchange charged on the loan.</td></tr>
<tr><td>stack · cash · borrowed (N× the equity)</td><td class="dim">—</td><td class="dim">the
portfolio's coins at the mark price; its unspent cash; the exchange's loan when it
runs on margin, and the stack as a multiple of the bot's equity. The margin floor
trims every leg together when free margin dips under it, and the bot then aims lower
until free margin is comfortable.</td></tr>
<tr><td>weight → actual · hedge ratio → actual</td><td class="dim">—</td><td class="dim">per
coin: the target share of the stack and where it sits; the hedge the bot wants and the
hedge it holds, as coins.</td></tr>
</table><p><a href="/">&larr; your bots</a></p>"""


# U112: the theme, set in the head before the page paints (no flash): the
# choice kept in the browser across tabs (gg-theme), a tab still on U46's
# light (gg-light) carried over once; a choice kept under a name since
# renamed (RENAMED_THEMES) moved once, gg-theme-v marking it done so the new
# dark is never read as the old; nothing kept, DEFAULT_THEME. ggTheme(1)
# steps to the next and every theme button says which is on. The first
# theme is the stylesheet's own :root, so it sets no class. Nothing else
# passes through it.
THEME_MOVE = ''.join(f"t==='{old}'?'{new}':" for old, new in RENAMED_THEMES.items()) + 't'
THEME_JS = ("<script>(function(){var T=" + json.dumps(list(THEMES)).replace(' ', '')
            + ",D='" + DEFAULT_THEME + """',r=document.documentElement,t=null;
try{t=localStorage.getItem('gg-theme');
 if(!t&&sessionStorage.getItem('gg-light'))localStorage.setItem('gg-theme',t='light');
 sessionStorage.removeItem('gg-light');
 if(t&&localStorage.getItem('gg-theme-v')!=='2')localStorage.setItem('gg-theme',t=""" + THEME_MOVE + """);
 localStorage.setItem('gg-theme-v','2');}catch(e){}
if(T.indexOf(t)<0)t=D;
window.ggTheme=function(step){if(step){t=T[(T.indexOf(t)+1)%T.length];
  try{localStorage.setItem('gg-theme',t);}catch(e){}}
 T.forEach(function(n){r.classList.toggle('t-'+n,n===t&&n!==T[0]);});
 document.querySelectorAll('[data-theme]').forEach(function(b){b.textContent='theme: '+t;});};
ggTheme(0);})();</script>""")


# V12: the live page reloads whole, so what the reader opened would shut and
# the page would jump on every refresh. This script only remembers, in the
# browser tab: which boxes are open and how far down the page is (U112: the
# theme is THEME_JS's). No number passes through it. U82: the newest swap wins — an older
# answer arriving late is dropped (seq) — and the timer waits while a swap is
# in flight or a form in the right half is being typed in (dirty).
KEEP_JS = """<script>(function(){
var N=(document.currentScript||{}).nonce||'',S=sessionStorage,open={},root=document.documentElement,KINDS=['fold','acct'];
try{open=JSON.parse(S.getItem('gg-open')||'{}');}catch(e){}
function wire(scope){
 KINDS.forEach(function(c){var g=S.getItem('gg-fold:'+c);
  if(g)scope.querySelectorAll('details.'+c).forEach(function(d){d.open=(g==='open');});});
 scope.querySelectorAll('details[data-k]').forEach(function(d){
  if(d.dataset.k in open)d.open=!!open[d.dataset.k];
  d.addEventListener('toggle',function(){
   open[d.dataset.k]=d.open?1:0;S.setItem('gg-open',JSON.stringify(open));});});}
function eqs(scope){scope.querySelectorAll('input.eqpick').forEach(function(r){
 var v=S.getItem('gg-eq:'+r.name);if(v&&document.getElementById(v))r.checked=(r.id===v);});}
document.addEventListener('change',function(e){var r=e.target;
 if(r.classList&&r.classList.contains('eqpick'))S.setItem('gg-eq:'+r.name,r.id);});
function inAcct(i){return document.querySelectorAll('details.acct[data-k="acct:'+i+'"]');}
function picks(){document.querySelectorAll('[data-fold]').forEach(function(a){
 a.classList.toggle('pick',a.dataset.fold===(S.getItem('gg-fold:'+a.dataset.cls)||'open'));});
 document.querySelectorAll('[data-foldin]').forEach(function(a){var all=true;
  inAcct(a.dataset.foldin).forEach(function(d){if(!d.open)all=false;});
  a.textContent=all?'fold cards':'open cards';});}
wire(document);picks();eqs(document);
window.ggFold=function(k,c){document.querySelectorAll('details.'+c).forEach(function(d){
 d.open=(k==='open');delete open[d.dataset.k];});
 S.setItem('gg-open',JSON.stringify(open));S.setItem('gg-fold:'+c,k);picks();};
window.ggFoldIn=function(i){var all=true,ds=inAcct(i);
 ds.forEach(function(d){if(!d.open)all=false;});
 ds.forEach(function(d){d.open=!all;open[d.dataset.k]=all?0:1;});
 S.setItem('gg-open',JSON.stringify(open));picks();};
if(window.ggTheme)ggTheme(0);
window.ggSize=function(k){['coin','value','cost'].forEach(function(u){
 root.classList.toggle('only-'+u,k===u);});S.setItem('gg-size',k);
 document.querySelectorAll('[data-size]').forEach(function(a){
 a.classList.toggle('pick',a.dataset.size===k);});};
ggSize(S.getItem('gg-size')||'all');
window.ggLev=function(k){root.classList.toggle('lev-on',k==='filled');
 S.setItem('gg-lev',k);document.querySelectorAll('[data-lev]').forEach(
 function(a){a.classList.toggle('pick',a.dataset.lev===k);});};
ggLev(S.getItem('gg-lev')||'now');
var hero=document.querySelector('.hero');
function top(){if(hero)root.style.setProperty('--hero',hero.offsetHeight+'px');}
top();window.addEventListener('resize',top);
var y=S.getItem('gg-y:'+location.pathname);
if(y)window.scrollTo(0,Number(y));
window.addEventListener('pagehide',function(){
 S.setItem('gg-y:'+location.pathname,String(window.scrollY));});
var seq=0,busy=0;
function swap(url,keep){var my=++seq;busy++;
 return fetch(url,{credentials:'same-origin',cache:'no-store'})
 .then(function(r){return r.ok?r.text():'';}).then(function(t){
  if(my!==seq)return null;
  if(!t)return false;
  var doc=new DOMParser().parseFromString(t,'text/html');
  // U110: the refresh keeps each half where it was scrolled to; a pick opens at its top
  var at={};if(keep)['.pane','nav.side'].forEach(function(q){var e=document.querySelector(q);if(e)at[q]=e.scrollTop;});
  ['.hero','main'].forEach(function(q){var a=document.querySelector(q),b=doc.querySelector(q);
   if(a&&b)a.innerHTML=b.innerHTML;});
  Object.keys(at).forEach(function(q){var e=document.querySelector(q);if(e)e.scrollTop=at[q];});
  document.querySelectorAll('main .pane script').forEach(function(old){
   var s=document.createElement('script');s.nonce=N;s.text=old.text;old.replaceWith(s);});
  wire(document.querySelector('main')||document);picks();eqs(document);top();return true;})
 .then(function(v){busy--;return v;},function(e){busy--;throw e;});}
function dirty(){var a=document.activeElement;
 if(a&&a.closest&&a.closest('.pane form'))return true;
 return [].some.call(document.querySelectorAll('.pane form input,.pane form textarea,.pane form select'),function(e){
  if(e.type==='checkbox'||e.type==='radio')return e.checked!==e.defaultChecked;
  if(e.tagName==='SELECT'){var d=0;[].forEach.call(e.options,function(o,i){if(o.defaultSelected)d=i;});
   return e.selectedIndex!==d;}
  return e.value!==e.defaultValue;});}
document.addEventListener('click',function(e){
 var t=e.target.closest&&e.target.closest('[data-fold],[data-foldin],[data-size],[data-lev],[data-back],[data-theme]');
 if(t){e.preventDefault();var d=t.dataset;
  if('fold' in d)ggFold(d.fold,d.cls);else if('foldin' in d)ggFoldIn(d.foldin);
  else if('size' in d)ggSize(d.size);else if('lev' in d)ggLev(d.lev);
  else if('back' in d)history.back();else if(window.ggTheme)ggTheme(1);return;}
 var o=e.target.closest&&e.target.closest('button[data-once]');
 if(o)setTimeout(function(){o.disabled=true;o.textContent=o.dataset.once;},0);
 var a=e.target.closest&&e.target.closest('a[data-pick]');
 if(!a||e.ctrlKey||e.metaKey||e.shiftKey||e.button)return;
 var u=new URL(a.href,location.href),v=new URLSearchParams(location.search).get('view');
 if(u.origin!==location.origin||u.pathname!==location.pathname)return;
 if(v)u.searchParams.set('view',v);
 e.preventDefault();swap(u.href).then(function(ok){
  if(ok)history.pushState(null,'',u.pathname+u.search);else if(ok===false)location.href=u.href;})
 .catch(function(){location.href=u.href;});});
window.addEventListener('popstate',function(){swap(location.href).catch(function(){});});
var m=document.querySelector('meta[name="gg-refresh"]'),every=m?Number(m.content):0;
if(every>0)setInterval(function(){if(busy||dirty())return;
 swap(location.href,1).catch(function(){});},every*1000);
})();</script>"""


# D159 (2026-11-01): a refusal takes the eye, and a typed confirmation is a
# pop-up. On load the page scrolls to its first refusal and gives it focus.
# A form holding a dialog.ggconfirm opens it instead of sending; its confirm
# button wakes only when the typing matches the dialog's data-accept (lower
# case, spaces squashed — confirmed()'s rule; data-multi: comma-separated
# names, each one accepted or made of accepted words, control's U43) and
# every retype with a data-want equals its number; on press the typing goes
# into the form's own fields and the form is sent. Escape or cancel sends
# nothing. Without dialog support the inline box stays (no gg-dlg class).
CONFIRM_JS = """<script>(function(){
var R=document.documentElement,D=window.HTMLDialogElement,can=typeof D==='function'&&'showModal' in D.prototype;
if(can)R.classList.add('gg-dlg');
var bad=document.querySelector('.refusal[tabindex]');
if(bad){bad.scrollIntoView({block:'center'});bad.focus({preventScroll:true});}
function sq(s){return String(s||'').toLowerCase().split(/\\s+/).filter(Boolean).join(' ');}
function named(d,t){var acc=[];try{acc=JSON.parse(d.dataset.accept||'[]');}catch(e){}
 function one(p){return acc.indexOf(sq(p))>=0;}
 if(!d.dataset.multi)return one(t);
 var parts=t.split(',').filter(function(p){return sq(p);});
 return parts.length>0&&parts.every(function(p){return one(p)||sq(p).split(' ').every(one);});}
function near(i){if(!('want' in i.dataset))return true;var s=i.value.replace(/,/g,'').trim(),n=Number(s),w=Number(i.dataset.want),
 d=n-w,m=w<0?-w:w;if(!s||n!==n)return false;return (d<0?-d:d)<=1e-9*(m>1?m:1);}
function check(d){var ok=named(d,d.querySelector('input.gg-typed').value)&&
 [].every.call(d.querySelectorAll('input[data-into]'),near);
 d.querySelector('button[data-go]').disabled=!ok;return ok;}
function go(d){if(!check(d))return;var f=d.closest('form'),c=f.querySelector('[name=confirm]');
 if(c)c.value=d.querySelector('input.gg-typed').value.trim();
 d.querySelectorAll('input[data-into]').forEach(function(i){
  var t=f.querySelector('[name="'+i.dataset.into+'"]');if(t)t.value=i.value;});
 f.dataset.ggGo='1';d.close();if(d._by)f.requestSubmit(d._by);else f.requestSubmit();
 setTimeout(function(){delete f.dataset.ggGo;},0);}
document.addEventListener('submit',function(e){var f=e.target,d=f.querySelector&&f.querySelector('dialog.ggconfirm');
 if(!can||!d||f.dataset.ggGo)return;e.preventDefault();
 d._by=e.submitter&&e.submitter.form===f?e.submitter:null;check(d);d.showModal();},true);
document.addEventListener('input',function(e){var d=e.target.closest&&e.target.closest('dialog.ggconfirm');if(d)check(d);});
document.addEventListener('keydown',function(e){var d=e.target.closest&&e.target.closest('dialog.ggconfirm');
 if(d&&e.key==='Enter'&&e.target.tagName==='INPUT'){e.preventDefault();go(d);}});
document.addEventListener('click',function(e){var d=e.target.closest&&e.target.closest('dialog.ggconfirm');if(!d)return;
 if(e.target.closest('[data-cancel]'))d.close();else if(e.target.closest('button[data-go]'))go(d);});
})();</script>"""

KEEP_JS += CONFIRM_JS


# D161 (2026-11-01): the column's view switches, one button each naming what
# is on (as theme does) — accounts full/folded, size in stepping all → coins →
# value → cost, leverage now / if all filled — over KEEP_JS's own ggFold,
# ggSize and ggLev; arrange goes on change; "new bot" opens its chooser
# (without dialog support the link goes to the /new page); Escape, with no
# dialog open and the cursor in no field, goes back to the overview the way
# the name and "overview" do. Nothing else passes through it.
NAV_JS = """<script>(function(){
var S=sessionStorage,STEP=['all','coin','value','cost'],SW={all:'all',coin:'coins',value:'value',cost:'cost'};
var D=window.HTMLDialogElement,can=typeof D==='function'&&'showModal' in D.prototype;
function fold(){return S.getItem('gg-fold:acct')||'open';}
function size(){var s=S.getItem('gg-size');return STEP.indexOf(s)<0?'all':s;}
function lev(){return S.getItem('gg-lev')==='filled'?'filled':'now';}
var SINCE=['1h','24h','7d'],R=document.documentElement;
function since(){var s=S.getItem('gg-since');return SINCE.indexOf(s)<0?'24h':s;}
function ggSince(k){SINCE.forEach(function(w){R.classList.toggle('since-'+w,w===k&&k!=='24h');});S.setItem('gg-since',k);}
ggSince(since());
function label(){document.querySelectorAll('[data-tog]').forEach(function(b){var k=b.dataset.tog;
 if(k==='acct')b.textContent='accounts: '+(fold()==='open'?'full':'folded');
 else if(k==='size')b.textContent='size in: '+SW[size()];
 else if(k==='lev')b.textContent='leverage: '+(lev()==='now'?'now':'if all filled');});}
label();
document.addEventListener('click',function(e){var c=e.target.closest?e.target:null;if(!c)return;
 var t=c.closest('[data-tog]');
 if(t){e.preventDefault();var k=t.dataset.tog;
  if(k==='acct'&&window.ggFold)ggFold(fold()==='open'?'folded':'open','acct');
  else if(k==='size'&&window.ggSize)ggSize(STEP[(STEP.indexOf(size())+1)%STEP.length]);
  else if(k==='lev'&&window.ggLev)ggLev(lev()==='now'?'filled':'now');
  else if(k==='since')ggSince(SINCE[(SINCE.indexOf(since())+1)%SINCE.length]);
  label();return;}
 var d=document.querySelector('dialog.ggnew'),n=c.closest('a[data-new]');
 if(n&&can&&d&&!e.ctrlKey&&!e.metaKey&&!e.shiftKey&&!e.button){e.preventDefault();d.showModal();return;}
 var g=c.closest('dialog.ggnew');
 if(g&&(c.closest('[data-cancel]')||c.closest('a')))g.close();},true);
document.addEventListener('change',function(e){var s=e.target;
 if(s.matches&&s.matches('select[data-go]')&&s.form)s.form.submit();});
document.addEventListener('keydown',function(e){
 if(e.key!=='Escape'||e.defaultPrevented||document.querySelector('dialog[open]'))return;
 var a=document.activeElement;
 if(a&&(a.isContentEditable||/^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName)))return;
 var h=document.querySelector('a[data-home]');if(h){e.preventDefault();h.click();}});
})();</script>"""

KEEP_JS += NAV_JS
