# The setup form (§11): a bot configured in plain words, two ways in.
#
# QUICK   — a preset and three answers (which coin, how much, how careful);
#           every other value is derived from today's price.
# ADVANCED — every key the config file accepts, grouped and labelled. A spec
#           holds the schema to config.py's key lists, so a key the engine
#           learns and the form does not is a failure, not a file-only note.
#
# Both produce the same thing the file would hold: one bot row. Nothing here
# validates — the engine's validators judge the row at the gates, in their
# own words. Nothing here holds a key or talks to a private endpoint.
#
# Percent fields are typed as percent (1.5 = 1.5%) and stored as the
# fraction the file uses (0.015).
import math
import html
import time

from gridgremlin.apply import check_link_fits, make_botid, widest_rung
from gridgremlin.config import ConfigError
from gridgremlin.main import BYBIT_LINK_LIMIT
from panel.chart import CHART_BOX, CHART_JS

# (form name, config path, kind, label, help)
# kinds: num · int · pct · choice:<a|b> · switch · cap · weights · tranches
COMMON = [
    ('symbol', 'symbol', 'text', 'Coin / market',
     'the venue\'s own name: BTCUSDT on Bybit, BTC on Hyperliquid'),
    ('side', 'side', 'choice:long|short', 'Direction',
     'long buys low and sells higher; short sells high and buys back lower'),
    ('capital', 'capital', 'num', 'Investment',
     'what you put up (collateral), or the position size in USDT, or coins '
     '— converted at today\'s price and the leverage below'),
    ('leverage', 'leverage', 'num', 'Leverage',
     '1 to 125. Position size = investment x leverage. '
     'Leave blank on spot'),
    ('risk_profile', 'risk_profile', 'text', 'Risk profile',
     'optional: a named set of limits from this fleet\'s risk_profiles; '
     'anything you fill in here wins over it (D57)'),
]

GRID = {
    'The basics': COMMON + [
        ('market_type', 'market_type', 'choice:linear|inverse|spot',
         'Market type',
         'linear = USDT/USDC futures; inverse = coin-margined futures; spot'),
    ],
    'The range': [
        ('lower', 'lower', 'num', 'Lowest price', 'the bottom of the grid'),
        ('upper', 'upper', 'num', 'Highest price', 'the top of the grid'),
        ('rungs', 'rungs', 'int', 'Number of grids',
         'give this OR the gap below, not both'),
        ('spacing_pct', 'spacing_pct', 'pct', 'Gap between grids (%)',
         'give this OR the number of grids, not both'),
        ('spacing_type', 'spacing_type', 'choice:percent|fixed',
         'How the grids are spaced',
         'percent = each gap the same % of price; fixed = the same amount'),
    ],
    'Order sizes': [
        ('rung_sizing', 'rung_sizing', 'choice:equal|weighted',
         'Size at each grid', 'equal, or weighted by the list below'),
        ('rung_weights', 'rung_weights', 'weights', 'Weights',
         'one number per grid, comma separated; only with "weighted"'),
        ('place_within_pct', 'place_within_pct', 'pct',
         'Only place orders within (%) of the price',
         'grids further away wait until the price comes near. Default 5'),
        ('seed', 'seed', 'switch', 'Start with inventory',
         'on a first start, buy one piece for each grid above the price '
         'so there is something to sell straight away'),
    ],
    'Follow the price (trailing up and down)': [
        ('slide_on', 'slide', 'block', 'Let the range follow the price',
         'when the price leaves the range and stays out, the whole range '
         'moves after it'),
        ('slide_direction', 'slide.direction', 'choice:favourable|both',
         'Which way it may follow',
         'favourable = only the profitable way (a long follows up); both '
         '= the losing way too, which buys more than the investment'),
        ('slide_trigger', 'slide.trigger_rungs', 'int',
         'Grids outside before it moves', 'how far out the price must be'),
        ('slide_confirm', 'slide.confirm_seconds', 'num',
         'Seconds it must stay out', 'so a brief spike does not move it'),
        ('slide_max', 'slide.max_rungs', 'int',
         'Furthest it may travel (grids)', 'a hard limit from where it '
         'started; required when following is on'),
        ('slide_ref', 'slide.ref_position', 'num',
         'Where the price lands in the moved range',
         '0.5 = the middle; 1 = the whole ladder on the buying side'),
    ],
    'Stop loss': [
        ('stop_on', 'stop', 'block', 'Use a stop loss',
         'when it fires the bot sells its position, cancels its orders '
         'and stops for good'),
        ('stop_watch', 'stop.watch',
         'choice:mark_price|account_equity|position_sl', 'What it watches',
         'the price, the whole account\'s value, or a stop you placed on '
         'the exchange yourself'),
        ('stop_level', 'stop.level', 'num', 'Level',
         'the price (or account value) that fires it'),
        ('stop_rungs', 'stop.rungs_beyond', 'int',
         'Or: grids beyond the range',
         'use this instead of a level when the range follows the price'),
        ('stop_server', 'stop.server_side', 'switch',
         'Keep the stop on the exchange',
         'it then works even if this program is not running (futures only)'),
        ('stop_confirm', 'stop.confirm_seconds', 'num',
         'Wait before it fires (s)',
         'the price must stay past the level this long, so a quick dip '
         'that recovers does not fire it. Blank = fire at once'),
        ('stop_candle', 'stop.confirm_candle',
         'choice:1m|5m|15m|30m|1h|4h', 'Or: wait for a candle to close',
         'the stop only looks at the price when a candle of this length '
         'closes, so a wick inside it does not fire. Use this OR the '
         'seconds above'),
        ('stop_emergency', 'stop.emergency_pct', 'pct',
         'Emergency stop, further out (%)',
         'only with a wait above: if the price goes this much further past '
         'the stop, it fires at once. On Bybit futures it is kept on the '
         'exchange, so it works even if this program is not running'),
        ('stop_action', 'stop.action', 'choice:stop_bot|leave_position',
         'When it fires',
         'stop_bot = close the position and stop for good. leave_position '
         '= cancel the orders and stop, but leave the position open for '
         'you to manage yourself, unprotected'),
    ],
    'The most it may lose': [
        ('max_loss', 'max_loss', 'num', 'Most this bot may lose',
         'in money. When its own losses, closed and still open together, '
         'reach this, it closes its position and stops for good. Blank = '
         'no limit. Counts at most the last 30 days'),
        ('max_loss_since', 'max_loss_since', 'text', 'Counting losses since',
         'filled in for you when you set a limit. Clear it to start the '
         'count again from now'),
    ],
    'Limits and fine tuning': [
        ('max_position_base', 'max_position_base', 'cap',
         'Largest position (in coins)',
         'blank = the full grid; type "unbounded" for no limit'),
        ('min_position_base', 'min_position_base', 'num',
         'Coins never to sell', 'a core holding no exit and no stop touches'),
        ('exit_floor', 'exit_floor', 'choice:rung|basis',
         'How each piece is sold',
         'rung = one grid above where it was bought; basis = never below '
         'the average cost'),
        ('split_hysteresis_rungs', 'split_hysteresis_rungs', 'num',
         'Jitter guard (0 to 0.5 of a gap)',
         'holds orders still when the price wobbles on a grid'),
        ('assumed_avg_entry', 'assumed_avg_entry', 'num',
         'Your average cost (spot only)',
         'for coins you already hold and the exchange cannot price'),
        ('spot_borrow', 'spot_borrow', 'switch', 'Margin spot (borrow)',
         'spot only: lets a spot bot go short or use leverage'),
        ('spot_leverage', 'spot_leverage', 'num', 'Spot leverage',
         '1 to 10, only with margin spot'),
    ],
}

