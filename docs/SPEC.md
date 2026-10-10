# SPEC — the invariants

**Status: decided, 2026-08-04 — every former ⚠ DECIDE is resolved; the record of who
decided what is `DECISIONS.md` (D-numbers cited inline). Numbering is stable** — cite
IDs in reviews, commits, and conversation. Each line is one statement that is true or
false, with its source (an incident, a decision, or a study — see `archive/research/`). The linkage
to the suite is the NAME: each spec function carries the ID it pins
(`spec_G7_...`), greppable in both directions.

Rules of this file: one sentence per invariant · unit named where one exists · nothing
enters the code that isn't stated here first · nothing is stated here that a spec can't
eventually pin (T1).

---

## E — the engine core

- **E1** `plan(config, truth)` is pure: no I/O, no clock, no randomness, no module state.
  *(DESIGN §0; what makes backtest parity and every golden test possible)*
- **E2** `apply()` is the only writer; cancels run before creates.
- **E3** The exchange is the only durable state: every in-memory quantity is either
  derivable from venue + config or explicitly documented as reset-on-restart. Two
  narrow local facts are the stated exceptions, each because the exchange cannot
  express it: the tombstone (X7) and the slide window's offset (G22). *(OPERATING
  idea 1; the restart-resets list in v2-history §2)*
- **E4** `plan()` is lookahead-free: the same truth prefix produces the same orders
  regardless of what data follows. *(freqtrade study — "the single highest-value steal")*
- **E5** A partial truth read is an error, never a result — refuse and retry, don't
  truncate. *(the order-runaway incident, 2026-07-30)*
- **E6** The engine reacts to error *kinds*, never venue codes; `ambiguous` means "the
  write may have landed" and defers to the next truth read.
- **E7** No error kind kills: every kind maps to retry, backoff, skip, or warn;
  stand-down happens only by stop rule or operator. This holds at the fleet loop
  too: a failed read or venue error costs the cycle, never the process — no
  snapshot is written for a lost cycle, so a persistent outage still raises the
  watchdog's staleness page. *(two overnight TLS resets killed the HL unit,
  2026-08-05)*
- **E7b** A refusal for a position that just closed is the close, not a fault.
  Bybit answers a stop/TP write for a position it has just closed with retCode
  10001 "can not set tp/sl/ts for zero position"; that sentence (10001 alone is
  generic) is the kind `flat`, reacted to as done — no warning; the next read
  sees flat and M5 decides. *(2026-10-05: two warns at every tranche round's
  end on the live breakeven-ladder row)*
- **E8** Unknown is not flat: a failed startup read refuses to trade. *(nautilus TAKE)*
- **E9** A DEGRADED answer is not a fact: an empty positions list and a genuinely
  flat position are indistinguishable, and a hollow wallet payload is unknown equity,
  never zero. No irreversible action (kill, tombstone, cancel-all, stop-fire) may be
  taken on a single such read — flat is confirmed across consecutive reads, and
  unknown equity fires nothing. *(audit 2026-08-06, demonstrated: one empty read
  killed a holding grid and abandoned its position)*
- **E10** The venue READS ride one kept HTTPS connection per host; writes keep a
  fresh connection each. Only a stale failure (the server closed the idle kept
  connection, so the request never reached it) on a REUSED connection is sent
  again, once, fresh — a timeout or a fresh connection's failure raises as before.
  A 4xx/5xx raises urllib's HTTPError, so every caller's handling (HL's 429
  ladder) is unchanged. *(measured on the box 2026-10-06: a Bybit truth read was
  five requests and 71 ms of CPU, 84% of it opening connections; a request on a
  kept connection costs about 1 ms)*
