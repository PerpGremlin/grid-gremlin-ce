# Retire a whole fleet, and clear it (D149).
#   python3 -m gridgremlin.retire_all <fleet.json> [--dry] [--sell] [--clear]
#
# The owner (2026-10-22): "we should set up an all clear/retire so we can
# wipe the UI with nothing." With the fleet stopped, every row is retired
# the way one is (X15c): a grid or DCA row by retire_bot (tombstone, its
# orders cancelled, its position closed); a spot row tombstoned and its
# orders cancelled (its coins are the wallet's, see --sell); a portfolio
# row flattened, every leg together (H4); each open trade (D81) as the
# row it is. Then the venue is read back, row by row and a portfolio's
# perps leg by leg. --sell sells every coin on the Bybit account but USDT
# (dust under the venue's minimum stays; Hyperliquid's USDC is its cash).
# --clear, once the read-back is flat, takes every row out of the fleet
# file with its watchdog line, and every row and trade's local state with
# it (X16), so the page shows nothing; an empty fleet is a file the engine
# refuses to run until a bot is added. Not flat, nothing is cleared; a row
# the engine refuses (D52) is never retired, so it refuses the clear.
#
# Narrow like retire: never mainnet, never beside its running fleet, and
# the fleet's prelock held throughout so it cannot start meanwhile (F3).
# --dry says what it would do and does nothing. Prints one JSON object;
# a refusal is {"refused": "..."}.
import json
import time
import sys
from decimal import Decimal
from pathlib import Path

from .apply import row_botid, rung_of
from .config import ConfigError, market_rows, validate_fleet

REASON = 'retired with its whole fleet (D149)'


def kind_of(row):
    """What retiring this row means: portfolio, spot or perp."""
    if row.get('strategy') == 'portfolio':
        return 'portfolio'
    return 'spot' if row.get('market_type') == 'spot' else 'perp'


def clear_rows(fleet_raw, wd_raw, gone):
    """The fleet file and its watchdog without the rows in `gone` — each
    row and its watchdog line leave together (F1). Pure: copies in, copies
    out; the rest of each file is untouched."""
    fleet = json.loads(json.dumps(fleet_raw))
    wd = json.loads(json.dumps(wd_raw)) if wd_raw is not None else None
    fleet['bots'] = [b for b in fleet.get('bots') or [] if row_botid(b) not in gone]
    if wd is not None:
        for botid in gone:
            (wd.get('positions') or {}).pop(botid, None)
    return fleet, wd


def dump(obj):
    """The repo's one config format (panel.create.dump_config, U19)."""
    return json.dumps(obj, indent=2, ensure_ascii=False) + '\n'


