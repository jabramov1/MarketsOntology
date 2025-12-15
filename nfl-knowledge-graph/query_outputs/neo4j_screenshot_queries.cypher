// ================================================
// Neo4j Graph Visual Results Query
// ================================================

// 1. NODE COUNTS 
MATCH (n) RETURN labels(n)[0] AS type, count(*) AS count ORDER BY count DESC

// 2. RELATIONSHIP COUNTS 
MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS count ORDER BY count DESC

// 3. SCHEMA VISUALIZATION  the diagram
CALL db.schema.visualization()

// 4. SAMPLE GRAPH PATH (for visual demo) 
MATCH path = (p:Player)-[:PLAYS_FOR]->(t:Team)<-[:HOME_TEAM]-(g:Game)-[:HAS_DRIVE]->(d:Drive)-[:HAS_PLAY]->(play:Play)
WHERE t.abbreviation = 'KC'
RETURN path LIMIT 5

// 5. NEWS LINKED TO GAMES 
MATCH path = (n:NewsItem)-[:REFERS_TO_GAME]->(g:Game)
RETURN path LIMIT 10

// 6. INJURY AFFECTS PLAYER 
MATCH path = (i:InjuryEvent)-[:AFFECTS]->(p:Player)-[:PLAYS_FOR]->(t:Team)
RETURN path LIMIT 10
