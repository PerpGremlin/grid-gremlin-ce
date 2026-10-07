# Specs for SPEC R1-R5 — the readout: venue fills -> grid profit vs total P&L.

import inspect

from gridgremlin.report import (apply_fill, ledger, new_book, owner_of,
                                total_pnl)
from gridgremlin.exchange.errors import VenueError


def _fill(t, side, price, qty, fee=0.0, link='', symbol='BTCUSDT'):
    return {'time_ms': t, 'side': side, 'price': price, 'qty': qty,
            'fee': fee, 'link_id': link, 'symbol': symbol,
            'exec_id': f'e{t}'}


# --- R1: ownership is the link prefix, exactly I1's rule ---------------------

def spec_R1_a_fill_is_ours_iff_the_link_parses():
    bots = ['linBTCUSDTl', 'linETHUSDTs']
    assert owner_of('linBTCUSDTl-3-ab12', bots) == 'linBTCUSDTl'
    assert owner_of('linBTCUSDTlx-3-a', bots) is None      # not our prefix
    assert owner_of('linBTCUSDTl-x-a', bots) is None       # rung must parse
    assert owner_of('', bots) is None


# --- R2: average-cost arithmetic ---------------------------------------------

def spec_R2_long_build_then_partial_exit():
    b = new_book()
    apply_fill(b, 'buy', 100.0, 1.0, 0.1)
    apply_fill(b, 'buy', 110.0, 1.0, 0.1)
    assert abs(b['avg_cost'] - 105.0) < 1e-9
    apply_fill(b, 'sell', 120.0, 1.5, 0.2)
    assert abs(b['realized'] - 22.5) < 1e-9
    assert abs(b['position'] - 0.5) < 1e-9
    assert abs(b['avg_cost'] - 105.0) < 1e-9               # reduce keeps basis
    assert abs(b['fees'] - 0.4) < 1e-9


def spec_R2_short_side_realises_on_the_buy():
    b = new_book()
    apply_fill(b, 'sell', 100.0, 2.0, 0.0)
    apply_fill(b, 'buy', 90.0, 1.0, 0.0)
    assert abs(b['realized'] - 10.0) < 1e-9
    assert abs(b['position'] - -1.0) < 1e-9


def spec_R2_flip_through_zero_reanchors():
    b = new_book()
    apply_fill(b, 'buy', 100.0, 1.0, 0.0)
    apply_fill(b, 'sell', 90.0, 2.0, 0.0)
    assert abs(b['realized'] - -10.0) < 1e-9
    assert abs(b['position'] - -1.0) < 1e-9
    assert abs(b['avg_cost'] - 90.0) < 1e-9                # remainder opens here


def spec_R2_full_close_zeroes_the_book():
    b = new_book()
    apply_fill(b, 'buy', 100.0, 1.0, 0.0)
    apply_fill(b, 'sell', 105.0, 1.0, 0.0)
    assert b['position'] == 0.0 and b['avg_cost'] == 0.0
    assert abs(b['realized'] - 5.0) < 1e-9


# --- R3: unowned fills are reported, never dropped ---------------------------

def spec_R3_external_activity_gets_its_own_bucket():
    fills = [_fill(1, 'buy', 100.0, 1.0, link='linBTCUSDTl-0-ab'),
             _fill(2, 'sell', 101.0, 0.5, link='')]
    books = ledger(fills, ['linBTCUSDTl'])
    assert 'linBTCUSDTl' in books
    assert ('unowned', 'BTCUSDT') in books
    assert books[('unowned', 'BTCUSDT')]['fills'] == 1


def spec_R3_ledger_orders_by_time_not_arrival():
    fills = [_fill(2, 'sell', 120.0, 1.0, link='linBTCUSDTl-1-ab'),
             _fill(1, 'buy', 100.0, 1.0, link='linBTCUSDTl-0-ab')]
    b = ledger(fills, ['linBTCUSDTl'])['linBTCUSDTl']
    assert abs(b['realized'] - 20.0) < 1e-9                # buy first, then sell


# --- R4: read-only by construction -------------------------------------------

def spec_R4_no_write_client_in_the_readout():
    import gridgremlin.report as report
    src = inspect.getsource(report)
    for forbidden in ('WriteClient', 'place_order', 'place_market',
                      'exchange_action', 'cancel_order'):
        assert forbidden not in src, f'readout touches {forbidden}'


# --- R5: total P&L ------------------------------------------------------------

def spec_R5_total_adds_mark_to_average_on_the_open_remainder():
    b = new_book()
    apply_fill(b, 'buy', 100.0, 1.0, 1.0)
    apply_fill(b, 'buy', 110.0, 1.0, 1.0)
    apply_fill(b, 'sell', 120.0, 1.5, 1.0)
    assert abs(total_pnl(b, 120.0) - (22.5 - 3.0 + 7.5)) < 1e-9
    assert total_pnl(b, None) is None                      # open + no mark
    flat = new_book()
    apply_fill(flat, 'buy', 100.0, 1.0, 0.5)
    apply_fill(flat, 'sell', 105.0, 1.0, 0.5)
    assert abs(total_pnl(flat, None) - 4.0) < 1e-9         # flat needs no mark


# --- R1 at the Bybit seam: windows, cursors, Trade-only, dedup ---------------

class FakeExec:
    def __init__(self):
        self.calls = []
        self.rows = [
            {'execId': 'a', 'execType': 'Trade', 'execTime': '2',
             'symbol': 'BTCUSDT', 'side': 'Buy', 'execPrice': '100',
             'execQty': '1', 'execFee': '0.1', 'orderLinkId': 'x-0-a'},
            {'execId': 'f', 'execType': 'Funding', 'execTime': '3',
             'symbol': 'BTCUSDT', 'side': 'Buy', 'execPrice': '0',
             'execQty': '0', 'execFee': '0.5', 'orderLinkId': ''},
            {'execId': 'a', 'execType': 'Trade', 'execTime': '2',
             'symbol': 'BTCUSDT', 'side': 'Buy', 'execPrice': '100',
             'execQty': '1', 'execFee': '0.1', 'orderLinkId': 'x-0-a'}]

    def executions_page(self, category, symbol, start_ms, end_ms, cursor=None):
        self.calls.append((start_ms, end_ms, cursor))
        return {'list': self.rows, 'nextPageCursor': None}


def spec_R1_bybit_fills_window_filter_and_dedup():
    from gridgremlin.exchange.bybit.truth import SEVEN_DAYS_MS, read_fills
    fake = FakeExec()
    fills = read_fills(fake, 'linear', 'BTCUSDT', 0, SEVEN_DAYS_MS + 10)
    assert len(fake.calls) == 2                            # 8 days -> 2 windows
    assert [f['exec_id'] for f in fills] == ['a']          # Trade-only, deduped
    assert fills[0]['side'] == 'buy' and fills[0]['fee'] == 0.1


def spec_R1_bybit_runaway_history_raises_partial_read():
    from gridgremlin.exchange.bybit.truth import read_fills

    class Endless(FakeExec):
        def executions_page(self, *a, cursor=None):
            return {'list': [], 'nextPageCursor': 'again'}
    try:
        read_fills(Endless(), 'linear', 'BTCUSDT', 0, 1000)
    except VenueError as e:
        assert e.kind == 'partial_read'
    else:
        raise AssertionError('runaway pagination did not raise')


