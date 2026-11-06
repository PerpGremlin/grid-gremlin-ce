# Specs for SPEC I1-I3 and E2's decision half, plus the E6/E7 matrix.

from gridgremlin.adapters import LinearAdapter, SpotAdapter
from gridgremlin.apply import (bot_identity, check_fleet_unique,
                               check_link_fits, diff, make_botid, make_link,
                               matches, pair_amends, rung_of)
from gridgremlin.config import ConfigError
from gridgremlin.exchange.errors import KINDS, KIND_REACTIONS

BOT = 'linBTCUSDTl'


def _desired(rung, price, qty, side='Buy', ro=False):
    return {'rung': rung, 'side': side, 'price': price, 'qty': qty,
            'reduce_only': ro}


def _resting(rung, price, qty, side='Buy', ro=False, link=None, gen='a1'):
    return {'order_id': f'oid{rung}', 'link_id': link or make_link(BOT, rung, gen),
            'side': side, 'price': price, 'qty': qty, 'cum_exec_qty': 0.0,
            'reduce_only': ro, 'status': 'New', 'position_idx': 1,
            'order_type': 'Limit', 'updated_time_ms': 0}


# --- I1: identity and ownership ----------------------------------------------

def spec_I1_botid_strips_hyphens():
    assert make_botid('linear', 'BTC-PERP', 'long') == 'linBTCPERPl'
    assert make_botid('spot', 'ETHUSDT', 'short') == 'spoETHUSDTs'


def spec_I1_rung_of_is_the_ownership_guard():
    assert rung_of(make_link(BOT, 7, 1722), BOT) == 7
    assert rung_of('my-own-stop-loss', BOT) is None          # the manual order
    assert rung_of(f'{BOT}-junk-1', BOT) is None             # unparseable tail
    assert rung_of('otherbot-7-100', BOT) is None            # foreign prefix
    assert rung_of(None, BOT) is None


def spec_I2_one_bot_per_identity():
    hedge = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001,
                           'price_tick': 0.1, 'min_qty': 0.001})
    long_cfg = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long'}
    short_cfg = dict(long_cfg, side='short')
    a = bot_identity(long_cfg, hedge)
    b = bot_identity(short_cfg, hedge)
    assert a != b                          # hedge legs coexist (idx 1 vs 2)
    check_fleet_unique([('botA', a), ('botB', b)])
    try:
        check_fleet_unique([('botA', a), ('botC', a)])
    except ConfigError as e:
        assert 'one bot per' in str(e)
    else:
        raise AssertionError('identity collision accepted')


def spec_I2_spot_and_linear_are_distinct_identities():
    spot = SpotAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001,
                        'price_tick': 0.1, 'min_qty': 0.001})
    lin = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001,
                         'price_tick': 0.1, 'min_qty': 0.001,
                         'one_way_mode': True})
    s = bot_identity({'market_type': 'spot', 'symbol': 'BTCUSDT',
                      'side': 'long'}, spot)
    l = bot_identity({'market_type': 'linear', 'symbol': 'BTCUSDT',
                      'side': 'long'}, lin)
    assert s != l


def spec_I3_link_length_refuses_at_build():
    check_link_fits(BOT, 999, venue_limit=36)
    try:
        check_link_fits('linSOMEVERYLONGSYMBOLNAMEUSDTl', 999, venue_limit=36)
    except ConfigError as e:
        assert 'venue limit' in str(e)
    else:
        raise AssertionError('oversized link accepted')


# --- E2 decisions: keep / cancel / create ------------------------------------

def spec_E2_matching_orders_are_kept():
    desired = [_desired(3, 53000.0, 0.008)]
    resting = [_resting(3, 53000.0, 0.008)]
    cancel, create = diff(desired, resting, BOT)
    assert cancel == [] and create == []                     # steady state


def spec_E2_foreign_orders_are_invisible():
    resting = [_resting(3, 53000.0, 0.008, link='my-own-stop-loss'),
               _resting(4, 54000.0, 0.008, link='otherbot-4-9')]
    cancel, create = diff([], resting, BOT)
    assert cancel == []                                      # I1 immunity


def spec_E2_unwanted_rungs_cancel_missing_rungs_create():
    desired = [_desired(3, 53000.0, 0.008)]
    resting = [_resting(9, 59000.0, 0.008)]
    cancel, create = diff(desired, resting, BOT)
    assert [o['link_id'] for o in cancel] == [make_link(BOT, 9, 'a1')]
    assert create == desired


