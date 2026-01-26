"""Recompose decomposed specs into an implementable, tagged bundle.

Recomposition is a *mechanical regrouping* step. It should not rewrite content.

Inputs:
- id_map.json with fact_id annotations (from `tag-facts`)
- facts.json (canonical fact store)
- entity_index.json

Outputs (under output/recomposed/):
- spec.json (machine-friendly)
- facts.md and entities.md (human-friendly)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.spec_decomposition.entity_index import load_entity_index
from scripts.spec_decomposition.id_generator import IDType, get_ids_by_type, load_id_map


def _id_sort_key(id_str: str) -> tuple[str, int]:
    try:
        prefix, n = id_str.split("-", 1)
        return prefix, int(n)
    except Exception:
        return id_str, 0


def _relation_edges(sources: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """Return (from, to, label) edges from a relation's id_map sources."""
    edges: list[tuple[str, str, str]] = []
    for src in sources:
        if not isinstance(src, dict):
            continue

        label = str(src.get("relation_type") or src.get("relationship") or "related")

        if src.get("from") and src.get("to"):
            edges.append((str(src["from"]), str(src["to"]), label))
            continue

        if src.get("source") and src.get("target"):
            edges.append((str(src["source"]), str(src["target"]), label))
            continue

        if src.get("source") and isinstance(src.get("targets"), list):
            for t in src.get("targets", []):
                edges.append((str(src["source"]), str(t), label))

    # De-dup while preserving order
    seen = set()
    uniq: list[tuple[str, str, str]] = []
    for e in edges:
        if e in seen:
            continue
        seen.add(e)
        uniq.append(e)
    return uniq


def recompose(workspace: Path, out_dir: Path | None = None) -> dict[str, Any]:
    workspace = Path(workspace)
    id_map = load_id_map(workspace)
    entity_index = load_entity_index(workspace)

    facts_path = workspace / "facts.json"
    if not facts_path.exists():
        raise FileNotFoundError(
            f"facts.json not found at {facts_path}. Run `tag-facts` before `recompose`."
        )

    facts: dict[str, Any] = json.loads(facts_path.read_text(encoding="utf-8"))

    if out_dir is None:
        out_dir = workspace / "output" / "recomposed"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build entity -> fact_ids
    entities: dict[str, Any] = {}
    for entity_id, info in sorted(entity_index.items(), key=lambda kv: _id_sort_key(kv[0])):
        sources = id_map.get(entity_id, [])
        fact_ids = []
        for src in sources if isinstance(sources, list) else []:
            fid = src.get("fact_id") if isinstance(src, dict) else None
            if isinstance(fid, str):
                fact_ids.append(fid)
        # De-dup
        fact_ids = list(dict.fromkeys(fact_ids))
        entities[entity_id] = {
            "name": info.get("name"),
            "keywords": info.get("keywords", []),
            "fact_ids": fact_ids,
        }

    # Build relations summary + adjacency
    relation_ids = get_ids_by_type(id_map, IDType.RELATION)
    relations: dict[str, Any] = {}
    outgoing: dict[str, list[dict[str, Any]]] = {eid: [] for eid in entities}
    incoming: dict[str, list[dict[str, Any]]] = {eid: [] for eid in entities}

    for rel_id in sorted(relation_ids, key=_id_sort_key):
        sources = id_map.get(rel_id, [])
        if not isinstance(sources, list):
            continue
        edges = _relation_edges(sources)
        fact_ids = []
        for src in sources:
            if isinstance(src, dict) and isinstance(src.get("fact_id"), str):
                fact_ids.append(src["fact_id"])
        fact_ids = list(dict.fromkeys(fact_ids))

        relations[rel_id] = {
            "edges": [{"from": f, "to": t, "label": lbl} for f, t, lbl in edges],
            "fact_ids": fact_ids,
            "sources": sources,
        }

        for f, t, lbl in edges:
            if f in outgoing:
                outgoing[f].append({"relation_id": rel_id, "to": t, "label": lbl})
            if t in incoming:
                incoming[t].append({"relation_id": rel_id, "from": f, "label": lbl})

    # Contexts and orphans are included verbatim (tagged via fact_id where possible).
    contexts: dict[str, Any] = {}
    for cid in sorted(get_ids_by_type(id_map, IDType.CONTEXT), key=_id_sort_key):
        contexts[cid] = id_map.get(cid, [])

    orphans: dict[str, Any] = {}
    for oid in sorted(get_ids_by_type(id_map, IDType.ORPHAN), key=_id_sort_key):
        orphans[oid] = id_map.get(oid, [])

    spec = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "facts": facts,
        "entities": entities,
        "relations": relations,
        "contexts": contexts,
        "orphans": orphans,
    }

    # Write spec.json
    spec_json_path = out_dir / "spec.json"
    spec_json_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")

    # Write facts.md
    facts_md_path = out_dir / "facts.md"
    facts_lines = ["# Facts", ""]
    for fid in sorted(facts.keys(), key=_id_sort_key):
        rec = facts.get(fid, {})
        if not isinstance(rec, dict):
            continue
        facts_lines.append(f"## {fid}")
        facts_lines.append(f"- **Source**: `{rec.get('file', '')}:{rec.get('line', '')}`")
        if rec.get("hash"):
            facts_lines.append(f"- **Hash**: `{rec.get('hash')}`")
        facts_lines.append("")
        facts_lines.append("> " + str(rec.get("text", "")).replace("\n", "\n> "))
        facts_lines.append("")
    facts_md_path.write_text("\n".join(facts_lines), encoding="utf-8")

    # Write entities.md
    entities_md_path = out_dir / "entities.md"
    ent_lines = ["# Entities", ""]
    for eid in sorted(entities.keys(), key=_id_sort_key):
        info = entities[eid]
        ent_lines.append(f"## {eid} — {info.get('name', '')}")
        kw = info.get("keywords", [])
        if kw:
            ent_lines.append(f"- **Keywords**: {', '.join(str(k) for k in kw)}")

        # Facts (verbatim)
        ent_lines.append("\n### Facts")
        for fid in info.get("fact_ids", []):
            rec = facts.get(fid, {})
            if not isinstance(rec, dict):
                continue
            ent_lines.append(
                f"- `{fid}` `{rec.get('file', '')}:{rec.get('line', '')}` — {str(rec.get('text', ''))}"
            )

        # Relations
        out_rels = outgoing.get(eid, [])
        in_rels = incoming.get(eid, [])
        if out_rels:
            ent_lines.append("\n### Outgoing relations")
            for r in out_rels:
                ent_lines.append(
                    f"- `{r['relation_id']}` — {r.get('label', '')} → `{r.get('to', '')}`"
                )
        if in_rels:
            ent_lines.append("\n### Incoming relations")
            for r in in_rels:
                ent_lines.append(
                    f"- `{r['relation_id']}` — {r.get('label', '')} ← `{r.get('from', '')}`"
                )

        ent_lines.append("")
    entities_md_path.write_text("\n".join(ent_lines), encoding="utf-8")

    return {
        "out_dir": str(out_dir),
        "spec_json": str(spec_json_path),
        "facts_md": str(facts_md_path),
        "entities_md": str(entities_md_path),
        "entities": len(entities),
        "facts": len(facts),
        "relations": len(relations),
    }
