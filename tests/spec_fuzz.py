"""A stdlib fuzz over the ladder arithmetic (the 2026-10-08 audit, gap (b)):
thousands of random instruments, prices, holdings and lots against the
invariants the specs state one hand-picked case at a time. Seeded, so a
failure reproduces exactly; the seed and the case are in the message."""
import random
from decimal import Decimal

from gridgremlin.adapters import LinearAdapter
from gridgremlin.ladder import (exit_ladder, exit_ladder_sized, grid_rungs, lots_free,
                                lots_held)

STEPS = (1e-8, 1e-6, 0.0001, 0.001, 0.01, 0.1, 1.0, 10.0, 0.005, 0.05, 0.5, 5.0, 0.0002, 0.025)
CASES = 2500


def _adapter(rng):
    step, tick = rng.choice(STEPS), rng.choice(STEPS)
    min_qty = step * rng.choice((1, 1, 2, 10))
    return LinearAdapter({'symbol': 'FUZZUSDT', 'qty_step': step, 'price_tick': tick,
                          'min_qty': min_qty, 'min_notional': rng.choice((None, 1.0, 5.0)),
                          'settle_coin': 'USDT'})


def _steps(x, step):
    """x in whole steps, exactly, or None when x is not on the step."""
    q = Decimal(str(x)) / Decimal(str(step))
    return int(q) if q == q.to_integral_value() else None


def spec_A2_fuzz_rounding_floors_quantities_rounds_prices_and_never_writes_exponents():
    rng = random.Random(20261010)
    for n in range(CASES):
        a = _adapter(rng)
        q = rng.uniform(0, 1000) * rng.choice((1e-6, 1e-3, 1, 1e3))
        p = rng.uniform(1e-6, 1e6)
        rq = a.round_qty(q)
        case = f'case {n}: step {a.qty_step} tick {a.price_tick} q {q!r} p {p!r}'
        assert _steps(rq, a.qty_step) is not None, case                   # on the step
        assert Decimal(str(rq)) <= Decimal(str(q)), case                  # floors: never more than asked
        assert Decimal(str(q)) - Decimal(str(rq)) < Decimal(str(a.qty_step)), case
        nq = a.nearest_qty(q)
        assert abs(Decimal(str(nq)) - Decimal(str(q))) <= Decimal(str(a.qty_step)) / 2, case
        rp = a.round_price(p)
        assert _steps(rp, a.price_tick) is not None, case
        assert abs(Decimal(str(rp)) - Decimal(str(p))) <= Decimal(str(a.price_tick)) / 2, case
        for s in (a.fmt_qty(q), a.fmt_price(p)):
            assert 'e' not in s.lower() and s.strip() == s, (case, s)     # plain venue strings
        assert Decimal(a.fmt_qty(q)) == Decimal(str(rq)), case            # the string is the rounded value


def spec_G8_fuzz_the_exit_ladders_cover_the_whole_holding_in_whole_steps():
    """For any holding, rungs and lot: the exits sum to exactly the holding
    in whole steps — no step lost, none invented — every share is whole
    steps, no rung twice, and nothing exceeds what is held."""
    rng = random.Random(81)
    for n in range(CASES):
        a = _adapter(rng)
        step = a.qty_step
        held_steps = rng.randint(1, 5000)
        noise = rng.choice((0.0, 1e-12, -1e-12, step * 1e-9))           # float dust on a holding
        sellable = float(Decimal(str(step)) * held_steps) + noise
        k = rng.randint(1, 12)
        base = rng.uniform(1, 1e5)
        exits = [(i, a.round_price(base * (1 + 0.003 * (i + 1)))) for i in range(k)]
        lot_q = float(Decimal(str(step)) * rng.randint(1, max(1, held_steps // max(1, k) + 2)))
        case = f'case {n}: step {step} held_steps {held_steps} noise {noise} k {k} lot {lot_q}'
        for out in (exit_ladder(exits, sellable, lot_q, a),
                    exit_ladder_sized([(i, p, lot_q) for i, p in exits], sellable, a)):
            if not out:
                # nothing kept only when no single rung could take a share at the minimum
                assert not any(a.meets_minimum(sellable, p) for _, p in exits), case
                continue
            shares = [_steps(q, step) for _, _, q in out]
            assert all(s is not None and s > 0 for s in shares), (case, out)
            assert sum(shares) == held_steps, (case, sum(shares), out)
            assert len({i for i, _, _ in out}) == len(out), (case, out)


def spec_G1_fuzz_grid_rungs_are_ordered_on_whole_ticks_inside_the_range():
    from gridgremlin.config import validate_config
    rng = random.Random(1)
    for n in range(CASES // 5):
        a = _adapter(rng)
        lower = rng.uniform(1, 1e5)
        upper = lower * rng.uniform(1.01, 2.0)
        rungs = rng.randint(2, 120)
        spacing = rng.choice(('fixed', 'percent'))
        try:
            cfg = validate_config({'market_type': 'linear', 'symbol': 'FUZZUSDT', 'side': 'long',
                                   'capital': 1000.0, 'leverage': 2, 'lower': lower, 'upper': upper,
                                   'rungs': rungs, 'spacing_type': spacing})
        except Exception:                                                   # noqa: BLE001
            continue                                                        # the validator refused: not a ladder
        ps = grid_rungs(cfg, a)
        case = f'case {n}: tick {a.price_tick} {lower}..{upper} x{rungs} {spacing}'
        assert len(ps) == rungs, case
        assert all(b >= p for p, b in zip(ps, ps[1:])), (case, ps[:5])
        assert all(_steps(p, a.price_tick) is not None for p in ps), case
        assert ps[0] >= lower - a.price_tick and ps[-1] <= upper + a.price_tick, case


def spec_G7_G10_fuzz_lots_are_counted_whole_and_headroom_is_never_negative():
    rng = random.Random(7)
    for n in range(CASES):
        lot_q = rng.uniform(1e-6, 100)
        k = rng.randint(0, 200)
        held = lot_q * k
        assert lots_held(held, lot_q) == k, (n, lot_q, k)                  # whole lots, exactly
        assert lots_held(held + lot_q * 0.01, lot_q) == k + 1, (n, lot_q, k)   # any part of a lot is held
        cap = rng.choice((None, rng.uniform(0, 1000)))
        free = lots_free(cap, rng.uniform(-500, 500), lot_q)
        assert free is None if cap is None else free >= 0, (n, cap, free)
