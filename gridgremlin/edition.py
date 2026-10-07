"""D68: which edition this is.

The community edition — the tree ops/public_export.py writes for testers —
cannot reach real money whatever a fleet file or a launch flag says: demo
and testnet only, enforced here and not in a document. The private edition
keeps D25's double safety.
"""
PUBLIC = True


def real_money_refused():
    """The reason this edition refuses real money, or None."""
    if PUBLIC:
        return ('this edition cannot reach real money — demo and testnet '
                'only (D68)')
    return None