# --- R1 at the HL seam: cloid decodes back to the link -----------------------

def spec_R1_hl_fills_decode_the_cloid():
    from gridgremlin.exchange.hyperliquid.signing import link_to_cloid
    from gridgremlin.exchange.hyperliquid.truth import read_fills
    raw = [{'coin': 'XRP', 'px': '3.0', 'sz': '10', 'side': 'B',
            'time': 2, 'tid': 42, 'fee': '0.01',
            'cloid': link_to_cloid('linXRPl-0-ab')},
           {'coin': 'ETH', 'px': '2500', 'sz': '1', 'side': 'A',
            'time': 1, 'tid': 41, 'fee': '0.5', 'cloid': None},
           {'coin': 'BTC', 'px': '60000', 'sz': '1', 'side': 'B',
            'time': 3, 'tid': 40, 'fee': '1'}]
    fills = read_fills(raw, {'XRP', 'ETH'}, '0xabc')
    assert [f['symbol'] for f in fills] == ['ETH', 'XRP']  # time-ordered, filtered
    xrp = fills[1]
    assert xrp['link_id'] == 'linXRPl-0-ab' and xrp['side'] == 'buy'
    assert xrp['exec_id'] == '42'
    assert fills[0]['side'] == 'sell' and fills[0]['link_id'] == ''


# --- A4 reaches the readout: inverse books realise in the BASE coin ----------

def spec_R2_an_inverse_book_realises_in_base_coin():
    b = new_book()
    apply_fill(b, 'buy', 50000.0, 1000, 0.0, inverse=True)   # $1000 contracts
    apply_fill(b, 'sell', 62500.0, 1000, 0.0, inverse=True)
    assert abs(b['realized'] - 1000 * (1 / 50000 - 1 / 62500)) < 1e-12   # BTC
    assert abs(b['realized'] - 0.004) < 1e-9


def spec_R5_inverse_total_converts_to_quote_at_mark():
    b = new_book()
    apply_fill(b, 'buy', 50000.0, 1000, 0.0, inverse=True)
    from gridgremlin.report import unreal_pnl
    u = unreal_pnl(b, 62500.0)
    assert abs(u - 0.004) < 1e-9                       # base coin
    assert abs(total_pnl(b, 62500.0) - 250.0) < 1e-6   # $ at mark
    assert total_pnl(b, None) is None                  # open + no mark


# --- audit M2: spot fees settle in the base coin -----------------------------

def spec_R2_spot_base_coin_fees_are_quote_normalised():
    from gridgremlin.exchange.bybit.truth import read_fills

    class SpotExec:
        def executions_page(self, category, symbol, s, e, cursor=None):
            return {'list': [
                {'execId': 'b', 'execType': 'Trade', 'execTime': '2',
                 'symbol': 'LTCUSDT', 'side': 'Buy', 'execPrice': '50',
                 'execQty': '1', 'execFee': '0.001', 'feeCurrency': 'LTC',
                 'orderLinkId': 'x-1-a'},
                {'execId': 's', 'execType': 'Trade', 'execTime': '3',
                 'symbol': 'LTCUSDT', 'side': 'Sell', 'execPrice': '52',
                 'execQty': '1', 'execFee': '0.052', 'feeCurrency': 'USDT',
                 'orderLinkId': 'x-2-a'}], 'nextPageCursor': None}
    fills = read_fills(SpotExec(), 'spot', 'LTCUSDT', 0, 1000)
    assert abs(fills[0]['fee'] - 0.05) < 1e-12      # 0.001 LTC @ 50 -> quote
    assert abs(fills[1]['fee'] - 0.052) < 1e-12     # already quote: untouched


# --- R6: the activity layer — same fills, no new state -----------------------

def spec_R6_every_realisation_is_a_trip():
    b = new_book()
    apply_fill(b, 'buy', 100.0, 1.0, 0.0)
    apply_fill(b, 'sell', 102.0, 1.0, 0.0)       # trip 1 (+2, flat)
    apply_fill(b, 'buy', 101.0, 1.0, 0.0)
    apply_fill(b, 'sell', 100.0, 0.5, 0.0)       # trip 2 — underwater churn
    assert b['trips'] == 2                       # counted even at a loss
    assert abs(b['realized'] - (2.0 - 0.5)) < 1e-9


def spec_R6_rounds_close_on_flat_and_carry_their_pnl():
    b = new_book()
    link = 'x'
    apply_fill(b, 'buy', 100.0, 1.0, 0.0, entry_side='buy', rung=0)
    apply_fill(b, 'buy', 99.0, 1.0, 0.0, entry_side='buy', rung=1)   # SO 1
    apply_fill(b, 'buy', 98.0, 2.0, 0.0, entry_side='buy', rung=2)   # SO 2
    apply_fill(b, 'sell', 100.0, 4.0, 0.0, entry_side='buy')         # TP: flat
    apply_fill(b, 'buy', 100.0, 1.0, 0.0, entry_side='buy', rung=0)
    apply_fill(b, 'sell', 101.0, 1.0, 0.0, entry_side='buy')         # round 2
    assert b['rounds'] == 2
    assert b['so_fills'] == 2 and b['max_depth'] == 2
    # round 1: avg (100+99+196)/4 = 98.75 -> +5; round 2: +1
    assert abs(b['round_pnl_sum'] - 6.0) < 1e-9


def spec_R6_depth_resets_between_rounds():
    b = new_book()
    apply_fill(b, 'buy', 100.0, 1.0, 0.0, entry_side='buy', rung=0)
    apply_fill(b, 'buy', 99.0, 1.0, 0.0, entry_side='buy', rung=3)
    apply_fill(b, 'sell', 101.0, 2.0, 0.0, entry_side='buy')
    apply_fill(b, 'buy', 100.0, 1.0, 0.0, entry_side='buy', rung=0)
    apply_fill(b, 'buy', 99.5, 1.0, 0.0, entry_side='buy', rung=1)
    apply_fill(b, 'sell', 101.0, 2.0, 0.0, entry_side='buy')
    assert b['max_depth'] == 3                   # the high-water survives
    assert b['_round_depth'] == 0                # but the round gauge reset


def spec_R6_the_ledger_threads_rungs_from_links():
    fills = [_fill(1, 'buy', 100.0, 1.0, link='linBTCUSDTl-0-aa'),
             _fill(2, 'buy', 99.0, 1.0, link='linBTCUSDTl-2-ab'),
             _fill(3, 'sell', 101.0, 2.0, link='linBTCUSDTl-0-ac')]
    b = ledger(fills, ['linBTCUSDTl'],
               entry_sides={'linBTCUSDTl': 'buy'})['linBTCUSDTl']
    assert b['so_fills'] == 1 and b['max_depth'] == 2 and b['rounds'] == 1


# --- R7: venue-created closes, and honest windows ---------------------------

