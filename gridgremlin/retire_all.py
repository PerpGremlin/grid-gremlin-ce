# Retire a whole fleet, and clear it (D149).
#   python3 -m gridgremlin.retire_all <fleet.json> [--dry] [--sell] [--clear]
#
# The owner (2026-10-22): "we should set up an all clear/retire so we can
# wipe the UI with nothing." With the fleet stopped, every row is retired
# the way one is (X15c): a grid or DCA row by retire_bot (tombstone, its
# orders cancelled, its position closed); a spot row tombstoned and its
# orders cancelled (its coins are the wallet's, see --sell); a portfolio
# row flattened, every leg together (H4). Then the venue is read back,
# row by row. --sell sells every coin on the Bybit account but USDT
# (dust under the venue's minimum stays; Hyperliquid's USDC is its cash).
# --clear takes every tombstoned row out of the fleet file, with its
# watchdog line and its tombstone, so the page shows nothing; an empty
# fleet is a file the engine refuses to run until a bot is added.
#
# Narrow like retire: never mainnet, never beside its running fleet.
# --dry says what it would do and does nothing. Prints one JSON object;
# a refusal is {"refused": "..."}.
import json
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


def retire_fleet(fleet_path, dry=False, sell=False, clear=False):
    """The whole act on one fleet file; the JSON-able answer."""
    from common.env import load_env
    from .exchange.env import select_account
    from .main import build_portfolio, fleet_running
    from .retire import open_venue, retire_bot
    from .tombstones import Tombstones, path_for, remove
    load_env()
    fleet_path = Path(fleet_path)
    raw = json.loads(fleet_path.read_text())
    fleet = validate_fleet(raw)
    select_account(fleet['account'])                         # H5
    if fleet_running(str(fleet_path), {c['venue'] for c in fleet['bots']}, fleet['account']):
        return {'refused': 'the fleet is running on this file — stop it first: '
                           'its running bots would place their orders back'}
    tombs = Tombstones(str(path_for(str(fleet_path), fleet)))
    clients, rows = {}, []
    for cfg in market_rows(fleet):
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
    for cfg in [c for c in fleet['bots'] if kind_of(c) == 'portfolio']:
        botid = row_botid(cfg)
        if dry:
            rows.append({'botid': botid, 'kind': 'portfolio', 'dry': True,
                         'would': 'flatten every leg together (H4)'})
            continue
        from .durable import state_path
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
        if clear:
            state.forget(bot.botid)
        rows.append({'botid': botid, 'kind': 'portfolio', 'after': after})
    out = {'fleet': fleet_path.name, 'dry': dry, 'rows': rows}
    if not dry:                                              # X4: read back, never assume
        left = []
        for cfg in market_rows(fleet):
            t = clients[cfg['venue']].read_symbol_truth(cfg['market_type'], cfg['symbol'])
            botid = row_botid(cfg)
            held = (0.0 if cfg['market_type'] == 'spot' else
                    sum(float(p.get('size') or 0) for p in (t.get('positions') or {}).values()))
            mine = [o['link_id'] for o in t['orders'] if rung_of(o['link_id'], botid) is not None]
            if held > 1e-12 or mine:
                left.append({'botid': botid, 'held': held, 'orders': mine})
        out['flat'] = not left
        if left:
            out['left'] = left
    if sell:
        # only a Bybit account is sold down; an empty fleet names no venue
        out['sold'] = (sell_down(clients['bybit'], dry=dry) if 'bybit' in clients
                       else [{'left': 'no Bybit row in this fleet: nothing sold'}])
    if clear:
        # every row was just retired, so every row leaves (a dry run says which)
        gone = {row_botid(b) for b in raw.get('bots') or [] if isinstance(b, dict)}
        out['cleared'] = sorted(gone)
        if not dry and gone:
            wd_path = raw.get('watchdog')
            wd_raw = json.loads(Path(wd_path).read_text()) if wd_path and Path(wd_path).exists() else None
            new_fleet, new_wd = clear_rows(raw, wd_raw, gone)
            write_atomic(fleet_path, dump(new_fleet))
            if new_wd is not None:
                write_atomic(wd_path, dump(new_wd))
            for botid in gone:
                remove(tombs.path, botid)
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
