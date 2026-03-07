"""
Auction Simulation Engine

Runs full auction simulations using the AI manager behavior engine.
Supports three modes:

1. "AI assist" in Manual Mode — AI makes X picks, then stops
2. Interactive Mode — AI runs auction, human makes own picks
3. Batch Mode — AI makes ALL picks (run N times for statistics)
4. Throwback Mode — Batch sim with keepers thrown back into the pool
"""

import copy
import random
import statistics
from typing import List, Dict, Optional, Tuple

from engine.manager_ai import ManagerAI, run_auction_pick, run_auction_pick_lite, choose_nominator
from engine.inflation import calculate_inflation, calculate_inflation_lite, calculate_team_needs, calculate_max_bid, find_best_position
from engine.standings import (
    calculate_team_stats,
    calculate_power_rankings,
    ALL_CATEGORIES,
)


def create_ai_managers(profiles: List[dict], teams: List[dict]) -> Dict[str, ManagerAI]:
    """
    Create ManagerAI instances for all managers.

    Args:
        profiles: Analyzed behavioral profiles from profile_analyzer
        teams: Current team states from league_state

    Returns:
        Dict of {manager_name: ManagerAI}
    """
    ai_managers = {}
    for team in teams:
        name = team["manager"]
        # Find matching profile
        profile = next((p for p in profiles if p["manager"] == name), None)
        if profile is None:
            # Create a default/average profile
            profile = {
                "manager": name,
                "spending_behavior": {
                    "avg_hitter_spend_pct": 55,
                    "avg_pitcher_spend_pct": 45,
                    "avg_max_bid": 25,
                    "avg_dollar_one_count": 3,
                    "avg_money_left_over": 5,
                    "avg_players_drafted": 10,
                    "tier_distribution": {
                        "dollar_one_pct": 25,
                        "low_2_10_pct": 35,
                        "mid_11_25_pct": 25,
                        "high_26_50_pct": 10,
                        "elite_51_plus_pct": 5,
                    },
                },
                "inflation_tolerance": {
                    "avg_inflation_ratio": 2.0,
                    "overpay_frequency_pct": 50,
                },
                "bidding_patterns": {
                    "avg_top3_concentration_pct": 60,
                    "consistency_stdev": 15,
                },
                "service_time_preferences": {
                    "veteran": 20,
                    "prime_established": 35,
                    "emerging": 30,
                    "rookie_sophomore": 15,
                },
                "position_preferences": {},
                "classification": {},
            }
        ai_managers[name] = ManagerAI(name, profile, team)
    return ai_managers