MARTINGALE = {
    'The basics': COMMON + [
        ('market_type', 'market_type', 'choice:linear|spot', 'Market type',
         'futures, or spot (D59: Bybit, long); the exits rest as sells'),
        ('spot_borrow', 'spot_borrow', 'switch', 'Margin spot (borrow)',
         'spot only: buys on borrowed money up to the spot leverage'),
        ('spot_leverage', 'spot_leverage', 'num', 'Spot leverage',
         '1 to 10, only with margin spot'),
    ],
    'The orders': [
        ('base_order_size', 'base_order_size', 'num', 'First order size',
         'in the quote currency, leverage included'),
        ('start_order_type', 'start_order_type', 'choice:market|maker',
         'How the first order goes in',
         'market = at once; maker = waits at the best price to pay the '
         'lower fee'),
        ('start_order_requote_seconds', 'start_order_requote_seconds',
         'num', 'Re-price a waiting first order after (s)',
         'maker only. Default 40'),
        ('start_order_expire_seconds', 'start_order_expire_seconds', 'num',
         'Give up on a first order after (s)',
         'maker only. Blank = keep waiting'),
        ('safety_order_size', 'safety_order_size', 'num',
         'First add-on order size', 'bought when the price moves against '
         'you'),
        ('order_size_multiplier', 'order_size_multiplier', 'num',
         'Each add-on is this many times the last', '1 = all the same size'),
        ('max_averaging_orders', 'max_averaging_orders', 'int',
         'How many add-on orders', '1 to 50'),
        ('deviation_pct', 'deviation_pct', 'pct',
         'First add-on after a move of (%)', 'against you, from the start'),
        ('deviation_step_multiplier', 'deviation_step_multiplier', 'num',
         'Each next gap is this many times wider', '1 = evenly spaced'),
        ('place_within_pct', 'place_within_pct', 'pct',
         'Only place orders within (%) of the price', 'default 5'),
    ],
    'Taking profit': [
        ('take_profit_avg_pct', 'take_profit_avg_pct', 'pct',
         'Take profit at (%) from the average price',
         'the whole position at one target. Use this OR the steps below'),
        ('take_profit_tranches', 'take_profit_tranches', 'tranches',
         'Or take profit in steps',
         'gain % : share % — for example 1:50, 2:50 sells half at +1% '
         'and half at +2%. Shares must add up to 100'),
        ('breakeven_ladder', 'breakeven_ladder', 'switch',
         'Move the stop up as steps fill',
         'after step 1 fills the stop goes to break-even; after step 2, to '
         'step 1\'s price. Needs two or more steps'),
        ('breakeven_offset_pct', 'breakeven_offset_pct', 'pct',
         'Where the first stop sits (%)',
         'how you take the hit: from the average, -0.2 gives the trade room '
         'at a small loss, 0 is break-even before fees, 0.3 locks a little '
         'profit. Blank = break-even plus fees. Below the first step'),
        ('trailing_stop_pct', 'trailing_stop_pct', 'pct',
         'Trailing stop (%)', 'a stop that follows the best price by this '
         'much. Bybit holds it on the exchange; on Hyperliquid this '
         'program watches it. Not together with the option above'),
        ('trailing_activation_pct', 'trailing_activation_pct', 'pct',
         'Start trailing after a gain of (%)',
         'the trailing stop only switches on once the price is this far '
         'in profit from the average. Blank = from the start. Not with '
         'take profit in steps, where it starts when step 1 fills'),
    ],
    'After a round': [
        ('repeat', 'repeat', 'switch', 'Start again after taking profit',
         'off = one round, then the bot stops'),
        ('repeat_cooldown_seconds', 'repeat_cooldown_seconds', 'num',
         'Wait before the next round (s)', 'only with repeat on'),
        ('reinvest', 'reinvest', 'switch', 'Grow order sizes with profit',
         'sizes follow the last 30 days of results, up to +20%'),
        ('stop_cooldown_seconds', 'stop_cooldown_seconds', 'num',
         'Wait after a stop loss (s)',
         'only when the stop loss ends the round and not the bot'),
        ('max_hold_seconds', 'max_hold_seconds', 'num',
         'Close a round still open after (s)',
         'counted from the round\'s first order; closes at the market '
         'price, in profit or loss. 3600 = an hour, 86400 = a day. Blank '
         '= no limit'),
        ('max_rounds', 'max_rounds', 'int', 'Stop after this many rounds',
         'the bot finishes that round, then stops for good. Blank = no '
         'limit. Counts at most the last 30 days'),
        ('max_rounds_since', 'max_rounds_since', 'text',
         'Counting rounds since',
         'filled in for you when you set a limit. Clear it to start the '
         'count again from now'),
    ],
    'The most it may lose': GRID['The most it may lose'],
    'Stop loss': [
        f for f in GRID['Stop loss']
        if f[1] not in ('stop.rungs_beyond', 'stop.action')] + [
        ('stop_from_base', 'stop.from_base_pct', 'pct',
         'Or: percent from the first order (%)',
         'use this instead of a level: the stop sits this far past each '
         'round\'s first order. It must be further than the last add-on'),
        ('stop_action', 'stop.action',
         'choice:stop_bot|end_round|leave_position', 'When it fires',
         'stop_bot = close and stop for good. end_round = close this '
         'round only and start again (needs the percent form above, and '
         'start-again switched on). leave_position = cancel the orders '
         'and stop, but leave the position open for you to manage '
         'yourself, unprotected'),
    ],
}

