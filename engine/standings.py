"""
Projected Standings Engine

Calculates power rankings by:
1. Summing projected stats for each team (keepers + drafted players)
2. Ranking teams 1-12 in each of 10 scoring categories
3. Totaling rank points to produce overall standings

Scoring categories:
  Hitting:  R, RBI, HR, SB, OPS
  Pitching: SV_HLD, QS, ERA, WHIP, K

Rate stats (OPS, ERA, WHIP) are weighted by PA or IP to avoid
skewing toward small-sample players.
"""

import json
from typing import List, Dict, Optional, Tuple

# Categories where HIGHER is better (rank 12 = best)
HIGHER_IS_BETTER = {"R", "RBI", "HR", "SB", "OPS", "SV_HLD", "QS", "K"}

# Categories where LOWER is better (rank 12 = best for lowest value)
LOWER_IS_BETTER = {"ERA", "WHIP"}

ALL_CATEGORIES = ["R", "RBI", "HR", "SB", "OPS", "SV_HLD", "QS", "ERA", "WHIP", "K"]

HITTING_CATS = ["R", "RBI", "HR", "SB", "OPS"]
PITCHING_CATS = ["SV_HLD", "QS", "ERA", "WHIP", "K"]

# Display-friendly names
CAT_DISPLAY = {
    "R": "R",
    "RBI": "RBI",
    "HR": "HR",
    "SB": "SB",
    "OPS": "OPS",
    "SV_HLD": "SV+HLD",
    "QS": "QS",
    "ERA": "ERA",
    "WHIP": "WHIP",
    "K": "K",
}


def load_stat_projections(
    filepath: str = "data/stat_projections_2026.json",
    player_proj_filepath: str = None,
) -> Dict[str, dict]:
    """
    Load stat projections, merging from multiple sources.

    Priority:
    1. stat_projections file (primary, has keeper + draftable stats)
    2. player_projections file (fallback, has draftable player stats in 'stats' sub-object)

    Also normalizes key differences (e.g. SV_H → SV_HLD).
    """
    result = {}

    # Load primary stat projections
    try:
        with open(filepath) as f:
            data = json.load(f)
        for name, stats in data.get("players", {}).items():
            result[name] = stats
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # Merge from player_projections as fallback for missing/zero entries
    if player_proj_filepath:
        try:
            with open(player_proj_filepath) as f:
                pdata = json.load(f)
            for player in pdata.get("players", []):
                name = player.get("player", "")
                pp_stats = player.get("stats", {})
                if not pp_stats:
                    continue

                # Normalize SV_H → SV_HLD
                if "SV_H" in pp_stats and "SV_HLD" not in pp_stats:
                    pp_stats["SV_HLD"] = pp_stats.pop("SV_H")

                # Add player type from parent object
                pp_stats["type"] = player.get("type", "")

                # Use player_proj stats if stat_proj entry is missing or all zeros
                existing = result.get(name, {})
                existing_has_data = any(
                    existing.get(k, 0) > 0
                    for k in ["R", "HR", "RBI", "PA", "IP", "K", "SV_HLD", "QS"]
                )

                if not existing_has_data:
                    pp_has_data = any(
                        pp_stats.get(k, 0) > 0
                        for k in ["R", "HR", "RBI", "PA", "IP", "K", "SV_HLD", "QS"]
                    )
                    if pp_has_data:
                        result[name] = pp_stats
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    return result


def calculate_team_stats(
    teams: List[dict],
    draft_log: List[dict],
    stat_projections: Dict[str, dict],
    my_manager: str = "Clay Dunker",
) -> List[dict]:
    """
    Calculate projected stat totals for each team.

    Sums stats across keepers + drafted players. Rate stats (OPS, ERA, WHIP)
    are properly weighted by PA or IP.

    Args:
        teams: Team data from league_state
        draft_log: Current draft picks
        stat_projections: {player_name: stats} from stat_projections file
        my_manager: Highlight this manager

    Returns:
        List of team stat summaries, one per team.
    """

    team_stats = []

    for team in teams:
        manager = team["manager"]

        # Collect all players on this team
        roster = []

        # 1. Keepers
        for keeper in team.get("keepers", []):
            player_name = keeper["player"]
            stats = stat_projections.get(player_name, {})
            roster.append({
                "player": player_name,
                "source": "keeper",
                "position": keeper.get("position", ""),
                "price": keeper.get("price", 0),
                "stats": stats,
            })

        # 2. Drafted players
        for pick in draft_log:
            if pick["manager"] == manager:
                player_name = pick["player"]
                stats = stat_projections.get(player_name, {})
                roster.append({
                    "player": player_name,
                    "source": "drafted",
                    "position": pick.get("position", ""),
                    "price": pick.get("price", 0),
                    "stats": stats,
                })

        # Aggregate stats
        totals = _aggregate_stats(roster)

        team_stats.append({
            "manager": manager,
            "team_name": team.get("team_name", ""),
            "is_me": manager == my_manager,
            "roster_size": len(roster),
            "keepers": sum(1 for r in roster if r["source"] == "keeper"),
            "drafted": sum(1 for r in roster if r["source"] == "drafted"),
            "roster": roster,
            "stats": totals,
        })

    return team_stats


