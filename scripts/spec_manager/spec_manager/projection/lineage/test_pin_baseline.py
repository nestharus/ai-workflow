"""Test-span baselining and persistence.

Extracts and persists content hashes of test function spans associated with
pin-functions, providing a stable baseline for drift detection.
"""

from __future__ import annotations

import hashlib
import json
import logging
import textwrap
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spec_manager.core.code_analysis import RawFunctionInfo, analyze_source

if TYPE_CHECKING:
    from spec_manager.projection.lineage.test_pin_discovery import TestPinMap

logger = logging.getLogger(__name__)


@dataclass
class TestSignatureBaseline:
    """Baseline signature of a single test function.

    Attributes:
        test_file: Path to the test file.
        test_function: Fully qualified test function name.
        pin_func_id: The associated pin-function ID.
        signature_hash: Hash of normalized test span content.
        signature_text: Diagnostic text representation of captured test span.
        recorded_at: ISO-8601 timestamp of when the baseline was recorded.
    """

    test_file: str
    test_function: str
    pin_func_id: str
    signature_hash: str
    signature_text: str
    recorded_at: str


@dataclass
class TestPinBaselineStore:
    """Persistent store of all test-pin signature baselines.

    Attributes:
        schema_version: Schema version for forward compatibility.
        baselines: List of baseline entries.
        created_at: ISO-8601 timestamp of initial creation.
        updated_at: ISO-8601 timestamp of last update.
    """

    schema_version: str = "1.0"
    baselines: list[TestSignatureBaseline] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def get_baseline(self, test_file: str, test_function: str) -> TestSignatureBaseline | None:
        """Find a baseline entry by test file and function name.

        Args:
            test_file: Path to the test file.
            test_function: Fully qualified test function name.

        Returns:
            The matching baseline, or None if not found.
        """
        for bl in self.baselines:
            if bl.test_file == test_file and bl.test_function == test_function:
                return bl
        return None


def build_baseline(test_pin_map: TestPinMap) -> TestPinBaselineStore:
    """Build a baseline store from a test-pin association map.

    For each association, computes a span-content hash for the test
    function and stores a diagnostic text snapshot.

    Args:
        test_pin_map: The test-pin association map.

    Returns:
        A populated TestPinBaselineStore.
    """
    now = datetime.now(UTC).isoformat()
    baselines: list[TestSignatureBaseline] = []
    seen: set[tuple[str, str]] = set()

    for assoc in test_pin_map.associations:
        key = (assoc.test_file, assoc.test_function)
        if key in seen:
            continue
        seen.add(key)

        # Compute signature hash for the test function
        sig_hash = _compute_test_signature_hash(assoc.test_file, assoc.test_function)
        sig_text = _extract_test_signature_text(assoc.test_file, assoc.test_function)

        if sig_hash is None:
            logger.warning(
                "Could not compute signature hash for %s in %s",
                assoc.test_function,
                assoc.test_file,
            )
            continue

        baselines.append(
            TestSignatureBaseline(
                test_file=assoc.test_file,
                test_function=assoc.test_function,
                pin_func_id=assoc.pin_func_id,
                signature_hash=sig_hash,
                signature_text=sig_text,
                recorded_at=now,
            )
        )

    return TestPinBaselineStore(
        schema_version="1.0",
        baselines=baselines,
        created_at=now,
        updated_at=now,
    )


