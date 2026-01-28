"""CLI for spec decomposition operations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts.spec_decomposition.entity_index import (
    add_entity_to_index,
    add_keywords_to_entity,
    add_source_to_entity,
    check_rediscovery,
    load_entity_index,
    save_entity_index,
)
from scripts.spec_decomposition.execution import execute_spec
from scripts.spec_decomposition.extract import (
    append_evidence_to_entity,
    create_discovered_entity_document,
    create_rich_relation_document,
    extract_context_to_document,
    extract_entity_to_document,
    extract_relation_to_document,
)
from scripts.spec_decomposition.finalize import finalize_output
from scripts.spec_decomposition.graph import build_dependency_graph, save_dependency_graph
from scripts.spec_decomposition.id_generator import IDType, generate_id, load_id_map, save_id_map
from scripts.spec_decomposition.recompose import recompose
from scripts.spec_decomposition.staging import (
    collect_and_remove_snippets,
    get_remaining_lines,
    get_staged_from_path,
    is_file_empty,
    mark_relation_snippet,
    remove_lines,
    write_snippet_staging_file,
)
from scripts.spec_decomposition.tagging import tag_facts
from scripts.spec_decomposition.workspace import (
    init_workspace,
    list_discovery_staging_files,
    load_state,
    resolve_discovery_staging,
    save_state,
)


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize workspace for spec decomposition."""
    spec_path = Path(args.spec_path)
    workspace = Path(args.workspace) if args.workspace else Path(".tmp/spec-decomposition")

    if not spec_path.exists():
        print(f"Error: Spec path does not exist: {spec_path}", file=sys.stderr)
        return 1

    init_workspace(workspace, spec_path)
    print(f"Workspace initialized: {workspace}")
    print(f"Spec staged: {workspace}/staging/discovery/")
    return 0


def cmd_extract_entity(args: argparse.Namespace) -> int:
    """Extract entity from spec."""
    workspace = Path(args.workspace)
    entity_name = args.entity
    evidence = json.loads(args.evidence)
    keywords = json.loads(args.keywords) if args.keywords else []
    append_mode = args.append
    explicit_entity_id = getattr(args, "entity_id", None)
    staging_file_arg = args.file

    # Load current state and ID map
    state = load_state(workspace)
    id_map = load_id_map(workspace)

    # Decide whether we're creating a new entity ID or appending to an existing one.
    if explicit_entity_id:
        entity_id = explicit_entity_id
    elif append_mode and state.get("current_entity"):
        entity_id = state["current_entity"]
    else:
        entity_id = generate_id(IDType.ENTITY, id_map)

        # Add to entity index (one-time)
        source_ref = (
            f"{evidence[0].get('file', 'unknown')}:{evidence[0].get('line', 0)}"
            if evidence
            else "unknown:0"
        )
        add_entity_to_index(workspace, entity_id, entity_name, keywords, source_ref)

    # Deduplicate evidence per-entity (by file+line) to avoid repeated appends.
    existing_sources = id_map.get(entity_id, [])
    existing_keys = {
        (src.get("file", ""), int(src.get("line", 0)))
        for src in existing_sources
        if "file" in src and "line" in src
    }

    filtered_evidence = []
    for ev in evidence:
        file_key = ev.get("file", "")
        line_key = int(ev.get("line", 0))
        if file_key and line_key and (file_key, line_key) in existing_keys:
            continue
        filtered_evidence.append(ev)
        if file_key and line_key:
            existing_keys.add((file_key, line_key))

    # Write/update entity document.
    entity_doc_path = workspace / "entities" / f"{entity_id}.md"
    if entity_doc_path.exists():
        # Append evidence (do not overwrite existing content).
        for ev in filtered_evidence:
            append_evidence_to_entity(workspace, entity_id, ev)
        entity_file = entity_doc_path
        # Update index sources/keywords for the existing entity.
        for ev in filtered_evidence:
            if ev.get("file") and ev.get("line"):
                add_source_to_entity(workspace, entity_id, f"{ev['file']}:{ev['line']}")
        if keywords:
            add_keywords_to_entity(workspace, entity_id, keywords)
    else:
        # Create a new entity document.
        entity_file = extract_entity_to_document(
            workspace=workspace,
            entity_id=entity_id,
            entity_name=entity_name,
            evidence=filtered_evidence,
        )

    # Remove lines from discovery staging (redaction). Prefer file-based removal.
    if staging_file_arg:
        staging_file = Path(staging_file_arg)
        if not staging_file.is_absolute():
            candidate = workspace / "staging" / "discovery" / staging_file_arg
            if candidate.exists():
                staging_file = candidate

        if staging_file.exists():
            line_numbers = [int(ev.get("line", 0)) for ev in filtered_evidence if ev.get("line")]
            if line_numbers:
                remove_lines(staging_file, line_numbers, note=entity_id)
    else:
        # Group evidence by source file.
        by_file: dict[str, list[int]] = {}
        for ev in filtered_evidence:
            if not ev.get("file") or not ev.get("line"):
                continue
            by_file.setdefault(ev["file"], []).append(int(ev["line"]))

        for src_file, lines_for_file in by_file.items():
            staging_path = resolve_discovery_staging(workspace, src_file)
            if staging_path and staging_path.exists():
                remove_lines(staging_path, sorted(set(lines_for_file)), note=entity_id)

    # Update ID map (only for newly-added evidence).
    for ev in filtered_evidence:
        id_map.setdefault(entity_id, []).append(
            {
                "file": ev.get("file", ""),
                "line": int(ev.get("line", 0)),
                "type": "entity",
            }
        )

    # Update state
    if entity_id not in state.get("extracted_entities", []):
        state.setdefault("extracted_entities", []).append(entity_id)
    state["current_entity"] = entity_id

    # Save
    save_id_map(workspace, id_map)
    save_state(workspace, state)

    print(
        json.dumps(
            {
                "entity_id": entity_id,
                "entity_name": entity_name,
                "entity_file": str(entity_file),
                "evidence_count": len(filtered_evidence),
                "keywords": keywords,
            }
        )
    )
    return 0


def cmd_check_rediscovery(args: argparse.Namespace) -> int:
    """Check if entity matches existing by keywords."""
    workspace = Path(args.workspace)
    entity_name = args.entity_name
    keywords = json.loads(args.keywords)

    result = check_rediscovery(workspace, entity_name, keywords)
    print(json.dumps(result))
    return 0


def cmd_check_file_empty(args: argparse.Namespace) -> int:
    """Check if staging file has been fully extracted."""
    workspace = Path(args.workspace)
    staging_file = Path(args.file)

    empty = is_file_empty(staging_file)
    remaining = get_remaining_lines(staging_file) if not empty else []

    print(
        json.dumps(
            {
                "empty": empty,
                "remaining_lines": len(remaining),
                "sample": remaining[:5] if remaining else [],
            }
        )
    )
    return 0


def cmd_build_graph(args: argparse.Namespace) -> int:
    """Build dependency graph from relations."""
    workspace = Path(args.workspace)

    graph = build_dependency_graph(workspace)
    save_dependency_graph(workspace, graph)

    print(
        json.dumps(
            {
                "nodes": graph["statistics"]["node_count"],
                "edges": graph["statistics"]["edge_count"],
                "output": str(workspace / "output" / "dependency_graph.json"),
            }
        )
    )
    return 0


