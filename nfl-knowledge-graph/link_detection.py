#!/usr/bin/env python3
"""Optional Part 4.4 (WIP): read-only link detection (no edge writes).

This script is intentionally lightweight and only writes CSV outputs.

Detectors:
- Missing NewsItem↔Market links via embedding similarity.
- Odds moves with no nearby NewsItem in a time window.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path
from typing import Any, Dict, List

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from db import Neo4jConnection


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return float("nan")
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    denom = math.sqrt(na) * math.sqrt(nb)
    return dot / denom if denom else float("nan")


def _write_csv(rows: List[Dict[str, Any]], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        if not rows:
            return
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def detect_news_market_candidates(db: Neo4jConnection, *, threshold: float) -> List[Dict[str, Any]]:
    # Candidate generation: markets for the NewsItem's referenced game.
    pairs = db.run(
        """
        MATCH (n:NewsItem)-[:REFERS_TO_GAME]->(g:Game)
        WHERE n.embedding IS NOT NULL
          AND NOT (n)-[:REFERS_TO_MARKET]->(:Market)
        MATCH (g)-[:HAS_MARKET]->(m:Market)
        WHERE m.embedding IS NOT NULL
          AND NOT (n)-[:REFERS_TO_MARKET]->(m)
        RETURN
          g.id AS game_id,
          n.id AS news_id,
          toString(n.published_at) AS news_published_at,
          n.headline AS news_headline,
          n.embedding AS news_embedding,
          m.id AS market_id,
          m.market_type AS market_type,
          m.name AS market_name,
          m.embedding AS market_embedding
        """,
        {},
    )

    out: List[Dict[str, Any]] = []
    for r in pairs:
        sim = _cosine_similarity(r.get("news_embedding") or [], r.get("market_embedding") or [])
        if math.isnan(sim) or sim < threshold:
            continue
        out.append(
            {
                "game_id": r.get("game_id"),
                "news_id": r.get("news_id"),
                "news_published_at": r.get("news_published_at"),
                "news_headline": r.get("news_headline"),
                "market_id": r.get("market_id"),
                "market_type": r.get("market_type"),
                "market_name": r.get("market_name"),
                "similarity": sim,
            }
        )
    out.sort(key=lambda x: (x["similarity"], x["news_published_at"] or ""), reverse=True)
    return out


def detect_unexplained_odds_moves(
    db: Neo4jConnection, *, window_hours: int, min_change: float, limit: int
) -> List[Dict[str, Any]]:
    window_seconds = int(window_hours) * 3600
    return db.run(
        """
        MATCH (m:Market)<-[:HAS_MARKET]-(g:Game)
        MATCH (m)-[:HAS_ODDS_MOVE]->(om:OddsMovementEvent)
        WHERE om.change_magnitude >= $min_change
        WITH m, g, om, $window_seconds AS ws
        WHERE NOT EXISTS {
          MATCH (n:NewsItem)-[:REFERS_TO_GAME]->(g)
          WHERE abs(duration.inSeconds(n.published_at, om.at_time).seconds) <= ws
        }
        RETURN
          g.id AS game_id,
          m.id AS market_id,
          m.market_type AS market_type,
          om.id AS odds_move_id,
          toString(om.at_time) AS moved_at,
          om.change_magnitude AS change_magnitude,
          om.direction AS direction,
          om.name AS move_name
        ORDER BY change_magnitude DESC, moved_at DESC
        LIMIT $limit
        """,
        {"window_seconds": window_seconds, "min_change": float(min_change), "limit": int(limit)},
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Read-only link detection (Part 4.4, WIP).")
    ap.add_argument("--mode", choices=["all", "news-market", "unexplained-moves"], default="all")
    ap.add_argument("--out-dir", type=str, default="query_outputs", help="Directory for CSV outputs")
    ap.add_argument("--threshold", type=float, default=0.25, help="Cosine similarity threshold (news-market)")
    ap.add_argument("--window-hours", type=int, default=24, help="Time window around move timestamp")
    ap.add_argument("--min-change", type=float, default=0.5, help="Minimum odds move magnitude")
    ap.add_argument("--limit", type=int, default=100, help="Max unexplained moves to output")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)

    db = Neo4jConnection()
    try:
        if args.mode in ("all", "news-market"):
            rows = detect_news_market_candidates(db, threshold=args.threshold)
            _write_csv(rows, out_dir / "news_market_candidates.csv")
            print(f"Wrote {len(rows)} rows to {out_dir/'news_market_candidates.csv'}")

        if args.mode in ("all", "unexplained-moves"):
            rows = detect_unexplained_odds_moves(
                db, window_hours=args.window_hours, min_change=args.min_change, limit=args.limit
            )
            _write_csv(rows, out_dir / "unexplained_odds_moves.csv")
            print(f"Wrote {len(rows)} rows to {out_dir/'unexplained_odds_moves.csv'}")
    finally:
        db.close()


if __name__ == "__main__":
    main()

