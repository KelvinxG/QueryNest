from __future__ import annotations

import logging
from threading import Lock
from typing import Any

from neo4j import Driver, GraphDatabase
from neo4j.exceptions import Neo4jError

from config import get_settings

logger = logging.getLogger(__name__)


class Neo4jManager:
    def __init__(self, uri: str, user: str, password: str) -> None:
        self._uri = uri
        self._user = user
        self._password = password
        self._driver: Driver = GraphDatabase.driver(self._uri, auth=(self._user, self._password))
        self._lock = Lock()

        try:
            self._driver.verify_connectivity()
        except Exception as exc:
            logger.exception("Failed to connect to Neo4j at %s.", self._uri)
            self._driver.close()
            raise RuntimeError("Failed to connect to Neo4j.") from exc

    def close(self) -> None:
        with self._lock:
            try:
                self._driver.close()
            except Exception as exc:
                logger.exception("Failed to close Neo4j driver cleanly.")
                raise RuntimeError("Failed to close Neo4j driver cleanly.") from exc

    def check_health(self) -> bool:
        try:
            self._driver.verify_connectivity()
            return True
        except Exception as exc:
            logger.exception("Neo4j connectivity check failed.")
            raise RuntimeError("Neo4j connectivity check failed.") from exc

    def save_document_relationships(self, doc_id: str, title: str, metadata: dict[str, Any]) -> None:
        query = """
        MERGE (document:Document {id: $doc_id})
        SET document.title = $title,
            document.summary = $summary,
            document.updated_at = datetime()
        WITH document
        OPTIONAL MATCH (document)-[old_category:BELONGS_TO]->(:Category)
        DELETE old_category
        WITH document
        OPTIONAL MATCH (document)-[old_topic:RELATES_TO]->(:Topic)
        DELETE old_topic
        WITH document
        MERGE (category:Category {name: $category})
        MERGE (document)-[:BELONGS_TO]->(category)
        WITH document
        UNWIND $related_topics AS topic_name
        MERGE (topic:Topic {name: topic_name})
        MERGE (document)-[:RELATES_TO]->(topic)
        """

        try:
            related_topics = [
                topic.strip()
                for topic in metadata.get("related_topics", [])
                if isinstance(topic, str) and topic.strip()
            ]
            parameters = {
                "doc_id": doc_id,
                "title": title,
                "summary": str(metadata.get("summary", "")).strip(),
                "category": str(metadata.get("category", "Uncategorized")).strip() or "Uncategorized",
                "related_topics": related_topics,
            }

            with self._driver.session() as session:
                session.execute_write(lambda tx: tx.run(query, parameters).consume())
        except Neo4jError as exc:
            logger.exception("Neo4j write failed for document %s.", doc_id)
            raise RuntimeError(f"Failed to save document relationships for {doc_id}.") from exc
        except Exception as exc:
            logger.exception("Unexpected error while saving document %s.", doc_id)
            raise RuntimeError(f"Unexpected error while saving document {doc_id}.") from exc

    def fetch_structural_context(self) -> list[dict[str, Any]]:
        query = """
        MATCH (document:Document)
        OPTIONAL MATCH (document)-[:BELONGS_TO]->(category:Category)
        OPTIONAL MATCH (document)-[:RELATES_TO]->(topic:Topic)
        WITH document, category, collect(DISTINCT topic.name) AS topics
        RETURN document.id AS doc_id,
               document.title AS title,
               document.summary AS summary,
               category.name AS category,
               topics AS topics
        ORDER BY title
        """

        try:
            with self._driver.session() as session:
                records = session.run(query)
                return [record.data() for record in records]
        except Neo4jError as exc:
            logger.exception("Neo4j read failed while fetching structural context.")
            raise RuntimeError("Failed to fetch structural context from Neo4j.") from exc
        except Exception as exc:
            logger.exception("Unexpected error while fetching structural context.")
            raise RuntimeError("Unexpected error while fetching structural context from Neo4j.") from exc


def build_neo4j_manager() -> Neo4jManager:
    settings = get_settings()
    return Neo4jManager(
        uri=settings.NEO4J_URI,
        user=settings.NEO4J_USER,
        password=settings.NEO4J_PASSWORD,
    )