def run_single_simulation(
    teams: List[dict],
    players: List[dict],
    profiles: List[dict],
    league_settings: dict,
    human_manager: Optional[str] = None,
    existing_draft_log: Optional[List[dict]] = None,
    forced_picks: Optional[List[dict]] = None,
    use_projected_anchor: bool = False,
) -> dict:
    """
    Run a complete auction simulation from scratch (or from existing state).

    Args:
        teams: Team states (will be deep-copied, not modified)
        players: Player projections (will be deep-copied)
        profiles: Manager behavioral profiles
        league_settings: League settings
        human_manager: If set, skip this manager's picks (for interactive mode)
        existing_draft_log: Start from this draft state instead of empty
        forced_picks: Pre-determined picks to inject before the sim runs.
            Each entry: {"player": "Name", "price": int, "manager": "Clay Dunker"}
            These are treated as already-completed auction picks.
        use_projected_anchor: If True, AI bids anchor to projected (stat-based)
            value instead of predicted (market) value.

    Returns:
        dict with:
            - draft_log: Complete list of picks
            - team_results: Final state of each team
            - inflation_history: How inflation changed over the auction
    """

    # Deep copy to avoid mutating original data
    sim_teams = copy.deepcopy(teams)
    sim_players = copy.deepcopy(players)
    draft_log = copy.deepcopy(existing_draft_log or [])

    total_roster = league_settings.get("total_roster_size", 22)

    # Create AI managers
    ai_managers = create_ai_managers(profiles, sim_teams)

    # Inject forced picks before the auction starts
    if forced_picks:
        for fp in forced_picks:
            player_name = fp["player"]
            price = fp.get("price", 1)
            manager = fp.get("manager", human_manager or "Clay Dunker")

            # Find the player in projections to get full data
            player_data = next(
                (p for p in sim_players if p["player"] == player_name), None
            )

            # Calculate best position for this manager's needs
            team_needs = calculate_team_needs(sim_teams, league_settings, draft_log)
            mgr_needs = team_needs.get(manager, {})
            if player_data:
                best_pos = find_best_position(player_data, mgr_needs)
            else:
                best_pos = fp.get("position", "UTIL")

            pick = {
                "pick_num": len(draft_log) + 1,
                "player": player_name,
                "position": best_pos,
                "manager": manager,
                "price": price,
                "projected_value": player_data.get("projected_value", 0) if player_data else 0,
                "predicted_value": player_data.get("predicted_value", 0) if player_data else 0,
                "over_under": round(price - (player_data.get("projected_value", 0) if player_data else 0), 1),
                "tier": player_data.get("tier", "") if player_data else "",
                "type": player_data.get("type", "") if player_data else fp.get("type", "Hitter"),
                "is_rookie": player_data.get("is_rookie", False) if player_data else False,
                "is_forced": True,  # Flag so UI can distinguish
            }
            draft_log.append(pick)

            # Record the pick for the AI manager's internal tracking
            if manager in ai_managers and player_data:
                ai_managers[manager].record_pick(player_data, price)

    # Track inflation over time
    inflation_history = []

    # Get already-drafted player names (includes forced picks)
    drafted_names = {p["player"] for p in draft_log}

    # Maximum picks = total auction spots across all teams
    max_picks = sum(
        total_roster - t.get("keeper_count", 0)
        for t in sim_teams
    )

    # Safety counter
    max_iterations = max_picks + 50  # Extra safety margin
    iteration = 0

    while len(draft_log) < max_picks and iteration < max_iterations:
        iteration += 1

        # Determine nominator
        nominator = choose_nominator(sim_teams, draft_log, total_roster)
        if nominator is None:
            break

        # Skip human manager's nominations in non-interactive sims
        # (In batch mode, human_manager is None so everyone is AI)

        # Get remaining players
        remaining_players = [p for p in sim_players if p["player"] not in drafted_names]
        if not remaining_players:
            break

        # Nominator chooses a player to put up
        ai = ai_managers.get(nominator)
        needs = calculate_team_needs(sim_teams, league_settings, draft_log).get(nominator, {})

        if ai and nominator != human_manager:
            nominated = ai.decide_nomination(
                available_players=remaining_players,
                my_needs=needs,
                my_budget_remaining=_budget_remaining(sim_teams, nominator, draft_log),
                my_max_bid=_max_bid(sim_teams, nominator, draft_log, total_roster),
            )
        else:
            # For human manager or missing AI, nominate highest value available
            nominated = max(remaining_players, key=lambda p: p.get("projected_value", 0))

        if nominated is None:
            break

        # Calculate current inflation
        team_needs = calculate_team_needs(sim_teams, league_settings, draft_log)
        remaining_dollars = sum(
            t["auction_budget"] - sum(p["price"] for p in draft_log if p["manager"] == t["manager"])
            for t in sim_teams
        )
        filled_total = sum(
            t.get("keeper_count", 0) + sum(1 for p in draft_log if p["manager"] == t["manager"])
            for t in sim_teams
        )
        remaining_roster_spots = total_roster * len(sim_teams) - filled_total

        # Use lite inflation + lite auction for batch mode (no human)
        if human_manager is None:
            inflation = calculate_inflation_lite(
                remaining_dollars=remaining_dollars,
                remaining_players=remaining_players,
                remaining_roster_spots=remaining_roster_spots,
                league_settings=league_settings,
                team_needs=team_needs,
                draft_log=draft_log,
                all_players=sim_players,
            )
            winner, price = run_auction_pick_lite(
                nominated_player=nominated,
                ai_managers=ai_managers,
                teams=sim_teams,
                team_needs=team_needs,
                inflation_data=inflation,
                draft_log=draft_log,
                league_settings=league_settings,
                use_projected_anchor=use_projected_anchor,
            )
        else:
            inflation = calculate_inflation(
                remaining_dollars=remaining_dollars,
                remaining_players=remaining_players,
                remaining_roster_spots=remaining_roster_spots,
                league_settings=league_settings,
                team_needs=team_needs,
                draft_log=draft_log,
                all_players=sim_players,
            )
            winner, price = run_auction_pick(
                nominated_player=nominated,
                ai_managers=ai_managers,
                teams=sim_teams,
                team_needs=team_needs,
                inflation_data=inflation,
                draft_log=draft_log,
                league_settings=league_settings,
                human_manager=human_manager,
                human_bid=None,
                use_projected_anchor=use_projected_anchor,
            )

        # Skip if nobody could legally roster this player
        if winner is None:
            drafted_names.add(nominated["player"])  # Remove from pool
            continue

        # Determine best roster slot for the winner
        winner_needs = team_needs.get(winner, {})
        best_pos = find_best_position(nominated, winner_needs)

        # Record the pick
        pick = {
            "pick_num": len(draft_log) + 1,
            "player": nominated["player"],
            "position": best_pos,
            "manager": winner,
            "price": price,
            "projected_value": nominated.get("projected_value", 0),
            "predicted_value": nominated.get("predicted_value", 0),
            "over_under": round(price - nominated.get("projected_value", 0), 1),
            "tier": nominated.get("tier", ""),
            "type": nominated.get("type", ""),
            "is_rookie": nominated.get("is_rookie", False),
        }
        draft_log.append(pick)
        drafted_names.add(nominated["player"])

        # Track inflation every 10 picks
        if len(draft_log) % 10 == 0:
            inflation_history.append({
                "pick": len(draft_log),
                "global": inflation["global_inflation"],
                "remaining_dollars": remaining_dollars,
            })

    # Build final team results
    team_results = []
    for team in sim_teams:
        name = team["manager"]
        team_picks = [p for p in draft_log if p["manager"] == name]
        total_spent = sum(p["price"] for p in team_picks)
        total_value = sum(p["projected_value"] for p in team_picks)
        team_results.append({
            "manager": name,
            "picks": team_picks,
            "total_spent": total_spent,
            "total_value": round(total_value, 1),
            "budget_remaining": team["auction_budget"] - total_spent,
            "pick_count": len(team_picks),
        })

    return {
        "draft_log": draft_log,
        "team_results": team_results,
        "inflation_history": inflation_history,
        "total_picks": len(draft_log),
    }


