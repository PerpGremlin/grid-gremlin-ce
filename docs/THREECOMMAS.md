# The 3Commas ledger

**Status (2026-10-06): the reference for what this engine is.** Every grid and
DCA mechanic below is built or decided except the few still open in
`BACKLOG.md` §1. The owner, on
being asked two decisions: *"realistically i am trying to reverse engineer
3commas… i dont want to pay them, i wana build my own."* This file is the
feature-by-feature account: what 3Commas does, what we do, and what is still
open. Each open item becomes a D-number (copy, diverge, or skip) from the
owner; nothing here is built until it has one.

**Which 3Commas.** The *classic* bots — the v1 Grid Bot and DCA Bot whose
mechanics the field copied and which our D11 vocabulary already speaks. 3Commas
deactivated v1 on 2026-09-11; v2 is a different engine built with WunderTrading
(Long/Neutral/Short/Hedge grids, $-denominated TP/SL, 30-day backtests). The
classic help articles are still up and are the sources. Full inventories with
every quote and URL: `docs/archive/3commas/` (grid, DCA, platform, v2 changes,
Altrady, the limit entry). §5 is what v2 changed and why; §6 is Altrady against both.

**Two things the research settled at once.** (1) The slide (D28) *is* Trailing
Up: "when the price moves 2 steps above the High price, the bot cancels the
lowest buy order and places it one step above the High price" — our
`trigger_rungs`, one rung per slide, ratchet, with a clamp where they have a
Stop Trailing price. We add a confirmation delay (G21); they slide on the
first read. (2) 3Commas has **no leverage rule**: a slider, generic tiers, no
cap, no liquidation guard. The owner's D29: *"no rule on leverage, freedom,
discipline and personal accountability are key here."* The build's warning
above 20× on a slide row stays a warning.

Reading the tables: **same** = the mechanic matches (ours may be stricter);
**ours wider** = we cover more; **gap** = they have it, we do not, decision
pending; **absent by decision** = we chose not to, D-number cited.

---

## 1. Grid bot

