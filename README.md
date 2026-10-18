# grid-gremlin — community edition

A grid and DCA (martingale) trading engine for **Bybit Demo Trading** and
**Hyperliquid Testnet**, with a browser panel and a Telegram phone. Python
3.12, standard library only: clone it and run it.

**This edition trades play money only.** It refuses real money whatever a
file or a flag says (D68). Everything you see — fills, P&L, stops, the
market readings — is real exchange behaviour on demo and testnet accounts.
You are here as a tester: run it, poke it, and tell us what you find.

## On Windows: run it inside WSL

The engine runs on Linux and macOS. On Windows 10 (version 2004 or later)
or 11, run it inside **WSL**, the Linux that Windows ships with. It is not a
virtual machine to look after: a Linux terminal, and its files, beside
Windows.

1. Open **PowerShell as administrator** and run `wsl --install`. Restart
   when it asks.
2. **Ubuntu** opens by itself after the restart (or find it in the Start
   menu). Choose a user name and password: that is your Linux login, not
   your Windows one.
3. In that Ubuntu window, get git and Python (Ubuntu 24.04 ships 3.12):
   ```
   sudo apt update && sudo apt install -y git python3
   ```
4. Follow the steps below **in the Ubuntu window**, and clone into your
   Linux home (`cd ~` first), not under `/mnt/c`: Windows' own drives
   cannot keep `.env` private, and the engine refuses a readable one.
5. The panel's address works in your **Windows browser** as it is. If no
   browser opens when you start it, copy the address the terminal prints
   (`http://127.0.0.1:41960/?t=…`) into your browser.

Close the Ubuntu window to stop everything. A native Windows version is
not built; tell us if WSL is a wall for you.

## Ten minutes to a running bot

1. **Python 3.12 or newer.** `python3 --version`.
2. **Clone, then run the suite** — every spec, about half a minute, must end "0 failed":
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
5. **Start it.** Double-click `grid-gremlin` in this folder (choose "Run in
   terminal" if asked), or from a terminal:
   ```
   ./grid-gremlin
   ```
   It runs the doctor, starts the panel and **opens your browser on it**. The
   address stays the same, `http://127.0.0.1:41960/`, so bookmark it. Start
   it again while it runs and it just opens the browser. Close its window, or
   press Ctrl+C, to stop it. `./grid-gremlin --desktop` adds it to your
   applications menu. (Linux for now. It opens the demo example, or a fleet
   you name: `./grid-gremlin configs/mine.json`; a name that does not exist
   yet offers **init**, then **set up a bot**.)

   In the panel, the **control** page starts the engine; the cards show
   every bot; **key** explains every word; **set up a bot** makes one from a
   preset and three answers, through four gates, before anything is
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
`fleet.agent.json`: the agent experiment (docs/AGENT.md) in paper — no
bots and no keys; a model sends trade intents through one door, they are
filled on paper and judged by the market's 1-minute candles, and the score
says whether its discretion beats doing nothing (ops/README §15).

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
