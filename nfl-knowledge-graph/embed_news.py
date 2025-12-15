#!/usr/bin/env python3
"""Minimal node embeddings + Neo4j vector search.

Embeds text-bearing nodes (not edges). Default target is NewsItem.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sentence_transformers import SentenceTransformer

from db import Neo4jConnection

MODEL = "all-MiniLM-L6-v2"  # 384 dims
DIMENSIONS = 384

INDEX_NEWS = "news_embedding"
INDEX_MARKET = "market_embedding"
INDEX_PLAY = "play_embedding"


def _ensure_index(db: Neo4jConnection, *, index: str, label: str) -> None:
    try:
        db.run_write(
            f"""
            CREATE VECTOR INDEX {index} IF NOT EXISTS
            FOR (n:{label}) ON (n.embedding)
            OPTIONS {{indexConfig: {{
              `vector.dimensions`: {DIMENSIONS},
              `vector.similarity_function`: 'cosine'
            }}}}
            """
        )
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Failed to create Neo4j vector index. "
            "This requires Neo4j 5.11+ (Aura supports it)."
        ) from e


def _embed(
    db: Neo4jConnection,
    *,
    index: str,
    label: str,
    match: str,
    text_key: str,
    limit: int | None,
) -> int:
    _ensure_index(db, index=index, label=label)
    cypher = f"{match} RETURN n.id AS id, {text_key} AS text"
    if limit:
        cypher += " LIMIT $limit"
    items = db.run(cypher, {"limit": limit} if limit else None)
    if not items:
        return 0

    model = SentenceTransformer(MODEL)
    rows = []
    for item in items:
        text = (item.get("text") or "").strip()
        if text:
            rows.append({"id": item["id"], "embedding": model.encode(text).tolist()})

    db.run_write(
        f"""
        UNWIND $rows AS row
        MATCH (n:{label} {{id: row.id}})
        SET n.embedding = row.embedding,
            n.embedding_model = $model,
            n.embedded_at = datetime()
        """,
        {"rows": rows, "model": MODEL},
    )
    return len(rows)


def embed_news(db: Neo4jConnection, limit: int | None) -> int:
    return _embed(
        db,
        index=INDEX_NEWS,
        label="NewsItem",
        match="MATCH (n:NewsItem) WHERE n.embedding IS NULL",
        text_key="coalesce(n.headline,'')",
        limit=limit,
    )


def embed_markets(db: Neo4jConnection, limit: int | None) -> int:
    return _embed(
        db,
        index=INDEX_MARKET,
        label="Market",
        match="MATCH (n:Market) WHERE n.embedding IS NULL",
        text_key="trim(coalesce(n.name,'') + ' ' + coalesce(n.description,'') + ' ' + coalesce(n.market_type,''))",
        limit=limit,
    )


def embed_plays(db: Neo4jConnection, limit: int | None) -> int:
    return _embed(
        db,
        index=INDEX_PLAY,
        label="Play",
        match="MATCH (n:Play) WHERE n.embedding IS NULL AND n.description IS NOT NULL",
        text_key="coalesce(n.description,'')",
        limit=limit,
    )


def search_news(db: Neo4jConnection, query: str, k: int, since: str | None, until: str | None):
    _ensure_index(db, index=INDEX_NEWS, label="NewsItem")
    model = SentenceTransformer(MODEL)
    emb = model.encode(query).tolist()
    return db.run(
        """
        WITH CASE WHEN $since IS NULL THEN NULL ELSE datetime($since) END AS since,
             CASE WHEN $until IS NULL THEN NULL ELSE datetime($until) END AS until,
             $emb AS emb, $k AS k
        CALL db.index.vector.queryNodes($index, k * 5, emb) YIELD node, score
        WITH node, score, since, until
        WHERE (since IS NULL OR node.published_at >= since)
          AND (until IS NULL OR node.published_at <= until)
        RETURN node.id AS id, node.published_at AS published_at, node.headline AS headline, score
        ORDER BY score DESC
        LIMIT k
        """,
        {"index": INDEX_NEWS, "emb": emb, "k": k, "since": since, "until": until},
    )


def search_markets(db: Neo4jConnection, query: str, k: int):
    _ensure_index(db, index=INDEX_MARKET, label="Market")
    model = SentenceTransformer(MODEL)
    emb = model.encode(query).tolist()
    return db.run(
        """
        WITH $emb AS emb, $k AS k
        CALL db.index.vector.queryNodes($index, k, emb) YIELD node, score
        RETURN node.id AS id, node.market_type AS market_type, node.name AS name, score
        ORDER BY score DESC
        """,
        {"index": INDEX_MARKET, "emb": emb, "k": k},
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-plays", action="store_true", help="Also embed Play descriptions (can be large)")
    ap.add_argument("--limit", type=int, default=0, help="Optional limit per embed step (0 = no limit)")
    ap.add_argument("--q", type=str, help="Query string for semantic search")
    ap.add_argument("--in", dest="search_in", choices=["news", "markets"], default="news")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--since", type=str, default=None, help="ISO datetime filter (published_at >= since)")
    ap.add_argument("--until", type=str, default=None, help="ISO datetime filter (published_at <= until)")
    args = ap.parse_args()

    db = Neo4jConnection()
    try:
        limit = None if args.limit <= 0 else args.limit
        # Default: embed News + Markets every run
        print(f"Embedded {embed_news(db, limit)} NewsItems.")
        print(f"Embedded {embed_markets(db, limit)} Markets.")
        if args.include_plays:
            print(f"Embedded {embed_plays(db, limit)} Plays.")
        if args.q:
            if args.search_in == "news":
                for r in search_news(db, args.q, args.k, args.since, args.until):
                    print(f"[{r['score']:.3f}] {r['published_at']} {r['headline']}")
            else:
                for r in search_markets(db, args.q, args.k):
                    print(f"[{r['score']:.3f}] {r['market_type']} {r['name']} ({r['id']})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