def spec_R7_a_hosted_TP_fill_belongs_to_the_bot_it_closed():
    """Bybit's position-TP fills carry NO link (found live 2026-08-06: a
    completed martingale round showed realized 0.00 and a phantom short)."""
    from gridgremlin.report import closer_of
    closers = {('linear', 'DOGEUSDT', 'sell'): 'linDOGEUSDTl'}
    tp = dict(_fill(9, 'sell', 0.07049, 14330, 0.55, link='',
                    symbol='DOGEUSDT'),
              market_type='linear', venue_closed=True,
              venue_kind='TakeProfit')
    assert closer_of(tp, closers) == 'linDOGEUSDTl'
    manual = dict(tp, venue_closed=False)          # an operator's own sell
    assert closer_of(manual, closers) is None      # stays unowned (R3)
    wrong_side = dict(tp, side='buy')
    assert closer_of(wrong_side, closers) is None  # never guesses a side


def spec_R16_an_unlinked_fill_on_a_bots_exit_side_is_booked_to_it():
    """HL SOL 2026-10-04 12:28: the venue rebuilt an amended exit without
    its link; 0.19 sold unlinked, and the readout's book held 0.19 more
    than the exchange for a month. The owner (2026-10-05): the readout
    books the money where it went; the engine's outside-hand law stands."""
    from gridgremlin.report import exit_side_owner
    closers = {('linear', 'SOL', 'sell'): 'linSOLl',
               ('linear', 'BTCUSDT', 'sell'): 'linBTCUSDTl',
               ('linear', 'BTCUSDT', 'buy'): 'linBTCUSDTs'}
    stray = dict(_fill(5, 'sell', 127.2, 0.19, 0.01, link='', symbol='SOL'),
                 market_type='linear', venue_closed=False)
    assert exit_side_owner(stray, closers) == 'linSOLl'
    entry = dict(stray, side='buy')                   # a hand BUY on SOL:
    assert exit_side_owner(entry, closers) is None    # nobody's exit (R3)
    linked = dict(stray, link_id='linSOLl-0-x')
    assert exit_side_owner(linked, closers) is None   # a link is R1's
    hedge_sell = dict(stray, symbol='BTCUSDT')        # hedge pair: by side
    assert exit_side_owner(hedge_sell, closers) == 'linBTCUSDTl'
    assert exit_side_owner(dict(hedge_sell, side='buy'), closers) == 'linBTCUSDTs'
    L = 'linSOLl'
    fills = [_fill(1, 'buy', 125.0, 0.39, 0.0, link=f'{L}-3-a', symbol='SOL'),
             _fill(2, 'sell', 127.2, 0.2, 0.0, link=f'{L}-0-b', symbol='SOL'),
             stray]
    for f in fills:
        f.setdefault('market_type', 'linear')
        f.setdefault('venue_closed', False)
    books = ledger(fills, [L], entry_sides={L: 'buy'}, closers=closers)
    assert abs(books[L]['position']) < 1e-12           # flat, as the venue
    assert ('unowned', 'SOL') not in books
    assert abs(books[L]['realized'] - (2.2 * 0.39)) < 1e-9
    # the guard: a hand sale while the bot is FLAT is nobody's exit, and
    # one beyond its holding is its exit only up to the holding — the demo
    # SOL long read 8.2 short of the exchange when the owner's September
    # hand-flattening sat inside the month
    flat_then_hand = [dict(_fill(1, 'sell', 120.0, 5.0, 0.5, link='',
                                 symbol='SOL'), market_type='linear',
                           venue_closed=False)]
    books = ledger(flat_then_hand, [L], entry_sides={L: 'buy'},
                   closers=closers)
    assert L not in books and ('unowned', 'SOL') in books
    over = [_fill(1, 'buy', 120.0, 1.0, 0.0, link=f'{L}-2-q', symbol='SOL'),
            dict(_fill(2, 'sell', 121.0, 3.0, 0.3, link='', symbol='SOL'),
                 market_type='linear', venue_closed=False)]
    for f in over:
        f.setdefault('market_type', 'linear')
    books = ledger(over, [L], entry_sides={L: 'buy'}, closers=closers)
    assert abs(books[L]['position']) < 1e-12 and books[L]['fills'] == 2
    assert abs(books[L]['fees'] - 0.1) < 1e-9             # a third of 0.3
    rest = books[('unowned', 'SOL')]
    assert abs(rest['sold'] - 2.0) < 1e-9 and abs(rest['fees'] - 0.2) < 1e-9


def spec_R7_the_ledger_credits_the_round_to_the_bot():
    fills = [_fill(1, 'buy', 0.07, 7000, 0.1, link='linDOGEUSDTl-0-a',
                   symbol='DOGEUSDT'),
             dict(_fill(2, 'sell', 0.0705, 7000, 0.1, link='',
                        symbol='DOGEUSDT'),
                  market_type='linear', venue_closed=True)]
    for f in fills:
        f.setdefault('market_type', 'linear')
        f.setdefault('venue_closed', False)
    books = ledger(fills, ['linDOGEUSDTl'],
                   entry_sides={'linDOGEUSDTl': 'buy'},
                   closers={('linear', 'DOGEUSDT', 'sell'): 'linDOGEUSDTl'})
    b = books['linDOGEUSDTl']
    assert b['rounds'] == 1 and abs(b['realized'] - 3.5) < 1e-9
    assert ('unowned', 'DOGEUSDT') not in books


def spec_R7_a_mid_round_window_declares_itself():
    from gridgremlin.report import window_truncated
    b = new_book()
    apply_fill(b, 'sell', 0.0705, 14330, 0.0)      # close seen, open missed
    assert window_truncated(b, 'long') is True     # a long cannot be short
    assert window_truncated(b, 'short') is False   # a short legitimately is
    flat = new_book()
    assert window_truncated(flat, 'long') is False


# --- R14: money is counted from the last flat ---------------------------------

def spec_R14_the_last_flat_is_where_the_open_round_began():
    from gridgremlin.report import last_flat_ms, bot_fills
    L = 'linBTCUSDTl'
    fills = [_fill(1, 'buy', 100, 1, link=f'{L}-1-a'),
             _fill(2, 'buy', 99, 1, link=f'{L}-2-b'),
             _fill(3, 'sell', 101, 2, link=f'{L}-0-c'),      # flat here
             _fill(4, 'buy', 98, 1, link=f'{L}-3-d'),        # the open round
             _fill(5, 'buy', 97, 1, link=f'{L}-4-e'),
             _fill(6, 'sell', 99, 1, link=f'{L}-0-f'),
             _fill(7, 'buy', 96, 2, link='linBTCUSDTs-0-x')]  # the other leg
    own = bot_fills(fills, L)
    assert [f['time_ms'] for f in own] == [1, 2, 3, 4, 5, 6]
    stray = dict(_fill(8, 'sell', 100, 1, link=''), market_type='linear')
    closers = {('linear', 'BTCUSDT', 'sell'): L}
    es = {L: 'buy'}
    assert [f['time_ms'] for f in bot_fills(fills + [stray], L, closers, es)] \
        == [1, 2, 3, 4, 5, 6, 8]                        # R16 in the walk too
    assert last_flat_ms(bot_fills(fills + [stray], L, closers, es), 'buy') == 9
    early = dict(stray, time_ms=0)                      # before it held any
    assert [f['time_ms'] for f in bot_fills(fills + [early], L, closers, es)] \
        == [1, 2, 3, 4, 5, 6]                           # nobody's exit
    assert last_flat_ms(own, 'buy') == 4
    assert last_flat_ms(own[3:], 'buy') is None   # a slice's own first fill
    assert last_flat_ms(own[:3], 'buy') == 4      # is never the tell (R7);
    assert last_flat_ms([], 'buy') is None        # flat now: after the close
    # a slice that opens mid-round CAN show a phantom return to flat (fills
    # 5-6 alone: +1, -1) — the exchange's holding is the proof, below
    assert last_flat_ms(own[4:], 'buy') == 7


