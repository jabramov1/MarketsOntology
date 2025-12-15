# Interview Guide 2 — NFL Event & Market Temporal Knowledge Graph (Neo4j)

Use this as a “talk track” + cheat sheet so you can confidently explain what you built, why you modeled it this way, and how to defend design tradeoffs.

---

## 0) 20–30 second intro (say this)

“I built an event-centric temporal knowledge graph for the 2024 NFL season in Neo4j. It unifies games and play-by-play structure (Game → Drive → Play) with participants (Team, Player) and betting context (Market → time-stamped BettingLine snapshots + OddsMovementEvent). Injuries and news are added as time-stamped signals, and I intentionally **don’t** encode speculative causality as edges — I infer correlations at query time using temporal joins.”

If they ask what it’s for:
“The point is to support *as-of* analytics: ‘what would we have known at time T?’ so you can analyze odds moves, signals, and outcomes without leaking future data.”

---

## 1) 60–90 second walkthrough (say this)

1) “I start by applying constraints/indexes (`nfl-knowledge-graph/schema.cypher`).”
2) “Then I load core entities: `Season`, `Team`, `Player`, `Game` (`nfl-knowledge-graph/load_data.py`).”
3) “If play-by-play exists, I add `Drive` and `Play` nodes from nflverse-style data, and link players to plays/games via participation edges (`nfl-knowledge-graph/loaders/games.py`).”
4) “Markets are modeled as a `Market` node per game-market, and odds are modeled as immutable `BettingLine` snapshots with timestamps. Optional synthetic open-line + odds movement is generated for end-to-end demos (`nfl-knowledge-graph/loaders/markets.py`).”
5) “Signals: `InjuryEvent` nodes are loaded and linked to the next game for that team, and `NewsItem` is loaded and linked heuristically with reference fields (`nfl-knowledge-graph/loaders/signals.py`).”
6) “Finally, I have a set of Cypher queries that demonstrate temporal reasoning and provenance filtering (`nfl-knowledge-graph/query_definitions.py`, `nfl-knowledge-graph/queries.py`).”

---

## 2) What to emphasize (the “why”)

### Event-centric + temporal modeling
- Events (games/plays, signals, market moves) are first-class nodes with timestamps.
- Temporal relationships use `valid_from`, `valid_to`, `valid_to_or_max` (implemented on `PLAYS_FOR`).

### Provenance is explicit (what’s real vs synthetic)
- Every major node type has `source`, `source_id`, `ingested_at`, and sometimes `synthetic` + `synthetic_reason`.
- This makes it easy to demo end-to-end behavior without pretending synthetic data is real.

### “No causal edges” (strong interview answer)
- I did **not** add edges like `InjuryEvent -> Market` that would imply causality.
- Instead: store facts and infer relationships at query time (temporal correlation windows).

---

## 3) What’s in the graph (labels + key edges)

### Core nodes
- `Season`, `Game`, `Drive`, `Play`
- `Team`, `Player`
- `Market`, `BettingLine`, `OddsMovementEvent`, `MarketResolutionEvent`, `Venue`
- `InjuryEvent`, `NewsItem`

### Core relationships
- `(:Game)-[:PART_OF_SEASON]->(:Season)`
- `(:Game)-[:HOME_TEAM|AWAY_TEAM]->(:Team)`
- `(:Player)-[:PLAYS_FOR {valid_from, valid_to, ...}]->(:Team)`
- `(:Game)-[:HAS_DRIVE]->(:Drive)-[:HAS_PLAY]->(:Play)`
- `(:Game)-[:HAS_MARKET]->(:Market)-[:QUOTED_ON]->(:Venue)`
- `(:Market)-[:HAS_LINE]->(:BettingLine)`
- `(:Market)-[:HAS_ODDS_MOVE]->(:OddsMovementEvent)`
- `(:Market)-[:RESOLVED_BY]->(:MarketResolutionEvent)`
- `(:InjuryEvent)-[:AFFECTS]->(:Player)`
- `(:InjuryEvent)-[:REPORTED_BEFORE]->(:Game)` (linked to the next game after the report)
- `(:NewsItem)-[:REFERS_TO_GAME]->(:Game)` (heuristic)

