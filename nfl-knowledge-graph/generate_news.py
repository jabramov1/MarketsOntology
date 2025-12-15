#!/usr/bin/env python3
"""Deterministic synthetic news: preview+recap per game, injury item per injury row, sparse roster notes."""
from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from util import first_of, find_col

SOURCES = ["ESPN", "NFL.com", "The Athletic", "CBS Sports", "Yahoo Sports", "Bleacher Report"]
AUTHORS = ["Staff", "AP", "Reuters", "ESPN Staff", "NFL.com Staff", "The Athletic Staff"]


def stable_id(prefix: str, *parts: str) -> str:
    h = hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{h}"

def _stable_int(*parts: str) -> int:
    return int(hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()[:12], 16)


def _stable_choice(options: list[str], *parts: str) -> str:
    if not options:
        raise ValueError("options must be non-empty")
    return options[_stable_int(*parts) % len(options)]


def _stable_coin_flip(p: float, *parts: str) -> bool:
    if p <= 0:
        return False
    if p >= 1:
        return True
    # Deterministic pseudo-random in [0, 1)
    r = (_stable_int(*parts) % 1_000_000) / 1_000_000.0
    return r < p


def kickoff_dt(gameday: str | None, season: int, hour: int = 18) -> datetime:
    base = pd.to_datetime(gameday, utc=True, errors="coerce")
    if pd.notna(base):
        return base.to_pydatetime().replace(hour=hour, minute=0, second=0, microsecond=0)
    return datetime(season, 9, 1, hour=hour, tzinfo=timezone.utc)


def make_summary(kind: str, away: str, home: str, player_name: str | None) -> str:
    if kind == "preview":
        return f"Preview for {away} at {home}: matchups, injuries, and what to watch."
    if kind == "injury" and player_name:
        return f"Injury update: {player_name} status ahead of {away} at {home}."
    if kind == "recap":
        return f"Recap: {home} vs {away} with key moments and final score context."
    return f"Roster note for {away} at {home}: changes that could impact the matchup."


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2024)
    ap.add_argument("--data", type=str, default="data")
    ap.add_argument("--roster-notes-ratio", type=float, default=0.1, help="Prob. of emitting roster note per game")
    args = ap.parse_args()

    data_dir = Path(args.data)
    sched_path = data_dir / f"schedules_{args.season}.parquet"
    roster_path = data_dir / f"rosters_{args.season}.parquet"
    injuries_path = data_dir / f"injuries_{args.season}.parquet"

    if not sched_path.exists():
        raise SystemExit(f"Missing {sched_path}. Run download_data.py first.")

    sched = pd.read_parquet(sched_path)
    rosters = pd.read_parquet(roster_path) if roster_path.exists() else pd.DataFrame()
    injuries = pd.read_parquet(injuries_path) if injuries_path.exists() else pd.DataFrame()

    player_name_by_id: dict[str, str] = {}
    player_team_by_id: dict[str, str] = {}
    if not rosters.empty:
        pid_col = find_col(rosters, "gsis_id", "player_id")
        name_col = find_col(rosters, "player_name", "full_name", "name")
        team_col = find_col(rosters, "team", "team_abbr", "club_code")
        if pid_col and name_col:
            for _, r in rosters.iterrows():
                pid = first_of(r, pid_col)
                if pid:
                    player_name_by_id[pid] = first_of(r, name_col)
                    if team_col:
                        player_team_by_id[pid] = first_of(r, team_col)

    rows = []

    # One preview + one recap per game; optional roster note
    for _, g in sched.iterrows():
        home = str(first_of(g, "home_team", "home_team_abbr", "home_team_x", default="HOME"))
        away = str(first_of(g, "away_team", "away_team_abbr", "away_team_x", default="AWAY"))
        game_id = str(first_of(g, "game_id", "gameid", "gsis_id", "id", default=f"{args.season}_{away}_{home}"))
        gameday = first_of(g, "gameday", "game_date", "date", default=f"{args.season}-09-05")
        kickoff = kickoff_dt(gameday, args.season)
        source = _stable_choice(SOURCES, "source", game_id)
        author = _stable_choice(AUTHORS, "author", game_id)

        # Preview
        news_id = stable_id("NEWS", source, game_id, "PRE")
        rows.append({
            "id": news_id,
            "headline": f"{away} vs {home}: what to watch on Sunday",
            "summary": make_summary("preview", away, home, None),
            "source": source,
            "url": f"https://example.com/{game_id}_preview",
            "published_at": (kickoff - timedelta(days=2)).isoformat(),
            "author": author,
            "sentiment_score": 0.1,
            "ref_game_id": game_id,
            "ref_team_abbr": None,
            "ref_player_id": None,
            "ref_market_id": None,
            "synthetic": True,
            "synthetic_reason": "deterministic_preview_news",
        })

        # Recap removed - publishes AFTER game, can't affect odds

        # Sparse roster note
        if _stable_coin_flip(args.roster_notes_ratio, "roster_note", game_id):
            roster_id = stable_id("NEWS", source, game_id, "ROS")
            rows.append({
                "id": roster_id,
                "headline": f"Roster note: changes could affect {away}–{home}",
                "summary": make_summary("trade", away, home, None),
                "source": source,
                "url": f"https://example.com/{game_id}_roster",
                "published_at": (kickoff - timedelta(days=1)).isoformat(),
                "author": author,
                "sentiment_score": 0.0,
                "ref_game_id": game_id,
                "ref_team_abbr": None,
                "ref_player_id": None,
                "ref_market_id": None,
                "synthetic": True,
                "synthetic_reason": "deterministic_roster_note",
            })

    # One injury item per injury record
    if not injuries.empty:
        pid_col = find_col(injuries, "player_id", "gsis_id")
        status_col = find_col(injuries, "report_status", "status", "injury_status")
        part_col = find_col(injuries, "injury", "body_part", "injury_type", "report_primary_injury")
        date_col = find_col(injuries, "report_date", "date", "date_modified")
        team_col = find_col(injuries, "team", "team_abbr")
        week_col = find_col(injuries, "week")
        for _, r in injuries.iterrows():
            pid = first_of(r, pid_col) if pid_col else None
            player_name = player_name_by_id.get(pid) if pid else None
            team_abbr = first_of(r, team_col) if team_col else player_team_by_id.get(pid)
            if not player_name:
                continue
            status = first_of(r, status_col) or "Status Unknown"
            part = first_of(r, part_col)
            headline = f"{player_name} {status}" + (f" ({part})" if part else "") + " injury update"
            reported_at = kickoff_dt(first_of(r, date_col), args.season, hour=12)
            week = first_of(r, week_col)
            inj_id = stable_id("NEWS", "INJ", headline, str(pid), str(week or ""))
            rows.append({
                "id": inj_id,
                "headline": headline,
                "summary": make_summary("injury", "TBD", "TBD", player_name),
                "source": "NFL.com",
                "url": f"https://example.com/{pid}_injury",
                "published_at": reported_at.isoformat(),
                "author": "Staff",
                "sentiment_score": -0.2,
                "ref_game_id": None,
                "ref_team_abbr": team_abbr,
                "ref_player_id": pid,
                "ref_market_id": None,
                "synthetic": True,
                "synthetic_reason": "deterministic_injury_news",
            })

    news = pd.DataFrame(rows).sort_values(["published_at", "id"], kind="stable").reset_index(drop=True)
    news.to_parquet(data_dir / "news.parquet", index=False)
    news.to_csv(data_dir / "news.csv", index=False)
    print(f"Wrote {len(news)} news items to {data_dir/'news.parquet'}")


if __name__ == "__main__":
    main()
