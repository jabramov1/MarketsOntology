"""Game, Drive, and Play loaders."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pandas as pd

from db import Neo4jConnection
from util import find_col, safe_int, safe_str, dt_parse, approx_play_timestamp, chunked, now_utc_iso


def load_games(db: Neo4jConnection, sched: pd.DataFrame, year: int) -> None:
    """Load game nodes and relationships to teams/season."""
    if sched.empty:
        print("No schedule data provided.")
        return

    game_id_col = find_col(sched, "game_id", "gsis_id", "gameid", "id")
    week_col = find_col(sched, "week", "game_week")
    st_col = find_col(sched, "game_datetime", "start_time", "gameday", "game_date")
    home_col = find_col(sched, "home_team", "home_team_abbr", "home_team_x")
    away_col = find_col(sched, "away_team", "away_team_abbr", "away_team_x")
    home_score_col = find_col(sched, "home_score", "home_points", "score_home")
    away_score_col = find_col(sched, "away_score", "away_points", "score_away")

    if home_col is None or away_col is None:
        raise ValueError("Schedule dataframe missing home_team/away_team columns.")

    season_id = f"NFL_{year}"
    rows = []
    ingested_at = now_utc_iso()

    for _, r in sched.iterrows():
        gid_raw = safe_str(r.get(game_id_col))
        home = safe_str(r.get(home_col))
        away = safe_str(r.get(away_col))
        if not home or not away:
            continue

        wk = safe_int(r.get(week_col))
        wk_str = f"WK{wk}" if wk is not None else "WKU"
        game_node_id = f"NFL_{year}_REG_{wk_str}_{away}_{home}"

        start_time_iso = dt_parse(r.get(st_col))
        home_score = safe_int(r.get(home_score_col))
        away_score = safe_int(r.get(away_score_col))

        rows.append({
            "id": game_node_id,
            "game_id": gid_raw,
            "week": wk,
            "season_type": "REG",
            "start_time": start_time_iso,
            "end_time": None,
            "stadium": r.get("stadium") or r.get("venue"),
            "home_score": home_score,
            "away_score": away_score,
            "status": "FINAL" if (home_score is not None and away_score is not None) else "SCHEDULED",
            "home_abbr": home,
            "away_abbr": away,
            "source": "nfl_data_py",
            "source_id": gid_raw,
            "ingested_at": ingested_at,
            "schema_version": "v1.0",
        })

    db.run_write(
        """
        UNWIND $rows AS row
        MERGE (g:Game {id: row.id})
        SET g.game_id = row.game_id,
            g.week = row.week,
            g.season_type = row.season_type,
            g.start_time = CASE WHEN row.start_time IS NULL THEN NULL ELSE datetime(row.start_time) END,
            g.end_time = CASE WHEN row.end_time IS NULL THEN NULL ELSE datetime(row.end_time) END,
            g.stadium = row.stadium,
            g.home_score = row.home_score,
            g.away_score = row.away_score,
            g.status = row.status,
            g.source = row.source,
            g.source_id = row.source_id,
            g.ingested_at = datetime(row.ingested_at),
            g.schema_version = row.schema_version
        WITH g, row
        MATCH (s:Season {id: $season_id})
        MERGE (g)-[:PART_OF_SEASON]->(s)
        WITH g, row
        MATCH (home:Team {id: 'NFL_' + row.home_abbr})
        MATCH (away:Team {id: 'NFL_' + row.away_abbr})
        MERGE (g)-[:HOME_TEAM]->(home)
        MERGE (g)-[:AWAY_TEAM]->(away)
        """,
        {"rows": rows, "season_id": season_id},
    )
    print(f"Loaded {len(rows)} games")


def load_drives_and_plays(db: Neo4jConnection, pbp: pd.DataFrame, year: int, max_plays: int) -> None:
    """Load drive and play nodes from play-by-play data."""
    if pbp.empty:
        print("No play-by-play data provided.")
        return

    # Sample if needed
    if max_plays > 0 and len(pbp) > max_plays:
        pbp = pbp.sample(max_plays, random_state=42).reset_index(drop=True)

    # Build game start map for timestamp approximation
    game_times = db.run(
        """
        MATCH (g:Game) WHERE g.start_time IS NOT NULL
        RETURN g.game_id AS game_id, g.id AS node_id, toString(g.start_time) AS start_time
        """
    )
    game_start_by_ext: Dict[str, Tuple[str, str]] = {}
    for r in game_times:
        if r.get("game_id"):
            game_start_by_ext[str(r["game_id"])] = (str(r["node_id"]), str(r["start_time"]))

    drive_rows: Dict[Tuple[str, int], Dict[str, Any]] = {}
    play_rows: List[Dict[str, Any]] = []
    ingested_at = now_utc_iso()

    for _, r in pbp.iterrows():
        ext_gid = safe_str(r.get("game_id"))
        if not ext_gid or ext_gid not in game_start_by_ext:
            continue

        game_node_id, game_start_iso = game_start_by_ext[ext_gid]
        drive_no = safe_int(r.get("drive"))
        if drive_no is None:
            continue

        dkey = (game_node_id, drive_no)
        if dkey not in drive_rows:
            drive_id = f"{game_node_id}_D{drive_no}"
            drive_rows[dkey] = {
                "id": drive_id,
                "game_node_id": game_node_id,
                "drive_number": drive_no,
                "start_time": None,
                "end_time": None,
                "result": None,
                "plays_count": 0,
                "yards_gained": 0,
                "source": "nfl_data_py",
                "source_id": drive_id,
                "ingested_at": ingested_at,
                "schema_version": "v1.0",
            }

        play_id = safe_int(r.get("play_id"))
        if play_id is None:
            continue

        ts = approx_play_timestamp(game_start_iso, r.get("qtr"), r.get("time"))
        pid = f"{game_node_id}_P{play_id}"

        is_td = r.get("touchdown") == 1 if "touchdown" in pbp.columns else False
        is_fg_made = False
        if "field_goal_result" in pbp.columns:
            fg = r.get("field_goal_result")
            is_fg_made = isinstance(fg, str) and fg.lower() == "made"

        is_scoring = is_td or is_fg_made
        is_turnover = (r.get("interception") == 1 or r.get("fumble_lost") == 1) if "interception" in pbp.columns else None

        play_rows.append({
            "id": pid,
            "game_node_id": game_node_id,
            "drive_number": drive_no,
            "play_id": play_id,
            "play_type": r.get("play_type"),
            "quarter": safe_int(r.get("qtr")),
            "time": r.get("time"),
            "down": safe_int(r.get("down")),
            "yards_to_go": safe_int(r.get("ydstogo")),
            "yards_gained": safe_int(r.get("yards_gained")),
            "description": r.get("desc"),
            "timestamp": ts,
            "is_scoring_play": is_scoring,
            "is_turnover": is_turnover,
            "source": "nfl_data_py",
            "source_id": pid,
            "ingested_at": ingested_at,
            "schema_version": "v1.0",
        })

        # Update drive aggregates (track earliest/latest play timestamps)
        d = drive_rows[dkey]
        d["plays_count"] += 1
        if is_td:
            d["result"] = "TOUCHDOWN"
        elif is_fg_made and d.get("result") is None:
            d["result"] = "FIELD_GOAL"
        yg = safe_int(r.get("yards_gained"))
        if yg is not None:
            d["yards_gained"] += yg
        if ts:
            d["start_time"] = min(ts, d["start_time"]) if d["start_time"] else ts
            d["end_time"] = max(ts, d["end_time"]) if d["end_time"] else ts

    drive_list = list(drive_rows.values())

    # Upsert drives
    db.run_write(
        """
        UNWIND $rows AS row
        MERGE (d:Drive {id: row.id})
        SET d.drive_number = row.drive_number,
            d.start_time = CASE WHEN row.start_time IS NULL THEN NULL ELSE datetime(row.start_time) END,
            d.end_time = CASE WHEN row.end_time IS NULL THEN NULL ELSE datetime(row.end_time) END,
            d.result = row.result,
            d.plays_count = row.plays_count,
            d.yards_gained = row.yards_gained,
            d.source = row.source,
            d.source_id = row.source_id,
            d.ingested_at = datetime(row.ingested_at),
            d.schema_version = row.schema_version
        WITH d, row
        MATCH (g:Game {id: row.game_node_id})
        MERGE (g)-[:HAS_DRIVE]->(d)
        """,
        {"rows": drive_list},
    )
    print(f"Loaded {len(drive_list)} drives")

    # Upsert plays in batches
    cypher_plays = """
    UNWIND $rows AS row
    MERGE (p:Play {id: row.id})
    SET p.play_id = row.play_id,
        p.play_type = row.play_type,
        p.quarter = row.quarter,
        p.time = row.time,
        p.down = row.down,
        p.yards_to_go = row.yards_to_go,
        p.yards_gained = row.yards_gained,
        p.description = row.description,
        p.timestamp = CASE WHEN row.timestamp IS NULL THEN NULL ELSE datetime(row.timestamp) END,
        p.is_scoring_play = row.is_scoring_play,
        p.is_turnover = row.is_turnover,
        p.source = row.source,
        p.source_id = row.source_id,
        p.ingested_at = datetime(row.ingested_at),
        p.schema_version = row.schema_version
    WITH p, row
    MATCH (g:Game {id: row.game_node_id})
    MATCH (d:Drive {id: g.id + '_D' + toString(row.drive_number)})
    MERGE (d)-[:HAS_PLAY {sequence: row.play_id}]->(p)
    """
    for batch in chunked(play_rows, 2000):
        db.run_write(cypher_plays, {"rows": batch})
    print(f"Loaded {len(play_rows)} plays (batched)")


def load_player_participation(db: Neo4jConnection, pbp: pd.DataFrame, year: int, max_plays: int) -> None:
    """Load PARTICIPATED_IN relationships between players and plays."""
    if pbp.empty:
        print("No play-by-play data provided.")
        return

    if max_plays > 0 and len(pbp) > max_plays:
        pbp = pbp.sample(max_plays, random_state=42).reset_index(drop=True)

    # Map player ID columns to roles
    player_roles = [
        ("passer_player_id", "QB"),
        ("rusher_player_id", "RB"),
        ("receiver_player_id", "WR"),
        ("kicker_player_id", "K"),
        ("punter_player_id", "P"),
        ("kickoff_returner_player_id", "KR"),
        ("punt_returner_player_id", "PR"),
        ("interception_player_id", "DB"),
    ]

    game_times = db.run(
        """
        MATCH (g:Game) WHERE g.start_time IS NOT NULL
        RETURN g.game_id AS game_id, g.id AS node_id
        """
    )
    game_map = {}
    for r in game_times:
        game_id = r.get("game_id")
        if game_id:
            game_map[str(game_id)] = str(r["node_id"])

    participation_rows = []

    for _, r in pbp.iterrows():
        ext_gid = safe_str(r.get("game_id"))
        if not ext_gid or ext_gid not in game_map:
            continue

        game_node_id = game_map[ext_gid]
        play_id = safe_int(r.get("play_id"))
        if play_id is None:
            continue

        play_node_id = f"{game_node_id}_P{play_id}"

        for col, role in player_roles:
            player_id = safe_str(r.get(col))
            if not player_id:
                continue

            yards = safe_int(r.get("yards_gained"))
            participation_rows.append({
                "play_id": play_node_id,
                "player_id": player_id,
                "role": role,
                "yards": yards,
            })

    cypher = """
    UNWIND $rows AS row
    MATCH (p:Play {id: row.play_id})
    MATCH (player:Player {gsis_id: row.player_id})
    MERGE (player)-[part:PARTICIPATED_IN]->(p)
    SET part.role = row.role,
        part.yards = row.yards
    """
    for batch in chunked(participation_rows, 2000):
        db.run_write(cypher, {"rows": batch})
    print(f"Loaded {len(participation_rows)} player participation relationships")


def load_player_game_stats(db: Neo4jConnection, year: int) -> None:
    """Aggregate player participation into PLAYED_IN relationships."""
    cypher = """
    MATCH (player:Player)-[part:PARTICIPATED_IN]->(play:Play)
    MATCH (play)<-[:HAS_PLAY]-(:Drive)<-[:HAS_DRIVE]-(game:Game)
    WITH player, game,
         count(part) AS plays,
         sum(COALESCE(part.yards, 0)) AS total_yards
    MERGE (player)-[played:PLAYED_IN]->(game)
    SET played.plays = plays,
        played.yards = total_yards
    """
    db.run_write(cypher)
    result = db.run("MATCH ()-[r:PLAYED_IN]->() RETURN count(r) AS cnt")
    count = result[0]["cnt"] if result else 0
    print(f"Created {count} PLAYED_IN relationships")