SCHEMAS = {'grid': GRID, 'martingale': MARTINGALE}
OPEN_GROUPS = ('The basics', 'The range', 'The orders', 'Taking profit')

PRESETS = {      # the quick setup: name -> (label, what it is for)
    'sideways': ('Sideways market',
                 'a grid around today\'s price: buys dips, sells rises'),
    'rising': ('Rising market',
               'a grid that starts holding coins and follows the price up'),
    'falling': ('Falling market',
                'a short grid that follows the price down'),
    'dca_long': ('Buy the dips',
                 'buys more as the price falls, sells the lot on a bounce'),
    'dca_short': ('Sell the rallies',
                  'the same, the other way: sells more as the price rises'),
    'reversal': ('Reversal (neutral)',
                 'a mid price: a short grid above it, a long grid below — '
                 'two bots on one coin, set up one after the other'),
}
CAUTION = ('careful', 'balanced', 'bold')
# careful / balanced / bold — every number here is a default, stated in the
# summary sentence and editable in the advanced form before anything is saved
GRID_HALF_WIDTH = {'careful': 0.15, 'balanced': 0.10, 'bold': 0.06}
GRID_RUNGS = {'careful': 31, 'balanced': 31, 'bold': 25}
GRID_LEVERAGE = {'careful': 2, 'balanced': 5, 'bold': 10}
DCA_LEVERAGE = {'careful': 2, 'balanced': 3, 'bold': 5}
DCA_SHAPE = {    # first gap, gap multiplier, add-on orders, take profit
    'careful': (0.015, 1.3, 6, 0.012),
    'balanced': (0.010, 1.4, 5, 0.010),
    'bold': (0.008, 1.5, 4, 0.010),
}
DCA_SIZE_MULTIPLIER = 1.5


def fields(strategy):
    return [f for group in SCHEMAS[strategy].values() for f in group]


def config_paths(strategy):
    """Every config key the advanced form reaches — the completeness spec
    compares this against config.py's key lists."""
    return {f[1] for f in fields(strategy)} | {'venue', 'strategy'}


def _num(text):
    v = float(str(text).replace(',', '').strip())
    if not math.isfinite(v):                       # "nan", "inf", 1e400
        raise ValueError(f'"{text}" is not a number a bot can use')
    return v


SIZE_UNITS = (('collateral', 'collateral (USDT, or USDC on a PERP market and on Hyperliquid)'),
              ('notional', 'position size (USDT / USDC, the market\'s own)'),
              ('coins', 'coins'))


def capital_from(size, unit, leverage, mark=None):
    """U24: the size in the unit the person thinks in -> `capital`, which
    is collateral. notional / leverage; coins x mark / leverage. A unit
    that needs the price refuses without one, by name."""
    lev = float(leverage or 1.0)
    if unit in (None, '', 'collateral'):
        return size
    if unit == 'notional':
        return size / lev
    if unit == 'coins':
        if not mark:
            raise ValueError('"Investment" in coins needs today\'s price, '
                             'which could not be read — try again or use '
                             'collateral')
        return size * mark / lev
    raise ValueError(f'unknown size unit "{unit}"')


def size_unit_select(value=None):
    opts = ''.join(f'<option value="{k}"{" selected" if k == value else ""}>'
                   f'{lb}</option>' for k, lb in SIZE_UNITS)
    return f'<select name="size_unit">{opts}</select>'


def resolve_size(form, mark_fn, leverage=None):
    """U24, the advanced form: the typed size and unit become `capital`
    (collateral) before the row is read. Returns a new form; the unit is
    spent. `mark_fn` is called only when the unit needs the price."""
    unit = (form.get('size_unit') or 'collateral').strip()
    raw = (form.get('capital') or '').strip()
    if unit == 'collateral' or not raw:
        return dict(form, size_unit='collateral')
    lev = leverage if leverage is not None else (
        _num(form['leverage']) if (form.get('leverage') or '').strip()
        else 1.0)
    mark = mark_fn() if unit == 'coins' else None
    cap = capital_from(_num(raw), unit, lev, mark)
    return dict(form, capital=f'{cap:.10g}', size_unit='collateral')


HINT_JS = """<script>(function(){
function q(n){var e=document.querySelector('[name="'+n+'"]');return e?e:null;}
var lo=q('lower'),up=q('upper'),ru=q('rungs'),gp=q('spacing_pct'),st=q('spacing_type');
if(!lo||!up||!ru||!gp)return;
function num(e){var v=parseFloat((e.value||'').replace(/,/g,''));return isFinite(v)?v:null;}
// U38: the one you type governs; the other box fills itself (as Pionex and
// Bybit do), reads dim, and is dropped on submit so the engine gets one.
var governs=(ru.value&&!gp.value)?'rungs':(gp.value&&!ru.value)?'spacing_pct':null;
var rh=document.getElementById('rungs_hint'),gh=document.getElementById('spacing_pct_hint');
function mark(e,h,derived,from){e.classList.toggle('derived',derived);
 h.textContent=derived?'\\u2190 from the '+from:'';}
function show(){var l=num(lo),u=num(up),fixed=st&&st.value==='fixed';
 mark(ru,rh,false);mark(gp,gh,false);
 if(!governs||l===null||u===null||u<=l||l<=0)return;
 if(governs==='rungs'){var r=num(ru);
  if(r===null||r<2){gp.value='';return;}
  var gap=fixed?(u-l)/(r-1)/l*100:(Math.pow(u/l,1/(r-1))-1)*100;
  gp.value=gap.toFixed(2);mark(gp,gh,true,'grid count');}
 else{var g=num(gp);
  if(g===null||g<=0){ru.value='';return;}
  var n=fixed?Math.round((u-l)/(g/100*l)+1):Math.round(Math.log(u/l)/Math.log(1+g/100)+1);
  ru.value=n;mark(ru,rh,true,'gap');}}
ru.addEventListener('input',function(){governs='rungs';show();});
gp.addEventListener('input',function(){governs='spacing_pct';show();});
[lo,up,st].forEach(function(e){if(e)e.addEventListener('input',show);});
var form=ru.form;if(form)form.addEventListener('submit',function(){
 if(gp.classList.contains('derived'))gp.disabled=true;
 if(ru.classList.contains('derived'))ru.disabled=true;});
show();})();</script>"""


