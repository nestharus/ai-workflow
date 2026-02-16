"""Render analysis artifacts as Markdown reports."""

from __future__ import annotations

from spec_manager.schemas.lineage import (
    AnalysisFileSchema,
    AtomAnalysisEntry,
)


def render_analysis_markdown(analysis: AnalysisFileSchema) -> str:
    """Render a complete analysis artifact as Markdown.

    Output structure:
    # Analysis Report
    - run_id, generated_at

    ## Summary
    | Metric | Value |

    ## Per-Atom Analysis
    ### atom_name (atom_file)
    **Forward Traces:**
    | Architectural Location | Projection Type | Confidence |
    **Relationships:**
    - Calls: [pin_a -> pin_b]
    - Events: [pin_a -(evt)-> pin_b]
    - Stores: [pin_a -(read)-> store_x]
    **Data Flow:**
    - Signals in: [param_a, param_b]
    - Signals out: [return_type]
    - Stores touched: [store_x]

    ## Unimplemented Atoms
    | Atom | File | Reason |

    ## Orphaned Architecture
    | Location | Description | Suggested Action |

    Args:
        analysis: Complete analysis artifact.

    Returns:
        Markdown string.
    """
    lines: list[str] = []

    # Header
    lines.append("# Analysis Report")
    lines.append("")
    lines.append(f"- run_id: {analysis.run_id}")
    lines.append(f"- generated_at: {analysis.generated_at}")
    lines.append("")

    # Summary table
    lines.append("## Summary")
    lines.append("")
    lines.append(render_summary_table(analysis))
    lines.append("")

    # Per-Atom Analysis
    lines.append("## Per-Atom Analysis")
    lines.append("")

    implemented_atoms = [a for a in analysis.atoms if not a.is_unimplemented]
    if not implemented_atoms:
        lines.append("No implemented atoms found.")
        lines.append("")
    else:
        for atom in implemented_atoms:
            lines.extend(_render_atom_section(atom))
            lines.append("")

    # Unimplemented Atoms
    lines.append("## Unimplemented Atoms")
    lines.append("")
    unimplemented = [a for a in analysis.atoms if a.is_unimplemented]
    if not unimplemented:
        lines.append("No unimplemented atoms.")
    else:
        lines.append("| Atom | File | Reason |")
        lines.append("| --- | --- | --- |")
        for atom in unimplemented:
            lines.append(f"| {atom.atom_id} | {atom.atom_file} | No architectural imports found |")
    lines.append("")

    # Orphaned Architecture
    lines.append("## Orphaned Architecture")
    lines.append("")
    if not analysis.orphaned_architecture:
        lines.append("No orphaned architecture detected.")
    else:
        lines.append("| Location | Description | Suggested Action |")
        lines.append("| --- | --- | --- |")
        for orphan in analysis.orphaned_architecture:
            lines.append(
                f"| {orphan.location} | {orphan.description} | {orphan.suggested_action} |"
            )
    lines.append("")

    return "\n".join(lines)


def _render_atom_section(atom: AtomAnalysisEntry) -> list[str]:
    """Render a single atom's analysis section."""
    lines: list[str] = []
    lines.append(f"### {atom.atom_id} ({atom.atom_file})")
    lines.append("")

    # Forward traces
    lines.append("**Forward Traces:**")
    lines.append("")
    if atom.forward_traces:
        lines.append("| Architectural Location | Projection Type | Confidence |")
        lines.append("| --- | --- | --- |")
        for trace in atom.forward_traces:
            xform = (
                trace.transformation.value
                if hasattr(trace.transformation, "value")
                else str(trace.transformation)
            )
            lines.append(f"| {trace.to_location} | {xform} | {trace.confidence:.2f} |")
    else:
        lines.append("No forward traces.")
    lines.append("")

    # Relationship facts
    lines.append("**Relationships:**")
    lines.append("")
    if atom.relationship_facts:
        call_entries = [
            f"{fact.caller_pin} -> {fact.callee_pin}" for fact in atom.relationship_facts.calls
        ]
        reference_entries = [
            f"{fact.referrer_pin} -> {fact.referenced_id}"
            for fact in atom.relationship_facts.references
        ]
        event_entries = [
            (
                f"{fact.emitter_pin} -({fact.event_id})-> {fact.consumer_pin}"
                if fact.consumer_pin
                else f"{fact.emitter_pin} -({fact.event_id})-> ?"
            )
            for fact in atom.relationship_facts.events
        ]
        store_entries = [
            f"{fact.pin} -({fact.access_type})-> {fact.store_id}"
            for fact in atom.relationship_facts.stores
        ]
        calls = ", ".join(call_entries) if call_entries else "none"
        references = ", ".join(reference_entries) if reference_entries else "none"
        events = ", ".join(event_entries) if event_entries else "none"
        stores = ", ".join(store_entries) if store_entries else "none"
        lines.append(f"- Calls: [{calls}]")
        lines.append(f"- References: [{references}]")
        lines.append(f"- Events: [{events}]")
        lines.append(f"- Stores: [{stores}]")
    else:
        lines.append("- No relationship facts.")
    lines.append("")

    # Data flow
    lines.append("**Data Flow:**")
    lines.append("")
    if atom.data_flow:
        sig_in = ", ".join(atom.data_flow.signals_in) if atom.data_flow.signals_in else "none"
        sig_out = ", ".join(atom.data_flow.signals_out) if atom.data_flow.signals_out else "none"
        stores = (
            ", ".join(atom.data_flow.stores_touched) if atom.data_flow.stores_touched else "none"
        )
        lines.append(f"- Signals in: [{sig_in}]")
        lines.append(f"- Signals out: [{sig_out}]")
        lines.append(f"- Stores touched: [{stores}]")
    else:
        lines.append("- No data flow data.")

    return lines


def render_summary_table(analysis: AnalysisFileSchema) -> str:
    """Render just the summary statistics table.

    Useful for embedding in other reports (e.g., run audit).

    Args:
        analysis: Analysis artifact.

    Returns:
        Markdown table string.
    """
    summary = analysis.summary

    rows: list[tuple[str, str]] = [
        ("Total atoms", str(summary.get("total_atoms", 0))),
        ("Implemented atoms", str(summary.get("implemented_atoms", 0))),
        ("Unimplemented atoms", str(summary.get("unimplemented_atoms", 0))),
        ("Orphaned architecture", str(summary.get("orphaned_architecture", 0))),
        ("Pass-through imports", str(summary.get("pass_through_imports", 0))),
        ("Wrap imports", str(summary.get("wrap_imports", 0))),
        ("Smear imports", str(summary.get("smear_imports", 0))),
        ("Total lineage edges", str(summary.get("total_lineage_edges", 0))),
    ]

    lines: list[str] = []
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    for metric, value in rows:
        lines.append(f"| {metric} | {value} |")

    return "\n".join(lines)
