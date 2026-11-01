from __future__ import annotations

import csv
import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import jieba.analyse
from dotenv import load_dotenv
from pipeline.content_identity import content_fingerprint
from pipeline.research_intelligence import ingest_analysis
from pipeline.topic_taxonomy import TOPIC_TAXONOMY, canonical_topic, topic_catalog

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
ANALYSIS_DIR = DATA_DIR / "analysis"
load_dotenv(PROJECT_ROOT / ".env")

AI_SAFETY_TAXONOMY = {label: list(spec["aliases"]) for label, spec in TOPIC_TAXONOMY.items()}

SOURCE_WEIGHTS = {"arxiv": 1.0, "github": 0.9, "bili": 0.7, "zhihu": 0.6, "xhs": 0.5, "dy": 0.5, "wb": 0.4}


def _safe_path(relative_path: str) -> Path:
    path = (DATA_DIR / relative_path).resolve()
    path.relative_to(DATA_DIR.resolve())
    if not path.is_file():
        raise FileNotFoundError(relative_path)
    return path


def _read_rows(path: Path, limit: int) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    rows: list[dict[str, Any]] = []
    if suffix == ".jsonl":
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rows.append(value if isinstance(value, dict) else {"value": value})
                if len(rows) >= limit:
                    break
    elif suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8"))
        values = value if isinstance(value, list) else [value]
        rows = [item if isinstance(item, dict) else {"value": item} for item in values[:limit]]
    elif suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))[:limit]
    elif suffix in {".xlsx", ".xls"}:
        import pandas as pd

        frame = pd.read_excel(path, nrows=limit)
        rows = frame.where(frame.notna(), None).to_dict(orient="records")
    else:
        raise ValueError(f"Unsupported analysis file type: {suffix}")
    return rows


def prepare_merged_input(relative_paths: list[str], limit_per_file: int = 500) -> str:
    """Create one hidden analysis input while preserving original file/platform provenance."""
    merged: list[dict[str, Any]] = []
    for relative_path in list(dict.fromkeys(relative_paths)):
        path = _safe_path(relative_path)
        platform = relative_path.replace("\\", "/").split("/")[0]
        for row in _read_rows(path, max(1, min(limit_per_file, 5000))):
            merged.append({**row, "__source_platform": platform, "__source_file": relative_path})
    if not merged:
        raise ValueError("未读取到可合并的采集内容")
    batch_dir = ANALYSIS_DIR / "batch_inputs"
    batch_dir.mkdir(parents=True, exist_ok=True)
    output = batch_dir / f"merged_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(relative_paths)}files.jsonl"
    with output.open("w", encoding="utf-8") as handle:
        for row in merged:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return str(output.relative_to(DATA_DIR))


