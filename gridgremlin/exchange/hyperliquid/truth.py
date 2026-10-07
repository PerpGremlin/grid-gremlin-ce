# HL truth (SPEC V1-V5): the SAME schema, built from HL's answers. Funding is
# hourly at the source, so the per-hour normalisation is an identity here —
# the unit trap between venues (exchange study M16) dies in the field name.
from ..errors import VenueError
from ..truth import _f, validate_truth, validate_wallet
from .signing import cloid_to_link

FUNDING_INTERVAL_MINUTES = 60.0


def parse_instrument(entry):
    """A1's venue half. price_tick is the DECIMALS cap, not the binding rule —
    HL prices round by significant figures (see adapters)."""
    if entry.get('isDelisted'):
        raise VenueError(f"{entry['name']}: delisted")
    sz = int(entry.get('szDecimals', 0))
    step = 10.0 ** -sz
    return {'symbol': entry['name'], 'qty_step': step, 'min_qty': step,
            'price_tick': 10.0 ** -(6 - sz), 'min_notional': 10.0,
            'settle_coin': 'USDC', 'sz_decimals': sz,
            'funding_interval_minutes': FUNDING_INTERVAL_MINUTES,
            # V16: the venue's own limits on this coin's margin
            'max_leverage': int(entry.get('maxLeverage') or 0) or None,
            'only_isolated': bool(entry.get('onlyIsolated'))}


UNIFIED_MODES = ('unifiedAccount', 'portfolioMargin')


def read_wallet(client):
    """Abstraction-mode-aware (v2, measured live 2026-07-27): unified accounts
    keep collateral in the SPOT clearinghouse and MIRROR perp margin as a spot
    hold — the non-double-counting sum is perp accountValue + free spot."""
    state = client.clearinghouse_state()
    summary = state.get('marginSummary', {})
    perp_value = _f(summary.get('accountValue'), 0.0)
    maint = _f(state.get('crossMaintenanceMarginUsed'), 0.0)
    used = _f(summary.get('totalMarginUsed'), 0.0)
    perp_avail = _f(state.get('withdrawable'), 0.0)
    mode = client.user_abstraction()
    spot_total = 0.0
    equity, avail = perp_value, perp_avail
    if mode in UNIFIED_MODES:
        sp = client.spot_clearinghouse_state()
        usdc = next((b for b in sp.get('balances', [])
                     if b.get('coin') == 'USDC'), {})
        spot_total = _f(usdc.get('total'), 0.0)
        spot_free = spot_total - _f(usdc.get('hold'), 0.0)
        equity = perp_value + spot_free
        avail = perp_avail + spot_free
    return validate_wallet({
        'equity': equity,
        'available': avail,
        'mm_rate': maint / equity if equity else None,
        'im_rate': used / equity if equity else None,
        'maint_margin': maint,
        'mode': mode,
        'coins': {'USDC': {'wallet_balance': equity, 'equity': equity,
                           'available': avail, 'perp': perp_value,
                           'spot': spot_total}}})


def account_figures(client):
    """R19, as Hyperliquid states it: total position value over its account
    value (on a unified account, the USDC held as perp margin), and the
    whole collateral beside it — every position on the account, the
    owner's own included. Reads only."""
    state = client.clearinghouse_state()
    summary = state.get('marginSummary', {})
    wallet = read_wallet(client)
    return {'notional': _f(summary.get('totalNtlPos'), 0.0),
            'equity': _f(summary.get('accountValue')),
            'collateral': wallet['equity'],
            'source': 'hyperliquid'}


def read_positions(state, coin):
    """One shape, every key. stop_loss is always None on HL — trigger orders
    are not a position field here — which is exactly why watch: position_sl
    documents itself as inert on this venue."""
    out = {}
    for ap in state.get('assetPositions', []):
        p = ap.get('position', {})
        if p.get('coin') != coin:
            continue
        szi = _f(p.get('szi'), 0.0)
        if not szi:
            continue
        out[0] = {'position_idx': 0,
                  'side': 'Buy' if szi > 0 else 'Sell',
                  'size': abs(szi),
                  'avg_entry': _f(p.get('entryPx')) or None,
                  'liq_price': _f(p.get('liquidationPx')) or None,
                  'stop_loss': None,
                  'take_profit': None,
                  'trailing_stop': None,
                  'leverage': _f((p.get('leverage') or {}).get('value')),
                  'unrealised_pnl': _f(p.get('unrealizedPnl')),
                  'position_im': _f(p.get('marginUsed')),
                  'position_mm': None}      # HL states no maintenance figure
    return out


def read_orders(raw, coin):
    """V5: trigger orders excluded. HL's sz is the REMAINDER; qty is origSz."""
    out = []
    for o in raw:
        if o.get('coin') != coin or o.get('isTrigger'):
            continue
        orig = _f(o.get('origSz'), 0.0)
        left = _f(o.get('sz'), 0.0)
        out.append({'order_id': str(o.get('oid')),
                    'link_id': cloid_to_link(o.get('cloid'))
                    or (o.get('cloid') or ''),
                    'side': 'Buy' if o.get('side') == 'B' else 'Sell',
                    'price': _f(o.get('limitPx')),
                    'qty': orig,
                    'cum_exec_qty': max(orig - left, 0.0),
                    'reduce_only': bool(o.get('reduceOnly')),
                    'status': 'PartiallyFilled' if left < orig else 'New',
                    'position_idx': 0,
                    'order_type': o.get('orderType', 'Limit'),
                    'updated_time_ms': int(o.get('timestamp') or 0)})
    return out


