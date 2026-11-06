"""The bot's constants (E9, G26, G15, B5, B7, M12, X11, X12): one place, imported by
the bot and its mixins."""
FLAT_CONFIRMATIONS = 3  # E9: consecutive flat reads before standing down
RUNGS_LAG_SECONDS = 60.0    # G26: how long both sides wait for the fill list
                            # (a time, not cycles: polls differ by venue)
FROZEN_REMIND_SECONDS = 6 * 3600.0   # G28 (D158): a freeze past the wait is
                                     # said again this often while it lasts
FROZEN_WHY_CHARS = 160      # G28: the exchange's error, cut to this for the
                            # card and the phone
DEFER_ESCALATE_CYCLES = 60  # G15: withheld-exit cycles before the operator
                            # is told the cost is not reconstructable
FLAP_LIMIT = 3          # B5: strikes before a (rung, side) cools
FLAP_COOLDOWN = 60.0
BACKOFF_BASE = 30.0     # B7: margin backoff, doubling to the ceiling
BACKOFF_CEILING = 300.0
HISTORY_WINDOW_DAYS = 30    # M12/M13: the venue-practical fills lookback
VENUE_STOP = 'the venue-held stop'    # X12: how a round ended (M14)
STOP_RUNG = 99    # X11: the link rung of a stop that ends the ROUND — no
CASH_LOG_OVERLAP_MS = 10 * 60 * 1000   # D169: the cash log is re-read this far back
FILL_FEE_SLACK = 0.005                 # D169: a fill's fee in the coin, at most, of its size
FUNDING_HOURS_UTC = (0, 8, 16)         # D169: Bybit's inverse funding settles on these hours
FUNDING_WINDOW_SECONDS = 300.0         # D169: a move begun this soon after one is funding's
FUNDING_LAG_SECONDS = 300.0            # D169: ...and waits this long for its log row (measured
                                       # 2026-11-05: the wallet at +5 s, the row at +91 s, +112 s)
ROUND_REACH_DAYS = 365      # M31: how far back an open DCA round's base is sought,
                            # past HISTORY_WINDOW_DAYS, once per process
