"""Shared content identity for analysis and subsequent database ingestion."""
from __future__ import annotations

import hashlib
import re
from typing import Any


def content_fingerprint(item: dict[str, Any]) -> str:
    """Preserve the analysis fingerprint policy, ignoring whitespace changes."""
    source = f"{item.get('title', '')}\n{item.get('text', '')}\n{item.get('source_url', '')}"
    return hashlib.sha1(re.sub(r"\s+", " ", source).strip().encode("utf-8")).hexdigest()
