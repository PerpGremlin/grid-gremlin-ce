# Trades (SPEC L, D81): a single trade — long or short, an entry, a take
# profit, an optional stop and trailing — is a one-round DCA row with no
# safety orders (`trade: true`). It lives in the fleet's trades file
# (logs/trades-<fleet>.json, beside the tombstones), not in the tracked
# config, and a running fleet builds a new one within a cycle: no restart.
# The owner's door is this module's CLI (and, next, the panel's form); the
# agent's door (D80) will write the same rows through the same validator.
#
#   python3 -m gridgremlin.trade <fleet.json> open long BTCUSDT --capital 500 \
#       --leverage 5 --tp 1.5 [--stop 2] [--trail 0.5 --trail-from 1] [--maker]
#   python3 -m gridgremlin.trade <fleet.json> list
#   python3 -m gridgremlin.trade <fleet.json> clear <botid>    # a finished trade
import json
from pathlib import Path

from .apply import make_botid
from .config import ConfigError, market_rows, validate_config, validate_fleet
from .durable import locked, state_path, write_json
from .fmt import utc_stamp


class TradeError(Exception):
    pass


def trades_path(fleet_path, fleet_raw):
    return state_path(fleet_path, fleet_raw, 'trades')


def _read(path):
    try:
        rows = json.loads(Path(path).read_text() or '[]')
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        raise TradeError(f'{path}: unreadable ({e}) — fix or move it, deliberately; '
                         'refusing rather than drop live trades') from e
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise TradeError(f'{path}: malformed — a list of trade rows')
    return rows


META = ('opened', 'by', 'reason', 'confidence')      # the trade's own record, not the bot's terms


def validate_trade(row, where='trade'):
    """A trade row through the bot validator, marked a trade (D81); its
    record (when it opened, who opened it, why) rides beside the terms."""
    if not isinstance(row, dict):
        raise ConfigError(f'{where}: a trade is an object')
    if row.get('strategy', 'martingale') != 'martingale':
        raise ConfigError(f"{where}: a trade is a one-round DCA row — strategy 'martingale' (D81)")
    terms = {k: v for k, v in row.items() if k not in META}
    cfg = validate_config(dict(terms, strategy='martingale', trade=True), where)
    cfg['_record'] = {k: row[k] for k in META if k in row}
    return cfg


def load_trades(path):
    """The trades file's rows, each validated; a row that does not validate
    is named and set aside, the rest stand (D52's shape)."""
    out, refused = [], []
    for i, row in enumerate(_read(path)):
        try:
            out.append(validate_trade(row, f'trades[{i}]'))
        except ConfigError as e:
            refused.append((i, str(e)))
    return out, refused


def _botid(cfg):
    return make_botid(cfg['market_type'], cfg['symbol'], cfg['side'])


def add_trade(path, fleet_cfg_rows, row):
    """Validate a new trade against the fleet's rows and the trades already
    open, then append it under the file's lock. A market and side another
    row holds is refused: the venue keeps one position per side of a
    market per account, so two rows there would be one position (I2)."""
    cfg = validate_trade(row)
    botid = _botid(cfg)
    taken = {make_botid(c['market_type'], c['symbol'], c['side'])
             for c in fleet_cfg_rows if c.get('strategy') != 'portfolio'}
    if botid in taken:
        raise TradeError(f'{botid}: a bot of this fleet already trades {cfg["symbol"]} '
                         f'{cfg["side"]} — one position per side of a market per account (I2)')
    with locked(path):
        rows = _read(path)
        for r in rows:
            try:
                if _botid(validate_trade(r)) == botid:
                    raise TradeError(f'{botid}: a trade on {cfg["symbol"]} {cfg["side"]} is '
                                     'already in the file — clear it first when it has finished')
            except ConfigError:
                continue
        clean = {k: v for k, v in row.items() if k not in ('strategy', 'trade')}
        clean['opened'] = utc_stamp()
        clean.setdefault('by', 'owner')
        rows.append(clean)
        write_json(path, rows)
    return botid


