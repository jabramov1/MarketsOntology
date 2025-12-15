// ================================================
// Neo4j Browser Screenshot Queries
// Copy-paste these into Neo4j Browser and screenshot the results
// ================================================

// 1. NODE COUNTS - Run this and screenshot
MATCH (n) RETURN labels(n)[0] AS type, count(*) AS count ORDER BY count DESC

// 2. RELATIONSHIP COUNTS - Run this and screenshot  
MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS count ORDER BY count DESC

// 3. SCHEMA VISUALIZATION - Run this and screenshot the diagram
CALL db.schema.visualization()

// 4. SAMPLE GRAPH PATH (for visual demo) - Run this and screenshot
MATCH path = (p:Player)-[:PLAYS_FOR]->(t:Team)<-[:HOME_TEAM]-(g:Game)-[:HAS_DRIVE]->(d:Drive)-[:HAS_PLAY]->(play:Play)
WHERE t.abbreviation = 'KC'
RETURN path LIMIT 5

// 5. NEWS LINKED TO GAMES - Run this and screenshot
MATCH path = (n:NewsItem)-[:REFERS_TO_GAME]->(g:Game)
RETURN path LIMIT 10

// 6. INJURY AFFECTS PLAYER - Run this and screenshot
MATCH path = (i:InjuryEvent)-[:AFFECTS]->(p:Player)-[:PLAYS_FOR]->(t:Team)
RETURN path LIMIT 10

