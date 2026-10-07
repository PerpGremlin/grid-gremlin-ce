# Fleet build and run (SPEC E8, F1-F7, I2, I3, C5, C6). Mainnet is
# double-safetied (F7), never an accident.
import fcntl
import json
import time
from pathlib import Path

from .apply import (bot_identity, check_fleet_unique, check_link_fits,
                    make_botid, widest_rung)
from .adapters import adapter_for
from .bot import Bot
from .config import (ConfigError, VENUE_ICONS, check_placeable,
                     venue_leverage_problem,
                     slide_adverse_commitment, slide_adverse_warning,
                     slide_leverage_warning, validate_fleet)
import os

from .events import Notifier, TelegramNotifier, VenueNotifier
from .exchange.bybit.client import WriteClient
from .exchange.bybit.truth import parse_instrument
from .exchange.errors import VenueError
from .exchange.env import load_env
from .ladder import grid_rungs, position_cap
from .slide_state import SlideState, SlideStateError
from .tombstones import Tombstones, TombstoneError
from .watchdog import validate_watchdog

BYBIT_LINK_LIMIT = 36
CEILING_MULTIPLE = 1.5      # F2: a watchdog ceiling beyond this is decorative


def refuse_mainnet(client, fleet_allows=False, run_allows=False):
    """F7 (D25): mainnet fires only with BOTH safeties off — the fleet file
    declares `"allow_mainnet": true` (reviewed, committed intent) AND the
    launch passes `--allow-mainnet` (operator intent, per start). Either
    alone refuses. The demo/testnet env flags are the helmet; this is the
    armour — a cloned repo cannot reach real money by accident."""
    if client.env != 'mainnet':
        return
    from .edition import real_money_refused
    if real_money_refused():                              # D68: the public
        raise ConfigError(real_money_refused())           # edition, flatly
    missing = []
    if not fleet_allows:
        missing.append('\'"allow_mainnet": true\' in the fleet file')
    if not run_allows:
        missing.append('--allow-mainnet on the launch')
    if missing:
        raise ConfigError('mainnet is double-safetied (D25) — missing '
                          + ' AND '.join(missing))


def check_watchdog_coverage(bots_caps, watchdog_cfg):
    """F1: every bot runs under the fleet's account guards; a per-bot bound
    is opt-in (D32), and one that names no bot in the fleet is refused.
    F2: a bound that exists is pinned near the cap."""
    watched = set(watchdog_cfg['positions'])
    fleet_ids = {botid for botid, _ in bots_caps}
    for botid, cap in bots_caps:
        if botid not in watched:
            continue
        if cap is not None:
            entry = watchdog_cfg['positions'][botid]
            ceiling = entry['max']
            if ceiling < cap:
                raise ConfigError(
                    f'{botid}: watchdog ceiling {ceiling:.10g} sits below '
                    f'the cap {cap:.10g} — a healthy full grid would trip '
                    'it, and an alarm that fires in normal operation '
                    'trains you to ignore alarms (F2)')
            if ceiling > cap * CEILING_MULTIPLE and not entry.get(
                    'ceiling_loose'):
                raise ConfigError(
                    f'{botid}: ceiling {ceiling:.10g} is beyond '
                    f'{CEILING_MULTIPLE}x the cap ({cap:.10g}) — it will '
                    'not fire until the position is far past anything the '
                    "config authorises. State 'ceiling_loose': true beside "
                    'it to accept a disaster-only watcher, deliberately '
                    '(F2/D28)')
    for botid in watched - fleet_ids:
        raise ConfigError(f"watchdog watches '{botid}' which is not in the "
                          'fleet — stale entry (F1)')


def acquire_fleet_lock(path):
    """F3: one fleet process per account, enforced, not remembered."""
    handle = open(path, 'w')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise ConfigError(f'another fleet process holds {path} — one fleet '
                          'per account, ever (F3)')
    return handle


