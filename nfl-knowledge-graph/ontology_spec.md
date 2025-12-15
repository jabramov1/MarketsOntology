# Event & Market Temporal Knowledge Graph
## Ontology Specification for NFL Domain

**Author:** Joseph  
**Date:** December 2025  
**Version:** 1.1

---

## 1. Overview

This document specifies an event-centric temporal ontology for modeling NFL games, participants, betting markets, and news signals. The schema is designed to:

- Unify games, plays, entities (teams, players), markets, odds, and news into one coherent structure
- Encode time correctly with `valid_from`, `valid_to`, and timestamps for all temporal relationships
- Support complex queries for fair value engines, odds movement analysis, and market surfaces
- Generalize across domains (sports → elections → macro events)

---


## 1.1 MVP Scope (Weekend Build)

This weekend build targets an **end-to-end working graph** with clean temporal modeling and queries:

- **Season coverage:** 2024 completed season only (Sep 2024 → Feb 2025)
- **Markets/Odds coverage:** one venue/dataset only (optimize for cleanliness)
- **Betting lines:** store odds as **time-stamped `BettingLine` snapshots** (minimum: one “closing” snapshot per market)
- **Odds movement:** optional (recommended) — generate 1–2 pregame snapshots *flagged `synthetic=true`* so `OddsMovementEvent` queries work end-to-end
- **Stretch (after stability):** add 2023 season and/or a second venue with simple equivalence

## 1.2 Inputs & Data (MVP)

This implementation uses public NFL datasets and a small amount of explicitly flagged synthetic data to make end-to-end temporal queries work:

- **Schedules / teams / rosters / injuries / play-by-play**: `nfl_data_py` (downloaded via `download_data.py`)
- **Markets & lines**: Kaggle NFL scores/betting CSV (`spreadspoke_scores.csv`) → `Market` + time-stamped `BettingLine`
- **Odds movements**: optional synthetic opening snapshots (`synthetic=true`) to demonstrate `OddsMovementEvent` workflows when true time-series odds aren't available
- **News**: deterministic synthetic `NewsItem` rows (`synthetic=true`) linked to games/teams/players/markets to support signal queries

## 2. Core Entities

### 2.1 Event Hierarchy

In the Neo4j MVP, “events” are modeled as first-class labeled nodes (`Season`, `Game`, `Drive`, `Play`, `InjuryEvent`, `OddsMovementEvent`, `MarketResolutionEvent`) rather than a single `:Event` supertype. Each event carries its own timestamp fields, plus provenance fields (e.g., `source`, `source_id`, `ingested_at`, `schema_version`) where applicable.

#### Season

> **Note**: The spec lists Season, Competition, and Tournament as separate entities. For NFL, these concepts collapse into a single Season node since there is one competition per year. The cross-domain section (Section 5) addresses how these would separate for other domains like NCAA tournaments or multi-competition leagues.

| Property | Type | Description |
|----------|------|-------------|
| `id` | String | e.g., "NFL_2024" |
| `year` | Integer | e.g., 2024 |
| `start_date` | Date | Season start (e.g., 2024-09-05) |
| `end_date` | Date | Season end including playoffs (e.g., 2025-02-09) |
| `season_type` | String | REGULAR, PLAYOFF, PRO_BOWL |

#### Game
| Property | Type | Description |
|----------|------|-------------|
| `id` | String | e.g., "NFL_2024_REG_WK1_BAL_KC" |
| `game_id` | String | External reference (nflverse game_id) |
| `week` | Integer | Week number (1-18 regular, 19+ playoffs) |
| `season_type` | String | REG, POST |
| `start_time` | DateTime | Scheduled kickoff |
| `end_time` | DateTime | Game conclusion |
| `stadium` | String | Venue name |
| `home_score` | Integer | Final home score |
| `away_score` | Integer | Final away score |
| `status` | String | SCHEDULED, IN_PROGRESS, FINAL |

#### Drive
| Property | Type | Description |
|----------|------|-------------|
| `id` | String | e.g., "NFL_2024_REG_WK1_BAL_KC_D1" |
| `drive_number` | Integer | Sequential drive number in game |
| `start_time` | DateTime | Drive start |
| `end_time` | DateTime | Drive end |
| `result` | String | TOUCHDOWN, FIELD_GOAL, PUNT, TURNOVER, etc. |
| `plays_count` | Integer | Number of plays in drive |
| `yards_gained` | Integer | Net yards |