| 3Commas classic | grid-gremlin v3 | status |
|---|---|---|
| High / Low price; levels or step % | `{lower, upper, rungs}`, spacing derives (D8, G1–G3) | same |
| Geometric (step % of price) / Arithmetic (fixed step) | `spacing_type` percent / fixed (G17) | same |
| Trailing Up only on Geometric (spot) | slide on either spacing | ours wider |
| Order size: geometric = fixed **quote** per level, arithmetic = fixed **base** | the lot, fixed base, priced at the split ref (G4, D5) | gap · minor: no fixed-quote sizing mode |
| Line at the current price carries no order; sells above, buys below | entries only below the ref, exits only above the floor; cross guard (G5, G13, B3) | same |
| Each sell pairs with the buy one level below it; the grid trades every oscillation, in a drawdown too | G23 (D35): each lot exits one rung above its own, the held rungs read from our fills; before D35 the engine sold nothing below average cost | same, since D35 |
| Investment ≤ ~95 % of balance, ~2 % base overbought for fees, rebalance at start | `capital` per row; the seed buys one lot per exit rung (S3); fee floor on every exit (G6) | same intent, different mechanics |
| Price leaves range: sells/buys its last level, waits, resumes | G11 idles, never chases; resumes on return | same |
| **Trailing Up / Down**: 2 steps beyond → cancel far rung, place one beyond; repeat; Stop Trailing price | **the slide** D28: G17–G20, clamp G19; trailing down (a short's up) opt-in, D34 G24, the cap lifted or raised | same · the uppermost sells: theirs become virtual levels, ours keep resting at their own rungs (D36, G25), virtual only if cancelled from outside — ours stricter |
| — (they slide on the first read) | `confirm_seconds` G21 — the control replay's 0.5 % wick | ours stricter, deliberate |
| Lower Stop Bot moves up with Trailing Up, keeping its distance | X8 the stop follows the window | same |
| **Expansion Up / Down** + Stop Expansion price: add levels beyond the range, never cancel, needs more capital | not built — skipped (D45): it grows capital without bound | absent by decision (D45) |
| Upper / Lower Stop Bot: **stop** (leave position) · stop & buy/sell base · futures: close position & stop | X1 flattens and kills (D1); `stop.action: leave_position` stops and leaves the position (X13, D43); `end_round` ends the round, not the bot (X10, D42) | **copied (D42, D43)** |
| Stop must sit outside the range | X8 `rungs_beyond`; an absolute `level` is not checked against the range | gap · minor |
| Max active buy / sell orders (soft cap for exchange order limits) | the window W1–W3 (placement-limited, never cancels by distance) | same |
| Insufficient funds: retry every 3 hours | margin backoff halts growth, doubling to a ceiling (B7) | same intent |
| Futures directions Long / Short / **Reversal** (long zone below a midpoint, short above; flips at the boundary) | long / short rows; both sides = two bots on one symbol (hedge); the **reversal preset** (D54): two halves split at a static mid on Bybit hedge mode. The single position that flips at the mid is parked | **copied as two legs (D54)**; the flipping shape parked |
| Futures position is netted, PnL from average entry | netted engine (G12), average-cost readout (R2) | same |
| Leverage: cross / isolated / custom; no cap, no guard | `leverage` per row; warning above 20× on a slide row | same · D29 |
| Binance stores leverage per pair — bots overwrite each other | Bybit demands equal buy/sell leverage — one symbol leverage = max of legs (soak finding, 2026-08-04) | same class, handled |
| Profit currency (accumulate in base or quote) | — | gap · skip candidate |
| Add funds (spot): rebalance across all lines | edit `capital` in the config; the diff applies it (D10 path) | same |
| No profit reinvest for grids ("close and restart with more") | `reinvest` refuses on a grid; manual `capital` edit (M12, D26) | same |
| Edit live: some keys without cancelling, others cancel everything; some reset stats | diff-based apply keeps every matching order (S6); stats are venue-derived, never reset (R1) | ours ahead |
| Close: sell base / buy base / keep both; futures: close position / leave open | stop flattens (X1), or leaves the position (X13); the panel's **close position** closes a stopped bot's holding (X15, D48); a process stop leaves everything resting | **copied (D43, D48)** |
| Profit: buy/sell pairing; futures rPnL from average entry ("may appear as a loss… the bot is managing the position efficiently"); fees included | G23 pairs per rung (D35); R2 books against the average, R5 net of fees, R6 trips, R9 must read zero | same, since D35 |
| Backtest 120 days; **AI Optimize** searches the step; pre-optimised pair list | T3/T6 backtester on the real planner, 5-minute bars, funding modelled; **T8 sweeps the step** (D50): every candidate shown, best and plateau named, scored by net | ours transparent · no pair list |
| Presets: Rising (1 sell / 9 buy, trailing up), Stable (5/5), To the Moon, Falling, Reversal | the panel's quick presets (D40, U1–U6) and a **reversal** preset (D54); `copy` reuses any bot's settings | **copied (D40)** |
| Default asymmetric grid "5 sell + 95 buy" | `ref_position` on a slide row places the ref anywhere in the window | same idea |
| Backtest fee model, fill model, trigger price source | stated: trade-through fills, maker fee, funding (T3) | ours documented |

## 2. DCA bot (our martingale)

| 3Commas classic | grid-gremlin v3 | status |
|---|---|---|
| Long / short | `side` | same |
| Base order size: quote, base, or % of **total** balance | `base_order_size` (quote) | same · % mode absent |
| **Start order type: Limit** at best ask, re-pegged every 40 s until filled; or Market | `start_order_type: maker` — post-only at the near side, re-quoted when the book leaves it (M16); market stays the default | **diverged (D37)** — 3Commas' limit crosses the spread, so it is still taker |
| Deal start conditions: ASAP · TradingView screener · QFL · indicators (RSI, MACD, BB, …) · webhook · manual; AND-combined; evaluated on candle close | ASAP only (`repeat`). Signals deferred by the owner: "i usually do my own TA to enter" | absent by decision (D15, D26) — BACKLOG §1 |
| Deal start delay; min/max price to open; min 24 h volume | — | gap · minor |
| Safety orders: step % from base (cumulative), size, step multiplier, volume multiplier, max SOs, max **active** SOs on the book | M2 exactly: `deviation`, `deviation_step_multiplier`, `order_size_multiplier`, `max_averaging_orders`; the window limits what rests; required capital refused if over `capital` | same · ours refuses at build |
| Required capital = V0 + V1 (mⁿ−1)/(m−1) shown | the validator expands the series and states the number (M2) | same |
| SO anchor is the base price; a restart keeps it | M15 recovers the anchor from the venue's resting SO — never re-anchors on average | same, ours proven |
| Custom price ladder (up to 20 explicit levels, each sized) | — | gap · skip candidate |
| SOs triggered by indicators / signals, executed at market | — | absent by decision (signals) |
| Manual add funds (market / limit) mid-deal | operator's own orders are foreign (I1); adoption is at build (S4) | gap · minor |
| TP % from **average** (default) or from base order (fixed $ profit) | M4 from average, recomputed as fills deepen (D12) | same · "from base" absent |
| TP is a limit at target; market when trailing | venue-hosted position TP (Bybit) or the resting reduce-only exit (HL, D21); a run-through target closes marketable (M3) | same |
| Up to 4 TP targets, equal split by default | tranches M10 (D23), shares sum to one, re-anchored as fills deepen | same |
| **Trailing TP**: bot-side, follows the high, market close at deviation % | M11 rides the venue's trailing order; refused where the venue cannot host it | diverge by D23 |
| Trade close conditions (indicators) + minimum profit gate | — | absent by decision (signals) |
| SL % from the **base order price**, must sit beyond the last SO; action close, or close & stop bot | X2 `mark_price` / `account_equity` / `position_sl`; X1 flattens and kills; X3 server-side where hosted | same for "close & stop bot"; "close deal, keep the bot" is `stop.action: end_round` with `from_base_pct` (X10/X11, D42) |
| SL timeout (price must stay beyond for N s) | `stop.confirm_seconds` (X9); a recovery resets the clock | **copied (D33)** |
| Trailing SL (% of the highest price) | `trailing_stop_pct` (+ `trailing_activation_pct`): venue-hosted where it can be, engine-watched on HL (M21, D31) — proven live 2026-10-03 | **copied (D31)** |
| **SL to breakeven** ladder: TP1 → breakeven, TP2 → TP1, … | `breakeven_ladder` (M17): venue partial SL on Bybit, mark-watched on HL; firing ends the round; `breakeven_activation_pct` (M17c) arms it on profit instead, any take-profit shape | **copied (D38, D69)** |
| Reinvest 0–100 % of profit into next deal's orders; never below initial | M12 toggle: factor 1 + realized/capital over 30 days, floored 0, capped 1.2 | same in spirit; percentage absent |
| Risk reduction: shrink orders after losses, back to normal on profit | the same M12 factor goes below 1 on losses | same — one factor covers both |
| Cooldown between deals | M13 `repeat_cooldown_seconds`, anchored to the venue's TP-fill time | same, ours restart-proof |
| Max trade iterations (stop after N deals) | `max_rounds` + `max_rounds_since` (M18): counted from venue fills | **copied (D41)**, ours restart-proof |
| Max hold period (close after N hours, profit or loss) | `max_hold_seconds` (M19), clocked from venue fills | **copied (D44)** |
| Max active deals; multi-pair bots; pairs blacklist | one bot per (market, symbol, side) (I2); the fleet file is the multi-pair bot | same via the fleet |
| Futures: sizes include leverage; margin = size / leverage | `capital` × `leverage`; the validator sizes the series | same |
| Liquidation: a status, no mechanics | M14 stands down; R10 knows whose liquidation it was | ours ahead |
| Edit a running bot applies to new deals only; SL action never touches open deals | the diff applies now; M6 never rewrites a live round's exit | comparable |
| Close at market (panic sell) · cancel (leave coins) · stop bot (deals keep running) | X1 flatten-and-kill · `leave_position` (X13) · the panel's close position (X15) · process stop leaves everything | **copied (D43, D48)** |
| Paper trading: instant fills, no book, Binance spot prices | Bybit demo and HL testnet: real books, real rejections | ours ahead |
| Backtest: 1-minute candles, fill at the next close, fees | 5-minute bars, trade-through fills, funding; martingales replayed by running the real bot against candles (T7) | comparable |

## 3. Stops, risk, and the platform

| 3Commas | grid-gremlin v3 | status |
|---|---|---|
| Server-side TP/SL/trailing held by 3Commas; only futures-DCA SL is exchange-native | venue-hosted wherever the venue can (X3, D21, D23); bot-side only as fallback | ours ahead — a dead process leaves the stop resting |
| **No portfolio guard**: no drawdown switch, no equity floor, no pause on disconnect | watchdog: staleness, mm_rate, equity floor, drawdown from peak, per-bot bounds (F1–F9); opt-in account caps (D56), a holding cap (D70) and risk profiles (D57) | ours ahead |
| Telegram: every event + commands (`/stop_all_long_bots`, `/my_stats`, …) | the phone carries emergencies, startup and urgent or persisting warnings (D60); read commands `/pnl`, `/positions`, … (D61); a daily digest (D62). Write commands wait for the agentic phase (D46) | reads **copied**; writes deferred (D46) |
| Fleet on/off by direction; close-all-and-stop per bot; Sell All per spot account | systemd unit per fleet; panel control start/stop/restart; no per-direction switch | partial |
| Dashboard, per-bot stats, event log, CSV/XLSX | the panel (View, rehearse, create/edit, control) + `report` readout | comparable |
| Webhook ingress (signal bot), TradingView | — | absent by decision (signals) |
| SmartTrade terminal | — | skip — the owner trades on the venue |
| Key custody: signing service, exchange IP allowlist; ~100k keys leaked 2022 | keys in `.env` (0600) on the box; the panel is keyless; mainnet double-gated (F7) | different problem, ours smaller |
| Mobile app | the panel is a web page | skip |
| Presets, copy bot, share | the panel's presets (D40) and `copy`; no sharing between users | **copied (D40)**; sharing skip |

**Where we are ahead, and stay ahead** (from the archived field survey, confirmed):
adopting an existing position (S4), diff-based live edits with zero churn (S6),
hedged sides as two bots, windowed placement (W), venue-derived everything
(E3, R1), liquidation semantics (M14, R10), the watchdog, a real testnet book.

---

## 4. Open items — decided: copy them all (D30)

Ordered by my recommendation; the owner, 2026-09-28: *"i like all the things they
have that we dont."* Every item below is wanted, in this order, one PR each with
its specs. Signals (item 13) stay deferred by D15/D26 until the owner says so.

1. **Limit entry for the base order** (DCA §2). **Built 2026-10-02 as D37 /
   M16, diverged:** their limit sits at the best ask, which crosses the
   spread and still pays taker; ours rests post-only at the best bid, chased
   on 3Commas' 40 s timer, with (n)'s expiration as an opt-in. The 48-day run
   paid taker on two-thirds of its fills, nearly all martingale entries.
2. **SL to breakeven ladder** (DCA §2). **Built 2026-10-02 as D38 / M17,
   copied:** TP1 → average entry plus G6's fee floor, TP n → TP n-1, never
   loosening; Bybit's partial stop-loss, HL bot-side; firing ends the round,
   not the bot. D55 places the first step with an offset; **D69 adds v2's
   activation %** (`breakeven_activation_pct`, M17c): the stop arms once the
   round is N% up, one target or steps alike.
3. **SL timeout and max trade iterations** (DCA §2). **Built 2026-10-02 as
   X9 and M18 (D33, D41), copied**, with 3Commas' "close deal, keep the bot"
   stop beside them (X10/X11, D42) and D33's cooldown after a stop. Never run
   live. D33's candle-close mode and emergency level followed the same day
   (X12).
4. **Presets** (grid §1, DCA §2). **Built 2026-10-02 as D40:** five presets
   in the panel's quick setup (sideways, rising, falling, buy the dips, sell
   the rallies), each sized from today's price at three levels of caution,
   and each opening in the advanced form. In the panel rather than as files
   under `configs/`. No engine change.