def coin_list(symbols):
    """U25: the venue's own markets as a datalist — typing still works,
    and an empty list (the venue unreachable) draws nothing."""
    if not symbols:
        return ''
    return ('<datalist id="coins">'
            + ''.join(f'<option value="{html.escape(s)}">' for s in symbols)
            + '</datalist>')


def _whole(x):
    """A typed whole number is written as one: 3000 not 3000.0 — the
    file then reads as a hand would write it (U19)."""
    return int(x) if isinstance(x, float) and x.is_integer() else x


def _venue_key(venue):
    """The engine's default venue is left OUT of the row, as a blank is:
    a Bybit row written by the panel is the row a hand would write (U19)."""
    return {} if venue == 'bybit' else {'venue': venue}


def _sig(x, n=5):
    return float(f'{x:.{n}g}')


def _convert(kind, raw):
    raw = (raw or '').strip()
    if raw == '':
        return None
    if kind in ('num',):
        return _whole(_num(raw))
    if kind == 'int':
        return int(_num(raw))
    if kind == 'pct':
        return round(_num(raw) / 100.0, 10)
    if kind.startswith('choice:') or kind == 'text':
        return raw
    if kind == 'cap':
        return ('unbounded' if raw.lower() == 'unbounded'
                else _whole(_num(raw)))
    if kind == 'weights':
        return [_num(w) for w in raw.split(',') if w.strip()]
    if kind == 'tranches':
        out = []
        for part in raw.split(','):
            gain, share = part.split(':')
            out.append({'at_avg_pct': round(_num(gain) / 100.0, 10),
                        'share': round(_num(share) / 100.0, 10)})
        return out
    raise ValueError(kind)


def bot_from_form(form, venue):
    """The advanced form -> one bot row, exactly as the file would hold it.
    A blank is left OUT, so the engine's own default applies and its own
    refusal names what is missing. Raises ValueError on a field that does
    not parse, naming the label."""
    strategy = form.get('strategy', 'grid')
    bot = _venue_key(venue)
    if strategy == 'martingale':
        bot['strategy'] = 'martingale'
    blocks = {f[1] for f in fields(strategy) if f[2] == 'block'}
    for name, path, kind, label, _ in fields(strategy):
        if kind == 'block':
            continue
        head, _, leaf = path.partition('.')
        if leaf and form.get(f'{head}_on') != '1':
            continue                       # the block is switched off
        if kind == 'switch':
            value = True if form.get(name) == '1' else None
        else:
            try:
                value = _convert(kind, form.get(name))
            except (ValueError, TypeError):
                raise ValueError(f'"{label}": could not read '
                                 f'"{form.get(name)}"')
        if value is None:
            continue
        if name == 'symbol':
            value = value.upper()
        if leaf:
            bot.setdefault(head, {})[leaf] = value
        else:
            bot[path] = value
    for b in blocks:                       # switched on but left empty: the
        if form.get(f'{b}_on') == '1':     # engine says what it needs
            bot.setdefault(b, {})
    if bot.get('max_loss') and not bot.get('max_loss_since'):      # D47
        bot['max_loss_since'] = time.strftime('%Y-%m-%dT%H:%M:%SZ',
                                              time.gmtime())
    if bot.get('max_rounds') and not bot.get('max_rounds_since'):
        # D41: the count starts when the limit is set, as 3Commas' does;
        # an edit carries the stamp, so only a cleared box restarts it
        bot['max_rounds_since'] = time.strftime('%Y-%m-%dT%H:%M:%SZ',
                                                time.gmtime())
    return bot


def form_from_bot(bot):
    """The reverse, for 'copy this bot': a row back into form values."""
    strategy = bot.get('strategy', 'grid')
    out = {'strategy': strategy}
    for name, path, kind, _, _ in fields(strategy):
        head, _, leaf = path.partition('.')
        if kind == 'block':
            if bot.get(path):
                out[name] = '1'
            continue
        value = (bot.get(head) or {}).get(leaf) if leaf else bot.get(path)
        if value is None or value is False:
            continue
        if kind == 'switch':
            out[name] = '1'
        elif kind == 'pct':
            out[name] = f'{value * 100:.10g}'
        elif kind == 'weights':
            out[name] = ', '.join(f'{w:.10g}' for w in value)
        elif kind == 'tranches':
            out[name] = ', '.join(
                f"{t['at_avg_pct'] * 100:.10g}:{t['share'] * 100:.10g}"
                for t in value)
        elif isinstance(value, float):
            out[name] = f'{value:.10g}'
        else:
            out[name] = str(value)
    return out


def _quick_limits(bot, form):
    """The quick setup's one optional limit: the most the bot may lose
    (X14). Blank = none."""
    raw = (form.get('max_loss') or '').strip()
    if raw:
        try:
            bot['max_loss'] = _num(raw)
        except (ValueError, TypeError):
            raise ValueError(f'"Most this bot may lose": could not read '
                             f'"{raw}"')
        bot['max_loss_since'] = time.strftime('%Y-%m-%dT%H:%M:%SZ',
                                              time.gmtime())
    return bot