def _compute_sim_standings(
    teams: List[dict],
    draft_log: List[dict],
    stat_projections: Dict[str, dict],
    my_manager: str,
) -> dict:
    """
    Run the standings engine on a single simulation's draft log.
    Returns Clay's standings data for that sim.
    """
    team_stats = calculate_team_stats(teams, draft_log, stat_projections, my_manager)
    rankings = calculate_power_rankings(team_stats)

    # Find my manager's result
    my_ranking = None
    for r in rankings:
        if r["is_me"]:
            my_ranking = r
            break

    if not my_ranking:
        return None

    # Also compute all managers' total points for league context
    all_points = [r["total_points"] for r in rankings]

    return {
        "overall_rank": my_ranking["overall_rank"],
        "total_points": my_ranking["total_points"],
        "ranks": my_ranking["ranks"],  # {category: rank_value}
        "stats": my_ranking["stats"],
        "league_avg_points": round(statistics.mean(all_points), 1) if all_points else 0,
        "league_points": all_points,
    }


def run_batch_simulations(
    teams: List[dict],
    players: List[dict],
    profiles: List[dict],
    league_settings: dict,
    num_simulations: int = 50,
    my_manager: str = "Clay Dunker",
    stat_projections: Optional[Dict[str, dict]] = None,
    forced_picks: Optional[List[dict]] = None,
    use_projected_anchor: bool = False,
) -> dict:
    """
    Run N complete auction simulations and aggregate results.

    Now includes per-sim standings analysis for Features 1-3:
    - Average standings finish and rank distribution
    - Best/worst 3 outcomes with full roster details
    - Category-level strengths/weaknesses
    - Spending profile analysis

    Args:
        forced_picks: Pre-determined picks injected at the start of every sim.
            Each entry: {"player": "Name", "price": int, "manager": "Clay Dunker"}
            Use this to test specific draft strategies — lock in target players
            at planned prices, then let the AI fill the rest of the league.
        use_projected_anchor: If True, AI bids anchor to projected (stat-based)
            value instead of predicted (market) value.

    Returns:
        dict with:
            - player_stats: Per-player price statistics across all sims
            - my_team_stats: What Clay's team typically looks like
            - consistent_values: Players who reliably go below projection
            - volatile_players: Players with high price variance
            - simulation_count: How many sims completed
            - standings_analysis: Per-sim standings data (Features 1-3)
    """

    all_results = []
    player_prices = {}  # {player_name: [prices across sims]}
    player_buyers = {}  # {player_name: {manager: count}} — for standings
    my_team_picks = {}  # {player_name: count of times drafted by me}
    my_team_spent = []
    my_team_value = []

    # Feature 1-3: Per-sim standings tracking
    sim_standings_data = []  # One entry per sim with standings + roster details

    for i in range(num_simulations):
        result = run_single_simulation(
            teams=teams,
            players=players,
            profiles=profiles,
            league_settings=league_settings,
            human_manager=None,  # All AI in batch mode
            forced_picks=forced_picks,
            use_projected_anchor=use_projected_anchor,
        )
        all_results.append(result)

        # Collect player prices and buyers
        for pick in result["draft_log"]:
            name = pick["player"]
            buyer = pick["manager"]
            if name not in player_prices:
                player_prices[name] = []
                player_buyers[name] = {}
            player_prices[name].append(pick["price"])
            player_buyers[name][buyer] = player_buyers[name].get(buyer, 0) + 1

        # Collect my team data
        my_result = next(
            (t for t in result["team_results"] if t["manager"] == my_manager),
            None,
        )
        if my_result:
            my_team_spent.append(my_result["total_spent"])
            my_team_value.append(my_result["total_value"])
            for pick in my_result["picks"]:
                pname = pick["player"]
                my_team_picks[pname] = my_team_picks.get(pname, 0) + 1

        # Feature 1-3: Run standings analysis on this sim
        if stat_projections:
            standings_result = _compute_sim_standings(
                teams, result["draft_log"], stat_projections, my_manager
            )
            if standings_result and my_result:
                # Build roster detail for best/worst tracking (drafted only)
                roster_detail = []
                for pick in my_result["picks"]:
                    roster_detail.append({
                        "player": pick["player"],
                        "position": pick["position"],
                        "price": pick["price"],
                        "tier": pick.get("tier", ""),
                        "type": pick.get("type", ""),
                        "projected_value": pick.get("projected_value", 0),
                    })

                # Compute spending profile
                hitter_spend = sum(
                    p["price"] for p in my_result["picks"]
                    if p.get("type") == "Hitter"
                )
                pitcher_spend = sum(
                    p["price"] for p in my_result["picks"]
                    if p.get("type") == "Pitcher"
                )
                dollar_one_count = sum(
                    1 for p in my_result["picks"] if p["price"] == 1
                )
                top3_spend = sum(sorted(
                    [p["price"] for p in my_result["picks"]], reverse=True
                )[:3])

                sim_standings_data.append({
                    "sim_num": i + 1,
                    "overall_rank": standings_result["overall_rank"],
                    "total_points": standings_result["total_points"],
                    "category_ranks": standings_result["ranks"],
                    "total_spent": my_result["total_spent"],
                    "total_value": my_result["total_value"],
                    "roster": roster_detail,
                    "league_avg_points": standings_result["league_avg_points"],
                    "hitter_spend": hitter_spend,
                    "pitcher_spend": pitcher_spend,
                    "dollar_one_count": dollar_one_count,
                    "top3_spend": top3_spend,
                })

    # ---- Aggregate player statistics ----
    player_stats = []
    for pname, prices in player_prices.items():
        # Find original projection
        orig = next((p for p in players if p["player"] == pname), {})
        proj_value = orig.get("projected_value", 0)
        predicted = orig.get("predicted_value", 0)

        avg_price = statistics.mean(prices)
        if len(prices) > 1:
            std_dev = statistics.stdev(prices)
        else:
            std_dev = 0

        # Find most common buyer for standings
        buyers = player_buyers.get(pname, {})
        most_common_buyer = max(buyers, key=buyers.get) if buyers else ""

        player_stats.append({
            "player": pname,
            "position": orig.get("position_primary", ""),
            "tier": orig.get("tier", ""),
            "type": orig.get("type", ""),
            "projected_value": proj_value,
            "predicted_value": predicted,
            "avg_price": round(avg_price, 1),
            "min_price": min(prices),
            "max_price": max(prices),
            "std_dev": round(std_dev, 1),
            "times_drafted": len(prices),
            "avg_over_under": round(avg_price - proj_value, 1),
            "most_common_buyer": most_common_buyer,
        })

    player_stats.sort(key=lambda x: x["avg_price"], reverse=True)

    # ---- Consistent values: reliably go below projection ----
    consistent_values = [
        p for p in player_stats
        if p["projected_value"] > 0
        and p["avg_price"] < p["projected_value"] * 0.85
        and p["std_dev"] < 5
    ]
    consistent_values.sort(key=lambda x: x["projected_value"] - x["avg_price"], reverse=True)

    # ---- Volatile players: high price variance ----
    volatile_players = [
        p for p in player_stats
        if p["std_dev"] > 8
    ]
    volatile_players.sort(key=lambda x: x["std_dev"], reverse=True)

    # ---- My average team ----
    my_frequent_picks = sorted(
        my_team_picks.items(), key=lambda x: x[1], reverse=True
    )
    my_avg_team = []
    for pname, count in my_frequent_picks:
        freq_pct = round(count / num_simulations * 100, 1)
        pstat = next((p for p in player_stats if p["player"] == pname), {})
        my_avg_team.append({
            "player": pname,
            "frequency_pct": freq_pct,
            "times_drafted": count,
            "avg_price": pstat.get("avg_price", 0),
            "position": pstat.get("position", ""),
            "tier": pstat.get("tier", ""),
        })

    # ---- Feature 1-3: Standings analysis ----
    standings_analysis = _build_standings_analysis(sim_standings_data, num_simulations)

    return {
        "simulation_count": num_simulations,
        "player_stats": player_stats,
        "consistent_values": consistent_values[:20],
        "volatile_players": volatile_players[:15],
        "my_avg_team": my_avg_team[:25],
        "my_avg_spent": round(statistics.mean(my_team_spent), 1) if my_team_spent else 0,
        "my_avg_value": round(statistics.mean(my_team_value), 1) if my_team_value else 0,
        "standings_analysis": standings_analysis,
    }


