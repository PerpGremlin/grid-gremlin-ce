"""The bot's constants (E9, G26, G15, B5, B7, M12, X11, X12): one place, imported by
the bot and its mixins."""
FLAT_CONFIRMATIONS = 3  # E9: consecutive flat reads before standing down
RUNGS_LAG_CYCLES = 20       # G26: cycles the exit side waits for the fill list
DEFER_ESCALATE_CYCLES = 60  # G15: withheld-exit cycles before the operator
                            # is told the cost is not reconstructable
FLAP_LIMIT = 3          # B5: strikes before a (rung, side) cools
FLAP_COOLDOWN = 60.0
BACKOFF_BASE = 30.0     # B7: margin backoff, doubling to the ceiling
BACKOFF_CEILING = 300.0
HISTORY_WINDOW_DAYS = 30    # M12/M13: the venue-practical fills lookback
VENUE_STOP = 'the venue-held stop'    # X12: how a round ended (M14)
STOP_RUNG = 99    # X11: the link rung of a stop that ends the ROUND — no