def cmd_extract_orphan(args: argparse.Namespace) -> int:
    """Extract orphan statement."""
    workspace = Path(args.workspace)
    analysis = args.analysis
    possible_entities = json.loads(args.possible_entities) if args.possible_entities else []
    evidence = json.loads(args.evidence)

    # Load state and ID map
    state = load_state(workspace)
    id_map = load_id_map(workspace)

    # Generate orphan ID
    orphan_id = generate_id(IDType.ORPHAN, id_map)

    # Create orphan document
    orphan_file = workspace / "orphans" / f"{orphan_id}.md"
    (workspace / "orphans").mkdir(exist_ok=True)

    ev = evidence.get("evidence", evidence)
    lines = [
        "# Orphan Statement",
        "",
        f"**ID**: `{orphan_id}`",
        f"**Category**: `{analysis}`",
        f"**Possible Entities**: {', '.join(possible_entities) if possible_entities else 'None'}",
        "",
        "## Evidence",
        "",
        f"- **File**: `{ev.get('file', 'unknown')}`",
        f"- **Line**: {ev.get('line', 0)}",
        "",
        f"> {ev.get('text', '')}",
        "",
    ]
    orphan_file.write_text("\n".join(lines))

    # Update ID map
    id_map[orphan_id] = [
        {
            "file": ev.get("file", ""),
            "line": ev.get("line", 0),
            "type": "orphan",
            "category": analysis,
            "possible_entities": possible_entities,
        }
    ]

    # Update state
    state["orphans_found"] = state.get("orphans_found", 0) + 1

    # Save
    save_id_map(workspace, id_map)
    save_state(workspace, state)

    print(
        json.dumps(
            {
                "orphan_id": orphan_id,
                "category": analysis,
                "orphan_file": str(orphan_file),
            }
        )
    )
    return 0


def cmd_mark_relation_snippets(args: argparse.Namespace) -> int:
    """Mark lines as relation snippets (don't remove yet)."""
    workspace = Path(args.workspace)
    source_entity = args.source_entity
    snippets = json.loads(args.snippets)
    staging_file = Path(args.file) if args.file else None

    # Load state and ID map
    state = load_state(workspace)
    id_map = load_id_map(workspace)

    marked: list[dict] = []
    for snippet in snippets:
        # Generate snippet ID
        snippet_id = generate_id(IDType.SNIPPET, id_map)

        # Determine discovery staging file.
        # Preference order:
        # 1) snippet['file'] (original path) -> resolve via workspace file_map
        # 2) --file argument (path or discovery staging filename)
        target_file: Path | None = None

        if snippet.get("file"):
            target_file = resolve_discovery_staging(workspace, snippet["file"])

        if target_file is None and staging_file:
            candidate = staging_file
            if not candidate.is_absolute():
                # If just a filename, interpret it relative to discovery staging.
                discovery_candidate = workspace / "staging" / "discovery" / str(candidate)
                candidate = discovery_candidate if discovery_candidate.exists() else candidate
            target_file = candidate

        if target_file and target_file.exists():
            mark_relation_snippet(target_file, int(snippet["line"]), snippet_id, source_entity)

            original_source = (
                snippet.get("file") or get_staged_from_path(target_file) or str(target_file)
            )

            # Update ID map
            id_map[snippet_id] = [
                {
                    "file": original_source,
                    "line": int(snippet["line"]),
                    "type": "snippet",
                    "source_entity": source_entity,
                    "text": snippet.get("text", ""),
                    "references": snippet.get("references", []),
                }
            ]

            marked.append(
                {
                    "snippet_id": snippet_id,
                    "line": int(snippet["line"]),
                }
            )

    # Update state
    state["snippets_marked"] = state.get("snippets_marked", 0) + len(marked)

    # Save
    save_id_map(workspace, id_map)
    save_state(workspace, state)

    print(
        json.dumps(
            {
                "source_entity": source_entity,
                "snippets_marked": len(marked),
                "marked": marked,
            }
        )
    )
    return 0


def cmd_collect_relation_snippets(args: argparse.Namespace) -> int:
    """Collect all marked snippets and move to relation staging."""
    workspace = Path(args.workspace)

    # Load state and entity index
    state = load_state(workspace)
    entity_index = load_entity_index(workspace)

    total_collected = 0
    snippet_files = []

    # Process each discovery staging file
    for staging_file in list_discovery_staging_files(workspace):
        snippets = collect_and_remove_snippets(staging_file)

        if not snippets:
            continue

        # Group by source entity
        by_entity: dict[str, list[dict]] = {}
        for snippet in snippets:
            entity_id = snippet["source_entity"]
            if entity_id not in by_entity:
                by_entity[entity_id] = []
            by_entity[entity_id].append(snippet)

        # Write snippet staging files
        for entity_id, entity_snippets in by_entity.items():
            entity_name = entity_index.get(entity_id, {}).get("name", entity_id)
            original_source = get_staged_from_path(staging_file) or staging_file.name
            snippet_file = write_snippet_staging_file(
                workspace,
                entity_id,
                entity_name,
                entity_snippets,
                original_source,
            )
            snippet_files.append(str(snippet_file))
            total_collected += len(entity_snippets)

    # Update state
    state["phase"] = "snippet_decomposition"

    save_state(workspace, state)

    print(
        json.dumps(
            {
                "snippets_collected": total_collected,
                "snippet_files": snippet_files,
            }
        )
    )
    return 0


def cmd_create_discovered_entity(args: argparse.Namespace) -> int:
    """Create entity discovered from relation snippet."""
    workspace = Path(args.workspace)
    entity_name = args.entity
    keywords = json.loads(args.keywords)
    discovered_from = args.discovered_from
    context_text = args.context

    # Load state and ID map
    state = load_state(workspace)
    id_map = load_id_map(workspace)

    # Generate entity ID
    entity_id = generate_id(IDType.ENTITY, id_map)

    # Create entity document
    entity_file = create_discovered_entity_document(
        workspace=workspace,
        entity_id=entity_id,
        entity_name=entity_name,
        keywords=keywords,
        discovered_from_snippet=discovered_from,
        context_text=context_text,
    )

    # Add to entity index with discovered_from marker
    index = load_entity_index(workspace)
    index[entity_id] = {
        "name": entity_name,
        "keywords": [kw.lower() for kw in keywords] + [entity_name.lower()],
        "aliases": [],
        "sources": [],
        "discovered_from": discovered_from,
    }
    save_entity_index(workspace, index)

    # Update ID map
    id_map[entity_id] = [
        {
            "type": "entity",
            "discovered_from": discovered_from,
        }
    ]

    # Update state
    state.setdefault("extracted_entities", []).append(entity_id)
    state["entities_from_snippets"] = state.get("entities_from_snippets", 0) + 1

    # Save
    save_id_map(workspace, id_map)
    save_state(workspace, state)

    print(
        json.dumps(
            {
                "entity_id": entity_id,
                "entity_name": entity_name,
                "discovered_from": discovered_from,
                "entity_file": str(entity_file),
            }
        )
    )
    return 0


