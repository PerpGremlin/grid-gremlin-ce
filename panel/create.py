"""The create flow's gates (docs/archive/DASHBOARD.md §11), pure and testable.

A proposal is one object: {'bot': {...}, 'watchdog': {'max': N}}. The
gates run in order — whole-fleet validation (the engine's own loaders,
coverage included), diff, keyless dry-run — and apply is an atomic file
write that ends at the file: enacting is phase 3's job.
"""
import difflib
import json
import os
import tempfile
from pathlib import Path

from gridgremlin.adapters import adapter_for
from gridgremlin.apply import row_botid, check_link_fits, make_botid, widest_rung
from gridgremlin.config import (market_rows, ConfigError, check_placeable,
                                check_venue_leverage, validate_fleet)
from gridgremlin.ladder import grid_rungs, order_qty, plan_grid, position_cap
from gridgremlin.main import BYBIT_LINK_LIMIT, check_watchdog_coverage
from gridgremlin.watchdog import validate_watchdog



def merge_proposal(fleet_raw, wd_raw, proposal):
    """Bot and watcher land together (§8: one act) — into COPIES."""
    bot = proposal['bot']
    botid = make_botid(bot['market_type'], bot['symbol'], bot['side'])
    fleet = json.loads(json.dumps(fleet_raw))
    wd = json.loads(json.dumps(wd_raw))
    if any(row_botid(b) == botid
           for b in fleet.get('bots', [])):
        raise ConfigError(f'{botid}: already in this fleet — edit or '
                          'remove it first; identities are not reused')
    fleet.setdefault('bots', []).append(bot)
    wmax = (proposal.get('watchdog') or {}).get('max')
    if wmax is not None:               # D32: a limit only when one is asked
        wd.setdefault('positions', {})[botid] = {'min': 0, 'max': wmax}
    return botid, fleet, wd


def edit_proposal(fleet_raw, wd_raw, botid, bot, wmax):
    """§11 for a changed bot: the entry and its watcher move together —
    identity is fixed (market, symbol, side never change in an edit;
    that is a remove plus a create, deliberately)."""
    new_id = make_botid(bot['market_type'], bot['symbol'], bot['side'])
    if new_id != botid:
        raise ConfigError(f'{botid}: an edit cannot change identity '
                          f'(-> {new_id}) — remove and create instead')
    fleet = json.loads(json.dumps(fleet_raw))
    wd = json.loads(json.dumps(wd_raw))
    for i, b in enumerate(fleet.get('bots', [])):
        if row_botid(b) == botid:
            fleet['bots'][i] = _in_order_of(b, bot)
            if wmax is None:           # D32: blanked = the limit is lifted
                (wd.get('positions') or {}).pop(botid, None)
            else:
                wd.setdefault('positions', {})[botid] = {'min': 0,
                                                         'max': wmax}
            return botid, fleet, wd
    raise ConfigError(f'{botid}: not in this fleet')


def _in_order_of(old, new):
    """The edited row keeps the old row's key order (one level into its
    blocks); what is new comes after. An edit that changes nothing then
    writes the file it read (U19)."""
    out = {}
    for k in list(old) + [k for k in new if k not in old]:
        if k not in new:
            continue
        v = new[k]
        if isinstance(v, dict) and isinstance(old.get(k), dict):
            v = {**{j: v[j] for j in old[k] if j in v}, **v}
        out[k] = v
    return out


def remove_proposal(fleet_raw, wd_raw, botid):
    """The bot and its watchdog line leave together — coverage would
    refuse an orphan in either direction (F1)."""
    fleet = json.loads(json.dumps(fleet_raw))
    wd = json.loads(json.dumps(wd_raw))
    before = len(fleet.get('bots', []))
    fleet['bots'] = [b for b in fleet.get('bots', [])
                     if row_botid(b) != botid]
    if len(fleet['bots']) == before:
        raise ConfigError(f'{botid}: not in this fleet')
    (wd.get('positions') or {}).pop(botid, None)
    return botid, fleet, wd


