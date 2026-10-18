"""Text hashing for stale-detection in documents.

`body_hash` is computed over a section's body (excluding its child
subsections), normalized to ignore trailing whitespace and leading/trailing
blank lines. `summary_hash` is computed over the raw summary text. Both are
sha1 over UTF-8 bytes. Sidecar storage is managed by `indexers.meta`.
"""
from __future__ import annotations

import hashlib


def hash_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def normalize_body(text: str) -> str:
    """Strip trailing whitespace per line, drop leading/trailing blank lines."""
    lines = [l.rstrip() for l in text.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)

def content_hash(data: bytes) -> int:
    """Full-content hash for duplicate detection (blake2b-8, 64-bit)."""
    return int.from_bytes(hashlib.blake2b(data, digest_size=8).digest(), "big")
