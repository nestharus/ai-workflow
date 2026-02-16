"""Runtime-observed test-pin baselining and persistence.

Persists hashes of runtime test identity observations associated with
pin-functions, providing a stable baseline for drift detection.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from spec_manager.projection.lineage.test_pin_discovery import (
        TestPinAssociation,
        TestPinMap,
    )


@dataclass
class TestSignatureBaseline:
    """Baseline signature of a single runtime-observed test identity."""

    test_file: str
    test_function: str
    pin_func_id: str
    signature_hash: str
    signature_text: str
    recorded_at: str
    status: str = "active"
    status_reason: str = ""
    supersedes_hash: str = ""
    superseded_at: str = ""
    superseded_by_hash: str = ""


@dataclass
class TestPinBaselineStore:
    """Persistent store of test-pin runtime signature baselines."""

    schema_version: str = "2.0"
    baselines: list[TestSignatureBaseline] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def get_baseline(self, test_file: str, test_function: str) -> TestSignatureBaseline | None:
        """Find a baseline entry by test file and function name."""
        candidates = [
            bl
            for bl in self.baselines
            if bl.test_file == test_file
            and bl.test_function == test_function
            and bl.status != "superseded"
        ]
        if not candidates:
            return None
        return candidates[-1]


def build_baseline(test_pin_map: TestPinMap) -> TestPinBaselineStore:
    """Build a baseline store from runtime test-pin association observations."""
    now = datetime.now(UTC).isoformat()
    baselines: list[TestSignatureBaseline] = []
    seen: set[tuple[str, str]] = set()

    for assoc in test_pin_map.associations:
        key = (assoc.test_file, assoc.test_function)
        if key in seen:
            continue
        seen.add(key)

        sig_hash = compute_test_signature_hash(test_pin_map, assoc.test_file, assoc.test_function)
        sig_text = _extract_test_signature_text(test_pin_map, assoc.test_file, assoc.test_function)

        primary_pin = _primary_pin_for_test(test_pin_map, assoc.test_file, assoc.test_function)
        status = "active"
        status_reason = ""
        if sig_hash is None:
            status = "missing_signature"
            status_reason = "signature_hash_unavailable_for_test_identity"

        baselines.append(
            TestSignatureBaseline(
                test_file=assoc.test_file,
                test_function=assoc.test_function,
                pin_func_id=primary_pin,
                signature_hash=sig_hash or "",
                signature_text=sig_text,
                recorded_at=now,
                status=status,
                status_reason=status_reason,
            )
        )

    return TestPinBaselineStore(
        schema_version="2.0",
        baselines=baselines,
        created_at=now,
        updated_at=now,
    )


def save_baseline(store: TestPinBaselineStore, path: Path) -> None:
    """Save the baseline store to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _store_to_dict(store)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_baseline(path: Path) -> TestPinBaselineStore:
    """Load a baseline store from a JSON file.

    Returns an empty store if the file does not exist.
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
    """Merge new runtime associations into an existing baseline store."""
    now = datetime.now(UTC).isoformat()
    changes: list[str] = []
    mutated = False

    new_baseline = build_baseline(new_map)

    for new_bl in new_baseline.baselines:
        old_bl = existing.get_baseline(new_bl.test_file, new_bl.test_function)
        if old_bl is not None:
            if old_bl.signature_hash != new_bl.signature_hash:
                if force:
                    old_bl.status = "superseded"
                    old_bl.status_reason = "superseded_by_forced_update"
                    old_bl.superseded_at = now
                    old_bl.superseded_by_hash = new_bl.signature_hash
                    new_bl.supersedes_hash = old_bl.signature_hash
                    new_bl.recorded_at = now
                    existing.baselines.append(new_bl)
                    mutated = True
                    changes.append(
                        f"Updated {new_bl.test_function} in {new_bl.test_file}: "
                        f"{old_bl.signature_hash} -> {new_bl.signature_hash}"
                    )
                else:
                    changes.append(
                        f"Drift detected for {new_bl.test_function} in {new_bl.test_file}: "
                        f"{old_bl.signature_hash} -> {new_bl.signature_hash}"
                    )
        else:
            existing.baselines.append(new_bl)
            mutated = True
            changes.append(f"Added new baseline for {new_bl.test_function} in {new_bl.test_file}")

    if mutated:
        existing.updated_at = now
    return existing, changes


def compute_test_signature_hash(
    test_pin_map: TestPinMap,
    test_file: str,
    test_function: str,
) -> str | None:
    """Compute hash for runtime test identity facts."""
    rows = _collect_associations(test_pin_map, test_file, test_function)
    if not rows:
        return None

    payload = {
        "test_file": test_file,
        "test_function": test_function,
        "associations": rows,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _extract_test_signature_text(
    test_pin_map: TestPinMap,
    test_file: str,
    test_function: str,
) -> str:
    """Extract human-readable runtime identity text used for baseline hashing."""
    rows = _collect_associations(test_pin_map, test_file, test_function)
    if not rows:
        return ""
    payload = {
        "test_file": test_file,
        "test_function": test_function,
        "associations": rows,
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _primary_pin_for_test(test_pin_map: TestPinMap, test_file: str, test_function: str) -> str:
    rows = _collect_associations(test_pin_map, test_file, test_function)
    if not rows:
        return ""
    return str(rows[0].get("pin_func_id", ""))


def _collect_associations(
    test_pin_map: TestPinMap,
    test_file: str,
    test_function: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for assoc in test_pin_map.associations:
        if assoc.test_file != test_file or assoc.test_function != test_function:
            continue
        rows.append(_association_to_row(assoc))
    rows.sort(
        key=lambda row: (
            str(row.get("pin_func_id", "")),
            str(row.get("association_type", "")),
        )
    )
    return rows


def _association_to_row(assoc: TestPinAssociation) -> dict[str, Any]:
    return {
        "pin_func_id": assoc.pin_func_id,
        "pin_function_name": assoc.pin_function_name,
        "association_type": assoc.association_type,
        "confidence": round(float(assoc.confidence), 6),
    }


def _store_to_dict(store: TestPinBaselineStore) -> dict[str, Any]:
    """Serialize a TestPinBaselineStore to a dictionary."""
    return {
        "schema_version": store.schema_version,
        "baselines": [asdict(bl) for bl in store.baselines],
        "created_at": store.created_at,
        "updated_at": store.updated_at,
    }


def _store_from_dict(data: dict[str, Any]) -> TestPinBaselineStore:
    """Deserialize a TestPinBaselineStore from a dictionary."""
    return TestPinBaselineStore(
        schema_version=data.get("schema_version", "2.0"),
        baselines=[TestSignatureBaseline(**bl) for bl in data.get("baselines", [])],
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
    )


__all__ = [
    "TestPinBaselineStore",
    "TestSignatureBaseline",
    "build_baseline",
    "compute_test_signature_hash",
    "load_baseline",
    "save_baseline",
    "update_baseline",
]
