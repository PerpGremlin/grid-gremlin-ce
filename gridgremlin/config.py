# Config doctrine (SPEC C1-C7). The RENAMED/RETIRED tables are
# docs/archive/MIGRATION.md's refusal column, all of it. The why lives in docs/SPEC.md.

import math
import difflib

MATCH_CUTOFF = 0.7  # the one difflib cutoff (C1)

VENUES = ('bybit', 'hyperliquid')
MARKET_TYPES = ('linear', 'inverse', 'spot')
# the phone's at-a-glance venue colours (owner 2026-08-05); config.py is the
# one venue-name surface (A6), so the map lives here, not in events
VENUE_ICONS = {'bybit': '🟠⚫ Bybit',
               'hyperliquid': '🟢🟢 Hyperliquid'}   # owner's final pick
SIDES = ('long', 'short')
STRATEGIES = ('grid', 'martingale', 'portfolio')
SPACING_TYPES = ('percent', 'fixed')
EXIT_FLOORS = ('rung', 'basis')
RUNG_SIZINGS = ('equal', 'weighted')
STOP_WATCHES = ('mark_price', 'account_equity', 'position_sl')
UNBOUNDED = 'unbounded'

COMMON_KEYS = ('venue', 'market_type', 'symbol', 'side', 'strategy', 'capital',
               'leverage', 'stop', 'max_loss', 'max_loss_since', 'risk_profile',
               'holding', 'holding_since')
# D57: what a risk profile may set — the limits and guards, never what a
# bot IS (identity, lattice, sizes); a key outside this list is refused
RISK_KEYS = ('leverage', 'stop', 'max_loss', 'max_rounds', 'max_hold_seconds',
             'max_position_base', 'stop_cooldown_seconds', 'trailing_stop_pct',
             'trailing_activation_pct', 'breakeven_ladder',
             'breakeven_offset_pct')
GRID_KEYS = COMMON_KEYS + (
    'upper', 'lower', 'rungs', 'spacing_pct', 'spacing_type', 'rung_sizing',
    'rung_weights', 'place_within_pct', 'split_hysteresis_rungs',
    'assumed_avg_entry', 'min_position_base', 'max_position_base',
    'spot_borrow', 'spot_leverage', 'seed', 'slide', 'exit_floor')
MARTINGALE_KEYS = COMMON_KEYS + (
    'take_profit_tranches', 'trailing_stop_pct', 'breakeven_ladder',
    'breakeven_offset_pct', 'breakeven_activation_pct',
    'reinvest', 'repeat_cooldown_seconds', 'start_order_type',
    'start_order_requote_seconds', 'start_order_expire_seconds',
    'base_order_size', 'safety_order_size', 'order_size_multiplier',
    'deviation_pct', 'deviation_step_multiplier', 'max_averaging_orders',
    'take_profit_avg_pct', 'repeat', 'place_within_pct',
    'stop_cooldown_seconds', 'max_rounds', 'max_rounds_since',
    'max_hold_seconds', 'trailing_activation_pct', 'spot_borrow',
    'spot_leverage')
STOP_KEYS = ('watch', 'level', 'rungs_beyond', 'server_side',
             'from_base_pct', 'confirm_seconds', 'action',
             'confirm_candle', 'emergency_pct')
CANDLE_SECONDS = {'1m': 60, '5m': 300, '15m': 900, '30m': 1800,
                  '1h': 3600, '4h': 14400}        # X12: D33's candle close
STOP_ACTIONS = ('stop_bot', 'end_round',      # X1 default; D42 opt-in
                'leave_position')             # D43 opt-in
SLIDE_KEYS = ('trigger_rungs', 'max_rungs', 'ref_position', 'confirm_seconds',
              'direction')
SLIDE_DIRECTIONS = ('favourable', 'both')   # D28 default; D34 opt-in
START_ORDER_TYPES = ('market', 'maker')       # D37: the base order's entry
FLEET_KEYS = ('bots', 'poll_seconds', 'allow_mainnet', 'preflight', 'account_caps',
              'risk_profiles', 'account', 'label',
              'tombstones', 'slide_state', 'portfolio_state',
              'notify_orders', 'watchdog')

# C2 — renames. old key -> (new key, message).
RENAMED = {
    'investment': ('capital', "renamed: 'investment' is now 'capital' — the quote margin "
                   "you commit; the engine derives exposure as capital x leverage"),
    'category': ('market_type', "renamed: 'category' is now 'market_type' "
                 "(linear / inverse / spot)"),
    'split_deadband_rungs': ('split_hysteresis_rungs', "renamed: "
                             "'split_deadband_rungs' is now 'split_hysteresis_rungs'"),
    'type': ('watch', "stop is restructured: 'type' is now 'watch' "
             "(mark_price / account_equity / position_sl)"),
    'value': ('level', "stop is restructured: 'value' is now 'level'"),
}

# C2 — retirements. old key -> message. The concept left v3 (docs/archive/MIGRATION.md).
RETIRED = {
    'notional': "derived, not configured: the engine computes capital x leverage "
                "itself — remove it (set 'capital')",
    'no_trade_pct': "retired: the no-trade behaviour is emergent (DECISIONS D6) — "
                    "the suppression around an adopted basis needs no key",
    'entry_deadband_pct': "retired: the no-trade band family left v3 (DECISIONS D6)",
    'exit_deadband_pct': "retired: the no-trade band family left v3 (DECISIONS D6)",
    'exit_markup_pct': "retired: the fee floor is an internal constant (SPEC G6), "
                       "not a knob",
    'exit_against': "retired: the exit floor is unconditional (SPEC G6) — there is "
                    "no 'rung' bypass",
    'arm_order': "retired: entries arm nearest-first; furthest-first returns only "
                 "with a spec and a user (docs/archive/MIGRATION.md)",
    'trail': "retired: edit 'upper'/'lower' instead — range edits flow through the "
             "normal diff (DECISIONS D10)",
    'sma_periods': "retired: the trail feature left v3 (D10); following is 'slide' (D28)",
    'trail_min': "retired: the trail feature left v3 (D10); the clamp is 'max_rungs' under 'slide' (D28)",
    'trail_max': "retired: the trail feature left v3 (D10); the clamp is 'max_rungs' under 'slide' (D28)",
    'levels': "martingale is restructured (DECISIONS D11): a base order plus "
              "'max_averaging_orders' safety orders — see docs/archive/MIGRATION.md #3",
    'level_weights': "martingale is restructured (DECISIONS D11): sizing is "
                     "'order_size_multiplier' of the previous order",
    'first_entry': "martingale is restructured (DECISIONS D11): the round starts "
                   "from a base order — see docs/archive/MIGRATION.md #3",
    'take_profit_price': "retired: the absolute take-profit left with the "
                         "restructure (DECISIONS D11/D12); targets are relative",
}


