"""Workflow orchestrator - coordinates the full ingest workflow.

The orchestrator:
- Manages phase transitions
- Applies strategies at appropriate points
- Saves intermediate states
- Handles errors gracefully
"""

from __future__ import annotations

import json
import logging
import re
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from spec_manager.core.gaps import detect_gaps, format_gaps_md
from spec_manager.core.libs_registry import LibsRegistry
from spec_manager.core.sections import SectionExtractor
from spec_manager.workflow.config import (
    TrackedUnit,
    UnitLabels,
    UnitStatus,
    UnitType,
    WorkflowConfig,
    WorkflowPhase,
    WorkflowState,
)
from spec_manager.workflow.context import ContextIndex, PatchDependencyGraph

logger = logging.getLogger(__name__)


class Severity:
    """Severity levels for evidence."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class WorkflowEvidence:
    """Evidence collected during workflow execution.

    Named WorkflowEvidence (not GapEvidence) to avoid collision with:
    - DetectorFinding in gaps.py (raw detector output)
    - GapEvidence in data_structures.py (v2.0 evidence with invariant families)
    """

    severity: str
    message: str
    location: str
    detector: str = ""
    details: dict[str, Any] = field(default_factory=dict)


class IntermediateManager:
    """Manages intermediate state snapshots."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.intermediates_dir = workspace / "intermediates"
        self.intermediates_dir.mkdir(parents=True, exist_ok=True)
        self._version = 0

    def create_snapshot(
        self, phase: str, description: str, tracker: Any = None, **extra: Any
    ) -> dict[str, Any]:
        """Create a snapshot of the current state."""
        self._version += 1
        return {
            "version": self._version,
            "phase": phase,
            "description": description,
            "timestamp": datetime.now().isoformat(),
            "coverage_percent": 100.0,  # Placeholder
            **extra,
        }

    def save(self, state: dict[str, Any]) -> Path:
        """Save a state snapshot."""
        version = state.get("version", self._version)
        phase = state.get("phase", "unknown")
        filename = f"v{version:03d}_{phase}.json"
        path = self.intermediates_dir / filename
        path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        return path

    def load(self, version: int) -> dict[str, Any] | None:
        """Load a state by version number."""
        for path in self.intermediates_dir.glob(f"v{version:03d}_*.json"):
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def list_states(self) -> list[dict[str, Any]]:
        """List all saved states."""
        states = []
        for path in sorted(self.intermediates_dir.glob("v*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                states.append(data)
            except json.JSONDecodeError:
                continue
        return states

    def compare(self, state1: dict[str, Any], state2: dict[str, Any]) -> dict[str, Any]:
        """Compare two states."""
        return {
            "units_added": [],
            "units_removed": [],
            "status_changes": [],
            "coverage_change": {
                "from": state1.get("coverage_percent", 0),
                "to": state2.get("coverage_percent", 0),
            },
        }


class ProvenanceTracker:
    """Tracks provenance of content units."""

    def __init__(self) -> None:
        self.units: list[TrackedUnit] = []
        self._id_counter = 0

    def extract_units_from_file(
        self, content: str, file_path: str, patch_id: str
    ) -> list[TrackedUnit]:
        """Extract tracked units from a file."""
        units = []
        extractor = SectionExtractor()
        result = extractor.extract(content)

        for id_value, section in result.sections.items():
            unit_type = self._infer_unit_type(id_value, section.body)
            unit = TrackedUnit(
                id=id_value,
                content=section.full_content,
                unit_type=unit_type,
                source=file_path,
                introduced_by=patch_id,
                declarations=[id_value],
            )
            units.append(unit)
            self.units.append(unit)

        # Handle orphan content as prose
        if result.orphan_content.strip():
            self._id_counter += 1
            unit = TrackedUnit(
                id=f"prose_{patch_id}_{self._id_counter}",
                content=result.orphan_content,
                unit_type=UnitType.PROSE,
                source=file_path,
                introduced_by=patch_id,
            )
            units.append(unit)
            self.units.append(unit)

        return units

    def _infer_unit_type(self, id_value: str, body: str) -> UnitType:
        """Infer unit type from ID and content."""
        id_lower = id_value.lower()
        if id_lower.startswith("algorithm"):
            return UnitType.ALGORITHM
        elif re.match(r"^p?\d*c\d+$", id_lower):
            return UnitType.CLAIM
        elif re.match(r"^p?\d*i\d+$", id_lower):
            return UnitType.INVARIANT
        elif re.match(r"^g\d+$", id_lower):
            return UnitType.GOAL
        elif re.match(r"^d\d+$", id_lower):
            return UnitType.DATA_STRUCTURE
        elif id_lower.startswith("lean"):
            return UnitType.LEAN
        elif "proof" in id_lower:
            return UnitType.PROOF
        else:
            return UnitType.PROSE

    def get_coverage_report(self) -> dict[str, Any]:
        """Get a coverage report of tracked units."""
        total = len(self.units)
        mapped = sum(1 for u in self.units if u.status == UnitStatus.ACTIVE)
        dropped = sum(1 for u in self.units if u.status == UnitStatus.DROPPED)
        unaccounted = total - mapped - dropped

        return {
            "total": total,
            "mapped": mapped,
            "dropped": dropped,
            "unaccounted": unaccounted,
            "coverage_percent": (mapped / total * 100) if total > 0 else 100.0,
        }


class WorkflowOrchestrator:
    """Orchestrates the full ingest workflow.

    Usage:
        orchestrator = WorkflowOrchestrator(spec_folder)
        result = orchestrator.run()
    """

    def __init__(self, spec_folder: Path, config: WorkflowConfig | None = None) -> None:
        self.spec_folder = Path(spec_folder)
        self.config = config or WorkflowConfig()

        # Initialize components
        self.workspace = self.spec_folder / ".workspace"
        self.workspace.mkdir(exist_ok=True)

        self.tracker = ProvenanceTracker()
        self.intermediate_mgr = IntermediateManager(self.workspace)

        # Patch-chain + context index for entity resolution
        self.patch_graph = PatchDependencyGraph()
        self.context_index = ContextIndex(self.workspace)

        # State
        self.state = WorkflowState()

    def run(self) -> WorkflowState:
        """Run the full workflow:

        1. INIT       - Load inputs, extract units
        2. CLEANING   - Iterative clean with compliance gate
        3. COMPOSITING - Merge + remainder partition
        4. DISCOVERY  - Multi-label library identification (after compliance)
        5. REVIEW     - Concrete resolution actions
        6. SYNC       - plan.md <-> libraries synchronization
        7. FINALIZE   - Stamps removed, gaps.md, relations written
        """
        try:
            self._phase_init()
            self._phase_cleaning()
            self._phase_compositing()
            self._phase_discovery()
            self._phase_review()
            self._phase_sync()
            self._phase_finalize()

            self.state.phase = WorkflowPhase.COMPLETE
            logger.info("Workflow completed successfully")

        except Exception as e:
            logger.exception(f"Workflow failed: {e}")
            self.state.errors.append(str(e))
            raise

        return self.state

    def _phase_init(self) -> None:
        """Initialize: Load inputs, extract units.

        Support both patch layouts:
        1. patches/*.md - patch files in a patches subdirectory
        2. p*.md - patch files directly in spec folder (p1.md, p2.md, etc.)
        3. Existing plan.md + libraries/ - use as starting state
        """
        logger.info("Phase: INIT")
        self.state.phase = WorkflowPhase.INIT

        # Discover input files from multiple layouts
        patch_files: list[Path] = []

        # Layout 1: patches/*.md (preferred)
        patches_dir = self.spec_folder / "patches"
        if patches_dir.exists():
            patch_files.extend(sorted(patches_dir.glob("*.md")))
            logger.info(f"  Found {len(patch_files)} files in patches/ directory")

        # Layout 2: p*.md directly in spec_folder
        direct_patches = sorted(self.spec_folder.glob("p*.md"))
        # Filter to actual patch files (p1.md, p2.md, etc.) not plan.md or other files
        direct_patches = [p for p in direct_patches if re.match(r"^p\d+\.md$", p.name)]
        if direct_patches:
            patch_files.extend(direct_patches)
            logger.info(f"  Found {len(direct_patches)} direct patch files (p*.md)")

        # Also index existing plan.md + libraries/ as starting state
        existing_plan = self.spec_folder / "plan.md"
        existing_libraries = self.spec_folder / "libraries"

        if existing_plan.exists():
            logger.info("  Found existing plan.md - indexing as original stratum")
            self.context_index.add_stratum(
                existing_plan,
                existing_plan.read_text(encoding="utf-8"),
                priority=100,  # High priority - authoritative starting state
                stratum_type="original",
            )

        if existing_libraries.exists():
            for lib_file in existing_libraries.glob("*.md"):
                logger.info(f"  Found existing library: {lib_file.name}")
                self.context_index.add_stratum(
                    lib_file,
                    lib_file.read_text(encoding="utf-8"),
                    priority=100,
                    stratum_type="original",
                )

        # Validate we have at least some input
        if not patch_files and not existing_plan.exists():
            raise ValueError(
                f"No inputs found. Expected one of:\n"
                f"  - {patches_dir}/*.md\n"
                f"  - {self.spec_folder}/p*.md\n"
                f"  - {existing_plan} + {existing_libraries}/"
            )

        # Extract units from each patch
        for patch_file in patch_files:
            patch_id = patch_file.stem  # e.g., "p1", "p5"
            content = patch_file.read_text(encoding="utf-8")

            units = self.tracker.extract_units_from_file(
                content=content, file_path=str(patch_file), patch_id=patch_id
            )

            self.state.units.extend(units)
            logger.info(f"  Extracted {len(units)} units from {patch_file.name}")

            # Index patches as strata for entity resolution
            self.context_index.add_stratum(
                patch_file,
                content,
                priority=50,  # Lower than originals, higher than intermediates
                stratum_type="patch",
            )

            # Infer patch dependencies
            self.patch_graph.infer_from_content(content, patch_id)

        logger.info(f"  Total units: {len(self.state.units)}")

        # Save initial state
        if self.config.save_intermediates:
            state = self.intermediate_mgr.create_snapshot(
                phase="init", description="Initial extraction from patches", tracker=self.tracker
            )
            self.intermediate_mgr.save(state)

    def _phase_cleaning(self) -> None:
        """Clean inputs iteratively using Clean->Validate->Fix->Snapshot loop.

        Each pass reads from PREVIOUS INTERMEDIATE PROJECTION, not from the
        original source folder. This closes the loop so detectors operate
        on the evolving state.

        COMPLIANCE GATE: Library discovery is BLOCKED until:
        - Format compliance score > threshold (90%)
        - No critical errors
        - Remainder queue < threshold
        """
        logger.info("Phase: CLEANING (with compliance gate)")
        self.state.phase = WorkflowPhase.CLEANING

        current_projection_path: Path | None = None

        for pass_num in range(1, self.config.max_cleaning_passes + 1):
            self.state.cleaning_pass = pass_num
            logger.info(f"  Cleaning pass {pass_num}")

            # Step 1: Run validation against INTERMEDIATE PROJECTION
            # First pass: read from spec_folder
            # Subsequent passes: read from previous intermediate projection
            evidence = self._collect_evidence(current_projection_path)
            compliance_score = self._compute_compliance_score(evidence)
            logger.info(f"    Compliance score: {compliance_score:.1%}")

            # Step 2: Check compliance gate
            if compliance_score >= self.config.compliance_threshold:
                logger.info(
                    f"  Compliance gate PASSED "
                    f"({compliance_score:.1%} >= {self.config.compliance_threshold:.1%})"
                )
                break

            # Step 3: Apply fix strategies (placeholder - strategies module not implemented)
            # In a full implementation, this would apply registered fix strategies
            pass

            # Compute prose_ratio for this pass
            prose_ratio = self._compute_prose_ratio(self.state.units)
            logger.info(f"    Prose ratio: {prose_ratio:.1%}")

            # Step 4: Snapshot (versioned per pass) - BECOMES NEXT INPUT
            if self.config.save_intermediates:
                # Create versioned directory for this pass
                pass_dir = self.intermediate_mgr.intermediates_dir / f"cleaning_pass_{pass_num:02d}"
                pass_dir.mkdir(exist_ok=True)

                # Save composite.md - THIS BECOMES THE NEXT PASS INPUT
                composite_md = self._generate_composite_markdown(self.state.units)
                composite_path = pass_dir / "composite.md"
                composite_path.write_text(composite_md, encoding="utf-8")

                # Save plan.md projection for this pass
                plan_md = self._generate_plan_projection(self.state.units)
                (pass_dir / "plan.md").write_text(plan_md, encoding="utf-8")

                # Save evidence.json
                evidence_data = [
                    {"severity": e.severity, "message": e.message, "location": e.location}
                    for e in evidence
                ]
                (pass_dir / "evidence.json").write_text(
                    json.dumps(evidence_data, indent=2), encoding="utf-8"
                )

                # Save metrics.json
                metrics_data = {
                    "pass": pass_num,
                    "compliance_score": compliance_score,
                    "prose_ratio": prose_ratio,
                    "unit_count": len(self.state.units),
                    "prose_units": sum(
                        1
                        for u in self.state.units
                        if str(getattr(u, "unit_type", "")).lower() == "prose"
                        or u.unit_type == UnitType.PROSE
                    ),
                    "structured_units": sum(
                        1
                        for u in self.state.units
                        if u.unit_type
                        in (UnitType.ALGORITHM, UnitType.CLAIM, UnitType.INVARIANT, UnitType.GOAL)
                    ),
                }
                (pass_dir / "metrics.json").write_text(
                    json.dumps(metrics_data, indent=2), encoding="utf-8"
                )

                # Save state snapshot
                state = self.intermediate_mgr.create_snapshot(
                    phase=f"cleaning_pass_{pass_num}",
                    description=(
                        f"After cleaning pass {pass_num} "
                        f"(compliance: {compliance_score:.1%}, prose: {prose_ratio:.1%})"
                    ),
                    tracker=self.tracker,
                )
                self.intermediate_mgr.save(state)

                # UPDATE: Set current projection path for NEXT pass to read
                current_projection_path = pass_dir
                logger.info(f"    Intermediate saved: {pass_dir} (will be input for next pass)")

        # Final compliance check - THIS IS A TRUE GATE
        final_evidence = self._collect_evidence(current_projection_path)
        final_score = self._compute_compliance_score(final_evidence)
        has_critical = any(e.severity == Severity.ERROR for e in final_evidence)
        remainder_ratio = len(self.state.remainders) / max(len(self.state.units), 1)

        self.state.compliance_passed = False
        self.state.compliance_score = final_score
        self.state.compliance_details = {
            "score": final_score,
            "threshold": self.config.compliance_threshold,
            "has_critical_errors": has_critical,
            "remainder_ratio": remainder_ratio,
        }

        if final_score < self.config.compliance_threshold:
            if self.config.compliance_gate_mode == "block":
                logger.error(
                    f"  Compliance gate BLOCKED: "
                    f"{final_score:.1%} < {self.config.compliance_threshold:.1%}"
                )
                logger.error("     Discovery phase will be SKIPPED. Fix compliance issues first.")
            else:
                logger.warning(
                    f"  Compliance gate WARNING: {final_score:.1%} (mode=warn, continuing)"
                )
                self.state.compliance_passed = True
        elif has_critical and self.config.require_no_critical_errors:
            if self.config.compliance_gate_mode == "block":
                error_count = sum(1 for e in final_evidence if e.severity == Severity.ERROR)
                logger.error(f"  Compliance gate BLOCKED: {error_count} critical errors")
                logger.error("     Discovery phase will be SKIPPED. Fix critical errors first.")
            else:
                logger.warning("  Critical errors present but mode=warn, continuing")
                self.state.compliance_passed = True
        elif remainder_ratio > self.config.max_remainder_ratio:
            if self.config.compliance_gate_mode == "block":
                logger.error(
                    f"  Compliance gate BLOCKED: "
                    f"{remainder_ratio:.1%} atoms in remainder "
                    f"(max {self.config.max_remainder_ratio:.1%})"
                )
            else:
                logger.warning("  High remainder ratio but mode=warn, continuing")
                self.state.compliance_passed = True
        else:
            logger.info(f"  Compliance gate PASSED: {final_score:.1%}")
            self.state.compliance_passed = True

        # Store projection path in state for finalize phase
        self.state.current_projection_path = current_projection_path

    def _collect_evidence(self, projection_path: Path | None) -> list[WorkflowEvidence]:
        """Collect gap evidence from a path."""
        if projection_path and projection_path.exists():
            target_path = projection_path
        else:
            target_path = self.spec_folder

        # Build registry from libraries
        libraries_dir = self.spec_folder / "libraries"
        if libraries_dir.exists():
            registry = LibsRegistry.from_libraries(libraries_dir)
        else:
            registry = LibsRegistry()

        # Get content from the target path
        content = ""
        if target_path.is_dir():
            for md_file in target_path.glob("*.md"):
                content += md_file.read_text(encoding="utf-8") + "\n\n"
        elif target_path.is_file():
            content = target_path.read_text(encoding="utf-8")

        # Detect gaps
        gaps = detect_gaps(content, registry, libraries_dir)

        # Convert to WorkflowEvidence
        evidence = []
        for gap in gaps:
            evidence.append(
                WorkflowEvidence(
                    severity=gap.get("severity", "info"),
                    message=gap.get("description", ""),
                    location=gap.get("source_id", gap.get("id", "unknown")),
                    detector=gap.get("type", "unknown"),
                    details=gap,
                )
            )

        return evidence

    def _compute_compliance_score(self, evidence: list[WorkflowEvidence]) -> float:
        """Compute compliance score from evidence (0-1)."""
        if not evidence:
            return 1.0

        # Count by severity
        errors = sum(1 for e in evidence if e.severity == Severity.ERROR)
        warnings = sum(1 for e in evidence if e.severity == Severity.WARNING)

        # Simple scoring: each error = -10%, each warning = -2%
        penalty = (errors * 0.10) + (warnings * 0.02)
        return max(0.0, 1.0 - penalty)

    def _phase_compositing(self) -> None:
        """Composite units using MERGE + REMAINDER PARTITION.

        NOT just "latest wins" - instead:
        - Keep unchanged atoms + updated atoms
        - Carry unresolved atoms as remainder
        - Persist composite artifacts as intermediate markdown
        """
        logger.info("Phase: COMPOSITING (merge + remainder)")
        self.state.phase = WorkflowPhase.COMPOSITING

        # Select granularity level for compositing
        granularity = self._select_compositing_granularity()
        logger.info(f"  Using granularity level: {granularity}")

        # Group units by ID to find overlaps
        units_by_id: dict[str, list[TrackedUnit]] = {}
        for unit in self.state.units:
            if unit.id not in units_by_id:
                units_by_id[unit.id] = []
            units_by_id[unit.id].append(unit)

        # Handle overlaps with merge + remainder
        composited_units: list[TrackedUnit] = []
        remainder_units: list[TrackedUnit] = []

        for id_value, units in units_by_id.items():
            if len(units) == 1:
                composited_units.append(units[0])
            else:
                # Multiple patches define this ID - merge with remainder
                composited, remainder = self._merge_with_remainder(units, granularity)
                composited_units.append(composited)
                if remainder:
                    remainder_units.extend(remainder)
                logger.info(f"  Merged {id_value} from {len(units)} sources")
                if remainder:
                    logger.info(f"    Remainder: {len(remainder)} unresolved atoms")

        self.state.units = composited_units
        self.state.remainders = remainder_units

        # Persist composite artifacts as intermediate markdown
        if self.config.save_intermediates:
            composite_md = self._generate_composite_markdown(composited_units)
            composite_path = self.intermediate_mgr.intermediates_dir / "composite.md"
            composite_path.write_text(composite_md, encoding="utf-8")
            logger.info(f"  Saved composite.md ({len(composite_md)} chars)")

            state = self.intermediate_mgr.create_snapshot(
                phase="compositing",
                description=(
                    f"After compositing: {len(composited_units)} units, "
                    f"{len(remainder_units)} remainders"
                ),
                tracker=self.tracker,
            )
            self.intermediate_mgr.save(state)

    def _select_compositing_granularity(self) -> str:
        """Select the appropriate granularity level for compositing.

        When annotations are sparse, emit fine atoms (line/sentence).
        When well-annotated, use coarser section-level atomization.

        Returns: 'line', 'sentence', 'clause', or 'section'
        """
        # Count annotation density across all units
        total_decls = 0
        total_lines = 0

        for unit in self.state.units:
            content = getattr(unit, "content", "")
            decl_count = content.count("([=")
            line_count = len(content.splitlines())
            total_decls += decl_count
            total_lines += line_count

        if total_lines == 0:
            return "line"  # Default to finest granularity

        density = total_decls / total_lines

        # Granularity ladder
        if density > 0.1:
            # Well-annotated: use section-level
            return "section"
        elif density > 0.05:
            # Moderately annotated: use sentence-level
            return "sentence"
        elif density > 0.02:
            # Sparse annotations: use clause-level
            return "clause"
        else:
            # Very sparse: use line-level for maximum tracking
            return "line"

    def _merge_with_remainder(
        self, units: list[TrackedUnit], granularity: str = "line"
    ) -> tuple[TrackedUnit, list[TrackedUnit]]:
        """Merge multiple units with same ID using ATOM-BASED MEMBERSHIP.

        Does NOT use set-of-lines (destroys order/duplicates).
        Instead, uses diff hunks with stable atom IDs.

        Returns: (merged_unit, remainder_units)
        """

        # Sort by patch order (p1 < p5 < p10)
        def patch_order(u: TrackedUnit) -> int:
            patch_id = u.introduced_by
            if patch_id.startswith("p"):
                try:
                    return int(patch_id[1:])
                except ValueError:
                    return 999
            return 999

        sorted_units = sorted(units, key=patch_order)
        base = sorted_units[0]  # Start from earliest

        # Convert to atoms with stable IDs
        base_atoms = self._content_to_atoms(base.content, base.introduced_by, granularity)
        membership_evidence: dict[str, dict[str, Any]] = {}

        # Track all atoms through transformations
        all_atoms = list(base_atoms)  # Ordered list, not set
        remainder_atoms: list[dict[str, Any]] = []
        lineage_edges: list[dict[str, Any]] = []

        # Apply each subsequent patch using diff hunks
        for later_unit in sorted_units[1:]:
            later_atoms = self._content_to_atoms(
                later_unit.content, later_unit.introduced_by, granularity
            )

            # Use SequenceMatcher for diff hunks (preserves order)
            matcher = SequenceMatcher(
                None, [a["content"] for a in all_atoms], [a["content"] for a in later_atoms]
            )

            new_atoms: list[dict[str, Any]] = []
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag == "equal":
                    # Unchanged atoms - carry forward with lineage
                    for idx in range(i1, i2):
                        atom = all_atoms[idx].copy()
                        atom["status"] = "unchanged"
                        new_atoms.append(atom)
                        # Record membership evidence
                        membership_evidence[atom["id"]] = {
                            "rationale": "Unchanged through patch",
                            "confidence": 1.0,
                            "method": "exact_match",
                        }

                elif tag == "replace":
                    # Modified atoms - later patch wins, old goes to remainder
                    for idx in range(i1, i2):
                        old_atom = all_atoms[idx]
                        remainder_atoms.append(
                            {
                                **old_atom,
                                "status": "replaced",
                                "replaced_by": later_unit.introduced_by,
                            }
                        )

                    for idx in range(j1, j2):
                        new_atom = later_atoms[idx].copy()
                        new_atom["status"] = "added"
                        new_atoms.append(new_atom)
                        # Record lineage edge (many-to-many possible)
                        for old_idx in range(i1, i2):
                            lineage_edges.append(
                                {
                                    "from": all_atoms[old_idx]["id"],
                                    "to": new_atom["id"],
                                    "transformation": "replace",
                                    "patch": later_unit.introduced_by,
                                }
                            )
                        membership_evidence[new_atom["id"]] = {
                            "rationale": f"Replaced by {later_unit.introduced_by}",
                            "confidence": 0.9,
                            "method": "diff_replace",
                        }

                elif tag == "delete":
                    # Deleted atoms - go to remainder
                    for idx in range(i1, i2):
                        remainder_atoms.append(
                            {
                                **all_atoms[idx],
                                "status": "deleted",
                                "deleted_by": later_unit.introduced_by,
                            }
                        )

                elif tag == "insert":
                    # New atoms from later patch
                    for idx in range(j1, j2):
                        new_atom = later_atoms[idx].copy()
                        new_atom["status"] = "added"
                        new_atoms.append(new_atom)
                        membership_evidence[new_atom["id"]] = {
                            "rationale": f"Added by {later_unit.introduced_by}",
                            "confidence": 1.0,
                            "method": "diff_insert",
                        }

            all_atoms = new_atoms

        # Convert atoms back to content (preserves order)
        merged_content = "\n".join(a["content"] for a in all_atoms)

        # Create merged unit with membership tracking
        merged = TrackedUnit(
            id=base.id,
            content=merged_content,
            unit_type=base.unit_type,
            source=sorted_units[-1].source,
            introduced_by=base.introduced_by,
            modified_by=[u.introduced_by for u in sorted_units[1:]],
            declarations=sorted_units[-1].declarations,
            references=sorted_units[-1].references,
            source_atom_ids=[a["id"] for a in all_atoms],
            membership_evidence=membership_evidence,
            lineage_edges=lineage_edges,
        )

        # Create remainder units for unresolved content
        remainders: list[TrackedUnit] = []
        if remainder_atoms:
            remainder_content = "\n".join(
                f"[{a.get('deleted_by', a.get('replaced_by', 'unknown'))}] {a['content']}"
                for a in remainder_atoms
            )
            remainder_unit = TrackedUnit(
                id=f"{base.id}_remainder",
                content=remainder_content,
                unit_type=UnitType.PROSE,
                source=base.source,
                introduced_by="composite",
                status=UnitStatus.PENDING,
                source_atom_ids=[a["id"] for a in remainder_atoms],
            )
            remainders.append(remainder_unit)

        return merged, remainders

    def _content_to_atoms(
        self, content: str, source_id: str, granularity: str = "line"
    ) -> list[dict[str, Any]]:
        """Convert content to atoms with stable IDs.

        Granularity ladder drives atom size:
        - 'line': One atom per line (maximum tracking fidelity)
        - 'sentence': One atom per sentence
        - 'clause': One atom per clause (using NLP)
        - 'section': One atom per annotated section

        Atoms preserve order and multiplicity (unlike sets).
        Each atom has: id, content, source, line_number
        """
        atoms: list[dict[str, Any]] = []

        if granularity == "line":
            # Line-level atomization (default, maximum tracking)
            for i, line in enumerate(content.split("\n")):
                atom_id = f"{source_id}_L{i + 1}_{hash(line) % 10000:04d}"
                atoms.append(
                    {
                        "id": atom_id,
                        "content": line,
                        "source": source_id,
                        "line_number": i + 1,
                        "granularity": "line",
                    }
                )

        elif granularity == "sentence":
            # Sentence-level atomization
            sentences = re.split(r"(?<=[.!?])\s+", content)
            line_num = 1
            for i, sent in enumerate(sentences):
                sent = sent.strip()
                if not sent:
                    continue
                atom_id = f"{source_id}_S{i + 1}_{hash(sent) % 10000:04d}"
                atoms.append(
                    {
                        "id": atom_id,
                        "content": sent,
                        "source": source_id,
                        "line_number": line_num,
                        "granularity": "sentence",
                    }
                )
                line_num += sent.count("\n") + 1

        elif granularity == "clause":
            # Clause-level atomization (using conjunctions and semicolons)
            clauses = re.split(r";\s*|\s+and\s+|\s+or\s+", content)
            line_num = 1
            for i, clause in enumerate(clauses):
                clause = clause.strip()
                if not clause:
                    continue
                atom_id = f"{source_id}_CL{i + 1}_{hash(clause) % 10000:04d}"
                atoms.append(
                    {
                        "id": atom_id,
                        "content": clause,
                        "source": source_id,
                        "line_number": line_num,
                        "granularity": "clause",
                    }
                )
                line_num += clause.count("\n") + 1

        elif granularity == "section":
            # Section-level atomization (using annotations and headers)
            section_pattern = re.compile(r"(?=\(\[=|\n##+ )")
            sections = section_pattern.split(content)
            line_num = 1
            for i, section in enumerate(sections):
                section = section.strip()
                if not section:
                    continue
                # Extract section ID if available
                decl_match = re.search(r"\(\[=([^\]]+)\]\)", section)
                if decl_match:
                    section_name = decl_match.group(1)
                    atom_id = f"{source_id}_{section_name}_{hash(section) % 10000:04d}"
                else:
                    atom_id = f"{source_id}_SEC{i + 1}_{hash(section) % 10000:04d}"
                atoms.append(
                    {
                        "id": atom_id,
                        "content": section,
                        "source": source_id,
                        "line_number": line_num,
                        "granularity": "section",
                    }
                )
                line_num += section.count("\n") + 1

        return atoms

    def _generate_composite_markdown(self, units: list[TrackedUnit]) -> str:
        """Generate markdown representation of composite state."""
        lines = ["# Composite State\n"]
        lines.append(f"Generated: {datetime.now().isoformat()}\n")
        lines.append(f"Units: {len(units)}\n\n")

        for unit in sorted(units, key=lambda u: u.id):
            lines.append(f"## {unit.id}\n")
            unit_type = (
                unit.unit_type.value if hasattr(unit.unit_type, "value") else str(unit.unit_type)
            )
            lines.append(f"Type: {unit_type}\n")
            lines.append(f"Introduced: {unit.introduced_by}\n")
            if unit.modified_by:
                lines.append(f"Modified: {', '.join(unit.modified_by)}\n")
            lines.append(f"\n```\n{unit.content}\n```\n\n")

        return "\n".join(lines)

    def _generate_plan_projection(self, units: list[TrackedUnit]) -> str:
        """Generate plan.md projection from current units.

        This creates a unified view that can be compared against library state.
        """
        lines = ["# Plan (Intermediate Projection)\n"]
        lines.append(f"Generated: {datetime.now().isoformat()}\n")
        lines.append(f"Units: {len(units)}\n\n")

        # Group by unit type
        by_type: dict[str, list[TrackedUnit]] = {}
        for unit in units:
            type_name = (
                unit.unit_type.value if hasattr(unit.unit_type, "value") else str(unit.unit_type)
            )
            if type_name not in by_type:
                by_type[type_name] = []
            by_type[type_name].append(unit)

        # Output each type section
        type_order = [
            "algorithm",
            "claim",
            "invariant",
            "goal",
            "data_structure",
            "proof",
            "lean",
            "prose",
        ]
        for type_name in type_order:
            if type_name in by_type:
                lines.append(f"## {type_name.replace('_', ' ').title()}s\n")
                for unit in sorted(by_type[type_name], key=lambda u: u.id):
                    lines.append(f"### {unit.id} ([={unit.id}])\n")
                    lines.append(f"{unit.content}\n")
                    lines.append("---\n")
                lines.append("\n")

        # Add remaining types not in order
        for type_name, type_units in by_type.items():
            if type_name not in type_order:
                lines.append(f"## {type_name.replace('_', ' ').title()}s\n")
                for unit in sorted(type_units, key=lambda u: u.id):
                    lines.append(f"### {unit.id}\n")
                    lines.append(f"{unit.content}\n")
                    lines.append("---\n")

        return "\n".join(lines)

    def _phase_discovery(self) -> None:
        """Discover libraries through multi-labeling.

        This phase is BLOCKED if compliance gate did not pass.
        """
        logger.info("Phase: DISCOVERY")
        self.state.phase = WorkflowPhase.DISCOVERY

        # COMPLIANCE GATE CHECK
        if not getattr(self.state, "compliance_passed", False):
            logger.warning("  SKIPPING discovery - compliance gate not passed")
            logger.warning(f"     Compliance: {getattr(self.state, 'compliance_score', 0):.1%}")
            logger.warning(f"     Details: {getattr(self.state, 'compliance_details', {})}")
            logger.warning("  To force discovery, set compliance_gate_mode='warn' in config")
            return  # Skip discovery entirely

        # Simple library discovery: assign units to libraries based on type
        # In a full implementation, this would use CandidateIdentifier, MultiLabeler, etc.
        library_assignments: dict[str, list[TrackedUnit]] = {}

        for unit in self.state.units:
            # Determine library based on unit type
            unit_type = unit.unit_type
            if unit_type == UnitType.ALGORITHM:
                lib_name = "algorithms"
            elif unit_type == UnitType.CLAIM:
                lib_name = "claims"
            elif unit_type == UnitType.INVARIANT:
                lib_name = "invariants"
            elif unit_type == UnitType.GOAL:
                lib_name = "goals"
            elif unit_type == UnitType.DATA_STRUCTURE:
                lib_name = "data_structures"
            elif unit_type == UnitType.PROOF:
                lib_name = "proofs"
            elif unit_type == UnitType.LEAN:
                lib_name = "lean"
            else:
                lib_name = "other"

            if lib_name not in library_assignments:
                library_assignments[lib_name] = []
            library_assignments[lib_name].append(unit)
            unit.primary_library = lib_name

        # Update state
        self.state.candidate_libraries = list(library_assignments.keys())
        self.state.library_shapes = {
            name: {"strong": len(units), "medium": 0, "convergence": 1.0}
            for name, units in library_assignments.items()
        }

        # Create final labels
        for unit in self.state.units:
            self.state.final_labels[unit.id] = UnitLabels(
                primary=unit.primary_library, relations=[], confidence=1.0
            )

        logger.info(f"  Identified {len(library_assignments)} candidate libraries")
        for lib_name, units in library_assignments.items():
            logger.info(f"    {lib_name}: {len(units)} units")

        # Save intermediate
        if self.config.save_intermediates:
            state = self.intermediate_mgr.create_snapshot(
                phase="discovery",
                description="After library discovery",
                tracker=self.tracker,
                candidate_libraries=self.state.candidate_libraries,
                library_shapes=self.state.library_shapes,
            )
            self.intermediate_mgr.save(state)

    def _phase_review(self) -> None:
        """Review libraries for overlap and resolve conflicts.

        - Enforce proof-chain non-authoritative state in projections
        - Produce concrete actions (merge/split/drop/legacy) with provenance
        """
        logger.info("Phase: REVIEW")
        self.state.phase = WorkflowPhase.REVIEW

        # Check proof chains for non-authoritative elements
        logger.info("  Checking proof chains for non-authoritative elements...")
        non_authoritative_units: set[str] = set()

        for unit in self.state.units:
            # Check if this unit type requires proof chain
            unit_type = getattr(unit, "unit_type", None)
            if unit_type and unit_type == UnitType.ALGORITHM:
                content = getattr(unit, "content", "")

                # Check for claim references in algorithms
                has_claim_ref = bool(re.search(r"\(@\[\+?P?\d*C\d+\]\)", content))
                has_claim_mention = bool(re.search(r"\bP?\d*C\d+\b", content))

                if not has_claim_ref and not has_claim_mention:
                    non_authoritative_units.add(unit.id)
                    unit.status = UnitStatus.NON_AUTHORITATIVE

        if non_authoritative_units:
            logger.warning(
                f"  {len(non_authoritative_units)} units marked NON_AUTHORITATIVE "
                "(broken proof chain)"
            )
            for unit_id in list(non_authoritative_units)[:5]:
                logger.warning(f"      - {unit_id}")
            if len(non_authoritative_units) > 5:
                logger.warning(f"      ... and {len(non_authoritative_units) - 5} more")

        self.state.non_authoritative_units = list(non_authoritative_units)

        # LIBRARY REVIEW ACTIONS
        # Produce concrete actions: merge/split/drop/legacy with provenance justification
        review_actions: list[dict[str, Any]] = []

        # Use RELATIVE, PER-INGEST PROVENANCE ordering instead of hardcoded thresholds
        all_patch_nums = []
        for unit in self.state.units:
            p = getattr(unit, "introduced_by", "")
            if p.startswith("p"):
                with suppress(ValueError):
                    all_patch_nums.append(int(p[1:]))

        max_patch_in_ingest = max(all_patch_nums) if all_patch_nums else 1
        min_patch_in_ingest = min(all_patch_nums) if all_patch_nums else 1
        patch_range = max_patch_in_ingest - min_patch_in_ingest + 1

        # Define "early" as first third of the patch range (relative, not hardcoded < 3)
        early_threshold = min_patch_in_ingest + max(1, patch_range // 3)
        logger.info(
            f"  Relative provenance thresholds: early={early_threshold}, range={patch_range}"
        )

        # Analyze overlap between libraries
        if hasattr(self.state, "library_shapes") and self.state.library_shapes:
            logger.info("  Analyzing library overlap for concrete actions...")

            for lib_name, shape_info in self.state.library_shapes.items():
                lib_units = [
                    u for u in self.state.units if getattr(u, "primary_library", None) == lib_name
                ]

                # Check for merge candidates (high overlap)
                convergence = shape_info.get("convergence", 0)
                if convergence < 0.5:  # Low convergence suggests split
                    review_actions.append(
                        {
                            "action": "SPLIT",
                            "target": lib_name,
                            "provenance": (
                                f"Low convergence ({convergence:.2f}) suggests internal divergence"
                            ),
                            "confidence": 1 - convergence,
                            "auto_applicable": False,
                            "proposed_implementation": (
                                f"Split {lib_name} into sub-libraries based on clustering"
                            ),
                        }
                    )

                # Check for empty/deprecated libraries
                if len(lib_units) == 0:
                    review_actions.append(
                        {
                            "action": "DROP",
                            "target": lib_name,
                            "provenance": "No elements assigned to library",
                            "confidence": 1.0,
                            "auto_applicable": True,
                        }
                    )

                # Check for legacy artifacts - Use RELATIVE thresholds
                if lib_units:
                    patches = [getattr(u, "introduced_by", "") for u in lib_units]
                    patch_nums = []
                    for p in patches:
                        if p.startswith("p"):
                            with suppress(ValueError):
                                patch_nums.append(int(p[1:]))

                    # Use relative threshold instead of hardcoded < 3
                    if patch_nums and max(patch_nums) < early_threshold:
                        # Check if this library is referenced elsewhere
                        is_referenced = any(
                            lib_name in getattr(u, "relation_libraries", [])
                            for u in self.state.units
                            if getattr(u, "primary_library", None) != lib_name
                        )

                        review_actions.append(
                            {
                                "action": "LEGACY",
                                "target": lib_name,
                                "provenance": (
                                    f"All elements from early patches "
                                    f"(p{min(patch_nums)}-p{max(patch_nums)}), "
                                    f"before threshold p{early_threshold}"
                                ),
                                "confidence": 0.7 if not is_referenced else 0.4,
                                "auto_applicable": (
                                    not is_referenced
                                    and self._is_fully_superseded(lib_name, lib_units)
                                ),
                                "is_referenced": is_referenced,
                                "proposed_implementation": (
                                    f"Archive {lib_name} to legacy/ folder"
                                    if not is_referenced
                                    else f"Review references before archiving {lib_name}"
                                ),
                            }
                        )

        # Store review actions
        self.state.review_actions = review_actions

        if review_actions:
            logger.info(f"  Review produced {len(review_actions)} concrete actions:")
            for action in review_actions[:5]:
                logger.info(
                    f"    {action['action']}: {action['target']} ({action['provenance'][:50]}...)"
                )

        # Save intermediate
        if self.config.save_intermediates:
            state = self.intermediate_mgr.create_snapshot(
                phase="review",
                description="After library review",
                tracker=self.tracker,
                candidate_libraries=self.state.candidate_libraries,
                library_shapes=self.state.library_shapes,
                review_actions=self.state.review_actions,
                non_authoritative_units=self.state.non_authoritative_units,
            )
            self.intermediate_mgr.save(state)

    def _phase_sync(self) -> None:
        """Synchronize plan.md <-> libraries.

        AUTHORITY IS NOT CONFIGURABLE.
        - LIBRARIES are authoritative (always, at finalization)
        - plan.md is ALWAYS REGENERATED from libraries (it's a projection/unified view)
        - "Plan-only" content becomes DRIFT EVIDENCE + REMAINDER, never a competing authority

        This phase detects drift to surface in gaps.md, but does NOT make plan.md authoritative.
        """
        logger.info("Phase: SYNC (libraries -> plan.md projection)")
        self.state.phase = WorkflowPhase.SYNC

        plan_path = self.spec_folder / "plan.md"
        libraries_dir = self.spec_folder / "libraries"

        drift_evidence: list[dict[str, Any]] = []
        plan_only_remainder: list[dict[str, Any]] = []

        # If existing plan.md exists, check for content that isn't in libraries (drift)
        if plan_path.exists() and libraries_dir.exists():
            plan_content = plan_path.read_text(encoding="utf-8")

            # Convert plan to atoms with stable IDs
            plan_atoms = self._content_to_atoms(plan_content, "plan", "line")

            # Collect all library atoms (multiset - preserves duplicates)
            library_atoms: list[dict[str, Any]] = []
            for lib_file in libraries_dir.glob("*.md"):
                lib_content = lib_file.read_text(encoding="utf-8")
                lib_atoms = self._content_to_atoms(lib_content, lib_file.stem, "line")
                library_atoms.extend(lib_atoms)

            # Use SequenceMatcher for sequence-aware comparison
            lib_lines = [a["content"] for a in library_atoms if a["content"].strip()]

            # Create a set of library content for quick lookup
            lib_content_set = set(lib_lines)

            # Find plan-only content -> this is DRIFT, not authority
            for atom in plan_atoms:
                line_stripped = atom["content"].strip()
                if line_stripped and not line_stripped.startswith("#") and line_stripped != "---":
                    if line_stripped not in lib_content_set:
                        # Also check for fuzzy matches
                        best_match_ratio = 0.0
                        for lib_line in lib_lines:
                            ratio = SequenceMatcher(None, line_stripped, lib_line).ratio()
                            if ratio > best_match_ratio:
                                best_match_ratio = ratio

                        # Only mark as drift if no good fuzzy match
                        if best_match_ratio < 0.85:
                            plan_only_remainder.append(
                                {
                                    "line": atom["line_number"],
                                    "content": line_stripped[:100],
                                    "type": "plan_only_drift",
                                    "best_fuzzy_match": best_match_ratio,
                                    "atom_id": atom["id"],
                                }
                            )

            if plan_only_remainder:
                drift_evidence.append(
                    {
                        "type": "plan_only_content",
                        "description": (
                            "Content in plan.md not found in any library "
                            "(will be lost on regeneration)"
                        ),
                        "lines_count": len(plan_only_remainder),
                        "samples": plan_only_remainder[:5],
                        "severity": "warning",
                        "action": "Either add to a library or accept as intentional removal",
                    }
                )
                logger.warning(
                    f"  {len(plan_only_remainder)} lines in plan.md not in libraries (drift)"
                )
                logger.warning("     These will be LOST when plan.md is regenerated from libraries")

        if drift_evidence:
            logger.info(f"  Detected {len(drift_evidence)} drift issues -> gaps.md")

        self.state.sync_drift = drift_evidence
        self.state.plan_only_remainder = plan_only_remainder

    def _phase_finalize(self) -> None:
        """Finalize: Remove stamps, generate output, write relations.

        - Stamps are REMOVED from output files (explicit step with test)
        - plan.md is generated from authoritative library state
        - Non-authoritative units are quarantined
        - Relations are WRITTEN to output libraries
        - Gaps.md includes drift from sync phase
        """
        logger.info("Phase: FINALIZE")
        self.state.phase = WorkflowPhase.FINALIZE

        # Run gap detection on PROJECTION OUTPUT, not original spec_folder
        projection_path = getattr(self.state, "current_projection_path", None)

        libraries_dir = self.spec_folder / "libraries"
        if libraries_dir.exists():
            registry = LibsRegistry.from_libraries(libraries_dir)
        else:
            registry = LibsRegistry()

        if projection_path and Path(projection_path).exists():
            logger.info(f"  Running gap detection on projection output: {projection_path}")
            content = ""
            for md_file in Path(projection_path).glob("*.md"):
                content += md_file.read_text(encoding="utf-8") + "\n\n"
            gaps = detect_gaps(content, registry, libraries_dir)
        else:
            # Fallback to spec_folder if no projection available
            logger.warning("  No projection path available, falling back to spec_folder")
            content = ""
            for md_file in self.spec_folder.glob("*.md"):
                content += md_file.read_text(encoding="utf-8") + "\n\n"
            gaps = detect_gaps(content, registry, libraries_dir)

        # Add sync drift as gap evidence
        for drift in getattr(self.state, "sync_drift", []):
            gaps.append(
                {
                    "type": "library_drift",
                    "severity": "warning",
                    "description": f"Library drift: {drift.get('type', 'unknown')}",
                    "details": drift,
                }
            )

        gaps_md = format_gaps_md(gaps)

        # Write gaps.md
        gaps_path = self.spec_folder / "gaps.md"
        gaps_path.write_text(gaps_md, encoding="utf-8")
        logger.info(f"  Wrote {len(gaps)} gaps to gaps.md")

        # Write libraries (with relations preserved)
        libraries_dir.mkdir(exist_ok=True)

        # Group units by primary library (excluding non-authoritative)
        by_library: dict[str, list[TrackedUnit]] = {}
        quarantined: list[TrackedUnit] = []

        for unit in self.state.units:
            # Quarantine non-authoritative units
            if unit.id in getattr(self.state, "non_authoritative_units", []):
                quarantined.append(unit)
                continue

            labels = self.state.final_labels.get(unit.id)
            if labels and labels.primary:
                lib = labels.primary
                if lib not in by_library:
                    by_library[lib] = []
                by_library[lib].append(unit)

        if quarantined:
            logger.warning(f"  {len(quarantined)} units quarantined (non-authoritative)")

        # Write each library (with relations, stamps stripped)
        for lib_name, units in by_library.items():
            lib_path = libraries_dir / f"{lib_name}.md"
            content = self._format_library_with_relations(lib_name, units)

            # STAMP STRIPPING
            content = self._strip_provenance_stamps(content)

            lib_path.write_text(content, encoding="utf-8")
            logger.info(f"  Wrote {len(units)} elements to {lib_name}.md")

        # PLAN.MD PROJECTION FROM LIBRARIES
        # plan.md is a deterministic projection of authoritative library state
        logger.info("  Generating plan.md from authoritative library state...")
        plan_content = self._generate_plan_from_libraries(by_library)

        # Strip stamps from plan.md too
        plan_content = self._strip_provenance_stamps(plan_content)

        plan_path = self.spec_folder / "plan.md"
        plan_path.write_text(plan_content, encoding="utf-8")
        logger.info(f"  Wrote plan.md (projection of {len(by_library)} libraries)")

        # STAMP STRIPPING FINALIZATION CHECK
        stamp_check_failed = False
        stamp_pattern = re.compile(r"@(from|modified|line):[^\s]+")

        for lib_path in libraries_dir.glob("*.md"):
            lib_content = lib_path.read_text(encoding="utf-8")
            if stamp_pattern.search(lib_content):
                logger.error(f"  STAMP STRIPPING FAILED: {lib_path.name} contains stamps")
                stamp_check_failed = True

        if stamp_pattern.search(plan_path.read_text(encoding="utf-8")):
            logger.error("  STAMP STRIPPING FAILED: plan.md contains stamps")
            stamp_check_failed = True

        if not stamp_check_failed:
            logger.info("  Stamp stripping verified: no stamps in output artifacts")

        # Write quarantined units to separate file
        if quarantined:
            quarantine_path = self.spec_folder / "quarantine.md"
            quarantine_content = self._format_quarantine_file(quarantined)
            quarantine_path.write_text(quarantine_content, encoding="utf-8")
            logger.info(f"  Wrote {len(quarantined)} quarantined units to quarantine.md")

        # Final coverage report
        report = self.tracker.get_coverage_report()
        logger.info(f"  Coverage: {report['coverage_percent']:.1f}%")
        logger.info(
            f"  Mapped: {report['mapped']}, Dropped: {report['dropped']}, "
            f"Unaccounted: {report['unaccounted']}"
        )

    def _strip_provenance_stamps(self, content: str) -> str:
        """Strip provenance stamps from content.

        Removes @from:p#, @modified:p#, @line:# from output.
        Stamps are preserved in .workspace/ for debugging.
        """
        # Pattern: <!-- @from:p1 @modified:p5,p7 @line:234 -->
        content = re.sub(r"\s*<!--\s*@(from|modified|line):[^>]+-->", "", content)

        # Pattern: @from:p1 (inline)
        content = re.sub(r"\s*@(from|modified|line):[^\s]+", "", content)

        return content

    def _generate_plan_from_libraries(self, by_library: dict[str, list[TrackedUnit]]) -> str:
        """Generate plan.md as a deterministic projection from authoritative library state.

        This is NOT a separate source of truth - it's computed from libraries.
        """
        lines = ["# Plan\n"]
        lines.append(
            f"<!-- Generated from authoritative library state: {datetime.now().isoformat()} -->\n"
        )
        lines.append("<!-- DO NOT EDIT DIRECTLY - Edit libraries/*.md instead -->\n\n")

        # Table of contents
        lines.append("## Table of Contents\n")
        for lib_name in sorted(by_library.keys()):
            lib_units = by_library[lib_name]
            lines.append(
                f"- [{lib_name}](#{lib_name.replace(' ', '-').lower()}) "
                f"({len(lib_units)} elements)\n"
            )
        lines.append("\n---\n\n")

        # Each library section
        for lib_name in sorted(by_library.keys()):
            units = by_library[lib_name]
            lines.append(f"## {lib_name}\n\n")

            # Sort units by type then by ID
            def unit_sort_key(u: TrackedUnit) -> tuple[int, str]:
                type_order = {
                    "algorithm": 0,
                    "claim": 1,
                    "invariant": 2,
                    "goal": 3,
                    "data_structure": 4,
                }
                unit_type = (
                    str(getattr(u, "unit_type", "unknown")).lower()
                    if not hasattr(u.unit_type, "value")
                    else u.unit_type.value.lower()
                )
                return (type_order.get(unit_type, 99), u.id)

            for unit in sorted(units, key=unit_sort_key):
                # Header with declaration and pinning back to library
                lines.append(
                    f"### {unit.id} ([={unit.id}]) <!-- @pin:libraries/{lib_name}.md -->\n\n"
                )

                # Content
                lines.append(f"{unit.content}\n\n")

                # Relations (if any)
                if hasattr(unit, "relation_libraries") and unit.relation_libraries:
                    rels = ", ".join(f"(@[+rel:{r}])" for r in unit.relation_libraries)
                    lines.append(f"Relations: {rels}\n\n")

                lines.append("---\n\n")

        return "\n".join(lines)

    def _compute_prose_ratio(self, units: list[TrackedUnit]) -> float:
        """Compute the prose ratio for the current unit set.

        prose_ratio = (prose bytes/lines/units) / (total bytes/lines/units)

        This metric is used in:
        - Evolution triggers: "Prose ratio not decreasing"
        - Termination conditions: "Prose minimized enough"
        - Acceptance gates: "Prose below threshold"

        Returns a value between 0.0 (no prose) and 1.0 (all prose).
        """
        if not units:
            return 0.0

        # Count by unit type
        prose_count = 0
        total_count = len(units)
        prose_bytes = 0
        total_bytes = 0

        for unit in units:
            unit_type = (
                unit.unit_type.value.lower()
                if hasattr(unit.unit_type, "value")
                else str(unit.unit_type).lower()
            )
            content = getattr(unit, "content", "")
            content_len = len(content.encode("utf-8"))

            total_bytes += content_len

            if unit_type in ("prose", "unknown", "paragraph", "text"):
                prose_count += 1
                prose_bytes += content_len

        # Return byte-weighted ratio (more accurate than unit count)
        if total_bytes > 0:
            return prose_bytes / total_bytes
        elif total_count > 0:
            return prose_count / total_count
        else:
            return 0.0

    def _is_fully_superseded(self, lib_name: str, lib_units: list[TrackedUnit]) -> bool:
        """Check if a library has been fully superseded by later patches.

        A library is fully superseded if:
        - All its element IDs appear in later patches with the same or updated content
        - No element from this library is the sole source of an ID

        Returns True if safe to auto-archive, False if manual review needed.
        """
        lib_ids = {getattr(u, "id", "") for u in lib_units}

        # Find all units from later patches
        later_units = []
        for unit in self.state.units:
            if getattr(unit, "primary_library", None) != lib_name:
                p = getattr(unit, "introduced_by", "")
                if p.startswith("p"):
                    try:
                        patch_num = int(p[1:])
                        max_lib_patch = 0
                        for u in lib_units:
                            p2 = getattr(u, "introduced_by", "p0")
                            if p2.startswith("p"):
                                with suppress(ValueError):
                                    max_lib_patch = max(max_lib_patch, int(p2[1:]))
                        if patch_num > max_lib_patch:
                            later_units.append(unit)
                    except ValueError:
                        pass

        # Check if all library IDs appear in later units
        later_ids = {getattr(u, "id", "") for u in later_units}
        superseded_ids = lib_ids & later_ids

        # Only fully superseded if all IDs are covered
        return superseded_ids == lib_ids and len(lib_ids) > 0

    def _format_quarantine_file(self, units: list[TrackedUnit]) -> str:
        """Format quarantine.md for non-authoritative units."""
        lines = ["# Quarantined Elements\n"]
        lines.append("These elements have broken proof chains and are NON-AUTHORITATIVE.\n")
        lines.append("They are excluded from libraries/*.md and plan.md until resolved.\n\n")
        lines.append("## Unresolved Elements\n\n")

        for unit in units:
            lines.append(f"### {unit.id}\n")
            lines.append("- **Status**: NON_AUTHORITATIVE\n")
            lines.append("- **Issue**: Broken proof chain (no claim reference)\n")
            lines.append(f"- **Source**: {getattr(unit, 'source', 'unknown')}\n")
            lines.append(f"- **Introduced by**: {getattr(unit, 'introduced_by', 'unknown')}\n\n")
            content = getattr(unit, "content", "")
            lines.append(f"```\n{content[:500]}...\n```\n\n")

        return "\n".join(lines)

    def _format_library_with_relations(self, name: str, units: list[TrackedUnit]) -> str:
        """Format units as a library file WITH relation annotations preserved.

        Per-element: (@[+rel:library_name])
        Library-level: cross-links index at end
        """
        lines = [f"# {name.replace('_', ' ').title()}\n"]

        cross_links: set[str] = set()

        for unit in sorted(units, key=lambda u: u.id):
            # Get relation libraries from labels
            labels = self.state.final_labels.get(unit.id)
            relation_libs = labels.relations if labels else []

            # Add relation annotation if present
            if relation_libs:
                rel_annotations = " ".join(f"(@[+rel:{r}])" for r in relation_libs)
                lines.append(f"{unit.content}\n{rel_annotations}")
                cross_links.update(relation_libs)
            else:
                lines.append(unit.content)

            lines.append("\n---\n")

        # Add cross-links index at end
        if cross_links:
            lines.append("\n## Cross-References\n")
            lines.append("This library has elements related to:\n")
            for lib in sorted(cross_links):
                lines.append(f"- [{lib}](libraries/{lib}.md)")
            lines.append("")

        return "\n".join(lines)
