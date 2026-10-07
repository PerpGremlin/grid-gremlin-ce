# Decisions — frozen 2026-08-04; D28 added 2026-09-25; D29–D36 2026-09-28; D37–D40 2026-10-02

The owner's answers to every open call from `archive/ALIGNMENT.md` §13, `archive/LEAN.md` §4 and
`SPEC.md`'s ⚠ markers, organised from the owner's written response plus a four-question
follow-up. **From this file on, these are settled — the migration map and the build do
not relitigate them.** Where I interpreted an answer, the interpretation is flagged and
stands unless the owner corrects it.

## The engine

- **D1 — A stop is the off button** *(S7, X)*. A fired stop **flattens the position,
  cancels every owned order, kills the bot, and prevents restart**. A position fully
  closed from outside (manual market/limit close — detected as a flat position not
  caused by our exits) ends the bot the same way: cancel, kill, page. This deliberately
  overturns v2's "the bot never closes a position"; the owner's words: *"the idea that a
  bot can never close out a position is a false assumption."*
- **D2 — Stop scope: grid inventory only.** On a bot with a `min_position` floor, a stop
  flattens down **to the floor** — the long-held stack survives. Server-side stops must
  respect this (partial-SL sized to inventory where the venue supports it; bot-side
  flatten otherwise).
- **D3 — Stops are opt-in, restable anywhere the venue allows**, and a venue-side SL the
  operator placed by hand is picked up and respected (`watch: position_sl`). X2's
  `stop: {watch: mark_price | account_equity | position_sl}` restructure: **approved**.
  Server-side as the preferred implementation (X3): **approved**.
- **D4 — The replenish rule is the law of both strategies** *(G7)*: an entry is never
  replenished until its corresponding exit has filled. Owner's example: a 63,000 buy
  with its sell at 63,500 does not re-arm at 63,000 until the 63,500 exit fills.
- **D5 — The lot has one anchor: the split ref, always** *(G4)*. No state-dependent
  re-pricing.
- **D6 — No configurable deadband** *(B9)*. The dissolving no-trade behaviour the owner
  described — entries inside the band release furthest-from-mark first as exits fill,
  converging on average entry — **is exactly what D4 + the floor + the fee floor
  produce**, so it ships as emergent behaviour with zero keys. `no_trade_pct`,
  `entry_deadband_pct`, `exit_deadband_pct` and the ratchet are retired. The 0.1% fee
  floor stays a constant.

  *Why adoption is safe without the knob* (owner asked, 2026-08-04). Normal operation
  places only post-only limits — market orders exist solely in the seed and the
  stop-flatten — so nothing can offload or load inventory "at market"; the question is
  only where limits may rest, and three invariants answer it:
  1. **Adopt in profit** (basis below mark): the exit floor is `max(ref, basis×1.001)`
     and ref wins — every exit rests *above* the current price, one lot per rung,
     nearest ~one rung up. No dumping. Re-buying the rungs the position already
     occupies is blocked by the replenish prefix (G7): the nearest `held-lots` entries
     are suppressed and release furthest-first as exits fill — the owner's dissolving
     band, converging on the basis. The cap bounds accumulation regardless.
  2. **Adopt underwater** (basis above mark): the basis wins the max — exits rest only
     above `basis×1.001`; basis beyond the range ⇒ no exits, one warning, position
     left to the operator (S5). The zone between mark and basis holds *nothing by
     construction*: above ref so not entries, below the floor so not exits — the
     deadband, unconfigured. Entries below mark arm normally (buying the dip is the
     job), cap-bounded.
  3. **Autofill on placement** is blocked three independent ways: the ref split (G5),
     the basis floor (G6), and the cross guard (B3) — and post-only makes a crossing
     order a venue rejection, not a fill.
  v2's audit measured the configured exit band as inert whenever the mark-to-basis gap
  exceeded it, and no shipped config ever set the family — the emergent guards anchor
  to the actual position instead of a guessed number.
- **D7 — A bad fleet row refuses the whole fleet** *(C6)*. No silent skips; nothing
  starts until the file is fixed.

## The grid

- **D8 — Input model confirmed**: `{upper, lower, rungs, capital}`; spacing derives.
  The Bybit/Pionex per-grid profit reporting model (grid profit vs total P&L) is the
  one users understand — adopt it.
- **D9 — Seeding is a config toggle for flat starts** (irrelevant to adoption). Seed by
  **market order**, sized by bounds + mark: the lower in the range the mark sits, the
  larger the seed, covering **all** exit-side rungs. Windowing governs which exits
  *rest*, never how much is seeded (the Pionex shape). On failure: refuse and retry.
  *Interpretation confirmed by the owner 2026-08-04.*
- **D10 — Trail is deleted.** Range edits through the normal diff give trailing for
  free when wanted; the SMA machinery goes. Infinity-grid-style behaviour is likewise
  covered by editing bounds. (Owner note for the ops layer: routine range-review can be
  an agentic health-check task rather than engine code.)

## The martingale

- **D11 — 3Commas vocabulary and semantics adopted**: `base_order` + `safety_order` +
  order-size multiplier (of the previous order) + `deviation` +
  `deviation_step_multiplier` + `max_averaging_orders`; TP-basis switch exists but
  **defaults to average entry** (D12). The validator expands the full series and refuses
  any ladder whose total exceeds `capital`, stating the number (Binance-style).
- **D12 — TP measures from average entry** *(M4)*, recomputed as fills deepen. Not
  Bybit's %-of-investment model — owner: "i dont like how bybit calculates it."