def snapshot_row(bots, wallet, now, tiers=None):
    """F4/E3: derived from venue truth only; the DEAD are visible. F9: a
    dead bot no longer reads the venue, so its position is NOTHING — not
    its last belief (the 48-day run: a killed bot's frozen size paged a
    phantom breach every re-alert window for 48 days). D65: `tiers` is the
    network each venue's client connected to, as the fleet itself holds it."""
    return {'t': now, 'equity': wallet['equity'], 'mm_rate': wallet['mm_rate'],
            **({'tiers': dict(tiers)} if tiers else {}),
            'bots': {b.botid: {'alive': b.alive,
                               'position': (b._last_pos or 0.0) if b.alive
                               else None,
                               **({'offset': b.offset} if getattr(b, 'offset', 0) else {}),
                               # X14: the loss limit and where the bot
                               # stands against it, for the panel's card
                               **({'loss': {'limit': b.cfg['max_loss'],
                                            'result': b._loss_now}}
                                  if b.alive and getattr(b, '_loss_now', None)
                                  is not None else {}),
                               # D56/D70: held back by a cap, and why
                               **({'capped': b.capped}
                                  if b.alive and getattr(b, 'capped', None)
                                  else {}),
                               # V14: the venue's margin on the position
                               **({'margin': b.margin_view}
                                  if b.alive and getattr(b, 'margin_view',
                                                         None) else {}),
                               # V15: what rests and what waits (W1)
                               **({'orders': b.orders_view}
                                  if b.alive and getattr(b, 'orders_view',
                                                         None) else {})}
                     for b in bots}}


def cap_verdict(caps, mm_rate, bots):
    """D56, pure: the reason the account is at its cap, or None. mm_rate is
    the venue's own; notional is every living bot's position at mark (the
    previous cycle's — a cap read one second late, never a guess). An
    unknown mm_rate judges nothing on that leg."""
    if not caps:
        return None
    notional = sum(getattr(b, 'notional_now', 0.0) or 0.0
                   for b in bots if b.alive)
    if caps.get('notional_max') is not None and notional >= caps['notional_max']:
        return f"notional {notional:,.0f} >= {caps['notional_max']:,.0f}"
    if (caps.get('mm_rate_max') is not None and mm_rate is not None
            and mm_rate >= caps['mm_rate_max']):
        return f"maintenance margin {mm_rate:.1%} >= {caps['mm_rate_max']:.1%}"
    return None


def holding_verdict(caps, bots):
    """D70, pure: the reason no FLAT bot may open, or None — the venue's
    living bots holding a position, counted against `holding_max`. Those
    holding are not held back by this leg: their safeties and exits run,
    and the count falls by their own closing."""
    if not caps or caps.get('holding_max') is None:
        return None
    n = sum(1 for b in bots
            if b.alive and abs(getattr(b, '_last_pos', 0.0) or 0.0) > 1e-12)
    if n >= caps['holding_max']:
        return f"bots holding {n} >= {caps['holding_max']}"
    return None


def _vn(notifier, venue):
    """Label a fleet-level event with its venue for the phone (owner ask)."""
    return VenueNotifier(notifier, VENUE_ICONS.get(venue, ''))


def preflight_verdict(failures, tolerance, total=None):
    """F8's policy, pure. D52: with no tolerance stated, the failed bots stay
    dead-and-visible and the rest run — unless every bot failed, when there
    is nothing to run and the fleet refuses. With a tolerance, beyond it the
    fleet refuses, naming every failure (D7/D27)."""
    listed = '; '.join(f'{b}: {r}' for b, r in failures)
    if tolerance is None:
        if failures and total is not None and len(failures) >= total:
            raise ConfigError(
                f'every bot failed — nothing would run: {listed}')
        return
    if len(failures) > tolerance:
        raise ConfigError(
            f'preflight failed for {len(failures)} bot(s) '
            f'(tolerance {tolerance}) — {listed}')


