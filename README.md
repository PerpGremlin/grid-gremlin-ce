# grid-gremlin — community edition

A grid and DCA (martingale) trading engine for **Bybit Demo Trading** and
**Hyperliquid Testnet**, with a browser panel and a Telegram phone. Python
3.12, standard library only: clone it and run it.

**This edition trades play money only.** It refuses real money whatever a
file or a flag says (D68). Everything you see — fills, P&L, stops, the
market readings — is real exchange behaviour on demo and testnet accounts.
You are here as a tester: run it, poke it, and tell us what you find.

## Ten minutes to a running bot

1. **Python 3.12 or newer.** `python3 --version`.
2. **Clone, then run the suite** — 740-odd specs, half a minute, must be green:
   ```
   git clone <this repo> && cd grid-gremlin
   python3 tests/run.py
   ```
3. **Keys.** Both are free and need no real money — `docs/TESTERS.md` has the
   clicks. Put them in a file called `.env` in the repo root:
   ```
   BYBIT_API_KEY=...          # from a Bybit DEMO TRADING account
   BYBIT_API_SECRET=...
   BYBIT_DEMO=true
   HL_ACCOUNT_ADDRESS=0x...   # optional: Hyperliquid TESTNET
   HL_PRIVATE_KEY=0x...       # an API wallet's key, never your main wallet
   HL_TESTNET=true
   TELEGRAM_BOT_TOKEN=...     # optional: pages and the phone commands
   TELEGRAM_CHAT_ID=...
   TELEGRAM_OWNER_ID=...
   ```
   then `chmod 600 .env`. The engine refuses a readable one.
4. **The doctor** says what is missing, and what is next:
   ```
   python3 -m gridgremlin.doctor
   ```
   It checks Python, `.env`, each exchange with a read-only call, which network
   each key is on, Telegram, and your fleet files. Run it until every line is ✓.
5. **Start the panel** on one of the example fleets, or on a name that does
   not exist yet (it offers **init**, then **set up a bot**):
   ```
   python3 -m panel.server configs/fleet.demo.json --supervise
   ```
   Open the link it prints. The **control** page starts the engine; the cards
   show every bot; **key** explains every word; **set up a bot** makes one
   from a preset and three answers, through four gates, before anything is
   written.

## The examples in `configs/`

Small sizes, every mechanic shown once, each row with a note saying what it
is. `fleet.demo.json` (Bybit): a sliding long grid with a stop, a hedge
pair, a grid with a loss limit, a repeating DCA bot, a DCA bot with two
take-profit tranches and the breakeven ladder. `fleet.hl.testnet.json`
(Hyperliquid): a sliding grid, a short grid, a DCA bot with the
engine-watched trailing stop. The `watchdog.*.json` beside them are the
account guards the fleet refuses to run without. Edit the rows, or make your
own in the panel — the panel writes the same file.
`examples/fleet.portfolio.json`: the hedged portfolio (README §4b) — two
coins on spot at equal weights, each hedged one for one by its inverse
perpetual, the funding collected and compounded, rebalanced daily; pure
carry, no leverage. It is edited in the file, not the form, and it starts
from its capital in cash on a demo account.

## What to try, and what to look at

`docs/TESTERS.md`: three scenarios, what to watch while they run, and what
to report. In short: a sideways grid on demo for a day; a DCA bot on testnet
through a few rounds; **compare grid counts** on a range you choose. Watch
the cards, `/market` on the phone, and the daily digest.

## Telling us what you found

Findings are the point. Open an issue with one of the templates: a **failing
spec** (the best report there is), a **reproduction**, a **description**, or
a **word on the screen that the key did not explain**. Never include keys,
account figures or hostnames; redact them.

## Where the detail is

- `docs/SPEC.md` — every invariant, by ID; the suite pins each one.
- `docs/DECISIONS.md` — why things are the way they are, in order.
- `docs/THREECOMMAS.md` — the mechanics ledger: what 3Commas does, what this does.
- `ops/README.md` — running it unattended on a box (units, watchdog, pages).

## Licence and terms

**Apache License 2.0** — `LICENSE` and `NOTICE`. Use it, change it, build on
it, keep the notice. Contributions are welcome under the same licence:
`CONTRIBUTING.md` says how (one change per pull request with its spec, the
suite green, commits signed off).

This is software, not advice and not a service. Trading carries risk of
loss, more so with leverage; this edition cannot reach real money.
