"""
Dynamic Inflation Calculator for IPL Auction

Inflation tracks how much ACTUAL auction prices are deviating from Clay's
predicted_value (model-predicted auction prices). The predicted values already
have inflation baked in, so:

- Before any picks: inflation = 0% (no deviation from predictions)
- If players sell above predictions: inflation goes positive (hot market)
- If players sell below predictions: inflation goes negative (cold market)

The "Adj $" column = predicted_value adjusted by current deviation + scarcity bumps.
"""

from typing import Dict, List, Optional


def calculate_inflation_lite(
    remaining_dollars: float,
    remaining_players: List[dict],
    remaining_roster_spots: int,
    league_settings: dict,
    team_needs: Optional[Dict[str, Dict[str, int]]] = None,
    draft_log: Optional[List[dict]] = None,
    all_players: Optional[List[dict]] = None,
) -> dict:
    """
    Lightweight inflation calculation for batch simulation.
    Returns inflation numbers and position scarcity WITHOUT building
    the expensive per-player adjusted prices list.
    ~3-5x faster than full calculate_inflation.
    """
    player_predicted = {}
    if all_players:
        for p in all_players:
            player_predicted[p.get("player", "")] = p.get("predicted_value", 0)

    total_actual_spent = 0
    total_predicted_spent = 0
    if draft_log:
        for pick in draft_log:
            total_actual_spent += pick.get("price", 0)
            pred = player_predicted.get(pick.get("player", ""), 0)
            total_predicted_spent += max(pred, 1)

    if total_predicted_spent > 0:
        global_deviation = (total_actual_spent / total_predicted_spent) - 1.0
    else:
        global_deviation = 0.0

    value_players = [p for p in remaining_players if p.get("predicted_value", 0) > 1]
    remaining_predicted_value = sum(p.get("predicted_value", 0) for p in value_players)
    estimated_filler_spots = max(0, remaining_roster_spots - len(value_players))
    available_dollars = max(0, remaining_dollars - estimated_filler_spots)

    if remaining_predicted_value > 0:
        forward_pressure = (available_dollars / remaining_predicted_value) - 1.0
    else:
        forward_pressure = 0.0

    picks_made = len(draft_log) if draft_log else 0
    blended_inflation = forward_pressure if picks_made > 0 else 0.0

    # Position scarcity (same logic as full version)
    position_scarcity = {}
    if team_needs:
        position_demand = {}
        for manager, needs in team_needs.items():
            for pos, count in needs.items():
                if count > 0:
                    position_demand[pos] = position_demand.get(pos, 0) + count

        flex_supply_map = {
            "P": ["SP", "RP"],
            "CI": ["1B", "3B"],
            "MI": ["2B", "SS"],
        }

        position_supply = {}
        for p in remaining_players:
            for pos in p.get("position_eligibility", []):
                position_supply[pos] = position_supply.get(pos, 0) + 1

        for flex_pos, specific_positions in flex_supply_map.items():
            if flex_pos in position_demand:
                flex_eligible = set()
                for p in remaining_players:
                    elig = p.get("position_eligibility", [])
                    if flex_pos in elig or any(sp in elig for sp in specific_positions):
                        flex_eligible.add(p.get("player", ""))
                position_supply[flex_pos] = len(flex_eligible)

        for pos, demand in position_demand.items():
            supply = position_supply.get(pos, 0)
            if supply > 0:
                ratio = demand / supply
                if ratio > 1.0:
                    position_scarcity[pos] = {
                        "demand": demand, "supply": supply,
                        "ratio": round(ratio, 2),
                        "bump_dollars": min(3, int(ratio)),
                        "is_scarce": True,
                    }
            elif demand > 0:
                position_scarcity[pos] = {
                    "demand": demand, "supply": 0,
                    "ratio": 999, "bump_dollars": 5, "is_scarce": True,
                }

    return {
        "global_inflation": round(blended_inflation * 100, 1),
        "blended_inflation_raw": blended_inflation,
        "position_scarcity": position_scarcity,
        "is_lite": True,
    }