def _build_standings_analysis(sim_standings_data: List[dict], num_simulations: int) -> dict:
    """
    Build the aggregate standings analysis from per-sim data.
    Covers Features 1, 2, and 3.
    """
    if not sim_standings_data:
        return {}

    # Feature 1: Average finish and rank distribution
    ranks = [s["overall_rank"] for s in sim_standings_data]
    points = [s["total_points"] for s in sim_standings_data]

    rank_distribution = {}
    for r in ranks:
        rank_distribution[r] = rank_distribution.get(r, 0) + 1
    # Convert to sorted list of {rank, count, pct}
    rank_dist_list = []
    for rank in sorted(rank_distribution.keys()):
        rank_dist_list.append({
            "rank": rank,
            "count": rank_distribution[rank],
            "pct": round(rank_distribution[rank] / num_simulations * 100, 1),
        })

    avg_rank = round(statistics.mean(ranks), 1)
    best_rank = min(ranks)
    worst_rank = max(ranks)
    avg_points = round(statistics.mean(points), 1)

    # Feature 2: Best and worst 3 outcomes
    sorted_by_points = sorted(sim_standings_data, key=lambda s: s["total_points"], reverse=True)
    best_outcomes = sorted_by_points[:3]
    worst_outcomes = sorted_by_points[-3:]
    worst_outcomes.reverse()  # Show worst first

    # Feature 3: Category analysis
    cat_rank_totals = {cat: [] for cat in ALL_CATEGORIES}
    for s in sim_standings_data:
        for cat, rank_val in s["category_ranks"].items():
            if cat in cat_rank_totals:
                cat_rank_totals[cat].append(rank_val)

    category_analysis = {}
    for cat, vals in cat_rank_totals.items():
        if vals:
            avg_cat_rank = round(statistics.mean(vals), 1)
            category_analysis[cat] = {
                "avg_rank": avg_cat_rank,
                "min_rank": round(min(vals), 1),
                "max_rank": round(max(vals), 1),
            }

    # Identify strengths (avg rank >= 9) and weaknesses (avg rank <= 4)
    strengths = [cat for cat, data in category_analysis.items() if data["avg_rank"] >= 9]
    weaknesses = [cat for cat, data in category_analysis.items() if data["avg_rank"] <= 4]

    # Feature 3: Spending profile averages
    avg_hitter_spend = round(statistics.mean([s["hitter_spend"] for s in sim_standings_data]), 1)
    avg_pitcher_spend = round(statistics.mean([s["pitcher_spend"] for s in sim_standings_data]), 1)
    avg_dollar_one = round(statistics.mean([s["dollar_one_count"] for s in sim_standings_data]), 1)
    avg_top3 = round(statistics.mean([s["top3_spend"] for s in sim_standings_data]), 1)

    # League context: average points across all managers (from sim data)
    league_avg_pts = round(
        statistics.mean([s["league_avg_points"] for s in sim_standings_data]), 1
    ) if sim_standings_data else 0

    return {
        # Feature 1
        "avg_rank": avg_rank,
        "best_rank": best_rank,
        "worst_rank": worst_rank,
        "avg_points": avg_points,
        "rank_distribution": rank_dist_list,

        # Feature 2
        "best_outcomes": best_outcomes,
        "worst_outcomes": worst_outcomes,

        # Feature 3
        "category_analysis": category_analysis,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "spending_profile": {
            "avg_hitter_spend": avg_hitter_spend,
            "avg_pitcher_spend": avg_pitcher_spend,
            "avg_dollar_one_count": avg_dollar_one,
            "avg_top3_spend": avg_top3,
        },
        "league_avg_points": league_avg_pts,
    }


