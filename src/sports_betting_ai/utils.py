"""Utilities shared by provider adapters and risk guardrails."""
from __future__ import annotations
from datetime import datetime, timezone
import re
import unicodedata


def parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Naive datetime prohibited; require timezone offset")
    return dt.astimezone(timezone.utc)


def norm_name(value: str) -> str:
    base = unicodedata.normalize("NFKD", value)
    base = "".join(c for c in base if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", base.casefold())