def cmd_create_rich_relation(args: argparse.Namespace) -> int:
    """Create rich relation document with full context."""
    workspace = Path(args.workspace)
    source_entity = args.source
    targets = json.loads(args.targets)
    relationship_type = args.type
    relationship_context = args.context
    snippet_id = args.snippet_id
    original_text = args.original_text
    file = args.file
    line = int(args.line)

    # Load state and ID map
    state = load_state(workspace)
    id_map = load_id_map(workspace)
    entity_index = load_entity_index(workspace)

    # Generate relation ID
    relation_id = generate_id(IDType.RELATION, id_map)

    # Get source entity name (fallback to CLI-provided name if index is missing).
    source_name = (
        entity_index.get(source_entity, {}).get("name")
        or getattr(args, "source_name", None)
        or source_entity
    )

    # Build targets list with names
    target_list = []
    for target in targets:
        target_name = entity_index.get(target["id"], {}).get(
            "name", target.get("name", target["id"])
        )
        target_list.append(
            {
                "id": target["id"],
                "name": target_name,
                "discovered_from_snippet": target.get("discovered_from_snippet", False),
            }
        )

    # Create rich relation document
    relation_file = create_rich_relation_document(
        workspace=workspace,
        relation_id=relation_id,
        snippet_id=snippet_id,
        source_entity=source_entity,
        source_entity_name=source_name,
        targets=target_list,
        relationship_type=relationship_type,
        relationship_context=relationship_context,
        original_text=original_text,
        file=file,
        line=line,
    )

    # Update ID map
    id_map[relation_id] = [
        {
            "file": file,
            "line": line,
            "type": "relation",
            "source": source_entity,
            "targets": [t["id"] for t in target_list],
            "relation_type": relationship_type,
            "context": relationship_context,
            "snippet_id": snippet_id,
        }
    ]

    # Update state
    state.setdefault("extracted_relations", []).append(relation_id)
    state["snippets_decomposed"] = state.get("snippets_decomposed", 0) + 1

    # Save
    save_id_map(workspace, id_map)
    save_state(workspace, state)

    print(
        json.dumps(
            {
                "relation_id": relation_id,
                "source": source_entity,
                "targets": [t["id"] for t in target_list],
                "type": relationship_type,
                "relation_file": str(relation_file),
            }
        )
    )
    return 0


def cmd_extract_relation(args: argparse.Namespace) -> int:
    """Extract relation between entities."""
    workspace = Path(args.workspace)
    from_id = args.from_entity
    to_id = args.to_entity
    relation_type = args.type
    evidence = json.loads(args.evidence)

    # Load current state and ID map
    state = load_state(workspace)
    id_map = load_id_map(workspace)

    # Generate relation ID
    relation_id = generate_id(IDType.RELATION, id_map)

    # Extract to document
    relation_file = extract_relation_to_document(
        workspace=workspace,
        relation_id=relation_id,
        from_entity=from_id,
        to_entity=to_id,
        relation_type=relation_type,
        evidence=evidence,
    )

    # Redact line from discovery staging file
    staging_file = resolve_discovery_staging(workspace, evidence.get("file", ""))
    if staging_file and staging_file.exists():
        remove_lines(staging_file, [int(evidence["line"])], note=relation_id)

    # Update ID map
    id_map[relation_id] = [
        {
            "file": evidence["file"],
            "line": evidence["line"],
            "type": "relation",
            "from": from_id,
            "to": to_id,
            "relation_type": relation_type,
        }
    ]

    # Update state
    if relation_id not in state.get("extracted_relations", []):
        state.setdefault("extracted_relations", []).append(relation_id)

    # Save
    save_id_map(workspace, id_map)
    save_state(workspace, state)

    print(
        json.dumps(
            {
                "relation_id": relation_id,
                "from": from_id,
                "to": to_id,
                "type": relation_type,
                "relation_file": str(relation_file),
            }
        )
    )
    return 0


def cmd_extract_context(args: argparse.Namespace) -> int:
    """Extract context for an entity."""
    workspace = Path(args.workspace)
    entity_id = args.entity
    evidence = json.loads(args.evidence)

    # Load current state and ID map
    state = load_state(workspace)
    id_map = load_id_map(workspace)

    # Generate context ID
    context_id = generate_id(IDType.CONTEXT, id_map)

    # Determine context type from evidence if present
    context_type = evidence.get("type", "note")

    # Extract to document
    context_file = extract_context_to_document(
        workspace=workspace,
        context_id=context_id,
        entity_id=entity_id,
        context_type=context_type,
        evidence=evidence,
    )

    # Redact line from discovery staging file
    ev = evidence.get("evidence", evidence)
    staging_file = resolve_discovery_staging(workspace, ev.get("file", ""))
    if staging_file and staging_file.exists():
        remove_lines(staging_file, [int(ev["line"])], note=context_id)

    # Update ID map
    id_map[context_id] = [
        {
            "file": ev["file"],
            "line": ev["line"],
            "type": "context",
            "entity": entity_id,
            "context_type": context_type,
        }
    ]

    # Update state
    if context_id not in state.get("extracted_contexts", []):
        state.setdefault("extracted_contexts", []).append(context_id)

    # Save
    save_id_map(workspace, id_map)
    save_state(workspace, state)

    print(
        json.dumps(
            {
                "context_id": context_id,
                "entity_id": entity_id,
                "context_type": context_type,
                "context_file": str(context_file),
            }
        )
    )
    return 0


def cmd_finalize(args: argparse.Namespace) -> int:
    """Generate final output documents."""
    workspace = Path(args.workspace)

    finalize_output(workspace)

    print(f"Output generated in {workspace}/output/")
    return 0


def cmd_tag_facts(args: argparse.Namespace) -> int:
    """Assign Fact IDs (F-###) to referenced source lines."""
    workspace = Path(args.workspace)
    result = tag_facts(workspace)
    print(json.dumps(result))
    return 0


def cmd_recompose(args: argparse.Namespace) -> int:
    """Recompose tagged facts and extracted IDs into an implementable bundle."""
    workspace = Path(args.workspace)
    out_dir = Path(args.output) if getattr(args, "output", None) else None
    result = recompose(workspace, out_dir=out_dir)
    print(json.dumps(result))
    return 0


def cmd_execute_spec(args: argparse.Namespace) -> int:
    """Execute recomposed specs with iterative implementation tracking."""
    workspace = Path(args.workspace)
    repo = Path(args.repo) if getattr(args, "repo", None) else None
    ingest_path = Path(args.ingest) if getattr(args, "ingest", None) else None

    result = execute_spec(workspace, repo=repo, ingest_path=ingest_path)
    print(json.dumps(result, indent=2))
    return 0


def cmd_format_discovery(args: argparse.Namespace) -> int:
    """Format discovery staging content for agent consumption."""
    workspace = Path(args.workspace)
    output_file = Path(args.output)

    discovery_dir = workspace / "staging" / "discovery"
    if not discovery_dir.exists():
        print(
            f"Error: Discovery staging directory does not exist: {discovery_dir}", file=sys.stderr
        )
        return 1

    # Collect formatted content from all discovery staging files
    all_content = []
    for staging_file in sorted(discovery_dir.glob("*_staged.md")):
        remaining = get_remaining_lines(staging_file)
        if remaining:
            all_content.append(f"# From: {staging_file.name}")
            for item in remaining:
                all_content.append(f"{item['line']}: {item['text']}")
            all_content.append("")

    output_file.write_text("\n".join(all_content))

    print(
        json.dumps(
            {
                "output_file": str(output_file),
                "lines_remaining": sum(
                    1 for line in all_content if line and not line.startswith("#")
                ),
            }
        )
    )
    return 0


