"""Market, BettingLine, and OddsMovement loaders."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from db import Neo4jConnection
from util import safe_float, american_to_implied_prob, chunked, now_utc_iso

SYNTH_SPREAD_NOISE = 0.5
SYNTH_TOTAL_NOISE = 1.0


def _offset_iso(iso_str: str, hours: int) -> str:
    """Offset an ISO timestamp by N hours (negative = before)."""
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return (dt + timedelta(hours=hours)).isoformat()


def _norm_team(x: Any, team_map: Dict[str, str]) -> Optional[str]:
    """Normalize team name to abbreviation using team map."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    s = str(x).strip().lower()
    return team_map.get(s)


def load_odds_and_markets(
    db: Neo4jConnection,
    year: int,
    team_map: Dict[str, str],
    odds_csv_path: Path,
    synth_moves: bool,
    venue_id: str = "KAGGLE",
) -> None:
    """Load markets, betting lines, odds movements, and resolutions."""
    if not odds_csv_path.exists():
        print(f"Odds CSV file not found at {odds_csv_path}. Skipping odds/markets.")
        return

    odds = pd.read_csv(odds_csv_path)
    ingested_at = now_utc_iso()

    # Create venue
    db.run_write(
        """
        MERGE (v:Venue {id: $id})
        SET v.name = $name, v.venue_type = 'SPORTSBOOK'
        """,
        {"id": venue_id, "name": venue_id.title()},
    )

    # Build game lookup
    games = db.run(
        """
        MATCH (g:Game)-[:HOME_TEAM]->(h:Team)
        MATCH (g)-[:AWAY_TEAM]->(a:Team)
        RETURN g.id AS gid, g.week AS week, h.abbreviation AS home, 
               a.abbreviation AS away, toString(g.start_time) AS start_time
        """
    )
    game_lookup = {
        (int(r["week"]) if r.get("week") is not None else None, r["home"], r["away"]): r
        for r in games
    }

    market_rows = []
    line_rows = []
    move_rows = []
    resolve_rows = []

    for _, r in odds.iterrows():
        if int(r.get("schedule_season", -1)) != year:
            continue

        try:
            week = int(r.get("schedule_week"))
        except (ValueError, TypeError):
            continue

        home_abbr = _norm_team(r.get("team_home"), team_map) or _norm_team(r.get("home_team"), team_map)
        away_abbr = _norm_team(r.get("team_away"), team_map) or _norm_team(r.get("away_team"), team_map)
        if not home_abbr or not away_abbr:
            continue

        gkey = (week, home_abbr, away_abbr)
        if gkey not in game_lookup:
            continue

        g = game_lookup[gkey]
        game_node_id = g["gid"]
        start_time = g.get("start_time")
        if start_time is None:
            continue

        spread = safe_float(r.get("spread_favorite"))
        # Kaggle CSV uses team_favorite_id; derive underdog from home/away
        favorite = _norm_team(r.get("team_favorite_id"), team_map)
        underdog = away_abbr if favorite == home_abbr else home_abbr
        total = safe_float(r.get("over_under_line"))

        # Spread market
        if spread is not None:
            _add_spread_market(
                market_rows, line_rows, move_rows, resolve_rows,
                game_node_id, start_time, spread, favorite, underdog,
                home_abbr, r, synth_moves, ingested_at
            )

        # Total market
        if total is not None:
            _add_total_market(
                market_rows, line_rows, move_rows, resolve_rows,
                game_node_id, start_time, total, r, synth_moves, ingested_at
            )

    # Deduplicate and load
    market_df = pd.DataFrame(market_rows).drop_duplicates(subset=["id"]) if market_rows else pd.DataFrame()
    line_df = pd.DataFrame(line_rows).drop_duplicates(subset=["id"]) if line_rows else pd.DataFrame()
    move_df = pd.DataFrame(move_rows).drop_duplicates(subset=["id"]) if move_rows else pd.DataFrame()
    res_df = pd.DataFrame(resolve_rows).drop_duplicates(subset=["id"]) if resolve_rows else pd.DataFrame()

    # Upsert markets
    if not market_df.empty:
        db.run_write(
            """
            UNWIND $rows AS row
            MERGE (m:Market {id: row.id})
            SET m.market_type = row.market_type,
                m.description = row.description,
                m.name = row.name,
                m.source = row.source,
                m.source_id = row.source_id,
                m.ingested_at = datetime(row.ingested_at),
                m.schema_version = row.schema_version
            WITH m, row
            MATCH (g:Game {id: row.game_node_id})
            MERGE (g)-[:HAS_MARKET]->(m)
            WITH m
            MATCH (v:Venue {id: $venue_id})
            MERGE (m)-[:QUOTED_ON]->(v)
            """,
            {"rows": market_df.to_dict("records"), "venue_id": venue_id},
        )

    # Upsert betting lines
    if not line_df.empty:
        for batch in chunked(line_df.to_dict("records"), 2000):
            db.run_write(
                """
                UNWIND $rows AS row
                MERGE (bl:BettingLine {id: row.id})
                SET bl.line_type = row.line_type, bl.value = row.value,
                    bl.odds = row.odds, bl.implied_probability = row.implied_probability,
                    bl.timestamp = datetime(row.timestamp), bl.synthetic = row.synthetic,
                    bl.source = row.source, bl.name = row.name,
                    bl.source_id = row.source_id,
                    bl.ingested_at = datetime(row.ingested_at),
                    bl.schema_version = row.schema_version,
                    bl.synthetic_reason = row.synthetic_reason
                WITH bl, row
                MATCH (m:Market {id: row.market_id})
                MERGE (m)-[:HAS_LINE]->(bl)
                """,
                {"rows": batch},
            )

    # Upsert odds moves
    if not move_df.empty:
        db.run_write(
            """
            UNWIND $rows AS row
            MERGE (om:OddsMovementEvent {id: row.id})
            SET om.at_time = datetime(row.at_time), om.old_odds = row.old_odds,
                om.new_odds = row.new_odds, om.old_line = row.old_line,
                om.new_line = row.new_line, om.change_magnitude = row.change_magnitude,
                om.direction = row.direction, om.synthetic = row.synthetic,
                om.source = row.source, om.name = row.name,
                om.source_id = row.source_id,
                om.ingested_at = datetime(row.ingested_at),
                om.schema_version = row.schema_version,
                om.synthetic_reason = row.synthetic_reason
            WITH om, row
            MATCH (m:Market {id: row.market_id})
            MERGE (m)-[:HAS_ODDS_MOVE]->(om)
            """,
            {"rows": move_df.to_dict("records")},
        )

    # Upsert resolutions
    if not res_df.empty:
        db.run_write(
            """
            UNWIND $rows AS row
            MERGE (mr:MarketResolutionEvent {id: row.id})
            SET mr.resolved_at = datetime(row.resolved_at), mr.outcome = row.outcome,
                mr.final_value = row.final_value, mr.name = row.name
            WITH mr, row
            MATCH (m:Market {id: row.market_id})
            MERGE (m)-[:RESOLVED_BY]->(mr)
            """,
            {"rows": res_df.to_dict("records")},
        )

    print(f"Loaded markets={len(market_df)}, lines={len(line_df)}, moves={len(move_df)}, resolutions={len(res_df)}")


