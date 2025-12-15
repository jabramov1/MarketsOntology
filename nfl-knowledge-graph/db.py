from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from dotenv import load_dotenv
from neo4j import GraphDatabase


@dataclass
class Neo4jConfig:
    uri: str
    username: str
    password: str


class Neo4jConnection:
    def __init__(self, config: Optional[Neo4jConfig] = None):
        load_dotenv()
        if config is None:
            uri = os.getenv("NEO4J_URI", "")
            username = os.getenv("NEO4J_USERNAME", "")
            password = os.getenv("NEO4J_PASSWORD", "")
            if not uri or not username or not password:
                raise ValueError(
                    "Missing Neo4j credentials. Set NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD in .env"
                )
            config = Neo4jConfig(uri=uri, username=username, password=password)

        self.config = config
        self.driver = GraphDatabase.driver(self.config.uri, auth=(self.config.username, self.config.password))

    def close(self) -> None:
        self.driver.close()

    def run(self, cypher: str, parameters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        parameters = parameters or {}
        with self.driver.session() as session:
            result = session.run(cypher, parameters)
            return [r.data() for r in result]

    def run_write(self, cypher: str, parameters: Optional[Dict[str, Any]] = None) -> None:
        parameters = parameters or {}
        with self.driver.session() as session:
            session.execute_write(lambda tx: tx.run(cypher, parameters).consume())

    def run_write_returning(
        self, cypher: str, parameters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Run a write query that returns records (e.g., `RETURN count(*)`)."""
        parameters = parameters or {}

        def _work(tx):
            result = tx.run(cypher, parameters)
            return [r.data() for r in result]

        with self.driver.session() as session:
            return session.execute_write(_work)


if __name__ == "__main__":
    db = Neo4jConnection()
    out = db.run("RETURN 1 AS ok")
    print(out)
    db.close()