def calculate_inflation(
    remaining_dollars: float,
    remaining_players: List[dict],
    remaining_roster_spots: int,
    league_settings: dict,
    team_needs: Optional[Dict[str, Dict[str, int]]] = None,
    draft_log: Optional[List[dict]] = None,
    all_players: Optional[List[dict]] = None,
    my_manager: Optional[str] = None,
    my_budget_remaining: float = 0,
    my_max_bid: int = 1,
    my_needs: Optional[Dict[str, int]] = None,
) -> dict:
    """
    Calculate inflation as deviation from predicted prices.

    Args:
        remaining_dollars: Total auction dollars remaining across all teams
        remaining_players: List of undrafted player dicts
        remaining_roster_spots: Total roster spots still to fill across the league
        league_settings: The league_settings.json dict
        team_needs: Optional dict of {manager_name: {position: count_needed}}
        draft_log: List of completed picks (each has 'player', 'price', etc.)
        all_players: Full player list (for looking up predicted_value of drafted players)

    Returns:
        dict with inflation data and per-player adjusted prices
    """
    # Build a lookup for predicted values
    player_predicted = {}
    if all_players:
        for p in all_players:
            player_predicted[p.get("player", "")] = p.get("predicted_value", 0)

    # ---- Step 1: Calculate deviation from predictions ----
    # How much has been spent vs. how much was predicted for those players
    total_actual_spent = 0
    total_predicted_spent = 0

    if draft_log:
        for pick in draft_log:
            total_actual_spent += pick.get("price", 0)
            pred = player_predicted.get(pick.get("player", ""), 0)
            # If predicted was $0 or missing, use $1 as floor
            total_predicted_spent += max(pred, 1)

    # Global deviation: how much actual spending exceeds predictions
    if total_predicted_spent > 0:
        global_deviation = (total_actual_spent / total_predicted_spent) - 1.0
    else:
        global_deviation = 0.0  # No picks yet = no deviation

    # Also calculate a forward-looking pressure metric:
    # remaining dollars vs remaining predicted values
    #
    # IMPORTANT: Only count players with real predicted value (> $1).
    # Zero-value players ($0 predicted, $0 projected) are filler — they'll
    # go for $1 if drafted at all. Including them in the denominator would
    # artificially deflate forward pressure by inflating "remaining value"
    # with phantom dollars. The filler spots mechanism already reserves $1
    # per roster spot that needs a filler player.
    value_players = [p for p in remaining_players if p.get("predicted_value", 0) > 1]
    remaining_predicted_value = sum(
        p.get("predicted_value", 0) for p in value_players
    )

    # Filler spots: roster spots beyond available value players
    estimated_filler_spots = max(0, remaining_roster_spots - len(value_players))
    available_dollars = max(0, remaining_dollars - estimated_filler_spots)

    if remaining_predicted_value > 0:
        forward_pressure = (available_dollars / remaining_predicted_value) - 1.0
    else:
        forward_pressure = 0.0

    # Inflation = forward pressure only.
    # This correctly captures auction economics: if managers overspend early,
    # there's LESS money left for remaining players, so prices drop.
    # If managers underspend early, there's MORE money floating around,
    # so remaining players get bid up.
    # global_deviation is still tracked for display purposes but doesn't
    # feed into adjusted prices — it was pulling the wrong direction.
    picks_made = len(draft_log) if draft_log else 0

    if picks_made == 0:
        blended_inflation = 0.0
    else:
        blended_inflation = forward_pressure

    # ---- Step 2: Hitter/Pitcher split ----
    hitter_spent = 0
    hitter_predicted = 0
    pitcher_spent = 0
    pitcher_predicted = 0

    if draft_log and all_players:
        player_type_map = {p["player"]: p.get("type", "Hitter") for p in all_players}
        for pick in draft_log:
            ptype = player_type_map.get(pick.get("player", ""), "Hitter")
            pred = player_predicted.get(pick.get("player", ""), 1)
            if ptype == "Hitter":
                hitter_spent += pick.get("price", 0)
                hitter_predicted += max(pred, 1)
            else:
                pitcher_spent += pick.get("price", 0)
                pitcher_predicted += max(pred, 1)

    hitter_deviation = ((hitter_spent / hitter_predicted) - 1.0) if hitter_predicted > 0 else 0.0
    pitcher_deviation = ((pitcher_spent / pitcher_predicted) - 1.0) if pitcher_predicted > 0 else 0.0

    if picks_made == 0:
        hitter_deviation = 0.0
        pitcher_deviation = 0.0

    # ---- Step 3: Position scarcity ----
    position_scarcity = {}
    if team_needs:
        position_demand = {}
        for manager, needs in team_needs.items():
            for pos, count in needs.items():
                if count > 0:
                    position_demand[pos] = position_demand.get(pos, 0) + count

        # Map flex slots to the specific positions that can fill them.
        # Players may not list the flex slot in their eligibility
        # (e.g. SP/RP players don't list "P"), so we count them manually.
        flex_supply_map = {
            "P": ["SP", "RP"],
            "CI": ["1B", "3B"],
            "MI": ["2B", "SS"],
        }

        position_supply = {}
        for p in remaining_players:
            for pos in p.get("position_eligibility", []):
                position_supply[pos] = position_supply.get(pos, 0) + 1

        # For flex demand slots, count players eligible for the underlying positions
        # Use a set to avoid double-counting players who are already counted
        for flex_pos, specific_positions in flex_supply_map.items():
            if flex_pos in position_demand:
                # Count unique players who can fill this flex slot
                flex_eligible = set()
                for p in remaining_players:
                    elig = p.get("position_eligibility", [])
                    # Player counts if they have the flex pos OR any specific pos
                    if flex_pos in elig or any(sp in elig for sp in specific_positions):
                        flex_eligible.add(p.get("player", ""))
                position_supply[flex_pos] = len(flex_eligible)

        for pos, demand in position_demand.items():
            supply = position_supply.get(pos, 0)
            if supply > 0:
                ratio = demand / supply
                if ratio > 1.0:
                    scarcity_bump = min(3, int(ratio))
                    position_scarcity[pos] = {
                        "demand": demand,
                        "supply": supply,
                        "ratio": round(ratio, 2),
                        "bump_dollars": scarcity_bump,
                        "is_scarce": True,
                    }
                else:
                    position_scarcity[pos] = {
                        "demand": demand,
                        "supply": supply,
                        "ratio": round(ratio, 2),
                        "bump_dollars": 0,
                        "is_scarce": False,
                    }
            elif demand > 0:
                position_scarcity[pos] = {
                    "demand": demand,
                    "supply": 0,
                    "ratio": 999,
                    "bump_dollars": 5,
                    "is_scarce": True,
                }

    # ---- Step 4: Rookie keeper premium ----
    rookie_premium = 0
    rookie_config = league_settings.get("rookie_keeper_premium", {})
    if rookie_config.get("enabled", False):
        rookie_premium = rookie_config.get("premium_dollars", 3)

    # ---- Step 5: Calculate adjusted prices ----
    # Two adjusted columns:
    #   Adj Proj $ = projected_value × (1 + inflation) + scarcity
    #     → "what this player's production is worth given current draft dynamics"
    #   Adj Pred $ = predicted_value × (1 + inflation) + scarcity
    #     → "what this player will likely sell for given current draft dynamics"
    player_adjusted_prices = []
    for p in remaining_players:
        base_value = p.get("projected_value", 0)
        pred_value = p.get("predicted_value", 0)

        # Adj Pred $ (market-based, inflation-adjusted)
        if pred_value > 1:
            adjusted_pred = pred_value * (1.0 + blended_inflation)
        else:
            adjusted_pred = 1.0

        # Adj Proj $ (stat-based, inflation-adjusted)
        if base_value > 1:
            adjusted_proj = base_value * (1.0 + blended_inflation)
        else:
            adjusted_proj = 1.0

        # Rookie keeper premium (applies to both)
        if p.get("is_rookie", False) and rookie_premium > 0:
            adjusted_pred += rookie_premium
            adjusted_proj += rookie_premium

        # Position scarcity bump — only apply after picks start
        max_scarcity_bump = 0
        if picks_made > 0:
            for pos in p.get("position_eligibility", []):
                bump = position_scarcity.get(pos, {}).get("bump_dollars", 0)
                max_scarcity_bump = max(max_scarcity_bump, bump)
            adjusted_pred += max_scarcity_bump
            adjusted_proj += max_scarcity_bump

        # Floor at $1
        adjusted_pred = max(1.0, adjusted_pred)
        adjusted_proj = max(1.0, adjusted_proj)

        # ---- Value Gap: Pred $ minus Proj $ ----
        # Positive = player costs more than they produce (overpay risk)
        # Negative = player produces more than they cost (bargain)
        value_gap = round(pred_value - base_value, 1) if pred_value > 0 and base_value > 0 else 0

        # ---- Target $: Max Clay should pay ----
        # Based on: player's value to Clay's team, budget constraints, need
        target = _calculate_target_price(
            player=p,
            adjusted_price=adjusted_pred,
            base_value=base_value,
            pred_value=pred_value,
            my_needs=my_needs or {},
            my_budget_remaining=my_budget_remaining,
            my_max_bid=my_max_bid,
        )

        player_adjusted_prices.append(
            {
                "player": p.get("player", "Unknown"),
                "base_projected_value": base_value,
                "adj_projected_value": round(adjusted_proj, 1),
                "predicted_value": pred_value,
                "inflation_adjusted_value": round(adjusted_pred, 1),
                "target_price": target,
                "value_gap": value_gap,
                "rookie_premium_applied": rookie_premium if p.get("is_rookie", False) else 0,
                "scarcity_bump_applied": max_scarcity_bump,
                "type": p.get("type", "Unknown"),
                "tier": p.get("tier", ""),
                "position_primary": p.get("position_primary", ""),
                "position_eligibility": p.get("position_eligibility", []),
                "is_rookie": p.get("is_rookie", False),
                "rank": p.get("rank", 999),
                "mlb_team": p.get("mlb_team", ""),
                "notes": p.get("notes", ""),
                "stats": p.get("stats", {}),
                "scott_white_tag": p.get("scott_white_tag", ""),
            }
        )

    return {
        "global_inflation": round(blended_inflation * 100, 1),  # As percentage: 0% at start
        "hitter_inflation": round(hitter_deviation * 100, 1),
        "pitcher_inflation": round(pitcher_deviation * 100, 1),
        "global_deviation": round(global_deviation * 100, 1),
        "forward_pressure": round(forward_pressure * 100, 1),
        "remaining_dollars": remaining_dollars,
        "remaining_predicted_value": round(remaining_predicted_value, 1),
        "remaining_roster_spots": remaining_roster_spots,
        "estimated_filler_spots": estimated_filler_spots,
        "available_dollars_for_value": round(available_dollars, 1),
        "total_actual_spent": total_actual_spent,
        "total_predicted_spent": round(total_predicted_spent, 1),
        "picks_made": picks_made,
        "position_scarcity": position_scarcity,
        "player_adjusted_prices": sorted(
            player_adjusted_prices, key=lambda x: x["rank"] if x["rank"] is not None else 999
        ),
    }


