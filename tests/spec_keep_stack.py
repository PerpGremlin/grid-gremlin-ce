"""D160 — a carry bot's leverage changed with its coins kept (H18), the
leverage page's review of it (U135), and the account shown as the exchange
holds it (U136–U138). The engine's half drives a real PortfolioBot against
the suite's fake carry venue (spec_portfolio_bot)."""
import json
import time

from gridgremlin.config import validate_config
from gridgremlin.events import Notifier
from gridgremlin.portfolio import borrowed_split, keep_stack_move
from gridgremlin.portfolio_bot import PortfolioBot
from gridgremlin.portfolio_state import PortfolioState
from gridgremlin.tombstones import Tombstones
from spec_portfolio_bot import ROW, Clock, _legs, _leg_for, _venue


def _row(lev, capital, keep=False):
    half = lev / 2
    return dict(ROW, capital=capital, spot_borrow=True, margin={'spot_leverage': float(lev)},
                hedge={'product': 'inverse', 'ratio': 0.0},             # unhedged: the value moves with the price
                assets=[{'coin': 'BTC', 'weight': half}, {'coin': 'ETH', 'weight': half}],
                risk={'max_weight': max(half, 0.5)}, **({'terms_move': 'keep_stack'} if keep else {}))


def _bot(venue, lines, tmp, clock, row):
    return PortfolioBot(validate_config(json.loads(json.dumps(row))), _legs('none'), venue,
                        Notifier(sink=lines.append), PortfolioState(tmp / 'portfolio_state.json'),
                        tombstones=Tombstones(tmp / 'tombstones.json'), clock=clock, leg_builder=_leg_for)


def _step(clock, venue, s=61):
    clock.t += s
    venue.t_ms = int(clock.t * 1000)


def _world(tmp, price_up=1.1):
    """A 5x row of 100,000 on a 300,000 account: it buys 500,000 of coins on
    the venue's loan, then both coins rise together, so the row's value is
    no longer its capital."""
    lines, clock, venue = [], Clock(), _venue()
    venue.coins['USDT'] = 300000.0
    venue.t_ms = int(clock.t * 1000)
    bot = _bot(venue, lines, tmp, clock, _row(5, 100000))
    bot.cycle()
    _step(clock, venue)
    bot.cycle()
    for k in list(venue.marks):
        venue.marks[k] *= price_up
    _step(clock, venue)
    bot.cycle()
    return venue, lines, clock, bot


def _wallet_quote(venue):
    return venue.coins['USDT']


def spec_H18_keeping_the_coins_moves_value_less_stack_over_the_new_leverage_once():
    """The owner (2026-11-01): change the leverage but keep the coins, "in
    case you just want to free up margin". The money moved is the row's
    value less its stack over the new leverage, booked as capital out;
    nothing is bought or sold; two restarts on the same file move nothing
    more."""
    import tempfile
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp())
    venue, lines, clock, bot = _world(tmp)
    v = bot.portfolio_view
    value, stack, out, contributed, total = (v['value'], v['stack_value'], bot.row['outside_cash'],
                                            bot.row['contributed'], v['total'])
    want = value - stack / 10.0
    assert want > 0 and abs(value - 100000.0) > 1000.0                 # the price moved: value is not the capital
    n = len(venue.orders)
    _step(clock, venue)
    again = _bot(venue, lines, tmp, clock, _row(10, 55555, keep=True))   # the file's capital is the panel's statement
    again.cycle()
    w = again.portfolio_view
    assert len(venue.orders) == n                                        # nothing bought or sold
    assert abs((again.row['outside_cash'] - out) - want) < 1e-6
    assert abs((contributed - again.row['contributed']) - want) < 1e-6
    assert abs(w['value'] - stack / 10.0) < 1e-6 and abs(w['leverage'] - 10.0) < 1e-6
    assert abs(w['total'] - total) < 1e-6                                # never a profit or a loss
    assert again.row['terms_seen']['leverage'] == 10.0
    assert any('the coins kept' in ln and 'freed to the account' in ln for ln in lines)
    booked = {k: again.row[k] for k in ('cash', 'outside_cash', 'contributed')}
    for _ in range(2):                                                   # two restarts on the same file
        _step(clock, venue, 25 * 3600)                                   # past the clock: a tick
        third = _bot(venue, lines, tmp, clock, _row(10, 55555, keep=True))
        third.cycle()
        assert {k: third.row[k] for k in booked} == booked or all(
            abs(third.row[k] - booked[k]) < 1e-6 for k in booked)
        assert len(venue.orders) == n                                    # at its weights: still nothing