def save_baseline(store: TestPinBaselineStore, path: Path) -> None:
    """Save the baseline store to a JSON file.

    Args:
        store: The baseline store to persist.
        path: File path to write to (default: .spec/test_pin_baselines.json).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _store_to_dict(store)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_baseline(path: Path) -> TestPinBaselineStore:
    """Load a baseline store from a JSON file.

    Returns an empty store if the file does not exist.

    Args:
        path: File path to read from.

    Returns:
        The loaded or empty TestPinBaselineStore.
    """
    if not path.exists():
        return TestPinBaselineStore()

    raw = json.loads(path.read_text(encoding="utf-8"))
    return _store_from_dict(raw)


def update_baseline(
    existing: TestPinBaselineStore,
    new_map: TestPinMap,
    force: bool = False,
) -> tuple[TestPinBaselineStore, list[str]]:
    """Merge new associations into an existing baseline store.

    For new test functions, adds baseline entries. For existing entries
    whose signatures have changed, only overwrites if force=True.

    Args:
        existing: The existing baseline store.
        new_map: The new test-pin association map.
        force: If True, overwrite changed signatures.

    Returns:
        Tuple of (updated store, list of change descriptions).
    """
    now = datetime.now(UTC).isoformat()
    changes: list[str] = []

    # Build a lookup of existing baselines
    existing_lookup: dict[tuple[str, str], int] = {}
    for i, bl in enumerate(existing.baselines):
        existing_lookup[(bl.test_file, bl.test_function)] = i

    new_baseline = build_baseline(new_map)

    for new_bl in new_baseline.baselines:
        key = (new_bl.test_file, new_bl.test_function)
        if key in existing_lookup:
            idx = existing_lookup[key]
            old_bl = existing.baselines[idx]
            if old_bl.signature_hash != new_bl.signature_hash:
                if force:
                    existing.baselines[idx] = new_bl
                    changes.append(
                        f"Updated {new_bl.test_function} in {new_bl.test_file}: "
                        f"span hash changed ({old_bl.signature_hash} -> {new_bl.signature_hash})"
                    )
                else:
                    changes.append(
                        f"Drift detected for {new_bl.test_function} in {new_bl.test_file}: "
                        f"span hash changed ({old_bl.signature_hash} -> {new_bl.signature_hash})"
                    )
        else:
            existing.baselines.append(new_bl)
            changes.append(f"Added new baseline for {new_bl.test_function} in {new_bl.test_file}")

    existing.updated_at = now
    return existing, changes


def _compute_test_signature_hash(file_path: str, test_function: str) -> str | None:
    """Compute content hash for a test function span.

    Args:
        file_path: Path to the test file.
        test_function: Test function name, possibly class-qualified.

    Returns:
        SHA-256 hex digest of normalized span text, or None if not found.
    """
    func_info = _find_function_info(file_path, test_function)
    if func_info is None:
        return None

    span_text = _extract_function_span_text(file_path, func_info)
    if not span_text:
        return None

    normalized = textwrap.dedent(span_text).strip()
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _extract_test_signature_text(file_path: str, test_function: str) -> str:
    """Extract captured span text used for baseline hashing.

    Args:
        file_path: Path to the test file.
        test_function: Test function name, possibly class-qualified.

    Returns:
        Human-readable signature string, or empty string if not found.
    """
    func_info = _find_function_info(file_path, test_function)
    if func_info is None:
        return ""

    span_text = _extract_function_span_text(file_path, func_info)
    return textwrap.dedent(span_text).strip()


def _extract_function_span_text(file_path: str, func_info: RawFunctionInfo) -> str:
    path = Path(file_path)
    if not path.exists():
        return ""
    try:
        source = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""

    lines = source.splitlines()
    start = max(0, func_info.start_line - 1)
    end = min(len(lines), max(func_info.end_line, func_info.start_line))
    return "\n".join(lines[start:end])


def _find_function_info(file_path: str, test_function: str) -> RawFunctionInfo | None:
    """Find the RawFunctionInfo for a test function using analyze_source.

    Args:
        file_path: Path to the source file.
        test_function: Function name, possibly class-qualified (e.g., "TestClass.test_method").

    Returns:
        The matching RawFunctionInfo, or None if not found.
    """
    path = Path(file_path)
    if not path.exists():
        return None

    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None

    try:
        analysis = analyze_source(source, filepath=file_path)
    except Exception:
        logger.debug("Pin baseline test parse failed", exc_info=True)
        return None

    # Match by qualified_name for class methods, by name for top-level functions
    for func in analysis.functions:
        if func.qualified_name == test_function:
            return func
        # Also try matching just by name for simple (non-class-qualified) functions
        if "." not in test_function and func.name == test_function:
            return func

    return None


def _store_to_dict(store: TestPinBaselineStore) -> dict[str, Any]:
    """Serialize a TestPinBaselineStore to a dictionary.

    Args:
        store: The store to serialize.

    Returns:
        Dictionary representation.
    """
    return {
        "schema_version": store.schema_version,
        "baselines": [asdict(bl) for bl in store.baselines],
        "created_at": store.created_at,
        "updated_at": store.updated_at,
    }


def _store_from_dict(data: dict[str, Any]) -> TestPinBaselineStore:
    """Deserialize a TestPinBaselineStore from a dictionary.

    Args:
        data: Dictionary representation.

    Returns:
        Reconstructed TestPinBaselineStore.
    """
    return TestPinBaselineStore(
        schema_version=data.get("schema_version", "1.0"),
        baselines=[TestSignatureBaseline(**bl) for bl in data.get("baselines", [])],
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
    )


__all__ = [
    "TestPinBaselineStore",
    "TestSignatureBaseline",
    "build_baseline",
    "load_baseline",
    "save_baseline",
    "update_baseline",
]
