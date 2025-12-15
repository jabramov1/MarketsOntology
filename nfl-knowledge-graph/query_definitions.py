from __future__ import annotations

from typing import Dict

QUERIES: Dict[str, str] = {
    # 1
    "injuries_affecting_odds_moves": """
        MATCH (i:InjuryEvent)-[:AFFECTS]->(p:Player)-[r:PLAYS_FOR]->(t:Team),
              (g:Game)-[:HOME_TEAM|AWAY_TEAM]->(t),
              (g)-[:HAS_MARKET]->(m:Market)-[:HAS_ODDS_MOVE]->(om:OddsMovementEvent)
        WHERE i.reported_at < g.start_time
          AND i.reported_at > g.start_time - duration('P7D')
          AND r.valid_from <= date(g.start_time)
          AND r.valid_to_or_max > date(g.start_time)
        RETURN i.id AS injury_id, p.name AS player, t.abbreviation AS team, g.id AS game,
               om.old_line AS old_line, om.new_line AS new_line, om.at_time AS moved_at
        ORDER BY i.reported_at DESC
        LIMIT 50
    """,
    # 2
    "odds_moves_explained_by_nearby_news": """
        MATCH (om:OddsMovementEvent)<-[:HAS_ODDS_MOVE]-(m:Market)<-[:HAS_MARKET]-(g:Game),
              (n:NewsItem)-[:REFERS_TO_GAME]->(g)
        // Use inSeconds().seconds for TOTAL seconds (duration.between().minutes is only the minutes component)
        WHERE abs(duration.inSeconds(n.published_at, om.at_time).seconds) < 7200 * 60
        RETURN g.id AS game, m.id AS market, n.headline AS headline,
               om.old_line AS old_line, om.new_line AS new_line, om.at_time AS moved_at,
               toFloat(duration.inSeconds(n.published_at, om.at_time).seconds) / 60.0 AS minutes_before
        ORDER BY om.at_time DESC
        LIMIT 50
    """,
    # 3
    "point_in_time_roster": """
        MATCH (p:Player)-[r:PLAYS_FOR]->(t:Team)
        WHERE r.valid_from <= date(datetime($as_of))
          AND r.valid_to_or_max > date(datetime($as_of))
        RETURN t.abbreviation AS team, count(p) AS players
        ORDER BY players DESC
        LIMIT 32
    """,
    # 4
    "market_resolution_vs_closing_line": """
        MATCH (g:Game)-[:HAS_MARKET]->(m:Market)-[:HAS_LINE]->(bl:BettingLine),
              (m)-[:RESOLVED_BY]->(mr:MarketResolutionEvent)
        WHERE bl.synthetic = false AND m.market_type IN ['SPREAD','TOTAL']
        RETURN g.id AS game, m.market_type AS market_type, bl.value AS closing_line,
               mr.outcome AS outcome, mr.final_value AS final_value
        ORDER BY g.start_time DESC
        LIMIT 50
    """,
    # 5
    "largest_line_moves": """
        MATCH (m:Market)-[:HAS_ODDS_MOVE]->(om:OddsMovementEvent)
        RETURN m.id AS market, om.old_line AS old_line, om.new_line AS new_line,
               om.change_magnitude AS magnitude, om.direction AS direction, om.synthetic AS synthetic
        ORDER BY magnitude DESC
        LIMIT 25
    """,
    # 6
    "news_sentiment_vs_move_direction": """
        MATCH (om:OddsMovementEvent)<-[:HAS_ODDS_MOVE]-(m:Market)<-[:HAS_MARKET]-(g:Game),
              (n:NewsItem)-[:REFERS_TO_GAME]->(g)
        WHERE abs(duration.inSeconds(n.published_at, om.at_time).seconds) < 240 * 60
        RETURN om.direction AS direction,
               avg(n.sentiment_score) AS avg_sentiment,
               count(*) AS samples
        ORDER BY samples DESC
    """,
    # 7
    "teams_outperforming_spread": """
        MATCH (m:Market {market_type:'SPREAD'})-[:RESOLVED_BY]->(mr:MarketResolutionEvent),
              (m)<-[:HAS_MARKET]-(g:Game)-[:HOME_TEAM]->(home:Team),
              (g)-[:AWAY_TEAM]->(away:Team)
        RETURN mr.outcome AS outcome, count(*) AS games
        ORDER BY games DESC
    """,
    # 8
    "over_under_misses": """
        MATCH (m:Market {market_type:'TOTAL'})-[:HAS_LINE]->(bl:BettingLine),
              (m)-[:RESOLVED_BY]->(mr:MarketResolutionEvent)
        WHERE bl.synthetic = false
        RETURN m.id AS market, bl.value AS total_line, mr.final_value AS total_points,
               (mr.final_value - bl.value) AS diff
        ORDER BY abs(diff) DESC
        LIMIT 25
    """,
    # 9
    "college_connections_cross_team": """
        MATCH (p1:Player), (p2:Player)
        WHERE p1.college IS NOT NULL AND p1.college = p2.college AND p1.id < p2.id
        MATCH (p1)-[:PLAYS_FOR]->(t1:Team)
        MATCH (p2)-[:PLAYS_FOR]->(t2:Team)
        WHERE t1.id <> t2.id
        RETURN p1.college AS college, t1.abbreviation AS team1, t2.abbreviation AS team2,
               collect(p1.name)[0] AS example1, collect(p2.name)[0] AS example2
        LIMIT 25
    """,
    # 10
    "markets_by_venue": """
        MATCH (m:Market)-[:QUOTED_ON]->(v:Venue)
        RETURN v.id AS venue, m.market_type AS market_type, count(*) AS markets
        ORDER BY markets DESC
    """,
    # 11
    "odds_moves_with_no_nearby_news": """
        MATCH (om:OddsMovementEvent)<-[:HAS_ODDS_MOVE]-(m:Market)<-[:HAS_MARKET]-(g:Game)
        WHERE NOT EXISTS {
            MATCH (n:NewsItem)-[:REFERS_TO_GAME]->(g)
            WHERE abs(duration.inSeconds(n.published_at, om.at_time).seconds) < 240 * 60
        }
        RETURN g.id AS game, m.id AS market, om.change_magnitude AS magnitude, om.at_time AS moved_at
        ORDER BY magnitude DESC
        LIMIT 50
    """,
    # 12 - Player Injury Impact on Spreads (Query-Time Causality Inference)
    "player_injury_impact": """
        MATCH (i:InjuryEvent)-[:AFFECTS]->(p:Player)-[:PLAYS_FOR]->(t:Team)
        MATCH (i)-[:REPORTED_BEFORE]->(g:Game)-[:HOME_TEAM|AWAY_TEAM]->(t)
        MATCH (g)-[:HAS_MARKET]->(m:Market {market_type: 'SPREAD'})-[:HAS_ODDS_MOVE]->(om:OddsMovementEvent)
        WHERE abs(duration.inSeconds(i.reported_at, om.at_time).seconds) < 48 * 3600
        WITH p.position AS position, i.injury_type AS injury,
             toFloat(duration.inSeconds(i.reported_at, om.at_time).seconds) / 3600.0 AS hours_after,
             om.change_magnitude AS magnitude,
             om.direction AS direction,
             collect(DISTINCT p.name)[0..3] AS example_players
        RETURN position, injury,
               avg(magnitude) AS avg_movement,
               count(*) AS sample_size,
               example_players
        ORDER BY avg_movement DESC
        LIMIT 25
    """,
    # 13 - Temporal Event Sequences (Timeline Reconstruction)
    "temporal_event_sequences": """
        MATCH (om:OddsMovementEvent)<-[:HAS_ODDS_MOVE]-(m:Market)<-[:HAS_MARKET]-(g:Game)
        WHERE om.change_magnitude > 2.0

        OPTIONAL MATCH (n:NewsItem)-[:REFERS_TO_GAME]->(g)
        WHERE n.published_at > om.at_time - duration('PT24H')
          AND n.published_at < om.at_time

        OPTIONAL MATCH (i:InjuryEvent)-[:REPORTED_BEFORE]->(g)
        WHERE i.reported_at > om.at_time - duration('PT24H')
          AND i.reported_at < om.at_time

        WITH om, g, m,
             collect(DISTINCT {type: 'news', time: n.published_at, data: n.headline}) AS news_events,
             collect(DISTINCT {type: 'injury', time: i.reported_at, data: i.injury_type}) AS injury_events

        WITH om, g, m, news_events + injury_events AS all_events
        UNWIND all_events AS event
        WITH om, g, m, event
        WHERE event.time IS NOT NULL

        RETURN g.id AS game,
               m.market_type AS market,
               om.change_magnitude AS movement,
               event.type AS event_type,
               toString(event.time) AS event_time,
               event.data AS event_data,
               toFloat(duration.inSeconds(event.time, om.at_time).seconds) / 3600.0 AS hours_before_move
        ORDER BY g.id, hours_before_move ASC
        LIMIT 100
    """,
    # 14 - Market Surface Construction (Odds Evolution Over Time)
    "market_surface_construction": """
        MATCH (g:Game)-[:HAS_MARKET]->(m:Market {market_type: 'SPREAD'})-[:HAS_LINE]->(bl:BettingLine)
        // Use total hours (duration.between().hours is only the hours component)
        WITH g, m, bl, toFloat(duration.inSeconds(bl.timestamp, g.start_time).seconds) / 3600.0 AS hours_before
        WHERE hours_before >= 0 AND hours_before <= 168

        WITH toInteger(hours_before / 24) AS days_before,
             bl.value AS line_value,
             bl.synthetic AS is_synthetic

        RETURN days_before,
               avg(line_value) AS avg_line,
               stdev(line_value) AS line_stddev,
               count(*) AS data_points,
               sum(CASE WHEN is_synthetic THEN 1 ELSE 0 END) AS synthetic_count
        ORDER BY days_before DESC
    """,
    # 15 - Capstone: Point-in-Time Snapshot with Full Provenance (Zero Temporal Leakage)
    "capstone_as_of_snapshot": """
        // Capstone: Complete market context at point-in-time T with zero temporal leakage
        // Pass $as_of as ISO datetime string (e.g., "2024-11-15T12:00:00+00:00")
        MATCH (g:Game)-[:HAS_MARKET]->(m:Market)-[:HAS_LINE]->(bl:BettingLine)
        WHERE g.start_time > datetime($as_of)               // Games in the future at T
          AND bl.timestamp <= datetime($as_of)              // Line exists at T

        // Find the LATEST betting line at or before T
        WITH g, m, bl
        ORDER BY bl.timestamp DESC
        WITH g, m, collect(bl)[0] AS latest_line

        // Find injuries reported BEFORE T
        OPTIONAL MATCH (i:InjuryEvent)-[:AFFECTS]->(p:Player)-[r:PLAYS_FOR]->(t:Team),
                       (g)-[:HOME_TEAM|AWAY_TEAM]->(t)
        WHERE i.reported_at <= datetime($as_of)
          AND i.reported_at > g.start_time - duration('P7D')
          AND r.valid_from <= date(datetime($as_of))
          AND r.valid_to_or_max > date(datetime($as_of))

        // Find news published BEFORE T
        OPTIONAL MATCH (n:NewsItem)-[:REFERS_TO_GAME]->(g)
        WHERE n.published_at <= datetime($as_of)
          AND n.published_at > g.start_time - duration('P7D')

        // Find odds movements BEFORE T
        OPTIONAL MATCH (m)-[:HAS_ODDS_MOVE]->(om:OddsMovementEvent)
        WHERE om.at_time <= datetime($as_of)
          AND om.at_time > g.start_time - duration('P7D')

        RETURN
          g.id AS game_id,
          g.start_time AS game_start,
          g.source AS game_source,
          g.ingested_at AS game_ingested_at,
          m.market_type AS market_type,
          latest_line.value AS current_line,
          latest_line.timestamp AS line_as_of,
          latest_line.synthetic AS line_is_synthetic,
          latest_line.synthetic_reason AS line_synthetic_reason,
          latest_line.source AS line_source,
          latest_line.ingested_at AS line_ingested_at,
          collect(DISTINCT {
            player: p.name,
            injury_type: i.injury_type,
            body_part: i.body_part,
            reported_at: i.reported_at,
            synthetic: coalesce(i.synthetic, false),
            synthetic_reason: i.synthetic_reason,
            source: i.source,
            ingested_at: i.ingested_at
          }) AS injuries,
          collect(DISTINCT {
            headline: n.headline,
            published_at: n.published_at,
            source: n.source,
            sentiment: n.sentiment_score,
            synthetic: coalesce(n.synthetic, false),
            synthetic_reason: n.synthetic_reason,
            ingested_at: n.ingested_at
          }) AS news,
          collect(DISTINCT {
            old_line: om.old_line,
            new_line: om.new_line,
            at_time: om.at_time,
            direction: om.direction,
            synthetic: om.synthetic,
            synthetic_reason: om.synthetic_reason,
            source: om.source,
            ingested_at: om.ingested_at
          }) AS odds_moves
        ORDER BY g.start_time ASC
        LIMIT 50
    """,
}
