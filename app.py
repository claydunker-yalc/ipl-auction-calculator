"""
IPL Auction Calculator — Main Flask Application

A personal fantasy baseball auction preparation tool for the Illini Penal League.
Features three modes: Manual Draft, Interactive AI Sim, and Batch AI Sim.

Run with: python app.py
Opens at: http://localhost:5000
"""

import json
import math
import os
import copy
from functools import wraps
from flask import Flask, render_template, request, Response, redirect, abort


def safe_jsonify(obj):
    """jsonify replacement that handles Infinity and NaN."""
    def sanitize(o):
        if isinstance(o, float):
            if math.isinf(o):
                return 999
            if math.isnan(o):
                return 0
            return o
        if isinstance(o, dict):
            return {k: sanitize(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [sanitize(v) for v in o]
        return o

    clean = sanitize(obj)
    return Response(json.dumps(clean), mimetype="application/json")

from engine.inflation import (
    calculate_inflation,
    calculate_team_needs,
    calculate_max_bid,
)
from engine.profile_analyzer import analyze_all_managers
from engine.recommendations import generate_recommendations
from engine.simulator import run_batch_simulations, run_batch_throwback, run_ai_picks, run_single_simulation
from engine.standings import load_stat_projections, get_standings

# ============================================================
# Flask App Setup
# ============================================================
app = Flask(__name__)
app.config["SECRET_KEY"] = "ipl-auction-2026"

# Dashboard access key — set via environment variable or use default for local dev.
DASHBOARD_KEY = os.environ.get("DASHBOARD_KEY", "YandyChrist")
print(f"[STARTUP] Dashboard key configured (default: YandyChrist)")

# Public routes that don't need the key
PUBLIC_ROUTES = {"/board", "/api/board_state", "/favicon.ico"}


@app.before_request
def check_dashboard_access():
    """Protect all non-public routes with a key parameter."""
    path = request.path

    # Allow public routes
    if path in PUBLIC_ROUTES:
        return None

    # Allow static files
    if path.startswith("/static/"):
        return None

    # Check for key in query string (?key=xxx) or session cookie
    key = request.args.get("key") or request.cookies.get("dashboard_key")
    if key == DASHBOARD_KEY:
        return None

    # No valid key — redirect to board
    return redirect("/board")


DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# ============================================================
# Global State — loaded at startup, modified during auction
# ============================================================
state = {
    "league_settings": {},
    "league_state": {},
    "player_projections": [],
    "stat_projections": {},     # {player_name: stats} for standings
    "manager_profiles_raw": [],
    "manager_profiles_analyzed": [],
    "draft_log": [],           # List of {pick_num, player, position, manager, price, projected_value}
    "mode": "manual",          # manual | interactive | batch
    "last_batch_results": None, # Store last batch sim for standings
    "draft_active": False,     # When False, public board hides draft picks (sim mode)
    # Nomination order for auction day — set manager names in draft order, index tracks who's up
    "nomination_order": [],    # e.g. ["Clay Dunker", "Brad Garrett", ...]
    "nomination_index": 0,     # current nominator position in the list
}

MY_MANAGER = "Clay Dunker"


def load_data():
    """Load all JSON data files into memory."""
    with open(os.path.join(DATA_DIR, "league_settings.json")) as f:
        state["league_settings"] = json.load(f)

    with open(os.path.join(DATA_DIR, "league_state_2026.json")) as f:
        state["league_state"] = json.load(f)

    with open(os.path.join(DATA_DIR, "player_projections_2026.json")) as f:
        pdata = json.load(f)
        state["player_projections"] = pdata.get("players", [])

    with open(os.path.join(DATA_DIR, "manager_profiles.json")) as f:
        mdata = json.load(f)
        state["manager_profiles_raw"] = mdata.get("managers", [])

    # Load stat projections for standings (merges from both files)
    state["stat_projections"] = load_stat_projections(
        filepath=os.path.join(DATA_DIR, "stat_projections_2026.json"),
        player_proj_filepath=os.path.join(DATA_DIR, "player_projections_2026.json"),
    )

    # Run the profile analyzer
    state["manager_profiles_analyzed"] = analyze_all_managers(state["manager_profiles_raw"])

    # Auto-restore draft log from last save (crash recovery)
    draft_save_path = os.path.join(DATA_DIR, "draft_save.json")
    if os.path.exists(draft_save_path):
        try:
            with open(draft_save_path) as f:
                saved = json.load(f)
            state["draft_log"] = saved.get("draft_log", [])
            state["mode"] = saved.get("mode", "manual")
            state["draft_active"] = saved.get("draft_active", False)
            state["nomination_order"] = saved.get("nomination_order", [])
            state["nomination_index"] = saved.get("nomination_index", 0)
            if state["draft_log"]:
                print(f"Auto-restored {len(state['draft_log'])} picks from saved draft")
            if state["nomination_order"]:
                print(f"Restored nomination order: {len(state['nomination_order'])} managers, index {state['nomination_index']}")
            print(f"Draft active: {state['draft_active']}")
        except Exception as e:
            print(f"[WARNING] Could not restore draft save: {e}")
            state["draft_log"] = []
    else:
        state["draft_log"] = []

    print(f"Loaded {len(state['player_projections'])} players")
    print(f"Loaded {len(state['league_state'].get('teams', []))} teams")
    print(f"Loaded {len(state['stat_projections'])} stat projections")
    print(f"Analyzed {len(state['manager_profiles_analyzed'])} manager profiles")


def save_data(filename, data):
    """Save data back to a JSON file."""
    filepath = os.path.join(DATA_DIR, filename)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


def auto_save_draft():
    """Auto-save draft state after every pick/undo/move. Crash-proof."""
    try:
        save_data("draft_save.json", {
            "draft_log": state["draft_log"],
            "mode": state["mode"],
            "draft_active": state["draft_active"],
            "nomination_order": state["nomination_order"],
            "nomination_index": state["nomination_index"],
        })
    except Exception as e:
        print(f"[WARNING] Auto-save failed: {e}")


def get_current_inflation():
    """Calculate current inflation based on auction state."""
    teams = state["league_state"].get("teams", [])
    settings = state["league_settings"]
    draft_log = state["draft_log"]
    total_roster_size = settings.get("total_roster_size", 22)

    # Calculate remaining dollars across all teams
    remaining_dollars = 0
    total_roster_spots = 0
    filled_spots = 0

    for team in teams:
        budget = team.get("auction_budget", 0)
        spent = sum(p["price"] for p in draft_log if p["manager"] == team["manager"])
        remaining_dollars += (budget - spent)

        filled = team.get("keeper_count", 0) + sum(
            1 for p in draft_log if p["manager"] == team["manager"]
        )
        total_roster_spots += total_roster_size
        filled_spots += filled

    remaining_roster_spots = total_roster_spots - filled_spots

    # Get remaining (undrafted) players
    drafted_names = {p["player"] for p in draft_log}
    remaining_players = [
        p for p in state["player_projections"] if p["player"] not in drafted_names
    ]

    # Calculate team needs for position scarcity
    team_needs = calculate_team_needs(teams, settings, draft_log)

    # Get Clay's budget info for Target $ calculation
    my_team = None
    for t in teams:
        if t["manager"] == MY_MANAGER:
            my_team = t
            break

    my_budget_remaining = 0
    my_max_bid_val = 1
    my_needs = team_needs.get(MY_MANAGER, {})
    if my_team:
        my_spent = sum(p["price"] for p in draft_log if p["manager"] == MY_MANAGER)
        my_budget_remaining = my_team["auction_budget"] - my_spent
        my_max_bid_val = calculate_max_bid(
            my_team, draft_log, settings.get("total_roster_size", 22)
        )

    # Run inflation calculation
    inflation = calculate_inflation(
        remaining_dollars=remaining_dollars,
        remaining_players=remaining_players,
        remaining_roster_spots=remaining_roster_spots,
        league_settings=settings,
        team_needs=team_needs,
        draft_log=draft_log,
        all_players=state["player_projections"],
        my_manager=MY_MANAGER,
        my_budget_remaining=my_budget_remaining,
        my_max_bid=my_max_bid_val,
        my_needs=my_needs,
    )

    return inflation, team_needs


def get_my_team():
    """Get Clay Dunker's team data."""
    for team in state["league_state"].get("teams", []):
        if team["manager"] == MY_MANAGER:
            return team
    return None


# ============================================================
# Routes — Pages
# ============================================================
@app.route("/")
def dashboard():
    """Main dashboard page. Key must be provided to reach here (before_request enforces it)."""
    resp = Response(render_template("dashboard.html"))
    # Set cookie so subsequent requests (API calls, etc.) don't need ?key= in the URL
    key = request.args.get("key") or request.cookies.get("dashboard_key")
    if key == DASHBOARD_KEY:
        resp.set_cookie("dashboard_key", key, max_age=60*60*24*7, httponly=True, samesite="Lax")
    return resp


@app.route("/board")
def public_board():
    """Public read-only draft board for league members."""
    return render_template("board.html")


@app.route("/api/board_state")
def api_board_state():
    """Slim state for the public board — no inflation, no recommendations, no profiles.

    When draft_active is False, draft picks are hidden from the public board
    so the commissioner can run sims without updating the live board.
    """
    # When draft is inactive, the public board sees NO draft picks
    visible_log = state["draft_log"] if state["draft_active"] else []

    teams_info = []
    for team in state["league_state"].get("teams", []):
        spent = sum(p["price"] for p in visible_log if p["manager"] == team["manager"])
        drafted_count = sum(1 for p in visible_log if p["manager"] == team["manager"])
        teams_info.append({
            "manager": team["manager"],
            "auction_budget": team["auction_budget"],
            "spent": spent,
            "budget_remaining": team["auction_budget"] - spent,
            "keeper_count": team.get("keeper_count", 0),
            "keepers": team.get("keepers", []),
            "drafted_count": drafted_count,
            "spots_remaining": (
                state["league_settings"].get("total_roster_size", 22)
                - team.get("keeper_count", 0)
                - drafted_count
            ),
            "drafted_players": [
                p for p in visible_log if p["manager"] == team["manager"]
            ],
        })
    return safe_jsonify({
        "teams": teams_info,
        "draft_log": visible_log,
        "draft_active": state["draft_active"],
        "total_roster_size": state["league_settings"].get("total_roster_size", 22),
        "nomination_order": state["nomination_order"],
        "nomination_index": state["nomination_index"],
    })


# ============================================================
# Routes — API Endpoints
# ============================================================

@app.route("/api/state")
def api_state():
    """Return the full current state for the dashboard to render."""
    inflation, team_needs = get_current_inflation()
    my_team = get_my_team()

    # Calculate max bid for each team
    teams_with_info = []
    for team in state["league_state"].get("teams", []):
        team_info = dict(team)
        spent = sum(p["price"] for p in state["draft_log"] if p["manager"] == team["manager"])
        team_info["spent"] = spent
        team_info["budget_remaining"] = team["auction_budget"] - spent
        team_info["max_bid"] = calculate_max_bid(
            team, state["draft_log"], state["league_settings"].get("total_roster_size", 22)
        )
        # Count drafted players
        team_info["drafted_count"] = sum(
            1 for p in state["draft_log"] if p["manager"] == team["manager"]
        )
        team_info["spots_remaining"] = (
            state["league_settings"].get("total_roster_size", 22)
            - team.get("keeper_count", 0)
            - team_info["drafted_count"]
        )
        team_info["needs"] = team_needs.get(team["manager"], {})

        # Get drafted players for this team
        team_info["drafted_players"] = [
            p for p in state["draft_log"] if p["manager"] == team["manager"]
        ]

        teams_with_info.append(team_info)

    # Generate my recommendations
    my_budget_remaining = 0
    my_max_bid = 1
    my_needs = {}
    if my_team:
        spent = sum(p["price"] for p in state["draft_log"] if p["manager"] == MY_MANAGER)
        my_budget_remaining = my_team["auction_budget"] - spent
        my_max_bid = calculate_max_bid(
            my_team, state["draft_log"], state["league_settings"].get("total_roster_size", 22)
        )
        my_needs = team_needs.get(MY_MANAGER, {})

    recommendations = generate_recommendations(
        my_team=my_team or {},
        my_needs=my_needs,
        adjusted_players=inflation["player_adjusted_prices"],
        my_budget_remaining=my_budget_remaining,
        my_max_bid=my_max_bid,
        draft_log=state["draft_log"],
    )

    return safe_jsonify({
        "inflation": {
            "global_inflation": inflation["global_inflation"],
            "hitter_inflation": inflation["hitter_inflation"],
            "pitcher_inflation": inflation["pitcher_inflation"],
            "global_deviation": inflation["global_deviation"],
            "forward_pressure": inflation["forward_pressure"],
            "remaining_dollars": inflation["remaining_dollars"],
            "remaining_predicted_value": inflation["remaining_predicted_value"],
            "remaining_roster_spots": inflation["remaining_roster_spots"],
            "total_actual_spent": inflation["total_actual_spent"],
            "total_predicted_spent": inflation["total_predicted_spent"],
            "picks_made": inflation["picks_made"],
            "position_scarcity": inflation["position_scarcity"],
        },
        "players": inflation["player_adjusted_prices"],
        "teams": teams_with_info,
        "draft_log": state["draft_log"],
        "recommendations": recommendations,
        "my_manager": MY_MANAGER,
        "my_auction_budget": my_team["auction_budget"] if my_team else 0,
        "my_spots_remaining": (
            state["league_settings"].get("total_roster_size", 22)
            - (my_team.get("keeper_count", 0) if my_team else 0)
        ),
        "league_settings": state["league_settings"],
        "mode": state["mode"],
        "draft_active": state["draft_active"],
        "profiles": state["manager_profiles_analyzed"],
        "nomination_order": state["nomination_order"],
        "nomination_index": state["nomination_index"],
    })


def _manager_spots_remaining(manager_name):
    """How many roster spots does this manager still need to fill?"""
    total_roster = state["league_settings"].get("total_roster_size", 22)
    team = next((t for t in state["league_state"].get("teams", []) if t["manager"] == manager_name), None)
    if not team:
        return 0
    keeper_count = team.get("keeper_count", 0)
    drafted_count = sum(1 for p in state["draft_log"] if p["manager"] == manager_name)
    return total_roster - keeper_count - drafted_count


def advance_nomination(direction=1):
    """Advance (or retreat) the nomination index, skipping managers with full rosters.
    direction: +1 for forward, -1 for backward.
    """
    order = state["nomination_order"]
    if not order:
        return
    n = len(order)
    idx = state["nomination_index"]
    # Try up to n steps to find a manager who still has spots
    for _ in range(n):
        idx = (idx + direction) % n
        if _manager_spots_remaining(order[idx]) > 0:
            break
    state["nomination_index"] = idx


@app.route("/api/nomination_nav", methods=["POST"])
def api_nomination_nav():
    """Manually move the nomination pointer. Body: {direction: 1 or -1} or {index: N}"""
    data = request.json
    if "index" in data:
        # Jump to a specific index
        order = state["nomination_order"]
        if order:
            state["nomination_index"] = max(0, min(data["index"], len(order) - 1))
    else:
        direction = data.get("direction", 1)
        advance_nomination(direction)
    return safe_jsonify({
        "nomination_index": state["nomination_index"],
        "nomination_order": state["nomination_order"],
    })


@app.route("/api/set_nomination_order", methods=["POST"])
def api_set_nomination_order():
    """Set the nomination order. Body: {order: ["Manager1", "Manager2", ...]}"""
    data = request.json
    order = data.get("order", [])
    if not order:
        return safe_jsonify({"error": "Order list is required"}), 400
    state["nomination_order"] = order
    state["nomination_index"] = 0
    auto_save_draft()
    return safe_jsonify({"success": True, "nomination_order": order, "nomination_index": 0})


@app.route("/api/draft", methods=["POST"])
def api_draft():
    """Draft a player. Body: {player, manager, price, position}"""
    data = request.json
    player_name = data.get("player", "")
    manager_name = data.get("manager", "")
    price = data.get("price", 1)
    position = data.get("position", "")

    # Validate
    if not player_name or not manager_name:
        return safe_jsonify({"error": "Player and manager are required"}), 400

    # Check player exists and isn't drafted
    drafted_names = {p["player"] for p in state["draft_log"]}
    if player_name in drafted_names:
        return safe_jsonify({"error": f"{player_name} is already drafted"}), 400

    # Find player in projections (may be None for manual entries)
    player_data = None
    for p in state["player_projections"]:
        if p["player"] == player_name:
            player_data = p
            break

    # Find the current inflation-adjusted value for over/under calc
    adjusted_value = price  # default
    if player_data:
        inflation, _ = get_current_inflation()
        for ap in inflation["player_adjusted_prices"]:
            if ap["player"] == player_name:
                adjusted_value = ap["inflation_adjusted_value"]
                break

    # Add to draft log
    pick = {
        "pick_num": len(state["draft_log"]) + 1,
        "player": player_name,
        "position": position or (player_data.get("position_primary", "") if player_data else "UTIL"),
        "manager": manager_name,
        "price": price,
        "projected_value": player_data.get("projected_value", 0) if player_data else 0,
        "predicted_value": player_data.get("predicted_value", 0) if player_data else 0,
        "inflation_adjusted_value": adjusted_value,
        "over_under": round(price - (player_data.get("projected_value", 0) if player_data else 0), 1),
        "tier": player_data.get("tier", "") if player_data else "",
        "type": player_data.get("type", "") if player_data else "",
        "is_rookie": player_data.get("is_rookie", False) if player_data else False,
    }
    state["draft_log"].append(pick)
    auto_save_draft()

    # Advance nomination order (skip full rosters)
    advance_nomination(1)

    return safe_jsonify({"success": True, "pick": pick})


@app.route("/api/undraft", methods=["POST"])
def api_undraft():
    """Undo the last draft pick."""
    if not state["draft_log"]:
        return safe_jsonify({"error": "No picks to undo"}), 400

    removed = state["draft_log"].pop()
    auto_save_draft()

    # Step nomination order back (skip full rosters)
    advance_nomination(-1)

    return safe_jsonify({"success": True, "removed": removed})


@app.route("/api/delete_pick", methods=["POST"])
def api_delete_pick():
    """Delete a specific draft pick by player name.

    Body: {player, manager}
    Removes the pick from draft_log and renumbers remaining picks.
    The player returns to the available pool automatically (they're no longer in draft_log).
    """
    data = request.json
    player_name = data.get("player", "")
    manager_name = data.get("manager", "")

    if not player_name or not manager_name:
        return safe_jsonify({"error": "Player and manager are required"}), 400

    # Find and remove the pick
    removed = None
    for i, pick in enumerate(state["draft_log"]):
        if pick["player"] == player_name and pick["manager"] == manager_name:
            removed = state["draft_log"].pop(i)
            break

    if not removed:
        return safe_jsonify({"error": f"No draft pick found for {player_name} on {manager_name}"}), 404

    # Renumber remaining picks
    for j, pick in enumerate(state["draft_log"]):
        pick["pick_num"] = j + 1

    auto_save_draft()
    return safe_jsonify({"success": True, "removed": removed})


@app.route("/api/update_team", methods=["POST"])
def api_update_team():
    """Update a team's data (budget, keepers, etc.)"""
    data = request.json
    manager_name = data.get("manager", "")

    for team in state["league_state"]["teams"]:
        if team["manager"] == manager_name:
            if "total_budget" in data:
                team["total_budget"] = data["total_budget"]
            if "keepers" in data:
                team["keepers"] = data["keepers"]
                team["keeper_count"] = len(data["keepers"])
                team["keeper_cost"] = sum(k.get("price", 0) for k in data["keepers"])

            # Recalculate auction budget
            team["auction_budget"] = team["total_budget"] - team["keeper_cost"]

            # Save back to file
            save_data("league_state_2026.json", state["league_state"])
            return safe_jsonify({"success": True, "team": team})

    return safe_jsonify({"error": f"Manager '{manager_name}' not found"}), 404


@app.route("/api/update_player", methods=["POST"])
def api_update_player():
    """Update a player's projection data."""
    data = request.json
    player_name = data.get("player", "")

    for p in state["player_projections"]:
        if p["player"] == player_name:
            if "projected_value" in data:
                p["projected_value"] = data["projected_value"]
            if "tier" in data:
                p["tier"] = data["tier"]
            if "is_rookie" in data:
                p["is_rookie"] = data["is_rookie"]

            # Save back to file
            save_data(
                "player_projections_2026.json",
                {"_README": "Updated via app", "players": state["player_projections"]},
            )
            return safe_jsonify({"success": True, "player": p})

    return safe_jsonify({"error": f"Player '{player_name}' not found"}), 404


@app.route("/api/move_player", methods=["POST"])
def api_move_player():
    """Move a player to a different roster position.

    Body: {manager, player, new_position}
    Searches both keepers and draft_log for the player.
    """
    data = request.json
    manager_name = data.get("manager", "")
    player_name = data.get("player", "")
    new_position = data.get("new_position", "")

    if not manager_name or not player_name or not new_position:
        return safe_jsonify({"error": "Missing manager, player, or new_position"}), 400

    # ---- Check if the target position is full ----
    # Max slots per position on a 22-man roster
    POS_MAX = {
        'C': 1, '1B': 1, '2B': 1, 'SS': 1, '3B': 1,
        'CI': 1, 'MI': 1, 'OF': 5, 'UTIL': 1,
        'SP': 4, 'RP': 3, 'P': 2,
    }

    max_slots = POS_MAX.get(new_position, 1)

    # Count how many players this manager already has at new_position
    # (excluding the player being moved)
    count_at_pos = 0
    for pick in state["draft_log"]:
        if (pick.get("manager") == manager_name
                and pick.get("position") == new_position
                and pick.get("player") != player_name):
            count_at_pos += 1

    for team in state["league_state"]["teams"]:
        if team["manager"] == manager_name:
            for keeper in team.get("keepers", []):
                if (keeper.get("position") == new_position
                        and keeper.get("player") != player_name):
                    count_at_pos += 1

    if count_at_pos >= max_slots:
        return safe_jsonify({
            "error": f"{new_position} is full ({count_at_pos}/{max_slots}). Move the existing player out first."
        }), 400

    # Check draft log first
    for pick in state["draft_log"]:
        if pick.get("manager") == manager_name and pick.get("player") == player_name:
            old_pos = pick.get("position", "")
            pick["position"] = new_position
            auto_save_draft()
            return safe_jsonify({
                "success": True,
                "player": player_name,
                "old_position": old_pos,
                "new_position": new_position,
                "source": "draft_log",
            })

    # Check keepers
    for team in state["league_state"]["teams"]:
        if team["manager"] == manager_name:
            for keeper in team.get("keepers", []):
                if keeper.get("player") == player_name:
                    old_pos = keeper.get("position", "")
                    keeper["position"] = new_position
                    save_data("league_state_2026.json", state["league_state"])
                    return safe_jsonify({
                        "success": True,
                        "player": player_name,
                        "old_position": old_pos,
                        "new_position": new_position,
                        "source": "keeper",
                    })

    return safe_jsonify({"error": f"Player '{player_name}' not found for {manager_name}"}), 404


@app.route("/api/save_draft", methods=["POST"])
def api_save_draft():
    """Save the current draft state to a JSON file."""
    save_path = os.path.join(DATA_DIR, "draft_save.json")
    save_data("draft_save.json", {
        "draft_log": state["draft_log"],
        "mode": state["mode"],
        "draft_active": state["draft_active"],
    })
    return safe_jsonify({"success": True, "path": save_path})


@app.route("/api/download_draft")
def api_download_draft():
    """Download the current draft state as a JSON file for local backup."""
    backup = {
        "draft_log": state["draft_log"],
        "mode": state["mode"],
        "draft_active": state["draft_active"],
        "backup_picks": len(state["draft_log"]),
    }
    resp = Response(
        json.dumps(backup, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=draft_backup.json"},
    )
    return resp


@app.route("/api/upload_draft", methods=["POST"])
def api_upload_draft():
    """Restore draft state from an uploaded JSON backup file."""
    if "file" not in request.files:
        return safe_jsonify({"error": "No file uploaded"}), 400

    f = request.files["file"]
    try:
        saved = json.load(f)
    except Exception as e:
        return safe_jsonify({"error": f"Invalid JSON: {e}"}), 400

    state["draft_log"] = saved.get("draft_log", [])
    state["mode"] = saved.get("mode", "manual")
    state["draft_active"] = saved.get("draft_active", False)
    auto_save_draft()
    return safe_jsonify({"success": True, "picks_loaded": len(state["draft_log"])})


@app.route("/api/load_draft", methods=["POST"])
def api_load_draft():
    """Load a saved draft state."""
    save_path = os.path.join(DATA_DIR, "draft_save.json")
    if not os.path.exists(save_path):
        return safe_jsonify({"error": "No saved draft found"}), 404

    with open(save_path) as f:
        saved = json.load(f)

    state["draft_log"] = saved.get("draft_log", [])
    state["mode"] = saved.get("mode", "manual")
    state["draft_active"] = saved.get("draft_active", False)
    state["nomination_order"] = saved.get("nomination_order", [])
    state["nomination_index"] = saved.get("nomination_index", 0)
    return safe_jsonify({"success": True, "picks_loaded": len(state["draft_log"])})


@app.route("/api/reset_draft", methods=["POST"])
def api_reset_draft():
    """Reset the draft log."""
    state["draft_log"] = []
    return safe_jsonify({"success": True})


@app.route("/api/set_mode", methods=["POST"])
def api_set_mode():
    """Set the auction mode."""
    data = request.json
    mode = data.get("mode", "manual")
    if mode in ("manual", "interactive", "batch"):
        state["mode"] = mode
        return safe_jsonify({"success": True, "mode": mode})
    return safe_jsonify({"error": "Invalid mode"}), 400


@app.route("/api/toggle_draft", methods=["POST"])
def api_toggle_draft():
    """Toggle draft active/inactive. When inactive, board hides draft picks (sim mode)."""
    state["draft_active"] = not state["draft_active"]
    auto_save_draft()
    return safe_jsonify({
        "success": True,
        "draft_active": state["draft_active"],
    })


@app.route("/api/profiles")
def api_profiles():
    """Return analyzed manager profiles."""
    return safe_jsonify(state["manager_profiles_analyzed"])


@app.route("/api/inflation_history")
def api_inflation_history():
    """Return inflation multiplier at each pick for charting."""
    # Replay the draft to get inflation at each step
    history = []
    temp_log = []

    # Starting inflation (before any picks)
    inflation_start, _ = get_current_inflation()
    history.append({
        "pick": 0,
        "global": inflation_start["global_inflation"],
        "hitter": inflation_start["hitter_inflation"],
        "pitcher": inflation_start["pitcher_inflation"],
    })

    # Current state's inflation
    if state["draft_log"]:
        inflation_now, _ = get_current_inflation()
        history.append({
            "pick": len(state["draft_log"]),
            "global": inflation_now["global_inflation"],
            "hitter": inflation_now["hitter_inflation"],
            "pitcher": inflation_now["pitcher_inflation"],
        })

    return safe_jsonify(history)


# ============================================================
# Routes — AI Simulation Endpoints
# ============================================================

@app.route("/api/ai_picks", methods=["POST"])
def api_ai_picks():
    """
    Run N AI-controlled picks from the current draft state.
    Used for "AI, make the next X picks" in manual mode.
    Body: {num_picks: int}
    """
    data = request.json
    num_picks = data.get("num_picks", 5)
    num_picks = max(1, min(150, num_picks))  # Clamp 1-150

    try:
        new_picks = run_ai_picks(
            num_picks=num_picks,
            teams=state["league_state"].get("teams", []),
            players=state["player_projections"],
            profiles=state["manager_profiles_analyzed"],
            league_settings=state["league_settings"],
            existing_draft_log=state["draft_log"],
            human_manager=MY_MANAGER,
        )

        # Apply new picks to the real draft log
        for pick in new_picks:
            pick["pick_num"] = len(state["draft_log"]) + 1
            state["draft_log"].append(pick)

        return safe_jsonify({
            "success": True,
            "new_picks": new_picks,
            "total_picks": len(state["draft_log"]),
        })
    except Exception as e:
        return safe_jsonify({"error": str(e)}), 500


@app.route("/api/run_batch", methods=["POST"])
def api_run_batch():
    """
    Run N complete auction simulations in batch mode.
    Body: {num_simulations: int}
    Returns aggregated statistics.
    """
    data = request.json
    num_sims = data.get("num_simulations", 25)
    num_sims = max(1, min(200, num_sims))  # Clamp 1-200

    # Optional forced draft plan — lock in specific players at specific prices
    forced_picks = data.get("forced_picks", None)
    # Each entry: {"player": "Name", "price": 25}
    # Manager defaults to MY_MANAGER
    if forced_picks:
        for fp in forced_picks:
            if "manager" not in fp:
                fp["manager"] = MY_MANAGER

    # Optional: anchor AI bids to projected (stat) value instead of predicted (market) value
    use_projected_anchor = data.get("use_projected_anchor", False)

    try:
        results = run_batch_simulations(
            teams=state["league_state"].get("teams", []),
            players=state["player_projections"],
            profiles=state["manager_profiles_analyzed"],
            league_settings=state["league_settings"],
            num_simulations=num_sims,
            my_manager=MY_MANAGER,
            stat_projections=state["stat_projections"],
            forced_picks=forced_picks,
            use_projected_anchor=use_projected_anchor,
        )

        # Store for standings page
        state["last_batch_results"] = results

        return safe_jsonify({
            "success": True,
            "results": results,
        })
    except Exception as e:
        import traceback
        return safe_jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@app.route("/api/interactive_step", methods=["POST"])
def api_interactive_step():
    """
    Run one step of interactive simulation: AI nominates a player,
    all AIs bid, human can override their bid.
    Body: {human_bid: int or null} — null means let AI decide for human too
    """
    data = request.json
    human_bid = data.get("human_bid", None)

    try:
        # Run a single AI pick, skipping human manager
        new_picks = run_ai_picks(
            num_picks=1,
            teams=state["league_state"].get("teams", []),
            players=state["player_projections"],
            profiles=state["manager_profiles_analyzed"],
            league_settings=state["league_settings"],
            existing_draft_log=state["draft_log"],
            human_manager=None,  # Everyone is AI in each step
        )

        # Apply the pick
        for pick in new_picks:
            pick["pick_num"] = len(state["draft_log"]) + 1
            state["draft_log"].append(pick)

        return safe_jsonify({
            "success": True,
            "new_pick": new_picks[0] if new_picks else None,
            "total_picks": len(state["draft_log"]),
        })
    except Exception as e:
        return safe_jsonify({"error": str(e)}), 500


@app.route("/api/run_batch_throwback", methods=["POST"])
def api_run_batch_throwback():
    """
    Run batch simulations with specified keepers thrown back into the pool.
    Body: {keepers_to_throw_back: [player_name, ...], num_simulations: int}
    Returns batch results with throwback metadata.
    """
    data = request.json
    keepers = data.get("keepers_to_throw_back", [])
    num_sims = data.get("num_simulations", 25)
    num_sims = max(1, min(200, num_sims))

    if not keepers:
        return safe_jsonify({"error": "No keepers specified to throw back"}), 400

    # Optional forced draft plan and anchor toggle (shared with regular batch)
    forced_picks = data.get("forced_picks", None)
    if forced_picks:
        for fp in forced_picks:
            if "manager" not in fp:
                fp["manager"] = MY_MANAGER
    use_projected_anchor = data.get("use_projected_anchor", False)

    try:
        results = run_batch_throwback(
            teams=state["league_state"].get("teams", []),
            players=state["player_projections"],
            profiles=state["manager_profiles_analyzed"],
            league_settings=state["league_settings"],
            keepers_to_throw_back=keepers,
            num_simulations=num_sims,
            my_manager=MY_MANAGER,
            stat_projections=state["stat_projections"],
            forced_picks=forced_picks,
            use_projected_anchor=use_projected_anchor,
        )

        return safe_jsonify({
            "success": True,
            "results": results,
        })
    except Exception as e:
        import traceback
        return safe_jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


# ============================================================
# Standings Routes
# ============================================================

@app.route("/standings")
def standings_page():
    """Serve the projected standings page."""
    return render_template("standings.html")


@app.route("/api/standings")
def api_standings():
    """
    Return projected power rankings based on current draft state.
    Teams are ranked 1-12 in each of 10 categories, with total
    rank points determining overall standings.
    """
    try:
        standings = get_standings(
            teams=state["league_state"].get("teams", []),
            draft_log=state["draft_log"],
            stat_projections=state["stat_projections"],
            my_manager=MY_MANAGER,
        )
        standings["source"] = "current_draft"
        standings["picks_made"] = len(state["draft_log"])
        return safe_jsonify(standings)
    except Exception as e:
        import traceback
        return safe_jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@app.route("/api/standings/batch")
def api_standings_batch():
    """
    Return projected standings based on the last batch simulation.
    Uses the most common team composition from batch results.
    """
    try:
        if not state.get("last_batch_results"):
            return safe_jsonify({
                "error": "No batch simulation has been run yet.",
                "standings": [],
                "has_stats": False,
            })

        # Build a synthetic draft log from batch sim averages
        # For each team, use the players they drafted most frequently
        batch = state["last_batch_results"]
        synthetic_draft_log = []

        # The batch results have my_team_stats for Clay, but we need all teams.
        # Use the last simulation's draft_log if available, or reconstruct from player_stats
        # For simplicity, use the player_stats averages: assign each player to their
        # most frequent buyer at their average price
        if "player_stats" in batch:
            for ps in batch["player_stats"]:
                # Each player_stat may have a most_common_buyer field
                buyer = ps.get("most_common_buyer", "")
                if buyer:
                    synthetic_draft_log.append({
                        "player": ps["player"],
                        "manager": buyer,
                        "price": ps.get("avg_price", 1),
                        "position": ps.get("position", ""),
                    })

        standings = get_standings(
            teams=state["league_state"].get("teams", []),
            draft_log=synthetic_draft_log,
            stat_projections=state["stat_projections"],
            my_manager=MY_MANAGER,
        )
        standings["source"] = "batch_sim"
        standings["num_simulations"] = batch.get("simulation_count", 0)
        return safe_jsonify(standings)
    except Exception as e:
        import traceback
        return safe_jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


# ============================================================
# Startup
# ============================================================
# Load data at module level so both gunicorn and direct run work
load_data()

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  IPL AUCTION CALCULATOR 2026")
    print("  http://localhost:5050")
    print("=" * 60 + "\n")
    app.run(debug=True, port=5050)