def spec_R14_a_truncated_window_widens_to_the_last_flat_or_the_cap():
    """The BTC long 2026-10-05: 24 h showed -14,090 — sells of lots bought
    before the window, a remainder priced from nothing; 96 h showed +9,559
    and the exchange's own average. The card counts from the last flat."""
    from gridgremlin.report import count_from_flat, ledger
    L = 'linBTCUSDTl'
    now = 100 * 3_600_000
    h = 3_600_000
    history = [_fill(now - 90 * h, 'buy', 100, 2, link=f'{L}-1-a'),
               _fill(now - 80 * h, 'sell', 110, 2, link=f'{L}-0-b'),   # flat
               _fill(now - 70 * h, 'buy', 105, 3, link=f'{L}-2-c'),    # round
               _fill(now - 30 * h, 'buy', 95, 1, link=f'{L}-3-d'),
               _fill(now - 10 * h, 'sell', 100, 2, link=f'{L}-0-e')]
    pulls = []

    def pull(since):
        pulls.append(since)
        return [f for f in history if f['time_ms'] >= since]
    own, how, start = count_from_flat(L, 24.0, now, pull,
                                      'buy', venue_size=2.0)
    assert how == 'flat' and start == now - 70 * h
    assert [f['time_ms'] for f in own] == [now - 70 * h, now - 30 * h,
                                           now - 10 * h]
    assert pulls == [now - 48 * h, now - 96 * h]          # doubled until flat
    book = ledger(own, [L], entry_sides={L: 'buy'})[L]
    assert abs(book['position'] - 2.0) < 1e-9             # 3 + 1 - 2
    assert abs(book['avg_cost'] - 102.5) < 1e-9           # the round's own
    # never flat in a month: the cap, and the truncation stands
    deep = [_fill(now - 900 * h, 'buy', 100, 5, link=f'{L}-1-z'),
            _fill(now - 10 * h, 'sell', 100, 2, link=f'{L}-0-y')]
    own2, how2, start2 = count_from_flat(
        L, 24.0, now, lambda s: [f for f in deep
                                              if f['time_ms'] >= s], 'buy',
        venue_size=3.0)
    assert how2 == 'cap' and start2 == now - 720 * h
    assert [f['time_ms'] for f in own2] == [now - 10 * h]
    # a phantom flat inside a slice is refused by the exchange's holding:
    # the slice +1/-1 "returns to flat" while the venue holds 3 more
    ghost = [_fill(now - 400 * h, 'buy', 100, 3, link=f'{L}-1-g'),
             _fill(now - 30 * h, 'buy', 95, 1, link=f'{L}-2-i'),
             _fill(now - 10 * h, 'sell', 100, 1, link=f'{L}-0-j')]
    own3, how3, start3 = count_from_flat(
        L, 24.0, now, lambda s: [f for f in ghost
                                              if f['time_ms'] >= s], 'buy',
        venue_size=3.0)
    assert how3 == 'cap'                                # never truly flat
    assert len(own3) == 3


def spec_R9_zero_spread_is_margin_against_the_cost_it_closes():
    """An exit inside the fee of its own book's average is churn; an exit
    that earned the gap is not — even at a price an EARLIER round entered
    at. The first cut kept a lifetime entry-price set, and since grids
    reuse a fixed lattice it flagged profitable full-gap trips on two live
    bots (audit 2026-08-07 H1: the counter's own name was believed)."""
    from gridgremlin.report import apply_fill, new_book
    # true zero-spread churn: buy and sell at one price -> flagged
    churn = new_book()
    apply_fill(churn, 'buy', 0.1913, 980.0, 0.19)
    apply_fill(churn, 'sell', 0.1913, 979.0, 0.19)
    assert churn['same_rung'] == 1
    # a full-gap SHORT round exiting at a price the PREVIOUS round entered
    # at: profitable, and never flagged
    short = new_book()
    apply_fill(short, 'sell', 1.100, 9.0, 0.01)     # round 1 entry
    apply_fill(short, 'buy', 1.093, 9.0, 0.01)      # +gap, flat
    apply_fill(short, 'sell', 1.107, 9.0, 0.01)     # round 2 entry
    apply_fill(short, 'buy', 1.100, 9.0, 0.01)      # +gap, at R1's entry px
    assert short['same_rung'] == 0, 'lattice reuse is not churn'
    # multi-lot averaging: nearest-first exit clearing the fee -> clean
    avg = new_book()
    apply_fill(avg, 'sell', 1.100, 9.0, 0.01)
    apply_fill(avg, 'sell', 1.107, 9.0, 0.01)       # avg 1.1035
    apply_fill(avg, 'buy', 1.100, 9.0, 0.01)        # +0.32% margin
    assert avg['same_rung'] == 0
    # but an exit scraping its own average IS flagged, long or short
    scrape = new_book()
    apply_fill(scrape, 'sell', 1.100, 9.0, 0.01)
    apply_fill(scrape, 'buy', 1.1002, 9.0, 0.01)    # 0.018% — inside fee
    assert scrape['same_rung'] == 1

def spec_D8_the_contract_serialises_every_public_field_and_no_working_state():
    """One data contract feeds the terminal table, the JSON emitter, and
    (next) the panel — so they can never disagree. Private working state
    (underscore keys, sets) must never leak; a truncated window must void
    the R9 verdict, not report one (R9 honours R7)."""
    import json as _json
    from gridgremlin.report import apply_fill, new_book, public_book
    b = new_book()
    apply_fill(b, 'buy', 100.0, 2.0, 0.1)
    apply_fill(b, 'sell', 101.0, 1.0, 0.1)
    out = public_book(b, mark=102.0, side='long', strategy='grid')
    _json.dumps(out)                       # serialisable, whole
    assert not any(k.startswith('_') for k in out)
    assert out['bought'] == 2.0 and out['sold'] == 1.0
    assert abs(out['unreal_at_mark'] - 2.0) < 1e-9    # 1 @ basis 100, mark 102
    assert out['truncated'] is False
    # a window opening mid-round voids the churn verdict
    t = new_book()
    apply_fill(t, 'sell', 110.0, 1.0, 0.1)   # long book opening with a sell
    tout = public_book(t, side='long')
    assert tout['truncated'] is True and tout['same_rung'] is None


def spec_R7_a_balanced_slice_still_declares_its_truncation():
    """The sign test alone passed a window that opened mid-round but
    netted flat (audit 2026-08-07 MED: reinvest scaled on the corrupt
    net). The window's FIRST fill is the other tell: a one-sided book
    cannot legitimately open with its exit side."""
    from gridgremlin.report import apply_fill, new_book, window_truncated
    b = new_book()
    apply_fill(b, 'sell', 110.0, 1.0, 0.1)     # pre-window buy invisible
    apply_fill(b, 'buy', 105.0, 1.0, 0.1)      # re-entry: nets to +1
    assert window_truncated(b, 'long') is True
    clean = new_book()
    apply_fill(clean, 'buy', 100.0, 1.0, 0.1)
    apply_fill(clean, 'sell', 110.0, 1.0, 0.1)
    assert window_truncated(clean, 'long') is False


