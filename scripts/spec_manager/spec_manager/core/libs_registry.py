"""Library registry derived from scanning library files.

Replaces the manual libs.md file by scanning library files for:
- ([=ID]) declarations - where an ID lives
- (@[+ID]) references - what each section references

Maintains backwards-compatible API for existing code.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .annotations import AnnotationParser
from .sections import SectionExtractor


@dataclass
class LibsEntry:
    """An entry representing an ID's location and references."""

    id_value: str
    primary: str  # Library containing this ID's declaration
    related: list[str] = field(default_factory=list)  # Libraries of referenced IDs
    line_number: int = 0


@dataclass
class LibsRegistry:
    """Registry of ID locations derived from scanning library files.

    Instead of parsing a libs.md file, this scans library .md files
    to find ([=ID]) declarations and (@[+ID]) references.

    Provides the same API as before for backwards compatibility.
    """

    entries: dict[str, LibsEntry] = field(default_factory=dict)
    libraries_dir: Path | None = None

    # Internal: maps library name to set of IDs declared in it
    _library_ids: dict[str, set[str]] = field(default_factory=dict)

    @classmethod
    def from_libraries(cls, libraries_dir: Path) -> LibsRegistry:
        """Build registry by scanning library files."""
        registry = cls(libraries_dir=libraries_dir)
        registry._scan_libraries()
        return registry

    @classmethod
    def from_file(cls, path: Path) -> LibsRegistry:
        """Build registry from a path.

        If path is libs.md, looks for sibling libraries/ directory.
        If path is a directory, scans it directly.
        """
        if path.is_dir():
            return cls.from_libraries(path)

        # Assume libs.md, look for sibling libraries/
        libraries_dir = path.parent / "libraries"
        if libraries_dir.exists():
            return cls.from_libraries(libraries_dir)

        # Fallback: empty registry
        return cls()

    @classmethod
    def from_content(cls, content: str) -> LibsRegistry:
        """For backwards compatibility - returns empty registry."""
        return cls()

    def _scan_libraries(self) -> None:
        """Scan all .md files in the libraries directory."""
        if not self.libraries_dir or not self.libraries_dir.exists():
            return

        extractor = SectionExtractor()
        parser = AnnotationParser()

        for lib_file in sorted(self.libraries_dir.glob("*.md")):
            lib_name = lib_file.stem  # e.g., "data" from "data.md"
            content = lib_file.read_text(encoding="utf-8")

            result = extractor.extract(content)
            self._library_ids[lib_name] = set()

            for id_value, section in result.sections.items():
                self._library_ids[lib_name].add(id_value)

                # Find what this section references and map to libraries
                refs = parser.parse_references(section.full_content)
                ref_ids = [r.id_value for r in refs if r.id_value != id_value]

                self.entries[id_value] = LibsEntry(
                    id_value=id_value,
                    primary=lib_name,
                    related=ref_ids,  # Store ref IDs, resolve to libs later
                )

        # Second pass: resolve ref IDs to library names
        for entry in self.entries.values():
            related_libs = set()
            for ref_id in entry.related:
                ref_entry = self.entries.get(ref_id)
                if ref_entry and ref_entry.primary != entry.primary:
                    related_libs.add(ref_entry.primary)
            entry.related = sorted(related_libs)

    def get_primary(self, id_value: str) -> str | None:
        """Get the primary library for an ID."""
        entry = self.entries.get(id_value)
        return entry.primary if entry else None

    def get_related(self, id_value: str) -> list[str]:
        """Get the related libraries for an ID."""
        entry = self.entries.get(id_value)
        return entry.related if entry else []

    def get_all_libraries(self) -> set[str]:
        """Get all unique library names."""
        return set(self._library_ids.keys())

    def get_ids_by_library(self, library: str) -> list[str]:
        """Get all IDs declared in a library."""
        return sorted(self._library_ids.get(library, set()))

    def get_ids_related_to_library(self, library: str) -> list[str]:
        """Get all IDs that reference a library."""
        return [entry.id_value for entry in self.entries.values() if library in entry.related]

    def iter_entries(self) -> Iterator[LibsEntry]:
        """Iterate over all entries."""
        yield from sorted(self.entries.values(), key=lambda e: e.id_value)

    # --- Divergence/Convergence Detection ---

    def detect_divergence_candidates(
        self, min_related_count: int = 3
    ) -> list[tuple[str, str, list[str]]]:
        """Detect potential library split candidates.

        A library is a divergence candidate if many of its IDs reference
        a different library, suggesting those IDs should move.

        Returns:
            List of (source_lib, target_lib, [ids]) tuples
        """
        candidates = []

        for lib_name, ids in self._library_ids.items():
            # Count how many IDs in this lib reference each other lib
            refs_to_lib: dict[str, list[str]] = {}

            for id_value in ids:
                entry = self.entries.get(id_value)
                if not entry:
                    continue
                for related_lib in entry.related:
                    if related_lib != lib_name:
                        refs_to_lib.setdefault(related_lib, []).append(id_value)

            for target_lib, referencing_ids in refs_to_lib.items():
                unique_ids = list(set(referencing_ids))
                if len(unique_ids) >= min_related_count:
                    candidates.append((lib_name, target_lib, unique_ids))

        return sorted(candidates, key=lambda x: -len(x[2]))

    def detect_convergence_candidates(
        self, min_cross_reference: int = 3
    ) -> list[tuple[str, str, list[str]]]:
        """Detect potential library merge candidates.

        Two libraries are convergence candidates if many IDs reference
        each other across the library boundary.

        Returns:
            List of (lib1, lib2, [shared_ids]) tuples
        """
        cross_refs: dict[tuple[str, str], set[str]] = {}

        for id_value, entry in self.entries.items():
            source_lib = entry.primary
            for related_lib in entry.related:
                pair = tuple(sorted([source_lib, related_lib]))
                cross_refs.setdefault(pair, set()).add(id_value)

        candidates = []
        for (lib1, lib2), shared_ids in cross_refs.items():
            if len(shared_ids) >= min_cross_reference:
                candidates.append((lib1, lib2, sorted(shared_ids)))

        return sorted(candidates, key=lambda x: -len(x[2]))

    # --- Modification Methods (for resolver compatibility) ---

    def add_entry(self, id_value: str, primary: str, related: list[str] | None = None) -> None:
        """Add or update an entry in the registry."""
        self.entries[id_value] = LibsEntry(
            id_value=id_value,
            primary=primary,
            related=related or [],
        )
        self._library_ids.setdefault(primary, set()).add(id_value)

    def remove_entry(self, id_value: str) -> bool:
        """Remove an entry from the registry."""
        if id_value in self.entries:
            entry = self.entries.pop(id_value)
            if entry.primary in self._library_ids:
                self._library_ids[entry.primary].discard(id_value)
            return True
        return False

    def save(self, path: Path | None = None) -> None:
        """No-op: registry is derived from library files, not stored."""
        pass

    def to_markdown(self) -> str:
        """Generate markdown summary (for debugging/display only)."""
        lines = ["# Library Structure (derived from annotations)", ""]
        for lib_name in sorted(self._library_ids.keys()):
            ids = sorted(self._library_ids[lib_name])
            lines.append(f"## {lib_name}")
            for id_value in ids:
                entry = self.entries.get(id_value)
                if entry and entry.related:
                    lines.append(f"- {id_value} → {', '.join(entry.related)}")
                else:
                    lines.append(f"- {id_value}")
            lines.append("")
        return "\n".join(lines)
