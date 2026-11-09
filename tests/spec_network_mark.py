# Specs for D175: a real-money fleet's every phone message opens with
# '🔴 MAINNET' — its own pages wore the venue's colours alone, the same
# 🟢🟢 the testnet fleet's wear (owner, 2026-11-09, at the first live start).

from pathlib import Path


def _phone(mark=''):
    from gridgremlin.events import TelegramNotifier
    now, sent, log = [1000.0], [], []
    n = TelegramNotifier('t', 'c', transport=sent.append, clock=lambda: now[0], sink=log.append)
    n.network_mark = mark
    return n, now, sent, log


def spec_D175_a_mainnet_fleets_every_message_opens_with_the_mark():
    """Every message, startup and later, opens with the mark on its own
    first line (what a lock screen shows); a paper fleet's never does; the
    log, the audit trail tools grep, stays without it."""
    n, now, sent, log = _phone('🔴 MAINNET')
    n.event('fleet', 'fleet', '1 bot(s) on hyperliquid:mainnet: linBTCl', icon='🟢🟢 Hyperliquid')
    n.close()
    n.startup = False
    now[0] += 10
    n.event('warn', 'linBTCl', 'margin refusal', urgent=True)
    n.close()
    assert len(sent) == 2 and all(p.split('\n')[0] == '🔴 MAINNET' for p in sent), sent
    assert '🟢🟢 Hyperliquid fleet: 1 bot(s)' in sent[0]
    assert not any('MAINNET' in line for line in log)
    paper, _, psent, _ = _phone('')
    paper.event('fleet', 'fleet', '1 bot(s) on hyperliquid:testnet: linBTCl', icon='🟢🟢 Hyperliquid')
    paper.close()
    assert psent and not any('MAINNET' in p for p in psent)


def spec_D175_a_long_burst_with_the_mark_stays_under_telegrams_limit():
    """The mark is counted in the trim: a burst that fills a message still
    sends every part under Telegram's 4,096, each part opening with it."""
    n, now, sent, _ = _phone('🔴 MAINNET')
    n.startup = False
    for i in range(400):
        n.event('warn', f'linBTCl{i}', 'x' * 40, urgent=True)
    n.close()
    assert sent and all(len(p) <= 4096 and p.startswith('🔴 MAINNET\n') for p in sent)


def spec_D175_the_mark_follows_d25_before_the_build_and_the_network_after():
    """Before the build: both halves of D25 (the file's JSON true and the
    launch's flag), else nothing. After: the network a client reached — a
    mainnet client marks the fleet, demo or testnet never does."""
    from gridgremlin.main import MAINNET_MARK, network_mark

    class C:
        def __init__(self, env):
            self.env = env
    assert network_mark({'allow_mainnet': True}, True) == MAINNET_MARK
    assert network_mark({'allow_mainnet': True}, False) == ''
    assert network_mark({'allow_mainnet': 'true'}, True) == ''          # D25b: JSON true only
    assert network_mark({}, True) == ''
    assert network_mark({}, True, {'hyperliquid': C('mainnet')}) == MAINNET_MARK
    assert network_mark({'allow_mainnet': True}, True, {'hyperliquid': C('testnet')}) == ''
    assert network_mark({}, False, {'bybit': C('demo'), 'hyperliquid': C('mainnet')}) == MAINNET_MARK


def spec_D175_the_fleet_sets_the_mark_before_its_first_message_and_after_the_build():
    """run() sets the mark before build_fleet (whose startup lines are the
    first to reach the phone) and again from the clients it built."""
    src = (Path(__file__).resolve().parents[1] / 'gridgremlin' / 'main.py').read_text()
    body = src[src.index('\ndef run('):]
    before = body.index('notifier.network_mark = network_mark(json.loads')
    build = body.index('build_fleet(fleet_path, notifier')
    after = body.index('notifier.network_mark = network_mark(fleet, allow_mainnet, clients)')
    assert before < build < after