def spec_A4_totals_never_mix_quote_currencies():
    """'TOTAL (quote)' summed USDT and USDC books as one number — A4 in
    miniature. One row per actual quote coin."""
    import io
    import sys as _s
    from gridgremlin.report import apply_fill, new_book
    # exercised through the printing path is heavy; the grouping rule is
    # the invariant: suffix -> bucket
    sym_quotes = {'BTCUSDT': 'USDT', 'SOLUSDC': 'USDC', 'ADAEUR': 'EUR'}
    for sym, want in sym_quotes.items():
        got = next((c for c in ('USDT', 'USDC', 'USD', 'EUR', 'BTC')
                    if sym.endswith(c)), 'quote')
        assert got == want, (sym, got)


def spec_T3_the_backtest_spread_drops_near_quote_rungs():
    """Without bid/ask the replay filled rungs live would guard-drop —
    optimistic by construction. A wide synthetic spread must fill LESS
    than a zero spread on the same bars."""
    from gridgremlin.adapters import LinearAdapter
    from gridgremlin.backtest import backtest
    from gridgremlin.config import validate_grid
    cfg = validate_grid({'market_type': 'linear', 'symbol': 'XUSDT',
                         'side': 'long', 'capital': 1000, 'lower': 90,
                         'upper': 110, 'rungs': 21,
                         'stop': {'watch': 'mark_price', 'level': 80}})
    a = LinearAdapter({'symbol': 'XUSDT', 'qty_step': 0.01, 'min_qty': 0.01,
                       'price_tick': 0.01, 'min_notional': 1.0})
    bars = [{'o': 100.0, 'h': 101.0, 'l': 99.0, 'c': 100.0}] * 30
    tight = backtest(cfg, a, bars, spread_bps=0.0)
    wide = backtest(cfg, a, bars, spread_bps=500.0)   # 2.5% half-spread
    assert wide['entry_fills'] < tight['entry_fills'], (
        wide['entry_fills'], tight['entry_fills'])


def spec_R11_a_grid_exit_is_judged_against_its_own_rung_not_the_average():
    """Live 2026-10-03: a long grid sliding down bought cheaper lots all
    day; each lot's exit sat one rung above ITS entry (a full gap) but
    below the book's falling average, and R9 flagged 6 of 80 as churn.
    With the lattice known, an exit is measured against the rung it
    closes; a true same-rung exit is still flagged."""
    from gridgremlin.config import validate_config
    from gridgremlin.report import ledger
    cfg = validate_config({'market_type': 'linear', 'symbol': 'BTCUSDT',
                           'side': 'long', 'capital': 1000, 'leverage': 10,
                           'lower': 80000, 'upper': 90000, 'rungs': 11,
                           'spacing_type': 'fixed'})
    b = 'linBTCUSDTl'

    def f(t, side, price, qty, rung):
        return {'time_ms': t, 'side': side, 'price': price, 'qty': qty,
                'fee': 0.0, 'link_id': f'{b}-{rung}-x', 'symbol': 'BTCUSDT',
                'exec_id': f'e{t}'}
    fills = [f(1, 'buy', 85000.0, 1.0, 5),       # the average starts high
             f(2, 'buy', 83000.0, 1.0, 3),       # slid down: avg 84,000
             f(3, 'sell', 84000.0, 1.0, 4)]      # lot 3 exits at rung 4:
    kw = dict(entry_sides={b: 'buy'}, grids={b: cfg})     # +1,000, a gap
    assert ledger(fills, [b], **kw)[b]['same_rung'] == 0
    assert ledger(fills, [b])[b]['same_rung'] == 1       # R9 alone: "churn"
    churn = fills[:2] + [f(3, 'sell', 83010.0, 1.0, 4)]   # 0.01% over its own
    assert ledger(churn, [b], **kw)[b]['same_rung'] == 1  # entry: flagged


def spec_R15_an_exit_is_judged_against_the_price_its_lot_was_bought_at():
    """Live 2026-10-05: the SOL long's lattice went 31 -> 19 at a restart;
    the window held fills from both, and R12 judged the older exits
    against a lattice they were never on — 60 of 61 trips 'zero-spread',
    -41 per trip, on a day the book realised +251. The venue's own fill
    says what the lot cost: when the entry fill is in the window, THAT is
    the level; the config's lattice is the fallback for an entry not seen."""
    from gridgremlin.config import validate_config
    from gridgremlin.report import ledger
    cfg = validate_config({'market_type': 'linear', 'symbol': 'BTCUSDT',
                           'side': 'long', 'capital': 1000, 'leverage': 10,
                           'lower': 80000, 'upper': 90000, 'rungs': 11,
                           'spacing_type': 'fixed'})
    b = 'linBTCUSDTl'

    def f(t, side, price, qty, rung):
        return {'time_ms': t, 'side': side, 'price': price, 'qty': qty,
                'fee': 0.0, 'link_id': f'{b}-{rung}-x', 'symbol': 'BTCUSDT',
                'exec_id': f'e{t}'}
    kw = dict(entry_sides={b: 'buy'}, grids={b: cfg})
    # the lot at rung 3 was bought at 82,400 (an old lattice's level), its
    # exit at rung 4 sells at 83,200: +800 by the venue's prices; the
    # config's lattice (83,000 at rung 3) would have said +200
    seen = [f(1, 'buy', 82400.0, 1.0, 3), f(2, 'sell', 83200.0, 1.0, 4)]
    book = ledger(seen, [b], **kw)[b]
    assert abs(book['gap_realized'] - 800.0) < 1e-9 and book['same_rung'] == 0
    # the entry NOT in the window: the lattice level stands in
    unseen = [f(2, 'sell', 83200.0, 1.0, 4)]
    assert abs(ledger(unseen, [b], **kw)[b]['gap_realized'] - 200.0) < 1e-9
    # a slid window: rung 14 is beyond the home lattice; the buy was seen
    slid = [f(1, 'buy', 93100.0, 1.0, 13), f(2, 'sell', 94000.0, 1.0, 14)]
    assert abs(ledger(slid, [b], **kw)[b]['gap_realized'] - 900.0) < 1e-9
    # the lot bought twice (two rounds): the LATEST buy at that rung is it
    twice = [f(1, 'buy', 82000.0, 1.0, 3), f(2, 'sell', 83000.0, 1.0, 4),
             f(3, 'buy', 82600.0, 1.0, 3), f(4, 'sell', 83000.0, 1.0, 4)]
    assert abs(ledger(twice, [b], **kw)[b]['gap_realized'] - 1400.0) < 1e-9