def _first(row: dict[str, Any], *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _normalize(row: dict[str, Any]) -> dict[str, Any]:
    title = _first(row, "title", "note_title", "desc", "content", "text")
    description = _first(row, "desc", "content", "text", "title")
    author = _first(row, "nickname", "author", "user_nickname", "creator")
    url = _first(row, "url", "aweme_url", "note_url", "video_url", "source_url")
    return {
        "title": title[:500],
        "text": description[:4000],
        "author": author[:200],
        "source_url": url[:1000],
        "source_platform": _first(row, "__source_platform"),
        "published_at": _first(row, "published_at", "create_time", "publish_time", "time", "date"),
        "raw": row,
    }


def _keywords(text: str, limit: int = 8) -> list[str]:
    if not text:
        return []
    values = jieba.analyse.extract_tags(text, topK=limit, withWeight=False)
    return [item for item in values if len(item.strip()) > 1]


def _content_type(item: dict[str, Any]) -> str:
    text = f"{item['title']} {item['text']}".lower()
    if any(term in text for term in ("论文", "arxiv", "实验", "benchmark", "基准")): return "research"
    if any(term in text for term in ("教程", "实战", "代码", "github", "部署")): return "practice"
    if any(term in text for term in ("新闻", "发布", "报告", "政策")): return "news"
    if any(term in text for term in ("观点", "怎么看", "认为", "建议")): return "opinion"
    return "discussion"


def available_themes() -> list[str]:
    return list(AI_SAFETY_TAXONOMY)


def available_topic_catalog() -> list[dict[str, Any]]:
    return topic_catalog()


def _analysis_taxonomy(selected_themes: list[str] | None, custom_themes: list[str] | None) -> dict[str, list[str]]:
    selected = set(available_themes() if selected_themes is None else selected_themes)
    taxonomy = {label: terms for label, terms in AI_SAFETY_TAXONOMY.items() if label in selected}
    for theme in custom_themes or []:
        label = re.sub(r"\s+", " ", str(theme)).strip()[:80]
        if label:
            # A custom theme is deliberately precise: it matches its supplied phrase.
            taxonomy[label] = [label]
    return taxonomy


def _taxonomies(text: str, taxonomy: dict[str, list[str]]) -> list[str]:
    lowered = text.lower()
    return [label for label, terms in taxonomy.items() if any(term.lower() in lowered for term in terms)][:3]


def _evidence_sentences(text: str, limit: int = 3) -> list[str]:
    sentences = [part.strip() for part in re.split(r"[。！？!?\n]+", text) if len(part.strip()) >= 12]
    signal = re.compile(r"(实验|结果|发现|显示|表明|风险|攻击|防御|漏洞|评测|数据|模型|建议|问题)", re.I)
    ranked = sorted(sentences, key=lambda value: (bool(signal.search(value)), len(value)), reverse=True)
    return [value[:300] for value in ranked[:limit]]


def _source_quality(platform: str, content_type: str, text_length: int) -> float:
    base = SOURCE_WEIGHTS.get(platform.lower(), 0.45)
    type_bonus = {"research": 0.15, "practice": 0.08, "news": 0.02, "opinion": -0.03}.get(content_type, 0)
    depth_bonus = min(0.15, text_length / 4000)
    return round(min(1.0, max(0.1, base + type_bonus + depth_bonus)), 2)


def _fingerprint(item: dict[str, Any]) -> str:
    return content_fingerprint(item)


def _rule_analysis(item: dict[str, Any], taxonomy: dict[str, list[str]]) -> dict[str, Any]:
    text = item["text"]
    terms = _keywords(f"{item['title']} {text}")
    content_type = _content_type(item)
    taxonomies = _taxonomies(f"{item['title']} {text}", taxonomy)
    return {
        **item,
        "summary": text[:240] + ("…" if len(text) > 240 else ""),
        "topics": terms[:5],
        "keywords": terms,
        "claims": [],
        "evidence": _evidence_sentences(text),
        "content_type": content_type,
        "research_domains": taxonomies,
        "source_quality": _source_quality(item["source_platform"], content_type, len(text)),
        "analysis_method": "rules",
        "quality_score": round(min(1.0, 0.35 + min(len(text), 1600) / 3200), 2),
    }


def _build_research_intelligence(items: list[dict[str, Any]]) -> dict[str, Any]:
    clusters: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        for domain in item.get("research_domains", ["人工智能安全"]):
            clusters.setdefault(domain, []).append(item)
    topic_rows: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for name, members in clusters.items():
        platform_counts: dict[str, int] = {}
        all_terms: list[str] = []
        for member in members:
            platform = member.get("source_platform", "unknown")
            platform_counts[platform] = platform_counts.get(platform, 0) + 1
            all_terms.extend(member.get("keywords", []))
        term_counts: dict[str, int] = {}
        for term in all_terms: term_counts[term] = term_counts.get(term, 0) + 1
        top_terms = [term for term, _ in sorted(term_counts.items(), key=lambda pair: pair[1], reverse=True)[:8]]
        quality = round(sum(float(member.get("source_quality", 0.4)) for member in members) / max(1, len(members)), 2)
        recent = sum(1 for member in members if _is_recent(member.get("published_at", ""), now, 45))
        trend = "rising" if recent >= max(2, len(members) * 0.45) else "stable"
        canonical = canonical_topic(name)
        topic_rows.append({"topic": canonical["label"], "topic_id": canonical["id"], "taxonomy_version": canonical["version"], "content_count": len(members), "platforms": platform_counts, "representative_terms": top_terms, "recent_count": recent, "trend": trend, "evidence_count": sum(len(member.get("evidence", [])) for member in members), "quality_score": quality})
    topic_rows.sort(key=lambda row: (row["content_count"], row["quality_score"]), reverse=True)
    directions = []
    for topic in topic_rows[:8]:
        feasibility = min(1.0, 0.35 + 0.12 * len(topic["platforms"]) + 0.04 * min(topic["content_count"], 8))
        score = round(100 * (0.25 * (1 if topic["trend"] == "rising" else 0.65) + 0.2 * min(1, len(topic["platforms"]) / 3) + 0.2 * topic["quality_score"] + 0.15 * min(1, topic["evidence_count"] / 10) + 0.2 * feasibility))
        directions.append({"research_direction": topic["topic"], "score": score, "topic": topic["topic"], "why_now": f"该方向涉及 {topic['content_count']} 条内容，覆盖 {len(topic['platforms'])} 个平台，当前趋势为 {topic['trend']}。", "research_questions": [f"如何建立可复现的{topic['topic']}风险评测基准？", f"现有防御方法在真实应用场景中的有效性如何？"], "recommended_methods": ["跨平台证据对照", "构造可复现实验集", "比较攻击成功率与任务性能"], "evidence_topics": topic["representative_terms"][:5]})
    return {"topics": topic_rows, "research_directions": directions, "generated_at": datetime.now().isoformat(timespec="seconds")}


def _is_recent(value: Any, now: datetime, days: int) -> bool:
    if not value: return False
    try:
        parsed = datetime.fromtimestamp(float(value), tz=timezone.utc) if str(value).isdigit() else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None: parsed = parsed.replace(tzinfo=timezone.utc)
        return (now - parsed).days <= days
    except (TypeError, ValueError, OverflowError):
        return False


async def _ai_enrich(item: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("AI_API_KEY", "").strip()
    if not api_key:
        return item
    base_url = os.getenv("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("AI_MODEL", "gpt-4o-mini")
    prompt = {
        "title": item["title"],
        "text": item["text"],
        "instruction": "返回 JSON：summary(不超过120字), topics(最多5个), claims(最多3条), quality_score(0到1)。不要补写原文没有的事实。",
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0)) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "temperature": 0.1, "response_format": {"type": "json_object"}, "messages": [{"role": "system", "content": "你是严谨的资料分析助手。"}, {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}]},
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            enriched = json.loads(content)
            return {**item, **{key: enriched[key] for key in ("summary", "topics", "claims", "quality_score") if key in enriched}, "analysis_method": "ai"}
    except Exception:
        return item


async def _summarize_batch(items: list[dict[str, Any]], batch_number: int) -> dict[str, Any]:
    """Create one grounded observation for a representative block of records."""
    api_key = os.getenv("AI_API_KEY", "").strip()
    if not api_key:
        return {}
    source_items = [
        {"title": item["title"][:160], "text": item["text"][:360]}
        for item in items
    ]
    prompt = {
        "batch_number": batch_number,
        "records": source_items,
        "instruction": "基于这批原始内容返回 JSON：summary(不超过180字), topics(最多6个), claims(最多5条)。仅总结输入中出现的信息，不要补写事实。",
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(35.0, connect=8.0)) as client:
            response = await client.post(
                f"{os.getenv('AI_BASE_URL', 'https://api.openai.com/v1').rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": os.getenv("AI_MODEL", "gpt-4o-mini"), "temperature": 0.1, "response_format": {"type": "json_object"}, "messages": [{"role": "system", "content": "你是严谨的资料分析助手。"}, {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}]},
            )
            response.raise_for_status()
            return json.loads(response.json()["choices"][0]["message"]["content"])
    except Exception:
        return {}


