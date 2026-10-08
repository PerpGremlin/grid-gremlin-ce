"""T1 and T5: the suite and the documents stay one vocabulary with the
SPEC — held by the suite itself (audit 2026-10-08: 35 ids had no spec
named for them; most were pinned under the decision that minted them)."""
import ast
import glob
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = r'[A-Z]{1,2}\d{1,3}[a-z]?'


def _spec_ids():
    text = (ROOT / 'docs' / 'SPEC.md').read_text()
    return dict(re.findall(r'^- \*\*(' + ID + r')\*\*(.*?)(?=^- \*\*|^## |\Z)', text, re.M | re.S))


def _spec_functions():
    out = []
    for f in sorted(glob.glob(str(ROOT / 'tests' / 'spec_*.py'))):
        src = Path(f).read_text()
        for node in ast.parse(src).body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith('spec_'):
                out.append((node.name, ast.get_source_segment(src, node) or ''))
    return out


def _mentions(seg, ident):
    return re.search(r'(?<![A-Za-z0-9])' + re.escape(ident) + r'(?![A-Za-z0-9])', seg) is not None


def spec_T1_every_invariant_has_a_spec_named_for_it_or_for_its_decision():
    """A spec names the id it pins — in its name, its docstring or a
    `# pins:` line — or is named for the D-number the SPEC entry cites
    (both namespaces are stable; D23's specs pin M10/M11)."""
    ids = _spec_ids()
    funcs = _spec_functions()
    names = {n for n, _ in funcs}
    unpinned = []
    for ident, text in ids.items():
        if any(_mentions(seg, ident) for _, seg in funcs):
            continue
        decisions = set(re.findall(r'\bD\d+\b', text))
        if any(any(n.startswith(f'spec_{d}_') for n in names) for d in decisions):
            continue
        unpinned.append(ident)
    if not (ROOT / 'ops' / 'public_export.py').exists():
        # the public tree (D68) carries neither the exporter nor its spec —
        # F23 is pinned in the private tree, where the export is run
        unpinned = [i for i in unpinned if i != 'F23']
    assert not unpinned, f'SPEC ids no spec names and no minting decision pins: {unpinned}'


def spec_T5_the_documents_cite_only_ids_that_exist():
    """Prose rots; an id that exists nowhere is a claim with no pin. The
    README, SPEC, DECISIONS, the runbooks and the ops README cite only ids
    the SPEC or DECISIONS define, within the SPEC's own families."""
    ids = set(_spec_ids())
    decisions = set(re.findall(r'^- \*\*(D\d+)', (ROOT / 'docs' / 'DECISIONS.md').read_text(), re.M))
    families = {re.match(r'[A-Z]+', i).group(0) for i in ids} | {'D'}
    files = ['README.md', 'ops/README.md', 'docs/SPEC.md', 'docs/DECISIONS.md', 'docs/RUNBOOK.md',
             'docs/PROMOTION.md', 'docs/SOAK.md', 'docs/BACKLOG.md'] + \
            [str(p.relative_to(ROOT)) for p in (ROOT / 'docs' / 'public').glob('*.md')]
    bad = {}
    for rel in files:
        p = ROOT / rel
        if not p.exists():
            continue
        for tok in set(re.findall(r'(?<![A-Za-z0-9_/.\-])(' + ID + r')(?![A-Za-z0-9_])', p.read_text())):
            fam = re.match(r'[A-Z]+', tok).group(0)
            if fam in families and tok not in ids and tok not in decisions:
                bad.setdefault(tok, []).append(rel)
    assert not bad, f'ids cited but defined nowhere: {bad}'


def spec_C10_the_primitives_exist_once():
    """The float parser, the UTC stamp, the number words and the fee
    constants live in fmt.py and fees.py; a second definition anywhere in
    the engine or the panel is the drift the audit found (five parsers,
    five stamps, seven fee literals)."""
    from gridgremlin import fees, fmt
    assert fmt.float_or('1.5') == 1.5 and fmt.float_or('x') is None and fmt.float_or(None, 0.0) == 0.0
    assert fmt.utc_stamp(0) == '1970-01-01T00:00:00Z' and fmt.utc_stamp().endswith('Z')
    assert fmt.num(1234.5) == '1,234.50' and fmt.num(None) == '—' and fmt.num(2, 0) == '2'
    assert fmt.big(12_000) == '12k' and fmt.big(999.6) == '1,000' and fmt.big(None) == '—'
    assert fmt.big_si(2.5e9) == '2.5B' and fmt.big_si(51_900_000) == '51.9M' and fmt.big_si(500) == '500'
    assert fmt.pct(1.234) == '+1.23%' and fmt.pct(1.234, sign=False) == '1.23%' and fmt.pct(None) == '—'
    assert fees.fee_floor_for('spot') > fees.fee_floor_for('linear') > fees.BYBIT_TAKER > fees.BYBIT_MAKER
    offenders = []
    for p in list((ROOT / 'gridgremlin').rglob('*.py')) + list((ROOT / 'panel').rglob('*.py')):
        if p.name in ('fmt.py', 'fees.py'):
            continue
        code = '\n'.join(ln for ln in p.read_text().splitlines() if not ln.lstrip().startswith('#'))
        if re.search(r"except \(TypeError, ValueError\):\s*\n\s*return (None|default)\b", code):
            offenders.append(f'{p.name}: a second float parser')
        if '%Y-%m-%dT%H:%M:%SZ' in code:
            offenders.append(f'{p.name}: the stamp written out')
        if re.search(r'(?<![\d.])0\.0002\b|(?<![\d.])0\.00055\b', code):
            offenders.append(f'{p.name}: a fee rate as a literal')
    assert not offenders, offenders