def size_jumps(fleet_raw, mode, orig, bot):
    """D64, pure: on a Mainnet fleet, the numbers to type twice — a new
    bot's capital, or an edit that raises capital or leverage past double
    what the row holds now. The gates pass a valid number; only a second
    typing catches 50000 meant as 5000. -> [(key, old, new)]"""
    if mode == 'remove' or not bot:
        return []
    if mode == 'create':
        cap = _num_or_none(bot.get('capital'))
        return [('capital', None, cap)] if cap else []
    old = next((b for b in (fleet_raw or {}).get('bots') or []
                if _raw_botid(b) == orig), None)
    if old is None:
        return []
    out = []
    for key, default in (('capital', None), ('leverage', 1.0)):
        was = _num_or_none(old.get(key, default))
        now = _num_or_none(bot.get(key, default))
        if was and now and now > 2.0 * was:
            out.append((key, was, now))
    return out


def _raw_botid(row):
    """D64c: a raw fleet row's id, or None when it has none to give. A
    portfolio row has no side and a half-typed row may lack a symbol:
    make_botid on either raised TypeError and the review of ANY edit on a
    Mainnet fleet holding one crashed (audit 2026-11-05)."""
    if not isinstance(row, dict):
        return None
    if row.get('strategy') == 'portfolio':
        return row_botid(row)
    if not (row.get('symbol') and row.get('side')):
        return None
    return make_botid(row.get('market_type') or 'linear', row['symbol'],
                      row['side'])


def retype_refusal(jumps, form):
    """D64: the first number not typed a second time, said; None when all
    match. Commas are a typist's, not a value's."""
    for key, was, now in jumps:
        got = _num_or_none(str(form.get(f'retype_{key}', '')).replace(',', ''))
        if got is None or abs(got - now) > 1e-9 * max(1.0, abs(now)):
            why = ('a new bot' if was is None
                   else f'raising it past double ({was:g} → {now:g})')
            return (f"{key}: type the new {key}, {now:g}, a second time — "
                    f'on Mainnet {why} asks for it twice')
    return None


from common.fmt import float_or as _num_or_none  # noqa: E402  (C10)


def validate_whole(fleet, wd, adapter_of):
    """Gate 1: the engine's own loaders over the MERGED result — a new bot
    is judged as part of its fleet, never alone. Returns the refusal text
    verbatim, or None. adapter_of(cfg) is injected so specs need no
    network and the panel can use public endpoints."""
    try:
        vfleet = validate_fleet(fleet)
        if vfleet.get('refused'):
            # D52 sets a bad row aside at the ENGINE; at the gate a bad row
            # is a refusal, never a quiet skip (C6's spirit, audit 10-05)
            return '; '.join(f'{w} ({lab}): {r}'
                             for w, lab, r in vfleet['refused'])
        vwd = validate_watchdog(wd)
        caps = []
        for cfg in market_rows(vfleet):
            botid = make_botid(cfg['market_type'], cfg['symbol'],
                               cfg['side'])
            cap = None
            if cfg.get('strategy', 'grid') == 'grid':
                adapter = adapter_of(cfg)
                # C5 at the gate: the engine sets an unplaceable row aside
                # dead (D52); here it is refused before it is written
                check_placeable(cfg, adapter, where=botid)
                check_venue_leverage(cfg, adapter, where=botid)     # V16
                cap = position_cap(cfg, adapter, grid_rungs(cfg, adapter))
            caps.append((botid, cap))
            hl = cfg.get('venue') == 'hyperliquid'      # I3, as the build
            check_link_fits(botid, widest_rung(cfg),
                            16 if hl else BYBIT_LINK_LIMIT,
                            gen_chars=4 if hl else 10)
        check_watchdog_coverage(caps, vwd)
    except ConfigError as e:
        return str(e)
    return None


def unified_diff(old_text, new_text, name):
    """Gate 2: the change as text — what review has always looked like."""
    return ''.join(difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=f'{name} (current)', tofile=f'{name} (proposed)'))


def dry_ladder(cfg, adapter, mark):
    """Gate 3: the orders the new bot would want at this mark — plan only,
    keyless, nothing placed."""
    return plan_grid(cfg, adapter, mark, 0.0, None, mark, mark)