5. **Stop action choice** (grid §1, DCA §2). **Built 2026-10-02 as X13
   (D43), copied as an opt-in:** `stop.action: leave_position`. D1 stays the
   default.
6. **Max hold period** (DCA §2). **Built 2026-10-02 as M19 (D44), copied
   as an opt-in:** `max_hold_seconds`, clocked from the venue's fills.
7. **Expansion Down / Up** (grid §1). **Skipped (D45).** It grows the
   ladder below the range with new capital until a stop price; D28 declined
   it because capital is unbounded. The slide plus a `capital`/range edit
   covers the same ground with a human in the loop.
8. **Reversal grid** (grid §1). **BUILT 2026-10-05 as D54:** the quick
   setup's "Reversal (neutral)" preset — a long grid below a static mid and a
   short grid above it, two bots on one market made one after the other
   through the same gates (Bybit hedge mode). Held 2026-10-04 as *"a deal of
   work"*, then taken on the framing: the two-leg preset first, the mid
   static (the slide follows), the single flipping position for one-way
   venues (Bybit inverse, Hyperliquid) **parked**; HL refuses the pair by
   name.
9. **Trailing SL** (DCA §2). **Built 2026-10-03 as M21, per D31:** rides the venue where hosted
   (Bybit trailing stop); elsewhere the engine carries v2's activation +
   execution object with "no activation, no stop" and "a plain stop wins".