def quick_bot(form, venue, mark):
    """The quick setup: a preset and three answers -> a full bot row, every
    price derived from the mark. The row then goes through the same gates
    as any other, and opens in the advanced form for whoever wants to
    change a number."""
    preset = form.get('preset', 'sideways')
    if preset not in PRESETS:
        raise ValueError(f'unknown preset "{preset}"')
    caution = form.get('caution', 'balanced')
    if caution not in CAUTION:
        raise ValueError(f'unknown caution "{caution}"')
    symbol = (form.get('symbol') or '').strip().upper()
    if not symbol:
        raise ValueError('"Coin / market": which coin?')
    try:
        size = _num(form.get('capital'))
    except (ValueError, TypeError):
        raise ValueError('"Investment": how much?')
    unit = form.get('size_unit') or 'collateral'          # U24
    stop = form.get('stop_on') == '1'
    if preset.startswith('dca'):
        dev, step, n, tp = DCA_SHAPE[caution]
        lev = DCA_LEVERAGE[caution]
        money = _sig(capital_from(size, unit, lev, mark), 6)
        k = DCA_SIZE_MULTIPLIER
        # M2: base + every add-on must fit inside money x leverage
        unit = money * lev * 0.98 / (1.0 + sum(k ** i for i in range(n)))
        bot = {**_venue_key(venue), 'strategy': 'martingale',
               'market_type': 'linear', 'symbol': symbol,
               'side': 'long' if preset == 'dca_long' else 'short',
               'capital': money, 'leverage': lev,
               'base_order_size': _sig(unit, 4),
               'safety_order_size': _sig(unit, 4),
               'order_size_multiplier': k, 'deviation_pct': dev,
               'deviation_step_multiplier': step,
               'max_averaging_orders': n, 'take_profit_avg_pct': tp,
               'repeat': True}
        if stop:                           # past the last add-on, with room
            depth = sum(dev * step ** i for i in range(n)) * 1.25
            sign = -1.0 if bot['side'] == 'long' else 1.0
            bot['stop'] = {'watch': 'mark_price',
                           'level': _sig(mark * (1.0 + sign * depth))}
        return _quick_limits(bot, form)
    half = GRID_HALF_WIDTH[caution]
    if preset == 'reversal':
        return _quick_limits(reversal_leg(form, venue, mark, caution, half,
                                          symbol, size, unit, stop), form)
    side = 'short' if preset == 'falling' else 'long'
    money = _sig(capital_from(size, unit, GRID_LEVERAGE[caution], mark), 6)
    bot = {**_venue_key(venue), 'market_type': 'linear', 'symbol': symbol,
           'side': side, 'capital': money,
           'leverage': GRID_LEVERAGE[caution],
           'lower': _sig(mark * (1.0 - half)),
           'upper': _sig(mark * (1.0 + half)),
           'rungs': GRID_RUNGS[caution]}
    if preset in ('rising', 'falling'):
        bot['slide'] = {'direction': 'favourable', 'trigger_rungs': 2,
                        'confirm_seconds': 900, 'max_rungs': 90,
                        'ref_position': 0.5}
        hl = venue == 'hyperliquid'        # I3: the furthest link must fit
        botid = make_botid('linear', symbol, side)
        while bot['slide']['max_rungs'] > 1:
            try:
                check_link_fits(botid, widest_rung(bot),
                                16 if hl else BYBIT_LINK_LIMIT,
                                gen_chars=4 if hl else 10)
                break
            except ConfigError:
                bot['slide']['max_rungs'] -= 1
        if preset == 'rising':
            bot['seed'] = True
        if stop:
            bot['stop'] = {'watch': 'mark_price', 'rungs_beyond': 3}
    elif stop:
        edge = bot['lower'] * 0.98 if side == 'long' else bot['upper'] * 1.02
        bot['stop'] = {'watch': 'mark_price', 'level': _sig(edge)}
    return _quick_limits(bot, form)


def reversal_leg(form, venue, mark, caution, half, symbol, size, unit, stop):
    """D54: the reversal grid is two legs split at a STATIC mid — a long
    grid below it, a short grid above — on a venue that holds both sides
    of one market (Bybit hedge mode). The quick setup makes them one after
    the other: this call builds the leg `form['leg']` (long first) around
    `form['mid']` (today's mark the first time), each leg half the
    investment and half the rungs. No slide: the mid is the owner's.
    Hyperliquid holds one position per coin, so it cannot host the pair;
    the flipping single-position shape is parked (D54)."""
    if venue == 'hyperliquid':
        raise ValueError('a reversal grid is two bots on one coin, a long '
                         'below the mid and a short above — Hyperliquid '
                         'holds one position per coin, so it cannot host '
                         'the pair (D54)')
    leg = form.get('leg') or 'long'
    if leg not in ('long', 'short'):
        raise ValueError(f'unknown leg "{leg}"')
    mid = _num(form['mid']) if (form.get('mid') or '').strip() else mark
    if mid <= 0:
        raise ValueError('"Mid price": a price above zero')
    lev = GRID_LEVERAGE[caution]
    money = _sig(capital_from(size, unit, lev, mark) / 2.0, 6)
    rungs = GRID_RUNGS[caution] // 2 + 1
    bot = {**_venue_key(venue), 'market_type': 'linear', 'symbol': symbol,
           'side': leg, 'capital': money, 'leverage': lev,
           'lower': _sig(mid * (1.0 - half)) if leg == 'long' else _sig(mid),
           'upper': _sig(mid) if leg == 'long' else _sig(mid * (1.0 + half)),
           'rungs': rungs,
           '_note': (f'reversal grid (D54): the {leg} half, '
                     f"{'below' if leg == 'long' else 'above'} the mid "
                     f'{_sig(mid):g}')}
    if stop:                       # a static grid's stop is a level (X8)
        edge = bot['lower'] * 0.98 if leg == 'long' else bot['upper'] * 1.02
        bot['stop'] = {'watch': 'mark_price', 'level': _sig(edge)}
    return bot


def mirror_leg(bot):
    """U42: the other side of a market, mirrored from a written grid row —
    the same width, rungs, money and leverage on the far side of its edge:
    a long's mirror is a short from its upper up, a short's a long from its
    lower down. Slide, seed, loss clocks and notes do not carry; a level
    stop is mirrored past the new far edge. Together they are a reversal
    pair meeting at that edge (D54) without the preset's numbers."""
    if bot.get('strategy', 'grid') != 'grid' or not all(
            k in bot for k in ('lower', 'upper', 'rungs')):
        raise ValueError('only a grid row has another side to mirror')
    lower, upper = float(bot['lower']), float(bot['upper'])
    fixed = bot.get('spacing_type') == 'fixed'
    long = bot.get('side', 'long') == 'long'
    if long:
        lo, hi = upper, (upper + (upper - lower) if fixed
                         else upper * (upper / lower))
    else:
        lo, hi = (lower - (upper - lower) if fixed
                  else lower / (upper / lower)), lower
    if lo <= 0:
        raise ValueError('the mirror would reach below zero')
    out = {k: bot[k] for k in ('venue', 'market_type', 'symbol', 'capital',
                                'leverage', 'rungs', 'spacing_type',
                                'rung_sizing', 'place_within_pct')
           if k in bot}
    out.update(side='short' if long else 'long', lower=_sig(lo),
               upper=_sig(hi))
    stop = bot.get('stop') or {}
    if stop.get('watch') == 'mark_price' and stop.get('level') is not None:
        edge = out['upper'] * 1.02 if long else out['lower'] * 0.98
        out['stop'] = {'watch': 'mark_price', 'level': _sig(edge)}
    botid = make_botid(bot.get('market_type', 'linear'), bot['symbol'],
                       bot.get('side', 'long'))
    out['_note'] = (f'the other side of {botid}, mirrored at '
                    f"{_sig(upper if long else lower):g} (U42)")
    return out