def _aggregate_stats(roster: List[dict]) -> dict:
    """
    Aggregate stats across a roster.

    Counting stats (R, RBI, HR, SB, SV_HLD, QS, K): simple sum.
    Rate stats:
      - OPS: weighted by PA (plate appearances)
      - ERA: weighted by IP (innings pitched)
      - WHIP: weighted by IP
    """

    # Initialize
    totals = {cat: 0 for cat in ALL_CATEGORIES}
    total_pa = 0  # For weighting OPS
    total_ip = 0  # For weighting ERA and WHIP
    total_ops_weighted = 0  # OPS × PA sum
    total_era_weighted = 0  # ERA × IP sum
    total_whip_weighted = 0  # WHIP × IP sum

    for player in roster:
        stats = player.get("stats", {})

        if stats.get("type") == "Hitter":
            totals["R"] += stats.get("R", 0)
            totals["RBI"] += stats.get("RBI", 0)
            totals["HR"] += stats.get("HR", 0)
            totals["SB"] += stats.get("SB", 0)

            pa = stats.get("PA", 0)
            ops = stats.get("OPS", 0)
            if pa > 0 and ops > 0:
                total_pa += pa
                total_ops_weighted += ops * pa

        elif stats.get("type") == "Pitcher":
            totals["SV_HLD"] += stats.get("SV_HLD", 0)
            totals["QS"] += stats.get("QS", 0)
            totals["K"] += stats.get("K", 0)

            ip = stats.get("IP", 0)
            era = stats.get("ERA", 0)
            whip = stats.get("WHIP", 0)
            if ip > 0:
                total_ip += ip
                total_era_weighted += era * ip
                total_whip_weighted += whip * ip

    # Calculate weighted rate stats
    if total_pa > 0:
        totals["OPS"] = round(total_ops_weighted / total_pa, 3)
    else:
        totals["OPS"] = 0.000

    if total_ip > 0:
        totals["ERA"] = round(total_era_weighted / total_ip, 2)
        totals["WHIP"] = round(total_whip_weighted / total_ip, 3)
    else:
        totals["ERA"] = 0.00
        totals["WHIP"] = 0.000

    totals["PA"] = total_pa
    totals["IP"] = total_ip

    return totals


def calculate_power_rankings(
    team_stats: List[dict],
) -> List[dict]:
    """
    Rank teams 1-12 in each category, sum rank points for overall standings.

    Rank 12 = best, Rank 1 = worst.
    For counting stats (R, HR, etc.): highest value gets rank 12.
    For rate stats (ERA, WHIP): lowest value gets rank 12.
    Ties get averaged ranks.

    Args:
        team_stats: Output from calculate_team_stats()

    Returns:
        List of team standings dicts sorted by total rank points (desc).
    """

    num_teams = len(team_stats)
    if num_teams == 0:
        return []

    # Initialize rankings
    rankings = []
    for ts in team_stats:
        rankings.append({
            "manager": ts["manager"],
            "team_name": ts["team_name"],
            "is_me": ts["is_me"],
            "roster_size": ts["roster_size"],
            "keepers": ts["keepers"],
            "drafted": ts["drafted"],
            "stats": ts["stats"],
            "ranks": {},
            "total_points": 0,
            "overall_rank": 0,
        })

    # Rank each category
    for cat in ALL_CATEGORIES:
        # Get (index, value) pairs
        values = [(i, r["stats"].get(cat, 0)) for i, r in enumerate(rankings)]

        # Sort: for higher-is-better, sort descending; for lower-is-better, sort ascending
        if cat in HIGHER_IS_BETTER:
            values.sort(key=lambda x: x[1], reverse=True)
        else:
            # Lower is better: sort ascending (lowest ERA first = best)
            values.sort(key=lambda x: x[1])

        # Assign ranks (best gets num_teams, worst gets 1)
        # Handle ties with averaged ranks
        assigned = [0] * num_teams
        i = 0
        while i < len(values):
            # Find all tied entries
            j = i
            while j < len(values) and values[j][1] == values[i][1]:
                j += 1

            # Ranks for this group: (num_teams - i) down to (num_teams - j + 1)
            # Average them for ties
            rank_sum = sum(num_teams - k for k in range(i, j))
            avg_rank = rank_sum / (j - i)

            for k in range(i, j):
                idx = values[k][0]
                assigned[idx] = avg_rank

            i = j

        # Store ranks
        for idx, rank in enumerate(assigned):
            rankings[idx]["ranks"][cat] = rank

    # Calculate total points
    for r in rankings:
        r["total_points"] = sum(r["ranks"].values())
        r["total_points"] = round(r["total_points"], 1)

    # Sort by total points descending
    rankings.sort(key=lambda x: x["total_points"], reverse=True)

    # Assign overall rank
    for i, r in enumerate(rankings):
        r["overall_rank"] = i + 1

    return rankings


def get_standings(
    teams: List[dict],
    draft_log: List[dict],
    stat_projections: Dict[str, dict],
    my_manager: str = "Clay Dunker",
) -> dict:
    """
    Full standings pipeline: aggregate stats → rank → return.

    Returns:
        {
            "standings": [...],  # Power rankings sorted by total points
            "categories": [...], # Category names for display
            "has_stats": bool,   # Whether any stats are populated
        }
    """

    team_stats = calculate_team_stats(teams, draft_log, stat_projections, my_manager)
    rankings = calculate_power_rankings(team_stats)

    # Check if any stats are actually populated
    has_stats = any(
        any(ts["stats"].get(cat, 0) != 0 for cat in ALL_CATEGORIES)
        for ts in team_stats
    )

    return {
        "standings": rankings,
        "categories": ALL_CATEGORIES,
        "category_display": CAT_DISPLAY,
        "hitting_cats": HITTING_CATS,
        "pitching_cats": PITCHING_CATS,
        "has_stats": has_stats,
    }