#### Play
| Property | Type | Description |
|----------|------|-------------|
| `id` | String | Unique play identifier |
| `play_id` | Integer | External play_id from nflverse |
| `play_type` | String | PASS, RUSH, PUNT, KICKOFF, FIELD_GOAL, etc. |
| `quarter` | Integer | 1-4, 5 for OT |
| `time` | String | Game clock (e.g., "12:34") |
| `down` | Integer | 1-4 |
| `yards_to_go` | Integer | Distance needed |
| `yards_gained` | Integer | Result of play |
| `description` | String | Play-by-play text |
| `timestamp` | DateTime | Actual time of play |
| `is_scoring_play` | Boolean | Did this result in points |
| `is_turnover` | Boolean | Did possession change |

#### InjuryEvent
| Property | Type | Description |
|----------|------|-------------|
| `id` | String | Unique identifier |
| `injury_type` | String | QUESTIONABLE, OUT, IR, etc. |
| `body_part` | String | Knee, shoulder, concussion, etc. |
| `reported_at` | DateTime | When injury was reported (may be synthetic if source date missing) |
| `synthetic` | Boolean | True if timestamp was synthesized |
| `synthetic_reason` | String | Reason for synthesis (nullable) |

---

### 2.2 Participants

#### Team
| Property | Type | Description |
|----------|------|-------------|
| `id` | String | e.g., "NFL_KC" |
| `abbreviation` | String | e.g., "KC" |
| `name` | String | e.g., "Chiefs" |
| `full_name` | String | e.g., "Kansas City Chiefs" |
| `conference` | String | AFC, NFC |
| `division` | String | East, West, North, South |
| `primary_color` | String | Hex color |
| `secondary_color` | String | Hex color |

#### Player
| Property | Type | Description |
|----------|------|-------------|
| `id` | String | e.g., "NFL_P_00-0036442" |
| `gsis_id` | String | Official NFL ID |
| `name` | String | Display name |
| `position` | String | QB, RB, WR, TE, etc. |
| `jersey_number` | Integer | Current number |
| `description` | String | Short text for display/search (e.g., "QB • College: Texas Tech • Jersey: 15") |
| `birth_date` | Date | Date of birth |
| `college` | String | College attended |

---

### 2.3 Markets & Odds

> **Note**: In the MVP implementation, `Market` is the market container and `BettingLine` is a time-stamped quote/snapshot (i.e., “contract at time T”).

#### Market
| Property | Type | Description |
|----------|------|-------------|
| `id` | String | Unique market identifier |
| `market_type` | String | SPREAD, TOTAL (MVP; extensible) |
| `name` | String | Display name for UI/search |
| `description` | String | Human-readable description |

#### BettingLine
| Property | Type | Description |
|----------|------|-------------|
| `id` | String | Unique line identifier |
| `line_type` | String | SPREAD, TOTAL (MVP; extensible) |
| `value` | Float | The line value (e.g., -3.5 for spread) |
| `odds` | Integer | American odds (e.g., -110) |
| `implied_probability` | Float | Calculated probability |
| `timestamp` | DateTime | When this line was captured |
| `synthetic` | Boolean | True if generated (e.g., opening line demo) |
| `synthetic_reason` | String | Reason for synthesis (nullable) |

#### OddsMovementEvent
| Property | Type | Description |
|----------|------|-------------|
| `id` | String | Unique identifier |
| `at_time` | DateTime | When movement occurred |
| `old_odds` | Integer | Previous odds |
| `new_odds` | Integer | Updated odds |
| `old_line` | Float | Previous line (for spreads) |
| `new_line` | Float | Updated line |
| `change_magnitude` | Float | Absolute change size |
| `direction` | String | UP, DOWN |
| `synthetic` | Boolean | True if generated (demo movement) |
| `synthetic_reason` | String | Reason for synthesis (nullable) |

#### MarketResolutionEvent
| Property | Type | Description |
|----------|------|-------------|
| `id` | String | Unique identifier |
| `resolved_at` | DateTime | Settlement time |
| `outcome` | String | WIN, LOSS, PUSH, OVER, UNDER |
| `final_value` | Float | Result value (e.g., margin or total points) |