def _m(v):
    """A number a person reads: no exponents, no false precision."""
    a = abs(v)
    if a >= 1000:
        return f'{v:,.0f}'
    if a >= 1:
        return f'{v:,.2f}'.rstrip('0').rstrip('.')
    return f'{v:.4g}'


def sentence(cfg, mark=None):
    """The whole bot in plain words, from a VALIDATED config. If the
    sentence reads wrong, the setup is wrong."""
    long = cfg['side'] == 'long'
    lev = cfg.get('leverage') or 1.0
    notional = cfg.get('ladder_notional') or cfg['capital'] * lev
    coins = (f" (about {notional / mark:,.4g} coins at today's price)"
             if mark else '')
    money = (f"Its investment is {_m(cfg['capital'])}"
             + (f" at {lev:g}x leverage, so up to {_m(notional)} in the "
                f'market{coins}.' if lev != 1 else f'{coins}.'))
    stop = cfg.get('stop')
    if not stop:
        stop_s = ('It has no stop loss: if the price runs against it, it '
                  'keeps what it holds.')
    elif stop['watch'] == 'mark_price' and (
            stop.get('level') is not None
            or stop.get('from_base_pct') is not None):
        if stop.get('level') is not None:
            where = f"reaches {_m(stop['level'])}"
        else:
            where = (f"{'falls' if long else 'rises'} "
                     f"{stop['from_base_pct']:.2%} from a round's first "
                     'order')
        wait = stop.get('confirm_seconds')
        held = f' and stays there {wait:g} seconds' if wait else ''
        if stop.get('confirm_candle'):
            held = f" and a {stop['confirm_candle']} candle closes there"
        if stop.get('action') == 'end_round':
            cd = cfg.get('stop_cooldown_seconds')
            stop_s = (f'If the price {where}{held} it closes that round at '
                      'a loss and starts a new one'
                      + (f' after waiting {cd:g} seconds.' if cd else '.'))
        elif stop.get('action') == 'leave_position':
            stop_s = (f'If the price {where}{held} it cancels its orders '
                      'and stops for good, but LEAVES its position open, '
                      'unprotected, for you to manage.')
        else:
            stop_s = (f'If the price {where}{held} it closes its position, '
                      'cancels its orders and stops for good.')
        if stop.get('emergency_pct') is not None:
            stop_s += (f" If the price goes {stop['emergency_pct']:.2%} "
                       'further than that, it closes at once without '
                       'waiting.')
    elif stop['watch'] == 'mark_price':
        stop_s = (f"If the price goes {stop['rungs_beyond']} grids beyond "
                  'the range it closes its position, cancels its orders '
                  'and stops for good.')
    elif stop['watch'] == 'account_equity':
        stop_s = (f"If the whole account falls to {_m(stop['level'])} it "
                  + ('cancels its orders and stops for good, but LEAVES '
                     'its position open, unprotected, for you to manage.'
                     if stop.get('action') == 'leave_position' else
                     'closes its position and stops for good.'))
    else:
        stop_s = ('It obeys the stop loss you place on the exchange '
                  'yourself.')
    loss_s = ''
    if cfg.get('max_loss'):
        loss_s = (f" If it is ever down {_m(cfg['max_loss'])} in total, "
                  'counting closed and open losses since '
                  f"{cfg['max_loss_since']}, it closes its position and "
                  'stops for good.')
    if cfg['strategy'] == 'martingale':
        n = int(cfg['max_averaging_orders'])
        depth = sum(cfg['deviation_pct'] * cfg['deviation_step_multiplier']
                    ** i for i in range(n))
        entry = ('at the market price' if cfg.get('start_order_type',
                                                  'market') == 'market'
                 else 'waiting at the best price to pay the lower fee')
        parts = [
            f"This bot {'buys' if long else 'sells'} {cfg['symbol']} in "
            f"steps. It opens with {_m(cfg['base_order_size'])}, {entry}.",
            f"Each time the price {'falls' if long else 'rises'} further "
            f"it adds to the position: up to {n} more orders, the first "
            f"after a {cfg['deviation_pct']:.2%} move, covering a move of "
            f"about {depth:.1%} in all, {_m(cfg['ladder_total_notional'])} "
            'in total.',
            money]
        tr = cfg.get('take_profit_tranches')
        if tr:
            steps = ', '.join(f"{t['share']:.0%} at {t['at_avg_pct']:.2%}"
                              for t in tr)
            parts.append('It takes profit in steps from its average '
                         f'price: {steps}.')
        else:
            parts.append('It takes profit on the whole position '
                         f"{cfg['take_profit_avg_pct']:.2%} "
                         f"{'above' if long else 'below'} its average "
                         'price.')
        if cfg.get('breakeven_ladder'):
            off = cfg.get('breakeven_offset_pct')
            at = ('break-even' if off is None else
                  'break-even before fees' if off == 0 else
                  f"{abs(off):.2%} {'above' if (off > 0) == long else 'below'} "
                  'the average')
            parts.append(f'Once the first step fills, a stop moves to {at} '
                         'and then climbs one step behind.')
        if cfg.get('trailing_stop_pct'):
            who = ('This program' if cfg.get('venue') == 'hyperliquid'
                   else 'The exchange')
            when = ''
            if cfg.get('trailing_activation_pct'):
                when = (', once the price is '
                        f"{cfg['trailing_activation_pct']:.2%} in profit")
            elif tr:
                when = ', once the first step has filled'
            parts.append(f'{who} trails a stop '
                         f"{cfg['trailing_stop_pct']:.2%} behind the best "
                         f'price{when}.')
        parts.append('After taking profit it starts again.'
                     if cfg.get('repeat') else
                     'After taking profit once, it stops.')
        if cfg.get('max_hold_seconds'):
            parts.append('A round still open after '
                         f"{cfg['max_hold_seconds'] / 3600:g} hours is "
                         'closed at the market price, in profit or loss.')
        if cfg.get('max_rounds'):
            parts.append(f"After {cfg['max_rounds']} rounds, counted from "
                         f"{cfg['max_rounds_since']}, it finishes the "
                         'round it is in and stops for good.')
        parts.append(stop_s + loss_s)
        return ' '.join(parts)
    rungs = int(cfg['rungs'])
    gap = (cfg['upper'] / cfg['lower']) ** (1.0 / (rungs - 1)) - 1.0
    parts = [
        f"This bot trades {cfg['symbol']} on {rungs} grids between "
        f"{_m(cfg['lower'])} and {_m(cfg['upper'])}, about {gap:.2%} apart.",
        (f"It buys about {_m(notional / rungs)} worth each time the price "
         'drops a grid, and sells each piece one grid higher.' if long
         else
         f"It sells about {_m(notional / rungs)} worth each time the price "
         'rises a grid, and buys each piece back one grid lower.'),
        money]
    if cfg.get('seed'):
        parts.append('On its first start it buys enough at the market to '
                     'have something to sell at every level above the '
                     'price.')
    slide = cfg.get('slide')
    if slide:
        both = slide.get('direction') == 'both'
        way = ('up or down' if both else 'up' if long else 'down')
        parts.append(
            f"When the price sits {slide['trigger_rungs']} grids outside "
            f"the range for {slide['confirm_seconds'] / 60:g} minutes, the "
            f"whole range follows it {way}, at most {slide['max_rungs']} "
            'grids from where it started.')
        if both:
            parts.append('Following the price the losing way buys MORE '
                         'than its investment.')
    parts.append(stop_s + loss_s)
    if mark is not None:
        where = ('inside' if cfg['lower'] <= mark <= cfg['upper']
                 else 'OUTSIDE')
        parts.append(f"Today's price, {_m(mark)}, is {where} the range.")
    return ' '.join(parts)