def spec_H18_sabotage_were_the_terms_not_learned_with_the_move_a_restart_moves_it_again():
    import tempfile
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp())
    venue, lines, clock, bot = _world(tmp)
    before = bot.row['terms_seen']
    _step(clock, venue)
    b = _bot(venue, lines, tmp, clock, _row(10, 55555, keep=True))
    b.cycle()
    once = b.row['outside_cash']
    b.row['terms_seen'] = before                                         # the guard removed
    b.state.set(b.botid, b.row)
    for k in list(venue.marks):
        venue.marks[k] *= 1.05                                           # the price moves between restarts
    _step(clock, venue)
    c = _bot(venue, lines, tmp, clock, _row(10, 55555, keep=True))
    c.cycle()
    assert c.row['outside_cash'] > once + 1.0                            # the money moved twice


def spec_H18_live_and_restart_book_the_same():
    """Live (D143's path swaps the running bot's terms) or at a restart (a
    new bot on the kept state), the next read books the same move."""
    import tempfile
    from pathlib import Path
    got = []
    for live in (True, False):
        tmp = Path(tempfile.mkdtemp())
        venue, lines, clock, bot = _world(tmp)
        _step(clock, venue)
        new = _row(10, 55555, keep=True)
        if live:
            bot.cfg = dict(validate_config(json.loads(json.dumps(new))), account=bot.cfg.get('account'))
            bot._next_read = 0.0
        else:
            bot = _bot(venue, lines, tmp, clock, new)
        bot.cycle()
        got.append({k: round(bot.row[k], 6) for k in ('cash', 'outside_cash', 'contributed')}
                   | {'terms': bot.row['terms_seen']})
    assert got[0] == got[1], got


def spec_H18_sabotage_with_the_files_capital_as_the_move_the_row_is_not_at_its_leverage():
    """Booked from the file's capital difference, not the read's value, a
    row whose value has moved lands off its new leverage, and its next
    tick trades — the coins were not kept."""
    import tempfile
    from pathlib import Path
    import gridgremlin.portfolio_bot as pb
    tmp = Path(tempfile.mkdtemp())
    venue, lines, clock, bot = _world(tmp)
    saved = pb.keep_stack_move
    pb.keep_stack_move = lambda value, stack, w: 100000.0 - 50000.0     # the guard removed
    try:
        _step(clock, venue)
        b = _bot(venue, lines, tmp, clock, _row(10, 50000, keep=True))
        b.cycle()
        assert abs(b.portfolio_view['leverage'] - 10.0) > 0.5
        n = len(venue.orders)
        _step(clock, venue, 25 * 3600)
        b.cycle()
        assert len(venue.orders) > n
    finally:
        pb.keep_stack_move = saved


def spec_H18_lowering_it_takes_money_in_from_the_account_bounded_by_it():
    """The reverse: lowering the leverage and keeping the coins puts the
    account's own money into the row, at most what the account's own
    holds; short, nothing moves and nothing is planned, said, until it can
    cover it."""
    import tempfile
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp())
    venue, lines, clock, bot = _world(tmp, price_up=1.0)
    v = bot.portfolio_view
    stack, out, contributed = v['stack_value'], bot.row['outside_cash'], bot.row['contributed']
    assert abs(out - 200000.0) < 1.0 and abs(stack - 500000.0) < 1.0
    n = len(venue.orders)
    _step(clock, venue)
    short = _bot(venue, lines, tmp, clock, _row(1.25, 400000, keep=True))   # needs 300,000 of 200,000
    short.cycle()
    assert abs(short.row['outside_cash'] - out) < 1e-6 and short.row['terms_seen']['leverage'] == 5.0
    assert 'needs 299,999.98' in short.portfolio_view['keep_held']   # the stack's own rounding
    _step(clock, venue, 25 * 3600)                                       # past the clock: still nothing
    short.cycle()
    assert len(venue.orders) == n and abs(short.row['contributed'] - contributed) < 1e-6
    assert any("from the account's own, which holds 200,000.00" in ln for ln in lines)
    venue.coins['USDT'] += 200000.0                                      # a deposit, the account's (H13b)
    short.row['outside_cash'] += 200000.0
    _step(clock, venue)
    short.cycle()
    assert abs(short.row['outside_cash'] - 100000.0) < 1.0 and short.row['terms_seen']['leverage'] == 1.25
    assert abs(short.row['contributed'] - contributed - 300000.0) < 1.0 and len(venue.orders) == n
    assert abs(short.portfolio_view['leverage'] - 1.25) < 1e-6