def _find_stat_comparables(
    player_stats: dict,
    existing_players: List[dict],
    top_n: int = 5,
) -> List[Tuple[float, dict]]:
    """
    Find the most statistically similar players in the draft pool.

    Returns a list of (distance, player_dict) tuples sorted by similarity
    (closest first). Used by both projected_value and predicted_value
    estimation so they reference the same set of comparables.
    """
    player_type = player_stats.get("type", "Hitter")

    # Only compare against same type with actual value and stats
    comparables = [
        p for p in existing_players
        if p.get("type") == player_type
        and p.get("projected_value", 0) > 0
        and p.get("stats")
    ]

    if not comparables:
        return []

    if player_type == "Hitter":
        stat_keys = ["R", "HR", "RBI", "SB", "OPS"]
        # OPS is on different scale, weight it higher since it matters a lot
        weights = {"R": 1.0, "HR": 2.0, "RBI": 1.0, "SB": 1.5, "OPS": 150.0}
    else:
        stat_keys = ["QS", "ERA", "WHIP", "K", "SV_H"]
        # ERA and WHIP are inverted (lower = better), handled by distance
        weights = {"QS": 3.0, "ERA": 80.0, "WHIP": 150.0, "K": 0.5, "SV_H": 3.0}

    def stat_distance(p_stats: dict, comp_stats: dict) -> float:
        """Weighted Euclidean distance between two stat lines."""
        total = 0.0
        for key in stat_keys:
            val_a = p_stats.get(key, 0) or 0
            val_b = comp_stats.get(key, 0) or 0
            w = weights.get(key, 1.0)
            total += w * ((val_a - val_b) ** 2)
        return total ** 0.5

    # Calculate distance to every comparable player
    distances = []
    for comp in comparables:
        comp_stats = comp.get("stats", {})
        dist = stat_distance(player_stats, comp_stats)
        distances.append((dist, comp))

    # Sort by distance (closest first)
    distances.sort(key=lambda x: x[0])
    return distances[:top_n]