- **D13 — The martingale has no range bounds.** Under D11 the ladder's depth derives
  from the deviation schedule × max orders — there is no `lower` key to name, which
  dissolves naming question #12 (the owner's instinct was right: they're *safety/
  averaging orders*, and that is what the field calls them). The grid keeps its bounds.
- **D14 — No floor/cap/damping keys for the martingale** *(M7, resolved by D11)*: the
  cap is the refused-if-over-capital series, a floor is meaningless under a
  whole-position TP, and damping guards a boundary the martingale doesn't have.
  Absence is derived, not missing.
- **D15 — Staged, not skeleton** *(owner may pull any forward)*: partial TPs, trailing
  TP, signal start-conditions, profit reinvest, cooldown-between-rounds tuning.

## Naming and structure

- **D16 — Position ceiling keeps the unit in the name** (`max_position_base` form).
- **D17 — Martingale ladder vocabulary dissolves under D11/D13** — `levels`/
  `level_weights` leave the config surface entirely.
- **D18 — The one-sentence grid definition (ALIGNMENT §1) is approved**, amended by D1:
  the final clause becomes "…idles outside its range, refuses what it cannot verify,
  and closes the position only when its stop says so."

## The build

- **D19 — Bybit first, Hyperliquid second**, once the build's shape is proven.
- **D20 — Field-note correction from the owner**: Pionex *does* ship a futures
  martingale/DCA product, available only in their mobile/tablet app — recorded against
  `archive/research/field-martingale-bots.md`'s "not confirmed."

- **D21 — HL martingales via the venue-resting exit (2026-08-04).** M3 generalises:
  *a round is never without a venue-resting exit* — a hosted position-TP where the
  venue offers one (Bybit keeps its native TP: arguably stronger), a resting
  reduce-only limit at the target elsewhere (HL). The choice is a client
  *capability* (`hosts_position_tp`), never a venue-name test — the bot stays
  venue-blind. Rung 0 of a round is reserved for the resting exit and shielded from
  the diff. A resting-limit TP fills on trade-through rather than mark-trigger —
  at the target or better, accepted.

- **D22 — 1s polling instead of WS wake (2026-08-05).** The owner's call on the
  WS-wake question: raise the poll to 1s fleet-wide. The venue's rate budget is
  the real pace — the Bybit glide and HL's 429-sleep stretch a nominal 1s to
  whatever the venue allows — so "1" means "as fast as permitted", with zero
  new moving parts. WS wake leaves the backlog; it can return as its own
  decision if 1s proves insufficient for tight grids.
- **D23 — Martingale partial TPs and trailing ride the venue (2026-08-05).**
  The owner: "utilise bybit's exchange side options… do what we did for the
  full TP logic, except partial." Same doctrine as D21: venue-hosted where the
  venue offers it (Bybit's Partial tpslMode / trailing stop), the resting
  reduce-only ladder where it doesn't (HL: partial TPs are simply several
  rung-0-style exits at tranche prices). Staged next; D15's list shrinks.

- **D24 — Margin spot as the unhedgeable linear perp (2026-08-05).** The owner's
  framing, confirmed: "as long as margin is on, you can always sell more than you
  hold and go negative on a product." `spot_borrow: true` sends the venue's
  leverage flag on every spot order; the position is the **signed** base balance
  (negative = short, side Sell); the dust rule applies symmetrically around zero;
  shorts are legal for spot **only** under borrow; the ladder sizes against
  `capital × spot_leverage`; interest is venue-side (auto-borrow/auto-repay —
  read, never modelled). Capability-complete; the soak exercises a borrow-long
  first (the owner does not foresee spot shorts, but wants the option).
- **D25 — The armed switch (2026-08-05).** Mainnet exists behind a double safety:
  the fleet file must declare `"allow_mainnet": true` AND the launch must pass
  `--allow-mainnet`; either alone refuses, naming the missing half. Owner's
  words: *"keep it off as a toggle so [cloners] dont try to clone my repo and
  lose money immediately… i know that testnet/demo=true does this, but think of
  it like wearing a helmet and armour."* Supersedes the testnet-only HL
  constructor refusal (F5 → F7); the demo fleet still never carries the flag.

