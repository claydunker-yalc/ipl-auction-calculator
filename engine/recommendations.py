"""
Personal Recommendation Engine for Clay's team (Waxahatchie Swaps)

Generates personalized draft recommendations based on:
- Current inflation-adjusted values
- Positions still needed
- Budget remaining
- Best value available
"""

from typing import List, Dict


def generate_recommendations(
    my_team: dict,
    my_needs: Dict[str, int],
    adjusted_players: List[dict],
    my_budget_remaining: float,
    my_max_bid: int,
    draft_log: List[dict] = None,
) -> dict:
    """
    Generate personalized recommendations for the Waxahatchie Swaps.

    Returns dict with:
        - best_value: Top players where adjusted price represents good value
        - position_targets: Recommended players by position needed
        - avoid_list: Players that are overpriced given current budget/inflation
        - budget_summary: Quick budget overview
    """

    # Filter to only available (undrafted) players
    drafted_names = set()
    if draft_log:
        drafted_names = {p["player"] for p in draft_log}

    available = [p for p in adjusted_players if p["player"] not in drafted_names]

    # ---- Best Value Available ----
    # Value = projected_value - inflation_adjusted_value (higher = more underpriced)
    # Also filter to players we can actually afford
    affordable = [p for p in available if p["inflation_adjusted_value"] <= my_max_bid]

    best_value = []
    for p in affordable:
        base = p.get("base_projected_value", 0)
        adjusted = p.get("inflation_adjusted_value", 1)
        predicted = p.get("predicted_value", adjusted)
        # Value score: how much projected value per adjusted dollar
        if adjusted > 0:
            value_ratio = base / adjusted
        else:
            value_ratio = 0

        # Check if this player fills a need
        fills_need = False
        for pos in p.get("position_eligibility", []):
            if my_needs.get(pos, 0) > 0:
                fills_need = True
                break

        best_value.append({
            **p,
            "value_ratio": round(value_ratio, 2),
            "fills_need": fills_need,
            "affordable": True,
        })

    # Sort by value ratio (best deals first), prioritize need-fillers
    best_value.sort(key=lambda x: (-x["fills_need"], -x["value_ratio"]))

    # ---- Position Targets ----
    # For each position I still need, recommend the best players
    position_targets = {}
    for pos, count in my_needs.items():
        if count <= 0:
            continue

        # Find players eligible for this position
        eligible = [
            p for p in affordable
            if pos in p.get("position_eligibility", [])
        ]

        # Sort by value (best deals first)
        eligible.sort(key=lambda x: x.get("inflation_adjusted_value", 999), reverse=False)

        # Add value info
        targets = []
        for p in eligible[:8]:  # Top 8 per position
            base = p.get("base_projected_value", 0)
            adjusted = p.get("inflation_adjusted_value", 1)
            targets.append({
                **p,
                "value_ratio": round(base / adjusted, 2) if adjusted > 0 else 0,
            })

        position_targets[pos] = {
            "count_needed": count,
            "options_available": len(eligible),
            "targets": targets,
        }

    # ---- Avoid List ----
    # Players where inflation makes them way too expensive for what they provide
    avoid_list = []
    for p in available:
        adjusted = p.get("inflation_adjusted_value", 1)
        base = p.get("base_projected_value", 0)
        predicted = p.get("predicted_value", adjusted)

        # Avoid if adjusted price > budget allows and they don't fill critical need
        if adjusted > my_max_bid:
            avoid_list.append({
                **p,
                "reason": f"Over max bid (${my_max_bid})",
            })
        elif base > 0 and adjusted / base > 2.0:
            avoid_list.append({
                **p,
                "reason": f"Inflated {round(adjusted/base, 1)}x above projection",
            })

    avoid_list.sort(key=lambda x: x.get("inflation_adjusted_value", 0), reverse=True)

    # ---- Budget Summary ----
    spots_filled = len(my_team.get("keepers", []))
    if draft_log:
        spots_filled += sum(1 for p in draft_log if p.get("manager") == my_team.get("manager"))

    total_roster = 22
    spots_remaining = total_roster - spots_filled

    budget_summary = {
        "total_budget": my_team.get("total_budget", 260),
        "keeper_cost": my_team.get("keeper_cost", 0),
        "auction_budget": my_team.get("auction_budget", 260),
        "spent_so_far": sum(
            p.get("price", 0) for p in (draft_log or [])
            if p.get("manager") == my_team.get("manager")
        ),
        "budget_remaining": my_budget_remaining,
        "max_bid": my_max_bid,
        "spots_remaining": spots_remaining,
        "spots_at_dollar_one": max(0, spots_remaining - 1),
    }
    budget_summary["available_for_value_picks"] = (
        budget_summary["budget_remaining"] - budget_summary["spots_at_dollar_one"]
    )

    return {
        "best_value": best_value[:15],  # Top 15 value plays
        "position_targets": position_targets,
        "avoid_list": avoid_list[:10],  # Top 10 to avoid
        "budget_summary": budget_summary,
    }