def spec_H18_sabotage_were_money_in_not_bounded_the_row_would_take_what_the_account_has_not():
    import tempfile
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp())
    venue, lines, clock, bot = _world(tmp, price_up=1.0)
    _step(clock, venue)
    b = _bot(venue, lines, tmp, clock, _row(1.25, 400000, keep=True))
    b._covers = lambda outside, moved: True                              # the guard removed
    b.cycle()
    assert b.row['outside_cash'] == 0.0
    assert abs(b.row['cash'] + b.row['outside_cash'] - _wallet_quote(venue)) > 50000.0   # money from nowhere


def spec_H18_a_lowered_capital_without_the_flag_is_still_only_said():
    import tempfile
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp())
    venue, lines, clock, bot = _world(tmp, price_up=1.0)
    n = len(venue.orders)
    _step(clock, venue)
    b = _bot(venue, lines, tmp, clock, _row(6, 50000))
    b.cycle()
    assert any('capital lowered by 50,000.00' in ln for ln in lines)
    assert len(venue.orders) > n                                         # it grows, as before


def spec_H18_the_gate_takes_keep_stack_only_on_a_row_with_a_loan_block():
    from gridgremlin.config import ConfigError
    validate_config(json.loads(json.dumps(_row(5, 1000, keep=True))))
    for bad, frag in ((dict(ROW, terms_move='keep_stack'), "'margin' block"),
                      (dict(_row(5, 1000), terms_move='grow'), "'keep_stack' or absent")):
        try:
            validate_config(json.loads(json.dumps(bad)))
        except ConfigError as e:
            assert frag in str(e), e
            continue
        raise AssertionError('passed')
    assert keep_stack_move(25000.0, 250000.0, 20.0) == 12500.0
    assert keep_stack_move(25000.0, 250000.0, 2.0) == -100000.0


def spec_U137_the_borrowed_splits_into_the_accounts_spare_and_the_venues_loan():
    """The owner (2026-11-01): what was already in the account is shown.
    The row's borrowed stands partly on the account's spare quote (H13) and
    partly on the venue's real loan; the two add up to the borrowed."""
    import tempfile
    from pathlib import Path
    venue, lines, clock, bot = _world(Path(tempfile.mkdtemp()), price_up=1.0)
    v = bot.portfolio_view
    assert abs(v['wallet_quote'] - _wallet_quote(venue)) < 1e-6 and abs(v['venue_loan'] - 200000.0) < 1.0
    assert abs(v['borrowed_spare'] - 200000.0) < 1.0 and abs(v['borrowed_venue'] - 200000.0) < 1.0
    assert abs(v['borrowed_spare'] + v['borrowed_venue'] - v['borrowed']) < 1e-9
    for borrowed, wq in ((400000.0, -200000.0), (400000.0, 50000.0), (400000.0, -500000.0), (0.0, -10.0)):
        spare, real = borrowed_split(borrowed, wq)
        assert abs(spare + real - borrowed) < 1e-9 and spare >= 0 and real >= 0
    assert borrowed_split(400000.0, -500000.0) == (0.0, 400000.0)      # a sibling's loan is not this row's


def spec_U137_sabotage_uncapped_a_siblings_loan_would_not_add_up():
    borrowed, wq = 400000.0, -500000.0
    real = max(-wq, 0.0)                                                 # the cap at the row's borrowed removed
    assert abs((borrowed - real) + real - borrowed) < 1e-9 and borrowed - real < 0   # a negative spare part


def spec_U137_the_carry_card_shows_the_split():
    from panel.card import holdings_table
    v = {'borrowed': 400000.0, 'borrowed_spare': 150000.0, 'borrowed_venue': 250000.0,
         'spot': {}, 'legs': [], 'stables': {}}
    out = holdings_table(v, 'USDT', 0)
    assert "from the account's spare 150,000.00, the exchange's real loan 250,000.00" in out


def _snapshot(d, view, t=None):
    (d / 's').write_text(json.dumps({'t': time.time() if t is None else t, 'equity': 1.0, 'mm_rate': 0.1,
                                     'bots': {'pfocarry': {'alive': True, 'portfolio': view}}}) + '\n')