def _format_line(val: float, line_type: str) -> str:
    """Format line value for display."""
    if line_type == "SPREAD":
        return f"{val:+.1f}" if val != 0 else "PK"
    return f"{val:.1f}"


def _add_lines_and_movement(
    line_rows, move_rows, m_id: str, line_type: str,
    closing_value: float, start_time: str, synth_moves: bool, noise_std: float, ingested_at: str
):
    """Add closing line + optional synthetic opening line and movement."""
    closing_odds = -110
    closing_ts = _offset_iso(start_time, -1)  # 1h before game

    line_rows.append({
        "id": f"{m_id}_L_CLOSING",
        "market_id": m_id,
        "line_type": line_type,
        "value": closing_value,
        "odds": closing_odds,
        "implied_probability": float(american_to_implied_prob(closing_odds)),
        "timestamp": closing_ts,
        "synthetic": False,
        "source": "kaggle",
        "source_id": f"{m_id}_L_CLOSING",
        "ingested_at": ingested_at,
        "schema_version": "v1.0",
        "synthetic_reason": None,
        "name": f"{_format_line(closing_value, line_type)} (Close)",
    })

    # Synthetic opening line 24h before game (for demo when real historical data unavailable)
    if synth_moves:
        open_value = closing_value + float(np.random.normal(0, noise_std))
        open_ts = _offset_iso(closing_ts, -24)
        line_rows.append({
            "id": f"{m_id}_L_OPEN",
            "market_id": m_id,
            "line_type": line_type,
            "value": float(open_value),
            "odds": closing_odds,
            "implied_probability": float(american_to_implied_prob(closing_odds)),
            "timestamp": open_ts,
            "synthetic": True,
            "source": "generated",
            "source_id": f"{m_id}_L_OPEN",
            "ingested_at": ingested_at,
            "schema_version": "v1.0",
            "synthetic_reason": "demo_opening_line",
            "name": f"{_format_line(open_value, line_type)} (Open)",
        })
        move_rows.append({
            "id": f"{m_id}_OM1",
            "market_id": m_id,
            "at_time": _offset_iso(closing_ts, -2),
            "old_odds": closing_odds,
            "new_odds": closing_odds,
            "old_line": float(open_value),
            "new_line": float(closing_value),
            "change_magnitude": float(abs(closing_value - open_value)),
            "direction": "UP" if closing_value > open_value else "DOWN",
            "synthetic": True,
            "source": "generated",
            "source_id": f"{m_id}_OM1",
            "ingested_at": ingested_at,
            "schema_version": "v1.0",
            "synthetic_reason": "demo_odds_movement",
            "name": f"{_format_line(open_value, line_type)}→{_format_line(closing_value, line_type)}",
        })