10. **Telegram commands** (§3). **Deferred to the agentic phase (D46).** The relay is read-only by design; a
    `/stop_all_longs` would be its first write. The panel already has the
    control surface.
11. **Step optimizer** (grid §1). **Built 2026-10-03 as T8, per D50:** the
    rehearsal swept over `rungs`, scored by net, the table shown, best and
    plateau named; `--optimize` and the panel's "find the step".
12. **Skip, unless the owner says otherwise**: fixed-quote lot sizing, profit
    currency, custom price ladder, TP "from base order", % of balance base
    order, min/max price and volume gates, deal start delay, manual add-funds,
    SmartTrade, mobile.
13. **Signals and webhooks** stay deferred by the owner's own word (D15, D26)
    until they say otherwise.

Not on this list because the answer is already ours: leverage (D29),
reinvest and risk reduction (M12 covers both), portfolio guards (the watchdog),
server-side stops (X3), liquidation handling (M14, R10).

---

## 5. What 3Commas changed in v2, and why (2026-09-28)

Source: `docs/archive/3commas/v2-changes.md`. The owner's question: *"if one of
the bigest trading bot apps in the world is updating, i want to know what."*

**What v2 is.** Not an update. 3Commas' own replies: *"V2 is a new platform
with a different technical foundation… a completely different infrastructure,
which unfortunately makes a direct rollover of bots, settings, trades, and
historical data technically impossible."* The evidence that it is a
white-labelled WunderTrading deployment is overwhelming: the webhook endpoint is
`3c.wtalerts.com` against WunderTrading's `wtalerts.com`; a dozen help articles
share titles and word-for-word text between the two help centres; the grid
types, indicator set, pricing rows and Hyperliquid key flow are WunderTrading's.
Announced 2026-08-11 with a one-month deadline; v1 deactivated 2026-09-11;
strategies did not migrate; mobile apps gone; API portal login-gated; 22
exchanges cut to 9 (Hyperliquid added). **No published rationale** beyond
"new features" — nothing on performance, cost or regulation. Trustpilot,
August–September: *"stripped 90% of the functionality"*, lifetime-plan holders
issued lower-tier codes; the company: *"Some V1 functionality is not yet
available, V2 continues to receive updates."*