#### Venue (Sportsbook/Exchange)
| Property | Type | Description |
|----------|------|-------------|
| `id` | String | e.g., "KAGGLE" |
| `name` | String | e.g., "Kaggle" |
| `venue_type` | String | SPORTSBOOK, EXCHANGE, PREDICTION_MARKET |

---

### 2.4 News & Signals

#### NewsItem
| Property | Type | Description |
|----------|------|-------------|
| `id` | String | Unique identifier |
| `headline` | String | Article headline |
| `summary` | String | Brief summary or first paragraph |
| `source` | String | Publisher (ESPN, NFL.com, etc.) |
| `url` | String | Link to article |
| `published_at` | DateTime | Publication timestamp |
| `author` | String | Author name (nullable) |
| `sentiment_score` | Float | Computed sentiment (-1 to 1) |
| `embedding` | Vector | Optional text embedding for similarity search |
| `synthetic` | Boolean | True if generated (demo news) |
| `synthetic_reason` | String | Reason for synthesis (nullable) |

---

## 3. Relationships

### 3.1 Event Relationships

| Relationship | From | To | Cardinality | Properties | Description |
|--------------|------|-----|-------------|------------|-------------|
| `PART_OF_SEASON` | Game | Season | N:1 | | Game belongs to season |
| `HAS_DRIVE` | Game | Drive | 1:N | | Game contains drives |
| `HAS_PLAY` | Drive | Play | 1:N | sequence: Integer | Drive contains ordered plays |
| `HOME_TEAM` | Game | Team | N:1 | | Home team in game |
| `AWAY_TEAM` | Game | Team | N:1 | | Away team in game |

**Optional (not implemented in MVP):** `NEXT_PLAY`, `NEXT_DRIVE` (sequential ordering edges)

### 3.2 Participant Relationships

| Relationship | From | To | Cardinality | Properties | Description |
|--------------|------|-----|-------------|------------|-------------|
| `PLAYS_FOR` | Player | Team | N:1 (temporal) | valid_from: Date, valid_to: Date, valid_to_or_max: Date, jersey_number: Integer | Temporal team membership |
| `PARTICIPATED_IN` | Player | Play | N:N | role: String, yards: Integer | Player involvement in play (role-coded) |
| `PLAYED_IN` | Player | Game | N:N | plays: Integer, yards: Integer | Game-level aggregate derived from participation |

### 3.3 Market Relationships

| Relationship | From | To | Cardinality | Properties | Description |
|--------------|------|-----|-------------|------------|-------------|
| `HAS_MARKET` | Game | Market | 1:N | | Game has associated markets |
| `QUOTED_ON` | Market | Venue | N:N | | Market available at venue |
| `HAS_LINE` | Market | BettingLine | 1:N | | Time-stamped line snapshots |
| `HAS_ODDS_MOVE` | Market | OddsMovementEvent | 0..N | | Odds/line movement events (synthetic optional) |
| `RESOLVED_BY` | Market | MarketResolutionEvent | 0..1 | | Market settlement |

**Optional (not implemented in MVP):** `FOR_PARTICIPANT` (market explicitly about a team/player; redundant with Game→Team path for game markets)

### 3.4 News Relationships

| Relationship | From | To | Cardinality | Properties | Description |
|--------------|------|-----|-------------|------------|-------------|
| `REFERS_TO_GAME` | NewsItem | Game | N:N | confidence: Float | News about game |
| `REFERS_TO_PLAYER` | NewsItem | Player | N:N | confidence: Float | News mentions player |
| `REFERS_TO_TEAM` | NewsItem | Team | N:N | confidence: Float | News mentions team |
| `REFERS_TO_MARKET` | NewsItem | Market | N:N | confidence: Float | News about market |

### 3.5 Injury Relationships

| Relationship | From | To | Cardinality | Properties | Description |
|--------------|------|-----|-------------|------------|-------------|
| `AFFECTS` | InjuryEvent | Player | N:1 | | Player is injured |
| `REPORTED_BEFORE` | InjuryEvent | Game | 0..1 | days_before: Integer | Injury reported before the player's next game |

### 3.6 Relationship Classification

This section distinguishes relationships that are **ground truth / derived** vs. **heuristic linkage**.

#### Observable + Derived (MVP)