def probe_bot(bot):
    """F8: the dress rehearsal — one unfillable post-only order at a far
    price on the ENTRY side, resting proves the whole placement path (auth,
    permissions, collateral, lot rules), then it is cancelled. Returns None
    on success, the venue's reason on failure."""
    cfg, adapter, client = bot.cfg, bot.adapter, bot.client
    try:
        truth = client.read_symbol_truth(
            cfg['market_type'], cfg['symbol'],
            cfg.get('funding_interval_minutes', 480.0))
        mark = truth['mark']
        far = mark * (0.7 if cfg['side'] == 'long' else 1.3)
        price = adapter.round_price(far)
        floor_notional = (adapter.min_notional or 0.0) * 1.05
        qty = adapter.round_qty(max(
            adapter.min_qty,
            adapter.qty_from_notional(floor_notional, price)
            if floor_notional else adapter.min_qty))
        # round_qty rounds DOWN: 5% over the minimum value can land under
        # it again on a coarse step (live 2026-10-02: 0.528 -> 0.5 coins,
        # 4.97 against a 5 minimum, and the venue refused the probe — the
        # whole fleet with it). Step up until the venue's own rule holds.
        for _ in range(100):
            if adapter.meets_minimum(qty, price):
                break
            qty = adapter.round_qty(qty + adapter.qty_step * 1.000001)
        bot._gen += 1
        r = client.place_order(
            cfg['market_type'], cfg['symbol'], bot._entry_side,
            adapter.fmt_qty(qty), adapter.fmt_price(price),
            bot._make_link(0),
            adapter.position_idx(bot._entry_side, False) or 0,
            reduce_only=False, post_only=True,
            borrow=bool(cfg.get('spot_borrow')))
        oid = (r or {}).get('orderId') or (r or {}).get('oid')
        if oid is not None:
            for attempt in (1, 2, 3):
                try:
                    client.cancel_order(cfg['market_type'], cfg['symbol'],
                                        oid)
                    break
                except VenueError as e:
                    if e.kind == 'gone':
                        break
                    if attempt == 3:
                        # a dead bot skips cycle() forever — nobody would
                        # ever cancel this order (audit 2026-08-07 MED).
                        # Name the strand so a human can.
                        return (f'probe cancel failed 3x: order {oid} may '
                                f'REST at {price:.10g} — cancel it by '
                                f'hand ({e})')
        return None
    except Exception as e:                                   # noqa: BLE001
        return f'{type(e).__name__}: {e}'   # one bot fails, not the build


def hl_leverage_plan(cfg, adapter):
    """V16: what the build asks of HL's updateLeverage -> (leverage, is_cross,
    note). Past the coin's maximum the venue refuses and keeps what it has:
    no call, and the note says so (2026-10-06: SOL asked 15x of a 10x coin
    and the refusal read as a 'venue hiccup' at every start). An
    isolated-only coin takes the row's leverage isolated — cross is refused
    there — and the note says its margin sits outside the cross figures."""
    lev, sym = int(cfg['leverage']), cfg['symbol']
    problem = venue_leverage_problem(cfg, adapter)
    if problem:
        return None, None, f'{problem} — the venue keeps its current leverage'
    if adapter.only_isolated:
        return lev, False, (f'{sym} is isolated-only on Hyperliquid: its '
                            f'{lev}x is set isolated — a loss on it is '
                            'bounded by its own margin, and the cross '
                            'projections above do not include it')
    return lev, True, None


def leverage_refusal_note(e):
    """V16: an answered refusal (HTTP 200, status not ok) is the venue's
    word and stands until something changes — HL will not lower an open
    isolated position's leverage without margin added (2026-10-06, HYPE).
    Only a rate limit or a write of unknown fate is a hiccup."""
    if getattr(e, 'status', None) == 200 and not getattr(e, 'ambiguous', False):
        return f'the venue refused the leverage and keeps what it has: {e}'
    return f'leverage assert deferred (venue hiccup): {e}'


def placeable_or_dead(cfg, adapter):
    """C5 under D52: a row that cannot place one order builds dead-and-visible
    through the preflight's door and the rest start — counted against
    max_failed_bots like any failed bot. It used to raise out of the build:
    2026-10-06 one HYPE row's dust rungs held five HL bots in a restart
    loop. Named by symbol and side; the bare 'row' named nothing."""
    try:
        check_placeable(cfg, adapter, where=f"{cfg['symbol']} {cfg['side']}")
    except ConfigError as e:
        cfg['_preflight_fail'] = str(e)