def _extract_matchup(game_node_id: str) -> str:
    """Extract matchup from game ID like NFL_2024_REG_WK1_BAL_KC -> BAL@KC."""
    parts = game_node_id.split("_")
    if len(parts) >= 6:
        return f"{parts[-2]}@{parts[-1]}"
    return game_node_id


def _add_spread_market(
    market_rows, line_rows, move_rows, resolve_rows,
    game_node_id, start_time, spread, favorite, underdog,
    home_abbr, r, synth_moves, ingested_at
):
    """Add spread market data."""
    m_id = f"{game_node_id}_M_SPREAD_FAV"
    matchup = _extract_matchup(game_node_id)
    market_rows.append({
        "id": m_id,
        "game_node_id": game_node_id,
        "market_type": "SPREAD",
        "description": "Point spread (favorite side)",
        "name": f"{matchup} Spread",
        "source": "kaggle",
        "source_id": m_id,
        "ingested_at": ingested_at,
        "schema_version": "v1.0",
    })

    closing_value = float(spread)
    _add_lines_and_movement(line_rows, move_rows, m_id, "SPREAD", closing_value, start_time, synth_moves, SYNTH_SPREAD_NOISE, ingested_at)

    # Resolution
    sh = safe_float(r.get("score_home"))
    sa = safe_float(r.get("score_away"))
    if sh is not None and sa is not None and favorite and underdog:
        fav_score = sh if favorite == home_abbr else sa
        dog_score = sa if favorite == home_abbr else sh
        margin = fav_score - dog_score
        adj = margin + spread
        outcome = "PUSH" if abs(adj) < 1e-9 else ("WIN" if adj > 0 else "LOSS")
        resolve_rows.append({
            "id": f"{m_id}_RES",
            "market_id": m_id,
            "resolved_at": start_time,
            "outcome": outcome,
            "final_value": float(margin),
            "name": f"Result: {outcome}",
        })


def _add_total_market(
    market_rows, line_rows, move_rows, resolve_rows,
    game_node_id, start_time, total, r, synth_moves, ingested_at
):
    """Add total (over/under) market data."""
    m_id = f"{game_node_id}_M_TOTAL"
    matchup = _extract_matchup(game_node_id)
    market_rows.append({
        "id": m_id,
        "game_node_id": game_node_id,
        "market_type": "TOTAL",
        "description": "Game total points (over/under)",
        "name": f"{matchup} O/U",
        "source": "kaggle",
        "source_id": m_id,
        "ingested_at": ingested_at,
        "schema_version": "v1.0",
    })

    closing_value = float(total)
    _add_lines_and_movement(line_rows, move_rows, m_id, "TOTAL", closing_value, start_time, synth_moves, SYNTH_TOTAL_NOISE, ingested_at)

    # Resolution
    sh = safe_float(r.get("score_home"))
    sa = safe_float(r.get("score_away"))
    if sh is not None and sa is not None:
        pts = sh + sa
        diff = pts - total
        outcome = "PUSH" if abs(diff) < 1e-9 else ("OVER" if diff > 0 else "UNDER")
        resolve_rows.append({
            "id": f"{m_id}_RES",
            "market_id": m_id,
            "resolved_at": start_time,
            "outcome": outcome,
            "final_value": float(pts),
            "name": f"Result: {outcome}",
        })

