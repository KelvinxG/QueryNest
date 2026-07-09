from __future__ import annotations

import unittest

from engine import _format_structural_context


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


if __name__ == "__main__":
    unittest.main()