def _logs_dir(fleet_path):
    """logs/ beside the fleet's home: configs/x.json -> configs/../logs;
    a fleet file anywhere else keeps logs as its sibling. Anchored to the
    file so every launcher agrees, whatever directory it ran from."""
    parent = Path(fleet_path).resolve().parent
    root = parent.parent if parent.name == 'configs' else parent
    return root / 'logs'


def build_fleet(fleet_path, notifier, allow_mainnet=False):
    load_env()
    fleet = validate_fleet(json.loads(Path(fleet_path).read_text()))
    for where, label, reason in fleet.get('refused', ()):
        # D52: a bad row is named and set aside; the rest start
        notifier.event('warn', 'fleet',
                       f'{where} ({label}) is skipped — {reason} — the '
                       'rest start (D52)')
    try:
        tombs = Tombstones(fleet.get('tombstones')
                           or str(_logs_dir(fleet_path)
                                  / 'tombstones.json'))
    except TombstoneError as e:
        raise ConfigError(str(e)) from e
    try:
        slide = SlideState(fleet.get('slide_state')
                           or str(_logs_dir(fleet_path) / 'slide_state.json'))
    except SlideStateError as e:            # G22: fails CLOSED like X7
        raise ConfigError(str(e)) from e
    clients, bots, identities = {}, [], []
    for cfg in fleet['bots']:
        venue = cfg['venue']
        if venue not in clients:
            armed = fleet.get('allow_mainnet', False) and allow_mainnet
            if venue == 'hyperliquid':
                from .exchange.hyperliquid.venue import HLVenueClient
                clients[venue] = HLVenueClient(allow_mainnet=armed)
            else:
                clients[venue] = WriteClient()
            refuse_mainnet(clients[venue], fleet.get('allow_mainnet', False),
                           allow_mainnet)
        client = clients[venue]
        if venue == 'hyperliquid':
            # _entry refuses BY NAME — a coin the venue removed must say so
            # (the XRP testnet delisting crashed the build as StopIteration)
            _, entry = client._entry(cfg['symbol'])
            from .exchange.hyperliquid.truth import parse_instrument as hl_pi
            spec = hl_pi(entry)
            from .exchange.hyperliquid.adapters import HLPerpAdapter
            adapter = HLPerpAdapter(spec)
        else:
            spec = parse_instrument(cfg['market_type'],
                                    client.instruments_info(cfg['market_type'],
                                                            cfg['symbol']))
            adapter = adapter_for(cfg['market_type'], spec)
        cfg['funding_interval_minutes'] = spec['funding_interval_minutes']
        if cfg.get('strategy') != 'martingale':
            # G16: the venue's own fee schedule vs this grid's own spacing —
            # a grid that cannot clear its round trip loses on every trip,
            # and nothing else in the build would ever say so.
            rates = getattr(client, 'fee_rates', None)
            if rates is not None:
                try:
                    from .ladder import grid_rungs as _g16, trip_economics
                    maker = rates(cfg['market_type'], cfg['symbol'])['maker']
                    net, gap, trip = trip_economics(_g16(cfg, adapter), maker)
                    if net is not None and net <= 0:
                        _vn(notifier, venue).event(
                            'warn', cfg['symbol'],
                            f'EVERY ROUND TRIP LOSES: rung gap {gap:.4%} vs '
                            f'round-trip fee {trip:.4%} — widen the range or '
                            f'cut rungs (G16)')
                    elif net is not None and net < trip:
                        _vn(notifier, venue).event(
                            'warn', cfg['symbol'],
                            f'thin margin: rung gap {gap:.4%} barely clears '
                            f'the {trip:.4%} round trip (net {net:.4%}/trip)')
                except (VenueError, OSError, KeyError, TypeError):
                    pass
            # B8 was pinned as a pure function and never wired to a call site
            # (audit 2026-08-06): a grid whose gap sits inside the guard band
            # churns forever, silently. It needs LIVE quotes, so it lands
            # here — stated loudly, not refused on a transient spread.
            try:
                from .ladder import (SPACING_GUARD_MULTIPLE,
                                     grid_rungs as _gr,
                                     spacing_clears_guard)
                t = client.read_symbol_truth(
                    cfg['market_type'], cfg['symbol'],
                    spec['funding_interval_minutes'])
                ok, gap, guard = spacing_clears_guard(
                    _gr(cfg, adapter), t['bid'], t['ask'])
                # the guard scales with the LIVE spread, so a grid sitting
                # within a few percent of the threshold flips either way
                # between restarts — warn on a real shortfall, not on noise
                if not ok and gap < 0.95 * SPACING_GUARD_MULTIPLE * guard:
                    _vn(notifier, venue).event(
                        'warn', cfg['symbol'],
                        f'rung gap {gap:.10g} sits inside the cross guard '
                        f'({guard:.10g}, needs '
                        f'{SPACING_GUARD_MULTIPLE * guard:.10g}) — nearest '
                        'rungs will be dropped; widen the range or cut '
                        'rungs (B8)')
            except (VenueError, OSError, KeyError, TypeError):
                pass                    # a quote we cannot read is not a verdict
        if (cfg.get('spot_borrow')
                and spec.get('margin_trading') not in (None, 'both',
                                                       'utaOnly')):
            # F8's metadata half: the venue's own catalogue says this coin
            # cannot margin-trade — ask what CAN be asked (D27)
            cfg['_preflight_fail'] = (f"venue catalogue: marginTrading="
                                      f"'{spec.get('margin_trading')}' — "
                                      'this coin cannot borrow')
        placeable_or_dead(cfg, adapter)
        bot = Bot(cfg, adapter, client, notifier, gen_seed=int(time.time()),
                  tombstones=tombs, slide_state=slide)
        if bot.offset:
            # G22: the window survived the process — say so at the start
            _vn(notifier, venue).event(
                'slide', bot.botid,
                f'resuming {bot.offset:+d} rungs from home (G22)')
        for warn in (slide_leverage_warning(cfg), slide_adverse_warning(cfg)):
            if warn:
                _vn(notifier, venue).event('warn', bot.botid, warn)
        if tombs.has(bot.botid):
            # X7: a fired stop survives the process. Dead AND visible (F4);
            # revival = the operator deletes the tombstone entry, on purpose.
            bot.alive = False
            _vn(notifier, venue).event('warn', bot.botid,
                           'tombstoned — a stop fired '
                           f'({tombs.reason(bot.botid)}); remove the entry '
                           f"from {fleet.get('tombstones') or 'logs/tombstones.json'} "
                           'to revive, deliberately')
        limit = 16 if venue == 'hyperliquid' else BYBIT_LINK_LIMIT
        chars = 4 if venue == 'hyperliquid' else 10
        check_link_fits(bot.botid, widest_rung(cfg), limit, gen_chars=chars)
        identities.append((bot.botid, bot_identity(cfg, adapter)))
        if venue == 'bybit' and cfg['market_type'] == 'linear':
            client.ensure_hedge_mode(cfg['market_type'], cfg['symbol'])
        elif (venue == 'bybit' and cfg['market_type'] == 'spot'
                and cfg.get('spot_borrow')):
            try:
                client.ensure_collateral(spec['base_coin'])
            except VenueError as e:
                _vn(notifier, venue).event('warn', cfg['symbol'],
                                           f'collateral switch deferred: {e}')
        elif venue == 'hyperliquid':
            lev, cross, note = hl_leverage_plan(cfg, adapter)
            if note:
                _vn(notifier, venue).event('warn', cfg['symbol'], note)
            try:
                if lev is not None:
                    client.update_leverage(client._entry(cfg['symbol'])[0],
                                           lev, is_cross=cross)
            except VenueError as e:
                _vn(notifier, venue).event('warn', cfg['symbol'],
                                           leverage_refusal_note(e))
        bots.append(bot)
    _ensure_symbol_capacity(bots, notifier)
    check_fleet_unique(identities)
    pf = fleet['preflight']
    failures = [(label, reason) for _, label, reason
                in fleet.get('refused', ())]          # D52: counted too
    for b in bots:
        if not b.alive:
            continue                       # tombstoned: already dead-visible
        reason = b.cfg.pop('_preflight_fail', None)
        if reason is None and pf.get('probe'):
            reason = probe_bot(b)
        if reason is not None:
            failures.append((b.botid, reason))
            b.alive = False
            _vn(notifier, b.cfg['venue']).event(
                'warn', b.botid, f'preflight FAILED — building dead: {reason}')
    preflight_verdict(failures, pf.get('max_failed_bots'),
                      total=len(bots) + len(fleet.get('refused', ())))
    if not fleet.get('watchdog'):
        raise ConfigError("the fleet has no 'watchdog' config — nothing "
                          'trades unwatched (F1)')
    if fleet.get('watchdog'):
        wd = validate_watchdog(json.loads(Path(fleet['watchdog']).read_text()))
        caps = [(b.botid,
                 position_cap(b.cfg, b.adapter, grid_rungs(b.cfg, b.adapter))
                 if b.cfg['strategy'] == 'grid' else None)
                for b in bots]
        check_watchdog_coverage(caps, wd)
    envs = ', '.join(f'{v}:{c.env}' for v, c in clients.items())
    fleet_n = (_vn(notifier, next(iter(clients))) if len(clients) == 1
               else notifier)                     # single-venue fleet: labeled
    fleet_n.event('fleet', 'fleet',
                  f'{len(bots)} bot(s) on {envs}: '
                  + ', '.join(b.botid for b in bots))
    _project_margin(clients, fleet['bots'], fleet_n)
    return fleet, clients, bots


