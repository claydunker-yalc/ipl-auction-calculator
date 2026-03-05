"""
AI Manager Behavior Engine

Each AI manager's bidding is driven by their behavioral profile (generated
from historical data by profile_analyzer.py). The AI is statistically modeled
from each manager's actual patterns — not rule-based.

Key behaviors modeled:
- Budget allocation (hitter/pitcher split)
- Tier distribution (how they spread money)
- Position targeting (what they still need)
- Bid sizing (max bid, avg bid, $1 frequency)
- Inflation tolerance (how much they overpay)
- Needs-based escalation (bidding up scarce positions)
- Controlled randomness (variance from their historical patterns)

Auction mechanic: SECOND-PRICE auction (winner pays second-highest bid + $1).
This mirrors real fantasy auctions where the price is set by competition,
not by the winner's private willingness. This produces much more realistic
price distributions.
"""

import random
import math
from typing import List, Dict, Optional, Tuple


class ManagerAI:
    """
    AI-controlled manager that bids based on their historical behavioral profile.
    """

    def __init__(self, manager_name: str, profile: dict, team_state: dict):
        """
        Args:
            manager_name: The manager's name
            profile: The analyzed behavioral profile from profile_analyzer
            team_state: Current team state from league_state (budget, keepers, etc.)
        """
        self.name = manager_name
        self.profile = profile
        self.team_state = team_state

        # Extract key profile stats with safe defaults
        sb = profile.get("spending_behavior", {})
        it = profile.get("inflation_tolerance", {})
        bp = profile.get("bidding_patterns", {})
        st = profile.get("service_time_preferences", {})
        cls = profile.get("classification", {})

        # Spending tendencies
        self.hitter_pct_target = sb.get("avg_hitter_spend_pct", 55) / 100
        self.pitcher_pct_target = sb.get("avg_pitcher_spend_pct", 45) / 100
        self.avg_max_bid = sb.get("avg_max_bid", 25)
        self.avg_dollar_one_count = sb.get("avg_dollar_one_count", 3)
        self.avg_money_left_over = sb.get("avg_money_left_over", 5)
        self.avg_players_drafted = sb.get("avg_players_drafted", 10)

        # Tier distribution targets
        td = sb.get("tier_distribution", {})
        self.dollar_one_pct = td.get("dollar_one_pct", 25) / 100
        self.low_pct = td.get("low_2_10_pct", 35) / 100
        self.mid_pct = td.get("mid_11_25_pct", 25) / 100
        self.high_pct = td.get("high_26_50_pct", 10) / 100
        self.elite_pct = td.get("elite_51_plus_pct", 5) / 100

        # Bidding patterns
        self.overpay_frequency = it.get("overpay_frequency_pct", 50) / 100
        self.avg_inflation_ratio = it.get("avg_inflation_ratio", 2.0)
        self.consistency_stdev = bp.get("consistency_stdev", 15)
        self.top3_concentration = bp.get("avg_top3_concentration_pct", 60) / 100

        # Service time preferences
        self.veteran_pref = st.get("veteran", 20) / 100
        self.prime_pref = st.get("prime_established", 35) / 100
        self.emerging_pref = st.get("emerging", 30) / 100
        self.rookie_pref = st.get("rookie_sophomore", 15) / 100

        # Position preferences from profile
        self.position_preferences = profile.get("position_preferences", {})

        # Track spending during simulation
        self.hitter_spent = 0
        self.pitcher_spent = 0
        self.picks_made = 0
        self.dollar_one_picks = 0

    def _fills_position_need(self, player: dict, my_needs: Dict[str, int]) -> bool:
        """
        Check if a player fills ANY roster need, including flex positions.
        A 3B player can fill 3B, CI, or UTIL. An SP can fill SP or P.
        """
        player_positions = set(player.get("position_eligibility", []))
        primary = player.get("position_primary", "")

        # Hitter-only slots — pitchers can NEVER fill these
        hitter_only_slots = {"UTIL", "CI", "MI"}

        # Direct position needs
        for pos in player_positions:
            # Skip hitter-only slots for pitchers
            if pos in hitter_only_slots and player.get("type") != "Hitter":
                continue
            if my_needs.get(pos, 0) > 0:
                return True

        # Flex slot mapping: which flex slots can this player fill?
        if player.get("type") == "Hitter":
            # Any hitter can fill UTIL
            if my_needs.get("UTIL", 0) > 0:
                return True
            # Corner infielders: 1B or 3B can fill CI
            if ("1B" in player_positions or "3B" in player_positions) and my_needs.get("CI", 0) > 0:
                return True
            # Middle infielders: 2B or SS can fill MI
            if ("2B" in player_positions or "SS" in player_positions) and my_needs.get("MI", 0) > 0:
                return True
        else:
            # Any pitcher can fill P
            if my_needs.get("P", 0) > 0:
                return True

        return False

    def decide_bid(
        self,
        player: dict,
        predicted_value: float,
        inflation_adjusted_value: float,
        my_needs: Dict[str, int],
        my_budget_remaining: float,
        my_max_bid: int,
        my_spots_remaining: int,
        position_scarcity: dict,
        all_remaining_players: List[dict],
    ) -> int:
        """
        Decide the MAXIMUM this manager would pay for a player.
        Returns 0 if not interested at all.

        The willingness is anchored to predicted_value (expected market price)
        because that's the best estimate of what a player will actually sell for.
        Manager personality then adjusts up/down from that anchor.

        In the auction, the actual price paid will be second-highest bid + $1,
        so this willingness is a ceiling, not the actual price.
        """

        # Can't bid more than max
        if my_max_bid <= 0 or my_budget_remaining <= 0:
            return 0

        # ---- Interest & willingness ----
        fills_need = self._fills_position_need(player, my_needs)
        player_positions = set(player.get("position_eligibility", []))

        # HARD ROSTER CHECK: If this player cannot fill ANY remaining roster
        # slot (direct or flex), do not bid at all. This prevents managers
        # from winning players they literally have no room for.
        if not fills_need:
            # Check if ANY roster slot is open that this player could fill.
            # Total open slots = sum of all remaining needs
            total_open = sum(max(0, v) for v in my_needs.values())
            if total_open <= 0:
                return 0  # Roster is completely full

            # Player can't fill any specific slot — check if there are open
            # hitter/pitcher slots they might contest in a real auction.
            # But fundamentally, if _fills_position_need says no, this player
            # has no legal roster slot. Don't bid.
            # (Non-need bidding is for driving up prices in theory, but in
            # practice it causes illegal roster construction.)
            return 0

        # Market price anchor: use predicted_value if available, fall back to adjusted
        market_price = predicted_value if predicted_value > 0 else inflation_adjusted_value

        # Everyone starts with the market price as their anchor
        willingness = market_price

        # Direct need = one of the player's listed positions matches an open slot
        direct_need = any(my_needs.get(pos, 0) > 0 for pos in player_positions)

        if fills_need and direct_need:
            # Direct roster need — willing to pay around market price.
            # Keep this tight to prevent Tier 1B/2 overshoot.
            willingness *= random.uniform(0.85, 1.10)
        elif fills_need:
            # Flex fill (UTIL, CI, MI, P) — solid interest, slightly less aggressive
            willingness *= random.uniform(0.75, 1.0)
        else:
            # Doesn't fill any need. In real auctions, managers STILL bid on good players
            # because: (a) they're competing for value, (b) driving up rival prices,
            # (c) the player might be underpriced. In a 12-team auction with 134 players,
            # nearly every decent player attracts multiple bidders.
            #
            # KEY INSIGHT: The second-price auction means the PRICE is set by the
            # second-highest bidder. If non-need managers don't bid, mid-tier players
            # go for $1 even though they should be $8-12. We need broad participation
            # with lower willingness to create realistic competition.
            if market_price >= 20:
                # Premium: almost everyone at least considers them
                if random.random() < 0.75:
                    willingness *= random.uniform(0.55, 0.85)
                else:
                    return 0
            elif market_price >= 10:
                # Solid mid-tier ($10-19): broad competition is essential.
                # In real auctions, $10 players ALWAYS get multiple bidders.
                if random.random() < 0.70:
                    willingness *= random.uniform(0.60, 0.85)
                else:
                    return 0
            elif market_price >= 5:
                # Lower mid: decent participation
                if random.random() < 0.40:
                    willingness *= random.uniform(0.40, 0.70)
                else:
                    return 0
            elif market_price >= 3:
                # Low-tier: occasional interest
                if random.random() < 0.20:
                    willingness *= random.uniform(0.30, 0.55)
                else:
                    return 0
            else:
                # True filler — nobody bids without a need
                return 0

        # ---- Personal inflation tolerance ----
        # Some managers consistently overpay, others are disciplined
        if random.random() < self.overpay_frequency:
            inflation_bump = 1.0 + random.uniform(0.05, 0.2)
            willingness *= inflation_bump
        else:
            # Disciplined managers shade down, but not harshly — 0.85-1.0
            # (too harsh here compounds with non-need discount and kills Tier 3)
            willingness *= random.uniform(0.85, 1.0)

        # ---- Type balance adjustment ----
        # Mild penalty when over-invested in one type. Kept small (0.9) because
        # stacking with non-need and inflation discounts was crushing mid-tier prices.
        total_spent = self.hitter_spent + self.pitcher_spent
        if total_spent > 0:
            current_hitter_pct = self.hitter_spent / total_spent
            if player.get("type") == "Hitter" and current_hitter_pct > self.hitter_pct_target + 0.15:
                willingness *= 0.9
            elif player.get("type") == "Pitcher" and current_hitter_pct < self.hitter_pct_target - 0.15:
                willingness *= 0.9

        # ---- Position scarcity escalation ----
        max_scarcity_ratio = 0
        for pos in player_positions:
            sc = position_scarcity.get(pos, {})
            if sc.get("is_scarce", False):
                max_scarcity_ratio = max(max_scarcity_ratio, sc.get("ratio", 1))

        if max_scarcity_ratio > 1.0 and fills_need:
            scarcity_bump = min(10, int(max_scarcity_ratio * 3))
            willingness += scarcity_bump

        # ---- Tier-based behavior ----
        tier = player.get("tier", "5")
        is_elite = tier in ("1A", "1B")
        if is_elite:
            if my_budget_remaining < 40:
                willingness *= 0.3  # Can't compete for elites
            elif self.top3_concentration > 0.65:
                willingness *= random.uniform(1.0, 1.1)  # Stars-and-scrubs push a little more
        elif tier == "5" and market_price <= 2:
            # True $1 filler — cap willingness low
            if self.dollar_one_picks < self.avg_dollar_one_count:
                willingness = min(willingness, 2)
            else:
                willingness = min(willingness, 3)

        # ---- Rookie premium ----
        if player.get("is_rookie", False):
            if self.rookie_pref > 0.20:
                willingness += random.uniform(1, 4)
            elif self.rookie_pref < 0.10:
                willingness *= 0.85

        # ---- Random variance ----
        noise_factor = self.consistency_stdev / 100
        noise = random.gauss(1.0, noise_factor)
        willingness *= max(0.6, min(1.4, noise))

        # ---- Budget-scaled max bid cap ----
        # Scale personal max based on current budget vs typical
        typical_budget = 260 * (self.avg_players_drafted / 22)
        if typical_budget > 0 and my_budget_remaining > typical_budget * 1.2:
            budget_scale = min(2.5, my_budget_remaining / typical_budget)
        else:
            budget_scale = 1.0
        personal_max = self.avg_max_bid * budget_scale * random.uniform(0.8, 1.3)
        # For elite players, raise the cap — everyone stretches for superstars
        if is_elite:
            personal_max = max(personal_max, market_price * random.uniform(0.9, 1.15))
        willingness = min(willingness, personal_max)

        # ---- Budget reality check ----
        willingness = min(willingness, my_max_bid)

        # ---- Floor at $1, round to integer ----
        final_bid = max(1, round(willingness))

        # If bid is $1 and doesn't fill a need, skip
        if final_bid <= 1 and not fills_need:
            return 0

        return final_bid

    def decide_nomination(
        self,
        available_players: List[dict],
        my_needs: Dict[str, int],
        my_budget_remaining: float,
        my_max_bid: int,
    ) -> Optional[dict]:
        """
        Choose which player to nominate for auction.

        In real auctions, managers use a MIXED strategy:
        1. Nominate players they WANT while they still have budget to compete
        2. Nominate expensive players they DON'T want to drain rivals
        3. Nominate cheap fills to secure roster spots

        CRITICAL: Mid-tier players ($8-15 range) must be nominated throughout
        the auction, not saved for the end. If Tier 3 players are all nominated
        late when budgets are depleted, they go for $1 regardless of actual value.
        """

        if not available_players:
            return None

        candidates = []
        for p in available_players:
            fills_need = self._fills_position_need(p, my_needs)
            pred_value = p.get("predicted_value", 0)

            # Base score: predicted value creates a natural ordering
            # that spreads nominations across all price tiers
            score = pred_value

            if fills_need:
                if pred_value >= 10:
                    # Nominate mid/high-value players we WANT while we have budget.
                    # This is the key fix: in real auctions, managers nominate players
                    # they want to buy BEFORE their budget runs out.
                    if my_budget_remaining > pred_value * 1.5:
                        score = pred_value * 1.8 + random.uniform(0, 10)
                    else:
                        score = pred_value * 1.2
                elif pred_value <= 3:
                    # Cheap players we want — nominate to grab at $1
                    score = 8 + random.uniform(0, 5)
                else:
                    # Mid-value needs
                    score = pred_value * 1.5 + random.uniform(0, 5)
            else:
                if pred_value > 20:
                    # Expensive players we DON'T need — drain rivals
                    score = pred_value * 1.5 + random.uniform(0, 5)
                elif pred_value >= 8:
                    # Mid-tier non-needs — still worth nominating to keep
                    # the auction flowing (don't let them pile up at the end)
                    score = pred_value + random.uniform(0, 8)
                elif pred_value <= 0:
                    # Worthless filler — low priority
                    score = random.uniform(0, 3)
                else:
                    # Low-value non-needs
                    score = random.uniform(2, 7)

            candidates.append((p, score))

        # Add noise to prevent perfectly deterministic ordering
        candidates.sort(key=lambda x: x[1] + random.uniform(-5, 5), reverse=True)
        return candidates[0][0] if candidates else available_players[0]

    def record_pick(self, player: dict, price: int):
        """Record a pick this AI made (for tracking spending balance)."""
        self.picks_made += 1
        if price == 1:
            self.dollar_one_picks += 1
        if player.get("type") == "Hitter":
            self.hitter_spent += price
        else:
            self.pitcher_spent += price