def read_symbol_truth(client, coin):
    meta, ctxs = client.meta_and_ctxs()
    names = [e['name'] for e in meta['universe']]
    if coin not in names:
        raise VenueError(f'{coin}: not in the HL universe')
    ctx = ctxs[names.index(coin)]           # positional pairing, perps only
    book = client.l2_book(coin)
    bids, asks = book.get('levels', [[], []])
    bid = _f(bids[0]['px']) if bids else None
    ask = _f(asks[0]['px']) if asks else None
    mark = _f(ctx.get('markPx'))
    return validate_truth({
        'symbol': coin,
        'market_type': 'linear',
        'mark': mark,
        'mark_is_mark': mark is not None,
        'bid': bid,
        'ask': ask,
        'split_ref': (bid + ask) / 2.0 if bid and ask else mark,
        'funding_rate_hourly': _f(ctx.get('funding')),      # hourly at source
        'next_funding_time_ms': None,
        'orders': read_orders(client.open_orders(coin), coin),
        'positions': read_positions(client.clearinghouse_state(), coin)})


def _addr(s):
    return str(s or '').strip().lower()


def read_fills(raw, coins, address):
    """R1: the shared fill shape; tid is the execution id, the cloid decodes
    back to the link. Rows outside `coins` are not ours to ledger.

    R10: HL stamps `liquidation` on BOTH sides of a liquidation trade and
    names the liquidated user in it. It is a liquidation of US only when
    that address is ours; a counterparty's liquidation filled our resting
    order and is an ordinary fill. The 48-day run killed two healthy grids
    by reading any stamp as ours (JOURNAL 2026-09-25 post-mortem)."""
    ours = _addr(address)
    if not ours:
        raise VenueError('read_fills: no account address to judge liquidation '
                         'stamps against — refuse, never guess (R10)')
    out = []
    for f in raw:
        if f.get('coin') not in coins:
            continue
        liq = f.get('liquidation') or None
        liquidated_us = False
        if liq:
            who = _addr(liq.get('liquidatedUser')) if isinstance(liq, dict) \
                else ''
            if not who:
                raise VenueError(f"{f.get('coin')} fill {f.get('tid')}: "
                                 'liquidation stamp names no liquidatedUser '
                                 '— cannot tell whose it was (R10)')
            liquidated_us = who == ours
        out.append({'exec_id': str(f.get('tid')),
                    'time_ms': int(f.get('time') or 0),
                    'symbol': f.get('coin'),
                    'market_type': 'linear',
                    # HL's round exits are OUR resting orders (D21) and carry
                    # cloids; only a venue liquidation OF US is venue-created
                    'venue_closed': liquidated_us,
                    'venue_kind': 'liquidation' if liquidated_us else '',
                    'side': 'buy' if f.get('side') == 'B' else 'sell',
                    'price': _f(f.get('px')),
                    'qty': _f(f.get('sz'), 0.0),
                    'fee': _f(f.get('fee'), 0.0),
                    'link_id': cloid_to_link(f.get('cloid'))
                    or (f.get('cloid') or '')})
    out.sort(key=lambda f: f['time_ms'])
    return out


FUNDING_PAGES = 200        # E5 backstop: hitting it is an error, not a bound


def read_funding(client, coins, start_ms, end_ms=None):
    """D63: funding paid or received, per position side. HL's `usdc` is
    already the account's P/L (negative = paid); the side is the sign of
    the position it was charged on (`szi`). A page holds at most 500 rows
    and every coin settles at the same instant, so the next page starts AT
    the last instant seen and rows are kept once by (time, coin)."""
    out, seen, start = [], set(), int(start_ms)
    for _ in range(FUNDING_PAGES):
        raw = client.user_funding(start, end_ms) or []
        new = 0
        for r in raw:
            d = r.get('delta') or {}
            t = int(r.get('time') or 0)
            key = (t, d.get('coin'))
            if key in seen:
                continue
            seen.add(key)
            new += 1
            szi = _f(d.get('szi'), 0.0)
            if d.get('type') != 'funding' or d.get('coin') not in coins \
                    or not szi:
                continue
            out.append({'time_ms': t, 'symbol': d.get('coin'),
                        'market_type': 'linear',
                        'side': 'buy' if szi > 0 else 'sell',
                        'amount': _f(d.get('usdc'), 0.0)})
        if not new or len(raw) < 500:
            break
        start = max(int(r.get('time') or 0) for r in raw)
    else:
        raise VenueError(f'funding history beyond {FUNDING_PAGES} pages',
                         kind='partial_read')
    out.sort(key=lambda f: f['time_ms'])
    return out