VIEW = {'stack_value': 500000.0, 'value': 100000.0, 'cash': -400000.0, 'outside_cash': 200000.0,
        'wallet_quote': -200000.0, 'borrowed': 400000.0, 'borrowed_spare': 200000.0,
        'borrowed_venue': 200000.0, 'wallet_coins': {'BTC': 5.0, 'ETH': 80.0},
        'spot': {'BTC': {'coins': 4.5}, 'ETH': {'coins': 80.0}}, 'stables': {'USDT': -200000.0, 'USDC': 12.5}}


def spec_U135_the_leverage_page_offers_keep_the_coins_with_its_figures_before_the_name():
    from spec_setup import _call, _served_fleet
    base, d, close = _served_fleet()
    try:
        f = d / 'f.json'
        fleet = json.loads(f.read_text())
        fleet['bots'].append(dict(_row(5, 100000), name='carry'))
        f.write_text(json.dumps(fleet))
        door = _call(base, '/edit?fleet=0&bot=pfocarry')
        assert 'name="how" value="keep"' in door and 'name="how" value="grow" checked' in door
        form = {'fleet': '0', 'orig': 'pfocarry', 'spot': '10', 'how': 'keep'}
        assert 'no snapshot' in _call(base, '/lever', form) or 'not reviewed' in _call(base, '/lever', form)
        _snapshot(d, VIEW, t=time.time() - 3600)
        assert '60 minutes old' in _call(base, '/lever', form)              # stale: not offered
        _snapshot(d, VIEW)
        review = _call(base, '/lever', form)
        import html
        head = html.unescape(review.split('name="confirm"')[0])           # all of it before the typed name
        assert 'keeping the coins' in head and '500,000.00 USDT</td><td>500,000.00 USDT' in head
        assert '100,000.00 USDT</td><td>50,000.00 USDT' in head            # the bot's money
        assert 'Money moved: <b>50,000.00 USDT</b> from the bot to the account' in head
        assert '200,000.00 USDT</td><td>250,000.00 USDT' in head            # the account's spare after
        assert 'margin floor read as they did' in head
        assert "the exchange's real loan</td><td>200,000.00 USDT</td><td>200,000.00 USDT" in head   # U137
        assert "from the account's spare USDT</td><td>200,000.00 USDT</td><td>250,000.00 USDT" in head
        assert 'the account, as the exchange holds it' in head             # U136
        assert "0.5 BTC in the wallet are not the bot's: it leaves them alone" in head
        assert "12.50 USDC in the wallet are not the bot's" in head
        assert json.loads(f.read_text()) == fleet                          # a review writes nothing
        seen = review.split('name="seen" value="')[1].split('"')[0].replace('&quot;', '"')
        ok = _call(base, '/lever', dict(form, seen=seen, keep_money='50000.0', confirm='pfocarry'))
        assert 'pfocarry: written' in ok and 'the coins stay' in ok
        row = json.loads(f.read_text())['bots'][1]
        assert row['terms_move'] == 'keep_stack' and row['capital'] == 50000.0
        assert row['margin']['spot_leverage'] == 10
        grow = _call(base, '/lever', {'fleet': '0', 'orig': 'pfocarry', 'spot': '8', 'how': 'grow'})
        seen = grow.split('name="seen" value="')[1].split('"')[0].replace('&quot;', '"')
        _call(base, '/lever', {'fleet': '0', 'orig': 'pfocarry', 'spot': '8', 'how': 'grow',
                               'seen': seen, 'confirm': 'pfocarry'})
        assert 'terms_move' not in json.loads(f.read_text())['bots'][1]    # growing clears it
        low = _call(base, '/lever', {'fleet': '0', 'orig': 'pfocarry', 'spot': '1.25', 'how': 'keep'})
        assert 'needs 300,000.00' in low and 'holds 200,000.00' in low      # refused in plain words
    finally:
        close()


def _contract(age_s=5, **fig):
    return {'generated_ms': int((time.time() - age_s) * 1000), 'account': {'bybit': dict(
        tier='demo', wallet={'BTC': {'balance': 0.5, 'usd': 35000.0, 'borrow': 0.0, 'interest': 0.0, 'upl': 0.0},
                             'USDT': {'balance': -1200.0, 'usd': -1200.0, 'borrow': 1200.0, 'interest': 0.42,
                                      'upl': 0.0}},
        available=8765.43, **fig)}}