- **E11** Writes are paced, reads are not. The Bybit write client holds a
  floor of 120 ms between its posts, so a fleet's start spreads its ladders
  over seconds instead of bursting them into the venue's per-second budget;
  and it reads the venue's budget headers after every post — a spent budget
  names its refill moment, and the next write waits for it (five seconds at
  most, never a minute). The backoff (B7) still answers a refusal that gets
  through. *(thirty orders in the carry sub's first minute met 10006,
  2026-10-08; Hyperliquid's own weights are the open half)*

## A — contract maths (the adapter seam)

- **A1** Everything instrument-shaped is asked from the exchange at startup, never
  declared in config.
- **A2** Quantity rounding always floors — never place more than intended; price rounds
  to tick.
- **A3** One `placeable(qty, price)` predicate at plan time folds min-qty, qty-step,
  min-notional, and affordability; an unplaceable order is never intent. *(hummingbot
  counter-example)*
- **A4** Units never mix: inverse PnL is base-coin, never summed with quote PnL.
  *(v1's +$396k bug)*
- **A5** `position_idx` derives jointly from (side, reduce_only).
- **A6** The adapter seam exists from day one even with one venue; a second venue is a
  slice, not a fork.

## G — the grid

- **G1** The lattice is computed once from `{lower, upper, rungs}`, tick-rounded; price
  never moves it. A slide (G17–G19) moves the *window* over the unchanged lattice by
  whole rungs, on a trigger, never continuously. *(v1's central bug; §5d; D28)*
- **G2** Exactly one of {count, spacing} is given, the other derives, and the stored pair
  is reconciled — the config never carries a spacing the lattice doesn't have. *(config
  study M9)*
- **G3** N rungs span N−1 gaps; the divisor is load-bearing. *(GRID-MATHS §1)*
- **G4** The lot is the one canonical inventory unit, priced at the split ref in every
  position state; exit ladder, cap headroom, and entry suppression all count in it.
  *(D5; CONCEPTS §12·N2)*
- **G5** Entries rest only on the entry side of the split ref; exits only beyond the
  floor — G23's per-rung floor by default, G6's basis floor under `exit_floor: basis`.
- **G6** *(the opt-in, `exit_floor: basis`)* The exit floor is `max(ref, basis × (1 +
  fee_floor))`, and the fee floor is VENUE-SHAPED — spot charges roughly ten times a
  perp per side, so one constant rested spot exits that lose money on a round trip
  *(audit 2026-08-06)* — the grid never sells below cost plus fees; the fee floor is a
  constant, not a knob. Under this mode suppression is the count proxy (G7's second
  sentence). Superseded as the default by D35/G23.
- **G7** An entry rung never re-arms while its lot is unexited — observable from arming
  order, entry side only. *(the owner's invariant; the stacking incident, 2026-08-02)*
  By IDENTITY under G23: the held rungs are known, and exactly they stay suppressed.
  By COUNT under G6: the n nearest entry rungs below the ref stand in for n held lots
  — a proxy that is wrong by one rung per lot on a descent (measured 2026-09-28: a
  ladder bought 60k, 58k, 55k, 51k), suppressed every rung below a seed, and flipped
  on every wobble across a rung (the churn B2 was built to cure).
- **G8** The exit ladder covers the sellable position one lot per rung, nearest-first;
  remainders fold without creating sub-lot rungs; the nearest exit sits within ~one rung
  of the mark. *(the dead-band incident, 2026-07-31)*
- **G9** The floor (`min_position`) core is never offered for sale; the cap measures
  *held* while the ladder covers *held − floor* — two named quantities, never one
  variable. *(the overnight cap failure)*
- **G10** Entry headroom is whole lots under the cap; zero headroom stops entries and
  nothing else.
- **G11** Out of range the grid idles — it never chases; it ends only when its stop
  fires or the position is closed from outside (S7). With `slide` configured, "out of
  range" in the favourable direction is the G18 trigger and the window follows; the
  adverse direction still idles (the stop is the off button, D1) unless the row
  opted into G24. *(§5d; field consensus; D1; D28; D34)*
- **G12** The engine is netted (Camp B): the ladder re-derives from the net position;
  no per-rung paired state exists anywhere. *(decided 2026-07-20; ALIGNMENT §1)*
- **G13** No planned order is ever marketable — in any position state, including every
  adoption case: entries only below the ref, exits only above their floor, the cross
  guard drops anything near the opposite quote, and post-only is the venue-enforced
  backstop (a crossing order is rejected, never filled). Pinned by sabotage: with the
  split or the floor removed, the guard and the venue must still refuse. *(the owner's
  adoption concern, 2026-08-04; D6)*

- **G15** A venue that reports no average entry (spot: the position IS a wallet
  balance) still knows the cost — the basis is derived from its own fill history, so
  the exit floor always has something to clear. Without it the floor collapses to the
  split ref and exits rest at the very price the inventory was bought at: the grid
  churns at zero spread and pays fees both ways. `assumed_avg_entry` wins when set.
  *(measured live 2026-08-06: 17 LTC round trips, every buy and sell at one price)*
- **G16** A grid whose rung gap cannot clear the venue's own round-trip fee loses on
  every completed trip by construction — the build asks the venue what it charges and
  says so, before a single order rests. *(the spot fee lesson, 2026-08-06)*
- **G17** One lattice, many windows: the home range defines an unbounded lattice
  (geometric or arithmetic, extended past both ends by the same rule); a window is N
  consecutive absolute indices starting at an `offset` (home: 0). Rung ids in plans and
  order links are absolute indices, so a slid window's overlap keeps every resting
  order's identity — only the rungs that left the window are cancelled, only the new
  ones placed. Endpoint N−1 is `upper` exactly in every window. *(D28; the 48-day
  post-mortem)*
- **G18** The slide is a ratchet: the window moves only when the split ref sits
  `trigger_rungs` whole rungs beyond its far edge in the FAVOURABLE direction (long:
  above the top; short: below the bottom), then by whole rungs so the ref lands at
  `ref_position` of the range (0.5 default; 1.0 = the whole ladder on the entry side).
  By default it never retreats — a long window never slides down, a short one never
  up; the adverse side belongs to the stop (D1) — and G24 is the one opt-in exception. No band, no SMA, no snap home: the trigger
  count is the only hysteresis, and a ratchet cannot flap. Pinned by sabotage: with
  `slide` absent the same trend leaves the grid idle. *(D28; v2's trail retired by D10)*
- **G19** `max_rungs` clamps the window's offset from home in either direction; the
  clamp is required, never defaulted — an unbounded follower is a decision, not an
  omission. *(D28)*
- **G20** A slide touches no inventory: held lots keep their basis and their exits
  (G25 under `exit_floor: rung`; under `basis` the ladder re-derives over the new
  window by G6/G8), and nothing is sold to make room. In the
  favourable direction the trigger price lies beyond the old top, so the position is
  normally already exited when the window moves. *(D28)*
- **G21** A slide is confirmed, never instant: the trigger (G18) must hold on every
  cycle for `confirm_seconds` before the window moves, and a ref that returns inside
  resets the clock. Required, never defaulted — zero is a decision. The clock is
  in-memory and resets on restart (E3); the backtester honours it in whole bars (T6).
  Pinned by sabotage: at zero, one read past the trigger moves the house. *(the
  control replay: one 0.5% wick slid an ETH window for good — JOURNAL 2026-09-25)*
- **G23** Exits pair per rung (D35): a long sells each held lot one rung above the
  rung it was bought at, a short covers one rung below — regardless of the position's
  average. The engine stays netted (G12): WHICH rungs the lots came from is derived
  from the venue — the bot's own fills walked newest-first, LIFO, each link carrying
  its absolute rung (G17) — and, when the account cannot yet cover the holding
  (adoption, a lagging fill list), from the block the venue's average pins
  (`held_block`: the n contiguous rungs whose mean is nearest the average). The floor
  is the block's lowest rung (short: highest), bounded by the ref (G13); suppression is
  the block itself, and only when it lies wholly on the entry side of the ref — a
  seed (its fill carries `SEED_RUNG`, off every lattice) or a block across the ref
  suppresses nothing. Every trip clears the fee by G16's rule on the gap. A same-rung
  exit is now a defect (R9 reads zero), and the wobble churn of B2's fixture is gone
  without the band. The readout keeps average-cost P&L (R2): a per-rung trip on the
  way down books as a small realised loss against the average, as 3Commas' own docs
  say. `exit_floor: rung` is the default; `basis` keeps G6. *(D35: "thats how every
  exchange grid bot works, and how 3c worked"; the sparse-ladder and seed artefacts of
  the count proxy, JOURNAL 2026-09-28)*
- **G22** The window offset is the second narrow local durable fact E3 permits,
  beside X7's tombstone: written BEFORE the orders move (a crash mid-slide resumes
  at the new window, whose orders may already rest), read at build, clamped to G19
  and the row's side (both sides under G24); missing means home — safe, because every link carries its
  absolute index (G17), so a resting order outside home is cancelled or re-adopted
  by the same diff as always (a lost ratchet, never lost money). The file fails
  CLOSED like the tombstone; a failed WRITE never blocks the slide itself. One
  file per fleet (`logs/slide_state-<fleet>.json`, X7b's rule), each write
  re-read under the lock: on 2026-10-08 two fleets shared one file and the HL
  fleet's slide wrote back a copy taken before the demo's BTC, SOL and XRP
  windows moved — 28 rungs of a held position, gone from the file. *(D28;
  BACKLOG §6 PR B; the clobber 2026-10-08)*
- **G24** The adverse slide is opt-in (`slide.direction: both`, default `favourable`):
  the window also moves when the ref sits `trigger_rungs` beyond the ADVERSE edge (a
  long's bottom, a short's top), by G18's landing, G19's clamp (±`max_rungs`) and
  G21's confirmation; each move only goes the way the ref went. The new far rungs are
  new lots beyond `capital`, bought from free balance (3Commas' 2023 trailing down),
  so the row is refused unless `max_position_base` is lifted (`"unbounded"`) or set
  to a number — the default cap is the ladder's own size, which the old window's lots
  already fill, and it would stop the new rungs part-way (pinned by sabotage). The
  slide event names an adverse move; the build warns when a `mark_price` stop sits at
  or inside the adverse trigger (it fires first, D1, and the slide never runs), and
  the margin projection states each row's commitment at its clamp and the fleet line
  with it (D32: informative). Held lots beyond the slid window keep their own exits
  (G25). *(D34: "freedom, discipline, accountability"; JOURNAL 2026-09-28)*
- **G25** A lot's exit rests where it was intended until it fills or the bot ends
  (D36): every lot the bot's own fills prove (G23) keeps its exit one rung beyond the
  rung it was bought at, wherever that rung lies on the lattice — inside the window
  or left behind by a slide — sized to that lot at its own entry price, not at the
  ref. W3 keeps it resting; one cancelled from outside is re-placed when the mark
  returns inside the placement window (the virtual fallback). A lot whose own rung
  cannot be placed now (not beyond the ref, or inside B4's band) and does not
  already rest there takes the nearest free placeable window exit, so a mark
  jittering on the rung keeps the exit it has. Seed lots (no lattice rung) and the
  block the average pins stay inside the window — a fit never places an order
  outside it, and S5 stands — except that an own exit already RESTING outside the
  window is kept: once the fills age out of the history window (30 days), the
  venue order is the proof (E3). G8 still covers the whole sellable: a remainder folds
  onto the furthest exit. *(D36: "i want it to be exited where it was intended to be
  exited"; JOURNAL 2026-09-28)*
- **G26** The fills must account for the change before exits are re-paired. The
  venue's position moves at once; its fill list follows seconds later. Since the
  last derivation that added up, the NEW own fills must net to the change in the
  holding (2% plus one step of slack). While they do not, BOTH sides are frozen —
  nothing placed, nothing cancelled — because which lots are held is unknown either
  way: a missing exit fill re-places that exit, a missing entry fill re-buys that
  rung. The plan itself is left whole, so S5 still sees its exits. After `RUNGS_LAG_CYCLES` (20)
  the change is taken as one no fill of ours will explain (an outside hand, a
  venue close): one warning, and pairing resumes from the fills there are. The
  baseline is in memory: a restart's first derivation is not checked. *(measured
  live 2026-10-02: 21 of 93 trips at zero spread, 11 at a loss — an exit that had
  just filled was missing from the list, so its lot still looked held and its
  exit was placed again. The first cut froze exits only and planned entries from
  the last good account: over the next 3.2 hours no trip lost money, but 5 of 56
  still closed at zero spread, from entries bought twice)*

## W — the window
 When a lagging list catches up, the log says after how many cycles
  (log-only), so the lag is measured, not guessed.
- **W1** The window limits placement, never cancellation.
- **W2** One named window anchor, used by every consumer — no raw-vs-sticky split
  between the window and the planner. *(audit 3.4; CONCEPTS §12·N4)*
- **W3** A resting, still-planned order outside the window is left alone.

## B — bands and churn guards

- **B1** One mechanism per boundary, one name each; "deadband" and "hysteresis" appear
  unqualified nowhere. The only banded mechanism is the split hysteresis (B2): the
  no-trade behaviour is emergent (B9); trail is retired (D10) and its successor, the
  slide, is a ratchet with a rung-count trigger, not a band (G18, D28). *(ALIGNMENT
  §13.6; D6, D10, D28)*
- **B2** Split hysteresis: the split ref moves only when price has moved more than the
  band (a fraction of the *narrowest* rung gap), and then snaps to current.
- **B3** The cross guard — nothing rests within `max(spread, guard-bps of mid)` of the
  opposite quote — has exactly one implementation, shared by planner and placer.
  *(CONCEPTS §12·N6)*
- **B4** A rung whose exit already rests is exempt from the cross-guard drop; resting
  detection keys on side, never on reduce_only. *(the spot-exit bug)*
- **B5** A rung repeatedly placed-but-not-resting cools off; a rung whose position moved
  is trading, not flapping, and is never cooled. *(the actively-trading-rung bug)*
- **B6** Every cooldown is per-cause: distinguishable in state, in logs, and in events.
  *(CONCEPTS §12·N9)*
- **B7** Margin backoff halts growth only — cancels still run — doubling to a ceiling,
  retrying forever. The venue's cap on a position's value is a margin refusal
  too: Bybit's 110090 (the risk tier's limit on positions plus orders) classed
  as a rung's fault flapped every buy rung of a 28-rung adverse slide for 13
  hours, a page a minute *(2026-10-08)*; as `margin` the growth halts and the
  phone hears the backoff.
- **B8** Spacing must clear the guard band with stated margin, against the true
  minimum gap, not the mean — checked at BUILD against live quotes (the guard
  depends on the live spread), stated loudly rather than refused on a transient
  widening. Pinned as a pure function with no call site for 30 slices *(audit
  2026-08-06)*. *(the gold-grid measurement; strategy
  study D11)*
- **B9** There is no configurable no-trade band: the dissolving suppression around an
  adopted basis emerges from G7 + G9 + G6 — entries release furthest-from-mark first as
  exits fill, converging on the basis. v2's `no_trade_pct` family and the ratchet are
  retired. *(D6, the owner's dissolution description)*

## M — the martingale

- **M1** The martingale is the grid's ladder math run with different data: one
  direction, cumulative-prefix suppression, no per-rung exits — one implementation,
  zero duplicated formulas. *(audit 3.2/3.3)*
- **M2** The config speaks 3Commas' vocabulary — `base_order`, `safety_order`,
  order-size multiplier (of the previous order), `deviation`,
  `deviation_step_multiplier`, `max_averaging_orders` — and the validator expands the
  full series, refusing any ladder whose total exceeds `capital`, stating the number in
  the error. *(D11)*
- **M3** A round is never without an exit: the whole-position TP is set before the
  round rests, and a target the market has run through closes at the target or better
  via reduce-only marketable limit. *(the stale-target incident)*
- **M4** The round TP measures from average entry, recomputed as fills deepen, the
  basis named into the key. *(D12)*
- **M5** `repeat` re-anchors only from flat; an absolute TP is refused alongside it.
- **M5a** On a venue that hosts the position-TP, a TP fill and an operator's manual
  close are INDISTINGUISHABLE in truth (both leave flat with no owned order gone) —
  a repeat martingale there re-enters after a manual close; the watchdog's
  `assumes_sole_actor` is the assumption that makes this safe, and on the resting-
  exit venue S7 detects it properly. *(audit M1 — documented limitation)*
- **M6** Round state is venue-derivable: a restart adopts the resting TP and never
  rewrites a live round's exit. *(the restart-flattens-a-round incident)*
- **M7** The martingale carries no floor/cap/damping keys: its cap is the
  refused-if-over-capital series, a floor is meaningless under a whole-position TP, and
  damping guards a boundary it doesn't have — absence is derived, not missing. *(D14)*
- **M8** The martingale has no range bounds: ladder depth derives from the deviation
  schedule × `max_averaging_orders`, and the risk is stated as the required-capital
  number at load. The grid keeps its bounds. *(D13)*
- **M9** Staged beyond the skeleton, not in it: signal start conditions (owner-
  deferred — they do their own TA). *(D15; partials/trailing left via D23 → M10/M11;
  reinvest and the cooldown left via D26 → M12/M13)*
- **M10** A round's exit may be TRANCHED (D23): shares of one position at ascending
  targets, summing to one, every price re-anchored from the average as fills deepen —
  venue-hosted partial TPs where the venue hosts them, several D21 resting exits
  where it does not. A tranche the mark has PASSED is done — 'passed' measured against the
  best mark the ROUND has seen, so a fired tranche never resurrects when price
  retreats (audit 2026-08-06) — never re-placed below mark (the venue refuses those, correctly); the remaining shares renormalise over
  what is still held, and with every target met the remainder closes marketable at
  the deepest target, or better. The same law as M3, split into shares. *(the ADA
  re-anchor warns, 2026-08-05)*
- **M11** Trailing rides the venue or does not exist: set once per round from the
  average, the venue moves it from there; refused where the venue cannot host it.
  With tranches it arms only AFTER the first target fills — a trail tighter than
  the first tranche closes the round before it can take profit. *(measured live
  2026-08-06: 30 rounds averaging a small loss)*
  *(D23)*
- **M15** A round's anchor is recovered from the VENUE, never remembered: a
  resting safety order's price and rung invert the deviation schedule back to the
  base price. Re-anchoring on average entry after a restart deepens every remaining
  rung and un-suppresses rungs that already filled — past the capital the validator
  approved. *(audit 2026-08-06, demonstrated)*
- **M14** A round that ended by liquidation, ADL, or an outside hand is NOT a
  completed round: the venue's own account of the closing fill decides, and anything
  but our own exit stands the bot down instead of re-entering. Silence from the venue
  is never evidence. *(audit 2026-08-06: `repeat` walked straight back into what had
  just liquidated it)*
- **M12** Reinvest is a toggle (D26): on, the round's sizes scale by
  1 + realized-net/capital over the last 30 days of the bot's own venue fills
  (bounded — an epoch-0 history pull was ~3,000 requests, the audit's H1; the
  window is stated in the event), restart-proof by derivation — floored at 0 — and zero is a REAL factor that refuses the
  next round, never a falsy 'unset' that re-enters at full size (audit
  2026-08-06) — and CAPPED at 1.2, the watchdog ceiling's own headroom (F2); beyond +20% the owner raises
  `capital` in config, ceiling reviewed together. Grids reinvest only by that
  manual path; the key refuses on a grid, naming it.
- **M13** The round cooldown anchors to the VENUE's timestamp of the TP fill, never
  a process clock — `repeat_cooldown_seconds` after the last owned fill; a restart
  re-derives it; refused without `repeat`. *(D26 — "so martingale bots dont just
  spam an entry immediately after an exit")*

- **M16** The maker base (D37): with `start_order_type: maker` the base rests
  post-only at the near side as the entry side's rung 0, so a restart adopts it
  by identity and never reads it as a finished round. It keeps its queue place
  while it is the best price; once it has rested `start_order_requote_seconds`
  and the book has left it, it is cancelled — confirmed before the new one, E2 —
  and re-rested at the near side for the unfilled remainder. The round anchors
  at the price the base last rested at. Safety orders wait for the base to fill;
  a partial fill gets its TP at once (M3). `start_order_expire_seconds` kills a
  base that has not begun to fill in time (D1); a partial fill is a round and
  never expires. The entry clocks restart at first sight after a restart, so a
  restart can only delay a requote or an expiry. `limit` is refused by name.
- **M17** The breakeven ladder (D38): with `breakeven_ladder` on a tranche round,
  no stop rests until a tranche has fired (M10's own gauge). One fired: average
  entry plus G6's fee floor. n fired: tranche n-1's price. The level only
  tightens within a round. Hosted, it rests as ONE partial stop-loss sized to
  what is still held; a step or a size change clears the old row first
  (partial mode stacks). A restart adopts the venue's row and never loosens it.
  Unhosted, the engine watches the mark. The round's best mark is re-seeded on
  restart from the round's own exit fills, unwinding the holding back to flat,
  so a fired tranche is not re-placed and the step survives (M10 across a
  restart). With the mark through the level: a resting venue stop is left to
  fire; with nothing resting, the round's exits are cancelled first (E2) and
  what is held closes at market under our link, so M14 reads it as our exit.
  Firing ends the ROUND; M5 decides what follows (`repeat` off still stands the
  bot down). The round latch is set on fire, so a restart that fires at once is
  still a round that ended. Refused without two tranches, with
  `trailing_stop_pct`, or with a `server_side` or `position_sl` stop.

- **M17b** The ladder's first step is where the owner put it (D55):
  `breakeven_offset_pct` from the average — negative, zero or positive —
  else G6's fee floor; later steps unchanged. Validated below the first
  tranche's target and only with the ladder.
- **M17c** The stop arms on profit (D69): with `breakeven_activation_pct`, no
  stop rests until the mark is that far in profit from the average; then the
  ladder's first step (M17b's level) rests, sized to the holding, and only
  tightens — the mark falling back under the activation does not lift it; the
  mark falling through it ends the round. One target or tranches alike; refused
  with the ladder (one arming rule), with a trailing stop or a venue-row stop
  (one protection), at or beyond the take-profit, and with the offset at or
  beyond it. Unhosted, a restart re-arms when the mark is next in profit by
  the activation (M21's shape).
- **M26** A DCA bot on margin spot (D59): long, Bybit, `spot_borrow` with
  `spot_leverage` as its leverage; the round's exit rests as a plain sell
  recognised by its link (spot has no reduce-only and no position TP); base
  and safeties buy on borrow; trailing and the breakeven ladder are watched
  by the engine; the rehearsal replays it in its one position shape.
- **M18** `max_rounds` (D41, 3Commas' maximum trade iterations): after that many
  rounds have OPENED since `max_rounds_since` and the last has finished, the bot
  stands down for good (tombstoned, like any kill). A round opens at a rung-0
  entry fill and the next is counted only after an exit fill came between, so a
  re-quoted maker base is one round. The count is the venue's fills, asked when a
  round completes and when a process comes back flat; if the venue cannot be read
  nothing opens and nothing is killed. It reaches back at most the fills window
  (30 days). The two keys travel together and need `repeat`.

- **M19** `max_hold_seconds` (D44, 3Commas' maximum hold period): a round still
  open that long after its first fill closes at market under our own link, profit
  or loss, after its resting exits are cancelled (E2); M14 reads it as our exit and
  M5 decides what follows. The round's start is the venue's: the fills are walked
  newest first, unwinding the holding to flat. If the venue cannot be read nothing
  closes. At least 60.

- **M20** The remainder close is one order. When every re-anchored tranche target
  is already behind the round's best mark (a tranche filled, then a safety order
  did), the uncovered remainder gets one resting reduce-only limit at the deepest
  target (M3). It counts as cover on every venue, hosted or not, and rung 0 on the
  exit side is shielded from the ladder's diff on every venue (D21's shield,
  widened), so it is placed once, left resting, and the fill is announced once.
  *(found by T7's first run, 2026-10-03: twelve placements in twelve cycles)*

- **M21** The trailing stop the engine carries (D31): on a venue that hosts none
  (M11's refusal, lifted) `trailing_stop_pct` is a fixed distance, that fraction of
  the average, behind the best mark since the trail was armed. It arms at once; or,
  with tranches, when the first fills (M11's rule); or, with
  `trailing_activation_pct`, when the mark is that far in profit from the average:
  no activation, no stop. The trail belongs to one average: a fill that moves the
  average starts it again from the mark it finds. Nothing is remembered across a
  restart (E3): a new process trails from the mark it finds, or with tranches from
  the round's best exit fill. A plain stop is judged first and wins a tie. Firing
  closes the round at market under our own link (M14 reads an exit; M5 decides).
  Where the venue hosts the trail (M11) the activation price is handed to it.
- **M22** The tranche gauge belongs to one average, and a venue-fired round stop
  ends the round. (1) M10's "passed" gauge — the best mark the round has seen —
  starts again when a fill moves the average: a safety fill lowers every target,
  and measured against the round's old high those new targets read as already
  met, a tranche "fired" that never did, and the breakeven ladder (D38) armed
  above the mark and closed the round at a loss (replay 2026-10-03). Within one
  average the gauge stays monotone (M10). (2) The venue fills in price order: a
  hosted breakeven stop above a resting safety order closes the position and the
  safety fills a moment later, so the position is never flat for M5 to see and
  the bot read the net change as a continuing round. While a breakeven stop is
  known, the venue's own stop-loss close AFTER this round's base order is the
  evidence the round ended there: what is held is a stray — closed at market
  under our link (M14 reads an exit), the rest cancelled, M5 decides. Silence
  (no fill history) judges nothing.
- **M23** The last tranche takes what rounding leaves. Tranche shares round down
  to the lot step (two halves of 0.017 are 0.008 and 0.008), so a dust remainder
  had no exit of its own, and where the venue's lot is bigger than the dust the
  round could never end. The shares sum to the holding: every tranche but the
  last is its share rounded down, the last is the rest — to the NEAREST lot,
  since the rest of an on-grid holding is on the grid and float subtraction
  puts it a hair under (3.19 − 1.59 floored to 1.59 left 0.01 with no exit;
  replay 2026-10-04).
- **M24** A tranche exit shrinks the holding, not the ladder. M1 suppresses a
  safety rung when the holding covers the schedule's cumulative prefix; after a
  partial exit the holding no longer does, and the rung that already filled this
  round was placed — and filled — again, past `max_averaging_orders` and the
  capital M2 approved (replay 2026-10-04: 12 of 113 rounds). The venue's fills
  since the round's first fill (M19's walk) name the rungs that filled this
  round, read once per change of holding and unioned; a named rung is never
  re-placed. Only a tranche row reads; a plain round's holding is its prefix.
- **M25** A filled tranche is done even while the mark lags it. A resting exit
  fills on a trade and the venue's mark can sit under it: HL's `markPx` stayed
  below a filled TP1 for 286 cycles, so M10's gauge read t1 as unfired, the
  remainder re-split into halves, and the half under the venue's minimum was
  refused every cycle with no exit resting at all (live, 2026-10-05). When the
  holding shrinks within a round, the round's own exit fills (M17's restart
  walk) are prices it reached and fold into the gauge; a fill list still
  lagging the position answers nothing and is asked again next cycle.
- **M25b** A sliver folds; a refusal does not abort (D71). A tranche whose
  quantity is under the venue's minimum folds into the next target out, else
  the one before — the holding covered whole, said once per change; a lone
  tranche stays. In either placement loop a venue refusing one order leaves
  the others written; the first refusal is raised after the loop (a `flat`
  refusal still stops it: the round just closed).

## S — start states

- **S1** From flat, every basis-anchored mechanism is inert by construction — verified
  by identity, not by tolerance.
- **S2** Seeding is observable as already-done from the venue alone; a restart never
  re-seeds.
- **S3** Seeding is a config toggle for flat starts: a market buy covering the
  exit-side rungs implied by bounds + mark (lower in range ⇒ larger seed); on failure,
  refuse and retry with backoff; windowing governs which exits rest, never how much is
  seeded. *(D9)*
- **S4** Adopting: the venue's basis always wins; a basis is never invented, fills are
  never fabricated, and a position the bot cannot explain halts and alerts. *(nautilus
  REJECT of phantom orders)*
- **S5** An adopted basis beyond the range means no exits, one warning, and the position
  left to the operator.
- **S6** A restart re-adopts resting orders by identity with zero churn; every quantity
  that does reset on restart is on a named list with its consequence stated.
- **S7** Involuntary flat is terminal: a position that reaches zero through anything
  other than our own exits (a stop, a manual close — distinguishable by order
  ownership) ends the bot — cancel owned orders, kill, page, never restart. *(D1)*
- **S8** Every non-collapsing cell of the start matrix (state × mark position × basis
  state × position size × venue-basis × foreign orders) has a numbered spec row in this
  section's appendix.

## I — identity and orders

- **I1** Every order carries `{botid}-{rung}-{gen}`; ownership is the prefix plus a
  parsing rung; foreign orders are never cancelled, amended, or counted.
- **I2** One bot owns one `(category, symbol, positionIdx)`; the fleet refuses
  collisions at build.
- **I3** The id fits every venue's link limit, checked at build with a refusal — never a
  silent row skip. With a slide the check sizes for whichever window edge prints
  longest: one rung past the far edge of the furthest window, where a lot's exit can
  rest (G25; a short's is negative, and the sign is a character; under G24 both far
  edges count) or the last home rung. *(D28; D34; D36)*
- **I4** Fills deduplicate by venue execution id, across reconnects and restarts.
- **I5** Market-path orders (seed, martingale base, stop-flatten) carry an owned link
  like every other order — I1 has no exceptions; an unattributable own-fill is a
  defect. *(found by R3's unowned bucket, first live readout)*
- **I6** An amended order keeps its link. Hyperliquid's modify is a new order
  made from the body it is given; the venue client's amend rebuilds that body
  from a fresh read and carries the order's own cloid into it. Without it the
  remainder fills unlinked, and an unlinked reduce is an outside hand to D1.
  *(live 2026-10-04: the HL SOL grid's part-filled top-rung exit, amended,
  then killed as "an outside close")*

## V — venue and truth

- **V1** The truth contract is a schema, not a convention: one validated shape, same
  keys, both venues, pinned by a shared spec.
- **V2** Every truth field carries its unit; per-venue period differences (funding) are
  normalised at read time, never left to the consumer. *(CONCEPTS §12·N10)*
- **V3** Truth reads are pure reads: no read mutates cache state that another read
  depends on. *(the HL cache coupling)*
- **V4** A method that exists on two venues has the same completeness guarantee on both
  (`open_orders` returns all of them, always). *(CONCEPTS §12·N11)*
- **V5** Trigger/conditional orders are excluded from order truth on every venue,
  stated in the schema.
- **V6** Spot's position is the wallet's base-coin holding, synthesized into the one
  position shape — the position endpoint is never called for spot. Where a venue
  keeps no basis (spot; v2's demo lesson — the reason the field exists),
  `assumed_avg_entry` serves; a venue-reported basis always overrules the config.
  Spot write bodies carry no positionIdx/reduceOnly, and market orders pin
  `marketUnit=baseCoin` so qty is base-denominated on both sides. A residue below
  the venue's minimum order qty is FLAT, never a position — spot fees settle in
  the base coin, so a full exit always leaves an unsellable shaving. *(the
  8.85e-06 LTC dust, 2026-08-05)* Under D24 the balance is SIGNED: negative is a
  short (side Sell), the dust rule is symmetric around zero, every order carries
  the venue's borrow flag (`isLeverage`), shorts are legal only under
  `spot_borrow`, and sizing flows the one normal path (`leverage :=
  spot_leverage`).

- **V6b** A spot bot owns only its own coins (D58): it holds min(its own
  fills' net, the wallet's balance of the coin) unless the row states
  `assumed_avg_entry`; an unexplained rise of half a lot freezes orders until
  the fill is listed (G26's class), and past RUNGS_LAG_CYCLES is said once.
- **V6c** A stated holding is the book's start (D76): with `holding` and
  `holding_since` (together, spot only, `holding_since_ms` derived), the
  bot's own count is that figure plus its link-attributed fills from that
  moment, never the thirty-day walk; the wallet stays the ceiling; it wins
  over `assumed_avg_entry`'s adoption of the wallet. The readout carries, per
  such bot, the wallet balance, the book, the difference, the inverse books'
  coin P&L less fees since the moment (from the kept ledger) and the
  unexplained rest; the card says it, red when more than half is
  unexplained. The form stamps the moment when the holding is set.
- **V10** A card says the bot in a glance and keeps every number: the state
  word, the money box, the range strip, the holding; a card says when the
  price has left its range; the dense table is still served at `/table`.
- **V11** A watchdog that is off says OFF, not a number.
- **V14** The truth carries the venue's own margin on a position: `position_im`
  and `position_mm` (Bybit's positionIM / positionMM; Hyperliquid's marginUsed as
  the initial figure and no maintenance figure, which is said as None). The bot
  keeps the last read as `margin_view`, derived every cycle and never decided on;
  the snapshot carries it (F4) and the card says "margin IM … · MM … · at Nx on
  the exchange".
- **V18** Hyperliquid's signing is pinned bit for bit to the official SDK's
  production vectors on both nets (keccak, msgpack, the phantom agent,
  EIP-712), and its writes go out in the SDK's envelope: a cloid carries the
  link verbatim and is refused past 16 bytes, nonces strictly increase,
  floats never reach the wire, a gone cancel is success, and a clean `err`
  is a real rejection. One spec per layer, every vector named in its own
  failure. *(vendored 2026-07-27; one module-body spec until the 2026-10-08
  audit)*
- **V17** The venue's own liquidation price rides the margin view (`liq`, from
  Bybit's `liqPrice` and Hyperliquid's `liquidationPx`) into the snapshot, and
  the card says "liquidates at X · N% away" from the mark — red inside 5%.
  Display only; nothing decides on it. *(2026-10-06: HYPE, isolated at 10x, was
  liquidated with no line on its card saying how close it stood)*

- **V15** The snapshot says what rests and what waits. Each cycle the bot
  records, from its own plan, how many buys and sells rest within the placement
  window (W1) and how many wait beyond it with the nearest waiting price, and
  the snapshot carries it for a live bot (`orders`). A wide grid rests one order
  and looks broken to anyone who does not know W1; the record lets the card say
  so.
- **V16** A row's leverage is judged against the venue's own limit on its coin.
  Hyperliquid publishes a maximum per coin and marks some coins isolated-only.
  Past the maximum the panel's gate refuses the row; the build makes no
  `updateLeverage` call and says the venue keeps what it has — never a "venue
  hiccup". An isolated-only coin takes the row's leverage isolated, and the build
  says its margin sits outside the cross projections. A refusal the venue answered
  is its word and is said as one; only a rate limit or a write of unknown fate is a
  hiccup. *(2026-10-06: SOL asked 15x
  of a 10x coin and HYPE asked cross on an isolated-only coin; both refusals read
  as hiccups at every start, and the venue held 5x cross and 10x isolated)*
## C — config doctrine

- **C1** Unknown keys are refused at every level including nested objects; one refusal
  implementation, one exception type, one difflib cutoff.
- **C2** A rename is one commit spanning validator, readers, docs, examples, and error
  text; the old key is refused with the migration stated — never aliased. *(the capital
  pattern; the five HEAD defects)*
- **C3** Every numeric key validates type, sign, and range; fraction-valued keys share
  one interval convention.
- **C4** Derived values are written back once; an operator-supplied value for a derived
  key is refused, never silently overwritten. *(the notional lesson)*
- **C5** A config that cannot place a single order refuses at load — never a silent
  empty ladder. In a fleet it is a failed bot under D52: it builds dead-and-visible
  through the preflight's door, named by symbol and side, counted against
  `max_failed_bots`, and the rest start. The panel's whole-fleet gate refuses it
  before it is written. *(2026-10-06: one row of dust rungs raised out of the
  build and held a whole fleet in a restart loop)*
- **C6** A row that fails validation is never silently skipped. *(D7, amended by
  D52)* Today: it is set aside BY NAME — `fleet['refused']` carries where it was,
  its symbol and side, and the refusal verbatim; the build announces each one
  and the rest start. A stated `max_failed_bots` refuses the whole fleet past
  it (0 = D7's all-or-nothing), and a fleet with no good row refuses whatever
  the tolerance: nothing would run.
- **C7** Every error message names only keys and values that exist.
- **C9** A risk profile fills the blanks (D57). `risk_profiles` in a fleet
  holds named bundles of RISK_KEYS only; a row naming one is merged — the
  profile under, the row over — before the validators judge it, at the
  engine and at the panel's gates alike. Unknown names and non-limit keys
  are refused by name. At the panel's whole-fleet gate a row the engine
  would set aside (D52) is a refusal, never a skip.
- **C10** One vocabulary for the primitives (audit 2026-10-08). The float
  parser (`fmt.float_or`), the UTC stamp (`fmt.utc_stamp`), the number words
  (`fmt.num`, `big`, `big_si`, `pct`) and the fee constants (`fees.py`: the
  maker and taker rates, G6's floors) exist once; every other module imports
  them. A second definition of the parser's shape, the stamp's format or a
  fee rate anywhere in the engine or the panel fails the suite.
- **C8** A number is finite or it is refused. NaN passes every comparison
  as False and Infinity every lower bound; JSON reads both from a file and a
  form's float() reads "nan". The validator refuses non-finite values by
  name, and so does the panel's number parse. *(audit 2026-10-05: a NaN
  capital was accepted and the bot would have looped on venue refusals)*

## X — stops

- **X1** A stop is the off button: firing flattens the grid's inventory, cancels every
  owned order, kills the bot, and prevents restart. Opt-in per bot, restable anywhere
  the venue allows. *(D1, D3 — deliberately overturns v2's stand-down-only stop)*
- **X2** The stop rule names the quantity it watches:
  `stop: {watch: mark_price | account_equity | position_sl}`; a venue-side SL the
  operator placed by hand is picked up and respected. *(D3; CONCEPTS §7)*
- **X3** Server-side is the preferred implementation: its own opt-in key, refused where
  the venue cannot host it, sized to respect X6 (partial-SL where supported, bot-side
  flatten otherwise). *(the liquidation study's #1 TAKE; D3)*
- **X4** Every stop/kill path states what still rests on the venue after it — in its
  event, and in spec.
- **X5** Flatten-and-kill uses the same paginated truth read as everything else; only
  owned orders are cancelled. *(the cancel_all divergence, CONCEPTS §12·N1)*
- **X6** Stop scope is grid inventory only: the `min_position` floor core survives a
  stop. *(D2)*
- **X7b** Two writers, one lock. The engine's stop and the panel's revive
  both change the tombstone file only under one advisory lock, re-reading it
  inside the lock, and write it atomically with fsync; neither can undo the
  other (a revive undone by the next stop, or a stop's row lost to a revive's
  write). Engine, close command and panel find the file by one rule: the
  fleet's `tombstones` key, else `logs/tombstones-<fleet>.json` beside its
  home, the fleet named by its file (`fleet.demo.json` → `demo`). ONE FILE
  PER FLEET: two fleets sharing one file each held their own copy since
  their build and the last writer won; and the demo and carry fleets share
  botids (both run a BTCUSDT pair), so a shared file could never be right.
  The old fleet-wide `logs/tombstones.json` or `logs/slide_state.json`
  beside a fleet that does not name it REFUSES the build, naming the split
  (`ops/split_local_state.py`, once, with every fleet stopped). The slide
  state and the portfolio state (`portfolio_state-<fleet>.json`, H2) write
  the same durable way, under the lock, re-read inside it. *(audit
  2026-10-05, 2026-10-08; the clobbered slide file 2026-10-08; the second
  subaccount's fleet writing the first's book back stale, 2026-10-09)*
- **X7** A fired stop survives the process: the tombstone is durable BEFORE the
  flatten (a crash mid-stop stays dead), a tombstoned botid builds dead-and-visible
  (F4), and revival is a deliberate operator act — delete the entry, never automatic.
  The file fails CLOSED (corrupt ⇒ the fleet refuses to build, never a silent
  revival), but a failed WRITE never blocks the flatten itself — stopping beats
  remembering.
  The one narrow local durable fact E3 permits: the exchange cannot express "this
  bot's stop fired". *(the undesigned fifth start state, ALIGNMENT — closed
  2026-08-05)* G22 is the second, by the same argument.
- **X8** A slide bot's `mark_price` stop follows the window: it is expressed as
  `rungs_beyond` the window's near edge (below the bottom for a long, above the top
  for a short) and re-derived from the current offset every cycle — after an adverse
  slide (G24) too, so it follows the window down (a short's, up) — so a server-side
  stop (X3, level-triggered) is re-set after each slide. An absolute `level` is
  refused with `slide` — once the window has left home it protects nothing — and
  `rungs_beyond` is refused without it. `account_equity` stays absolute: a wallet
  has no window. *(D28's wiring; JOURNAL 2026-09-25 evening)*
- **X9** The stop's timeout (D33's "Time" mode, 3Commas' SL timeout):
  with `stop.confirm_seconds` a `mark_price` stop fires only after the level has
  stayed crossed that long; a recovery resets the clock, and both are said once.
  The clock is in memory: a restart delays the stop by at most the timeout and
  never brings it early (E3). Refused beside `server_side` (the venue fires on the
  first touch) and on the other watches.
- **X10** A martingale's `mark_price` stop may be `from_base_pct`: a fraction from
  the round's base order price, so each round has its own level. It must lie beyond
  the last safety order (3Commas' rule) and is refused beside `level`,
  `server_side`, or on a grid. Flat, there is no base and no stop. The base is the
  round's anchor; after a restart with no anchor (M15) it is the newest rung-0
  entry fill on the venue.
- **X11** `stop.action: end_round` (D42, opt-in; the default is X1): the stop ends
  the round, not the bot. The round's own resting exits and hosted conditionals are
  cancelled first (E2; never a foreign one, I1), then the position closes at market
  under link rung `STOP_RUNG`, so M14 reads it as our exit and M5 opens the next
  round. No tombstone. It needs `from_base_pct` and `repeat`. Because the closing
  fill carries `STOP_RUNG`, the venue remembers how the round ended:
  `stop_cooldown_seconds` (D33) is M13's pause when the newest fill is the stop's,
  across a restart too; any other close takes `repeat_cooldown_seconds`.

- **X12** D33's other two parts. *Candle close*: with `stop.confirm_candle` (1m to
  4h) the engine compares the mark with the level only at each interval boundary,
  read from its own clock, so a wick inside a candle never fires the stop; the first
  cycle of a process has seen no boundary and waits for the next. One cool-down per
  stop: refused beside `confirm_seconds`. *Emergency level*: `stop.emergency_pct`
  is a second level that far beyond the stop's own (so it follows a slide, X8, and
  a round's base, X10); crossing it fires the stop at once and overrides either
  cool-down. Where the venue can hold a position stop (X3's venues) it rests there,
  sized as X3 sizes it, and survives the process; elsewhere the engine watches it.
  It needs a cool-down to override. When the venue fires a stop this row keeps
  there (X3's or this one), the closing fill says so and M14 reads it as the stop:
  the bot stands down (X1) even if the mark recovered before the next read, unless
  the stop is X11's, which ends the round and takes the stop's cooldown.

- **X13** `stop.action: leave_position` (D43, opt-in; the default is X1): the stop
  cancels every owned order, tombstones the bot (X7) and sells nothing. The kill
  line states the size left open, that it is unprotected and the operator's, and
  that anything the venue holds on the position itself still rests (X4). Works with
  `mark_price` (and its cool-downs) and `account_equity`; refused beside
  `server_side`, `emergency_pct` and `position_sl`, where the venue would close the
  position itself.

- **X14** `max_loss` (D47, opt-in, grids and martingales): the most the bot may
  lose, in quote money, since `max_loss_since`. Realised is walked from the venue's
  fills at average cost on the bot's own side, net of fees; an exit of a holding
  older than the moment realises nothing here. Open is what is held now against
  the venue's average. When realised plus open is down `max_loss` the bot does X1:
  flatten, cancel, tombstone, even where its stop's action is `leave_position`.
  The fills are re-read when the holding changes and once a minute; a venue that
  has never answered is not a breach. It reaches back the fills window (30 days)
  at most. The two keys travel together and the panel stamps the moment. The
  result last judged rides the engine's snapshot (F4), and the card shows it as
  "down X of the limit", red from three quarters; the quick setup offers the limit
  as its one optional box; the what-if (U9) ends a move where the loss first
  reaches it, unless a stop ended it sooner.

- **X15** Closing what a stopped bot left open (D48): `python3 -m gridgremlin.close
  <fleet> <botid> [--dry]` sends one reduce-only market order for exactly what the
  venue shows on that bot's side of that market, and re-reads to say what is left
  (X4). It refuses a bot that is not tombstoned (a running bot manages its own
  position, and an outside close is what S7 stands it down for), refuses spot (the
  wallet's coins are the operator's too), and has no way to mainnet: D25's run half
  is passed shut and the command takes no flag that opens it. The panel offers it
  on a DEAD bot's card not known to be flat (a bot that stood down flat has
  nothing to close — HL AVAX, 2026-10-06), where control is armed (§12), behind a page that first
  shows what the venue holds and asks for the bot's name typed; the panel runs the
  command as a subprocess and holds no key.

## F — fleet and operations

- **X15b** On Hyperliquid the close command waits for the fleet (D77): nonces
  are per wallet, and a second signer beside the running fleet collides with
  it. The command asks this fleet's own locks — its prelock, and the venue
  locks of its venues on its account, never another fleet's beside them
  (on a three-fleet box every fleet read as running, 2026-10-08); held, it
  refuses before any client is built — stop the fleet, or close by hand on
  the venue. The portfolio flatten (H4) asks the same way.
- **F1** Every fleet names a watchdog config, and its account guards (staleness,
  mm_rate, equity floor, drawdown) cover every bot. A per-bot position bound is
  opt-in (D32): present, it is checked; absent, the bot has no limit of its own. A
  bound naming a bot that is not in the fleet is refused. *(was: every bot listed,
  both directions — a second file kept in step by hand, and a fixed ceiling that a
  slide beyond capital breaches by design)*
- **F2** Watchdog position ceilings, where given, are pinned near the cap (breach ⇒ the cap itself
  failed), never derived from "held plus budget". Beyond 1.5x the cap only with
  `ceiling_loose: true` beside the max — a disaster-only watcher is chosen, never
  defaulted (D28).
- **F3** One fleet process per account, ever.
- **F4** Snapshots include dead bots — liveness must be detectable from the file.
- **F5** The demo fleet can never carry the mainnet flag; the gate is per-venue and
  write-only paths need it.
- **F6** Every watchdog threshold documents its assumption set — including whether the
  grid is assumed to be the only actor on the account.
- **F7** Mainnet is double-safetied (D25): it fires only when the fleet file declares
  `"allow_mainnet": true` AND the launch passes `--allow-mainnet`. Either alone
  refuses, naming the missing half. The demo/testnet env flags are the helmet; this
  is the armour — a cloned repo cannot reach real money by accident. *(supersedes
  F5's "no mainnet path"; F5's demo-fleet clause stands)*

- **F8** The preflight (D27, optional): `probe` places ONE unfillable post-only
  rehearsal order per bot at build and cancels it — the whole placement path
  (auth, permissions, collateral, lot rules, the preconditions nobody published)
  proven before any strategy order; the metadata half refuses what the venue's
  catalogue already knows (a borrow bot on a coin whose `marginTrading` says no).
  `max_failed_bots` is the tolerance: absent (D52), a failed bot builds
  dead-and-visible (F4) and the rest trade, refusing only when every bot
  failed; stated, the fleet refuses past it, and 0 is D7's all-or-nothing.
  Rows refused at validation count against it too. *(the 170037 incident:
  ~1,500 runtime warns that should have been one build refusal; the 2026-10-02
  one: one test row's probe took thirteen bots down)*
- **F9** A dead bot is visible (F4) and carries NO position: it no longer reads the
  venue, so its last belief is not truth. The watchdog bounds only the living; the
  range review lists the dead from the fleet's newest snapshot row and reviews
  nobody dead. *(the 48-day run: one killed bot's frozen size paged a phantom
  breach every re-alert window for 48 days)*
- **F10** The range review pages the FACTS always; a judgement is an extra on top,
  and when there is none the page names why (no CLI, no token, not authenticated,
  timeout, non-zero exit). A CLI's error text is never paged as the review.
  *(30 of the 48 days paged "Failed to authenticate", exit 0, as the verdict)*
- **F11** The fleet logs the units append to are size-rotated in place
  (`copytruncate`, the writer is never restarted for it); snapshot files are one
  history and are never rotated. The spec ties the rotated path to the unit's.
  *(2.4 GB in 48 days)*

- **F15** The account cap (D56). With `account_caps` set, each cycle the
  fleet judges every venue: notional = the sum of its living bots' positions
  at mark (each bot's own last read), mm_rate = the venue's. At or past
  either cap every bot on that venue is capped: no order that adds exposure
  rests or is placed — entries withdrawn, no seed, no new round — and exits
  run. Reached and cleared are each said once. Unknown mm_rate judges
  nothing on that leg; absent caps, nothing changes.
- **F15b** The holding cap (D70). With `holding_max` set, each cycle the venue's
  living bots holding a position are counted; at or past the cap every FLAT
  living bot on that venue is capped — no base order, no seed, no entry — and
  the holding ones are not held back by this leg. The snapshot carries each
  capped bot's reason and the card says it: a flat bot waits, a holding one
  adds nothing. Reached and cleared are each said once.
- **F14** The watchdog's memory survives a torn write. Its state is written
  atomically (temp, fsync, rename, fsync the directory); an unreadable state
  file starts the memory again and pages once saying so — the cost is a
  re-page per standing breach and a drawdown peak restarted at today's
  equity — rather than failing every tick until a hand repairs it.
  *(audit 2026-10-05)*
- **F13** One unknown equity is a blip, not a page. A rate-limited wallet read
  runs the cycle with unknown equity (E9) and writes one null-equity snapshot
  row; the watchdog judges that row beside its neighbours of the last
  `staleness_seconds`: a known neighbour's figure stands in for the floor and
  drawdown checks, and `equity_unknown` is a breach only when the whole window
  is unknown. *(2026-10-05: the HL watchdog paged "could not read equity" and
  "recovered" five minutes apart, four times a day, on single rate-limit blips.)*
- **F12** A running fleet takes an edited row's terms (D49). The engine stats the
  fleet file once per cycle; a change older than 1.5 s is read and validated
  (a refused file changes nothing, and says so). For each running bot whose row
  changed: a change among the HOT keys (leverage, capital, stop, the limits,
  take profit, trailing, repeat and cooldowns, placement window, position caps) is
  applied in place, the build's carried values kept and the loss ledger re-read;
  a change among the COLD keys (identity, strategy, venue, lattice, slide, seed,
  floor, a martingale's sizes and deviations) applies nothing of that row and
  names what waits for a restart. A portfolio row is known to the watch by
  its own id, and any change to it waits for a restart (H2), said so. A leverage change goes to the venue first, one
  leverage per market (the legs' highest, as at build) on Bybit, one per coin
  on Hyperliquid (its updateLeverage, as the build asserts it); the venue's
  refusal is said in its own words and nothing of that row is applied. *(live
  2026-10-04: the hot-apply once resized two HL ladders to 25x on a venue still
  margining at 5x, and every rung was refused for margin)* New and removed rows
  wait for a restart, and are said.
- **F16** The phone carries what needs the owner now (D60). Every event still
  prints; Telegram gets `kill margin backoff fleet` always, everything while
  the fleet is starting (until `build_fleet` returns), and otherwise only an
  event its call site marks `urgent` — a refused exit, stop, breakeven or
  trail, a stop level crossed, a round closed by a stop, trail or hold limit,
  the wrong-side halt, an outside hand's coins, exits withheld, a refused
  fleet-file edit. An urgent line that recurs is said the first time and then
  at most every 15 minutes with its count; a kill is never held. A warning not
  marked urgent reaches the phone once as *persisting* when the same bot's same
  message (its numbers aside) comes 5 times in 15 minutes, then at most
  hourly. Fills, exits, take-profit placement, round turns and slides are the
  log's and the ledger's. *(2026-10-05: 1,389 pings in a day, 86% trading
  churn, and the one that mattered — the SUI exit refused with nothing
  resting — was 286 of them; replayed under F16, 141, the SUI refusal once)*
- **F17** The day is digested (D62). Once a day at 23:58 UTC (07:58 Perth),
  after the archive and before Tokyo opens, one message per box: for each
  exchange the UTC day's result after fees — each bot's kept book (R18) at
  the day's start and now, from its stored anchor, a bot with no whole start
  left out and counted — its fees, trips (grids) and rounds (DCA bots), the
  open P&L and kept history from the archive the readout just wrote, the
  day's best and worst bot, equity and margin rate from the newest snapshot;
  then what the fleet's log said since the last digest (kills, stop and trail
  closes, refused orders, fill lags, margin, tracebacks — the log has no clock,
  so the digest keeps its byte place, starting again on a rotated file); then
  health (bots alive, or a stale snapshot named; the watchdog's and the
  ledger's last runs). The ledger is collected first so the day is whole. The
  place moves only once the message is sent; one fleet's trouble costs no
  other. *(owner, 2026-10-05: "give me the daily digest before asia start")*
- **F18** The owner can read the box from the phone (D61). A long-polling
  service answers `/help /status /pnl [bot] /today /positions /orders [bot]
  /grids /rounds /risk /alerts [n] /log <bot> [n]` — a bot named in part,
  case-blind — from what the box already keeps: the snapshot, the readout (the
  service keeps one warm, refreshed every minute, and an answer built on it
  says its age — a failed refresh keeps the last), the digest built unsent, the newest 20 MB of
  each log's `[ship]` events. Only `/commands` from `TELEGRAM_OWNER_ID` are
  answered; without that id it refuses to run. It is the channel's one
  getUpdates consumer, keeping the relay's offset file, and writes the next
  offset BEFORE it answers — a crash costs an unanswered question, never a
  loop. A source that cannot be read is said in the reply, never raised.
  Nothing in it can write: no venue client, no subprocess of its own, no
  systemctl. *(owner, 2026-10-05: "the reading suggestion is really good")*
- **F19** Real money runs from a pinned copy that moves only by promotion
  (D65): `ops/promote.py` moves the live worktree to a version that is on the
  merged main and has run in the play-money checkout for a day by that
  checkout's own reflog — or the same day as a hotfix with its reason written
  down. A version never deployed to play money waits or is a hotfix; an
  unmerged one never moves it. Every move is appended to the live copy's
  `logs/promotions.log`; nothing is restarted.
- **F20** A Telegram message carries its heading in bold: every sender builds
  its request through one function (`tg.payload`), which marks a line's label
  — up to its first ': ', or the whole line when it has none — bold under
  Telegram's HTML mode and escapes everything else verbatim (`<`, `&`, `>`
  included). The first line of a page, a digest or a reply; every line of the
  engine's coalesced events. The two systemd alerts carry their own bold
  heading. *(owner, 2026-10-07: "is there a way to make the headings at the
  start of each message type bold?")*
- **F21** The public edition refuses real money in code (D68): with the
  edition flag set, `refuse_mainnet`, the Hyperliquid client and the
  `--allow-mainnet` flag all refuse flatly, whatever the fleet file or the
  launch says; the private edition keeps D25's double safety. The example
  fleets in `configs/examples/` build clean, keep every size small (capital
  ≤ 300, leverage ≤ 5), and show every mechanic once — the slide, a stop, the
  loss limit, tranches with the breakeven ladder, the trailing stop, repeat.
- **F22** The doctor (`gridgremlin.doctor`) says what is missing and what is
  next, in plain words: Python, the edition, `.env` and its mode, each
  exchange by a read-only call and which network its key is on (real money
  named as refused in the public edition), Telegram, the fleet files, the
  suite on request. A ✗ line names its fix; the last line is the next step.
  It writes nothing and places nothing.
- **F23** The export (`ops/public_export.py`) writes the public tree and
  refuses it unless the scan is clean: nothing excluded present, no host,
  path or name of the owner's own, the edition flag set, the testers'
  README, guide and issue templates and the example fleets in place. It
  never writes into a directory that is not empty, and `--check` runs the
  written tree's own suite. The tree carries the Apache License 2.0 verbatim,
  a NOTICE, CONTRIBUTING.md, a CODEOWNERS naming the owner and a workflow
  that runs the suite on every pull request, or the scan refuses it (D68).
  The testers' runbook (`docs/public/RUNBOOK.md`) stands where the private
  one does, so F28 holds in the exported tree too.
- **F24** The dead-man's switch (D74). At the end of every completed watchdog
  run — breached or not, paged or not — one GET to `DEADMAN_URL` when `.env`
  names it; the outside check alarms when the pings stop. A failed ping is
  one printed line and never a failed run; no URL, no ping.
- **F25** A filling disk is a breach (D74). The watchdog judges the used
  fraction of the volume its snapshot lives on against `disk_used_max`, 85%
  unless the config says otherwise, before it reads the snapshot at all; an
  unknown usage judges nothing. It pages and re-pages like every breach.
- **F26** Retention (D74). A log under `logs/archive/` not modified within a
  day is compressed in place, the .gz replacing it only once written whole;
  kept, never deleted; anything that is not a log is left alone. Snapshot
  files stay one history, never rotated (F11); the disk alarm (F25) is what
  watches their growth.
- **F27** The pull backup (D74), on the workstation: once a day, over the ssh
  alias already in use, `logs/`, `configs/` and `.env` (mode kept) into
  `DEST/<UTC date>/`, hard-linked against `DEST/latest` so an unchanged file
  costs nothing; `latest` moves; the newest `KEEP` days stay; the destination
  is the owner's alone (mode 700). Settings come from one file and never from
  the script, which refuses to run without them.
- **F29** The expiry calendar (D79). `configs/expiry.json` lists what runs
  out — keys, tokens, demo accounts, the box's billing — as `{name,
  expires, note, where}`, `expires` an ISO date or null for unknown
  (listed by `python3 -m gridgremlin.expiry`, never paged, never guessed).
  One fleet's watchdog names it (`expiry`); every run adds to its breaches
  what runs out within `expiry_warn_days` (7) and what has run out, so the
  page comes once, the reminder on the watchdog's interval, and
  "recovered" when the date is moved on. An unreadable calendar is one
  breach, not a silent watch. Nothing renews anything.
- **F28** The runbook (`docs/RUNBOOK.md`, D75) names what exists: every unit
  the templates in `ops/systemd/` render (by its `grid-gremlin3-` or `gg-`
  name), every timer, every phone command the phone answers, the close tool,
  the promote tool, the dead-man and the backup — or the suite fails, so the
  page cannot drift from the box.

## R — the readout

- **R1** Fill history is venue-derived and link-attributed (I1's rule: ours iff the
  rung parses), deduped by execution id (I4), every cursor followed to the end or
  refused (E5) — never a local guess of what filled. *(the exchange is the state)*
- **R2** Per-bot profit is average-cost accounting over time-ordered fills: a reduce
  realises against the basis, a flip re-anchors at the flip price — in the
  contract's own PnL coin (A4): base for inverse, quote elsewhere. *(the
  −121,570 phantom, 2026-08-05)*
- **R3** Fills owned by no bot are reported in their own bucket, never dropped —
  external activity on the account must be visible. *(F6's other half; since
  R16 that bucket holds fills on no bot's exit side — hand entries, markets
  with no bot)*
- **R17** The day is archived. Once a day (a user timer near UTC midnight,
  `gridgremlin.archive`), each fleet's readout contract — every bot's money
  counted from its last flat point, trips, rounds, the window's activity —
  is written beside the fleet's newest snapshot row to
  `logs/daily/<fleet>/<UTC date>.json`, atomically; a later run the same day
  replaces that day's file, and one fleet's failure never costs another.
  Read-only toward the venues. *(2026-10-05: results existed only when
  someone looked; the owner's thesis needs them kept)*
- **R18** The fills are kept. Hourly (`gridgremlin.kept_fills`), every fill of
  a fleet is merged into `logs/fills/<fleet>.json` — one fill once, keyed by
  venue, market and execution id (I4), the newer read winning, written
  atomically under a lock; a file that will not parse is refused by name,
  never restarted empty. Each venue key records how far collection reached;
  the first run backfills 90 days, then each run reads on from its mark less
  an hour. Hyperliquid's 2000-fill answer is halved until every half fits. A
  venue that cannot be read keeps its mark and costs no other; a market
  taken out of the fleet is still collected. The readout merges the kept
  fills with its own fresh ones into each bot's book from its FIRST CLEAN
  FLAT (`since_first` in the contract): the holding the exchange states now,
  unwound newest fill first, lands on flat at that fill and never below it
  — a record that opens mid-position realises against a basis it never saw
  (the first backfill: +181k and −202k on one demo BTC pair). A spot bot's
  figure is the engine's own count from its snapshot (D58). The start is
  ANCHORED: the hourly collector stores a clean start when it finds one (a
  flat in the past stays a flat, so a lagging read — G26 — can never lose
  it), and a bot that has never had one, on three runs in a row, starts
  FRESH: from then, holding what it holds at the price then, an opening
  balance the record counts on from (owner, 2026-10-05). An anchor never
  moves; a live clean start counts only when it reaches further back. No
  anchor yet and no landing is `whole: false` and is not summed —
  and where collection last reached a
  market before the readout's window began, the hole is said (`behind`) and
  no number is shown; the exchange's sum names the bots it leaves out.
  *(owner, 2026-10-05: per-bot and per-exchange P&L that survives round
  ends and the venues forgetting)*
- **R19** The account's leverage is said as the exchange states it, and as if
  every order filled. *Now*: Hyperliquid's own total position value over its
  own account value (on a unified account the USDC held as perp margin —
  2.66x on 2026-10-06, its screen's figure); Bybit, which states none, its
  own `positionValue` over every open position (inverse at its mark price)
  over its `totalMarginBalance`. Both count every position on the account, a
  hand-held one too. *If every order filled*, by direction — a long's ladder
  fills on a fall, a short's on a rise, and one market cannot do both (summed,
  the demo read 38.9x for a move that cannot happen): each side's bots add
  their row's most in the market (`terms.notional`) less what they hold, over
  the whole collateral (a unified account's account value is only the margin
  held so far, which a projection outgrows); the other side's exits are not
  netted off. Unknown is never zero. One wording on the panel's exchange box
  (a now · if all filled switch, kept per tab), `/risk` and the digest.
  *(owner, 2026-10-06: "leverage is always determined by what my account
  leverage after all positions are loaded would be … id prefer if it
  displayed the way hyperliquid does … and then for the figure as if
  everything is filled as a toggle")*
- **R16** An unlinked fill on a bot's exit side is booked to that bot, whoever
  created it: a modify the venue rebuilt without the link, a hand close, a
  venue close without a label. I2 makes it unambiguous — one bot per (market,
  symbol, side), a hedge pair's long exiting by sells and its short by buys.
  The readout books the money where it went; the engine's law is untouched,
  and to it an unlinked reduce is still an outside hand (D1), which is the
  signal the kill needs. The fill is the bot's only while the bot's own
  fills say it holds something, and only up to what it holds — the excess,
  or a sale made while the bot was flat, is the unowned bucket's (R3). *(HL
  SOL 2026-10-04: 0.19 sold unlinked by the I6 incident, the book 0.19 over
  the exchange for a month; and the demo SOL long read 8.2 short the moment
  the rule landed without the guard — the owner's September hand-flattening
  inside the month)*
- **R4** The readout is read-only by construction: no write surface appears in its
  module.
- **R5** "Grid profit" is realized minus fees (D8); "total P&L" adds funding (R20)
  and mark-to-average on the open remainder; an unknown mark yields no number,
  never a guess.
- **R20** Funding is its own term (D63). Each exchange's own record of funding —
  Bybit's executions of type Funding, whose `side` is the position's and whose
  fee is positive when paid (one settlement is one execId on both legs of a hedge
  pair — kept once per id AND side); Hyperliquid's `userFunding`, signed already, its side
  the sign of `szi` — is booked to the bot of that (market, symbol, side) (I2),
  over that bot's own window (the readout's, the widened one, or the kept
  history's), in the settle coin and at the mark for an inverse book. Every total
  is realized − fees + funding + unrealized, through one function every renderer
  calls. Funding a venue would not give is None and said '—', never a zero.
  *(audit 2026-10-06: funding was in no figure; on HL one bot's total read about
  twice its true value and another showed a profit that was a loss)*
- **R21** Per trip is also said after fees: the trip's own gain (R12) less both
  legs' fees at the book's average fee per fill — what every grid platform calls
  grid profit per pair. The gross figure stays beside it.
- **R22** A card counted over the 30-day cap says where its fills start when that
  is later than the cap: "never flat in 30 d; its fills start 4.4 d ago", not
  "last 30 d". *(audit 2026-10-06: a "last 30 d" card counted 4.4 days)*
- **R23** The fleet's log keeps time: every line the fleet process prints
  ends with its UTC time (` @2026-10-11T04:12:33Z`). The time goes at the
  end because every reader keys on the start (`[ship] kill …` — the digest,
  the phone, the replay); the specs' own notifiers print no time. *(2026-10-11:
  a fill-list lag could not be measured — the log carried no clock)*
- **R24** The results page (`/results`) says what every bot has made after
  fees since its first kept fill, as a curve: the ledger records each bot's
  realized less fees after every fill, thinned to 200 points (evenly, the
  last kept), carried in the readout as each `since_first` book's `series`.
  A bot whose market has left the fleet — its fills kept, its card gone — is
  found by the botid in its own links (`<botid>-<rung>-<gen>`, I1) and
  booked from those alone, said as partial since a venue-made close carries
  no link; the readout carries those as `gone`. A record that is not whole
  is listed, never summed.
- **R9** The readout counts SAME-RUNG exits: an exit filling at a price the book
  entered at. It needs no basis, so a truncated window cannot fake it. Read it as a
  RATIO, not a verdict — in a netted engine (G12) a rung legitimately flips between
  entry and exit as the ref crosses it, and the basis floor (G6) keeps those trips
  profitable against the average. A ratio near 1.0 means the floor is inert and the
  bot is churning at zero spread. *(spot ran ~100% before G15; linear runs low)*
  Under G23 the ratio should read ZERO: a lot's exit is one rung above its own by
  construction, so any same-rung exit is a defect to chase, not a ratio to watch.
- **R8** A forced close is a fill: liquidation (`BustTrade`) and auto-deleveraging
  (`AdlTrade`) move the position and realise the loss, so they enter the ledger like
  any other — funding and settlement rows still do not. *(audit 2026-08-06: the
  execType filter hid liquidations from both the P&L and reinvest sizing)*
- **R7** A fill the VENUE created to close a position (hosted TP/SL, trailing,
  liquidation) carries no link — the venue's own labels say what it is, and I2 says
  exactly one bot owns (market, symbol, side), so it attributes to the bot whose
  exits sit on that side: evidence, not inference. A time window that opens
  mid-round declares itself rather than printing the phantom remainder.
  *(the DOGE round that read realized 0.00 with a phantom short, 2026-08-06)*
- **R6** The activity layer derives from the SAME fills, no new state: every
  realisation is a trip (counted at a loss too — underwater churn is visible), a
  flat crossing closes a round and banks its realized, an entry fill at rung ≥ 1 is
  a safety order and its rung is the round's depth; the max depth ever reached is
  the martingale's true risk gauge.

- **R10** HL stamps `liquidation` on BOTH sides of a liquidation trade and names
  the liquidated user in it. A fill is a venue liquidation of us only when that
  address is ours; a counterparty's liquidation filled our resting order and is an
  ordinary fill. A stamp that names nobody, or a read with no account address,
  refuses rather than guesses. *(the 48-day run: both HL grid deaths were healthy
  bots stood down by someone else's liquidation, 2026-08-13 and 08-19)*

- **R11** A grid exit is judged against its own rung. The zero-spread count
  measures an exit with a link rung against the lattice price of the rung it
  closes (one below for a long, one above for a short; G25), never against the
  book's average: a sliding grid's average moves with every lot it adds, so a
  full-gap exit below the average read as churn (6 of 80 on 2026-10-03, every one
  a full gap by identity). R9's average test remains for fills with no rung. An
  inverse book's money is the base coin (A4); the data contract converts
  realized, fees and the open remainder to quote at the mark and carries the coin
  figures beside them (`settle`), so the panel never prints a coin amount as
  dollars; the card says both, dollars and coin, as the exchange does. The stop-now estimate of an inverse position is its contracts, each a
  dollar.
- **R15** An exit is judged against the price its lot was bought at. R11/R12
  take the level from the config's lattice; when the entry fill for that rung
  is in the window, the venue's own price is the level and the lattice is only
  the fallback for an entry not seen. A slid or re-identified lattice is then
  judged right wherever the buy was seen. *(2026-10-05: the SOL long re-latticed
  31→19 at a restart; the window held fills from both, and 60 of 61 trips were
  flagged zero-spread at −41 per trip on a day the book realised +251.)*
- **R12** Per trip is what the trip earned. The book's realized is average-cost
  (R2): a long grid that bought cheaper lots on the way down carries an average
  above its exits, so every full-gap trip "realises" a loss while the
  remainder's mark-to-average rises by the same amount — the sum is R5's and
  unchanged, the split is not the trip's. For every exit with a link rung the
  book also sums the gain against the rung it closes (R11's identity) and
  counts it; the activity layer's per-trip figure is that sum over that count,
  and falls back to realized per trip only for a book with no rung-identified
  exit — and not even then under a truncated window (R7), when the book's
  position is a phantom: None, never a guess. Identity needs no book: the sum
  is taken on every exit-side fill with a rung, for its whole quantity,
  whatever a window that opened mid-round made of the position. The data
  contract carries `per_trip`; an inverse book's figure is in the base coin and
  converts at the mark like its realized, in the terminal table too. Measured
  2026-10-03: the demo BTC long printed -156 per trip over 55 trips with every
  exit a full gap by identity; three shorts whose windows opened on an exit
  kept a phantom figure until the sum was freed from the book.
- **R14** Money is counted from the last flat. A bot whose round is older
  than the readout's window is re-read from the last time its own fills show
  it flat — widening in doublings up to a month — and its book, realized,
  remainder and per-trip are the round's, with `counted_from: flat` and the
  moment it began in the contract; the card's headline says "since it was
  last flat, N d". The tell is the exchange: one read per venue says what
  each bot's side holds, and a window whose book does not hold that — a
  short as much as a long, or a bot with no fills in the window at all — is
  partial and is widened; a flat point is accepted only when the fills since
  it add up to that holding. Never flat in a month: the month's fills, `cap`,
  and the truncation mark stands, naming the exchange's own position figure
  as the truth. *(2026-10-05: the busiest grid's card read -14,090 over 24 h — sells
  of lots bought before the window, a remainder priced from nothing — on a
  round the exchange showed at +9,559.)*
- **R13** A round begins flat at its base order. A martingale's book in a
  window that opened mid-round carries a phantom position that no later close
  can land at zero, so its rounds and average per round counted nothing (the
  ADA looper: 692 fills, no round, BACKLOG since 2026-09-25). The ledger knows
  which bots begin a round flat (`rounders`: the martingales) and at the first
  fill of a NEW base order — the entry side's rung 0 under a link not seen
  before, where D37's maker base rests too — re-anchors the book flat and
  starts the round's P&L there; a split base order shares one link and anchors
  once; a window that opened flat is untouched. The book says `anchored`.
  Identity, not inference: the money columns before the anchor stay partial
  and marked (R7).

## K — the market readings (D67)

- **K1** The regime is read from 4 h candles with Wilder's ADX and ATR, the
  latter as a percent of the last close; short of 2×period+1 candles both say
  None, never a guess.
- **K2** Numbers become words by stated bands: ADX under 20 is *ranging*, 30
  and over *trending* (up or down by +DI/−DI), between them *leaning*. A side
  holding 60% or more of accounts is *leaning*, and *crowded* when funding
  per 8 h also pays that side 0.01% or more. A market is *thin* for a fleet
  when less rests within 1% of the mark than the fleet's whole ladder there,
  or less trades in a day than ten ladders — floors of 10k and 100k quote
  for a tiny fleet. *(HYPE on the testnet, 2026-10-06: a grid about half the
  whole market)*
- **K3** Depth is the quote resting within 1% of the mark on both sides; an
  inverse book's sizes are $1 contracts and are read as such (A4).
- **K4** Funding is said per 8 h whatever interval the venue charges by
  (Bybit's `fundingIntervalHour`, Hyperliquid's hourly rate). Funding on
  Binance, OKX and Bitget stands beside it as the mainnet reference a demo or
  testnet rate lacks, with a flag when they disagree on direction.
- **K5** Every reading is kept: one row an hour in `logs/market.jsonl`, each
  market the fleets trade once with what the fleets put there, each part that
  could not be read said by name in its place, never a zero. The row is read
  back newest-last; no readings yet is said as such.
- **K6** The report says sentiment, each coin once with its regime, each of
  its markets with their own numbers, funding elsewhere, and Bybit's notices
  that name a fleet coin or a delisting, maintenance or suspension — in
  messages under Telegram's cap, ending "readings only — nothing acts on
  them". Paged at the three session opens; `/market [n]` on the phone.
- **K7** The module is read-only and keyless: public endpoints, no venue
  client, no key, no signing; nothing in the engine imports it.
- **K8** `/market` answers from the kept readings as the report says them,
  part n of a report too long for one message.
- **K9** The newest reading sits beside each bot: the readout's contract
  carries each bot's market words (`market`), the card says them — red, with
  "THIN for this fleet", when the book cannot hold the grid — and the digest
  ends with sentiment and each coin's regime, naming the venues where it is
  thin. A bot whose market was not read carries nothing; no readings yet is
  said as such. Display only, like the rest of K.

- **U55** The dash reads as the owner reads it. A fleet file's `label` is
  what the panel calls the fleet (forty characters at most); without one,
  the venue and the file's environment word. Every card is a column with
  its footer — the id and the buttons — aligned at the bottom, so the
  buttons line up across cards. The portfolio card is three cards wide
  and no wider, its money and its facts side by side, the assets below.

- **U56** One position, one page. A card holds its state, its money and
  its holding; its numbers live at `/position?fleet=&bot=` behind a
  `numbers` button — the exchange's own view of the position first
  (symbol, side, size, value, entry, mark, liquidation, margin, leverage,
  open and closed P&L, funding), then the card with every number and the
  ladder laid open. A card folds nothing, so U22's show-all switch is
  retired (the owner, 2026-10-08: the opened tables collided and the cards
  ran very long).

- **U57** The card judges the price against the window the bot trades,
  not the home it started from: a slid window (G17) is the home range
  moved by the offset times the lattice's gap, and the card says how far
  it slid. The readout carries every configured bot's mark, so a quiet
  bot shows where the price sits in its range too.
- **U58** A card's lower half folds. What sits under the money box and the
  range bar — holding, kind, liquidation, market, margin, investment, loss
  limit; a portfolio's assets table — sits behind one summary word, open
  by default; the page's script remembers each card's click either way,
  and the side panel's **cards: full / folded** switch sets every card at
  once (where U22's show-all switch was). The numbers stay the position
  page's (U56); an export, which carries no script, shows every fold open.
- **U59** An account folds to its heading and its box: each fleet's cards
  sit behind "N bots", open by default, remembered like a card's fold; the
  side panel's **accounts: full / folded** sets every account at once,
  apart from the cards switch; one link beside each account's count
  (**fold cards** / **open cards**) folds or opens that account's cards
  alone. The fleets stand in the order the panel was
  given them — the Bybit accounts first, by the owner's word.
- **U60** Every page wears the panel's navigation as the fleet page does:
  a column on the left with the pages, a way back, the forms' one warning
  and the theme; the content beside it. One function names the pages.
  *(first built as a bar across the top, whose class was the progress
  bar's — the links spilled onto the heading; the column, 2026-10-09)*
- **U61** The live page refreshes in place, never whole: the script
  fetches this same URL — the one fetch it makes, same origin, nothing
  else — and swaps the strip and the cards, re-wiring what folds, so
  nothing flickers and nothing the reader opened or scrolled to moves.
  Without script the whole-page refresh stands (`<noscript>`); an export
  refreshes nothing and carries no script.
- **U62** Nothing on the panel is truncated to fit: the table and the
  exchange's view of a position sit in a box that scrolls sideways when
  the screen is narrower than they are, every number whole; on a phone
  the strip stacks one account per row instead of clipping its totals.
  *(screenshots 2026-10-09: "6…", "-43,3…", a funding column off the page)*
- **U63** The account's equity over time, from the fleet's own snapshot
  file (F4, never rotated — F26): a sparkline of the last day in the strip,
  and under each account's box a 24 h and a 7 d line with the low, the
  high and the change over the window, a native tooltip per point, no
  script. One series, two pixels, the page's own ink; the sign's colour
  only on the change. The file is read from its tail, once cold and then
  only what was appended (`gridgremlin.equity_series`), so a 40 MB history
  costs a refresh a few kilobytes; an unpriced row (E9) and a torn line are
  skipped; fewer than two points draw nothing and the box says so.
- **U64** A card says how long it has run and its grid profit per day and
  a year, as every grid product does: in the figure's own span (since last
  flat, since the first fill in the cap, or the window), realised after
  fees per day, and — where the bot states its investment — Bybit's grid
  APR: grid profit / investment / days x 365, a run under a day counted as
  one day.
- **U65** A position's page draws its price over a day and a week with the
  bot's own levels and fills: the engine's per-minute snapshot carries each
  live bot's last mark (F4, amended — the only price history at grid
  resolution, no new venue read); the fills come from the kept ledger
  (R18) by the link's prefix (I1); the window's rungs (slid, U57), its
  edges dashed, and liquidation in red when it is on the chart, named
  beneath when it is not. Buys and sells are ringed dots with a native
  tooltip; no script; nothing without two points, and a quiet line until
  the snapshots carry the price (the fleet's next restart).

## L — trades (D81)

- **U66** Every account says its MMR — maintenance margin over equity, the
  gauge the exchange liquidates at 100% — from the fleet's latest snapshot:
  in its box ("account MMR 27.9% · the exchange liquidates at 100%") and
  beside its leverage in the strip; red from 50%, its age said when the
  snapshot is over ten minutes old, nothing claimed without one. A card's
  folded tables align each heading with its numbers (right), the first
  column left and as wide as it needs — the info pages' `details td` rule
  had reached into them. *(the owner, 2026-10-11)*
- **L1** A new trade joins a running fleet within a cycle. The trade watch
  stats the trades file once a cycle; a changed file's new rows are each
  built by the fleet's own builder (`main.build_market_bot`, the one every
  bot meets at the start) and appended to the running bots. A trade on a
  venue the fleet has no client for, a builder's refusal, or a position
  another bot already holds (I2) is said and refused; the rest stand. A
  live trade then gets its symbol's risk tier and leverage set on the venue
  with every leg already there, as the start does, so it margins at the
  leverage it states. The
  fleet file watch (F12) leaves trades alone. At a start, the trades file's
  rows join the build like any row; a malformed file refuses the build.
- **L2** A trade is a one-round DCA row with no safety orders: its base
  order is the whole trade (capital x leverage unless stated), repeat is
  off, a DCA bot's ladder keys are refused by name, and its exit is still
  required (M3). The real bot then enters, sets its take profit, rests no
  safety order, and stands down when the round ends (M5).
- **L3** The trades file is per fleet (`logs/trades-<fleet>.json`, X7b's
  rule), changed only under its lock and re-read inside it. A market and
  side another row of the fleet holds, or a trade already open there, is
  refused. A trade's record (opened, by, reason, confidence) rides beside
  its terms. Clearing a finished trade removes its row and its tombstone,
  which only kept the finished trade from starting again.
- **L4** The owner's door: `python3 -m gridgremlin.trade <fleet.json> open
  long|short SYMBOL --capital Q --tp PCT [--leverage X] [--stop PCT]
  [--trail PCT --trail-from PCT] [--maker]`, `list`, `clear <botid>`.
  Percentages are of the entry; the stop is watched at the mark by the
  engine (a venue stop sits at one fixed level, X10). Every number meets the
  bot validator.
- **L5** Every reader sees a trade as the bot it is: the readout and its
  cards, the kept ledger, the digest, the market readings and the close
  command read the fleet with its open trades among its rows
  (`trades.with_trades`); a trade a config row already covers is not added
  twice; an unreadable trades file adds nothing.
- **L6** The owner's door on the panel: **new trade** in the navigation
  opens one form — account, side, market, investment, leverage, take
  profit, stop, trailing, maker or market — written through the same
  validator; a refusal is said above the form with the typing kept. Below
  it, every account's trades with a typed-name clear for one that has
  ended. A trade's card names it a trade, states its exit and who opened it
  when, offers **close trade** while it holds (the close page, one
  reduce-only market order) and **clear** once it has ended.
- **L7** A running trade is closed by its own bot, never from outside: a
  close request (`{t, by, reason}`) rides in the trade's record in the
  trades file; the fleet hands it to the trade's bot — at once when the
  file changes, and at the start for a request made before a restart —
  which flattens with one reduce-only market order under its own link and
  stands down, tombstoned with who asked and why. The first request
  stands. The owner's **close trade** on the panel, the agent's live
  `close` and the engine's day-loss flatten all write it; the close
  command (X15) stays for what a stopped bot left open. *(2026-10-10: the
  panel's close trade ran the close command, which refuses a bot that has
  not stood down — the button could never close a live trade)*

## J — the agent (D80)

- **J1** The agent's one door is a forced command behind a restricted ssh
  key (`gridgremlin.agent_door`): the key runs it and nothing else, and the
  fleet file is named by the owner in the key's own line, never by the
  agent. Two verbs, held by a spec so a third cannot creep in: **read** (its
  limits, its open trades, its intents left this hour, today's loss, as
  JSON) and **intent** (one JSON trade request). Anything else is refused by
  name. The model holds no key, shell, file, config or unit.
- **J3** The agent's limits are the fleet file's `agent` block, which only
  the owner's merged main changes: the markets it may trade, the most
  notional a trade and across its open trades, its most leverage, its loss
  for the UTC day (its own subaccount's equity at the first snapshot after
  midnight less its equity now), its intents per hour, a stop it must always
  set between a least and a most distance, its session hours, and `paper`
  (on unless the owner turns it off). Every limit refuses by name. A passing
  intent becomes a trade row through D81's validator, marked `by: agent`
  with its reason and confidence — or, in paper, is only checked. Every
  intent is logged with its verdict (`logs/agent-intents-<fleet>.jsonl`),
  the experiment's record. An agent fleet may start with no bot of its own
  and opens its venue's client at the build, behind the mainnet gate. Live,
  the engine enforces the day's loss too: at the limit every open trade of
  the agent's gets a close request (L7) — and a live agent fleet must name
  its watchdog, whose snapshots the day's loss is read from, or it is
  refused.

- **J6** Paper is a book judged by the market, not a log: a paper intent is
  filled at the last 1-minute close and recorded with its stop, take profit
  and trail; each time the door is used every open position is walked from
  its entry over Bybit's public 1-minute candles after the entry's minute
  — a candle opening beyond the stop fills at its open, one reaching both
  stop and take profit takes the stop, the trail moves after the candle is
  judged — and a position the candles closed is frozen. Fees on both sides
  at the base tier (a take profit's exit at maker, every other exit at
  taker; a maker entry assumed filled, stated as optimistic). In paper the
  open trades, the gross and the day's loss are the book's (closed since
  00:00 UTC plus open at the last price). `side: close` closes a market's
  paper positions at the last price — never refused by the hour's count or
  the session, since reducing is always allowed — unless the candles
  closed them first; live, it writes a close request for each of the
  agent's trades on that market (L7). A market that cannot be read closes
  nothing.
- **J5** The score is computed from the closed positions alone: P&L after
  fees against flat, the worst drawdown of the closed P&L, the hit rate,
  the average win and loss, fees as a share of gross, the count by how each
  closed, and calibration — hit rate by confidence band (below 0.5, 0.5 to
  0.7, 0.7 and above), and whether higher bands win at least as often. No
  verdict before 200 closed trades: the score says how many remain. The
  nightly digest carries it under the agent fleet's section (the paper
  book; a live agent's trades are their own cards), and the readout
  contract carries it as `agent` — the score, its words and the open paper
  positions — which the panel draws as the account's agent box. A paper
  agent fleet with no rows reads no venue, so its readout — and the
  digest's section — need no keys: paper needs no subaccount; a live one
  does. The panel reads an agent's fleet though it has no bots (a fleet
  with neither bots nor an agent block is a fresh world and is not read).

- **J2** The agent's working program does the arithmetic of technical
  analysis in code, so a model — or the owner by hand — only judges
  (`python3 -m gridgremlin.agent_tools <SYMBOL> … [--tf 5m,15m,1h,4h]`).
  Read-only, Bybit's public endpoints, no key. Per market, one plain-text
  block: the price, the day's change, funding per 8 h, open interest's
  24 h change, the accounts' long share, depth within 1% (D67's reader);
  per timeframe, EMA 9/21/50/200 and how many the price sits above, RSI 14
  (Wilder), ATR 14 as a percent, Bollinger width, ADX with the D67 regime
  word, and the last three pivot highs and lows (a flat top one level, a
  dead-flat window none); the session's VWAP from its opening (Asia 00,
  Europe 08, US 16 UTC) and the UTC day's high and low. A figure that
  cannot be read is said in its place, never guessed.

## H — the hedged portfolio (D78)

The design is `docs/PORTFOLIO.md`; an invariant appears here with the spec
that pins it (T1).

- **H1** The row is its assets, hedges, clock and risk, with stated defaults.
  `strategy: portfolio` carries `name` (its id, `pfo<name>`), `venue`,
  `account` (the keys it trades with, H5), `capital`, `assets` — `{coin,
  weight, holding}` (`holding`: coins on spot the row adopts as its own,
  never on an outright short), each coin once, no zero weight, the weights' sizes summing to 1
  (to `spot_leverage` with `margin`, which needs `spot_borrow`), none above
  `risk.max_weight` (default 0.5; up to 10, since a levered weight may
  exceed 1), a negative weight an outright short (H1c) — and
  `hedge`: one `{product, ratio}` for every long, or one per coin, product in
  usdt / usdc / inverse (default inverse), ratio 0–3 (default 1); a hedge on a
  coin not held is refused, a short's entry may name only its product.
  `rebalance` {every_hours 24, drift_pct 0.05, min_notional 0, cash_reserve
  0.003}; `regime`
  opt-in {tilt ≤ 0.9, hold_hours required, source structure}; `funding_rule`
  on by default {stand_down_below 0, trailing_days 7}; `risk` {max_loss with
  max_loss_since, margin_floor_pct 0.4, basis_stop_pct 0.01, max_weight 0.5}.
  Every refusal names the key and the rule.
- **H1c** An outright short is a USD-margined perp: its product defaults to
  `usdt`, may be `usdc`, and is never `inverse` — an inverse contract is
  margined in its own coin, so the row would hold the coin, a long the short
  exists not to have and the planner never counts. Refused, naming why.
  *(the 2026-10-09 review: the outright inverse short's coin collateral was
  not modelled)*
- **H2** The row runs in the fleet on legs that are identities. The build
  resolves each leg from the venue's catalogue (A1): a spot market per
  long asset, a short per hedged asset on its product (usdt → linear
  `<COIN>USDT`, usdc → linear `<COIN>PERP`, inverse → `<COIN>USD`), the
  outright shorts the same; each is an I2 identity the fleet holds unique,
  so a grid on the row's hedge market is refused at build. The row's book
  is its own: it starts at first sight from `capital` in cash (the row's
  `spot_quote`, USDT or USDC — its spot legs are `<COIN><QUOTE>`) plus each
  asset's stated `holding`, and moves only by the row's own fills (a buy's
  fee shaved from the coins received), an inverse leg's funding — paid in
  the coin, it joins the book as coins — and its cash, like its coins,
  is bounded by what the wallet holds in its quote; at a tick spot sells
  are placed before spot buys, the perps after, and a spot buy is placed
  in quote ("spend this much"), since the venue checks a coin-sized market
  buy at a buffered price and refuses one that spends nearly all the cash; (link-attributed, deduped
  by execution id across a re-read overlap) and the funding its shorts
  received; coins are bounded by the wallet (D76). The book, the clock's
  last tick, the unspent cash and the value the row is judged against
  live in `logs/portfolio_state.json` — the third durable local fact
  beside X7 and G22, written atomically under its lock after every cycle,
  missing meaning never seen, unreadable failing closed. The row reads
  the venue at most once a minute; the plan runs on its clock and is
  placed as market orders (a daily rebalance is a taker act by design;
  G13's post-only law is the grid's). The row learns new terms at a
  restart on an edited file: a raised `capital` is cash to spend, a raised
  `holding` adopts the difference, a lowered one of either is said and
  nothing is sold, a changed asset list is said, a changed `spot_quote` is
  a new cash pot of the capital — or, for a levered row whose loan the
  owner swapped to the new coin on the venue, the new quote's negative
  balance read as the loan, nothing contributed — and the next read plans
  at once, not at the next tick. A Hyperliquid portfolio row is refused
  by name until its leg is built.
- **H3** The plan at a tick is pure. Between ticks (`every_hours` since the
  last) nothing is wanted. The stack is the row's equity: its coins at
  mark plus its cash, which is negative when the venue has lent it quote;
  each target is weight × equity, so with `margin` (weights summing to
  `spot_leverage`) the coins held are `spot_leverage` × equity, the
  excess bought on the venue's loan (the borrow flag on every spot buy)
  and the loan's interest the row's own. At a tick, in order: cash (a
  linear leg's funding, capital raised) buys spot toward the weights —
  the longs' shortfalls from their targets, by shortfall, which at the
  weights is pro rata; what the shortfalls do not need stays cash (an
  outright short's share is its margin), `rebalance.cash_reserve` (0.3%)
  of the cash kept for the buys' own fees; a long leg past `drift_pct` of the stack is
  bought or sold to its weight; an outright short past the drift is resized
  from the stack; a hedge past the drift of its holding is resized to its
  ratio — the row's ratio leaned by the regime tilt (up × (1 − tilt), down ×
  (1 + tilt)) and stood down to zero while the trailing funding to the short
  is below the funding rule's floor. A want under `min_notional` is left.
  Each want is one order, named for why it is wanted.
- **H4** The risk is the portfolio's. The row is valued every read — the
  stack at mark, the cash and parked cash, the shorts' open P&L, their
  realised P&L and fees from the row's own books — against the value at
  its anchor (its first sight, moved along by every contribution since —
  a capital raise, an adopted holding at the day's price, a new cash pot
  — so the total counts only what the book made; `max_loss_since` is
  the stated moment the loss counts from). At `max_loss` every leg goes together in one cycle —
  shorts bought back reduce-only, the stack sold, as market orders — then
  the tombstone (X7) and the page; a leg that refuses is named and the
  rest still go, since a hedged book cut on one side is a directional bet
  taken at the worst moment. The owner's flatten
  (`gridgremlin.portfolio_flatten <fleet> <name> [--reset]`, the fleet
  stopped) is the same act by hand — the cycle's reads, every leg
  together, the venue read back; `--reset` forgets the row's book and its
  tombstone so the next start is a first sight. A parked asset's share is its parked cash;
  the rest keep their relative shares of the stack. Under
  `margin_floor_pct` of free margin the whole book shrinks each read by
  the share that restores the floor plus a 5-point buffer (the shortfall
  over the initial margin the account uses; 3% at least, a quarter at
  most; a quarter when the venue states no margin) — each long's coins
  sold and its hedge bought back together, an outright short bought back
  by the same share — so the book stays neutral while the loan is
  repaid; said once an hour. A levered row remembers the floor's verdict:
  after a trim it aims lower by the trimmed share, and eases back toward
  the file's leverage by 5% a tick only while free margin sits two
  buffers above the floor — so the daily tick does not lever back into
  the floor it was just trimmed from. The loan's cost is read from the
  venue's own ledger (`borrow_history`: the hourly charges on the
  interest-bearing size) and kept as the row's own figure; the latest
  hourly rate, as a yearly one, is judged against `margin.borrow_apr_max`
  — above it the loan stands down (the cap to 1×, planned at the next
  read, said once an hour) and the ratchet does not ease back while the
  rate stays above. *(measured 2026-10-08 on the carry sub: 0.000449%
  an hour, 3.93% a year, 2.34 USDT for the first hour on 520k)* The loan
  stands down the same way when the shorts' trailing funding, as a yearly
  yield on what they cover at mark, is under the venue's rate (H1: a loan
  that costs more than the carry it buys is a levered long with a bill) —
  judged once the row has a day of history, over the funding rule's
  window, and the ratchet does not ease back while it holds *(designed in
  H1, found unbuilt 2026-10-09)*. Past
  `basis_stop_pct` between an asset's perp and spot marks, that asset's
  pair alone is unwound — hedge bought back, coins sold, the quote parked
  — and the rest held; it re-enters from its parked cash when the basis is
  back under half the stop. The funding rule's stand-down lifts a hedge
  and keeps the stack (H3).
- **H8** An inverse hedge is counted in its own coin. A short of N $1
  contracts opened at E has a constant coin exposure of N / E; its open P&L,
  N (1/mark − 1/E), accrues in the coin. So the coins the planner weighs and
  hedges are the row's spot coins, its hedge's realised coin net of the
  coin-paid fees (settled into the coin's wallet, bounded by it — D76 —
  and counted there once, never again as quote), and its hedge's open
  coin P&L; the hedge is N / mark; and a ratio-1 book then needs no hedge
  order through any price path. The planner's equity is the row's: those
  coins at mark, the cash with every linear leg's P&L. An inverse leg's
  average entry is the contracts-weighted harmonic mean. The rehearsal
  holds the same rules and pays its fees and interest from the cash.
  *(the return-split audit, 2026-10-09, confirmed by an independent review:
  the hedge counted against the spot coins alone drifted a ratio-1 book net
  short in a rally and long in a fall, and the arithmetic entry invented
  ~40 points of the rehearsal's two-year return; the true neutral basket
  earned its funding, x1.13, at a 1% drawdown)*
- **H6** The card says the three truths. A portfolio's card shows the
  stack's value and coins, one line per asset (weight target → actual,
  hedge ratio target → actual, coins hedged, the regime word when the tilt
  is on, "unwound" under the basis stop), and three money lines that never
  mix: **carry** (funding received), **tilt** (the shorts' excess over
  neutral — the row's ratio × the coins held — marked each read against
  the price's move; no second model), **basis & shape** (what is left of
  the total since the anchor after those two and after the loan's
  interest: the spot/perp gap and the inverse contract's shape); the
  loan's interest and its yearly rate stand beside them, their own. The exchange box and the strip count the
  row's total like any card (D63); the *by strategy* view groups it under
  "portfolios", the *by coin* view too. A regime from D67's readings is
  believed only after it has held `hold_hours` ('trending up' → up,
  'trending down' → down, a lean or a range → range). The row is edited in
  the fleet file, not the form.
- **H7** The rehearsal is the engine's own planner over history —
  `gridgremlin/portfolio_rehearse.py` runs `plan_portfolio` on hourly
  closes and 8h funding per coin with the research's fees (spot 0.1%,
  perp 0.02%, a 10% collateral haircut on the margin test) and answers
  equity (× start), the worst drawdown, funding, fees and the ticks that
  placed. It reproduces the research harness (`ops/research/
  basket_carry.py`) within 1.5 points of equity over 120 synthetic days,
  with the same drawdown and funding; the CLI fetches two years through
  the research's own fetchers (Hyperliquid's funding for an HL row).
- **H3b** The funding rule judges the MARKET's funding, never the row's own
  payments: the sum of the hedge contract's funding rates over
  `trailing_days`, as a yearly rate (`trailing_yield`), judged only after a
  day; under `stand_down_below` (a yearly fraction, default 0) the hedge
  stands down and stays down until the market's rate recovers. Unreadable
  rates judge nothing and the hedge stays. The rehearsal applies the same
  figure. *(the review: a raw window sum had no units; then found: judged on
  the row's payments, which stop once the hedge is lifted, the rule saw
  nothing and re-hedged the next day — a daily flip-flop, 2026-10-10)*
- **H7b** The tilt is rehearsed with the regime the live bot would have
  read: Wilder's ADX on the last 60 CLOSED 4h candles, built from the hourly
  ones, turned into the planner's word (`regime_word`) and believed only
  after it has held `hold_hours` — no candle from after the moment judged.
  *(before, the rehearsal passed no regimes and a tilt rehearsed as neutral;
  first scored 2026-10-10)*
- **H5** Two accounts on one box. A fleet file names its `account`
  (default `default`, today's keys untouched); every row on it must name
  the same, or none — one account per process (F3). At start the process
  reads that account's keys under the standard names: `BYBIT_<NAME>_API_KEY`,
  `_API_SECRET`, `_DEMO`, `_TESTNET` (an account that says neither is real
  money, D25 decides) and `HL_<NAME>_SUBACCOUNT` — the sub-account's address,
  read for truth and stamped on every signed action as its `vaultAddress`;
  the signer stays `HL_PRIVATE_KEY`, the master's agent. An account with no
  keys on either venue refuses by name. The fleet lock is named for the
  account too, so two accounts on one box are two locks.

## U — the panel's setup form

- **U1** The advanced form reaches every key the config accepts: its schema is
  held to `GRID_KEYS`, `MARTINGALE_KEYS`, `STOP_KEYS` and `SLIDE_KEYS` by spec, so a
  key the engine learns and the form does not is a failure. Every field has a
  plain-word label and a line of help.
- **U2** The form builds a row exactly as the file would hold it and validates
  nothing itself: a blank is left out (the engine's default applies, the engine's
  refusal names what is missing); a block's fields count only when the block is
  switched on; percent fields are typed as percent and stored as the fraction.
  Row → form → row is lossless for every shipped row.
- **U3** The quick setup is a preset and three answers; every other number derives
  from the public mark. Every preset at every caution, on both venues, is a row the
  engine accepts and the build can link (I3). The stop is opt-in (D32).
- **U4** The summary is written from the VALIDATED config, in plain words, and names
  what the bot lacks as well as what it has (no stop loss; following the losing way
  buys beyond its investment).
- **U5** The setup form holds no key and calls no private endpoint (§11's floor).
- **U6** A refusal returns to the form it came from with every value kept and the
  engine's words on top. Nothing is written before the typed botid (§11's fourth
  gate, unchanged). Gate 1 runs the build's link check, so the panel cannot accept
  a row the fleet would refuse to build. A DCA bot whose first order is below the
  venue's minimum at today's price is refused at the form, with the numbers.
- **U7** Edit is the same advanced form, filled in from the row: every setting of
  the bot can change; its identity (symbol, side, market type — I2) is shown and
  fixed, and a forged one is refused by the engine's own identity check. The row is
  rebuilt from the form, which reaches every engine key (U1), and the operator's own
  `_` keys ride along. A choice left at "(default)" stays out of the file.

- **U8** The bot is drawn on its price. Every level on the chart is computed on
  the server by the engine's own functions (`lattice_price`, `stop_level_for`,
  `martingale_schedule`) from the validated config: the edges and rungs, the stop,
  the slide triggers; a martingale's orders and targets anchored at the mark. The
  page's script computes no level: it drags an edge, writes the price under the
  pointer into the form, and asks the server to redraw. Only the two edges drag.
  An unfinished grid still draws the edges it has; with none, a range 10% either
  side of the mark is offered. Labels of close lines are stacked, never
  overprinted. Candles are public data, kept five minutes; no key (U5).
- **U9** The summary page answers "what if the price moves": one straight move
  from the mark, starting flat. The orders are the engine's own plan at the mark
  (`plan_grid` from flat; `martingale_schedule` with the first order at the mark)
  and an order counts as filled when the move passes its price. Holdings, average,
  worth, gain or loss and the margin behind it (cost / leverage) follow from those
  fills; the money goes through the adapter (A4), so an inverse market is counted
  in its own terms. A `mark_price` stop on the way ends the move at the stop, with
  the loss taken there and nothing held; a martingale's targets the price reaches
  sell their shares. A slide the move would trigger is named, never simulated, and
  an adverse one is said to buy more than is counted. Fees, funding and grid
  round trips are left out, and the page says so. The page's script computes no
  price and no money: it reads the slider and shows the server's words.
- **U10** A refresh does not undo the reader. The live page reloads whole; the
  boxes the reader opened reopen, the scroll position returns and the chosen
  theme holds, remembered in the browser tab by one script that carries no number.
  Each foldable box is named by fleet and botid. The export carries no script.
- **U11** No form is a dead end. Every page off the main one opens with the link
  back to it. A refusal is the first thing on the page it returns to: boxed, saying
  that nothing was saved, then the engine's words. The commonest one (a bot for
  that market and side already exists, I2) adds what to do: the link to edit that
  bot, or pick another coin or direction.

- **U12** The main page's bots can be arranged, per venue: as listed (the fleet
  file's order), longs then shorts, or pairs (a market held both ways, its long
  beside its short, then the rest). It is an arrangement only: every bot appears
  exactly once in every view. The choice lives in the address (`?view=`), so the
  refresh keeps it, and it carries between the cards and the table.

- **U14** The summary page rehearses the bot exactly as configured: the whole row
  goes to the rehearsal, so a martingale and every setting of a grid are replayed,
  not a simplified draft. The result names its candles, and for a martingale reads
  in rounds: rounds completed, add-on orders filled, deepest reached, stops fired,
  rounds closed by the hold limit, how it ended. At most 90 days.
- **U13** The rehearsal's form holds what was typed: a result or a refusal comes
  back above the same values, escaped as text. Its columns carry the setup form's
  words (coin, direction, lowest and highest price, levels, investment).

- **U15** Long and short read at a glance: a coloured tag (LONG / SHORT) on every
  card and table row and a coloured edge on the card. A bot the engine reports dead
  says DEAD whether or not it had fills in the window. Buttons that act are filled
  in the accent colour; the small ones (theme, change something) stay quiet; the
  one that sends an order is red.

- **U16** A card states its terms: the investment, the leverage (when not 1x) and
  the most the bot puts in the market (a grid's `capital × leverage`, a
  martingale's ladder total), from the row's own numbers carried on the contract.

- **U17** The summary page keeps the next step in reach: the apply box, named for
  what it does ("create this bot", "apply the change", "remove this bot"), sits
  under the summary; the file diff and the dry-run orders fold away. The forms'
  forward button says it is a step: "Next: review the bot →".

- **U18** The typed name is the decision; its capitals and stray spaces are not.
  Apply, close and revive accept the bot's name in any case, trimmed; anything
  else is refused with the name spelled out and "capitals do not matter".
- **U19** The panel writes the file a hand would write: one writer, the committed
  files' own format; a typed whole number written whole; the engine's default
  venue left out; an edited row keeps its key order. Every shipped config
  round-trips byte-identical, and every shipped row opened in the form and
  applied untouched writes the file it read.
- **U20** A bot's name typed into the unit box is pointed to its tombstone's own
  revive box; the tombstone table says how to revive.
- **U21** Every page off the main one opens with "← back" (one step) beside
  "back to your bots".
- **U22** The cards page carries "numbers: show all · hide all"; no word on it
  says open or close; the table and the export carry neither.
- **U23** The sweep on the page fits the box: it reads a fixed 14 days (T9),
  14 replays per window, not 22; the rehearsal subprocess runs under the
  fleets' priority; the buttons say how long and "press once", and read
  "sweeping…" once pressed. The terminal has no limit.
- **U24** The size is typed in the unit the person thinks in — collateral,
  position size in the quote, or coins — and becomes `capital` (collateral) by
  the leverage and today's price before the row is read; a unit that needs the
  price refuses without one; the sentence says the coins at today's price.
- **U25** The coin box offers the venue's own markets (Bybit's tradable USDT
  and USDC perps; HL's universe) as a list, cached an hour, typing still works;
  an unreachable venue draws no list and refuses nothing.
- **U26** A rehearsal is a job. The form's post starts it and redirects to its
  own address; that page answers at once, refreshes itself every three seconds
  with the engine's own progress words ("fetching candles", "replay 6 of about
  14", "replaying N candles") read live from the subprocess, and becomes the
  verdict when the job is done; a finished verdict stays fifteen minutes, an
  unknown job is refused by name. No spinner: nothing on the page claims work
  the engine has not reported.
- **U27** Grids and gap are one question shown both ways: beside the grid
  count a live "≈ x% gap", beside the gap a live "≈ n grids", from the typed
  range and spacing; only the one the person typed is written.
- **U28** The quick page's "open in the advanced form" needs nothing filled:
  whatever was typed rides over (coin, size and its unit, the preset's side and
  strategy), the rest stays blank for the engine's defaults, and the page says
  so beside the button.
- **U29** Leaving the working page stops the run. The page's three-second
  refreshes are the job's heartbeat; unseen for twelve seconds (three missed),
  the subprocess is ended and the page, when next seen, says the run was
  stopped because the page was left, in words, as a refusal. A finished verdict
  is not touched by leaving. Over the words a progress bar drawn from the
  engine's own fraction (the CLI emits `frac` beside each progress line); no
  bar moves on its own. Every button is visibly a button: the quiet ones carry
  the accent's soft tint and border.
- **U30** A verdict hands its exact draft to the advanced form. Under a
  rehearsal's verdict, "set up this bot →"; on every row of the grid-count
  comparison, "set up with n grids →". Each opens the advanced form through the
  panel's own reopen door with the draft's values carried over (that row's
  count in place of the draft's; weights written for another count set aside)
  and the verdict's own words as the note on top — the net and benchmark, or
  the count's place in the plateau and whether the older week's choice held
  up. It opens the form only; every gate still follows, and nothing is applied.
- **U31** The written page names the next step. After an apply it says what
  starts now and what waits: a new or removed bot starts or leaves at the
  fleet's next restart, and the page names the unit that runs this fleet file
  (by the tag they share) with the way to restart it from control, and the
  restart's own small risk in a sentence; an edit says the hot terms apply
  within seconds and the cold ones wait. Then the way back to the cards.
- **U32** A bot's name pasted where a market was wanted is named as one: every
  "lists no such market" refusal, on both venues and in the terminal, says
  "looks like a bot's name, not a market; the coin inside it is X, type that"
  when the text is shaped like an id (I1), and nothing else otherwise.
  *(2026-10-05: a Bybit name ending in USDC says the USDC perpetual is
  named with PERP instead — BTCUSDC → "BTCPERP, type that".)*
- **U33** Every blank says what it becomes. The advanced form's empty boxes
  carry the engine's own default as their placeholder ("default 1", "default
  5%", "default off") or "required" where nothing stands in, and each dropdown
  names its default; the values are read from the engine by validating a
  minimal row and each block on its own, never typed by hand, so they cannot
  drift from the loader. The words vanish as soon as something is typed.
- **U34** A new bot is not running until the restart, and the panel says so
  everywhere it could be mistaken. Its card reads NOT STARTED, "waits for the
  fleet's restart", not RESTING, judged by the engine's last snapshot. The
  control page lists under each unit what waits for a restart: rows in the
  file the engine does not run, and rows the engine runs that left the file.
  A bot's name typed into the unit box is answered with its fleet's unit and
  the word restart. "start" on a running unit does nothing and says so,
  pointing at restart, instead of "done".
- **U35** The state words explain themselves and the card says what rests.
  NOT STARTED, RESTING, HOLDING, FLAT and DEAD each carry their meaning on
  hover and their own colour; the key page defines them and the placement rule
  in one paragraph. From V15 the card shows an "orders" line in words —
  "resting: 1 buy · waiting: 3 sells — placed when the price comes within 5% of
  them (the nearest at 0.2054)" — so a grid that rests little is read as
  waiting, not broken.
- **U36** Every card says what kind of thing the bot is, in one line, first:
  the market (futures USDT/USDC-margined, futures coin-margined, spot, spot on
  margin), the leverage or "no leverage", and for a DCA whether its add-ons
  grow — "martingale-style: each add-on 1.5× the last, up to 2", with the one
  word that needs it explained on hover — or "equal add-ons". The contract
  carries the facts (`terms`: market type, strategy, borrow, multiplier, add-ons).
- **U37** A sentence on a card spans the card. The orders line (U35) is one
  cell across both columns with its label inline, not a value squeezed into the
  right-hand column beside a fixed-width label.
- **U38** The other box fills itself. Type the grid count and the gap box is
  written with the gap it means (and the other way round), dim, italic, saying
  which box it came from; the one typed last governs, a loaded row's stated one
  governs, and the derived box is dropped on submit so the engine receives one
  of the two, as the config requires. Without script both boxes stay free.
- **U39** The reversal preset (D54) is two quick setups that meet at a mid:
  the long half first — lower at the mid less the preset's half-width, upper
  at the mid, half the investment, half the rungs, no slide, a level stop if
  asked — through its gates and its typed name; the written page then
  offers the short half with the same answers and the same mid carried as
  hidden fields, through its own gates and name. The gates page says which
  half it is. The quick form's "Mid price" box skews the pair: blank is
  today's price; above it the long half holds the price and the short half
  waits above; below it the other way. Hyperliquid refuses the pair by name
  (one position per coin).
- **U42** A written grid offers its other side. After any grid is written on
  a venue that holds both sides of a market, the written page offers its
  mirror — the same width, rungs, money and leverage past its edge, a short
  above a long's upper or a long below a short's lower, slide and seed left
  behind, a level stop mirrored past the new far edge — through its own
  gates and name. The two are a reversal pair meeting at that edge (D54)
  whichever door the first came through.

- **U43** Several units at once. The control page's unit box takes several
  names, separated by spaces or commas; every one must be an armed unit or
  nothing is done (each refusal as for one name), and one systemctl call
  carries them all.
- **U44** A holding is said in coins, value and cost. Every card states its
  position as the coins held, what they are worth at the mark, and what they
  cost at the average (an inverse position, counted by the venue in dollars,
  also as coins); the page's "size in" switch shows all three or one, kept
  per browser tab like the theme.
- **U45** The money has a box of its own. Every card's total after fees sits
  in a bordered box, coloured by its sign, with what it is made of beneath it:
  realised after fees, funding (R20), and open at the mark ('—' when the mark
  or the funding is unknown, R5).
  Each exchange's section carries the same box under its heading, summing its
  bots — each counted as its own card says (R14), so the box never claims one
  window for all. *(owner, 2026-10-05: "maybe we could make it more visible…
  in its own box around where it is placed now")*
- **U46** The panel reads cleanly. Every link is a button (the quiet
  button's look; a switch's current choice filled; a destructive door —
  remove, close — red-edged), and the dots that separated links as text are
  dropped on the way out. A dropdown never says "(default)": the default is
  named as an option — the engine's own, else `none` for the stop candle and
  `stop_bot` for the stop action — and a key the row does not state is still
  written as nothing (U33); a key it does state lists the plain options with
  its own chosen, so the form never drops a stated key behind the owner's
  back (a dropped cold key reads as a change, F12). A card's kind line is a
  line of its own. Audited against every page the live panel renders,
  spell-checked: the kind line ran into the holding ("75x leverageholding")
  and the table's LONG/SHORT badge into the bot's name. *(owner, 2026-10-06:
  "i see leverageheld as one word on all cards … make all clickable links
  buttons … just simply state the options available")*
- **U47** One readout per fleet at a time. A fresh readout is served as it
  is; a stale one is served at once while ONE background refresh runs (the
  page says its age), a failed refresh keeping the last; with none yet, the
  first asker reads and the rest wait for that same read. *(2026-10-06: each
  request whose cache had expired started its own readout; on a slow venue
  they piled up — 18 demo readouts at once, 350 timeouts in an hour, the page
  and the owner's HYPE rehearsal hung; the trading fleet itself was untouched)*
- **U48** Every fleet heading names its network in the exchange's own words —
  Bybit Demo Trading / Testnet / Mainnet, Hyperliquid Testnet / Mainnet —
  Mainnet in red, linking to `/trading`, which explains the networks and what
  real money asks for and never says how to arm it (D65). The name is the one
  the running fleet connected to, written into every snapshot (`tiers`); the
  readout's own connection stands in only before the first snapshot. No panel
  source names the network switches, and a row carrying one is refused at the
  gate.
- **U49** On a Mainnet fleet the panel asks twice: a new bot's capital, and an
  edit raising capital or leverage past double what the row holds, must be
  typed again before the file is written (D64). The check reads the readout
  the page was drawn from and never starts one; an unknown network asks
  nothing more.
- **U50** The exchange boxes ride in a strip pinned to the top of the page:
  one line per fleet — name (a jump to its box), network, total after fees,
  bots and how many are dead, the account's leverage now — read from the
  same contract as the box, so the two never disagree; one grid, so every
  column lines up whatever the words' lengths. Cards, table and the static
  export alike.
- **U51** Every page link and every view switch sits in one side panel beside
  the cards — pages, arrange, numbers (cards only), size in, leverage, theme
  — 14em wide, pinned under the strip while the page
  scrolls, folding into a row under it at phone width. The export, having no actions, has none. Spacing comes
  from one scale (`--gap`, `--gap-s`) shared by cards, boxes, pills and
  buttons.
- **U52** A DCA card folds its ladder: for each step, where it fills from
  the base price, its size, what is then committed, the average entry and
  how far the price must come back for take-profit; the summary line says
  the move the ladder covers. From the engine's own schedule, carried in the
  contract's terms as fractions of the base price, so it holds before a round
  and during one. A grid card has none.
- **U54** The bots can be arranged by strategy and by coin, beside U12's
  arrangements: *by strategy* puts one heading per kind of bot (grids, DCA,
  pairs) in the order the kinds first appear; *by coin* puts one heading per
  coin across its products (spot, perp, inverse, each side), so what shares a
  wallet or an index sits together. Every bot appears exactly once in every
  view; the choice rides the links and the table alike.
- **U53** Every money figure names its coin. The contract's terms carry each
  bot's `quote` (the coin its capital, notional, loss and P&L are in) and
  `margin_coin` (the coin the venue's margin on its position is in): the
  settle quote for linear and spot, dollars and the base coin for inverse. The
  card's total, holding worth and cost, margin, investment, loss limit and
  ladder say it; the exchange's total and the strip join the coins its bots
  use. A contract without terms answers from the bot's own name. A margin in
  a dollar coin shows two decimals; one held in the coin itself, six figures.

## P — the panel's boundary and the keys

- **P1** The panel holds its boundary behind the token too. Operator and
  venue text is HTML-escaped wherever it is drawn (the diff, refusals,
  tombstone rows, systemctl's words, hidden fields); /init writes only the
  fleet file the panel was started on; a negative or unreadable
  Content-Length reads nothing; at most two rehearsals run at once on the
  one-core box, under `nice` as the command (not preexec_fn in a threaded
  server), their stdout drained beside stderr. *(audit 2026-10-05)*
- **P2** The keys stay the owner's. `.env` readable by anyone but its owner
  is refused by name with the chmod to run; the Telegram token reaches curl
  on stdin (`-K -`) from the shell's own printf, never in an argv `ps` can
  read. *(audit 2026-10-05)*

- **P3** A Telegram token never leaves a sender in an error. The token travels
  in the request URL; every sender — the fleet's notifier, the watchdog, the
  phone — raises a redacted error, so no journal or log line can carry it.
## T — testing meta-invariants

- **T1** Every invariant in this file has a spec named after its ID — or after the
  D-number that minted it (both namespaces are stable; D23's specs pin M10/M11).
  A spec that passes with the behaviour sabotaged is a defect. *(audit 3.8)*
- **T2** Every loop is driven at least two iterations by some spec. *(the fleet-loop
  NameError that no spec caught)*
- **T3a** The backtester's money is the adapter's (A4): fees and funding on
  the adapter's notional (qty × price for linear and spot, the contracts
  for inverse), the basis by its average (arithmetic by quantity; harmonic
  for inverse), P&L realised and marked in its settle coin and stated in
  USD — so an inverse or spot row rehearses in its own maths; the
  linear-only refusal is gone (the owner's rehearse of the inverse ETH
  long, 2026-10-08).
- **T3** The backtester drives the real `plan()`; fills require trade-through, not
  touch; funding is modelled; inventory is counted in integer qty-steps — float
  subtract-then-floor drops a whole step per iteration *(audit 2026-08-06)*. *(freqtrade + passivbot studies)*
- **T7** The martingale's rehearsal has no second engine: the real `Bot` runs
  cycle by cycle against a venue made of candles (`replay.BarVenue`), so every
  stop, limit and round rule is the live code. The pretend venue's assumptions are
  stated: a candle is walked open → adverse extreme → the other extreme → close,
  so a stop comes before a target in the same candle; whatever rests on the venue
  fills in the order the price reaches it; a resting limit needs trade-through
  (T3) and pays the maker fee, market orders and the venue's own TP/SL the taker
  fee; fills are never stamped in the bot's future; nothing is refused for margin.
  Anything timed in seconds is judged at quarter-candle steps. The ledger is R2's
  own (`apply_fill`). The venue's trailing stop is modelled (armed at its
  activation, a fixed distance behind the best price since). What is not modelled
  is refused by name (a `position_sl`). Five-minute candles. The pretend venue
  wears the ROW's venue shape: a Hyperliquid row rehearses against a venue that
  hosts no position TP/SL (D21), so the engine's trail (M21) and resting exits
  are what run; the result says which shape it wore.
- **T8** The step optimiser is the rehearsal, swept (D50). `sweep_rungs` runs
  the grid backtester (T3/T6) once per candidate rung count over the same
  5-minute candles, the range as written; the score is net (grid profit − fees);
  every row is returned (rungs, gap, net, trips, fees, fee share, max drawdown),
  sorted; the coarse pass is every eighth count from 5, the best is then refined
  by ±4 and ±2 (14 replays — a 30-day sweep of 22 took 293 s on the one-core
  box); the plateau is every candidate
  within 5% of the best net. A candidate whose gap cannot clear the round-trip
  fee is a row that says so (G16) and is not run; so is one whose level's order
  sits under the venue's minimum (F8); a candidate the engine refuses is a row
  in the engine's words. Candles come from the row's venue (Bybit's public
  klines; Hyperliquid's own, the testnet's). Keys written for one rung count
  (`rung_weights`, `rung_sizing`, `seed`) are set aside for the sweep and
  named in `dropped`. A martingale has no step to find and is refused by name.
  Nothing is applied by the sweep.
- **T9** The sweep is read on two windows and tested out of sample. The page's
  "compare grid counts" fetches 14 days of 5-minute candles once and sweeps three
  ways: the whole, the newer 7 days, the older 7. The count chosen on the older
  half alone is scored on the newer half against that half's own best: within a
  tenth of it the choice holds up; otherwise the sweep is fitting noise and the
  page says so. Beside it, the share of candles whose close sat inside the range,
  for each window — a weak result is explained before the grid is blamed. The
  table shows both windows' nets per count, both bests marked, the 14-day
  plateau coloured. CLI `--windows`.
- **T4** v3's `plan()` is diffed against v2's on identical fixtures before v3 places a
  single live order. *(the v1→v2 method)*
- **T5** Docs cite spec IDs; no doc asserts behaviour a spec doesn't pin. *("prose rots;
  an assertion fails loudly")*
- **T6** The backtester rests only what the live bot would rest: the placement window
  (W1) filters each bar's plan before fills are judged, and the window offset (G17)
  is carried bar to bar. Entries stay optimistic on coarse bars — every rung a bar
  trades through fills, where a live fast move skips rungs — so a replay is run on
  bars no coarser than the move it asks about, and says which. A slide's confirmation
  (G21) is honoured in whole bars: the trigger must still hold at the open of
  ⌈confirm_seconds / bar⌉ further bars. *(the 48-day post-mortem: an hourly replay
  carried 3× the live short inventory)*
- **T10** The grid's rehearsal charges the market's own funding: a Bybit
  futures grid's window reads the settlements (public), and each one the
  held position crosses is paid or received at its rate on the notional at
  that bar's close; unread or not read for the market (spot, Hyperliquid,
  a DCA bot) is said as "not modelled", never as nothing. Margin is the
  account's, which one row cannot know, and D34 buys an adverse slide from
  free balance — so the replay trades as decided and only says when the
  row on its capital alone would first have met its maintenance margin
  (Bybit's base tier, 0.5%) at a bar's worst price: a risk line, never a
  refusal or a stop.
- **T11** The rehearsal projects the account's MMR, the exchange's own
  liquidation gauge (maintenance margin over equity; Bybit liquidates at
  100%): from the account's latest snapshot — the venue's default account,
  named — each bar's worst price adds the row's maintenance margin and P&L,
  and the verdict says the start, the peak and the first bar it would have
  reached 100%. No snapshot: nothing claimed. *(the owner, 2026-10-11:
  "cant we just use MMR that the exchange shows?")*
- **T12** A spec never reaches the network: the runner refuses name
  resolution for anything but loopback (the panel's specs serve on
  127.0.0.1), so the workstation runs the suite as GitHub's runners do.
  *(2026-10-10: a door spec fetched a live price — green here, red on the
  public edition's CI, where Bybit answers 403)*

- **T13** No tracked file carries a Telegram bot token, in its name or its
  text (digits, then `AA…`: a shape nothing else has). The suite lists the
  tracked files (every file, in an exported tree) and refuses any match.
  *(2026-10-11: a file named with the live bot token was committed by a
  blind `git add -A` on 2026-10-07 and sat in the private repo four days;
  the sweep of added lines never sees a filename)*