- **Schedule / structure:** `PART_OF_SEASON`, `HOME_TEAM`, `AWAY_TEAM` (and, if play-by-play is loaded, `HAS_DRIVE`, `HAS_PLAY`)
- **Participants:** `PLAYS_FOR` (season-level snapshot), `PARTICIPATED_IN` (optional), `PLAYED_IN` (derived)
- **Markets:** `HAS_MARKET`, `QUOTED_ON`, `HAS_LINE`, `RESOLVED_BY`
- **Injuries:** `AFFECTS`, `REPORTED_BEFORE` (links each injury to the player's next game)

Some records are **synthetic** to keep end-to-end demos runnable (optional `OddsMovementEvent` demo moves, fallback injury timestamps, and deterministic synthetic news). Synthetic records are explicitly flagged (`synthetic=true`, `synthetic_reason=...`).

#### Heuristic Relationships (Inferred Linkage)

These relationships use lightweight rules/metadata and carry a confidence score:

| Relationship | Method | Confidence |
|--------------|--------|------------|
| `REFERS_TO_GAME` | News row references `game_id` | 0.7 |
| `REFERS_TO_TEAM` | News row references team abbr | 0.6 |
| `REFERS_TO_PLAYER` | News row references player id | 0.6 |
| `REFERS_TO_MARKET` | News row references market id | 0.8 |

The ontology does not encode speculative causal edges (e.g., `MAY_EXPLAIN`, `MAY_IMPACT`). Instead, infer correlation at query-time using temporal windows, e.g.:

```cypher
// Infer causality at query-time
MATCH (i:InjuryEvent)-[:AFFECTS]->(p:Player)-[:PLAYS_FOR]->(t:Team)
MATCH (g:Game)-[:HOME_TEAM|AWAY_TEAM]->(t)
MATCH (g)-[:HAS_MARKET]->(m:Market)-[:HAS_ODDS_MOVE]->(om:OddsMovementEvent)
WHERE abs(duration.inSeconds(i.reported_at, om.at_time).seconds) < 48 * 3600
RETURN i, om, duration.inSeconds(i.reported_at, om.at_time) AS time_gap
// This computes correlation WITHOUT storing a speculative edge
```

---

## 4. Temporal Modeling

### 4.1 Temporal Relationship Pattern

For relationships that change over time (e.g., player-team affiliations), we use:

```
(player:Player)-[:PLAYS_FOR {valid_from: date, valid_to: date}]->(team:Team)
```

- `valid_from`: When the relationship became true (required)
- `valid_to`: When the relationship ended (null = current)
- `valid_to_or_max`: Convenience field for queries (`valid_to` or `9999-12-31` when open-ended)
- **Semantics:** treat team membership as a half-open interval `[valid_from, valid_to_or_max)` (inclusive start, exclusive end)
- **MVP data note:** the default roster input is season-level, so most `PLAYS_FOR.valid_to` values are null (no mid-season trade feed loaded)

### 4.2 Point-in-Time Queries

To find state at a specific moment:

```cypher
MATCH (p:Player)-[r:PLAYS_FOR]->(t:Team)
WHERE r.valid_from <= date('2024-11-15') 
  AND r.valid_to_or_max > date('2024-11-15')
RETURN p, t
```

### 4.3 Event Timestamps

All events have precise timestamps:

| Entity | Timestamp Field | Precision |
|--------|-----------------|-----------|
| Game | start_time, end_time | Minute |
| Play | timestamp | Second |
| OddsMovementEvent | at_time | Second |
| NewsItem | published_at | Minute |
| InjuryEvent | reported_at | Minute |

### 4.4 Temporal Sequences

The schema supports temporal sequence queries:

```
Game → Drive → Play → OddsMovementEvent
         ↓
    NewsItem (within time window)
```

---

## 5. Cross-Domain Generalization

### 5.1 Abstract Event Model

The schema is designed to generalize. Core abstractions:

| NFL Concept | Abstract Concept | Elections Equivalent | Macro Equivalent |
|-------------|------------------|---------------------|------------------|
| Season | Competition | ElectionCycle | FiscalYear |
| Game | Event | ElectionDay, Debate | EconomicRelease |
| Team | Participant | Candidate, Party | CentralBank, Country |
| Player | Actor | Politician | Official |
| Drive/Play | SubEvent | PollRelease, Speech | DataPoint |
| Market | Market | PredictionMarket | FuturesContract |
| Sportsbook | Venue | Kalshi, Polymarket | CME, Exchange |
| InjuryEvent | ImpactEvent | Scandal, Endorsement | PolicyChange |

### 5.2 NFL → NBA Extension

Minimal changes required:

| Change | Description |
|--------|-------------|
| Remove Drive | NBA has no drive concept |
| Add Quarter node | More granular than NFL quarters |
| Modify Play types | SHOT, REBOUND, ASSIST, TURNOVER, FOUL |
| Player stats | Different stat categories |

Schema remains 95% identical.

### 5.3 NFL → Elections Extension

| NFL Entity | Elections Entity |
|------------|------------------|
| Season | ElectionCycle (2024 Presidential) |
| Game | Event (Debate, Primary, ElectionDay) |
| Team | Party |
| Player | Candidate |
| Play | PollRelease, Speech, Endorsement |
| Market | PredictionMarket (Kalshi contract) |
| BettingLine | ContractPrice |
| InjuryEvent | ScandalEvent, GaffeEvent |
| NewsItem | NewsItem (unchanged) |

### 5.4 Cross-Domain Notes (Short)

The reusable pattern is: time-stamped events + time-bounded affiliations + market price snapshots + linked text signals. Porting to a new domain mostly swaps entity labels and role vocabularies; the temporal join patterns stay identical.

---

## 6. ID Space Design

Following AsteraCode ID conventions:

| Entity | ID Format | Example |
|--------|-----------|---------|
| Season | `{LEAGUE}_{YEAR}` | NFL_2024 |
| Team | `{LEAGUE}_{ABBR}` | NFL_KC |
| Player | `{LEAGUE}_P_{GSIS_ID}` | NFL_P_00-0036442 |
| Game | `{LEAGUE}_{YEAR}_{TYPE}_{WEEK}_{AWAY}_{HOME}` | NFL_2024_REG_WK1_BAL_KC |
| Drive | `{GAME_ID}_D{N}` | NFL_2024_REG_WK1_BAL_KC_D1 |
| Play | `{GAME_ID}_P{PLAY_ID}` | NFL_2024_REG_WK1_BAL_KC_P42 |
| Market | `{GAME_ID}_M_SPREAD_FAV` or `{GAME_ID}_M_TOTAL` | NFL_2024_REG_WK1_BAL_KC_M_TOTAL |
| BettingLine | `{MARKET_ID}_L_CLOSING` (and `_L_OPEN` if synthetic) | NFL_2024_REG_WK1_BAL_KC_M_TOTAL_L_CLOSING |
| OddsMovementEvent | `{MARKET_ID}_OM{N}` | NFL_2024_REG_WK1_BAL_KC_M_TOTAL_OM1 |
| MarketResolutionEvent | `{MARKET_ID}_RES` | NFL_2024_REG_WK1_BAL_KC_M_TOTAL_RES |
| Venue | `{NAME_UPPER}` | KAGGLE |
| InjuryEvent | `INJ_{YEAR}_{GSIS_ID}_{REPORTED_AT}` | INJ_2024_00-0036442_2024-10-01T12:00:00+00:00 |
| NewsItem | `NEWS_{HASH}` | NEWS_a1b2c3d4e5 |

---

## 7. Schema Diagram

```
                                    ┌─────────────┐
                                    │   Season    │
                                    └──────┬──────┘
                                           │ PART_OF_SEASON
                                           ▼
┌─────────────┐   HOME_TEAM    ┌─────────────┐    HAS_MARKET    ┌─────────────┐
│    Team     │◄───────────────│    Game     │─────────────────►│   Market    │
└──────┬──────┘   AWAY_TEAM    └──────┬──────┘                  └──────┬──────┘
       │                              │                                │
       │ PLAYS_FOR*                   │ HAS_DRIVE                      │ QUOTED_ON
       │                              ▼                                ▼
┌──────┴──────┐              ┌─────────────┐                   ┌─────────────┐
│   Player    │              │    Drive    │                   │    Venue    │
└──────┬──────┘              └──────┬──────┘                   └─────────────┘
       │                            │                                 
       │ AFFECTS                    │ HAS_PLAY                        │
       │                            ▼                                 │ HAS_ODDS_MOVE
┌──────┴──────┐              ┌─────────────┐                          ▼
│ InjuryEvent │              │    Play     │                   ┌─────────────┐
└─────────────┘              └─────────────┘                   │OddsMovement │
                                    ▲                          └──────┬──────┘
                                    │                                 │
                                    │ REFERS_TO                       │ (query-time inference)
                                    │                                 │
                             ┌──────┴──────┐◄─────────────────────────┘
                             │  NewsItem   │
                             └─────────────┘

* PLAYS_FOR has temporal properties: valid_from, valid_to, valid_to_or_max
```

---

## 8. Example Queries

### 8.1 Recent injuries affecting team's implied probability

```cypher
MATCH (i:InjuryEvent)-[:AFFECTS]->(p:Player)-[r:PLAYS_FOR]->(t:Team),
      (g:Game)-[:HOME_TEAM|AWAY_TEAM]->(t),
      (g)-[:HAS_MARKET]->(m:Market)-[:HAS_ODDS_MOVE]->(om:OddsMovementEvent)
WHERE i.reported_at < g.start_time
  AND i.reported_at > g.start_time - duration('P7D')
  AND r.valid_from <= date(g.start_time)
  AND r.valid_to_or_max > date(g.start_time)
RETURN i, p, t, g, om
ORDER BY i.reported_at DESC
```

### 8.2 Odds movement explanations via nearby news

```cypher
MATCH (om:OddsMovementEvent)<-[:HAS_ODDS_MOVE]-(m:Market)<-[:HAS_MARKET]-(g:Game),
      (n:NewsItem)-[:REFERS_TO_GAME]->(g)
WHERE abs(duration.inSeconds(n.published_at, om.at_time).seconds) < 120 * 60
RETURN n.headline, om.old_odds, om.new_odds, om.at_time,
       toFloat(duration.inSeconds(n.published_at, om.at_time).seconds) / 60.0 AS minutes_before
ORDER BY om.at_time DESC
```

### 8.3 Drives leading to scoring and market reactions

```cypher
MATCH (g:Game)-[:HAS_DRIVE]->(d:Drive)-[:HAS_PLAY]->(p:Play),
      (g)-[:HAS_MARKET]->(m:Market)-[:HAS_ODDS_MOVE]->(om:OddsMovementEvent)
WHERE d.result IN ['TOUCHDOWN', 'FIELD_GOAL']
  AND om.at_time > d.end_time
  AND om.at_time < d.end_time + duration('PT5M')
RETURN g.id, d.drive_number, d.result, p.description, 
       om.old_odds, om.new_odds
ORDER BY g.start_time, d.drive_number
```

### 8.4 Player trade impact on team markets

```cypher
// Requires multiple PLAYS_FOR stints (e.g., trade feed); season-level rosters won't produce this.
MATCH (p:Player)-[r1:PLAYS_FOR]->(t1:Team),
      (p)-[r2:PLAYS_FOR]->(t2:Team),
      (g:Game)-[:HOME_TEAM|AWAY_TEAM]->(t2),
      (g)-[:HAS_MARKET]->(m:Market)
WHERE r1.valid_to = r2.valid_from
  AND date(g.start_time) >= r2.valid_from
  AND date(g.start_time) < r2.valid_from + duration('P30D')
RETURN p.name, t1.name AS from_team, t2.name AS to_team, 
       r2.valid_from AS trade_date, g.id, m.id
```

---

## 9. Implementation Notes

- Constraints + standard indexes are defined in `schema.cypher` and applied by `load_data.py`.
- **Indexes (MVP):** `Game.start_time`, `Player.name`, `Team.abbreviation`, `NewsItem.published_at`, `OddsMovementEvent.at_time`, `InjuryEvent.reported_at`.
- **Uniqueness constraints (MVP):** unique `id` for `Season`, `Team`, `Player`, `Game`, `Drive`, `Play`, `Market`, `Venue`, `BettingLine`, `OddsMovementEvent`, `MarketResolutionEvent`, `NewsItem`, `InjuryEvent`.
- **Vector index (optional):** created by `embed_news.py` for `NewsItem.embedding` (384 dims, cosine).

---

## 10. Appendix: Property Type Reference

| Type | Neo4j Type | Example |
|------|------------|---------|
| String | String | "Kansas City Chiefs" |
| Integer | Integer | 42 |
| Float | Float | -3.5 |
| Boolean | Boolean | true |
| Date | Date | date('2024-09-05') |
| DateTime | DateTime | datetime('2024-09-05T20:15:00Z') |
| Duration | Duration | duration('PT2H30M') |
| Vector | List<Float> | [0.1, 0.2, ...] |
| Map | Map | {yards: 10, touchdowns: 1} |
