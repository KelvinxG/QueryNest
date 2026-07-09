from __future__ import annotations

import logging

from langchain_openai import ChatOpenAI

from config import get_llm_kwargs, get_settings
from graph_db import build_neo4j_manager

logger = logging.getLogger(__name__)


def _format_structural_context(rows: list[dict[str, object]]) -> str:
    if not rows:
        return "No graph context is available yet."

    blocks: list[str] = []
    for row in rows:
        topics = [topic for topic in row.get("topics", []) if isinstance(topic, str)]
        block = "\n".join(
            [
                f"Document ID: {row.get('doc_id', 'unknown')}",
                f"Title: {row.get('title', 'Untitled')}",
                f"Category: {row.get('category', 'Uncategorized')}",
                f"Summary: {row.get('summary', '')}",
                f"Topics: {', '.join(topics) if topics else 'None'}",
            ]
        )
        blocks.append(block)

    return "\n\n".join(blocks)


def query_graph_rag(user_question: str) -> str:
    if not user_question.strip():
        raise ValueError("User question must not be empty.")

    manager = build_neo4j_manager()
    try:
        rows = manager.fetch_structural_context()
        structural_context = _format_structural_context(rows)

        system_prompt = (
            "You are a GraphRAG assistant answering questions using structured enterprise "
            "document relationships from Neo4j. Prefer the supplied graph context over prior "
            "knowledge, cite uncertainty when the graph does not contain enough evidence, and "
            "respond conversationally but precisely.\n\n"
            f"Graph context:\n{structural_context}\n\n"
            f"User question:\n{user_question}"
        )

        llm = ChatOpenAI(
            temperature=0.1,
            **get_llm_kwargs(model=get_settings().OPENAI_LARGE_MODEL),
        )
        response = llm.invoke(system_prompt)
        content = getattr(response, "content", "")
        if isinstance(content, str) and content.strip():
            return content.strip()
        raise RuntimeError("The LLM returned an empty response.")
    except Exception as exc:
        logger.exception("GraphRAG query failed.")
        raise RuntimeError("GraphRAG query failed.") from exc
    finally:
        manager.close()