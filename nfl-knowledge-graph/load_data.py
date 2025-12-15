#!/usr/bin/env python3
"""
NFL Knowledge Graph - Data Loader

Pipeline: Schema → Season → Teams → Players → Games → Drives/Plays → Markets → Signals

All entities use MERGE for idempotency (safe to re-run). Use --clear for full rebuild.
Player-team relationships are temporal (valid_from/valid_to). Betting lines are immutable
time-stamped snapshots; odds movements track transitions between them.

Usage:
    python load_data.py --clear --season 2024 --synth-odds-moves
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from db import Neo4jConnection
from loaders import (
    upsert_season,
    load_teams,
    load_players,
    load_games,
    load_drives_and_plays,
    load_player_participation,
    load_player_game_stats,
    load_odds_and_markets,
    load_injuries,
    link_injuries_to_games,
    load_news,
)


def run_schema(db: Neo4jConnection, schema_path: Path) -> None:
    """Apply schema constraints and indexes."""
    cypher = schema_path.read_text()
    statements = [s.strip() for s in cypher.split(";") if s.strip()]
    for stmt in statements:
        db.run_write(stmt)
    print(f"Applied schema: {schema_path.name}")


def clear_graph(db: Neo4jConnection) -> None:
    """Delete all nodes and relationships."""
    db.run_write("MATCH (n) DETACH DELETE n")
    print("Cleared graph.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Load NFL data into Neo4j")
    parser.add_argument("--season", type=int, default=2024, help="NFL season year")
    parser.add_argument("--data", type=str, default="data", help="Data directory")
    parser.add_argument("--clear", action="store_true", help="Clear graph before loading")
    parser.add_argument("--plays", type=int, default=10000, help="Max plays to load (0 = all)")
    parser.add_argument("--synth-odds-moves", action="store_true", help="Generate synthetic odds movements")
    args = parser.parse_args()

    load_dotenv()
    odds_csv = Path(os.getenv("ODDS_CSV_PATH", "data/spreadspoke_scores.csv"))

    # Data file paths
    data_dir = Path(args.data)
    paths = {
        "teams": data_dir / "team_desc.parquet",
        "schedule": data_dir / f"schedules_{args.season}.parquet",
        "roster": data_dir / f"rosters_{args.season}.parquet",
        "pbp": data_dir / f"pbp_{args.season}.parquet",
        "injuries": data_dir / f"injuries_{args.season}.parquet",
        "news": data_dir / "news.parquet",
    }

    # Load dataframes
    def read_if_exists(p: Path) -> pd.DataFrame:
        return pd.read_parquet(p) if p.exists() else pd.DataFrame()

    teams = read_if_exists(paths["teams"])
    sched = pd.read_parquet(paths["schedule"])  # Required
    rosters = pd.read_parquet(paths["roster"])  # Required
    pbp = read_if_exists(paths["pbp"])
    injuries = read_if_exists(paths["injuries"])
    news = read_if_exists(paths["news"])

    # Connect and load
    db = Neo4jConnection()
    try:
        if args.clear:
            clear_graph(db)

        run_schema(db, Path(__file__).with_name("schema.cypher"))

        # Core entities
        upsert_season(db, args.season)
        team_map = load_teams(db, teams)
        load_players(db, rosters, args.season)
        load_games(db, sched, args.season)

        # Play-by-play (optional)
        if not pbp.empty:
            load_drives_and_plays(db, pbp, args.season, args.plays)
            load_player_participation(db, pbp, args.season, args.plays)
            load_player_game_stats(db, args.season)

        # Markets & odds
        load_odds_and_markets(
            db, args.season, team_map, odds_csv,
            synth_moves=args.synth_odds_moves, venue_id="KAGGLE"
        )

        # Signals
        load_injuries(db, injuries, args.season)
        link_injuries_to_games(db)  # Link injuries to next game
        load_news(db, news)

        print("\n✓ Load complete.")

    finally:
        db.close()


if __name__ == "__main__":
    main()