# --- the pages ---------------------------------------------------------------

IDENTITY = ('symbol', 'side', 'market_type')    # I2: what a bot IS
ALWAYS_STATED = ('side', 'market_type', 'stop_watch')
# U46: what a choice left unstated means, where the engine names no default
# of its own: no candle wait (the seconds, or at once); X1's stop_bot
BLANK_NAMES = {'stop_candle': 'none', 'stop_action': 'stop_bot'}


_MINIMAL = {
    'grid': {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
             'capital': 1000, 'lower': 100, 'upper': 200, 'rungs': 11},
    'martingale': {'strategy': 'martingale', 'market_type': 'linear',
                   'symbol': 'BTCUSDT', 'side': 'long', 'capital': 1000,
                   'base_order_size': 50, 'safety_order_size': 50,
                   'deviation_pct': 0.01, 'max_averaging_orders': 2,
                   'take_profit_avg_pct': 0.01}}
_MINIMAL_BLOCKS = {'slide': {'trigger_rungs': 1, 'max_rungs': 1,
                             'confirm_seconds': 0},
                   'stop': {'watch': 'mark_price', 'level': 50}}
_DERIVED = {'spacing_pct', 'venue', 'strategy', 'ladder_notional',
            'ladder_total_notional', 'max_rounds_since_ms', 'max_loss_since_ms'}


def engine_defaults(strategy):
    """U33: what a blank becomes, read from the engine itself — a minimal
    row validated, every key it filled in that the row did not give. Blocks
    (slide, stop) the same way with their required keys. Never typed by hand,
    so it cannot drift from config.py. Required keys map to None."""
    from gridgremlin.config import validate_config
    base = dict(_MINIMAL[strategy])
    out = {}
    for k, v in validate_config(dict(base)).items():
        if k in _DERIVED or k.startswith('_') or isinstance(v, (dict, list)):
            continue
        out[k] = None if k in base else v    # required: no default stands in
    # each block on its own row — a slide bot's stop is rung-based (X8), so
    # the two cannot share one minimal row
    for blk, need in _MINIMAL_BLOCKS.items():
        if blk == 'slide' and strategy != 'grid':
            continue
        cfg = validate_config(dict(base, **{blk: dict(need)}))
        for j, w in (cfg.get(blk) or {}).items():
            if j not in need and not j.startswith('_') and w is not None:
                out[f'{blk}.{j}'] = w
    return out


def default_words(kind, value):
    """The default as the form speaks it: percent fields as percent, flags
    as on/off, numbers as numbers."""
    if value is None:
        return 'required'
    if kind == 'pct':
        return f'default {value * 100:g}%'
    if isinstance(value, bool) or kind == 'switch':
        return 'default ' + ('on' if value else 'off')
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f'default {value}'


def _field(name, kind, label, help_, value, fixed=False, unit=None,
           default=...):
    e = html.escape
    v = e(str(value)) if value is not None else ''
    # U33: the empty box says what a blank becomes — the engine's own default,
    # or "required" — and the words vanish as soon as something is typed
    ph = (f' placeholder="{e(default_words(kind, default))}"'
          if default is not ... and kind not in ('switch', 'block')
          and not kind.startswith('choice:') else '')
    if fixed:                              # an edit never changes identity
        control = f'<b>{v}</b><input type="hidden" name="{name}" value="{v}">'
    elif kind.startswith('choice:'):
        # a blank first choice leaves the key out, so the engine's default
        # applies and the file is not littered with restated defaults
        # U46: no "(default)" — the default is named as an option. A key the
        # row does not state keeps the blank value, so the file is not
        # littered with restated defaults (U33); a key it states lists the
        # plain options with its own chosen, so nothing is dropped from the
        # file behind the owner's back (a dropped cold key reads as a change)
        choices = kind[7:].split('|')
        named = (default if default not in (..., None)
                 else BLANK_NAMES.get(name))
        if name in ALWAYS_STATED or value not in (None, '') or named is None:
            blank = ('' if name in ALWAYS_STATED or value not in (None, '')
                     else '<option value="">—</option>')
            opts = blank + ''.join(
                f'<option{" selected" if o == value else ""}>{o}</option>'
                for o in choices)
        else:
            opts = (f'<option value="" selected>{e(str(named))}</option>'
                    + ''.join(f'<option>{o}</option>' for o in choices
                              if o != named))
        control = f'<select name="{name}">{opts}</select>'
    elif kind in ('switch', 'block'):
        control = (f'<input type="checkbox" name="{name}" value="1"'
                   f'{" checked" if value == "1" else ""}>')
    elif name == 'symbol':
        control = f'<input name="{name}" value="{v}" size="14" list="coins">'
    elif name in ('rungs', 'spacing_pct'):     # U27: each shows the other
        control = (f'<input name="{name}" value="{v}" size="14"{ph}> '
                   f'<span class="dim" id="{name}_hint"></span>')
    elif name == 'capital':                # U24: the size in your unit
        control = (f'<input name="{name}" value="{v}" size="10"{ph}> '
                   + size_unit_select(unit))
    else:
        control = f'<input name="{name}" value="{v}" size="14"{ph}>'
    return (f'<tr><td>{e(label)}</td><td>{control}</td>'
            f'<td class="dim">{e(help_)}</td></tr>')