def _calculate_target_price(
    player: dict,
    adjusted_price: float,
    base_value: float,
    pred_value: float,
    my_needs: Dict[str, int],
    my_budget_remaining: float,
    my_max_bid: int,
) -> int:
    """
    Calculate the max Clay should pay for a player.

    Logic:
    - Start from the player's projected value (what they produce)
    - Bump up if Clay NEEDS a position this player fills
    - Bump up for rookies (keeper value)
    - Cap at Clay's max bid
    - If player doesn't fill any need, discount slightly (luxury pick)
    """
    if base_value <= 0:
        return 1  # Filler player

    # Start from projected value — what the player is actually worth to your team
    target = base_value

    # Does this player fill a position Clay needs?
    fills_need = False
    positions = player.get("position_eligibility", [])
    for pos in positions:
        if my_needs.get(pos, 0) > 0:
            fills_need = True
            break
    # Also check flex slots
    flex_map = {"1B": "CI", "3B": "CI", "2B": "MI", "SS": "MI"}
    for pos in positions:
        flex = flex_map.get(pos, "")
        if flex and my_needs.get(flex, 0) > 0:
            fills_need = True
            break
    if any(my_needs.get("UTIL", 0) > 0 for _ in [1]):
        if not fills_need and player.get("type") == "Hitter":
            fills_need = True  # Can always use a hitter in UTIL

    # Need premium: willing to pay more for positions you need
    if fills_need:
        # Pay up to the live prediction for a needed player
        target = max(target, adjusted_price * 0.9)
    else:
        # Luxury pick — only buy if it's a bargain
        target = target * 0.75

    # Rookie keeper premium: they have future value beyond this year
    if player.get("is_rookie", False):
        target += 5  # Willing to overpay a bit for keeper upside

    # Cap at max bid
    target = min(target, my_max_bid)

    # Floor at $1
    target = max(1, round(target))

    return target


