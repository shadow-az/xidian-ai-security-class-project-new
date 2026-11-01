"""Small, reproducible course collection using the existing GitHub adapter."""
from __future__ import annotations

import asyncio
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import config
from media_platform.research.core import GithubCrawler


async def main(query: str, limit: int) -> None:
    config.CRAWLER_TYPE = "search"
    config.KEYWORDS = query
    config.CRAWLER_MAX_NOTES_COUNT = limit
    config.CRAWLER_MAX_SLEEP_SEC = 1
    rows = []

    class CourseCrawler(GithubCrawler):
        async def _write(self, item, item_type="contents"):
            rows.append(item)

    started = datetime.now(timezone.utc)
    await CourseCrawler().start()
    if not rows:
        raise RuntimeError("GitHub search returned no records; collection is not complete")
    if len(rows) > limit or any(not row.get("title") or not row.get("url") for row in rows):
        raise ValueError("Unexpected count or missing title/source URL")
    if len({row["url"] for row in rows}) != len(rows):
        raise ValueError("Duplicate source URLs in collection")
    root = Path(__file__).resolve().parents[1]
    output = root / "data/github/jsonl" / f"course_rag_security_{started.strftime('%Y%m%dT%H%M%S%fZ')}.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"started_at": started.isoformat(), "query": config.KEYWORDS,
                      "limit": limit, "count": len(rows), "output": str(output.relative_to(root)),
                      "sources": [row["url"] for row in rows]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="topic:rag topic:prompt-injection")
    parser.add_argument("--limit", type=int, choices=range(1, 6), default=5)
    args = parser.parse_args()
    if not args.query.strip() or "," in args.query:
        parser.error("Provide one non-empty query without commas to keep one request per run")
    asyncio.run(main(args.query.strip(), args.limit))
