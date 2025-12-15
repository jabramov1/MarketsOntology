// Constraints
CREATE CONSTRAINT season_id_unique IF NOT EXISTS FOR (s:Season) REQUIRE s.id IS UNIQUE;
CREATE CONSTRAINT team_id_unique IF NOT EXISTS FOR (t:Team) REQUIRE t.id IS UNIQUE;
CREATE CONSTRAINT player_id_unique IF NOT EXISTS FOR (p:Player) REQUIRE p.id IS UNIQUE;
CREATE CONSTRAINT game_id_unique IF NOT EXISTS FOR (g:Game) REQUIRE g.id IS UNIQUE;
CREATE CONSTRAINT drive_id_unique IF NOT EXISTS FOR (d:Drive) REQUIRE d.id IS UNIQUE;
CREATE CONSTRAINT play_id_unique IF NOT EXISTS FOR (p:Play) REQUIRE p.id IS UNIQUE;
CREATE CONSTRAINT market_id_unique IF NOT EXISTS FOR (m:Market) REQUIRE m.id IS UNIQUE;
CREATE CONSTRAINT venue_id_unique IF NOT EXISTS FOR (v:Venue) REQUIRE v.id IS UNIQUE;
CREATE CONSTRAINT bettingline_id_unique IF NOT EXISTS FOR (bl:BettingLine) REQUIRE bl.id IS UNIQUE;
CREATE CONSTRAINT odds_move_id_unique IF NOT EXISTS FOR (om:OddsMovementEvent) REQUIRE om.id IS UNIQUE;
CREATE CONSTRAINT market_res_id_unique IF NOT EXISTS FOR (mr:MarketResolutionEvent) REQUIRE mr.id IS UNIQUE;
CREATE CONSTRAINT news_id_unique IF NOT EXISTS FOR (n:NewsItem) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT injury_id_unique IF NOT EXISTS FOR (i:InjuryEvent) REQUIRE i.id IS UNIQUE;

// Indexes
CREATE INDEX game_start_time IF NOT EXISTS FOR (g:Game) ON (g.start_time);
CREATE INDEX player_name IF NOT EXISTS FOR (p:Player) ON (p.name);
CREATE INDEX team_abbr IF NOT EXISTS FOR (t:Team) ON (t.abbreviation);
CREATE INDEX news_published IF NOT EXISTS FOR (n:NewsItem) ON (n.published_at);
CREATE INDEX odds_move_time IF NOT EXISTS FOR (om:OddsMovementEvent) ON (om.at_time);
CREATE INDEX injury_reported IF NOT EXISTS FOR (i:InjuryEvent) ON (i.reported_at);
