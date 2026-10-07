# For testers

## Getting keys (free, no real money)

**Bybit Demo Trading.** Sign in to Bybit, switch to **Demo Trading** (the
account menu). Demo Trading has its own API management: make a key there with
**trade** permission only — no withdrawal, no transfer. Those keys only ever
reach the demo account. Put them in `.env` with `BYBIT_DEMO=true`.

**Hyperliquid Testnet** (optional). Go to `app.hyperliquid-testnet.xyz`,
connect a wallet you use for nothing else, take testnet USDC from the faucet,
then under **API** create an **API wallet** and keep its private key. In
`.env`: `HL_ACCOUNT_ADDRESS` is your wallet's address, `HL_PRIVATE_KEY` is
the API wallet's key (never your wallet's own), `HL_TESTNET=true`. Testnet
books are thin on most coins; BTC and ETH are the ones worth testing on.

**Telegram** (optional). Make a bot with @BotFather, put the bot in a group
with you, and set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (the group's id)
and `TELEGRAM_OWNER_ID` (your user id). Then `/help` in the group.

Run `python3 -m gridgremlin.doctor` after each step; it tells you what is
still missing.

## Three things to try

1. **A sideways grid on demo, for a day.** Open the panel, **set up a bot**,
   preset *sideways*, a coin you like, a small capital. Read the summary page
   before you confirm: it says in plain words what the bot will do, and the
   what-if slider shows what a move would do to it. Start the fleet from the
   control page. Come back in a day: the card says what it made, what it
   holds, and where the price sits in the range.
2. **A DCA bot on testnet, through a few rounds.** Use the Hyperliquid example
   or set one up (preset *DCA*). Watch a round: the base order, the safety
   orders as the price falls, the take-profit above the average. `/rounds` on
   the phone says where it stands.
3. **Compare grid counts.** On a bot's page, press *compare grid counts*: it
   replays your range with 5 to 77 grids over two weeks of real candles and
   says which did best and whether that holds up. About six minutes; press
   once.

## What to watch while it runs

- The **cards**: the state word (never a silent "working"), the money box
  (realised, funding, open), the range strip, the holding, the market line.
- **key** on every page: if a word on the screen needs more than the key
  says, that word has failed — tell us.
- **`/market`** (or the session reports if Telegram is on): regime, crowding,
  funding, how thin the book is for your fleet.
- The **digest** at 23:58 UTC, if Telegram is on.
- The log in `logs/`: every event is written there, the phone gets the few
  that need you.

## What to report, and how

In order of usefulness:

1. **A failing spec**: a `spec_*` function in `tests/spec_*.py` that fails
   against today's code and passes against the behaviour you think is right.
2. **A reproduction** against the fakes in `tests/` — inputs, state, the wrong
   outcome.
3. **A description**: the file, the line, the market scenario.
4. **A word that confused you**: what the screen said, what you expected.

Use the issue templates. Never paste keys, account figures or hostnames.

## What not to do

- Do not put real-money keys anywhere near this. The edition refuses them,
  but a key in a file is a key in a file.
- Do not run two fleets on one account: the lock refuses the second, by design.
- Do not expect a testnet fill to say much about a mainnet one on a thin coin;
  the market line says **THIN** when the book cannot hold your grid.