def calculate_team_needs(teams: List[dict], league_settings: dict, draft_log: List[dict] = None) -> Dict[str, Dict[str, int]]:
    """
    Calculate what positions each team still needs to fill.
    """
    roster_positions = league_settings.get("roster_positions", {})
    roster_positions = {k: v for k, v in roster_positions.items() if not k.startswith("_")}

    team_needs = {}
    for team in teams:
        manager = team["manager"]
        needs = dict(roster_positions)

        for keeper in team.get("keepers", []):
            pos = keeper.get("position", "")
            _fill_position(needs, pos, keeper.get("player", ""))

        if draft_log:
            for pick in draft_log:
                if pick.get("manager") == manager:
                    pos = pick.get("position", "")
                    _fill_position(needs, pos, pick.get("player", ""))

        team_needs[manager] = needs

    return team_needs


def find_best_position(player: dict, needs: dict) -> str:
    """
    Given a player's full eligibility and current needs, find the best
    position to assign them. Tries each eligible position and its flex
    cascade, preferring direct slot matches over flex slots.

    Returns the position string that should be used for _fill_position,
    or the player's primary position if no slot can be found.
    """
    position_eligibility = player.get("position_eligibility", [])
    primary = player.get("position_primary", "")
    player_type = player.get("type", "Hitter")

    # Hitter-only slots that pitchers can never fill
    hitter_only_slots = {"UTIL", "CI", "MI"}

    flex_map = {
        "1B": ["CI", "UTIL"],
        "3B": ["CI", "UTIL"],
        "2B": ["MI", "UTIL"],
        "SS": ["MI", "UTIL"],
        "OF": ["UTIL"],
        "C": ["UTIL"],
        "SP": ["P"],
        "RP": ["P"],
        "DH": ["UTIL"],
    }

    # First pass: try to find a direct slot match (prefer primary position)
    # Check primary first
    if primary in needs and needs.get(primary, 0) > 0:
        if not (primary in hitter_only_slots and player_type != "Hitter"):
            return primary

    # Check other eligible positions for direct slot
    for pos in position_eligibility:
        if pos == primary:
            continue
        if pos in hitter_only_slots and player_type != "Hitter":
            continue
        if needs.get(pos, 0) > 0:
            return pos

    # Second pass: try flex slots for each eligible position
    # Check primary's flex first
    for flex_pos in flex_map.get(primary, []):
        if flex_pos in hitter_only_slots and player_type != "Hitter":
            continue
        if needs.get(flex_pos, 0) > 0:
            return primary  # Use primary, _fill_position will cascade to flex

    # Check other positions' flex cascades
    for pos in position_eligibility:
        if pos == primary:
            continue
        if pos in hitter_only_slots and player_type != "Hitter":
            continue
        for flex_pos in flex_map.get(pos, []):
            if flex_pos in hitter_only_slots and player_type != "Hitter":
                continue
            if needs.get(flex_pos, 0) > 0:
                return pos  # Use this position, _fill_position will cascade

    # No slot found — return primary as fallback
    return primary


