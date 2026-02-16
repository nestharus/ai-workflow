"""CLI commands for entity coverage gap analysis.

Provides the ``coverage`` subcommand group with the ``entity-gaps``
subcommand for on-demand entity-to-atom coverage analysis.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def setup_coverage_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'coverage' subcommand group in the CLI parser.

    Args:
        subparsers: The parent subparsers action to register into.
    """
    p_coverage = subparsers.add_parser("coverage", help="Coverage analysis commands")
    coverage_sub = p_coverage.add_subparsers(dest="coverage_command", required=True)

    p_entity_gaps = coverage_sub.add_parser(
        "entity-gaps", help="Analyze entity-to-atom coverage gaps"
    )
    p_entity_gaps.add_argument("run_id", help="Run identifier")
    p_entity_gaps.add_argument(
        "--input-folder",
        default=".",
        help="Input folder path (default: .)",
    )
    p_entity_gaps.add_argument(
        "--threshold",
        type=float,
        default=0.0,
        help="Minimum entity coverage ratio to pass (default: 0.0)",
    )
    p_entity_gaps.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format (default: text)",
    )
    p_entity_gaps.add_argument(
        "--output",
        help="Write output to file instead of stdout",
    )


def handle_coverage_command(args: argparse.Namespace) -> int:
    """Dispatch coverage subcommands.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 for success, non-zero for error).
    """
    handlers = {
        "entity-gaps": cmd_entity_gaps,
    }

    handler = handlers.get(args.coverage_command)
    if handler is None:
        print(f"Unknown coverage command: {args.coverage_command}", file=sys.stderr)
        return 1

    return handler(args)


def cmd_entity_gaps(args: argparse.Namespace) -> int:
    """Run entity coverage gap analysis.

    Loads the evidence index and atom registry, optionally loads the
    entities artifact, runs analysis, and prints the coverage report.

    Args:
        args: Parsed command-line arguments with run_id, input-folder,
            threshold, format, and output options.

    Returns:
        0 if coverage >= threshold, 1 otherwise.
    """
    from spec_manager.branches.atoms import AtomRegistry
    from spec_manager.branches.layout import BranchLayout
    from spec_manager.compliance.coverage.analyzer import EntityCoverageAnalyzer
    from spec_manager.core.evidence_index import EvidenceIndex
    from spec_manager.core.project_root import resolve_from_root
    from spec_manager.core.run_folder import RunFolderStructure
    from spec_manager.schemas.entities import EntitiesArtifact

    input_root = Path(args.input_folder)
    if not input_root.is_absolute():
        input_root = resolve_from_root(args.input_folder)

    structure = RunFolderStructure(
        run_id=args.run_id,
        root=input_root / "runs" / args.run_id,
    )

    # Load evidence index
    index_path = structure.evidence_index_path
    if not index_path.exists():
        print(f"Evidence index not found: {index_path}", file=sys.stderr)
        print("Run 'evidence-store rebuild-index' first.", file=sys.stderr)
        return 1

    evidence_index = EvidenceIndex.load(index_path)

    # Load atom registry
    layout = BranchLayout(run_root=structure.root)
    atom_registry = AtomRegistry.load(layout)

    # Optionally load entities artifact
    entities_artifact: EntitiesArtifact | None = None
    entities_dir = structure.libraries_dir
    loaded_artifacts: list[EntitiesArtifact] = []
    if entities_dir.exists():
        for lib_dir in sorted(entities_dir.iterdir()):
            if not lib_dir.is_dir():
                continue
            entities_path = lib_dir / "entities.json"
            if entities_path.exists():
                try:
                    data = json.loads(entities_path.read_text(encoding="utf-8"))
                    loaded_artifacts.append(EntitiesArtifact.model_validate(data))
                except Exception as exc:
                    print(
                        f"Failed to load entities artifact '{entities_path}': {exc}",
                        file=sys.stderr,
                    )
                    return 1
    if loaded_artifacts:
        entities = []
        mentions = []
        tags = []
        for artifact in loaded_artifacts:
            entities.extend(artifact.entities)
            mentions.extend(artifact.mentions)
            tags.extend(artifact.tags)
        entities_artifact = EntitiesArtifact(
            schema_version=loaded_artifacts[0].schema_version,
            entities=entities,
            mentions=mentions,
            tags=tags,
            extraction_method="merged",
            source_file=None,
        )

    # Run analysis
    analyzer = EntityCoverageAnalyzer(evidence_index, atom_registry, entities_artifact)
    report = analyzer.analyze()

    # Format output
    if args.format == "json":
        output_text = json.dumps(report.to_dict(), indent=2)
    else:
        lines = [
            "Entity Coverage Report",
            "=" * 40,
            f"Total entities: {report.total_entities}",
            f"Total atoms:    {report.total_atoms}",
            f"Matched:        {len(report.matched)}",
            f"Entity coverage: {report.entity_coverage:.1%}",
            f"Atom coverage:   {report.atom_coverage:.1%}",
        ]

        if report.matched:
            lines.append("")
            lines.append("Matched Pairs:")
            for m in report.matched:
                lines.append(
                    f"  {m.entity_id} ({m.entity_name}) <-> "
                    f"{m.atom_id} ({m.atom_function_name}) "
                    f"[{m.match_method}, confidence={m.confidence:.1f}]"
                )

        if report.unmatched_entities:
            lines.append("")
            lines.append("Unmatched Entities:")
            for ue in report.unmatched_entities:
                lib_info = f" (libs: {', '.join(ue.lib_ids)})" if ue.lib_ids else ""
                lines.append(f"  {ue.entity_id} - {ue.name} [{ue.kind}]{lib_info}")

        if report.unmatched_atoms:
            lines.append("")
            lines.append("Unmatched Atoms:")
            for ua in report.unmatched_atoms:
                slice_info = f" (slice: {ua.vertical_slice})" if ua.vertical_slice else ""
                lines.append(f"  {ua.atom_id} - {ua.function_name} [{ua.kind}]{slice_info}")

        if report.diagnostics:
            lines.append("")
            lines.append("Diagnostics:")
            for diagnostic in report.diagnostics:
                message = diagnostic.get("message")
                if isinstance(message, str) and message:
                    lines.append(f"  - {message}")
                else:
                    lines.append(f"  - {diagnostic}")

        output_text = "\n".join(lines)

    # Write or print output
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_text, encoding="utf-8")
        print(f"Report written to: {output_path}")
    else:
        print(output_text)

    # Return code based on threshold
    if report.entity_coverage >= args.threshold:
        return 0
    return 1


__all__ = [
    "handle_coverage_command",
    "setup_coverage_parser",
]
