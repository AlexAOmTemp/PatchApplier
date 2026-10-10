"""Doc indexer — walk markdown files, parse with Format, render INDEX.md."""
from __future__ import annotations

from dataclasses import dataclass

from ..core.backend import Backend
from ..core.models import Section
from ..formats import Format
from ..formats.renderer import FileIndex, PREAMBLE, render_index


@dataclass
class BuildResult:
    text: str
    files_count: int
    missing_summary: int
    files: list[FileIndex]


def build_index(
    backend: Backend,
    fmt: Format,
    *,
    docs_dir: str = "",
    skip_files: set[str] | None = None,
    meta_path: str | None = None,
) -> BuildResult:
    import time
    from .meta import load_meta, save_meta, update_file_meta

    skip = set(skip_files or {"INDEX.md"})
    paths = backend.list(docs_dir, "*.md") if docs_dir else backend.list("", "*.md")
    files: list[FileIndex] = []
    missing = 0

    old_meta = load_meta(backend, meta_path) if meta_path else {}
    new_meta: dict = {}
    now_ts = time.time()

    for path in paths:
        name = path.rsplit("/", 1)[-1]
        if name in skip:
            continue
        if backend.filter_check(path, "index_docs"):
            continue
        try:
            text = backend.read(path)
        except Exception:
            continue
        try:
            doc = fmt.parse(text)
        except Exception:
            continue
        try:
            st = backend.stat(path)
        except Exception:
            continue

        flat = _flatten(doc.sections)
        if meta_path:
            snapshots = [{
                "heading": _heading_key(s),
                "summary": s.summary,
                "body_hash": s.body_hash,
                "summary_hash": s.summary_hash,
            } for s in flat]
            old_file_meta = old_meta.get(path, {})
            new_file_meta, stale_keys = update_file_meta(
                old_file_meta, snapshots, now_ts, st.mtime,
            )
            new_meta[path] = new_file_meta
            stale_set = set(stale_keys)
            for s in flat:
                s.stale = _heading_key(s) in stale_set

        files.append(FileIndex(
            path=path,
            lines=st.lines,
            size_bytes=st.size_bytes,
            mtime=st.mtime,
            source=text,
            sections=doc.sections,
        ))
        missing += sum(1 for s in flat if s.summary is None)

    if meta_path:
        save_meta(backend, meta_path, new_meta)

    files.sort(key=lambda fi: fi.path)
    text = render_index(files, PREAMBLE)
    return BuildResult(
        text=text,
        files_count=len(files),
        missing_summary=missing,
        files=files,
    )


def _flatten(sections: list[Section]) -> list[Section]:
    out: list[Section] = []
    for s in sections:
        out.append(s)
        out.extend(_flatten(s.children))
    return out


def _heading_key(s: Section) -> str:
    """Stable per-file key for a section: the heading text as rendered."""
    if s.number is None:
        return s.title
    if "." in s.number:
        return f"{s.number} {s.title}"
    return f"{s.number}. {s.title}"
