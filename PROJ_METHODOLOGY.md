PROJ$ METHODOLOGY: Z-Score Auction Value Calculator

STEP 1: GATHER INPUTS

League Structure
  • Number of teams: 12
  • Roster size per team: 22 (13 hitters + 9 pitchers)
  • Hitter positions per team: C(1), 1B(1), 2B(1), SS(1), 3B(1), CI(1), MI(1), OF(5), UTIL(1) = 13
  • Pitcher positions per team: SP(up to 4), RP(up to 3), P(remainder) = 9
  • Total league roster spots: 12 × 22 = 264

Determine Auction Pool Size
  • Count total keepers across all teams
  • Auction spots = 264 − total keepers
  • Example (Mar 2026): 264 − 135 keepers = 129 auction spots

Determine Positional Slot Counts at Auction
  • For each position, count how many keepers occupy that slot across all 12 teams
  • Auction slots at position = Total league slots − Keeper slots at that position
  • Example (Mar 2026): C:7, 1B:2, 2B:7, SS:3, 3B:5, CI:8, MI:10, OF:28, UTIL:10 = 80 hitters
  • Pitchers: SP:5, RP:27, P:17 = 49 pitchers

Determine Auction Budget
  • Total league budget = 12 teams × $260 = $3,120
  • Sum all keeper salaries across all teams
  • Auction dollars available = $3,120 − total keeper salaries
  • Example (Mar 2026): $3,120 − $1,629 = $1,491

Player Projections with Z-Scores
  • Each player needs a single Total Z value representing their overall projected statistical value
  • Hitter z-score categories: R, HR, RBI, SB, OPS
  • Pitcher z-score categories: QS, K, SV+H, ERA, WHIP
  • The z-score calculation is a separate process (done on zScore sheets); this Proj$ model only needs the final Total Z

═══════════════════════════════════════════════════════════════════════════════════════════════════════

STEP 2: CLASSIFY PITCHERS AS SP-ELIGIBLE OR RP-ELIGIBLE

Every pitcher must be classified into one of two pools:
  • SP-eligible: Can fill SP slots or P slots. Uses the SP valuation pool (higher $/VAR rate).
  • RP-eligible: Can fill RP slots or P slots. Uses the RP valuation pool (lower $/VAR rate).

Use the Type column (SP or RP) from your pitcher projection sheet. This classification determines which
valuation pool they belong to, which is critical because SP and RP pools use very different $/VAR rates.

═══════════════════════════════════════════════════════════════════════════════════════════════════════

STEP 3: GREEDY POSITION ASSIGNMENT

Purpose: Assign each draftable player to exactly one roster slot. Players with multi-position eligibility
could fill several slots — the greedy algorithm assigns them to the scarcest slot they qualify for,
ensuring the most constrained positions get filled first.

Algorithm:
  1. Sort ALL players by Total Z, descending (best player first).
  2. For each player (highest Z first):
     a. Look at all positions they're eligible for
     b. Among those positions that still have open slots, assign to the SCARCEST one (fewest remaining slots)
     c. If all their eligible positions are full, they go unassigned (undrafted)
  3. Continue until all auction slots are filled.

Hitter Position Priority (tiebreaker when multiple positions have same remaining slots):
  C → SS → 1B → 3B → 2B → MI → CI → OF → UTIL

Pitcher Assignment (handled in two SEPARATE pools):
  • SP-eligible pitchers fill: SP slots first → then P slots (overflow)
  • RP-eligible pitchers fill: RP slots first → then P slots (overflow)

P SLOT ALLOCATION — CRITICAL DECISION:
The P (flex pitcher) slots must be pre-allocated between SP-eligible and RP-eligible pitchers.
This reflects how your league actually behaves.

In this league, ~80% of P slots are historically filled by SP-eligible pitchers.
So the 17 P slots are split:
  • 14 P slots → SP-eligible (called SP_P internally)
  • 3 P slots → RP-eligible (called RP_P internally)

This means:
  • SP-eligible pitchers compete for: 5 SP + 14 P = 19 total slots
  • RP-eligible pitchers compete for: 27 RP + 3 P = 30 total slots

WHY THIS MATTERS: Without this split, the model treats all P slots as equally available to SP and RP,
which produces unrealistically high RP values. The split correctly reflects that managers mostly draft SPs for P slots.

After this step, every drafted player has an assigned slot (C, 1B, 2B, SS, 3B, CI, MI, OF, UTIL, SP, RP, or P).
Undrafted players have no slot and will receive Proj$ = $0.

