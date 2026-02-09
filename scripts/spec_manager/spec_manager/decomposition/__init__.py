"""Spec decomposition package for breaking down large specifications."""

from __future__ import annotations

from spec_manager.decomposition.entity_index import (
    add_entity_to_index,
    add_source_to_entity,
    check_rediscovery,
    load_entity_index,
    save_entity_index,
)
from spec_manager.decomposition.extract import (
    append_evidence_to_entity,
    create_discovered_entity_document,
    create_rich_relation_document,
    extract_context_to_document,
    extract_entity_to_document,
    extract_relation_to_document,
)
from spec_manager.decomposition.finalize import finalize_output
from spec_manager.decomposition.id_generator import (
    IDType,
    generate_id,
    get_ids_by_type,
    get_source_lines,
    load_id_map,
    save_id_map,
)
from spec_manager.decomposition.recompose import recompose
from spec_manager.decomposition.staging import (
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
from spec_manager.decomposition.tagging import tag_facts
from spec_manager.decomposition.workspace import (
    create_investigation_staging,
    init_workspace,
    list_discovery_staging_files,
    load_state,
    resolve_discovery_staging,
    resolve_original_copy,
    save_state,
)

__all__ = [
    "IDType",
    "add_entity_to_index",
    "add_source_to_entity",
    "append_evidence_to_entity",
    "check_rediscovery",
    "collect_and_remove_snippets",
    "create_discovered_entity_document",
    "create_investigation_staging",
    "create_rich_relation_document",
    "create_staging_file",
    "embed_id_at_line",
    "extract_context_to_document",
    "extract_entity_to_document",
    "extract_relation_to_document",
    "finalize_output",
    "format_content_for_agent",
    "generate_id",
    "get_embedded_ids",
    "get_ids_by_type",
    "get_line_content",
    "get_marked_snippets",
    "get_remaining_lines",
    "get_source_lines",
    "init_workspace",
    "is_file_empty",
    "list_discovery_staging_files",
    "load_entity_index",
    "load_id_map",
    "load_state",
    "mark_relation_snippet",
    "recompose",
    "remove_lines",
    "resolve_discovery_staging",
    "resolve_original_copy",
    "save_entity_index",
    "save_id_map",
    "save_state",
    "tag_facts",
    "write_snippet_staging_file",
]