def cmd_create_investigation_staging(args: argparse.Namespace) -> int:
    """Create fresh investigation staging from original for an entity."""
    from scripts.spec_decomposition.workspace import (
        create_investigation_staging,
        load_file_index,
    )

    workspace = Path(args.workspace)
    entity_name = args.entity

    investigation_dir = create_investigation_staging(workspace, entity_name)

    # Combine all investigation files into a single formatted output with line mapping
    safe_name = entity_name.replace(" ", "_").replace("/", "_")
    all_formatted_lines = []
    line_map = {}  # combined_line -> {file, line, text}
    combined_line_number = 1

    # Get file index to map back to original source files
    file_index = load_file_index(workspace)

    # Iterate over all investigation files in the directory
    for investigation_file in sorted(investigation_dir.rglob("*_investigation.md")):
        remaining = get_remaining_lines(investigation_file)
        if not remaining:
            continue

        # Try to determine original source file from investigation file path
        # Investigation files are named like: {original_stem}_investigation.md
        rel_path = investigation_file.relative_to(investigation_dir)
        original_stem = investigation_file.stem.replace("_investigation", "_original")

        # Find the matching original file entry
        original_source = None
        for entry in file_index.get("files", []):
            orig_copy = entry.get("original_copy", "")
            if original_stem in orig_copy:
                original_source = entry.get("source", "")
                break

        if original_source is None:
            original_source = str(investigation_file)

        all_formatted_lines.append(f"# From: {original_source}")
        for item in remaining:
            all_formatted_lines.append(f"{combined_line_number}: {item['text']}")
            line_map[str(combined_line_number)] = {
                "file": original_source,
                "line": item["line"],
                "text": item["text"],
            }
            combined_line_number += 1
        all_formatted_lines.append("")

    # Write combined formatted output
    combined_file = investigation_dir / f"{safe_name}_combined_investigation.md"
    combined_file.write_text("\n".join(all_formatted_lines))

    # Write line map for later tracing
    map_file = investigation_dir / f"{safe_name}_combined_map.json"
    map_file.write_text(json.dumps({"line_map": line_map}, indent=2))

    # Update state with investigation staging info
    state = load_state(workspace)
    state.setdefault("investigation_staging", {})[safe_name] = {
        "combined_file": str(combined_file),
        "map_file": str(map_file),
        "investigation_dir": str(investigation_dir),
    }
    save_state(workspace, state)

    print(
        json.dumps(
            {
                "investigation_dir": str(investigation_dir),
                "combined_file": str(combined_file),
                "map_file": str(map_file),
                "entity": entity_name,
                "total_lines": combined_line_number - 1,
            }
        )
    )

    return 0


def cmd_process_investigation(args: argparse.Namespace) -> int:
    """Process entity investigation findings from agent output."""
    workspace = Path(args.workspace)
    findings_file = Path(args.findings)
    redact_discovery = args.redact_discovery

    if not findings_file.exists():
        print(f"Error: Findings file does not exist: {findings_file}", file=sys.stderr)
        return 1

    findings = json.loads(findings_file.read_text())

    # Load state and ID map
    state = load_state(workspace)
    id_map = load_id_map(workspace)
    entity_index = load_entity_index(workspace)

    entity_name = findings.get("entity", "unknown")
    safe_name = entity_name.replace(" ", "_").replace("/", "_")

    theories = findings.get("theories", [])
    related_entities = findings.get("related_entities", [])

    # Load combined investigation line->(file,line,text) mapping.
    map_path = Path(
        state.get("investigation_staging", {}).get(safe_name, {}).get("map_file")
        or (workspace / "staging" / "investigation" / f"{safe_name}_combined_map.json")
    )

    if not map_path.exists():
        print(
            json.dumps(
                {
                    "entity": entity_name,
                    "status": "error",
                    "message": f"Investigation map file not found: {map_path}",
                }
            )
        )
        return 1

    map_data = json.loads(map_path.read_text())
    line_map: dict[str, dict] = map_data.get("line_map", {})

    # Collect all combined-line numbers from findings.
    combined_lines: list[int] = []
    for finding in findings.get("findings", []):
        combined_lines.extend(int(l) for l in finding.get("lines", []) if str(l).isdigit())

    combined_lines = sorted(set(combined_lines))
    if not combined_lines:
        print(
            json.dumps(
                {
                    "entity": entity_name,
                    "status": "no_findings",
                    "message": "No line numbers found in investigation",
                }
            )
        )
        return 0

    # Map combined line numbers back to original file/line/text so we never store
    # paraphrases as evidence.
    evidence: list[dict] = []
    for cl in combined_lines:
        mapped = line_map.get(str(cl))
        if not mapped:
            continue
        evidence.append(
            {
                "file": mapped.get("file", ""),
                "line": int(mapped.get("line", 0)),
                "text": mapped.get("text", ""),
            }
        )

    # If everything failed to map, bail rather than generating junk.
    if not evidence:
        print(
            json.dumps(
                {
                    "entity": entity_name,
                    "status": "no_mapped_evidence",
                    "message": "No findings lines mapped back to source files (check map generation)",
                }
            )
        )
        return 0

    # Find existing entity ID by name (investigation MUST add to an existing entity).
    # Investigation phase requires the entity to have been discovered first.
    entity_id = None
    for existing_id, info in entity_index.items():
        if info.get("name", "").strip().lower() == entity_name.strip().lower():
            entity_id = existing_id
            break

    if not entity_id:
        print(
            json.dumps(
                {
                    "entity": entity_name,
                    "status": "error",
                    "message": f"Entity '{entity_name}' not found in entity index. "
                    "Investigation requires the entity to exist from discovery phase.",
                }
            )
        )
        return 1

    # Deduplicate evidence per-entity by (file,line).
    existing_keys = {
        (src.get("file", ""), int(src.get("line", 0)))
        for src in id_map.get(entity_id, [])
        if src.get("file") and src.get("line")
    }

    filtered_evidence = []
    for ev in evidence:
        k = (ev.get("file", ""), int(ev.get("line", 0)))
        if k[0] and k[1] and k in existing_keys:
            continue
        filtered_evidence.append(ev)
        if k[0] and k[1]:
            existing_keys.add(k)

    # Update entity document.
    entity_doc_path = workspace / "entities" / f"{entity_id}.md"
    if entity_doc_path.exists():
        for ev in filtered_evidence:
            append_evidence_to_entity(workspace, entity_id, ev)
        entity_file = entity_doc_path
    else:
        entity_file = extract_entity_to_document(
            workspace=workspace,
            entity_id=entity_id,
            entity_name=entity_name,
            evidence=filtered_evidence,
        )

    # Update entity index for new sources/keywords.
    for ev in filtered_evidence:
        if ev.get("file") and ev.get("line"):
            add_source_to_entity(workspace, entity_id, f"{ev['file']}:{ev['line']}")
    if related_entities:
        add_keywords_to_entity(workspace, entity_id, related_entities)

    # Redact from discovery staging if requested.
    if redact_discovery:
        by_file: dict[str, list[int]] = {}
        for ev in filtered_evidence:
            if ev.get("file") and ev.get("line"):
                by_file.setdefault(ev["file"], []).append(int(ev["line"]))

        for src_file, lines_for_file in by_file.items():
            staging_path = resolve_discovery_staging(workspace, src_file)
            if staging_path and staging_path.exists():
                remove_lines(staging_path, sorted(set(lines_for_file)), note=entity_id)

    # Redact from the combined investigation staging for this entity so subsequent
    # context extraction can focus on the remaining text.
    combined_investigation_path = Path(
        state.get("investigation_staging", {}).get(safe_name, {}).get("combined_file")
        or (workspace / "staging" / "investigation" / f"{safe_name}_combined_investigation.md")
    )
    if combined_investigation_path.exists():
        remove_lines(combined_investigation_path, combined_lines, note=f"{entity_id}")

    # Update ID map
    for ev in filtered_evidence:
        id_map.setdefault(entity_id, []).append(
            {
                "file": ev.get("file", ""),
                "line": int(ev.get("line", 0)),
                "type": "entity",
            }
        )

    # Update state
    if entity_id not in state.get("extracted_entities", []):
        state.setdefault("extracted_entities", []).append(entity_id)
    state["current_entity"] = entity_id

    # Save
    save_id_map(workspace, id_map)
    save_state(workspace, state)

    print(
        json.dumps(
            {
                "entity_id": entity_id,
                "entity_name": entity_name,
                "entity_file": str(entity_file),
                "lines_claimed": len(combined_lines),
                "theories": theories,
                "related_entities": related_entities,
                "redacted_discovery": redact_discovery,
            }
        )
    )
    return 0