def spec_R11_an_inverse_book_speaks_dollars_to_the_panel():
    """The inverse book realises in BTC (A4). The panel printed it as if
    quote: -0.0003 BTC read "-0.00". The contract converts at the mark and
    carries the coin figures beside it."""
    from gridgremlin.report import public_book
    b = new_book()
    apply_fill(b, 'buy', 80000.0, 8000.0, 0.0001, inverse=True)   # $8,000
    apply_fill(b, 'sell', 84000.0, 4000.0, 0.0001, inverse=True)
    out = public_book(b, mark=85000.0, side='long', strategy='grid')
    btc = 4000.0 * (1 / 80000.0 - 1 / 84000.0)
    assert abs(out['settle']['realized'] - btc) < 1e-12
    assert abs(out['realized'] - btc * 85000.0) < 1e-9       # in dollars
    assert abs(out['fees'] - 0.0002 * 85000.0) < 1e-9
    unreal_btc = 4000.0 * (1 / 80000.0 - 1 / 85000.0)
    assert abs(out['unreal_at_mark'] - unreal_btc * 85000.0) < 1e-9
    assert abs(out['settle']['unreal'] - unreal_btc) < 1e-12
    assert out['inverse'] and out['settle']['coin'] == 'coin'   # no symbol
    from gridgremlin.report import base_coin
    assert base_coin('BTCUSD') == 'BTC' and base_coin('ETHUSD') == 'ETH'
    assert base_coin('SOLUSDH26') == 'SOL' and base_coin('XRPUSDT') == 'XRP'
    named = public_book(b, mark=85000.0, side='long', strategy='grid',
                        symbol='ETHUSD')
    assert named['settle']['coin'] == 'ETH'
    dark = public_book(b, mark=None, side='long', strategy='grid')
    assert dark['realized'] is None and dark['unreal_at_mark'] is None


def spec_U16_the_contract_carries_each_bots_terms():
    import io
    import json
    import sys
    import tempfile
    from pathlib import Path
    import gridgremlin.report as rp
    d = Path(tempfile.mkdtemp())
    (d / 'wd.json').write_text(json.dumps({
        'tag': 't', 'snapshot': 's', 'state': 'st', 'staleness_seconds': 9,
        'mm_rate_max': 0.5, 'equity_min': 10, 're_alert_seconds': 9,
        'assumes_sole_actor': True}))
    (d / 'f.json').write_text(json.dumps({'watchdog': str(d / 'wd.json'), 'bots': [
        {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
         'capital': 1000, 'leverage': 5, 'lower': 80000, 'upper': 90000,
         'rungs': 11},
        {'strategy': 'martingale', 'market_type': 'linear',
         'symbol': 'SOLUSDT', 'side': 'long', 'capital': 4000, 'leverage': 2,
         'base_order_size': 300, 'safety_order_size': 300,
         'deviation_pct': 0.01, 'max_averaging_orders': 5,
         'take_profit_avg_pct': 0.01}]}))
    saved = rp._bybit_pull, sys.stdout
    try:
        rp._bybit_pull = lambda rows, a, b: ([], {})
        sys.stdout = io.StringIO()
        rp.main([str(d / 'f.json'), '--json'])
        out = json.loads(sys.stdout.getvalue())
    finally:
        rp._bybit_pull, sys.stdout = saved
    btc = out['terms']['linBTCUSDTl']
    assert {k: btc[k] for k in ('capital', 'leverage', 'notional')} == {
        'capital': 1000.0, 'leverage': 5.0, 'notional': 5000.0}
    assert btc['market_type'] == 'linear' and btc['strategy'] == 'grid'   # U36
    sol = out['terms']['linSOLUSDTl']
    assert sol['capital'] == 4000.0 and sol['leverage'] == 2.0
    assert abs(sol['notional'] - 1800.0) < 1e-9        # the ladder's total,
                                                        # not capital x lev


def spec_R14_a_shorts_partial_window_widens_on_the_venues_holding():
    """2026-10-05 cross-check: every long matched the exchange; every short
    showed the window's partial book — the mid-round sign test cannot see
    a short holding short. The exchange's held size is the tell for any
    bot, and a bot with no fills in the window but a holding is read too."""
    import io
    import json
    import sys
    import tempfile
    from pathlib import Path
    import gridgremlin.report as rp
    d = Path(tempfile.mkdtemp())
    (d / 'wd.json').write_text(json.dumps({
        'tag': 't', 'snapshot': 's', 'state': 'st', 'staleness_seconds': 9,
        'mm_rate_max': 0.5, 'equity_min': 10, 're_alert_seconds': 9,
        'assumes_sole_actor': True}))
    (d / 'f.json').write_text(json.dumps({'watchdog': str(d / 'wd.json'), 'bots': [
        {'market_type': 'linear', 'symbol': 'ETHUSDT', 'side': 'short',
         'capital': 1000, 'leverage': 5, 'lower': 2000, 'upper': 3000,
         'rungs': 11, 'spacing_type': 'fixed'}]}))
    S = 'linETHUSDTs'
    now = 100 * 3_600_000
    h = 3_600_000
    history = [_fill(now - 90 * h, 'sell', 2500, 2, link=f'{S}-5-a', symbol='ETHUSDT'),
               _fill(now - 80 * h, 'buy', 2400, 2, link=f'{S}-4-b', symbol='ETHUSDT'),  # flat
               _fill(now - 70 * h, 'sell', 2600, 3, link=f'{S}-6-c', symbol='ETHUSDT'),
               _fill(now - 10 * h, 'sell', 2700, 1, link=f'{S}-7-d', symbol='ETHUSDT')]
    pulls = []

    def pull(rows, since, until):
        pulls.append(since)
        return [f for f in history if f['time_ms'] >= since], {('linear', 'ETHUSDT'): 2650.0}
    saved = rp._bybit_pull, rp._venue_held_all, rp.time.time, sys.stdout
    try:
        rp._bybit_pull = pull
        rp._venue_held_all = lambda venue, rows: {S: 4.0}   # the exchange
        rp.time.time = lambda: now / 1000.0
        sys.stdout = io.StringIO()
        rp.main([str(d / 'f.json'), '--hours', '24', '--json'])
        out = json.loads(sys.stdout.getvalue())
    finally:
        rp._bybit_pull, rp._venue_held_all, rp.time.time, sys.stdout = saved
    b = out['bots'][S]
    assert b['counted_from'] == 'flat' and b['counted_since_ms'] == now - 70 * h
    assert abs(b['position'] + 4.0) < 1e-9             # the short, whole
    assert abs(b['avg_cost'] - 2625.0) < 1e-9          # (3x2600 + 2700) / 4
    assert not b['truncated'] and pulls[0] == now - 24 * h and len(pulls) >= 3