def _estimate_projected_value(
    player_stats: dict,
    existing_players: List[dict],
    comparables: Optional[List[Tuple[float, dict]]] = None,
) -> float:
    """
    Estimate a thrown-back keeper's projected_value (production dollar value)
    by comparing their stats to existing players in the draft pool who have
    known projected_values.

    Uses inverse-distance-weighted average of the nearest stat comparables.
    This produces a value consistent with Clay's existing projection
    methodology rather than inventing a new formula.
    """
    if comparables is None:
        comparables = _find_stat_comparables(player_stats, existing_players)

    if not comparables:
        return 10.0

    # Weighted average: closer players count more
    # Use inverse distance weighting (add small epsilon to avoid division by zero)
    total_weight = 0.0
    weighted_value = 0.0
    for dist, comp in comparables:
        w = 1.0 / (dist + 0.01)
        weighted_value += w * comp.get("projected_value", 0)
        total_weight += w

    estimated = weighted_value / total_weight if total_weight > 0 else 10.0
    return round(estimated, 1)


def _estimate_predicted_value(
    player_stats: dict,
    existing_players: List[dict],
    comparables: Optional[List[Tuple[float, dict]]] = None,
) -> float:
    """
    Estimate predicted_value (expected auction price) using the same stat
    comparables used for projected_value.

    This ensures context-awareness: if the 5 nearest stat neighbors have
    pred$ of $20, $24, $21, $18, $22, the estimate will land in that range
    rather than being derived from a global formula that ignores what
    similar players actually cost.

    The inverse-distance weighting means the closest stat match has the
    most influence, so the estimate naturally respects the local price
    neighborhood in the draft pool.
    """
    if comparables is None:
        comparables = _find_stat_comparables(player_stats, existing_players)

    if not comparables:
        return 10.0

    # Same inverse-distance weighting, but on predicted_value
    total_weight = 0.0
    weighted_value = 0.0
    for dist, comp in comparables:
        pred = comp.get("predicted_value", 0)
        if pred <= 0:
            # Skip comparables with no predicted value
            continue
        w = 1.0 / (dist + 0.01)
        weighted_value += w * pred
        total_weight += w

    if total_weight == 0:
        # Fallback: no comparables had predicted values, use projected
        return _estimate_projected_value(player_stats, existing_players, comparables)

    estimated = weighted_value / total_weight
    return round(max(1.0, estimated), 1)


def _assign_rank(projected_value: float, existing_players: List[dict]) -> int:
    """
    Assign a rank to a thrown-back player by inserting them into the
    existing ranked player list based on projected_value.

    Players with higher projected_value get lower (better) ranks.
    """
    # Count how many existing draft pool players have higher projected_value
    better_count = sum(
        1 for p in existing_players
        if (p.get("projected_value", 0) or 0) > projected_value
    )
    # Rank = number of better players + 1
    return better_count + 1


def _assign_tier(projected_value: float) -> str:
    """Assign a tier label based on projected value."""
    if projected_value >= 40:
        return "1A"
    elif projected_value >= 30:
        return "1B"
    elif projected_value >= 20:
        return "2"
    elif projected_value >= 12:
        return "3"
    elif projected_value >= 6:
        return "4"
    elif projected_value >= 1:
        return "5"
    else:
        return "6"


