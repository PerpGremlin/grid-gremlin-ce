"""The fee table (C10, audit 2026-10-09): every fee constant the engine,
the rehearsal and the backtests assume, in one place. Rates are fractions
per side; the floors are what an exit must clear (G6)."""

BYBIT_MAKER = 0.0002         # per side, the base tier
BYBIT_TAKER = 0.00055
BYBIT_SPOT_TAKER = 0.001     # spot, per side — what a market rebalance pays (H7)

FEE_FLOOR_PCT = 0.001        # perps: ~0.02-0.055%/side, round trip covered
SPOT_FEE_FLOOR_PCT = 0.0025  # spot: ~0.1%/side — a 0.001 floor sold at a LOSS


def fee_floor_for(market_type):
    """G6: the floor is the venue's ROUND TRIP plus margin — spot charges
    about ten times a perp per side, so one constant cannot serve both."""
    return SPOT_FEE_FLOOR_PCT if market_type == 'spot' else FEE_FLOOR_PCT
