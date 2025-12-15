"""News and Injury loaders."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import hashlib

import pandas as pd

from db import Neo4jConnection
from util import find_col, safe_str, dt_parse, now_utc_iso


def _stable_injury_date(year: int, player_id: str | None) -> str:
    """Deterministic fallback injury date within the NFL season window."""
    key = f"{year}|{player_id or 'UNKNOWN'}"
    day_offset = int(hashlib.md5(key.encode("utf-8")).hexdigest()[:8], 16) % 140
    base = datetime(year, 9, 2, 12, tzinfo=timezone.utc)  # Week 1-ish Monday noon UTC
    return (base + timedelta(days=day_offset)).isoformat()


def _week_aligned_injury_date(year: int, week: int | None, player_id: str | None = None) -> str:
    """
    Fallback injury date that stays inside the season window and occurs before weekly games.
    Anchored to the Monday of Week 1 (early September) at noon UTC to keep it before kickoffs.
    """
    try:
        w = int(week)
    except (TypeError, ValueError):
        return _stable_injury_date(year, player_id)

    # Keep week bounds reasonable (regular season + playoffs)
    w = max(1, min(w, 22))
    week1_monday = datetime(year, 9, 2, 12, tzinfo=timezone.utc)
    return (week1_monday + timedelta(days=(w - 1) * 7)).isoformat()

# Confidence scores for entity linking (0-1 scale)
CONFIDENCE_GAME_REF = 0.7   # News explicitly includes game_id
CONFIDENCE_TEAM_REF = 0.6   # Team abbreviation appears in headline/data
CONFIDENCE_PLAYER_REF = 0.6 # Player ID appears in headline/data


def load_injuries(db: Neo4jConnection, injuries: pd.DataFrame, year: int) -> None:
    """Load injury events and link to players."""
    if injuries.empty:
        print("No injuries loaded.")
        return

    pid_col = find_col(injuries, "player_id", "gsis_id")
    status_col = find_col(injuries, "report_status", "status")
    part_col = find_col(
        injuries,
        "injury",
        "body_part",
        "injury_type",
        "report_primary_injury",
        "practice_primary_injury",
    )
    date_col = find_col(injuries, "report_date", "date", "date_modified")
    week_col = find_col(injuries, "week")

    if pid_col is None:
        print("Injuries dataframe missing player_id; skipping injuries.")
        return

    rows = []
    rels = []
    ingested_at = now_utc_iso()

    for _, r in injuries.iterrows():
        pid = safe_str(r.get(pid_col))
        if not pid:
            continue

        raw_date = r.get(date_col) if date_col else None
        week_val = r.get(week_col) if week_col else None

        # Check if we used fallback date
        parsed_date = dt_parse(raw_date)
        if parsed_date:
            reported_at = parsed_date
            is_synthetic = False
            synthetic_reason = None
        else:
            reported_at = _week_aligned_injury_date(year, week_val, pid)
            is_synthetic = True
            synthetic_reason = "fallback_injury_date"

        date_key = safe_str(reported_at)
        iid = f"INJ_{year}_{pid}_{date_key}"

        rows.append({
            "id": iid,
            "injury_type": r.get(status_col),
            "body_part": r.get(part_col),
            "reported_at": reported_at,
            "source": "nfl_data_py",
            "source_id": iid,
            "ingested_at": ingested_at,
            "schema_version": "v1.0",
            "synthetic": is_synthetic,
            "synthetic_reason": synthetic_reason,
        })
        rels.append({
            "injury_id": iid,
            "player_id": f"NFL_P_{pid}",
        })

    db.run_write(
        """
        UNWIND $rows AS row
        MERGE (i:InjuryEvent {id: row.id})
        SET i.injury_type = row.injury_type,
            i.body_part = row.body_part,
            i.reported_at = datetime(row.reported_at),
            i.source = row.source,
            i.source_id = row.source_id,
            i.ingested_at = datetime(row.ingested_at),
            i.schema_version = row.schema_version,
            i.synthetic = row.synthetic,
            i.synthetic_reason = row.synthetic_reason
        """,
        {"rows": rows},
    )

    db.run_write(
        """
        UNWIND $rels AS rel
        MATCH (i:InjuryEvent {id: rel.injury_id})
        MATCH (p:Player {id: rel.player_id})
        MERGE (i)-[:AFFECTS]->(p)
        """,
        {"rels": rels},
    )

    print(f"Loaded injuries={len(rows)}")


def link_injuries_to_games(db: Neo4jConnection) -> None:
    """Create REPORTED_BEFORE relationships from injuries to the next game."""
    print("Linking injuries to upcoming games...")
    
    # Simplified query: Just link injury to player's team's next game
    result = db.run_write_returning(
        """
        MATCH (i:InjuryEvent)-[:AFFECTS]->(p:Player)-[:PLAYS_FOR]->(t:Team)
        MATCH (g:Game)-[:HOME_TEAM|AWAY_TEAM]->(t)
        WHERE i.reported_at < g.start_time
        
        // Find the EARLIEST game after the injury for each injury
        WITH i, g
        ORDER BY g.start_time
        WITH i, collect(g)[0] AS next_game
        WHERE next_game IS NOT NULL
        
        // Calculate days before
        WITH i, next_game, duration.between(i.reported_at, next_game.start_time).days AS days_before
        
        // Create relationship to next game only
        MERGE (i)-[r:REPORTED_BEFORE]->(next_game)
        SET r.days_before = days_before
        RETURN count(r) AS links_created
        """,
        {}
    )
    
    count = result[0]["links_created"] if result else 0
    print(f"  Created {count} REPORTED_BEFORE relationships")


def load_news(db: Neo4jConnection, news: pd.DataFrame) -> None:
    """Load news items and link to games/teams/players."""
    if news.empty:
        print("No news loaded.")
        return

    rows = []
    ingested_at = now_utc_iso()

    for _, r in news.iterrows():
        rows.append({
            "id": r.get("id"),
            "headline": r.get("headline"),
            "summary": r.get("summary"),
            "source": r.get("source"),
            "url": r.get("url"),
            "published_at": r.get("published_at"),
            "author": r.get("author"),
            "sentiment_score": r.get("sentiment_score"),
            "ref_game_id": r.get("ref_game_id"),
            "ref_team_abbr": r.get("ref_team_abbr"),
            "ref_player_id": r.get("ref_player_id"),
            "ref_market_id": r.get("ref_market_id"),
            "source_id": r.get("id"),
            "ingested_at": ingested_at,
            "schema_version": "v1.0",
            "synthetic": r.get("synthetic", False),
            "synthetic_reason": r.get("synthetic_reason"),
        })

    db.run_write(
        """
        UNWIND $rows AS row
        MERGE (n:NewsItem {id: row.id})
        SET n.headline = row.headline,
            n.summary = row.summary,
            n.source = row.source,
            n.url = row.url,
            n.published_at = datetime(row.published_at),
            n.author = row.author,
            n.sentiment_score = row.sentiment_score,
            n.source_id = row.source_id,
            n.ingested_at = datetime(row.ingested_at),
            n.schema_version = row.schema_version,
            n.synthetic = row.synthetic,
            n.synthetic_reason = row.synthetic_reason
        """,
        {"rows": rows},
    )

    # Link to games
    db.run_write(
        """
        UNWIND $rows AS row
        WITH row WHERE row.ref_game_id IS NOT NULL
        MATCH (n:NewsItem {id: row.id})
        MATCH (g:Game {game_id: row.ref_game_id})
        MERGE (n)-[:REFERS_TO_GAME {confidence: $conf}]->(g)
        """,
        {"rows": rows, "conf": CONFIDENCE_GAME_REF},
    )

    # Link to teams
    db.run_write(
        """
        UNWIND $rows AS row
        WITH row WHERE row.ref_team_abbr IS NOT NULL
        MATCH (n:NewsItem {id: row.id})
        MATCH (t:Team {id: 'NFL_' + row.ref_team_abbr})
        MERGE (n)-[:REFERS_TO_TEAM {confidence: $conf}]->(t)
        """,
        {"rows": rows, "conf": CONFIDENCE_TEAM_REF},
    )

    # Link to players
    db.run_write(
        """
        UNWIND $rows AS row
        WITH row WHERE row.ref_player_id IS NOT NULL
        MATCH (n:NewsItem {id: row.id})
        MATCH (p:Player {id: 'NFL_P_' + row.ref_player_id})
        MERGE (n)-[:REFERS_TO_PLAYER {confidence: $conf}]->(p)
        """,
        {"rows": rows, "conf": CONFIDENCE_PLAYER_REF},
    )

    # Link to markets
    db.run_write(
        """
        UNWIND $rows AS row
        WITH row WHERE row.ref_market_id IS NOT NULL
        MATCH (n:NewsItem {id: row.id})
        MATCH (m:Market {id: row.ref_market_id})
        MERGE (n)-[:REFERS_TO_MARKET {confidence: 0.8}]->(m)
        """,
        {"rows": rows},
    )

    print(f"Loaded news={len(rows)}")