async def _summarize_batches(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    batch_size = max(10, min(int(os.getenv("AI_BATCH_SIZE", "50")), 100))
    batches = [items[index:index + batch_size] for index in range(0, len(items), batch_size)]
    semaphore = asyncio.Semaphore(3)

    async def summarize(batch: list[dict[str, Any]], number: int) -> dict[str, Any]:
        async with semaphore:
            summary = await _summarize_batch(batch, number)
            return {"batch": number, "record_count": len(batch), **summary} if summary else {}

    summaries = await asyncio.gather(*(summarize(batch, number + 1) for number, batch in enumerate(batches)))
    return [summary for summary in summaries if summary]


async def analyze_file(
    relative_path: str,
    limit: int = 500,
    selected_themes: list[str] | None = None,
    custom_themes: list[str] | None = None,
) -> dict[str, Any]:
    path = _safe_path(relative_path)
    rows = _read_rows(path, max(1, min(limit, 5000)))
    taxonomy = _analysis_taxonomy(selected_themes, custom_themes)
    if not taxonomy:
        raise ValueError("请至少选择一个固定主题或填写一个自定义主题")
    seen: set[str] = set()
    analyzed: list[dict[str, Any]] = []
    platform = relative_path.replace("\\", "/").split("/")[0]
    pending: list[dict[str, Any]] = []
    scope_excluded = 0
    for row in rows:
        normalized = _normalize(row)
        normalized["source_platform"] = normalized.get("source_platform") or platform
        key = _fingerprint(normalized)
        if key in seen or not (normalized["title"] or normalized["text"]):
            continue
        seen.add(key)
        item = _rule_analysis(normalized, taxonomy)
        if not item["research_domains"]:
            scope_excluded += 1
            continue
        pending.append(item)

    # AI works on evenly-sized blocks, then the UI presents the resulting
    # progressive summaries alongside the complete local analysis.
    batch_summaries: list[dict[str, Any]] = []
    if os.getenv("AI_API_KEY", "").strip() and pending:
        batch_summaries = await _summarize_batches(pending)
        analyzed = pending
    else:
        analyzed = pending

    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_name = f"{path.stem}_analysis_{stamp}.jsonl"
    output_path = ANALYSIS_DIR / output_name
    with output_path.open("w", encoding="utf-8") as handle:
        for item in analyzed:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    intelligence = _build_research_intelligence(analyzed)
    meta = {"source_file": relative_path, "output_file": str(output_path.relative_to(DATA_DIR)), "input_count": len(rows), "output_count": len(analyzed), "scope_excluded": scope_excluded, "selected_themes": list(taxonomy), "ai_enabled": bool(os.getenv("AI_API_KEY", "").strip()), "batch_size": max(10, min(int(os.getenv("AI_BATCH_SIZE", "50")), 100)), "batch_summaries": batch_summaries, "intelligence": intelligence, "created_at": datetime.now().isoformat(timespec="seconds")
    }
    (output_path.with_suffix(".meta.json")).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    # Persist the machine-readable research record and update human-readable Obsidian views.
    meta["intelligence_store"] = ingest_analysis(
        source_file=relative_path,
        analysis_file=str(output_path.relative_to(DATA_DIR)),
        items=analyzed,
        intelligence=intelligence,
        batch_summaries=batch_summaries,
    )
    (output_path.with_suffix(".meta.json")).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta
