# One bot's fills, each with what it realised (D96, U78). The panel's
# right half lists them when a bot is picked. Read-only: the kept ledger
# (R18) as the readout counts it — the same attribution (R7, R16), the same
# start (the anchor, or the earliest flat the venue's holding allows), the
# same walk (R2, R13) — so the list's total is the card's kept history.
from .report import EPS, bot_fills, counted_fills, first_flat_ms, fleet_maps, ledger
from .config import market_rows
from .kept_fills import anchor_of, since_cut


def fill_list(kept, fleet, botid, held=None):
    """{'whole': bool, 'rows': [...], 'realized', 'fees'} for `botid`, rows
    oldest first: {time_ms, side, entry (bool), price, qty, fee, realized
    (this fill's), net (realised less fees, running), kind (the venue's
    label for a fill it made itself: 'liquidation', a stop's name)}. An
    opening balance (a fresh anchor) is the first row, kind 'opening'.
    Without a whole start (no anchor, no flat the holding allows) the rows
    are the bot's own fills, realized None — said, never guessed.
    U113: a grid's rows also carry the trip each exit closed (R12): `own`
    (the entry price it is judged against, R15/R15b), `trip` (the gain
    against it after both legs' fees, R21: the entry fill's own fee per
    unit when seen, the exit's otherwise) and `trip_net` (those, running);
    an exit no entry is linked to has own and trip None. The answer adds
    `per_trip` (True for a grid), `trip_total`, `trip_gross`, `trips`
    (orders, R12b) and `unmatched` (exits with no entry). Other kinds —
    a martingale, whose exit closes the round's average — keep `realized`."""
    key_of, entry_sides, closers, _ = fleet_maps(fleet)
    entry = entry_sides.get(botid)
    if entry is None:
        return None
    inverse = {botid} if key_of[botid][0] == 'inverse' else set()
    cfg = next((c for c in market_rows(fleet) if (c['market_type'], c['symbol']) == key_of[botid]
                and entry_sides[botid] == ('buy' if c['side'] == 'long' else 'sell')), {})
    grids = {botid: cfg} if cfg.get('lower') and cfg.get('upper') else {}
    rounders = {botid} if cfg.get('strategy') == 'martingale' else set()
    own = since_cut(kept, botid, bot_fills(kept.get('fills') or [], botid, closers, entry_sides))
    got = counted_fills(botid, own, entry, anchor_of(kept, botid),
                        first_flat_ms(own, entry, held))
    if got is None:
        return {'whole': False, 'realized': None, 'fees': sum(f['fee'] for f in own),
                'rows': [_row(f, entry, None, None) for f in own]}
    counted, _ = got
    series, trips = {}, {}
    book = ledger(counted, [botid], inverse, entry_sides, closers, grids,
                  rounders=rounders, series=series, trips=trips).get(botid)
    rows, before, fees = [], 0.0, 0.0
    tsum = tgross = 0.0
    links, unmatched = set(), 0
    for f, (_, net), (own, own_fee) in zip(counted, series.get(botid, []), trips.get(botid, [])):
        fees += f['fee']
        realized = net + fees - before                  # the series is net after fees, cumulative
        before += realized
        row = _row(f, entry, realized if abs(realized) > EPS else 0.0, net)
        if grids and not row['entry']:
            if own is None:
                unmatched += 1
                row['own'] = row['trip'] = None
            else:                                       # R12's own sum, this fill's share
                sign = 1.0 if entry == 'buy' else -1.0
                gross = (f['qty'] * (1.0 / own - 1.0 / f['price']) if inverse
                         else (f['price'] - own) * f['qty']) * sign
                rate = own_fee if own_fee is not None else (f['fee'] / f['qty'] if f['qty'] else 0.0)
                row['own'], row['trip'] = own, gross - f['fee'] - rate * f['qty']
                tgross += gross
                tsum += row['trip']
                link = f.get('link_id') or f['exec_id']
                links.add(link)
        row['trip_net'] = tsum if grids else None
        rows.append(row)
    return {'whole': True, 'rows': rows, 'realized': book['realized'] if book else 0.0,
            'fees': book['fees'] if book else 0.0, 'per_trip': bool(grids),
            'trip_total': tsum, 'trip_gross': tgross, 'trips': len(links), 'unmatched': unmatched}


def _row(f, entry, realized, net):
    opening = str(f.get('exec_id', '')).startswith('open:')
    return {'time_ms': f['time_ms'], 'side': f['side'], 'entry': f['side'] == entry,
            'price': f['price'], 'qty': f['qty'], 'fee': f['fee'], 'realized': realized, 'net': net,
            'kind': 'opening' if opening else (f.get('venue_kind') if f.get('venue_closed') else '')}