def spec_R14_the_widening_shares_one_history_read_per_venue_and_horizon():
    """Hyperliquid's fill history is read per ADDRESS: five bots widening
    to the same horizon made five identical reads, ten seconds apart from
    the panel, and the fleet lost 5% of its cycles to the rate limit."""
    import io
    import json
    import sys
    import tempfile
    from pathlib import Path
    import gridgremlin.report as rp
    d = Path(tempfile.mkdtemp())
    (d / 'wd.json').write_text(json.dumps({
        'tag': 't', 'snapshot': 's', 'state': 'st', 'staleness_seconds': 9,
        'mm_rate_max': 0.5, 'equity_min': 10, 're_alert_seconds': 9,
        'assumes_sole_actor': True}))
    rows = [{'venue': 'hyperliquid', 'market_type': 'linear', 'symbol': c,
             'side': 'long', 'capital': 100, 'leverage': 3, 'lower': 50,
             'upper': 150, 'rungs': 11, 'spacing_type': 'fixed'}
            for c in ('SOL', 'AVAX')]
    (d / 'f.json').write_text(json.dumps({'watchdog': str(d / 'wd.json'),
                                           'bots': rows}))
    now = 100 * 3_600_000
    h = 3_600_000
    history = []
    for c in ('SOL', 'AVAX'):
        L = f'lin{c}l'
        history += [_fill(now - 90 * h, 'buy', 100, 1, link=f'{L}-1-a', symbol=c),
                    _fill(now - 80 * h, 'sell', 101, 1, link=f'{L}-0-b', symbol=c),
                    _fill(now - 70 * h, 'buy', 100, 2, link=f'{L}-2-c', symbol=c)]
    pulls = []

    def hl_pull(rows_, since):
        pulls.append(since)
        return ([dict(f, market_type='linear') for f in history
                 if f['time_ms'] >= since],
                {('linear', 'SOL'): 100.0, ('linear', 'AVAX'): 100.0})
    saved = rp._hl_pull, rp._venue_held_all, rp.time.time, sys.stdout
    try:
        rp._hl_pull = hl_pull
        rp._venue_held_all = lambda venue, rows_: {'linSOLl': 2.0, 'linAVAXl': 2.0}
        rp.time.time = lambda: now / 1000.0
        sys.stdout = io.StringIO()
        rp.main([str(d / 'f.json'), '--hours', '24', '--json'])
        out = json.loads(sys.stdout.getvalue())
    finally:
        rp._hl_pull, rp._venue_held_all, rp.time.time, sys.stdout = saved
    assert out['bots']['linSOLl']['counted_from'] == 'flat'
    assert out['bots']['linAVAXl']['counted_from'] == 'flat'
    assert pulls == [now - 24 * h, now - 48 * h, now - 96 * h]   # once each


def spec_R17_the_day_is_archived_once_per_fleet_and_date():
    """2026-10-05, for the results chapter the owner will write: the
    readout answered "now" and nothing kept yesterday. The archive writes
    the readout's contract beside the newest snapshot row to one file per
    fleet per UTC date; a later run the same day replaces it; one fleet's
    failure never costs the other."""
    import json
    import tempfile
    from pathlib import Path
    from gridgremlin import archive as ar
    d = Path(tempfile.mkdtemp())
    t = 1791158400.0                                  # 2026-10-05 00:00 UTC
    contract = {'window_hours': 24.0, 'bots': {'linBTCUSDTl': {'realized': 5.0}}}
    p = ar.archive(d / 'fleet.demo.json', d / 'daily', now=t + 3600,
                   readout=lambda f: contract,
                   snapshot=lambda f: {'t': t, 'equity': 1000.0})
    assert p == d / 'daily' / 'demo' / '2026-10-05.json'
    rec = json.loads(p.read_text())
    assert rec['date'] == '2026-10-05' and rec['fleet'] == 'fleet.demo.json'
    assert rec['readout'] == contract and rec['snapshot']['equity'] == 1000.0
    contract['bots']['linBTCUSDTl']['realized'] = 9.0          # later that day
    ar.archive(d / 'fleet.demo.json', d / 'daily', now=t + 80000,
               readout=lambda f: contract, snapshot=lambda f: None)
    assert json.loads(p.read_text())['readout']['bots']['linBTCUSDTl'][
        'realized'] == 9.0                                    # replaced
    nxt = ar.archive(d / 'fleet.hl.testnet.json', d / 'daily', now=t + 90000,
                     readout=lambda f: {}, snapshot=lambda f: None)
    assert nxt == d / 'daily' / 'hl.testnet' / '2026-10-06.json'
    saved = ar.archive
    try:
        def boom(f, out):
            if 'bad' in str(f):
                raise RuntimeError('venue down')
            return Path(out) / 'ok'
        ar.archive = boom
        assert ar.main(['bad.json', 'good.json', '--out', str(d)]) == 1
    finally:
        ar.archive = saved


# --- R12: per trip is what the trip earned, by its own rung -------------------

def spec_R12_per_trip_is_the_exits_gain_against_its_own_rung():
    """Live 2026-10-03: the demo BTC long printed -156 per trip over 55
    trips while R11 found every exit a full gap. Average-cost realized
    charges each exit against an average lifted by the lots bought higher;
    the remainder's mark-to-average takes the same amount back. The sum is
    the same (R5 holds); the figure per trip must be the trip's own."""
    from gridgremlin.config import validate_config
    from gridgremlin.report import per_trip, public_book
    raw = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
           'capital': 1000, 'leverage': 10, 'lower': 80000, 'upper': 90000,
           'rungs': 11, 'spacing_type': 'fixed'}
    cfg = validate_config(dict(raw))
    b = 'linBTCUSDTl'

    def f(t, side, price, qty, rung):
        return {'time_ms': t, 'side': side, 'price': price, 'qty': qty,
                'fee': 0.0, 'link_id': f'{b}-{rung}-x', 'symbol': 'BTCUSDT',
                'exec_id': f'e{t}'}
    fills = [f(1, 'buy', 85000.0, 1.0, 5),       # avg 85,000
             f(2, 'buy', 83000.0, 1.0, 3),       # avg 84,000
             f(3, 'sell', 84000.0, 1.0, 4)]      # lot 3 exits: +1,000 by rung
    book = ledger(fills, [b], entry_sides={b: 'buy'}, grids={b: cfg})[b]
    assert abs(book['realized'] - 0.0) < 1e-9          # average-cost: nothing
    assert book['gap_trips'] == 1 and abs(book['gap_realized'] - 1000.0) < 1e-9
    assert abs(per_trip(book) - 1000.0) < 1e-9
    # the sum agrees once flat: the remainder is sold at its own exit too
    fills.append(f(4, 'sell', 86000.0, 1.0, 6))          # lot 5 exits: +1,000
    book = ledger(fills, [b], entry_sides={b: 'buy'}, grids={b: cfg})[b]
    assert abs(book['realized'] - 2000.0) < 1e-9
    assert abs(book['gap_realized'] - 2000.0) < 1e-9
    # the contract carries it; a short measures the other way
    assert abs(public_book(book, mark=86000.0, side='long',
                           strategy='grid')['per_trip'] - 1000.0) < 1e-9
    s = 'linBTCUSDTs'
    short = [dict(f(1, 'sell', 85000.0, 1.0, 5), link_id=f'{s}-5-x'),
             dict(f(2, 'buy', 84000.0, 1.0, 4), link_id=f'{s}-4-x')]
    scfg = validate_config(dict(raw, side='short'))
    sb = ledger(short, [s], entry_sides={s: 'sell'}, grids={s: scfg})[s]
    assert abs(per_trip(sb) - 1000.0) < 1e-9


def spec_R12_without_a_rung_per_trip_is_average_cost_realized():
    b = new_book()
    apply_fill(b, 'buy', 100.0, 1.0, 0.0)
    apply_fill(b, 'buy', 98.0, 1.0, 0.0)
    apply_fill(b, 'sell', 99.5, 1.0, 0.0)                # vs avg 99: +0.5
    from gridgremlin.report import per_trip
    assert b['gap_trips'] == 0 and abs(per_trip(b) - 0.5) < 1e-9
    assert per_trip(new_book()) is None