class ConfigError(ValueError):
    """The one exception for every config refusal (C1)."""


def _refuse(msg):
    raise ConfigError(msg)


def _reject_unknown(given, allowed, where):
    """C1: unknown keys are refused at every level; '_'-prefixed keys are comments."""
    for key in given:
        if key.startswith('_') or key in allowed:
            continue
        if key in RENAMED:
            _refuse(f'{where}: {RENAMED[key][1]}')
        if key in RETIRED:
            _refuse(f'{where}: {RETIRED[key]}')
        hint = difflib.get_close_matches(key, allowed, n=1, cutoff=MATCH_CUTOFF)
        did = f" — did you mean '{hint[0]}'?" if hint else ''
        _refuse(f"{where}: unknown key '{key}'{did}")


# --- C3: the bounds helpers. Every numeric passes through one of these. -------

def _num(row, key, where, *, least=None, most=None, least_open=False,
         most_open=False, required=False, integer=False):
    v = row.get(key)
    if v is None:
        if required:
            _refuse(f"{where}: '{key}' is required")
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _refuse(f"{where}: '{key}' must be a number")
    if not math.isfinite(v):
        # every comparison with NaN is False: a NaN capital passed every
        # bound below and the bot looped on venue refusals (audit 2026-10-05)
        _refuse(f"{where}: '{key}' must be a finite number, not {v!r}")
    if integer and int(v) != v:
        _refuse(f"{where}: '{key}' must be an integer")
    if least is not None and (v <= least if least_open else v < least):
        _refuse(f"{where}: '{key}' must be {'>' if least_open else '>='} {least}")
    if most is not None and (v >= most if most_open else v > most):
        _refuse(f"{where}: '{key}' must be {'<' if most_open else '<='} {most}")
    return int(v) if integer else float(v)


def _fraction(row, key, where, *, zero_means_off=False, most=1.0):
    """C3: the one interval convention for fraction-valued keys — (0, most),
    with zero admitted only where zero means 'off' and is identical to unset."""
    return _num(row, key, where, least=0.0, least_open=not zero_means_off,
                most=most, most_open=True)


def _enum(row, key, where, allowed, default=None):
    v = row.get(key, default)
    if v not in allowed:
        _refuse(f"{where}: '{key}' must be one of {allowed}")
    return v


def _flag(row, key):
    """Config-study M16's lesson: coerce booleans unconditionally, never inside an `if`."""
    return bool(row.get(key, False))


# --- the validators -----------------------------------------------------------

def _stop_extras(stop, where, watch, server, martingale):
    """X9/X10/X11: the opt-ins beside the level — the timeout, the level as
    a percent from the round's base order, and what a fired stop ends.
    Returns only what was asked for, so a plain stop validates as before."""
    w = f'{where}.stop'
    out = {}
    confirm = _num(stop, 'confirm_seconds', w, least=0.0, least_open=True)
    pct = _fraction(stop, 'from_base_pct', w)
    action = _enum(stop, 'action', w, STOP_ACTIONS, default='stop_bot')
    candle = _enum(stop, 'confirm_candle', w, tuple(CANDLE_SECONDS),
                   default=None) if 'confirm_candle' in stop else None
    emergency = _fraction(stop, 'emergency_pct', w)
    for key, given in (('confirm_seconds', confirm is not None),
                       ('confirm_candle', candle is not None),
                       ('emergency_pct', emergency is not None),
                       ('from_base_pct', pct is not None),
                       ("action: 'end_round'", action == 'end_round')):
        if not given:
            continue
        if watch != 'mark_price':
            _refuse(f"{w}: {key} belongs to watch: mark_price — it is the "
                    'engine watching a price, and this stop watches '
                    f'{watch}')
        if server:
            _refuse(f"{w}: {key} beside server_side — the venue's stop fires "
                    'on the first touch at its own fixed level, so the '
                    'engine could keep neither promise; not both, this phase')
    if (pct is not None or action == 'end_round') and not martingale:
        _refuse(f"{w}: from_base_pct and action: 'end_round' are the "
                "martingale's — a grid has no base order and no round")
    if pct is not None and 'level' in stop:
        _refuse(f"{w}: 'level' and 'from_base_pct' are two answers to one "
                'question — pick one')
    if action == 'end_round' and pct is None:
        _refuse(f"{w}: action: 'end_round' needs 'from_base_pct' — the next "
                "round opens at a new price, where an absolute 'level' would "
                'fire at once or never (D42)')
    if action == 'leave_position':
        if watch == 'position_sl' or server or emergency is not None:
            _refuse(f"{w}: action: 'leave_position' beside a stop the venue "
                    'holds (server_side, emergency_pct, position_sl) — the '
                    'venue closes the position when that fires, so there '
                    'would be nothing left to leave (D43)')
    if confirm is not None and candle is not None:
        _refuse(f"{w}: 'confirm_seconds' and 'confirm_candle' are two "
                'cool-downs for one stop — by time or by candle close, '
                'pick one (D33)')
    if emergency is not None and confirm is None and candle is None:
        _refuse(f"{w}: 'emergency_pct' is the stop that overrides a "
                "cool-down — it needs 'confirm_seconds' or "
                "'confirm_candle'; a stop with no cool-down fires at once, "
                "and 'server_side' already keeps that one on the venue "
                '(D33)')
    if confirm is not None:
        out['confirm_seconds'] = confirm
    if candle is not None:
        out['confirm_candle'] = candle
    if emergency is not None:
        out['emergency_pct'] = emergency
    if pct is not None:
        out['from_base_pct'] = pct
    if action != 'stop_bot':
        out['action'] = action
    return out


