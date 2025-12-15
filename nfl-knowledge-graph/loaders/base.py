"""Base entity loaders: Season, Teams, Players."""
from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

from db import Neo4jConnection
from util import find_col, safe_int, safe_str, now_utc_iso


def _to_neo4j_date_str(x: object) -> Optional[str]:
    """Convert birth_date to 'YYYY-MM-DD' for Neo4j. Handles strings, Timestamps, NaN."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None

    # String: extract date portion or parse
    if isinstance(x, str):
        s = x.strip()
        if not s:
            return None
        # Fast path: "1982-01-22" or "1982-01-22 00:00:00"
        if len(s) >= 10 and s[4] == "-" and s[7] == "-":
            return s[:10]

    # Let pandas handle everything else
    dt = pd.to_datetime(x, errors="coerce", utc=True)
    return dt.date().isoformat() if pd.notna(dt) else None


def upsert_season(db: Neo4jConnection, year: int) -> None:
    """Create or update a Season node."""
    season_id = f"NFL_{year}"
    start_date = f"{year}-09-01"
    end_date = f"{year + 1}-02-15"
    ingested_at = now_utc_iso()

    db.run_write(
        """
        MERGE (s:Season {id: $id})
        SET s.year = $year,
            s.start_date = date($start_date),
            s.end_date = date($end_date),
            s.season_type = 'REG+POST',
            s.source = $source,
            s.source_id = $source_id,
            s.ingested_at = datetime($ingested_at),
            s.schema_version = $schema_version
        """,
        {
            "id": season_id,
            "year": year,
            "start_date": start_date,
            "end_date": end_date,
            "source": "nfl_data_py",
            "source_id": str(year),
            "ingested_at": ingested_at,
            "schema_version": "v1.0",
        },
    )
    print(f"Upserted Season {season_id}")


def load_teams(db: Neo4jConnection, teams: pd.DataFrame) -> Dict[str, str]:
    """Load team nodes and return mapping from team name variants to abbreviation."""
    if teams.empty:
        print("No teams data provided.")
        return {}

    abbr_col = find_col(teams, "team_abbr", "abbr")
    name_col = find_col(teams, "team_name", "name")
    city_col = find_col(teams, "team_city", "city")

    mapping: Dict[str, str] = {}
    rows = []
    ingested_at = now_utc_iso()

    for _, r in teams.iterrows():
        abbr = safe_str(r.get(abbr_col))
        if not abbr:
            continue
        name = safe_str(r.get(name_col)) or ""
        city = safe_str(r.get(city_col)) or ""
        full = f"{city} {name}".strip()

        rows.append({
            "id": f"NFL_{abbr}",
            "abbreviation": abbr,
            "name": name,
            "full_name": full,
            "conference": r.get("conference"),
            "division": r.get("division"),
            "primary_color": r.get("team_color"),
            "secondary_color": r.get("team_color2"),
            "source": "nfl_data_py",
            "source_id": abbr,
            "ingested_at": ingested_at,
            "schema_version": "v1.0",
        })

        # Build mapping keys
        for k in {abbr, name, city, full}:
            if k:
                mapping[k.lower()] = abbr

    db.run_write(
        """
        UNWIND $rows AS row
        MERGE (t:Team {id: row.id})
        SET t.abbreviation = row.abbreviation,
            t.name = row.name,
            t.full_name = row.full_name,
            t.conference = row.conference,
            t.division = row.division,
            t.primary_color = row.primary_color,
            t.secondary_color = row.secondary_color,
            t.source = row.source,
            t.source_id = row.source_id,
            t.ingested_at = datetime(row.ingested_at),
            t.schema_version = row.schema_version
        """,
        {"rows": rows},
    )
    print(f"Loaded {len(rows)} teams")
    return mapping


def load_players(db: Neo4jConnection, rosters: pd.DataFrame, year: int) -> None:
    """Load player nodes and PLAYS_FOR relationships."""
    if rosters.empty:
        print("No roster data provided.")
        return

    gsis = find_col(rosters, "gsis_id", "player_id")
    name = find_col(rosters, "player_name", "full_name", "name")
    pos = find_col(rosters, "position", "pos")
    team = find_col(rosters, "team", "team_abbr", "club_code")
    jersey = find_col(rosters, "jersey_number", "jersey")

    if gsis is None or name is None:
        raise ValueError("Roster dataframe missing required columns (gsis_id/player_id and player_name).")

    start_date = f"{year}-09-01"
    rows = []
    rels = []
    ingested_at = now_utc_iso()

    for _, r in rosters.iterrows():
        pid = safe_str(r.get(gsis))
        if not pid:
            continue
        player_node_id = f"NFL_P_{pid}"
        pname = safe_str(r.get(name))
        if not pname:
            continue

        position = safe_str(r.get(pos)) if pos else None
        college = safe_str(r.get("college"))
        jersey_number = safe_int(r.get(jersey)) if jersey else None
        # Short, stable description intended for display and (optional) embeddings.
        desc_parts = []
        if position:
            desc_parts.append(position)
        if college:
            desc_parts.append(f"College: {college}")
        if jersey_number is not None:
            desc_parts.append(f"Jersey: {jersey_number}")
        description = " • ".join(desc_parts) if desc_parts else None

        rows.append({
            "id": player_node_id,
            "gsis_id": pid,
            "name": pname,
            "position": position,
            "jersey_number": jersey_number,
            "college": college,
            "birth_date": _to_neo4j_date_str(r.get("birth_date")),
            "description": description,
            "source": "nfl_data_py",
            "source_id": pid,
            "ingested_at": ingested_at,
            "schema_version": "v1.0",
        })

        tabbr = safe_str(r.get(team))
        if tabbr:
            rels.append({
                "player_id": player_node_id,
                "team_id": f"NFL_{tabbr}",
                "valid_from": start_date,
                "valid_to": None,
                "valid_to_or_max": "9999-12-31",
                "jersey_number": jersey_number,
            })

    # Upsert players
    db.run_write(
        """
        UNWIND $rows AS row
        MERGE (p:Player {id: row.id})
        SET p.gsis_id = row.gsis_id,
            p.name = row.name,
            p.position = row.position,
            p.jersey_number = row.jersey_number,
            p.college = row.college,
            p.birth_date = CASE WHEN row.birth_date IS NULL THEN NULL ELSE date(row.birth_date) END,
            p.description = row.description,
            p.source = row.source,
            p.source_id = row.source_id,
            p.ingested_at = datetime(row.ingested_at),
            p.schema_version = row.schema_version
        """,
        {"rows": rows},
    )
    print(f"Loaded {len(rows)} players")

    # Upsert PLAYS_FOR relationships
    db.run_write(
        """
        UNWIND $rels AS rel
        MATCH (p:Player {id: rel.player_id})
        MATCH (t:Team {id: rel.team_id})
        MERGE (p)-[r:PLAYS_FOR]->(t)
        SET r.valid_from = date(rel.valid_from),
            r.valid_to = CASE WHEN rel.valid_to IS NULL THEN NULL ELSE date(rel.valid_to) END,
            r.valid_to_or_max = date(rel.valid_to_or_max),
            r.jersey_number = rel.jersey_number
        """,
        {"rels": rels},
    )
    print(f"Loaded {len(rels)} PLAYS_FOR relationships")
