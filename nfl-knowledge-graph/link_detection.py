#!/usr/bin/env python3
"""Optional Part 4.4 (WIP): read-only link detection (no edge writes).

This script is intentionally lightweight and writes a JSON report.

Detectors:
- Odds moves with no nearby NewsItem in a time window.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from db import Neo4jConnection


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(payload: Dict[str, Any], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


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
    ap.add_argument("--mode", choices=["all", "unexplained-moves"], default="all")
    ap.add_argument("--out-dir", type=str, default="query_outputs", help="Directory for JSON output")
    ap.add_argument("--window-hours", type=int, default=24, help="Time window around move timestamp")
    ap.add_argument("--min-change", type=float, default=0.5, help="Minimum odds move magnitude")
    ap.add_argument("--limit", type=int, default=100, help="Max unexplained moves to output")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)

    db = Neo4jConnection()
    try:
        report: Dict[str, Any] = {
            "generated_at": _utc_now_iso(),
            "mode": args.mode,
            "params": {
                "window_hours": args.window_hours,
                "min_change": args.min_change,
                "limit": args.limit,
            },
        }

        rows = detect_unexplained_odds_moves(
            db, window_hours=args.window_hours, min_change=args.min_change, limit=args.limit
        )
        report["unexplained_odds_moves"] = rows
        report["unexplained_odds_moves_count"] = len(rows)

        out_path = out_dir / "link_detection.json"
        _write_json(report, out_path)
        print(f"Wrote {out_path}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