def _validate_stop(stop, where, slide=False, martingale=False):
    """X2's shape. Sub-keys are enumerated — C1 does not stop at the row level.
    X8: a slide bot's mark_price stop is `rungs_beyond` the window, never an
    absolute `level` — the window leaves home, an absolute level does not."""
    if stop is None:
        return None
    if not isinstance(stop, dict):
        _refuse(f"{where}: 'stop' must be an object")
    _reject_unknown(stop, STOP_KEYS, f'{where}.stop')
    watch = _enum(stop, 'watch', f'{where}.stop', STOP_WATCHES)
    server = _flag(stop, 'server_side')
    if server and watch != 'mark_price':
        _refuse(f"{where}.stop: server_side applies to watch: mark_price only — "
                "account_equity lives in-process; position_sl IS the "
                'venue-hosted stop')
    extras = _stop_extras(stop, where, watch, server, martingale)
    if watch == 'position_sl':
        if 'level' in stop:
            _refuse(f"{where}.stop: 'level' does not apply to watch: position_sl — "
                    "the level is the stop-loss you placed on the venue")
        return {'watch': watch, 'server_side': False}
    if watch == 'mark_price' and slide:
        if 'level' in stop:
            _refuse(f"{where}.stop: a slide bot's window leaves home, so an absolute "
                    "'level' would be meaningless once it has — give 'rungs_beyond' "
                    '(rungs below the window for a long, above it for a short; X8)')
        r = _num(stop, 'rungs_beyond', f'{where}.stop', least=1, required=True,
                 integer=True)
        return dict({'watch': watch, 'rungs_beyond': r,
                     'server_side': server}, **extras)
    if 'rungs_beyond' in stop:
        _refuse(f"{where}.stop: 'rungs_beyond' is the slide bot's stop (X8) — "
                "without 'slide', give 'level'")
    if 'from_base_pct' in extras:        # X10: the level is the round's own
        return dict({'watch': watch, 'level': None, 'server_side': server},
                    **extras)
    least = 1.0 if watch == 'account_equity' else 0.0
    level = _num(stop, 'level', f'{where}.stop', least=least, least_open=(least == 0.0),
                 required=True)
    return dict({'watch': watch, 'level': level, 'server_side': server},
                **extras)


def _derive_rungs(cfg, where):
    """G2: exactly one of rungs/spacing_pct given; the other derives; the stored
    pair is reconciled — the config never carries a spacing the lattice lacks."""
    import math
    has_n = cfg.get('rungs') is not None
    has_s = cfg.get('spacing_pct') is not None
    if has_n == has_s:
        _refuse(f"{where}: give exactly one of 'rungs' or 'spacing_pct'")
    upper, lower = cfg['upper'], cfg['lower']
    if has_s:
        s = _num(cfg, 'spacing_pct', where, least=0.0, least_open=True)
        if cfg['spacing_type'] == 'percent':
            n = max(2, int(math.log(upper / lower) / math.log(1.0 + s)) + 1)
        else:
            n = max(2, int(round((upper - lower) / s)) + 1)
        cfg['rungs'] = n
    n = _num(cfg, 'rungs', where, least=2, required=True, integer=True)
    cfg['rungs'] = n
    # reconcile: store the gap the lattice will actually have (N-1 divisor, G3)
    if cfg['spacing_type'] == 'percent':
        cfg['spacing_pct'] = (upper / lower) ** (1.0 / (n - 1)) - 1.0
    else:
        cfg['spacing_pct'] = (upper - lower) / (n - 1)


def _profile_name(cfg, where):
    rp = cfg.get('risk_profile')
    if rp is not None and (not isinstance(rp, str) or not rp.strip()):
        _refuse(f"{where}: 'risk_profile' names a profile in the fleet's "
                "'risk_profiles' (D57)")


def validate_grid(row, where='row'):
    _reject_unknown(row, GRID_KEYS, where)
    cfg = {k: v for k, v in row.items() if not k.startswith('_')}
    _profile_name(cfg, where)

    cfg['venue'] = _enum(cfg, 'venue', where, VENUES, default='bybit')
    cfg['market_type'] = _enum(cfg, 'market_type', where, MARKET_TYPES)
    if not isinstance(cfg.get('symbol'), str) or not cfg.get('symbol'):
        _refuse(f"{where}: 'symbol' must be a non-empty string")
    cfg['side'] = _enum(cfg, 'side', where, SIDES)
    if cfg['market_type'] == 'spot' and cfg['side'] == 'short' \
            and not cfg.get('spot_borrow'):
        _refuse(f"{where}: a spot short needs 'spot_borrow': true — only "
                'borrow can sell what is not held (D24)')
    if cfg['market_type'] == 'spot' and cfg.get('leverage') is not None:
        _refuse(f"{where}: spot does not take 'leverage' — borrow sizing is "
                "'spot_leverage' under 'spot_borrow' (D24)")
    cfg['strategy'] = 'grid'  # normalised back for BOTH strategies (config study M14)

    capital = _num(cfg, 'capital', where, least=0.0, least_open=True, required=True)
    leverage = _num(cfg, 'leverage', where, least=1.0, most=125.0)
    if leverage is None:
        leverage = 1.0
    cfg['capital'], cfg['leverage'] = capital, leverage

    lower = _num(cfg, 'lower', where, least=0.0, least_open=True, required=True)
    upper = _num(cfg, 'upper', where, least=lower, least_open=True, required=True)
    cfg['lower'], cfg['upper'] = lower, upper

    cfg['spacing_type'] = _enum(cfg, 'spacing_type', where, SPACING_TYPES,
                                default='percent')
    _derive_rungs(cfg, where)

    cfg['rung_sizing'] = _enum(cfg, 'rung_sizing', where, RUNG_SIZINGS,
                               default='equal')
    # G23 (D35): exits pair per rung by default — how every exchange grid
    # bot and 3Commas work; G6's average-cost floor is the opt-in
    cfg['exit_floor'] = _enum(cfg, 'exit_floor', where, EXIT_FLOORS,
                              default='rung')
    weights = cfg.get('rung_weights')
    if cfg['rung_sizing'] == 'weighted':
        if (not isinstance(weights, (list, tuple)) or len(weights) != cfg['rungs']
                or not all(isinstance(w, (int, float)) and not isinstance(w, bool)
                           and w > 0 for w in weights)):
            _refuse(f"{where}: weighted sizing needs 'rung_weights' — a list of "
                    f"{cfg['rungs']} positive numbers, one per rung")
        cfg['rung_weights'] = [float(w) for w in weights]
    elif weights is not None:
        _refuse(f"{where}: 'rung_weights' is only read when rung_sizing is "
                "'weighted'")

    w = _fraction(cfg, 'place_within_pct', where)
    cfg['place_within_pct'] = 0.05 if w is None else w
    h = _fraction(cfg, 'split_hysteresis_rungs', where, zero_means_off=True, most=0.5)
    cfg['split_hysteresis_rungs'] = 0.0 if h is None else h

    aae = _num(cfg, 'assumed_avg_entry', where, least=0.0, least_open=True)
    if aae is not None and cfg['market_type'] != 'spot':
        _refuse(f"{where}: 'assumed_avg_entry' applies to market_type 'spot' only — "
                "derivative venues report the average entry themselves")

    floor = _num(cfg, 'min_position_base', where, least=0.0)
    cfg['min_position_base'] = 0.0 if floor is None else floor
    cap = cfg.get('max_position_base')
    if cap is not None and cap != UNBOUNDED:
        cap = _num(cfg, 'max_position_base', where, least=0.0, least_open=True)
        if cap <= cfg['min_position_base']:
            _refuse(f"{where}: 'max_position_base' must exceed 'min_position_base'")
        cfg['max_position_base'] = cap

    slide = cfg.get('slide')
    if slide is not None:
        # D28: the slide — a ratchet, not a trail; every knob bounded (C3)
        sw = f'{where}.slide'
        if not isinstance(slide, dict):
            _refuse(f"{sw}: must be an object {{trigger_rungs, max_rungs, "
                    "confirm_seconds, ref_position, direction}}")
        _reject_unknown(slide, SLIDE_KEYS, sw)
        k = _num(slide, 'trigger_rungs', sw, least=1, required=True, integer=True)
        m = _num(slide, 'max_rungs', sw, least=1, required=True, integer=True)
        rp = _num(slide, 'ref_position', sw, least=0.0, most=1.0)   # 1.0 = all entries
        c = _num(slide, 'confirm_seconds', sw, least=0.0, required=True)
        d = _enum(slide, 'direction', sw, SLIDE_DIRECTIONS, default='favourable')
        if d == 'both' and cfg.get('max_position_base') is None:
            # D34: an adverse slide buys NEW lots beyond the ladder's capital
            # from the account's free balance; the default cap (the ladder's
            # size in base, G10) is already full of the old window's lots
            # and silently stops the new rungs part-way (measured: 5 of 10)
            _refuse(f"{sw}: direction 'both' buys beyond the ladder's capital "
                    "on an adverse slide (D34) — lift the cap "
                    "(max_position_base: \"unbounded\") or raise it to a number "
                    'you chose; the default cap is the ladder\'s own size, which '
                    "the old window's lots already fill, so it would silently "
                    'stop the new rungs part-way')
        cfg['slide'] = {'trigger_rungs': k, 'max_rungs': m,
                        'ref_position': 0.5 if rp is None else rp,
                        'confirm_seconds': c, 'direction': d}

    if cfg.get('reinvest') is not None:
        _refuse(f"{where}: grids reinvest by EDITING 'capital' — deliberate, "
                'ceiling reviewed together (D26); the toggle is martingale-only')
    cfg['seed'] = _flag(cfg, 'seed')
    cfg['spot_borrow'] = _flag(cfg, 'spot_borrow')
    sl = _num(cfg, 'spot_leverage', where, least=1.0, most=10.0)
    if (cfg['spot_borrow'] or sl is not None) and cfg['market_type'] != 'spot':
        _refuse(f"{where}: 'spot_borrow'/'spot_leverage' apply to market_type "
                "'spot' only")
    if cfg['spot_borrow'] and sl is None:
        _refuse(f"{where}: 'spot_borrow' needs 'spot_leverage' — say the "
                'multiple (D24)')
    if sl is not None and not cfg['spot_borrow']:
        _refuse(f"{where}: 'spot_leverage' without 'spot_borrow' is half a "
                'directive (D24)')
    if cfg['spot_borrow']:
        cfg['spot_leverage'] = sl
        cfg['leverage'] = sl     # D24: sizing flows the one normal path

    cfg['stop'] = _validate_stop(cfg.get('stop'), where,
                                 slide=bool(cfg.get('slide')))
    _validate_max_loss(cfg, where)
    _validate_holding(cfg, where)                                 # D76
    if (cfg['stop'] and cfg['stop']['server_side']
            and (cfg['market_type'] == 'spot'
                 or cfg['venue'] == 'hyperliquid')):
        _refuse(f"{where}.stop: server_side needs a venue that hosts "
                'position-level stops — not spot, not hyperliquid (this phase)')

    # C4: the one derived value, written back once.
    eff = 1.0
    if cfg['market_type'] != 'spot':
        eff = leverage
    elif cfg['spot_borrow']:
        eff = cfg.get('spot_leverage', 1.0)
    cfg['ladder_notional'] = capital * eff
    return cfg


