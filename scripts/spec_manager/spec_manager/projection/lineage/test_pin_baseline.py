"""Test signature baselining and persistence.

Extracts and persists the signatures of test functions associated with
pin-functions, providing a stable baseline for drift detection.
"""

from __future__ import annotations

import hashlib
import json
import logging
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
        signature_hash: MD5 hash from compute_signature_hash().
        signature_text: Human-readable signature string for diagnostics.
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

    For each association, computes the test function's signature hash
    and extracts the human-readable signature text.

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
                        f"signature changed ({old_bl.signature_hash} -> {new_bl.signature_hash})"
                    )
                else:
                    changes.append(
                        f"Drift detected for {new_bl.test_function} in {new_bl.test_file}: "
                        f"signature changed ({old_bl.signature_hash} -> {new_bl.signature_hash})"
                    )
        else:
            existing.baselines.append(new_bl)
            changes.append(f"Added new baseline for {new_bl.test_function} in {new_bl.test_file}")

    existing.updated_at = now
    return existing, changes


def _compute_test_signature_hash(file_path: str, test_function: str) -> str | None:
    """Compute signature hash for a test function, handling class-qualified names.

    For names like "TestClass.test_method", finds the method inside the class.
    For simple names like "test_foo", finds the top-level function.

    Args:
        file_path: Path to the test file.
        test_function: Test function name, possibly class-qualified.

    Returns:
        MD5 hex digest of the signature, or None if not found.
    """
    func_info = _find_function_info(file_path, test_function)
    if func_info is None:
        return None

    sig_parts = _extract_signature_parts_from_info(func_info)
    sig_str = "|".join(sig_parts)
    return hashlib.md5(sig_str.encode()).hexdigest()  # noqa: S324


def _extract_test_signature_text(file_path: str, test_function: str) -> str:
    """Extract human-readable signature text for a test function.

    Args:
        file_path: Path to the test file.
        test_function: Test function name, possibly class-qualified.

    Returns:
        Human-readable signature string, or empty string if not found.
    """
    func_info = _find_function_info(file_path, test_function)
    if func_info is None:
        return ""

    parts = _extract_signature_parts_from_info(func_info)
    return "|".join(parts)


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


def _extract_signature_parts_from_info(func_info: RawFunctionInfo) -> list[str]:
    """Extract signature components from a RawFunctionInfo.

    Produces output compatible with the original AST-based _extract_signature_parts:
    function name, then arg specs, then return annotation.

    Args:
        func_info: Function info from analyze_source.

    Returns:
        List of signature component strings.
    """
    parts: list[str] = [func_info.name]

    # Parameters: args is a tuple of strings like "param", "param: Type", etc.
    for arg_str in func_info.args:
        arg_str = arg_str.strip()
        if arg_str.startswith("*") and not arg_str.startswith("**"):
            # *args / vararg
            vararg_name = arg_str.lstrip("*").split(":")[0].strip()
            if vararg_name:
                parts.append(f"vararg:{vararg_name}")
        elif arg_str.startswith("**"):
            # **kwargs / kwarg
            kwarg_name = arg_str.lstrip("*").split(":")[0].strip()
            if kwarg_name:
                parts.append(f"kwarg:{kwarg_name}")
        else:
            # Regular arg or keyword-only arg
            if ":" in arg_str:
                name, annotation = arg_str.split(":", 1)
                name = name.strip()
                annotation = annotation.strip()
            else:
                name = arg_str
                annotation = ""
            parts.append(f"arg:{name}:{annotation}")

    # Return annotation
    if func_info.return_annotation:
        parts.append(f"return:{func_info.return_annotation}")

    return parts


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
