# H5: which account's keys a process reads. Loading .env is common.env (D91).
import os


ACCOUNT_KEYS = ('API_KEY', 'API_SECRET', 'DEMO', 'TESTNET')
STANDARD_NAMES = ('BYBIT_API_KEY', 'BYBIT_API_SECRET', 'BYBIT_DEMO', 'BYBIT_TESTNET',
                  'HL_ACCOUNT_ADDRESS', 'HL_SUBACCOUNT')
_defaults = None               # the standard names as the process first saw them


def select_account(name):
    """H5 (D78): a fleet names the account it trades with; this process
    then reads that account's keys under the standard names. `default` is
    today's keys, untouched. `carry` reads BYBIT_CARRY_API_KEY, _SECRET,
    _DEMO, _TESTNET and HL_CARRY_SUBACCOUNT (the sub-account's address,
    read for truth and stamped on every signed action as its vault); the
    Hyperliquid signer stays HL_PRIVATE_KEY, the master's agent. Refuses by
    name when the account has no keys on either venue."""
    global _defaults
    if _defaults is None:
        _defaults = {k: os.environ.get(k) for k in STANDARD_NAMES}
    name = (name or 'default').lower()
    if name == 'default':
        # a process that reads several fleets (the digest, the kept fills)
        # selects per fleet: the defaults come back whole, never the last
        # account's keys under the default's name
        for k, v in _defaults.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return {}
    tag = name.upper()
    picked = {}
    for k in ACCOUNT_KEYS:
        v = os.environ.get(f'BYBIT_{tag}_{k}')
        if v is not None:
            picked[f'BYBIT_{k}'] = v
    if f'BYBIT_{tag}_API_KEY' in os.environ and 'BYBIT_DEMO' not in picked and 'BYBIT_TESTNET' not in picked:
        picked['BYBIT_DEMO'] = ''            # the account said neither: real money, D25 decides
        picked['BYBIT_TESTNET'] = ''
    sub = os.environ.get(f'HL_{tag}_SUBACCOUNT')
    if sub:
        picked['HL_ACCOUNT_ADDRESS'] = sub
        picked['HL_SUBACCOUNT'] = sub
    if not picked:
        raise PermissionError(f"account '{name}': no keys — .env carries no BYBIT_{tag}_API_KEY "
                              f"and no HL_{tag}_SUBACCOUNT (H5)")
    for k, v in picked.items():
        os.environ[k] = v                    # the account wins over the defaults
    return picked
