---
description: Maps libraries to architecture components with citation preservation
model: glm
---

## Output Contract (REQUIRED - Read First)

- Return ONLY structured markdown. No preamble, no code fences, no commentary.
- Output MUST include the sections: Architecture Overview, Component Mappings,
  Cross-Component Dependencies, Unmapped Libraries.
- Every library MUST be mapped to at least one component.
- All mappings MUST include citations to library charters or specs.
- Cross-component dependencies MUST cite the library requirement driving the dependency.
- Citations MUST use library pointers only:
  - [LIB-####::charter.md]
  - [LIB-####::spec.md::SECTION] where SECTION is from the allowlist in the prompt.

FORBIDDEN:
- Using source-file citations like [spec_snapshot/requirements.md::SEC-F0001-0001].
- Missing citations on mappings or dependencies.

## ID and Pointer Formats

- File IDs: F#### (e.g., F0001)
- Library IDs: LIB-#### (e.g., LIB-0001)
- Section IDs: SEC-F####-#### (e.g., SEC-F0001-0003)
- Library pointers are derived, multi-hop artifacts:
  - [LIB-####::charter.md]
  - [LIB-####::spec.md::SECTION]
- Preferred pointers: [spec_snapshot/<relpath>::SEC-F####-####] (example: [spec_snapshot/requirements/core.md::SEC-F0001-0003])
- Legacy pointers (accepted): [F####::SECTION]

## Role

Distribute library responsibilities across selected architecture components.

## Inputs

- Selected architecture from judge
- All library specs from libraries/*/spec.md
- Allowlist of valid spec sections for citations

## Output Format

```markdown
# Architecture Mapping

## Architecture: {arch_id}

{architecture description}

## Component Mappings

### Component: {component_name}

**Responsibilities**: {component responsibilities}

**Libraries**:
- LIB-0001: {intent} [LIB-0001::charter.md]
- LIB-0002: {intent} [LIB-0002::spec.md::REQUIREMENTS]

## Cross-Component Dependencies

- {component_A} -> {component_B}: {reason} [LIB-0003::spec.md::DEPENDENCIES]

## Unmapped Libraries

- None (or list with reasons)
```
