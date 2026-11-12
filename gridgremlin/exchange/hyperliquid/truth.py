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
    positions = account_positions(state)               # D162: from the same read
    upl = sum(p['upnl'] or 0.0 for p in positions)
    # U138c: the one coin HL settles in, as U138's other wallets are said —
    # the balance (the collateral less the positions' open P&L, so balance
    # plus open P&L is the collateral) and that open P&L apart; no loans here
    return {'notional': _f(summary.get('totalNtlPos'), 0.0),
            'equity': _f(summary.get('accountValue')),
            'collateral': wallet['equity'],
            'source': 'hyperliquid',
            'available': wallet.get('available'),
            'wallet': {'USDC': {'balance': wallet['equity'] - upl, 'usd': None,
                                'borrow': 0.0, 'interest': 0.0, 'upl': upl}},
            'positions': positions}


def account_positions(state):
    """D162 (R25): every perpetual position on the account, from the
    clearinghouse state already read — HL's market is the coin, its mark
    the position's value over its size."""
    out = []
    for ap in state.get('assetPositions', []):
        p = ap.get('position', {})
        szi = _f(p.get('szi'), 0.0)
        if not szi:
            continue
        value = _f(p.get('positionValue'))
        out.append({'market': 'linear', 'symbol': p.get('coin'),
                    'side': 'long' if szi > 0 else 'short', 'size': abs(szi),
                    'entry': _f(p.get('entryPx')) or None,
                    'mark': (abs(value) / abs(szi)) if value else None,
                    'upnl': _f(p.get('unrealizedPnl')),
                    'leverage': _f((p.get('leverage') or {}).get('value')) or None})
    return out


def hand_exits(orders, symbol, side):
    """D183: the exits resting on a coin that no bot and no managed trade
    placed by link — Hyperliquid's reduce-only trigger orders on the side
    that closes `side`, carrying no cloid (every bot order carries its
    link, I1) — as [{oid, kind 'tp'|'sl', trigger, qty, whole}]. `whole`
    is HL's position TP/SL: it closes whatever is held when it fires.
    From frontendOpenOrders rows already read; reads nothing."""
    close = 'A' if side == 'long' else 'B'
    out = []
    for o in orders or []:
        if (o.get('coin') != symbol or not o.get('isTrigger') or not o.get('reduceOnly')
                or o.get('side') != close or o.get('cloid')):
            continue
        kind = 'tp' if 'take profit' in str(o.get('orderType') or '').lower() else 'sl'
        out.append({'oid': str(o.get('oid')), 'kind': kind,
                    'trigger': _f(o.get('triggerPx')), 'qty': _f(o.get('sz'), 0.0),
                    'whole': bool(o.get('isPositionTpsl'))})
    return sorted(out, key=lambda x: (x['kind'], x['trigger'] or 0.0))


def attach_hand_exits(positions, orders):
    """D183: each position's hand exits (`hand_exits`), in place."""
    for p in positions or []:
        p['exits'] = hand_exits(orders, p.get('symbol'), p.get('side'))
    return positions


def _addr_eq(a, b):
    return bool(a) and bool(b) and str(a).lower() == str(b).lower()


def transfer_row(u, address):
    """D162 (R27): one entry of HL's ledger of money moved (deposits,
    withdrawals, transfers; funding is not in it) as {id, t, dir, coin,
    amount, what}; None for a move inside the account (spot to perp) or a
    kind that moves no money in or out."""
    d = u.get('delta') or {}
    kind = d.get('type')
    base = {'id': f"hl:{u.get('hash')}:{kind}", 't': int(u.get('time') or 0)}
    if kind == 'deposit':
        return dict(base, dir='in', coin='USDC', amount=_f(d.get('usdc'), 0.0), what='deposit')
    if kind == 'withdraw':
        fee = _f(d.get('fee'), 0.0)
        return dict(base, dir='out', coin='USDC', amount=_f(d.get('usdc'), 0.0),
                    what='withdrawal' + (f' (fee {fee:g})' if fee else ''))
    if kind in ('internalTransfer', 'subAccountTransfer', 'spotTransfer'):
        into = _addr_eq(d.get('destination'), address)
        if into == _addr_eq(d.get('user'), address):
            return None
        coin = d.get('token') or 'USDC'
        amount = _f(d.get('amount') if kind == 'spotTransfer' else d.get('usdc'), 0.0)
        return dict(base, dir='in' if into else 'out', coin=coin, amount=amount,
                    what=f"transfer {'from' if into else 'to'} another address")
    if kind in ('vaultDeposit', 'vaultWithdraw'):
        return dict(base, dir='out' if kind == 'vaultDeposit' else 'in', coin='USDC',
                    amount=_f(d.get('usdc') or d.get('requestedUsd'), 0.0),
                    what='into a vault' if kind == 'vaultDeposit' else 'out of a vault')
    return None


def read_transfers(client, start_ms, end_ms):
    """D162 (R27): HL's own record of money moved, `userNonFundingLedgerUpdates`
    — the address's public ledger, no key needed. Returns (rows, unread)."""
    try:
        raw = client.ledger_updates(start_ms, end_ms) or []
    except (VenueError, OSError, ValueError, KeyError, TypeError) as e:
        return [], {'the ledger of money moved': str(e)[:200]}
    rows = [r for r in (transfer_row(u, client.address) for u in raw) if r is not None]
    return sorted(rows, key=lambda r: r['t']), {}


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


def order_state(answer):
    """G23: HL's orderStatus answer as 'filled' (some of it executed),
    'cancelled' (ended with nothing executed), 'open', or None."""
    if not isinstance(answer, dict) or answer.get('status') != 'order':
        return None
    wrap = answer.get('order') or {}
    status = str(wrap.get('status') or '')
    order = wrap.get('order') or {}
    done = _f(order.get('origSz'), 0.0) - _f(order.get('sz'), 0.0) > 0
    if status == 'filled':
        return 'filled'
    if status in ('open', 'triggered'):
        return 'open'
    if status.endswith('anceled') or status.endswith('ejected'):
        return 'filled' if done else 'cancelled'
    return None


def _reduces(direction, liquidated_us):
    """G23: did the fill reduce a position — 'Close Long'/'Close Short', a
    flip ('Long > Short': its closing part), or our own liquidation. None
    where HL does not say."""
    if liquidated_us:
        return True
    if not direction:
        return None
    d = str(direction)
    return d.startswith('Close') or '>' in d


def _fill_time(raw, tid):
    """G29: a fill's time, or a refusal naming the fill — a bare int() named
    nothing, and the one bad row could not be found to deal with by hand."""
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        raise ValueError(f'fill id {tid} refused: its time {raw!r} is not '
                         'a time (G29)') from None


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
                # G29: the refused fill's id leads, so the freeze's card
                # and phone line name the one fill to deal with by hand
                raise VenueError(f"fill id {f.get('tid')} ({f.get('coin')}) "
                                 'refused: its liquidation stamp names no '
                                 'liquidatedUser — cannot tell whose it was '
                                 '(R10)')
            liquidated_us = who == ours
        out.append({'exec_id': str(f.get('tid')),
                    'time_ms': _fill_time(f.get('time'), f.get('tid')),
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
                    or (f.get('cloid') or ''),
                    'reduces': _reduces(f.get('dir'), liquidated_us)})
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
