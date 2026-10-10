# The agent's score (SPEC J5, D80): what its closed trades made, judged the
# way docs/AGENT.md states in advance — P&L after fees against doing nothing,
# the worst drawdown, the hit rate, the average win against the average
# loss, fees as a share of gross, and calibration: do its confident trades
# win more often than its unsure ones? No verdict before 200 closed trades
# (or 20 sessions); until then the score says how far it has to go.
#
#   python3 -m gridgremlin.agent_score configs/fleet.agent.json
import sys

VERDICT_TRADES = 200
BANDS = ((0.0, 0.5, 'below 0.5'), (0.5, 0.7, '0.5 to 0.7'), (0.7, 1.0001, '0.7 and above'))


def score(book):
    """Pure: the closed positions of a paper book (or any list shaped like
    one) scored. Open positions are counted, never scored."""
    closed = sorted((p for p in book if p.get('closed')), key=lambda p: p['closed']['t'])
    pnl = [p['closed']['pnl'] for p in closed]
    fees = sum(p['closed']['fees'] for p in closed)
    wins = [x for x in pnl if x > 0]
    losses = [x for x in pnl if x <= 0]
    eq = peak = dd = 0.0
    for x in pnl:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    gross = sum(abs(x) for x in pnl) + fees
    bands = []
    for lo, hi, name in BANDS:
        sel = [p['closed']['pnl'] for p in closed
               if p.get('confidence') is not None and lo <= p['confidence'] < hi]
        bands.append({'band': name, 'trades': len(sel),
                      'hit_rate': sum(1 for x in sel if x > 0) / len(sel) if sel else None})
    rated = [b for b in bands if b['trades']]
    return {'closed': len(closed), 'open': sum(1 for p in book if not p.get('closed')),
            'pnl': sum(pnl), 'fees': fees, 'vs_flat': sum(pnl),
            'max_drawdown': dd,
            'hit_rate': len(wins) / len(pnl) if pnl else None,
            'avg_win': sum(wins) / len(wins) if wins else None,
            'avg_loss': sum(losses) / len(losses) if losses else None,
            'fees_share': fees / gross if gross else None,
            'by_how': {h: sum(1 for p in closed if p['closed']['how'] == h)
                       for h in sorted({p['closed']['how'] for p in closed})},
            'calibration': bands,
            'calibrated': (None if len(rated) < 2 else
                           all(a['hit_rate'] <= b['hit_rate'] for a, b in zip(rated, rated[1:]))),
            'verdict_in': max(0, VERDICT_TRADES - len(closed))}


def render(s):
    def money(x):
        return '—' if x is None else f'{x:+,.2f}'

    def pct(x):
        return '—' if x is None else f'{x:.0%}'
    lines = [f"closed {s['closed']} · open {s['open']} · P&L after fees {money(s['pnl'])} "
             f"(flat: +0.00) · fees {s['fees']:,.2f} ({pct(s['fees_share'])} of gross) · "
             f"worst drawdown {s['max_drawdown']:,.2f}",
             f"hit rate {pct(s['hit_rate'])} · average win {money(s['avg_win'])} · "
             f"average loss {money(s['avg_loss'])} · closed by "
             + (', '.join(f'{h} {n}' for h, n in s['by_how'].items()) or 'nothing yet'),
             'calibration: ' + ' · '.join(f"{b['band']}: {b['trades']} trades, hit {pct(b['hit_rate'])}"
                                          for b in s['calibration'])
             + ('' if s['calibrated'] is None else
                ' — confidence ' + ('orders the outcomes' if s['calibrated'] else 'does not order the outcomes'))]
    lines.append(f"no verdict: {s['verdict_in']} closed trades to go (J5 waits for {VERDICT_TRADES})"
                 if s['verdict_in'] else f"{VERDICT_TRADES}+ closed trades: the score may be judged (J5)")
    return '\n'.join(lines)


def view(book, limits):
    """J5 for the readout contract: the score, its words, and the open paper
    positions as the door last settled them — what the panel's agent box
    draws. Pure."""
    s = score(book)
    return {'paper': limits['paper'], 'score': s, 'text': render(s),
            'max_loss_day': limits['max_loss_day'], 'markets': limits['markets'],
            'open': [{k: p.get(k) for k in ('id', 'market', 'side', 'notional', 'entry', 'stop', 'tp',
                                             'mark', 'open_pnl', 'reason', 'confidence')}
                     for p in book if not p.get('closed')]}


def main(argv):
    if len(argv) != 1:
        print('usage: python3 -m gridgremlin.agent_score configs/fleet.agent.json')
        return 2
    from .agent_paper import book_path, load_book
    print(render(score(load_book(book_path(argv[0])))))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