def fleet_select(fleets, chosen=0):
    opts = ''.join(
        f'<option value="{i}"{" selected" if i == chosen else ""}>'
        f'{html.escape(label)}</option>' for i, label in enumerate(fleets))
    return f'<select name="fleet">{opts}</select>'


def quick_page(fleets, chosen=0, symbols=()):
    presets = ''.join(
        f'<tr><td><label><input type="radio" name="preset" value="{k}"'
        f'{" checked" if k == "sideways" else ""}> {html.escape(lb)}'
        f'</label></td><td class="dim">{html.escape(what)}</td></tr>'
        for k, (lb, what) in PRESETS.items())
    caution = ''.join(
        f'<option{" selected" if c == "balanced" else ""}>{c}</option>'
        for c in CAUTION)
    return (
        '<h1>set up a bot <span class="dim">— three answers; today\'s '
        'price fills in the rest. Nothing is saved until you have read '
        'the summary and typed the bot\'s name.</span></h1>'
        '<form method="post" action="/setup">'
        '<input type="hidden" name="gg" value="1">'
        '<input type="hidden" name="how" value="quick">'
        f'<table>{presets}</table><table>'
        f'<tr><td>Account</td><td>{fleet_select(fleets, chosen)}</td>'
        '<td class="dim">which fleet the bot joins</td></tr>'
        '<tr><td>Which coin?</td><td><input name="symbol" size="14" '
        'list="coins" placeholder="BTCUSDT"></td><td class="dim">the '
        'venue\'s own name: BTCUSDT on Bybit, BTC on Hyperliquid'
        + (' — pick from the list or type' if symbols else '')
        + f'</td></tr>{coin_list(symbols)}'
        '<tr><td>Investment</td><td><input name="capital" size="10"> '
        f'{size_unit_select()}</td><td class="dim">what you put up '
        '(collateral), or the position\'s size in USDT, or in coins — '
        'converted at today\'s price and the preset\'s leverage</td>'
        '</tr><tr><td>How careful?</td><td><select name="caution">'
        f'{caution}</select></td><td class="dim">careful = wider and '
        'lower leverage; bold = tighter and higher</td></tr>'
        '<tr><td>Stop loss</td><td><input type="checkbox" name="stop_on" '
        'value="1"></td><td class="dim">off by default: sells everything '
        'and stops the bot for good if the price goes well past its '
        'orders</td></tr>'
        '<tr><td>Most it may lose</td><td><input name="max_loss" size="14">'
        '</td><td class="dim">optional, in money: if the bot is ever down '
        'this much in total it closes everything and stops for good. '
        'Blank = no limit</td></tr>'
        '<tr><td>Mid price</td><td><input name="mid" size="14" '
        'placeholder="today\'s price"></td><td class="dim">reversal only: '
        'the price the two halves meet at. Above today\'s price and the '
        'long half is the one working now, the short half waits above it; '
        'below, the other way round (D54)</td></tr></table>'
        '<button name="then" value="gates">Next: review the bot &rarr;'
        '</button> '
        '<button name="then" value="advanced" class="quiet">Open in the '
        'advanced form &rarr;</button> <span class="dim">(nothing above '
        'needs filling for that)</span></form>'
        '<p class="dim">or start from a blank advanced form: '
        '<a href="/setup?adv=grid">grid</a> · '
        '<a href="/setup?adv=martingale">buy-the-dips (DCA)</a> — every '
        'setting the config file accepts.</p>')


def advanced_page(strategy, values, fleets, chosen=0, note='', edit=None,
                  alert='', symbols=()):
    """edit=<botid> turns the same form into the edit door: every setting
    of an existing bot, its identity fixed."""
    groups = []
    dflts = engine_defaults(strategy)                      # U33
    for title, rows in SCHEMAS[strategy].items():
        body = ''.join(_field(n, k, lb, h, values.get(n),
                              fixed=bool(edit) and n in IDENTITY,
                              unit=values.get('size_unit'),
                              default=dflts.get(p, ...))
                       for n, p, k, lb, h in rows)
        opened = ' open' if title in OPEN_GROUPS or any(
            values.get(n) for n, *_ in rows) else ''
        groups.append(f'<details{opened}><summary>{html.escape(title)}'
                      f'</summary><table>{body}</table></details>')
    name = 'grid' if strategy == 'grid' else 'buy-the-dips (DCA)'
    if edit:
        title = (f'<h1>edit {html.escape(edit)} <span class="dim">— every '
                 'setting of this bot. The coin, direction and market type '
                 'are what the bot IS and cannot change here: remove it '
                 'and set up a new one. The running fleet keeps the old '
                 'settings until it is restarted.</span></h1>')
        account = (f'<input type="hidden" name="fleet" value="{chosen}">'
                   '<input type="hidden" name="mode" value="edit">'
                   f'<input type="hidden" name="orig" '
                   f'value="{html.escape(edit)}">'
                   f'<table><tr><td>Account</td><td><b>'
                   f'{html.escape(fleets[chosen])}</b></td>'
                   '<td class="dim">the fleet this bot is in</td></tr>')
    else:
        title = (f'<h1>advanced setup: {name} <span class="dim">— every '
                 'setting the config file accepts. Leave a field blank to '
                 'take the engine\'s default. Percent fields are typed as '
                 'percent: 1.5 means 1.5%.</span></h1>')
        account = (f'<table><tr><td>Account</td><td>'
                   f'{fleet_select(fleets, chosen)}</td>'
                   '<td class="dim">which fleet the bot joins</td></tr>')
    return (
        alert + title + note +
        '<form method="post" action="/setup">' + coin_list(symbols) + HINT_JS +
        
        '<input type="hidden" name="gg" value="1">'
        '<input type="hidden" name="how" value="advanced">'
        f'<input type="hidden" name="strategy" value="{strategy}">'
        + account +
        '<tr><td>Position limit for the alarm</td><td>'
        f'<input name="ceiling" size="14" value="'
        f'{html.escape(str(values.get("ceiling", "")))}"></td>'
        '<td class="dim">optional: the watchdog pages above this '
        'position size. Blank = no limit</td></tr></table>'
        + CHART_BOX + ''.join(groups) +
        '<button>Next: review the bot &rarr;</button></form>' + CHART_JS
        + ('<p class="dim"><a href="/">back to the fleet</a></p>' if edit
           else '<p class="dim"><a href="/setup">back to the quick setup'
                '</a></p>'))
