"""Synthetic records only; run with unittest without crawler dependencies."""
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

from pipeline import research_intelligence as store


class ResearchDeduplicationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(dir=Path.cwd())))
        self.stack.enter_context(patch.object(store, "DATA_DIR", root))
        self.stack.enter_context(patch.object(store, "DB_PATH", root / "test.sqlite"))
        original_connect = store._connect

        @contextmanager
        def connect():
            conn = original_connect()
            try:
                with conn:
                    yield conn
            finally:
                conn.close()

        self.stack.enter_context(patch.object(store, "_connect", connect))
        self.stack.enter_context(patch.object(store, "refresh_trends", return_value=[]))
        self.stack.enter_context(patch.object(store, "upsert_candidates", return_value=0))
        self.stack.enter_context(patch.object(store, "sync_obsidian", return_value={}))

    def ingest(self, ordinal, **changes):
        item = {"title": "RAG security", "text": "Synthetic prompt injection evidence.",
                "source_url": "https://example.org/synthetic", "source_platform": "github"}
        item.update(changes)
        store.ingest_analysis(f"github/batch{ordinal}.jsonl", f"analysis/{ordinal}.jsonl", [item], {})

    def count_documents(self):
        with store._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]

    def test_whitespace_variants_across_batches_share_document(self):
        self.ingest(1)
        self.ingest(2, title="RAG  security", text="Synthetic\nprompt\t injection evidence.")
        self.assertEqual(self.count_documents(), 1)
        with store._connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM crawl_observations").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT SUM(is_new) FROM crawl_observations").fetchone()[0], 1)

    def test_identical_record_is_idempotent(self):
        self.ingest(1)
        self.ingest(2)
        self.assertEqual(self.count_documents(), 1)

    def test_same_file_can_be_ingested_twice_in_one_second(self):
        with patch.object(store, "_now_text", return_value="2026-11-01T12:00:00+00:00"):
            self.ingest(1)
            self.ingest(1)
        self.assertEqual(self.count_documents(), 1)
        with store._connect() as conn:
            for table in ("analysis_runs", "crawl_observations", "sync_runs"):
                self.assertEqual(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 2)

    def test_different_content_or_source_is_retained(self):
        self.ingest(1)
        self.ingest(2, text="Synthetic prompt injection defense.")
        self.ingest(3, source_url="https://example.org/another-source")
        self.assertEqual(self.count_documents(), 3)

    def test_case_and_punctuation_are_not_discarded(self):
        self.ingest(1)
        self.ingest(2, text="Synthetic prompt injection evidence!")
        self.ingest(3, text="SYNTHETIC prompt injection evidence.")
        self.assertEqual(self.count_documents(), 3)


if __name__ == "__main__":
    unittest.main()
