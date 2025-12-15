#!/usr/bin/env python3
"""
NFL Knowledge Graph - Query Runner

Executes all predefined Cypher queries from query_definitions.py and optionally
exports results to JSON.

Usage:
    python queries.py --export
    python queries.py --export --as-of 2024-12-01T12:00:00+00:00
    python queries.py --export --as-of 2024-12-01
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict

from db import Neo4jConnection
from query_definitions import QUERIES


def run_all(db: Neo4jConnection, export: bool, as_of: str = "2024-11-15T12:00:00+00:00") -> Dict[str, Any]:
    """Run all queries and optionally export results to JSON."""
    results: Dict[str, Any] = {}
    for name, cypher in QUERIES.items():
        params = {}
        if "$as_of" in cypher:
            params["as_of"] = as_of
        results[name] = db.run(cypher, params)

    if export:
        out = Path("query_outputs") / "all_queries.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(results, default=str, indent=2))
        print(f"Wrote {out}")

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run NFL knowledge graph queries")
    parser.add_argument("--export", action="store_true", help="Export results to JSON")
    parser.add_argument("--as-of", type=str, default="2024-11-15T12:00:00+00:00",
                        help="ISO datetime for point-in-time queries (YYYY-MM-DDTHH:MM:SS+00:00)")
    args = parser.parse_args()

    # Allow passing a date-only string for convenience (treated as midnight UTC).
    # Many Cypher queries use datetime($as_of) and date(datetime($as_of)).
    as_of = args.as_of
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of):
        as_of = f"{as_of}T00:00:00+00:00"

    db = Neo4jConnection()
    try:
        run_all(db, export=args.export, as_of=as_of)
    finally:
        db.close()


if __name__ == "__main__":
    main()