---

## 4) “As-of” and why Query 15 can be empty (know this cold)

### What is `$as_of`?
It’s the “freeze time T” parameter: an ISO datetime string used as `datetime($as_of)` in Cypher.

### Why can Query 15 return 0 rows?
Query 15 requires **both**:
1) the game is **in the future** at time T (`g.start_time > as_of`), and
2) at least one betting line exists **at or before** time T (`bl.timestamp <= as_of`).

But the loader only creates two line timestamps per market:
- closing line at `game_start - 1 hour`
- optional synthetic opening line at `game_start - 25 hours`

So if you set `as_of` more than ~25 hours before the next upcoming game, there are **no lines “known” yet**, and Query 15 is correctly empty.

### How to run it in Neo4j Browser
First set:
```cypher
:param {as_of: "2024-11-09T12:00:00+00:00"}
```
Then run Query 15.

If they challenge this design:
“It’s an MVP demo choice. With a real odds feed I’d ingest many historical snapshots, so the as-of window could be weeks/months.”

---

## 5) Demo plan (what to show in 2 minutes)

If you have Neo4j Browser open, use:
`nfl-knowledge-graph/query_outputs/neo4j_screenshot_queries.cypher`

Suggested sequence:
1) `CALL db.schema.visualization()` (shows you built an ontology, not just a table dump)
2) A path query: Player → Team → Game → Drive → Play (shows event hierarchy)
3) Market path: Game → Market → BettingLine / OddsMovementEvent (shows time-stamped odds)
4) Signals: InjuryEvent → Player and NewsItem → Game (shows “signals” layer)
5) A provenance filter (`WHERE bl.synthetic = false`) (shows rigor / auditability)

---

## 6) Likely questions (with answers you can reuse)

### “Why Neo4j / a graph at all?”
- You’re querying *relationships* and *paths* (player/team/game/market/signal) and need flexible joins.
- Cypher pattern matching + graph traversals make “timeline reconstruction” and “as-of joins” natural.

### “What’s your temporal model?”
- Time-stamped event nodes (`reported_at`, `published_at`, `at_time`, `timestamp`)
- Time-bounded relationships for state (`PLAYS_FOR.valid_from/valid_to`)
- As-of queries are just temporal filters on those fields.

### “How do you prevent temporal leakage?”
- For “as-of” analytics, I filter each signal and market snapshot with `<= as_of`.
- I also excluded post-game recap news because it would leak outcomes into “pre-game” analysis (`nfl-knowledge-graph/generate_news.py`).

### “Is there real mid-season team change support?”
- The schema supports it (multiple `PLAYS_FOR` edges with time bounds).
- Current roster input is season-level, so the loader doesn’t populate mid-season changes yet (known limitation).

### “What are the biggest limitations?”
- Odds history is sparse (only closing + optional synthetic opening), so long-horizon as-of views can be empty.
- Game `start_time` is from schedule `gameday` (often midnight UTC), not true kickoff; good enough for weekly demo windows.
- News links are heuristic; they’re explicitly marked as such.

### “What would you do next if this were production?”
- Real odds feed ingestion (many snapshots), incremental updates, partitioning by season, and stronger entity resolution.
- Better temporal accuracy (true kickoff timestamps) and a trade/transaction dataset for mid-season `PLAYS_FOR` changes.
- Observability: loader metrics, retries, and backfills.

---

## 7) Two-page low-level design (LLD)

### 7.1 Goals / non-goals
- Goal: end-to-end temporal graph for NFL 2024 with clean provenance and demonstrable temporal queries.
- Non-goal: perfect historical accuracy for odds and news causality (synthetic data is clearly labeled).