def run_batch_throwback(
    teams: List[dict],
    players: List[dict],
    profiles: List[dict],
    league_settings: dict,
    keepers_to_throw_back: List[str],
    num_simulations: int = 25,
    my_manager: str = "Clay Dunker",
    stat_projections: Optional[Dict[str, dict]] = None,
    forced_picks: Optional[List[dict]] = None,
    use_projected_anchor: bool = False,
) -> dict:
    """
    Feature 4: Run batch simulations with specified keepers thrown back.

    Modifies Clay's team by removing specified keepers, adding their cost
    back to auction budget, and returning those players to the draft pool.
    Then runs a standard batch simulation on the modified state.

    Key accuracy features:
    - Estimates projected_value (production) using nearest-neighbor stat
      comparison against the existing draft pool, so values are consistent
      with Clay's projection methodology
    - Estimates predicted_value (auction price) using the proj/pred
      relationship in the existing pool
    - Assigns proper rank so AI managers nominate/bid on thrown-back
      players appropriately
    - The inflation engine recalculates dynamically each pick, correctly
      accounting for the changed money supply and player pool

    Args:
        teams: Original team states
        players: Original player projections
        profiles: Manager profiles
        league_settings: League settings
        keepers_to_throw_back: List of player names to throw back
        num_simulations: How many sims to run
        my_manager: Clay's manager name
        stat_projections: For standings calculation

    Returns:
        dict with standard batch results plus throwback metadata
    """
    # Deep copy so we don't modify originals
    modified_teams = copy.deepcopy(teams)
    modified_players = copy.deepcopy(players)

    # Find Clay's team
    my_team = None
    for team in modified_teams:
        if team["manager"] == my_manager:
            my_team = team
            break

    if not my_team:
        return {"error": "Manager not found"}

    # Track what we threw back for the response
    thrown_back_details = []
    existing_player_names = {p["player"] for p in modified_players}

    for keeper_name in keepers_to_throw_back:
        # Find and remove the keeper from Clay's list
        keeper_entry = None
        for k in my_team.get("keepers", []):
            if k["player"] == keeper_name:
                keeper_entry = k
                break

        if not keeper_entry:
            continue  # Skip if not found

        # Remove from keepers
        my_team["keepers"].remove(keeper_entry)
        my_team["keeper_count"] = len(my_team["keepers"])
        my_team["keeper_cost"] = sum(k.get("price", 0) for k in my_team["keepers"])
        my_team["auction_budget"] = my_team["total_budget"] - my_team["keeper_cost"]

        thrown_back_details.append({
            "player": keeper_name,
            "position": keeper_entry.get("position", ""),
            "price": keeper_entry.get("price", 0),
        })

        # Add player back to draft pool if not already there
        if keeper_name not in existing_player_names:
            # Get real stats from stat_projections (covers all 486 players)
            player_stats_data = stat_projections.get(keeper_name, {}) if stat_projections else {}
            player_type = player_stats_data.get("type", "Hitter")
            position = keeper_entry.get("position", "UTIL")

            # Build position eligibility
            pos_elig = [position]
            if position in ("1B", "3B"):
                pos_elig.append("CI")
            if position in ("2B", "SS"):
                pos_elig.append("MI")
            if position in ("C", "1B", "2B", "SS", "3B", "OF"):
                pos_elig.append("UTIL")
            if position in ("SP", "RP"):
                pos_elig.append("P")

            # Find stat comparables once, use for both estimates
            comparables = _find_stat_comparables(
                player_stats_data, modified_players
            )

            # Estimate projected_value by comparing stats to similar players
            # in the existing draft pool (nearest-neighbor approach)
            projected_value = _estimate_projected_value(
                player_stats_data, modified_players, comparables
            )

            # Estimate predicted_value (auction price) using the SAME
            # stat comparables — ensures pred$ is contextually consistent
            # with what similar players actually sell for
            predicted_value = _estimate_predicted_value(
                player_stats_data, modified_players, comparables
            )

            # Assign rank based on where this player's value falls
            # among existing draft pool players
            rank = _assign_rank(projected_value, modified_players)

            # Assign tier based on projected value
            tier = _assign_tier(projected_value)

            modified_players.append({
                "player": keeper_name,
                "position_primary": position,
                "position_eligibility": pos_elig,
                "type": player_type,
                "tier": tier,
                "projected_value": projected_value,
                "predicted_value": predicted_value,
                "rank": rank,
                "is_rookie": False,
                "mlb_team": "",
                "notes": "Thrown-back keeper",
                "stats": player_stats_data,
            })
            existing_player_names.add(keeper_name)

    # Run batch simulations with modified state
    batch_results = run_batch_simulations(
        teams=modified_teams,
        players=modified_players,
        profiles=profiles,
        league_settings=league_settings,
        num_simulations=num_simulations,
        my_manager=my_manager,
        stat_projections=stat_projections,
        forced_picks=forced_picks,
        use_projected_anchor=use_projected_anchor,
    )

    # Add throwback metadata
    batch_results["is_throwback"] = True
    batch_results["thrown_back"] = thrown_back_details
    batch_results["new_auction_budget"] = my_team["auction_budget"]
    batch_results["new_keeper_count"] = my_team["keeper_count"]

    return batch_results


