"""D86: show mode's data — what the public showcase may say about the bots,
written by the private side, read by the showcase (D91: the showcase never
imports the engine; this file is the one thing that crosses).

An ALLOWLIST, never a filter: each bot is rebuilt from named fields — its
coin, side, kind, market, state, return on its own capital, days running
and trips — so a field the readout gains later cannot leak. Dollar amounts
and leverage are added only with --amounts. A fleet on real money is
refused: the public page is for paper (D86).

  python3 -m gridgremlin.show configs/a.json [configs/b.json] [--amounts]
"""
import json
import subprocess
import sys
import time
from pathlib import Path

from common.files import write_json
from common.symbols import coin_of
from .config import fleet_label
from .report import card_total, contract_tiers

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'logs' / 'show' / 'show.json'
KINDS = {'grid': 'grid', 'martingale': 'DCA', 'portfolio': 'portfolio', 'trade': 'trade'}
MARKETS = {'linear': 'perpetual', 'inverse': 'inverse perpetual', 'spot': 'spot'}
NETWORKS = {'demo': 'paper (exchange demo)', 'testnet': 'testnet'}


class RealMoney(Exception):
    """A fleet not shown: real money, or a network the readout could not say."""


def _parts(botid):
    """I1: market_type[:3] + symbol + side initial; pfo<name> a portfolio."""
    if botid.startswith('pfo'):
        return None, None, None
    side = {'l': 'long', 's': 'short'}.get(botid[-1])
    return botid[:3], botid[3:-1], side


def show_bot(botid, b, terms, record, now_ms, amounts=False, belief=None):
    """One bot, rebuilt from named fields. `b` is the window's book (None:
    not started), `record` its since-first-trade book when the readout has
    one (R18) — the public page counts from the first trade."""
    terms = terms or {}
    belief = belief or {}
    prefix, symbol, side = _parts(botid)
    book = record or b
    capital = terms.get('capital')
    total = card_total(book) if book else None
    pfo = belief.get('portfolio') if terms.get('strategy') == 'portfolio' else None
    if pfo and pfo.get('total') is not None:          # H6: a portfolio row values itself
        total = pfo['total']
    if belief.get('alive') is False:
        state = 'stopped'
    elif b is not None or pfo or belief.get('alive'):
        state = 'running'
    else:
        state = 'stopped' if book else 'not started'
    out = {
        'coin': coin_of(symbol) if symbol else 'basket',
        'side': side or 'hedged',
        'kind': KINDS.get(terms.get('strategy') or (book or {}).get('strategy'), 'grid'),
        'market': ('spot, perpetual hedge' if terms.get('strategy') == 'portfolio'
                   else MARKETS.get(terms.get('market_type'), terms.get('market_type') or '')),
        'state': state,
        'return_pct': (round(total / capital * 100.0, 2)
                       if total is not None and capital else None),
        'days': (round((now_ms - book['first_ms']) / 86_400_000, 1)
                 if book and book.get('first_ms') is not None else None),
        'trips': (book.get('rounds') if (book or {}).get('strategy') == 'martingale'
                  else (book or {}).get('trips')),
    }
    if amounts:
        out.update(capital=capital, total=None if total is None else round(total, 2),
                   quote=terms.get('quote'), leverage=terms.get('leverage'))
    return out


def show_account(label, contract, amounts=False):
    tiers = contract_tiers(contract)
    # fail closed (the review, 2026-10-11): a fleet whose network the
    # readout could not say — no snapshot, a failed account read — is not
    # paper until it says so; only demo and testnet are shown
    if not tiers or any(t not in NETWORKS for t in tiers.values()):
        raise RealMoney(f'{label}: network {sorted(set(tiers.values())) or "unknown"} — '
                        'the public page shows paper only (D86)')
    now_ms = contract.get('generated_ms') or int(time.time() * 1000)
    terms = contract.get('terms') or {}
    records = contract.get('since_first') or {}
    belief = ((contract.get('watchdog') or {}).get('belief') or {}).get('bots') or {}
    bots = [show_bot(bid, b, terms.get(bid), records.get(bid), now_ms, amounts, belief.get(bid))
            for bid, b in sorted(contract.get('bots', {}).items())]
    # the account's return: the running bots' totals over their capital,
    # both in the quote (an inverse book counts in its coin, so it sits out)
    pairs = [(b['total_q'], b['capital_q']) for b in
             (_quote_pair(bid, contract, belief.get(bid)) for bid in contract.get('bots', {}))
             if b]
    networks = sorted({NETWORKS.get(t, t) for t in tiers.values()})
    return {'name': label, 'network': ', '.join(networks) or 'unknown',
            'return_pct': (round(sum(t for t, _ in pairs) / sum(c for _, c in pairs) * 100.0, 2)
                           if pairs else None),
            'bots': bots}


def _quote_pair(botid, contract, belief):
    b = contract['bots'].get(botid)
    terms = (contract.get('terms') or {}).get(botid) or {}
    capital = terms.get('capital')
    pfo = (belief or {}).get('portfolio') if terms.get('strategy') == 'portfolio' else None
    if pfo and pfo.get('total') is not None and capital:
        return {'total_q': pfo['total'], 'capital_q': capital}
    if b is None or b.get('inverse') or not capital:
        return None
    book = (contract.get('since_first') or {}).get(botid) or b
    return {'total_q': card_total(book), 'capital_q': capital}


def readout(fleet, hours=24):
    out = subprocess.run([sys.executable, '-m', 'gridgremlin.report', fleet,
                          '--hours', str(hours), '--json'],
                         capture_output=True, text=True, timeout=180, cwd=ROOT)
    return json.loads(out.stdout)


def build(fleets, amounts=False, read=readout, now=None):
    accounts, refused = [], []
    for f in fleets:
        try:
            accounts.append(show_account(fleet_label(f), read(f), amounts))
        except RealMoney as e:
            refused.append(str(e))
    return {'generated_ms': int((time.time() if now is None else now) * 1000),
            'amounts': bool(amounts), 'accounts': accounts, 'refused': refused}


def main(argv):
    fleets = [a for a in argv if not a.startswith('--')]
    if not fleets:
        print('usage: python3 -m gridgremlin.show <fleet.json> ... [--amounts]')
        return 2
    data = build(fleets, amounts='--amounts' in argv)
    write_json(OUT, data)
    print(f"show: {len(data['accounts'])} accounts, "
          f"{sum(len(a['bots']) for a in data['accounts'])} bots"
          + (f"; refused {len(data['refused'])} (real money)" if data['refused'] else ''),
          flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