SLIDE_LEVERAGE_WARN = 20.0   # the 48-day replay: 10x held, 55-75x liquidated


def slide_leverage_warning(cfg):
    """A build WARNING, not a rule — a fleet-level leverage rule needs its
    own D-number (BACKLOG §6). Pure: the replay's evidence, stated at the
    build where the row is armed."""
    if not cfg.get('slide'):
        return None
    lev = float(cfg.get('leverage') or 1.0)
    if lev <= SLIDE_LEVERAGE_WARN:
        return None
    return (f'slide at {lev:g}x: a slide deploys 3-4x the ladder in a trend, '
            'and the 48-day replay at 75x was liquidated on one dip with it '
            f'on (10x held) — above {SLIDE_LEVERAGE_WARN:g}x this is a '
            'full-ladder trend bet (JOURNAL 2026-09-25)')


def slide_adverse_warning(cfg):
    """D34: a build WARNING, never a refusal. With `direction: both` a
    `mark_price` stop at or inside the adverse trigger fires first — the stop
    is the off button (D1) — so the adverse slide this row asked for can
    never happen. Pure; says which knob to move."""
    s = cfg.get('slide') or {}
    stop = cfg.get('stop') or {}
    if s.get('direction') != 'both' or stop.get('rungs_beyond') is None:
        return None
    k, r = s['trigger_rungs'], stop['rungs_beyond']
    if r > k:
        return None
    return (f'slide direction both, but the stop sits {r} rungs beyond the '
            f'window and the adverse trigger {k}: the stop fires first and '
            'ends the bot (D1), so this window never slides the adverse way — '
            "raise stop.rungs_beyond above slide.trigger_rungs if the slide "
            'is meant to run (D34)')


def slide_adverse_commitment(cfg):
    """D34: what an adverse slide can add beyond the ladder, pure. Each
    adverse rung is one new lot at its window position's notional (the mean
    rung, ladder_notional / rungs), up to `max_rungs` of them. Returns
    (lots, notional) or None for a row that cannot slide adverse. The cap, if
    a number, may stop it sooner; the caller says so beside the figure."""
    s = cfg.get('slide') or {}
    if s.get('direction') != 'both':
        return None
    lots = int(s['max_rungs'])
    return lots, cfg['ladder_notional'] * lots / cfg['rungs']


def _validate_max_loss(cfg, where):
    """X14 (D47): the most this bot may lose, in quote money, counted from
    a stated moment — the pair travels together, as D41's does."""
    ml = _num(cfg, 'max_loss', where, least=0.0, least_open=True)
    since = cfg.get('max_loss_since')
    if (ml is None) != (since is None):
        _refuse(f"{where}: 'max_loss' and 'max_loss_since' travel together "
                "— the loss is counted from the venue's fills since a stated "
                "moment (UTC, like '2026-10-02T14:30:00Z'), so a restart "
                'cannot lose count; the panel stamps it (D47)')
    if ml is not None:
        cfg['max_loss'] = ml
        cfg['max_loss_since_ms'] = _utc_ms(since, f"{where}: "
                                           "'max_loss_since'")


