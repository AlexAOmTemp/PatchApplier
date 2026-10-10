"""Pure logic for the project settings directory tree.

Turns the flat list of ``(rel_path, is_hidden)`` pairs returned by
``config.loader.scan_subdirs`` into a nested tree of dicts. No Tk here —
testable in isolation, and reusable from any future view (Tk, web, CLI).

Output shape::

    [
        {'name': 'code', 'hidden': False, 'children': [
            {'name': 'bridge', 'hidden': False, 'children': []},
            {'name': 'toolkit', 'hidden': False, 'children': [
                {'name': 'backends', 'hidden': False, 'children': []},
                ...
            ]},
        ]},
        {'name': 'docs', 'hidden': False, 'children': []},
    ]

A node is a directory. Files are never part of this tree — see
docs/GUI_PROJECT_SETTINGS.md §3 for why.

Order of input is preserved: siblings appear in the same relative order
they came in. ``scan_subdirs`` returns sorted entries, so the tree is
alphabetical by construction unless the caller re-orders.
"""
from __future__ import annotations


# --- build ----------------------------------------------------------------


def build_tree(paths: list[tuple[str, bool]]) -> list[dict]:
    """Nested tree from a flat list of (rel_path, hidden) pairs.

    ``rel_path`` uses forward slashes and never starts with one
    (``'code/toolkit/backends'``). Last segment is the node's name.

    Missing intermediate levels are created implicitly: an input of
    ``['a/b/c']`` alone produces a three-deep chain ``a → b → c``.
    Repeated prefixes are merged; the first ``hidden`` flag seen for a
    node wins (later duplicates do not overwrite it).
    """
    root: list[dict] = []
    index: dict[str, dict] = {}

    for raw_path, hidden in paths:
        if not raw_path:
            continue
        parts = [p for p in raw_path.replace("\\", "/").split("/") if p]
        if not parts:
            continue
        parent_children = root
        prefix = ""
        for seg in parts:
            prefix = f"{prefix}/{seg}" if prefix else seg
            node = index.get(prefix)
            if node is None:
                node = {"name": seg, "hidden": bool(hidden), "children": []}
                index[prefix] = node
                parent_children.append(node)
            parent_children = node["children"]

    return root


# --- filter ---------------------------------------------------------------


def filter_hidden(tree: list[dict]) -> list[dict]:
    """Return a copy with hidden nodes and their subtrees removed.

    A hidden node's whole branch disappears, even if a child is not
    itself marked hidden — hiding a directory hides everything under it.
    Non-hidden nodes are copied (not mutated in place).
    """
    out: list[dict] = []
    for node in tree:
        if node.get("hidden"):
            continue
        out.append({
            "name": node["name"],
            "hidden": False,
            "children": filter_hidden(node.get("children", [])),
        })
    return out


# --- helpers --------------------------------------------------------------


def flatten(tree: list[dict], prefix: str = "") -> list[tuple[str, bool]]:
    """Inverse of ``build_tree``: nested → flat [(rel_path, hidden)].

    Useful in tests, and for comparing two trees for equality.
    """
    out: list[tuple[str, bool]] = []
    for node in tree:
        path = f"{prefix}/{node['name']}" if prefix else node["name"]
        out.append((path, bool(node.get("hidden", False))))
        out.extend(flatten(node.get("children", []), prefix=path))
    return out
