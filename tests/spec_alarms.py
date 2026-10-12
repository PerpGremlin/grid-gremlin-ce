# Specs for the alarm paths found by the pre-real-money audit (2026-10-13):
# E12 a held page goes out on the next cycle, E13 a failure page's stamp
# only after Telegram took it.

from pathlib import Path


def spec_E12_a_held_page_goes_out_on_the_next_cycle_not_the_next_event():
    """Pages coalesce under the interval; before, only a NEW event flushed
    what was held — on a quiet fleet the last page of a burst (an urgent
    stop warning one second after a refusal) waited hours. The fleet now
    flushes every cycle; a send that failed is tried again the same way."""
    from gridgremlin.events import TelegramNotifier
    now, sent = [1000.0], []
    n = TelegramNotifier('t', 'c', transport=sent.append, clock=lambda: now[0])
    n.startup = False
    n.event('warn', 'linBTCUSDTl', 'margin refusal', urgent=True)
    now[0] += 1.0
    n.event('warn', 'linBTCUSDTl', 'stop warning', urgent=True)
    held = len(sent)
    now[0] += 5.0
    n.flush()
    assert len(sent) == held + 1 and 'stop warning' in sent[-1]
    fails = [0]

    def down(text):
        fails[0] += 1
        raise OSError('no route')
    n._transport = down
    now[0] += 5.0
    n.event('warn', 'linBTCUSDTl', 'third', urgent=True)              # its own send fails
    n._transport = sent.append
    now[0] += 5.0
    n.flush()
    assert fails[0] == 1 and 'third' in sent[-1]                       # retried on the cycle
    src = (Path(__file__).resolve().parents[1] / 'gridgremlin' / 'main.py').read_text()
    assert 'notifier.flush()' in src                                     # the loop calls it


def spec_E13_a_failure_pages_stamp_is_written_only_after_telegram_took_it():
    """The fleet-down and watchdog-failing pages are rate-limited by a
    stamp. Written before the send, with curl's errors ignored, a failed
    send silenced the next 30 minutes; now curl fails on an HTTP error and
    the stamp follows only its success."""
    root = Path(__file__).resolve().parents[1] / 'ops' / 'systemd'
    for name in ('fleet-failed.service.template', 'watchdog-failed.service.template'):
        line = next(ln for ln in (root / name).read_text().splitlines() if ln.startswith('ExecStart='))
        assert 'curl -sf -m 20' in line, name
        assert line.endswith('" >/dev/null && echo "$$now" > "$$stamp"\''), name
        assert line.count('> "$$stamp"') == 1, name                     # never before the send


def spec_F2b_a_position_bound_is_numbers_min_not_above_max():
    """A bound the validator let through as text crashed the watchdog's
    evaluation, leaving only its generic failing page; min above max could
    never be satisfied. Both are refused by name; a sound bound passes."""
    from gridgremlin.config import ConfigError
    from gridgremlin.watchdog import validate_watchdog
    base = {'tag': 't', 'snapshot': 's', 'state': 'st', 'staleness_seconds': 9, 'mm_rate_max': 0.5,
            'equity_min': 10, 're_alert_seconds': 9, 'assumes_sole_actor': True}
    assert validate_watchdog(dict(base, positions={'b': {'min': 0, 'max': 0.5}}))
    for bad in ({'min': '0', 'max': 1}, {'min': 2, 'max': 1}, {'min': -1, 'max': 1}, {'min': True, 'max': 1}):
        try:
            validate_watchdog(dict(base, positions={'b': bad}))
            raise AssertionError(f'accepted {bad}')
        except ConfigError as e:
            assert 'positions.b' in str(e)