def _ensure_symbol_capacity(bots, base_notifier):
    """Hedge-aware, ONCE per (venue, symbol): the risk tier fits the SUM of
    both legs' ladders (a small hedge leg must never downgrade the big one —
    the 110048 incident), and buy/sell leverage are set per leg."""
    notifier = _vn(base_notifier, 'bybit')       # this function IS bybit-only
    groups = {}
    for b in bots:
        if b.cfg['venue'] == 'bybit' and b.cfg['market_type'] == 'linear':
            groups.setdefault(b.cfg['symbol'], []).append(b)
    for symbol, legs in groups.items():
        client = legs[0].client
        need = sum(b.cfg['ladder_notional'] for b in legs)
        tiers = client.risk_limit_tiers('linear', symbol)
        tier = next((t for t in tiers if need <= t['limit']), tiers[-1])
        for idx in (1, 2):        # both hedge indexes, always
            try:
                client.set_risk_limit('linear', symbol, tier['id'], idx)
            except Exception as e:
                notifier.event('warn', symbol, f'risk limit: {e}')
        # the venue requires buy lv == sell lv (10001): one symbol leverage,
        # the max of the legs — margin-cheapest; ladder sizes come from config
        levs = []
        for b in legs:
            lev = min(b.cfg['leverage'], tier['max_leverage'] or b.cfg['leverage'])
            if lev != b.cfg['leverage']:
                notifier.event('warn', symbol,
                               f"{b.botid}: leverage clamped "
                               f"{b.cfg['leverage']:g} -> {lev:g} (tier max at "
                               f'{need:,.0f} symbol notional)')
                b.cfg['leverage'] = lev
            levs.append(lev)
            b.cfg['_tier_mm_rate'] = tier['mm_rate']
        symbol_lev = max(levs)
        if len(set(levs)) > 1:
            notifier.event('warn', symbol,
                           f'legs configured {sorted(set(levs))} but the venue '
                           f'requires equal buy/sell leverage — using '
                           f'{symbol_lev:g} for both (sizes unaffected)')
        client.set_leverage('linear', symbol, symbol_lev)


