from __future__ import annotations

import pytest
from pydantic import ValidationError
from spec_manager.schemas.sections import FileSections
from spec_manager.schemas.validation_utils import validate_atom_sequence


def test_file_sections_allows_empty_when_total_lines_zero() -> None:
    manifest = FileSections(file_id="F0001", sections=[], total_lines=0)

    assert manifest.sections == []
    assert manifest.total_lines == 0


def test_file_sections_rejects_empty_when_total_lines_missing() -> None:
    with pytest.raises(ValidationError):
        FileSections(file_id="F0001", sections=[])


def test_validate_atom_sequence_accepts_empty_when_total_lines_zero() -> None:
    assert validate_atom_sequence([], total_lines=0) == []