def dump_config(obj):
    """The one way a config file is written: the repo's own format, so an
    edit that changes nothing writes nothing and a panel edit on the box
    is a plain diff against the committed file (U19)."""
    return json.dumps(obj, indent=2, ensure_ascii=False) + '\n'


def atomic_write(path, text):
    """Apply's only primitive: tempfile + os.replace, .bak kept. 'Safe'
    means an atomic rename, not an exception handler (the OctoBot
    safe_dump lesson, audit 2026-08-07 prior-art)."""
    p = Path(path)
    if p.exists():
        p.with_suffix(p.suffix + '.bak').write_text(p.read_text())
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(p))
    except BaseException:
        os.unlink(tmp)
        raise


HL_NETWORK = 'testnet'      # D177: set by the server from the fleets it shows
MIXED = ('this panel shows Hyperliquid fleets on both networks, so its forms '
         'cannot know which prices to read: set up the bot from the panel of '
         'its own network (D174: real money has a panel of its own)')


def set_hl_network(fleet_paths):
    """D177: the network the panel's PUBLIC Hyperliquid reads go to (prices,
    markets, candles — no key, no address), from its fleets' own switch
    (network_of); never an env guess. A panel over both is 'mixed', and
    every such read is refused in words rather than priced off the other."""
    import json as _json
    from gridgremlin.exchange.hyperliquid.client import network_of
    global HL_NETWORK
    nets = set()
    for f in fleet_paths:
        try:
            raw = _json.loads(Path(f).read_text())
        except (OSError, ValueError):
            continue
        if any((b or {}).get('venue') == 'hyperliquid' for b in raw.get('bots') or []) \
                or raw.get('venue') == 'hyperliquid':
            nets.add(network_of(raw))
    HL_NETWORK = 'mixed' if len(nets) > 1 else (nets.pop() if nets else 'testnet')
    return HL_NETWORK


def hl_network():
    if HL_NETWORK == 'mixed':
        raise ConfigError(MIXED)
    return HL_NETWORK


def _hl_public(symbol):
    """HL's public universe: (instrument entry, mark). No key, no address,
    on the panel's network (D177: the fleets' own switch, never an env)."""
    from gridgremlin.exchange.hyperliquid.client import public_info
    meta, ctxs = public_info(hl_network()).meta_and_ctxs()
    names = [e['name'] for e in meta['universe']]
    if symbol not in names:
        from gridgremlin.apply import not_listed
        raise ConfigError(not_listed(
            symbol, 'Hyperliquid lists no such market here — its markets are '
                    'named by the coin alone (BTC, ETH), and the testnet lists '
                    'fewer coins'))
    i = names.index(symbol)
    return meta['universe'][i], float(ctxs[i]['markPx'])


_SYMBOLS = {}                     # venue -> (fetched_at, [symbols]) — U25


def parse_symbols(rows):
    """Bybit's instruments-info rows -> the tradable USDT/USDC perps, sorted."""
    return sorted(r['symbol'] for r in rows
                  if r.get('status', 'Trading') == 'Trading'
                  and r.get('quoteCoin', 'USDT') in ('USDT', 'USDC'))


def public_symbols(venue, max_age=3600.0):
    """U25: the venue's own market names from public data, cached an hour;
    unreachable -> () and the form falls back to typing."""
    import time
    hit = _SYMBOLS.get(venue)
    if hit and time.time() - hit[0] < max_age:
        return hit[1]
    try:
        if venue == 'hyperliquid':
            from gridgremlin.exchange.hyperliquid.client import public_info
            meta, _ = public_info(hl_network()).meta_and_ctxs()
            out = sorted(e['name'] for e in meta['universe'])
        else:
            import json as _json
            import urllib.parse
            import urllib.request
            from gridgremlin.exchange.bybit.klines import PUBLIC_HOST
            rows, cursor = [], ''
            for _ in range(10):
                q = urllib.parse.urlencode({'category': 'linear', 'limit': 1000,
                                            'cursor': cursor})
                with urllib.request.urlopen(
                        f'{PUBLIC_HOST}/v5/market/instruments-info?{q}',
                        timeout=15) as r:
                    res = _json.load(r)['result']
                rows += res.get('list', [])
                cursor = res.get('nextPageCursor') or ''
                if not cursor:
                    break
            out = parse_symbols(rows)
    except Exception:                                      # noqa: BLE001
        return ()
    _SYMBOLS[venue] = (time.time(), tuple(out))
    return tuple(out)