def cmd_process_relations(args: argparse.Namespace) -> int:
    """Process relation analysis findings from agent output."""
    workspace = Path(args.workspace)
    findings_file = Path(args.findings)

    if not findings_file.exists():
        print(f"Error: Findings file does not exist: {findings_file}", file=sys.stderr)
        return 1

    findings = json.loads(findings_file.read_text())
    analysis = findings.get("analysis", [])

    # Load state, ID map, and entity index
    state = load_state(workspace)
    id_map = load_id_map(workspace)
    entity_index = load_entity_index(workspace)

    created_relations = []

    for item in analysis:
        entities_involved = item.get("entities_involved", [])
        if len(entities_involved) < 2:
            continue

        # Find entity IDs for involved entities
        entity_ids = []
        for entity_name in entities_involved:
            for eid, info in entity_index.items():
                if info.get("name", "").lower() == entity_name.lower():
                    entity_ids.append(eid)
                    break

        if len(entity_ids) < 2:
            continue

        # Create relation from first entity to others
        source_id = entity_ids[0]
        for target_id in entity_ids[1:]:
            relation_id = generate_id(IDType.RELATION, id_map)

            source_name = entity_index.get(source_id, {}).get("name", source_id)
            target_name = entity_index.get(target_id, {}).get("name", target_id)

            # Create relation document
            source_file = item.get("source_file") or str(findings_file)
            source_line = item.get("source_line") or 0

            relation_file = create_rich_relation_document(
                workspace=workspace,
                relation_id=relation_id,
                snippet_id=item.get("snippet_id", ""),
                source_entity=source_id,
                source_entity_name=source_name,
                targets=[{"id": target_id, "name": target_name}],
                relationship_type=item.get("relationship", "related"),
                relationship_context=item.get("context", ""),
                original_text=item.get("snippet", ""),
                file=source_file,
                line=source_line,
            )

            # Update ID map
            id_map[relation_id] = [
                {
                    "type": "relation",
                    "file": source_file,
                    "line": source_line,
                    "snippet_id": item.get("snippet_id", ""),
                    "source": source_id,
                    "target": target_id,
                    "relationship": item.get("relationship", "related"),
                }
            ]

            state.setdefault("extracted_relations", []).append(relation_id)
            created_relations.append(
                {
                    "relation_id": relation_id,
                    "source": source_id,
                    "target": target_id,
                }
            )

    # Check for newly discovered entities
    discovered = findings.get("discovered_entities", [])
    new_entities = []
    for entity_name in discovered:
        # Check if already exists
        exists = False
        for info in entity_index.values():
            if info.get("name", "").lower() == entity_name.lower():
                exists = True
                break
        if not exists:
            new_entities.append(entity_name)

    # Save
    save_id_map(workspace, id_map)
    save_state(workspace, state)

    print(
        json.dumps(
            {
                "relations_created": len(created_relations),
                "relations": created_relations,
                "newly_discovered_entities": new_entities,
            }
        )
    )
    return 0


def cmd_process_context(args: argparse.Namespace) -> int:
    """Process context extraction findings from agent output."""
    workspace = Path(args.workspace)
    findings_file = Path(args.findings)
    entity_name = args.entity

    if not findings_file.exists():
        print(f"Error: Findings file does not exist: {findings_file}", file=sys.stderr)
        return 1

    findings = json.loads(findings_file.read_text())
    context_items = findings.get("context_found", [])

    if not context_items:
        print(
            json.dumps(
                {
                    "entity": entity_name,
                    "context_found": False,
                    "message": "No context found in this round",
                }
            )
        )
        return 0

    # Load state and ID map
    state = load_state(workspace)
    id_map = load_id_map(workspace)
    entity_index = load_entity_index(workspace)

    # Find entity ID
    entity_id = None
    for eid, info in entity_index.items():
        if info.get("name", "").lower() == entity_name.lower():
            entity_id = eid
            break

    if not entity_id:
        print(f"Error: Entity not found: {entity_name}", file=sys.stderr)
        return 1

    safe_name = entity_name.replace(" ", "_").replace("/", "_")

    # Load combined investigation line->(file,line,text) mapping.
    map_path = Path(
        state.get("investigation_staging", {}).get(safe_name, {}).get("map_file")
        or (workspace / "staging" / "investigation" / f"{safe_name}_combined_map.json")
    )

    if not map_path.exists():
        print(
            json.dumps(
                {
                    "entity": entity_name,
                    "status": "error",
                    "message": f"Investigation map file not found: {map_path}",
                }
            )
        )
        return 1

    map_data = json.loads(map_path.read_text())
    line_map: dict[str, dict] = map_data.get("line_map", {})

    # Collect all combined line numbers for redaction and build relations.
    all_combined_lines: list[int] = []
    created_relations: list[str] = []

    for item in context_items:
        combined_lines = [int(l) for l in item.get("lines", []) if str(l).isdigit()]
        combined_lines = sorted(set(combined_lines))
        if not combined_lines:
            continue

        all_combined_lines.extend(combined_lines)

        # Map combined lines back to source text.
        mapped_evidence = []
        original_text_lines = []
        for cl in combined_lines:
            mapped = line_map.get(str(cl))
            if not mapped:
                continue
            mapped_evidence.append(
                {
                    "file": mapped.get("file", ""),
                    "line": int(mapped.get("line", 0)),
                    "text": mapped.get("text", ""),
                    "combined_line": cl,
                }
            )
            original_text_lines.append(mapped.get("text", ""))

        if not mapped_evidence:
            continue

        first = mapped_evidence[0]
        relation_id = generate_id(IDType.RELATION, id_map)

        relationship_type = item.get("relationship", "context") or "context"
        relationship_context = item.get("role", "")

        relation_file = create_rich_relation_document(
            workspace=workspace,
            relation_id=relation_id,
            snippet_id="",
            source_entity=entity_id,
            source_entity_name=entity_name,
            targets=[],
            relationship_type=relationship_type,
            relationship_context=relationship_context,
            original_text="\n".join(original_text_lines),
            file=first.get("file", ""),
            line=first.get("line", 0),
        )

        # Store one source entry per mapped evidence line so facts can be tagged/deduped.
        id_map[relation_id] = [
            {
                "file": ev.get("file", ""),
                "line": int(ev.get("line", 0)),
                "type": "context_relation",
                "source": entity_id,
                "relationship": relationship_type,
                "role": relationship_context,
                "combined_line": int(ev.get("combined_line", 0)),
            }
            for ev in mapped_evidence
        ]

        state.setdefault("extracted_relations", []).append(relation_id)
        created_relations.append(relation_id)

    # Redact from the combined investigation staging for this entity.
    combined_investigation_path = Path(
        state.get("investigation_staging", {}).get(safe_name, {}).get("combined_file")
        or (workspace / "staging" / "investigation" / f"{safe_name}_combined_investigation.md")
    )
    if combined_investigation_path.exists() and all_combined_lines:
        remove_lines(
            combined_investigation_path,
            sorted(set(all_combined_lines)),
            note=f"context:{entity_id}",
        )

    # Save
    save_id_map(workspace, id_map)
    save_state(workspace, state)

    print(
        json.dumps(
            {
                "entity": entity_name,
                "context_found": True,
                "relations_created": len(created_relations),
                "lines_redacted": len(set(all_combined_lines)),
                "theories": findings.get("theories", []),
            }
        )
    )
    return 0