def write_atomic(path, text):
    """tempfile + os.replace with a .bak beside it, as the panel's apply."""
    import os
    import tempfile
    p = Path(path)
    if p.exists():
        p.with_suffix(p.suffix + '.bak').write_text(p.read_text())
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(p))
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def sell_down(client, dry=False, quote='USDT'):
    """Every coin on a Bybit account but `quote`, sold at market for it;
    what is under the venue's minimum stays as dust. [{coin, qty, ...}]."""
    out = []
    acc = (client.wallet_balance().get('list') or [{}])[0]
    for x in acc.get('coin', []):
        coin, bal = x['coin'], Decimal(x.get('walletBalance') or '0')
        if coin == quote or bal <= 0:
            continue
        if Decimal(x.get('borrowAmount') or '0') > 0:
            out.append({'coin': coin, 'left': 'borrowed — repay it first'})
            continue
        sym = coin + quote
        try:
            inst = client.instruments_info('spot', sym)
            px = Decimal(client.tickers('spot', sym)['lastPrice'])
        except Exception:                                    # noqa: BLE001
            out.append({'coin': coin, 'left': f'no {sym} market'})
            continue
        lot = inst['lotSizeFilter']
        step = Decimal(lot['basePrecision'])
        qty = (bal // step) * step
        if qty < Decimal(lot['minOrderQty']) or qty * px < Decimal(lot.get('minOrderAmt') or '0'):
            out.append({'coin': coin, 'left': 'dust under the minimum'})
            continue
        if not dry:
            client.place_market('spot', sym, 'Sell', str(qty))
        out.append({'coin': coin, 'sold' if not dry else 'would_sell': str(qty)})
    return out


def portfolio_left(bot):
    """X4 for a portfolio row: each hedge and short leg's position read
    back. Its flatten answers with the wallet's balances, which say nothing
    of a perp left open, so a clean wallet over an open short read flat.
    [{leg, symbol, held}] for each leg still open."""
    left = []
    for kind in ('hedge', 'short'):
        for coin, leg in (bot.legs.get(kind) or {}).items():
            size, _ = bot._short_size(bot.client.read_symbol_truth(leg['market_type'], leg['symbol']), leg)
            if size > 1e-12:
                left.append({'leg': f'{kind} {coin}', 'symbol': leg['symbol'], 'held': size})
    return left


def retire_fleet(fleet_path, dry=False, sell=False, clear=False):
    """The whole act on one fleet file; the JSON-able answer."""
    from common.env import load_env
    from .durable import logs_dir, state_path
    from .exchange.env import select_account
    from .main import acquire_fleet_lock, fleet_running
    from .trades import load_trades
    load_env()
    fleet_path = Path(fleet_path)
    raw = json.loads(fleet_path.read_text())
    fleet = validate_fleet(raw)
    select_account(fleet['account'])                         # H5
    if fleet_running(str(fleet_path), {c['venue'] for c in fleet['bots']}, fleet['account']):
        return {'refused': 'the fleet is running on this file — stop it first: '
                           'its running bots would place their orders back'}
    # D81: the fleet's open trades are bots of it too, retired with it
    trades, trade_refused = load_trades(state_path(str(fleet_path), fleet, 'trades'))
    trades = [dict(t, account=fleet['account']) for t in trades]
    refused = ([f'{where} ({label}): {why}' for where, label, why in fleet.get('refused', ())]
               + [f'trades[{i}]: {why}' for i, why in trade_refused])
    if clear and refused:
        # a row the engine refuses (D52) is not retired, so clearing it would
        # leave whatever it holds with nothing to manage it
        return {'refused': 'rows the engine refuses are not retired, so the fleet cannot be '
                           'cleared — fix or remove them first: ' + '; '.join(refused)}
    if dry:
        return _retire(fleet_path, raw, fleet, trades, refused, dry, sell, clear)
    # F3: the fleet's own prelock held for the whole retire, so the engine
    # cannot start on this file while its orders are being cancelled
    lockdir = logs_dir(fleet_path)
    lockdir.mkdir(parents=True, exist_ok=True)
    try:
        prelock = acquire_fleet_lock(str(lockdir / f'{fleet_path.resolve().name}.prelock'))
    except ConfigError:
        return {'refused': 'the fleet is starting on this file — let it start and stop it, '
                           'or wait, then retire'}
    try:
        return _retire(fleet_path, raw, fleet, trades, refused, dry, sell, clear)
    finally:
        prelock.close()


def _retire(fleet_path, raw, fleet, trades, refused, dry, sell, clear):
    from .durable import state_path
    from .main import build_portfolio
    from .retire import open_venue, retire_bot
    from .tombstones import Tombstones, path_for
    tombs = Tombstones(str(path_for(str(fleet_path), fleet)))
    clients, rows = {}, []
    markets = market_rows(fleet) + trades
    for cfg in markets:
        botid = row_botid(cfg)
        client, adapter = open_venue(cfg, clients)
        if kind_of(cfg) == 'spot':
            truth = client.read_symbol_truth('spot', cfg['symbol'])
            owned = [o for o in truth['orders'] if rung_of(o['link_id'], botid) is not None]
            if not dry:
                if not tombs.has(botid):
                    tombs.add(botid, REASON)                 # X7: first, before any write
                for o in owned:
                    client.cancel_order('spot', cfg['symbol'], o['order_id'])
            rows.append({'botid': botid, 'kind': 'spot', 'orders': len(owned),
                         'note': 'its coins are the wallet\'s: --sell sells them'})
            continue
        rows.append(dict(retire_bot(cfg, client, adapter, tombs, REASON, dry=dry), kind='perp'))
    open_legs = []
    for cfg in [c for c in fleet['bots'] if kind_of(c) == 'portfolio']:
        botid = row_botid(cfg)
        if dry:
            rows.append({'botid': botid, 'kind': 'portfolio', 'dry': True,
                         'would': 'flatten every leg together (H4)'})
            continue
        from .events import Notifier
        from .portfolio_state import PortfolioState
        if 'bybit' not in clients:
            from .exchange.bybit.client import WriteClient
            from .main import refuse_mainnet
            clients['bybit'] = WriteClient()
            refuse_mainnet(clients['bybit'], False, False)
        state = PortfolioState(str(state_path(str(fleet_path), fleet, 'portfolio_state')))
        bot, _ = build_portfolio(cfg, clients['bybit'], Notifier(sink=lambda *_: None), state, tombs)
        after = bot.flatten_now(REASON, tombstone=True)
        legs = portfolio_left(bot)                           # X4: the perps read back too
        if legs:
            open_legs.append({'botid': botid, 'legs': legs})
        rows.append({'botid': botid, 'kind': 'portfolio', 'after': after})
    out = {'fleet': fleet_path.name, 'dry': dry, 'rows': rows}
    if refused:
        out['not_retired'] = refused                         # D52: said, never silent
    if not dry:                                              # X4: read back, never assume
        left = []
        for cfg in markets:
            t = clients[cfg['venue']].read_symbol_truth(cfg['market_type'], cfg['symbol'])
            botid = row_botid(cfg)
            held = (0.0 if cfg['market_type'] == 'spot' else
                    sum(float(p.get('size') or 0) for p in (t.get('positions') or {}).values()))
            mine = [o['link_id'] for o in t['orders'] if rung_of(o['link_id'], botid) is not None]
            if held > 1e-12 or mine:
                left.append({'botid': botid, 'held': held, 'orders': mine})
        left += open_legs
        out['flat'] = not left
        if left:
            out['left'] = left
    if sell:
        # only a Bybit account is sold down; an empty fleet names no venue
        out['sold'] = (sell_down(clients['bybit'], dry=dry) if 'bybit' in clients
                       else [{'left': 'no Bybit row in this fleet: nothing sold'}])
    if clear:
        # every row and trade was just retired, so every one leaves (a dry
        # run says which) — but only once the venue read back flat: a row
        # cleared over what it left lets a new bot of its name adopt it
        gone = sorted({row_botid(b) for b in raw.get('bots') or [] if isinstance(b, dict)}
                      | {row_botid(t) for t in trades})
        out['cleared'] = gone if dry or out['flat'] else []
        if not dry and not out['flat']:
            out['not_cleared'] = ('the venue is not flat (see left): every row, tombstone and '
                                  'record stays — retire what is left, then clear again')
        elif not dry and gone:
            wd_path = raw.get('watchdog')
            wd_raw = json.loads(Path(wd_path).read_text()) if wd_path and Path(wd_path).exists() else None
            new_fleet, new_wd = clear_rows(raw, wd_raw, set(gone))
            write_atomic(fleet_path, dump(new_fleet))
            if new_wd is not None:
                write_atomic(wd_path, dump(new_wd))
            from .forget import forget_bot
            at = time.time() * 1000
            for botid in gone:
                forget_bot(fleet_path, raw, botid, at)       # X16: everything under its name
    return out


def command(fleet_path, dry=False, sell=False, clear=False):
    """The argv, for the panel (a subprocess with the fleet's own keys)."""
    return ([sys.executable, '-m', 'gridgremlin.retire_all', str(fleet_path)]
            + (['--dry'] if dry else []) + (['--sell'] if sell else [])
            + (['--clear'] if clear else []))


def main(argv):
    flags = {a for a in argv if a.startswith('--')}
    args = [a for a in argv if not a.startswith('--')]
    if len(args) != 1 or flags - {'--dry', '--sell', '--clear'}:
        print('usage: python3 -m gridgremlin.retire_all <fleet.json> [--dry] [--sell] [--clear]')
        return 2
    try:
        out = retire_fleet(args[0], dry='--dry' in flags, sell='--sell' in flags,
                           clear='--clear' in flags)
    except (ConfigError, Exception) as e:                    # noqa: BLE001
        out = {'refused': f'{type(e).__name__}: {e}'}
    print(json.dumps(out))
    return 1 if 'refused' in out or out.get('flat') is False else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