def public_adapter(cfg):
    """An adapter from PUBLIC endpoints — the panel holds no keys."""
    if cfg.get('venue') == 'hyperliquid':
        from gridgremlin.exchange.hyperliquid.adapters import HLPerpAdapter
        from gridgremlin.exchange.hyperliquid.truth import (
            parse_instrument as hl_parse)
        return HLPerpAdapter(hl_parse(_hl_public(cfg['symbol'])[0]))
    from gridgremlin.exchange.bybit.klines import fetch_instrument
    from gridgremlin.exchange.bybit.truth import parse_instrument
    return adapter_for(cfg['market_type'], parse_instrument(
        cfg['market_type'],
        fetch_instrument(cfg['market_type'], cfg['symbol'])))


def public_mark(cfg):
    if cfg.get('venue') == 'hyperliquid':
        return _hl_public(cfg['symbol'])[1]
    import urllib.parse
    import urllib.request
    from gridgremlin.exchange.bybit.klines import PUBLIC_HOST
    q = urllib.parse.urlencode({'category': cfg['market_type'],
                                'symbol': cfg['symbol']})
    with urllib.request.urlopen(
            f'{PUBLIC_HOST}/v5/market/tickers?{q}', timeout=20) as r:
        rows = (json.load(r).get('result') or {}).get('list') or []
    if not rows:
        from gridgremlin.apply import not_listed
        raise ConfigError(not_listed(
            cfg['symbol'], f"Bybit lists no such {cfg['market_type']} market "
                           '— its markets are named like BTCUSDT'))
    return float(rows[0].get('markPrice') or rows[0]['lastPrice'])


_KINDS = {}                  # (venue, symbol) -> (t, market type), five minutes


def market_kind(venue, symbol):
    """U161: the quick setup has no market-type field, so the symbol says
    it — the Bybit category whose public instruments list it, judged by
    A8's own contractType check (a linear query for BTCUSD answers with the
    inverse contract, refused): 'linear', 'inverse' or 'spot'. Listed in
    none is the not-listed refusal; Hyperliquid is linear, as before. A
    network failure is raised, never read as not listed."""
    if venue == 'hyperliquid':
        return 'linear'
    import time
    from gridgremlin.exchange.bybit import klines
    from gridgremlin.exchange.bybit.truth import parse_instrument
    from gridgremlin.exchange.errors import VenueError
    key = (venue, symbol)
    hit = _KINDS.get(key)
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    for category in ('linear', 'inverse', 'spot'):
        try:
            parse_instrument(category, klines.fetch_instrument(category, symbol))
        except (IndexError, KeyError, TypeError, VenueError):
            continue
        _KINDS[key] = (time.time(), category)
        return category
    from gridgremlin.apply import not_listed
    raise ConfigError(not_listed(
        symbol, 'Bybit lists no such market — its markets are named like '
                'BTCUSDT, or BTCUSD for a coin-margined one'))


MARKET_WORDS = {'linear': 'USDT/USDC perpetual', 'inverse': 'coin-margined (inverse) perpetual',
                'spot': 'spot'}


def public_bars(cfg, days=30, bar_minutes=240):
    """A month of PUBLIC candles, oldest first, for the chart: [{t, o, h,
    l, c}]. Venue-aware like its neighbours; no key."""
    import time
    end = int(time.time() * 1000)
    start = end - days * 86_400_000
    from ggdata.candles import candles                           # D91: one candle fetcher
    venue = cfg.get('venue') or 'bybit'
    return candles(venue, cfg['market_type'], cfg['symbol'], bar_minutes, start, end,
                   network=hl_network() if venue == 'hyperliquid' else 'testnet')