def cmd_investigate_orphans(args: argparse.Namespace) -> int:
    """Investigate orphans at entity or project level."""
    workspace = Path(args.workspace)
    level = args.level

    # Get remaining orphan lines from discovery staging with original file content
    discovery_dir = workspace / "staging" / "discovery"
    orphan_lines = []
    file_contents: dict[str, str] = {}

    for staging_file in sorted(discovery_dir.glob("*_staged.md")):
        remaining = get_remaining_lines(staging_file)
        original_source = get_staged_from_path(staging_file) or staging_file.name
        for item in remaining:
            orphan_lines.append(
                {
                    "file": original_source,
                    "line": item["line"],
                    "text": item["text"],
                }
            )
        # Load original file content for context
        if original_source not in file_contents:
            source_path = Path(original_source)
            if source_path.exists():
                try:
                    file_contents[original_source] = source_path.read_text(encoding="utf-8")
                except (PermissionError, UnicodeDecodeError, OSError):
                    file_contents[original_source] = ""
            else:
                # Try to find in staging directory
                copy_path = (
                    staging_file.parent / f"{staging_file.stem.replace('_staged', '_original')}.md"
                )
                if copy_path.exists():
                    try:
                        file_contents[original_source] = copy_path.read_text(encoding="utf-8")
                    except (PermissionError, UnicodeDecodeError, OSError):
                        file_contents[original_source] = ""
                else:
                    file_contents[original_source] = ""

    if not orphan_lines:
        print(
            json.dumps(
                {
                    "level": level,
                    "orphans_found": 0,
                    "message": "No orphan lines remaining",
                }
            )
        )
        return 0

    # Write orphan lines to file for agent (with original_content for investigator)
    orphans_file = workspace / f"orphans_{level}_input.json"
    orphans_file.write_text(
        json.dumps(
            {
                "orphan_lines": orphan_lines,
                "original_content": file_contents,
            },
            indent=2,
        )
    )

    # Load context based on level
    entity_index = load_entity_index(workspace)
    state = load_state(workspace)

    if level == "entity":
        context = {
            "known_entities": [info.get("name", "") for info in entity_index.values()],
            "entity_count": len(entity_index),
        }
    else:  # project level
        context = {
            "known_entities": [info.get("name", "") for info in entity_index.values()],
            "entity_count": len(entity_index),
            "files": state.get("files_remaining", []) + state.get("files_completed", []),
            "extracted_relations": state.get("extracted_relations", []),
        }

    context_file = workspace / f"orphans_{level}_context.json"
    context_file.write_text(json.dumps(context, indent=2))

    print(
        json.dumps(
            {
                "level": level,
                "orphans_found": len(orphan_lines),
                "orphans_file": str(orphans_file),
                "context_file": str(context_file),
                "message": "Run orphan-investigator (entity) or project-investigator (project) agent",
            }
        )
    )
    return 0


def cmd_assess_orphan_value(args: argparse.Namespace) -> int:
    """Assess value of final orphans."""
    workspace = Path(args.workspace)

    # Get truly orphaned lines from project investigation results
    project_results = workspace / "orphans_project_results.json"
    if project_results.exists():
        results = json.loads(project_results.read_text())
        truly_orphaned = results.get("truly_orphaned", [])
    else:
        # Fall back to remaining discovery staging lines
        discovery_dir = workspace / "staging" / "discovery"
        truly_orphaned = []
        for staging_file in sorted(discovery_dir.glob("*_staged.md")):
            remaining = get_remaining_lines(staging_file)
            for item in remaining:
                truly_orphaned.append(
                    {
                        "line": item["line"],
                        "content": item["text"],
                    }
                )

    if not truly_orphaned:
        print(
            json.dumps(
                {
                    "orphans_to_assess": 0,
                    "message": "No orphans to assess",
                }
            )
        )
        return 0

    # Write for agent
    value_input = workspace / "value_assessment_input.json"
    value_input.write_text(json.dumps({"orphan_lines": truly_orphaned}, indent=2))

    print(
        json.dumps(
            {
                "orphans_to_assess": len(truly_orphaned),
                "input_file": str(value_input),
                "message": "Run value-assessor agent",
            }
        )
    )
    return 0


def cmd_format_other_files(args: argparse.Namespace) -> int:
    """Format content from other files for file-level extraction."""
    workspace = Path(args.workspace)
    target_file = args.target_file

    # Get content from all files EXCEPT the target file
    discovery_dir = workspace / "staging" / "discovery"
    all_content = []

    for staging_file in sorted(discovery_dir.glob("*_staged.md")):
        # Skip the target file
        if target_file in staging_file.name:
            continue

        remaining = get_remaining_lines(staging_file)
        if remaining:
            all_content.append(f"# From: {staging_file.name}")
            for item in remaining:
                all_content.append(f"{item['line']}: {item['text']}")
            all_content.append("")

    output_file = workspace / f"other_files_for_{target_file}.txt"
    output_file.write_text("\n".join(all_content))

    print(
        json.dumps(
            {
                "target_file": target_file,
                "output_file": str(output_file),
                "lines_from_other_files": sum(
                    1 for line in all_content if line and not line.startswith("#")
                ),
            }
        )
    )
    return 0


