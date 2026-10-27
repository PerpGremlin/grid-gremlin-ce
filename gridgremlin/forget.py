# One bot's local state forgotten (SPEC X16): when its row leaves a fleet
# or a new row takes its name. A bot's name is its coin, side and kind, so
# a new bot of the same name read every fact the old one left: its slide
# offset (D149, the owner's grids of 2026-10-22), a retire request (D145)
# its first cycle would act on, a tombstone that stands it down, the kept
# ledger's fills (R18c), a carry row's book and loan (H2), and an ended
# trade's row. Every removal path forgot a different few of these; this is
# the one list, and spec_X16 walks every kind so a new one cannot be missed.
#
# Never a write on the venue, and never a live trade: a trade whose bot has
# not stood down (no tombstone) keeps its row — its position is still open.
import time

FORGETS = ('slide_state', 'retire_requests', 'tombstones', 'kept_fills',
           'portfolio_state', 'trades')


def forget_bot(fleet_path, fleet_raw, botid, at_ms=None):
    """Every local fact under `botid` forgotten. Returns the kinds that
    held something ({kind: what}); a live trade's row is said, not cleared."""
    from .durable import state_path
    from .kept_fills import cut
    from .portfolio_state import PortfolioState
    from .retire import drop, requests_path
    from .slide_state import forget as slide_forget
    from .tombstones import Tombstones, remove
    from .trades import TradeError, clear_trade, trade_status
    out = {}
    fleet_path = str(fleet_path)
    tpath = state_path(fleet_path, fleet_raw, 'tombstones')
    # the trade first: its tombstone is what says it ended
    try:
        status = trade_status(state_path(fleet_path, fleet_raw, 'trades'), botid,
                              Tombstones(str(tpath)))
    except TradeError:
        status = None
    if status == 'ended':
        if clear_trade(state_path(fleet_path, fleet_raw, 'trades'), botid) is not None:
            out['trades'] = 'row cleared'
    elif status == 'live':
        out['trades'] = 'a live trade — its row kept'
    if slide_forget(state_path(fleet_path, fleet_raw, 'slide_state'), botid) is not None:
        out['slide_state'] = 'window home'
    if requests_path(fleet_path).exists() and drop(requests_path(fleet_path), botid):
        out['retire_requests'] = 'request dropped'
    if tpath.exists() and remove(tpath, botid) is not None:
        out['tombstones'] = 'tombstone removed'
    pp = state_path(fleet_path, fleet_raw, 'portfolio_state')
    if pp.exists():
        ps = PortfolioState(str(pp))
        if ps.get(botid):
            ps.forget(botid)
            out['portfolio_state'] = 'book forgotten'
    if cut(fleet_path, [botid], time.time() * 1000 if at_ms is None else at_ms) is not None:
        out['kept_fills'] = 'record cut'
    return out
