"""F23b (D144): a finding never asks who you are. Read where the pages
stand: the private tree keeps them in docs/public/, the public tree at its
root — so a change sent to the edition is held to it too."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASKS = re.compile(r'signed-off-by|git commit -s|certificate of origin|your name|'
                  r'your e-?mail address|give (us|me) your|phone number|'
                  r'contact (me|us) at', re.I)
SAID = 'no name, email or phone number'


def _pages():
    if (ROOT / 'docs' / 'public').is_dir():
        base = ROOT / 'docs' / 'public'
        said = [base / 'README.md', base / 'CONTRIBUTING.md', base / 'TESTERS.md']
        templates = base / 'issue_templates'
    else:
        said = [ROOT / 'README.md', ROOT / 'CONTRIBUTING.md', ROOT / 'docs' / 'TESTERS.md']
        templates = ROOT / '.github' / 'ISSUE_TEMPLATE'
    return said, sorted(templates.glob('*.md'))


def spec_F23b_a_finding_never_asks_who_you_are():
    said, templates = _pages()
    assert all(p.exists() for p in said) and len(templates) == 3
    for page in said + templates:
        text = page.read_text()
        hits = [m.group(0) for m in ASKS.finditer(text)
                if SAID not in text[max(0, m.start() - 40):m.end() + 40].replace('\n', ' ').lower()]
        assert not hits, (page.name, hits)
    for page in said:
        assert SAID in page.read_text().replace('\n', ' ').lower(), page.name