- **D26 — Reinvest and the round cooldown (2026-08-05).** Reinvest is a per-bot
  toggle — the owner: risk might not always make reinvesting smart. On, the
  martingale auto-compounds at round boundaries from lifetime venue fills
  (capped at the watchdog's own +20% headroom); off, and for grids always, the
  manual path is editing `capital` — deliberate, ceiling reviewed together
  (the range review suggests when). The cooldown anchors to the venue's TP-fill
  timestamp. Signal start-conditions: deferred by the owner ("i usually do my
  own TA to enter, even with bots").

- **D27 — The preflight is optional, with a tolerance (2026-08-05).** Probe +
  metadata checks per F8, but the owner's call: *"there may be times when users
  might be okay with one bot failing, not the whole fleet. or a tolerance for
  how many failed bots a user may allow before the algo says nope."*
  `preflight: {probe, max_failed_bots}` — strict D7 refusal at tolerance 0
  (default), dead-and-visible bots within tolerance. Born from the 170037
  incident and the owner's read that metadata checks are "ask the exchange for
  truth — asking what we can find."

- **D28 — The slide supersedes D10's "a human moves the range" (2026-09-25).**
  Evidence first: the 48-day post-mortem (JOURNAL 2026-09-25) — fixed ranges idle
  from day eleven of a 31–62% rally, and the replay put weekly re-anchoring at ~6–8×
  the long grids' income. The owner: *"reanchoring is just trailing yes?"* — yes, and
  v3 had deleted it. Decided, in the owner's words: **the slide** ("i think the slide
  would work well"): drop rungs at the near end, add the same number at the far end,
  spacing and lot unchanged, the lattice unchanged (G17). Trigger: "N rungs past"
  (G18). Direction: favourable only — long slides up, short slides down; *"if i ever
  want to trail down i can just adjust the settings within the config file"* (the D10
  path stays for the adverse side). Inventory untouched (G20). Clamp required (G19).
  On hysteresis — *"we will need some form of hysteresis. but we have had problems
  with it before"* — the answer is that a ratchet needs none: it never returns, so it
  cannot flap; the trigger count is the only band. Not built: extend (the infinity
  grid — capital grows without bound) and widen (every lot changes; the replay says
  wider earns less). The rule lives in the pure planner, not the ops layer, so the
  backtester replays the real rule (T3/T6). Wiring order, agreed: decision → spec →
  backtester fidelity → replay of the real rule → the live bot. Until the live bot
  carries the offset, a fleet row with `slide` is refused by name.
- **D29 — Leverage is the operator's, never a rule (2026-09-28).** Asked for a
  fleet-level leverage cap on slide rows (the 48-day replay at 75× was liquidated
  on one dip; 10× held), the owner: *"no rule on leverage, freedom, discipline and
  personal accountability are key here."* 3Commas has none either — a slider,
  generic tiers, no guard. The build's warning above 20× on a slide row stays a
  warning; no key, no refusal. Context: the same session named the engine's purpose
  — *"realistically i am trying to reverse engineer 3commas… i dont want to pay them,
  i wana build my own"* — and `docs/THREECOMMAS.md` is the ledger that follows from
  it: every open gap there gets its own D-number from the owner before it is built.

- **D30 — The 3Commas gap list is to be copied (2026-09-28).** Shown the ledger
  (`docs/THREECOMMAS.md` §4), the owner: *"i like all the things they have that we
  dont."* Read as: every item in §4, in its recommended order, is wanted — the
  build order is the ledger's, and each item still lands as its own PR with its
  own specs, named against this decision. The one exclusion is signals/webhooks/
  deal-start conditions, which D15 and D26 deferred in the owner's own words and
  which this sentence did not name; they stay deferred until the owner says so.
  Items the ledger marked "skip candidate" (fixed-quote lot, profit currency,
  custom price ladder, TP from base order, % of balance base order, price and
  volume gates, deal start delay, manual add-funds) are wanted too, last.

- **D31 — Trailing stops ride the venue first; bot-side only where the venue has
  none (2026-09-28).** The owner: *"for the trailing stops, lets make use of the
  exchanges trailing if they have it first, then lets make it the way you suggested
  if no venue function for it."* This extends M11/D23 (which refused trailing where
  the venue could not host it): where the venue hosts a trailing stop (Bybit's
  trailing stop, HL's none) it is set once and the venue moves it; where it does
  not, the engine carries v2's object — an activation price, then a fixed-distance
  trail from the best price since — with the two rules "no activation, no stop"
  and "a plain stop wins a tie". The bot-side trail is E3-honest: its high-water
  mark is re-derived from venue fills and marks on restart, never remembered. The
  ledger's item 9 is now decided; its spec IDs come with the PR.

- **D32 — Caps are opt-in; projections are informative (2026-09-28).** The owner:
  *"id like to make the capital and position cap infinite by default, and be able to
  set them for safety and discipline… it should be informative, not a cap that
  restricts the user… for the account wide setup, that too should not be restrictive
  unless the user sets it. it must be an opt-in function."* Applied, with one
  distinction the owner should veto if wrong: on a **grid**, `capital` is the lot's
  size (D8: lot = capital across the rungs) and cannot be absent; the **cap**
  (`max_position_base`) already defaults to the full ladder and takes
  `"unbounded"` — that stays. On a **martingale**, `capital` was the ceiling the
  series is refused against (M2); it becomes optional — absent, the validator
  derives it from the series and prints the number; present, it refuses as before.
  The watchdog's per-bot position bounds (F1/F2) become opt-in per bot; the account
  guards (staleness, mm_rate, equity floor, drawdown) stay as they are. The margin
  projection stays a log line and grows: per row, the combined notional, initial and
  maintenance margin of the whole ladder, and the fleet total — what the venue's
  order screen shows before one order, for all of them at once; in the build log,
  the readout and the panel. Any account-wide risk rule (open-risk fraction, round
  count, a stop required) is a fleet-file key that refuses only when set.
- **D33 — Cooldown after a stop, and a candle-close stop (2026-09-28).** The owner:
  *"CD after a stop loss is as good an idea as it is for TP, implement kind sir."*
  `repeat_cooldown_seconds` gains a sibling anchored to the venue's timestamp of the
  stop's closing fill, restart-proof like M13. The candle-close cool-down (Altrady's
  "Candle Close" mode) needs no kline feed: the engine already reads the mark every
  second, and a candle's close is the mark at the interval boundary, so the bot-side
  stop compares only the mark at each boundary of `confirm_candle` (e.g. `15m`)
  against the level; a wick inside the candle never fires it. The emergency stop
  that overrides it is the venue-side stop we already have (X3) at its own wider
  level — two levels, the venue holds the hard one. `confirm_seconds` (G21's
  pattern) is the "Time" mode beside it.