def _project_margin(clients, cfgs, notifier):
    equities = [c.read_wallet()['equity'] for c in clients.values()]
    if any(e is None for e in equities):
        # E9 made unknown equity None; summing None crashed the build with
        # a bare TypeError (audit 2026-08-07 LOW). Unknown is named, and
        # a projection is optional — the build proceeds without it.
        notifier.event('warn', 'fleet',
                       'margin projection skipped: a venue answered no '
                       'equity (unknown is not zero, E9)')
        return
    equity = sum(equities)
    if not equity:
        return
    mm = sum(c['ladder_notional'] * c.get('_tier_mm_rate', 0.005)
             for c in cfgs if c['market_type'] != 'spot')
    im = sum(c['capital'] for c in cfgs)
    notifier.event('fleet', 'fleet',
                   f'projected full-deployment: MM {mm / equity:.1%} of equity, '
                   f'IM {im / equity:.1%}')
    # D34: an adverse slide commits BEYOND capital. Informative (D32): the
    # figure per row at its clamp, then the fleet line with it included.
    extra_mm = extra_im = 0.0
    for c in cfgs:
        more = slide_adverse_commitment(c)
        if more is None:
            continue
        lots, notional = more
        lev = c['ladder_notional'] / c['capital'] if c['capital'] else 1.0
        extra_im += notional / lev
        if c['market_type'] != 'spot':
            extra_mm += notional * c.get('_tier_mm_rate', 0.005)
        cap = c.get('max_position_base')
        notifier.event('fleet', make_botid(c['market_type'], c['symbol'],
                                            c['side']),
                       f'adverse slide at its clamp adds up to {lots} lots, '
                       f'~{notional / equity:.1%} of equity notional beyond '
                       f'capital (IM {notional / lev / equity:.1%}); cap '
                       f'{cap if cap == "unbounded" else f"{cap:g} base"} (D34)')
    if extra_im:
        notifier.event('fleet', 'fleet',
                       'projected with every adverse slide at its clamp: '
                       f'MM {(mm + extra_mm) / equity:.1%} of equity, '
                       f'IM {(im + extra_im) / equity:.1%}')


