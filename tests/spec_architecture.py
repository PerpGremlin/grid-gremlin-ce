"""D91 (docs/ARCHITECTURE.md): imports point one way. common imports the
standard library only; ggdata imports common; showcase imports common and
ggdata — never the engine or the panel, so the public side can never reach
a key or an order. Read from each package's source."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OURS = ('common', 'ggdata', 'gridgremlin', 'panel', 'showcase')
ALLOWED = {'common': set(), 'ggdata': {'common'}, 'showcase': {'common', 'ggdata'}}


def imports_of(path):
    """The top-level packages of ours a module imports (relative imports
    stay inside its own package)."""
    tree = ast.parse(path.read_text())
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name.split('.')[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module.split('.')[0])
    return out & set(OURS)


def spec_D91_imports_point_one_way():
    seen = 0
    for pkg, allowed in ALLOWED.items():
        for f in (ROOT / pkg).glob('**/*.py') if (ROOT / pkg).is_dir() else []:
            bad = imports_of(f) - allowed - {pkg}
            assert not bad, f'{f.relative_to(ROOT)} imports {sorted(bad)} — {pkg} may import only {sorted(allowed) or "the standard library"}'
            seen += 1
    assert seen >= 5                                                  # common/ exists and was read
    assert imports_of(ROOT / 'common' / 'fmt.py') == set()


def spec_D91_the_rule_catches_a_wrong_import():
    """The guard's sabotage: a common module that imports the engine is caught."""
    import tempfile
    f = Path(tempfile.mkdtemp()) / 'bad.py'
    f.write_text('from gridgremlin.config import validate_fleet\nimport json\n')
    assert imports_of(f) - ALLOWED['common'] == {'gridgremlin'}