**Grid, v2 against classic.**

| classic | v2 | for us |
|---|---|---|
| Trailing Up / Down, Expansion Up / Down | **removed**; replaced by an "Infinite" grid (fixed profit per grid, no bounds) whose capital allocation is undocumented | the slide stays; the infinite grid is D28's "extend", declined |
| geometric or arithmetic | geometric only, "arithmetic will be available soon" | keep both |
| resting limit exits | entries rest as limits; **every exit is a server-side market order on bid touch** | do not copy: X3 keeps exits resting on the venue |
| Long / Short / Reversal | Long / Short / Neutral (long below a user-set **Mid price**, short above) / **Hedge** (both sides at every level, market in and out) | the Mid price is the reversal grid, item 8, with a cleaner knob |
| stop bot at a price | **bot-level $ TP and $ SL** on realized + unrealized: "close all remaining positions and stop"; a Stop Trigger on channel exit with three actions | a single kill criterion per bot — worth copying as an `account_equity`-style watch per bot |
| — | per-position stop loss %; per-position trailing stop fixed at 30 % of the grid step | the first is a knob; the 30 % is a simplification |
| — | **Pump Protection**: pauses entries on abnormal moves against the position; thresholds undocumented | a named guard with no rule — we would have to write our own (G21's confirmation is the nearest thing we have) |
| started immediately | **start conditions**: immediate, RSI, MACD, Bollinger, price change, webhook; closed candles only | signals — deferred by D15/D26 |
| 120-day backtest, AI Optimize, presets | 30-day backtest, Optimize over profit-per-grid, "Profit-Optimized Pairs" cards | our backtester already replays any window |

**DCA, v2 against classic.**

| classic | v2 | for us |
|---|---|---|
| base order + independent first safety order | one "amount per trade"; **DCA Mode** position-averaging (SO1 = base, scaling from SO2) or order-averaging (scaling from SO1) | M2 keeps both sizes independent — the classic degree of freedom, keep it |
| max safety orders excludes the base; max **active** SOs on the book | "Max DCA Orders" **includes** the base order; active cap gone | keep M2's counting and the window |
| quote-sized orders | **fixed coin amount or fixed order value** | a sizing mode, cheap; add to item 12 |
| TP % from average, or fixed $ profit from base; up to 4 targets; trailing TP | single TP; entry-based TP is now a **fixed price**; multi-TP and trailing TP removed from DCA (the Signal Bot keeps 10) | keep M10/M11 |
| SL from base; timeout; native on-exchange SL for futures | SL market on ask touch; **timeout removed; on-exchange SL custody removed** | do not copy |
| move-to-breakeven after TP1 | **activation % and execution %** ("SL to $1,020 after a 3 % gain, accounting for fees") | copy into item 2: the breakeven ladder gets an activation and an execution offset |
| trailing TP by deviation from the high | a **Trailing Stop object**: activation price, then a fixed-distance trail; "if the activation price is not reached, your strategy will not have a stop level"; "if Stop Loss and Trailing Stop share the same price level, Stop Loss takes priority" | clean, testable semantics — the shape for item 9 |
| per-bot max active deals | **global max open positions** across all bots; the offending bot is "declined, and the bot will be stopped" | **D70** `holding_max` in `account_caps` (F15b): a flat bot waits and its card says why; holders run on; nothing is stopped |
| QFL, TradingView screener, CQS, indicator close conditions, signal-triggered SOs | removed; TradingView custom signals and manual/API moved to the Signal Bot; up to 5 indicators AND-ed on 15 m / 60 m closed candles | signals — deferred |
| reinvest, risk reduction, cooldown, min profit, close-after-timeout, custom ladder, profit currency | **all removed** | we keep M12/M13; the ledger's items stand |
| — | the **DCA summary box**: required capital closed-form, max drop covered, capital-weighted break-even, with declared caveats | M2 refuses over-capital; **U52** the card folds the ladder: each step's fill, size, committed, average and the bounce to take-profit; the move covered in one line |

**Order custody, the material change.** Classic v1 rested TPs as limits and, on
Binance/Bybit/Gate futures, placed the SL on the exchange. v2 monitors bid/ask
server-side and fires market orders for every exit; only the Signal Bot and
Terminal have an opt-in "place conditional orders on exchange", capped by the
venue at about ten per pair. A 3Commas outage now leaves every grid and DCA
position without a stop. Our X3 doctrine is the opposite and stays.

**What v2 is worth copying** — decided 2026-09-28: (a) is D31's bot-side shape;
(c) only as an opt-in key under D32; (d) built after all as D47's `max_loss`;
(f) built as D54's mid; (b) half built (D55's offset; the activation % open);
(c), (e), (g) still open: (a) the trailing-stop object as activation + execution with the
"no activation, no stop" and "SL wins a tie" rules; (b) breakeven with
activation % and execution %; (c) a global max-open-positions cap with refusal;
(d) a bot-level $ TP/SL kill criterion on realized + unrealized; (e) fixed-coin
vs fixed-value averaging; (f) the Mid price as the reversal grid's knob; (g) the
summary box in the readout. **What not to copy:** server-side market exits, the
30 % hard-coded trail, the base-inclusive order count, the removal of the
active-SO cap and of the first safety order's own size.