def spec_E2_duplicates_on_one_rung_keep_exactly_one():
    desired = [_desired(3, 53000.0, 0.008)]
    resting = [_resting(3, 53000.0, 0.008, gen='a1'),
               _resting(3, 53000.0, 0.008, gen='a2'),
               _resting(3, 53000.0, 0.008, gen='a3')]
    cancel, create = diff(desired, resting, BOT)
    assert len(cancel) == 2 and create == []                 # self-heals


def spec_E2_truncation_is_kept_but_a_grown_position_is_recovered():
    """The old spec pinned keeping a 0.009 exit against a 0.021 desire
    forever — conflating venue truncation with a position that GREW past
    a stale cover (audit 2026-08-07 wrong-spec). Small shrink: keep.
    Below three quarters: re-size, or the growth never exits."""
    want = _desired(12, 63000.0, 0.021, side='Sell', ro=True)
    shrunk = _resting(12, 63000.0, 0.019, side='Sell', ro=True)
    cancel, create = diff([want], [shrunk], BOT)
    assert cancel == [] and create == []          # venue-shrunk: keep
    stale = _resting(12, 63000.0, 0.009, side='Sell', ro=True)
    cancel, create = diff([want], [stale], BOT)
    assert len(cancel) == 1 and len(create) == 1  # grown past it: re-size
    oversized = _resting(12, 63000.0, 0.030, side='Sell', ro=True)
    cancel, create = diff([want], [oversized], BOT)
    assert len(cancel) == 1 and len(create) == 1  # over-covering: replace


def spec_E2_entry_qty_uses_relative_tolerance():
    want = _desired(3, 53000.0, 0.008)
    assert matches(want, _resting(3, 53000.0, 0.0079))       # within 5%
    assert not matches(want, _resting(3, 53000.0, 0.006))    # outside


def spec_D88_an_entry_a_step_off_its_plan_is_corrected():
    """The audit (2026-10-08), granted by the owner 2026-10-11: a resting
    entry within 5% of its plan was accepted — wide for a desk. Given the
    venue's step, an entry matches only within half a step: one step off is
    a cancel and a create at the same price, which the pairing makes an
    amend. Exits keep their truncation band; without a step, the old rule."""
    import inspect
    from gridgremlin import bot
    step = 0.001
    want = _desired(3, 53000.0, 0.008)
    assert matches(want, _resting(3, 53000.0, 0.008), qty_step=step)
    assert matches(want, _resting(3, 53000.0, 0.0084), qty_step=step)          # inside half a step
    assert not matches(want, _resting(3, 53000.0, 0.009), qty_step=step)       # a step off
    assert not matches(want, _resting(3, 53000.0, 0.0079 - 0.0005), qty_step=step)
    assert matches(want, _resting(3, 53000.0, 0.0079))                        # no step: the 5% band
    cancel, create = diff([want], [_resting(3, 53000.0, 0.009)], BOT, qty_step=step)
    amends, cancels, creates = pair_amends(cancel, create, BOT)
    assert len(amends) == 1 and cancels == [] and creates == []               # an amend, not a re-place
    exit_want = _desired(12, 63000.0, 0.021, side='Sell', ro=True)
    assert matches(exit_want, _resting(12, 63000.0, 0.019, side='Sell', ro=True), qty_step=step)  # truncation band
    src = inspect.getsource(bot)
    assert src.count('qty_step=step)') == 2                                   # both of the bot's diffs pass it


# --- amend pairing: qty yes, price never -------------------------------------

def spec_E2_same_price_qty_change_is_an_amend():
    cancel = [_resting(3, 53000.0, 0.010)]
    create = [_desired(3, 53000.0, 0.008)]
    amends, cancels, creates = pair_amends(cancel, create, BOT)
    assert len(amends) == 1 and cancels == [] and creates == []
    old, new = amends[0]
    assert old['qty'] == 0.010 and new['qty'] == 0.008


def spec_E2_a_moved_price_is_never_amended():
    # the trail-shaped case that made v2's spec vacuous (audit 3.8): same rung,
    # new price MUST cancel+create — amending price would jump the book queue
    cancel = [_resting(3, 53000.0, 0.008)]
    create = [_desired(3, 53500.0, 0.008)]
    amends, cancels, creates = pair_amends(cancel, create, BOT)
    assert amends == [] and len(cancels) == 1 and len(creates) == 1


def spec_E2_amend_never_crosses_sides_or_flags():
    cancel = [_resting(3, 53000.0, 0.008, side='Sell', ro=True)]
    create = [_desired(3, 53000.0, 0.010)]
    amends, cancels, creates = pair_amends(cancel, create, BOT)
    assert amends == []