═══════════════════════════════════════════════════════════════════════════════════════════════════════

STEP 4: CALCULATE REPLACEMENT LEVELS

The replacement level for each position is the Total Z of the WORST (last) drafted player at that position.
This represents freely available talent — the baseline every player's value is measured against.

For each position slot type, find the player with the LOWEST Total Z among all players assigned to that slot.

March 3, 2026 Replacement Levels:
Position    Replacement Player    Total Z
C           Alejandro Kirk        -1.105
1B          Willson Contreras     2.213
2B          Nico Hoerner          0.352
SS          Corey Seager          4.008
3B          Matt Chapman          2.51
CI          Royce Lewis           -0.857
MI          Caleb Durbin          -1.274
OF          Brandon Marsh         -1.137
UTIL        Ernie Clement         -1.451
SP          Gerrit Cole           5.634
P (SP-elig) Merrill Kelly         3.308
RP          Phil Maton            2.343
P (RP-elig) Fernando Cruz         2.193

Interpretation: A player assigned to OF needs Total Z above −1.137 to have any value above replacement.
A player assigned to SS needs Total Z above 4.008 — shortstop is so scarce that even Corey Seager is barely replacement level.

═══════════════════════════════════════════════════════════════════════════════════════════════════════

STEP 5: CALCULATE VAR (VALUE ABOVE REPLACEMENT)

For each drafted player:

  VAR = Player's Total Z  −  Replacement Level of their assigned position

Examples:
Player            Position   Total Z    Repl Level
Shohei Ohtani     UTIL       17.678     -1.451
Bobby Witt Jr.    SS         10.619     4.008
Chris Sale        SP         11.466     5.634
Josh Hader        RP         6.53       2.343
Corey Seager      SS         4.008      4.008

Note: The replacement player at each position will always have VAR = 0 (they define the baseline).

═══════════════════════════════════════════════════════════════════════════════════════════════════════

STEP 6: SET BUDGET SPLITS — THREE INDEPENDENT VALUATION POOLS

The hitter/pitcher budget split comes from the natural proportion of total VAR in each pool.
Then the pitcher budget is further split 75% SP / 25% RP to reflect actual league behavior.

This creates THREE independent valuation pools, each with its own $/VAR rate:
  1. Hitters: all hitter budget
  2. SP-eligible pitchers: 75% of pitcher budget
  3. RP-eligible pitchers: 25% of pitcher budget

March 3, 2026:
  • Hitter budget: $1,067 (80 players)
  • SP-eligible budget: $424 × 75% = $318 (19 players)
  • RP-eligible budget: $424 − $318 = $106 (30 players)
  • Total: $1,067 + $318 + $106 = $1,491 ✓

═══════════════════════════════════════════════════════════════════════════════════════════════════════

STEP 7: CALCULATE $/VAR FOR EACH POOL

Each pool has a $1 minimum per player. The remaining dollars are distributed proportionally to VAR.

  Available $ Above Minimums = Pool Budget  −  (Number of Players in Pool × $1)
  $/VAR = Available $ Above Minimums  ÷  Sum of All VARs in Pool

HISTORICAL NOTE: In 2025, 36 players were drafted at $1 (not counting keepers). With keepers included,
roughly 53 players were at $1. This is not atypical — expect ~25-30% of the auction pool to go for
the minimum. The $1 floor assumption in this model aligns well with actual league behavior.


═══════════════════════════════════════════════════════════════════════════════════════════════════════
═══════════════════════════════════════════════════════════════════════════════════════════════════════

PRED$ METHODOLOGY: Tier-Based Auction Inflation Model
March 3, 2026 — Compiled by Clay (with AI assistance)

PURPOSE
Proj$ = statistical value above replacement. Pred$ = what a player ACTUALLY SELLS FOR in auction.
The gap is caused by: scarcity inflation, name-value premiums, positional scarcity, $1 compression.

═══ STEP 1: ESTABLISH THE BUDGET CONSTRAINT ═══

All Pred$ must sum to exactly the Available Auction Dollars.
  Total League Budget = 12 × $260 + bonuses = $3,150
  Keeper Salaries = $1,659  |  Available Auction $ = $1,491
  → Pred$ across BOTH hitter and pitcher sheets must total $1,491.

═══ STEP 2: RANK ALL PLAYERS BY PROJ$ AND ASSIGN TIERS ═══

