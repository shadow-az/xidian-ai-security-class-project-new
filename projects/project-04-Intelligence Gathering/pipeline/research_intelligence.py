"""Persistent research-intelligence store and Obsidian export.

The SQLite database is the machine-readable source of truth.  Obsidian files are
derived, human-readable views that retain stable IDs back to this database.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pipeline.topic_taxonomy import canonical_topic, topic_catalog
from pipeline.content_identity import content_fingerprint

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "research_intelligence.sqlite"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_text() -> str:
    return _now().isoformat(timespec="seconds")


def _slug(value: str, limit: int = 70) -> str:
    value = re.sub(r"[\\/:*?\"<>|]+", "-", value)
    value = re.sub(r"\s+", "-", value).strip(".- " )
    return value[:limit] or "untitled"


def _topic_directory(*values: Any) -> str:
    """Return one stable, readable folder name for a record.

    The first matching taxonomy topic wins.  This also supports raw crawler
    files, whose search keyword (for example ``RAG 安全``) may not be an exact
    canonical label yet.
    """
    text = " ".join(str(value or "") for value in values).casefold()
    for topic in topic_catalog():
        candidates = [topic["label"], *(topic.get("aliases") or [])]
        if any(str(candidate).casefold() in text for candidate in candidates):
            return _slug(str(topic["label"]), 60)
    fallback = next((str(value).strip() for value in values if str(value or "").strip()), "未分类")
    return _slug(canonical_topic(fallback)["label"], 60)


def _id(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha1(value.encode('utf-8')).hexdigest()[:16]}"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def initialize() -> None:
    with _connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
            text TEXT NOT NULL, platform TEXT NOT NULL, source_url TEXT, author TEXT,
            published_at TEXT, source_file TEXT NOT NULL, source_quality REAL NOT NULL,
            content_type TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            first_seen_at TEXT, last_crawled_at TEXT
        );
        CREATE TABLE IF NOT EXISTS analyses (
            document_id TEXT PRIMARY KEY REFERENCES documents(id), summary TEXT, topics_json TEXT NOT NULL,
            keywords_json TEXT NOT NULL, domains_json TEXT NOT NULL, claims_json TEXT NOT NULL,
            analysis_method TEXT NOT NULL, quality_score REAL NOT NULL, analysis_file TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS evidence (
            id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id), statement TEXT NOT NULL,
            ordinal INTEGER NOT NULL, confidence REAL NOT NULL, created_at TEXT NOT NULL, UNIQUE(document_id, ordinal)
        );
        CREATE TABLE IF NOT EXISTS trend_snapshots (
            id TEXT PRIMARY KEY, topic TEXT NOT NULL, snapshot_date TEXT NOT NULL,
            window_days INTEGER NOT NULL, document_count INTEGER NOT NULL, evidence_count INTEGER NOT NULL,
            platform_count INTEGER NOT NULL, quality_score REAL NOT NULL, velocity REAL NOT NULL, trend TEXT NOT NULL,
            keywords_json TEXT NOT NULL, source_document_ids_json TEXT NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(topic, snapshot_date, window_days)
        );
        CREATE TABLE IF NOT EXISTS document_topics (
            document_id TEXT NOT NULL REFERENCES documents(id), topic_id TEXT NOT NULL,
            topic_label TEXT NOT NULL, taxonomy_version TEXT NOT NULL, source TEXT NOT NULL,
            match_method TEXT NOT NULL, confidence REAL NOT NULL, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, PRIMARY KEY(document_id, topic_id)
        );
        CREATE TABLE IF NOT EXISTS crawl_observations (
            id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
            observed_at TEXT NOT NULL, analysis_run_id TEXT NOT NULL, is_new INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS analysis_runs (
            id TEXT PRIMARY KEY, source_file TEXT NOT NULL, analysis_file TEXT NOT NULL,
            input_count INTEGER NOT NULL, output_count INTEGER NOT NULL,
            batch_summaries_json TEXT NOT NULL, intelligence_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS research_candidates (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, topic TEXT NOT NULL, score REAL NOT NULL,
            why_now TEXT NOT NULL, questions_json TEXT NOT NULL, methods_json TEXT NOT NULL,
            evidence_topics_json TEXT NOT NULL, evidence_document_ids_json TEXT NOT NULL,
            source TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS generated_ideas (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, payload_json TEXT NOT NULL, source_context_json TEXT NOT NULL,
            method TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sync_runs (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, details_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        """)
        _ensure_column(conn, "documents", "first_seen_at", "TEXT")
        _ensure_column(conn, "documents", "last_crawled_at", "TEXT")
        _ensure_column(conn, "trend_snapshots", "topic_id", "TEXT")
        _ensure_column(conn, "trend_snapshots", "trend_metrics_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(conn, "research_candidates", "topic_id", "TEXT")
        _ensure_column(conn, "research_candidates", "taxonomy_version", "TEXT")
        # Backfill stable topic links for records created before this schema.
        rows = conn.execute("SELECT document_id, domains_json FROM analyses").fetchall()
        now = _now_text()
        for row in rows:
            for label in json.loads(row["domains_json"] or "[]") or ["人工智能安全（其他）"]:
                topic = canonical_topic(str(label))
                conn.execute("""INSERT OR IGNORE INTO document_topics
                    (document_id, topic_id, topic_label, taxonomy_version, source, match_method, confidence, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'backfill', 'legacy-label', 0.8, ?, ?)""",
                    (row["document_id"], topic["id"], topic["label"], topic["version"], now, now))
        # Candidate cards are named after their canonical theme.  Their research
        # questions remain in the body; avoid appending a generic title suffix.
        candidates = conn.execute("SELECT * FROM research_candidates").fetchall()
        for candidate in candidates:
            topic = canonical_topic(str(candidate["topic"] or candidate["title"]))
            canonical_id = _id("candidate", topic["id"])
            if candidate["id"] != canonical_id:
                existing = conn.execute("SELECT 1 FROM research_candidates WHERE id=?", (canonical_id,)).fetchone()
                if existing:
                    conn.execute("DELETE FROM research_candidates WHERE id=?", (candidate["id"],))
                else:
                    conn.execute("UPDATE research_candidates SET id=? WHERE id=?", (canonical_id, candidate["id"]))
            conn.execute("UPDATE research_candidates SET title=?, topic=?, topic_id=?, taxonomy_version=?, updated_at=? WHERE id=?", (topic["label"], topic["label"], topic["id"], topic["version"], now, canonical_id))


def _is_curated(item: dict[str, Any]) -> bool:
    """Keep raw discussions for statistics, but only export research-grade material."""
    source_file = str(item.get("source_file") or "").lower()
    text = str(item.get("text") or "")
    evidence = [str(value).strip() for value in item.get("evidence") or []]
    quality = float(item.get("source_quality") or 0)
    domains = item.get("research_domains") or []
    is_comment = "comment" in source_file
    has_research_source = str(item.get("source_platform") or "").lower() in {"arxiv", "github"}
    return bool(
        item.get("source_url")
        and len(text) >= (320 if is_comment else 180)
        and evidence
        and domains
        and (has_research_source or quality >= 0.68)
        and (not is_comment or (quality >= 0.78 and len(evidence[0]) >= 40))
    )


def ingest_analysis(source_file: str, analysis_file: str, items: list[dict[str, Any]], intelligence: dict[str, Any], batch_summaries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Upsert one analyzed crawler batch and refresh its aggregate views."""
    initialize()
    document_ids: list[str] = []
    evidence_count = 0
    now = _now_text()
    with _connect() as conn:
        run_id = f"analysis_{uuid4().hex}"
        for item in items:
            title = str(item.get("title") or "").strip()[:500]
            text = str(item.get("text") or "").strip()[:4000]
            url = str(item.get("source_url") or "").strip()[:1000]
            fingerprint = content_fingerprint({"title": title, "text": text, "source_url": url})
            document_id = _id("doc", fingerprint)
            is_new = conn.execute("SELECT 1 FROM documents WHERE fingerprint=?", (fingerprint,)).fetchone() is None
            normalized_item = {**item, "source_file": source_file}
            if _is_curated(normalized_item):
                document_ids.append(document_id)
            conn.execute("""INSERT INTO documents(id, fingerprint, title, text, platform, source_url, author, published_at, source_file, source_quality, content_type, created_at, updated_at, first_seen_at, last_crawled_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET title=excluded.title, text=excluded.text, source_file=excluded.source_file, source_quality=excluded.source_quality, content_type=excluded.content_type, published_at=COALESCE(NULLIF(excluded.published_at, ''), documents.published_at), updated_at=excluded.updated_at, last_crawled_at=excluded.last_crawled_at""", (
                document_id, fingerprint, title, text, str(item.get("source_platform") or "unknown"), url,
                str(item.get("author") or ""), str(item.get("published_at") or ""), source_file,
                float(item.get("source_quality") or 0.4), str(item.get("content_type") or "discussion"), now, now, now, now,
            ))
            conn.execute("""INSERT INTO analyses(document_id, summary, topics_json, keywords_json, domains_json, claims_json, analysis_method, quality_score, analysis_file, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET summary=excluded.summary, topics_json=excluded.topics_json, keywords_json=excluded.keywords_json, domains_json=excluded.domains_json, claims_json=excluded.claims_json, analysis_method=excluded.analysis_method, quality_score=excluded.quality_score, analysis_file=excluded.analysis_file, updated_at=excluded.updated_at""", (
                document_id, str(item.get("summary") or ""), _json(item.get("topics") or []), _json(item.get("keywords") or []),
                _json(item.get("research_domains") or ["人工智能安全"]), _json(item.get("claims") or []),
                str(item.get("analysis_method") or "rules"), float(item.get("quality_score") or 0.0), analysis_file, now,
            ))
            for label in item.get("research_domains") or ["人工智能安全（其他）"]:
                topic = canonical_topic(str(label))
                conn.execute("""INSERT INTO document_topics
                    (document_id, topic_id, topic_label, taxonomy_version, source, match_method, confidence, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'crawler', 'taxonomy-keyword', 0.85, ?, ?)
                    ON CONFLICT(document_id, topic_id) DO UPDATE SET topic_label=excluded.topic_label, taxonomy_version=excluded.taxonomy_version, source=excluded.source, match_method=excluded.match_method, confidence=excluded.confidence, updated_at=excluded.updated_at""",
                    (document_id, topic["id"], topic["label"], topic["version"], now, now))
            conn.execute("INSERT INTO crawl_observations VALUES (?, ?, ?, ?, ?)",
                (_id("obs", f"{document_id}:{run_id}"), document_id, now, run_id, int(is_new)))
            for ordinal, statement in enumerate(item.get("evidence") or []):
                statement = str(statement).strip()[:500]
                if not statement:
                    continue
                evidence_count += 1
                conn.execute("""INSERT INTO evidence(id, document_id, statement, ordinal, confidence, created_at) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(document_id, ordinal) DO UPDATE SET statement=excluded.statement, confidence=excluded.confidence""",
                    (_id("ev", f"{document_id}:{ordinal}"), document_id, statement, ordinal, float(item.get("quality_score") or 0.5), now))
        conn.execute("INSERT OR REPLACE INTO analysis_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (
            run_id, source_file, analysis_file, len(items), len(items),
            _json(batch_summaries or []), _json(intelligence), now,
        ))
    snapshots = refresh_trends()
    candidate_count = upsert_candidates(intelligence, document_ids)
    sync = sync_obsidian()
    details = {"documents": len(set(document_ids)), "evidence": evidence_count, "trends": len(snapshots), "candidates": candidate_count, "obsidian": sync}
    with _connect() as conn:
        conn.execute("INSERT INTO sync_runs VALUES (?, ?, ?, ?, ?)", (_id("run", run_id), "analysis_ingest", "completed", _json(details), now))
    return details


def import_existing_analyses(limit: int = 100) -> dict[str, Any]:
    """Import prior analysis JSONL files without invoking an AI model."""
    analysis_dir = DATA_DIR / "analysis"
    if not analysis_dir.is_dir():
        return {"imported": 0, "skipped": 0, "errors": []}
    imported = 0
    skipped = 0
    errors: list[str] = []
    files = sorted(analysis_dir.glob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)[:limit]
    for path in files:
        meta_path = path.with_suffix(".meta.json")
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if not rows:
                skipped += 1
                continue
            ingest_analysis(str(meta.get("source_file") or path.name), str(path.relative_to(DATA_DIR)), rows, meta.get("intelligence") or {}, meta.get("batch_summaries") or [])
            imported += 1
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{path.name}: {exc}")
    return {"imported": imported, "skipped": skipped, "errors": errors}


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).strip()
        parsed = datetime.fromtimestamp(float(text), tz=timezone.utc) if text.replace(".", "", 1).isdigit() else datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _velocity(event_times: list[datetime], now: datetime) -> tuple[int, int, float, str]:
    recent_cutoff = now - timedelta(days=7)
    previous_cutoff = now - timedelta(days=14)
    recent = sum(1 for value in event_times if value >= recent_cutoff)
    previous = sum(1 for value in event_times if previous_cutoff <= value < recent_cutoff)
    velocity = round((recent - previous) / max(1, previous), 2)
    return recent, previous, velocity, "rising" if recent >= 2 and velocity >= 0.25 else "stable"


def refresh_trends(window_days: int = 30) -> list[dict[str, Any]]:
    initialize()
    now = _now()
    cutoff = now - timedelta(days=window_days)
    with _connect() as conn:
        rows = conn.execute("""SELECT d.*, a.keywords_json, t.topic_id, t.topic_label, t.taxonomy_version,
            t.confidence AS topic_confidence FROM documents d JOIN analyses a ON a.document_id=d.id
            JOIN document_topics t ON t.document_id=d.id""").fetchall()
        observations = conn.execute("SELECT document_id, observed_at, is_new FROM crawl_observations").fetchall()
    buckets: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        buckets[str(row["topic_id"])].append(row)
    observations_by_doc: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for observation in observations:
        observations_by_doc[str(observation["document_id"])].append(observation)
    snapshot_date = _now_text()  # every completed analysis records a timeline point
    result: list[dict[str, Any]] = []
    with _connect() as conn:
        for topic_id, members in buckets.items():
            topic = str(members[0]["topic_label"])
            current = len(members)
            ids = [member["id"] for member in members]
            published_times = [value for member in members if (value := _parse_time(member["published_at"])) and value >= cutoff]
            collected_times = [value for member in members if (value := _parse_time(member["first_seen_at"] or member["created_at"])) and value >= cutoff]
            observation_times = [value for doc_id in ids for observation in observations_by_doc.get(doc_id, []) if (value := _parse_time(observation["observed_at"])) and value >= cutoff]
            incremental_times = [value for doc_id in ids for observation in observations_by_doc.get(doc_id, []) if observation["is_new"] and (value := _parse_time(observation["observed_at"])) and value >= cutoff]
            pub_recent, pub_previous, pub_velocity, pub_trend = _velocity(published_times, now)
            col_recent, col_previous, col_velocity, col_trend = _velocity(observation_times, now)
            new_recent, new_previous, new_velocity, new_trend = _velocity(incremental_times or collected_times, now)
            # Publication time is the primary external signal.  If a platform does
            # not expose it, retain the explicit fallback marker instead of hiding it.
            primary = (pub_recent, pub_velocity, pub_trend, "published") if published_times else (new_recent, new_velocity, new_trend, "incremental")
            recent, velocity, trend, basis = primary
            evidence_total = conn.execute(f"SELECT COUNT(*) FROM evidence WHERE document_id IN ({','.join('?' for _ in ids)})", ids).fetchone()[0] if ids else 0
            terms = Counter(term for member in members for term in json.loads(member["keywords_json"] or "[]"))
            metrics = {"published": {"window_count": len(published_times), "recent": pub_recent, "previous": pub_previous, "velocity": pub_velocity, "trend": pub_trend, "available": bool(published_times)}, "collected": {"window_count": len(observation_times), "recent": col_recent, "previous": col_previous, "velocity": col_velocity, "trend": col_trend}, "incremental": {"window_count": len(incremental_times or collected_times), "recent": new_recent, "previous": new_previous, "velocity": new_velocity, "trend": new_trend}, "primary_basis": basis, "taxonomy_version": members[0]["taxonomy_version"], "mapping_confidence": round(sum(member["topic_confidence"] for member in members) / current, 2)}
            item = {"topic": topic, "topic_id": topic_id, "document_count": current, "evidence_count": evidence_total, "platform_count": len({member["platform"] for member in members}), "quality_score": round(sum(member["source_quality"] for member in members) / current, 2), "velocity": velocity, "trend": trend, "keywords": [term for term, _ in terms.most_common(8)], "source_document_ids": ids, "metrics": metrics}
            conn.execute("""INSERT INTO trend_snapshots (id, topic, snapshot_date, window_days, document_count, evidence_count, platform_count, quality_score, velocity, trend, keywords_json, source_document_ids_json, created_at, topic_id, trend_metrics_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(topic, snapshot_date, window_days) DO UPDATE SET document_count=excluded.document_count, evidence_count=excluded.evidence_count, platform_count=excluded.platform_count, quality_score=excluded.quality_score, velocity=excluded.velocity, trend=excluded.trend, keywords_json=excluded.keywords_json, source_document_ids_json=excluded.source_document_ids_json, created_at=excluded.created_at, topic_id=excluded.topic_id, trend_metrics_json=excluded.trend_metrics_json""",
                (_id("trend", f"{topic}:{snapshot_date}:{window_days}"), topic, snapshot_date, window_days, current, evidence_total, item["platform_count"], item["quality_score"], velocity, trend, _json(item["keywords"]), _json(ids), _now_text(), topic_id, _json(metrics)))
            result.append(item)
    return sorted(result, key=lambda item: (item["trend"] == "rising", item["document_count"], item["quality_score"]), reverse=True)


def upsert_candidates(intelligence: dict[str, Any], document_ids: list[str]) -> int:
    directions = intelligence.get("research_directions") or []
    now = _now_text()
    with _connect() as conn:
        for direction in directions:
            topic = canonical_topic(str(direction.get("topic") or "人工智能安全（其他）"))
            title = str(direction.get("research_direction") or direction.get("title") or topic["label"]).strip()
            candidate_id = _id("candidate", f"{topic['id']}:{title}")
            conn.execute("""INSERT INTO research_candidates (id, title, topic, score, why_now, questions_json, methods_json, evidence_topics_json, evidence_document_ids_json, source, status, created_at, updated_at, topic_id, taxonomy_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET topic=excluded.topic, topic_id=excluded.topic_id, taxonomy_version=excluded.taxonomy_version, score=excluded.score, why_now=excluded.why_now, questions_json=excluded.questions_json, methods_json=excluded.methods_json, evidence_topics_json=excluded.evidence_topics_json, evidence_document_ids_json=excluded.evidence_document_ids_json, updated_at=excluded.updated_at""",
                (candidate_id, title, topic["label"], float(direction.get("score") or 0), str(direction.get("why_now") or ""), _json(direction.get("research_questions") or []), _json(direction.get("recommended_methods") or []), _json(direction.get("evidence_topics") or []), _json(list(dict.fromkeys(document_ids))[:20]), "crawler", now, now, topic["id"], topic["version"]))
    return len(directions)


def context_snapshot(limit: int = 12) -> dict[str, list[dict[str, Any]]]:
    initialize()
    with _connect() as conn:
        trends = [dict(row) for row in conn.execute("""SELECT t.* FROM trend_snapshots t
            JOIN (SELECT topic, MAX(created_at) AS latest FROM trend_snapshots WHERE window_days=30 GROUP BY topic) recent
              ON recent.topic=t.topic AND recent.latest=t.created_at
            WHERE t.window_days=30 ORDER BY t.trend='rising' DESC, t.document_count DESC LIMIT ?""", (limit,))]
        candidates = [dict(row) for row in conn.execute("SELECT * FROM research_candidates ORDER BY score DESC, updated_at DESC LIMIT ?", (limit,))]
        docs = [dict(row) for row in conn.execute("""SELECT d.*, a.summary, a.keywords_json, a.domains_json FROM documents d
            JOIN analyses a ON a.document_id=d.id
            WHERE d.source_url <> '' AND d.source_file NOT LIKE '%comment%' AND LENGTH(d.text) >= 180
              AND (d.platform IN ('arxiv', 'github') OR d.source_quality >= 0.68)
            ORDER BY d.updated_at DESC LIMIT ?""", (limit,))]
        mappings = defaultdict(list)
        for mapping in conn.execute("SELECT document_id, topic_id, topic_label, taxonomy_version, match_method, confidence FROM document_topics"):
            mapping_dict = dict(mapping)
            mappings[mapping_dict.pop("document_id")].append(mapping_dict)
    for row in trends:
        row["keywords"] = json.loads(row.pop("keywords_json"))
        row["source_document_ids"] = json.loads(row.pop("source_document_ids_json"))
        row["metrics"] = json.loads(row.pop("trend_metrics_json") or "{}")
    for row in candidates:
        for key in ("questions", "methods", "evidence_topics", "evidence_document_ids"):
            row[key] = json.loads(row.pop(f"{key}_json"))
    for row in docs:
        row["keywords"] = json.loads(row.pop("keywords_json"))
        row["domains"] = json.loads(row.pop("domains_json"))
        row["topic_mappings"] = mappings.get(row["id"], [])
    return {"trends": trends, "candidates": candidates, "documents": docs}


def overview_counts() -> dict[str, int]:
    """Counts for the Scientist page, sourced from the unified intelligence DB."""
    initialize()
    with _connect() as conn:
        records = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        trends = conn.execute("SELECT COUNT(DISTINCT topic) FROM trend_snapshots WHERE window_days=30").fetchone()[0]
        candidates = conn.execute("SELECT COUNT(*) FROM research_candidates").fetchone()[0]
    return {"records": int(records), "trends": int(trends), "candidates": int(candidates)}


def record_generated_ideas(ideas: list[dict[str, Any]], method: str, context: dict[str, Any]) -> None:
    initialize()
    now = _now_text()
    with _connect() as conn:
        for idea in ideas:
            title = str(idea.get("Title") or idea.get("title") or "Untitled idea")
            conn.execute("INSERT OR REPLACE INTO generated_ideas VALUES (?, ?, ?, ?, ?, ?)",
                (_id("idea", f"{title}:{now}"), title, _json(idea), _json(context), method, now))
    sync_obsidian()


ACADEMIC_VAULT_ENV = "OBSIDIAN_ACADEMIC_VAULT_PATH"
SOCIAL_VAULT_ENV = "OBSIDIAN_SOCIAL_VAULT_PATH"
ACADEMIC_PLATFORMS = {"github", "arxiv"}


def _vault(env_name: str = "OBSIDIAN_VAULT_PATH") -> Path | None:
    value = os.getenv(env_name, "").strip()
    path = Path(value).expanduser() if value else None
    return path if path and path.is_dir() else None


def _write_note(path: Path, content: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_text(encoding="utf-8", errors="replace") == content:
        return False
    path.write_text(content, encoding="utf-8")
    return True


def _frontmatter(values: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in values.items():
        if isinstance(value, list):
            lines.append(f"{key}: [{', '.join(json.dumps(str(item), ensure_ascii=False) for item in value)}]")
        else:
            lines.append(f"{key}: {json.dumps(str(value), ensure_ascii=False)}")
    return "\n".join(lines + ["---", ""])


def _documents_for_platforms(platforms: set[str], limit: int = 2000) -> list[dict[str, Any]]:
    initialize()
    placeholders = ",".join("?" for _ in platforms)
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT d.*, a.summary, a.keywords_json, a.domains_json
                FROM documents d JOIN analyses a ON a.document_id=d.id
                WHERE LOWER(d.platform) IN ({placeholders})
                ORDER BY d.updated_at DESC LIMIT ?""",
            (*sorted(platforms), limit),
        ).fetchall()
    return [{**dict(row), "keywords": json.loads(row["keywords_json"] or "[]"), "domains": json.loads(row["domains_json"] or "[]")} for row in rows]


def _evidence_for_platforms(platforms: set[str], limit: int = 3000) -> list[dict[str, Any]]:
    initialize()
    placeholders = ",".join("?" for _ in platforms)
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT e.*, d.title, d.source_url, d.platform, a.domains_json
                FROM evidence e JOIN documents d ON d.id=e.document_id
                JOIN analyses a ON a.document_id=d.id
                WHERE LOWER(d.platform) IN ({placeholders})
                ORDER BY e.created_at DESC LIMIT ?""",
            (*sorted(platforms), limit),
        ).fetchall()
    return [{**dict(row), "domains": json.loads(row["domains_json"] or "[]")} for row in rows]


def _crawl_keyword(path: Path) -> str:
    """Extract the search keyword from MediaCrawler's JSONL file name."""
    match = re.match(r"search_(.+?)_(?:contents|comments)_\d{4}-\d{2}-\d{2}$", path.stem)
    return match.group(1).strip() if match else "未分类"


def _raw_comments() -> list[dict[str, Any]]:
    """Load local comment captures so comments remain browsable in Obsidian.

    Comments are intentionally stored as separate notes below the originating
    content entry.  They are raw public captures, not automatically endorsed
    research evidence.
    """
    result: list[dict[str, Any]] = []
    for path in DATA_DIR.glob("*/*/*_comments_*.jsonl"):
        if path.parent.name != "jsonl":
            continue
        platform = path.parents[1].name.lower()
        keyword = _crawl_keyword(path)
        content_titles: dict[str, str] = {}
        contents_name = path.name.replace("_comments_", "_contents_")
        contents_path = path.with_name(contents_name)
        if contents_path.is_file():
            try:
                for line in contents_path.read_text(encoding="utf-8", errors="replace").splitlines():
                    item = json.loads(line)
                    content_id = str(item.get("content_id") or "")
                    if content_id:
                        content_titles[content_id] = str(item.get("title") or content_id)
            except (OSError, json.JSONDecodeError):
                pass
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            comment_id = str(item.get("comment_id") or "")
            content = str(item.get("content") or "").strip()
            if not comment_id or not content:
                continue
            content_id = str(item.get("content_id") or "unknown")
            result.append({
                "id": comment_id,
                "content": content,
                "content_id": content_id,
                "content_title": content_titles.get(content_id, f"条目-{content_id}"),
                "platform": platform,
                "keyword": keyword,
                "author": str(item.get("user_nickname") or "匿名用户"),
                "published_at": item.get("publish_time") or "",
                "source_file": str(path.relative_to(DATA_DIR)),
            })
    return result


def _document_note(doc: dict[str, Any], note_type: str) -> str:
    return _frontmatter({"type": note_type, "source_id": doc["id"], "platform": doc["platform"], "url": doc["source_url"], "created": doc["updated_at"][:10], "tags": ["ai-security", "auto-captured", *doc["domains"]]}) + f"# {doc['title'] or '未命名来源'}\n\n## 自动摘要\n\n{doc.get('summary') or doc['text'][:800]}\n\n## 关键词\n\n{', '.join('#' + item for item in doc['keywords']) or '未提取'}\n\n## 原始链接\n\n- {doc['source_url'] or '未提供'}\n\n## 采集信息\n\n- 平台：{doc['platform']}\n- 采集文件：`{doc['source_file']}`\n- 系统 ID：`{doc['id']}`\n"


def _sync_academic_literature(vault: Path) -> dict[str, Any]:
    target = vault / "30-来源" / "自动采集"
    if not target.is_dir():
        return {"status": "skipped", "vault": str(vault), "reason": "未找到既有目录 30-来源/自动采集；为保护原有结构未写入任何文件。"}
    removed = 0
    # Earlier versions exported trends, evidence cards and generated candidates
    # into this vault.  Only remove files bearing the automation marker; manual
    # notes and the existing vault structure remain untouched.
    for path in vault.rglob("*.md"):
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        generated = "auto-captured" in content or "auto-generated" in content
        note_type = re.search(r"(?m)^type:\s*\"?([^\n\"]+)", content)
        if generated and (not note_type or note_type.group(1).strip() != "literature"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
    docs = _documents_for_platforms(ACADEMIC_PLATFORMS)
    written = 0
    # Migrate only the old flat, system-managed layout.  Existing manual notes
    # and any folders already maintained by the user are left untouched.
    for legacy in target.glob("L-*.md"):
        try:
            if "auto-captured" in legacy.read_text(encoding="utf-8", errors="replace"):
                legacy.unlink()
        except OSError:
            continue
    for doc in docs:
        topic_dir = _topic_directory(*(doc.get("domains") or []), doc.get("title"))
        platform_dir = _slug(str(doc["platform"]).lower(), 40)
        filename = f"文献-{_slug(doc['title'], 80)}-{doc['id'][-8:]}.md"
        written += int(_write_note(target / topic_dir / platform_dir / filename, _document_note(doc, "literature")))
    return {"status": "completed", "vault": str(vault), "notes_written": written, "notes_removed": removed, "documents": len(docs), "target": str(target)}


def _social_platforms() -> set[str]:
    initialize()
    with _connect() as conn:
        return {str(row[0]).lower() for row in conn.execute("SELECT DISTINCT platform FROM documents") if str(row[0]).lower() not in ACADEMIC_PLATFORMS}


def _analysis_runs_for_reports() -> list[dict[str, Any]]:
    initialize()
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM analysis_runs ORDER BY created_at DESC LIMIT 200").fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        source_file = str(item.get("source_file") or "").replace("\\", "/")
        platform = source_file.split("/", 1)[0].lower()
        item["platform"] = platform if platform else "unknown"
        item["source_category"] = "学术与开源" if platform in ACADEMIC_PLATFORMS else ("跨平台批次" if platform == "analysis" else "社交媒体")
        item["batch_summaries"] = json.loads(item.get("batch_summaries_json") or "[]")
        item["intelligence"] = json.loads(item.get("intelligence_json") or "{}")
        result.append(item)
    return result


def _sync_social_intelligence(vault: Path) -> dict[str, Any]:
    sources_root = vault / "10-原始内容"
    evidence_root = vault / "20-评论与证据"
    observations_root = vault / "30-专题观察"
    reports_root = observations_root / "分析报告"
    for directory in (vault / "00-主页", sources_root, evidence_root, observations_root, reports_root):
        directory.mkdir(parents=True, exist_ok=True)
    index = vault / "00-主页" / "社交情报知识库.md"
    _write_note(index, "# 人工智能安全社交情报知识库\n\n本知识库保存公开社交平台的原始内容、评论与证据摘录，并统一保存系统生成的内容分析报告。请在引用前人工核验原始链接、上下文和发布时间。\n\n## 目录\n\n- `10-原始内容/<研究主题>/<平台>`：社交内容条目\n- `20-评论与证据/<研究主题>/<平台>/<原始条目>`：该条目下的原始评论与自动证据\n- `30-专题观察/分析报告/<研究主题>`：按研究主题归档的内容分析报告\n- `30-专题观察` 中的其他内容：预留给人工整理，不由系统自动改写\n")
    platforms = _social_platforms()
    docs = _documents_for_platforms(platforms) if platforms else []
    evidence = _evidence_for_platforms(platforms) if platforms else []
    comments = _raw_comments()
    written = 0
    # One-time migration from the previous flat automatic layout.
    for legacy_platform_dir in sources_root.iterdir():
        if not legacy_platform_dir.is_dir():
            continue
        for legacy in legacy_platform_dir.glob("S-*.md"):
            try:
                if "type: \"social-source\"" in legacy.read_text(encoding="utf-8", errors="replace"):
                    legacy.unlink()
            except OSError:
                continue
    legacy_evidence_root = vault / "20-证据摘录"
    if legacy_evidence_root.is_dir():
        for legacy in legacy_evidence_root.rglob("E-*.md"):
            try:
                if "type: \"social-evidence\"" in legacy.read_text(encoding="utf-8", errors="replace"):
                    legacy.unlink()
            except OSError:
                continue
    for doc in docs:
        topic_dir = _topic_directory(*(doc.get("domains") or []), doc.get("title"))
        platform_dir = sources_root / topic_dir / _slug(str(doc["platform"]).lower(), 40)
        filename = f"内容-{_slug(doc['title'], 80)}-{doc['id'][-8:]}.md"
        written += int(_write_note(platform_dir / filename, _document_note(doc, "social-source")))
    for item in evidence:
        topic_dir = _topic_directory(*(item.get("domains") or []), item.get("title"))
        platform_dir = evidence_root / topic_dir / _slug(str(item["platform"]).lower(), 40) / _slug(item["title"], 70)
        filename = f"证据-{item['id'][-8:]}.md"
        content = _frontmatter({"type": "social-evidence", "evidence_id": item["id"], "source_document_id": item["document_id"], "platform": item["platform"], "url": item["source_url"], "created": item["created_at"][:10], "tags": ["ai-security", "social-evidence", "auto-captured"]}) + f"# {item['statement'][:90]}\n\n## 证据摘录\n\n{item['statement']}\n\n## 来源定位\n\n- {item['source_url'] or '未提供'}\n\n## 使用提示\n\n此条目由公开内容自动提取，需结合原始上下文人工核验。\n"
        written += int(_write_note(platform_dir / filename, content))
    for item in comments:
        topic_dir = _topic_directory(item["keyword"], item["content_title"])
        comment_dir = evidence_root / topic_dir / _slug(item["platform"], 40) / _slug(item["content_title"], 70)
        filename = f"评论-{_slug(item['author'], 24)}-{item['id'][-8:]}.md"
        content = _frontmatter({"type": "social-comment", "comment_id": item["id"], "content_id": item["content_id"], "platform": item["platform"], "keyword": item["keyword"], "author": item["author"], "published_at": item["published_at"], "source_file": item["source_file"], "tags": ["ai-security", "social-comment", "auto-captured", item["keyword"]]}) + f"# 评论：{item['content_title']}\n\n{item['content']}\n\n## 来源信息\n\n- 检索词：{item['keyword']}\n- 平台：{item['platform']}\n- 评论者：{item['author']}\n- 原始数据：`{item['source_file']}`\n"
        written += int(_write_note(comment_dir / filename, content))
    # Analysis reports are kept in this dedicated intelligence vault regardless
    # of whether their input was social, academic, or a merged cross-platform batch.
    analysis_runs = _analysis_runs_for_reports()
    for run in analysis_runs:
        topic_dir = _topic_directory(*(topic.get("topic") for topic in run["intelligence"].get("topics") or []), Path(run["source_file"]).stem)
        filename = f"分析-{run['created_at'][:10]}-{_slug(Path(run['source_file']).stem, 60)}.md"
        intelligence = run["intelligence"]
        lines = [f"# 内容分析：{Path(run['source_file']).name}", "", "## 本次分析", "", f"- 来源类别：{run['source_category']}", f"- 平台或批次：{run['platform']}", f"- 时间：{run['created_at']}", f"- 原始来源：`{run['source_file']}`", f"- 分析记录：{run['output_count']}", "", "## 主题观察", ""]
        for topic in (intelligence.get("topics") or [])[:10]:
            lines.append(f"- {topic.get('topic', '未命名主题')}：{topic.get('content_count', 0)} 条内容，趋势 {topic.get('trend', 'stable')}，证据 {topic.get('evidence_count', 0)} 条")
        if run["batch_summaries"]:
            lines.extend(["", "## 分批分析摘要", ""])
            for summary in run["batch_summaries"]:
                lines.extend([f"### 第 {summary.get('batch', '?')} 批（{summary.get('record_count', 0)} 条）", "", str(summary.get('summary') or '未生成摘要。'), ""])
        content = _frontmatter({"type": "analysis-report", "source_category": run["source_category"], "platform": run["platform"], "source_file": run["source_file"], "created": run["created_at"][:10], "tags": ["ai-security", "analysis-report", "auto-generated"]}) + "\n".join(lines) + "\n"
        written += int(_write_note(reports_root / topic_dir / filename, content))
    return {"status": "completed", "vault": str(vault), "notes_written": written, "documents": len(docs), "evidence": len(evidence), "comments": len(comments), "analysis_reports": len(analysis_runs)}


def sync_obsidian() -> dict[str, Any]:
    """Synchronize academic literature and social intelligence into separate vaults."""
    academic_vault = _vault(ACADEMIC_VAULT_ENV) or _vault()
    social_vault = _vault(SOCIAL_VAULT_ENV)
    academic = _sync_academic_literature(academic_vault) if academic_vault else {"status": "skipped", "reason": "未配置学术知识库路径"}
    social = _sync_social_intelligence(social_vault) if social_vault else {"status": "skipped", "reason": "未配置社交情报知识库路径"}
    statuses = {academic.get("status"), social.get("status")}
    return {"status": "completed" if "completed" in statuses else "skipped", "academic": academic, "social": social}