### 7.2 Key modules (where to point in code)
- `nfl-knowledge-graph/db.py`: Neo4j driver wrapper (read/write helpers).
- `nfl-knowledge-graph/schema.cypher`: constraints + indexes (performance + integrity).
- `nfl-knowledge-graph/util.py`: parsing helpers (ISO time parsing, safe casting, chunking).
- `nfl-knowledge-graph/load_data.py`: orchestration CLI (pipeline order + flags).
- `nfl-knowledge-graph/loaders/base.py`: Season/Team/Player + temporal `PLAYS_FOR`.
- `nfl-knowledge-graph/loaders/games.py`: Game nodes + Drive/Play + participation edges.
- `nfl-knowledge-graph/loaders/markets.py`: Market/Venue + BettingLine snapshots + movement + resolution.
- `nfl-knowledge-graph/loaders/signals.py`: InjuryEvent + NewsItem + links to games/players/teams.
- `nfl-knowledge-graph/query_definitions.py`: the “portfolio” of demo Cypher queries.
- `nfl-knowledge-graph/queries.py`: runs all queries; injects `$as_of` automatically when needed.

### 7.3 Data inputs (what you load)
- `data/team_desc.parquet` (teams + colors/divisions)
- `data/schedules_2024.parquet` (games + home/away + week)
- `data/rosters_2024.parquet` (players + season roster membership)
- `data/pbp_2024.parquet` (optional: drives/plays/participants)
- `data/injuries_2024.parquet` (optional: injury reports)
- `data/news.parquet` (generated synthetic news)
- `data/spreadspoke_scores.csv` (optional: Kaggle odds + scores; path override via `ODDS_CSV_PATH`)

### 7.4 IDs and provenance rules
- Every node gets a stable `id` (domain-prefixed), plus `source`, `source_id`, `ingested_at`.
- Synthetic/demo data gets `synthetic=true` and `synthetic_reason` (e.g., demo open line).
- This is what lets you say “I can filter out anything synthetic in one WHERE clause.”

### 7.5 Loader pipeline behavior (exact sequence)
Entry point: `python3 nfl-knowledge-graph/load_data.py [--clear] [--synth-odds-moves]`

1) (Optional) clear: `MATCH (n) DETACH DELETE n`
2) apply schema: split `schema.cypher` by semicolons and run each statement
3) `upsert_season(year)`
4) `load_teams(teams_df)` → returns team-name normalization map used by odds loader
5) `load_players(rosters_df, year)` → upserts Player nodes + `PLAYS_FOR` edges with `valid_from=Sep 1`
6) `load_games(schedule_df, year)` → creates Game nodes + HOME/AWAY_TEAM edges + PART_OF_SEASON
7) If pbp exists:
   - `load_drives_and_plays(pbp_df)` → Drive and Play nodes + HAS_DRIVE/HAS_PLAY
   - `load_player_participation(pbp_df)` → Player ↔ Play edges (role/stats-like fields)
   - `load_player_game_stats(year)` → aggregates participation into Player ↔ Game stats
8) `load_odds_and_markets(...)` → Market nodes + Venue + BettingLine snapshots + optional movement + resolution
9) `load_injuries(...)` + `link_injuries_to_games(...)` → InjuryEvent + REPORTED_BEFORE edges
10) `load_news(...)` → NewsItem nodes + REFERS_TO_* heuristic links

### 7.6 Query layer (how to explain it)
- Queries are stored as named strings in `query_definitions.py`.
- Runner (`queries.py`) scans for `"$as_of"` and supplies a default `as_of` value so point-in-time queries run reproducibly.
- Key patterns:
  - provenance filters (`synthetic=false`, `source='kaggle'`)
  - temporal windows (`abs(duration.inSeconds(...).seconds) < N`)
  - “as-of latest snapshot” = order by `bl.timestamp DESC` then `collect(bl)[0]`

### 7.7 Performance notes (simple but credible)
- Uses `UNWIND $rows` to batch upserts in Neo4j (fast enough for MVP scale).
- `chunked(...)` batching for large line loads (keeps transactions bounded).
- Indexes/constraints in `schema.cypher` prevent slow lookups and duplicate IDs.

---

## 8) One-sentence “closing”

“The graph is designed to be auditably temporal: facts are time-stamped, state is time-bounded, and causality is computed at query time — which makes the system both explainable and extensible beyond NFL.”

