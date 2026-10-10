"""ParsedDoc — result of parsing a markdown document with a Format."""
from __future__ import annotations

from dataclasses import dataclass

from ..core.models import Section


@dataclass
class ParsedDoc:
    source: str
    sections: list[Section]

    def flatten(self) -> list[Section]:
        """Depth-first traversal: parents first, then children."""
        out: list[Section] = []

        def walk(items: list[Section]) -> None:
            for s in items:
                out.append(s)
                walk(s.children)

        walk(self.sections)
        return out

    def find(
        self,
        number: str | None = None,
        title: str | None = None,
    ) -> Section | None:
        """Find by number (exact) or by title (substring, case-insensitive).
        If both given -- number wins."""
        if number is not None:
            want = str(number).strip()
            for s in self.flatten():
                if s.number == want:
                    return s
        if title is not None:
            want_t = title.lower()
            for s in self.flatten():
                if want_t in s.title.lower():
                    return s
        return None

    @staticmethod
    def section_full_end(s: Section) -> int:
        """End offset of a section including all its subsections.
        For a leaf -- same as body_end. For a parent -- last child's full end.
        """
        if s.children:
            return ParsedDoc.section_full_end(s.children[-1])
        return s.body_end
