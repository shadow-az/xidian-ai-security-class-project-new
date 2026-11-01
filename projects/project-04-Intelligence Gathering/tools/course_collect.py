"""Small, reproducible course collection using the existing GitHub adapter."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import config
from media_platform.research.core import GithubCrawler


async def main() -> None:
    config.CRAWLER_TYPE = "search"
    config.KEYWORDS = "RAG security"
    config.CRAWLER_MAX_NOTES_COUNT = 5
    config.CRAWLER_MAX_SLEEP_SEC = 1
    rows = []

    class CourseCrawler(GithubCrawler):
        async def _write(self, item, item_type="contents"):
            rows.append(item)

    started = datetime.now(timezone.utc)
    await CourseCrawler().start()
    if not rows:
        raise RuntimeError("GitHub search returned no records; collection is not complete")
    if len(rows) > 5 or any(not row.get("title") or not row.get("url") for row in rows):
        raise ValueError("Unexpected count or missing title/source URL")
    root = Path(__file__).resolve().parents[1]
    output = root / "data/github/jsonl" / f"course_rag_security_{started.strftime('%Y%m%dT%H%M%S%fZ')}.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"started_at": started.isoformat(), "query": config.KEYWORDS,
                      "limit": 5, "count": len(rows), "output": str(output.relative_to(root)),
                      "sources": [row["url"] for row in rows]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