def _fill_position(needs: dict, player_position: str, player_name: str = ""):
    """
    Fill a position slot in needs dict. Handles flex positions (CI, MI, UTIL).
    """
    if player_position in needs and needs[player_position] > 0:
        needs[player_position] -= 1
        return

    flex_map = {
        "1B": ["CI", "UTIL"],
        "3B": ["CI", "UTIL"],
        "2B": ["MI", "UTIL"],
        "SS": ["MI", "UTIL"],
        "OF": ["UTIL"],
        "C": ["UTIL"],
        "SP": ["P"],
        "RP": ["P"],
        "CI": ["UTIL"],
        "MI": ["UTIL"],
        "UT": ["UTIL"],
        "DH": ["UTIL"],
    }

    for flex_pos in flex_map.get(player_position, []):
        if flex_pos in needs and needs[flex_pos] > 0:
            needs[flex_pos] -= 1
            return


def calculate_max_bid(team: dict, draft_log: List[dict] = None, total_roster_size: int = 22) -> int:
    """
    Calculate the maximum bid a manager can make.
    """
    filled_spots = team.get("keeper_count", 0)
    if draft_log:
        filled_spots += sum(1 for p in draft_log if p.get("manager") == team["manager"])

    spots_remaining = total_roster_size - filled_spots

    current_budget = team.get("auction_budget", 0)
    if draft_log:
        spent = sum(p.get("price", 0) for p in draft_log if p.get("manager") == team["manager"])
        current_budget -= spent

    if spots_remaining <= 1:
        return max(1, current_budget)
    else:
        return max(1, current_budget - (spots_remaining - 1))
