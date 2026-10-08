# A running fleet takes an edited row's TERMS without a restart (SPEC F12,
# D49). The fleet file is the owner's memory and the panel writes it; until
# now every write waited for a restart, which restarts every bot. Now the
# engine watches the file and applies what can be applied in place:
# - HOT keys: what a bot does with its position — leverage, investment,
#   stops and limits, take profit, trailing, repeat, cooldowns. The bot's
#   config is swapped; its ladder is re-planned from the next cycle.
# - COLD keys stay a restart: what a bot IS (identity, strategy, venue),
#   its lattice (range, levels, spacing, weights, slide, seed, floor) and
#   a martingale's ladder (sizes, deviations, depth) — a change there
#   re-identifies every resting order and every held lot.
# Leverage goes to the venue first: Bybit's set-leverage, one leverage per
# market (the legs' max, as at build); Hyperliquid's updateLeverage, one per
# coin, as the build asserts it (F12 amended 2026-10-04: the ladder once
# resized to 25x on a venue still margining at 5x, and every rung was
# refused for margin). A refusal is said in the venue's own words and
# NOTHING of that row is applied.
import json
import os
from pathlib import Path

from .apply import make_botid
from .config import market_rows, ConfigError, validate_fleet
from .exchange.errors import VenueError

HOT_KEYS = frozenset((
    'leverage', 'capital', 'stop', 'max_loss', 'max_loss_since',
    'max_rounds', 'max_rounds_since', 'max_hold_seconds', 'repeat',
    'repeat_cooldown_seconds', 'stop_cooldown_seconds', 'reinvest',
    'trailing_stop_pct', 'trailing_activation_pct', 'take_profit_avg_pct',
    'take_profit_tranches', 'breakeven_ladder', 'breakeven_offset_pct',
    'place_within_pct',
    'start_order_type', 'start_order_requote_seconds',
    'start_order_expire_seconds', 'split_hysteresis_rungs',
    'min_position_base', 'max_position_base'))
CARRIED = ('funding_interval_minutes', '_tier_mm_rate')   # the build's own
SETTLE_SECONDS = 1.5          # an atomic write lands whole; wait it out


def _user_keys(cfg):
    """The row as written, minus the engine's derived values and notes."""
    derived = {'ladder_notional', 'ladder_total_notional',
               'max_rounds_since_ms', 'max_loss_since_ms'} | set(CARRIED)
    return {k: v for k, v in cfg.items()
            if k not in derived and not k.startswith('_')}


class FleetWatch:
    """Notices the fleet file changing (by mtime, one stat per cycle) and
    applies the hot terms of changed rows to the running bots."""

    def __init__(self, fleet_path, bots, clients, notifier):
        self.path = Path(fleet_path)
        self.bots, self.clients, self.notifier = bots, clients, notifier
        self.mtime = self._mtime()

    def _mtime(self):
        try:
            return os.stat(self.path).st_mtime
        except OSError:
            return None

    def poll(self, now):
        m = self._mtime()
        if m is None or m == self.mtime or now - m < SETTLE_SECONDS:
            return None
        self.mtime = m
        return self.apply()

    def apply(self):
        """Returns {botid: 'applied' | 'refused' | 'restart'} for changed
        rows — the specs' view; the notifier carries the words."""
        try:
            fleet = validate_fleet(json.loads(self.path.read_text()))
        except (ConfigError, ValueError, OSError) as e:
            self.notifier.event('warn', 'fleet',
                                f'the fleet file changed but is refused ({e}) '
                                '— running on with the terms it has (F12)', urgent=True)
            return {}
        rows = {make_botid(c['market_type'], c['symbol'], c['side']): c
                for c in market_rows(fleet)}
        out = {}
        by_id = {b.botid: b for b in self.bots}
        for botid in rows:
            if botid not in by_id:
                self.notifier.event('warn', 'fleet',
                                    f'{botid}: new in the file — it starts at '
                                    'the next restart (F12)', urgent=True)
        for bot in self.bots:
            new = rows.get(bot.botid)
            if new is None:
                self.notifier.event('warn', bot.botid,
                                    'removed from the file — nothing changes '
                                    'until the next restart (F12)', urgent=True)
                continue
            old_u, new_u = _user_keys(bot.cfg), _user_keys(new)
            changed = {k for k in set(old_u) | set(new_u)
                       if old_u.get(k) != new_u.get(k)}
            if not changed:
                continue
            cold = sorted(changed - HOT_KEYS)
            if cold:
                self.notifier.event(
                    'warn', bot.botid,
                    f'the file changed {", ".join(cold)} — that re-identifies '
                    'the ladder, so it waits for a restart; nothing of this '
                    'row is applied (F12)', urgent=True)
                out[bot.botid] = 'restart'
                continue
            if 'leverage' in changed:
                why = self._set_leverage(bot, new)
                if why:
                    self.notifier.event(
                        'warn', bot.botid,
                        f"leverage {bot.cfg['leverage']:g} -> {new['leverage']:g} "
                        f'REFUSED by the venue: {why} — nothing of this row is '
                        'applied (F12)', urgent=True)
                    out[bot.botid] = 'refused'
                    continue
            def say(v):
                return f'{v:g}' if isinstance(v, float) else repr(v)
            said = ', '.join(f'{k} {say(old_u.get(k))} -> {say(new_u.get(k))}'
                             for k in sorted(changed))
            for k in CARRIED:
                if k in bot.cfg:
                    new[k] = bot.cfg[k]
            bot.cfg = new
            if hasattr(bot, '_loss_cache'):
                bot._loss_cache = None        # X14: the moment may have moved
            self.notifier.event('repeat', bot.botid,
                                f'applied live from the file: {said} (F12)')
            out[bot.botid] = 'applied'
        return out

    def _set_leverage(self, bot, new):
        """The venue first. None on success, else the venue's words."""
        cfg = bot.cfg
        if cfg['venue'] == 'hyperliquid':
            # one leverage per coin, set the way the build asserts it; the
            # venue's refusal (margin, its cap) leaves the row as it was
            client = self.clients.get('hyperliquid')
            if client is None:
                return 'no Hyperliquid client to set leverage on'
            try:
                client.update_leverage(client._entry(cfg['symbol'])[0],
                                       int(new['leverage']))
            except (VenueError, OSError) as e:
                return str(e)
            return None
        if cfg['market_type'] == 'spot':
            return None
        client = self.clients.get(cfg['venue'])
        if client is None or not hasattr(client, 'set_leverage'):
            return None
        # one leverage per market on Bybit: the legs' max, as at build
        legs = [b for b in self.bots if b.cfg['venue'] == cfg['venue']
                and b.cfg['symbol'] == cfg['symbol'] and b is not bot]
        want = max([new['leverage']] + [b.cfg['leverage'] for b in legs])
        try:
            client.set_leverage(cfg['market_type'], cfg['symbol'], want)
        except (VenueError, OSError) as e:
            return str(e)
        if legs and want != new['leverage']:
            self.notifier.event('warn', bot.botid,
                                f'the venue holds one leverage for {cfg["symbol"]} '
                                f'— set to {want:g}, the legs\' highest; '
                                'sizes follow each row\'s own figure')
        return None