def run_auction_pick(
    nominated_player: dict,
    ai_managers: Dict[str, ManagerAI],
    teams: List[dict],
    team_needs: Dict[str, Dict[str, int]],
    inflation_data: dict,
    draft_log: List[dict],
    league_settings: dict,
    human_manager: Optional[str] = None,
    human_bid: Optional[int] = None,
    use_projected_anchor: bool = False,
) -> Tuple[str, int]:
    """
    Run a single auction pick using SECOND-PRICE mechanics.

    How it works (mirroring a real fantasy auction):
    1. All managers decide their max willingness to pay
    2. The highest willing bidder wins
    3. The PRICE is the second-highest bid + $1 (not the winner's max)
       This is how real auctions work — the price is set by competition.
    4. If only one bidder, they get the player for $1.

    This produces realistic prices because:
    - Stars get expensive (many bidders push price up)
    - Mid-tier players go for fair value (2-3 bidders = competitive)
    - True filler goes for $1 (nobody else wants them)
    """

    total_roster = league_settings.get("total_roster_size", 22)

    # Find the inflation-adjusted and predicted values for this player
    adjusted_value = 1
    predicted_value = nominated_player.get("predicted_value", 0)
    projected_value = nominated_player.get("projected_value", 0)
    for ap in inflation_data.get("player_adjusted_prices", []):
        if ap["player"] == nominated_player.get("player"):
            adjusted_value = ap["inflation_adjusted_value"]
            predicted_value = ap.get("predicted_value", predicted_value)
            projected_value = ap.get("projected_value", projected_value)
            break

    # When use_projected_anchor is True, AI bids anchor to stat-based
    # projected value instead of Clay's predicted market price
    if use_projected_anchor:
        predicted_value = projected_value

    position_scarcity = inflation_data.get("position_scarcity", {})
    remaining_players = [
        p for p in inflation_data.get("player_adjusted_prices", [])
        if p["player"] not in {d["player"] for d in draft_log}
    ]

    # Collect max willingness from all managers
    bids = {}
    for team in teams:
        manager_name = team["manager"]

        spent = sum(p["price"] for p in draft_log if p["manager"] == manager_name)
        budget_remaining = team["auction_budget"] - spent
        filled = team.get("keeper_count", 0) + sum(
            1 for p in draft_log if p["manager"] == manager_name
        )
        spots_remaining = total_roster - filled

        if spots_remaining <= 0 or budget_remaining <= 0:
            continue

        max_bid = max(1, budget_remaining - (spots_remaining - 1))
        needs = team_needs.get(manager_name, {})

        if manager_name == human_manager:
            if human_bid is not None and human_bid > 0:
                bids[manager_name] = min(human_bid, max_bid)
            continue

        ai = ai_managers.get(manager_name)
        if ai is None:
            continue

        bid = ai.decide_bid(
            player=nominated_player,
            predicted_value=predicted_value,
            inflation_adjusted_value=adjusted_value,
            my_needs=needs,
            my_budget_remaining=budget_remaining,
            my_max_bid=max_bid,
            my_spots_remaining=spots_remaining,
            position_scarcity=position_scarcity,
            all_remaining_players=remaining_players,
        )

        if bid > 0:
            bids[manager_name] = bid

    if not bids:
        # Nobody wanted them — assign to a team that has both open spots
        # AND a legal roster slot for this player's position
        for team in teams:
            manager_name = team["manager"]
            spent = sum(p["price"] for p in draft_log if p["manager"] == manager_name)
            filled = team.get("keeper_count", 0) + sum(
                1 for p in draft_log if p["manager"] == manager_name
            )
            if total_roster - filled > 0 and team["auction_budget"] - spent > 0:
                # Check if this team can actually roster this player
                needs = team_needs.get(manager_name, {})
                ai = ai_managers.get(manager_name)
                if ai and ai._fills_position_need(nominated_player, needs):
                    return (manager_name, 1)
        # Nobody can legally roster this player — return None to signal
        # the caller to skip this pick entirely
        return (None, 0)

    # ---- SECOND-PRICE AUCTION ----
    # Sort bids descending
    sorted_bids = sorted(bids.items(), key=lambda x: x[1], reverse=True)

    # Winner is highest bidder (random tiebreak)
    max_bid_value = sorted_bids[0][1]
    top_bidders = [m for m, b in sorted_bids if b == max_bid_value]
    winner = random.choice(top_bidders)

    # Price = second-highest bid + $1 (or $1 if only one bidder)
    if len(sorted_bids) >= 2:
        second_highest = sorted_bids[1][1]
        # In real auctions there's often a +$1 jump at the end
        final_price = second_highest + 1
        # But can't exceed the winner's actual willingness
        final_price = min(final_price, max_bid_value)
    else:
        # Only one bidder — they get it for $1
        final_price = 1

    # Floor at $1
    final_price = max(1, final_price)

    # Record the pick for the winning AI
    if winner in ai_managers:
        ai_managers[winner].record_pick(nominated_player, final_price)

    return (winner, final_price)


def choose_nominator(
    teams: List[dict],
    draft_log: List[dict],
    total_roster: int,
) -> Optional[str]:
    """
    Choose which manager nominates the next player.
    Rotates through managers who still have roster spots to fill.
    """
    pick_num = len(draft_log)

    eligible = []
    for team in teams:
        filled = team.get("keeper_count", 0) + sum(
            1 for p in draft_log if p["manager"] == team["manager"]
        )
        spent = sum(p["price"] for p in draft_log if p["manager"] == team["manager"])
        budget = team["auction_budget"] - spent
        if total_roster - filled > 0 and budget > 0:
            eligible.append(team["manager"])

    if not eligible:
        return None

    idx = pick_num % len(eligible)
    return eligible[idx]