def spec_R12_identity_needs_no_book_so_a_truncated_window_still_states_it():
    """Live 2026-10-03: three shorts kept a negative per-trip after R12 —
    their windows opened on an exit fill, the book ran the wrong way all
    window (R7) and the sum was gated on that book's direction. An exit
    with a rung closes that rung's lot whatever the book thinks; a book
    without rungs says nothing under a truncated window."""
    from gridgremlin.config import validate_config
    from gridgremlin.report import per_trip, public_book, window_truncated
    cfg = validate_config({'market_type': 'linear', 'symbol': 'XRPUSDT',
                           'side': 'short', 'capital': 1000, 'leverage': 10,
                           'lower': 1.0, 'upper': 2.0, 'rungs': 11,
                           'spacing_type': 'fixed'})
    s = 'linXRPUSDTs'

    def f(t, side, price, qty, rung):
        return {'time_ms': t, 'side': side, 'price': price, 'qty': qty,
                'fee': 0.0, 'link_id': f'{s}-{rung}-x', 'symbol': 'XRPUSDT',
                'exec_id': f'e{t}'}
    fills = [f(1, 'buy', 1.5, 100.0, 5),      # the window opens on an EXIT:
             f(2, 'sell', 1.5, 100.0, 5),     # lot 6 (1.6) closed: +10
             f(3, 'buy', 1.5, 100.0, 5)]      # lot 5 sold, lot 6 closed: +10
    book = ledger(fills, [s], entry_sides={s: 'sell'}, grids={s: cfg})[s]
    assert window_truncated(book, 'short')
    assert book['gap_trips'] == 2 and abs(book['gap_realized'] - 20.0) < 1e-9
    assert abs(per_trip(book, True) - 10.0) < 1e-9
    assert abs(public_book(book, mark=1.5, side='short',
                           strategy='grid')['per_trip'] - 10.0) < 1e-9
    plain = new_book()                         # no rungs, opened mid-round
    apply_fill(plain, 'buy', 1.5, 100.0, 0.0)
    apply_fill(plain, 'sell', 1.6, 100.0, 0.0)
    assert plain['trips'] == 1 and per_trip(plain, truncated=True) is None
    assert abs(per_trip(plain, truncated=False) - 10.0) < 1e-9


# --- R13: a round begins flat at its base order ------------------------------

def spec_R13_a_round_bots_book_re_anchors_flat_at_a_new_base_order():
    """Live 2026-10-03 (and BACKLOG since 09-25): the ADA looper showed 692
    fills and no completed round. Its 24h window opened on the previous
    round's take-profit fills, the book went -2,083 and no later close
    ever landed at zero. A base order (the entry side's rung 0, a new
    link) begins a round from flat by the martingale's own law, so the
    book is re-anchored there; a split base order anchors once; a window
    that opened flat is untouched."""
    b = 'linADAUSDTl'
    kw = dict(entry_sides={b: 'buy'},
              closers={('linear', 'ADAUSDT', 'sell'): b}, rounders={b})

    def f(t, side, price, qty, link):
        return dict(_fill(t, side, price, qty, 0.0, link=link,
                          symbol='ADAUSDT'),
                    market_type='linear', venue_closed=(link == ''))
    fills = [f(1, 'sell', 0.258, 2083.0, ''),            # last round's TP
             f(2, 'buy', 0.257, 2126.0, f'{b}-0-a'),     # base: anchor
             f(3, 'buy', 0.254, 2147.0, f'{b}-1-b'),     # safety 1
             f(4, 'sell', 0.2538, 4273.0, ''),           # TP closes the round
             f(5, 'buy', 0.2537, 1000.0, f'{b}-0-c'),    # next base, split
             f(6, 'buy', 0.2537, 1284.0, f'{b}-0-c')]    # in two fills
    book = ledger(fills, [b], **kw)[b]
    assert book['anchored'] is True
    assert book['rounds'] == 1
    pnl = (0.2538 - 0.257) * 2126.0 + (0.2538 - 0.254) * 2147.0
    assert abs(book['round_pnl_sum'] - pnl) < 1e-6
    assert abs(book['position'] - 2284.0) < 1e-9          # one base, whole
    assert ledger(fills, [b], entry_sides={b: 'buy'},
                  closers=kw['closers'])[b]['rounds'] == 0    # without R13
    flat = ledger(fills[1:], [b], **kw)[b]                   # opened flat:
    assert flat['anchored'] is False and flat['rounds'] == 1  # untouched


# --- D63: funding is its own term --------------------------------------------

def _ev(t, side, amount, symbol='SOLUSDT', mt='linear'):
    return {'time_ms': t, 'side': side, 'amount': amount, 'symbol': symbol,
            'market_type': mt}


def spec_D63_funding_is_this_legs_own_over_this_books_window():
    from gridgremlin.report import funding_of
    ev = [_ev(100, 'buy', -1.0), _ev(200, 'buy', -2.0), _ev(200, 'sell', 5.0),
          _ev(300, 'buy', -4.0), _ev(200, 'buy', -8.0, symbol='BTCUSDT'),
          _ev(200, 'buy', -16.0, mt='inverse')]
    assert funding_of(ev, 'linear', 'SOLUSDT', 'buy', 150, 300) == -6.0
    assert funding_of(ev, 'linear', 'SOLUSDT', 'sell', 0, 999) == 5.0
    assert funding_of(ev, 'linear', 'SOLUSDT', 'buy', 400, 999) == 0.0


def spec_D63_unread_funding_is_none_never_a_zero():
    from gridgremlin.report import new_book, set_funding
    b = set_funding(new_book(), [_ev(1, 'buy', -3.0)], {'bybit'}, 'bybit',
                    'linear', 'SOLUSDT', 'buy', 0, 9)
    assert b['funding'] is None
    b = set_funding(new_book(), [_ev(1, 'buy', -3.0)], set(), 'bybit',
                    'linear', 'SOLUSDT', 'buy', 0, 9)
    assert b['funding'] == -3.0


def spec_D63_the_total_carries_funding_and_an_inverse_book_converts_it():
    from gridgremlin.report import new_book, public_book, total_pnl
    b = new_book()
    b.update(realized=10.0, fees=1.0, funding=-4.0)
    assert total_pnl(b, 100.0) == 5.0          # 10 - 1 - 4, flat
    inv = new_book()
    inv.update(realized=0.001, fees=0.0001, funding=-0.0002, inverse=True)
    out = public_book(inv, mark=50000.0, symbol='BTCUSD')
    assert abs(out['funding'] - (-10.0)) < 1e-9
    assert out['settle']['funding'] == -0.0002
    assert abs(total_pnl(inv, 50000.0) - 35.0) < 1e-9    # (0.001-0.0001-0.0002)*50000


def spec_D63_per_trip_after_fees_takes_both_legs_off_each_trip():
    from gridgremlin.report import per_trip, per_trip_net, public_book
    b = new_book()
    b.update(gap_realized=30.0, gap_trips=3, fees=1.2, fills=6)   # 0.2/fill
    assert per_trip(b) == 10.0
    assert abs(per_trip_net(b) - 9.6) < 1e-9                       # 10 - 2*0.2
    out = public_book(b, mark=1.0, side='long', strategy='grid')
    assert abs(out['per_trip_net'] - 9.6) < 1e-9
    assert per_trip_net(new_book()) is None


def spec_D63_hl_books_total_in_usdc_whatever_the_coin_is_called():
    from gridgremlin.report import settle_quote
    assert settle_quote('hyperliquid', 'BTC') == 'USDC'
    assert settle_quote('bybit', 'BTCUSDT') == 'USDT'
    assert settle_quote('bybit', 'BTCPERP') == 'USDC'