- **Skipped by the owner, same session:** the per-bot dollar kill (venue-side stops
  cover a position; the only case it adds — a losing streak across rounds — is
  cheaper as a stand-down after N losing rounds, offered, not built); Altrady's
  contradiction guard, the slide's funding rule, R/expectancy in the readout, and a
  separate entry-expiration knob (the limit entry's re-peg timer is the expiry).

- **D34 — The slide may go the adverse way too, opt-in (2026-09-28).** The owner:
  *"we should allow trailing down like 3c, the same reasons as previous — freedom,
  discipline, accountability."* D28's favourable-only ratchet stays the default;
  `slide.direction: both` lets a long window slide DOWN (a short's UP) when the ref
  sits `trigger_rungs` past the adverse edge, by the same confirmation and clamp. An
  adverse slide buys beyond the ladder's `capital` — new bottom rungs are new lots
  from the account's free balance, exactly 3Commas' 2023 trailing down "using the
  quote currency from your balance" — so it requires the cap lifted or raised (D32)
  and the margin projection says what the slid ladder now commits. The stop still
  follows the window (X8) and is still the off button (D1).
- **D35 — Exits pair per rung; the average-cost floor becomes the opt-in (2026-09-28).**
  The owner, on being shown that G5/G6 never sell below average cost plus fees:
  *"thats the fix we need. that was my intent from the beginning, even with the
  portfolio engine from awaaaaaaaay back. thats how every exchange grid bot works,
  and how 3c worked."* So: a grid sells each held lot one rung above the rung it was
  bought at, regardless of the position's average — the exit floor is **the highest
  held entry rung plus one gap**, derived from the venue (G7's held-rung knowledge),
  never from per-lot state (G12 stands). Every trip clears the fee by G16's rule on
  the gap; a same-rung exit (R9) is now a defect, not a ratio. `exit_floor: rung` is
  the default; `exit_floor: basis` keeps today's average-cost floor for whoever wants
  it (the 2026-08-06 spot lesson stays specced under it). The readout keeps the
  average-cost P&L (R2) — a per-rung trip books as a small realised loss against
  the average on the way down, as 3Commas' own docs say, and D8's split shows it.
- **D36 — A lot's exit rests where it was intended, until it fills or the bot
  ends (2026-09-28).** Shown that after an adverse slide (D34) the lots bought
  beyond the new window lost their exit rungs and G8 poured them onto the
  window's edge, and that 3Commas kept those sells as "virtual levels", the owner:
  *"they need to rest where they were intended to be exited indefinetly. and only
  closed when the user kills the bot. because we still hold that inventory, and i
  want it to be exited where it was intended to be exited."* Asked whether to keep
  them virtual instead, the owner agreed with resting on the venue first: it
  survives a dead process, cannot be skipped by a fast move and keeps its queue
  place, and the order count only matters with many bots on one symbol. So: every
  lot the bot's own fills prove keeps its exit one rung beyond its entry rung,
  wherever that lies on the lattice, sized to that lot; W3 keeps it resting; one
  cancelled from outside is re-placed when the mark returns inside the placement
  window (the virtual fallback). A lot that already has an exit keeps it while
  the mark jitters on its rung. A block the average pins is a fit, not a fact:
  it stays inside the window, and S5 stands.
- **D37 — The limit entry is a maker entry, chased until it fills
  (2026-10-02).** 3Commas' limit base sits at the best ask for a long (best bid
  for a short) and re-quotes every 40 s until filled, with no timeout. That
  price crosses the spread: it stops slippage, but the fill is still taker,
  and the ledger's reason for this item was fees (two-thirds of the 48-day
  run's fills were taker). Shown that, the owner chose to diverge: the base
  rests **post-only at the near side** — best bid for a long, best ask for a
  short — keeps its queue place while it is still the best price, and is
  re-quoted for what remains unfilled once it has rested
  `start_order_requote_seconds` (3Commas' 40 by default) and the book has
  moved away. The safety ladder waits for the base to fill; a partial fill
  gets its TP at once, because M3 never relaxes. `start_order_expire_seconds`
  (opt-in, Altrady's entry expiration) stands the bot down when a base has
  not begun to fill in time. `start_order_type: market` stays the default;
  3Commas' `limit` is refused by name, so nobody gets a taker fill under a
  limit's name.
- **D38 — The stop climbs the tranche ladder, and firing it ends the round
  (2026-10-02).** Copied from 3Commas classic (Altrady's follow-TP is the same
  shape): when TP1 fills, the stop moves to average entry plus fees; when TP n
  fills, it moves to TP n-1's price. The owner chose all three forks put to
  them: **firing ends the round, not the bot** — it is an exit, and `repeat`
  decides what follows, so X1 stays the only off button; **the full ladder**,
  stepping on tranche fills, so it needs `take_profit_tranches` (two or more);
  **venue first, bot-side fallback** (D31's shape) — Bybit's partial
  stop-loss where hosted, the engine watching the mark where not (HL this
  phase). Opt-in as `breakeven_ladder: true`. One protection per round, as
  Altrady makes it one choice: refused with `trailing_stop_pct`, and with a
  `server_side` or `position_sl` stop, which would share its row on the
  venue's stop book. v2's activation-% variant for single-target rounds is not
  part of it.
- **D39 — The watchdog pages only, and waits its turn (2026-10-02).** The
  owner: *"page only for now, fewer pages and less to maintain"*; then *"keep
  the watchdog off for now. im happy to work with you here and finish the
  program, then we can work on our agentic workflow"*; and *"the opt ins must
  be a feature."* So: the watchdog never acts. Its timers stay off until the
  owner says otherwise. D32's opt-in per-bot bounds are built now (F1), and a
  breach reminds daily, not every half hour. The rest of the agreed shape — a
  daily digest built on the box, and a check-the-box routine for the assistant
  — belongs to the later agentic phase and is not built. An independent
  exchange read was considered and dropped: the snapshot's equity and margin
  are already a direct venue read, and staleness covers a dead fleet.
- **D40 — A bot is set up in plain words, two ways (2026-10-02).** The owner:
  *"how a layperson could easily configure a bot with our parametres… just
  like if a user was to set up on an exchange bot or with 3commas"*, keys kept
  out of the UI; then *"there needs to be a quick setup… but i want there to
  be an advanced setup so we can have every configurable part of creating a
  bot accessible through the UI."* So the panel gets a quick setup (a preset
  and three answers) and an advanced form held by spec to every config key,
  both ending in a plain-sentence summary before the existing four gates.
  This is also the ledger's presets item (D30, item 4), built in the panel
  rather than as files under `configs/`. The presets' numbers are the
  assistant's defaults, stated here for the owner's veto: grids span ±15 /
  ±10 / ±6% of price on 31 / 31 / 25 levels at 2x / 5x / 10x for careful /
  balanced / bold; rising and falling follow the price the favourable way
  only (trigger 2 levels, 15 minutes, at most 90 levels); DCA uses 6 / 5 / 4
  add-on orders covering about 19 / 11 / 6.5% at 2x / 3x / 5x, each 1.5x the
  last, taking profit at 1.2 / 1.0 / 1.0%. The stop loss is a tick box, off by
  default (D32).
- **D41 — Maximum rounds, copied from 3Commas (2026-10-02).** Asked "3Commas
  has maximum trade iterations: the bot opens N rounds, lets the last one
  finish, then switches itself off. Build it the same way?", the owner chose
  **copy**. `max_rounds` counts rounds OPENED since `max_rounds_since`, as
  theirs counts from the moment the setting is switched on. Where theirs is a
  counter on their server, ours is read from the venue's fills, so a restart
  cannot lose count; that is why the moment is written in the row, and the
  panel stamps it. The losing-streak variant offered beside it was not chosen.
- **D42 — A stop may end the round instead of the bot, opt-in (2026-10-02).**
  Asked whether to add 3Commas' "close the deal, keep the bot" beside D1's off
  button, the owner chose **add it as an opt-in**. D1 stands as the default:
  a stop flattens, cancels, kills, tombstones. `stop.action: end_round` on a
  repeating martingale closes the round at market and lets M5 open the next.
  It takes its level as 3Commas does, a percent from the round's base order
  beyond the last safety order (`from_base_pct`), because an absolute level
  would fire at once or never on the next round. This is what gives D33's
  cooldown after a stop something to wait for: `stop_cooldown_seconds`.
  D33's timeout is built with it (`stop.confirm_seconds`), and D33's
  candle-close mode and wider venue-side emergency level the same day
  (`stop.confirm_candle`, `stop.emergency_pct`; X12).
- **D43 — A stop may leave the position, opt-in (2026-10-02).** Asked whether
  to add 3Commas' "stop the bot and leave the position open", the owner chose
  **add as opt-in**. D1 stands as the default. `stop.action: leave_position`
  cancels the bot's orders, tombstones it and sells nothing; the kill line
  says the position is left open, unprotected and the owner's. Refused beside
  any stop the venue itself holds, which would close the position anyway.
- **D44 — Maximum hold period, copied, opt-in (2026-10-02).** The owner chose
  **copy**: a martingale round still open `max_hold_seconds` after its first
  fill closes at market, in profit or loss. The clock is the venue's fill
  time, so a restart cannot reset it. It ends the round; `repeat` and
  `max_rounds` decide what follows.
- **D45 — Expansion stays skipped (2026-10-02).** Asked again with 3Commas'
  Expansion Down/Up in front of them, the owner kept the earlier answer: the
  slide covers the ground, and the capital it could use is unbounded.
- **D46 — Telegram commands wait for the agentic phase (2026-10-02).** The
  relay stays read-only for now; the panel is the control surface.
- **D48 — The panel may close what a stopped bot left open (2026-10-03).**
  After the first live `leave_position` stop left a short on the demo account
  and the assistant closed it by hand at the owner's request, the owner said
  *"yes add the close position button."* It is the panel's one act that
  reaches the venue, and it reaches it the way the readout does: the panel
  runs the engine's own command as a subprocess and holds no key itself. Only
  a tombstoned bot's position, only a reduce-only market order for what the
  venue says is held, typed confirmation, never mainnet, not spot.
- **D49 — Leverage and terms change on a running bot, through the venue
  (2026-10-03).** The owner, on seeing leverage missing from the cards and
  thinking of Pionex: *"it would just need to interact with the exchanges
  leverage changing mechanisms… if the margin available doesnt allow it, or the
  venue has leverage caps on certain position values, it could reject and give
  the same warning that the exchange does. as for the margin, that too could be
  derived from the MM margin posted on each position from the venues side."*
  So: the card states investment and leverage (U16) and the venue's own IM and
  MM on the position (V14); and a running fleet applies an edited row's TERMS
  without a restart (F12): leverage goes to the venue first and a refusal is
  said in the venue's words with nothing of that row applied; a change to what
  a bot IS, its lattice or a martingale's ladder still waits for a restart.
  Per-position margin add/remove the Pionex way is **not wanted**: the owner,
  the same day: *"the way pionex does it uses iso mode… leave it the way we
  have it… we took what i wanted from them, and kept what i wanted."* Cross
  margin stays; a bot's ring-fence is the account it runs on.
- **D47 — The most a bot may lose, opt-in (2026-10-02).** The owner, thinking
  about Expansion: *"how about we add a max risk set to the creation. it can
  be optional, but that could be a function that does cap it."* Exposure is
  already capped by `capital`; what had no cap was the money lost, and the
  per-bot dollar kill skipped on 2026-09-28 (D33's note) is that cap. Asked,
  the owner said *"yes build the max loss limit."* `max_loss` is quote money:
  when the bot's own result since `max_loss_since`, closed and open together
  and after fees, is down that much, it flattens and stands down, whatever
  its stop's action says. Counted from the venue's fills, as D41 is.

- **D50 — The step optimiser is the rehearsal, swept (2026-10-03).** Ledger
  item 11. 3Commas' *AI Optimize* picks the grid step from a backtest and scores
  profit per grid, opaquely. Measured first on the demo SOL long over 30 days of
  5-minute candles: the rung count has a real optimum and a plateau around it
  (net within 5% from 15 to 25 rungs; fees rise from 1% to 20% of profit as the
  grid gets finer). Offered copy or diverge, the owner chose the transparent
  sweep scored by **net** (grid profit − fees, funding when given): the range
  exactly as set, only `rungs` moves, every candidate is the real planner over
  the same candles (T3/T6), the whole table is shown, the best is named and so
  is the plateau. Per-trip as the score was declined — on the same sweep it
  picks the fewest rungs (16 trips in a month). A gap inside the round-trip fee
  is skipped by name (G16); what is written for one rung count (weights, a
  seed) is set aside and said. Nothing is applied: the number is typed into
  the form. CLI `--optimize`; the rehearse forms' "find the step" (T8).

- **D51 — The watchdog's timers are on for the soak (2026-10-04).** Amends
  D39's "off until the owner says otherwise": the owner, asked at the end of
  the infrastructure pass, chose *"turn both on now."* Everything else D39
  decided stands: the watchdog pages and never acts; one page per breach, a
  daily reminder, the clear announced; per-bot bounds opt-in and none set;
  the digest and the check-the-box routine stay with the agentic phase. Both
  watchdogs were run once by hand first and reported no breach (the HL state
  carried one stale per-bot alert from September, which cleared); the demo's
  drawdown alarm measures from September's high-water of the account, so it
  sits about 25% under that, not under tonight's equity.
- **D52 — One bad row, the rest start (2026-10-04).** Amends D7 (and D27's
  default) from the rules review: *"D7 one bad row, rest start. its as simple
  as going into the terminal, or editing the control in UI."* A row that
  fails validation or its preflight probe is set aside by name with its
  refusal, builds dead-and-visible, and the rest of the fleet starts; only a
  fleet with nothing left to run refuses. `max_failed_bots` stays as the
  opt-in the other way: a stated N refuses past N bad rows, 0 is the old
  all-or-nothing. The shipped fleets drop their explicit 0. The 2026-10-02
  incident — one test row's probe refused thirteen bots at preflight — is
  the case.
- **D53 — The pace is the fleet file's, per venue (2026-10-04).** Amends D22
  from the rules review (*"d22 do it"*): the units pass no `--interval`; each
  fleet file's `poll_seconds` is its pace — 1 on Bybit demo, 2 on Hyperliquid
  testnet. Measured 2026-10-04: at a 1-second interval the HL fleet lost about
  one bot-cycle in a hundred to the venue's rate limit after a 2-4-8 s retry
  ladder and cycled every ~5 s regardless. The number is a starting point; the
  lost-cycle rate after the next HL restart says whether it moves.
- **D54 — The reversal grid is two halves split at a static mid (2026-10-05).**
  Ledger item 8, held 2026-10-03 as *"a deal of work with a few important
  decisions"*; the owner took the three recommendations put to them (*"i like
  your reccommendations"*): **the two-leg shape first** — a long grid below a
  mid and a short grid above it, on a venue that holds both sides of one
  market (Bybit hedge mode), which is a preset and no engine change; **the
  mid is static** — the owner's number, today's mark by default; the slide is
  the human-shaped follower and v2's moving-average logic stays retired;
  **built now** as the quick setup's "Reversal (neutral)" preset, the two
  legs made one after the other through the same gates and the same typed
  name, each half the investment and half the rungs. Hyperliquid holds one
  position per coin and refuses the pair by name; the single flipping
  position for one-way venues is **parked** until one asks for it.

- **D55 — The ladder's first step is the owner's to place (2026-10-05).**
  From the review of what remained: breakeven offsets *"should be an option,
  the user should be able to choose how to take the hit."* Opt-in as
  `breakeven_offset_pct`, a signed fraction of the average for the ladder's
  first step: below zero gives the trade room at a small loss, zero is
  breakeven before fees, above zero locks a minimum profit; blank keeps
  D38's fee-covering default. Refused without the ladder, and at or beyond
  the first tranche's own target (the stop would sit where the price has
  just been and fire at once). Later steps still climb to the previous
  tranche's price. Hot (F12).

- **D56 — An account cap, opt-in, in maintenance margin and notional
  (2026-10-05).** The owner: *"i dont want my acct to go above N MMR /
  notional USD / collateral used. id say MMR and notional would be the best
  to use. these should be opt-in."* A fleet key, `account_caps`, with
  `mm_rate_max` (the venue's own maintenance-margin rate) and/or
  `notional_max` (every living bot's position at mark, in the quote coin).
  At the cap, nothing that adds exposure rests or is placed — grid entries
  are withdrawn, no seed, no new martingale round or safety — and every exit
  keeps working, so the account leaves the cap by the bots' own selling,
  never a forced close. One event when reached, one when cleared. The kill
  at a higher line stays the job of the per-bot `max_loss`, and of Bybit's
  own All Futures TP/SL, which the owner sets by hand (it has no API).

- **D57 — Risk profiles, opt-in, like the quick presets (2026-10-05).** The
  owner: *"risk profiles could be like the quick setups we have, opt in as
  well."* A fleet may carry `risk_profiles`, named bundles of limits only —
  leverage, stop, max loss, max rounds, max hold, position cap, stop cooldown,
  trailing, the breakeven ladder and its offset — never what a bot is. A row
  opts in with `risk_profile: "<name>"`; the profile fills only what the row
  leaves blank, the row always wins, and the merged row is judged by the
  validators like any other (a profile with `max_loss` still needs the row's
  `max_loss_since`). An unknown name or a non-limit key is refused by name.
  Changing a profile reaches its bots at the next restart, or live for the
  hot keys (F12).

- **D58 — A spot bot owns only its own coins (2026-10-05).** The owner wants
  *"to see how a light margin spot fleet works alongside my perpetual position
  bots"* — on one account, BTC and ETH, where the wallet's coin balance also
  holds the inverse bots' settled profit and dust. Amends V6 (the wallet's
  balance IS the position) for rows that do not adopt inventory: a spot bot
  holds the smaller of its own fills (entries less exits, by link) and the
  wallet. Surplus coins are not its; missing coins are gone whoever took
  them, and D1 judges that as ever. The wallet is also the lag tell: a rise
  of half the bot's smallest lot that its listed fills do not explain is its
  own fill in flight, and nothing is placed or cancelled until it is listed;
  past the G26 wait it is said once as an outside hand's coins. A row stating
  `assumed_avg_entry` still adopts the wallet's coins as its own (V6).

- **D59 — A DCA bot on margin spot, long, on Bybit (2026-10-05).** The
  owner asked for BTC as a spot DCA bot in a light margin-spot fleet, *"make
  it to your specs."* `market_type: spot` is now open to the martingale
  with `spot_borrow` and `spot_leverage` (1–10, D24's pair; `leverage`
  itself is refused there). Spot holds no position TP and has no
  reduce-only, so the round's exit rests as a plain sell the bot knows by
  its link (the venue-less shape D21 gave Hyperliquid); trailing and the
  breakeven ladder run bot-side. Long only this phase — a spot short borrows
  the coin itself; Bybit only. Its holding is its own coins (D58).

- **D60 — The phone carries what needs the owner now (2026-10-05).** The
  owner: *"cut the random churn from buys and sells, unless it is tied to a
  more important function at that time. startup seems important enough to
  keep. warnings, but some are spam … the more impactful warnings that need
  my immediate attention, or that could cost me $. keep emergencies."*
  Telegram gets: every stand-down (kill), margin refusals and backoffs, the
  startup lines, the watchdog and unit-down pages, a round ended by a stop
  or at a loss, and the warnings marked urgent where they are raised (an
  exit or stop the venue refused, a position left without its exit). A
  fill, exit, take-profit placement, round turn or slide is the log's and
  the ledger's, not the phone's. A warning not marked urgent that repeats
  for the same bot reaches the phone once as persisting (the SUI exit
  refused 286 times, 2026-10-05). Everything still prints; nothing is
  dropped from the log. Amends the verbose-during-the-build standing.

- **D61 — Reading commands over Telegram, read-only (2026-10-05).** The
  owner asked what can be read from the phone and agreed the list: P&L
  (now and kept, per exchange and per bot), the day, positions, orders,
  rounds, grids, risk, status, and the trimmed alerts and a bot's log on
  demand. Owner-only, fail-closed, answered from the box's own files and
  read-only venue reads — no Claude, no write of any kind. Anything that
  changes something waits for the agentic phase.

- **D62 — A daily digest before Asia opens (2026-10-05).** The owner: *"give
  me the daily digest before asia start, around where NY/USA closes …
  approx 0800am … perth time."* Once a day at 23:58 UTC (07:58 Perth),
  after the archive, before Tokyo's open: the UTC day's P&L per exchange
  (the day, now, and kept), rounds and trips, fees, anything that paged,
  and the health of the fleets and timers. One message.
- **D63 — Funding is its own line (2026-10-06).** From the audit of every
  displayed figure against the exchanges: positions, average entries,
  realized, fees and unrealized all matched to the cent, and funding was in
  none of them — on Hyperliquid testnet one bot's total read about twice its
  true figure, another a profit that was a loss. The owner: *"fix all three,
  funding as its own line is the D-number."* Funding paid or received is
  read from each exchange's own record (Bybit's Funding executions,
  Hyperliquid's userFunding), booked to the bot whose leg it was charged on
  over that bot's own window, shown as its own part, and added to every
  total: total = realized − fees + funding + unrealized (Binance's futures
  grid states it the same way). Unread funding is said, never a zero. The
  digest's day line, built from kept fills alone, says it is before funding.
- **D64 — Real money gets the whole panel, with two guards (2026-10-07).**
  Offered a real-money fleet kept off the panel at first, the owner:
  *"ultimately, for real money this would be best if it had the UI features
  that the demo/testnet fleets get. otherwise building the dashboard seems
  pointless."* So a Mainnet fleet gets every panel feature. Its fleet file
  lives on the box beside `.env` — never in git, since its rows are real
  sizes — with a private backup off the box; it is never flowed back (U19).
  Two guards: on a Mainnet fleet a new bot's capital, and an edit raising
  capital or leverage past double, are typed a second time (the gates pass
  a valid number; only the second typing catches 50000 meant as 5000); and
  Mainnet is shown in red wherever it appears (D65).
- **D65 — The network is shown everywhere and set nowhere in the panel; real
  money runs from a pinned copy (2026-10-07).** The owner: the demo/mainnet
  value is *"only able to be configured from the actual file itself"*; the
  dashboard needs *"some form of indicator… an instruction on demo and main
  trading and the requirements"*, without the exact how-to; labels as each
  exchange names its networks. So: no panel code names the switches (a spec
  holds it); every fleet heading carries its network in the exchange's words
  (Bybit Demo Trading / Testnet / Mainnet, Hyperliquid Testnet / Mainnet),
  read from what the running fleet connected to, Mainnet in red; a page
  explains the networks and what real money asks for, and does not say how
  to arm it. And two copies of the code: the play-money fleets run from the
  one every deploy updates; a real-money fleet runs from a second copy that
  moves only when the owner promotes a version that has run on play money —
  with a hotfix path the same day, so a fix is never locked out (the owner:
  *"we must be careful that we dont block you out of fixing bugs"*). Built
  and rehearsed with a testnet fleet standing in; no live key exists until
  the owner chooses to go live.
- **D66 — Bybit first, on a dedicated small subaccount, when the owner
  chooses (2026-10-07).** The engine is most mature there (stops and
  take-profits rest on the exchange), its books are deep, Hyperliquid stays
  testnet-only by the owner's word, and the main account is not a testing
  surface. The subaccount's keys are minted fresh — trading only, locked to
  the box — at that time, not before.
- **D67 — Market readings, display only (2026-10-07).** The owner, on the
  old portfolio engine's market report: *"is there anything like that we can
  build better and use. like some good data to read"* — then *"lets do it. i
  would also like regular TG notifications as readable data as well. similar
  to how it was."* What a grid or DCA operator wants to know about each
  market the fleets are on, read hourly from public endpoints and kept
  beside the day's readout, so a reading can later be set against the bots'
  own results: the regime (ADX, ATR on 4 h candles), how crowded a side is
  (long/short accounts, funding, open interest), how thin the book is
  against what the fleet puts there (the HYPE lesson), fear & greed, funding
  on the other large venues as the reference a demo or testnet rate lacks,
  and Bybit's notices that name a fleet coin or a delisting. Paged at the
  three session opens — 00:00, 08:00 and 16:00 UTC, as the old report was —
  and on `/market`; a block in the digest and a line on each card follow.
  Nothing acts on a reading: that is the signals phase (D15/D26), and this
  is its measured foundation. Public endpoints only; the panel stays keyless.
- **D68 — A public edition for testers (2026-10-07).** The owner: *"is there
  a way to make a public facing version of this repo for a trading group i
  am a part of? id like to get some colleagues using the demo and testnet
  versions"* — then *"go with your recommendations on all four, build it.
  but leave some fleet examples there."* A separate public repository,
  written from this one by `ops/public_export.py`: the code, the specs, the
  ops templates, SPEC, DECISIONS and the ledger; not the journal, the
  archive, the backlog, the soak and promotion sheets, the real configs or
  anything local. Example fleets of small sizes, every mechanic shown once,
  stand where the real configs were. The edition flag is set in the written
  tree, and with it real money is refused flatly in code, whatever a file or
  a flag says — the networks page explains and never arms. A hygiene scan
  refuses an export carrying a host, a path or a name of the owner's own.
  Testers are shown setup by a doctor (`python3 -m gridgremlin.doctor`) that
  says what is missing and what is next, by the panel's own first run, and
  by a short guide; findings come as issues in the shapes the README asks
  for. Both exchanges. **Licensed Apache-2.0** the same day: offered the
  shapes, the owner — *"im just a nerd who likes building… i wana let these
  other nerds do their thing if they want"* — chose the permissive one:
  use it, change it, build on it, keep the notice; contributions come under
  the same licence by its section 5, each commit signed off (DCO). The
  NOTICE says what it is and is not: software, not advice and not a service.
- **D69 — The breakeven stop arms on profit, v2's activation (2026-10-08).**
  Granted on the "not built" list — *"D69 D70 D71 all granted. i like your
  ideas."* D38 built the ladder, which arms on the first tranche and so
  needs tranches; a single-target DCA round had no breakeven protection at
  all. `breakeven_activation_pct`: once the round is that far in profit, the
  stop arms at the ladder's first step (D55's offset, else G6's fee floor)
  and stays — one target or steps alike. The same stop machinery (M17:
  Bybit's partial stop-loss, HL mark-watched, firing ends the round). One
  arming rule and one protection per round, as D38: refused with the
  ladder, with a trailing stop, and with a server-side, emergency or
  position_sl stop; refused at or beyond the take-profit (it would never
  arm) and with the offset at or beyond it (it would fire at once).
- **D70 — A holding cap: the most bots that may hold at once (2026-10-08).**
  Granted with D69. 3Commas' "max active deals", fleet-wide: D56 caps the
  account's margin and notional, not how many bots may be in a position
  together, and in a dump every long loads its ladder at once. `holding_max`
  joins `account_caps`: at the cap a flat bot opens nothing — no base order,
  no seed, no entry — and says so on its card; the bots holding keep their
  safeties and exits, so the count falls by their own closing, never a forced
  close (D56's shape). Reached and cleared are each said once. Dead bots do
  not count; the three legs are independent and any one caps.
- **D71 — A sliver tranche folds; a refused exit does not abort the rest
  (2026-10-08).** Granted with D69. M25's open half: on 2026-10-05 the half
  under HL's minimum was asked for and refused 286 times, and the refusal
  aborted the loop, so the other exit was not written either. Now a tranche
  under the venue's minimum folds into the next target out (else the one
  before), the holding still covered whole, said once; and a venue refusing
  one exit's order no longer stops the others — the rest are written, then
  the refusal is said. Both venues; a lone tranche is left as it is.

*Source documents: the owner's response file (local), the 2026-08-04 Q&A, and the
2026-08-05 morning directives. Scrutiny was invited; scrutiny applied is recorded
inline above.*
