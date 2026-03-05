"""
Manager Profile Analysis Engine

Reads raw historical data from manager_profiles.json and generates
behavioral profiles for each manager. These profiles drive the AI
simulation engine.

The analyzer extracts:
- Spending behavior (hitter/pitcher split, tier distribution, etc.)
- Position preferences
- Player type preferences (service time targeting)
- Bidding patterns (concentration, consistency, etc.)
"""

import statistics
from typing import List, Dict, Any


def analyze_all_managers(manager_data: List[dict]) -> List[dict]:
    """
    Generate behavioral profiles for all managers.

    Args:
        manager_data: The 'managers' list from manager_profiles.json

    Returns:
        List of profile dicts, one per manager
    """
    profiles = []
    for manager in manager_data:
        profile = analyze_single_manager(manager)
        profiles.append(profile)
    return profiles


def analyze_single_manager(manager: dict) -> dict:
    """
    Generate a comprehensive behavioral profile for a single manager.
    """
    name = manager.get("manager", "Unknown")
    team_name = manager.get("team_name", "")
    snapshots = manager.get("yearly_snapshots", [])
    total_drafts = len(snapshots)

    if total_drafts == 0:
        return _empty_profile(name, team_name)

    # ---- Spending Behavior ----
    hitter_pcts = [s.get("hitter_spend_pct", 50) for s in snapshots]
    pitcher_pcts = [s.get("pitcher_spend_pct", 50) for s in snapshots]
    avg_hitter_pct = round(statistics.mean(hitter_pcts), 1)
    avg_pitcher_pct = round(statistics.mean(pitcher_pcts), 1)

    # Tier distribution across all years
    all_dollar_one = []
    all_low = []
    all_mid = []
    all_high = []
    all_elite = []
    all_max_bids = []
    all_avg_bids = []
    all_leftover = []
    all_auction_budgets = []
    all_auction_spends = []
    all_player_counts = []

    for s in snapshots:
        total_players = s.get("auctioned_player_count", 0)
        if total_players == 0:
            continue

        d1 = s.get("dollar_one_players", 0)
        low = s.get("low_tier_2_10", 0)
        mid = s.get("mid_tier_11_25", 0)
        high = s.get("high_tier_26_50", 0)
        elite = s.get("elite_tier_51_plus", 0)

        # Store as percentages of total players
        all_dollar_one.append(d1 / total_players * 100)
        all_low.append(low / total_players * 100)
        all_mid.append(mid / total_players * 100)
        all_high.append(high / total_players * 100)
        all_elite.append(elite / total_players * 100)

        all_max_bids.append(s.get("max_bid", 0))
        all_avg_bids.append(s.get("avg_bid", 0))
        all_leftover.append(s.get("money_left_over", 0))
        all_auction_budgets.append(s.get("auction_budget", 0))
        all_auction_spends.append(s.get("auction_spend", 0))
        all_player_counts.append(total_players)

    spending_behavior = {
        "avg_hitter_spend_pct": avg_hitter_pct,
        "avg_pitcher_spend_pct": avg_pitcher_pct,
        "hitter_spend_range": [round(min(hitter_pcts), 1), round(max(hitter_pcts), 1)],
        "tier_distribution": {
            "dollar_one_pct": round(statistics.mean(all_dollar_one), 1) if all_dollar_one else 0,
            "low_2_10_pct": round(statistics.mean(all_low), 1) if all_low else 0,
            "mid_11_25_pct": round(statistics.mean(all_mid), 1) if all_mid else 0,
            "high_26_50_pct": round(statistics.mean(all_high), 1) if all_high else 0,
            "elite_51_plus_pct": round(statistics.mean(all_elite), 1) if all_elite else 0,
        },
        "avg_max_bid": round(statistics.mean(all_max_bids), 1) if all_max_bids else 0,
        "max_bid_range": [min(all_max_bids, default=0), max(all_max_bids, default=0)],
        "avg_avg_bid": round(statistics.mean(all_avg_bids), 1) if all_avg_bids else 0,
        "avg_money_left_over": round(statistics.mean(all_leftover), 1) if all_leftover else 0,
        "avg_auction_budget": round(statistics.mean(all_auction_budgets), 1) if all_auction_budgets else 0,
        "avg_players_drafted": round(statistics.mean(all_player_counts), 1) if all_player_counts else 0,
        "avg_dollar_one_count": round(
            statistics.mean([s.get("dollar_one_players", 0) for s in snapshots]), 1
        ),
    }

    # ---- Position Preferences ----
    # Aggregate position spending across all years
    position_totals = {}
    total_spend_all = 0
    for s in snapshots:
        pos_spend = s.get("position_spending", {})
        spend = s.get("auction_spend", 0)
        total_spend_all += spend
        for pos, amount in pos_spend.items():
            position_totals[pos] = position_totals.get(pos, 0) + amount

    position_preferences = {}
    if total_spend_all > 0:
        for pos, amount in position_totals.items():
            position_preferences[pos] = round(amount / total_spend_all * 100, 1)

    # ---- Player Type / Service Time Preferences ----
    service_totals = {"veteran": 0, "prime_established": 0, "emerging": 0, "rookie_sophomore": 0}
    total_service_players = 0
    for s in snapshots:
        st = s.get("service_time_distribution", {})
        for key in service_totals:
            count = st.get(key, 0)
            service_totals[key] += count
            total_service_players += count

    service_time_pcts = {}
    if total_service_players > 0:
        for key, count in service_totals.items():
            service_time_pcts[key] = round(count / total_service_players * 100, 1)

    # ---- Inflation Tolerance ----
    all_ratios = []
    overpay_count = 0
    total_with_data = 0
    for s in snapshots:
        for p in s.get("auctioned_players", []):
            ratio = p.get("inflation_ratio")
            proj = p.get("proj_value")
            price = p.get("price", 0)
            if ratio is not None and proj is not None:
                all_ratios.append(ratio)
                total_with_data += 1
                if price > proj and proj > 0:
                    overpay_count += 1

    avg_inflation_ratio = round(statistics.mean(all_ratios), 2) if all_ratios else 1.0
    overpay_frequency = round(overpay_count / total_with_data * 100, 1) if total_with_data > 0 else 0

    # ---- Bidding Pattern: Concentration ----
    # Top-3 concentration: what % of budget goes to the 3 most expensive players
    top3_concentrations = []
    for s in snapshots:
        spend = s.get("auction_spend", 0)
        if spend <= 0:
            continue
        players = s.get("auctioned_players", [])
        prices = sorted([p.get("price", 0) for p in players], reverse=True)
        top3 = sum(prices[:3])
        top3_concentrations.append(round(top3 / spend * 100, 1))

    avg_top3_concentration = (
        round(statistics.mean(top3_concentrations), 1) if top3_concentrations else 0
    )

    # ---- Consistency Score ----
    # How predictable is this manager year-to-year?
    # Use stdev of hitter spend pct as a simple measure
    if len(hitter_pcts) > 1:
        consistency_stdev = round(statistics.stdev(hitter_pcts), 1)
    else:
        consistency_stdev = 0

    # ---- Budget-dependent behavior ----
    # How does behavior change with large vs small budget?
    budget_behavior = "insufficient_data"
    if len(all_auction_budgets) >= 3:
        budget_bid_pairs = list(zip(all_auction_budgets, all_max_bids))
        budget_bid_pairs.sort(key=lambda x: x[0])

        # Compare top third budgets vs bottom third
        third = max(1, len(budget_bid_pairs) // 3)
        low_budget_max = statistics.mean([x[1] for x in budget_bid_pairs[:third]])
        high_budget_max = statistics.mean([x[1] for x in budget_bid_pairs[-third:]])

        if high_budget_max > low_budget_max * 2:
            budget_behavior = "aggressive_when_rich"
        elif high_budget_max > low_budget_max * 1.3:
            budget_behavior = "scales_with_budget"
        else:
            budget_behavior = "consistent_regardless"

    # ---- Compile Profile ----
    profile = {
        "manager": name,
        "team_name": team_name,
        "total_drafts": total_drafts,
        "years_active": manager.get("years_active", []),
        "data_quality": "full" if total_drafts >= 4 else "limited" if total_drafts >= 2 else "minimal",
        "spending_behavior": spending_behavior,
        "position_preferences": position_preferences,
        "service_time_preferences": service_time_pcts,
        "inflation_tolerance": {
            "avg_inflation_ratio": avg_inflation_ratio,
            "overpay_frequency_pct": overpay_frequency,
        },
        "bidding_patterns": {
            "avg_top3_concentration_pct": avg_top3_concentration,
            "consistency_stdev": consistency_stdev,
            "budget_behavior": budget_behavior,
        },
        # Summary classification for quick reference
        "classification": _classify_manager(
            avg_hitter_pct, avg_top3_concentration, consistency_stdev,
            spending_behavior, service_time_pcts
        ),
    }

    return profile


def _classify_manager(
    hitter_pct, top3_conc, consistency, spending, service_time
) -> dict:
    """Generate human-readable classification labels."""

    # Strategy type
    if hitter_pct >= 65:
        strategy = "Hitter-heavy"
    elif hitter_pct <= 35:
        strategy = "Pitcher-heavy"
    else:
        strategy = "Balanced"

    # Spending style
    if top3_conc >= 70:
        spend_style = "Stars and scrubs"
    elif top3_conc <= 50:
        spend_style = "Spread the wealth"
    else:
        spend_style = "Moderate concentration"

    # Consistency
    if consistency <= 10:
        predictability = "Very predictable"
    elif consistency <= 18:
        predictability = "Moderately predictable"
    else:
        predictability = "Unpredictable"

    # Player age preference
    rookie_pct = service_time.get("rookie_sophomore", 0)
    veteran_pct = service_time.get("veteran", 0)
    if rookie_pct >= 30:
        age_pref = "Youth-oriented"
    elif veteran_pct >= 30:
        age_pref = "Veteran-oriented"
    else:
        age_pref = "Balanced age mix"

    # Dollar-one frequency
    d1_pct = spending.get("tier_distribution", {}).get("dollar_one_pct", 0)
    if d1_pct >= 40:
        filler_style = "Heavy $1 filler"
    elif d1_pct >= 25:
        filler_style = "Moderate $1 filler"
    else:
        filler_style = "Few $1 players"

    return {
        "strategy": strategy,
        "spend_style": spend_style,
        "predictability": predictability,
        "age_preference": age_pref,
        "filler_style": filler_style,
    }


def _empty_profile(name: str, team_name: str) -> dict:
    """Return an empty profile for managers with no data."""
    return {
        "manager": name,
        "team_name": team_name,
        "total_drafts": 0,
        "data_quality": "none",
        "spending_behavior": {},
        "position_preferences": {},
        "service_time_preferences": {},
        "inflation_tolerance": {},
        "bidding_patterns": {},
        "classification": {
            "strategy": "Unknown",
            "spend_style": "Unknown",
            "predictability": "Unknown",
            "age_preference": "Unknown",
            "filler_style": "Unknown",
        },
    }
