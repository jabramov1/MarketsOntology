# NFL Event & Market Temporal Knowledge Graph (MVP)

This repo builds a Neo4j graph for the **2024 NFL season** with:
- Season → Game → Drive → Play (event hierarchy)
- Team / Player entities + temporal `PLAYS_FOR`
- Markets + time-stamped `BettingLine` snapshots
- (Optional) synthetic `OddsMovementEvent` snapshots for end-to-end temporal demos
- News + injuries + example Cypher queries (season-aligned synthetic timestamps)

## 1) Setup

### Install
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Neo4j Aura credentials
Copy `.env.example` → `.env` and fill:
- `NEO4J_URI`
- `NEO4J_USERNAME`
- `NEO4J_PASSWORD`

Test:
```bash
python db.py
```

## 2) Get data (2024)

```bash
python scripts/download_data.py --season 2024 --pbp-sample 10000
python scripts/generate_news.py --season 2024  # deterministic: 1 preview per game, 1 item per injury row
```

Optional odds dataset (Kaggle):
- Put `spreadspoke_scores.csv` at `data/spreadspoke_scores.csv`
- Or set `ODDS_CSV_PATH` in `.env`

## 3) Load into Neo4j

```bash
python load_data.py --season 2024 --synth-odds-moves  # add --clear for a fresh DB
```

## 4) Run queries + export outputs

```bash
python queries.py --export
```

Outputs:
- `query_outputs/all_queries.json`

## (Optional) Semantic search (NewsItem embeddings)

```bash
python scripts/embed_news.py                 # embeds News + Markets; add --include-plays for Plays
python scripts/embed_news.py --q "quarterback injury" --k 5
```

Embed other text-bearing nodes (optional):

```bash
python3 -B embed_news.py --include-plays --limit 500   # embeds Plays too
python3 -B embed_news.py --q "Chiefs spread" --in markets --k 5
```

## (Optional) Part 4.4 (WIP)

Link detection / completeness checking is available as a read-only script (no edge writes):
```bash
python3 link_detection.py --out-dir query_outputs
```

## Data Sources and Provenance

### Kaggle NFL Betting Data
- **Source**: [Kaggle NFL Scores and Betting Data](https://www.kaggle.com/datasets/tobycrabtree/nfl-scores-and-betting-data)
- **Contains**: Spreads, totals, and final scores for NFL games 1966-2025
- **Accuracy**: Lines are within 0.5-1 point of known closing lines
- **Labeling**: `source='kaggle'`, `synthetic=false`

### Synthetic Odds Movement Data
The `--synth-odds-moves` flag generates synthetic opening lines to demonstrate 
temporal schema capabilities. All synthetic data is explicitly flagged:

| Property | Value | Description |
|----------|-------|-------------|
| `synthetic` | `true` | Indicates generated (not real) data |
| `source` | `'generated'` | Provenance marker for data lineage |

**Purpose:** Demonstrate that:
- Odds are modeled as time-indexed entities
- Movement can be queried and linked to events/news
- The schema supports real-time ingestion

**Not claimed:** Statistical validity of correlations. With real historical 
or live odds data, replacing synthetic data is purely an ingestion problem.

### Graph Statistics (2024 Season)
Typical counts with `--pbp-sample 10000`:
```
Play: 9,882              BettingLine: 1,020
Drive: 4,730             Market: 510
Player: 3,215            OddsMovementEvent: 510
InjuryEvent: 6,215       MarketResolutionEvent: 506
NewsItem: 6,820          Game: 285
Team: 36                 Venue: 1
REPORTED_BEFORE: 6,214
```

### Provenance Filtering Examples

**Query real data only** (exclude synthetic):
```cypher
// Get only real closing lines from Kaggle
MATCH (g:Game)-[:HAS_MARKET]->(m:Market)-[:HAS_LINE]->(bl:BettingLine)
WHERE bl.synthetic = false
RETURN g.id, m.market_type, bl.value, bl.timestamp
```

**Query synthetic data only** (for testing):
```cypher
// Get only synthetic opening lines
MATCH (g:Game)-[:HAS_MARKET]->(m:Market)-[:HAS_LINE]->(bl:BettingLine)
WHERE bl.synthetic = true
RETURN g.id, m.market_type, bl.value, bl.timestamp, bl.source
```

**Compare real vs synthetic**:
```cypher
// Opening vs closing line comparison with provenance
MATCH (m:Market)-[:HAS_LINE]->(closing:BettingLine {synthetic: false})
MATCH (m)-[:HAS_LINE]->(opening:BettingLine {synthetic: true})
WHERE opening.timestamp < closing.timestamp
RETURN m.id,
       opening.value AS synthetic_opening,
       closing.value AS real_closing,
       (closing.value - opening.value) AS movement,
       closing.source AS real_source
ORDER BY abs(movement) DESC
LIMIT 10
```

**Filter by data source**:
```cypher
// Get injury events from official reports only
MATCH (i:InjuryEvent)-[:AFFECTS]->(p:Player)
WHERE i.source = 'nfl_data_py'  // Not synthetic
RETURN p.name, i.injury_type, i.reported_at, i.source
ORDER BY i.reported_at DESC
LIMIT 20
```

### Schema Discipline: Observable vs. Heuristic Relationships

This graph follows strict **schema discipline** (per CEO guidance):
- **Observable relationships** store only verifiable facts (game schedules, play-by-play, official rosters)
- **Heuristic relationships** use text matching with confidence scores (news → game links)
- **No speculative causality** is encoded in edges - causality is inferred at query-time

See [ontology_spec.md Section 3.6](ontology_spec.md#36-relationship-classification) for full details.

**Example - Query-time causality vs. stored edges**:

```cypher
// BAD: Encoding speculation in the graph (NOT implemented)
// MATCH (i:InjuryEvent)-[:MAY_IMPACT]->(m:Market)  // ❌ Speculative edge

// GOOD: Infer correlation at query-time (our approach)
MATCH (i:InjuryEvent)-[:AFFECTS]->(p:Player)-[:PLAYS_FOR]->(t:Team)
MATCH (g:Game)-[:HOME_TEAM|AWAY_TEAM]->(t)
MATCH (g)-[:HAS_MARKET]->(m:Market)-[:HAS_ODDS_MOVE]->(om:OddsMovementEvent)
WHERE abs(duration.between(i.reported_at, om.at_time).hours) < 48
RETURN i.injury_type, p.name, om.change_magnitude,
       duration.between(i.reported_at, om.at_time) AS time_gap
ORDER BY om.change_magnitude DESC
// ✅ Temporal correlation without speculation
```

**Why this matters**:
- Graph stores **observable facts** only
- **Downstream models** can infer causality without corrupting the graph
- Queries can test **multiple causality hypotheses** without reloading data
- **Auditability** - you can see exactly how causality is computed