Combine hitters + pitchers, sort by Proj$ descending. Pick order → tier:
  Tier 1A — Picks 1–3   ("Best Available" premium, $55–100+)
  Tier 1B — Picks 4–8   (Elite tier, significant overpay expected)
  Tier 2  — Picks 9–20  (Strong starters, fair-to-slight premium)
  Tier 3  — Picks 21–40 (Mid-tier, moderate compression)
  Tier 4  — Picks 41–70 (Role players, compressed to $3–12)
  Tier 5  — Picks 71+   ($1–$4 floor, mostly filler)
  Tier 6  — Undrafted   ($0 Proj = $0 Pred)

⚠ Tiers = COMBINED ranking (hitters + pitchers). Always re-rank by current Proj$.
  2026 re-tiers: Marsee 6→2, Freeman 2→3, Estrada 5→3, Glasnow 3→4

═══ STEP 3: SET ANCHOR VALUES (Top ~15 Players — Gut Feel) ═══

Manually set Pred$ for top players FIRST. Ask: "What does this player sell for in MY league?"
2026 anchors: Ohtani $104, Judge $99, Schwarber $65, Tucker $63, Rodríguez $61, Witt $55,
  Lindor $57, Alvarez $42, Sale $51, Wheeler $48, Gilbert $45, Gray $37,
  Hader $19, Bednar $16, Castillo $21

═══ STEP 4: APPLY TIER-BASED INFLATION RULES ═══

From Clay's Inflation Analysis + 2018–2025 Compare sheets + current-year judgment.

2026 KEY: Projections were "pretty close" to auction prices for the first time.
Tier 1A/1B near 1.0x (historical norm: 1.3–1.9x hitters, 2.0x+ pitchers).

TIER 1A/1B: Individually priced (see anchors).
TIER 2 (Picks 9–20): ~1.0–1.15x. Historically best value at 0.90x; 2026 ≈ fair value.
  Pitcher/name premiums: Gray $7→$37, Gilbert $43→$45.
  Turner $33, Betts $30, Yelich $24, Robert $23, Jazz $23, Cruz $22, Happ $21, Duran $19
TIER 3 (Picks 21–40): 0.7–1.0x. Catchers hold ~1.0x. Pitchers get scarcity premium.
  Freeman $19, Ohtani SP $18, Bellinger/Ramírez/W.Contreras $15, Peña $15, Rodón $13
TIER 4 (Picks 41–70): Compressed $3–$11. Name exceptions: Trout $9, Williams $11, Glasnow $7.
TIER 5 (Picks 71+): $1–$4 floor. ~36 at $1. Big names get $3–4 (3.51x "bargain inflation").

═══ STEP 5: BALANCE TO BUDGET ═══

Iterate to hit $1,491 exactly. Adjust Tier 3 (±$1–2) > Tier 4 (±$1) > Tier 5 ($1↔$2).
Do NOT adjust Tier 1A/1B anchors.

═══ STEP 6: SANITY CHECKS ═══

  ✅ Total Pred$ = $1,491 exactly
  ✅ ~36 at $1, ~5 at $2 (league historical pattern)
  ✅ No $0 Proj player has Pred$ > $0
  ✅ Pitcher/catcher scarcity reflected (not discounted)
  ✅ Name-value premiums for elite low-Proj$ players (Lindor, Gray, Cole, Seager)

═══ SOURCES FROM CLAY'S FRAMEWORK ═══

  📊 Inflation Analysis — Historical rates (1.108x–1.566x), tier inflation ($1–4 at 3.51x)
  📊 Clays Auction Inflation Adjust — Tier defs, multiplier rules, anchor values
  📊 2018–2025 Compare sheets — Actual vs projected (7 years of data)
  📊 2026 Draft Pool — Budget ($1,491), 108 spots, 156 keepers, 1.125x inflation
  📊 Clay's league knowledge — "36 at $1, 5 at $2" historical draft pattern

2026 FINAL: Hitters $1,082 + Pitchers $409 = $1,491 ✅
  36 at $1 | 9 at $2 | 84 at $3+ | 186 at $0

═══ NOTE FOR NEXT YEAR ═══

If projections are again close to auction prices, use ~1.0x for Tiers 1–2.
If projections are lower than expected (the typical year), revert to historical multipliers:
  1A: 1.3–1.4x ($70–90+ floor) | 1B: 1.5–1.9x | Top pitchers: 2.0–2.6x
  Tier 3: ~0.63x | Tier 4: ~0.42x | Tier 5: $1–2 floor
Check the Inflation Analysis sheet each year — the overall rate determines the approach.