# --- E6/E7: the reaction matrix ----------------------------------------------

def spec_E7_every_kind_reacts_and_none_kills():
    # pins: E6 (kinds, never codes; ambiguous defers)
    assert set(KIND_REACTIONS) == set(KINDS)
    assert all('kill' not in r for r in KIND_REACTIONS.values())
    assert KIND_REACTIONS['margin'] == 'backoff_growth_only'
    assert KIND_REACTIONS['gone'] == 'treat_done'
    assert KIND_REACTIONS['flat'] == 'treat_done'


def spec_B7_bybits_tier_cap_is_a_margin_refusal_not_a_rung_flap():
    """2026-10-08: a 28-rung adverse slide at 75x met Bybit's risk-tier cap
    (110090, "the combined value of positions and orders has reached the
    limit of the current risk tier"). Classed 'other', every buy rung was
    placed, refused, struck out and cooled, and each cooling paged — a
    page a minute for 13 hours. The cap is the account's standing, not a
    rung's: 'margin', so B7 halts growth and backs off."""
    from gridgremlin.exchange.bybit.client import _post_kind
    from gridgremlin.exchange.errors import KIND_REACTIONS
    assert _post_kind(110090, 'The combined value of positions and orders has '
                      'reached the limit of the current risk tier.') == 'margin'
    assert _post_kind(110007, 'ab not enough for new order') == 'margin'
    assert KIND_REACTIONS[_post_kind(110090)] == 'backoff_growth_only'


def spec_E7_zero_position_is_the_close_we_expected_not_a_warning():
    # pins: E7b
    """Live 2026-10-05: every tranche round's end logged two warns — the
    stop and TP upkeep wrote for a position Bybit had just closed, and got
    retCode 10001 "can not set tp/sl/ts for zero position". That is the
    round ending, not a fault. 10001 is a generic code: only that sentence
    is 'flat'."""
    from gridgremlin.exchange.bybit.client import _post_kind
    assert _post_kind(10001, 'can not set tp/sl/ts for zero position') == 'flat'
    assert _post_kind(10001, 'params error: qty invalid') == 'other'
    assert _post_kind(110001, 'order not exists') == 'gone'
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from spec_round import ADAPTER, FakeVenue, _tranche_cfg
    from gridgremlin.bot import Bot
    from gridgremlin.events import Notifier
    from gridgremlin.exchange.errors import VenueError
    for kind, warned in (('flat', False), ('other', True)):
        venue, lines = FakeVenue(), []
        bot = Bot(_tranche_cfg(breakeven_ladder=True), ADAPTER, venue,
                  Notifier(sink=lines.append), gen_seed=1)
        bot.cycle()
        bot.cycle()
        venue.mark = 60800.0                         # tranche 1 passed
        venue.position = dict(venue.position, size='0.008')

        def refuse(*a, kind=kind, **k):
            raise VenueError('bybit /v5/position/trading-stop: retCode 10001: '
                             'can not set tp/sl/ts for zero position', kind=kind)
        venue.set_trading_stop = refuse
        bot.cycle()
        assert any('breakeven stop:' in ln and ' warn ' in ln
                   for ln in lines) is warned, (kind, lines[-4:])


def spec_I3_every_shipped_fleet_row_fits_its_venues_link():
    """A row that validates can still refuse at build: the HL fleet shipped
    with a slide clamp whose furthest link was 17 chars against HL's 16, and
    the unit crash-looped on start (2026-10-02)."""
    import glob
    import json
    import os
    from gridgremlin.apply import check_link_fits, make_botid, widest_rung
    from gridgremlin.config import validate_config
    from gridgremlin.main import BYBIT_LINK_LIMIT
    root = os.path.join(os.path.dirname(__file__), '..', 'configs')
    files = sorted(glob.glob(os.path.join(root, 'fleet*.json')))
    assert files
    for path in files:
        for row in json.load(open(path))['bots']:
            if row.get('strategy') == 'portfolio':
                continue                               # D78: no rung, no link
            cfg = validate_config(row)
            hl = cfg['venue'] == 'hyperliquid'
            check_link_fits(
                make_botid(cfg['market_type'], cfg['symbol'], cfg['side']),
                widest_rung(cfg), 16 if hl else BYBIT_LINK_LIMIT,
                gen_chars=4 if hl else 10)


# --- E6c/E6d: what a write's answer means (audit 2026-11-05) ----------------

