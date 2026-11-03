"""Validate real course records through analysis, SQLite and isolated Markdown export."""
from __future__ import annotations

import asyncio
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


async def main(source_name: str) -> None:
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    os.environ["AI_API_KEY"] = ""  # Rules only, even if a local key exists.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    vault = root / "knowledge/course_validation" / stamp
    (vault / "30-来源/自动采集").mkdir(parents=True)
    os.environ["OBSIDIAN_ACADEMIC_VAULT_PATH"] = str(vault)
    os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
    os.environ["OBSIDIAN_SOCIAL_VAULT_PATH"] = ""
    from pipeline import analysis_service as analysis
    from pipeline import research_intelligence as store

    store.DATA_DIR = root / "data/course_validation" / stamp
    store.DB_PATH = store.DATA_DIR / "research.sqlite"
    source = (root / "data" / source_name).resolve()
    source.relative_to((root / "data").resolve())
    original = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    selected_names = {"CyberSunil/LLMVault", "olegnazarov/rag-security-scanner"}
    selected = [row for row in original if row["title"] in selected_names]
    if len(selected) != 2:
        raise RuntimeError("The two manually selected real sources are unavailable")
    selected_path = source.parent / f"course_selected_{stamp}.jsonl"
    selected_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in selected), encoding="utf-8")
    relative = selected_path.relative_to(root / "data").as_posix()
    result = await analysis.analyze_file(relative, limit=5)
    rows = [json.loads(line) for line in (root / "data" / result["output_file"]).read_text(encoding="utf-8").splitlines()]
    assert result["ai_enabled"] is False
    assert result["input_count"] == result["output_count"] == 2
    originals = {row["url"]: row for row in selected}
    for row in rows:
        original_row = originals[row["source_url"]]
        assert row["title"] == original_row["title"]
        assert row["text"] == original_row["content"]
        assert row["published_at"] == original_row["published_at"], "Publication timestamp lost during normalization"
    notes = list(vault.rglob("*.md"))
    with store._connect() as conn:
        before = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        documents = conn.execute("SELECT * FROM documents").fetchall()
    for doc in documents:
        original_row = originals[doc["source_url"]]
        assert doc["title"] == original_row["title"]
        assert doc["text"] == original_row["content"]
        assert doc["published_at"] == original_row["published_at"]
        assert any(doc["id"] in note.read_text(encoding="utf-8") for note in notes)
    for row in rows:
        assert any(row["source_url"] in note.read_text(encoding="utf-8") for note in notes), "Source missing from Markdown"
    # Exercise the real ingestion path again, with a distinct run identifier.
    store.ingest_analysis(relative, result["output_file"] + ".repeat", rows, result["intelligence"])
    with store._connect() as conn:
        after = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        observations = conn.execute("SELECT COUNT(*) FROM crawl_observations").fetchone()[0]
    assert before == after == 2
    assert observations == 4
    assert len(list(vault.rglob("*.md"))) == 2
    print(json.dumps({"input_count": 2, "output_count": len(rows), "ai_enabled": False,
                      "documents_before_repeat": before, "documents_after_repeat": after,
                      "observations": observations, "markdown_notes": len(list(vault.rglob('*.md'))),
                      "database": str(store.DB_PATH.relative_to(root)), "vault": str(vault.relative_to(root)),
                      "analysis_file": result["output_file"]}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="JSONL path relative to data/")
    args = parser.parse_args()
    asyncio.run(main(args.source))
