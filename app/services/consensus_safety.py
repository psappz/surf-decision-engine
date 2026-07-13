from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from typing import Any

_SECRET_KEY = re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key|authorization|credential|cookie)")
_BEARER = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]+")
_ASSIGNMENT = re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key|authorization|credential)\s*[:=]\s*([^\s,;]+)")
_URL_CREDENTIALS = re.compile(r"(?P<scheme>https?://)(?P<user>[^/@:\s]+):(?P<password>[^/@\s]+)@")


def redact_text(value: Any, *, max_length: int = 1000) -> str:
    text = str(value)
    text = _URL_CREDENTIALS.sub(r"\g<scheme>[REDACTED]@", text)
    text = _BEARER.sub(r"\1[REDACTED]", text)
    text = _ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    for key, secret in os.environ.items():
        if _SECRET_KEY.search(key) and secret and len(secret) >= 4:
            text = text.replace(secret, "[REDACTED]")
    if len(text) > max_length:
        omitted = len(text) - max_length
        text = f"{text[:max_length]}…[truncated {omitted} chars]"
    return text


def bounded_json(
    value: Any,
    *,
    max_depth: int = 6,
    max_items: int = 24,
    max_string: int = 500,
    max_bytes: int = 131_072,
) -> Any:
    """Recursively redact and bound JSON-compatible data deterministically."""
    bounded = _bound(value, depth=0, max_depth=max_depth, max_items=max_items, max_string=max_string)
    encoded = _encoded(bounded)
    if len(encoded) <= max_bytes:
        return bounded
    if isinstance(bounded, dict):
        reduced: dict[str, Any] = {}
        omitted_keys = 0
        for key in sorted(bounded):
            candidate = dict(reduced)
            candidate[key] = bounded[key]
            candidate["_truncated"] = {"omitted_keys": max(0, len(bounded) - len(candidate) + 1)}
            if len(_encoded(candidate)) > max_bytes:
                omitted_keys += 1
                continue
            reduced[key] = bounded[key]
        reduced["_truncated"] = {
            "omitted_keys": max(omitted_keys, len(bounded) - len(reduced)),
            "omitted_bytes": len(encoded) - max_bytes,
        }
        while len(_encoded(reduced)) > max_bytes and len(reduced) > 1:
            key = sorted(k for k in reduced if k != "_truncated")[-1]
            reduced.pop(key)
            reduced["_truncated"]["omitted_keys"] += 1
        return reduced
    return {"_truncated": True, "omitted_bytes": len(encoded) - max_bytes, "type": type(value).__name__}


def _bound(value: Any, *, depth: int, max_depth: int, max_items: int, max_string: int) -> Any:
    if depth >= max_depth and isinstance(value, (Mapping, Sequence)) and not isinstance(value, (str, bytes, bytearray)):
        size = len(value) if hasattr(value, "__len__") else None
        return {"_truncated": True, "reason": "maximum_depth", "omitted_count": size}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (str, bytes, bytearray)):
        text = value.decode(errors="replace") if isinstance(value, (bytes, bytearray)) else value
        return redact_text(text, max_length=max_string)
    if isinstance(value, Mapping):
        items = sorted(((redact_text(k, max_length=120), v) for k, v in value.items()), key=lambda item: item[0])
        out: dict[str, Any] = {}
        for key, item in items[:max_items]:
            out[key] = "[REDACTED]" if _SECRET_KEY.search(key) else _bound(item, depth=depth + 1, max_depth=max_depth, max_items=max_items, max_string=max_string)
        if len(items) > max_items:
            out["_truncated"] = {"omitted_count": len(items) - max_items}
        return out
    if isinstance(value, Sequence) or isinstance(value, set):
        values = list(value)
        seq_out = [_bound(item, depth=depth + 1, max_depth=max_depth, max_items=max_items, max_string=max_string) for item in values[:max_items]]
        if len(values) > max_items:
            seq_out.append({'_truncated': True, 'omitted_count': len(values) - max_items})
        return seq_out
    return redact_text(repr(value), max_length=max_string)


def _encoded(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode()