def spec_U138_the_account_lines_are_the_readouts_own_numbers():
    """The owner (2026-11-01): "display what is in the asset balance and
    floating debt … what the available balance to trade with is"."""
    from gridgremlin.exchange.bybit.truth import account_figures, wallet_coins
    from panel.strip_view import account_lines
    acct = {'totalMarginBalance': '9000', 'totalAvailableBalance': '8765.43',
            'coin': [{'coin': 'BTC', 'walletBalance': '0.5', 'usdValue': '35000', 'borrowAmount': '0',
                      'accruedInterest': ''},
                     {'coin': 'USDT', 'walletBalance': '-1200', 'usdValue': '-1200', 'borrowAmount': '1200',
                      'accruedInterest': '0.42'},
                     {'coin': 'ETH', 'walletBalance': '0', 'usdValue': '0', 'borrowAmount': '0'}]}
    assert wallet_coins(acct) == _contract()['account']['bybit']['wallet']

    class C:
        def get(self, path, params, signed=False):
            return {'list': []}

        def wallet_balance(self):
            return {'list': [acct]}
    fig = account_figures(C())
    assert fig['available'] == 8765.43 and fig['wallet'] == wallet_coins(acct)
    out = account_lines(_contract())
    assert 'Demo Trading' in out and 'BTC 0.5 (≈ 35,000.00 USDT)' in out
    assert 'floating debt: <span class="dim">USDT 1,200 (+ 0.42 interest)</span>' in out
    assert 'available to trade: <b>8,765.43 USDT</b>' in out
    for stale in (_contract(age_s=3600), None, {'generated_ms': int(time.time() * 1000), 'account': {'bybit': None}}):
        got = account_lines(stale)
        assert got.count('not read') == 3, got
    hl = account_lines({'generated_ms': int(time.time() * 1000),
                        'account': {'hyperliquid': {'tier': 'testnet', 'available': 50.0}}})
    assert 'balances: <span class="dim">not read' in hl and '50.00 USDT' in hl


def spec_U138b_a_balance_is_worth_its_balance_and_dust_folds():
    """U138b (the owner's account box, 2026-11-01: "USDT 247,711.5 (≈ 236,773.34
    USDT)"): Bybit's usdValue is a coin's equity — its balance plus the open
    P&L of the perps settled in it. The balance is said at its own worth, the
    open P&L apart; coins under 1 USDT owing nothing fold into a count.
    Sabotage: the equity shown as the balance's worth is caught."""
    from gridgremlin.exchange.bybit.truth import wallet_coins
    from panel.strip_view import account_lines
    acct = {'coin': [{'coin': 'USDT', 'walletBalance': '1000', 'usdValue': '900', 'unrealisedPnl': '-100'},
                     {'coin': 'ADA', 'walletBalance': '0.0077', 'usdValue': '0.003'},
                     {'coin': 'SOL', 'walletBalance': '0.00004', 'usdValue': '0.008'},
                     {'coin': 'BTC', 'walletBalance': '0.1', 'usdValue': '7000'}]}
    w = wallet_coins(acct)
    assert w['USDT']['upl'] == -100.0
    out = account_lines({'generated_ms': int(time.time() * 1000),
                         'account': {'bybit': {'tier': 'demo', 'wallet': w, 'available': 1.0}}})
    assert 'USDT 1,000 (≈ 1,000.00 USDT)' in out, out
    assert '900.00' not in out                                   # never the equity as the worth
    assert 'open P&amp;L on its perps: <span class="dim">USDT -100.00' in out
    assert 'BTC 0.1 (≈ 7,000.00 USDT)' in out
    assert 'ADA' not in out and 'SOL' not in out and '+ 2 coins under 1 USDT' in out


def spec_U138_sabotage_with_no_age_limit_a_day_old_readout_reads_as_now():
    import panel.strip_view as sv
    saved = sv.READOUT_STALE_S
    sv.READOUT_STALE_S = 1e12                                            # the guard removed
    try:
        assert 'not read' not in sv.account_lines(_contract(age_s=86400))
    finally:
        sv.READOUT_STALE_S = saved
    assert sv.account_lines(_contract(age_s=86400)).count('not read') == 3


def spec_U138_every_setup_form_shows_the_account_lines_beside_its_money():
    from spec_setup import _call, _served_fleet
    base, d, close = _served_fleet()
    try:
        for path in ('/setup', '/setup?adv=grid', '/setup?adv=carry'):
            page = _call(base, path)
            assert 'the account now' in page and 'available to trade' in page, path
    finally:
        close()
