"""Synthetic records covering source fields emitted by the research crawlers."""
import pytest

from pipeline.analysis_service import _normalize


@pytest.mark.parametrize("date_fields, expected", [
    ({"published_at": "2024-01-02T03:04:05Z"}, "2024-01-02T03:04:05Z"),
    ({"create_time": 1700000000}, "1700000000"),
    ({"published_at": "", "date": "2024-01-02"}, "2024-01-02"),
    ({}, ""),
])
def test_normalization_preserves_publication_time(date_fields, expected):
    row = {"title": "Synthetic RAG security", "content": "Synthetic source description.",
           "url": "https://example.org/synthetic", **date_fields}
    normalized = _normalize(row)
    assert normalized["published_at"] == expected
    assert normalized["source_url"] == row["url"]
    assert normalized["text"] == row["content"]