def _validate_holding(cfg, where):
    """D76: what a spot bot holds, stated — the coins it owns at a stated
    moment; its book is that plus its own fills since. The pair travels
    together, as D47's does; spot only (a derivative venue states the
    position itself)."""
    h = _num(cfg, 'holding', where, least=0.0)
    since = cfg.get('holding_since')
    if (h is None) != (since is None):
        _refuse(f"{where}: 'holding' and 'holding_since' travel together — "
                'the coins this bot owns at a stated moment (UTC, like '
                "'2026-10-08T13:10:00Z'); its book is that plus its own fills "
                'since; the panel stamps it (D76)')
    if h is not None:
        if cfg['market_type'] != 'spot':
            _refuse(f"{where}: 'holding' applies to market_type 'spot' only — "
                    'a derivative venue states the position itself (D76)')
        cfg['holding'] = h
        cfg['holding_since_ms'] = _utc_ms(since, f"{where}: 'holding_since'")


def hosts_position_stop(cfg):
    """X3/X12: can this row's venue hold a stop on the position itself?
    Bybit derivatives can; spot and Hyperliquid cannot (this phase)."""
    return cfg['market_type'] != 'spot' and cfg.get('venue') != 'hyperliquid'


def _utc_ms(text, what):
    """An ISO-8601 moment, UTC unless it says otherwise -> epoch ms."""
    from datetime import datetime, timezone
    try:
        t = datetime.fromisoformat(str(text).strip().replace('Z', '+00:00'))
    except ValueError:
        _refuse(f"{what} must be a moment like '2026-10-02T14:30:00Z' "
                f'(UTC), got {text!r}')
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return int(t.timestamp() * 1000)


def _validate_tranches(v, where):
    """D23: shares of one position, ascending targets, summing to one."""
    if v is None:
        return None
    if not isinstance(v, list) or not v:
        _refuse(f"{where}: 'take_profit_tranches' must be a non-empty list")
    out, last = [], 0.0
    for i, t in enumerate(v):
        w2 = f'{where}.take_profit_tranches[{i}]'
        if not isinstance(t, dict):
            _refuse(f'{w2}: each tranche is {{at_avg_pct, share}}')
        _reject_unknown(t, ('at_avg_pct', 'share'), w2)
        pct = _fraction(t, 'at_avg_pct', w2)
        share = _num(t, 'share', w2, least=0.0, least_open=True, most=1.0)
        if pct is None or share is None or share <= 0:
            _refuse(f'{w2}: at_avg_pct and share are required, share > 0')
        if pct <= last:
            _refuse(f"{where}: tranches must ascend in 'at_avg_pct'")
        last = pct
        out.append({'at_avg_pct': pct, 'share': share})
    total = sum(t['share'] for t in out)
    if abs(total - 1.0) > 1e-6:
        _refuse(f'{where}: tranche shares sum to {total:.10g} — they are '
                'shares of ONE position, they must sum to 1')
    return out


