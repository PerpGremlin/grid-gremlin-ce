# Specs for the real-money panel made whole (D177, U138c; owner 2026-11-10:
# "lets make it completely functional"): its forms, charts and rehearsals
# read the network its fleets trade, and its account box says Hyperliquid's
# wallet in Hyperliquid's coin.

import json
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class _HL:
    """A unified HL account: 800 USDC free in spot, a 0.005 BTC long."""
    def clearinghouse_state(self):
        return {'marginSummary': {'accountValue': '40', 'totalNtlPos': '375', 'totalMarginUsed': '37.5'},
                'crossMaintenanceMarginUsed': '5', 'withdrawable': '0',
                'assetPositions': [{'position': {'coin': 'BTC', 'szi': '0.005', 'entryPx': '75500',
                                                 'positionValue': '375', 'unrealizedPnl': '-2.5',
                                                 'leverage': {'value': 10}}}]}

    def user_abstraction(self):
        return 'unifiedAccount'

    def spot_clearinghouse_state(self):
        return {'balances': [{'coin': 'USDC', 'total': '837.5', 'hold': '37.5'}]}


def spec_U138c_the_hl_account_box_says_its_usdc_wallet_and_its_coin():
    """The live account box said "balances: not read" and "available to
    trade … USDT" on Hyperliquid. Now its one coin is said as U138's are:
    the balance, the open P&L apart (balance + open P&L = the collateral),
    no loans, and the money in USDC. Bybit's is unchanged."""
    from gridgremlin.exchange.hyperliquid.truth import account_figures
    from panel.strip_view import account_lines
    fig = account_figures(_HL())
    assert fig['collateral'] == 840.0 and fig['available'] == 800.0
    w = fig['wallet']['USDC']
    assert w['balance'] + w['upl'] == fig['collateral'] and w['upl'] == -2.5 and w['borrow'] == 0.0
    out = account_lines({'generated_ms': int(time.time() * 1000),
                         'account': {'hyperliquid': dict(fig, tier='mainnet')}})
    assert 'USDC 842.5' in out and 'USDC -2.50' in out
    assert 'floating debt: <span class="dim">none' in out
    assert 'available to trade: <b>800.00 USDC</b>' in out and 'USDT' not in out
    by = account_lines({'generated_ms': int(time.time() * 1000),
                        'account': {'bybit': {'tier': 'demo', 'available': 5.0, 'wallet': {}}}})
    assert '5.00 USDT' in by


def _fleets(d, *switches):
    out = []
    for i, sw in enumerate(switches):
        raw = {'bots': [{'venue': 'hyperliquid', 'symbol': 'BTC'}]}
        if sw is not None:
            raw['allow_mainnet'] = sw
        p = Path(d) / f'fleet.{i}.json'
        p.write_text(json.dumps(raw))
        out.append(str(p))
    return out


def spec_D177_the_panels_public_hl_reads_go_to_its_fleets_network():
    """The live panel's forms priced a new bot off testnet's BTC. The panel
    takes its fleets' switch: mainnet when its HL fleets say JSON true,
    testnet when not, and a panel over both refuses in words rather than
    price one network off the other. Sabotage: the old hard-coded testnet
    read on a mainnet panel is caught by the network the read asks for."""
    from gridgremlin.exchange.hyperliquid import client as hl
    from gridgremlin.config import ConfigError
    from panel import create
    asked = []

    class Info:
        def __init__(self, env=None, allow_mainnet=None, **kw):     # what public_info asks
            asked.append((env, allow_mainnet))

        def meta_and_ctxs(self):
            return {'universe': [{'name': 'BTC', 'szDecimals': 5}]}, [{'markPx': '75000'}]
    real, saved = hl.InfoClient, create.HL_NETWORK
    hl.InfoClient = Info
    create._SYMBOLS.clear()
    try:
        with tempfile.TemporaryDirectory() as d:
            assert create.set_hl_network(_fleets(d, True)) == 'mainnet'
            assert create._hl_public('BTC')[1] == 75000.0 and asked[-1] == ('mainnet', True)
            assert create.public_symbols('hyperliquid') == ('BTC',) and asked[-1] == ('mainnet', True)
            create._SYMBOLS.clear()
            assert create.set_hl_network(_fleets(d, None)) == 'testnet'
            create._hl_public('BTC')
            assert asked[-1] == ('testnet', False)
            assert create.set_hl_network(_fleets(d, 'true')) == 'testnet'     # D25b: JSON true only
            assert create.set_hl_network(_fleets(d, True, None)) == 'mixed'
            try:
                create._hl_public('BTC')
                raise AssertionError('a mixed panel priced a bot')
            except ConfigError as e:
                assert 'both networks' in str(e)
            assert create.set_hl_network([]) == 'testnet'
    finally:
        hl.InfoClient, create.HL_NETWORK = real, saved
        create._SYMBOLS.clear()
    src = (ROOT / 'panel' / 'server.py').read_text()
    assert src.index('set_hl_network(Handler.fleets)') < src.index('ThreadingHTTPServer(')


def spec_D177_a_rehearsal_replays_its_fleets_network():
    """A rehearsal of an HL bot replays the panel's network's candles and
    instrument (the panel passes it; a fleet file's own switch otherwise);
    a mixed panel's is refused in words; a Bybit draft is untouched."""
    from gridgremlin import backtest_cli as bc
    from gridgremlin.exchange.hyperliquid.client import network_of
    assert network_of({'allow_mainnet': True}) == 'mainnet'
    assert network_of({'allow_mainnet': 'true'}) == network_of({}) == 'testnet'
    try:
        bc.bars_and_adapter({'venue': 'hyperliquid', 'symbol': 'BTC'}, 60, 1, 'mixed')
        raise AssertionError('a mixed panel rehearsed')
    except ValueError as e:
        assert 'both networks' in str(e)
    src = (ROOT / 'gridgremlin' / 'backtest_cli.py').read_text()
    assert "fetch_instrument(cfg['symbol'], env=network)" in src and 'network=network), adapter' in src
    assert "network='testnet'), adapter" not in src
    assert "['--hl-network', _hl_net()]" in (ROOT / 'panel' / 'routes.py').read_text()
