from __future__ import annotations

import logging
from pathlib import Path

from langchain_openai import ChatOpenAI

from config import get_llm_kwargs, get_settings
from graph_db import build_neo4j_manager

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
DOCUMENTATION_FILES = (
    PROJECT_ROOT / "README.md",
    PROJECT_ROOT / "architectural_decision_record.md",
)
MAX_QUERY_COMPLETION_TOKENS = 512


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


def _read_documentation_text() -> str:
    chunks: list[str] = []
    for file_path in DOCUMENTATION_FILES:
        try:
            if file_path.exists():
                chunks.append(file_path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to read documentation file %s.", file_path)

    return "\n\n".join(chunks)


def _derive_capability_lines(documentation_text: str) -> list[str]:
    lowered = documentation_text.lower()
    capabilities: list[str] = []

    if "google sheet" in lowered or "google slide" in lowered:
        capabilities.append("Ask about information extracted from Google Sheets and Google Slides.")
    if "categor" in lowered:
        capabilities.append("Ask which category a document belongs to and why it fits there.")
    if "relationship" in lowered or "relates_to" in lowered:
        capabilities.append("Ask how documents, categories, and topics connect across the graph.")
    if "summary" in lowered:
        capabilities.append("Ask for concise summaries of a document, topic, or category.")

    if not capabilities:
        capabilities.extend(
            [
                "Ask for summaries of documents stored in the graph.",
                "Ask how categories and topics relate to each other.",
            ]
        )

    return capabilities[:4]


def _build_suggested_questions(rows: list[dict[str, object]]) -> list[str]:
    if not rows:
        return [
            "What kinds of documents do you know about right now?",
            "How are documents grouped into categories?",
            "What topics are connected across our Sheets and Slides?",
            "Summarize the most important documents in the graph.",
        ]

    questions: list[str] = []
    first_row = rows[0]
    first_title = str(first_row.get("title") or "the first document")
    first_category = str(first_row.get("category") or "its category")
    first_topics = [topic for topic in first_row.get("topics", []) if isinstance(topic, str)]

    questions.append(f"Summarize the document '{first_title}'.")
    questions.append(f"What documents belong to the '{first_category}' category?")

    if first_topics:
        questions.append(f"Which documents are related to the topic '{first_topics[0]}'?")

    unique_categories = [
        str(row.get("category"))
        for row in rows
        if isinstance(row.get("category"), str) and str(row.get("category")).strip()
    ]
    if len(unique_categories) >= 2:
        questions.append(
            f"How do the '{unique_categories[0]}' and '{unique_categories[1]}' categories differ?"
        )

    titles = [
        str(row.get("title"))
        for row in rows
        if isinstance(row.get("title"), str) and str(row.get("title")).strip()
    ]
    if len(titles) >= 2:
        questions.append(f"How are '{titles[0]}' and '{titles[1]}' related?")

    seen: set[str] = set()
    deduped_questions: list[str] = []
    for question in questions:
        if question not in seen:
            seen.add(question)
            deduped_questions.append(question)

    return deduped_questions[:4]


def generate_usage_guidance() -> str:
    manager = build_neo4j_manager()
    try:
        rows = manager.fetch_structural_context()
        documentation_text = _read_documentation_text()
        capabilities = _derive_capability_lines(documentation_text)
        suggested_questions = _build_suggested_questions(rows)

        capability_block = "\n".join(f"- {line}" for line in capabilities)
        question_block = "\n".join(f"- {question}" for question in suggested_questions)

        return (
            "You can ask me about the documents and relationships stored in the graph.\n\n"
            "What I can help with:\n"
            f"{capability_block}\n\n"
            "Try asking one of these:\n"
            f"{question_block}"
        )
    except Exception as exc:
        logger.exception("Failed to generate usage guidance.")
        raise RuntimeError("Failed to generate usage guidance.") from exc
    finally:
        manager.close()


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
            max_tokens=MAX_QUERY_COMPLETION_TOKENS,
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