def cmd_process_orphans(args: argparse.Namespace) -> int:
    """Process orphan analysis findings from agent output."""
    workspace = Path(args.workspace)
    findings_file = Path(args.findings)

    if not findings_file.exists():
        print(f"Error: Findings file does not exist: {findings_file}", file=sys.stderr)
        return 1

    findings = json.loads(findings_file.read_text())

    # Support both orphan-investigator output schema (investigations/cross_cutting/no_context_found)
    # and orphan-analyzer output schema (analysis)
    investigations = findings.get("investigations", [])
    cross_cutting = findings.get("cross_cutting", [])
    no_context = findings.get("no_context_found", [])
    analysis = findings.get("analysis", [])

    # Load state and ID map
    state = load_state(workspace)
    id_map = load_id_map(workspace)

    created_orphans = []

    # Ensure orphans directory exists once before processing all loops
    (workspace / "orphans").mkdir(exist_ok=True)

    # Process orphan-investigator output (investigations, cross_cutting, no_context_found)
    for inv in investigations:
        orphan_id = generate_id(IDType.ORPHAN, id_map)
        orphan_file = workspace / "orphans" / f"{orphan_id}.md"

        orphan_line = inv.get("orphan_line", 0)
        orphan_text = inv.get("orphan_text", "")
        context_lines = inv.get("context_lines", [])
        entity_mentions = inv.get("entity_mentions", [])

        doc_lines = [
            "# Orphan Statement",
            "",
            f"**ID**: `{orphan_id}`",
            "**Importance**: `medium`",
            f"**Related Entities**: {', '.join(entity_mentions) if entity_mentions else 'None'}",
            "",
            "## Content",
            "",
            f"> {orphan_text}",
            "",
            "## Context Lines",
            "",
        ]
        for ctx in context_lines:
            doc_lines.append(f"- **{ctx.get('line', 0)}**: {ctx.get('text', '')}")

        doc_lines.extend(
            [
                "",
                "## Evidence",
                "",
                f"- **Line**: {orphan_line}",
            ]
        )

        orphan_file.write_text("\n".join(doc_lines))

        id_map[orphan_id] = [
            {
                "file": inv.get("file", ""),
                "line": orphan_line,
                "type": "orphan",
                "context_lines": context_lines,
                "entity_mentions": entity_mentions,
            }
        ]

        state["orphans_found"] = state.get("orphans_found", 0) + 1
        created_orphans.append(
            {
                "orphan_id": orphan_id,
                "line": orphan_line,
                "importance": "medium",
            }
        )

    # Process cross-cutting orphans from investigator
    for cc in cross_cutting:
        orphan_id = generate_id(IDType.ORPHAN, id_map)
        orphan_file = workspace / "orphans" / f"{orphan_id}.md"

        lines = cc.get("lines", [])
        affects = cc.get("affects_entities", [])

        doc_lines = [
            "# Orphan Statement",
            "",
            f"**ID**: `{orphan_id}`",
            "**Importance**: `high`",
            f"**Related Entities**: {', '.join(affects) if affects else 'None'}",
            "",
            "## Content",
            "",
            "> Cross-cutting concern affecting multiple entities",
            "",
            "## Evidence",
            "",
            f"- **Lines**: {', '.join(str(l) for l in lines)}",
        ]

        orphan_file.write_text("\n".join(doc_lines))

        id_map[orphan_id] = [
            {
                "lines": lines,
                "type": "orphan",
                "cross_cutting": True,
                "affects_entities": affects,
            }
        ]

        state["orphans_found"] = state.get("orphans_found", 0) + 1
        created_orphans.append(
            {
                "orphan_id": orphan_id,
                "lines": lines,
                "importance": "high",
            }
        )

    # Process orphans with no context found
    for nc in no_context:
        orphan_id = generate_id(IDType.ORPHAN, id_map)
        orphan_file = workspace / "orphans" / f"{orphan_id}.md"

        line = nc.get("line", 0)
        text = nc.get("text", "")

        doc_lines = [
            "# Orphan Statement",
            "",
            f"**ID**: `{orphan_id}`",
            "**Importance**: `low`",
            "**Related Entities**: None",
            "",
            "## Content",
            "",
            f"> {text}",
            "",
            "## Evidence",
            "",
            f"- **Line**: {line}",
            "- **Note**: No contextual evidence found",
        ]

        orphan_file.write_text("\n".join(doc_lines))

        id_map[orphan_id] = [
            {
                "line": line,
                "type": "orphan",
                "no_context_found": True,
            }
        ]

        state["orphans_found"] = state.get("orphans_found", 0) + 1
        created_orphans.append(
            {
                "orphan_id": orphan_id,
                "line": line,
                "importance": "low",
            }
        )

    # Process orphan-analyzer output (analysis with text array and 'about' field)
    for item in analysis:
        lines = item.get("lines", [])
        # Handle text as array (from orphan-analyzer) or string
        text_array = item.get("text", [])
        content = " ".join(text_array) if isinstance(text_array, list) else item.get("content", "")
        interpretation = item.get("about", item.get("interpretation", ""))
        importance = item.get("importance", "unknown")
        related_entities = item.get("related_entities", [])
        theories = item.get("theories", [])

        # Skip if no valid content
        if not content:
            continue

        orphan_id = generate_id(IDType.ORPHAN, id_map)
        orphan_file = workspace / "orphans" / f"{orphan_id}.md"

        doc_lines = [
            "# Orphan Statement",
            "",
            f"**ID**: `{orphan_id}`",
            f"**Importance**: `{importance}`",
            f"**Related Entities**: {', '.join(related_entities) if related_entities else 'None'}",
            "",
            "## Content",
            "",
            f"> {content}",
            "",
            "## Interpretation",
            "",
            interpretation,
            "",
            "## Theories",
            "",
        ]
        for theory in theories:
            doc_lines.append(f"- {theory}")

        doc_lines.extend(
            [
                "",
                "## Evidence",
                "",
                f"- **Lines**: {', '.join(str(l) for l in lines)}",
            ]
        )

        orphan_file.write_text("\n".join(doc_lines))

        id_map[orphan_id] = [
            {
                "lines": lines,
                "type": "orphan",
                "interpretation": interpretation,
                "related_entities": related_entities,
            }
        ]

        state["orphans_found"] = state.get("orphans_found", 0) + 1
        created_orphans.append(
            {
                "orphan_id": orphan_id,
                "lines": lines,
                "importance": importance,
            }
        )

    # Save
    save_id_map(workspace, id_map)
    save_state(workspace, state)

    print(
        json.dumps(
            {
                "orphans_created": len(created_orphans),
                "orphans": created_orphans,
                "summary": findings.get("summary", ""),
            }
        )
    )
    return 0


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Spec decomposition operations",
        prog="uv run python -m scripts.spec_decomposition",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize workspace")
    init_parser.add_argument("spec_path", help="Path to spec file or directory")
    init_parser.add_argument("--workspace", "-w", help="Workspace directory")

    # extract-entity command
    entity_parser = subparsers.add_parser("extract-entity", help="Extract entity")
    entity_parser.add_argument("--workspace", "-w", required=True, help="Workspace directory")
    entity_parser.add_argument("--entity", "-e", required=True, help="Entity name")
    entity_parser.add_argument(
        "--entity-id",
        help="Existing entity ID to attach evidence to (rediscovery/merge)",
    )
    entity_parser.add_argument("--evidence", required=True, help="Evidence JSON")
    entity_parser.add_argument("--keywords", "-k", help="Keywords JSON")
    entity_parser.add_argument("--file", "-f", help="Staging file to remove lines from")
    entity_parser.add_argument(
        "--append", "-a", action="store_true", help="Append to current entity"
    )

    # extract-relation command
    relation_parser = subparsers.add_parser("extract-relation", help="Extract relation")
    relation_parser.add_argument("--workspace", "-w", required=True, help="Workspace directory")
    relation_parser.add_argument("--from", dest="from_entity", help="From entity ID")
    relation_parser.add_argument("--to", dest="to_entity", help="To entity ID")
    relation_parser.add_argument("--target-entity", help="Target entity (for rediscovery)")
    relation_parser.add_argument("--type", help="Relation type")
    relation_parser.add_argument("--evidence", required=True, help="Evidence JSON")

    # extract-context command
    context_parser = subparsers.add_parser("extract-context", help="Extract context")
    context_parser.add_argument("--workspace", "-w", required=True, help="Workspace directory")
    context_parser.add_argument("--entity", "-e", required=True, help="Entity ID")
    context_parser.add_argument("--evidence", required=True, help="Evidence JSON")

    # check-rediscovery command
    rediscovery_parser = subparsers.add_parser(
        "check-rediscovery", help="Check for entity rediscovery"
    )
    rediscovery_parser.add_argument("--workspace", "-w", required=True, help="Workspace directory")
    rediscovery_parser.add_argument("--entity-name", required=True, help="Entity name to check")
    rediscovery_parser.add_argument("--keywords", required=True, help="Keywords JSON")

    # check-file-empty command
    empty_parser = subparsers.add_parser("check-file-empty", help="Check if staging file is empty")
    empty_parser.add_argument("--workspace", "-w", required=True, help="Workspace directory")
    empty_parser.add_argument("--file", "-f", required=True, help="Staging file to check")

    # build-graph command
    graph_parser = subparsers.add_parser("build-graph", help="Build dependency graph")
    graph_parser.add_argument("--workspace", "-w", required=True, help="Workspace directory")

    # extract-orphan command
    orphan_parser = subparsers.add_parser("extract-orphan", help="Extract orphan statement")
    orphan_parser.add_argument("--workspace", "-w", required=True, help="Workspace directory")
    orphan_parser.add_argument("--analysis", required=True, help="Orphan category")
    orphan_parser.add_argument("--possible-entities", help="Possible entity IDs JSON")
    orphan_parser.add_argument("--evidence", required=True, help="Evidence JSON")

    # finalize command
    finalize_parser = subparsers.add_parser("finalize", help="Generate final output")
    finalize_parser.add_argument("--workspace", "-w", required=True, help="Workspace directory")

    # tag-facts command
    tag_facts_parser = subparsers.add_parser(
        "tag-facts",
        help="Assign Fact IDs (F-###) to referenced source lines",
    )
    tag_facts_parser.add_argument("--workspace", "-w", required=True, help="Workspace directory")

    # recompose command
    recompose_parser = subparsers.add_parser(
        "recompose",
        help="Recompose tagged facts and extracted IDs into an implementable bundle",
    )
    recompose_parser.add_argument("--workspace", "-w", required=True, help="Workspace directory")
    recompose_parser.add_argument(
        "--output",
        help="Output directory (default: <workspace>/output/recomposed)",
    )

    # execute-spec command
    execute_spec_parser = subparsers.add_parser(
        "execute-spec",
        help="Execute recomposed specs with iterative implementation tracking",
    )
    execute_spec_parser.add_argument("--workspace", "-w", required=True, help="Workspace directory")
    execute_spec_parser.add_argument("--repo", "-r", help="Implementation repository root")
    execute_spec_parser.add_argument(
        "--ingest",
        help="Path to evidence file to ingest (implementation_map.json)",
    )

    # mark-relation-snippets command
    mark_snippets_parser = subparsers.add_parser(
        "mark-relation-snippets",
        help="Mark lines as relation snippets",
    )
    mark_snippets_parser.add_argument(
        "--workspace", "-w", required=True, help="Workspace directory"
    )
    mark_snippets_parser.add_argument("--source-entity", required=True, help="Source entity ID")
    mark_snippets_parser.add_argument(
        "--snippets", required=True, help="Snippets JSON (list of {line, text})"
    )
    mark_snippets_parser.add_argument("--file", "-f", required=True, help="Staging file name")

    # collect-relation-snippets command
    collect_snippets_parser = subparsers.add_parser(
        "collect-relation-snippets",
        help="Collect marked snippets to relation_staging",
    )
    collect_snippets_parser.add_argument(
        "--workspace", "-w", required=True, help="Workspace directory"
    )

    # create-discovered-entity command
    discovered_entity_parser = subparsers.add_parser(
        "create-discovered-entity",
        help="Create entity discovered from relation snippet",
    )
    discovered_entity_parser.add_argument(
        "--workspace", "-w", required=True, help="Workspace directory"
    )
    discovered_entity_parser.add_argument("--entity", "-e", required=True, help="Entity name")
    discovered_entity_parser.add_argument("--keywords", "-k", required=True, help="Keywords JSON")
    discovered_entity_parser.add_argument(
        "--discovered-from", required=True, help="Snippet ID where discovered"
    )
    discovered_entity_parser.add_argument(
        "--context", required=True, help="Context text from snippet"
    )

    # create-rich-relation command
    rich_relation_parser = subparsers.add_parser(
        "create-rich-relation",
        help="Create rich relation document with context",
    )
    rich_relation_parser.add_argument(
        "--workspace", "-w", required=True, help="Workspace directory"
    )
    rich_relation_parser.add_argument("--source", required=True, help="Source entity ID")
    rich_relation_parser.add_argument(
        "--source-name",
        required=False,
        help="Source entity name (optional; used if the entity index is missing)",
    )
    rich_relation_parser.add_argument("--targets", required=True, help="Target entities JSON")
    rich_relation_parser.add_argument("--type", required=True, help="Relationship type")
    rich_relation_parser.add_argument("--context", required=True, help="Relationship context")
    rich_relation_parser.add_argument("--snippet-id", required=True, help="Source snippet ID")
    rich_relation_parser.add_argument(
        "--original-text", required=True, help="Original text from spec"
    )
    rich_relation_parser.add_argument("--file", "-f", required=True, help="Source file")
    rich_relation_parser.add_argument(
        "--line", "-l", type=int, required=True, help="Source line number"
    )

    # format-discovery command
    format_discovery_parser = subparsers.add_parser(
        "format-discovery",
        help="Format discovery staging content for agent consumption",
    )
    format_discovery_parser.add_argument(
        "--workspace", "-w", required=True, help="Workspace directory"
    )
    format_discovery_parser.add_argument(
        "--output", "-o", required=True, help="Output file for formatted content"
    )

    # create-investigation-staging command
    create_investigation_parser = subparsers.add_parser(
        "create-investigation-staging",
        help="Create fresh investigation staging from original for an entity",
    )
    create_investigation_parser.add_argument(
        "--workspace", "-w", required=True, help="Workspace directory"
    )
    create_investigation_parser.add_argument(
        "--entity", "-e", required=True, help="Entity name to investigate"
    )

    # process-investigation command
    process_investigation_parser = subparsers.add_parser(
        "process-investigation",
        help="Process entity investigation findings from agent output",
    )
    process_investigation_parser.add_argument(
        "--workspace", "-w", required=True, help="Workspace directory"
    )
    process_investigation_parser.add_argument(
        "--findings", "-f", required=True, help="Path to findings JSON file"
    )
    process_investigation_parser.add_argument(
        "--redact-discovery", action="store_true", help="Also redact from discovery staging"
    )

    # process-relations command
    process_relations_parser = subparsers.add_parser(
        "process-relations",
        help="Process relation analysis findings from agent output",
    )
    process_relations_parser.add_argument(
        "--workspace", "-w", required=True, help="Workspace directory"
    )
    process_relations_parser.add_argument(
        "--findings", "-f", required=True, help="Path to findings JSON file"
    )

    # process-context command
    process_context_parser = subparsers.add_parser(
        "process-context",
        help="Process context extraction findings from agent output",
    )
    process_context_parser.add_argument(
        "--workspace", "-w", required=True, help="Workspace directory"
    )
    process_context_parser.add_argument(
        "--findings", "-f", required=True, help="Path to findings JSON file"
    )
    process_context_parser.add_argument(
        "--entity", "-e", required=True, help="Entity name the context is for"
    )

    # investigate-orphans command
    investigate_orphans_parser = subparsers.add_parser(
        "investigate-orphans",
        help="Investigate orphans at entity or project level",
    )
    investigate_orphans_parser.add_argument(
        "--workspace", "-w", required=True, help="Workspace directory"
    )
    investigate_orphans_parser.add_argument(
        "--level", "-l", required=True, choices=["entity", "project"], help="Investigation level"
    )

    # assess-orphan-value command
    assess_value_parser = subparsers.add_parser(
        "assess-orphan-value",
        help="Assess value of final orphans",
    )
    assess_value_parser.add_argument("--workspace", "-w", required=True, help="Workspace directory")

    # format-other-files command
    format_other_parser = subparsers.add_parser(
        "format-other-files",
        help="Format content from other files for file-level extraction",
    )
    format_other_parser.add_argument("--workspace", "-w", required=True, help="Workspace directory")
    format_other_parser.add_argument(
        "--target-file", "-t", required=True, help="Target file to find info about"
    )

    # process-orphans command
    process_orphans_parser = subparsers.add_parser(
        "process-orphans",
        help="Process orphan analysis findings from agent output",
    )
    process_orphans_parser.add_argument(
        "--workspace", "-w", required=True, help="Workspace directory"
    )
    process_orphans_parser.add_argument(
        "--findings", "-f", required=True, help="Path to findings JSON file"
    )

    args = parser.parse_args()

    commands = {
        "init": cmd_init,
        "extract-entity": cmd_extract_entity,
        "extract-relation": cmd_extract_relation,
        "extract-context": cmd_extract_context,
        "check-rediscovery": cmd_check_rediscovery,
        "check-file-empty": cmd_check_file_empty,
        "build-graph": cmd_build_graph,
        "extract-orphan": cmd_extract_orphan,
        "finalize": cmd_finalize,
        "tag-facts": cmd_tag_facts,
        "recompose": cmd_recompose,
        "execute-spec": cmd_execute_spec,
        "mark-relation-snippets": cmd_mark_relation_snippets,
        "collect-relation-snippets": cmd_collect_relation_snippets,
        "create-discovered-entity": cmd_create_discovered_entity,
        "create-rich-relation": cmd_create_rich_relation,
        "format-discovery": cmd_format_discovery,
        "create-investigation-staging": cmd_create_investigation_staging,
        "process-investigation": cmd_process_investigation,
        "process-context": cmd_process_context,
        "process-relations": cmd_process_relations,
        "investigate-orphans": cmd_investigate_orphans,
        "assess-orphan-value": cmd_assess_orphan_value,
        "format-other-files": cmd_format_other_files,
        "process-orphans": cmd_process_orphans,
    }

    return commands[args.command](args)
