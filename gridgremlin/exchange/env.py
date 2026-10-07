# .env loading. Inline comments strip on whitespace+# — a template comment once
# resolved a demo config to MAINNET (v2, pinned then, pinned again here).
import os
from pathlib import Path


def load_env(path=None):
    """Populate os.environ from .env; the process environment wins."""
    p = Path(path) if path else Path(__file__).resolve().parents[2] / '.env'
    if not p.exists():
        return
    mode = p.stat().st_mode & 0o077
    if mode:
        # the keys file is the owner's alone (audit 2026-10-05: the rule
        # was written down, never checked)
        raise PermissionError(f'{p} is readable by others (mode '
                              f'{p.stat().st_mode & 0o777:o}) — run: '
                              f'chmod 600 {p}')
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        for marker in (' #', '\t#'):
            if marker in value:
                value = value.split(marker, 1)[0]
        os.environ.setdefault(key.strip(), value.strip())