def validate_martingale(row, where='row'):
    _reject_unknown(row, MARTINGALE_KEYS, where)
    cfg = {k: v for k, v in row.items() if not k.startswith('_')}
    _profile_name(cfg, where)

    cfg['venue'] = _enum(cfg, 'venue', where, VENUES, default='bybit')
    cfg['market_type'] = _enum(cfg, 'market_type', where, ('linear', 'spot'),
                               default='linear')
    if not isinstance(cfg.get('symbol'), str) or not cfg.get('symbol'):
        _refuse(f"{where}: 'symbol' must be a non-empty string")
    cfg['side'] = _enum(cfg, 'side', where, SIDES)
    cfg['strategy'] = 'martingale'
    # D59: a DCA bot on (margin) spot. Long only this phase — a spot short
    # borrows the COIN, a different book; leverage is the spot multiple
    cfg['spot_borrow'] = _flag(cfg, 'spot_borrow')
    sl = _num(cfg, 'spot_leverage', where, least=1.0, most=10.0)
    if cfg['market_type'] == 'spot':
        if cfg['venue'] != 'bybit':
            _refuse(f"{where}: a spot DCA bot runs on Bybit (D59)")
        if cfg['side'] != 'long':
            _refuse(f"{where}: a spot DCA bot is long this phase — a spot "
                    'short borrows the coin itself (D59)')
        if cfg['spot_borrow'] and sl is None:
            _refuse(f"{where}: 'spot_borrow' needs 'spot_leverage' (D24)")
        if sl is not None and not cfg['spot_borrow']:
            _refuse(f"{where}: 'spot_leverage' without 'spot_borrow' is half "
                    'a directive (D24)')
        if cfg.get('leverage') is not None:
            _refuse(f"{where}: spot leverage is 'spot_leverage' with "
                    "'spot_borrow' — not 'leverage' (D24/D59)")
        cfg['leverage'] = sl if cfg['spot_borrow'] else 1.0
        if sl is not None:
            cfg['spot_leverage'] = sl
    elif cfg['spot_borrow'] or sl is not None:
        _refuse(f"{where}: 'spot_borrow'/'spot_leverage' apply to market_type "
                "'spot' only")

    capital = _num(cfg, 'capital', where, least=0.0, least_open=True, required=True)
    leverage = _num(cfg, 'leverage', where, least=1.0, most=125.0) or 1.0
    cfg['capital'], cfg['leverage'] = capital, leverage
    cfg['ladder_notional'] = capital * leverage

    cfg['base_order_size'] = _num(cfg, 'base_order_size', where, least=0.0,
                                  least_open=True, required=True)
    cfg['safety_order_size'] = _num(cfg, 'safety_order_size', where, least=0.0,
                                    least_open=True, required=True)
    cfg['order_size_multiplier'] = _num(cfg, 'order_size_multiplier', where,
                                        least=1.0, most=10.0) or 1.0
    cfg['deviation_pct'] = _fraction(cfg, 'deviation_pct', where)
    if cfg['deviation_pct'] is None:
        _refuse(f"{where}: 'deviation_pct' is required")
    cfg['deviation_step_multiplier'] = _num(cfg, 'deviation_step_multiplier',
                                            where, least=1.0, most=10.0) or 1.0
    cfg['max_averaging_orders'] = _num(cfg, 'max_averaging_orders', where,
                                       least=1, most=50, required=True,
                                       integer=True)
    _sched_d = cfg['deviation_pct']
    _sched_s = cfg['deviation_step_multiplier']
    _cum = sum(_sched_d * _sched_s ** i
               for i in range(int(cfg['max_averaging_orders'])))
    if _cum >= 1.0:
        _refuse(f'{where}: the deviation schedule compounds to '
                f'{_cum:.0%} — rungs beyond -100% have negative prices, '
                'and M15 anchor recovery would invert through them. '
                'Fewer safety orders, a smaller step multiplier, or a '
                'smaller deviation (audit 2026-08-07 LOW)')
    cfg['take_profit_avg_pct'] = _fraction(cfg, 'take_profit_avg_pct', where)
    cfg['take_profit_tranches'] = _validate_tranches(
        cfg.get('take_profit_tranches'), where)
    if cfg['take_profit_avg_pct'] is None and not cfg['take_profit_tranches']:
        _refuse(f"{where}: 'take_profit_avg_pct' (or 'take_profit_tranches') "
                'is required — a round is never without an exit (M3)')
    if cfg['take_profit_avg_pct'] is not None and cfg['take_profit_tranches']:
        _refuse(f"{where}: 'take_profit_avg_pct' and 'take_profit_tranches' "
                'are two answers to one question — pick one (D23)')
    t = _fraction(cfg, 'trailing_stop_pct', where)
    if t is not None:
        cfg['trailing_stop_pct'] = t     # M11 on the venue, M21 where it
                                         # cannot host one (D31)
    act = _fraction(cfg, 'trailing_activation_pct', where)
    if act is not None:
        if t is None:
            _refuse(f"{where}: 'trailing_activation_pct' arms a trailing "
                    "stop — it needs 'trailing_stop_pct' (D31)")
        if cfg['take_profit_tranches']:
            _refuse(f"{where}: 'trailing_activation_pct' beside "
                    "'take_profit_tranches' — with tranches the trail arms "
                    'when the first one fills (M11); two activations are '
                    'two answers to one question')
        cfg['trailing_activation_pct'] = act
    w = _fraction(cfg, 'place_within_pct', where)
    cfg['place_within_pct'] = 0.05 if w is None else w
    cfg['repeat'] = _flag(cfg, 'repeat')
    cfg['reinvest'] = _flag(cfg, 'reinvest')     # M12: auto-compound toggle
    cd = _num(cfg, 'repeat_cooldown_seconds', where, least=0.0)
    if cd and not cfg['repeat']:
        _refuse(f"{where}: 'repeat_cooldown_seconds' without 'repeat' is a "
                'pause before nothing (M13)')
    cfg['repeat_cooldown_seconds'] = cd or 0.0
    if cfg.get('start_order_type') == 'limit':
        _refuse(f"{where}: 'start_order_type' 'limit' is 3Commas' — a limit at "
                'the best ask for a long, which crosses the spread: a taker fill '
                "under a limit's name. Ours is 'maker': post-only at the near "
                'side of the book, re-quoted until it fills (D37)')
    cfg['start_order_type'] = _enum(cfg, 'start_order_type', where,
                                    START_ORDER_TYPES, default='market')
    rq = _num(cfg, 'start_order_requote_seconds', where, least=1.0)
    ex = _num(cfg, 'start_order_expire_seconds', where, least=0.0,
              least_open=True)
    if (rq is not None or ex is not None) and cfg['start_order_type'] != 'maker':
        _refuse(f"{where}: 'start_order_requote_seconds'/"
                "'start_order_expire_seconds' time a resting base order — "
                "they need 'start_order_type': 'maker' (D37)")
    cfg['start_order_requote_seconds'] = 40.0 if rq is None else rq  # 3Commas'
    cfg['start_order_expire_seconds'] = ex
    cfg['stop'] = _validate_stop(cfg.get('stop'), where, martingale=True)
    _validate_max_loss(cfg, where)
    _validate_holding(cfg, where)                                 # D76
    stop = cfg['stop'] or {}
    if stop.get('from_base_pct') is not None and stop['from_base_pct'] <= _cum:
        _refuse(f"{where}.stop: from_base_pct {stop['from_base_pct']:.4%} sits "
                f'inside the safety ladder, which reaches {_cum:.4%} from the '
                'base order — the stop must lie beyond the last safety order '
                "(3Commas' rule, X10)")
    ends_round = stop.get('action') == 'end_round'
    if ends_round and not cfg['repeat']:
        _refuse(f"{where}.stop: action: 'end_round' without 'repeat' ends the "
                'only round there is — that is the default stop (D42)')
    scd = _num(cfg, 'stop_cooldown_seconds', where, least=0.0)
    if scd and not ends_round:
        _refuse(f"{where}: 'stop_cooldown_seconds' is the pause after a stop "
                "that ends the round — it needs stop.action: 'end_round'; "
                'the default stop ends the bot (D33/D42)')
    cfg['stop_cooldown_seconds'] = scd or 0.0
    mr = _num(cfg, 'max_rounds', where, least=1, integer=True)
    since = cfg.get('max_rounds_since')
    if mr is not None and not cfg['repeat']:
        _refuse(f"{where}: 'max_rounds' without 'repeat' limits a bot that "
                'runs one round anyway (D41)')
    if (mr is None) != (since is None):
        _refuse(f"{where}: 'max_rounds' and 'max_rounds_since' travel "
                'together — rounds are counted from the venue\'s fills since '
                "a stated moment (UTC, like '2026-10-02T14:30:00Z'), so a "
                'restart cannot lose count; the panel stamps it (D41)')
    if mr is not None:
        cfg['max_rounds'] = mr
        cfg['max_rounds_since_ms'] = _utc_ms(since, f"{where}: "
                                             "'max_rounds_since'")
    mh = _num(cfg, 'max_hold_seconds', where, least=60.0)
    if mh is not None:
        cfg['max_hold_seconds'] = mh
    cfg['breakeven_ladder'] = _flag(cfg, 'breakeven_ladder')
    act = _fraction(cfg, 'breakeven_activation_pct', where)       # D69
    if act is not None:
        cfg['breakeven_activation_pct'] = act
    off = _num(cfg, 'breakeven_offset_pct', where, least=-0.5, most=0.5)
    if off is not None:
        # D55: where the ladder's FIRST step sits, from the average — the
        # owner's choice of how to take the hit: below zero gives the trade
        # room at a small loss, zero is breakeven before fees, above zero
        # locks a minimum profit. Blank keeps the fee-covering default (G6).
        if not cfg['breakeven_ladder'] and act is None:
            _refuse(f"{where}: 'breakeven_offset_pct' places the breakeven "
                    "stop — it needs 'breakeven_ladder' or "
                    "'breakeven_activation_pct' (D55, D69)")
        first = (cfg['take_profit_tranches'] or [{}])[0].get('at_avg_pct')
        if first is not None and off >= first:
            _refuse(f"{where}: 'breakeven_offset_pct' {off:.4%} is at or "
                    f"beyond the first step's {first:.4%} — the stop would "
                    'sit where the price has just been and fire at once (D55)')
        cfg['breakeven_offset_pct'] = off
    if cfg['breakeven_ladder']:
        if len(cfg['take_profit_tranches'] or ()) < 2:
            _refuse(f"{where}: 'breakeven_ladder' steps on tranche fills — it "
                    "needs 'take_profit_tranches' with at least two; after a "
                    'single target there is nothing left to protect (D38)')
        if cfg.get('trailing_stop_pct') is not None:
            _refuse(f"{where}: 'breakeven_ladder' and 'trailing_stop_pct' both "
                    'arm on the first tranche and both are the stop-loss of '
                    "one position — pick one protection, as Altrady's modes "
                    'are one choice (D38)')
        if cfg['stop'] and (cfg['stop']['server_side']
                            or cfg['stop'].get('emergency_pct') is not None
                            or cfg['stop']['watch'] == 'position_sl'):
            _refuse(f"{where}: 'breakeven_ladder' writes the position's "
                    'stop-loss on the venue; a server-side, emergency or '
                    'position_sl stop is the same order book row, and '
                    'neither could tell the other apart — not both, this '
                    'phase (D38)')

    if act is not None:
        # D69, v2's activation: the stop arms once the round is this far in
        # profit, whatever the take-profit's shape. One arming rule and one
        # protection per round, as D38 has it.
        if cfg['breakeven_ladder']:
            _refuse(f"{where}: 'breakeven_activation_pct' and "
                    "'breakeven_ladder' are two arming rules for one stop — "
                    'the ladder arms on the first tranche, the activation on '
                    'profit; pick one (D69)')
        if cfg.get('trailing_stop_pct') is not None:
            _refuse(f"{where}: 'breakeven_activation_pct' and "
                    "'trailing_stop_pct' are both the stop-loss of one "
                    'position — pick one protection (D38, D69)')
        if cfg['stop'] and (cfg['stop']['server_side']
                            or cfg['stop'].get('emergency_pct') is not None
                            or cfg['stop']['watch'] == 'position_sl'):
            _refuse(f"{where}: 'breakeven_activation_pct' writes the "
                    "position's stop-loss on the venue; a server-side, "
                    'emergency or position_sl stop is the same order book '
                    'row — not both (D38, D69)')
        target = cfg['take_profit_avg_pct']
        if target is None:
            target = cfg['take_profit_tranches'][0]['at_avg_pct']
        if act >= target:
            _refuse(f"{where}: 'breakeven_activation_pct' {act:.4%} is at or "
                    f"beyond the take-profit's {target:.4%} — the round would "
                    'close before the stop ever armed (D69)')
        if off is not None and off >= act:
            _refuse(f"{where}: 'breakeven_offset_pct' {off:.4%} is at or "
                    f"beyond the activation's {act:.4%} — the stop would arm "
                    'where the price already is and fire at once (D69)')

    # M2: expand the series; refuse a ladder the capital cannot carry.
    k, n = cfg['order_size_multiplier'], cfg['max_averaging_orders']
    total = cfg['base_order_size'] + sum(
        cfg['safety_order_size'] * k ** i for i in range(n))
    if total > cfg['ladder_notional'] + 1e-9:
        margin = total / leverage
        _refuse(f"{where}: the full ladder needs {total:.10g} notional "
                f"({margin:.10g} margin at {leverage:g}x) but capital is "
                f"{capital:.10g} — lower 'max_averaging_orders', "
                "'order_size_multiplier' or the order sizes")
    cfg['ladder_total_notional'] = total
    return cfg