def clear_trade(path, botid, tombstones_path=None):
    """Remove one trade row (and its tombstone, which only kept a finished
    trade from starting again). Returns the row removed, or None."""
    with locked(path):
        rows = _read(path)
        keep, gone = [], None
        for r in rows:
            try:
                same = _botid(validate_trade(r)) == botid
            except ConfigError:
                same = False
            if same and gone is None:
                gone = r
            else:
                keep.append(r)
        if gone is not None:
            write_json(path, keep)
    if gone is not None and tombstones_path is not None:
        from .tombstones import remove
        remove(tombstones_path, botid)
    return gone


class TradeWatch:
    """L1: notices the trades file changing (by mtime, one stat a cycle) and
    builds each new trade into the running fleet. `build(cfg)` is the
    fleet's own builder (main.build_market_bot on the venue's client) and
    returns (bot, identity); a trade on a venue the fleet has no client for,
    or an identity the fleet already holds, is refused by name."""

    def __init__(self, path, bots, identities, build, notifier, clients):
        self.path, self.bots, self.identities = Path(path), bots, identities
        self.build, self.notifier, self.clients = build, notifier, clients
        self.mtime = self._mtime()

    def _mtime(self):
        try:
            return self.path.stat().st_mtime
        except OSError:
            return None

    def poll(self, now=None):
        m = self._mtime()
        if m is None or m == self.mtime:
            return None
        self.mtime = m
        return self.apply()

    def apply(self):
        try:
            rows, refused = load_trades(self.path)
        except TradeError as e:
            self.notifier.event('warn', 'fleet', f'{e} (L1)', urgent=True)
            return {}
        for i, why in refused:
            self.notifier.event('warn', 'fleet', f'trade {i} refused: {why} (L1)', urgent=True)
        have = {b.botid for b in self.bots}
        held = {ident for _, ident in self.identities}
        out = {}
        for cfg in rows:
            botid = _botid(cfg)
            if botid in have:
                continue
            if cfg['venue'] not in self.clients:
                self.notifier.event('warn', botid, f"a trade on {cfg['venue']}, which this fleet "
                                                   'does not trade — refused (L1)', urgent=True)
                out[botid] = 'refused'
                continue
            try:
                bot, ident = self.build(cfg)
            except Exception as e:                               # noqa: BLE001
                self.notifier.event('warn', botid, f'trade not built: {type(e).__name__}: {e} (L1)',
                                    urgent=True)
                out[botid] = 'refused'
                continue
            if ident in held:
                self.notifier.event('warn', botid, 'its position is another bot\'s (I2) — refused (L1)',
                                    urgent=True)
                out[botid] = 'refused'
                continue
            self.bots.append(bot)
            self.identities.append((botid, ident))
            held.add(ident)
            self.notifier.event('start', botid,
                                f"trade opened live: {cfg['side']} {cfg['symbol']} "
                                f"{cfg['capital']:g} at {cfg['leverage']:g}x (L1)")
            out[botid] = 'built'
        return out


def with_trades(fleet_path, fleet):
    """L5: the validated fleet with its open trades among its rows, so every
    reader — the readout and its cards, the kept ledger, the digest, the
    market readings, the close command — sees a trade as the bot it is. A
    trades file that cannot be read adds nothing and is said once by the
    engine, which refuses to build beside it (L1)."""
    try:
        trades, _ = load_trades(state_path(fleet_path, fleet, 'trades'))
    except TradeError:
        return fleet
    have = {make_botid(c['market_type'], c['symbol'], c['side'])
            for c in fleet['bots'] if c.get('strategy') != 'portfolio'}
    extra = [dict(t, account=fleet['account']) for t in trades if _botid(t) not in have]
    return dict(fleet, bots=list(fleet['bots']) + extra) if extra else fleet


def fleet_rows(fleet_path):
    """The fleet's own grid and DCA rows, validated, for the collision check."""
    fleet = validate_fleet(json.loads(Path(fleet_path).read_text()))
    return fleet, market_rows(fleet)
