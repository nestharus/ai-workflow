"""Spec decomposition module for breaking down large specifications."""

from __future__ import annotations

from scripts.spec_decomposition.id_generator import (
    IDType,
    generate_id,
    load_id_map,
    save_id_map,
    get_ids_by_type,
    get_source_lines,
)
from scripts.spec_decomposition.workspace import (
    init_workspace,
    load_state,
    save_state,
    create_investigation_staging,
    resolve_original_copy,
    resolve_discovery_staging,
    list_discovery_staging_files,
)
from scripts.spec_decomposition.staging import (
    create_staging_file,
    embed_id_at_line,
    get_line_content,
    get_embedded_ids,
    remove_lines,
    get_remaining_lines,
    format_content_for_agent,
    is_file_empty,
    mark_relation_snippet,
    get_marked_snippets,
    collect_and_remove_snippets,
    write_snippet_staging_file,
)
from scripts.spec_decomposition.extract import (
    extract_entity_to_document,
    extract_relation_to_document,
    extract_context_to_document,
    append_evidence_to_entity,
    create_rich_relation_document,
    create_discovered_entity_document,
)
from scripts.spec_decomposition.entity_index import (
    load_entity_index,
    save_entity_index,
    add_entity_to_index,
    add_source_to_entity,
    check_rediscovery,
)
from scripts.spec_decomposition.graph import (
    build_dependency_graph,
    save_dependency_graph,
)
from scripts.spec_decomposition.finalize import finalize_output
from scripts.spec_decomposition.tagging import tag_facts
from scripts.spec_decomposition.recompose import recompose

__all__ = [
    # ID generation
    "IDType",
    "generate_id",
    "load_id_map",
    "save_id_map",
    "get_ids_by_type",
    "get_source_lines",
    # Workspace
    "init_workspace",
    "load_state",
    "save_state",
    "create_investigation_staging",
    "resolve_original_copy",
    "resolve_discovery_staging",
    "list_discovery_staging_files",
    # Staging
    "create_staging_file",
    "embed_id_at_line",
    "get_line_content",
    "get_embedded_ids",
    "remove_lines",
    "get_remaining_lines",
    "format_content_for_agent",
    "is_file_empty",
    "mark_relation_snippet",
    "get_marked_snippets",
    "collect_and_remove_snippets",
    "write_snippet_staging_file",
    # Extraction
    "extract_entity_to_document",
    "extract_relation_to_document",
    "extract_context_to_document",
    "append_evidence_to_entity",
    "create_rich_relation_document",
    "create_discovered_entity_document",
    # Entity Index
    "load_entity_index",
    "save_entity_index",
    "add_entity_to_index",
    "add_source_to_entity",
    "check_rediscovery",
    # Graph
    "build_dependency_graph",
    "save_dependency_graph",
    # Finalization
    "finalize_output",
    # Tagging & recomposition
    "tag_facts",
    "recompose",
]