---

## 6. Altrady against 3Commas (2026-09-28)

Source: `docs/archive/3commas/altrady.md`. Altrady is the platform an adept
discretionary trader the owner follows uses.

**What it is.** Dutch, 2017, terminal-first: a desktop app whose spine is scan →
smart order with entry, targets and stop in one ticket → journal. Bots came
later and are one of five pillars. Two engines only: a spot-only grid bot and a
signal-bot engine that the DCA, QFL, TradingView, webhook and HODL bots are
presets of; a "DCA Position" is a smart order, not a bot. 19 exchanges including
Hyperliquid perps; no testnets; no public REST API (webhooks in, a local MCP
server out, every write queued for a click in the app). Keys are encrypted
client-side under a five-word vault password; no breach on record, against
3Commas' 2022 leak of ~100k keys.

**Its grid bot, against ours.** Spot only, 2–100 levels, arithmetic or
geometric, one position, equal base per level, limit orders resting. Trailing
up triggers **one** level above the upper limit (3Commas: two), cancels the
lowest buy and places a new buy at the top, funded from accumulated profit first
and then free balance, and *fails* when the quote is short. Trailing down
mirrors it and fails on the venue's minimum size. A contradiction guard refuses
a bot whose TP sits below the trailing trigger. Exit rules: TP above the range,
SL below, auto-close after a duration, each with an action (to quote, to base,
or cancel only). Editing restarts the bot with every order re-placed. "After 100
consecutive errors, the bot stops automatically." No futures grid, no leverage,
no reversal. Verdict: the same slide with a lower trigger, an honest funding
rule and a contradiction guard we lack; everything else is behind ours.