def make_notifier():
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat = os.environ.get('TELEGRAM_CHAT_ID')
    if token and chat:
        return TelegramNotifier(token, chat)
    return Notifier()


def run(fleet_path, cycles=None, poll_seconds=None, ship_orders=None,
        snapshot=None, snapshot_every=60, lock_path=None, allow_mainnet=False):
    load_env()
    notifier = make_notifier()
    # L1: build_fleet issues account writes (hedge mode, leverage, tiers) —
    # a second launch must die BEFORE those, so a coarse per-file lock comes
    # first; the per-account lock follows once the venues are known
    # H4: /tmp is age-cleaned by systemd-tmpfiles (default 10d) — a held
    # flock does not protect the FILE, so a long-running fleet silently
    # loses its lock. Locks live beside the logs the fleet already owns.
    # cwd-relative paths meant two launches from different directories
    # held DIFFERENT locks — F3 only per-cwd (audit 2026-08-07 MED).
    # Everything anchors relative to the FLEET FILE, never the cwd.
    lockdir = _logs_dir(fleet_path)
    lockdir.mkdir(parents=True, exist_ok=True)
    prelock = acquire_fleet_lock(
        str(lockdir / f'{Path(fleet_path).resolve().name}.prelock'))
    fleet, clients, bots = build_fleet(fleet_path, notifier,
                                       allow_mainnet=allow_mainnet)
    notifier.startup = False         # D60: the start is said; now only what
                                     # needs the owner reaches the phone
    lock_tag = '+'.join(f'{v}.{c.env}' for v, c in sorted(clients.items()))
    lock = acquire_fleet_lock(lock_path
                              or str(lockdir / f'{lock_tag}.lock'))
    try:
        notifier.ship_orders = (fleet['notify_orders'] if ship_orders is None
                                else ship_orders)
        poll = poll_seconds or fleet['poll_seconds']
        n = 0
        capped_by = {}                 # D56: venue -> the cap reason
        held_by = {}                   # D70: venue -> the holding cap's
        failing = 0
        lost_warn_t = 0.0
        from .reload import FleetWatch
        watch = FleetWatch(fleet_path, bots, clients, notifier)   # F12
        while cycles is None or n < cycles:
            try:
                try:
                    watch.poll(time.time())
                except Exception as e:                       # noqa: BLE001
                    notifier.event('warn', 'fleet',
                                   f'fleet file watch: {type(e).__name__}: '
                                   f'{e} — running on (F12)')
                wallets = {}
                for v, c in clients.items():                          # E8
                    try:
                        wallets[v] = c.read_wallet()
                    except (VenueError, OSError, ValueError,
                            KeyError, IndexError) as e:
                        # one venue's trouble must not starve the other's
                        # bots of their stop evaluation (audit 2026-08-07
                        # MED — the fleet-level twin of the per-bot M3)
                        wallets[v] = {'equity': None, 'mm_rate': None}
                        _vn(notifier, v).event(
                            'net', 'fleet',
                            f'wallet read failed: {type(e).__name__}: '
                            f'{e} — '
                            'this cycle runs with unknown equity (E9)')
                known = [w['equity'] for w in wallets.values()
                         if w['equity'] is not None]
                wallet = {'equity': sum(known) if known else None,
                          'mm_rate': max((w['mm_rate'] or 0.0)
                                         for w in wallets.values())}
                caps = fleet.get('account_caps')
                if caps:                                         # D56
                    for v in wallets:
                        mine = [b for b in bots if b.cfg['venue'] == v]
                        why = cap_verdict(caps, wallets[v]['mm_rate'], mine)
                        was = capped_by.get(v)
                        if why and not was:
                            _vn(notifier, v).event(
                                'margin', 'fleet',
                                f'account cap reached: {why} — new entries '
                                'paused, exits keep working (D56)')
                        elif was and not why:
                            _vn(notifier, v).event(
                                'margin', 'fleet',
                                'account cap cleared — entries resume (D56)')
                        capped_by[v] = why
                        hold = holding_verdict(caps, mine)          # D70
                        if hold and not held_by.get(v):
                            _vn(notifier, v).event(
                                'margin', 'fleet',
                                f'holding cap reached: {hold} — flat bots '
                                'wait, holding bots run on (D70)')
                        elif held_by.get(v) and not hold:
                            _vn(notifier, v).event(
                                'margin', 'fleet',
                                'holding cap cleared — flat bots may open '
                                '(D70)')
                        held_by[v] = hold
                        for b in mine:
                            flat = not (b._last_pos or 0.0)
                            b.capped = why or (hold if flat else None)
                for bot in bots:
                    try:
                        counts = bot.cycle(
                            equity=wallets[bot.cfg['venue']]['equity'])
                    except Exception as e:              # noqa: BLE001
                        # M3: one bot's venue trouble must never starve the
                        # REST of the fleet's stop evaluation.
                        notifier.event('net', bot.botid,
                                       f'cycle lost: {type(e).__name__}: {e}')
                        continue
                    if counts is not None:
                        print(f"cycle {n} {bot.botid}: {counts}", flush=True)
                if snapshot and n % snapshot_every == 0:
                    row = snapshot_row(bots, wallet, time.time(),
                                       {v: c.env for v, c in clients.items()})
                    with open(snapshot, 'a') as f:
                        f.write(json.dumps(row) + '\n')
            except Exception as e:                       # noqa: BLE001
                # E7 at the loop: a failed read, a malformed venue response
                # (truncated JSON, an LB error page — the audit's M4), or an
                # ambiguous write — any costs THIS CYCLE, never the process.
                # No snapshot is written, so a persistent problem still
                # raises the watchdog's staleness page.
                failing += 1
                if time.time() - lost_warn_t >= 300.0:   # one page per 5 min,
                    lost_warn_t = time.time()            # not one per loss
                    import traceback
                    traceback.print_exc()
                    notifier.event('net', 'fleet',
                                   f'cycle {n} lost ({failing} in a row): '
                                   f'{type(e).__name__}: {e}')
            else:
                if failing:
                    notifier.event('net', 'fleet',
                                   f'venue readable again after {failing} '
                                   'lost cycle(s)')
                failing = 0
            if not any(b.alive for b in bots):
                print('all bots dead — fleet exits', flush=True)
                return 0
            n += 1
            if cycles is None or n < cycles:
                time.sleep(poll)
        return 0
    finally:
        if hasattr(notifier, 'close'):
            notifier.close()
        lock.close()
        prelock.close()