def order_minimum_problem(vbot, adapter, m0):
    """U107: a DCA order under the market's smallest at today's price, in
    words (the engine learns it only at the first cycle, "base order below
    minimum"), said in the unit the size is typed in (U107b); None when
    both orders clear it. Moved out of the create flow whole (D157) so the
    form's live check and the review ask the same question."""
    import math
    # the smallest order in money at today's price — the coin minimum binds
    # on a dear coin (0.001 BTC ≈ 82)
    least = max(adapter.min_notional or 0.0, adapter.notional(adapter.min_qty, m0))
    for what, key in (('first order', 'base_order_size'),
                      ('add-on order', 'safety_order_size')):
        size = vbot.get(key)
        if not size:
            continue
        coins = vbot.get('size_in') == 'coin'     # D89
        q0 = order_qty(vbot, adapter, size, m0)      # D165: an inverse one in contracts
        if q0 <= 0 or not adapter.meets_minimum(q0, m0):
            step = adapter.qty_step
            least_c = (math.ceil(least / m0 / step - 1e-9) * step
                       if coins else None)
            return (f"the {what} ({size:g}{' coins' if coins else ''}) "
                    "is under this market's smallest order: "
                    + (f"about {least_c:.4g} coins at today's price "
                       f"({least:.4g} at {m0:g}) — " if coins else
                       f"about {least:.4g} at today's price "
                       f"({adapter.min_qty:g} coins at {m0:g}) — ") +
                    f'raise the {what} size to at least that (it is '
                    "the order's whole value, leverage included), or "
                    'raise the investment the orders are worked out from, or '
                    'use fewer add-ons'
                    # D168: what it takes to fund this ladder, its shape kept
                    + ('' if coins else
                       ". This ladder's shape needs an investment of about "
                       f"{vbot['capital'] * least / size:.4g}"))
    return None


def martingale_preview(cfg, mark):
    """§8's promise kept: the deviation ladder as numbers — every safety
    price, size, and the running total, so nobody does the compounding by
    hand (the arithmetic every 3Commas thread ends in). cfg is VALIDATED;
    anchor is the current mark. Returns (rows, full_depth_base_qty)."""
    from gridgremlin.ladder import martingale_schedule
    sched = martingale_schedule(cfg)
    sign = -1.0 if cfg['side'] == 'long' else 1.0
    rows, cum_n, cum_q = [], 0.0, 0.0
    coin_sized = cfg.get('size_in') == 'coin'          # D89
    for i, (notional, cumdev) in enumerate(sched):
        price = mark * (1.0 + sign * cumdev)
        if coin_sized:
            qty, notional = notional, notional * price
        else:
            qty = notional / price if price > 0 else 0.0
        if cfg.get('market_type') == 'inverse':      # D165: $1 contracts
            qty = notional
        cum_n += notional
        cum_q += qty
        rows.append({'rung': i, 'price': price, 'notional': notional,
                     'qty': qty, 'cum_notional': cum_n, 'cum_qty': cum_q})
    return rows, cum_q


def init_pair(fleet_path, tag, equity_min, mm_rate_max=0.5,
              staleness_seconds=600):
    """First run: write a minimal VALID fleet + watchdog pair, so the
    create flow has something to merge into — the cliff between "cloned
    the repo" and "first bot", removed. Refuses to touch existing files:
    init is for the empty world only."""
    fp = Path(fleet_path)
    wp = fp.with_name(f'watchdog.{tag}.json')
    if fp.exists() or wp.exists():
        raise ConfigError(f'{fp.name} or {wp.name} already exists — init '
                          'is for first runs; edit or create instead')
    wd = {'tag': tag,
          'snapshot': f'logs/snapshots-{tag}.jsonl',
          'state': f'logs/watchdog-{tag}.json',
          'staleness_seconds': staleness_seconds,
          'mm_rate_max': mm_rate_max,
          'equity_min': equity_min,
          're_alert_seconds': 900,
          'assumes_sole_actor': True,
          'positions': {}}
    # the engine's loader refuses an EMPTY fleet, and that refusal is
    # correct for RUNNING. init only writes the shape; the first create
    # validates the merged whole at its gate, and until then the engine
    # will not start. Deliberate. (Per-bot bounds are opt-in, D32.)
    fleet = {'bots': [], 'watchdog': str(wp)}
    fp.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(wp, dump_config(wd))
    atomic_write(fp, dump_config(fleet))
    return wp
