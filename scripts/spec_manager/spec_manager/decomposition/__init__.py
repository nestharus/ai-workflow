"""Spec decomposition package for breaking down large specifications."""

from __future__ import annotations

from scripts.spec_manager.spec_manager.decomposition.entity_index import (
    add_entity_to_index,
    add_source_to_entity,
    check_rediscovery,
    load_entity_index,
    save_entity_index,
)
from scripts.spec_manager.spec_manager.decomposition.extract import (
    append_evidence_to_entity,
    create_discovered_entity_document,
    create_rich_relation_document,
    extract_context_to_document,
    extract_entity_to_document,
    extract_relation_to_document,
)
from scripts.spec_manager.spec_manager.decomposition.finalize import finalize_output
from scripts.spec_manager.spec_manager.decomposition.id_generator import (
    IDType,
    generate_id,
    get_ids_by_type,
    get_source_lines,
    load_id_map,
    save_id_map,
)
from scripts.spec_manager.spec_manager.decomposition.recompose import recompose
from scripts.spec_manager.spec_manager.decomposition.staging import (
    collect_and_remove_snippets,
    create_staging_file,
    embed_id_at_line,
    format_content_for_agent,
    get_embedded_ids,
    get_line_content,
    get_marked_snippets,
    get_remaining_lines,
    is_file_empty,
    mark_relation_snippet,
    remove_lines,
    write_snippet_staging_file,
)
from scripts.spec_manager.spec_manager.decomposition.tagging import tag_facts
from scripts.spec_manager.spec_manager.decomposition.workspace import (
    create_investigation_staging,
    init_workspace,
    list_discovery_staging_files,
    load_state,
    resolve_discovery_staging,
    resolve_original_copy,
    save_state,
)

__all__ = [
    # Entity Index
    "add_entity_to_index",
    "add_source_to_entity",
    "check_rediscovery",
    "load_entity_index",
    "save_entity_index",
    # Extraction
    "append_evidence_to_entity",
    "create_discovered_entity_document",
    "create_rich_relation_document",
    "extract_context_to_document",
    "extract_entity_to_document",
    "extract_relation_to_document",
    # Finalization
    "finalize_output",
    # ID generation
    "IDType",
    "generate_id",
    "get_ids_by_type",
    "get_source_lines",
    "load_id_map",
    "save_id_map",
    # Staging
    "collect_and_remove_snippets",
    "create_staging_file",
    "embed_id_at_line",
    "format_content_for_agent",
    "get_embedded_ids",
    "get_line_content",
    "get_marked_snippets",
    "get_remaining_lines",
    "is_file_empty",
    "mark_relation_snippet",
    "remove_lines",
    "write_snippet_staging_file",
    # Tagging & recomposition
    "recompose",
    "tag_facts",
    # Workspace
    "create_investigation_staging",
    "init_workspace",
    "list_discovery_staging_files",
    "load_state",
    "resolve_discovery_staging",
    "resolve_original_copy",
    "save_state",
]