def validate_config(row, where='row'):
    strategy = row.get('strategy', 'grid')
    if strategy not in STRATEGIES:
        _refuse(f"{where}: 'strategy' must be one of {STRATEGIES}")
    if strategy == 'martingale':
        return validate_martingale(row, where)
    if strategy == 'portfolio':                      # D78, SPEC H1
        from .portfolio import validate_portfolio
        return validate_portfolio(row, where)
    return validate_grid(row, where)


def check_placeable(cfg, adapter, where='row'):
    """C5: a config that cannot place a single order refuses at load, with the
    reason and the numbers. Martingale needs a live base price -> slice 12."""
    if cfg['strategy'] == 'martingale':
        return cfg
    weights = cfg.get('rung_weights') or [1.0] * cfg['rungs']
    smallest = cfg['ladder_notional'] * min(weights) / sum(weights)
    qty = adapter.qty_from_notional(smallest, cfg['upper'])
    if not adapter.meets_minimum(qty, cfg['upper']):
        _refuse(f"{where}: cannot place a single order — the smallest rung "
                f"({smallest:.10g} quote, {qty:.10g} base at {cfg['upper']:.10g}) "
                "is below the venue minimum; raise 'capital' or lower 'rungs'")
    return cfg


def venue_leverage_problem(cfg, adapter):
    """V16: a row's leverage within what the venue allows on its coin ->
    the problem in words, or None. Venues that publish no cap pass."""
    cap = getattr(adapter, 'max_leverage', None)
    lev = cfg.get('leverage')
    if cap and lev and lev > cap:
        return (f"'leverage' {lev:g} is above the venue's maximum of "
                f'{cap:g}x on {cfg["symbol"]} — the venue refuses to set it, '
                'and the ladder (capital × leverage) would be sized for margin '
                f"the venue never gives; set 'leverage' to {cap:g} or less")
    return None


def check_venue_leverage(cfg, adapter, where='row'):
    """The panel's gate refuses past the cap; the build states it and leaves
    the venue as it is (hl_leverage_plan)."""
    problem = venue_leverage_problem(cfg, adapter)
    if problem:
        _refuse(f'{where}: {problem}')
    return cfg


def _validate_preflight(v, where):
    """F8 (D27): optional. probe=true places one unfillable rehearsal order
    per bot at build and cancels it — the whole placement path proven before
    any strategy order. max_failed_bots is the tolerance. D52: absent, a
    bad row — one that fails validation or its probe — is set aside by name
    and the rest start; only a fleet with nothing left to run refuses. A
    stated N refuses the fleet past N bad rows; 0 is D7's all-or-nothing."""
    if v is None:
        return {'probe': False, 'max_failed_bots': None}
    if not isinstance(v, dict):
        _refuse(f"{where}.preflight: an object: "
                '{"probe": bool, "max_failed_bots": int}')
    _reject_unknown(v, ('probe', 'max_failed_bots'), f'{where}.preflight')
    out = {'probe': _flag(v, 'probe'),
           'max_failed_bots': _num(v, 'max_failed_bots', f'{where}.preflight',
                                   least=0, integer=True)}
    return out


