"""Modular data loaders for NFL Knowledge Graph."""

from .base import load_teams, load_players, upsert_season
from .games import load_games, load_drives_and_plays, load_player_participation, load_player_game_stats
from .markets import load_odds_and_markets
from .signals import load_injuries, link_injuries_to_games, load_news

__all__ = [
    "upsert_season",
    "load_teams",
    "load_players",
    "load_games",
    "load_drives_and_plays",
    "load_player_participation",
    "load_player_game_stats",
    "load_odds_and_markets",
    "load_injuries",
    "link_injuries_to_games",
    "load_news",
]