**Its DCA / signal bot, against ours.** Up to nine extra entries, each a
deviation and a size as a percentage of the entry, ladder or scaled; entry
expiration; entry price deviation; auto-close; cooldown after opening and
**cooldown after a stop loss**; min/max volume and price; white and black
lists; positions per market and per side. Targets up to ten (plan-gated), each
a profit % from average and a volume share, trailing on the last. Stop loss with
**four protection modes**: none, break-even at average entry including fees
after TP1, follow-TP (steps one level behind each target), follow-price
(trailing with trigger and distance). Stop **cool-down** by time or by candle
close, plus an **emergency stop** that overrides the cool-down. Spot stops live
at Altrady; futures stops are pre-placed on the exchange unless a cool-down is
set. Verdict: the most precisely documented exit stack in the field, and the
one the ledger's items 2, 3 and 9 should be written against.

**What Altrady has that neither we nor 3Commas have.**

- **Risk profiles** enforced before every order: total open risk % of equity,
  max risk per trade, max leverage, require a stop, max daily loss lockout,
  max consecutive losses, cooldown after a loss, no widening or removing a
  stop; each rule Off / Warn / Block. Pre-trade only; nothing closes positions.
- **The journal**: expectancy, profit factor, planned vs realized R, MAE/MFE,
  max drawdown of closed P&L, breakdowns by market, side, session, tag and
  strategy; a 1–5 rating of the decision, seeded tags (revenge trading, FOMO,
  moved stop, oversized), a per-strategy checklist shown in the ticket.