class _Resp:
    """urlopen's answer: a body, or a read that is cut off."""

    def __init__(self, body=None, err=None):
        self.body, self.err, self.headers = body, err, {}

    def read(self):
        if self.err is not None:
            raise self.err
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _bybit_post(answer):
    """One WriteClient cancel against a stubbed urlopen: `answer` is the
    response, or the exception urlopen raises. Returns what was raised."""
    import urllib.request
    from gridgremlin.exchange.bybit.client import WriteClient
    from gridgremlin.exchange.pacer import Pacer
    c = WriteClient(env='demo', api_key='k', api_secret='s',
                    transport=lambda url, h: {})
    c._synced, c._pacer = True, Pacer(min_gap=0.0)

    def urlopen(req, timeout=None):
        if isinstance(answer, BaseException):
            raise answer
        return answer
    saved = urllib.request.urlopen
    urllib.request.urlopen = urlopen
    try:
        c.cancel_order('linear', 'BTCUSDT', 'o1')
    except Exception as e:      # noqa: BLE001 — the spec reads what was raised
        return e
    finally:
        urllib.request.urlopen = saved
    return None


def spec_E6c_a_cancel_of_a_finished_order_is_gone():
    """Bybit v5's error table: 110008 "The order has been completed or
    cancelled.", 110010 "The order has been cancelled". Read as 'other',
    every cancel path kept the rung uncancelled, held its replacement back
    and warned of an order that had already filled. SABOTAGE: drop 110008
    from ORDER_GONE_CODES -> red."""
    import json
    from gridgremlin.exchange.bybit.client import _kind, _post_kind
    from gridgremlin.exchange.errors import may_have_landed
    for code in (110001, 110008, 110010, 170213):
        assert _post_kind(code, '') == 'gone', code
        assert _kind(code) == 'gone', code
        e = _bybit_post(_Resp(json.dumps({'retCode': code,
                                          'retMsg': 'finished'}).encode()))
        assert e is not None and e.kind == 'gone' and not may_have_landed(e), (code, e)
        assert KIND_REACTIONS[e.kind] == 'treat_done'


def spec_E6d_a_cut_off_answer_is_ambiguous_and_403_429_are_refusals():
    """A write whose answer is cut off (IncompleteRead) or garbled (JSON
    that does not parse) may have landed: it is ambiguous, a VenueError the
    write paths catch and reconcile — raw, neither is an OSError, so the
    whole cycle was lost instead. HTTP 403/429 are refusals before
    processing (Bybit v5: "IP rate limit breached", "System level frequency
    protection"): a definite no that waits for the window — raw, an
    HTTPError is an OSError and was taken for an unknown fate. A 5xx keeps
    E6b's careful reading. SABOTAGE: drop the cut-off clause in
    WriteClient.post -> red; drop 429 from HTTP_REFUSED_CODES -> red."""
    import http.client
    import io
    import urllib.error
    from gridgremlin.exchange.errors import VenueError, may_have_landed
    for resp in (_Resp(err=http.client.IncompleteRead(b'{"retCode":0,"res')),
                 _Resp(b'{"retCode":0,"res')):
        e = _bybit_post(resp)
        assert isinstance(e, VenueError) and e.ambiguous and may_have_landed(e), e
        assert 'may have landed' in str(e)
    for code in (403, 429):
        e = _bybit_post(urllib.error.HTTPError('u', code, 'no', {}, io.BytesIO(b'')))
        assert isinstance(e, VenueError) and e.kind == 'rate_limit', (code, e)
        assert not may_have_landed(e), code
        assert KIND_REACTIONS[e.kind] == 'wait_for_window'
    e = _bybit_post(urllib.error.HTTPError('u', 502, 'bad gateway', {}, io.BytesIO(b'')))
    assert may_have_landed(e)                    # 5xx: the fate is unknown


def spec_E6d_hl_a_cut_off_answer_is_ambiguous():
    """Hyperliquid's write transport, the same: a cut-off or garbled answer
    is HLError(ambiguous=True), never a raw exception. SABOTAGE: drop the
    clause in _post_action -> red."""
    import http.client
    import json
    from gridgremlin.exchange.hyperliquid.exchange import ExchangeClient
    from gridgremlin.exchange.errors import VenueError, may_have_landed
    c = ExchangeClient(env='testnet', address='0x' + '22' * 20,
                       private_key='0x' + '11' * 32)
    for err in (http.client.IncompleteRead(b'{"status":"o'),
                json.JSONDecodeError('Expecting value', '{"st', 4)):
        def post(path, body, retry_429=True, err=err):
            raise err
        c._post = post
        try:
            c.cancel_order(0, order_id=1)
            raised = None
        except Exception as e:      # noqa: BLE001 — the spec reads what was raised
            raised = e
        assert isinstance(raised, VenueError) and raised.ambiguous, raised
        assert may_have_landed(raised)