def run_ai_picks(
    num_picks: int,
    teams: List[dict],
    players: List[dict],
    profiles: List[dict],
    league_settings: dict,
    existing_draft_log: List[dict],
    human_manager: str = "Clay Dunker",
) -> List[dict]:
    """
    Run N AI-controlled picks from the current draft state.
    Used for "AI, make the next X picks" in manual mode.

    Returns:
        List of new picks made (just the new ones, not the full log)
    """

    sim_teams = copy.deepcopy(teams)
    draft_log = copy.deepcopy(existing_draft_log)
    total_roster = league_settings.get("total_roster_size", 22)

    ai_managers = create_ai_managers(profiles, sim_teams)
    drafted_names = {p["player"] for p in draft_log}

    new_picks = []

    for _ in range(num_picks):
        # Choose nominator (can be any manager including human — AI takes over)
        nominator = choose_nominator(sim_teams, draft_log, total_roster)
        if nominator is None:
            break

        remaining_players = [p for p in players if p["player"] not in drafted_names]
        if not remaining_players:
            break

        # Nominator picks a player
        ai = ai_managers.get(nominator)
        needs = calculate_team_needs(sim_teams, league_settings, draft_log).get(nominator, {})

        if ai:
            nominated = ai.decide_nomination(
                available_players=remaining_players,
                my_needs=needs,
                my_budget_remaining=_budget_remaining(sim_teams, nominator, draft_log),
                my_max_bid=_max_bid(sim_teams, nominator, draft_log, total_roster),
            )
        else:
            nominated = remaining_players[0]

        if nominated is None:
            break

        # Calculate inflation
        team_needs = calculate_team_needs(sim_teams, league_settings, draft_log)
        remaining_dollars = sum(
            t["auction_budget"] - sum(p["price"] for p in draft_log if p["manager"] == t["manager"])
            for t in sim_teams
        )
        filled_total = sum(
            t.get("keeper_count", 0) + sum(1 for p in draft_log if p["manager"] == t["manager"])
            for t in sim_teams
        )
        remaining_spots = total_roster * len(sim_teams) - filled_total

        inflation = calculate_inflation(
            remaining_dollars=remaining_dollars,
            remaining_players=remaining_players,
            remaining_roster_spots=remaining_spots,
            league_settings=league_settings,
            team_needs=team_needs,
            draft_log=draft_log,
            all_players=players,
        )

        # Run auction
        winner, price = run_auction_pick(
            nominated_player=nominated,
            ai_managers=ai_managers,
            teams=sim_teams,
            team_needs=team_needs,
            inflation_data=inflation,
            draft_log=draft_log,
            league_settings=league_settings,
        )

        # Skip if nobody could legally roster this player
        if winner is None:
            drafted_names.add(nominated["player"])
            continue

        # Determine best roster slot for the winner
        winner_needs = team_needs.get(winner, {}) if winner else {}
        best_pos = find_best_position(nominated, winner_needs) if winner else nominated.get("position_primary", "")

        pick = {
            "pick_num": len(draft_log) + 1,
            "player": nominated["player"],
            "position": best_pos,
            "manager": winner,
            "price": price,
            "projected_value": nominated.get("projected_value", 0),
            "predicted_value": nominated.get("predicted_value", 0),
            "over_under": round(price - nominated.get("projected_value", 0), 1),
            "tier": nominated.get("tier", ""),
            "type": nominated.get("type", ""),
            "is_rookie": nominated.get("is_rookie", False),
        }
        draft_log.append(pick)
        drafted_names.add(nominated["player"])
        new_picks.append(pick)

        # Record for AI tracking
        if winner in ai_managers:
            ai_managers[winner].record_pick(nominated, price)

    return new_picks


# ---- Helper functions ----

def _budget_remaining(teams, manager_name, draft_log):
    team = next((t for t in teams if t["manager"] == manager_name), None)
    if not team:
        return 0
    spent = sum(p["price"] for p in draft_log if p["manager"] == manager_name)
    return team["auction_budget"] - spent


def _max_bid(teams, manager_name, draft_log, total_roster):
    team = next((t for t in teams if t["manager"] == manager_name), None)
    if not team:
        return 1
    spent = sum(p["price"] for p in draft_log if p["manager"] == manager_name)
    filled = team.get("keeper_count", 0) + sum(
        1 for p in draft_log if p["manager"] == manager_name
    )
    spots = total_roster - filled
    budget = team["auction_budget"] - spent
    if spots <= 1:
        return max(1, budget)
    return max(1, budget - (spots - 1))