- **The ticket**: ladder entries with price and size scales, trailing entry,
  risk-% sizing against portfolio or account equity with size, stop and risk
  interlocked, presets on hotkeys, reduce-by-% keys, a position widget with
  invested, average entry, break-even after fees, net P&L.
- **Smart Sell**: attach exits to coins bought elsewhere — position adoption,
  manual and spot-only. Ours is automatic (S4).

**Head-to-head, the parts that matter to us.**

| | Altrady | 3Commas classic | ours |
|---|---|---|---|
| grid trailing trigger | 1 level past the edge, funded from profit, fails honestly | 2 steps, "cancels the lowest buy, places one above" | `trigger_rungs`, confirmation, clamp, stop follows |
| grid on futures | no | yes, long / short / reversal, to 125× | yes, long / short, D29 |
| DCA sizing | % of entry per rung, ≤ 9 | base + SO, multipliers, ≤ 200 | M2, the series refused over capital |
| stop protection | none / break-even / follow-TP / follow-price | breakeven ladder, trailing SL, timeout | X1–X8; the ladder is item 2 |
| stop cool-down | time or candle close + emergency stop | timeout | item 3 |
| stop custody | spot at Altrady; futures on the exchange | server-side; futures DCA native | venue-hosted wherever possible (X3) |
| portfolio guard | pre-trade block / warn rules | none | the watchdog: staleness, mm_rate, equity floor, drawdown |
| journal | full | statistics | the readout: trips, rounds, R9, D8 split |
| adoption | Smart Sell, manual, spot | Use Existing Assets, manual | automatic at build (S4) |
| testnet | none | none | Bybit demo, HL testnet |

**Candidates from Altrady** — decided 2026-09-28: (h) and (i) built under D33;
(j), (k), (m) skipped by the owner; (n) built after all with the limit entry
(M16); (l) built as D57's opt-in risk profiles:
(h) the stop cool-down by **candle close** and the **emergency stop** that
overrides it — write item 3's timeout this way; (i) **cooldown after a stop
loss** beside M13's cooldown after a TP; (j) the grid **contradiction guard** —
refuse a TP or stop that price would reach before the slide could trigger; (k)
the trailing-up **funding rule** — a slide that would need more quote than the
row has is refused or capped, said in the event; (l) **risk profiles** as
build-time refusals, the F-series shape: max leverage, require a stop, total
open risk; (m) the **journal's R and expectancy** in the readout, which already
has every fill; (n) **entry expiration** for item 1's limit entry.