# --- E6e: no answer to a write is an ambiguous VenueError -------------------

def _no_answer(exc):
    """What the Bybit adapter raises when urlopen raises `exc` on a write."""
    e = _bybit_post(exc)
    assert e is not None, exc
    return e


def spec_E6e_a_write_with_no_answer_is_an_ambiguous_venue_error():
    """A timeout, a reset or a dropped line after the send, and a 5xx: the
    write may have landed. Raw (an OSError), each escaped every `except
    VenueError` write path — the ladder's cancels, amends and places, the
    round's exits — and lost the cycle. Both venues now raise an ambiguous
    VenueError, never `gone`. SABOTAGE: drop the OSError clause in
    WriteClient.post -> red; drop the HTTPError fall-through -> red; drop
    the HL network clause in _post_action -> red."""
    import io
    import urllib.error
    from gridgremlin.exchange.errors import VenueError, may_have_landed
    for exc in (TimeoutError('timed out'), ConnectionResetError('reset'),
                urllib.error.URLError('no route'),
                urllib.error.HTTPError('u', 502, 'bad gateway', {}, io.BytesIO(b'')),
                urllib.error.HTTPError('u', 500, 'error', {}, io.BytesIO(b''))):
        e = _no_answer(exc)
        assert isinstance(e, VenueError) and e.ambiguous and may_have_landed(e), (exc, e)
        assert e.kind == 'other', (exc, e.kind)          # never 'gone'
    from gridgremlin.exchange.hyperliquid.client import HLError
    from gridgremlin.exchange.hyperliquid.exchange import ExchangeClient
    c = ExchangeClient(env='testnet', address='0x' + '22' * 20,
                       private_key='0x' + '11' * 32)
    for err in (TimeoutError('timed out'), urllib.error.URLError('no route'),
                HLError(502, '/exchange: HTTP 502', 'bad gateway')):
        def post(path, body, retry_429=True, err=err):
            raise err
        c._post = post
        try:
            c.cancel_order(0, order_id=1)
            raised = None
        except Exception as e:      # noqa: BLE001 — the spec reads what was raised
            raised = e
        assert isinstance(raised, VenueError) and raised.ambiguous, (err, raised)
        assert raised.kind != 'gone'


def spec_E6e_x17_an_unanswered_cancel_still_rests_and_a_place_is_never_resent():
    """The callers, as the adapter now raises: X17 counts a cancel with no
    answer as STILL RESTING (never gone) and the bot stays up doing the
    stop's work; a ladder place with no answer is not sent again in its
    cycle, and the next cycle reads the book first — an order that landed
    is never placed twice."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from spec_loop import FakeVenue, _cfg as loop_cfg, ADAPTER as LOOP_ADAPTER
    from spec_stops import _holding, _tombed
    from gridgremlin.bot import Bot
    from gridgremlin.events import Notifier
    timeout = _no_answer(TimeoutError('timed out'))

    class Unanswered(FakeVenue):
        def cancel_order(self, *a, **kw):
            raise timeout
    venue, lines = Unanswered(mark=61000.0), []
    _holding(venue)
    bot = _tombed(venue, lines, stop={'watch': 'mark_price', 'level': 58000})
    bot.cycle()
    resting = len(venue.orders)
    assert resting
    venue.mark = 57000.0
    bot.cycle()                                      # the adapter's error, caught
    said = next(ln for ln in lines if 'stop NOT finished' in ln)
    assert f'{resting} owned orders STILL REST' in said, said
    assert bot.alive and bot.stopping and len(venue.orders) == resting
    assert not any(' kill ' in ln for ln in lines)

    class Landed(FakeVenue):
        """Every place lands on the venue, and its answer never arrives."""
        calls = 0

        def place_order(self, *a, **kw):
            type(self).calls += 1
            super().place_order(*a, **kw)
            raise timeout
    venue, lines = Landed(), []
    grid = Bot(loop_cfg(), LOOP_ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1)
    grid.cycle()                                     # the cycle is not lost
    first = Landed.calls
    rungs = {(o['side'], o['price']) for o in venue.orders}
    assert first and len(rungs) == first == len(venue.orders)   # each rung once
    grid.cycle()
    assert Landed.calls == first, (Landed.calls, first)         # read back, none re-sent
    assert len(venue.orders) == first