def _validate_caps(v, where):
    """D56, opt-in: the account may not go past these. mm_rate_max is the
    venue's maintenance-margin rate (0..1); notional_max the sum of every
    bot's position at mark, in the quote coin; `holding_max` (D70) the most
    bots that may hold at once. Any of the three; none = no cap. At the cap,
    entries pause and exits run."""
    if v is None:
        return None
    w = f'{where}.account_caps'
    if not isinstance(v, dict) or not v:
        _refuse(f'{w}: an object with mm_rate_max and/or notional_max')
    _reject_unknown(v, ('mm_rate_max', 'notional_max', 'holding_max'), w)
    out = {'mm_rate_max': _fraction(v, 'mm_rate_max', w),
           'notional_max': _num(v, 'notional_max', w, least=0.0,
                                least_open=True),
           # D70: the most bots that may hold a position at once
           'holding_max': _num(v, 'holding_max', w, least=1.0)}
    if out['holding_max'] is not None:
        if not float(out['holding_max']).is_integer():
            _refuse(f'{w}.holding_max: a whole number of bots (D70)')
        out['holding_max'] = int(out['holding_max'])
    if all(out[k] is None for k in out):
        _refuse(f'{w}: name mm_rate_max, notional_max or holding_max (D56, D70)')
    return out


def validate_profiles(v, where):
    """D57: named bundles of limits, opt-in. Each a dict of RISK_KEYS only;
    their values are judged when a row that names them is validated."""
    if v is None:
        return {}
    w = f'{where}.risk_profiles'
    if not isinstance(v, dict):
        _refuse(f'{w}: an object of name -> limits')
    for name, prof in v.items():
        if not isinstance(prof, dict) or not prof:
            _refuse(f'{w}.{name}: an object of limits')
        _reject_unknown(prof, RISK_KEYS, f'{w}.{name}')
    return {k: dict(p) for k, p in v.items()}


def apply_profile(row, profiles, where='row'):
    """D57: a row that names a profile takes its limits wherever the row
    states none; the row's own values always win; the merged row is then
    judged by the validators like any other. Rows naming nothing are
    returned untouched."""
    name = row.get('risk_profile') if isinstance(row, dict) else None
    if name is None:
        return row
    if name not in (profiles or {}):
        _refuse(f"{where}: risk_profile '{name}' is not in the fleet's "
                f"risk_profiles ({', '.join(sorted(profiles or {})) or 'none'})"
                ' (D57)')
    merged = dict(profiles[name])
    merged.update(row)
    return merged


def validate_fleet(data, where='fleet'):
    """C6 (D7) amended by D52: a bad row is set aside BY NAME with its refusal
    and the rest validate; `fleet['refused']` carries (where, label, reason)
    for the build to announce and the verdict to count. A stated tolerance
    refuses here past it (0 = D7's all-or-nothing); a fleet with no good row
    refuses whatever the tolerance. A bare list is a fleet whose only key is
    'bots' — the same key check applies either way (config M15's fix)."""
    if isinstance(data, list):
        data = {'bots': data}
    if not isinstance(data, dict):
        _refuse(f'{where}: a fleet file is an object or a list of rows')
    _reject_unknown(data, FLEET_KEYS, where)
    bots = data.get('bots')
    if not isinstance(bots, list) or not bots:
        _refuse(f"{where}: 'bots' must be a non-empty list")
    fleet = {
        'watchdog': data.get('watchdog'),
        'poll_seconds': _num(data, 'poll_seconds', where, least=0.0,
                             least_open=True) or 5.0,
        'notify_orders': _flag(data, 'notify_orders'),
        'allow_mainnet': _flag(data, 'allow_mainnet'),   # D25: half of the safety
        'preflight': _validate_preflight(data.get('preflight'), where),
        'account_caps': _validate_caps(data.get('account_caps'), where),
        'risk_profiles': validate_profiles(data.get('risk_profiles'), where),
        'tombstones': data.get('tombstones'),            # X7 path (default logs/)
        'slide_state': data.get('slide_state'),          # G22 path (default logs/)
        'portfolio_state': data.get('portfolio_state'),  # H2 path (default logs/)
        'account': _account_name(data.get('account'), where),   # H5: whose keys
        'label': _fleet_label(data.get('label'), where),         # U55: the dash's name for it
    }
    rows, refused = [], []
    for i, row in enumerate(bots):
        try:
            rows.append(validate_config(
                apply_profile(row, fleet['risk_profiles'],
                              f'{where}.bots[{i}]'),
                where=f'{where}.bots[{i}]'))
        except ConfigError as e:
            label = (f"{row.get('symbol') or '?'} {row.get('side') or '?'}"
                     if isinstance(row, dict) else 'not an object')
            refused.append((f'{where}.bots[{i}]', label, str(e)))
    listed = '; '.join(f'{w} ({lab}): {r}' for w, lab, r in refused)
    if not rows:
        _refuse(f'{where}: every row refused — nothing would run: {listed}')
    tol = fleet['preflight']['max_failed_bots']
    if tol is not None and len(refused) > tol:
        _refuse(f'{where}: {len(refused)} bad row(s), tolerance {tol} — '
                f'{listed}')
    for cfg in rows:                                   # H5: one account per process
        if cfg.get('account') not in (None, fleet['account']):
            _refuse(f"{where}: row {cfg.get('botid') or cfg.get('symbol')} names account "
                    f"'{cfg['account']}' but the fleet trades '{fleet['account']}' — one "
                    'account per fleet process (F3); give that row a fleet file of its own')
        if cfg.get('strategy') == 'portfolio':
            cfg['account'] = fleet['account']          # a row that names none is the fleet's
    fleet['bots'] = rows
    fleet['refused'] = refused
    return fleet


def market_rows(fleet):
    """The rows that trade one market — a grid or a DCA with a symbol and
    a side. A portfolio row (D78) is several legs and is read by its own
    paths; every per-market walk of a fleet starts here."""
    return [c for c in fleet['bots'] if c.get('strategy') != 'portfolio']


def _fleet_label(v, where):
    """U55: what the panel calls the fleet — the owner's words, short."""
    if v is None:
        return None
    if not isinstance(v, str) or not v.strip() or len(v) > 40:
        _refuse(f"{where}: 'label' is a short name for the dash, forty characters at most")
    return v.strip()


def _account_name(v, where):
    import re
    if v is None:
        return 'default'
    if not isinstance(v, str) or not re.fullmatch(r'[a-z0-9]{1,12}', v):
        _refuse(f"{where}: 'account' is a short lower-case name — 'default', or one "
                'whose keys .env carries as BYBIT_<NAME>_API_KEY / HL_<NAME>_SUBACCOUNT (H5)')
    return v
