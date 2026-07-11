from __future__ import annotations

import unittest
from unittest.mock import patch

from engine import _build_suggested_questions, _format_structural_context, generate_usage_guidance


class StructuralContextFormattingTests(unittest.TestCase):
    def test_returns_placeholder_when_no_rows_exist(self) -> None:
        self.assertEqual(_format_structural_context([]), "No graph context is available yet.")

    def test_formats_documents_into_readable_blocks(self) -> None:
        rows = [
            {
                "doc_id": "doc-1",
                "title": "Roadmap",
                "category": "Strategy",
                "summary": "Quarterly plans.",
                "topics": ["planning", "budget"],
            },
            {
                "doc_id": "doc-2",
                "title": "Ops",
                "category": "Operations",
                "summary": "Runbook.",
                "topics": [],
            },
        ]

        result = _format_structural_context(rows)

        self.assertIn("Document ID: doc-1", result)
        self.assertIn("Title: Roadmap", result)
        self.assertIn("Topics: planning, budget", result)
        self.assertIn("Document ID: doc-2", result)
        self.assertIn("Topics: None", result)


class SuggestedQuestionsTests(unittest.TestCase):
    def test_build_suggested_questions_uses_graph_rows(self) -> None:
        rows = [
            {
                "doc_id": "doc-1",
                "title": "Roadmap",
                "category": "Strategy",
                "summary": "Quarterly plans.",
                "topics": ["planning", "budget"],
            },
            {
                "doc_id": "doc-2",
                "title": "Ops Plan",
                "category": "Operations",
                "summary": "Execution details.",
                "topics": ["budget"],
            },
        ]

        result = _build_suggested_questions(rows)

        self.assertTrue(any("Roadmap" in question for question in result))
        self.assertTrue(any("Strategy" in question for question in result))
        self.assertTrue(any("planning" in question for question in result))

    def test_generate_usage_guidance_includes_capabilities_and_examples(self) -> None:
        rows = [
            {
                "doc_id": "doc-1",
                "title": "Roadmap",
                "category": "Strategy",
                "summary": "Quarterly plans.",
                "topics": ["planning"],
            }
        ]

        with patch("engine.build_neo4j_manager") as build_manager:
            manager = build_manager.return_value
            manager.fetch_structural_context.return_value = rows
            with patch(
                "engine._read_documentation_text",
                return_value="Summaries, categories, relationships, Google Sheets and Google Slides.",
            ):
                result = generate_usage_guidance()

        self.assertIn("What I can help with", result)
        self.assertIn("Try asking one of these", result)
        self.assertIn("Google Sheets and Google Slides", result)
        manager.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
